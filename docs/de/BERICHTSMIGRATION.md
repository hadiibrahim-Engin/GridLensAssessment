# Berichtsmigration: Datenvertrag 5.0 → 6.0

Englische Fassung: [../REPORT_MIGRATION.md](../REPORT_MIGRATION.md)

| | Vorher | Nachher |
|---|---|---|
| Publisher | 7.0.0 | 8.0.0 |
| MRT (`MASTER_GRIDLENS.mrt`) | 5.0.0 | 6.0.0 → 6.1.0 (eine Seite je Kapitel; Felder ohne Ziffern) |
| Datenvertrag | 5.0, 18 Tabellen | 6.0, 19 Tabellen → 6.2, 23 Tabellen (n-1-Kapitel) |

Die MRT wird erzeugt: `python3 tools/build_mrt.py`. `tests/test_mrt.py` prüft,
dass ihre Datenquellen `TABLES` entsprechen und dass jede SQL-Abfrage gegen die
Tabellen läuft, die ein echter Lauf schreibt. Die neue Vorlage ist **weder** in
PowerFactory **noch** mit dem lokalen Stimulsoft-Harness gerendert.

Eine alte Vorlage 5.0 darf nicht mit dem Skript 6.0 verwendet werden: ihr
LODF-Kapitel fragt `ScriptedLodfRanking` und `ScriptedReportMeta.lodf_text` ab,
die es nicht mehr gibt; die Abfrage sollte daher fehlschlagen statt alte Daten
zu zeigen (V39). Wie Stimulsoft in PowerFactory das meldet, ist nicht
ausprobiert; `ScriptedReportMeta` trägt `template_version` und
`data_contract_version` zur Kontrolle.

## Tabellen

| Tabelle | Änderung |
|---|---|
| `ScriptedLodfRanking` | **entfernt** |
| `ScriptedCaseComparison` | **neu**, Matrixform (`block`, `row_order`, `element_name` = Kennzahl, `ref_text`, `c1..c6_text`, `h1..h6_name`, `col_count`, `violation`) |
| `ScriptedCalculationRuns` | **neu**: `run_order`, `run_id`, `run_kind`, `case_name`, `reference_text`, `period_text`, `time_steps`, `elapsed_text`, `status`, `provenance_text`, `result_object`, `note` |
| `ScriptedReportMeta` | entfernt `lodf_text`; neu `case_source_text`, `reference_text`, `qds_mode_text`, `coverage_statement` (alle Pflicht) |
| `ScriptedCases` | eine Zeile je Planungsfall; neu `case_description`, `outage_names`, `reference_text`, `states_text`, `windows_text`, `coverage_text`, `provenance_text`. `period_text` und `equipment_name` nennen alle FS des Falls. |
| `ScriptedCaseMetrics` | `largest_delta_text` ersetzt durch `coincident_delta_text` (zeitgleich) und `maxima_difference_text`; neu `violation_hours_text`, `coverage_text` |
| `ScriptedKpis` | `delta_text` ist jetzt der größte zeitgleiche Anstieg |
| `ScriptedTrendLargestDelta` | die Leitung wird nach dem zeitgleichen Delta gewählt |
| alle übrigen Tabellen | unverändert; sie zeigen Werte über den Gesamtzeitraum (Differenz der Maxima, wo sie vergleichen) |

## Kapitel der Vorlage

| Nr. | Kapitel | Änderung |
|---|---|---|
| 3 | Model Quality Assurance | neue Prüfungen: Planungsfälle, Fallwarnungen, feste FS, Abdeckung der Freischaltfenster, Wirkung außerhalb der Fenster, durch einen Fall spannungslose Knoten, Rechenzeitraum |
| 4 | Calculated Cases and Planned Outages | Überschriften *Outage periods*, *Findings at the same time steps as Reference*; Kasten mit Aussage A/B |
| 5 | **Case Definition and Network States** | neu: FS, Referenz, Netzzustände, Abdeckung, Herkunft des Ergebnisses |
| 6 | Reference Case | unverändert |
| 7 | Metric View | zeitgleicher Anstieg und Differenz der Maxima nebeneinander, Dauer verursachter Verletzungen; Erläuterung |
| 8 | **Case Comparison Summary** | neu: Kennzahlen je Fall, REF zuerst, Blöcke zu sechs Fällen |
| 9–13 | Case comparison, Radar, Top 10, Zeitplots | neu nummeriert; Zeitplot 13 nutzt das zeitgleiche Delta |
| 12 (alt) | Line Impact Ranking (LODF) | **entfernt** |
| 14 | Top 10 je Fall | neu nummeriert |
| 15 | **Calculation Evidence** | neu: jeder Lauf, Art, Schritte, Zeit, Status, erhaltenes Ergebnisobjekt, Hinweis; Aussage zum Rechenzeitraum |
| 16 | Anhang A–C | neu nummeriert |

Das Inhaltsverzeichnis hat jetzt 19 Einträge im Abstand von 0,7 cm, damit es
weiterhin zwischen Seitenkopf und -fuß passt.

## Was in der PDF-Vorlage zu prüfen ist

Die Vorlage ist generiert und gegen den Datenvertrag getestet, aber nicht
gerendert. Beim ersten Rendern in PowerFactory ansehen:

- Kapitel 5, 8 und 15 erscheinen je auf einer eigenen Seite, auch ohne Fälle.
- Die Matrix in Kapitel 8 zeigt je Fallanzahl die richtigen Spalten.
- Lange Zellen (`states_text`, `note`) brechen um, ohne das Zeilenraster zu zerreißen.
- Das Inhaltsverzeichnis passt auf eine Seite, alle Links springen richtig.
