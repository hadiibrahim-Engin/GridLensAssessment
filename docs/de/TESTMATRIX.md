# GridLens 8.0 – Testmatrix (Lieferteil G)

Historische Spezifikationsmatrix; die unten genannten Testzahlen gehören zu
diesem Entwicklungsstand. Aktuelle Prüfanleitung und Abgrenzung zur nativen
PowerFactory-Abnahme stehen in der [README](../../README.md).

Englische Fassung: [../TEST_MATRIX.md](../TEST_MATRIX.md)

Statuskategorien:

- **Testdaten** – automatischer Test mit PowerFactory-Nachbildungen oder reinen Daten, bestanden (`.venv/bin/pytest -q`)
- **Statisch** – folgt aus der Codestruktur, geprüft, ohne eigenen Test
- **PowerFactory** – in PowerFactory 2026 ausgeführt (bisher keiner)
- **Nicht verifiziert** – offen; braucht PowerFactory oder ist nicht umgesetzt

Keine Zeile ist **in PowerFactory verifiziert**. Die automatische Testsuite:
494 Tests, alle in der Projekt-`.venv` (python.org-Python 3.11 mit Tk 8.6); die 34 aus `test_case_manager_dialog.py`
öffnen das echte Tk-Fenster und werden nur übersprungen, wo `tkinter` fehlt. Die Testnamen sind englisch, wie der Code.

## Tests A–E der Vorgabe

| Test | Eingang | Erwartet | Ergebnis | Status | Test |
|---|---|---|---|---|---|
| A | REF 80 %, 60 %; Fall 70 %, 85 % | Differenz der Maxima +5 pp, zeitgleiches Delta +25 pp | +5 / +25 um 11:00 | Testdaten | `test_planner.py::test_a_coincident_delta_is_not_the_difference_of_the_maxima` |
| B | FS1 08–13, FS2 10–15, FS3 11–14 | 5 Zustände wie in Abschnitt 7 der Vorgabe | identisch | Testdaten | `test_b_three_overlapping_outages_pass_through_five_states` |
| C | FS1 KW10, FS2 KW40 in einem Fall | der ganze ComStatsim-Zeitraum, keine unbewiesene Lücke | ganzer Zeitraum; kein Fenster vorgeschlagen oder verkürzt (Zeitoptimierung in Teil 2 entfernt) | Testdaten | `test_c_kw10_and_kw40_run_over_the_complete_period_without_proposed_windows` |
| D | A: FS1 KW10, B: FS1 KW40 | kein automatisches A+B | unabhängige Fälle; jeder ausdrücklich zugeordnete gemeinsame Fall ist erlaubt | Testdaten | `test_d_alternative_dates_stay_separate_cases`, `test_any_explicit_combination_is_allowed` |
| E | A: FS1 KW10, B: FS2 KW10, gemeinsam AB | FS1+FS2 zusammen | AB enthält beide, ein Zustand | Testdaten | `test_e_a_joint_plan_calculates_both_outages_together` |

## Funktionsmatrix V01–V40

