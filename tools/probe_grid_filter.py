"""GridLens probe: show which elements the grid filter assesses and ignores.

A stand-alone diagnostic: it needs nothing but PowerFactory. It only reads;
nothing is calculated, written or published.

Create a ComPython for this file anywhere in the active study case and run it
once. It applies the same grid filter as gridlens_report.py and prints

1. every grid in the project and whether GRID_NAME_FILTER selects it,
2. for a few elements per class, how the grid was determined,
3. for all calculation-relevant elements, how many are in and out of scope,
   and whether the attribute "Grid" (cpGrid) and the element's storage path
   ever disagree,
4. for the result object bound to ComStatsim, exactly which result series
   the report would assess and which it would skip, grouped by grid.
"""

import time

ELEMENT_CLASSES = ("ElmLne", "ElmTr2", "ElmTr3", "ElmTerm")
EXAMPLES_PER_GROUP = 5
# Keep the probe quick on large models: at most this many elements per class
# and result columns are inspected. The output says when a limit applied.
MAX_ELEMENTS_PER_CLASS = 5000
MAX_RESULT_COLUMNS = 40000


def emit(app, message=""):
    printer = getattr(app, "PrintPlain", None)
    if callable(printer):
        try:
            printer(message)
            return
        except Exception:
            pass
    print(message, flush=True)


# --- The grid filter, kept identical to gridlens_report.py ------------------
# tests/test_probe_grid_filter.py fails if the two ever behave differently.

GRID_NAME_FILTER = ''  # type a grid name part here to preview what it would select
VARIABLES = {'line': ('c:loading', 'm:loading'), 'transformer': ('c:loading', 'm:loading'), 'voltage': ('m:u', 'm:u1')}
CLASS_CATEGORIES = {'ElmLne': ('line',), 'ElmTr2': ('transformer',), 'ElmTr3': ('transformer',), 'ElmTerm': ('voltage',)}


def safe_attr(obj, name, default=None):
    try:
        value = getattr(obj, name)
        return default if value is None else value
    except Exception:
        return default


def object_key(obj):
    try:
        value = obj.GetFullName()
        if value:
            return str(value)
    except Exception:
        pass
    return str(safe_attr(obj, 'loc_name', 'unknown'))


def object_name(obj):
    value = safe_attr(obj, 'loc_name', '')
    return str(value) if value else object_key(obj).rsplit('\\', 1)[-1]


def class_name(obj):
    try:
        return str(obj.GetClassName())
    except Exception:
        return ''


def element_grid_name(obj):
    """Name of the grid an element belongs to; '' when it has none."""
    grid = safe_attr(obj, 'cpGrid')
    if grid is not None and not isinstance(grid, (str, int, float, bool)):
        name = object_name(grid)
        if name:
            return name
    for part in reversed(object_key(obj).split('\\')):
        if part.endswith('.ElmNet'):
            return part[:-len('.ElmNet')]
    return ''


def element_in_scope(obj):
    return not GRID_NAME_FILTER or GRID_NAME_FILTER in element_grid_name(obj)


def result_category(obj, variable):
    for category in CLASS_CATEGORIES.get(class_name(obj), ()):
        if variable in VARIABLES[category]:
            return category
    return None


# --- Probe --------------------------------------------------------------------

def grid_source(obj):
    """How element_grid_name found the grid: cpGrid, path or none."""
    grid = safe_attr(obj, "cpGrid")
    if grid is not None and not isinstance(grid, (str, int, float, bool)) and object_name(grid):
        return "cpGrid"
    if any(part.endswith(".ElmNet") for part in object_key(obj).split("\\")):
        return "path"
    return "none"


def path_grid(obj):
    for part in reversed(object_key(obj).split("\\")):
        if part.endswith(".ElmNet"):
            return part[:-len(".ElmNet")]
    return ""


def calc_relevant(app, pattern):
    try:
        return list(app.GetCalcRelevantObjects(pattern, 1) or [])
    except TypeError:
        try:
            return list(app.GetCalcRelevantObjects(pattern) or [])
        except Exception:
            return []
    except Exception:
        return []


def section(app, title):
    emit(app)
    emit(app, "=== {} ===".format(title))


def report_grids(app):
    section(app, "1. GRIDS")
    grids = {}
    for grid in calc_relevant(app, "*.ElmNet"):
        grids[object_key(grid)] = (grid, "active")
    try:
        project = app.GetActiveProject()
        for grid in project.GetContents("*.ElmNet", 1) or []:
            grids.setdefault(object_key(grid), (grid, "inactive"))
    except Exception:
        pass
    if not grids:
        emit(app, "  No ElmNet found in the active project.")
        return
    for key in sorted(grids, key=lambda k: object_name(grids[k][0]).casefold()):
        grid, state = grids[key]
        name = object_name(grid)
        selected = not GRID_NAME_FILTER or GRID_NAME_FILTER in name
        emit(app, "  [{}] {:<40} {:<8}".format("IN " if selected else "out", name, state))


def report_examples(app):
    section(app, "2. HOW THE GRID IS DETERMINED (examples)")
    for element_class in ELEMENT_CLASSES:
        objects = calc_relevant(app, "*." + element_class)
        emit(app, "  {} ({} calculation-relevant)".format(element_class, len(objects)))
        shown = 0
        for obj in objects:
            if shown >= 3:
                break
            shown += 1
            raw = safe_attr(obj, "cpGrid")
            raw_text = "{} '{}'".format(class_name(raw), object_name(raw)) if raw is not None and hasattr(raw, "GetClassName") else repr(raw)
            emit(app, "    {:<32} cpGrid={:<36} path-grid='{}' -> grid='{}' via {} -> {}".format(
                object_name(obj)[:32], raw_text[:36], path_grid(obj),
                element_grid_name(obj), grid_source(obj),
                "ASSESSED" if element_in_scope(obj) else "ignored"))


