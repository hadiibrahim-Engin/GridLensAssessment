# GridLens und PowerFactory 2026 – wie GridLens mit PowerFactory arbeitet

Dieses Dokument beschreibt alles, was GridLens in PowerFactory 2026 tut: wie es
Objekte findet und liest, was es schreibt und wieder zurücksetzt, wie Planned
Outages wirken, wie die quasi-dynamische Simulation (QDS) und die Contingency
Analysis (n-1) laufen und wie aus der Fallkonfiguration Rechnungen werden.
Stand: GridLens 8.0.0, 24. Oktober 2026. Englische Fassung:
[`docs/POWERFACTORY.md`](../POWERFACTORY.md). Beide Fassungen werden gemeinsam
gepflegt.

Jede Aussage trägt einen Status:

| Status | Bedeutung |
|---|---|
| **geprüft** | in PowerFactory 2026 beobachtet (Probe- oder Testlauf, Datum genannt) |
| **genutzt** | GridLens verwendet es und es lief in PowerFactory ohne Fehler, aber nicht gezielt geprüft |
| **offen** | Annahme oder Beobachtung, die noch bestätigt werden muss |

Die Funktionsnamen in `code` stehen in `powerfactory/gridlens_report.py`.

---

## 1. Grundlagen der Python-API

GridLens läuft als ComPython-Skript in PowerFactory und braucht nur die
Standardbibliothek und das Modul `powerfactory`.

```python
import powerfactory
app = powerfactory.GetApplication()          # die laufende PowerFactory-Sitzung
script = app.GetCurrentScript()              # das ComPython, das gerade läuft
study_case = app.GetActiveStudyCase()        # IntCase
project = app.GetActiveProject()             # IntPrj
qds = app.GetFromStudyCase("ComStatsim")     # Kommando aus dem Study Case
clock = app.GetFromStudyCase("SetTime")      # Studienzeit (cDate, cTime)
app.PrintPlain("Text")                       # Ausgabe ins Ausgabefenster
```

| Was | Wie | Hinweis |
|---|---|---|
| Klasse eines Objekts | `obj.GetClassName()` → `"ElmLne"` | GridLens prüft jede gefundene Klasse, bevor es ein Objekt benutzt |
| Name | `obj.loc_name` | im Bericht nur dieser Kurzname |
| Identität | `obj.GetFullName()` → Pfad mit Klassen | interner Schlüssel (`object_key`); erscheint nie im Bericht |
| Attribut lesen | `obj.<attribut>` bzw. `getattr(obj, "attribut")`, sonst `obj.GetAttribute("attribut")` | `safe_attr` und `_read_setting` fangen Fehler ab |
| Attribut schreiben | `obj.<attribut> = wert`, sonst `obj.SetAttribute("attribut", wert)` | danach immer zurücklesen und vergleichen (`_set_scalar_attribute`) |
| Inhalt eines Ordners | `obj.GetContents("*.Klasse")`, rekursiv `obj.GetContents("*.Klasse", 1)` | bei manchen Objekten nur ohne zweites Argument |
| rechenrelevante Objekte | `app.GetCalcRelevantObjects("*.ElmLne")` | nur Betriebsmittel aktiver Netze |
| Projektordner | `app.GetProjectFolder("outage")`, `app.GetProjectFolder("netdat")` | Operational Library bzw. Netzdaten |
| Objekt anlegen | `ordner.CreateObject("Klasse", "Name")` | GridLens legt nur `ComSimoutage`, `ComOutage` und den Spaltenpuffer `IntVec` an |
| Objekt kopieren | `ziel.AddCopy(obj)` → Kopie (bzw. Liste) | für die erhaltenen Ergebnisobjekte |
| Objekt löschen | `obj.Delete()` | GridLens löscht nur seinen eigenen Spaltenpuffer |
| Rechnung starten | `kommando.Execute()` → `0` bei Erfolg | blockiert, bis PowerFactory fertig ist |

