# GridLens and PowerFactory 2026 – how GridLens works with PowerFactory

This document describes everything GridLens does in PowerFactory 2026: how it
finds and reads objects, what it writes and puts back, how planned outages take
effect, how the quasi-dynamic simulation (QDS) and the contingency analysis
(n-1) run, and how the case configuration becomes calculations. As of GridLens
8.0.0, 24 October 2026. German version:
[`docs/de/POWERFACTORY.md`](de/POWERFACTORY.md). Both versions are maintained
together.

Every statement carries a status:

| Status | Meaning |
|---|---|
| **verified** | observed in PowerFactory 2026 (probe or test run, date given) |
| **used** | GridLens uses it and it ran in PowerFactory without error, but was not checked on purpose |
| **open** | an assumption or observation still to be confirmed |

Function names in `code` refer to `powerfactory/gridlens_report.py`.

---

## 1. Basics of the Python API

GridLens runs as a ComPython script in PowerFactory and needs only the
standard library and the `powerfactory` module.

```python
import powerfactory
app = powerfactory.GetApplication()          # the running PowerFactory session
script = app.GetCurrentScript()              # the ComPython that is running
study_case = app.GetActiveStudyCase()        # IntCase
project = app.GetActiveProject()             # IntPrj
qds = app.GetFromStudyCase("ComStatsim")     # command from the study case
clock = app.GetFromStudyCase("SetTime")      # study time (cDate, cTime)
app.PrintPlain("text")                       # output window
```

| What | How | Note |
|---|---|---|
| class of an object | `obj.GetClassName()` → `"ElmLne"` | GridLens checks the class of every object it finds before using it |
| name | `obj.loc_name` | the report shows only this short name |
| identity | `obj.GetFullName()` → path with classes | internal key (`object_key`); never shown in the report |
| read an attribute | `obj.<attribute>` or `getattr(obj, "attribute")`, else `obj.GetAttribute("attribute")` | `safe_attr` and `_read_setting` catch errors |
| write an attribute | `obj.<attribute> = value`, else `obj.SetAttribute("attribute", value)` | always read back and compared afterwards (`_set_scalar_attribute`) |
| contents of a folder | `obj.GetContents("*.Class")`, recursive `obj.GetContents("*.Class", 1)` | some objects accept only the first argument |
| calculation-relevant objects | `app.GetCalcRelevantObjects("*.ElmLne")` | only equipment of active grids |
| project folders | `app.GetProjectFolder("outage")`, `app.GetProjectFolder("netdat")` | operational library, network data |
| create an object | `folder.CreateObject("Class", "name")` | GridLens creates only `ComSimoutage`, `ComOutage` and the column buffer `IntVec` |
| copy an object | `target.AddCopy(obj)` → the copy (or a list) | for the kept result objects |
| delete an object | `obj.Delete()` | GridLens deletes only its own column buffer |
| start a calculation | `command.Execute()` → `0` on success | blocks until PowerFactory is done |

**Activating.** GridLens never calls `Activate()` or `Deactivate()`; it changes
neither project nor study case, operation scenario or variation. What a
calculation takes into account is controlled only through attributes:

| Switch | Object | Meaning |
|---|---|---|
| `iopt_maint` | `ComStatsim` | 1: the QDS applies planned outages |
| `isPlannedOutages` | `ComSimoutage` | 1: the n-1 calculation applies planned outages |
| `outserv` ("Ignored") | `IntPlannedout` | 1: this planned outage is skipped |
| `outserv` ("Not analysed") | `ComOutage` | 1: this contingency is not calculated |

---

## 2. Which objects GridLens finds, and where

