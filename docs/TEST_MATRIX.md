# GridLens 8.0 – Test Matrix (deliverable G)

German version: [de/TESTMATRIX.md](de/TESTMATRIX.md)

Status categories:

- **Test data** – automated test with PowerFactory fakes or plain data, passes (`.venv/bin/pytest -q`)
- **Static** – follows from the code structure, reviewed, no dedicated test
- **PowerFactory** – run in PowerFactory 2026 (none yet)
- **Not verified** – open; needs PowerFactory or is not implemented

Every row is **not verified in PowerFactory**. The automated suite: 494 tests, all run in the project `.venv` (python.org Python 3.11 with Tk 8.6);
the 34 of `test_case_manager_dialog.py` open the real Tk window and are skipped only where `tkinter` is missing.

## Specification tests A–E

| Test | Input | Expected | Result | Status | Test |
|---|---|---|---|---|---|
| A | REF 80 %, 60 %; case 70 %, 85 % | difference of maxima +5 pp, coincident delta +25 pp | +5 / +25 at 11:00 | Test data | `test_planner.py::test_a_coincident_delta_is_not_the_difference_of_the_maxima` |
| B | FS1 08–13, FS2 10–15, FS3 11–14 | 5 states as in section 7 | identical | Test data | `test_b_three_overlapping_outages_pass_through_five_states` |
| C | FS1 KW10, FS2 KW40 in one case | the complete ComStatsim period, no unproven gap | full period; no window is proposed or shortened (time optimisation removed in part 2) | Test data | `test_c_kw10_and_kw40_run_over_the_complete_period_without_proposed_windows` |
| D | A: FS1 KW10, B: FS1 KW40 | no automatic A+B | independent cases; any explicitly assigned joint case is allowed | Test data | `test_d_alternative_dates_stay_separate_cases`, `test_any_explicit_combination_is_allowed` |
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
| V11 | jointly valid cases | explicit joint plan | direct outage assignments | Test data | test E |
| V12 | partly identical cases | reuse only on full identity | fingerprint over outages, windows, fixed outages; reused result marked | Test data | `test_v12_identical_cases_share_a_fingerprint_and_others_do_not`, `test_identical_cases_are_calculated_once_and_say_so` |
| V13 | two FS on the same line | consistent state | no warning, overlap is normal planning; PF semantics unknown (P4) | Test data; PF open | `test_v13_overlapping_outages_are_normal_planning_not_a_warning` |
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
| V30 | GUI cancel | no project change; report caller receives cancellation | no run, no copy, no publication; cancellation propagates from `main`, with and without previous report tables | Test data; IntReport handling needs PF verification | `test_v30_cancel_in_the_case_manager_changes_and_calculates_nothing`, `test_cancel_reaches_the_report_caller_instead_of_returning_success`, `test_case_manager_dialog.py::test_gui_17_cancel_returns_nothing` |
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
| outage rules, removed case relations and legacy cycles | `test_rules_*`, `test_removed_relations_cannot_silently_affect_current_configurations`, `test_legacy_cycle_is_rejected_before_assignments_can_be_lost` |
| saved configuration, revision, damaged file | `test_configuration_is_saved_with_a_revision_and_read_back`, `test_damaged_configuration_is_reported_not_ignored` |
| legacy configuration becomes independent cases; file unchanged until save | `test_legacy_cases_are_flattened_once_and_then_stay_independent`, `test_saved_legacy_relations_become_independent_case_runs` |
| result object per case kept and named | `test_reference_runs_without_and_every_outage_runs_as_its_own_case` |
| emitted tables match the MRT and its SQL | `test_executed_publisher_output_matches_mrt_and_all_sql_queries` |
| damaged configuration named before use (8 variants) | `test_damaged_configuration_is_named_before_anything_reads_it` |
| window that ends before it starts | `test_window_that_ends_before_it_starts_is_refused` |
| unknown or Ignored fixed outages warned | `test_unknown_or_ignored_fixed_outages_are_warned_about` |
| applied outages read back before each run; n-1 skip reason logged | `test_applied_text_reads_the_option_and_the_flags_back`, `test_run_output_is_structured_in_steps_cases_and_tables`, `test_run_n1_marks_every_case_when_no_contingency_analysis_exists_and_reports_on_the_qa_page` |
| effect of each outage checked against REF in its window (APPLIED, EFFECT SEEN, NO EFFECT, NOT CHECKABLE), QA row | `test_an_outaged_line_without_load_in_its_window_is_applied`, `test_an_unrecorded_component_counts_when_the_network_differs_in_the_window`, `test_a_case_equal_to_ref_in_the_window_shows_no_effect`, `test_the_effect_is_not_checkable_without_reference_or_window_rows`, `test_outage_quality_warns_about_an_outage_without_effect` |
| coverage text consistent with the verdict | `test_coverage_text_never_says_complete_when_the_verdict_does_not` |
| failing comparison fails only its case, ElmRes kept | `test_a_failing_comparison_fails_only_its_own_case` |
| memory budget stops before the next run | `test_memory_budget_stops_before_the_next_run_and_restores` |
| reused case names the shared result object | `test_reused_case_names_the_result_object_it_shares` |
| dialog that cannot be built → fallback | `test_case_manager_dialog.py::test_a_dialog_that_cannot_be_built_counts_as_unavailable` |
| errors in dialog buttons are shown | `test_case_manager_dialog.py::test_errors_in_buttons_are_shown_not_swallowed` |
| fast paths give the old results (statistics, plot points, excess, step status) | `test_extraction_builds_only_the_plotted_points_and_keeps_the_exact_statistics`, `test_array_statistics_equal_the_point_statistics`, `test_excess_function_keeps_the_definition`, `test_compare_element_agrees_with_step_status_at_every_step` |
| every case judged once, all pages show the same verdict | `test_every_case_is_judged_once_and_all_pages_show_that_verdict` |
| windows off the time axis: full comparison, warning in the log | `test_windows_off_the_time_axis_are_compared_in_full_and_said_so` |

