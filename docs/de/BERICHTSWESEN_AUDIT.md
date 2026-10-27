# GridLens-Berichtswesen – Audit, Zuordnung und Plan (Gate A)

Gate A von `GridLens_Coding_Agent_Arbeitsauftrag_Reporting.md` (verbindlicher
Berichtsauftrag, Wurzel des Repositorys): was vorhanden ist, was die zwei
neuen Berichte brauchen, wie jedes Berichtselement auf PowerFactory-Ergebnisse
abgebildet wird, welche API-Fragen offen sind und in welchen Schritten die
Gates B–D folgen. Stand: 26. Oktober 2026. Englische Fassung:
[`docs/REPORTING_AUDIT.md`](../REPORTING_AUDIT.md); beide werden gemeinsam
gepflegt.

Für dieses Audit wurde keine PowerFactory-Rechnung gestartet; alles stammt aus
Repository, Vorlage und früheren Probeläufen.

---

## 1. Eingangsvorlage

| Prüfung | Ergebnis |
|---|---|
| Datei | `powerfactory/MASTER_GRIDLENS.mrt`, MRT 6.2.0, Datenvertrag 6.2 |
| Identität mit `MASTER_GRIDLENS(1).mrt` des Auftrags | der Auftrag beschreibt 21 Seiten, 23 `Scripted…`-Datenquellen, die vier Contingency-Tabellen und eine leere SQLite-Verbindung: genau diese Datei. `MASTER_GRIDLENS(1).mrt` selbst liegt nicht auf diesem Rechner; der Name gilt als Download-Kopie davon. |
| Sicherung | `templates/archive/MASTER_GRIDLENS_6.2.0_original.mrt`, schreibgeschützt, SHA-256 `d541c80d8469bb37…` (identisch zur Eingangsdatei) |
| Seiten | Cover, Contents, Quality, Cases, Casedef, Reference, Metrics, Summary, Comparison, **Radar**, Toplines, **Trendmost**, **Trenddelta**, Topcase, Contingency, Findings, Evidence, Appendix, Appa, Appb, Appc |
| Diagramme | 17 Linien, **7 Radar**, 2 Kreise, 1 Balken, 1 Säulen; bis zu 7 Reihen in einem Diagramm |
| Farben | DIgSILENT-Rot `[181:18:62]`, Grautöne, Warngelb, feste Fallpalette. Der Auftrag nennt Navy/Teal; die Vorlage hat keine. Das **tatsächliche** Design bleibt. |
| Deckblatt | `CoverRow1_L` „Study ID“ / `CoverRow1_V` `{ScriptedReportMeta.study_id}`: zu entfernen, darunterliegende Zeilen rücken nach |
| LODF | keine (seit 8.0 entfernt; Tests verbieten es) |
| Verbindung | leer (`<ConnectionStringEncrypted />`); PowerFactory setzt die Datenbank je IntReport zur Laufzeit |
| PDF-Weg | GridLens publiziert die Tabellen in seinen `IntReport`; PowerFactory rendert die MRT als eigenen Schritt (Entscheidung vom 28.09.2026: kein `IntReport.Execute()` aus dem Skript) |

---

## 2. Ist-Stand gegen den Auftrag

