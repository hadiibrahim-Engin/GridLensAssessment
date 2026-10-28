"""CI-specific requirements; ordinary local tests retain their existing behavior."""

import faulthandler
import sys

import pytest


def pytest_addoption(parser):
    parser.addoption("--require-gui", action="store_true",
                     help="Fail desktop validation if any selected test is skipped")
    parser.addoption("--gui-timeout", type=int, default=60,
                     help="Terminate pytest with a traceback if a GUI test hangs (seconds, default: 60)")


def pytest_configure(config):
    if config.getoption("--gui-timeout") < 1:
        raise pytest.UsageError("--gui-timeout must be at least 1 second")
    config._gridlens_skip_tracker = _SkipTracker()
    config.pluginmanager.register(config._gridlens_skip_tracker, "gridlens-skips")


class _SkipTracker:
    skipped = False

    def pytest_collectreport(self, report):
        if report.skipped:
            self.skipped = True

    def pytest_runtest_logreport(self, report):
        if report.skipped:
            self.skipped = True


def pytest_sessionfinish(session, exitstatus):
    if session.config.getoption("--require-gui") and session.config._gridlens_skip_tracker.skipped:
        session.exitstatus = pytest.ExitCode.TESTS_FAILED
        reporter = session.config.pluginmanager.getplugin("terminalreporter")
        if reporter is not None:
            reporter.write_sep("=", "Required GUI validation contains skipped tests")


@pytest.fixture(autouse=True)
def _bounded_gui_test(request, monkeypatch):
    """Keep native dialogs unattended and bound even a blocked Tcl event loop."""
    if request.node.get_closest_marker("gui") is None:
        yield
        return
    timeout = request.config.getoption("--gui-timeout")
    faulthandler.dump_traceback_later(timeout, file=sys.__stderr__, exit=True)
    roots, callback_errors = [], []
    try:
        try:
            import tkinter as tk
            from tkinter import messagebox, simpledialog
        except ImportError:
            yield
            return

        original_init, original_update = tk.Tk.__init__, tk.Misc.update

        def tracked_init(root, *args, **kwargs):
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
            raise RuntimeError(f"Unexpected modal dialog in GUI test: {title}. Stub the expected dialog explicitly.")

        monkeypatch.setattr(tk.Tk, "__init__", tracked_init)
        monkeypatch.setattr(tk.Misc, "_report_exception", capture_callback_error)
        monkeypatch.setattr(tk.Misc, "update", checked_update)
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
