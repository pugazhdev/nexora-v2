import json

import httpx
import pytest
from openai import AsyncOpenAI
from pydantic import BaseModel

from app.clients.errors import (
    LLMAuthError,
    LLMBadResponseError,
    LLMQuotaError,
)
from app.clients.llm import LLM
from app.errors import AppError
from app.intake.image import PreparedImage


class Out(BaseModel):
    name: str


def _response(text: str, annotations: list | None = None, content_type: str = "output_text") -> dict:
    content = (
        {"type": "output_text", "text": text, "annotations": annotations or []}
        if content_type == "output_text"
        else {"type": "refusal", "refusal": "no"}
    )
    return {
        "id": "resp_1",
        "object": "response",
        "created_at": 0,
        "model": "m",
        "status": "completed",
        "parallel_tool_calls": False,
        "tool_choice": "auto",
        "tools": [],
        "output": [
            {
                "id": "msg_1",
                "type": "message",
                "role": "assistant",
                "status": "completed",
                "content": [content],
            }
        ],
    }


def make_llm(handler) -> LLM:
    client = AsyncOpenAI(
        api_key="x", max_retries=0, http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )
    return LLM("x", "text-model", "vision-model", 5.0, client=client)


def ok_handler(captured: list):
    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content))
        return httpx.Response(200, json=_response('{"name": "syringe"}'))

    return handler


async def test_parse_returns_model():
    got: list = []
    out = await make_llm(ok_handler(got)).parse(Out, instructions="i", text="t")
    assert out == Out(name="syringe")
    assert got[0]["model"] == "text-model"
    assert got[0]["store"] is False


async def test_401_maps_to_auth_error():
    llm = make_llm(lambda r: httpx.Response(401, json={"error": {"message": "bad key"}}))
    with pytest.raises(LLMAuthError) as ei:
        await llm.parse(Out, instructions="i", text="t")
    assert isinstance(ei.value, AppError)


async def test_429_maps_to_quota_error():
    llm = make_llm(lambda r: httpx.Response(429, json={"error": {"message": "slow"}}))
    with pytest.raises(LLMQuotaError) as ei:
        await llm.parse(Out, instructions="i", text="t")
    assert ei.value.status_code == 429


async def test_refusal_maps_to_bad_response():
    llm = make_llm(lambda r: httpx.Response(200, json=_response("", content_type="refusal")))
    with pytest.raises(LLMBadResponseError):
        await llm.parse(Out, instructions="i", text="t")


async def test_image_uses_vision_model():
    got: list = []
    img = PreparedImage(data=b"\xff\xd8\xff", mime_type="image/jpeg")
    await make_llm(ok_handler(got)).parse(Out, instructions="i", text="t", image=img)
    assert got[0]["model"] == "vision-model"


async def test_web_search_sends_india_location():
    got: list = []
    ann = [{"type": "url_citation", "url": "https://a.in/x", "title": "A", "start_index": 0, "end_index": 1}]

    def handler(request: httpx.Request) -> httpx.Response:
        got.append(json.loads(request.content))
        return httpx.Response(200, json=_response('{"name": "s"}', ann))

    await make_llm(handler).web_search(Out, instructions="i", prompt="p")
    assert got[0]["tools"][0]["user_location"]["country"] == "IN"


async def test_web_search_extracts_citations_and_strips_utm():
    got: list = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        got.append(body)
        if "tools" in body:
            ann = [
                {
                    "type": "url_citation",
                    "url": "https://tradeindia.com/p/x?id=5&utm_source=openai",
                    "title": "Syringe X",
                    "start_index": 0,
                    "end_index": 1,
                }
            ]
            return httpx.Response(200, json=_response("found syringes", ann))
        return httpx.Response(200, json=_response('{"name": "syringe"}'))

    out = await make_llm(handler).web_search(Out, instructions="i", prompt="p")
    assert out == Out(name="syringe")
    assert len(got) == 2
    assert "tools" not in got[1]
    second_input = json.dumps(got[1]["input"])
    assert "https://tradeindia.com/p/x?id=5" in second_input
    assert "utm_source" not in second_input


async def test_invalid_json_maps_to_bad_response():
    llm = make_llm(lambda r: httpx.Response(200, json=_response('{"name": ')))
    with pytest.raises(LLMBadResponseError):
        await llm.parse(Out, instructions="i", text="t")


async def test_web_search_without_citations_makes_one_call_and_raises():
    got: list = []

    def handler(request: httpx.Request) -> httpx.Response:
        got.append(json.loads(request.content))
        return httpx.Response(200, json=_response("nothing cited"))

    with pytest.raises(LLMBadResponseError, match="no cited sources"):
        await make_llm(handler).web_search(Out, instructions="i", prompt="p")
    assert len(got) == 1