| Auftrag | Ist-Stand | Lücke / Maßnahme |
|---|---|---|
| §1 n-0 = QDS des Grundnetzes ohne FS | REF R0 (`iopt_maint = 0`); Rfix mit festen FS | passt; Rfix wird so benannt |
| §1 n-1 = Time-Sweep-Contingency-Analyse des Grundnetzes | `ComSimoutage`, `isPlannedOutages = 0`, Zeitraum als `calcPeriod = 4` | passt |
| §1 (n-1)' = Time Sweep je FS-Szenario mit seinen aktiven FS | derselbe Sweep, `isPlannedOutages = 1`, nur die FS des Falls nicht „Ignored“ | passt |
| §1 Zeitbasis unverändert aus `ComStatsim` | QDS: ganzer Zeitraum. **n-1/(n-1)': nur die QDS-Schritte von der ersten bis zur letzten Fensterstunde eines Falls** (Entscheidung 23.10.2026) | **Entscheidung D1** (Abschnitt 6). Der Auswertekern berichtet, was gerechnet wurde, und zeigt geforderte gegen tatsächliche Zeitpunkte (Abdeckungsachse a). |
| §1 FS-Vorfehlerzustand | jeder Fall rechnet bereits seine eigene **QDS mit seinen FS** (ausdrücklich, nicht stillschweigend): native Vorfehlerwerte über den ganzen Zeitraum | bleibt und wird als „FS-Vorfehlerzustand (QDS mit den FS des Falls)“ ausgewiesen |
| §1 bereits ausgeschaltetes Betriebsmittel als Contingency | `NOT_APPLICABLE` über `ComOutage.GetObject` ∩ `IntPlannedout.components` (geprüft 23.10.) | passt |
| §2 persistente Ergebnisse als benannte `ElmRes` | `GridLens_<stamp>_REF`, `…_<Fall>`, `…_<Fall>_N1`, `…_<Fall>_N1P` (Kopien nach dem Lauf, geprüft 24.10.) | passt; der Stempel wird die **Run-ID** |
| §2 Statistik im Auswertekern, nicht in MRT-Ausdrücken | ja | passt |
| §2 keine CSV-/Excel-/JSON-Ergebnisexporte | keine; nur die Fallkonfiguration ist JSON (Settings, keine Ergebnisse) | passt |
| §2 Streaming, kein dichter Würfel | QDS: Arrays je Reihe und Lauf; **n-1: `read_n1_results` hält jeden Wert eines ganzen Sweeps in einem Dict** | **Gate B**: je Zeitpunkt lesen und einstufen (Referenz- und Szenario-Teilergebnis nebeneinander), aggregieren, verwerfen |
| §5 Statuscodes 0–5, 90–93, `MARGIN_REDUCED` | `CLASSIFICATION_STATUSES` genau diese | passt |
| §5 Vergleichsschlüssel: Zeit, Contingency, Betriebsmittel, Kriterium, Post-Fault-Phase | `COMPARISON_IDENTITY` genau diese | passt |
| §5 Unter- und Überspannung getrennt | eine Größe `voltage` mit Band | **Gate B**: Kriterien `loading`, `voltage_low`, `voltage_high` |
| §5 Ergebnis-ID mit Run, Szenario, Zeit, Contingency, Phase, Betriebsmittel, Kriterium | Identität ohne Run und Szenario | **Gate B**: beides ergänzen |
| §6 Statistiken 1–10 je Szenario und Ebene | nur schwerster Status je Betriebsmittel und Ergebnisanzahlen | **Gate B**: Statistikschicht (eindeutige Betriebsmittel, Ereignisse, Contingencies, Zeitpunkte, Befundfolgen, Extrema, zeitgleiche Verschlechterung, Abdeckung auf drei Achsen) |
| §6 Befundfolgen (zusammenhängende untersuchte Stützstellen) | keine | **Gate B** |
| §3/§4 zwei Berichte | ein Bericht | **Gate C**: Haupt- und Detailvorlage auf einem Datenvertrag; Entscheidung D2 |
| §4 Detail: jedes auffällige Betriebsmittel, kein Top-N | Anhänge nur über Schwellen; n-1-Befunde bei 40 je Fall gekürzt | **Gate C**: keine verdeckte Kürzung im Detailbericht |
| §7 mehr als 6 Szenarien | Matrixtabellen in Blöcken zu 6 (`case_a`–`case_f`), Diagramme zeichnen REF + 6 | Detail: Blöcke zu 3 mit wiederholter Betriebsmittel- und n-1-Spalte; beliebig viele Blöcke |
| §7 Farben je Status | nur violation 0/1/2 | **Gate C**: Statuspalette (NEW rot, WORSENED orangerot, PRE-EXISTING gelb, IMPROVED blaugrün, RESOLVED grün, Qualität grau), immer mit Text |
| §3 kein Radar, keine Zeitplots mit 5–6 Linien | Kapitel 10 Radar, Kapitel 12/13 REF + 6 Fälle | **Gate C**: entfernt; höchstens ein n-1/(n-1)'-Zeitvergleich einer Leitung unter einer Contingency |
| §3 Gantt, gestapelte Balken, zeitliche Kritikalität, Heatmap, Contingency-Ranking | keine | **Gate C**; Gantt und Heatmap zuerst in der lokalen Stimulsoft-Engine nachgewiesen |
| §9 synthetisches 5.000-Knoten-Profil | Testdaten mit wenigen Betriebsmitteln | **Gate B**: dünn besetzter Generator, als Testdaten gekennzeichnet |

---

## 3. Zuordnung des heutigen Berichts

Berichtselement → Tabelle → Aggregation (Funktion) → PowerFactory-Ergebnis → Qualitätsprüfung.

| Kapitel | Tabelle | Aggregation | PowerFactory-Ergebnis | Qualitätsprüfung |
|---|---|---|---|---|
| Deckblatt, Kopf, Fuß | `ScriptedReportMeta` | `build_cases_payload` | Study Case, Projekt, `ComStatsim`-Zeitraum | – |
| 3 Model Quality | `ScriptedModelQuality` | `_model_quality`, `outage_quality`, `persistence_quality`, `n1_quality` | alle erhaltenen Objekte | die Seite selbst |
| 4/5 Fälle | `ScriptedCases` | `_case_rows`, Urteil `assess_case` | `GridLens_<stamp>_<Fall>` gegen `…_REF` | Abdeckung, Spill-over, spannungslos |
| 6 Referenz | `ScriptedPie*`, `ScriptedReferenceExceeded` | `_pies`, `_reference_exceeded` | `…_REF` | – |
| 7 Kennzahlen | `ScriptedCaseMetrics`, `ScriptedKpis` | `_case_metrics` | QDS-Objekte | zeitgleiches Delta nur aus zeitgleichen Paaren |
| 8 Zusammenfassung | `ScriptedCaseComparison` | `_case_comparison` | QDS-Objekte | – |
| 9 Vergleich | `ScriptedCaseCounts` | `_case_counts` | QDS-Objekte | – |
| 10 Radar | `ScriptedRadar` | `_radar` | QDS-Objekte | **zu entfernen** |
| 11 Top-Leitungen | `ScriptedLineLoadingBars` | `_line_bars` | QDS-Objekte | – |
| 12/13 Zeitplots | `ScriptedTrend*` | `_trends` | QDS-Objekte | **zu entfernen** (REF + 6 Linien) |
| 14 Top-Leitungen je Fall | `ScriptedTopLinesByCase` | `_top_lines_by_case` | QDS-Objekte | – |
| 15/16 Contingency | `ScriptedContingency*` | `_n1_tables` aus `compare_n1` | `…_N1`, `…_N1P` (Teilergebnisse je `cnttime`) | Code 3, fehlende Zeitpunkte, `NOT_APPLICABLE` |
| 17 Nachweis | `ScriptedCalculationRuns` | `_calculation_runs` | alle erhaltenen Objekte | – |
| 18 Anhänge | `ScriptedAppendix*` | `_loading_appendix`, `_voltage_appendix` | QDS-Objekte | nur Schwellen |