**Aktivieren.** GridLens ruft nie `Activate()` oder `Deactivate()` auf; es
wechselt weder Projekt noch Study Case, Operation Scenario oder Variante. Was
eine Rechnung berücksichtigt, steuert es nur über Attribute:

| Schalter | Objekt | Bedeutung |
|---|---|---|
| `iopt_maint` | `ComStatsim` | 1: die QDS wendet Planned Outages an |
| `isPlannedOutages` | `ComSimoutage` | 1: die n-1-Rechnung wendet Planned Outages an |
| `outserv` („Ignored“) | `IntPlannedout` | 1: diese Außerbetriebnahme wird übergangen |
| `outserv` („Not analysed“) | `ComOutage` | 1: dieser Fehlerfall wird nicht gerechnet |

---

## 2. Welche Objekte GridLens findet und woher

| Objekt | Klasse | Wie gefunden | Funktion |
|---|---|---|---|
| laufendes Skript | `ComPython` | `app.GetCurrentScript()` | `execute_gridlens` |
| Bericht | `IntReport` | Elternobjekt des Skripts; fehlt es, läuft GridLens eigenständig und publiziert nicht | `execute_gridlens` |
| Study Case | `IntCase` | `app.GetActiveStudyCase()` | |
| QDS | `ComStatsim` | `app.GetFromStudyCase("ComStatsim")` | |
| Studienzeit | `SetTime` | `app.GetFromStudyCase("SetTime")` | `_restore_study_time` |
| Planned Outages | `IntPlannedout` | rekursiv unter `app.GetProjectFolder("outage")`; nur wenn dort keine liegt, im ganzen Projekt | `_find_project_outages` |
| Contingency Analysis | `ComSimoutage` | `study_case.GetContents("*.ComSimoutage")`; genau eine, sonst wird n-1 nicht gerechnet | `contingency_analysis` |
| Fehlerfälle | `ComOutage` | Inhalt der `ComSimoutage` | `contingency_equipment` |
| Netze | `ElmNet` | `app.GetCalcRelevantObjects("*.ElmNet")` (aktiv) und `GetProjectFolder("netdat")` (alle) | `project_grids` |
| Netz eines Betriebsmittels | – | Attribut `cpGrid`, sonst das `ElmNet` im Pfad | `element_grid_name` |
| Ergebnisse | `ElmRes` | nach dem QDS-Lauf `qds.results`; die Kopien von GridLens im Study Case | `_calculate_qds` |

Die veraltete Klasse `IntOutage` (dort legt PowerFactory auch Demand Transfers
ab) liest GridLens nicht.

---

## 3. Was GridLens schreibt und wie es zurücksetzt

Jeder Schreibzugriff wird **zurückgelesen** und verglichen. Die Werte eines
Laufs gehen über `StateGuard`: Der alte Wert wird gemerkt, der neue geschrieben;
am Ende des Blocks (auch nach einem Fehler) werden alle Werte in umgekehrter
Reihenfolge zurückgesetzt und wieder zurückgelesen. `iopt_maint` und die
Studienzeit setzt GridLens direkt und im Schritt „Restore“ verifiziert zurück.
Lässt sich ein Wert nicht zurücksetzen, stoppt der Lauf mit `StateRestoreError`
und nennt erwarteten und gefundenen Wert.

| Objekt | Attribut | Wann | Zurückgesetzt |
|---|---|---|---|
| `ComStatsim` | `iopt_maint` | 0 für REF, 1 für alle Fälle | nach dem Rechenschritt (Schritt 5) |
| `IntPlannedout` (alle) | `outserv` | je Lauf: 0 für die Außerbetriebnahmen des Falls und die festen, 1 für alle anderen | nach jedem Lauf |
| `SetTime` | `cDate`, `cTime` | PowerFactory setzt die Studienzeit beim Rechnen weiter | nach jedem Lauf |
| `ComSimoutage` | `isPlannedOutages` | 0 für n-1, 1 für (n-1)' | nach jedem Sweep |
| `ComSimoutage` | `calcPeriod`, `stepUnit`, `stepSize`, `startTime`, `endTime`, `stepNumber` | Zeitraum des Sweeps (Abschnitt 7.3) | nach jedem Sweep |
| `ComOutage` | `outserv` | 1 für Fehlerfälle außerhalb der gewählten Netze | nach jedem Sweep |

