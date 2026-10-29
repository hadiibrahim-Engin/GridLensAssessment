"""Outage Assessment probe: how fast does an IntReport write cells (CreateTable, CreateField, SetValue)?

Diagnostic tool, not part of the Outage Assessment delivery. It answers whether QDS time
series could be written into the report database and evaluated with SQL in the
Stimulsoft template: that would need one SetValue call per value (one year
hourly, 450 series, REF and 5 cases: about 24 million calls).

How to run it:
1. In PowerFactory create a NEW IntReport whose name contains "probe", e.g.
   "Outage Assessment write probe". Never use the Outage Assessment report: Reset() clears the
   tables of the IntReport the probe runs below.
2. Place this file as a ComPython directly below that IntReport.
3. Set ENABLED = True below and execute the ComPython.

What it measures, with the same calls Outage Assessment uses (SetValue(table, field,
row, value), field types 0 string, 1 integer, 2 number):
- Reset(), CreateTable() and CreateField() per call,
- SetValue() for numbers, integers and texts in a wide table (10 fields) in
  stages of STAGE_CELLS cells, each stage timed in blocks, so a slowdown with
  growing table size becomes visible,
- a narrow "long format" table (run, element, step, value) as SQL in the
  template would need it,
- the bare Python loop without SetValue, so the share of PowerFactory is clear.
Each stage stops after STAGE_SECONDS_MAX and extrapolates. At the end the
probe resets its own report again (CLEAN_UP) and prints estimates for the
Outage Assessment publication and for writing whole QDS series.

Privacy: only numbers, table and field names of the probe are printed.
"""

import time

ENABLED = False
REPORT_NAME_MARKER = "probe"
STAGE_CELLS = (1000, 10000, 100000)
BLOCK_CELLS = 10000
STAGE_SECONDS_MAX = 300.0
CLEAN_UP = True
PROBE_VERSION = "1.0"
FIELD_TYPES = {"string": 0, "integer": 1, "number": 2}
# Field names without digits: tables with digits in field names were missing from the report database.
WIDE_FIELDS = tuple("field_" + letter for letter in "abcdefghij")
LONG_FIELDS = (("run_key", "integer"), ("element_key", "integer"), ("step_key", "integer"), ("value", "number"))
# Estimates printed at the end: (label, cells).
ESTIMATES = (("Outage Assessment publication today (about 500 rows, 19 tables)", 6000),
             ("one QDS run, one year hourly, 450 series", 8784 * 450),
             ("REF + 5 cases, one year hourly, 450 series", 6 * 8784 * 450))


class Out:
    def __init__(self, printer):
        self.printer = printer
        self.lines = []

    def line(self, text=""):
        self.lines.append(text)
        self.printer("[write probe] " + text if text else "")


def code_of(returned):
    """0 for success; PowerFactory returns 0, None or [0, ...] on success."""
    if returned is None:
        return 0
    if isinstance(returned, (list, tuple)):
        returned = returned[0] if returned else 0
    try:
        return int(returned)
    except (TypeError, ValueError):
        return 0


def timed(call, *args):
    started = time.perf_counter()
    returned = call(*args)
    return time.perf_counter() - started, code_of(returned)


def grouped(number):
    """1234567 -> '1 234 567'."""
    return "{:,.0f}".format(number).replace(",", " ")


def rate_text(cells, seconds):
    if seconds <= 0:
        return "n/a"
    return "{} cells/s, {:.1f} µs per cell".format(grouped(cells / seconds), 1e6 * seconds / cells)


def duration_text(seconds):
    if seconds < 120:
        return "{:.1f} s".format(seconds)
    if seconds < 7200:
        return "{:.1f} min".format(seconds / 60)
    return "{:.1f} h".format(seconds / 3600)


def value_for(kind, index):
    if kind == "number":
        return 50.0 + (index % 997) * 0.137
    if kind == "integer":
        return index % 100000
    return "text {}".format(index % 1000)


def write_stage(out, report, table, fields, cells, kinds, first_row=0):
    """Write `cells` cells into new rows from `first_row` on; (cells written, seconds, errors, block seconds, next row)."""
    written, errors, blocks = 0, 0, []
    started = block_started = time.perf_counter()
    row = first_row
    while written < cells:
        for field, kind in zip(fields, kinds):
            if written >= cells:
                break
            if code_of(report.SetValue(table, field, row, value_for(kind, written))) != 0:
                errors += 1
            written += 1
            if written % BLOCK_CELLS == 0:
                now = time.perf_counter()
                blocks.append(now - block_started)
                block_started = now
        row += 1
        if time.perf_counter() - started > STAGE_SECONDS_MAX:
            out.line("  stage stopped after {:.0f} s at {} of {} cells".format(time.perf_counter() - started, written, cells))
            break
    return written, time.perf_counter() - started, errors, blocks, row