---

## 4. Ziel: Haupt- und Detailbericht

**Hauptbericht** (`MASTER_GRIDLENS.mrt`, bleibt der Hauptbericht, damit der
IntReport in PowerFactory weiter funktioniert). **Detailbericht**
(`MASTER_GRIDLENS_DETAIL.mrt`, neu). Beide lesen **denselben** Datenvertrag;
jeder zeigt seine Kapitel.

| Kapitel | Inhalt | Tabellen (Datenvertrag 7.0, Arbeitstitel, ohne Ziffern) | Plot |
|---|---|---|---|
| H01 Deckblatt / Inhalt | wie heute, ohne Study ID; Run-ID | `ScriptedReportMeta` (+ `run_id`) | – |
| H02 Gesamtbewertung | KPI-Zeile, Szenariostatus, kritischste Befunde | `ScriptedScenarioStatistics`, `ScriptedKpis` | – |
| H03 Rechenqualität | geforderte/tatsächliche Zeitpunkte, definierte/anwendbare/gerechnete Contingencies, Konvergenz, Wertabdeckung, Qualitätsstatus | `ScriptedCoverage` | Qualitätsmatrix |
| H04 FS-Planung | Szenarien, FS, Objekte, Fenster | `ScriptedCases`, `ScriptedOutageWindows` | **Gantt** |
| H05 Grundnetz | n-0 Min/Max, n-1 kritische Fehlerfälle, thermisch und Spannung getrennt | `ScriptedReferenceFindings` | Ranking |
| H06 Szenariovergleich | kritische Leitungen/Trafos/Knoten, eindeutige NEW/WORSENED-Betriebsmittel, NEW/WORSENED-Ereignisse, Vollständigkeit | `ScriptedScenarioStatistics`, `ScriptedScenarioCounts` | **gestapelte Statusbalken** (Einheit genannt) |
| H07 Kritische Betriebsmittel | n-1-Referenz, absolute (n-1)'-Extrema, Grenzen, Zähler; bis 20 Leitungen, 15 Trafos, 20 Knoten, „angezeigt x von y“ | `ScriptedCriticalElements` | – |
| H08 Kritische Contingencies / Ereignisse | Top-Ereignisse je Kriterium | `ScriptedContingencyEvents`, `ScriptedContingencyRegister` | **Contingency-Ranking** |
| H09 Zeitliche Kritikalität | eindeutige kritische Betriebsmittel / Contingencies je tatsächlichem Zeitpunkt, FS-Aktivität | `ScriptedTimeCriticality` | **Zeitverlauf**, **Heatmap** |
| H10 Settings / Nachweis | Grenzen, Toleranzen, Contingency-Set, Herkunft, Ergebnispfade | `ScriptedAssessmentSettings`, `ScriptedResultProvenance`, `ScriptedCalculationRuns` | – |
| D01 Umfang und Abdeckung | nach Netzbereich, Spannungsebene, Klasse und Ebene | `ScriptedCoverage` | – |
| D02 FS-Register | Szenario, FS, PF-Pfad, Ausrüstung, jedes Fenster | `ScriptedOutageWindows` | – |
| D03 n-0-Befunde | jedes kritische/warnende/qualitätsauffällige Grundnetzobjekt | `ScriptedReferenceFindings` | – |
| D04/D05 Leitungs-/Trafomatrix | n-1-Maximum, absolute (n-1)'-Maxima je Szenario, Zeit + Contingency + Phase jedes Extremums | `ScriptedElementExtremes` (Langformat, Blöcke zu 3 Szenarien) | – |
| D06a/b Spannungsminimum / -maximum | getrennte Tabellen | `ScriptedElementExtremes` | – |
| D07 Klassifizierungsmatrix | Betriebsmittel × Szenario, Zähler je Status („N 4 · W 2“) | `ScriptedClassificationCounts` | – |
| D08 Contingency-Register | je Contingency: untersuchte/anwendbare/nicht anwendbare/fehlgeschlagene Zeitpunkte, betroffene Betriebsmittel, kritische Zeiten, schwerster Befund | `ScriptedContingencyRegister` | – |
| D09 Einzelbefundregister | priorisierte Auswahl (als solche gekennzeichnet) | `ScriptedContingencyEvents` | – |
| D10 Befundfolgenregister | **jede** kritische Befundfolge | `ScriptedContingencyEpisodes` | – |
| D11 Qualitätsregister | FAILED / NOT_EVALUATED / NOT_APPLICABLE / NOT_COMPARABLE, Ursache, Umfang | `ScriptedQualityRegister` | – |
| D12 Settings und Herkunft | Schlüssel, Wert, Einheit, Herkunft, PF-Objektpfade | `ScriptedAssessmentSettings`, `ScriptedResultProvenance` | – |
| D13 Methodik / Leseschlüssel | nur Text, keine Formeln | fester Text in der Vorlage | – |

