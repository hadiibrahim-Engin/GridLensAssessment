"""GridLens contingency test run: a very small, controlled calculation on a PROJECT COPY.

Prepared for part 3, NOT to be run before Hadi releases it. Diagnostic tool,
not part of the GridLens delivery. It writes into the project, so it refuses
to do anything unless all of these hold:

1. ENABLED is True (it is False as delivered).
2. The active project is named exactly PROJECT_COPY_NAME, and that name
   contains COPY_MARKER, so it cannot be the production project by accident.
3. The settings to write (SWEEP_SETTINGS) are filled in from the output of
   tools/probe_contingency.py; nothing is guessed.
4. Before every writing test a Yes/No dialog names what will be written and
   the engineer answers Yes. Without a dialog (no Tk) nothing is written.

Every value it writes is recorded first, restored in reverse order afterwards
and read back to verify the restoration, also after an error. A failed
restoration is printed as RESTORE FAILED with the attribute name only.

Privacy: the output names no project, study case, object, value, study time or
error text; it prints PowerFactory attribute names, PASSED/FAILED and error
types only. Two things are read locally and never printed, because the safety
of a writing test needs them: the project name (compared with
PROJECT_COPY_NAME) and the study times (compared with the QDS steps). Unlike
tools/probe_contingency.py this tool is therefore not a strict-privacy tool.

Tests:

T1  Time sweep: write SWEEP_SETTINGS to the ComSimoutage, run it once for at
    most MAX_TIME_STEPS steps of the ComStatsim period, and compare the study
    times of its sub-results (p_rescnt, one ElmRes per study time) with the
    QDS time steps; only the comparison is printed.
T2  ElmRes round trip (prepared, not implemented): once the probe has shown
    the ElmRes write methods and their arguments, create one ElmRes named
    GridLens_TEST_<stamp> in the study case of the copy, write TEST_VALUES,
    read them back and delete the object again. Until then T2 creates nothing.
"""

ENABLED = False
# The exact name of the project copy, e.g. '<project> - GridLens TEST copy'.
PROJECT_COPY_NAME = ""
COPY_MARKER = "copy"
# Attribute -> value written to the ComSimoutage for T1, taken from the probe output.
SWEEP_SETTINGS = {}
# At most this many time steps in T1.
MAX_TIME_STEPS = 3
# ElmRes methods for T2, in call order, as the probe reported them (e.g. ("Init", "AddVariable", "Write")).
ELMRES_WRITE = ()
TEST_VALUES = (12.5, 100.0, 101.25)
RESTORE_ERROR = object()


def emit(app, message=""):
    try:
        app.PrintPlain(message)
    except Exception:
        print(message, flush=True)


def confirm(question):
    """Yes/No from the engineer; False without a dialog."""
    try:
        import tkinter
        from tkinter import messagebox
        root = tkinter.Tk()
        root.withdraw()
        try:
            return bool(messagebox.askyesno("GridLens contingency test", question, parent=root))
        finally:
            root.destroy()
    except Exception:
        return False


def name_of(obj):
    try:
        return str(obj.loc_name)
    except Exception:
        return "<unnamed>"


class Restorer:
    """Records original values and puts them back, verified, in reverse order."""

    def __init__(self, app):
        self.app = app
        self.changes = []

    def write(self, obj, attribute, value):
        original = getattr(obj, attribute)
        self.changes.append((obj, attribute, original))
        setattr(obj, attribute, value)
        if getattr(obj, attribute) != value:
            raise RuntimeError("an attribute did not accept the value")
        # Only the PowerFactory attribute name: no object name, no value (privacy).
        emit(self.app, "  wrote attribute {}".format(attribute))

    def restore(self):
        failures = []
        for obj, attribute, original in reversed(self.changes):
            try:
                setattr(obj, attribute, original)
                now = getattr(obj, attribute)
            except Exception:
                now = RESTORE_ERROR
            if now != original:
                failures.append("attribute {}".format(attribute))
        self.changes = []
        for failure in failures:
            emit(self.app, "  RESTORE FAILED " + failure)
        if not failures:
            emit(self.app, "  restored and verified every written value")
        return not failures


