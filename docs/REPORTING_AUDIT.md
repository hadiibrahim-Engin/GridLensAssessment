# GridLens reporting – audit, mapping and plan (gate A)

Gate A of `GridLens_Coding_Agent_Arbeitsauftrag_Reporting.md` (the binding
reporting assignment, repository root): what exists, what the two new reports
need, how every report element maps to PowerFactory results, which API
questions are open and in which steps gates B–D follow. As of 26 October 2026.
German version: [`docs/de/BERICHTSWESEN_AUDIT.md`](de/BERICHTSWESEN_AUDIT.md);
both are maintained together.

No PowerFactory calculation was started for this audit; everything below is
read from the repository, the template and earlier probe runs.

---

## 1. Input template

| Check | Result |
|---|---|
| File | `powerfactory/MASTER_GRIDLENS.mrt`, MRT 6.2.0, data contract 6.2 |
| Identity with `MASTER_GRIDLENS(1).mrt` of the assignment | the assignment describes 21 pages, 23 `Scripted…` data sources, the four contingency tables and an empty SQLite connection string: exactly this file. `MASTER_GRIDLENS(1).mrt` itself is not on this machine; the name is taken as a download copy of it. |
| Backup | `templates/archive/MASTER_GRIDLENS_6.2.0_original.mrt`, read-only, SHA-256 `d541c80d8469bb37…` (identical to the input) |
| Pages | Cover, Contents, Quality, Cases, Casedef, Reference, Metrics, Summary, Comparison, **Radar**, Toplines, **Trendmost**, **Trenddelta**, Topcase, Contingency, Findings, Evidence, Appendix, Appa, Appb, Appc |
| Charts | 17 line, **7 radar**, 2 pie, 1 bar, 1 column; up to 7 series in one chart |
| Colours | DIgSILENT red `[181:18:62]`, greys, warning yellow, fixed case palette. The assignment mentions navy/teal; the template has none. The **actual** design is kept. |
| Cover | `CoverRow1_L` "Study ID" / `CoverRow1_V` `{ScriptedReportMeta.study_id}`: to be removed, rows below moved up |
| LODF | none (removed in 8.0; tests forbid it) |
| Connection | empty (`<ConnectionStringEncrypted />`); PowerFactory sets the database per IntReport at run time |
| PDF path | GridLens publishes the tables into its `IntReport`; PowerFactory renders the MRT as a separate step (decision of 28 Sep 2026: no `IntReport.Execute()` from the script) |

---

## 2. Current state against the assignment

