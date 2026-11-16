"""A required desktop check must fail rather than silently skip its tests."""

from pathlib import Path

import pytest

pytest_plugins = ["pytester"]


def test_required_gui_run_rejects_skipped_tests(pytester):
    pytester.makeconftest((Path(__file__).with_name("conftest.py")).read_text())
    pytester.makepyfile("import pytest\ndef test_desktop(): pytest.skip('no display')")
    result = pytester.runpytest_subprocess("--require-gui", "-q")
    assert result.ret == 1
    result.stdout.fnmatch_lines(["*Required GUI validation contains skipped tests*"])


def test_local_gui_run_can_still_skip_without_a_display(pytester):
    pytester.makeconftest((Path(__file__).with_name("conftest.py")).read_text())
    pytester.makepyfile("import pytest\ndef test_desktop(): pytest.skip('no display')")
    result = pytester.runpytest_subprocess("-q")
    assert result.ret == 0


def test_required_gui_run_rejects_skips_without_terminal_reporter(pytester):
    pytester.makeconftest((Path(__file__).with_name("conftest.py")).read_text())
    pytester.makepyfile("import pytest\ndef test_desktop(): pytest.skip('no display')")
    result = pytester.runpytest_subprocess("--require-gui", "-p", "no:terminal")
    assert result.ret == 1


def test_required_gui_run_rejects_a_skipped_module(pytester):
    pytester.makeconftest((Path(__file__).with_name("conftest.py")).read_text())
    pytester.makepyfile("import pytest\npytest.skip('no display', allow_module_level=True)")
    result = pytester.runpytest_subprocess("--require-gui", "-q")
    assert result.ret == 1


@pytest.mark.parametrize("marked_gui", [False, True])
def test_unexpected_modal_dialog_fails_without_opening_a_window(pytester, marked_gui):
    pytester.makeconftest((Path(__file__).with_name("conftest.py")).read_text())
    pytester.makepyfile(('''
import pytest
''' + ('@pytest.mark.gui\n' if marked_gui else '') + '''
def test_message():
    messagebox = pytest.importorskip("tkinter.messagebox")
    try:
        messagebox.showinfo("Synthetic", "This must not require a user click")
    except Exception:
        pass  # Production fallback handlers must not swallow a test failure.
'''))
    result = pytester.runpytest_subprocess("-q", "--run-gui")
    result.assert_outcomes(failed=1)
    assert "Unexpected modal dialog" in result.stdout.str()


@pytest.mark.parametrize("interaction", [
    "input('Continue?')",
    "__import__('tkinter').mainloop()",
    "__import__('tkinter').Misc.mainloop(None)",
    "__import__('tkinter').Misc.wait_window(None)",
    "__import__('tkinter.filedialog', fromlist=['askopenfilename']).askopenfilename()",
    "__import__('tkinter.simpledialog', fromlist=['askstring']).askstring('Name', 'Value')",
])
def test_unattended_run_rejects_unautomated_interactions(pytester, interaction):
    if "tkinter" in interaction:
        pytest.importorskip("tkinter")
    pytester.makeconftest((Path(__file__).with_name("conftest.py")).read_text())
    pytester.makepyfile("def test_prompt():\n    " + interaction)
    result = pytester.runpytest_subprocess("-q", timeout=10)
    result.assert_outcomes(failed=1)
    assert "Unexpected" in result.stdout.str()


@pytest.mark.parametrize("runtime", ["tk", "qt"])
def test_non_gui_run_blocks_a_case_manager_before_loading_its_toolkit(pytester, runtime):
    pytester.makeconftest((Path(__file__).with_name("conftest.py")).read_text())
    path = Path(__file__).resolve().parents[1] / "outage-assessment" / ("main_qt.py" if runtime == "qt" else "main.py")
    pytester.makepyfile(f'''
import importlib.util
spec = importlib.util.spec_from_file_location("runtime", {str(path)!r})
runtime = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime)
def test_window():
    runtime.run_case_manager([], {{}}, (None, None), "unused.json")
''')
    result = pytester.runpytest_subprocess("-q", "-m", "not gui", timeout=10)
    result.assert_outcomes(failed=1)
    assert "Unexpected user interaction" in result.stdout.str()


@pytest.mark.parametrize("marked_gui", [False, True])
def test_hung_test_exits_with_a_traceback(pytester, marked_gui):
    pytester.makeconftest((Path(__file__).with_name("conftest.py")).read_text())
    pytester.makepyfile(('''
import time
import pytest
''' + ('@pytest.mark.gui\n' if marked_gui else '') + '''
def test_hang():
    time.sleep(20)
'''))
    result = pytester.runpytest_subprocess("--run-gui", "--gui-timeout=1", "-s", timeout=10)
    assert result.ret == 1
    assert "Timeout" in result.stdout.str() + result.stderr.str()


def test_native_gui_is_skipped_unless_explicitly_enabled(pytester):
    pytester.makeconftest((Path(__file__).with_name("conftest.py")).read_text())
    pytester.makepyfile('''
import pytest
@pytest.mark.gui
def test_window():
    raise AssertionError("The default test run must not reach native GUI code")
''')
    result = pytester.runpytest_subprocess("-q", "-rs", timeout=10)
    result.assert_outcomes(skipped=1)
    assert "Native GUI tests are opt-in" in result.stdout.str()
