"""PyQt test launched from PowerFactory, with automatic installation.

Run the COMPLETE file as a ComPython. PowerFactory only runs the standard
library launcher. Every invocation starts a fresh Python process for Qt;
closing the window ends that process. No Qt module is imported into the
PowerFactory process, including during the automatic installation.

Missing PyQt is downloaded into ~/GridLens/python on the first run and reused
later. Downloads require a compatible Python with pip and Internet access.
Set INSTALLER_PYTHON to that python.exe if automatic discovery fails.
AUTO_INSTALL_PYQT=False disables downloads. QT_BINDING selects auto/PyQt6/PyQt5.

Only active project/study names are read in PowerFactory. They are sent to the
GUI as JSON; the GUI does not connect to the PowerFactory API. No calculation
or model change is performed. Per-run logs are saved in ~/GridLens/logs.

Qt lifecycle: https://doc.qt.io/qt-6/qapplication.html
"""

from __future__ import annotations

import importlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import struct
import subprocess
import sys
import sysconfig
import tempfile
import threading

QT_BINDING = 'auto'
AUTO_INSTALL_PYQT = True
INSTALLER_PYTHON = ''  # Optional absolute path to a matching python.exe.
DEPENDENCY_DIR = ''  # Default: ~/GridLens/python.
LOG_DIR = ''  # Default: ~/GridLens/logs.

def python_identity():
    """The ABI and architecture the downloaded extension modules must match."""
    return [sys.implementation.cache_tag, sysconfig.get_platform(),
            platform.machine().lower(), struct.calcsize('P')]


