"""Log levels chosen in the case manager and the run time measurement."""

from __future__ import annotations

import importlib.util
import pytest

from _paths import delivered

SPEC = importlib.util.spec_from_file_location("outage_assessment_log_levels", delivered("main.py"))
gl = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gl)


class App:
    def __init__(self):
        self.lines = []

    def PrintPlain(self, line):
        # A long message arrives wrapped over several lines; the tests read it as one line.
        self.lines.append(gl.re.sub(r"\s*\n\s*", " ", line))


@pytest.fixture(autouse=True)
def _fresh_run():
    gl.RUN_STATS = gl.RunStats()
    gl.reset_run_context()
    yield
    gl.reset_run_context()


def _emit_all(level):
    app = App()
    logger = gl.RunLogger(app, level)
    logger.write("X", "compact line", 1, verbosity=gl.LOG_COMPACT)
    logger.write("X", "standard line", 1)
    logger.detail("detailed line", verbosity=gl.LOG_DETAILED)
    logger.detail("diagnostic line", verbosity=gl.LOG_DIAGNOSTIC)
    logger.detail("a warning", "WARNING", verbosity=gl.LOG_DIAGNOSTIC)
    logger.write("X", "an error", 1, "ERROR", verbosity=gl.LOG_DIAGNOSTIC)
    logger.table(("A", "B"), [("1", "2")], verbosity=gl.LOG_DETAILED)
    return "\n".join(app.lines)


@pytest.mark.parametrize("level, shown, hidden", [
    ("compact", ["compact line"], ["standard line", "detailed line", "diagnostic line", "A  B"]),
    ("standard", ["compact line", "standard line"], ["detailed line", "diagnostic line", "A  B"]),
    ("detailed", ["standard line", "detailed line", "A  B"], ["diagnostic line"]),
    ("diagnostic", ["compact line", "standard line", "detailed line", "diagnostic line", "A  B"], []),
])
def test_each_level_shows_its_lines_and_never_hides_warnings_or_errors(level, shown, hidden):
    text = _emit_all(level)
    for line in shown + ["a warning", "an error"]:
        assert line in text, (level, line)
    for line in hidden:
        assert line not in text, (level, line)


def test_an_unknown_level_falls_back_to_standard():
    assert gl.RunLogger(App(), "loud").level == gl.LOG_STANDARD
    assert gl.normalized_log_level("detailed") == gl.LOG_DETAILED and gl.normalized_log_level(None) == gl.LOG_STANDARD


def test_the_level_of_the_run_reaches_every_logger():
    gl.set_log_level("compact")
    assert gl.RunLogger(App()).level == gl.LOG_COMPACT, "also the logger of main() that reports a failure"


def test_sections_and_case_heads_are_always_shown():
    app = App()
    logger = gl.RunLogger(app, "compact")
    logger.step(4, "Calculation")
    logger.case("Case C1 · A")
    text = "\n".join(app.lines)
    assert "STEP 4/7 · Calculation" in text and "Case C1 · A" in text


def test_the_case_manager_window_is_no_run_time():
    stats = gl.RunStats()
    stats.started -= 110.0  # the run started 110 s ago
    with stats.wait():
        stats._wait_started -= 100.0  # the window stood open for 100 s of it
    assert 9.5 < stats.run_time() < 11.0
    assert 99.5 < stats.waited < 101.0


def test_log_lines_carry_clock_time_and_run_time():
    app = App()
    gl.RunLogger(app, "standard").write("X", "message", 2)
    line = app.lines[-1]
    assert gl.re.search(r"^\[OA\] \d\d:\d\d:\d\d \+\d+\.\ds +message$", line), line
    assert gl.elapsed_text(12.34) == "+12.3s" and gl.elapsed_text(245) == "+4m05s" and gl.elapsed_text(7380) == "+2h03m"


def test_long_messages_wrap_under_themselves_and_warnings_are_marked():
    # Hadi, 20 Nov 2026: blocks apart and readable, nothing lost in dense lines.
    printed = []

    class Window:
        def PrintPlain(self, text):
            printed.append(text)
    logger = gl.RunLogger(Window(), "standard")
    logger.write("X", "word " * 60, 2, "WARNING")
    lines = printed[-1].split("\n")
    assert len(lines) > 1 and "WARNING  word" in lines[0], "one call, several lines"
    column = lines[0].index("WARNING")
    assert all(line.startswith(" " * column) for line in lines[1:]), "continued under the message"
    logger.fields("Settings of this run", [("Assessments", "n-0"), ("Log", "standard")])
    assert printed[-3].strip() == "[OA]                   Settings of this run:".strip()
    assert printed[-2].endswith("Assessments ... n-0") and printed[-1].endswith("Log ........... standard"), (
        "names and values aligned")


