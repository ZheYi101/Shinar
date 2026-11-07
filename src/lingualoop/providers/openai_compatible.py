from __future__ import annotations

import json
import os
import asyncio
from time import perf_counter
from typing import Any, AsyncIterator
from urllib.parse import urlparse
import httpx

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_openai import ChatOpenAI
from langchain_openai.chat_models.base import BaseChatOpenAI
from pydantic import BaseModel, SecretStr, Field

from lingualoop.core.domain import (
    FeedbackItem,
    FeedbackType,
    LanguageEnum,
    MaterialAnalysis,
    MaterialExpression,
    LearningMaterial,
    Message,
    PracticeInstruction,
    ProficiencyLevel,
    ReviewItem,
    ReviewItemKind,
    PracticeSession,
    SessionReview,
    DiscussionTopic,
    PracticeOptions,
    AnswerBranch, MaterialCharacter, DialoguePreparation,
)
from lingualoop.core.ports import LearningLLMProvider
from lingualoop.core.knowledge import ReasoningRequest, ReasoningResponse
from lingualoop.core.preparation_validation import validate_prepared_topic, validate_dialogue_preparation
from lingualoop.core.material_context import custom_topic_context, source_chunk_ids, dialogue_knowledge, _terms, _score


from lingualoop.providers.openai_settings import (
    OpenAICompatibleLLMSettings as OpenAICompatibleLLMSettings,
    _chat_model_kwargs as _chat_model_kwargs,
    _env_flag as _env_flag,
    _is_deepseek as _is_deepseek,
    _optional_env as _optional_env,
    _optional_flag as _optional_flag,
    _required_env as _required_env,
    normalize_openai_base_url as normalize_openai_base_url,
)
from lingualoop.providers.openai_prompts import (
    _boundary_message as _boundary_message,
    _compact_reply_packet as _compact_reply_packet,
    _dialogue_system_prompt as _dialogue_system_prompt,
    _feedback_to_text as _feedback_to_text,
    _messages_to_text as _messages_to_text,
    _prepared_material_context as _prepared_material_context,
    _reasoning_system_prompt as _reasoning_system_prompt,
)
from lingualoop.providers.openai_responses import (
    _load_json_response as _load_json_response,
    _parse_feedback_items as _parse_feedback_items,
    _parse_material_analysis as _parse_material_analysis,
    _parse_review_items as _parse_review_items,
    _parse_session_review as _parse_session_review,
    _review_item_kind as _review_item_kind,
)


class _PreparationBudgetExceeded(Exception):
    pass




