"""Bounded, source-grounded preprocessing; no book-sized context in live turns."""
from __future__ import annotations
from hashlib import sha256
import os
import asyncio
import json

from lingualoop.core.domain import MaterialAnalysis, PreparedChunk, LearningMaterial, SessionUserProfile, new_id
from lingualoop.core.preparation_validation import validate_prepared_topic

CHUNK_CHARS = 12000
MAX_MATERIAL_CHARS = 1000000
MAX_TOPICS = 60
PREPARATION_CACHE_VERSION = 'free-chat-v1'


def preparation_cache_key(provider, material: LearningMaterial, profile: SessionUserProfile) -> tuple[str, str]:
    source_hash = sha256(material.content.encode('utf-8')).hexdigest()
    identity = getattr(provider, 'preparation_cache_identity', type(provider).__module__ + '.' + type(provider).__qualname__)
    data = {'version': PREPARATION_CACHE_VERSION, 'provider': identity, 'source_hash': source_hash,
            'title': material.title, 'source_language': material.source_language.value,
            'profile': profile.model_dump(mode='json'), 'read_through': material.read_through}
    return source_hash, sha256(json.dumps(data, sort_keys=True, ensure_ascii=False).encode('utf-8')).hexdigest()


def split_material(text: str, size: int = CHUNK_CHARS):
    try:
        budget = int(os.getenv("LINGUALOOP_MAX_MATERIAL_CHARS", str(MAX_MATERIAL_CHARS)))
        if not 12000 <= budget <= 5000000:
            raise ValueError
    except ValueError:
        raise ValueError("LINGUALOOP_MAX_MATERIAL_CHARS 须为 12000 到 5000000 的整数。") from None
    if len(text) > budget:
        raise ValueError(f"材料已保存。当前单份材料最多 {budget} 字符，请按卷或篇章拆分，或调整 LINGUALOOP_MAX_MATERIAL_CHARS。")
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        if end < len(text):
            boundary = max(text.rfind("\n", start + size // 2, end),
                           text.rfind("。", start + size // 2, end))
            if boundary >= 0:
                end = boundary + 1
        yield start, end, text[start:end]
        start = end


async def prepare_material(provider, material: LearningMaterial, profile: SessionUserProfile, on_progress=None) -> MaterialAnalysis:
    if getattr(provider, "supports_free_chat", False):
        from lingualoop.application.source_index import build_source_index
        return build_source_index(material)
    try:
        budget = int(os.getenv("LINGUALOOP_PREPARATION_DEADLINE_SECONDS", "1800"))
        if not 1 <= budget <= 86400:
            raise ValueError
    except ValueError:
        raise ValueError("LINGUALOOP_PREPARATION_DEADLINE_SECONDS 须为 1 到 86400 的整数。") from None
    try:
        return await asyncio.wait_for(_prepare_material(provider, material, profile, on_progress), timeout=budget)
    except TimeoutError:
        raise ValueError(f"本次材料整理达到 {budget} 秒预算，已保存完成的段落。请继续分析，或调大 LINGUALOOP_PREPARATION_DEADLINE_SECONDS。") from None


async def _prepare_material(provider, material: LearningMaterial, profile: SessionUserProfile, on_progress=None) -> MaterialAnalysis:
    # A whole novel needs a finite section index and a cross-section synthesis.
    # Keep the old small-material/provider path compatible and deterministic.
    sections = list(split_material(material.content, size=24000 if len(material.content) > 120000 else CHUNK_CHARS))
    completed = {}
    cached = {(chunk.start_char, chunk.end_char, chunk.content_hash): chunk
              for chunk in material.analysis.chunks} if material.analysis else {}
    parallelism = max(1, min(4, int(getattr(provider, "preparation_concurrency", 1))))
    semaphore, progress_lock = asyncio.Semaphore(parallelism), asyncio.Lock()
    section_analyzer = getattr(provider, "analyze_material_section", None) if len(sections) > 1 else None
    # Seed every reusable section before saving any progress. Otherwise retrying
    # an early missing section could overwrite later paid-for sections on disk.
    for index, (start, end, content) in enumerate(sections):
        prior = cached.get((start, end, sha256(content.encode('utf-8')).hexdigest()))
        if not prior or not prior.analysis_payload:
            continue
        try:
            analysis = MaterialAnalysis.model_validate(prior.analysis_payload)
            topics = []
            for topic in analysis.topics:
                try:
                    topics.append(validate_prepared_topic(topic, content))
                except ValueError:
                    continue
            if topics:
                completed[index] = analysis.model_copy(update={'topics': topics}), prior
        except (ValueError, TypeError):
            continue
    all_cached = len(completed) == len(sections)

    def snapshot():
        pairs = [completed[index] for index in sorted(completed)]
        return [pair[0] for pair in pairs], [pair[1] for pair in pairs]

    async def prepare_section(index, section):
        async with semaphore:
            if index in completed:
                return
            start, end, content = section
            digest = sha256(content.encode("utf-8")).hexdigest()
            prior = cached.get((start, end, digest))
            chunk_material = material.model_copy(update={"content": content, "analysis": None,
                "title": f"{material.title} — section {index + 1}/{len(sections)}",
                "raw_content": None, "normalized_content": None})
            analyzer = section_analyzer or provider.analyze_material
            analysis = await analyzer(material=chunk_material,
                target_language=profile.target_language, native_language=profile.native_language)
            topics = []
            for topic in analysis.topics:
                try:
                    topics.append(validate_prepared_topic(topic, content))
                except ValueError:
                    continue
            if not topics:
                raise ValueError("材料话题缺少完整且有原文依据的回答分支，已保留原文，请重新分析。")
            analysis = analysis.model_copy(update={"topics": topics})
            chunk = PreparedChunk(id=prior.id if prior else new_id("chunk"),
                start_char=start, end_char=end, summary=analysis.summary,
                source_excerpt=content[:200], content_hash=digest, analysis_payload=analysis.model_dump(mode="json"))
            async with progress_lock:
                completed[index] = analysis, chunk
                if on_progress:
                    analyses, chunks = snapshot()
                    await on_progress(_merge_analyses(analyses, chunks, material, complete=False))

    if completed and on_progress and not (all_cached and material.analysis.overview_complete and material.analysis.preparation_complete):
        analyses, chunks = snapshot()
        await on_progress(_merge_analyses(analyses, chunks, material, complete=False))
    if parallelism == 1:
        for index, section in enumerate(sections):
            await prepare_section(index, section)
    else:
        tasks = [asyncio.create_task(prepare_section(index, section)) for index, section in enumerate(sections)]
        try:
            await asyncio.gather(*tasks)
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
    analyses, chunks = snapshot()
    if not completed:
        raise ValueError("材料没有可分析的文字。")
    merged = _merge_analyses(analyses, chunks, material, complete=True)
    synthesizer = getattr(provider, "synthesize_material", None)
    if len(sections) > 1 and callable(synthesizer):
        previous = material.analysis
        if previous and previous.overview_complete and previous.preparation_complete and all_cached:
            return previous.model_copy(update={"chunks": chunks})
        overview = await synthesizer(material=material, sections=analyses,
            target_language=profile.target_language, native_language=profile.native_language)
        global_topics = []
        for topic in overview.topics:
            try:
                verified = validate_prepared_topic(topic, material.content)
            except ValueError:
                continue
            quotes = [verified.source_excerpt, *(quote for branch in verified.answer_branches for quote in branch.source_excerpts)]
            global_topics.append(verified.model_copy(update={"source_chunk_ids": [chunk.id for chunk in chunks
                if any(quote in material.content[chunk.start_char:chunk.end_char] for quote in quotes)]}))
        if not global_topics:
            raise ValueError("各段已保存，整书话题缺少有效依据，请继续整理。")
        merged = merged.model_copy(update={"summary": overview.summary, "outline": overview.outline,
            "characters": overview.characters, "topics": [*global_topics, *merged.topics][:MAX_TOPICS],
            "overview_complete": True})
    return merged


def _merge_analyses(analyses, chunks, material, *, complete):
    first = analyses[0]
    characters = {}
    topics = {}
    for analysis in analyses:
        for character in analysis.characters:
            if character.source_excerpts and all(quote and quote in material.content for quote in character.source_excerpts):
                characters.setdefault(character.name, character)
    # Round robin across processed sections keeps the topic budget from favouring early chapters.
    for index in range(max((len(analysis.topics) for analysis in analyses), default=0)):
        for analysis, chunk in zip(analyses, chunks):
            if index < len(analysis.topics):
                topic = analysis.topics[index]
                key = (topic.title, topic.source_excerpt)
                if key not in topics:
                    topics[key] = topic.model_copy(update={"source_chunk_ids": [chunk.id]})
                elif chunk.id not in topics[key].source_chunk_ids:
                    topics[key] = topics[key].model_copy(update={"source_chunk_ids": [*topics[key].source_chunk_ids, chunk.id]})
    outline = [item for analysis in analyses for item in (analysis.outline or [analysis.summary])]
    return first.model_copy(update={
        "summary": first.summary if len(analyses) == 1 else "\n".join(f"{i+1}. {chunk.summary}" for i, chunk in enumerate(chunks)),
        "outline": outline, "characters": list(characters.values()), "chunks": chunks,
        "preparation_complete": complete,
        "topics": list(topics.values())[:MAX_TOPICS],
        "keywords": list(dict.fromkeys(item for analysis in analyses for item in analysis.keywords))[:30],
    })