| ID | Situation | Erwartet | Ergebnis / Umsetzung | Status | Test(s) / Hinweis |
|---|---|---|---|---|---|
| V01 | eine FS in einem Fall | Einzelbewertung | wie in 7.x | Testdaten | `test_reference_runs_without_and_every_outage_runs_as_its_own_case` |
| V02 | zwei FS gleichzeitig | gemeinsamer Zustand | beide `outserv=0` in einem Lauf | Testdaten; PF P2/P3 offen | `test_a_case_with_two_outages_runs_them_together` |
| V03 | drei überlappende FS | wechselnde aktive Menge | Zustände berechnet; PF wendet die Fenster an | Testdaten | Test B |
| V04 | fünf FS gleichzeitig | eine QDS | durch den 50-FS-Test abgedeckt | Testdaten | `test_v37_fifty_outages_in_one_case_are_not_limited` |
| V05 | zehn FS nacheinander | richtige Folge | 10 Einzelzustände in Reihenfolge | Testdaten | `test_v05_ten_sequential_outages_keep_their_order` |
| V06 | FS in KW10 und KW40 | zwei Fenster, falls zulässig | nur vorgeschlagen; konservativer Lauf | Testdaten / **nicht umgesetzt** (Ausführung) | Test C |
| V07 | eine FS in mehreren Fällen | Mehrfachzuordnung | erlaubt, PF-Objekt nicht dupliziert | Testdaten | `test_shared_outage_counts_once_in_a_joint_plan`, Test D |
| V08 | gleiche FS in alternativen Wochen | Terminvarianten | je Termin eine `IntPlannedout`; eigene Termine erfasst, nicht angewendet | Testdaten | `test_d_alternative_dates_stay_separate_cases`, `test_own_dates_are_refused_while_overrides_are_off` |
| V09 | gleiche FS tatsächlich zweimal | beide Vorkommen | zwei Mitglieder, Zustände 1 → ∅ → 1 | Testdaten | `test_v09_the_same_outage_twice_in_one_case_is_two_real_executions` |
| V10 | alternative Fälle zur gleichen Zeit | keine ungeplante Kombination | nie automatisch kombiniert | Testdaten | `test_no_combination_is_generated_automatically` |
| V11 | gemeinsam gültige Fälle | ausdrücklicher Gesamtplan | direkte FS-Zuordnung | Testdaten | Test E |
| V12 | teilweise identische Fälle | Wiederverwendung nur bei voller Gleichheit | Fingerabdruck über FS, Fenster, feste FS; übernommenes Ergebnis gekennzeichnet | Testdaten | `test_v12_identical_cases_share_a_fingerprint_and_others_do_not`, `test_identical_cases_are_calculated_once_and_say_so` |
| V13 | zwei FS auf derselben Leitung | konsistenter Zustand | keine Warnung, Überlappung ist normale Planung; PF-Verhalten unbekannt (P4) | Testdaten; PF offen | `test_v13_overlapping_outages_are_normal_planning_not_a_warning` |
| V14 | FS mit dauerhafter Umschaltung | Nachwirkung berücksichtigt | Spill-over-Zeilen bewertet und gemeldet | Testdaten | `test_effect_after_the_window_is_assessed_as_well` |
| V15 | QDSL-Speicherzustand | richtige Fortsetzung | konservative Läufe sind durchgehend; Fenster abgelehnt, wenn `ElmQdsl` vorhanden | Statisch + Testdaten | `test_time_coupled_models_make_shorter_windows_inadmissible` |
| V16 | kurze FS zwischen QDS-Stützstellen | Ereignis erfasst | keine Zeile → Abdeckung 0 → nie „kein Grenzwert überschritten“ | Testdaten | `test_v16_short_outage_between_time_steps_has_no_coverage`, `test_incomplete_coverage_is_never_reported_as_secure` |
| V17 | FS beginnt vor dem Zeitraum | richtiger Ausgangszustand | mit Warnung behalten; Abdeckung reduziert | Testdaten | `test_f12_outage_starting_before_the_period_is_kept_with_a_warning` |
| V18 | FS endet nach dem Zeitraum | fortbestehender Zustand | Abdeckung < 100 % | Testdaten | `test_coverage_of_a_window_partly_after_the_period` |
| V19 | Netzmodellstand wechselt | richtiger Modellstand | PowerFactory innerhalb des Ganzzeitraum-Laufs überlassen | Statisch; nicht verifiziert | – |
| V20 | unterschiedliche Profile KW10 / KW40 | richtige Kalenderzuordnung | nur gleiche Zeitschritte werden verglichen | Testdaten | Test A, `test_v29_case_on_another_time_axis_is_not_compared` |
| V21 | REF bereits überlastet | vorbestehend | NO ADDITIONAL VIOLATION, gelb | Testdaten | `test_pre_existing_violation_is_no_additional_violation` |
| V22 | neue Überlastung | NEW | OVERLOAD, rot | Testdaten | `test_overload_inside_the_window_is_reported_with_its_element` |
| V23 | verschärfte Überlastung | WORSENED | je Zeitschritt | Testdaten | `test_every_time_step_is_classified` |
| V24 | verbesserte Überlastung | IMPROVED / RESOLVED | je Zeitschritt | Testdaten | `test_every_time_step_is_classified` |
| V25 | Spannung außerhalb des Bands | klassifiziert | VOLTAGE BAND | Testdaten | `test_voltage_band_violation_is_reported_separately` |
| V26 | nicht versorgte Insel | kein normaler Wert | DE-ENERGISED, eigenes Urteil und QA-Zeile | Testdaten | `test_v26_node_cut_off_by_the_case_is_reported_not_dropped` |
| V27 | QDS konvergiert nicht | nicht bewertbar | FAILED / NOT EVALUATED, der nächste Fall läuft | Testdaten | `test_failed_outage_case_is_reported_and_state_is_restored` |
| V28 | Referenz fehlt | kein behaupteter Vergleich | EXCEEDED, kein zeitgleiches Delta | Testdaten | `test_v28_without_reference_violations_are_not_called_new` |
| V29 | unterschiedliche Zeitachsen | fensterbezogene Prüfung | Fall nicht verglichen, NOT EVALUATED | Testdaten | `test_v29_case_on_another_time_axis_is_not_compared` |
| V30 | GUI abbrechen | keine Projektänderung; aufrufender Reportablauf erhält den Abbruch | kein Lauf, keine Kopie, keine Publikation; Abbruch verlässt `main`, mit und ohne vorhandene Berichtstabellen | Testdaten; IntReport-Behandlung noch in PF prüfen | `test_v30_cancel_in_the_case_manager_changes_and_calculates_nothing`, `test_cancel_reaches_the_report_caller_instead_of_returning_success`, `test_case_manager_dialog.py::test_gui_17_cancel_returns_nothing` |
| V31 | GUI ohne tkinter | kontrollierter Rückfall | gespeicherte Konfiguration, sonst je FS ein Fall; auch wenn der Dialog nicht aufgebaut werden kann | Testdaten; DPL-Rückfall **nicht umgesetzt** | `test_v31_*` (2), `test_a_dialog_that_cannot_be_built_counts_as_unavailable` |
| V32 | Ausnahme in der QDS | Zustand wiederhergestellt | Wiederherstellung in `finally`, mit Zurücklesen | Testdaten | `test_reference_failure_still_restores_option_and_result_binding`, `test_ignored_flag_that_cannot_be_restored_stops_the_run`, `test_memory_budget_stops_before_the_next_run_and_restores` |
| V33 | mehr als sechs Fälle | vollständige Bewertung, transparente Diagramme | Tabellen in Blöcken zu sechs; Diagramme die ersten sechs mit Hinweis | Testdaten | `test_more_than_six_cases_are_all_assessed_and_compared`, `test_charts_show_at_most_six_cases_and_say_so` |
| V34 | volle vs. Teil-QDS | Gleichwertigkeit | Teil-QDS wird nicht gerechnet | **Nicht umgesetzt** | braucht Probe zu P8 |
| V35 | gemeinsame Referenz | nur gültige Wiederverwendung | eine Referenz je Lauf (R0 oder Rfix) | Testdaten | `test_fixed_outages_stay_active_in_the_reference_and_every_case` |
| V36 | gleiche Zeiten, andere Schaltmaßnahmen | getrennte Bewertung | andere Objekte → andere Fingerabdrücke | Testdaten | `test_v12_*` |
| V37 | Fall mit 50 FS | keine Begrenzung auf zwei | 50 Mitglieder | Testdaten | `test_v37_fifty_outages_in_one_case_are_not_limited` |
| V38 | keine FS im Zeitraum | Referenz / keine Zusatzwirkung | NOT SIMULATED; keine Zeilen → nicht bewertet | Testdaten | `test_case_outside_the_simulated_period_is_not_simulated`, `test_v38_case_without_rows_in_its_window_is_not_assessed` |
| V39 | alte Vorlage mit LODF | Migrationsfehler sichtbar | LODF fehlt in Skript und Vorlage; alte Vorlage nicht gerendert | Testdaten (Abwesenheit); nicht verifiziert (Rendern) | `test_no_lodf_remains_in_the_template`, `test_table_contract_is_single_versioned_19_table_contract` |
| V40 | Jahresbericht, nur Teilfenster | keine falsche Jahresfreigabe | Aussagen A/B auf der Fallseite; INCOMPLETE COVERAGE | Testdaten | `test_report_states_what_the_assessment_does_and_does_not_prove` |