| Object | Class | How it is found | Function |
|---|---|---|---|
| running script | `ComPython` | `app.GetCurrentScript()` | `execute_gridlens` |
| report | `IntReport` | parent of the script; without it GridLens runs standalone and publishes nothing | `execute_gridlens` |
| study case | `IntCase` | `app.GetActiveStudyCase()` | |
| QDS | `ComStatsim` | `app.GetFromStudyCase("ComStatsim")` | |
| study time | `SetTime` | `app.GetFromStudyCase("SetTime")` | `_restore_study_time` |
| planned outages | `IntPlannedout` | recursively below `app.GetProjectFolder("outage")`; the whole project only when none lies there | `_find_project_outages` |
| contingency analysis | `ComSimoutage` | `study_case.GetContents("*.ComSimoutage")`; exactly one, else n-1 is not calculated | `contingency_analysis` |
| contingencies | `ComOutage` | contents of the `ComSimoutage` | `contingency_equipment` |
| grids | `ElmNet` | `app.GetCalcRelevantObjects("*.ElmNet")` (active) and `GetProjectFolder("netdat")` (all) | `project_grids` |
| grid of an element | – | attribute `cpGrid`, else the `ElmNet` in its path | `element_grid_name` |
| results | `ElmRes` | after the QDS run `qds.results`; GridLens' copies in the study case | `_calculate_qds` |

The obsolete class `IntOutage` (where PowerFactory also stores demand
transfers) is not read.

---

## 3. What GridLens writes and how it puts it back

Every write is **read back** and compared. The values of one run go through
`StateGuard`: the old value is remembered, the new one written; at the end of
the block (also after an error) every value is put back in reverse order and
read back again. `iopt_maint` and the study time are set directly and restored
and verified in the "Restore" step. A value that cannot be restored stops the
run with `StateRestoreError`, naming the expected and the found value.

| Object | Attribute | When | Restored |
|---|---|---|---|
| `ComStatsim` | `iopt_maint` | 0 for REF, 1 for every case | after the calculation step (step 5) |
| `IntPlannedout` (all) | `outserv` | per run: 0 for the case's outages and the fixed ones, 1 for every other | after every run |
| `SetTime` | `cDate`, `cTime` | PowerFactory moves the study time while calculating | after every run |
| `ComSimoutage` | `isPlannedOutages` | 0 for n-1, 1 for (n-1)' | after every sweep |
| `ComSimoutage` | `calcPeriod`, `stepUnit`, `stepSize`, `startTime`, `endTime`, `stepNumber` | period of the sweep (section 7.3) | after every sweep |
| `ComOutage` | `outserv` | 1 for contingencies outside the chosen grids | after every sweep |

What GridLens **creates** and leaves in the study case:

- `GridLens_<yymmdd-HHMMSS>_<case>` (`ElmRes`): a copy of the results of each QDS run,
- `GridLens_<stamp>_<case>_N1` and `_N1P` (`ElmRes`): copies of the n-1 and (n-1)' results,
- `GridLens_<stamp>_N1` (`ComSimoutage`): only when the study case has no contingency analysis.

What GridLens **never** does: delete result objects, rebind
`ComStatsim.results`, create operation scenarios, variations or study cases,
change `starttime`/`endtime` of a planned outage or the QDS period. Own dates
per case and shorter QDS windows are only shown.

---

## 4. Planned outages

### 4.1 The object

In PowerFactory 2026 `IntPlannedout` is a **pure data object**. It has **no
`Apply`, `Reset` or `Check`** (verified, probe October 2026). GridLens reads:

| Attribute | Content |
|---|---|
| `starttime`, `endtime` | window in epoch seconds, half-open `[start, end)` |
| `components` | the switched equipment |
| `outserv` | labelled "Ignored"; 1 = PowerFactory skips the planned outage |
| `priority` | priority, shown only |
| contents (`GetContents("*", 1)`) | switching and load-transfer actions (`Evt*`, `Sta*`, `Int*`), shown only |

`_outage_parts` reads the affected equipment from `components` and further
reference attributes of the outage and its actions
(`OUTAGE_EQUIPMENT_ATTRIBUTES`).

### 4.2 How PowerFactory applies them

PowerFactory applies a planned outage itself **during the calculation** when
all three conditions hold (verified):

