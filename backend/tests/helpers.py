ITEM = {
    "name": "Disposable syringe",
    "analysis": {"category": "syringe"},
    "questions": [{"key": "capacity", "label": "Capacity"}],
    "answers": {"capacity": "2 mL"},
}
SPEC = {"name": "Disposable syringe", "capacity": "2 mL"}


def seeded_item(repo, items=None) -> str:
    rid = repo.create_research("2 mL syringe", None, "Syringe", items or [ITEM])
    return repo.get_research(rid)["items"][0]["id"]
