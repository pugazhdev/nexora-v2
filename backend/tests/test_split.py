"""Split and research: part specs, per-part cheapest offer, parts total, guards and hardening."""
import asyncio
from decimal import Decimal

import pytest

from app.errors import ConflictError
from app.research.schemas import ItemResult, Offer, ResearchSpec, SplitResult, Tier
from app.research.spec import build_part_spec
from tests.test_api_runs import app_client, wait_for
from tests.test_runs import finish, qn, seed, service, until

PARTS = [
    {"name": "Barrel", "typical_material": "Polypropylene", "count_per_unit": 1},
    {"name": "Rubber gasket", "typical_material": "Rubber", "count_per_unit": 2},
    {"name": "Needle", "typical_material": "Stainless steel", "count_per_unit": 1},
]


def syringe(splittable=True, parts=PARTS):
    return {"name": "2 mL syringe", "analysis": {"category": "syringe", "splittable": splittable, "parts": parts},
            "questions": [qn("quantity"), {**qn("capacity", "text"), "price_relevant": True},
                          {**qn("gauge", "text"), "price_relevant": True}],
            "answers": {"quantity": 10, "capacity": "2 mL", "gauge": "23G"}}


def offer(oid, price, in_range=True, cls="manufacturer"):
    return Offer(id=oid, manufacturer="M" + oid, city=None, state=None, platform="x", url="http://x/" + oid,
                 classification=cls, tiers=[Tier(min_qty=1, unit_price=Decimal(price))], moq=None,
                 in_range=in_range, flags=[], extra_links=[], price_quote="q", spec_match="match", observed_at=None)


def make_fn(prices, seen=None, fail=(), gate=None):
    """prices: part name -> unit price (None = no offer). Item mode returns one offer at 20."""
    async def fn(deps, spec, mode):
        if mode == "item":
            return ItemResult(spec_title=spec.title, quantity=spec.quantity, offers=[offer("f", "20")])
        if seen is not None:
            seen[spec.name] = (spec, mode)
        if gate:
            await gate.wait()
        if spec.name in fail:
            raise RuntimeError("boom")
        p = prices.get(spec.name)
        offers = [offer("cheap", p), offer("dear", "99"), offer("out", "0.01", in_range=False)] if p else []
        return ItemResult(spec_title=spec.title, quantity=spec.quantity, offers=offers)
    return fn


async def done_item(repo, fn, **item):
    rid, (iid,) = seed(repo, syringe(**item))
    svc = service(repo, fn)
    await svc.start(rid)
    await finish(svc)
    return svc, iid


async def finish_split(repo, iid):
    await until(lambda: repo.runs_for_item(iid)[0]["split_status"] != "running")
    return repo.runs_for_item(iid)[0]


async def test_split_requires_done_run(repo):
    rid, (iid,) = seed(repo, syringe())
    svc = service(repo, make_fn({}))
    with pytest.raises(ConflictError):
        await svc.split(iid)
    repo.create_run(iid, {}, {})  # queued is not done
    with pytest.raises(ConflictError):
        await svc.split(iid)


async def test_split_not_splittable_409(repo):
    svc, iid = await done_item(repo, make_fn({}), splittable=False, parts=[])
    with pytest.raises(ConflictError):
        await svc.split(iid)


async def test_split_twice_while_running_409(repo):
    gate = asyncio.Event()
    svc, iid = await done_item(repo, make_fn({"Barrel": "1"}, gate=gate))
    await svc.split(iid)
    assert repo.runs_for_item(iid)[0]["split_status"] == "running"
    with pytest.raises(ConflictError):
        await svc.split(iid)
    gate.set()
    await finish_split(repo, iid)
    await svc.split(iid)  # allowed again once finished
    await finish_split(repo, iid)


async def test_parts_total_uses_count_per_unit(repo):
    seen = {}
    svc, iid = await done_item(repo, make_fn({"Barrel": "2", "Rubber gasket": "0.5", "Needle": "1.5"}, seen))
    await svc.split(iid)
    run = await finish_split(repo, iid)
    assert run["split_status"] == "done"
    res = SplitResult.model_validate(run["split"])
    assert res.complete and res.parts_total == Decimal("4.5")  # 2 + 0.5 x 2 + 1.5
    assert [p.part for p in res.parts] == ["Barrel", "Rubber gasket", "Needle"]
    assert [p.offer.id for p in res.parts] == ["cheap"] * 3 and res.finished_lowest == Decimal("20")
    assert all(mode == "part" for _, mode in seen.values())
    assert seen["Rubber gasket"][0].quantity == 20 and seen["Barrel"][0].quantity == 10
    events = [e for e in repo.events_after(repo.get_item(iid)["research_id"], 0) if e["phase"] == "split"]
    assert events


