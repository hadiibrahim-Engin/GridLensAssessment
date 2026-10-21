# GridLens 8.0 – Testmatrix (Lieferteil G)

Englische Fassung: [../TEST_MATRIX.md](../TEST_MATRIX.md)

Statuskategorien:

- **Testdaten** – automatischer Test mit PowerFactory-Nachbildungen oder reinen Daten, bestanden (`.venv/bin/pytest -q`)
- **Statisch** – folgt aus der Codestruktur, geprüft, ohne eigenen Test
- **PowerFactory** – in PowerFactory 2026 ausgeführt (bisher keiner)
- **Nicht verifiziert** – offen; braucht PowerFactory oder ist nicht umgesetzt

Keine Zeile ist **in PowerFactory verifiziert**. Die automatische Testsuite:
292 Tests, alle in der Projekt-`.venv` (python.org-Python 3.11 mit Tk 8.6); 5 davon
öffnen den echten Tk-Dialog und werden nur übersprungen, wo `tkinter` fehlt. Die Testnamen sind englisch, wie der Code.

## Tests A–E der Vorgabe

| Test | Eingang | Erwartet | Ergebnis | Status | Test |
|---|---|---|---|---|---|
| A | REF 80 %, 60 %; Fall 70 %, 85 % | Differenz der Maxima +5 pp, zeitgleiches Delta +25 pp | +5 / +25 um 11:00 | Testdaten | `test_planner.py::test_a_coincident_delta_is_not_the_difference_of_the_maxima` |
| B | FS1 08–13, FS2 10–15, FS3 11–14 | 5 Zustände wie in Abschnitt 7 der Vorgabe | identisch | Testdaten | `test_b_three_overlapping_outages_pass_through_five_states` |
| C | FS1 KW10, FS2 KW40 in einem Fall | nicht 52 Wochen, *falls* Trennung nachgewiesen; keine unbewiesene Lücke | 2 Fenster vorgeschlagen, nicht gerechnet (Trennung nicht nachweisbar) → konservativ ganzer Zeitraum | Testdaten; Ausführung der Fenster **nicht umgesetzt** | `test_c_kw10_and_kw40_give_two_proposed_windows_but_run_conservatively` |
| D | A: FS1 KW10, B: FS1 KW40 | kein automatisches A+B | zwei Fälle; ein gemeinsamer Fall mit einem Alternativpaar wird abgelehnt | Testdaten | `test_d_alternative_dates_stay_separate_cases`, `test_d_alternatives_in_one_joint_case_are_refused` |
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
| V11 | gemeinsam gültige Fälle | ausdrücklicher Gesamtplan | `includes` | Testdaten | Test E |
| V12 | teilweise identische Fälle | Wiederverwendung nur bei voller Gleichheit | Fingerabdruck über FS, Fenster, feste FS; übernommenes Ergebnis gekennzeichnet | Testdaten | `test_v12_identical_cases_share_a_fingerprint_and_others_do_not`, `test_identical_cases_are_calculated_once_and_say_so` |
| V13 | zwei FS auf derselben Leitung | konsistenter Zustand | Warnung; PF-Verhalten unbekannt (P4) | Testdaten (Warnung); PF offen | `test_v13_two_outages_on_the_same_line_warn` |
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
| V30 | GUI abbrechen | keine Projektänderung | kein Lauf, keine Kopie, keine Publikation | Testdaten | `test_v30_cancel_in_the_case_manager_changes_and_calculates_nothing`, `test_case_manager_dialog.py::test_cancel_returns_nothing` |
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
| Regelkonflikte, bedingte Fälle, Zyklen | `test_rules_*`, `test_conditional_case_needs_its_precondition`, `test_including_cases_in_a_circle_is_refused` |
| gespeicherte Konfiguration, Revision, beschädigte Datei | `test_configuration_is_saved_with_a_revision_and_read_back`, `test_damaged_configuration_is_reported_not_ignored` |
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
| Fall-Editor ohne Fenster: anlegen, kopieren, umbenennen, löschen, zuordnen, fixieren, eigene Termine, Regeln | `test_editor_*` (6) |
| Dialog-Schaltflächen erreichen den Editor, OK liefert seine Konfiguration | `test_case_manager_dialog.py::test_buttons_reach_the_editor_and_ok_returns_its_configuration` |
| jeder Fall wird einmal beurteilt, alle Seiten zeigen dasselbe Urteil | `test_every_case_is_judged_once_and_all_pages_show_that_verdict` |
| Fenster nicht auf der Zeitachse: voller Vergleich, Warnung im Log | `test_windows_off_the_time_axis_are_compared_in_full_and_said_so` |
