"""Explicit real-service novel acceptance, with persistent resumable local data.

The SQLite file contains the user's source and confirmed conversation; keep it
outside version control. JSON reports contain only timing and coverage metadata.
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import sys
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))


def emit(value):
    print(json.dumps(value, ensure_ascii=False), flush=True)


async def run(args):
    from dotenv import load_dotenv
    load_dotenv(ROOT / '.env')
    if not args.real or os.getenv('RUN_REAL_AI_TESTS') != '1':
        raise ValueError('Requires --real and RUN_REAL_AI_TESTS=1')
    from shinar.application import LearningWorkbench
    from shinar.infrastructure import SQLiteStore
    from shinar.infrastructure.material_import import import_material_file
    from shinar.providers.openai_compatible import OpenAICompatibleLLMProvider
    from shinar.core import LanguageEnum, ProficiencyLevel
    from benchmark_prepared_dialogue import AuditClient, inspect_analysis, candidate_hashes, wait_for_preparation

    args.data_dir.mkdir(parents=True, exist_ok=True)
    records = []
    provider = OpenAICompatibleLLMProvider.from_env()
    for name, role in (('_reasoning_client', 'reasoning'), ('_dialogue_client', 'dialogue')):
        client = getattr(provider, name).model_copy(update={'max_retries': 0})
        setattr(provider, name, AuditClient(client, role, records, max_calls=90 if role == 'reasoning' else 20))

    class ProgressStore(SQLiteStore):
        def save_material(self, material):
            super().save_material(material)
            if args.phase == 'prepare' and material.analysis:
                emit({'saved_sections': len(material.analysis.chunks),
                    'preparation_complete': material.analysis.preparation_complete,
                    'overview_complete': material.analysis.overview_complete,
                    'elapsed_s': round(perf_counter() - started, 1)})

    started = perf_counter()
    store = ProgressStore(args.data_dir / 'novel.sqlite3')
    work = LearningWorkbench(provider, event_store=store)
    report = {'phase': args.phase, 'date': datetime.now(timezone.utc).isoformat(), 'candidate': candidate_hashes()}
    try:
        if args.phase in {'prepare', 'start', 'turn', 'review', 'chat'}:
            from urllib.parse import urlparse
            if urlparse(provider._settings.base_url).hostname == 'api.deepseek.com':
                import httpx
                async with httpx.AsyncClient(timeout=15) as client:
                    response = await client.get('https://api.deepseek.com/user/balance', headers={
                        'Authorization': 'Bearer ' + provider._settings.api_key.get_secret_value()})
                response.raise_for_status()
                if not response.json().get('is_available'):
                    emit({'service_unavailable': 'insufficient_balance', 'models_not_called': True})
                    raise ValueError('DeepSeek 余额不足；请恢复账户后继续。')
        if args.phase == 'prepare':
            imported = import_material_file(args.material)
            digest = sha256(imported.normalized_content.encode()).hexdigest()
            existing = next((m for m in work.materials if sha256(m.content.encode()).hexdigest() == digest), None)
            emit({'source_chars': len(imported.normalized_content), 'source_sha256': digest, 'resume': bool(existing)})
            if existing:
                work.select_material(existing.id)
                if not existing.analysis or not existing.analysis.overview_complete:
                    await work.analyze_current_material()
            else:
                await work.load_imported_material(imported, title=args.title,
                    source_language=LanguageEnum.ENGLISH, target_language=LanguageEnum.ENGLISH,
                    native_language=LanguageEnum.CHINESE, learner_level=ProficiencyLevel.B2)
            report['analysis'] = inspect_analysis(work.material)
            report['analysis']['overview_complete'] = work.material.analysis.overview_complete
            report['source_sha256'] = digest
        elif args.phase == 'chat':
            report['turns'] = []
            emit({'event': 'ready', 'material': work.material.title,
                  'messages': len(work.session.messages) if work.session else 0})
            while True:
                line = await asyncio.to_thread(sys.stdin.readline)
                if not line: break
                command = json.loads(line)
                action = command.get('action', 'turn')
                if action == 'quit': break
                if action == 'start':
                    result = await work.start_session(topic_id=command.get('topic_id'), custom_topic=command.get('custom_topic'))
                    emit({'opening': result.assistant_message.content, 'topic': result.session.topic.title})
                elif action == 'turn':
                    turn_started = perf_counter()
                    first = True
                    def on_delta(delta):
                        nonlocal first
                        if first:
                            first = False
                            emit({'event': 'first_text', 'elapsed_ms': round((perf_counter()-turn_started)*1000, 2)})
                    result = await work.send_message(command['message'], on_delta=on_delta)
                    metrics = {**result.timing.model_dump(), 'end_to_end_ms': round((perf_counter()-turn_started)*1000, 2),
                        'background_was_ready': bool(result.session.preparation and
                            result.session.preparation.based_on_message_count == len(result.session.messages)-2)}
                    report['turns'].append(metrics)
                    emit({'reply': result.assistant_message.content, 'timing': metrics})
                elif action == 'wait':
                    emit({'background': await wait_for_preparation(work)})
                elif action == 'state':
                    emit({'messages': len(work.session.messages) if work.session else 0,
                        'status': work.session.status if work.session else None, 'background': work.preparation_status})
                elif action == 'review':
                    result = await work.complete_session()
                    emit({'review': result.session.review.model_dump(mode='json'), 'review_items': len(result.review_items)})
                else:
                    raise ValueError('Unknown chat action')
        elif args.phase == 'export':
            material, analysis = work.material, work.material.analysis
            if not analysis:
                raise ValueError('No saved section notes to export')
            lines = [f'# {material.title}：预处理资料', '',
                f'完整导入 {len(material.content)} 字符；已整理 {len(analysis.chunks)} 段、{len(analysis.topics)} 个话题。',
                '以下为模型生成的讨论资料；候选回答是假设，人物叙述与评论者观点应结合原文判断。', '',
                '## 整书概要' if analysis.preparation_complete else '## 逐段概要（汇总待完成）', '', analysis.summary, '', '## 情节与结构', '']
            if not analysis.preparation_complete:
                lines[2:2] = ['**状态：各段资料已保存，整书汇总尚未完成。下面的概要为逐段笔记，不是已验证的整书概要。**', '']
            lines += [f'{i}. {text}' for i, text in enumerate(analysis.outline, 1)]
            lines += ['', '## 人物', '']
            lines += [f'- **{character.name}**：{character.description}' for character in analysis.characters]
            lines += ['', '## 讨论话题与预制回答', '']
            locations = {chunk.id: f'第 {i} 段（字符 {chunk.start_char}–{chunk.end_char}）'
                for i, chunk in enumerate(analysis.chunks, 1)}
            for i, topic in enumerate(analysis.topics, 1):
                lines += [f'### {i}. {topic.title}', '', topic.opening_question, '',
                    '来源段落：' + '、'.join(locations.get(key, '旧记录未关联段落') for key in topic.source_chunk_ids), '']
                for branch in topic.answer_branches:
                    lines += [f'**可能的读者想法：{branch.user_intent}**', '']
                    lines += [f'- {point}' for point in branch.response_points]
                    lines += ['', f'回应示例：{branch.suggested_reply}', '', f'可选追问：{branch.follow_up}', '']
            lines += ['## 分段索引', '']
            for i, chunk in enumerate(analysis.chunks, 1):
                lines += [f'### 段落 {i} · {chunk.start_char}–{chunk.end_char}', '',
                    chunk.summary, '']
            destination = args.data_dir / 'prepared_notes.md'
            destination.write_text('\n'.join(lines), encoding='utf-8')
            emit({'notes': str(destination), 'topics': len(analysis.topics), 'sections': len(analysis.chunks)})
        elif args.phase == 'topics':
            emit({'summary': work.material.analysis.summary, 'outline': work.material.analysis.outline,
                'characters': [c.model_dump(exclude={'source_excerpts'}) for c in work.material.analysis.characters],
                'topics': [{'id': t.id, 'title': t.title, 'opening': t.opening_question, 'branches': len(t.answer_branches)}
                    for t in work.material.analysis.topics]})
        elif args.phase == 'start':
            result = await work.start_session(topic_id=args.topic_id, custom_topic=args.custom_topic)
            emit({'opening': result.session.messages[-1].content, 'topic': result.session.topic.title})
            report['background'] = await wait_for_preparation(work)
        elif args.phase == 'turn':
            message = args.message_file.read_text(encoding='utf-8') if args.message_file else args.message
            if not message: raise ValueError('A message is required')
            result = await work.send_message(message)
            emit({'reply': result.session.messages[-1].content, 'timing': result.timing.model_dump()})
            report['timing'] = result.timing.model_dump()
            report['background'] = await wait_for_preparation(work)
            emit({'background': report['background']})
        elif args.phase == 'review':
            result = await work.complete_session()
            emit({'review': result.session.review.model_dump(mode='json'), 'review_items': len(result.review_items)})
            report['review_items'] = len(result.review_items)
        elif args.phase == 'status':
            emit({'materials': len(work.materials), 'material_title': work.material.title if work.material else None,
                'session_status': work.session.status if work.session else None,
                'messages': len(work.session.messages) if work.session else 0,
                'review_items': len(work.review_queue)})
        report['success'] = True
    except Exception as exc:
        report.update(success=False, error_type=type(exc).__name__)
        emit({'failure_type': type(exc).__name__, 'saved_sections': len(work.material.analysis.chunks)
            if work.material and work.material.analysis else 0})
        raise
    finally:
        report['elapsed_s'] = round(perf_counter() - started, 2)
        await work.aclose()
        report['requests'] = records
        report['observed_usage'] = {'input_tokens': sum(r.get('input_tokens', 0) for r in records),
            'output_tokens': sum(r.get('output_tokens', 0) for r in records),
            'cancelled_requests_usage_unknown': sum(r['status'] == 'cancelled_usage_unknown' for r in records)}
        report['preparation_diagnostics'] = provider.preparation_diagnostics
        filename = args.data_dir / f'{args.phase}-{datetime.now().strftime("%Y%m%d-%H%M%S-%f")}.json'
        filename.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        emit({'metadata_report': str(filename), 'success': report.get('success', False)})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--real', action='store_true')
    parser.add_argument('--phase', choices=['prepare', 'topics', 'start', 'turn', 'review', 'status', 'chat', 'export'], required=True)
    parser.add_argument('--material', type=Path)
    parser.add_argument('--title')
    parser.add_argument('--data-dir', type=Path, required=True)
    parser.add_argument('--topic-id')
    parser.add_argument('--custom-topic')
    parser.add_argument('--message')
    parser.add_argument('--message-file', type=Path)
    args = parser.parse_args()
    if args.phase == 'prepare' and not args.material: parser.error('--material is required for prepare')
    try:
        asyncio.run(run(args))
    except Exception as exc:
        emit({'error_type': type(exc).__name__, 'success': False})
        return 1
    return 0


if __name__ == '__main__':
    sys.stdin.reconfigure(encoding='utf-8')
    sys.stdout.reconfigure(encoding='utf-8')
    raise SystemExit(main())