Bestehende Tabellen werden migriert, nicht dupliziert: `ScriptedCases`,
`ScriptedModelQuality`, `ScriptedCalculationRuns`, `ScriptedKpis`,
`ScriptedReportMeta` bleiben; `ScriptedRadar` und die zwei Trend-Tabellen
entfallen; `ScriptedContingency*` aus 6.2 werden durch die Langformat-Tabellen
oben ersetzt.

---

## 5. Offene PowerFactory-API-Proben

| # | Frage | Nötig für | Probe |
|---|---|---|---|
| R1 | Enthält ein Contingency-Teilergebnis auch den **Grundfall** (Vorfehler) jedes Zeitpunkts, und wie ist er gekennzeichnet? | FS-Vorfehler aus (n-1)' ohne QDS; Post-Fault-Phase | `tools/probe_contingency.py` erweitern (nur lesend) |
| R2 | Welche Variablen zeichnet der Sweep je Betriebsmittel auf (`c:loading`, `m:u`; weitere Phasen?), und kann es mehrere Post-Fault-Phasen geben? | Phasenschlüssel, Kriterien | ebenso |
| R3 | Kann ein ComPython unter einem IntReport in einen **zweiten** IntReport publizieren (`CreateTable` auf ein anderes Objekt)? | ein Lauf → zwei Berichte | erst lesend prüfen, dann Schreibtest auf Projektkopie (Freigabe) |
| R4 | Wie exportiert PowerFactory das PDF eines IntReport; lässt sich ein Bericht in nummerierte Teile aufteilen? | Teil-PDFs des Detailberichts | Dokumentation / Projektkopie |
| R5 | `SetValue`-Durchsatz (`tools/probe_report_write.py`) | Größe der Detailtabellen | Lauf der vorhandenen Probe |
| R6 | Rendern Stimulsoft-2025.3.5-Gantt und -Heatmap in PowerFactory wie lokal? | H04, H09 | erst lokal, dann Projektkopie |
| R7 | Stabile Objekt-IDs (`GetFullName` oder Fremdschlüssel) für Betriebsmittel und Contingencies | Ergebnis-IDs | lesende Probe |

Keine Rechnung, kein `Execute()`, `CreateObject()` und kein Schreibzugriff ist
Teil der Gates A–D; Gate E läuft erst nach Freigabe auf einer Projektkopie.

---

## 6. Standardmäßig getroffene Entscheidungen (änderbar)

| # | Entscheidung | Grund |
|---|---|---|
| D1 | Der n-1/(n-1)'-Time-Sweep bleibt wie am 23.10.2026 entschieden (QDS-Schritte der Fallfenster). Der Bericht zeigt geforderte Zeitpunkte (ganzer QDS-Zeitraum) gegen tatsächliche auf Abdeckungsachse (a); den Sweep auf die volle QDS-Zeitbasis umzustellen ist eine Gate-E-Änderung. | der Auftrag verbietet unverlangte Rechenänderungen; die Abdeckung macht die Einschränkung sichtbar |
| D2 | Zwei Berichte aus einem Lauf: den Hauptbericht publiziert der rechnende Lauf; den Detailbericht ein zweiter GridLens-Lauf unter einem eigenen IntReport, der **den erhaltenen Lauf neu auswertet** (keine Rechnung, dieselben Objekte, derselbe Settings-Snapshot, dieselbe Run-ID). Zeigt R3, dass ein Skript in beide Berichte publizieren kann, ersetzt das den zweiten Lauf. | nutzt nur geprüfte Wege |
| D3 | Dateinamen: `MASTER_GRIDLENS.mrt` (Haupt), `MASTER_GRIDLENS_DETAIL.mrt` (Detail); die Version steht in jeder Vorlage; das Original bleibt archiviert. | der PowerFactory-IntReport behält seinen Vorlagenpfad |
| D4 | FS-Vorfehlerzustand aus der vorhandenen QDS je Fall. | native Werte existieren; keine zusätzliche stille QDS |
| D5 | Szenarioblöcke: Hauptbericht bis 6 Szenarien je Block, Detailbericht 3, beliebig viele Blöcke. | Auftrag §7 |
| D6 | Beispiel-PDFs werden vom lokalen Render-Werkzeug auf jeder Seite als fiktive Testdaten gekennzeichnet, nicht von der Vorlage (`AGENTS`: die Vorlage trägt keinen „synthetisch“-Hinweis). | beide Regeln gelten |

---

## 7. Plan für die Gates B–D

**Gate B – Auswertekern (ohne PowerFactory):**
1. Kriterien `loading`, `voltage_low`, `voltage_high`; Ergebnis-ID mit Run und Szenario.
2. Streaming-n-1-Vergleich: je Zeitpunkt Referenz- und Szenario-Teilergebnis nebeneinander, einstufen, aggregieren, verwerfen; kein dichtes Array.
3. Aggregate je Szenario × Ebene × Klasse × Netzbereich: eindeutige überwachte/kritische/NEW/WORSENED-Betriebsmittel, Ereignisse je Status, kritische Contingencies und Zeitpunkte, Extrema mit vollem Schlüssel, größte zeitgleiche Verschlechterung, Befundfolgen, Abdeckung auf drei Achsen, Qualitätsregister.
4. Synthetischer dünn besetzter Generator (5.000 Knoten, 3.400 Leitungen, 210 Trafos, 320 Contingencies, 6 Szenarien, 84 Zeitpunkte zu 2 h) und die Pflichttests aus §9, auch 0/1/3/6/>6 Szenarien.