## Case manager window – functional checks 1–20

Not verified in PowerFactory; the editing rules are tested without a window (`test_planner.py`), the clicks in the real Tk window (`test_case_manager_dialog.py`).

| Check | Action | Expected | Tested with | Tests |
|---|---|---|---|---|
| 1-3 | click case A, then B, then A | A shows its outages at once, B its own, A unchanged | editor + real window | `test_gui_01_to_03_*` (2) |
| 4 | add an outage from the left list | centre table, FS count and mark update at once | editor + real window | `test_gui_04_and_06_*`, `test_gui_04_and_05_*` |
| 5 | remove an outage from a case | only the assignment ends | editor + real window | `test_gui_05_and_09_*`, `test_gui_04_and_05_*` |
| 6 | one outage in several cases | allowed | editor | `test_gui_04_and_06_*` |
| 7 | copy a case | assignments copied, both independent | editor | `test_gui_07_*` |
| 8 | rename a case | ID and other cases stay unchanged | editor + real window | `test_gui_08_*`, `test_new_case_gets_a_generated_id_and_is_named_in_its_window` |
| 9 | delete a case | planned outages stay; other cases unchanged | editor | `test_gui_05_and_09_*`, `test_gui_deleting_a_case_keeps_shared_assignments_in_other_cases` |
| 10 | fixed background outages | separate from case outages, never both; Rfix in the preview | editor | `test_gui_10_*` |
| 11 | search by equipment | matching outages only | editor + real window | `test_gui_11_and_12_*`, `test_gui_11_*` |
| 12 | very many outages | 5,005 outages searched in under 0.5 s; lists scroll | editor | `test_gui_11_and_12_*` |
| 13 | overlapping outages on the timeline | overlap band; KW10 and KW40 both readable | editor + real window | `test_gui_13_*` (2), `test_timeline_scale_is_monotonic_and_needs_a_window` |
| 14 | choose n-0, n-1, (n-1)' | n-0 handed over; n-1 and (n-1)' shown disabled (not available until part 3) and refused in a file | editor + real window | `test_gui_14_and_16_*`, `test_gui_14_to_16_*`, `test_assessments_and_enabled_flags_are_validated` |
| 15 | QDS period | the active ComStatsim period | editor + real window | `test_gui_15_*`, `test_gui_14_to_16_*` |
| 16 | no time optimisation | no option, no proposed windows; the field `mode` is dropped | editor + real window | `test_gui_14_and_16_*`, `test_gui_14_to_16_*` |
| 17 | Cancel | no calculation, no change | real window + run | `test_gui_17_*`, `test_v30_*` |
| 18 | Start calculation | configuration handed to the existing GridLens run | real window + run | `test_gui_18_and_19_*`, `test_a_case_with_two_outages_runs_them_together` |
| 19 | no result view | window closes; the PDF is the only result | real window | `test_gui_18_and_19_*` |
| 20 | reopen | saved assignments come back unchanged | editor + real window | `test_gui_20_*` (2) |
| GUI test tool: separate script with its own copy of the case manager (never loads `gridlens_report.py`), copy identical to the production window; project outages read only; temporary configuration copy; demo data; missing Tk | `test_case_manager_gui.py` (9) |
| table filters and sorting: contains / exact value, header sort ▲▼, column widths, filters aligned on every tab | `test_filter_rows_*`, `test_sort_rows_*`, `test_column_widths_*`, `test_gui_11_every_table_filters_per_column_and_clears`, `test_filters_stand_exactly_under_their_columns`, `test_header_click_sorts_and_shows_the_direction` |
| two tabs (Case Manager, Settings), status line, problem list; fixed outages and rules on their own Settings page | `test_tabs_status_line_and_problem_list`, `test_fixed_outages_and_rules_live_on_their_own_tab` |
| at most 5 cases (window, saved file, one case per outage); IDs generated, never typed | `test_gui_at_most_five_cases`, `test_gui_one_case_per_outage_stops_at_five`, `test_more_than_five_cases_are_refused_where_engineers_define_them`, `test_gui_ids_are_generated_and_the_engineer_only_names_cases`, `test_new_case_gets_a_generated_id_and_is_named_in_its_window`, `test_new_and_copy_stop_at_five_cases` |
| workspace order: available outages, case outages, cases; case relations removed; hover texts on buttons, column headings and filters | `test_workspace_runs_available_outages_then_case_outages_then_cases`, `test_hover_explains_the_controls_without_case_relations` |
| review fixes: one case per outage only in the period; Copy and Delete leave other cases unchanged; legacy relations become direct assignments; rule drop-downs keep same-named outages apart; one resolution per refresh; typing closes a hint | `test_one_case_per_outage_takes_only_outages_in_the_simulated_period`, `test_copy_keeps_own_dates_independent`, `test_legacy_cases_are_flattened_once_and_then_stay_independent`, `test_rule_choices_keep_outages_with_the_same_name_apart`, `test_statuses_problems_and_preview_share_one_resolution`, `test_hover_explains_the_controls_without_case_relations` |
| second review: a saved file with more than five cases still opens (excluded stays excluded); the GUI test survives a damaged saved file and imports what its own code needs; preview labels reused; a direct render cancels the pending one; one case per outage clears the case filter | `test_a_saved_file_with_too_many_cases_still_opens_so_cases_can_be_deleted`, `test_a_damaged_saved_configuration_does_not_stop_the_gui_test`, `test_the_copied_case_manager_matches_gridlens_report`, `test_refreshes_reuse_widgets_and_render_once` |
| check box in the outage list (tick adds, untick removes, a quick second click is no double-click), name and description in their own window (double-click, Edit, New), only `IntPlannedout` read (no demand transfers) | `test_the_check_box_adds_and_removes_one_outage`, `test_ticking_the_box_adds_and_removes_an_outage`, `test_new_case_gets_a_generated_id_and_is_named_in_its_window`, `test_double_click_on_a_case_opens_name_and_description`, `test_only_planned_outages_are_read_not_demand_transfers` |
| clear message for a result object without loading or voltage; run end says whether report tables were published | `test_a_result_object_without_loading_or_voltage_says_what_is_missing_and_what_to_do`, `test_a_result_object_with_only_dead_terminals_says_so`, `test_an_unusable_result_object_is_named_in_the_run_error`, `test_a_run_without_publication_says_that_the_report_cannot_be_generated`, `test_a_successful_run_names_the_report_to_generate` |
| large outage table: reuse rows on checkbox/case changes; preserve scroll and selection; filter reattachment and deletion | `test_large_outage_table_updates_one_checkbox_without_rebuilding_or_scrolling`, `test_filtered_rows_reattach_with_current_values_and_removed_rows_stay_gone` |
| visible purpose/examples for shared outages and each rule; keep/skip explanation; controls and help fit at 1000×620 and 1280×800 | `test_fixed_tab_explains_shared_outages_rules_and_optional_use_without_hover`, `test_explanations_and_rule_controls_fit_the_window` (2 sizes) |
| Run flags: click, Space, filtering and live settings preview; background, windows, reuse, blocked and excluded cases | `test_run_flags_toggle_the_clicked_case_and_update_the_settings_preview`, `test_calculation_preview_lists_effective_settings_and_keeps_blocked_cases_out` |
| Cancel or a failed run ends the script with exit code 1, so no report is rendered | `test_cancel_or_a_failure_ends_the_script_with_an_error_code_so_no_report_is_rendered`, `test_cancel_says_that_the_report_is_not_generated` |
| saved upgrade drops its one-time note; schema-2 file `.v2.json` never replaces the schema-1 file of the delivered script; outage choices built once | `test_the_upgrade_note_is_shown_until_the_cases_are_saved`, `test_this_version_never_overwrites_the_file_of_the_delivered_script`, `test_outage_choices_are_built_once` |
| only tests, `gridlens_report.py` and `MASTER_GRIDLENS.mrt` are needed: `tests/_paths.py` finds both in `powerfactory/` or next to `tests/`; tool tests skip without `tools/` | checked by running the suite in a copy with only those files (nested and flat) |
| keyboard: Delete/BackSpace remove in every list, Ctrl+N/S/O/F/Enter, Ctrl+A | `test_keyboard_deletes_and_shortcuts` |

