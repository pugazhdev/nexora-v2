"""Intake graph: validate, prepare image, analyse with the LLM, screen deterministically."""
from typing import TypedDict

from langgraph.graph import END, START, StateGraph
from pydantic import ValidationError

from app.clients.llm import LLM
from app.config import Settings
from app.errors import AppError
from app.intake.image import PreparedImage, prepare_image
from app.intake.prompts import ANALYSE_INSTRUCTIONS
from app.intake.schemas import IntakeAnalysis, IntakeAnalysisDraft, IntakeItem, Question
from app.intake.screen import Screened, screen_items

_IMAGE_ONLY_TEXT = "Identify the hospital consumables in this photo."


class IntakeState(TypedDict, total=False):
    text: str | None
    image_bytes: bytes | None
    image: PreparedImage | None
    analysis: IntakeAnalysisDraft
    screened: Screened


def _to_analysis(draft: IntakeAnalysisDraft) -> IntakeAnalysis:
    items = []
    for it in draft.items:
        qs = []
        for q in it.questions:
            try:
                qs.append(Question.model_validate(q.model_dump()))
            except ValidationError:
                continue  # drop only the malformed question
        items.append(IntakeItem.model_validate({**it.model_dump(), "questions": [q.model_dump() for q in qs]}))
    return IntakeAnalysis(items=items, input_quality=draft.input_quality, notes=draft.notes)


def build_intake_graph(llm: LLM, settings: Settings):
    async def validate_input(state: IntakeState):
        text = (state.get("text") or "").strip()
        if not text and not state.get("image_bytes"):
            raise AppError("Add a photo or paste the requirement.")
        if len(text) > settings.max_text_chars:
            raise AppError(f"Text is too long. Keep it under {settings.max_text_chars} characters.")
        return {"text": text}

    async def prepare(state: IntakeState):
        img = prepare_image(
            state["image_bytes"], None,
            max_bytes=settings.max_upload_bytes, max_pixels=settings.max_image_pixels,
            max_side=settings.image_max_side,
        )
        return {"image": img}

    async def analyse_input(state: IntakeState):
        text = state["text"] or _IMAGE_ONLY_TEXT
        analysis = await llm.parse(
            IntakeAnalysisDraft, instructions=ANALYSE_INSTRUCTIONS,
            text=f"<user_input>\n{text}\n</user_input>", image=state.get("image"),
        )
        return {"analysis": analysis}

    async def screen(state: IntakeState):
        return {"screened": screen_items(_to_analysis(state["analysis"]), max_items=settings.max_items)}

    g = StateGraph(IntakeState)
    g.add_node("validate_input", validate_input)
    g.add_node("prepare_image", prepare)
    g.add_node("analyse_input", analyse_input)
    g.add_node("screen", screen)
    g.add_edge(START, "validate_input")
    g.add_conditional_edges(
        "validate_input", lambda s: "prepare_image" if s.get("image_bytes") else "analyse_input",
        ["prepare_image", "analyse_input"],
    )
    g.add_edge("prepare_image", "analyse_input")
    g.add_edge("analyse_input", "screen")
    g.add_edge("screen", END)
    return g.compile()


async def run_intake(llm: LLM, settings: Settings, *, text: str | None, image_bytes: bytes | None) -> Screened:
    out = await build_intake_graph(llm, settings).ainvoke({"text": text, "image_bytes": image_bytes})
    return out["screened"]