| Assignment | Current state | Gap / action |
|---|---|---|
| §1 n-0 = QDS of the base network without planned outages | REF R0 (`iopt_maint = 0`); Rfix with fixed outages | fits; Rfix is labelled as such |
| §1 n-1 = time-sweep contingency analysis of the base network | `ComSimoutage`, `isPlannedOutages = 0`, period written as `calcPeriod = 4` | fits |
| §1 (n-1)' = time sweep per FS scenario with its active planned outages | same sweep, `isPlannedOutages = 1`, only the case's outages not "Ignored" | fits |
| §1 time base unchanged from `ComStatsim` | QDS: full period. **n-1/(n-1)': only the QDS steps from the first to the last window hour of a case** (decision 23 Oct 2026) | **decision D1** (section 6). The reporting core reports whatever was calculated and shows requested against actual time points (coverage axis a). |
| §1 FS pre-fault state | every case already runs its own **QDS with its planned outages** (explicit, not silent): native pre-fault values over the whole period | kept and labelled "FS pre-fault state (QDS with the case's outages)" |
| §1 already switched-off equipment as contingency | `NOT_APPLICABLE` via `ComOutage.GetObject` ∩ `IntPlannedout.components` (verified 23 Oct) | fits |
| §2 persistent results as named `ElmRes` | `GridLens_<stamp>_REF`, `…_<case>`, `…_<case>_N1`, `…_<case>_N1P` (copies after the run, verified 24 Oct) | fits; the stamp becomes the **run ID** |
| §2 statistics in the evaluation core, not in MRT expressions | yes | fits |
| §2 no CSV/Excel/JSON result exports | none; only the case configuration is JSON (settings, not results) | fits |
| §2 streaming, no dense cube | QDS: arrays per series and run; **n-1: `read_n1_results` holds every value of a whole sweep in one dict** | **gate B**: read and classify per study time (reference and scenario sub-result side by side), aggregate, discard |
| §5 status codes 0–5, 90–93, `MARGIN_REDUCED` | `CLASSIFICATION_STATUSES` exactly these | fits |
| §5 comparison key: time, contingency, element, criterion, post-fault phase | `COMPARISON_IDENTITY` exactly these | fits |
| §5 under- and overvoltage separately | one quantity `voltage` with a band | **gate B**: criteria `loading`, `voltage_low`, `voltage_high` |
| §5 result ID incl. run, scenario, timestamp, contingency, phase, element, criterion | identity without run and scenario | **gate B**: add both |
| §6 statistics 1–10 per scenario and level | only worst status per element and result counts | **gate B**: statistics layer (distinct elements, events, contingencies, time points, episodes, extremes, coincident worsening, coverage on three axes) |
| §6 episodes (consecutive examined support points) | none | **gate B** |
| §3/§4 two reports | one report | **gate C**: main and detail template on one data contract; decision D2 |
| §4 detail: every conspicuous element, no top-N | appendices only above thresholds; n-1 findings cut at 40 per case | **gate C**: no hidden cut in the detail report |
| §7 more than 6 scenarios | matrix tables in blocks of 6 (`case_a`–`case_f`), charts draw REF + 6 | detail: blocks of 3 with repeated element and n-1 column; any number of blocks |
| §7 colours per status | violation 0/1/2 only | **gate C**: status palette (NEW red, WORSENED orange-red, PRE-EXISTING yellow, IMPROVED teal, RESOLVED green, quality grey), always with text |
| §3 no radar, no 5–6-line time plots | chapter 10 radar, chapters 12/13 REF + 6 cases | **gate C**: removed; at most one n-1/(n-1)' time comparison of one line under one contingency |
| §3 Gantt, stacked bars, time criticality, heatmap, contingency ranking | none | **gate C**; Gantt and heatmap first proven in the local Stimulsoft engine |
| §9 synthetic 5,000-node profile | test data of a few elements | **gate B**: sparse generator, marked as test data |

---

## 3. Mapping of today's report

Report element → table → aggregation (function) → PowerFactory result → quality check.

| Chapter | Table | Aggregation | PowerFactory result | Quality check |
|---|---|---|---|---|
| Cover, header, footer | `ScriptedReportMeta` | `build_cases_payload` | study case, project, `ComStatsim` period | – |
| 3 Model quality | `ScriptedModelQuality` | `_model_quality`, `outage_quality`, `persistence_quality`, `n1_quality` | all kept objects | the page itself |
| 4/5 Cases | `ScriptedCases` | `_case_rows`, verdict `assess_case` | `GridLens_<stamp>_<case>` vs `…_REF` | coverage, spill-over, de-energised |
| 6 Reference | `ScriptedPie*`, `ScriptedReferenceExceeded` | `_pies`, `_reference_exceeded` | `…_REF` | – |
| 7 Metrics | `ScriptedCaseMetrics`, `ScriptedKpis` | `_case_metrics` | QDS objects | coincident delta only from time-aligned pairs |
| 8 Summary | `ScriptedCaseComparison` | `_case_comparison` | QDS objects | – |
| 9 Comparison | `ScriptedCaseCounts` | `_case_counts` | QDS objects | – |
| 10 Radar | `ScriptedRadar` | `_radar` | QDS objects | **to be removed** |
| 11 Top lines | `ScriptedLineLoadingBars` | `_line_bars` | QDS objects | – |
| 12/13 Time plots | `ScriptedTrend*` | `_trends` | QDS objects | **to be removed** (REF + 6 lines) |
| 14 Top lines per case | `ScriptedTopLinesByCase` | `_top_lines_by_case` | QDS objects | – |
| 15/16 Contingency | `ScriptedContingency*` | `_n1_tables` from `compare_n1` | `…_N1`, `…_N1P` (sub-results per `cnttime`) | code 3, missing study times, `NOT_APPLICABLE` |
| 17 Evidence | `ScriptedCalculationRuns` | `_calculation_runs` | all kept objects | – |
| 18 Appendices | `ScriptedAppendix*` | `_loading_appendix`, `_voltage_appendix` | QDS objects | thresholds only |

---

## 4. Target: main and detail report

