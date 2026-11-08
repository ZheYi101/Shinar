from typing import NotRequired, Required, TypedDict

from langgraph.graph import END, START, StateGraph

from shinar.core.domain import (
    FeedbackItem,
    LanguageEnum,
    LearningMaterial,
    Message,
    PracticeInstruction,
    ProficiencyLevel,
    ReviewItem,
)
from shinar.core.ports import LearningLLMProvider


class LearningState(TypedDict, total=False):
    material: Required[LearningMaterial]
    learner_level: Required[ProficiencyLevel]
    target_language: Required[LanguageEnum]
    user_message: Required[Message]
    current_instruction: NotRequired[PracticeInstruction]
    assistant_message: NotRequired[str]
    corrections: NotRequired[list[FeedbackItem]]
    review_items: NotRequired[list[ReviewItem]]


def build_learning_session_graph(llm_provider: LearningLLMProvider):
    """langgraph logical function. containing several second packaged function from ports.py"""

    async def create_task(state: LearningState) -> dict:
        task_prompt = await llm_provider.generate_task(
            material=state["material"],
            learner_level=state["learner_level"],
            target_language=state["target_language"],
        )
        return {"current_instruction": PracticeInstruction(prompt=task_prompt)}

    async def correct_answer(state: LearningState) -> dict:
        current_instruction = state.get("current_instruction")
        if current_instruction is None:
            raise ValueError(
                "Learning.current_instruction is required before using correct_answer"
            )
        corrections = await llm_provider.correct_answer(
            current_instruction=current_instruction,
            user_message=state["user_message"],
            target_language=state["target_language"],
        )
        return {"corrections": corrections}

    async def generate_reply(state: LearningState) -> dict:
        current_instruction = state.get("current_instruction")
        if current_instruction is None:
            raise ValueError(
                "Learning.current_instruction is required before using generate_reply"
            )
        assistant_message = await llm_provider.generate_reply(
            current_instruction=current_instruction,
            material=state["material"],
            message_history=[],
            user_message=state["user_message"],
            corrections=state.get("corrections", []),
            target_language=state["target_language"],
        )
        return {"assistant_message": assistant_message}

    async def create_review_items(state: LearningState) -> dict:
        review_items = await llm_provider.create_review_items(
            corrections=state.get("corrections", []),
            material=state["material"],
        )
        return {"review_items": review_items}

    graph = StateGraph(LearningState)
    graph.add_node("create_review_items", create_review_items)
    graph.add_node("create_task", create_task)
    graph.add_node("correct_answer", correct_answer)
    graph.add_node("generate_reply", generate_reply)

    graph.add_edge(START, "create_task")
    graph.add_edge("create_task", "correct_answer")
    graph.add_edge("correct_answer", "generate_reply")
    graph.add_edge("generate_reply", "create_review_items")
    graph.add_edge("create_review_items", END)

    return graph.compile()
