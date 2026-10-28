# Inspect a saved PowerFactory result object

Use [`powerfactory_tests/inspect_result_data.py`](../powerfactory_tests/inspect_result_data.py) as a
**separate ComPython script in PowerFactory**. It is standalone and needs only
Python's standard library and PowerFactory's own Python module. It does not
import or run GridLens.

## Run it

1. Copy the entire script into a ComPython, or configure that ComPython to use
   the script file.
2. Set the name at the top, for example:

   ```python
   RESULT_NAME = "GridLens_261024-103000_C1"
   ```

3. Run the ComPython with the appropriate project active.
4. The PowerFactory output window prints an inventory, progress and the path
   to `report.txt`. Open that file or `summary.json` first.

Leave `RESULT_NAME = ""` to list available `ElmRes` paths without creating any
output files. Names are exact: the active study case is searched first, then
the active project. If multiple matches exist in that scope, use the complete
`GetFullName()` path printed by the script. A `.ElmRes` suffix is accepted.

Output goes into a new, uniquely named local folder under
`~/GridLens/result_inspections/`. To change it, set, for example:

```python
OUTPUT_DIRECTORY = r"C:\Users\your_name\Documents\GridLens inspections"
```

## What it explores

The default settings inspect the complete selected result tree, including
nested `ElmRes` objects and recording-definition children such as `IntMon`.
No result-row or result-column sampling is used.

- Result and child-object names, full paths, classes, parents and hierarchy.
- Readable, discoverable attributes, with values, types, descriptions, units
  and shapes where the installed API supports them.
- Public method names and their API docstrings. Arbitrary discovered methods
  are listed, **never executed**.
- Result-object count, readable and unreadable results, rows, columns, cells,
  finite values, non-finite values and every cell-status frequency.
- Unique recorded objects and unique equipment by PowerFactory class.
  Equipment recorded in several columns or sub-results is counted once by
  full object path. Unresolved owners are reported separately per result.
- Every variable, unit, description, associated object and duplicate
  object-variable column. Global counts distinguish variable names from the
  number of columns recording those names.
- Current grid, type reference, nominal voltage, service state and description
  of column owners where these fields are directly exposed. This is current
  model context, **not** a reconstruction of the historical network state.
- All raw cell values and their return codes in separate CSVs. Object-valued
  cells are also probed and successfully resolved references are exported.
- Finite-value counts, zeros, positive/negative values, minimum, maximum,
  first/last finite values, mean and population standard deviation per column.
  Extreme values retain their row index and axis value.
- Implicit index column `-1`, explicit time columns, every row-to-object
  mapping the API exposes, and contingency-object identities.
- First/last/minimum/maximum axis values, recognized time units, duration,
  time-step histogram, duplicate values, descending steps, and candidate gaps.
- Unique `cnttime` values across contingency sub-results, independently of
  their fault-row counts. Their time span is reported in hours.
- Unsupported metadata queries and failed reads, including method, arguments
  and exception message.

## Reading the hours and counts correctly

**Four hourly timestamps can span three hours.** For example, timestamps at
00:00, 01:00, 02:00 and 03:00 give:

```text
row_count: 4
span_hours: 3
nominal_interval_hours_if_each_row_covers_one_step: 4
```

The last number assumes every row represents a complete interval. It is not
proof of the simulation end time. The explorer reports this assumption instead
of silently adding a time step.

If units are missing, or the index represents contingencies, the explorer does
not invent a duration. A longer step is a **candidate gap** relative to the
smallest positive step; it can also be intentional variable-step recording.
Large time values get UTC/local calendar interpretations explicitly labeled
as POSIX-epoch candidates.

For contingency results, rows can be faults and child results can be study
times. Adding all rows as hours would be incorrect. Counts summed across
sub-results are therefore labeled as sums, and equipment, fault identities and
`cnttime` study times are deduplicated separately.

**Code 3 is not a measured zero.** It means the value was not recorded in sparse
result storage. The script keeps the code and raw payload and excludes it from
numeric statistics. Other nonzero codes, NaN, infinity, booleans and non-numeric
payloads are also excluded from finite-number statistics. Object-cell lookup
statuses are separate from numeric-cell statuses: failure to resolve an object
from a numeric column does not invalidate that column's numeric values.

