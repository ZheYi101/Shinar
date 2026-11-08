"""Real Qt clicks and model replies on a private copy of a prepared novel DB.

Run after validate_novel.py prepare; requires desktop/dev dependencies and explicit
real-service opt-in. Sources, screenshots and the copied DB stay in ignored build/.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sqlite3
import sys
from time import monotonic

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('QT_QUICK_BACKEND', 'software')
os.environ['SHINAR_KIRIGAMI_MODE'] = 'off'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--real', action='store_true')
    parser.add_argument('--data-dir', type=Path, required=True)
    parser.add_argument('--inspect-only', action='store_true', help='Read-only UI inspection; no model calls, permits incomplete preparation')
    args = parser.parse_args()
    from dotenv import load_dotenv
    load_dotenv(ROOT / '.env')
    if not args.real or os.getenv('RUN_REAL_AI_TESTS') != '1':
        parser.error('Requires --real and RUN_REAL_AI_TESTS=1')
    from PySide6.QtCore import QObject, QPointF, QSettings, Qt
    from PySide6.QtGui import QFontDatabase, QGuiApplication
    from PySide6.QtQuick import QQuickItem, QQuickWindow
    from PySide6.QtTest import QTest
    from shinar.application import LearningWorkbench
    from shinar.desktop.app import create_engine
    from shinar.desktop.preferences import DesktopPreferences
    from shinar.desktop.viewmodel import LearningViewModel
    from shinar.infrastructure import SQLiteStore
    from shinar.providers.openai_compatible import OpenAICompatibleLLMProvider
    from benchmark_prepared_dialogue import AuditClient

    output = args.data_dir / ('desktop-inspection' if args.inspect_only else 'desktop')
    if not (args.data_dir / 'novel.sqlite3').is_file():
        raise ValueError('Prepare the novel database first.')
    output.mkdir(parents=True, exist_ok=True)
    database = output / 'shinar.sqlite3'
    if database.exists() and not args.inspect_only:
        raise ValueError('Desktop validation copy already exists; choose a fresh data directory or inspect it before rerunning.')
    if not database.exists():
        with sqlite3.connect(args.data_dir / 'novel.sqlite3') as source, sqlite3.connect(database) as target:
            source.backup(target)
    app = QGuiApplication([])
    for name in ('msyh.ttc', 'msyhbd.ttc', 'YuGothR.ttc'):
        QFontDatabase.addApplicationFont(str(Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts' / name))
    records = []
    provider = OpenAICompatibleLLMProvider.from_env()
    for name, role in (('_reasoning_client', 'reasoning'), ('_dialogue_client', 'dialogue')):
        client = getattr(provider, name).model_copy(update={'max_retries': 0})
        setattr(provider, name, AuditClient(client, role, records, max_calls=6))
    work = LearningWorkbench(provider, event_store=SQLiteStore(database))
    assert work.material and work.material.analysis
    if not args.inspect_only: assert work.material.analysis.overview_complete
    prefs = DesktopPreferences(QSettings(str(output / 'preferences.ini'), QSettings.Format.IniFormat))
    for key, value in (('targetLanguage', 'english'), ('difficulty', 'B2'), ('themeMode', 'light')):
        prefs.setValue(key, value)
    vm = LearningViewModel(work, '真实 AI · 小说验收', preferences=prefs)
    engine = create_engine(vm, window_settings=QSettings(str(output / 'window.ini'), QSettings.Format.IniFormat))
    window = engine.rootObjects()[0]
    window.setWidth(1180)
    window.setHeight(900)
    report = {'material_title': work.material.title, 'source_chars': len(work.material.content), 'topics': len(vm.topics), 'requests': records}

    def until(predicate, seconds=180):
        deadline = monotonic() + seconds
        while not predicate() and monotonic() < deadline:
            QTest.qWait(20)
        assert predicate(), vm.errorMessage

    def item(name):
        pending = [window.contentItem()]
        while pending:
            obj = pending.pop()
            if obj.objectName() == name: return obj
            pending.extend(obj.childItems())
        raise AssertionError(name)

    def click(name, scroll=None):
        target = item(name)
        if scroll:
            flick = item(scroll).property('contentItem')
            for _ in range(4):
                y = target.mapToItem(flick, QPointF()).y() + flick.property('contentY')
                flick.setProperty('contentY', max(0, min(y-16, flick.property('contentHeight')-flick.height())))
                QTest.qWait(60)
        QTest.qWait(80)
        target = item(name)
        assert target.isVisible() and target.isEnabled(), name
        point = target.mapToScene(QPointF(target.width()/2, target.height()/2)).toPoint()
        assert 0 <= point.x() < window.width() and 0 <= point.y() < window.height(), name
        QTest.mouseClick(window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, point)
        QTest.qWait(30)

    try:
        QTest.qWait(300)
        window.grabWindow().save(str(output / 'materials.png'))
        if args.inspect_only:
            for width in (360, 600, 800, 1180, 1440):
                window.setWidth(width)
                QTest.qWait(200)
                assert vm.materialTitle == report['material_title'] and len(vm.topics) == report['topics']
                window.grabWindow().save(str(output / f'materials-{width}.png'))
            report.update(success=True, inspect_only=True, model_calls=0,
                preparation_complete=work.material.analysis.preparation_complete)
            print(json.dumps({'inspection_success': True, 'model_calls': 0, 'report': str(output / 'report.json')}, ensure_ascii=False), flush=True)
            return
        click('selectTopic0', 'materialScroll')
        click('startDiscussionButton', 'materialScroll')
        until(lambda: vm.sessionActive and not vm.busy)
        assert not vm.errorMessage, vm.errorMessage
        initial = len(vm.messages)
        report['turns'] = []
        for message in (
            "The prose made me notice how easily I was accepting Humbert's version. What detail most clearly pushes back against him?",
            "I mean the gap between what he says and what Dolores does. I don't want to confuse understanding his voice with forgiving him.",
        ):
            field = item('messageInput')
            field.forceActiveFocus()
            for character in message:
                modifiers = Qt.KeyboardModifier.ShiftModifier if character.isupper() else Qt.KeyboardModifier.NoModifier
                QTest.keyClick(window, Qt.Key(ord(character.upper())), modifiers)
            assert vm.draft == message
            click('sendMessageButton')
            until(lambda: not vm.busy)
            assert not vm.errorMessage, vm.errorMessage
            report['turns'].append(work.session.messages[-1].metadata.get('timing'))
            print(json.dumps({'reply': vm.messages[-1]['content'], 'timing': report['turns'][-1]}, ensure_ascii=False), flush=True)
        assert len(vm.messages) == initial+4 and vm.draft == ''
        window.grabWindow().save(str(output / 'conversation.png'))
        draft = 'A thought to preserve while changing pages.'
        item('messageInput').setProperty('text', draft)
        click('nav0')
        click('nav1')
        assert vm.draft == draft
        for width in (360, 600, 800, 1180, 1440):
            window.setWidth(width)
            QTest.qWait(200)
            assert vm.draft == draft
            assert item('sendMessageButton').isVisible()
            window.grabWindow().save(str(output / f'conversation-{width}.png'))
        window.setWidth(1180)
        click('finishDiscussionButton')
        until(lambda: not vm.busy, 500)
        assert not vm.sessionActive and vm.reviewSummary and not vm.errorMessage
        window.grabWindow().save(str(output / 'review.png'))
        report.update(success=True, confirmed_messages=len(vm.messages), review_summary_present=bool(vm.reviewSummary))
    finally:
        vm.close()
        report['worker_stopped'] = not vm._worker._thread or not vm._worker._thread.is_alive()
        window.close()
        engine.deleteLater()
        app.processEvents()
        (output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    restored = SQLiteStore(database)
    sessions = restored.list_sessions()
    assert sessions[0].status.value == 'completed' and len(sessions[0].messages) == report['confirmed_messages']
    restored.close()
    print(json.dumps({'success': True, 'report': str(output / 'report.json'), 'restart_verified': True}), flush=True)


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()
