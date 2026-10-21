# GridLens 8.0 – Test Matrix (deliverable G)

German version: [de/TESTMATRIX.md](de/TESTMATRIX.md)

Status categories:

- **Test data** – automated test with PowerFactory fakes or plain data, passes (`.venv/bin/pytest -q`)
- **Static** – follows from the code structure, reviewed, no dedicated test
- **PowerFactory** – run in PowerFactory 2026 (none yet)
- **Not verified** – open; needs PowerFactory or is not implemented

Every row is **not verified in PowerFactory**. The automated suite: 292 tests, all run in the project `.venv` (python.org Python 3.11 with Tk 8.6);
5 of them open the real Tk dialog and are skipped only where `tkinter` is missing.

## Specification tests A–E

| Test | Input | Expected | Result | Status | Test |
|---|---|---|---|---|---|
| A | REF 80 %, 60 %; case 70 %, 85 % | difference of maxima +5 pp, coincident delta +25 pp | +5 / +25 at 11:00 | Test data | `test_planner.py::test_a_coincident_delta_is_not_the_difference_of_the_maxima` |
| B | FS1 08–13, FS2 10–15, FS3 11–14 | 5 states as in section 7 | identical | Test data | `test_b_three_overlapping_outages_pass_through_five_states` |
| C | FS1 KW10, FS2 KW40 in one case | not 52 weeks *if* separation proven; no unproven gap | 2 windows proposed, not executed (separation not provable) → conservative full period | Test data; execution of windows **not implemented** | `test_c_kw10_and_kw40_give_two_proposed_windows_but_run_conservatively` |
| D | A: FS1 KW10, B: FS1 KW40 | no automatic A+B | two cases; a joint case with an exclusive pair is refused | Test data | `test_d_alternative_dates_stay_separate_cases`, `test_d_alternatives_in_one_joint_case_are_refused` |
| E | A: FS1 KW10, B: FS2 KW10, joint AB | FS1+FS2 together | AB has both, one state | Test data | `test_e_a_joint_plan_calculates_both_outages_together` |

## Function matrix V01–V40