## Parts 1 and 2 (23 October 2026): n-1 preparation, settings, classification

Three levels of evidence, kept apart:

- **Static** – read from the code, checked by a test of the source, no run.
- **Mock / local Tk** – automated test with PowerFactory stand-ins or plain data,
  and the real Tk window on macOS (Tk 8.6).
- **PowerFactory 2026** – run and confirmed in PowerFactory: **none of part 1 or 2 yet.**

| Area | What | Level | Tests |
|---|---|---|---|
| Probe 2.1 (strict privacy) | no artificial sensitive string or number in the output; every line an allowlisted label and token; only allowlisted reading methods called; no name, path or other attribute read; failures and crashes give error codes only; allowlist not bypassable | Mock | `test_no_sensitive_string_or_value_ever_reaches_the_output`, `test_every_output_line_is_an_allowlisted_label_with_an_allowlisted_token`, `test_only_allowlisted_methods_are_called_and_nothing_writes`, `test_no_name_path_or_other_attribute_is_read`, `test_failures_yield_only_error_codes_never_their_text`, `test_a_check_that_crashes_reports_its_category_only`, `test_a_label_or_token_outside_the_allowlist_cannot_be_printed` |
| Probe 2.1 static analysis | imports only `sys`/`powerfactory`; no file, network, `print`, `repr`, `str()`, f-string or dynamic format; no forbidden attribute names; PowerFactory calls only through the gateway | Static | `test_static_*` (4) |
| Probe 2.1 findings | time sweep, planned outages, results, equipment and grid attribute, ElmRes methods, sub-results, code 3, storage | Mock | `test_the_expected_findings_are_reported`, `test_without_code_three_no_sparse_indicator_is_claimed` |
| Probe 2.1 in a real project | output free of project data | **PowerFactory – open** | Hadi runs `tools/probe_contingency.py`; check the copied text for PowerFactory's own messages |
| Test run tool | disabled, refuses a project that is not the configured copy without naming it, asks before writing, restores; prints no names, values, study times or error texts | Static + mock | `test_prepared_test_run_is_disabled_guarded_and_prints_no_names`; **not run, needs a separate release** |
| GUI | exactly two tabs, no results tab; problems on Case Manager; fixed background & rules under Settings | Local Tk | `test_tabs_status_line_and_problem_list`, `test_filters_stand_exactly_under_their_columns`, `test_fixed_tab_explains_*` |
| GUI | n-0, n-1, (n-1)' shown; n-1 and (n-1)' disabled with the explanation; refused in a file | Local Tk + editor | `test_gui_14_to_16_*`, `test_gui_14_and_16_*` |
| GUI | Settings: every setting shown with source and category; category B read only; QDS time base read only | Local Tk | `test_settings_tab_shows_every_setting_with_source_and_hover_text` |
| GUI | invalid entry red, tab *Settings (!)*, start blocked; apply, override, restore defaults; start applies edits | Local Tk | `test_invalid_setting_is_marked_and_blocks_the_start`, `test_apply_override_and_restore_defaults` |
| GUI | tooltips: about 450 ms delay, gone on leave, on every setting and button; start tooltip promises no automatic PDF | Local Tk | `test_tooltip_appears_after_the_delay_and_goes_on_leave`, `test_hover_explains_*`, `test_every_setting_has_a_hover_text` |
| GUI | case manager inside PowerFactory | **PowerFactory – open** | `tools/FS_CaseManager_GUI_Test_PowerFactory2026.py` |
| Settings | defaults equal the code; voltage proposal labelled; parsing, finite numbers, positive limits, non-negative tolerances, min < max, warning ≤ limit | Test data | `test_settings.py` (31) |
| Settings | stored with the cases (provisional JSON), cases unchanged, invalid file refused, `mode` of old files ignored | Test data | `test_settings_are_stored_with_the_cases_and_do_not_touch_them`, `test_invalid_saved_settings_are_refused_with_the_reason`, `test_a_file_of_an_earlier_version_with_mode_still_loads` |
| n-0 regression | defaults reproduce every report row exactly; changed limits change only the assessment; restored defaults reproduce the original | Test data | `test_default_settings_reproduce_the_n0_report_exactly`, `test_changed_assessment_limits_change_only_the_assessment_and_restore_cleanly`, `test_report_names_the_settings_and_the_rules_version` |
| n-0 with overrides | a real QDS run with changed limits | **PowerFactory – open** | – |
| Classification | all ten statuses, the master-prompt examples, limit and equality boundaries, user tolerances, invalid and missing values, NOT_APPLICABLE, NOT_COMPARABLE per identity field and limit definition, same post-fault phase, precedence keeps reasons, MARGIN_REDUCED, coincident delta, pure function, n-0 statuses untouched | Test data | `test_classification.py` (34) |
| Time base | no time optimisation left in the runtime; files with `mode` load | Test data | `test_no_time_optimisation_remains_in_the_runtime`, `test_c_kw10_and_kw40_run_over_the_complete_period_without_proposed_windows` |
| Deliberately disabled | n-1, (n-1)', category B, post-fault voltage limits, native storage, `GL_<scenario>_CLASSIFICATION` | – | part 3 |
| Network scope | every grid of the model listed (inactive labelled); assessed-equipment selection filters the n-0 assessment and takes precedence over `GRID_NAME_FILTER`; contingency selection stored, previewed via `ComOutage.GetObject`, never applied; warnings for missing or inactive grids; report row *Network scope* | Test data + local Tk | `test_network_scope.py` (7), `test_network_scope_lists_the_grids_of_the_model_for_selection`, `test_probe_follows_a_grid_selection_like_the_report` |