## Weitere Prüfungen

| Prüfung | Test |
|---|---|
| T01–T13, alle Beziehungen und ihre Zustandsfolgen | `test_all_thirteen_interval_relations` (13 Fälle) |
| halboffene Fenster `[Beginn, Ende)` | `test_windows_are_half_open` |
| Dauer mit ungleichen Zeitschritten gewichtet | `test_violation_duration_weights_uneven_time_steps` |
| eindeutige Zeitlabels bei der Herbst-Zeitumstellung | `test_clock_change_keeps_every_time_label_unique` |
| FS-Regeln, entfernte Fallbeziehungen und alte Zyklen | `test_rules_*`, `test_removed_relations_cannot_silently_affect_current_configurations`, `test_legacy_cycle_is_rejected_before_assignments_can_be_lost` |
| gespeicherte Konfiguration, Revision, beschädigte Datei | `test_configuration_is_saved_with_a_revision_and_read_back`, `test_damaged_configuration_is_reported_not_ignored` |
| alte Konfiguration wird unabhängige Fälle; Datei bis zum Speichern unverändert | `test_legacy_cases_are_flattened_once_and_then_stay_independent`, `test_saved_legacy_relations_become_independent_case_runs` |
| Ergebnisobjekt je Fall erhalten und benannt | `test_reference_runs_without_and_every_outage_runs_as_its_own_case` |
| geschriebene Tabellen passen zur MRT und ihrem SQL | `test_executed_publisher_output_matches_mrt_and_all_sql_queries` |
| beschädigte Konfiguration vor der Verwendung benannt (8 Varianten) | `test_damaged_configuration_is_named_before_anything_reads_it` |
| Fenster endet vor seinem Beginn | `test_window_that_ends_before_it_starts_is_refused` |
| unbekannte oder „Ignored“ feste FS gewarnt | `test_unknown_or_ignored_fixed_outages_are_warned_about` |
| Ergebnisobjekt ohne bewertete Variablen stoppt nach dem ersten Lauf, mit Kopie, Vorlage und Ursache; Fehlerbericht | `test_an_unusable_result_object_is_named_in_the_run_error`, `test_a_run_without_publication_says_that_the_report_cannot_be_generated`, `test_a_copy_without_the_variable_selection_gets_the_missing_monitors`, `test_recorded_text_lists_the_assessed_variables_first` |
| n-1-Sweep mit anderen als den geschriebenen Zeitpunkten stoppt mit beiden Listen | `test_a_failed_calculation_or_other_study_times_are_errors_and_settings_are_restored` |
| angewendete FS vor jedem Lauf zurückgelesen; Grund für ausgelassenes n-1 im Log | `test_applied_text_reads_the_option_and_the_flags_back`, `test_run_output_is_structured_in_steps_cases_and_tables`, `test_run_n1_marks_every_case_when_no_contingency_analysis_exists_and_reports_on_the_qa_page` |
| Wirkung jeder FS gegen REF in ihrem Fenster geprüft (APPLIED, EFFECT SEEN, NO EFFECT, NOT CHECKABLE), QA-Zeile | `test_an_outaged_line_without_load_in_its_window_is_applied`, `test_an_unrecorded_component_counts_when_the_network_differs_in_the_window`, `test_a_case_equal_to_ref_in_the_window_shows_no_effect`, `test_the_effect_is_not_checkable_without_reference_or_window_rows`, `test_outage_quality_warns_about_an_outage_without_effect` |
| Abdeckungstext passt zum Urteil | `test_coverage_text_never_says_complete_when_the_verdict_does_not` |
| scheiternder Vergleich trifft nur seinen Fall, ElmRes bleibt | `test_a_failing_comparison_fails_only_its_own_case` |
| Speicherbudget stoppt vor dem nächsten Lauf | `test_memory_budget_stops_before_the_next_run_and_restores` |
| wiederverwendeter Fall nennt das geteilte Ergebnisobjekt | `test_reused_case_names_the_result_object_it_shares` |
| Dialog nicht aufbaubar → Rückfall | `test_case_manager_dialog.py::test_a_dialog_that_cannot_be_built_counts_as_unavailable` |
| Fehler in Dialog-Schaltflächen werden angezeigt | `test_case_manager_dialog.py::test_errors_in_buttons_are_shown_not_swallowed` |
| schnelle Pfade liefern die alten Ergebnisse (Statistik, Plotpunkte, Überschreitung, Status je Schritt) | `test_extraction_builds_only_the_plotted_points_and_keeps_the_exact_statistics`, `test_array_statistics_equal_the_point_statistics`, `test_excess_function_keeps_the_definition`, `test_compare_element_agrees_with_step_status_at_every_step` |
| jeder Fall wird einmal beurteilt, alle Seiten zeigen dasselbe Urteil | `test_every_case_is_judged_once_and_all_pages_show_that_verdict` |
| Fenster nicht auf der Zeitachse: voller Vergleich, Warnung im Log | `test_windows_off_the_time_axis_are_compared_in_full_and_said_so` |