Was GridLens **anlegt** und im Study Case lässt:

- `GridLens_<yymmdd-HHMMSS>_<Fall>` (`ElmRes`): je QDS-Lauf eine Kopie der Ergebnisse,
- `GridLens_<stamp>_<Fall>_N1` und `_N1P` (`ElmRes`): Kopien der n-1- und (n-1)'-Ergebnisse,
- `GridLens_<stamp>_N1` (`ComSimoutage`): nur wenn der Study Case keine Contingency Analysis hat.

Was GridLens **nie** tut: Ergebnisobjekte löschen, `ComStatsim.results`
umbinden, Operation Scenarios, Varianten oder Study Cases anlegen,
`starttime`/`endtime` einer Außerbetriebnahme oder den Zeitraum der QDS
ändern. Eigene Termine je Fall und kürzere QDS-Fenster werden nur angezeigt.

---

## 4. Planned Outages

### 4.1 Das Objekt

`IntPlannedout` ist in PowerFactory 2026 ein **reines Datenobjekt**. Es hat
**weder `Apply` noch `Reset` noch `Check`** (geprüft, Probe Oktober 2026).
GridLens liest:

| Attribut | Inhalt |
|---|---|
| `starttime`, `endtime` | Fenster in Epoch-Sekunden, halboffen `[Beginn, Ende)` |
| `components` | die geschalteten Betriebsmittel |
| `outserv` | in der Oberfläche „Ignored“; 1 = PowerFactory übergeht die Außerbetriebnahme |
| `priority` | Priorität, nur angezeigt |
| Inhalt (`GetContents("*", 1)`) | Schalt- und Lastverschiebungsaktionen (`Evt*`, `Sta*`, `Int*`), nur angezeigt |

Die betroffenen Betriebsmittel liest `_outage_parts` aus `components` und
weiteren Verweis-Attributen der Außerbetriebnahme und ihrer Aktionen
(`OUTAGE_EQUIPMENT_ATTRIBUTES`).

### 4.2 Wie PowerFactory sie anwendet

PowerFactory wendet eine Außerbetriebnahme **während der Rechnung** selbst an,
wenn alle drei Bedingungen gelten (geprüft):

1. die Rechnung hat Planned Outages eingeschaltet (`ComStatsim.iopt_maint = 1`
   bzw. `ComSimoutage.isPlannedOutages = 1`),
2. die Außerbetriebnahme ist nicht „Ignored“ (`outserv = 0`),
3. der Rechenzeitpunkt liegt in ihrem Fenster.

PowerFactory wendet **jede** solche Außerbetriebnahme an, nicht nur die
gewünschte. GridLens wählt deshalb über `outserv` aus, **welche** gelten:
für einen Lauf 0 für genau die Außerbetriebnahmen des Falls (und die festen),
1 für alle anderen (`_isolate_outages`). Im Ausgabefenster meldet
PowerFactory dann z. B. „Switch … opened“, „Outage … applied“ und „1 Planned
Outages were automatically applied“. Wechselt die Menge der aktiven
Außerbetriebnahmen zwischen zwei Zeitpunkten, wendet PowerFactory sie neu an
(geprüft im n-1-Time-Sweep, 23.10.2026).

### 4.3 Wie GridLens prüft, dass sie wirkt

- **Vor jedem Lauf** liest GridLens zurück, was gilt (`applied_text`):
  „'Planned outages' [iopt_maint] = 1; planned outages applied: …“.