**Gate C – Vorlagen:** Tabellen des Vertrags 7.0; Hauptvorlage H01–H10 und
Detailvorlage D01–D13 aus dem vorhandenen Generator. **Layout und Icons bleiben
genau wie sie sind; übernommen wird nur der Inhalt** (Hadi, 26.10.2026): neue
Kapitel nutzen die vorhandenen Band-, Tabellen- und Diagrammmuster; einzige
Änderung am Deckblatt ist die entfernte Study-ID-Zeile. Radar und
Mehrlinien-Trends entfallen, Hinweise bei leeren Tabellen kommen; Gantt,
gestapelte Balken, Zeitverlauf, Heatmap und Ranking erst nach lokaler
Renderprüfung.

**Gate D – Demonstration:** beide Vorlagen lokal mit dem synthetischen Profil
gerendert, jede Seite als fiktiv gekennzeichnet; Layoutprüfung (Umbrüche,
wiederholte Köpfe, Blöcke > 6 Szenarien, lange Namen, leere und reine
Fehlerberichte).

**Gate E – PowerFactory:** Proben R1–R7 auf einer Projektkopie nach Freigabe;
danach die Anbindung des Streaming-Lesers über die geprüften Wege.

---

## 8. Stand Gate B (26. Oktober 2026)

Umgesetzt in `powerfactory/gridlens_report.py`, ohne PowerFactory getestet
(`tests/test_reporting_core.py`, synthetische Daten in `tests/synthetic_grid.py`):

| Teil | Funktion | Was sie tut |
|---|---|---|
| Kriterien | `criterion_thresholds`, `criterion_violation` | `loading` (über dem Maximum), `voltage_low` (unter dem Band), `voltage_high` (über dem Band), jeweils mit eigener Grenze und Einheit |
| Klassifizierung | `classify_criterion` | die Entscheidungsreihenfolge von `classify_comparison` je Kriterium; `NOT_COMPARABLE` bei abweichenden Grenzen; ein nicht aufgezeichneter Wert (innerhalb der Aufzeichnungsgrenzen) ist nur OK, wenn die Aufzeichnungsgrenze es beweist, sonst `NOT_EVALUATED`; `change` und `delta` nur aus einem zeitgleichen Paar; `MARGIN_REDUCED` als Zusatz |
| Streaming-Leser | `SweepReader`, `_read_n1_sub` | je Teilergebnis (Zeitpunkt) einzeln; nicht aufgezeichnete Zellen werden nicht gespeichert; unlesbare Zellen werden gemeldet, nie als Wert. `read_n1_results` (Kapitel aus 6.2) nutzt denselben Leser |
| Szenarioaggregat | `ScenarioAggregate`, `compare_scenario` | je Zeitpunkt: einstufen, aggregieren, verwerfen. Eindeutige überwachte / kritische / NEW- / WORSENED-Betriebsmittel je Klasse, Ereignisse je Status, kritische Contingencies und Zeitpunkte, größte Verletzung und größte zeitgleiche Verschlechterung je Kriterium mit vollem Schlüssel (Run, Szenario, Zeit, Contingency, Phase, Betriebsmittel, Kriterium), Befundfolgen, Contingency-Register, zeitliche Kritikalität, Abdeckung auf drei Achsen, Qualitätsregister, begrenzte Top-Ereignisliste (mit Gesamtzahl) |
| Betriebsmittelzähler | `element_counters` | je Betriebsmittel und Kriterium: ausdrückliche Status plus das nicht aufgezeichnete OK und die Qualitätszellen des Szenarios |
| Ebenenstatistik | `level_statistics`, `qds_level_statistics` | n-1-Referenz allein; n-0 aus der QDS-REF |

Von den Tests geprüft: jeder Status, Gleichheit mit der Grenze und
Toleranzränder; Unter- und Überspannung getrennt; Qualitätsstatus nie OK;
ausgeschaltete Betriebsmittel, fehlende Zeitpunkte, fehlende Zeilen und nicht
bewiesene nicht aufgezeichnete Zellen nie OK; unabhängige Maxima nie eine
zeitgleiche Änderung; ein Betriebsmittel mit vielen Ereignissen behält jeden
Zähler und zählt einmal als eindeutig; Befundfolgen brechen an Lücken und
Statuswechseln; 0, 1, 3, 6 und 8 Szenarien; derselbe Lauf ergibt identische
Statistik für beide Berichte; jeder geforderte Zeitpunkt wird verbucht
(halboffene Fenster); und das **Erhaltungsgesetz**: die Zellen je Status
ergeben genau die geforderten Zellen (Zeitpunkte × Contingencies × Kriterien
der überwachten Betriebsmittel). Das Mindestprofil (5.000 Knoten, 3.400
Leitungen, 210 Trafos, 320 Contingencies, 6 Szenarien, 84 Zeitpunkte zu 2 h)
läuft in der Testumgebung in rund einer halben Minute unter 300 MB Spitze; das
ist keine PowerFactory-Messung.

