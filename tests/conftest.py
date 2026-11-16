"""Unattended test execution: explicit GUI automation, no user prompts."""

import builtins
import faulthandler
import sys
from types import ModuleType

import pytest


def pytest_addoption(parser):
    parser.addoption("--run-gui", action="store_true",
                     help="Run automated native GUI tests (requires a graphical session; no manual clicks)")
    parser.addoption("--require-gui", action="store_true",
                     help="Fail desktop validation if any selected test is skipped")
    parser.addoption("--gui-timeout", type=int, default=60,
                     help="Terminate pytest with a traceback if a test hangs (seconds, default: 60)")


def pytest_configure(config):
    if config.getoption("--gui-timeout") < 1:
        raise pytest.UsageError("--gui-timeout must be at least 1 second")
    config._outage_assessment_skip_tracker = _SkipTracker()
    config.pluginmanager.register(config._outage_assessment_skip_tracker, "outage_assessment-skips")


class _SkipTracker:
    skipped = False

    def pytest_collectreport(self, report):
        if report.skipped:
            self.skipped = True

    def pytest_runtest_logreport(self, report):
        if report.skipped:
            self.skipped = True


def pytest_sessionfinish(session, exitstatus):
    if session.config.getoption("--require-gui") and session.config._outage_assessment_skip_tracker.skipped:
        session.exitstatus = pytest.ExitCode.TESTS_FAILED
        reporter = session.config.pluginmanager.getplugin("terminalreporter")
        if reporter is not None:
            reporter.write_sep("=", "Required GUI validation contains skipped tests")


@pytest.fixture(autouse=True)
def _bounded_gui_test(request, monkeypatch):
    """Fail on an unstubbed interaction, including in tests without a gui marker."""
    gui = request.node.get_closest_marker("gui") is not None
    if gui and not (request.config.getoption("--run-gui") or request.config.getoption("--require-gui")):
        pytest.skip("Native GUI tests are opt-in; use --run-gui in a graphical session")
    timeout = request.config.getoption("--gui-timeout")
    faulthandler.dump_traceback_later(timeout, file=sys.__stderr__, exit=True)
    roots, callback_errors = [], []

    def unexpected_interaction(*args, **kwargs):
        pytest.fail("Unexpected user interaction in test. Stub the prompt or automate the GUI explicitly.",
                    pytrace=False)

    monkeypatch.setattr(builtins, "input", unexpected_interaction)
    # Imported script modules are often loaded with exec_module rather than put
    # in sys.modules. Guard their shared GUI entry point before either Tk or Qt
    # can open a native window. Test-specific stubs may replace this guard.
    if not gui:
        for module in list(vars(request.module).values()):
            if isinstance(module, ModuleType) and callable(getattr(module, "run_case_manager", None)):
                monkeypatch.setattr(module, "run_case_manager", unexpected_interaction)
    try:
        try:
            import tkinter as tk
            from tkinter import messagebox, simpledialog
        except ImportError:
            yield
            return

        original_init, original_update = tk.Tk.__init__, tk.Misc.update

        def tracked_init(root, *args, **kwargs):
            if not gui:
                unexpected_interaction()
            original_init(root, *args, **kwargs)
            roots.append(root)

        def capture_callback_error(widget):
            callback_errors.append(sys.exc_info())

        def checked_update(widget):
            original_update(widget)
            if callback_errors:
                _kind, error, trace = callback_errors.pop(0)
                raise error.with_traceback(trace)

        def unexpected_dialog(*args, **kwargs):
            title = args[0] if args else kwargs.get("title", "")
            pytest.fail(f"Unexpected modal dialog in test: {title}. Stub the expected dialog explicitly.",
                        pytrace=False)

        monkeypatch.setattr(tk.Tk, "__init__", tracked_init)
        monkeypatch.setattr(tk.Misc, "_report_exception", capture_callback_error)
        monkeypatch.setattr(tk.Misc, "update", checked_update)
        # Native loops/waits need an explicit test driver; a gui marker alone
        # must never turn a test into a manual window demonstration.
        for name in ("mainloop", "wait_window", "wait_visibility", "wait_variable"):
            monkeypatch.setattr(tk.Misc, name, unexpected_interaction)
        monkeypatch.setattr(tk, "mainloop", unexpected_interaction)
        # Also cover filedialog and aliases imported before this fixture.
        from tkinter import commondialog
        monkeypatch.setattr(commondialog.Dialog, "show", unexpected_dialog)
        monkeypatch.setattr(simpledialog.Dialog, "__init__", unexpected_dialog)
        for name in ("showerror", "showinfo", "showwarning", "askyesno", "askokcancel",
                     "askquestion", "askretrycancel", "askyesnocancel"):
            monkeypatch.setattr(messagebox, name, unexpected_dialog)
        for name in ("askstring", "askinteger", "askfloat"):
            monkeypatch.setattr(simpledialog, name, unexpected_dialog)
        yield
        if callback_errors:
            _kind, error, trace = callback_errors[0]
            raise error.with_traceback(trace)
    finally:
        # Stop the watchdog even when destruction fails; it owns this test only.
        try:
            for root in reversed(roots):
                try:
                    root.destroy()
                except Exception:
                    pass
        finally:
            faulthandler.cancel_dump_traceback_later()