- **Nach dem Lauf** prüft es jede Außerbetriebnahme gegen REF in ihrem Fenster
  (`outage_effects`): **APPLIED** (ein aufgezeichnetes Betriebsmittel ist im
  Fall lastfrei, in REF nicht), **EFFECT SEEN**, **NO EFFECT** (Warnung) oder
  **NOT CHECKABLE**. Im Bericht steht je Fall eine QA-Zeile `outages_<Fall>`.
- **Im Schritt 3** protokolliert GridLens für jede Außerbetriebnahme ihre Daten
  (alle Attribute, über `dir()` gelesen) und was unter ihr liegt
  (Schaltaktionen mit ihren Daten), oder dass nichts darunter liegt – dann
  isoliert PowerFactory die Betriebsmittel selbst (`outage_contents_text`).
  Im Schritt 2 stehen die QDS-Optionen mit PowerFactorys eigener Beschriftung
  (`GetAttributeDescription`), z. B. `iopt_action` und `iopt_rep`.
- **Um jeden QDS-Lauf** liest GridLens den Zustand (`on_off`) aller
  rechenrelevanten Schalter (`ElmCoup`, `StaSwitch`) vorher und nachher und
  protokolliert jeden, der sich geändert hat (`switch_states`); GridLens
  selbst schaltet nichts.
- **Nach dem Fensterende** prüft GridLens im Ergebnis, ob die Betriebsmittel
  der Außerbetriebnahme im Fall weiter lastfrei sind, während REF Last zeigt
  (`outage_persistence`): Log-Zeile „stays in effect after its window … for N h
  (until …)“ oder „back in service right at its window end“, dazu die QA-Zeile
  `outages_after_<Fall>`.

### 4.4 Offen: Schaltzustand nach dem Fensterende

Im ersten vollständigen Lauf (24.10.2026) unterschied sich ein Fall mit einer
zweistündigen Außerbetriebnahme von REF in **fast allen Zeitschritten vom
Fensterende bis zum Ende des Jahres**. Das spricht dafür, dass die QDS die von
der Außerbetriebnahme geöffneten Schalter nach dem Fenster **nicht wieder
schließt** (der Schaltzustand bleibt bestehen). GridLens bewertet solche
Zeitschritte als Spill-over und warnt in der QA („Effect outside the outage
windows“); die verursachten Stunden werden dadurch zu groß. Zu prüfen: die
Auslastung des ausgeschalteten Betriebsmittels im erhaltenen Ergebnisobjekt
des Falls nach dem Fensterende, und ob die Außerbetriebnahme eine
Rückschaltaktion braucht oder die QDS eine Option dafür hat (Kandidaten:
`iopt_action` „Planned Outages: Processing Actions“; `iopt_rep` „Planned
Outages: Output“ lässt PowerFactory jede angewendete Aktion ausgeben). Die
Log-Zeilen aus 4.3 beantworten das im nächsten Lauf.

---

## 5. Quasi-dynamische Simulation (QDS)

### 5.1 Einstellungen, die GridLens liest

| Attribut von `ComStatsim` | Bedeutung |
|---|---|
| `startTime`, `endTime` | simulierter Zeitraum, Epoch-Sekunden (`qds_period`) |
| `stepSize`, `stepUnit` | Zeitschritt; `stepUnit` 0 s, 1 min, 2 h, 3 d (`qds_grid`) |
| `calcPeriod` | Art des Zeitraums (nur protokolliert) |
| `iopt_maint` | Planned Outages anwenden (wird gesetzt) |
| `results` | gebundenes Ergebnisobjekt (nur gelesen) |

Alle übrigen Einstellungen (Profile, Lastfluss-Optionen) nutzt GridLens
unverändert.

### 5.2 Rechnen und Ergebnisse erhalten (geprüft 24.10.2026)

```python
code = qds.Execute()                 # 0 = Erfolg
produced = qds.results               # das ElmRes, in das PowerFactory schrieb
copy = study_case.AddCopy(produced)  # Kopie DANACH
copy.loc_name = "GridLens_<stamp>_<Fall>"
```