**Main report** (`MASTER_GRIDLENS.mrt`, stays the main report so that the
IntReport in PowerFactory keeps working). **Detail report**
(`MASTER_GRIDLENS_DETAIL.mrt`, new). Both read the **same** data contract; each
shows its chapters.

| Chapter | Content | Tables (data contract 7.0, working titles, no digits) | Plot |
|---|---|---|---|
| H01 Cover / contents | as today, without Study ID; run ID | `ScriptedReportMeta` (+ `run_id`) | – |
| H02 Overall assessment | KPI row, scenario status, most critical findings | `ScriptedScenarioStatistics`, `ScriptedKpis` | – |
| H03 Calculation quality | requested vs. actual time points, contingencies defined/applicable/calculated, convergence, value coverage, quality statuses | `ScriptedCoverage` | quality matrix |
| H04 FS planning | scenarios, outages, objects, windows | `ScriptedCases`, `ScriptedOutageWindows` | **Gantt** |
| H05 Base network | n-0 min/max, n-1 critical contingencies, thermal and voltage separately | `ScriptedReferenceFindings` | ranking |
| H06 Scenario comparison | critical lines/transformers/nodes, distinct NEW/WORSENED elements, NEW/WORSENED events, completeness | `ScriptedScenarioStatistics`, `ScriptedScenarioCounts` | **stacked status bars** (unit named) |
| H07 Critical equipment | n-1 reference, absolute (n-1)' extremes, limits, counters; up to 20 lines, 15 transformers, 20 nodes, "shown x of y" | `ScriptedCriticalElements` | – |
| H08 Critical contingencies / events | top events per criterion | `ScriptedContingencyEvents`, `ScriptedContingencyRegister` | **contingency ranking** |
| H09 Time criticality | distinct critical elements / contingencies per actual time point, FS activity | `ScriptedTimeCriticality` | **time course**, **heatmap** |
| H10 Settings / evidence | limits, tolerances, contingency set, origin, result paths | `ScriptedAssessmentSettings`, `ScriptedResultProvenance`, `ScriptedCalculationRuns` | – |
| D01 Scope and coverage | by grid, voltage level, class and level | `ScriptedCoverage` | – |
| D02 FS register | scenario, outage, PF path, equipment, every window | `ScriptedOutageWindows` | – |
| D03 n-0 findings | every critical/warning/quality-conspicuous base element | `ScriptedReferenceFindings` | – |
| D04/D05 Line/transformer matrix | n-1 maximum, absolute (n-1)' maxima per scenario, time + contingency + phase of each extreme | `ScriptedElementExtremes` (long format, blocks of 3 scenarios) | – |
| D06a/b Voltage minimum / maximum | separate tables | `ScriptedElementExtremes` | – |
| D07 Classification matrix | element × scenario, counters per status ("N 4 · W 2") | `ScriptedClassificationCounts` | – |
| D08 Contingency register | per contingency: examined/applicable/not applicable/failed time points, affected elements, critical times, worst finding | `ScriptedContingencyRegister` | – |
| D09 Event register | prioritised selection (marked as such) | `ScriptedContingencyEvents` | – |
| D10 Episode register | **every** critical episode | `ScriptedContingencyEpisodes` | – |
| D11 Quality register | FAILED / NOT_EVALUATED / NOT_APPLICABLE / NOT_COMPARABLE, cause, scope | `ScriptedQualityRegister` | – |
| D12 Settings and provenance | key, value, unit, origin, PF object paths | `ScriptedAssessmentSettings`, `ScriptedResultProvenance` | – |
| D13 Method / reading key | text only, no formulas | static text in the template | – |

Existing tables are migrated, not duplicated: `ScriptedCases`,
`ScriptedModelQuality`, `ScriptedCalculationRuns`, `ScriptedKpis`,
`ScriptedReportMeta` stay; `ScriptedRadar` and the two trend tables go;
`ScriptedContingency*` of 6.2 are replaced by the long-format tables above.

---

## 5. Open PowerFactory API probes

