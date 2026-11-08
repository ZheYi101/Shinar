"""Strict gates for newly generated preparations; legacy payloads remain readable."""
from shinar.core.domain import DialoguePreparation, DiscussionTopic


def validate_prepared_topic(topic: DiscussionTopic, source: str) -> DiscussionTopic:
    if not topic.source_excerpt.strip() or topic.source_excerpt not in source:
        raise ValueError("Unverified topic quotation")
    branches = []
    for branch in topic.answer_branches:
        if (not branch.user_intent.strip() or not branch.suggested_reply.strip()
            or not branch.follow_up.strip() or not any(point.strip() for point in branch.response_points)
            or not branch.source_excerpts
            or any(not quote.strip() or quote not in source for quote in branch.source_excerpts)):
            continue
        branches.append(branch.model_copy(update={
            "response_points": [point.strip() for point in branch.response_points if point.strip()][:8],
            "source_excerpts": list(dict.fromkeys(branch.source_excerpts))[:5],
        }))
    if not branches:
        raise ValueError("Prepared topic requires at least one complete source-grounded answer branch")
    return topic.model_copy(update={"answer_branches": branches[:5]})


def validate_dialogue_preparation(preparation: DialoguePreparation, source: str) -> DialoguePreparation:
    intents = [item.strip() for item in preparation.predicted_intents if item.strip()]
    points = [item.strip() for item in preparation.response_points if item.strip()]
    if not intents or not points or not preparation.source_excerpts:
        raise ValueError("Dialogue preparation requires intents, response points and source quotations")
    if any(not quote.strip() or quote not in source for quote in preparation.source_excerpts):
        raise ValueError("Unverified preparation quotation")
    return preparation.model_copy(update={"predicted_intents": intents[:3],
        "response_points": points[:8], "source_excerpts": list(dict.fromkeys(preparation.source_excerpts))[:5]})