- PowerFactory schreibt eine QDS in **sein eigenes Ergebnisobjekt im Study
  Case**. Ist das gebundene Objekt eines ohne Variablenauswahl (etwa ein
  temporäres im Benutzerordner `…\Set\Tmp\RecB`), bindet PowerFactory beim
  `Execute` selbst ein Ergebnisobjekt mit seiner Standard-Variablenauswahl
  (klassenweite `IntMon`) und schreibt hinein. Jeder weitere Lauf schreibt in
  dasselbe Objekt und überschreibt es.
- Eine **nach** dem Lauf mit `AddCopy` angelegte Kopie behält Zeilen, Spalten,
  Werte und `IntMon` und bleibt nach dem nächsten Lauf unverändert. Eine
  **vor** dem Lauf angelegte Kopie eines Objekts ohne Variablenauswahl
  zeichnet dagegen nur `b:noconv` und `b:number` auf.
- Deshalb bindet GridLens `ComStatsim.results` nicht, rechnet wie konfiguriert
  und kopiert danach (`_calculate_qds`, `_case_result_object`). Die Bindung, die
  PowerFactory setzt, bleibt wie nach einem Lauf von Hand.
- Ist `ComStatsim.results` an ein erhaltenes GridLens-Objekt gebunden, stoppt
  GridLens vor jeder Rechnung: die QDS würde es überschreiben.
- Direkt nach dem ersten Lauf prüft GridLens, ob die Kopie Auslastung oder
  Spannung aufzeichnet (`check_recording`); sonst stoppt es mit
  `RecordingError` und nennt, was aufgezeichnet ist.
- In die Beschreibung (`desc`) jeder Kopie schreibt GridLens Version, Fall und
  einen Fingerabdruck der Außerbetriebnahmen; damit kann ein erhaltener Lauf
  später ohne Rechnung neu ausgewertet werden (`kept_runs`).
- PowerFactory setzt die Studienzeit nach der QDS auf den letzten Zeitpunkt;
  GridLens setzt sie nach jedem Lauf zurück.

### 5.3 Variablen

Bewertet werden `c:loading` bzw. `m:loading` von Leitungen und
Transformatoren und `m:u` bzw. `m:u1` von Knoten. Die Standardauswahl der QDS
zeichnet `c:loading` und `m:u` auf (geprüft). Andere Variablen werden gelesen,
aber nicht bewertet; Winkel nie.

---

## 6. Ergebnisse lesen (`ElmRes`)

```python
res.Load()                               # Daten in den Speicher
rows = res.GetNumberOfRows()             # Zeitschritte
cols = res.GetNumberOfColumns()
var = res.GetVariable(col)               # "c:loading"
obj = res.GetObject(col)                 # das Betriebsmittel der Spalte
err, value = res.GetValue(row, col)      # eine Zelle; err != 0: kein Wert
vec = script.CreateObject("IntVec", "GridLens_column_buffer")
res.GetColumnValues(vec, col)            # eine ganze Spalte nach vec.V
res.Release()
```

- Spalte für Spalte liest GridLens mit `GetColumnValues` in einen `IntVec`,
  den es im laufenden ComPython anlegt und am Ende wieder löscht
  (`open_column_buffer`, `read_column`); geht das nicht, Zelle für Zelle mit
  `GetValue` (langsam, im Laufbericht gezählt).
- Die Zeitspalte liefert die absolute Zeitachse; GridLens prüft, dass REF und
  jeder Fall dieselbe Zeitachse haben.
- NaN, Unendlich, `None`, Booleans und Fehlercodes sind keine Messwerte. Eine
  Spannung unter 0,1 p.u. oder NaN gilt als spannungslos.
- Der Filter auf Netze (`cpGrid`) greift, bevor Werte gelesen werden.
- **Im Log (Schritt 6)** steht für jedes Ergebnisobjekt, was es enthält
  (`result_object_text`): Anzahl der Zeitschritte, erster und letzter, Schritt,
  Spannweite, Spalten nach Klasse und nach Variable. Für jede
  Außerbetriebnahme eines Falls folgt je aufgezeichnetem Betriebsmittel, in
  wie vielen Schritten es innerhalb und außerhalb ihres Fensters lastfrei ist,
  und dasselbe für REF (`outage_component_lines`).

