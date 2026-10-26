from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from app.domain.matching import Requirements
from app.domain.tailoring import ResumeDocument, ResumeSource, build_document, validate_document


class TailoringState(TypedDict):
    document: ResumeDocument | None


async def tailor_document(
    source: ResumeSource, requirements: Requirements, maximum: int
) -> ResumeDocument:
    async def select_and_tailor(state: TailoringState) -> dict[str, Any]:
        return {"document": build_document(source, requirements, maximum)}

    async def verify_facts(state: TailoringState) -> dict[str, Any]:
        document = state["document"]
        assert document is not None
        validate_document(document, source, requirements, maximum)
        return {}

    graph = StateGraph(TailoringState)
    graph.add_node("select_and_tailor", select_and_tailor)
    graph.add_node("verify_facts", verify_facts)
    graph.add_edge(START, "select_and_tailor")
    graph.add_edge("select_and_tailor", "verify_facts")
    graph.add_edge("verify_facts", END)
    result = await graph.compile().ainvoke({"document": None})
    return ResumeDocument.model_validate(result["document"])