async def test_missing_part_marks_incomplete(repo):
    svc, iid = await done_item(repo, make_fn({"Barrel": "2", "Needle": "1"}, fail={"Needle"}))
    await svc.split(iid)
    run = await finish_split(repo, iid)
    res = SplitResult.model_validate(run["split"])
    assert run["split_status"] == "done" and not res.complete and res.parts_total is None
    by = {p.part: p for p in res.parts}
    assert by["Barrel"].offer and by["Rubber gasket"].offer is None and by["Needle"].offer is None
    assert any("boom" in n for n in by["Needle"].notes)


async def test_split_interrupted_on_restart(repo):
    gate = asyncio.Event()
    svc, iid = await done_item(repo, make_fn({}, gate=gate))
    await svc.split(iid)
    repo.mark_interrupted()
    assert repo.runs_for_item(iid)[0]["split_status"] == "interrupted"
    await svc.shutdown()
    assert repo.runs_for_item(iid)[0]["split_status"] == "interrupted"


async def test_split_task_survives_unexpected_error(repo):
    svc, iid = await done_item(repo, make_fn({"Barrel": "1"}))
    real = repo.set_split

    def flaky(run_id, *, status, **kw):
        if status == "done":
            raise RuntimeError("db down")
        return real(run_id, status=status, **kw)

    repo.set_split = flaky
    await svc.split(iid)
    run = await finish_split(repo, iid)
    assert run["split_status"] == "failed" and run["split_error"] == "Split failed unexpectedly"


async def test_worker_survives_unexpected_error(repo):
    rid, (a, b) = seed(repo, syringe(), syringe())
    real = repo.set_run

    def flaky(run_id, *, status, **kw):
        if status == "done" and not getattr(flaky, "hit", False):
            flaky.hit = True
            raise RuntimeError("db down")
        return real(run_id, status=status, **kw)

    repo.set_run = flaky
    svc = service(repo, make_fn({}))
    await svc.start(rid)
    await finish(svc)
    first, second = repo.runs_for_item(a)[0], repo.runs_for_item(b)[0]
    assert first["status"] == "failed" and first["error"] == "Research failed unexpectedly"
    assert second["status"] == "done"
    assert svc.tasks == {}


class Hard(BaseException):
    pass


async def test_worker_exit_fails_queued_runs(repo):
    rid, (a, b) = seed(repo, syringe(), syringe())
    svc = service(repo, make_fn({}))

    async def bad(*_):
        raise Hard  # not an Exception subclass: escapes the per-run guard

    svc._run_one = bad
    await svc.start(rid)
    await asyncio.gather(*svc.tasks.values(), return_exceptions=True)
    assert repo.runs_for_item(b)[0]["status"] == "failed"


def test_part_spec_for_syringe_parts():
    parent = ResearchSpec(name="2 mL syringe", attributes={"capacity": "2 ml", "gauge": "23g"},
                          quantity=10, title="t", must_match=["capacity", "gauge"])
    barrel = build_part_spec(parent, PARTS[0])
    assert barrel.attributes == {"material": "Polypropylene", "capacity": "2 ml"} and barrel.must_match == ["capacity"]
    assert barrel.quantity == 10 and barrel.type_terms == ["barrel"]
    gasket = build_part_spec(parent, PARTS[1])
    assert gasket.quantity == 20 and gasket.type_terms == ["rubber gasket"]
    needle = build_part_spec(parent, PARTS[2])
    assert needle.attributes["gauge"] == "23g" and "capacity" not in needle.attributes and needle.must_match == ["gauge"]


def test_api_split_flow_and_conflicts(settings, db, repo):
    rid, (iid,) = seed(repo, syringe())
    with app_client(settings, make_fn({"Barrel": "2", "Rubber gasket": "1", "Needle": "1"})) as c:
        assert c.post(f"/api/items/{iid}/split").status_code == 409  # no done run yet
        assert c.post("/api/items/nope/split").status_code == 404
        c.post(f"/api/research/{rid}/start")
        wait_for(c, rid, lambda b: b["status"] == "done")
        assert c.post(f"/api/items/{iid}/split").status_code == 200
        body = wait_for(c, rid, lambda b: b["items"][0]["latest_run"]["split_status"] == "done")
        assert Decimal(str(body["items"][0]["latest_run"]["split"]["parts_total"])) == Decimal("5")


def test_start_and_split_503_when_llm_not_configured(settings, db, repo):
    rid, (iid,) = seed(repo, syringe())
    with app_client(settings, make_fn({})) as c:
        c.app.state.llm.is_configured = lambda: False
        for url in (f"/api/research/{rid}/start", f"/api/items/{iid}/split"):
            r = c.post(url)
            assert r.status_code == 503 and r.json()["error"]["code"] == "config_missing"
            assert "OPENAI_API_KEY" in r.json()["error"]["message"]