def run_python(executable, arguments, timeout=30):
    """Run a real Python executable, with bounded waits and no inherited Python path."""
    options = {'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {}
    return subprocess.run([str(executable), '-I', *arguments], capture_output=True, text=True,
                          encoding='utf-8', errors='replace', timeout=timeout, **options)


def installer_python(require_pip=False):
    """Never run PowerFactory.exe as if it were a Python command-line interpreter."""
    if INSTALLER_PYTHON:
        candidates = [Path(INSTALLER_PYTHON).expanduser()]
    else:
        candidates = [Path(sys.executable)]
        for prefix in (sys.prefix, sys.base_prefix, sysconfig.get_path('stdlib')):
            if prefix:
                folder = Path(prefix)
                candidates.extend((folder / 'python.exe', folder / 'bin' / 'python3',
                                   folder.parent / 'python.exe'))
        located = shutil.which('python{}.{}'.format(*sys.version_info[:2]))
        if located:
            candidates.append(Path(located))
    probe = ('import importlib.util, json, platform, struct, sys, sysconfig; '
             'print(json.dumps([[sys.implementation.cache_tag, sysconfig.get_platform(), '
             'platform.machine().lower(), struct.calcsize("P")], '
             'importlib.util.find_spec("pip") is not None]))')
    checked = set()
    for path in candidates:
        if str(path) in checked or not re.fullmatch(r'python(?:w)?(?:\d+(?:\.\d+)?)?(?:\.exe)?', path.name, re.I):
            continue
        checked.add(str(path))
        if not path.is_file():
            continue
        try:
            result = run_python(path, ['-c', probe])
            identity, has_pip = json.loads(result.stdout) if result.returncode == 0 else (None, False)
        except (OSError, ValueError, subprocess.TimeoutExpired):
            continue
        if identity == python_identity() and (has_pip or not require_pip):
            return path
    raise RuntimeError('Kein passender Python-Interpreter gefunden. INSTALLER_PYTHON auf die '
                       'python.exe der in PowerFactory verwendeten Python-Version setzen '
                       '(Python {}, {} Bit). sys.executable={} kann in PowerFactory auf die '
                       'Host-Anwendung zeigen.'.format(platform.python_version(), struct.calcsize('P') * 8,
                                                       sys.executable))


def powerfactory_context():
    """The current PowerFactory application and a read-only context description."""
    try:
        powerfactory = importlib.import_module('powerfactory')
    except ModuleNotFoundError as exc:
        if exc.name == 'powerfactory':
            return None, 'Standalone · PowerFactory-Modul nicht verfügbar'
        raise
    get_application = getattr(powerfactory, 'GetApplication', None)
    if not callable(get_application):
        # A checkout may contain a directory named powerfactory, which Python
        # can import as a namespace package even without the PowerFactory API.
        return None, 'Standalone · Paket powerfactory enthält keine PowerFactory-API'
    app = get_application()
    if app is None:
        return None, 'Keine aktive PowerFactory-Verbindung'
    project, study = app.GetActiveProject(), app.GetActiveStudyCase()
    return app, 'PowerFactory verbunden\nProjekt: {}\nStudienfall: {}'.format(
        project.loc_name if project is not None else 'keines',
        study.loc_name if study is not None else 'keiner')


def log(app, text, error=False):
    message = '[PYQT-TEST] ' + text
    if app is not None:
        printer = getattr(app, 'PrintError' if error else 'PrintPlain', None)
        if callable(printer):
            printer(message)
            return
    print(message, file=sys.stderr if error else sys.stdout, flush=True)


def child_environment():
    """Do not inherit the host's Qt plugin paths or Python startup settings."""
    environment = dict(os.environ)
    for key in list(environment):
        if key.startswith('QT_') or key in ('PYTHONPATH', 'PYTHONHOME', 'PYTHONSTARTUP',
                                           'DYLD_LIBRARY_PATH', 'DYLD_FRAMEWORK_PATH', 'LD_LIBRARY_PATH'):
            environment.pop(key)
    environment['PYTHONIOENCODING'] = 'utf-8'
    if os.name == 'nt' and not re.fullmatch(r'python(?:w)?(?:\d+(?:\.\d+)?)?(?:\.exe)?', Path(sys.executable).name, re.I):
        host_folder = os.path.normcase(os.path.dirname(sys.executable))
        environment['PATH'] = os.pathsep.join(part for part in environment.get('PATH', '').split(os.pathsep)
                                             if os.path.normcase(os.path.normpath(part)) != host_folder)
    return environment


def launch_gui(context, app=None):
    if QT_BINDING not in ('auto', 'PyQt6', 'PyQt5'):
        raise RuntimeError('QT_BINDING muss auto, PyQt6 oder PyQt5 sein.')
    executable = installer_python()
    folder = Path(LOG_DIR).expanduser() if LOG_DIR else Path.home() / 'GridLens' / 'logs'
    folder.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(prefix='PyQtTest-', suffix='.log', dir=str(folder), delete=False) as handle:
        log_path = Path(handle.name)
    log(app, 'Starte PyQt in einem eigenen Prozess mit {}. Protokoll: {}'.format(executable, log_path))
    log(app, 'Beim ersten Start wird fehlendes PyQt automatisch installiert. Zum Fortsetzen das GUI-Fenster schließen.')
    options = {'binding': QT_BINDING, 'auto_install': AUTO_INSTALL_PYQT,
               'dependency_dir': DEPENDENCY_DIR, 'context': context}
    with tempfile.TemporaryDirectory(prefix='gridlens-pyqt-') as temporary:
        script = Path(temporary) / 'gui.py'
        config = Path(temporary) / 'context.json'
        script.write_text(CHILD_SOURCE, encoding='utf-8')
        config.write_text(json.dumps(options, ensure_ascii=False), encoding='utf-8')
        flags = {'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {}
        with log_path.open('w', encoding='utf-8') as output:
            process = subprocess.Popen([str(executable), '-I', '-u', '-X', 'faulthandler',
                                        str(script), str(config)], stdout=output, stderr=subprocess.STDOUT,
                                       env=child_environment(), cwd=temporary, **flags)
            returncode = process.wait()
    if returncode != 0:
        tail = log_path.read_text(encoding='utf-8', errors='replace')[-6000:]
        raise RuntimeError('Der separate PyQt-Prozess wurde mit Code {} (0x{:08X}) beendet. '
                           'Protokoll: {}\n{}'.format(returncode, returncode & 0xffffffff, log_path, tail))
    log(app, 'PyQt-Prozess beendet. PowerFactory kann weiterarbeiten. Protokoll: {}'.format(log_path))
    return log_path


def main():
    app = None
    try:
        app, context = powerfactory_context()
        return launch_gui(context, app)
    except Exception as exc:
        log(app, str(exc), error=True)
        raise


# Kept inline so the complete file also works when pasted into a ComPython.
# This source is written to a temporary file and executed ONLY by the child.
CHILD_SOURCE = r'''
from __future__ import annotations

import importlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import struct
import subprocess
import sys
import sysconfig
import tempfile
import threading

QT_BINDING = 'auto'
AUTO_INSTALL_PYQT = True
DEPENDENCY_DIR = ''
_qt_app = None

def python_identity():
    """The ABI and architecture the downloaded extension modules must match."""
    return [sys.implementation.cache_tag, sysconfig.get_platform(),
            platform.machine().lower(), struct.calcsize('P')]


def dependency_folder(binding):
    root = Path(DEPENDENCY_DIR).expanduser() if DEPENDENCY_DIR else Path.home() / 'GridLens' / 'python'
    identity = '-'.join(str(value) for value in python_identity())
    return root / re.sub(r'[^A-Za-z0-9_.-]', '_', identity) / binding


def run_python(executable, arguments, timeout=30):
    """Run a real Python executable, with bounded waits and no inherited Python path."""
    options = {'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {}
    return subprocess.run([str(executable), '-I', *arguments], capture_output=True, text=True,
                          encoding='utf-8', errors='replace', timeout=timeout, **options)


def ensure_pyqt(binding, report):
    """Stage and validate a wheel installation before loading it into the GUI process."""
    target = dependency_folder(binding)
    marker = target / '.gridlens-installed.json'
    if marker.is_file():
        try:
            if json.loads(marker.read_text(encoding='utf-8')) == python_identity():
                report('{} aus {} wiederverwenden.'.format(binding, target))
                return target
        except (OSError, ValueError):
            pass
    if target.exists():
        raise RuntimeError('Die lokale PyQt-Installation {} ist unvollständig. Diesen Ordner prüfen '
                           'oder DEPENDENCY_DIR auf einen anderen Ordner setzen.'.format(target))
    executable = Path(sys.executable)
    report('{} fehlt. Installiere mit {} nach {}. Der erste Download kann einige Minuten dauern.'
           .format(binding, executable, target))
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.pyqt-install-', dir=str(target.parent)) as temporary:
        staged = Path(temporary) / 'packages'
        requirement = 'PyQt6<7' if binding == 'PyQt6' else 'PyQt5<6'
        try:
            result = run_python(executable, ['-m', 'pip', '--disable-pip-version-check', 'install',
                                            '--no-input', '--only-binary=:all:', '--timeout', '30',
                                            '--retries', '1', '--target', str(staged), requirement], timeout=600)
            if result.returncode != 0:
                raise RuntimeError('PyQt-Installation fehlgeschlagen. Internet/Proxy und passende Wheels prüfen.\n' +
                                   (result.stdout + result.stderr)[-4000:])
            check = run_python(executable, ['-c', 'import importlib, sys; sys.path.insert(0, sys.argv[1]); '
                                            'importlib.import_module(sys.argv[2] + ".QtWidgets")', str(staged), binding])
            if check.returncode != 0:
                raise RuntimeError('Die installierten Qt-Module konnten nicht geladen werden:\n' + check.stderr[-4000:])
            (staged / marker.name).write_text(json.dumps(python_identity()), encoding='utf-8')
            os.rename(str(staged), str(target))
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError('Zeitlimit bei der PyQt-Installation überschritten. Internet/Proxy prüfen.') from exc
    report('{} installiert. Das Testfenster wird jetzt gestartet.'.format(binding))
    return target


def load_qt(allow_install=True, report=None):
    """Load one binding only; avoid mixing PyQt/PySide or different Qt majors."""
    if QT_BINDING not in ('auto', 'PyQt6', 'PyQt5'):
        raise RuntimeError('QT_BINDING muss auto, PyQt6 oder PyQt5 sein.')
    loaded = {name for name in ('PyQt6', 'PyQt5', 'PySide6', 'PySide2')
              if any(key == name or key.startswith(name + '.') for key in sys.modules)}
    if loaded & {'PySide6', 'PySide2'} or len(loaded) > 1:
        raise RuntimeError('Bereits geladene Qt-Bindings: {}. PyQt bitte in einer frischen '
                           'PowerFactory-Sitzung testen.'.format(', '.join(sorted(loaded))))
    if loaded and QT_BINDING != 'auto' and QT_BINDING not in loaded:
        raise RuntimeError('{} ist bereits geladen; QT_BINDING={} würde Qt-Versionen mischen.'
                           .format(next(iter(loaded)), QT_BINDING))
    candidates = sorted(loaded) if loaded else (['PyQt6', 'PyQt5'] if QT_BINDING == 'auto' else [QT_BINDING])
    for name in candidates:
        try:
            importlib.import_module(name)
        except ModuleNotFoundError as exc:
            if exc.name != name:
                raise RuntimeError('{} ist installiert, aber eine Abhängigkeit fehlt: {}'
                                   .format(name, exc)) from exc
            continue
        try:
            core = importlib.import_module(name + '.QtCore')
            widgets = importlib.import_module(name + '.QtWidgets')
        except (ImportError, OSError) as exc:
            raise RuntimeError('{} konnte nicht geladen werden: {}. Python-Version, '
                               'Architektur und Qt-/DLL-Installation prüfen.'.format(name, exc)) from exc
        return name, core, widgets
    if allow_install and AUTO_INSTALL_PYQT:
        binding = 'PyQt6' if QT_BINDING == 'auto' else QT_BINDING
        folder = str(ensure_pyqt(binding, report or print))
        if folder not in sys.path:
            sys.path.insert(0, folder)
        importlib.invalidate_caches()
        return load_qt(allow_install=False, report=report)
    raise RuntimeError('PyQt6/PyQt5 wurde nicht gefunden (Auswahl: {}). PyQt in der von PowerFactory '
                       'verwendeten Python-Umgebung installieren. Python: {}; Umgebung: {}'
                       .format(QT_BINDING, platform.python_version(), sys.prefix))


def application(core, widgets):
    """Keep the QApplication alive, and create widgets only on its GUI thread."""
    global _qt_app
    app = widgets.QApplication.instance()
    if app is None:
        if threading.current_thread() is not threading.main_thread():
            raise RuntimeError('PyQt benötigt den GUI-Hauptthread. Den ComPython direkt '
                               'aus der PowerFactory-Oberfläche starten.')
        app = widgets.QApplication(['GridLens-PyQt-Test'])
    if not isinstance(app, widgets.QApplication):
        raise RuntimeError('Die vorhandene Qt-Anwendung unterstützt keine Widgets.')
    if core.QThread.currentThread() != app.thread():
        raise RuntimeError('Der ComPython läuft außerhalb des Qt-GUI-Threads. '
                           'Den Test direkt aus der PowerFactory-Oberfläche starten.')
    _qt_app = app
    return app


def build_dialog(core, widgets, version, context, app=None):
    dialog = widgets.QDialog()
    dialog.setObjectName('GridLensPyQtTest')
    dialog.setWindowTitle('GridLens · PyQt-Test für PowerFactory')
    dialog.resize(1080, 720)
    dialog.setMinimumSize(840, 560)
    attribute = getattr(core.Qt, 'WidgetAttribute', core.Qt).WA_QuitOnClose
    dialog.setAttribute(attribute, False)
    dialog.setStyleSheet("""
        QDialog#GridLensPyQtTest { background: #101827; }
        QWidget { color: #e7edf7; font-family: "Segoe UI"; font-size: 13px; }
        QFrame#sidebar { background: #172236; border-radius: 12px; }
        QFrame#card { background: #1e2d45; border-radius: 12px; }
        QLabel#title { font-size: 25px; font-weight: bold; }
        QLabel#muted { color: #a4b3c9; }
        QLabel#success { color: #72d8a5; }
        QPushButton { background: #253650; border: 0; border-radius: 6px; padding: 12px 16px; }
        QPushButton:hover { background: #324967; }
        QPushButton:focus { border: 1px solid #91baff; }
        QPushButton#primary, QPushButton:checked { background: #3478ed; }
        QLineEdit, QComboBox { background: #172236; border: 1px solid #435676; padding: 8px; }
        QComboBox QAbstractItemView { background: #172236; selection-background-color: #3478ed; }
        QCheckBox { spacing: 8px; }
        QTableWidget { background: #172236; alternate-background-color: #1e2d45; gridline-color: #435676; }
        QHeaderView::section { background: #253650; color: #e7edf7; padding: 8px; border: 0; }
    """)
    layout = widgets.QHBoxLayout(dialog)
    layout.setContentsMargins(18, 18, 18, 18)
    layout.setSpacing(24)
    sidebar = widgets.QFrame()
    sidebar.setObjectName('sidebar')
    sidebar.setFixedWidth(205)
    navigation = widgets.QVBoxLayout(sidebar)
    brand = widgets.QLabel('GRIDLENS\nPyQt-Kompatibilität')
    navigation.addWidget(brand)
    navigation.addSpacing(24)
    layout.addWidget(sidebar)
    content = widgets.QVBoxLayout()
    content.setSpacing(16)
    layout.addLayout(content, 1)
    title = widgets.QLabel()
    title.setObjectName('title')
    content.addWidget(title)
    subtitle = widgets.QLabel(version)
    subtitle.setWordWrap(True)
    subtitle.setObjectName('muted')
    content.addWidget(subtitle)
    stack = widgets.QStackedWidget()
    stack.setObjectName('pages')
    content.addWidget(stack, 1)
    buttons = []
    group = widgets.QButtonGroup(dialog)
    group.setExclusive(True)

    def page(name):
        frame = widgets.QWidget()
        body = widgets.QVBoxLayout(frame)
        body.setSpacing(16)
        index = stack.addWidget(frame)
        button = widgets.QPushButton(name)
        button.setCheckable(True)
        button.setAutoDefault(False)
        group.addButton(button)
        navigation.addWidget(button)
        buttons.append(button)

        def show_page(_checked=False):
            stack.setCurrentIndex(index)
            title.setText(name)
        button.clicked.connect(show_page)
        return body

    home = page('Übersicht')
    card = widgets.QFrame()
    card.setObjectName('card')
    card_layout = widgets.QVBoxLayout(card)
    card_layout.setContentsMargins(20, 20, 20, 20)
    card_layout.addWidget(widgets.QLabel('GUI-Kompatibilität · Qt Widgets'))
    timer_label = widgets.QLabel('Ereignisschleife: wartet auf Timer …')
    timer_label.setObjectName('heartbeat')
    card_layout.addWidget(timer_label)
    home.addWidget(card)
    home.addWidget(widgets.QLabel('Name des Testfalls'))
    name = widgets.QLineEdit('Testfall 2030')
    name.setObjectName('caseName')
    home.addWidget(name)
    checks = widgets.QHBoxLayout()
    n0, n1 = widgets.QCheckBox('n-0'), widgets.QCheckBox('n-1')
    n0.setObjectName('n0')
    n1.setObjectName('n1')
    for check in (n0, n1):
        check.setChecked(True)
        checks.addWidget(check)
    checks.addStretch()
    home.addLayout(checks)
    test = widgets.QPushButton('Oberfläche testen')
    test.setObjectName('primary')
    test.setAutoDefault(False)

    def test_button(_checked=False):
        text = 'Testfall: {}\nn-0: {}\nn-1: {}\n\nPyQt-Signal empfangen. Keine Berechnung ausgeführt.'.format(
            name.text(), n0.isChecked(), n1.isChecked())
        log(app, text)
        widgets.QMessageBox.information(dialog, 'GridLens PyQt-Test erfolgreich', text)
    test.clicked.connect(test_button)
    home.addWidget(test)
    home.addStretch()

    cases = page('Planungsfälle')
    cases.addWidget(widgets.QLabel('Beispiel-Tabelle · keine echten Netzdaten'))
    table = widgets.QTableWidget(3, 3)
    table.setObjectName('caseTable')
    table.setHorizontalHeaderLabels(['Planungsfall', 'Status', 'Bewertung'])
    table.verticalHeader().hide()
    table.setAlternatingRowColors(True)
    view = widgets.QAbstractItemView
    table.setEditTriggers(getattr(view, 'EditTrigger', view).NoEditTriggers)
    for row, values in enumerate([('Referenz', 'Bereit', 'n-0'),
                                  ('Kabeltausch Nord', 'Entwurf', 'n-1'),
                                  ('Wartung Trafo 2', 'Entwurf', "(n-1)'")]):
        for column, value in enumerate(values):
            table.setItem(row, column, widgets.QTableWidgetItem(value))
    table.horizontalHeader().setStretchLastSection(True)
    table.resizeColumnsToContents()
    cases.addWidget(table)

    network = page('Netzauswahl')
    network.addWidget(widgets.QLabel('Beispiel-Netzauswahl'))
    grids = widgets.QComboBox()
    grids.setObjectName('gridChoice')
    grids.addItems(['Gesamtes Netz', 'Netz Nord', 'Netz Süd'])
    network.addWidget(grids)
    note = widgets.QLabel('Nur Demo-Werte. Es werden keine PowerFactory-Netze gelesen.')
    note.setWordWrap(True)
    network.addWidget(note)
    network.addStretch()

    settings = page('Einstellungen')
    details = widgets.QLabel('{}\n\n{}\n\nPython {} · {}\nInterpreter: {}\nUmgebung: {}'.format(
        version, context, platform.python_version(), platform.machine(), sys.executable, sys.prefix))
    details.setWordWrap(True)
    settings.addWidget(details)
    settings.addStretch()
    navigation.addStretch()
    safe = widgets.QLabel('NUR TEST\nKEINE BERECHNUNG')
    safe.setObjectName('success')
    navigation.addWidget(safe)
    close = widgets.QPushButton('Fenster schließen')
    close.setAutoDefault(False)
    close.clicked.connect(dialog.reject)
    content.addWidget(close)
    buttons[0].click()
    timer = core.QTimer(dialog)
    timer.setInterval(1000)
    ticks = [0]

    def tick():
        ticks[0] += 1
        timer_label.setText('Ereignisschleife aktiv · {} s'.format(ticks[0]))
    timer.timeout.connect(tick)
    timer.start()
    dialog.finished.connect(timer.stop)
    return dialog


def log(app, text, error=False):
    print('[PYQT-TEST] ' + text, file=sys.stderr if error else sys.stdout, flush=True)


def main(context, close_after_ms=0):
    binding, core, widgets = load_qt(report=lambda message: log(None, message))
    version = '{} {} · Qt {}'.format(binding, core.PYQT_VERSION_STR, core.QT_VERSION_STR)
    log(None, version + '\n' + context)
    qt_app = application(core, widgets)
    dialog = build_dialog(core, widgets, version, context)
    dialog.finished.connect(qt_app.quit)
    if close_after_ms:
        core.QTimer.singleShot(close_after_ms, dialog.reject)
    dialog.show()
    execute = getattr(qt_app, 'exec', None) or qt_app.exec_
    execute()
    dialog.deleteLater()
    deferred = getattr(core.QEvent, 'Type', core.QEvent).DeferredDelete
    core.QCoreApplication.sendPostedEvents(None, deferred)
    log(None, 'Testfenster geschlossen.')


if __name__ == '__main__':
    options = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
    QT_BINDING = options['binding']
    AUTO_INSTALL_PYQT = options['auto_install']
    DEPENDENCY_DIR = options['dependency_dir']
    main(options['context'])

'''


if __name__ == '__main__':
    main()