| # | Question | Needed for | Probe |
|---|---|---|---|
| R1 | Does a contingency sub-result also hold the **base case** (pre-fault) of each study time, and how is it marked? | FS pre-fault from (n-1)' without a QDS; post-fault phase | extend `ui/probe_contingency.py` (read only) |
| R2 | Which variables does the sweep record per element (`c:loading`, `m:u`; other phases?) and can several post-fault phases occur? | phase key, criteria | same |
| R3 | Can a ComPython below one IntReport publish into a **second** IntReport (`CreateTable` on another object)? | one run → two reports | read-only check of the object, then a write test on a project copy (approval) |
| R4 | How does PowerFactory export the PDF of an IntReport; can a report be split into numbered parts? | detail report parts | documentation / project copy |
| R5 | `SetValue` throughput (`ui/probe_report_write.py`) | size of the detail tables | run of the existing probe |
| R6 | Do Stimulsoft 2025.3.5 Gantt and heatmap render in PowerFactory as locally? | H04, H09 | local first, then project copy |
| R7 | Stable object IDs (`GetFullName` vs. foreign key) for elements and contingencies | result IDs | read-only probe |

No calculation, `Execute()`, `CreateObject()` or write access is part of gates
A–D; gate E runs only after approval on a project copy.

---

## 6. Decisions taken by default (revisable)

| # | Decision | Reason |
|---|---|---|
| D1 | The n-1/(n-1)' time sweep stays as decided on 23 Oct 2026 (QDS steps of the case's windows). The report shows requested time points (whole QDS period) against actual ones on coverage axis (a); switching the sweep to the full QDS time base is a gate-E change. | the assignment forbids unrequested calculation changes; the coverage makes the restriction visible |
| D2 | Two reports from one run: the main report is published by the calculating run; the detail report by a second GridLens run below its own IntReport that **re-evaluates the kept run** (no calculation, same objects, same settings snapshot, same run ID). If R3 shows that one script can publish into both reports, that replaces the second run. | uses only verified paths |
| D3 | File names: `MASTER_GRIDLENS.mrt` (main), `MASTER_GRIDLENS_DETAIL.mrt` (detail); the version is inside each template; the original stays archived. | the PowerFactory IntReport keeps its template path |
| D4 | FS pre-fault state from the existing QDS per case. | native values exist; no additional silent QDS |
| D5 | Scenario blocks: main report up to 6 scenarios per block, detail report 3, any number of blocks. | assignment §7 |
| D6 | Sample PDFs are marked as fictitious test data on every page by the local render harness, not by the template (`AGENTS`: the template carries no "synthetic" note). | both rules hold |

---

## 7. Plan for gates B–D

**Gate B – evaluation core (no PowerFactory):**
1. Criteria `loading`, `voltage_low`, `voltage_high`; result ID with run and scenario.
2. Streaming n-1 comparison: per study time, reference and scenario sub-result side by side, classify, aggregate, discard; no dense array.
3. Aggregates: per scenario × level × class × grid: distinct monitored/critical/NEW/WORSENED elements, events per status, critical contingencies and time points, extremes with full key, largest coincident worsening, episodes, coverage on three axes, quality register.
4. Synthetic sparse generator (5,000 nodes, 3,400 lines, 210 transformers, 320 contingencies, 6 scenarios, 84 time points at 2 h) and the mandatory tests of §9, also 0/1/3/6/>6 scenarios.

**Gate C – templates:** contract 7.0 tables; main template H01–H10 and detail
template D01–D13 from the existing generator. **Layout and icons stay exactly as
they are; only the content is taken over** (Hadi, 26 Oct 2026): new chapters
reuse the existing band, table and chart patterns; the only cover change is the
removed Study ID row. Radar and multi-line trends go, empty-state notes come;
Gantt, stacked bars, time course, heatmap and ranking only after a local render
check.

**Gate D – demonstration:** both templates rendered locally with the synthetic
profile, every page marked as fictitious; layout checks (breaks, repeated
headers, blocks > 6 scenarios, long names, empty and error-only reports).

**Gate E – PowerFactory:** probes R1–R7 on a project copy after approval; then
the integration of the streaming reader with the verified paths.

---

## 8. Gate B status (26 October 2026)

Implemented in `outage-assessment/main.py`, tested without PowerFactory
(`tests/test_reporting_core.py`, synthetic data in `tests/synthetic_grid.py`):