| ID | Situation | Expected | Result / implementation | Status | Test(s) / note |
|---|---|---|---|---|---|
| V01 | one FS in a case | single assessment | as in 7.x | Test data | `test_reference_runs_without_and_every_outage_runs_as_its_own_case` |
| V02 | two FS at the same time | common state | both `outserv=0` in one run | Test data; PF P2/P3 open | `test_a_case_with_two_outages_runs_them_together` |
| V03 | three overlapping FS | changing active set | states computed; PF applies windows | Test data | test B |
| V04 | five FS at the same time | one QDS | covered by the 50-FS test | Test data | `test_v37_fifty_outages_in_one_case_are_not_limited` |
| V05 | ten FS one after the other | correct sequence | 10 single states in order | Test data | `test_v05_ten_sequential_outages_keep_their_order` |
| V06 | FS in KW10 and KW40 | two windows if admissible | proposed only; conservative run | Test data / **not implemented** (execution) | test C |
| V07 | one FS in several cases | multiple assignment | allowed, no duplication of the PF object | Test data | `test_shared_outage_counts_once_in_a_joint_plan`, test D |
| V08 | same FS in alternative weeks | date variants | one `IntPlannedout` per date; own dates recorded but not applied | Test data | `test_d_alternative_dates_stay_separate_cases`, `test_own_dates_are_refused_while_overrides_are_off` |
| V09 | same FS really twice | both occurrences | two members, states 1 → ∅ → 1 | Test data | `test_v09_the_same_outage_twice_in_one_case_is_two_real_executions` |
| V10 | alternative cases at the same time | no unplanned combination | never combined automatically | Test data | `test_no_combination_is_generated_automatically` |
| V11 | jointly valid cases | explicit joint plan | `includes` | Test data | test E |
| V12 | partly identical cases | reuse only on full identity | fingerprint over outages, windows, fixed outages; reused result marked | Test data | `test_v12_identical_cases_share_a_fingerprint_and_others_do_not`, `test_identical_cases_are_calculated_once_and_say_so` |
| V13 | two FS on the same line | consistent state | warning; PF semantics unknown (P4) | Test data (warning); PF open | `test_v13_two_outages_on_the_same_line_warn` |
| V14 | FS with lasting switching | after-effect considered | spill-over rows assessed and reported | Test data | `test_effect_after_the_window_is_assessed_as_well` |
| V15 | QDSL storage state | correct continuation | conservative runs are continuous; windows refused when `ElmQdsl` exists | Static + test data | `test_time_coupled_models_make_shorter_windows_inadmissible` |
| V16 | short FS between QDS steps | event captured | no row → coverage 0 → never "no limit exceeded" | Test data | `test_v16_short_outage_between_time_steps_has_no_coverage`, `test_incomplete_coverage_is_never_reported_as_secure` |
| V17 | FS starts before the period | correct initial state | kept with warning; coverage reduced | Test data | `test_f12_outage_starting_before_the_period_is_kept_with_a_warning` |
| V18 | FS ends after the period | continuing state | coverage < 100 % | Test data | `test_coverage_of_a_window_partly_after_the_period` |
| V19 | network model version changes | correct model state | left to PowerFactory within the full-period run | Static; not verified | – |
| V20 | different profiles KW10 / KW40 | correct calendar mapping | only identical time steps are compared | Test data | test A, `test_v29_case_on_another_time_axis_is_not_compared` |
| V21 | REF already overloaded | pre-existing | NO ADDITIONAL VIOLATION, yellow | Test data | `test_pre_existing_violation_is_no_additional_violation` |
| V22 | new overload | NEW | OVERLOAD, red | Test data | `test_overload_inside_the_window_is_reported_with_its_element` |
| V23 | worsened overload | WORSENED | per step | Test data | `test_every_time_step_is_classified` |
| V24 | improved overload | IMPROVED / RESOLVED | per step | Test data | `test_every_time_step_is_classified` |
| V25 | voltage outside band | classified | VOLTAGE BAND | Test data | `test_voltage_band_violation_is_reported_separately` |
| V26 | unsupplied island | not a normal value | DE-ENERGISED, own verdict and QA row | Test data | `test_v26_node_cut_off_by_the_case_is_reported_not_dropped` |
| V27 | QDS does not converge | not assessable | FAILED / NOT EVALUATED, next case runs | Test data | `test_failed_outage_case_is_reported_and_state_is_restored` |
| V28 | reference missing | no claimed comparison | EXCEEDED, no coincident delta | Test data | `test_v28_without_reference_violations_are_not_called_new` |
| V29 | different time axes | window-wise validation | case not compared, NOT EVALUATED | Test data | `test_v29_case_on_another_time_axis_is_not_compared` |
| V30 | GUI cancel | no project change | no run, no copy, no publication | Test data | `test_v30_cancel_in_the_case_manager_changes_and_calculates_nothing`, `test_case_manager_dialog.py::test_cancel_returns_nothing` |
| V31 | GUI without tkinter | controlled fallback | saved configuration, else one case per outage; also when the dialog cannot be built | Test data; DPL fallback **not implemented** | `test_v31_*` (2), `test_a_dialog_that_cannot_be_built_counts_as_unavailable` |
| V32 | exception in the QDS | state restored | restore in `finally`, verified read-back | Test data | `test_reference_failure_still_restores_option_and_result_binding`, `test_ignored_flag_that_cannot_be_restored_stops_the_run`, `test_memory_budget_stops_before_the_next_run_and_restores` |
| V33 | more than six cases | complete assessment, transparent charts | tables in blocks of six; charts first six with note | Test data | `test_more_than_six_cases_are_all_assessed_and_compared`, `test_charts_show_at_most_six_cases_and_say_so` |
| V34 | full vs. partial QDS | equivalence | partial QDS not executed | **Not implemented** | needs P8 probe |
| V35 | shared reference | valid reuse only | one reference per run (R0 or Rfix) | Test data | `test_fixed_outages_stay_active_in_the_reference_and_every_case` |
| V36 | same times, other switching measures | separate assessment | different objects → different fingerprints | Test data | `test_v12_*` |
| V37 | case with 50 FS | no limit to two | 50 members | Test data | `test_v37_fifty_outages_in_one_case_are_not_limited` |
| V38 | no FS in the period | reference / no effect | NOT SIMULATED; no rows → not assessed | Test data | `test_case_outside_the_simulated_period_is_not_simulated`, `test_v38_case_without_rows_in_its_window_is_not_assessed` |
| V39 | old template with LODF | migration error visible | LODF absent from script and template; old template not rendered | Test data (absence); not verified (rendering) | `test_no_lodf_remains_in_the_template`, `test_table_contract_is_single_versioned_19_table_contract` |
| V40 | annual report, partial windows only | no false annual release | statements A/B on the cases page; INCOMPLETE COVERAGE | Test data | `test_report_states_what_the_assessment_does_and_does_not_prove` |