---

## 7. Contingency Analysis (n-1 und (n-1)')

### 7.1 Das Kommando und die Fehlerfälle

- GridLens nutzt die **eine** `ComSimoutage` des aktiven Study Case. Gibt es
  keine (z. B. im QDS-Study-Case), legt es `GridLens_<stamp>_N1` an
  (`create_contingency_analysis`): je ein `ComOutage` pro rechenrelevantem
  Betriebsmittel der Klassen `ElmLne`, `ElmBranch`, `ElmZpu`, `ElmTr2`,
  `ElmTr3`, `ElmTr4`, `ElmSind`, `ElmScap`, `ElmShnt`, `ElmSvs`, `ElmVsc`,
  `ElmVscmono` in den gewählten Netzen – keine Erzeuger, Lasten,
  Sammelschienen. Eine Leitung in einem `ElmBranch` zählt über den Zweig.

```python
ca = study_case.CreateObject("ComSimoutage", name)
ca.iEnableTS = 1                               # Time-Sweep an
fault = ca.CreateObject("ComOutage", element.loc_name)
fault.SetObjs([element])                       # 0 = Erfolg
```

- Welche Betriebsmittel ein Fehlerfall schaltet, liest GridLens mit
  `ComOutage.GetObject(i)` für i = 0, 1, … bis `None` (`contingency_equipment`).
- Fehlerfälle außerhalb der gewählten Netze setzt GridLens für den Lauf auf
  „Not analysed“ (`ComOutage.outserv = 1`, geprüft 23.10.2026).

### 7.2 Planned Outages im Sweep

`isPlannedOutages = 1` wendet die Planned Outages in jedem Zeitpunkt ihres
Fensters an (geprüft). n-1 rechnet mit `isPlannedOutages = 0` (oder nur den
festen), (n-1)' mit den Außerbetriebnahmen des Falls; die Auswahl erfolgt wie
bei der QDS über `IntPlannedout.outserv`. Ein Fehlerfall, dessen Betriebsmittel
die Außerbetriebnahme schon ausschaltet, fehlt im Ergebnis („none of the
interrupted components is relevant“) und wird als `NOT_APPLICABLE` geführt.

### 7.3 Zeitpunkte des Sweeps (geprüft 24.10.2026)

Mit `calcPeriod = 4` rechnet die Contingency Analysis von `startTime` bis
`endTime` (**exklusiv**) in Schritten von `stepSize`/`stepUnit`; der Vektor
`studyTime` wird dann **ignoriert**, auch wenn er geschrieben und unverändert
zurückgelesen wird. (Im Testlauf vom 23.10. war ein anderer `calcPeriod`
gewählt; dort folgte der Sweep `studyTime`.) GridLens schreibt deshalb je
Sweep den Zeitraum (`sweep_period`, `run_n1_sweep`):

| Attribut | Wert |
|---|---|
| `calcPeriod` | 4 |
| `stepUnit`, `stepSize` | der QDS-Zeitschritt (`step_setting`) |
| `startTime` | erster QDS-Schritt in den Fenstern des Falls |
| `endTime` | letzter QDS-Schritt in den Fenstern + ein Schritt |
| `stepNumber` | Anzahl der Schritte (wenn lesbar) |

Liegen Fenster auseinander, werden die Schritte dazwischen mitgerechnet, aber
nicht bewertet; ein Zeitraum über dem n-1-Limit wird abgelehnt. Direkt nach
dem Sweep prüft GridLens, ob jeder Zeitpunkt in den Fenstern gerechnet wurde.

### 7.4 Ergebnisse

- `ComSimoutage.p_rescnt` verweist auf ein `ElmRes` mit **einem Teil-`ElmRes`
  je Zeitpunkt**; dessen `cnttime` ist der Zeitpunkt (geprüft).