**Noch nicht angebunden:** der Kern ist noch nicht in `execute_gridlens` und
die Berichtstabellen eingebunden (Gate C baut daraus die Tabellen des Vertrags
7.0); das Lesen erhaltener Ergebnisse über `SweepReader` in PowerFactory folgt
der geprüften Teilergebnisstruktur, braucht aber die Proben R1, R2 und R7,
bevor es den Weg aus 6.2 ersetzt.

---

## 9. Stand Gate C (26. Oktober 2026)

Datenvertrag **7.0** (38 Tabellen, seit die ungenutzte Zählertabelle entfiel) und zwei Vorlagen, die
`tools/build_mrt.py` aus denselben Seitenbausteinen erzeugt:
**`MASTER_GRIDLENS.mrt`** (Hauptbericht, 13 Seiten) und
**`MASTER_GRIDLENS_DETAIL.mrt`** (Detailbericht, 20 Seiten). Beide deklarieren
jede Tabelle des Vertrags; jede zeigt ihre Kapitel. Die Originalvorlage 6.2
bleibt archiviert (Abschnitt 1). Tabelle für Tabelle:
[`BERICHTSTABELLEN.md`](BERICHTSTABELLEN.md), Abschnitte 3.22–3.43 und 4.

**Layout und Icons unverändert.** Titelseite, Kopf- und Fußzeile, Logo,
Farben, Schriften, Titelbänder sowie Tabellen-, Matrix- und Diagrammmuster sind
die vorhandenen. Geändert ist nur Inhalt: die Titelseitenzeile „Study ID“
entfällt (die Zeilen darunter rücken nach), die Detail-Titelseite hat einen
eigenen Untertitel, und die Kopfzeile nennt den Lauf (`Run: {run_id}`). Neue
Kapitel nutzen die vorhandenen Muster: gestapelte Statussäulen und
Contingency-Ranking das Säulendiagramm, der Zeitverlauf das Liniendiagramm,
das Gantt das Balkenlayout der vorhandenen Diagramme.

**Zuordnung** (Berichtselement → Tabelle → Aggregation → PowerFactory-Ergebnis
→ Qualitätsprüfung):

| Berichtselement | Tabelle | Aggregation | PowerFactory-Ergebnis | Qualitätsprüfung |
|---|---|---|---|---|
| H02 Status, H06 Vergleich | `ScriptedCaseStatistics` | `_case_statistics` aus `compare_scenario` / `qds_level_statistics` | `…_N1`, `…_N1P`; QDS `…_REF`, `…_<Fall>` | Vollständigkeitstext; INCOMPLETE COVERAGE nie OK |
| H03, D01 Abdeckung | `ScriptedCoverage`, `ScriptedScope` | Abdeckung aus `ScenarioAggregate.finish` | dieselben | Erhaltungsgesetz (Gate B) |
| H04, D02 Planung | `ScriptedOutageWindows` | `_outage_windows` aus den Planungsfällen | `IntPlannedout` (Pfad, `starttime`, `endtime`) | – |
| H05, D03 Grundnetz | `ScriptedReferenceFindings` | `_reference_findings` | QDS `…_REF`; n-1-Referenzextreme | n-0 und n-1 nie vermischt |
| H06 Diagramm | `ScriptedCaseStatusCounts` | Ereignisse je Status | `…_N1`, `…_N1P` | Einheit im Titel |
| H07, D04–D06b | `ScriptedCritical*`, `ScriptedDetail*` | `_element_view`: unabhängige Extreme, ausdrückliche Zähler | dieselben | Extreme nie subtrahiert |
| H08, D08, D09 | `ScriptedContingencyRanking`, `…Register`, `…Events` | Register und begrenzte Topliste des Aggregats | dieselben | „x of y“ aus der Gesamtzahl |
| D07 | `ScriptedClassificationMatrix`, `…Counts` | `element_counters` | dieselben | Qualität getrennt gezählt |
| D10 | `ScriptedContingencyEpisodes` | Befundfolgen des Aggregats | dieselben | keine durchgehende Dauer behauptet |
| H09 | `ScriptedTimeCriticality`, `ScriptedTimeMatrix` | Zeitzeilen des Aggregats | dieselben | nur tatsächliche Zeitpunkte |
| D11 | `ScriptedQualityRegister` | Qualitätsliste des Aggregats, nicht ausgewertete Fälle | dieselben | nichts ausgelassen |
| H10, D12 | `ScriptedAssessmentSettings`, `ScriptedResultProvenance` | Settings-Snapshot; erhaltene Objekte | jedes erhaltene `ElmRes` | – |

**Lokale Renderprüfung** (Stimulsoft 2025.3.5, Testdaten der Testsuite, nicht
PowerFactory): jede Seite beider Vorlagen rendert ohne Engine-Fehler; Gantt
(`StiGanttSeries`), gestapelte Säulen, Contingency-Ranking und Zeitverlauf
zeichnen wie vorgesehen. Unterwegs gefunden und behoben: die Zählachse des
Zeitverlaufs druckte doppelte Werte (jetzt ohne Beschriftung, die Werte stehen
an den Punkten); das Balkenmuster verbarg die Beschriftung der ersten und
letzten Kategorie (das Ranking nutzt stattdessen das Säulenmuster; das
vorhandene Diagramm der höchstbelasteten Leitungen hat dasselbe ererbte
Verhalten und bleibt unverändert); das Inhaltsverzeichnis des Detailberichts
lief auf ein zweites Blatt (die n-0-Top-10 steht jetzt auf der Anhangseite).