## Fall-Manager-Fenster – Funktionsprüfungen 1–20

Nicht in PowerFactory verifiziert; die Bearbeitungsregeln sind ohne Fenster getestet (`test_planner.py`), die Klicks im echten Tk-Fenster (`test_case_manager_dialog.py`).

| Prüfung | Aktion | Erwartet | Getestet mit | Tests |
|---|---|---|---|---|
| 1-3 | Fall A, dann B, dann A anklicken | A zeigt sofort seine FS, B die eigenen, A unverändert | Editor + echtes Fenster | `test_gui_01_to_03_*` (2) |
| 4 | FS aus der linken Liste hinzufügen | Falltabelle, FS-Zahl und Markierung sofort aktuell | Editor + echtes Fenster | `test_gui_04_and_06_*`, `test_gui_04_and_05_*` |
| 5 | FS aus einem Fall entfernen | nur die Zuordnung endet | Editor + echtes Fenster | `test_gui_05_and_09_*`, `test_gui_04_and_05_*` |
| 6 | eine FS in mehreren Fällen | erlaubt | Editor | `test_gui_04_and_06_*` |
| 7 | Fall kopieren | Zuordnungen kopiert, beide unabhängig | Editor | `test_gui_07_*` |
| 8 | Fall umbenennen | ID und andere Fälle bleiben unverändert | Editor + echtes Fenster | `test_gui_08_*`, `test_new_case_gets_a_generated_id_and_is_named_in_its_window` |
| 9 | Fall löschen | Freischaltungen bleiben; andere Fälle unverändert | Editor | `test_gui_05_and_09_*`, `test_gui_deleting_a_case_keeps_shared_assignments_in_other_cases` |
| 10 | feste Hintergrund-FS | getrennt von Fall-FS, nie beides; Rfix in der Vorschau | Editor | `test_gui_10_*` |
| 11 | Suche nach Betriebsmittel | nur passende FS | Editor + echtes Fenster | `test_gui_11_and_12_*`, `test_gui_11_*` |
| 12 | sehr viele FS | 5.005 FS in unter 0,5 s durchsucht; Listen scrollen | Editor | `test_gui_11_and_12_*` |
| 13 | überlappende FS in der Zeitachse | Überlappungsband; KW10 und KW40 beide lesbar | Editor + echtes Fenster | `test_gui_13_*` (2), `test_timeline_scale_is_monotonic_and_needs_a_window` |
| 14 | n-0, n-1, (n-1)' wählen | n-0 übergeben; n-1 und (n-1)' deaktiviert angezeigt (bis Teil 3 nicht verfügbar) und in einer Datei abgelehnt | Editor + echtes Fenster | `test_gui_14_and_16_*`, `test_gui_14_to_16_*`, `test_assessments_and_enabled_flags_are_validated` |
| 15 | QDS-Zeitraum | der Zeitraum des aktiven ComStatsim | Editor + echtes Fenster | `test_gui_15_*`, `test_gui_14_to_16_*` |
| 16 | keine Zeitoptimierung | keine Option, keine vorgeschlagenen Fenster; das Feld `mode` entfällt | Editor + echtes Fenster | `test_gui_14_and_16_*`, `test_gui_14_to_16_*` |
| 17 | Abbrechen | keine Rechnung, keine Änderung | echtes Fenster + Lauf | `test_gui_17_*`, `test_v30_*` |
| 18 | Berechnung starten | Konfiguration an den bestehenden GridLens-Lauf übergeben | echtes Fenster + Lauf | `test_gui_18_and_19_*`, `test_a_case_with_two_outages_runs_them_together` |
| 19 | keine Ergebnisansicht | Fenster schließt; das PDF ist das einzige Ergebnis | echtes Fenster | `test_gui_18_and_19_*` |
| 20 | erneut öffnen | gespeicherte Zuordnungen kommen unverändert zurück | Editor + echtes Fenster | `test_gui_20_*` (2) |
| GUI-Testwerkzeug: eigenständiges Skript mit eigener Kopie des Fallmanagers (lädt `main.py` nie), Kopie gleich dem Produktionsfenster; Projekt-FS nur lesend; temporäre Konfigurationskopie; Demodaten; fehlendes Tk | `test_preview_case_manager.py` (9) |
| Tabellenfilter und Sortierung: enthält / exakter Wert, Sortieren per Kopf ▲▼, Spaltenbreiten, Filter auf jedem Reiter ausgerichtet | `test_filter_rows_*`, `test_sort_rows_*`, `test_column_widths_*`, `test_gui_11_every_table_filters_per_column_and_clears`, `test_filters_stand_exactly_under_their_columns`, `test_header_click_sorts_and_shows_the_direction` |
| zwei Reiter (Case Manager, Settings), Statuszeile, Problemliste; feste FS und Regeln auf eigener Settings-Seite | `test_tabs_status_line_and_problem_list`, `test_fixed_outages_and_rules_live_on_their_own_tab` |
| höchstens 5 Fälle (Fenster, gespeicherte Datei, je FS ein Fall); IDs generiert, nie getippt | `test_gui_at_most_five_cases`, `test_gui_one_case_per_outage_stops_at_five`, `test_more_than_five_cases_are_refused_where_engineers_define_them`, `test_gui_ids_are_generated_and_the_engineer_only_names_cases`, `test_new_case_gets_a_generated_id_and_is_named_in_its_window`, `test_new_and_copy_stop_at_five_cases` |
| Reihenfolge im Workspace: verfügbare FS, FS des Falls, Fälle; Hover-Texte an Beziehungen, Schaltflächen, Spaltenköpfen und Filtern | `test_workspace_runs_available_outages_then_case_outages_then_cases`, `test_hover_explains_the_controls_without_case_relations` |
| Review-Korrekturen: je FS ein Fall nur im Zeitraum; Copy und Delete lassen andere Fälle unverändert; alte Beziehungen werden direkte Zuordnungen; Regelauswahl trennt gleichnamige FS; eine Auflösung je Aktualisierung; Tippen schließt einen Hinweis | `test_one_case_per_outage_takes_only_outages_in_the_simulated_period`, `test_copy_keeps_own_dates_independent`, `test_legacy_cases_are_flattened_once_and_then_stay_independent`, `test_rule_choices_keep_outages_with_the_same_name_apart`, `test_statuses_problems_and_preview_share_one_resolution`, `test_hover_explains_the_controls_without_case_relations` |
| zweites Review: eine gespeicherte Datei mit mehr als fünf Fällen öffnet sich trotzdem (ausgeschlossen bleibt ausgeschlossen); der GUI-Test übersteht eine beschädigte gespeicherte Datei und importiert, was sein eigener Code braucht; Vorschau-Labels werden wiederverwendet; ein direktes Rendern bricht das ausstehende ab; je FS ein Fall leert den Fallfilter | `test_a_saved_file_with_too_many_cases_still_opens_so_cases_can_be_deleted`, `test_a_damaged_saved_configuration_does_not_stop_the_gui_test`, `test_the_copied_case_manager_matches_gridlens_report`, `test_refreshes_reuse_widgets_and_render_once` |
| Häkchen in der FS-Liste (anhaken nimmt auf, abhaken entfernt, ein schneller zweiter Klick ist kein Doppelklick), Name und Beschreibung im eigenen Fenster (Doppelklick, Edit, New), nur `IntPlannedout` gelesen (keine Demand Transfers) | `test_the_check_box_adds_and_removes_one_outage`, `test_ticking_the_box_adds_and_removes_an_outage`, `test_new_case_gets_a_generated_id_and_is_named_in_its_window`, `test_double_click_on_a_case_opens_name_and_description`, `test_only_planned_outages_are_read_not_demand_transfers` |
| klare Meldung bei einem Ergebnisobjekt ohne Auslastung oder Spannung; das Laufende sagt, ob Berichtstabellen publiziert wurden | `test_a_result_object_without_loading_or_voltage_says_what_is_missing_and_what_to_do`, `test_a_result_object_with_only_dead_terminals_says_so`, `test_an_unusable_result_object_is_named_in_the_run_error`, `test_a_run_without_publication_says_that_the_report_cannot_be_generated`, `test_a_successful_run_names_the_report_to_generate` |
| große FS-Tabelle: Zeilen bei Häkchen/Fallwechsel weiterverwenden; Scrollposition und Auswahl erhalten; Filter und Löschen | `test_large_outage_table_updates_one_checkbox_without_rebuilding_or_scrolling`, `test_filtered_rows_reattach_with_current_values_and_removed_rows_stay_gone` |
| sichtbare Erklärung mit Beispielen für Hintergrund-FS und jede Regel; Häkchen erklärt; Bedienelemente und Hilfe bei 1000×620 und 1280×800 sichtbar | `test_fixed_tab_explains_shared_outages_rules_and_optional_use_without_hover`, `test_explanations_and_rule_controls_fit_the_window` (2 Größen) |
| Run flags: click, Space, filtering and live settings preview; background, windows, reuse, blocked and excluded cases | `test_run_flags_toggle_the_clicked_case_and_update_the_settings_preview`, `test_calculation_preview_lists_effective_settings_and_keeps_blocked_cases_out` |
| Abbrechen oder ein gescheiterter Lauf beenden das Skript mit Exit-Code 1, es wird kein Bericht erzeugt | `test_cancel_or_a_failure_ends_the_script_with_an_error_code_so_no_report_is_rendered`, `test_cancel_says_that_the_report_is_not_generated` |
| gespeicherte Umstellung verliert ihren einmaligen Hinweis; Schema-2-Datei `.v2.json` ersetzt nie die Schema-1-Datei des ausgelieferten Skripts; FS-Auswahl einmal aufgebaut | `test_the_upgrade_note_is_shown_until_the_cases_are_saved`, `test_this_version_never_overwrites_the_file_of_the_delivered_script`, `test_outage_choices_are_built_once` |
| nur Tests, `main.py` und `MASTER_GRIDLENS.mrt` nötig: `tests/_paths.py` findet beide in `outage-assessment/` oder neben `tests/`; Werkzeug-Tests werden ohne `ui/` übersprungen | geprüft durch einen Lauf in einer Kopie mit nur diesen Dateien (verschachtelt und flach) |
| Tastatur: Entf/Rücktaste entfernen in jeder Liste, Strg+N/S/O/F/Enter, Strg+A | `test_keyboard_deletes_and_shortcuts` |