| Part | Function | What it does |
|---|---|---|
| Criteria | `criterion_thresholds`, `criterion_violation` | `loading` (above its maximum), `voltage_low` (below the band), `voltage_high` (above the band), each with its own threshold and unit |
| Classification | `classify_criterion` | the decision order of `classify_comparison` per criterion; `NOT_COMPARABLE` for differing thresholds; an unrecorded value (inside the recording limits) is OK only when the recording limit proves it, else `NOT_EVALUATED`; `change` and `delta` only from a same-time pair; `MARGIN_REDUCED` as modifier |
| Streaming reader | `SweepReader`, `_read_n1_sub` | one sub-result (study time) at a time; unrecorded cells are not stored; unreadable cells are reported, never values. `read_n1_results` (6.2 chapters) uses the same reader |
| Scenario aggregate | `ScenarioAggregate`, `compare_scenario` | per study time: classify, aggregate, drop. Distinct monitored / critical / NEW / WORSENED elements per class, events per status, critical contingencies and time points, largest violation and largest coincident worsening per criterion with the full key (run, scenario, time, contingency, phase, element, criterion), episodes, contingency register, time criticality, coverage on three axes, quality register, bounded top-event list (with the total) |
| Element counters | `element_counters` | per element and criterion: explicit statuses plus the unrecorded OK and the quality cells of the scenario |
| Level statistics | `level_statistics`, `qds_level_statistics` | n-1 reference alone; n-0 from the QDS REF |

Guarantees checked by the tests: every status, the limit equality and the
tolerance edges; low and high voltage separately; quality statuses never OK;
switched-off elements, missing study times, missing rows and unproven
unrecorded cells never OK; independent maxima never a coincident change; an
element with many events keeps every counter and counts once as distinct;
episodes break at gaps and status changes; 0, 1, 3, 6 and 8 scenarios; the
same run gives identical statistics for both reports; every requested study
time is accounted for (half-open windows); and the **conservation law**: the
cells per status add up exactly to the required cells (study times ×
contingencies × criteria of the monitored elements). The minimum profile
(5,000 nodes, 3,400 lines, 210 transformers, 320 contingencies, 6 scenarios,
84 study times at 2 h) streams in about half a minute below 300 MB peak in the
test environment; this is no PowerFactory measurement.

**Not yet integrated:** the core is not wired into `execute_gridlens` and the
report tables yet (gate C builds the contract 7.0 tables from it); reading kept
results through `SweepReader` in PowerFactory follows the verified sub-result
structure but needs probes R1, R2 and R7 before it replaces the 6.2 path.

---

## 9. Gate C status (26 October 2026)

Data contract **7.0** (38 tables since the unused counters table was dropped) and two templates generated by
`tools/build_mrt.py` from the same page patterns: **`MASTER_GRIDLENS.mrt`**
(main report, 13 pages) and **`MASTER_GRIDLENS_DETAIL.mrt`** (detail report,
20 pages). Both declare every table of the contract; each shows its chapters.
The original 6.2 template stays archived (section 1). Table by table:
[`REPORT_TABLES.md`](REPORT_TABLES.md), sections 3.22–3.43 and 4.

**Layout and icons unchanged.** Cover, header, footer, logo, colours, fonts,
title bands, table, matrix and chart patterns are the existing ones. Content
changes only: the cover row "Study ID" is removed (the rows below move up),
the detail cover has its own subtitle, and the header names the run
(`Run: {run_id}`). New chapters reuse the existing patterns: the stacked
status columns and the contingency ranking use the column chart, the time
course the line chart, the Gantt the bar layout of the existing charts.

**Mapping** (report element → table → aggregation → PowerFactory result →
quality check):

| Report element | Table | Aggregation | PowerFactory result | Quality check |
|---|---|---|---|---|
| H02 status, H06 comparison | `ScriptedCaseStatistics` | `_case_statistics` from `compare_scenario` / `qds_level_statistics` | `…_N1`, `…_N1P`; QDS `…_REF`, `…_<case>` | completeness text; INCOMPLETE COVERAGE never OK |
| H03, D01 coverage | `ScriptedCoverage`, `ScriptedScope` | coverage of `ScenarioAggregate.finish` | same | conservation law (gate B) |
| H04, D02 planning | `ScriptedOutageWindows` | `_outage_windows` from the planning cases | `IntPlannedout` (path, `starttime`, `endtime`) | – |
| H05, D03 base network | `ScriptedReferenceFindings` | `_reference_findings` | QDS `…_REF`; n-1 reference extremes | n-0 and n-1 never mixed |
| H06 chart | `ScriptedCaseStatusCounts` | events per status | `…_N1`, `…_N1P` | unit named in the title |
| H07, D04–D06b | `ScriptedCritical*`, `ScriptedDetail*` | `_element_view`: independent extremes, explicit counters | same | extremes never subtracted |
| H08, D08, D09 | `ScriptedContingencyRanking`, `…Register`, `…Events` | register and bounded top list of the aggregate | same | "x of y" from the full count |
| D07 | `ScriptedClassificationMatrix`, `…Counts` | `element_counters` | same | quality counted separately |
| D10 | `ScriptedContingencyEpisodes` | episodes of the aggregate | same | no continuous duration claimed |
| H09 | `ScriptedTimeCriticality`, `ScriptedTimeMatrix` | time rows of the aggregate | same | only actual study times |
| D11 | `ScriptedQualityRegister` | quality list of the aggregate, cases not evaluated | same | nothing left out |
| H10, D12 | `ScriptedAssessmentSettings`, `ScriptedResultProvenance` | settings snapshot; kept objects | every kept `ElmRes` | – |

