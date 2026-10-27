# Report Migration: Data Contract 5.0 → 6.0

Historical migration record. The current delivery uses data contract 7.0 and
dictionary/page files; see [README](../README.md). The MRT generator mentioned
below is no longer part of the delivery.

German version: [de/BERICHTSMIGRATION.md](de/BERICHTSMIGRATION.md)

| | Before | After |
|---|---|---|
| Publisher | 7.0.0 | 8.0.0 |
| MRT (`MASTER_GRIDLENS.mrt`) | 5.0.0 | 6.0.0 → 6.1.0 (one page per chapter; fields without digits) |
| Data contract | 5.0, 18 tables | 6.0, 19 tables → 6.2, 23 tables (n-1 chapters) |

The MRT is generated: `python3 tools/build_mrt.py`. `tests/test_mrt.py` checks
that its data sources equal `TABLES` and that every SQL query runs against the
tables a real run emits. The new template has **not** been rendered in
PowerFactory or with the local Stimulsoft harness yet.

An old 5.0 template must not be used with the 6.0 script: its LODF chapter
queries `ScriptedLodfRanking` and `ScriptedReportMeta.lodf_text`, which no
longer exist, so the query is expected to fail rather than show stale data
(V39). How Stimulsoft in PowerFactory reports this has not been tried;
`ScriptedReportMeta` carries `template_version` and `data_contract_version`
for a manual check.

## Tables

| Table | Change |
|---|---|
| `ScriptedLodfRanking` | **removed** |
| `ScriptedCaseComparison` | **new**, matrix layout (`block`, `row_order`, `element_name` = key figure, `ref_text`, `c1..c6_text`, `h1..h6_name`, `col_count`, `violation`) |
| `ScriptedCalculationRuns` | **new**: `run_order`, `run_id`, `run_kind`, `case_name`, `reference_text`, `period_text`, `time_steps`, `elapsed_text`, `status`, `provenance_text`, `result_object`, `note` |
| `ScriptedReportMeta` | removed `lodf_text`; added `case_source_text`, `reference_text`, `qds_mode_text`, `coverage_statement` (all required) |
| `ScriptedCases` | one row per planning case; added `case_description`, `outage_names`, `reference_text`, `states_text`, `windows_text`, `coverage_text`, `provenance_text`. `period_text` and `equipment_name` list every outage of the case. |
| `ScriptedCaseMetrics` | `largest_delta_text` replaced by `coincident_delta_text` (same time step) and `maxima_difference_text`; added `violation_hours_text`, `coverage_text` |
| `ScriptedKpis` | `delta_text` is now the largest coincident increase |
| `ScriptedTrendLargestDelta` | the line is chosen by coincident delta |
| all other tables | unchanged; they keep whole-period values (difference of maxima where they compare) |

## Template chapters

| # | Chapter | Change |
|---|---|---|
| 3 | Model Quality Assurance | new checks: planning cases, case warnings, fixed outages, outage window coverage, effect outside the outage windows, nodes de-energised by a case, calculation period |
| 4 | Calculated Cases and Planned Outages | headings *Outage periods*, *Findings at the same time steps as Reference*; statement A/B box |
| 5 | **Case Definition and Network States** | new: outages, reference, network states, coverage, result provenance |
| 6 | Reference Case | unchanged |
| 7 | Metric View | coincident increase and difference of maxima side by side, caused-violation duration; explanatory note |
| 8 | **Case Comparison Summary** | new: key figures per case, REF first, blocks of six cases |
| 9–13 | Case comparison, radar, top 10, trends | renumbered; trend 13 uses the coincident delta |
| 12 (old) | Line Impact Ranking (LODF) | **removed** |
| 14 | Top 10 by case | renumbered |
| 15 | **Calculation Evidence** | new: every run, kind, steps, time, status, kept result object, note; calculation-period statement |
| 16 | Appendix A–C | renumbered |

The table of contents now has 19 entries at a 0.7 cm pitch so it still fits
between page header and footer.

## What to check in the PDF template

The template is generated and tested against the data contract, but not
rendered. At the first rendering in PowerFactory, look at:

- chapters 5, 8 and 15 each start on their own page, also without cases;
- the matrix in chapter 8 shows the right columns for each number of cases;
- long cells (`states_text`, `note`) wrap without breaking the row grid;
- the table of contents fits on one page and every link jumps correctly.