def python_baseline(cells, fields, kinds):
    """The same loop with a no-op instead of SetValue: what Python itself costs."""
    def noop(*_args):
        return 0
    started = time.perf_counter()
    written, row = 0, 0
    while written < cells:
        for field, kind in zip(fields, kinds):
            if written >= cells:
                break
            code_of(noop("t", field, row, value_for(kind, written)))
            written += 1
        row += 1
    return time.perf_counter() - started


def create(out, report, table, fields):
    seconds, code = timed(report.CreateTable, table)
    if code:
        raise RuntimeError("CreateTable({}) returned {}".format(table, code))
    field_seconds = 0.0
    for field, kind in fields:
        spent, code = timed(report.CreateField, table, field, FIELD_TYPES[kind])
        field_seconds += spent
        if code:
            raise RuntimeError("CreateField({}.{}) returned {}".format(table, field, code))
    out.line("{}: CreateTable {:.2f} ms, CreateField {:.2f} ms per field ({} fields)".format(
        table, 1000 * seconds, 1000 * field_seconds / len(fields), len(fields)))


def main(app=None, printer=print):
    if app is None:
        import powerfactory
        app = powerfactory.GetApplication()
    out = Out(lambda text: app.PrintPlain(text) if hasattr(app, "PrintPlain") else printer(text))
    out.line("Outage Assessment IntReport write probe {} (ENABLED = {})".format(PROBE_VERSION, ENABLED))
    script = app.GetCurrentScript()
    report = script.GetParent() if script is not None else None
    kind = report.GetClassName() if report is not None else ""
    name = getattr(report, "loc_name", "") if report is not None else ""
    if kind != "IntReport":
        out.line("Not run: this ComPython must lie directly below an IntReport (found: {}).".format(kind or "nothing"))
        return out.lines
    if REPORT_NAME_MARKER not in name.lower():
        out.line("Not run: the IntReport's name must contain '{}'. Reset() clears every table of the report, so the "
                 "probe never runs below the Outage Assessment report.".format(REPORT_NAME_MARKER))
        return out.lines
    if not ENABLED:
        out.line("Not run: set ENABLED = True. The probe resets this IntReport and writes test tables into it.")
        return out.lines

    seconds, code = timed(report.Reset)
    out.line("Reset: {:.2f} ms (code {})".format(1000 * seconds, code))
    results = []
    for value_kind in ("number", "integer", "string"):
        table = "Probe" + value_kind.capitalize()
        create(out, report, table, [(field, value_kind) for field in WIDE_FIELDS])
        row = 0
        for cells in STAGE_CELLS:
            written, spent, errors, blocks, row = write_stage(out, report, table, WIDE_FIELDS, cells,
                                                              [value_kind] * len(WIDE_FIELDS), row)
            baseline = python_baseline(written, WIDE_FIELDS, [value_kind] * len(WIDE_FIELDS))
            results.append((value_kind, written, spent))
            out.line("  {} {:>7} cells: {:.2f} s, {}; errors {}; Python loop alone {:.2f} s".format(
                value_kind, written, spent, rate_text(written, spent), errors, baseline))
            if len(blocks) >= 2:
                out.line("    per {} cells: first block {:.2f} s, last block {:.2f} s".format(BLOCK_CELLS, blocks[0], blocks[-1]))
    create(out, report, "ProbeLong", LONG_FIELDS)
    cells = STAGE_CELLS[-1]
    written, spent, errors, blocks, _ = write_stage(out, report, "ProbeLong", [f for f, _ in LONG_FIELDS], cells,
                                                 [k for _, k in LONG_FIELDS])
    results.append(("long format", written, spent))
    out.line("  long format (run, element, step, value) {} cells = {} rows: {:.2f} s, {}; errors {}".format(
        written, written // len(LONG_FIELDS), spent, rate_text(written, spent), errors))

    numbers = [(written, spent) for kind_, written, spent in results if kind_ == "number" and written]
    written, spent = numbers[-1] if numbers else (0, 0.0)
    out.line()
    out.line("Estimates from the largest number stage ({}):".format(rate_text(written, spent)))
    for label, total in ESTIMATES:
        out.line("  {}: {} cells -> {}".format(label, grouped(total), duration_text(total * spent / written) if written else "n/a"))
    if CLEAN_UP:
        seconds, code = timed(report.Reset)
        out.line("Clean-up Reset: {:.2f} ms (code {}); the probe report is empty again.".format(1000 * seconds, code))
    out.line("done")
    return out.lines


if __name__ == "__main__":
    main()
