"""Drive the actual desktop through Qt mouse/key events and inspect confirmed state.

Default uses a visible native Windows window and the normal application database.
JSON commands arrive on stdin; no command injects messages into the database.
Requires desktop/dev dependencies. Screenshots and operational metadata stay in build/.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import json
import os
from pathlib import Path
from queue import Queue, Empty
import re
import sys
from threading import Thread
from time import monotonic

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--real', action='store_true', help='Allow actual model calls; also requires RUN_REAL_AI_TESTS=1')
    parser.add_argument('--offscreen', action='store_true')
    parser.add_argument('--mock', action='store_true', help='Use an isolated offline provider')
    parser.add_argument('--settings-dir', type=Path, help='Keep Qt preferences/window state in this directory')
    parser.add_argument('--qt-dialogs', action='store_true')
    parser.add_argument('--target-language')
    parser.add_argument('--difficulty')
    parser.add_argument('--request-ledger', type=Path, help='Shared attempt ledger across real validation processes')
    parser.add_argument('--request-limit', type=int, default=100)
    parser.add_argument('--output', type=Path, default=ROOT / 'build' / 'native-session')
    args = parser.parse_args()
    os.environ['QT_QPA_PLATFORM'] = 'offscreen' if args.offscreen else 'windows'
    os.environ.setdefault('QT_QUICK_BACKEND', 'software')
    os.environ['LINGUALOOP_KIRIGAMI_MODE'] = 'off'
    from PySide6.QtCore import QObject, QPointF, Qt, QTimer, QSettings
    from PySide6.QtGui import QGuiApplication, QFontDatabase, QKeyEvent
    from PySide6.QtQuick import QQuickWindow
    from PySide6.QtTest import QTest
    from lingualoop.desktop.app import create_workbench, create_engine
    from lingualoop.desktop.viewmodel import LearningViewModel
    from lingualoop.desktop.preferences import DesktopPreferences
    from benchmark_prepared_dialogue import AuditClient

    if args.qt_dialogs:
        QGuiApplication.setAttribute(Qt.ApplicationAttribute.AA_DontUseNativeDialogs, True)
    app = QGuiApplication([])
    for name in ('msyh.ttc', 'msyhbd.ttc', 'YuGothR.ttc'):
        QFontDatabase.addApplicationFont(str(Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts' / name))
    args.output.mkdir(parents=True, exist_ok=True)
    if args.mock and args.real:
        parser.error("--mock and --real cannot be combined")
    if args.mock and not os.getenv("LINGUALOOP_DATA_DIR"):
        os.environ["LINGUALOOP_DATA_DIR"] = str(args.output / "mock-library")
    work = create_workbench(use_mock=args.mock)
    if args.real and os.getenv('RUN_REAL_AI_TESTS') != '1':
        raise SystemExit('--real requires RUN_REAL_AI_TESTS=1 in the local environment or .env')
    records = []
    from model_request_guard import ModelRequestGuard
    guard = ModelRequestGuard(args.request_ledger or args.output / 'request-guard.sqlite3', args.request_limit) if args.real else None
    network = []
    for role, http_client in getattr(work._provider, '_http_async_clients', {}).items():
        async def trace_request(request, request_role=role):
            item = {'request': len(network) + 1, 'role': request_role, 'tcp_connects': 0, 'tls_handshakes': 0}
            network.append(item)
            async def trace(name, info):
                # Never retain info: it may include headers or transport objects.
                if name == 'connection.connect_tcp.started': item['tcp_connects'] += 1
                elif name in {'connection.start_tls.started', 'proxy.start_tls.started'}: item['tls_handshakes'] += 1
            request.extensions['trace'] = trace
        http_client.event_hooks['request'].append(trace_request)
    class ProbeClient(AuditClient):
        def begin(self, streaming):
            if not args.real:
                raise RuntimeError('此探针当前只读；真实调用需要 --real 和 RUN_REAL_AI_TESTS=1。')
            guard.reserve(self.role)
            return super().begin(streaming)
    for name, role in (('_reasoning_client', 'reasoning'), ('_dialogue_client', 'dialogue')):
        client = getattr(work._provider, name, None)
        if client:
            client = client.model_copy(update={'max_retries': 0})
            setattr(work._provider, name, ProbeClient(client, role, records, max_calls=args.request_limit))
    if args.settings_dir:
        args.settings_dir.mkdir(parents=True, exist_ok=True)
    prefs = DesktopPreferences(QSettings(str(args.settings_dir / "preferences.ini"), QSettings.Format.IniFormat)) if args.settings_dir else DesktopPreferences()
    if args.target_language: prefs.setValue('targetLanguage', args.target_language)
    if args.difficulty: prefs.setValue('difficulty', args.difficulty)
    vm = LearningViewModel(work, '真实 AI', preferences=prefs)
    # This probe validates text; no speech request is made.
    vm._stt = vm._tts = None
    engine_kwargs = {}
    if args.settings_dir:
        from lingualoop.desktop.speech_library import SpeechLibraryViewModel
        engine_kwargs = {"window_settings": QSettings(str(args.settings_dir / "window.ini"), QSettings.Format.IniFormat),
                         "speech_library": SpeechLibraryViewModel(root=args.settings_dir / "speech")}
    engine = create_engine(vm, **engine_kwargs)
    window = engine.rootObjects()[0]
    if args.qt_dialogs:
        dialog = window.findChild(QObject, 'materialFileDialog')
        dialog.setProperty('popupType', 0)  # Public Popup.Item: same visible native app, inline Qt file picker.
        meta = dialog.metaObject()
        for index in range(meta.enumeratorCount()):
            enum = meta.enumerator(index)
            value, found = enum.keyToValue('DontUseNativeDialog')
            if found:
                dialog.setProperty('options', value)
                break
    window.setWidth(1440)
    window.setHeight(960)
    window.showNormal()
    window.requestActivate()
    queue = Queue()
    report = {'started': datetime.now().isoformat(), 'platform': app.platformName(),
              'real_calls_enabled': args.real,
              'network': network,
              'database': str(work._event_store.path), 'requests': records, 'commands': [], 'ui_turns': []}
    active_turn = {}
    processing = False
    scaffold = next(obj for obj in window.findChildren(QObject) if obj.metaObject().indexOfProperty('currentPage') >= 0)
    window_refs = [window]
    item_refs = {}

    def emit(data):
        (args.output / 'last-event.json').write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(data, ensure_ascii=False), flush=True)

    def visual_items():
        windows = [window] if args.qt_dialogs else app.allWindows()
        for native_window in windows:
            if native_window not in window_refs: window_refs.append(native_window)
        pending = [w.contentItem() for w in windows if w.isVisible() and hasattr(w, 'contentItem')]
        for obj in pending: item_refs[id(obj)] = obj
        while pending:
            obj = pending.pop()
            from shiboken6 import isValid
            if not isValid(obj): continue
            children = obj.childItems()
            for child in children: item_refs[id(child)] = child
            yield obj
            pending.extend(children)

    def find(name):
        return next(obj for obj in visual_items() if obj.objectName() == name)

    def click(target, scroll=None):
        target_window = target.window() or window
        name = target.objectName()
        current = lambda: find(name) if name else target
        if scroll:
            view = find(scroll)
            flick = view.property('contentItem')
            for _ in range(5):
                target = current()
                y = target.mapToItem(flick, QPointF()).y() + flick.property('contentY')
                flick.setProperty('contentY', max(0, min(y-16, flick.property('contentHeight')-flick.height())))
                QTest.qWait(60)
                target = current()
                point = target.mapToItem(view, QPointF(target.width()/2, target.height()/2))
                if 0 <= point.x() < view.width() and 0 <= point.y() < view.height():
                    break
            assert 0 <= point.x() < view.width() and 0 <= point.y() < view.height(), 'Control outside viewport'
        previous, stable = None, 0
        for _ in range(12):
            target = current()
            center = target.mapToScene(QPointF(target.width()/2, target.height()/2))
            geometry = (center.x(), center.y(), target.width(), target.height())
            stable = stable + 1 if geometry == previous else 0
            if stable >= 2: break
            previous = geometry
            QTest.qWait(20)
        assert stable >= 2, 'Control geometry did not settle'
        assert target.isVisible() and target.isEnabled(), 'Control unavailable'
        point = target.mapToScene(QPointF(target.width()/2, target.height()/2)).toPoint()
        assert 0 <= point.x() < target_window.width() and 0 <= point.y() < target_window.height(), 'Control outside window'
        QTest.mouseMove(target_window, point)
        QTest.qWait(20)
        target = current()
        point = target.mapToScene(QPointF(target.width()/2, target.height()/2)).toPoint()
        QTest.mousePress(target_window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, point)
        QTest.qWait(20)
        down = target.property('down')
        QTest.mouseRelease(target_window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, point)
        assert down is not False, 'Control did not receive the mouse press'
        QTest.qWait(100)

    def state():
        session = work.session
        knowledge = work.material.analysis.knowledge if work.material and work.material.analysis else None
        return {'busy': vm.busy, 'error': vm.errorMessage, 'material': vm.materialTitle,
            'knowledge': {'status': knowledge.status, 'units': len(knowledge.units),
                'completed': len(knowledge.completed_unit_ids), 'excluded': len(knowledge.excluded_unit_ids),
                'notes': len(knowledge.notes), 'errors': knowledge.errors, 'scope_end': knowledge.scope_end} if knowledge else None,
            'request_attempts': guard.count() if guard else 0,
            'window': {'width': window.width(), 'height': window.height(),
                'content_width': window.contentItem().width(), 'scaffold_width': scaffold.width(),
                'compact': scaffold.property('compact'), 'exposed': window.isExposed(),
                'state': str(window.windowState())},
            'materials': len(vm.materials), 'prepared': vm.materialPrepared,
            'preparation': vm.materialPreparation, 'topics': len(vm.topics), 'page': scaffold.property('currentPage'),
            'session_id': session.id if session else None, 'active': vm.sessionActive,
            'messages': len(vm.messages), 'histories': len(vm.sessionHistory), 'draft': vm.draft,
            'last_assistant': next((m['content'] for m in reversed(vm.messages) if m['role'] == 'assistant'), None),
            'timing': session.messages[-1].metadata.get('timing') if session and session.messages else None,
            'background': work.preparation_status}

    def type_text(target, text, replace=False):
        assert target.isEnabled() and target.isVisible(), 'Editor unavailable'
        target_window = target.window() or window
        target.forceActiveFocus()
        if replace: QTest.keyClick(target_window, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
        # Committed Unicode key events exercise the real editor and its bindings.
        for character in text:
            app.sendEvent(target_window, QKeyEvent(QKeyEvent.Type.KeyPress, 0, Qt.KeyboardModifier.NoModifier, character))
            app.sendEvent(target_window, QKeyEvent(QKeyEvent.Type.KeyRelease, 0, Qt.KeyboardModifier.NoModifier, character))
        QTest.qWait(40)

    def handle():
        nonlocal processing
        if processing:
            return
        try:
            command = queue.get_nowait()
        except Empty:
            return
        processing = True
        try:
            action = command.get('action')
            if action != 'quit' and window.windowState() == Qt.WindowState.WindowMinimized:
                window.showNormal()
                window.requestActivate()
                QTest.qWait(100)
            report['commands'].append({'action': action, 'at': datetime.now().isoformat()})
            if action == 'state': emit(state())
            elif action == 'click':
                click(find(command['name']), command.get('scroll'))
                emit(state())
            elif action == 'click_text':
                target = next(obj for obj in visual_items() if obj.isVisible() and obj.isEnabled() and (
                    (obj.property('text') == command['text'] and obj.property('down') is not None)
                    or obj.property('currentText') == command['text']))
                click(target, command.get('scroll'))
                emit(state())
            elif action == 'type':
                focused = app.focusWindow() or window
                target = find(command['name']) if command.get('name') else focused.activeFocusItem()
                assert target is not None
                type_text(target, command['text'], command.get('replace', False))
                emit({'typed': True, 'focus_type': target.metaObject().className(), 'state': state()})
            elif action == 'key':
                key = getattr(Qt.Key, 'Key_' + command['key'])
                modifier = Qt.KeyboardModifier.ControlModifier if command.get('control') else Qt.KeyboardModifier.NoModifier
                if command['key'] in {'Return', 'Enter'} and command.get('control') and vm.sessionActive and vm.draft.strip() and not vm.busy:
                    active_turn.update(started=monotonic(), session_id=work.session.id)
                QTest.keyClick(app.focusWindow() or window, key, modifier)
                QTest.qWait(100)
                emit(state())
            elif action == 'items':
                result = []
                for obj in visual_items():
                    if not obj.isVisible(): continue
                    cls = obj.metaObject().className()
                    if obj.objectName() or 'TextField' in cls or 'Button' in cls:
                        point = obj.mapToScene(QPointF()).toPoint()
                        owner = obj.window() or window
                        if 0 <= point.x() < owner.width() and 0 <= point.y() < owner.height():
                            result.append({'name': obj.objectName(), 'class': cls, 'text': str(obj.property('text') or '')[:100],
                                'x': point.x(), 'y': point.y(), 'enabled': obj.isEnabled(), 'focus': obj.hasActiveFocus()})
                emit({'items': result[:250]})
            elif action == 'windows':
                emit({'windows': [{'title': w.title(), 'class': w.metaObject().className(), 'visible': w.isVisible()}
                    for w in app.allWindows()]})
            elif action == 'snapshot':
                QTest.qWait(250)  # Let the 200 ms theme transition settle before visual inspection.
                name = re.sub(r'[^a-zA-Z0-9_-]', '_', command.get('name', 'window'))
                path = args.output / (name + '.png')
                assert window.grabWindow().save(str(path))
                emit({'snapshot': str(path), 'state': state()})
            elif action == 'resize':
                window.showNormal()
                window.setWidth(command['width'])
                window.setHeight(command.get('height', 900))
                emit(state())
            elif action == 'quit':
                app.quit()
            else:
                raise ValueError('Unknown command')
        except Exception as exc:
            import traceback
            emit({'command_error': type(exc).__name__, 'action': command.get('action'),
                'message': str(exc)[:250], 'trace': traceback.format_exc(limit=4)})
        finally:
            processing = False

    def reader():
        for line in sys.stdin:
            try: queue.put(json.loads(line))
            except ValueError: emit({'command_error': 'InvalidJSON'})

    Thread(target=reader, daemon=True).start()
    timer = QTimer()
    timer.timeout.connect(handle)
    timer.start(30)
    def first_text():
        if active_turn and vm.streamingText and 'first_ui_text_ms' not in active_turn:
            active_turn['first_ui_text_ms'] = round((monotonic()-active_turn['started'])*1000, 2)
    def frame_presented():
        if active_turn and 'first_ui_text_ms' in active_turn and 'first_frame_after_text_ms' not in active_turn:
            active_turn['first_frame_after_text_ms'] = round((monotonic()-active_turn['started'])*1000, 2)
    def operation_done():
        if active_turn:
            metrics = {key: value for key, value in active_turn.items() if key != 'started'}
            metrics['end_to_end_ms'] = round((monotonic()-active_turn['started'])*1000, 2)
            metrics['success'] = not bool(vm.errorMessage)
            metrics['model_timing'] = work.session.messages[-1].metadata.get('timing') if work.session and work.session.messages else None
            report['ui_turns'].append(metrics)
            emit({'ui_turn': metrics})
            active_turn.clear()
        emit({'operation_state': state()})
    vm.uiChanged.connect(first_text)
    window.frameSwapped.connect(frame_presented, Qt.ConnectionType.QueuedConnection)
    vm.busyChanged.connect(lambda: QTimer.singleShot(0, operation_done) if not vm.busy else None)
    QTimer.singleShot(400, lambda: emit({'ready': state(), 'database': report['database']}))
    try:
        app.exec()
    finally:
        vm.close()
        report['worker_stopped'] = not vm._worker._thread or not vm._worker._thread.is_alive()
        from shiboken6 import isValid
        report['final_state'] = state() if isValid(scaffold) else {'window_closed': True, 'messages': len(vm.messages)}
        (args.output / ('run-' + datetime.now().strftime('%Y%m%d-%H%M%S') + '.json')).write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    sys.stdin.reconfigure(encoding='utf-8')
    sys.stdout.reconfigure(encoding='utf-8')
    main()