**Bewusste Abweichungen vom Auftrag:**
- Statusfarben: Zeilen behalten die zwei vorhandenen Hervorhebungen (rot für
  NEW/WORSENED, gelb für andere Verletzungen und Qualität); jeder Status steht
  als Text. Eine Palette je Status würde das Layout ändern.
- Heatmap: H09 zeigt eine Matrix Zeitpunkt x Szenario (Zähler je Zelle,
  Zeilenhervorhebung) statt eines farbigen Heatmap-Diagramms.
- `ScriptedReferenceExceeded` ist durch `ScriptedReferenceFindings` ersetzt;
  `ScriptedRadar`, die zwei Trendtabellen und die vier Contingency-Tabellen
  aus 6.2 entfallen.

**Noch nicht angebunden oder geprüft:**
- Rendern in PowerFactory (R6) und der zweite IntReport für den
  Detailbericht (D2/R3); der Detailbericht braucht einen eigenen IntReport mit
  `MASTER_GRIDLENS_DETAIL.mrt`.
- Die Statistik entsteht aus den n-1-Daten, die `load_n1` bereits gelesen hat
  (`LoadedSweep`); das Streaming direkt aus den erhaltenen Ergebnissen über
  `SweepReader` wartet auf die Proben R1, R2 und R7.
- Die QDS-Ergebnisobjekte tragen in `ScriptedResultProvenance` noch keinen
  PowerFactory-Pfad (nur die n-1-Objekte).
- Als fiktiv markierte Demo-PDFs: Gate D.

---

## 10. Stand Gate D (26. Oktober 2026)

Beide Berichte lokal mit **fiktiven** Daten gerendert: `tools/render_demo.py`
baut jedes Profil mit dem echten Berichtsaufbau (`build_cases_payload`), den
n-0-Teil aus der QDS-Vorlage der Testsuite und den n-1-Teil gestreamt aus
`tests/synthetic_grid.py` (5.000 Knoten, 3.400 Leitungen, 210 Trafos, 320
Contingencies, 84 Zeitpunkte zu 2 h). Die Stimulsoft-2025.3.5-Engine in
`tools/stimulsoft_harness` rendert jede Vorlage in ein PDF mit dem Wasserzeichen
**FICTITIOUS TEST DATA** auf jeder Seite (Entscheidung D6; die Vorlagen tragen
keinen solchen Hinweis). Ausgabe: `demo/<Profil>/MASTER_GRIDLENS.pdf` und
`MASTER_GRIDLENS_DETAIL.pdf`. PowerFactory ist nicht beteiligt; das ist kein
PowerFactory-Rendering (Probe R6 bleibt offen).

| Profil | Inhalt | Blätter Haupt / Detail |
|---|---|---|
| `standard` | 6 Fälle; 150 schwache Zweige und Knoten mit zeitlich zusammenhängenden Tageskurven | 31 / 409 |
| `many` | 8 Fälle mit langen Namen: Blöcke über sechs, umbrechende Namen | 43 / 744 |
| `partial` | wie standard; 4 Zeitpunkte und 5 Contingency-Zeilen fehlen | 31 / 414 |
| `stress` | 6 Fälle; jeder Zweig und Knoten kann kritisch sein (die Tabellengrenzen) | 30 / 1262 |
| `empty` | kein Planungsfall, n-1 nicht bewertet | 15 / 21 |
| `errors` | 3 Fälle, deren QDS und n-1 beide scheiterten | 18 / 24 |

```bash
python3 tools/render_demo.py                       # jedes Profil, ein PDF je Vorlage
python3 tools/render_demo.py many --pages --png 8  # Seite für Seite mit PNG-Blättern für die Layoutprüfung
```

**Layoutprüfung: gefunden und behoben**