## Further checks

| Check | Test |
|---|---|
| T01–T13 all relations and their state sequences | `test_all_thirteen_interval_relations` (13 cases) |
| half-open windows `[start, end)` | `test_windows_are_half_open` |
| duration weighted by uneven steps | `test_violation_duration_weights_uneven_time_steps` |
| unique labels at the autumn clock change | `test_clock_change_keeps_every_time_label_unique` |
| rule conflicts, conditional cases, cycles | `test_rules_*`, `test_conditional_case_needs_its_precondition`, `test_including_cases_in_a_circle_is_refused` |
| saved configuration, revision, damaged file | `test_configuration_is_saved_with_a_revision_and_read_back`, `test_damaged_configuration_is_reported_not_ignored` |
| result object per case kept and named | `test_reference_runs_without_and_every_outage_runs_as_its_own_case` |
| emitted tables match the MRT and its SQL | `test_executed_publisher_output_matches_mrt_and_all_sql_queries` |
| damaged configuration named before use (8 variants) | `test_damaged_configuration_is_named_before_anything_reads_it` |
| window that ends before it starts | `test_window_that_ends_before_it_starts_is_refused` |
| unknown or Ignored fixed outages warned | `test_unknown_or_ignored_fixed_outages_are_warned_about` |
| coverage text consistent with the verdict | `test_coverage_text_never_says_complete_when_the_verdict_does_not` |
| failing comparison fails only its case, ElmRes kept | `test_a_failing_comparison_fails_only_its_own_case` |
| memory budget stops before the next run | `test_memory_budget_stops_before_the_next_run_and_restores` |
| reused case names the shared result object | `test_reused_case_names_the_result_object_it_shares` |
| dialog that cannot be built → fallback | `test_case_manager_dialog.py::test_a_dialog_that_cannot_be_built_counts_as_unavailable` |
| errors in dialog buttons are shown | `test_case_manager_dialog.py::test_errors_in_buttons_are_shown_not_swallowed` |
| fast paths give the old results (statistics, plot points, excess, step status) | `test_extraction_builds_only_the_plotted_points_and_keeps_the_exact_statistics`, `test_array_statistics_equal_the_point_statistics`, `test_excess_function_keeps_the_definition`, `test_compare_element_agrees_with_step_status_at_every_step` |
| case editor without a window: create, copy, rename, delete, assign, fix, own dates, rules | `test_editor_*` (6) |
| dialog buttons reach the editor, OK returns its configuration | `test_case_manager_dialog.py::test_buttons_reach_the_editor_and_ok_returns_its_configuration` |
| every case judged once, all pages show the same verdict | `test_every_case_is_judged_once_and_all_pages_show_that_verdict` |
| windows off the time axis: full comparison, warning in the log | `test_windows_off_the_time_axis_are_compared_in_full_and_said_so` |