def test_the_summary_shows_steps_cases_and_the_window_apart():
    stats = gl.RUN_STATS
    stats.start_step(1, "Startup")
    stats.start_step(4, "Calculation")
    stats.case_add("REF", "calculation", 3.0)
    stats.case_add("C1", "calculation", 3.5)
    stats.case_add("C1", "reading", 20.0)
    with stats.wait():
        stats._wait_started -= 50.0
    stats.finish_step()
    app = App()
    gl.log_run_summary(gl.RunLogger(app, "standard"), stats)
    text = "\n".join(app.lines)
    assert "STEP 1/7" in text and "STEP 4/7" in text, "time per step"
    assert "C1" in text and "20 s" in text, "time per case and phase"
    assert "case manager window stood open for 50 s" in text and "not counted" in text

    app = App()
    gl.log_run_summary(gl.RunLogger(app, "compact"), stats)
    assert len([line for line in app.lines if line.strip()]) <= 3, "compact: one summary line"
    assert any("Run time" in line for line in app.lines)


def test_the_log_level_is_saved_with_the_cases_and_checked():
    config = gl.empty_case_config("P")
    assert config["log_level"] == gl.LOG_STANDARD
    config["log_level"] = "loud"
    assert any("log_level" in problem for problem in gl.validate_case_config(config))
    editor = gl.CaseEditor([], gl.empty_case_config("P"), (None, None))
    assert editor.set_log_level("detailed") is None
    assert editor.config["log_level"] == "detailed" and editor.request()["log_level"] == "detailed"
    assert editor.set_log_level("loud") is not None
    assert "Log: Detailed" in editor.calculation_preview()


def test_warnings_of_the_same_kind_are_grouped_below_detailed():
    app = App()
    logger = gl.RunLogger(app, "standard")
    group = gl.WarningGroup(logger, "OUTAGES", 3)
    for name in ("A", "B", "C"):
        group.add("could not be compared with the simulated period", "Outage '{}': not comparable".format(name), name)
    group.flush()
    warnings = [line for line in app.lines if "WARNING" in line]
    assert len(warnings) == 1 and "3 planned outage(s)" in warnings[0] and "A, B, C" in warnings[0]

    app = App()
    logger = gl.RunLogger(app, "detailed")
    group = gl.WarningGroup(logger, "OUTAGES", 3)
    for name in ("A", "B"):
        group.add("could not be compared", "Outage '{}': not comparable".format(name), name)
    group.flush()
    assert len([line for line in app.lines if "WARNING" in line]) == 2, "one line each from detailed on"


def test_a_fresh_run_has_no_run_time_yet():
    assert gl.RunStats().run_time() < 1.0


def test_parts_of_a_service_are_shown_below_it_and_not_counted_twice():
    stats = gl.RunStats()
    stats.add(gl.READ_SERVICE, 10.0)
    stats.part(gl.READ_SERVICE, gl.READ_COLUMNS, 6.0, 450)
    stats.part(gl.READ_SERVICE, gl.READ_CONVERT, 3.0, 450)
    stats.started -= 12.0
    rows = stats.rows()
    names = [row[0] for row in rows]
    at = names.index("  Read the simulation results")
    assert names[at - 1] == "Reading the results", "grouped by what the work is for"
    assert names[at + 1:at + 3] == ["      of which: PowerFactory hands over the values, a whole curve at a time",
                                    "      of which: Outage Assessment takes over the values"]
    assert rows[at + 1][1] == "450 \u00d7"
    other = next(row for row in rows if row[0].startswith("Not measured"))
    assert other[2] == "2.0 s", "only the work counts, not its parts as well"


def test_durations_and_counts_read_like_a_clock():
    assert [gl.duration_text(value) for value in (0.04, 9.94, 12.4, 245.0, 3725.0)] == [
        "0.0 s", "9.9 s", "12 s", "4 min 05 s", "1 h 02 min"]
    assert gl.count_text(52800) == "52 800 \u00d7"
    stats = gl.RunStats()
    stats.add("QDS calculation (PowerFactory)", 30.0, 3)
    stats.add("a new piece of work", 1.0)
    assert stats.longest_work() == ("Quasi-dynamic simulation (QDS)", 30.0)
    assert stats.work("a new piece of work") == ("Other work", "A new piece of work"), "unknown work keeps its name"
    # Every measured service of the script has a plain wording.
    source = open(gl.__file__, encoding="utf-8").read()
    measured = set(gl.re.findall(r'RUN_STATS\.(?:measure|add)\("([^"]+)"', source)) | {gl.READ_SERVICE}
    assert measured <= set(gl.RunStats.WORK_LABELS), measured - set(gl.RunStats.WORK_LABELS)
    parts = {gl.READ_HEADERS, gl.READ_COLUMNS, gl.READ_CELLS, gl.READ_CONVERT, gl.READ_CHECK}
    assert parts <= set(gl.RunStats.PART_LABELS)