**Local render check** (Stimulsoft 2025.3.5, test payload of the test suite,
not PowerFactory): every page of both templates renders without an engine
error; Gantt (`StiGanttSeries`), stacked columns, contingency ranking and time
course draw as intended. Found and fixed on the way: the count axis of the time
course printed repeated values (now hidden, the values stand at the points);
the bar pattern hid the labels of the first and last category (the ranking
uses the column pattern instead; the existing top lines chart has the same
inherited behaviour and is unchanged); the detail contents page spilled onto a
second sheet (the n-0 top 10 now sits on the appendix page).

**Deliberate deviations from the assignment:**
- Status colours: rows keep the existing two highlight colours (red for
  NEW/WORSENED, yellow for other violations and quality); every status is
  written as text. A palette per status would change the layout.
- Heatmap: H09 shows a time x scenario matrix table (counts per cell, row
  highlight) instead of a coloured heatmap chart.
- `ScriptedReferenceExceeded` is replaced by `ScriptedReferenceFindings`;
  `ScriptedRadar`, the two trend tables and the four 6.2 contingency tables are
  removed.

**Not yet integrated or verified:**
- Rendering in PowerFactory (R6) and the second IntReport for the detail
  report (D2/R3); the detail report needs its own IntReport with
  `MASTER_GRIDLENS_DETAIL.mrt`.
- The statistics are built from the n-1 data `load_n1` has already read
  (`LoadedSweep`); streaming directly from the kept results through
  `SweepReader` waits for probes R1, R2 and R7.
- The QDS result objects carry no PowerFactory path in
  `ScriptedResultProvenance` yet (only the n-1 objects do).
- Demo PDFs marked as fictitious: gate D.

---

## 10. Gate D status (26 October 2026)

Both reports rendered locally with **fictitious** data: `ui/render_demo.py`
builds every profile with the real report builder (`build_cases_payload`), the
n-0 part from the QDS fixture of the test suite and the n-1 part streamed from
`tests/synthetic_grid.py` (5,000 nodes, 3,400 lines, 210 transformers, 320
contingencies, 84 study times at 2 h). The Stimulsoft 2025.3.5 engine in
`ui/stimulsoft_harness` renders each template into one PDF with the
watermark **FICTITIOUS TEST DATA** on every page (decision D6; the templates
carry no such note). Output: `demo/<profile>/MASTER_GRIDLENS.pdf` and
`MASTER_GRIDLENS_DETAIL.pdf`. No PowerFactory is involved; this is no
PowerFactory render (probe R6 stays open).

| Profile | Content | Main / detail sheets |
|---|---|---|
| `standard` | 6 cases; 150 weak branches and nodes with time-coherent daily curves | 31 / 409 |
| `many` | 8 cases with long names: blocks beyond six, wrapping names | 43 / 744 |
| `partial` | as standard; 4 study times and 5 contingency rows missing | 31 / 414 |
| `stress` | 6 cases; every branch and node can be critical (the table limits) | 30 / 1262 |
| `empty` | no planning case, n-1 not assessed | 15 / 21 |
| `errors` | 3 cases whose QDS and n-1 both failed | 18 / 24 |

```bash
python3 ui/render_demo.py                       # every profile, one PDF per template
python3 ui/render_demo.py many --pages --png 8  # page by page with PNG sheets for the layout check
```

**Layout check: found and fixed**

