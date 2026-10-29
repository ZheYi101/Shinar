"""Local lexical selection across every saved section; no extra model or vector service."""
from __future__ import annotations

import json
import re
from math import log

from lingualoop.core.domain import LearningMaterial
from lingualoop.core.reading_scope import scope_material


def _stem(word: str) -> str:
    if word == 'children': return 'child'
    if word.endswith(('ies', 'ied')) and len(word) > 4: return word[:-3] + 'y'
    if word.endswith('s') and not word.endswith(('ss', 'us')) and len(word) > 3: return word[:-1]
    return word


def _terms(text: str) -> set[str]:
    runs = re.findall(r"[a-z0-9]{2,}|[\u3040-\u30ff\u3400-\u9fff]+", text.casefold())
    stop = {'the', 'and', 'that', 'this', 'with', 'from', 'have', 'does', 'was', 'were', 'would', 'could',
            'what', 'which', 'about', 'think', 'book', 'story', 'reader', 'really', 'just', 'but', 'for',
            'you', 'your', 'his', 'her', 'she', 'him', 'not', 'how', 'can', 'did', 'its', 'are', 'there',
            'me', 'is', 'on', 'in', 'at', 'be', 'as', 'to', 'it', 'he', 'we', 'do', 'if', 'or', 'by', 'of',
            'an', 'no', 'up', 'so', 'am', 'when', 'than', 'then', 'also', 'very', 'their', 'them', 'they',
            'those', 'these', 'my', 'our', 'own', 'us', 'why', 'more', 'most', 'all', 'some', 'any', 'had', 'has',
            'think', 'thought', 'thing', 'things', 'feel', 'felt', 'feels', 'feeling', 'really', 'mean',
            'means', 'seem', 'seems', 'made', 'make', 'makes', 'making', 'say', 'says', 'said', 'saying',
            'tell', 'told', 'something', 'anything', 'everything', 'nothing', 'perhaps', 'maybe', 'almost',
            'actually', 'honestly', 'rather', 'quite', 'still', 'much', 'well', 'right', 'okay', 'hmm',
            'both', 'each', 'one', 'two', 'three', 'first', 'last', 'little', 'small', 'back', 'get', 'gets',
            'got', 'going', 'went', 'go', 'come', 'comes', 'coming', 'want', 'wanted', 'know', 'knew',
            'see', 'seen', 'look', 'looks', 'read', 'reading', 'remember', 'remembered', 'earlier', 'later',
            'also', 'now', 'here', 'where', 'way', 'take', 'takes', 'taken', 'through', 'over', 'other',
            'another', 'out', 'into', 'doesn', 'isn', 'wasn', 'don', 'didn', 'wouldn', 'couldn', 'isnt',
            'doe', 'thank', 'thanks', 'talk', 'talking', 'let', 'even', 'instead', 'being'}
    return {term for run in runs if run not in stop for term in
            ([_stem(run)] if run.isascii() else [run, *[run[index:index+2] for index in range(len(run)-1)]])}


def _score(text: str, terms: set[str]) -> int:
    folded = text.casefold()
    words = {_stem(word) for word in re.findall(r'[a-z0-9]+', folded)}
    return sum(min(len(term), 8) for term in terms if (term in words if term.isascii() else term in folded))