1. the calculation has planned outages switched on (`ComStatsim.iopt_maint = 1`
   or `ComSimoutage.isPlannedOutages = 1`),
2. the planned outage is not "Ignored" (`outserv = 0`),
3. the calculation time lies in its window.

PowerFactory applies **every** such planned outage, not only the one of
interest. GridLens therefore selects **which** apply through `outserv`: for a
run 0 for exactly the case's outages (and the fixed ones), 1 for all others
(`_isolate_outages`). PowerFactory then reports e.g. "Switch … opened",
"Outage … applied" and "1 Planned Outages were automatically applied". When
the set of active planned outages changes between two time points, PowerFactory
applies them anew (verified in the n-1 time sweep, 23 Oct 2026).

### 4.3 How GridLens checks that they take effect

- **Before every run** GridLens reads back what applies (`applied_text`):
  "'Planned outages' [iopt_maint] = 1; planned outages applied: …".
- **After the run** it checks every planned outage against REF in its window
  (`outage_effects`): **APPLIED** (a recorded component carries no load in the
  case but does in REF), **EFFECT SEEN**, **NO EFFECT** (warning) or **NOT
  CHECKABLE**. The report has one QA row `outages_<case>` per case.
- **In step 3** GridLens logs for every planned outage its data (every
  attribute, read through `dir()`) and what lies below it (switching actions
  with their data), or that nothing does – PowerFactory then isolates the
  components itself (`outage_contents_text`). Step 2 shows the QDS options with
  PowerFactory's own label (`GetAttributeDescription`), e.g. `iopt_action` and
  `iopt_rep`.
- **Around every QDS run** GridLens reads the state (`on_off`) of every
  calculation-relevant switch (`ElmCoup`, `StaSwitch`) before and after and
  logs each that changed (`switch_states`); GridLens itself switches nothing.
- **After the window end** GridLens checks in the results whether the
  outage's components still carry no load in the case while REF shows load
  (`outage_persistence`): log line "stays in effect after its window … for N h
  (until …)" or "back in service right at its window end", plus the QA row
  `outages_after_<case>`.

### 4.4 Open: switching state after the window end

