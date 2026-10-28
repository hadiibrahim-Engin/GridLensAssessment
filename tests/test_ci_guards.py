"""A required desktop check must fail rather than silently skip its tests."""

from pathlib import Path

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


def test_unexpected_modal_dialog_fails_without_opening_a_window(pytester):
    pytester.makeconftest((Path(__file__).with_name("conftest.py")).read_text())
    pytester.makepyfile('''
import pytest
@pytest.mark.gui
def test_message():
    messagebox = pytest.importorskip("tkinter.messagebox")
    with pytest.raises(RuntimeError, match="Unexpected modal dialog"):
        messagebox.showinfo("Synthetic", "This must not require a user click")
''')
    result = pytester.runpytest_subprocess("-q")
    assert result.ret == 0
    result.assert_outcomes(passed=1)


def test_hung_gui_test_exits_with_a_traceback(pytester):
    pytester.makeconftest((Path(__file__).with_name("conftest.py")).read_text())
    pytester.makepyfile('''
import time
import pytest
@pytest.mark.gui
def test_hang():
    time.sleep(20)
''')
    result = pytester.runpytest_subprocess("--gui-timeout=1", "-s", timeout=10)
    assert result.ret == 1
    assert "Timeout" in result.stdout.str() + result.stderr.str()