## Teil 1 und Teil 2 (23. Oktober 2026): n-1-Vorbereitung, Settings, Klassifizierung

Drei Nachweisstufen, getrennt gehalten:

- **Statisch** – aus dem Code gelesen, durch einen Test des Quelltexts geprüft, kein Lauf.
- **Mock / lokales Tk** – automatischer Test mit nachgebildeten PowerFactory-Objekten
  oder reinen Daten sowie das echte Tk-Fenster unter macOS (Tk 8.6).
- **PowerFactory 2026** – in PowerFactory gelaufen und bestätigt: **für Teil 1 und 2 noch nichts.**

| Bereich | Was | Stufe | Tests |
|---|---|---|---|
| Probe 2.1 (strikte Privacy) | keine künstliche sensible Zeichenfolge oder Zahl in der Ausgabe; jede Zeile ein erlaubtes Label mit erlaubtem Token; nur erlaubte Lesemethoden aufgerufen; kein Name, Pfad oder anderes Attribut gelesen; Fehler und Abstürze ergeben nur Fehlercodes; Allowlist nicht umgehbar | Mock | `test_no_sensitive_string_or_value_ever_reaches_the_output`, `test_every_output_line_is_an_allowlisted_label_with_an_allowlisted_token`, `test_only_allowlisted_methods_are_called_and_nothing_writes`, `test_no_name_path_or_other_attribute_is_read`, `test_failures_yield_only_error_codes_never_their_text`, `test_a_check_that_crashes_reports_its_category_only`, `test_a_label_or_token_outside_the_allowlist_cannot_be_printed` |
| Probe 2.1 statische Analyse | Importe nur `sys`/`powerfactory`; keine Datei, kein Netzwerk, kein `print`, `repr`, `str()`, f-String oder dynamisches Format; keine verbotenen Attributnamen; PowerFactory-Aufrufe nur über das Gateway | Statisch | `test_static_*` (4) |
| Probe 2.1 Befunde | Time Sweep, Planned Outages, Ergebnisse, Betriebsmittel und Grid-Attribut, ElmRes-Methoden, Unterergebnisse, Code 3, Ablage | Mock | `test_the_expected_findings_are_reported`, `test_without_code_three_no_sparse_indicator_is_claimed` |
| Probe 2.1 in einem echten Projekt | Ausgabe frei von Projektdaten | **PowerFactory – offen** | Hadi führt `powerfactory_tests/inspect_contingency_interface.py` aus; den kopierten Text auf eigene PowerFactory-Meldungen prüfen |
| Testlauf-Werkzeug | abgeschaltet, lehnt ein Projekt ab, das nicht die konfigurierte Kopie ist, ohne es zu nennen, fragt vor dem Schreiben, stellt wieder her; gibt keine Namen, Werte, Zeitpunkte oder Fehlertexte aus | Statisch + Mock | `test_prepared_test_run_is_disabled_guarded_and_prints_no_names`; **nicht ausgeführt, braucht eine eigene Freigabe** |
| GUI | genau zwei Reiter, kein Ergebnis-Reiter; Probleme im Case Manager; Fixed background & rules unter Settings | Lokales Tk | `test_tabs_status_line_and_problem_list`, `test_filters_stand_exactly_under_their_columns`, `test_fixed_tab_explains_*` |
| GUI | n-0, n-1, (n-1)' sichtbar; n-1 und (n-1)' deaktiviert mit Erklärung; in einer Datei abgelehnt | Lokales Tk + Editor | `test_gui_14_to_16_*`, `test_gui_14_and_16_*` |
| GUI | Settings: jede Einstellung mit Herkunft und Kategorie; Kategorie B schreibgeschützt; QDS-Zeitbasis schreibgeschützt | Lokales Tk | `test_settings_tab_shows_every_setting_with_source_and_hover_text` |
| GUI | ungültige Eingabe rot, Reiter *Settings (!)*, Start gesperrt; übernehmen, Override, Standards wiederherstellen; Start übernimmt Änderungen | Lokales Tk | `test_invalid_setting_is_marked_and_blocks_the_start`, `test_apply_override_and_restore_defaults` |
| GUI | Tooltips: etwa 450 ms Verzögerung, verschwinden beim Verlassen, an jeder Einstellung und Schaltfläche; der Start-Tooltip verspricht kein automatisches PDF | Lokales Tk | `test_tooltip_appears_after_the_delay_and_goes_on_leave`, `test_hover_explains_*`, `test_every_setting_has_a_hover_text` |
| GUI | Fallmanager innerhalb von PowerFactory | **PowerFactory – offen** | `ui/preview_case_manager.py` |
| Settings | Standards gleich dem Code; Spannungsvorschlag gekennzeichnet; Einlesen, endliche Zahlen, positive Grenzen, nicht negative Toleranzen, Min < Max, Warnschwelle ≤ Grenze | Testdaten | `test_settings.py` (31) |
| Settings | mit den Fällen gespeichert (vorläufiges JSON), Fälle unverändert, ungültige Datei abgelehnt, `mode` alter Dateien ignoriert | Testdaten | `test_settings_are_stored_with_the_cases_and_do_not_touch_them`, `test_invalid_saved_settings_are_refused_with_the_reason`, `test_a_file_of_an_earlier_version_with_mode_still_loads` |
| n-0-Regression | Standards reproduzieren jede Berichtszeile exakt; geänderte Grenzen ändern nur die Bewertung; wiederhergestellte Standards reproduzieren das Original | Testdaten | `test_default_settings_reproduce_the_n0_report_exactly`, `test_changed_assessment_limits_change_only_the_assessment_and_restore_cleanly`, `test_report_names_the_settings_and_the_rules_version` |
| n-0 mit Overrides | ein echter QDS-Lauf mit geänderten Grenzen | **PowerFactory – offen** | – |
| Klassifizierung | alle zehn Status, die Beispiele des Master-Prompts, Grenzwert- und Gleichheitsgrenzen, Benutzertoleranzen, ungültige und fehlende Werte, NOT_APPLICABLE, NOT_COMPARABLE je Identitätsfeld und Grenzwertdefinition, gleiche Post-Fault-Phase, Rangfolge behält Gründe, MARGIN_REDUCED, zeitgleiche Differenz, reine Funktion, n-0-Status unberührt | Testdaten | `test_classification.py` (34) |
| Zeitbasis | keine Zeitoptimierung mehr in der Laufzeit; Dateien mit `mode` laden | Testdaten | `test_no_time_optimisation_remains_in_the_runtime`, `test_c_kw10_and_kw40_run_over_the_complete_period_without_proposed_windows` |
| Bewusst deaktiviert | n-1, (n-1)', Kategorie B, Post-Fault-Spannungsgrenzen, native Ablage, `GL_<Szenario>_CLASSIFICATION` | – | Teil 3 |
| Netzumfang | jedes Grid des Modells gelistet (inaktive gekennzeichnet); Auswahl der bewerteten Betriebsmittel filtert die n-0-Bewertung und hat Vorrang vor `GRID_NAME_FILTER`; Contingency-Auswahl gespeichert, per `ComOutage.GetObject` als Vorschau, nie angewendet; Warnungen für fehlende oder inaktive Grids; Berichtszeile *Network scope* | Testdaten + lokales Tk | `test_network_scope.py` (7), `test_network_scope_lists_the_grids_of_the_model_for_selection`, `test_probe_follows_a_grid_selection_like_the_report` |