- In einem Teilergebnis sind die **Zeilen die Fehlerfälle** und die **Spalten
  die Betriebsmittel** (`c:loading`, `m:u`). Fehlerfälle ohne relevantes
  Betriebsmittel fehlen.
- Werte innerhalb der Aufzeichnungsgrenzen (`loadmax`, `vlmin`, `vlmax`)
  schreibt PowerFactory nicht: `GetValue` liefert Code 3. GridLens wertet sie
  als „innerhalb der Grenze“, wenn die Grenze das beweist.
- Nach jedem Sweep kopiert GridLens `p_rescnt` als `…_N1` bzw. `…_N1P` in den
  Study Case (`keep_copy`); die Aufzeichnungsgrenzen stehen in `desc`.
- **Im Log (Schritt 6)** steht für jedes n-1-Ergebnis (`n1_data_text`): wie
  viele Zeitpunkte bewertet und gerechnet wurden und von wie vielen
  QDS-Schritten des Zeitraums (die übrigen werden nicht gerechnet), je
  Zeitpunkt Fehlerfälle × Betriebsmittel mit Wert, Anzahl der Werte und der
  Werte innerhalb der Aufzeichnungsgrenzen; für (n-1)' zusätzlich, welche
  Fehlerfälle von n-1 fehlen (deren Betriebsmittel der Fall schon ausschaltet).

---

## 8. Definition der Fälle

### 8.1 Konfiguration

Die Fälle kommen aus dem Fall-Manager (`CASE_SOURCE = 'gui'`), aus der
gespeicherten Datei (`'saved'`, JSON unter `CASE_CONFIG_DIR`) oder je
Außerbetriebnahme ein Fall (`'per_outage'`). Die Datei hat Schema
`gridlens.cases` Version 2:

```json
{"schema": "gridlens.cases", "schema_version": 2, "revision": 3,
 "assessments": ["n-0", "n-1", "(n-1)'"],
 "background": ["<Schlüssel einer festen Außerbetriebnahme>"],
 "cases": [{"id": "C1", "name": "…", "description": "…",
            "outages": ["<Schlüssel>", "…"], "enabled": true, "overrides": {}}],
 "settings": {}}
```

Ein Schlüssel ist der volle PowerFactory-Pfad der `IntPlannedout`; ein Fall
listet beliebig viele Vorkommen. Fälle werden nie automatisch kombiniert.

### 8.2 Vom Fall zur Rechnung

| Begriff | Bedeutung | Funktion |
|---|---|---|
| REF | R0: keine Außerbetriebnahme (`iopt_maint = 0`); Rfix: nur die festen (`iopt_maint = 1`) | `_calculate_reference` |
| Planungsfall | die Vorkommen des Falls plus die festen, alle anderen „Ignored“, ein QDS-Lauf | `_calculate_case` |
| Fenster | `starttime`/`endtime` der Außerbetriebnahme; eigene Termine werden erfasst, aber nicht angewendet | `_occurrence_window` |
| Netzzustände | zwischen je zwei Fenstergrenzen gleiche aktive Menge | `network_states` |
| Fingerabdruck | gleiche Außerbetriebnahmen mit gleichen Fenstern → gleiches Ergebnis; solche Fälle werden einmal gerechnet (`REUSED`) | `plan_fingerprint` |
| n-1 / (n-1)' | je Fall ein Sweep ohne bzw. mit seinen Außerbetriebnahmen, über die QDS-Schritte in seinen Fenstern | `calculate_n1_case` |

### 8.3 Ablauf eines Laufs

1. Start, Kontext, Bericht oder eigenständiger Lauf.
2. ComStatsim-Einstellungen protokollieren.
3. Planned Outages lesen, Fall-Manager, Fälle prüfen.
4. **Rechnen** (Phase 1): REF, jeder Fall (QDS, Kopie danach), dann n-1 und (n-1)'.
5. **Zurücksetzen**: Studienzeit, `iopt_maint`; jeder geschriebene Wert verifiziert.
6. **Auswerten** (Phase 2): die erhaltenen Kopien lesen und mit REF vergleichen.
7. Berichtstabellen bauen und, unter einem `IntReport`, publizieren.