def dialogue_knowledge(material: LearningMaterial, query: str, previous: str = '') -> list[dict]:
    """Select already prepared facts, never scan the book or invoke reasoning live.

    Global overview and actual conversation remain separate from these quotations
    and possible readings. A late-book detail has the same chance as an opening one.
    """
    material = scope_material(material)
    analysis = material.analysis
    if not analysis:
        return []
    if analysis.preparation_strategy == "source-index-v1":
        return _source_references(material, query, previous)
    current_terms, previous_terms = _terms(query), _terms(previous)
    candidates = []
    searchable = []
    for chunk in analysis.chunks:
        payload = chunk.analysis_payload
        topics = [topic for topic in payload.get('topics', []) if isinstance(topic, dict)]
        for topic in topics:
            branches = topic.get('answer_branches', [])
            text = json.dumps(topic, ensure_ascii=False)
            score = 3 * _score(text, current_terms) + _score(text, previous_terms)
            if score:
                candidates.append((score, {'section': chunk.id, 'summary': chunk.summary[:400],
                    'discussion': str(topic.get('title', ''))[:160],
                    'points': [str(point)[:220] for branch in branches if isinstance(branch, dict)
                               for point in branch.get('response_points', [])][:5],
                    'quotes': list(dict.fromkeys([str(topic.get('source_excerpt', '')),
                        *[str(quote) for branch in branches if isinstance(branch, dict)
                          for quote in branch.get('source_excerpts', [])]]))[:3]}))
                searchable.append(text)
    # Characters and chronological outline offer factual recall beyond the chosen topic.
    for character in analysis.characters:
        text = character.name + ' ' + character.description + ' ' + ' '.join(character.source_excerpts)
        score = 3 * _score(text, current_terms) + _score(text, previous_terms)
        if score:
            candidates.append((score, {'character': character.name, 'points': [character.description[:500]],
                                      'quotes': character.source_excerpts[:2]}))
            searchable.append(text)
    # Names such as a first-person narrator appear everywhere. Rare scene words
    # must outrank frequent names/function words rather than rewarding repetition.
    terms = current_terms | previous_terms
    matches = [_terms(text) & terms for text in searchable]
    frequency = {term: sum(term in hit for hit in matches) for term in terms}
    weighted = []
    for (_, record), hit in zip(candidates, matches):
        score = sum((3 if term in current_terms else 1) * min(len(term), 8)
                    * log(1 + len(searchable) / (1 + frequency[term]))
                    for term in hit)
        weighted.append((score, record))
    candidates = weighted
    candidates.sort(key=lambda pair: pair[0], reverse=True)
    selected, per_section = [], {}
    for _, record in candidates:
        key = record.get('section', 'character')
        if per_section.get(key, 0) >= 2:
            continue
        per_section[key] = per_section.get(key, 0) + 1
        selected.append(record)
        if len(selected) == 4:
            break
    return selected


def _source_references(material: LearningMaterial, query: str, previous: str) -> list[dict]:
    """Prefer named participants, quoted wording and the latest conversational focus."""
    current, prior = _terms(query), _terms(previous)
    chunks = material.analysis.chunks
    names = set(material.analysis.keywords)
    current_names = current & names
    focus_names = current_names or (prior & names)
    quoted = [phrase.strip().casefold() for phrase in re.findall(r'[“"「](.*?)[”"」]', query)
              if len(phrase.strip()) >= 4]
    hits = [set(chunk.analysis_payload.get("search_terms", [])) & (current | prior) for chunk in chunks]
    frequency = {term: sum(term in hit for hit in hits) for term in current | prior}
    ranked = []
    for chunk, hit in zip(chunks, hits):
        score = sum((4 if term in current else 1) * min(len(term), 8)
                    * log(1 + len(chunks) / (1 + frequency[term])) for term in hit)
        source = material.content[chunk.start_char:chunk.end_char]
        matched_names = focus_names & hit
        score += 90 * len(matched_names)
        score += 180 * sum(phrase in source.casefold() for phrase in quoted)
        if score:
            ranked.append((score, chunk, matched_names))
    ranked.sort(key=lambda pair: pair[0], reverse=True)
    # Comparisons need both characters' scenes, not three passages about one name.
    selected, covered = [], set()
    notes_selected = 0
    requesting_notes = bool((current | prior) & {"commentary", "afterword", "foreword", "author", "nabokov", "critic"})
    for score, chunk, matched in ranked:
        heading = chunk.analysis_payload.get("source_section", "").casefold()
        is_note = "afterword" in heading or "on a book entitled" in heading
        if is_note and notes_selected >= 1 and not requesting_notes:
            continue
        if len(focus_names) > 1 and len(selected) == 1 and covered >= matched and focus_names - covered:
            continue
        selected.append((score, chunk))
        notes_selected += is_note
        covered.update(matched)
        if len(selected) == 3:
            break
    result = []
    for _, chunk in selected:
        text = material.content[chunk.start_char:chunk.end_char]
        window_terms = (current - names) | focus_names
        windows = _matching_windows(text, window_terms or prior, size=1200)
        excerpt = windows[0][2] if windows else text[:1200]
        result.append({"section": chunk.id, "source_heading_hint": chunk.analysis_payload.get("source_section", "Unlabeled source passage"),
                       "start_char": chunk.start_char, "end_char": chunk.end_char,
                       "points": [], "quotes": [excerpt]})
    return result


def _spread(items, count):
    if len(items) <= count:
        return list(items)
    if count <= 1:
        return items[:count]
    return [items[round(index * (len(items)-1)/(count-1))] for index in range(count)]


