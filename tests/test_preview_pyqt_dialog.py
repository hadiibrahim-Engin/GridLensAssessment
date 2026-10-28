"""PowerFactory PyQt test: dependency selection and host-application lifetime."""

import importlib.util
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from types import ModuleType
import json

import pytest


@pytest.fixture
def launcher():
    path = Path(__file__).resolve().parents[1] / 'powerfactory_tests' / 'preview_pyqt_dialog.py'
    if not path.is_file():
        pytest.skip('optional development tool not present')
    spec = importlib.util.spec_from_file_location('gridlens_pyqt_test', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def tool(launcher, monkeypatch):
    module = ModuleType('gridlens_pyqt_child')
    exec(compile(launcher.CHILD_SOURCE, 'pyqt_child.py', 'exec'), module.__dict__)
    module.__file__ = launcher.__file__
    for key in list(sys.modules):
        if key.split('.')[0] in ('PyQt6', 'PyQt5', 'PySide6', 'PySide2'):
            monkeypatch.delitem(sys.modules, key)
    return module


def test_missing_pyqt_names_the_powerfactory_python_environment(tool, monkeypatch):
    def missing(name):
        raise ModuleNotFoundError(name, name=name)
    monkeypatch.setattr(tool.importlib, 'import_module', missing)
    with pytest.raises(RuntimeError, match='von PowerFactory.*Python-Umgebung'):
        tool.load_qt()


def test_auto_can_use_pyqt5_when_pyqt6_is_absent(tool, monkeypatch):
    calls = []

    def load(name):
        calls.append(name)
        if name == 'PyQt6':
            raise ModuleNotFoundError(name, name=name)
        return name
    monkeypatch.setattr(tool.importlib, 'import_module', load)
    assert tool.load_qt() == ('PyQt5', 'PyQt5.QtCore', 'PyQt5.QtWidgets')
    assert calls == ['PyQt6', 'PyQt5', 'PyQt5.QtCore', 'PyQt5.QtWidgets']


def test_broken_qt_installation_does_not_load_another_qt_major(tool, monkeypatch):
    calls = []

    def load(name):
        calls.append(name)
        if name.endswith('.QtCore'):
            raise ImportError('DLL load failed')
        return name
    monkeypatch.setattr(tool.importlib, 'import_module', load)
    with pytest.raises(RuntimeError, match='DLL load failed'):
        tool.load_qt()
    assert calls == ['PyQt6', 'PyQt6.QtCore']


@pytest.mark.parametrize('loaded', ['PyQt5', 'PySide6', 'PySide2'])
def test_explicit_pyqt6_rejects_conflicting_loaded_bindings(tool, monkeypatch, loaded):
    tool.QT_BINDING = 'PyQt6'
    monkeypatch.setitem(sys.modules, loaded, SimpleNamespace())
    with pytest.raises(RuntimeError, match='bereits geladen|Bereits geladene'):
        tool.load_qt()


def test_auto_reuses_the_loaded_pyqt_binding(tool, monkeypatch):
    monkeypatch.setitem(sys.modules, 'PyQt5.QtCore', SimpleNamespace())
    monkeypatch.setattr(tool.importlib, 'import_module', lambda name: name)
    assert tool.load_qt()[0] == 'PyQt5'


def test_existing_host_application_is_reused_without_changing_settings(tool):
    thread = object()

    class HostApplication:
        @staticmethod
        def instance():
            return host

        def thread(self):
            return thread
    host = HostApplication()
    core = SimpleNamespace(QThread=SimpleNamespace(currentThread=lambda: thread))
    widgets = SimpleNamespace(QApplication=HostApplication)
    assert tool.application(core, widgets) is host
    assert tool._qt_app is host


def test_a_non_gui_thread_cannot_create_widgets_in_the_host_application(tool):
    class HostApplication:
        @staticmethod
        def instance():
            return host

        def thread(self):
            return 'host GUI thread'
    host = HostApplication()
    core = SimpleNamespace(QThread=SimpleNamespace(currentThread=lambda: 'worker thread'))
    with pytest.raises(RuntimeError, match='außerhalb des Qt-GUI-Threads'):
        tool.application(core, SimpleNamespace(QApplication=HostApplication))


def test_powerfactory_context_reads_only_project_and_study_names(launcher, monkeypatch):
    app = SimpleNamespace(GetActiveProject=lambda: SimpleNamespace(loc_name='Project'),
                          GetActiveStudyCase=lambda: SimpleNamespace(loc_name='Study'))
    module = SimpleNamespace(GetApplication=lambda: app)
    monkeypatch.setattr(launcher.importlib, 'import_module', lambda _name: module)
    found, description = launcher.powerfactory_context()
    assert found is app and 'Project' in description and 'Study' in description


def test_repository_folder_is_not_mistaken_for_the_powerfactory_api(launcher, monkeypatch):
    monkeypatch.setattr(launcher.importlib, 'import_module', lambda _name: SimpleNamespace())
    app, description = launcher.powerfactory_context()
    assert app is None and 'Standalone' in description and 'keine PowerFactory-API' in description


@pytest.mark.gui
@pytest.mark.optional_qt
def test_real_pyqt_navigation_signals_timer_and_host_lifetime(tool):
    if all(importlib.util.find_spec(name) is None for name in ('PyQt6', 'PyQt5')):
        pytest.skip('optional PyQt dependency not installed')
    # A separate process keeps Qt and the existing Tk tests from sharing the
    # native GUI runtime. Callback failures are collected outside Qt slots.
    script = r'''
import importlib.util
import sys
import traceback

spec = importlib.util.spec_from_file_location('pyqt_smoke', sys.argv[1])
launcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)
from types import ModuleType
tool = ModuleType('pyqt_child_test')
exec(compile(launcher.CHILD_SOURCE, 'pyqt_child.py', 'exec'), tool.__dict__)
binding, core, widgets = tool.load_qt()
app = tool.application(core, widgets)
app.setStyleSheet('QWidget { font-size: 12px; }')
app.setQuitOnLastWindowClosed(False)
original_style = app.styleSheet()
dialog = tool.build_dialog(core, widgets, binding, 'PowerFactory test context')
failures, messages = [], []

def exercise():
    try:
        pages = dialog.findChild(widgets.QStackedWidget, 'pages')
        buttons = {button.text(): button for button in dialog.findChildren(widgets.QPushButton)}
        for index, name in enumerate(('Übersicht', 'Planungsfälle', 'Netzauswahl', 'Einstellungen')):
            buttons[name].click()
            assert pages.currentIndex() == index
            assert pages.currentWidget().isVisible()
        table = dialog.findChild(widgets.QTableWidget, 'caseTable')
        assert table.rowCount() == 3 and table.item(1, 0).text() == 'Kabeltausch Nord'
        grids = dialog.findChild(widgets.QComboBox, 'gridChoice')
        grids.setCurrentIndex(2)
        assert grids.currentText() == 'Netz Süd'
        buttons['Übersicht'].click()
        dialog.findChild(widgets.QLineEdit, 'caseName').setText('PF-Test')
        dialog.findChild(widgets.QCheckBox, 'n1').setChecked(False)
        assert 'aktiv' in dialog.findChild(widgets.QLabel, 'heartbeat').text()

        def close_message():
            try:
                box = app.activeModalWidget()
                assert isinstance(box, widgets.QMessageBox)
                messages.append(box.text())
                box.accept()
            except BaseException:
                failures.append(traceback.format_exc())
                dialog.reject()
        core.QTimer.singleShot(50, close_message)
        buttons['Oberfläche testen'].click()
        assert len(messages) == 1 and 'PF-Test' in messages[0] and 'n-1: False' in messages[0]
        assert app.styleSheet() == original_style
        assert not app.quitOnLastWindowClosed()
        buttons['Fenster schließen'].click()
    except BaseException:
        failures.append(traceback.format_exc())
        dialog.reject()

core.QTimer.singleShot(1500, exercise)
execute = getattr(dialog, 'exec', None) or dialog.exec_
execute()
assert not failures, '\n'.join(failures)
assert not dialog.findChild(core.QTimer).isActive()
assert tool.application(core, widgets) is app

# Exercise the child's application event loop, with deterministic closure.
tool.main('PyQt smoke test', close_after_ms=50)
assert widgets.QApplication.instance() is app
assert app.styleSheet() == original_style
assert not app.quitOnLastWindowClosed()
print('PASS: native PyQt dialog, navigation, message box, timer and repeated entry point')
'''
    result = subprocess.run([sys.executable, '-c', script, tool.__file__],
                            capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'PASS: native PyQt' in result.stdout


def test_each_launch_uses_a_fresh_child_without_importing_qt_in_powerfactory(launcher, tmp_path, monkeypatch):
    launcher.LOG_DIR = str(tmp_path / 'logs')
    monkeypatch.setattr(launcher, 'gui_python', lambda: Path(sys.executable))
    monkeypatch.setenv('QT_PLUGIN_PATH', '/PowerFactory/Qt/plugins')
    monkeypatch.setenv('PYTHONPATH', '/PowerFactory/python')
    original_path = list(sys.path)
    calls = []

    def unexpected_import(name):
        raise AssertionError('Launcher must not import ' + name)
    monkeypatch.setattr(launcher.importlib, 'import_module', unexpected_import)

    class Process:
        def __init__(self, command, **options):
            script, config = Path(command[-2]), Path(command[-1])
            assert script.read_text(encoding='utf-8') == launcher.CHILD_SOURCE
            assert json.loads(config.read_text(encoding='utf-8'))['context'] == 'Project A'
            assert 'QT_PLUGIN_PATH' not in options['env']
            assert 'PYTHONPATH' not in options['env']
            assert command[1:3] == ['-I', '-u']
            calls.append(command)

        def wait(self):
            return 0
    monkeypatch.setattr(launcher.subprocess, 'Popen', Process)
    first = launcher.launch_gui('Project A')
    second = launcher.launch_gui('Project A')
    assert len(calls) == 2 and first != second
    assert sys.path == original_path


def test_a_native_child_crash_is_reported_as_an_error_in_the_launcher(launcher, tmp_path, monkeypatch):
    launcher.LOG_DIR = str(tmp_path)
    monkeypatch.setattr(launcher, 'gui_python', lambda: Path(sys.executable))

    class Crashed:
        def __init__(self, _command, **options):
            options['stdout'].write('Fatal Qt access violation')

        def wait(self):
            return 0xC0000005
    monkeypatch.setattr(launcher.subprocess, 'Popen', Crashed)
    with pytest.raises(RuntimeError, match='C0000005.*Protokoll:') as found:
        launcher.launch_gui('Project')
    assert 'Fatal Qt access violation' in str(found.value)
    assert len(list(tmp_path.glob('*.log'))) == 1


@pytest.mark.parametrize('compatible', [True, False])
def test_interpreter_discovery_does_not_execute_powerfactory_as_python(launcher, tmp_path, monkeypatch, compatible):
    host, python = tmp_path / 'PowerFactory.exe', tmp_path / 'python.exe'
    host.touch()
    python.touch()
    monkeypatch.setattr(sys, 'executable', str(host))
    monkeypatch.setattr(sys, 'prefix', str(tmp_path))
    monkeypatch.setattr(sys, 'base_prefix', str(tmp_path))
    monkeypatch.setattr(launcher.sysconfig, 'get_path', lambda _key: str(tmp_path / 'Lib'))
    monkeypatch.setattr(launcher.shutil, 'which', lambda _name: None)
    calls = []
    identity = launcher.python_identity() if compatible else ['different-python', 'wrong-architecture', '', 4]

    def probe(executable, _args):
        calls.append(executable)
        return SimpleNamespace(returncode=0, stdout=json.dumps(identity))
    monkeypatch.setattr(launcher, 'run_python', probe)
    if compatible:
        assert launcher.gui_python() == python
    else:
        with pytest.raises(RuntimeError, match='Kein passender Python-Interpreter'):
            launcher.gui_python()
    assert calls == [python]