Ein erhaltener Lauf lässt sich im Fall-Manager unter *Results* ohne Rechnung
neu auswerten.

---

## 9. Geprüft und offen

| Aussage | Status |
|---|---|
| `IntPlannedout` hat kein `Apply`/`Reset`/`Check`; Anwendung über `iopt_maint` + `outserv` + Fenster | geprüft (Okt. 2026) |
| `isPlannedOutages` wendet Planned Outages je Zeitpunkt im Sweep an | geprüft (23.10.2026) |
| `ComOutage.outserv = 1` nimmt einen Fehlerfall aus der Rechnung | geprüft (23.10.2026) |
| QDS schreibt in ihr eigenes Ergebnisobjekt; Kopie danach behält alles | geprüft (24.10.2026) |
| `calcPeriod = 4`: Sweep über `startTime`…`endTime`, `studyTime` ignoriert | geprüft (24.10.2026) |
| Teilergebnis je Zeitpunkt, Zeilen = Fehlerfälle, Code 3 = nicht aufgezeichnet | geprüft (23.10.2026) |
| `GetColumnValues(IntVec, Spalte)` füllt `IntVec.V` | genutzt (24.10.2026) |
| `CreateObject` von `ComSimoutage`/`ComOutage`, `SetObjs` | offen (noch nicht in PowerFactory gelaufen) |
| Schaltzustand einer Außerbetriebnahme bleibt in der QDS nach dem Fensterende bestehen | offen (Abschnitt 4.4) |
| Zwei Außerbetriebnahmen auf demselben Betriebsmittel | offen |
| Fall-Manager (tkinter) innerhalb von PowerFactory | genutzt |

Weitere Annahmen (P1–P10) und die Testmatrix stehen in
[`ARCHITEKTUR.md`](ARCHITEKTUR.md) und [`TESTMATRIX.md`](TESTMATRIX.md).

---

## 10. Rezepte für Skripte von Hand

**Eine Außerbetriebnahme allein rechnen und das Ergebnis behalten**

```python
outages = app.GetProjectFolder("outage").GetContents("*.IntPlannedout", 1)
saved = {o: o.outserv for o in outages}
for o in outages:
    o.outserv = 0 if o.loc_name == "MEINE_FS" else 1
old = qds.iopt_maint
qds.iopt_maint = 1
try:
    qds.Execute()
    kopie = study_case.AddCopy(qds.results)
    kopie.loc_name = "Meine_FS_Ergebnis"
finally:
    qds.iopt_maint = old
    for o, value in saved.items():
        o.outserv = value
```

**Eine Spalte eines Ergebnisobjekts lesen**

```python
res = kopie
res.Load()
for col in range(res.GetNumberOfColumns()):
    if res.GetVariable(col) == "c:loading" and res.GetObject(col).loc_name == "MEINE_LEITUNG":
        werte = [res.GetValue(row, col)[1] for row in range(res.GetNumberOfRows())]
res.Release()
```

**n-1 für einen Zeitraum rechnen**

```python
ca = study_case.GetContents("*.ComSimoutage")[0]
alt = {a: getattr(ca, a) for a in ("calcPeriod", "startTime", "endTime", "stepSize", "stepUnit")}
ca.calcPeriod, ca.stepSize, ca.stepUnit = 4, 1, 2           # stündlich
ca.startTime, ca.endTime = beginn, ende                      # Epoch-Sekunden, Ende exklusiv
try:
    ca.Execute()
    for teil in ca.p_rescnt.GetContents("*.ElmRes"):
        print(teil.cnttime, teil.GetNumberOfRows())
finally:
    for a, value in alt.items():
        setattr(ca, a, value)
```

Die Studienzeit (`SetTime.cDate`, `cTime`) nach jeder Rechnung zurücksetzen,
wenn sie erhalten bleiben soll.