def _matching_windows(text: str, terms: set[str], *, size: int = 600) -> list[tuple[int, int, str]]:
    candidates = {}
    folded = text.casefold()
    for term in sorted(terms, key=len, reverse=True):
        position = 0
        for _ in range(12):
            match = folded.find(term, position)
            if match < 0:
                break
            start = max(0, match - size // 2)
            end = min(len(text), start + size)
            window = text[start:end]
            candidates[(start, end)] = (_score(window, terms), window)
            position = match + max(1, len(term))
    ranked = sorted(candidates.items(), key=lambda item: (-item[1][0], item[0][0]))
    selected = []
    for (start, end), (_, window) in ranked:
        if any(start < prior_end and end > prior_start for prior_start, prior_end, _ in selected):
            continue
        selected.append((start, end, window))
        if len(selected) >= 2:
            break
    return selected


def custom_topic_context(material: LearningMaterial, title: str) -> dict:
    material = scope_material(material)
    analysis = material.analysis
    if analysis is None:
        return {"evidence": [material.content[:2000]], "coverage": {"total_chunks": 0, "selected_chunk_ids": []}}
    chunks = analysis.chunks
    if not chunks:
        return {"summary": analysis.summary[:3000], "outline": _spread(analysis.outline, 30),
            "characters": [item.model_dump() for item in analysis.characters[:30]],
            "evidence": [topic.source_excerpt for topic in _spread(analysis.topics, 30)],
            "coverage": {"total_chunks": 0, "selected_chunk_ids": [], "legacy_unsegmented": True}}
    terms = _terms(title)
    scores = {chunk.id: _score(chunk.summary + json.dumps(chunk.analysis_payload, ensure_ascii=False)
        + material.content[chunk.start_char:chunk.end_char], terms) for chunk in chunks}
    ranked = sorted(chunks, key=lambda chunk: scores[chunk.id], reverse=True)
    relevant = [chunk for chunk in ranked if scores[chunk.id] > 0][:4]
    selected = list(relevant)
    for chunk in _spread(chunks, 6):
        if chunk not in selected:
            selected.append(chunk)
        if len(selected) >= 6:
            break
    selected.sort(key=lambda chunk: chunk.start_char)
    evidence = []
    characters = {}
    outline = []
    source_windows = []
    for chunk in selected:
        payload = chunk.analysis_payload
        outline.extend(payload.get("outline", [])[:6])
        for character in payload.get("characters", []):
            if isinstance(character, dict):
                characters.setdefault(str(character.get("name", "")), character)
        topics = [topic for topic in payload.get("topics", []) if isinstance(topic, dict)]
        topics.sort(key=lambda topic: _score(json.dumps(topic, ensure_ascii=False), terms), reverse=True)
        for start, end, text in _matching_windows(material.content[chunk.start_char:chunk.end_char], terms):
            source_windows.append({"chunk_id": chunk.id, "start_char": chunk.start_char + start,
                "end_char": chunk.start_char + end, "text": text})
        for topic in topics[:6]:
            quote = topic.get("source_excerpt")
            if isinstance(quote, str) and quote.strip() and quote in material.content and quote not in evidence:
                evidence.append(quote[:300])
        if not topics and chunk.source_excerpt not in evidence:
            evidence.append(chunk.source_excerpt)
    return {"whole_material_overview": [{"chunk_id": chunk.id, "summary": chunk.summary[:140]}
                for chunk in _spread(chunks, 48)],
        "selected_sections": [{"chunk_id": chunk.id, "start_char": chunk.start_char,
            "end_char": chunk.end_char, "summary": chunk.summary[:700]} for chunk in selected],
        "outline": outline, "characters": list(characters.values())[:30], "evidence": evidence,
        "matching_source_windows": source_windows,
        "coverage": {"total_chunks": len(chunks), "overview_sampled": len(chunks) > 48,
            "selected_chunk_ids": [chunk.id for chunk in selected],
            "selection": "lexical matches across all saved chunks and source text, matching source windows plus evenly distributed coverage; not full source retrieval"}}


def source_chunk_ids(material: LearningMaterial, topic) -> list[str]:
    if not material.analysis:
        return []
    quotes = [topic.source_excerpt, *(quote for branch in topic.answer_branches for quote in branch.source_excerpts)]
    return [chunk.id for chunk in material.analysis.chunks
            if any(quote in material.content[chunk.start_char:chunk.end_char] for quote in quotes)]