| Befund | Behebung |
|---|---|
| Gruppentabellen (Blöcke, Register je Fall) von der Engine umsortiert, ohne Kopf auf Folgeblättern, erstes Blatt leer | ersetzt, siehe unten: gar keine Gruppenbänder |
| **PowerFactory-Export: „The name 'ScriptedCaseComparison' does not exist in the current context“** (kompilierter Bericht; die Fehler entsprechen genau den ersten Gruppenbedingungen in Seitenreihenfolge; Filter, Zellbedingungen und Textausdrücke kompilieren) | **kein GroupHeaderBand**: Matrixtabellen haben je Block ein Bandpaar (Filter `col_count` und `block`; Kopf aus der ersten Zeile des Blocks, auf jedem Blatt wiederholt; höchstens `MAX_PLANNING_CASES` = 20 Fälle); Register zeigen Fall oder Kriterium als Spalte. Der Harness kompiliert wie PowerFactory (`--compile`); jedes Profil kompiliert. Tests verbieten Gruppenbänder und nicht deklarierte Felder. |
| Zeilen über `MAX_TABLE_ROWS` wurden in Fallreihenfolge gekürzt: spätere Fälle verloren jede Zeile, Matrixblöcke verloren Spalten | `_fair_cut` teilt die Zeilen zwischen den Fällen, `_block_rows` behält in jedem Block dieselben Zeilen; beide behalten die schwersten und nennen die Kürzung in der Model Quality; die Statistik bleibt vollständig |
| Lauf nur mit Fehlern: gescheiterte Fälle fehlten in den Tabellen des Vertrags 7.0, der Gesamttext sagte „nicht bewertet“ | jeder Planungsfall behält seine Zeilen mit Grund (`planning_results`); der Text nennt gescheiterte QDS und gescheitertes n-1 |
| NOT APPLICABLE fehlte im Qualitätsregister (D11) | je Contingency und Ursache erfasst |
| n-1-Referenzbefunde vollständig publiziert, aber nur als Top 10 gezeigt | nur die Topzeilen werden publiziert |
| Zeitverlauf: 84 Wertbeschriftungen überlappten | ganzzahlige Beschriftung der Zählachse (`0;-0;0`, kein kulturabhängiges Dezimalzeichen) |
| Lange Namen drängten die Zeile mit Netz und Grenze aus der Matrixzelle; Zähler brachen mitten in der Zelle um | der Namensteil wird gekürzt; Zähler in eigener Zeile |

**Geprüft und in Ordnung:** Titelseite ohne Study ID, Run-ID in jeder
Kopfzeile, Hinweise bei leeren Tabellen im leeren Bericht, Blöcke zu 6
(Haupt) und 3 (Detail) mit wiederholter Betriebsmittel- und n-1-Spalte, lange
Namen, Gantt-Diagramm, gestapelte Statussäulen, Contingency-Ranking, jede
Seite jedes Profils ohne Engine-Fehler.

**Offen:**
- Der Hauptbericht hat 30–43 Blätter für 6–8 Fälle (Auftrag: etwa 10–20, „bei
  vielen FS ggf. etwas mehr“); die Zeitmatrix (84 Zeilen) und die Matrizen der
  kritischen Betriebsmittel sind die längsten Kapitel.
- Die Detailregister überschreiten `MAX_TABLE_ROWS = 5000` in `standard`
  (Befundfolgen) und in `stress` (Betriebsmittelmatrizen, Klassifizierung); der
  Druck ist dann unvollständig und sagt es. Ob PowerFactory mehr Zeilen in
  vertretbarer Zeit publiziert, klärt Probe R5; eine Teilung in nummerierte
  PDF-Teile ist R4.
- Das Stressprofil ist bewusst unrealistisch (fast jedes Betriebsmittel
  kritisch); `standard` liegt näher an einem realen Netz, ist aber ebenso fiktiv.

---

## 11. Die Berichte als Pages (26. Oktober 2026)

Seit dem 26. Oktober 2026 hält das Repository beide Berichte als **Pages**,
nicht als `.mrt`-Dateien (Entscheidung von Hadi: Änderungen werden je Page
beauftragt, der Bericht wird im Stimulsoft-Designer zusammengesetzt):

```
powerfactory/pages/MASTER_GRIDLENS/          MASTER_GRIDLENS.dct + 00_Cover.pg … 12_Evidence.pg
powerfactory/pages/MASTER_GRIDLENS_DETAIL/   MASTER_GRIDLENS_DETAIL.dct + 00_Cover.pg … 19_Appc.pg
```

- `.pg` ist Stimulsofts eigene Page-Datei („Save Page“/„Open Page“); sie
  speichert die Page mit ihrer Einheit (Zentimeter), die Maße stimmen also in
  jeder Designer-Einheit.
- `.dct` ist das Datenwörterbuch (38 Datenquellen mit Spalten und SQL, leere
  Verbindung); die zwei Berichte unterscheiden sich in einer Sortierung
  (Ereignisse), daher hat jeder sein eigenes.
- **Bericht zusammensetzen:** neuer Bericht im Designer → Berichtskultur auf
  **en-US** setzen (Zahlen und Datum; die Pages können sie nicht tragen) →
  `.dct` ins Wörterbuch laden → Open Page für jede `.pg` in Dateireihenfolge
  (00, 01, …) → die leere Standardseite entfernen → als `.mrt` speichern und in
  den IntReport laden.
- Die Pages wurden einmal mit der Stimulsoft-Engine aus MRT 7.0.0 exportiert;
  `tools/build_mrt.py` und beide `.mrt` 7.0.0 liegen archiviert in
  `templates/archive/` und sind nicht mehr die Quelle. Änderungen erfolgen in
  den `.pg`-Dateien.
- Lokale Prüfung: `tools/stimulsoft_harness` setzt einen Bericht genauso aus
  seinem Ordner zusammen (Wörterbuch, Pages in Dateireihenfolge, Kultur en-US)
  und rendert ihn, mit `--compile` kompiliert wie PowerFactory; die
  zusammengesetzten Berichte rendern genau wie die `.mrt` 7.0.0 (gleiche
  Blattzahlen in jedem Profil).
- Die Tests lesen die Ordner (`tests/_paths.py`: `report_tree`, `report_text`)
  und prüfen das Wörterbuch gegen den Datenvertrag, jede Page, die
  Dateireihenfolge und dass keine `.mrt` ausgeliefert wird. Auslieferung: Tests,
  `gridlens_report.py` und die zwei Page-Ordner.