def report_elements(app):
    section(app, "3. ALL CALCULATION-RELEVANT ELEMENTS")
    for element_class in ELEMENT_CLASSES:
        objects = calc_relevant(app, "*." + element_class)
        total = len(objects)
        objects = objects[:MAX_ELEMENTS_PER_CLASS]
        inside = outside = no_grid = disagree = 0
        by_grid = {}
        disagree_examples = []
        for obj in objects:
            grid = element_grid_name(obj)
            by_grid[grid or "<no grid>"] = by_grid.get(grid or "<no grid>", 0) + 1
            if not grid:
                no_grid += 1
            if element_in_scope(obj):
                inside += 1
            else:
                outside += 1
            stored = path_grid(obj)
            if grid and stored and grid != stored:
                disagree += 1
                if len(disagree_examples) < EXAMPLES_PER_GROUP:
                    disagree_examples.append("{} (cpGrid '{}', stored in '{}')".format(
                        object_name(obj), grid, stored))
        emit(app, "  {:<8} total {:>6}{} | assessed {:>6} | ignored {:>6} | without grid {:>4} | cpGrid differs from path {:>4}".format(
            element_class, total, " (first {} inspected)".format(len(objects)) if total > len(objects) else "",
            inside, outside, no_grid, disagree))
        for grid, count in sorted(by_grid.items(), key=lambda entry: -entry[1])[:8]:
            selected = grid != "<no grid>" and (not GRID_NAME_FILTER or GRID_NAME_FILTER in grid)
            emit(app, "      [{}] {:<40} {:>6}".format("IN " if selected else "out", grid, count))
        for example in disagree_examples:
            emit(app, "      differs: " + example)


def report_result_series(app):
    section(app, "4. RESULT SERIES THE REPORT WOULD READ")
    getter = getattr(app, "GetFromStudyCase", None)
    qds = getter("ComStatsim") if callable(getter) else None
    result = safe_attr(qds, "results") if qds is not None else None
    if result is None:
        emit(app, "  No ComStatsim.results bound; nothing to inspect.")
        return
    emit(app, "  Result object: '{}'".format(object_name(result)))
    try:
        result.Load()
    except Exception as exc:
        emit(app, "  Load() failed: {}".format(exc))
    try:
        columns = int(result.GetNumberOfColumns())
    except Exception as exc:
        emit(app, "  GetNumberOfColumns() failed: {}".format(exc))
        return
    if columns <= 0:
        emit(app, "  The result object holds no columns yet. Run the quasi-dynamic")
        emit(app, "  simulation once, then run this probe again for this section.")
        return
    inspected = min(columns, MAX_RESULT_COLUMNS)
    started = time.monotonic()
    assessed, skipped = {}, {}
    examples_in, examples_out = [], []
    unsupported = 0
    for column in range(inspected):
        try:
            obj = result.GetObject(column)
            variable = str(result.GetVariable(column))
            category = result_category(obj, variable)
        except Exception:
            unsupported += 1
            continue
        if not category or variable not in VARIABLES[category]:
            unsupported += 1
            continue
        grid = element_grid_name(obj) or "<no grid>"
        if element_in_scope(obj):
            assessed[grid] = assessed.get(grid, 0) + 1
            if len(examples_in) < EXAMPLES_PER_GROUP:
                examples_in.append("{} {} [{}] in '{}'".format(class_name(obj), object_name(obj), variable, grid))
        else:
            skipped[grid] = skipped.get(grid, 0) + 1
            if len(examples_out) < EXAMPLES_PER_GROUP:
                examples_out.append("{} {} [{}] in '{}'".format(class_name(obj), object_name(obj), variable, grid))
    elapsed = time.monotonic() - started
    emit(app, "  Columns: {}{}; not a GridLens variable: {}; filter time {:.1f} s ({:.0f} us per column)".format(
        columns, " (first {} inspected)".format(inspected) if inspected < columns else "",
        unsupported, elapsed, 1e6 * elapsed / max(inspected, 1)))
    emit(app, "  ASSESSED series: {}".format(sum(assessed.values())))
    for grid, count in sorted(assessed.items(), key=lambda entry: -entry[1])[:10]:
        emit(app, "      {:<40} {:>7}".format(grid, count))
    for example in examples_in:
        emit(app, "      e.g. " + example)
    emit(app, "  IGNORED series: {}".format(sum(skipped.values())))
    for grid, count in sorted(skipped.items(), key=lambda entry: -entry[1])[:10]:
        emit(app, "      {:<40} {:>7}".format(grid, count))
    for example in examples_out:
        emit(app, "      e.g. " + example)
    if not assessed:
        emit(app, "  !! No series would be assessed: the report would stop with a")
        emit(app, "     message about GRID_NAME_FILTER.")


def main():
    try:
        import powerfactory
    except ImportError:
        print("Run this probe from DIgSILENT PowerFactory 2026.", flush=True)
        return
    app = powerfactory.GetApplication()
    if app is None:
        print("PowerFactory returned no application object.", flush=True)
        return
    emit(app, "=== GridLens grid-filter probe (read-only) ===")
    emit(app, "GRID_NAME_FILTER : {!r}".format(GRID_NAME_FILTER))
    for step in (report_grids, report_examples, report_elements, report_result_series):
        try:
            step(app)
        except Exception as exc:
            emit(app, "  !! {} failed: {}: {}".format(step.__name__, type(exc).__name__, exc))
    emit(app)
    emit(app, "Probe finished. Nothing in the project was changed.")


if __name__ == "__main__":
    main()