| Finding | Fix |
|---|---|
| Group tables (blocks, registers per case) re-sorted by the engine, lost their header on continuation sheets and left a first sheet empty | replaced, see below: no group bands at all |
| **PowerFactory export: "The name 'ScriptedCaseComparison' does not exist in the current context"** (compiled report; the errors match exactly the first group conditions in page order; filters, cell conditions and text expressions compile) | **no GroupHeaderBand**: matrix tables have a band pair per block (filters `col_count` and `block`; header from the block's first row, repeated on every sheet; at most `MAX_PLANNING_CASES` = 20 cases); registers show the case or criterion as a column. The harness compiles like PowerFactory (`--compile`); every profile compiles. Tests forbid group bands and undeclared fields. |
| Rows over `MAX_TABLE_ROWS` were cut in case order: later cases lost every row, matrix blocks lost columns | `_fair_cut` shares the rows between the cases, `_block_rows` keeps the same rows in every block; both keep the most severe and name the cut in the model quality; statistics stay complete |
| Error-only run: failed cases disappeared from the contract 7.0 tables, the overall text said "not assessed" | every planning case keeps its rows with its reason (`planning_results`); the text names failed QDS and failed n-1 |
| NOT APPLICABLE missing from the quality register (D11) | registered per contingency and cause |
| n-1 reference findings published in full but shown only as a top 10 | only the top rows are published |
| Time course: 84 value labels overlapped | integer labels on the count axis (`0;-0;0`, no culture decimal) |
| Long names pushed the grid and limit line out of a matrix cell; counters wrapped mid-cell | the name part is shortened; counters on their own line |

**Checked and fine:** cover without Study ID, run ID in every header, empty-state
notes in the empty report, blocks of 6 (main) and 3 (detail) with repeated
element and n-1 columns, long names, the Gantt chart, stacked status columns,
the contingency ranking, every page of every profile without an engine error.

**Open:**
- The main report has 30–43 sheets for 6–8 cases (assignment: about 10–20, "more
  with many scenarios"); the time matrix (84 rows) and the critical equipment
  matrices are the longest chapters.
- The detail registers exceed `MAX_TABLE_ROWS = 5000` in `standard` (episodes)
  and in `stress` (element matrices, classification); the print is then
  incomplete and says so. Whether PowerFactory can publish more rows in
  acceptable time is probe R5; a split into numbered PDF parts is R4.
- The stress profile is deliberately unrealistic (nearly every element
  critical); `standard` is closer to a real network but still fictitious.

---

## 11. The reports as pages (26 October 2026)

Since 26 October 2026 the repository keeps both reports as **pages**, not as
`.mrt` files (Hadi's decision: changes are asked for per page, the report is
assembled in the Stimulsoft designer):

```
designer-pages/MASTER_GRIDLENS/          MASTER_GRIDLENS.dct + 00_Cover.pg … 12_Evidence.pg
designer-pages/MASTER_GRIDLENS_DETAIL/   MASTER_GRIDLENS_DETAIL.dct + 00_Cover.pg … 19_Appc.pg
```

- `.pg` is Stimulsoft's own page file ("Save Page"/"Open Page"); it stores the
  page with its unit (centimetres), so sizes stay right in any designer unit.
- `.dct` is the data dictionary (38 data sources with columns and SQL, empty
  connection); the two reports differ in one sort order (events), so each has
  its own.
- **Assembling a report:** new report in the designer → set the report culture
  to **en-US** (numbers and dates; the pages cannot carry it) → load the `.dct`
  into the dictionary → Open Page for every `.pg` in file order (00, 01, …) →
  remove the empty default page → save as `.mrt` and load it into the IntReport.
- The pages were exported once from MRT 7.0.0 with the Stimulsoft engine;
  `tools/build_mrt.py` and both 7.0.0 `.mrt` files are archived in
  `templates/archive/` and are no longer the source. Changes are made in the
  `.pg` files.
- Local check: `ui/stimulsoft_harness` assembles a report from its folder
  the same way (dictionary, pages in file order, culture en-US) and renders it,
  compiled like PowerFactory with `--compile`; the assembled reports render
  exactly as the 7.0.0 `.mrt` (same sheet counts for every profile).
- The tests read the folders (`tests/_paths.py`: `report_tree`, `report_text`)
  and check the dictionary against the data contract, every page, the file
  order and that no `.mrt` is delivered. Delivery: tests, `main.py`
  and the two page folders.