In the first complete run (24 Oct 2026) a case with a two-hour planned outage
differed from REF at **almost every time step from the window end to the end of
the year**. This suggests that the QDS does **not close again** the switches
the planned outage opened (the switching state persists). GridLens assesses such
time steps as spill-over and warns in the QA ("Effect outside the outage
windows"); the caused hours become too large. To check: the loading of the
switched-off element in the case's kept result object after the window end,
and whether the planned outage needs a re-closing action or the QDS has an
option for it (candidates: `iopt_action` "Planned Outages: Processing
Actions"; `iopt_rep` "Planned Outages: Output" makes PowerFactory print every
action it applies). The log lines of 4.3 answer this in the next run.

---

## 5. Quasi-dynamic simulation (QDS)

### 5.1 Settings GridLens reads

| Attribute of `ComStatsim` | Meaning |
|---|---|
| `startTime`, `endTime` | simulated period, epoch seconds (`qds_period`) |
| `stepSize`, `stepUnit` | time step; `stepUnit` 0 s, 1 min, 2 h, 3 d (`qds_grid`) |
| `calcPeriod` | kind of period (logged only) |
| `iopt_maint` | apply planned outages (set) |
| `results` | bound result object (read only) |

All other settings (profiles, load-flow options) are used unchanged.

### 5.2 Calculating and keeping the results (verified 24 Oct 2026)

```python
code = qds.Execute()                 # 0 = success
produced = qds.results               # the ElmRes PowerFactory wrote into
copy = study_case.AddCopy(produced)  # copy AFTERWARDS
copy.loc_name = "GridLens_<stamp>_<case>"
```

- PowerFactory writes a QDS into **its own result object in the study case**.
  If the bound object has no variable selection (for instance a temporary one
  in the user folder `…\Set\Tmp\RecB`), PowerFactory binds a result object with
  its default variable selection (class-wide `IntMon`) on `Execute` and writes
  into it. Every further run writes into the same object and overwrites it.
- A copy made **after** the run with `AddCopy` keeps rows, columns, values and
  `IntMon` and stays unchanged after the next run. A copy made **before** the
  run of an object without variable selection records only `b:noconv` and
  `b:number`.
- GridLens therefore does not bind `ComStatsim.results`, calculates as
  configured and copies afterwards (`_calculate_qds`, `_case_result_object`).
  The binding PowerFactory sets is left as after a run by hand.
- If `ComStatsim.results` is bound to a kept GridLens object, GridLens stops
  before any calculation: the QDS would overwrite it.
- Right after the first run GridLens checks that the copy records loading or
  voltage (`check_recording`); otherwise it stops with `RecordingError` and
  names what is recorded.
- GridLens writes version, case and a fingerprint of the outages into the
  description (`desc`) of every copy; a kept run can thus be re-evaluated later
  without calculating (`kept_runs`).
- PowerFactory moves the study time to the last time point of the QDS;
  GridLens puts it back after every run.

### 5.3 Variables

Assessed are `c:loading` or `m:loading` of lines and transformers and `m:u` or
`m:u1` of terminals. The default selection of the QDS records `c:loading` and
`m:u` (verified). Other variables are read but not assessed; angles never.

---

## 6. Reading results (`ElmRes`)

```python
res.Load()                               # data into memory
rows = res.GetNumberOfRows()             # time steps
cols = res.GetNumberOfColumns()
var = res.GetVariable(col)               # "c:loading"
obj = res.GetObject(col)                 # the element of the column
err, value = res.GetValue(row, col)      # one cell; err != 0: no value
vec = script.CreateObject("IntVec", "GridLens_column_buffer")
res.GetColumnValues(vec, col)            # a whole column into vec.V
res.Release()
```

- GridLens reads column by column with `GetColumnValues` into an `IntVec` it
  creates in the running ComPython and deletes at the end
  (`open_column_buffer`, `read_column`); where that fails, cell by cell with
  `GetValue` (slow, counted in the run summary).
- The time column gives the absolute time axis; GridLens checks that REF and
  every case share it.
- NaN, infinity, `None`, booleans and error codes are no measurements. A
  voltage below 0.1 p.u. or NaN counts as de-energised.
- The grid filter (`cpGrid`) applies before values are read.
- **In the log (step 6)** every result object is described
  (`result_object_text`): number of time steps, first and last, step, span,
  columns by class and by variable. For every planned outage of a case it
  follows, per recorded component, in how many steps the component carries no
  load inside and outside the window, and the same for REF
  (`outage_component_lines`).

---

## 7. Contingency analysis (n-1 and (n-1)')

### 7.1 The command and the contingencies

- GridLens uses the **one** `ComSimoutage` of the active study case. Without
  one (e.g. in the QDS study case) it creates `GridLens_<stamp>_N1`
  (`create_contingency_analysis`): one `ComOutage` per calculation-relevant
  element of the classes `ElmLne`, `ElmBranch`, `ElmZpu`, `ElmTr2`, `ElmTr3`,
  `ElmTr4`, `ElmSind`, `ElmScap`, `ElmShnt`, `ElmSvs`, `ElmVsc`, `ElmVscmono` in
  the chosen grids – no generators, loads or busbars. A line inside an
  `ElmBranch` counts through the branch.

```python
ca = study_case.CreateObject("ComSimoutage", name)
ca.iEnableTS = 1                               # time sweep on
fault = ca.CreateObject("ComOutage", element.loc_name)
fault.SetObjs([element])                       # 0 = success
```

- GridLens reads the equipment a contingency switches with
  `ComOutage.GetObject(i)` for i = 0, 1, … until `None` (`contingency_equipment`).
- Contingencies outside the n-1 grids, or outaging none of the elements chosen
  in the n-1 element filter, are set to "Not analysed" for the run (`ComOutage.outserv = 1`,
  verified 23 Oct 2026; `excluded_contingencies`). Where the filters act, also in
  a re-evaluation: [`CALCULATION_AND_EVALUATION.md`](CALCULATION_AND_EVALUATION.md).

### 7.2 Planned outages in the sweep

`isPlannedOutages = 1` applies the planned outages at every time point of their
window (verified). n-1 runs with `isPlannedOutages = 0` (or only the fixed
ones), (n-1)' with the case's outages; they are selected through
`IntPlannedout.outserv` as for the QDS. A contingency whose equipment the
planned outage already switches off is missing from the results ("none of the
interrupted components is relevant") and is reported as `NOT_APPLICABLE`.

### 7.3 Time points of the sweep (verified 24 Oct 2026)

With `calcPeriod = 4` the contingency analysis calculates from `startTime` to
`endTime` (**exclusive**) in steps of `stepSize`/`stepUnit`; the `studyTime`
vector is then **ignored**, even when it is written and reads back unchanged.
(In the test run of 23 Oct another `calcPeriod` was set; there the sweep
followed `studyTime`.) GridLens therefore writes the period for every sweep
(`sweep_period`, `run_n1_sweep`):

| Attribute | Value |
|---|---|
| `calcPeriod` | 4 |
| `stepUnit`, `stepSize` | the QDS time step (`step_setting`) |
| `startTime` | first QDS step inside the case's windows |
| `endTime` | last QDS step inside the windows + one step |
| `stepNumber` | number of steps (when readable) |

When windows lie apart, the steps between them are calculated but not assessed;
a period above the n-1 limit is refused. Right after the sweep GridLens checks
that every time point inside the windows was calculated.

### 7.4 Results

- `ComSimoutage.p_rescnt` references an `ElmRes` with **one sub-`ElmRes` per
  time point**; its `cnttime` is the time point (verified).
- In a sub-result the **rows are the contingencies** and the **columns the
  equipment** (`c:loading`, `m:u`). Contingencies without a relevant component
  are missing.
- PowerFactory does not write values inside the recording limits (`loadmax`,
  `vlmin`, `vlmax`): `GetValue` returns code 3. GridLens counts them as "within
  the limit" when the limit proves it.
- After every sweep GridLens copies `p_rescnt` into the study case as `…_N1`
  or `…_N1P` (`keep_copy`); the recording limits go into `desc`.
- **In the log (step 6)** every n-1 result is described (`n1_data_text`): how
  many study times were assessed and calculated and of how many QDS steps of
  the period (the others are not calculated), contingencies × equipment with a
  value per study time, the number of values and of values inside the
  recording limits; for (n-1)' also which contingencies of n-1 are missing
  (their equipment is already switched off by the case).

---

## 8. Defining the cases

### 8.1 Configuration

The cases come from the case manager (`CASE_SOURCE = 'gui'`), from the saved
file (`'saved'`, JSON under `CASE_CONFIG_DIR`) or one per planned outage
(`'per_outage'`). The file has schema `gridlens.cases` version 2:

```json
{"schema": "gridlens.cases", "schema_version": 2, "revision": 3,
 "assessments": ["n-0", "n-1", "(n-1)'"],
 "background": ["<key of a fixed planned outage>"],
 "cases": [{"id": "C1", "name": "…", "description": "…",
            "outages": ["<key>", "…"], "enabled": true, "overrides": {}}],
 "settings": {}}
```

A key is the full PowerFactory path of the `IntPlannedout`; a case lists any
number of occurrences. Cases are never combined automatically.

### 8.2 From case to calculation

| Term | Meaning | Function |
|---|---|---|
| REF | R0: no planned outage (`iopt_maint = 0`); Rfix: only the fixed ones (`iopt_maint = 1`) | `_calculate_reference` |
| planning case | the case's occurrences plus the fixed ones, all others "Ignored", one QDS run | `_calculate_case` |
| window | `starttime`/`endtime` of the planned outage; own dates are recorded but not applied | `_occurrence_window` |
| network states | between two window boundaries the active set is the same | `network_states` |
| fingerprint | the same outages with the same windows give the same result; such cases are calculated once (`REUSED`) | `plan_fingerprint` |
| n-1 / (n-1)' | per case one sweep without and one with its outages, over the QDS steps inside its windows | `calculate_n1_case` |

### 8.3 Course of a run

1. Startup, context, report or standalone run.
2. Log the ComStatsim settings.
3. Read the planned outages, case manager, check the cases.
4. **Calculate** (phase 1): REF, every case (QDS, copy afterwards), then n-1 and (n-1)'.
5. **Restore**: study time, `iopt_maint`; every written value verified.
6. **Evaluate** (phase 2): read the kept copies and compare them with REF.
7. Build the report tables and, below an `IntReport`, publish them.

A kept run can be re-evaluated without calculating under *Results* in the case
manager.

---

## 9. Verified and open

| Statement | Status |
|---|---|
| `IntPlannedout` has no `Apply`/`Reset`/`Check`; applied through `iopt_maint` + `outserv` + window | verified (Oct 2026) |
| `isPlannedOutages` applies planned outages per time point in the sweep | verified (23 Oct 2026) |
| `ComOutage.outserv = 1` takes a contingency out of the calculation | verified (23 Oct 2026) |
| the QDS writes into its own result object; a copy afterwards keeps everything | verified (24 Oct 2026) |
| `calcPeriod = 4`: sweep over `startTime`…`endTime`, `studyTime` ignored | verified (24 Oct 2026) |
| one sub-result per time point, rows = contingencies, code 3 = not recorded | verified (23 Oct 2026) |
| `GetColumnValues(IntVec, column)` fills `IntVec.V` | used (24 Oct 2026) |
| `CreateObject` of `ComSimoutage`/`ComOutage`, `SetObjs` | open (not yet run in PowerFactory) |
| the switching state of a planned outage persists in the QDS after the window end | open (section 4.4) |
| two planned outages on the same element | open |
| the case manager (tkinter) inside PowerFactory | used |

Further assumptions (P1–P10) and the test matrix are in
[`ARCHITECTURE.md`](ARCHITECTURE.md) and [`TEST_MATRIX.md`](TEST_MATRIX.md).

---

## 10. Recipes for scripts by hand

**Calculate one planned outage alone and keep the result**

```python
outages = app.GetProjectFolder("outage").GetContents("*.IntPlannedout", 1)
saved = {o: o.outserv for o in outages}
for o in outages:
    o.outserv = 0 if o.loc_name == "MY_OUTAGE" else 1
old = qds.iopt_maint
qds.iopt_maint = 1
try:
    qds.Execute()
    copy = study_case.AddCopy(qds.results)
    copy.loc_name = "My_outage_result"
finally:
    qds.iopt_maint = old
    for o, value in saved.items():
        o.outserv = value
```

**Read one column of a result object**

```python
res = copy
res.Load()
for col in range(res.GetNumberOfColumns()):
    if res.GetVariable(col) == "c:loading" and res.GetObject(col).loc_name == "MY_LINE":
        values = [res.GetValue(row, col)[1] for row in range(res.GetNumberOfRows())]
res.Release()
```

**Calculate n-1 for a period**

```python
ca = study_case.GetContents("*.ComSimoutage")[0]
old = {a: getattr(ca, a) for a in ("calcPeriod", "startTime", "endTime", "stepSize", "stepUnit")}
ca.calcPeriod, ca.stepSize, ca.stepUnit = 4, 1, 2           # hourly
ca.startTime, ca.endTime = start, end                       # epoch seconds, end exclusive
try:
    ca.Execute()
    for sub in ca.p_rescnt.GetContents("*.ElmRes"):
        print(sub.cnttime, sub.GetNumberOfRows())
finally:
    for a, value in old.items():
        setattr(ca, a, value)
```

Put the study time (`SetTime.cDate`, `cTime`) back after every calculation if
it is to stay.
