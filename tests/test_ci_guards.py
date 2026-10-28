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
