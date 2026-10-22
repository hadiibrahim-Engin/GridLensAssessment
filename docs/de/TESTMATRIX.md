# GridLens 8.0 – Testmatrix (Lieferteil G)

Englische Fassung: [../TEST_MATRIX.md](../TEST_MATRIX.md)

Statuskategorien:

- **Testdaten** – automatischer Test mit PowerFactory-Nachbildungen oder reinen Daten, bestanden (`.venv/bin/pytest -q`)
- **Statisch** – folgt aus der Codestruktur, geprüft, ohne eigenen Test
- **PowerFactory** – in PowerFactory 2026 ausgeführt (bisher keiner)
- **Nicht verifiziert** – offen; braucht PowerFactory oder ist nicht umgesetzt

Keine Zeile ist **in PowerFactory verifiziert**. Die automatische Testsuite:
375 Tests, alle in der Projekt-`.venv` (python.org-Python 3.11 mit Tk 8.6); 28 davon
öffnen das echte Tk-Fenster und werden nur übersprungen, wo `tkinter` fehlt. Die Testnamen sind englisch, wie der Code.

## Tests A–E der Vorgabe

| Test | Eingang | Erwartet | Ergebnis | Status | Test |
|---|---|---|---|---|---|
| A | REF 80 %, 60 %; Fall 70 %, 85 % | Differenz der Maxima +5 pp, zeitgleiches Delta +25 pp | +5 / +25 um 11:00 | Testdaten | `test_planner.py::test_a_coincident_delta_is_not_the_difference_of_the_maxima` |
| B | FS1 08–13, FS2 10–15, FS3 11–14 | 5 Zustände wie in Abschnitt 7 der Vorgabe | identisch | Testdaten | `test_b_three_overlapping_outages_pass_through_five_states` |
| C | FS1 KW10, FS2 KW40 in einem Fall | nicht 52 Wochen, *falls* Trennung nachgewiesen; keine unbewiesene Lücke | 2 Fenster vorgeschlagen, nicht gerechnet (Trennung nicht nachweisbar) → konservativ ganzer Zeitraum | Testdaten; Ausführung der Fenster **nicht umgesetzt** | `test_c_kw10_and_kw40_give_two_proposed_windows_but_run_conservatively` |
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
| 14 | n-0 und n-1 wählen | n-0 übergeben; n-1 deaktiviert angezeigt (nicht verfügbar) und in einer Datei abgelehnt | Editor + echtes Fenster | `test_gui_14_and_16_*`, `test_gui_14_to_16_*`, `test_assessments_and_enabled_flags_are_validated` |
| 15 | QDS-Zeitraum | der Zeitraum des aktiven ComStatsim | Editor + echtes Fenster | `test_gui_15_*`, `test_gui_14_to_16_*` |
| 16 | keine Zeitoptimierung | keine Option, keine vorgeschlagenen Fenster; Modus fest konservativ | Editor + echtes Fenster | `test_gui_14_and_16_*`, `test_gui_14_to_16_*` |
| 17 | Abbrechen | keine Rechnung, keine Änderung | echtes Fenster + Lauf | `test_gui_17_*`, `test_v30_*` |
| 18 | Berechnung starten | Konfiguration an den bestehenden GridLens-Lauf übergeben | echtes Fenster + Lauf | `test_gui_18_and_19_*`, `test_a_case_with_two_outages_runs_them_together` |
| 19 | keine Ergebnisansicht | Fenster schließt; das PDF ist das einzige Ergebnis | echtes Fenster | `test_gui_18_and_19_*` |
| 20 | erneut öffnen | gespeicherte Zuordnungen kommen unverändert zurück | Editor + echtes Fenster | `test_gui_20_*` (2) |
| GUI-Testwerkzeug: eigenständiges Skript mit eigener Kopie des Fallmanagers (lädt `gridlens_report.py` nie), Kopie gleich dem Produktionsfenster; Projekt-FS nur lesend; temporäre Konfigurationskopie; Demodaten; fehlendes Tk | `test_case_manager_gui.py` (9) |
| Tabellenfilter und Sortierung: enthält / exakter Wert, Sortieren per Kopf ▲▼, Spaltenbreiten, Filter auf jedem Reiter ausgerichtet | `test_filter_rows_*`, `test_sort_rows_*`, `test_column_widths_*`, `test_gui_11_every_table_filters_per_column_and_clears`, `test_filters_stand_exactly_under_their_columns`, `test_header_click_sorts_and_shows_the_direction` |
| Reiter, Statuszeile, Problemliste; feste FS und Regeln auf eigenem Reiter | `test_tabs_status_line_and_problem_list`, `test_fixed_outages_and_rules_live_on_their_own_tab` |
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