## Files

| File | Contents |
|---|---|
| `report.txt` | Combined detailed text report, every column's statistics and all inspected-object metadata |
| `summary.json` | Overall inventory and each result object's summary |
| `hierarchy.json` | Selected-object tree and the folder for every inspected object |
| `equipment.json` | Deduplicated equipment referenced by result columns |
| `recorded_objects.json` | All readable column owners, including non-equipment objects |
| `recorded_object_context.json` | Current grid/type/service-state context of those owners |
| `grids.json` | Unique current grid references exposed by column owners |
| `row_objects.json` | Deduplicated row objects, including contingencies |
| `read_errors.jsonl` | One JSON record for every caught read exception |
| `objects/.../metadata.json` | Attributes, discovery evidence, public methods and parent identity |
| `objects/.../result_summary.json` | Dimensions, recording/read status, variables, counts and axis interpretation |
| `objects/.../columns.csv` / `columns.json` | Mapping of CSV keys such as `c000012` to original columns, objects, variables and units |
| `objects/.../rows.csv` | Implicit index, selected time/index axis and row-object mapping for every row |
| `objects/.../data_values.csv` | Every raw value, using stable column keys |
| `objects/.../data_codes.csv` | Corresponding return code for every raw value |
| `objects/.../object_cells.jsonl` | Successfully resolved object-valued cell references |
| `objects/.../statistics.csv` / `statistics.json` | Full finite-value statistics per column |

CSV files use UTF-8 with a BOM and Python's CSV quoting. `columns.csv` must be
used to interpret the stable keys in `data_values.csv` and `data_codes.csv`.

## Scope, performance and API limits

The script reads every cell, and by default also probes each cell for an object
reference. It streams CSVs to disk rather than holding the result matrix in
Python memory. Statistics use a streaming algorithm; axis values and recording
metadata remain in memory. A full-year result with many columns can take a long
time and produce large files. Progress is printed at least every five seconds
while scanning rows; individual blocking PowerFactory API calls cannot report
intermediate progress.

For subsequent runs you can deliberately set:

```python
EXPORT_ALL_VALUES = False      # still scans every cell for full statistics
RESOLVE_OBJECT_CELLS = False   # skip object lookup for individual data cells
INSPECT_SUBRESULTS = False     # inspect only the selected result, with exclusions listed
```

These are explicit scope changes and are recorded in the output. The defaults
perform the full inspection.

It does not calculate, activate or change any PowerFactory object, and it does
not create a column-buffer object or run an export command. `Load` and `Release`
only manage reading the stored results. There is no network access in the
script. Raw names, paths and values are written into local files as requested.

“Complete” means all rows/columns attempted and all metadata discoverable
through the available read interfaces. Hidden/internal attributes cannot be
guaranteed. Result selectors are not changed, inaccessible results remain
explicitly marked, and linked objects outside the selected tree are exported
as references rather than recursively expanding the entire network. Python
metadata cycles and structures deeper than 20 levels receive explicit markers.
The original discovery returns are preserved so incomplete enumeration can be
distinguished from an empty object. An exception in an optional metadata query
does not necessarily mean the stored results are corrupt.

The cell-reading approach follows [DIgSILENT's ElmRes reading guidance](https://www.digsilent.de/index.php/en/faq-reader-powerfactory/how-can-i-read-data-from-a-result-file-elmres-via-script.html).
Cellwise access preserves sparse return codes; bulk column reads require an
additional `IntVec` object, which this read-only inspector does not create.

## Validation

```sh
.venv/bin/python -m pytest -q tests/test_inspect_result_data.py
```

Tests use synthetic PowerFactory objects, covering dense and sparse results,
sub-results, object-valued cells, missing reads, time interpretation, duplicate
names, exact equipment counts and the absence of PowerFactory write calls.
Execution against the installed PowerFactory API must be confirmed in an
actual PowerFactory session.