def preconditions(app):
    """The reason not to run, or None."""
    if not ENABLED:
        return "ENABLED is False; this tool runs only after an explicit release"
    project = app.GetActiveProject()
    name = name_of(project) if project is not None else ""
    if not PROJECT_COPY_NAME or COPY_MARKER.lower() not in PROJECT_COPY_NAME.lower():
        return "PROJECT_COPY_NAME must name the project copy and contain {!r}".format(COPY_MARKER)
    if name != PROJECT_COPY_NAME:
        # The name is compared locally and never printed.
        return "the active project is not the configured copy (PROJECT_COPY_NAME)"
    if app.GetActiveStudyCase() is None:
        return "no active study case"
    return None


def only(study_case, class_name):
    found = [item for item in study_case.GetContents("*." + class_name) or [] if item.GetClassName() == class_name]
    if len(found) != 1:
        raise RuntimeError("expected exactly one {} in the study case, found {}".format(class_name, len(found)))
    return found[0]


def qds_steps(qds):
    """The QDS time steps GridLens expects, limited to MAX_TIME_STEPS (epoch seconds)."""
    start, end = float(qds.startTime), float(qds.endTime)
    step = float(qds.stepSize) * {0: 1.0, 1: 60.0, 2: 3600.0, 3: 86400.0}.get(int(getattr(qds, "stepUnit", 2)), 3600.0)
    steps, moment = [], start
    while moment <= end and len(steps) < MAX_TIME_STEPS:
        steps.append(moment)
        moment += step
    return steps


def test_time_sweep(app, study_case):
    if not SWEEP_SETTINGS:
        emit(app, "T1 skipped: SWEEP_SETTINGS is empty; fill it in from the probe output.")
        return None
    command = only(study_case, "ComSimoutage")
    steps = qds_steps(only(study_case, "ComStatsim"))
    if not confirm("T1 writes to the ComSimoutage of the active study case:\n{}\nand runs it for {} time step(s). "
                   "Continue?".format("\n".join("{} = {!r}".format(key, value) for key, value in SWEEP_SETTINGS.items()),
                                      len(steps))):
        emit(app, "T1 not confirmed; nothing written.")
        return None
    restorer = Restorer(app)
    try:
        for attribute, value in SWEEP_SETTINGS.items():
            restorer.write(command, attribute, value)
        code = command.Execute()
        emit(app, "  ComSimoutage.Execute() returned {}".format(code))
        # The probe found the AC results in p_rescnt, one sub-result ElmRes per study time.
        result = getattr(command, "p_rescnt", None)
        if result is None:
            emit(app, "  no AC result object bound to the command; the study times cannot be compared")
            return False
        found = [child.GetAttribute("cnttime") for child in result.GetContents("*.ElmRes") or []]
        matches = sorted(found) == sorted(steps)
        # Privacy: only the comparison is printed, never the study times themselves.
        emit(app, "T1 {}: the study times of the time sweep {} the QDS steps".format(
            "PASSED" if matches else "FAILED", "equal" if matches else "differ from"))
        return matches
    finally:
        if not restorer.restore():
            emit(app, "T1: the ComSimoutage settings could not all be restored; check them by hand before any further use.")


def test_elmres_round_trip(app, study_case):
    """Prepared only. The arguments of Init/AddVariable/Write are unknown before the probe, and a guessed
    call is no test, so this test creates nothing until the write sequence is completed from the probe output."""
    if not ELMRES_WRITE:
        emit(app, "T2 skipped: ELMRES_WRITE is empty; fill it in from the probe output.")
        return None
    emit(app, "T2 NOT RUN: the write sequence {} is not implemented yet; nothing was created.".format(ELMRES_WRITE))
    return None


def main():
    import powerfactory  # noqa: F401  (only available inside PowerFactory)

    app = powerfactory.GetApplication()
    emit(app, "GridLens contingency test run (project copy only)")
    reason = preconditions(app)
    if reason:
        emit(app, "Nothing was done: " + reason + ".")
        return
    study_case = app.GetActiveStudyCase()
    for test in (test_time_sweep, test_elmres_round_trip):
        try:
            outcome = test(app, study_case)
        except Exception as exc:
            outcome = False
            # Only the type of the error: its text may contain names or paths.
            emit(app, "{} stopped: {}".format(test.__name__, type(exc).__name__))
        emit(app, "{}: {}".format(test.__name__, {True: "passed", False: "failed", None: "not run"}[outcome]))


if __name__ == "__main__":
    main()