class OpenAICompatibleLLMProvider(LearningLLMProvider):
    supports_semantic_preparation = True
    """LearningLLMProvider implementation for OpenAI-compatible endpoints."""

    def __init__(
        self,
        settings: OpenAICompatibleLLMSettings,
        *,
        reasoning_client: BaseChatModel | None = None,
        dialogue_client: BaseChatModel | None = None,
    ) -> None:
        self._settings = settings
        # ChatOpenAI rewrites max_tokens to OpenAI's max_completion_tokens.
        # DeepSeek's documented contract uses max_tokens; the compatible base preserves it.
        client_type = BaseChatOpenAI if _is_deepseek(settings.base_url) else ChatOpenAI
        # Human turns are farther apart than HTTPX's 5-second idle default.
        # Isolate pools: cancelling speculation must not close the dialogue socket.
        self._http_async_clients = {}
        def pooled(role, maximum):
            client = httpx.AsyncClient(timeout=settings.timeout,
                limits=httpx.Limits(max_connections=maximum, max_keepalive_connections=maximum, keepalive_expiry=120))
            self._http_async_clients[role] = client
            return {'http_async_client': client, 'http_socket_options': ()}
        self._reasoning_client: BaseChatModel = reasoning_client or client_type(
            **settings.reasoning_client_kwargs(), **pooled('reasoning', 4)
        )
        self._dialogue_client: BaseChatModel = dialogue_client or client_type(
            **settings.dialogue_client_kwargs(), **pooled('dialogue', 2)
        )
        self._preparation_diagnostics: list[dict[str, Any]] = []

    @classmethod
    def from_env(cls, prefix: str = "OPENAI_") -> "OpenAICompatibleLLMProvider":
        return cls(OpenAICompatibleLLMSettings.from_env(prefix=prefix))

    @property
    def preparation_cache_identity(self) -> str:
        endpoint = urlparse(self._settings.base_url)
        return json.dumps({'adapter': 'openai-compatible', 'host': endpoint.hostname, 'port': endpoint.port,
            'scheme': endpoint.scheme, 'path': endpoint.path, 'reasoning_model': self._settings.reasoning_model,
            'reasoning_thinking': self._settings.reasoning_thinking}, sort_keys=True)

    @property
    def preparation_concurrency(self) -> int:
        value = int(os.getenv("LINGUALOOP_PREPARATION_CONCURRENCY", "3"))
        if not 1 <= value <= 4:
            raise ValueError("LINGUALOOP_PREPARATION_CONCURRENCY 须为1到4。")
        return value

    supports_free_chat = True

    @property
    def dialogue_output_budget(self) -> int:
        return self._settings.dialogue_max_tokens

    async def _knowledge_request(self, task: str, request: ReasoningRequest) -> ReasoningResponse:
        from lingualoop.core.knowledge import ReasoningResponse
        from lingualoop.providers.knowledge_prompts import PROMPTS

        diagnostics = {}
        options = {"max_tokens": request.max_tokens}
        if _is_deepseek(self._settings.base_url):
            options["reasoning_effort"] = "low"
        content = await self._invoke_text(self._reasoning_client,
            [SystemMessage(content=PROMPTS[task]), HumanMessage(content=json.dumps(request.payload, ensure_ascii=False, separators=(',', ':')))],
            options=options, diagnostics=diagnostics,
            deadline_seconds=min(request.deadline_seconds, self._settings.reasoning_deadline_seconds))
        return ReasoningResponse(content=content, usage=diagnostics)

    async def prepare_source_unit(self, request: ReasoningRequest) -> ReasoningResponse:
        return await self._knowledge_request("unit", request)

    async def summarize_reading(self, request: ReasoningRequest) -> ReasoningResponse:
        return await self._knowledge_request("brief", request)

    async def prepare_focus(self, request: ReasoningRequest) -> ReasoningResponse:
        return await self._knowledge_request("focus", request)

    async def summarize_conversation(self, request: ReasoningRequest) -> ReasoningResponse:
        return await self._knowledge_request("memory", request)

    async def generate_task(
        self,
        *,
        material: LearningMaterial,
        learner_level: ProficiencyLevel,
        target_language: LanguageEnum,
        topic: DiscussionTopic | None = None,
        options: PracticeOptions | None = None,
    ) -> str:
        messages = [
            SystemMessage(content=_reasoning_system_prompt(target_language)),
            HumanMessage(
                content=(
                    "Create one concise practice task.\n"
                    "Ground the task strictly in the provided material. Do not invent/add facts "
                    "that are not present in the material. If a practice extension is needed, "
                    "label it as 'practice extension' and keep original material facts separate.\n"
                    f"Target language: {target_language.value}\n"
                    f"Learner level: {learner_level.value}\n"
                    f"Selected topic: {topic.model_dump_json() if topic else 'none'}\n"
                    f"Practice preferences: {options.model_dump_json() if options else 'legacy task'}\n"
                    "When a topic is provided, open a natural conversation in the target language. "
                    "For roleplay follow the selected roles, label invented scenario details as practice extensions. "
                    "Do not prescribe a lesson, retelling assignment, or comprehension test.\n"
                    f"Material title: {material.title}\n"
                    f"Material content:\n{_prepared_material_context(material)}"
                )
            ),
        ]
        return await self._invoke_text(self._reasoning_client, messages)

    async def analyze_material(
        self,
        *,
        material: LearningMaterial,
        target_language: LanguageEnum,
        native_language: LanguageEnum,
    ) -> MaterialAnalysis:
        return await self._analyze_material(material=material, target_language=target_language,
            native_language=native_language, compact=False)

    async def analyze_material_section(self, *, material, target_language, native_language) -> MaterialAnalysis:
        return await self._analyze_material(material=material, target_language=target_language,
            native_language=native_language, compact=True)

    async def _analyze_material(self, *, material, target_language, native_language, compact) -> MaterialAnalysis:
        topic_count = "2" if compact else "8-12"
        messages = [
            SystemMessage(
                content=(
                    "Analyze the learning material and return only a JSON object "
                    "with these fields: summary, keywords, expressions, difficulties, "
                    "suggested_goals, outline (ordered story/content events), characters (name, description, source_excerpts), topics. "
                    f"Prepare {topic_count} distinct reusable discussion topics covering central story, characters, relationships, choices, themes, personal reactions. "
                    "Only include topics supported by this excerpt; short sparse input may yield fewer. Each topic has "
                    "title (learner native language), opening_question (target language), "
                    "source_excerpt (an exact nonempty quotation from the material, at most 200 characters). "
                    "Also category and answer_branches (2-4 per topic): user_intent (possible learner response, explicitly hypothetical), "
                    "response_points (short factual response points), suggested_reply (one short target-language reaction), "
                    "follow_up (one short target-language question), source_excerpts (exact quotations supporting the points). "
                    "Cover opposing/common opinions where supported. Predictions are possibilities, never evidence that the learner said them. "
                    "Offer natural discussion about impressions, choices and personal connections. "
                    "Write the summary and explanations in the learner native language. "
                    "Do not require roleplay, retelling or vocabulary drills. Each expression must contain text, meaning, "
                    "and optionally example. Keep the result concise and useful for "
                    "a language learner. Attribute narrator claims and interpretations rather than treating every claim as objective fact. "
                    "Use non-graphic literary discussion and short non-graphic quotations. "
                    + ("This is an ordered section of a longer book, not its whole plot. Write a concise section summary (at most 250 Chinese characters), "
                       "3-5 concrete plot/argument outline items, at most 4 key characters with exact evidence, and exactly 2 branches per topic. "
                       "Keep each response point to one short factual sentence and quotations under 130 characters. "
                       "Prioritize events, motives, narrator reliability and details that help a reader discuss this section. "
                       "Set expressions, difficulties and suggested_goals to empty arrays; keep the entire final JSON under 2200 tokens."
                       if compact else "")
                )
            ),
            HumanMessage(
                content=(
                    f"Source language: {material.source_language.value}\n"
                    f"Target language: {target_language.value}\n"
                    f"Learner native language: {native_language.value}\n"
                    f"Material title: {material.title}\n"
                    f"Material content:\n{material.content}"
                )
            ),
        ]
        token_budget = 16000 if compact else self._settings.reasoning_max_tokens
        for attempt in range(2):
            options = {"reasoning_effort": "low", "max_tokens": token_budget} if compact and _is_deepseek(self._settings.base_url) else None
            diagnostics = {}
            content = await self._invoke_text(self._reasoning_client, messages, options=options, diagnostics=diagnostics)
            if diagnostics.get('finish_reason') == 'length':
                if compact and not attempt:
                    token_budget = max(token_budget + 8000, self._settings.reasoning_max_tokens)
                    continue
                raise ValueError('材料分析达到模型输出预算，已保存完成段落，请继续整理。')
            try:
                analysis = _parse_material_analysis(content)
                topics = []
                for topic in analysis.topics:
                    try:
                        topics.append(validate_prepared_topic(topic, material.content))
                    except ValueError:
                        continue
                if not topics:
                    raise ValueError("Source-grounded prepared answer branches are missing")
                return analysis.model_copy(update={"topics": topics[:12]})
            except (ValueError, TypeError):
                if attempt:
                    raise ValueError("材料分析格式或话题引用无效，原文已保留，请重试。") from None
                messages.append(HumanMessage(content="Return a valid JSON object. Each topic needs at least one complete answer branch with user_intent, response_points, suggested_reply, follow_up and nonempty exact source_excerpts. Use only exact source quotations."))
        raise AssertionError("unreachable")

    async def synthesize_material(self, *, material, sections, target_language, native_language):
        notes = [{"section": index + 1, "summary": section.summary, "outline": section.outline,
                  "characters": [{"name": character.name, "description": character.description[:180],
                      "source_excerpts": character.source_excerpts[:1]} for character in section.characters],
                  "topics": [{"title": topic.title, "source_excerpt": topic.source_excerpt,
                      "readings": [{"intent": branch.user_intent,
                          "points": branch.response_points[:2], "quotes": branch.source_excerpts[:1]}
                          for branch in topic.answer_branches[:2]]} for topic in section.topics]}
                 for index, section in enumerate(sections)]
        messages = [SystemMessage(content=(
            "Synthesize a whole-book reading companion from ALL ordered section notes. Return a JSON object with summary, outline, "
            "characters (name, description, source_excerpts), topics, keywords, expressions, difficulties, suggested_goals. "
            "The summary must integrate the opening, middle and ending, not concatenate section summaries (at most 900 Chinese characters). "
            "Write 12-18 chronological plot/argument beats including the ending. Consolidate character aliases and changing motives across the book. "
            "Prepare 12 distinct whole-book reader-discussion topics, covering narrative voice/reliability, important choices, relationships, "
            "reversals, ending and mixed reader reactions. Do not produce generic book-club questions that could fit any book. "
            "Each topic: title in the native language, category, opening_question in the target language, source_excerpt and exactly 2 answer_branches. "
            "Use a short, inviting spoken opening (at most 25 English words), not an essay question or a question with an assumed correct interpretation. "
            "Each branch: user_intent (a hypothetical, including opposing readings), response_points (specific grounded details), "
            "suggested_reply and follow_up in target language, source_excerpts. Copy short exact source quotations from the notes; "
            "never quote generated summaries as original text. Connect relevant scenes across sections where supported. "
            "Distinguish narrator assertions, observable events and interpretations; preserve other characters' perspectives. "
            "Separate the fictional foreword, main narrative, author afterword and critical commentary when present. "
            "Discuss sensitive material critically and non-graphically. No invented facts or vocabulary drills. "
            "Every character needs source_excerpts copied from supplied source quotes. Summary and explanations use the native language. "
            "Keep each branch to 1-2 response points, a one-sentence suggested_reply, one follow_up and one short exact quote. "
            "At most 10 consolidated characters. Set keywords, expressions, difficulties and suggested_goals to empty arrays. "
            "Keep final JSON under 6500 tokens; do not repeat lengthy passages."
        )), HumanMessage(content=json.dumps({"title": material.title,
            "target_language": target_language.value, "native_language": native_language.value,
            "ordered_sections": notes}, ensure_ascii=False))]
        token_budget = self._settings.reasoning_max_tokens
        for attempt in range(2):
            options = {'reasoning_effort': 'low', 'max_tokens': token_budget} if _is_deepseek(self._settings.base_url) else None
            diagnostics = {}
            content = await self._invoke_text(self._reasoning_client, messages, options=options, diagnostics=diagnostics,
                deadline_seconds=self._settings.synthesis_deadline_seconds)
            if diagnostics.get('finish_reason') == 'length':
                if not attempt:
                    token_budget += 8000
                    messages.append(HumanMessage(content='The previous response exceeded its output budget. Keep the JSON concise and complete; do not repeat source passages.'))
                    continue
                raise ValueError('整书汇总达到输出预算；各段已保存，请继续整理。')
            try:
                analysis = _parse_material_analysis(content)
                topics = []
                for topic in analysis.topics:
                    try:
                        topics.append(validate_prepared_topic(topic, material.content))
                    except ValueError:
                        continue
                characters = [character for character in analysis.characters if character.source_excerpts
                    and all(quote and quote in material.content for quote in character.source_excerpts)]
                if topics and analysis.summary and analysis.outline:
                    return analysis.model_copy(update={"topics": topics, "characters": characters})
            except (ValueError, TypeError):
                pass
            if not attempt:
                messages.append(HumanMessage(content="Return valid grounded JSON; source quotations must be copied verbatim from the notes. Include summary, chronological outline and complete discussion branches."))
        raise ValueError("整书概要或话题依据不完整；已保存各段，可继续整理。")

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
        messages = self._reply_messages(current_instruction=current_instruction, material=material,
            message_history=message_history, user_message=user_message, corrections=corrections,
            target_language=target_language)
        return await self._invoke_text(self._dialogue_client, messages)

    def _reply_messages(self, *, current_instruction, material, message_history, user_message,
                        corrections, target_language):
        from lingualoop.core.reading_scope import scope_material
        material = scope_material(material)
        metadata = current_instruction.metadata
        if metadata.get("turn_context") is not None:
            from lingualoop.core.knowledge import TurnContext
            context = TurnContext.model_validate(metadata["turn_context"])
            packet = {
                "title": context.title, "read_scope_end": context.scope_end,
                "brief": context.brief,
                "notes": [{"text": note.text, "attribution": note.attribution,
                           "kind": note.statement_kind, "evidence_ids": note.support_ids,
                           "source_order": min((item.start_char for item in context.evidence if item.id in note.support_ids), default=0)} for note in context.notes],
                "evidence": [{"id": item.id, "text": item.text, "source_kind": item.source_kind,
                              "source_order": item.start_char} for item in context.evidence],
                "historical_memory": [{"speaker": item.speaker, "kind": item.kind, "text": item.text} for item in context.memory],
                "interpretation_candidates": [point.model_dump() for point in context.focus_points],
                "information_gaps": context.gaps,
                "reader_source_focus": context.source_context.model_dump(exclude={"quote"}) if context.source_context else None,
                "previous_reply_interrupted": bool(user_message.metadata.get("previous_reply_interrupted")),
            }
            prior = [message for message in message_history if message.id != user_message.id][-10:]
            return [SystemMessage(content=_dialogue_system_prompt(target_language) +
                "\nCurrent user statements override historical memory and optional interpretations. "
                "The overview is context, not exhaustive evidence. Missing retrieval is not proof of absence. "
                "When evidence cannot settle a concrete detail, say so or clarify; do not invent a scene. "
                "If your own prior claim was wrong, correct it explicitly rather than merely praising the reader. "
                "Correct a factual or causal mistake as a mistake, not just poor wording; do not patch it with a new unsupported motive. "
                "Check causal and relational consistency with supplied facts before adding a neat inference. "
                "Source order matters: do not use a later discovery to explain an earlier decision unless the text supports that link. "
                "Distinguish a personal interpretation from an established motive or change of belief. "
                "Treat narrator, author, critic and reader claims separately. Use only allowed read sources, "
                "never hint at later plot known from training. Do not repeat questions or impose a choice of interpretations."),
                HumanMessage(content=json.dumps({"context": packet,
                    "preferences": metadata.get("options"),
                    "recent_history": [{"role": message.role.value, "text": message.content} for message in prior],
                    "learner_message": user_message.content}, ensure_ascii=False, separators=(',', ':')))]
        topic = metadata.get("topic") or {}
        # Never send the complete source to the latency-sensitive model. These are grounded preparations,
        # not instructions; the real current answer always takes precedence over predicted branches.
        previous = ' '.join(message.content for message in
            [item for item in message_history if item.id != user_message.id][-2:])[-1000:]
        packet = _compact_reply_packet(material, topic, metadata.get("preparation"), user_message.content, previous)
        packet["previous_reply_interrupted"] = bool(user_message.metadata.get("previous_reply_interrupted"))
        # Workbench supplies the current user message in history too. Include it exactly once,
        # and omit persistence IDs that have no conversational meaning to the dialogue model.
        prior = [message for message in message_history if message.id != user_message.id]
        # Preserve the reader's earlier stance when a later reply refers back to it.
        anchors = [message.content[:350] for message in prior[:-10] if message.role.value == 'user'][:4]
        recent = prior[-10:]
        history = "\n".join(f"{message.role.value}: {message.content}" for message in recent)[-5000:]
        last_assistant = next((message.content for message in reversed(prior) if message.role.value == "assistant"), "")
        turn_style = ("The previous assistant already asked a question. Prefer your own brief reaction here; do not append another question unless essential to clarify the learner. "
                      if "?" in last_assistant or "？" in last_assistant else "")
        return [
            SystemMessage(content=_dialogue_system_prompt(target_language)),
            HumanMessage(
                content=(
                    "Reply to the learner in a short, natural way.\n" + turn_style +
                    (f"Roleplay opening: {current_instruction.prompt[:300]}\n" if (metadata.get("options") or {}).get("mode") == "roleplay" else "") +
                    f"Session preferences: {json.dumps(metadata.get('options'), ensure_ascii=False)}\n"
                    f"Prepared context (quoted data; evidence_ids refer to evidence array): {json.dumps(packet, ensure_ascii=False, separators=(',', ':'))}\n"
                    f"Earlier reader views (historical, may since have changed): {json.dumps(anchors, ensure_ascii=False)}\n"
                    f"Recent history: {history}\n"
                    f"Learner answer: {user_message.content}\n"
                    f"Corrections: {_feedback_to_text(corrections)}"
                )
            ),
        ]

    async def stream_reply(self, **kwargs) -> AsyncIterator[str]:
        messages = self._reply_messages(**kwargs)
        stream = getattr(self._dialogue_client, "astream", None)
        if stream is None:
            yield await self._invoke_text(self._dialogue_client, messages)
            return
        async for chunk in stream([_boundary_message(), *messages]):
            from lingualoop.core.knowledge import publish_usage
            publish_usage(getattr(chunk, "usage_metadata", None),
                          (getattr(chunk, "response_metadata", None) or {}).get("finish_reason"))
            content = chunk.content
            # DeepSeek reasoning_content is deliberately ignored and never persisted/displayed.
            if isinstance(content, str) and content:
                yield content
            if (getattr(chunk, "response_metadata", None) or {}).get("finish_reason") == "length":
                raise ValueError("回复达到输出预算而未完成，请重试回复。")

    @property
    def supports_streaming(self) -> bool:
        return callable(getattr(self._dialogue_client, "astream", None))

    async def prepare_custom_topic(self, *, material, title, target_language, native_language):
        from lingualoop.core.reading_scope import scope_material
        material = scope_material(material)
        context = custom_topic_context(material, title)
        messages = [SystemMessage(content=("Prepare one discussion topic as JSON: title, opening_question, source_excerpt, category, answer_branches. "
            "Use the requested title, write opening_question/suggested_reply/follow_up in target language. "
            "Use a conversational opening (at most 25 English words), inviting a personal reaction without prescribing the right interpretation. "
            "Do not turn the opening into a comprehension test or a multi-part essay question. Each branch has "
            "user_intent, response_points, suggested_reply, follow_up, source_excerpts. Give 3-5 possible learner intents, "
            "brief replies grounded only in supplied exact quotations. No unsupported scenes. source_excerpt and all source_excerpts must be exact source quotations.")),
            HumanMessage(content=json.dumps({"requested_topic": title, "target_language": target_language.value,
                "native_language": native_language.value, "prepared_material": context}, ensure_ascii=False))]
        for attempt in range(2):
            try:
                topic = DiscussionTopic.model_validate(_load_json_response(await self._invoke_text(self._reasoning_client, messages)))
                topic = validate_prepared_topic(topic, material.content)
                return topic.model_copy(update={"title": title, "source_chunk_ids": source_chunk_ids(material, topic)})
            except (ValueError, TypeError):
                if attempt:
                    raise ValueError("自定话题整理失败，材料已保留，请重试。") from None
                messages.append(HumanMessage(content="Return valid JSON with at least one complete answer branch: user_intent, nonempty response_points, suggested_reply, follow_up and nonempty source_excerpts. Use only exact quotations from evidence."))
        raise AssertionError("unreachable")

    async def prepare_dialogue(self, *, material, session):
        from lingualoop.core.reading_scope import scope_material
        material = scope_material(material)
        topic = session.topic
        branches = topic.answer_branches if topic else []
        quote = (branches[0].source_excerpts[0] if branches and branches[0].source_excerpts
                 else topic.source_excerpt if topic else material.content[:160])[:200]
        recent_user = next((message.content for message in reversed(session.messages) if message.role.value == 'user'), '')
        knowledge = dialogue_knowledge(material, recent_user, session.messages[-1].content if session.messages else '')
        relevant = next((item for item in knowledge if item.get('quotes')), None)
        grounded_points = branches[0].response_points[:2] if branches else []
        if relevant:
            quote = relevant['quotes'][0][:600]
            grounded_points = relevant.get('points', [])[:2]
        data = {"topic": topic.title[:120] if topic else material.title[:120],
            "candidate_intents": [branch.user_intent[:80] for branch in branches[:3]],
            "grounded_points": [point[:100] for point in grounded_points],
            "quote": quote,
            "directions_language": session.profile.target_language.value,
            "allowed_source": [item.get("quotes", [])[:1] for item in knowledge[:3]],
            "recent": [{"role": message.role.value, "text": message.content[:220]} for message in session.messages[-2:]]}
        messages = [SystemMessage(content=("Prepare a tiny next-turn reference. Return only JSON: "
            '{"intent":"one possible NEXT learner intent","points":["one or two short reply points"],"quote":"exact supplied quote"}. '
            "The intent is a hypothesis, never an actual learner statement. Each intent/point must be at most 80 characters. "
            "Use only the supplied sources as evidence, do not add outside plot or future events. Select useful existing points, "
            "or briefly restate a source if no candidate fits. Copy quote exactly. Optionally add directions: up to 3 short "
            "specific, inviting discussion directions in directions_language, based on the reader's actual interests. "
            "They are suggestions, not a lesson plan, test or fixed script. No prepared answers. Empty directions is valid. "
            "Keep the JSON under 400 characters apart from quote. Stay within supplied read passages; never hint at later events.")),
            HumanMessage(content=json.dumps(data, ensure_ascii=False, separators=(',', ':')))]
        diagnostics: list[dict[str, Any]] = []
        self._preparation_diagnostics = diagnostics
        max_attempts = 1 if session.pattern_id == "free-discussion" else self._settings.background_max_attempts
        for attempt in range(max_attempts):
            record = {"attempt": attempt + 1, "result": "started"}
            diagnostics.append(record)
            stage = "invoke"
            try:
                options = {"max_tokens": 4000} if session.pattern_id == "free-discussion" else {}
                if _is_deepseek(self._settings.base_url):
                    options.update({"reasoning_effort": "low", "max_tokens": 4000})
                record.update({key: value for key, value in options.items() if key in {"reasoning_effort", "max_tokens"}})
                text = await self._invoke_text(self._reasoning_client, messages, options=options, diagnostics=record)
                if record.get("finish_reason") == "length":
                    record["result"] = "output_budget_exhausted"
                    # The same bounded request cannot repair a token-limit termination by retrying unchanged.
                    raise _PreparationBudgetExceeded
                stage = "json_parse"
                payload = _load_json_response(text)
                if isinstance(payload, dict) and any(key in payload for key in ("intent", "points", "quote")):
                    payload = {"predicted_intents": [payload.get("intent", "")],
                        "response_points": payload.get("points", []), "source_excerpts": [payload.get("quote", "")],
                        "suggested_directions": payload.get("directions", [])}
                stage = "schema_validation"
                result = DialoguePreparation.model_validate({**payload, "based_on_message_count": len(session.messages)})
                stage = "evidence_validation"
                result = validate_dialogue_preparation(result, material.content)
                stage = "compact_output_budget"
                if any(len(value) > 80 for value in [*result.predicted_intents[:1], *result.response_points[:2]]):
                    raise ValueError("Preparation intent and points exceed compact output budget")
                result = result.model_copy(update={"predicted_intents": result.predicted_intents[:1],
                    "response_points": result.response_points[:2], "source_excerpts": result.source_excerpts[:1],
                    "suggested_directions": [value.strip()[:70] for value in result.suggested_directions if value.strip()][:3]})
                record["result"] = "validated"
                return result
            except _PreparationBudgetExceeded:
                raise ValueError("后台准备达到输出预算；当前对话仍可继续。") from None
            except (ValueError, TypeError):
                record["result"] = "invalid_structure_or_evidence"
                record["failure_stage"] = stage
                if attempt + 1 >= max_attempts:
                    raise ValueError("后台准备格式或引用无效；当前对话仍可继续。") from None
                messages.append(HumanMessage(content='Return only {"intent":"one nonempty possibility","points":["one nonempty reply point"],"quote":"copy supplied quote exactly"}. No other fields or explanations.'))
        raise AssertionError("unreachable")

    @property
    def preparation_diagnostics(self) -> list[dict[str, Any]]:
        """Safe operational metadata only: never prompts, content, quotations or reasoning traces."""
        return [dict(record) for record in self._preparation_diagnostics]

    async def correct_answer(
        self,
        *,
        current_instruction: PracticeInstruction,
        user_message: Message,
        target_language: LanguageEnum,
    ) -> list[FeedbackItem]:
        # TODO: replace with stricter prompt + parser when you settle the schema.
        messages = [
            SystemMessage(
                content=(
                    "Return only a JSON array. Each item must contain "
                    "error_type, original, corrected, explanation."
                )
            ),
            HumanMessage(
                content=(
                    f"Task: {current_instruction.prompt}\n"
                    f"Feedback preferences: {json.dumps(current_instruction.metadata.get('options'), ensure_ascii=False)}\n"
                    f"Learner answer: {user_message.content}\n"
                    f"Target language: {target_language.value}"
                )
            ),
        ]
        content = await self._invoke_text(self._reasoning_client, messages)
        return _parse_feedback_items(content)

    async def create_review_items(
        self,
        *,
        corrections: list[FeedbackItem],
        material: LearningMaterial,
    ) -> list[ReviewItem]:
        # TODO: add richer item generation once review-item schema stabilizes.
        if not corrections:
            return []

        messages = [
            SystemMessage(
                content=(
                    "Return only a JSON array. Each item must contain prompt, answer, "
                    "and optionally kind."
                )
            ),
            HumanMessage(
                content=(
                    f"Material title: {material.title}\n"
                    f"Material content: {material.content}\n"
                    f"Corrections: {_feedback_to_text(corrections)}"
                )
            ),
        ]
        content = await self._invoke_text(self._reasoning_client, messages)
        return _parse_review_items(content)

    async def summarize_session(
        self,
        *,
        session: PracticeSession,
        material: LearningMaterial,
        target_language: LanguageEnum,
    ) -> SessionReview:
        review_context = (json.dumps({"title": material.title, "scope": "Only discuss confirmed learner output; no plot judgement."})
                          if session.pattern_id == "free-discussion" else _prepared_material_context(material))
        messages = [
            SystemMessage(
                content=(
                    "Return only a JSON object with fields summary, focus_areas, "
                    "feedback_items, review_items, and next_action. "
                    "feedback_items must contain error_type, original, corrected, "
                    "explanation, source_message_id (a real user message ID). review_items must contain prompt, answer, kind, "
                    "source_message_id or source_feedback_id. Only correct actual learner output. "
                    "Never diagnose pronunciation from transcripts. Return empty lists if there is no evidence. "
                    "Create no more than three feedback_items, focus_areas and review_items. Keep feedback pattern-level."
                )
            ),
            HumanMessage(
                content=(
                    f"Target language: {target_language.value}\n"
                    f"Practice preferences: {session.options.model_dump_json() if session.options else 'legacy'}\n"
                    f"Learner native language: {session.profile.native_language.value}. Write summary and explanations in this language; examples stay in the target language.\n"
                    "Respect correction_intensity: low focuses on one important pattern, medium on two, high on up to three.\n"
                    f"Material title: {material.title}\n"
                    f"Material:\n{review_context}\n"
                    f"Conversation:\n{_messages_to_text(session.messages[-40:])}\n"
                    f"Existing feedback:\n{_feedback_to_text(session.feedback_items)}"
                )
            ),
        ]
        options = None
        if session.pattern_id == "free-discussion":
            options = {"max_tokens": 4000}
            if _is_deepseek(self._settings.base_url):
                options["reasoning_effort"] = "low"
        content = await self._invoke_text(self._reasoning_client, messages, options=options)
        return _parse_session_review(content)

    async def _invoke_text(
        self, client: BaseChatModel, messages: list[BaseMessage], *, options: dict[str, Any] | None = None,
        diagnostics: dict[str, Any] | None = None,
        deadline_seconds: float | None = None,
    ) -> str:
        # HTTP read timeouts can be kept alive by service heartbeat whitespace.
        # An explicit wall-clock deadline bounds a non-streaming call as well.
        started = perf_counter()
        try:
            response = await asyncio.wait_for(client.ainvoke([_boundary_message(), *messages], **(options or {})),
                                              timeout=deadline_seconds if deadline_seconds is not None else self._settings.reasoning_deadline_seconds)
        except BaseException as exc:
            if diagnostics is not None:
                diagnostics["error_type"] = type(exc).__name__
                diagnostics["result"] = ("cancelled_or_deadline" if isinstance(exc, asyncio.CancelledError)
                    else "deadline_exceeded" if isinstance(exc, TimeoutError) else "provider_error")
            raise
        finally:
            if diagnostics is not None:
                diagnostics["elapsed_ms"] = round((perf_counter()-started)*1000, 2)
        if diagnostics is not None:
            metadata = getattr(response, "response_metadata", None) or {}
            reason = metadata.get("finish_reason")
            diagnostics["finish_reason"] = reason if reason in {None, "stop", "length", "content_filter", "tool_calls"} else "other"
            usage = getattr(response, "usage_metadata", None) or {}
            for key in ("input_tokens", "output_tokens", "total_tokens"):
                if isinstance(usage.get(key), int):
                    diagnostics[key] = usage[key]
        from lingualoop.core.knowledge import publish_usage
        publish_usage(getattr(response, "usage_metadata", None),
                      (getattr(response, "response_metadata", None) or {}).get("finish_reason"))
        content = response.content
        if isinstance(content, str):
            return content.strip()
        return str(content).strip()

    async def aclose(self) -> None:
        closed = set()
        for client in (self._reasoning_client, self._dialogue_client):
            root = getattr(client, "root_async_client", None)
            if root is not None and id(root) not in closed:
                closed.add(id(root))
                await root.close()
        for client in self._http_async_clients.values():
            if not client.is_closed:
                await client.aclose()
