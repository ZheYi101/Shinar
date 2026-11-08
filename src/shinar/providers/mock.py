from __future__ import annotations

import re
import json
from collections import Counter

from shinar.core.domain import (
    FeedbackItem,
    FeedbackType,
    LanguageEnum,
    LearningMaterial,
    MaterialAnalysis,
    MaterialExpression,
    Message,
    PracticeInstruction,
    ProficiencyLevel,
    ReviewItem,
    ReviewItemKind,
    SessionReview,
    DiscussionTopic,
    PracticeOptions,
    AnswerBranch, DialoguePreparation,
)
from shinar.core.ports import LearningLLMProvider
from shinar.core.knowledge import ReasoningRequest, ReasoningResponse


class MockLearningLLMProvider(LearningLLMProvider):
    supports_semantic_preparation = True
    supports_free_chat = True

    @staticmethod
    def _knowledge_response(value):
        from shinar.core.knowledge import ReasoningResponse
        return ReasoningResponse(content=json.dumps(value, ensure_ascii=False),
            usage={"input_tokens": 100, "output_tokens": 100, "finish_reason": "stop"})

    async def prepare_source_unit(self, request: ReasoningRequest) -> ReasoningResponse:
        paragraphs = request.payload["paragraphs"]
        selected = paragraphs[:2] + paragraphs[-1:] if len(paragraphs) > 2 else paragraphs
        return self._knowledge_response({"notes": [{"text": paragraph["text"][:220].strip(),
            "support_ids": [paragraph["id"]], "attribution": "source", "statement_kind": "narrated",
            "entities": [], "search_terms": [], "aliases": {}} for paragraph in selected]})

    async def summarize_reading(self, request: ReasoningRequest) -> ReasoningResponse:
        notes = request.payload["ordered_notes"]
        selected = notes[:2] + notes[-1:] if len(notes) > 2 else notes
        return self._knowledge_response({"summary": " ".join(note["text"][:180] for note in selected),
            "points": [{"text": note["text"][:180], "support_ids": [note["id"]]} for note in selected]})

    async def prepare_focus(self, request: ReasoningRequest) -> ReasoningResponse:
        return self._knowledge_response({"points": [{"text": evidence["text"][:160],
            "support_ids": [evidence["id"]]} for evidence in request.payload["evidence"][:1]], "directions": []})

    async def summarize_conversation(self, request: ReasoningRequest) -> ReasoningResponse:
        return self._knowledge_response({"items": [{"text": message["text"][:160],
            "message_ids": [message["id"]], "speaker": message["role"], "kind": "stance"}
            for message in request.payload["messages"][-4:]]})
    """Deterministic provider for CLI demos and offline tests."""

    async def analyze_material(
        self,
        *,
        material: LearningMaterial,
        target_language: LanguageEnum,
        native_language: LanguageEnum,
    ) -> MaterialAnalysis:
        words = _tokenize(material.content)
        keywords = [word for word, _ in Counter(words).most_common(5)]
        expressions = [
            MaterialExpression(
                text=word,
                meaning=f"Useful word from the material: {word}",
                example=f"Use {word} in your own sentence.",
            )
            for word in keywords[:3]
        ]
        summary = (_first_sentence(material.content) or material.title)[:300]
        difficulties = []
        if any(word in words for word in {"went", "bought", "was", "were"}):
            difficulties.append("simple past tense")
        if any(word in words for word in {"the", "a", "an"}):
            difficulties.append("article usage")

        japanese = target_language is LanguageEnum.JAPANESE
        titles = ["聊聊你的感受", "换成你会怎么做", "联系自己的经历", "故事的核心", "人物的选择", "人物关系", "最喜欢的片段", "不同的看法", "事情的起因", "结果与变化", "作品中的主题", "想继续了解什么"]
        questions = (["この内容で、何が一番印象に残りましたか？", "あなたなら、どうしますか？", "似た経験はありますか？",
            "この話で一番大切なのは何だと思いますか？", "登場人物の選択をどう思いますか？", "人と人との関係はどう変わりましたか？",
            "どの場面が好きですか？", "違う考え方もあると思いますか？", "なぜそうなったと思いますか？", "何が変わりましたか？",
            "この話のテーマは何だと思いますか？", "もっと知りたいことはありますか？"] if japanese else
            ["What stood out to you in this material?", "What would you do in this situation?", "Have you had a similar experience?",
             "What is the central idea?", "What do you think of the choices?", "How do the relationships change?",
             "Which part do you like?", "Could you see it another way?", "Why did this happen?", "What changed?",
             "What theme do you notice?", "What would you like to discuss further?"])
        quote = material.content[:160]
        branches = [AnswerBranch(user_intent=intent, response_points=[quote],
            suggested_reply=("その見方は面白いですね。" if japanese else "That's an interesting perspective."),
            follow_up=("どの部分からそう思いましたか？" if japanese else "Which part makes you think so?"),
            source_excerpts=[quote]) for intent in ("喜欢并认同", "不喜欢或不同意", "暂时没有想法")]
        return MaterialAnalysis(
            summary=summary,
            keywords=keywords,
            expressions=expressions,
            difficulties=difficulties,
            suggested_goals=[
                f"Retell the material in {target_language.value}",
                "Reuse one or two expressions from the text",
            ],
            topics=[DiscussionTopic(title=title, opening_question=question, source_excerpt=quote,
                category=("impression" if index < 3 else "story"), answer_branches=branches)
                for index, (title, question) in enumerate(zip(titles, questions))],
            outline=[summary],
        )

    async def prepare_custom_topic(self, *, material, title, target_language, native_language):
        opening = await self.generate_task(material=material, learner_level=ProficiencyLevel.UNKNOWN,
            target_language=target_language,
            topic=DiscussionTopic(title=title, opening_question=title, source_excerpt=material.content[:160]),
            options=PracticeOptions())
        quote = material.content[:160]
        return DiscussionTopic(title=title, opening_question=opening, source_excerpt=quote,
            category="custom", answer_branches=[AnswerBranch(user_intent="表达自己的看法",
                response_points=[quote], suggested_reply="なるほど。" if target_language is LanguageEnum.JAPANESE else "I see.",
                follow_up=opening, source_excerpts=[quote])])

    async def prepare_dialogue(self, *, material, session):
        quote = session.topic.source_excerpt if session.topic else material.content[:160]
        return DialoguePreparation(based_on_message_count=len(session.messages),
            predicted_intents=["补充理由", "询问看法", "谈自己的经历"], response_points=[quote], source_excerpts=[quote])

    async def stream_reply(self, **kwargs):
        reply = await self.generate_reply(**kwargs)
        for index in range(0, len(reply), 8):
            yield reply[index:index+8]

    async def generate_task(
        self,
        *,
        material: LearningMaterial,
        learner_level: ProficiencyLevel,
        target_language: LanguageEnum,
        topic: DiscussionTopic | None = None,
        options: PracticeOptions | None = None,
    ) -> str:
        if topic:
            if options and options.mode.value == "discussion":
                return ("この話題について、どう思いますか？" if target_language is LanguageEnum.JAPANESE
                        else "What do you think about this topic?")
            return ("では、この場面を一緒に演じましょう。どうしたのですか？"
                    if target_language is LanguageEnum.JAPANESE else "Let's try this scene. What brings you here?")
        if material.analysis and material.analysis.keywords:
            focus = ", ".join(material.analysis.keywords[:3])
            return (
                f"Retell the material in one or two sentences. "
                f"Try to include: {focus}."
            )
        return "Retell the material in one or two sentences."

    async def generate_reply(
        self,
        *,
        current_instruction: PracticeInstruction,
        material: LearningMaterial,
        message_history: list[Message],
        user_message: Message,
        corrections: list[FeedbackItem],
        target_language: LanguageEnum,
    ) -> str:
        if corrections:
            fixes = "; ".join(
                f"{item.original} -> {item.corrected}" for item in corrections[:3]
            )
            return (
                f"Good effort. Focus on these fixes: {fixes}. "
                f"Try adding one more detail from the material."
            )
        return ("なるほど。そう思った理由を、もう少し聞かせてもらえますか？"
                if target_language is LanguageEnum.JAPANESE else "That's interesting. What makes you feel that way?")

    async def correct_answer(
        self,
        *,
        current_instruction: PracticeInstruction,
        user_message: Message,
        target_language: LanguageEnum,
    ) -> list[FeedbackItem]:
        lowered = f" {user_message.content.lower()} "
        feedback: list[FeedbackItem] = []
        if " go " in lowered or lowered.strip().startswith("i go"):
            feedback.append(
                FeedbackItem(
                    error_type=FeedbackType.GRAMMAR,
                    original="go",
                    corrected="went",
                    explanation="Use the simple past tense for completed actions.",
                )
            )
        if " buy " in lowered or lowered.strip().startswith("i buy"):
            feedback.append(
                FeedbackItem(
                    error_type=FeedbackType.GRAMMAR,
                    original="buy",
                    corrected="bought",
                    explanation="Use the simple past tense for completed actions.",
                )
            )
        return feedback

    async def create_review_items(
        self,
        *,
        corrections: list[FeedbackItem],
        material: LearningMaterial,
    ) -> list[ReviewItem]:
        if corrections:
            correction = corrections[0]
            return [
                ReviewItem(
                    kind=ReviewItemKind.CLOZE,
                    prompt=f"Rewrite this using the correction: {correction.original} -> ____",
                    answer=correction.corrected,
                    source_feedback_id=correction.id,
                    source_message_id=correction.source_message_id,
                )
            ]
        return [
            ReviewItem(
                kind=ReviewItemKind.CLOZE,
                prompt=f"Summarize the material: {material.title}",
                answer=material.analysis.summary if material.analysis else material.content,
            )
        ]

    async def summarize_session(
        self,
        *,
        session,
        material: LearningMaterial,
        target_language: LanguageEnum,
    ) -> SessionReview:
        feedback = list(session.feedback_items)
        if not feedback:
            for message in session.messages:
                if message.role.value == "user":
                    items = await self.correct_answer(current_instruction=session.current_instruction,
                                                      user_message=message, target_language=target_language)
                    feedback.extend(item.model_copy(update={"source_message_id": message.id}) for item in items)
        review_items = await self.create_review_items(
            corrections=feedback[-3:],
            material=material,
        )
        return SessionReview(
            summary=(f"围绕《{material.title}》完成了 {sum(m.role.value == 'user' for m in session.messages)} 次发言。"
                if session.profile.native_language is LanguageEnum.CHINESE else
                f"You completed {len([m for m in session.messages if m.role.value == 'user'])} "
                f"learner response(s) around {material.title}."
            ),
            focus_areas=[
                item.explanation for item in feedback[:3]
            ],
            feedback_items=feedback[:3],
            review_items=review_items[:3] if feedback else [],
            next_action="Return later and produce the review answers without looking at the answer first.",
        )


def _tokenize(text: str) -> list[str]:
    words = re.findall(r"[a-zA-Z']+", text.lower())
    stopwords = {
        "the",
        "a",
        "an",
        "and",
        "or",
        "to",
        "of",
        "in",
        "is",
        "was",
        "were",
        "it",
        "i",
        "you",
        "we",
        "they",
        "he",
        "she",
        "that",
        "this",
        "with",
        "for",
        "on",
        "at",
        "as",
        "be",
        "by",
    }
    return [word for word in words if len(word) > 2 and word not in stopwords]


def _first_sentence(text: str) -> str:
    stripped = text.strip()
    if not stripped:
        return ""
    match = re.split(r"(?<=[.!?])\s+", stripped, maxsplit=1)
    return match[0].strip()


class LegacyMockLearningLLMProvider(MockLearningLLMProvider):
    """Explicit fixture for providers using the persisted topic-bank contract."""

    supports_free_chat = False
