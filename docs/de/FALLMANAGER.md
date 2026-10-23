# GridLens Fall-Manager – Bedienungsanleitung

Englische Fassung: [../CASE_MANAGER.md](../CASE_MANAGER.md)

Der Fall-Manager ist das Fenster, das GridLens beim Start des ComPython öffnet
(`CASE_SOURCE = 'gui'`). Er **konfiguriert** nur die Berechnung. Er zeigt keine
Ergebnisse: Ergebnisse, Grenzwertverletzungen und Diagramme stehen im
PDF-Bericht, den die bestehende GridLens-Publikation nach der Rechnung erzeugt.
PowerFactory wartet, solange das Fenster offen ist; vor **Start calculation**
wird nichts gerechnet und nichts verändert. Die Beschriftungen im Fenster sind
englisch wie Code, Log und Bericht; hier stehen sie kursiv.

Technik: `tkinter` / `ttk` des Python, das PowerFactory ausführt, einheitlich
über `ttk.Style` (Thema `clam`); `tk.Canvas` nur für die Zeitachse. Kein
weiteres Paket.

## Aufbau

Das Fenster öffnet mittig mit etwa 86 % des Bildschirms (höchstens 1480 × 860, nie größer als der Bildschirm).
**Genau zwei Reiter**, *Case Manager* und *Settings*; einen Ergebnis-Reiter gibt es nicht.
Statuszeile und Aktionsleiste bleiben auf beiden Reitern sichtbar:

```
 [ Case Manager (1) ] [ Settings ]
+--------------------------------------+------------------------------------+------------------------+
| Available planned outages            | Case A - Sommermaßnahmen           | Planning cases  2 of 5 |
| In case  Planned outage Equip. Start | 2 case outages · 1 fixed backgr.   | Planning case Outg Stat|
| ☑ in case FS Bedarf 1 NE_L1  ...     | FS Bedarf 1    NE_L1  ...          | Sommer         2  ready|
| ☐       FS Bedarf 3    NE_L7  ...    | FS Bedarf 2    NE_L2  ...          | Nord-Ost       1  ready|
| [Add to case] [Set as fixed] [Det.]  | [Remove from case] [Details]       | [New][Copy][Delete]    |
|                                      | Timeline of the case               |                        |
+--------------------------------------+------------------------------------+------------------------+
| Calculation                                  | Problems and warnings                                 |
| [x] n-0 - reference QDS                      | Where        Problem                                  |
| [ ] n-1 - reference contingency analysis     | Leer         Not calculated: no planned outage ...    |
| [ ] (n-1)' - ... planned-outage scenarios    |                                                       |
| QDS: ...        [Show calculation preview]   |                                                       |
+----------------------------------------------+-------------------------------------------------------+
 QDS ... · n-0 · 3 of 4 cases ready · 1 problem · default settings
 [Save configuration] [Load saved]                                    [Cancel] [Start calculation]
```

- **Case Manager** – oben die drei Bereiche, etwa 40 % / 38 % / 22 %, Trennlinien verschiebbar.
  Von links nach rechts der Weg einer FS: aus der Library in den gewählten
  Fall, der rechts ausgewählt wird.
  - **Verfügbare Freischaltungen** (links): alle FS (`IntPlannedout`) der Library mit *In case*
    (`in case`, `fixed`, leer; auch als Zeilenfarbe), *Planned outage,
    Equipment, Start, End, Status*; *Add to case* (oder Enter, für alle markierten Zeilen),
    *Set as fixed background*, *Details* (auch Doppelklick auf eine Zeile).
    Die erste Spalte *In case* ist ein **Häkchen**: anhaken (Klick oder
    Leertaste) nimmt die FS in den gewählten Fall auf, abhaken beendet die
    Zuordnung; `☑ in case`, `☐` frei, `fixed` (nicht anhakbar). Demand
    Transfers (`IntOutage`) werden nicht gelesen: Sie verschieben Last und
    schalten kein Betriebsmittel.
  - **Der gewählte Fall** (Mitte): Titel *Case A - Name*, die Zeile *n case outages ·
    m fixed background outages*, die Tabelle *Planned outage, Equipment, Start,
    End, Priority*, *Remove from case*, *Details* und die Zeitachse des Falls.
  - **Planungsfälle** (rechts) – **höchstens 5**; der Zähler *2 of 5 cases* steht über der
    Tabelle, bei fünf sind *New* und *Copy* gesperrt. Tabelle *Planning case, Outages*
    (Zahl der FS), *Status* (`ready`, `not calculated`, `excluded`). Niemand
    vergibt eine ID: GridLens nummeriert die Fälle selbst (C1 … C5, die kleinste
    freie Nummer) und nutzt die ID nur intern (Ergebnisobjekte
    `GridLens_<stamp>_C1`, Bericht). Darunter *New, Copy, Delete*, *One
    case per planned outage* (legt höchstens fünf an) sowie für den gewählten Fall
    *Run*. Jeder Fall enthält nur seine direkt zugeordneten
    Freischaltungen. Kopieren, Ändern oder Löschen verändert die anderen Fälle nicht.
  - **Calculation** (unten links): *n-0 - reference QDS*, *n-1 - reference
    contingency analysis* und *(n-1)' - contingency analysis with
    planned-outage scenarios*. n-0 (die QDS von REF und jedem Fall) wird immer
    gerechnet und hat kein Bedienelement; (n-1)' braucht n-1 (ein Haken bei
    (n-1)' setzt n-1). *Results*: *Calculate now* oder *Re-evaluate the kept
    run of <Datum Zeit>* – dann wird nichts gerechnet, und die behaltenen
    Ergebnisobjekte dieses Laufs werden mit den aktuellen Settings neu bewertet;
    ein seitdem geänderter Fall ist NOT EVALUATED. Die Auswahl wird nicht mit den
    Fällen gespeichert. Dazu der QDS-Zeitraum des aktiven
    ComStatsim und *Show calculation preview* (einklappbar, siehe unten).
  - **Problems and warnings** (unten rechts): alles, was die Berechnung
    verhindert oder einschränkt, auch ungültige Settings. Der Reiter zeigt die
    Zahl, z. B. *Case Manager (1)*.
- **Settings** – eine Leiste (*Restore defaults*, *Apply settings*, *Save
  settings*, Zustand der Settings) und sechs Seiten:
  - *Network scope*: zwei Listen mit **jedem Grid des Modells** (inaktive
    gekennzeichnet; das Summary Grid eines Study Case wird nicht angeboten).
    *Assessed equipment*: nur Leitungen, Transformatoren und
    Knoten in den gewählten Grids werden bewertet (QDS und n-1); keine
    Auswahl = jedes Grid; *Select all grids*, *Clear selection*. *Contingencies*:
    *Same grids as the assessed equipment* oder *Own selection*; darunter die
    Vorschau „x of y contingencies … in scope“; der n-1-Lauf setzt die Fehlerfälle
    außerhalb für den Lauf auf *Not analysed* und setzt sie zurück. Eine Auswahl
    wirkt sofort.
  - *Limits*: thermische Grenzwerte (Warnschwellen und n-0-Grenzen, Leitungen
    und Transformatoren getrennt; Grenzwertbehandlung für n-1 und (n-1)') und
    Spannungsgrenzen (ein Band in p.u. der Nennspannung für jede Spannungsebene,
    Standard 0,95–1,05 p.u., als GridLens-Vorschlag gekennzeichnet; die
    Spannungslos-Schwelle 0,1 p.u.; Post-Fault-Spannungsgrenzen schreibgeschützt).
  - *Report and run*: Anhang-Schwellen (1 %-Punkt, 0,005 p.u.), Zeilen der
    Top-N-Listen (10), Punkte je Zeitplot (200), der Referenzfall REF (an/aus),
    höchstens Planungsfälle (5, bis 20) und höchstens n-1-Zeitpunkte je Fall
    (2000). Die Fall-Grenze wirkt sofort im Reiter Case Manager.
  - *Classification*: n-0-Änderungstoleranzen und die Parameter der
    n-1-/(n-1)'-Klassifizierung (Regelversion 1.0).
  - *Contingency analysis*: Contingency-Set, Kategorien, überwachter Bereich,
    AC/DC, Inselbildung, nicht versorgte Last, Lastabwurf, Post-Fault-Phasen,
    Remedial Actions – Kategorie B, **schreibgeschützt** (`not verified yet`).
    Ohne Contingency Analysis im Study Case legt GridLens für n-1 selbst eine
    an (siehe Berechnungsoptionen).
  - *QDS time base*: Beginn, Ende, Zeitschritt und Zeitdefinition des aktiven
    ComStatsim, schreibgeschützt.
  - *Fixed background & rules*: der bisherige Reiter dieses Namens, unverändert:
    die festen Hintergrund-FS (Rfix) mit *Remove from fixed background* und die
    Regeln zwischen FS mit drei Auswahllisten, *Add rule*, *Remove rule*.
- **Statuszeile** (beide Reiter): QDS-Zeitraum, Bewertung, rechenbare Fälle,
  Problemzahl in Rot, Zahl der Settings-Overrides; ein Klick öffnet *Case Manager*.

### Settings-Felder

Jede Zeile: *Setting, Value, Unit, Source, Category* und eine Meldung. *Source*
ist `GridLens` (GridLens-Standard), `PowerFactory` (aus Modell oder
Berechnungskonfiguration gelesen – derzeit nur die schreibgeschützten Felder der
Kategorie B, angezeigt als `not verified yet`), `user` (übernommener Override)
oder `edited, not applied`. *Category* ist `A · evaluation` (deutet Ergebnisse,
ändert nie Lastfluss, Bemessung oder Modell) oder `B · calculation` (würde
ändern, was PowerFactory rechnet; bis zur Verifikation schreibgeschützt).

Jede Eingabe wird beim Tippen geprüft: endliche Zahl, positive Grenzen,
nicht negative Toleranzen, ein Wert aus der Liste für die n-1-Grenzwertbehandlung.
Bei *Apply* zusätzlich Spannungslos-Schwelle < Minimum < Maximum der Spannung und
Warnschwelle ≤ Grenze. Ein ungültiges Feld wird rot mit seiner Meldung, der Reiter heißt
*Settings (!)*, und *Start calculation* sowie *Save* lehnen mit der Liste der
Probleme ab. *Start calculation* und *Save* übernehmen geänderte Werte zuerst.
*Restore defaults* entfernt jeden Override.

Gespeichert werden nur Overrides, unter `settings` in der Konfigurationsdatei
der Fälle. **Diese JSON-Ablage ist vorläufig** (Teil 2); eine native Ablage im
PowerFactory-Projekt und ein gespeicherter Settings-Snapshot je Lauf folgen,
sobald die Probe ein geeignetes Objekt gefunden hat. Zu Beginn eines Laufs
werden die Settings als Snapshot festgehalten (Werte, Herkunft, Overrides,
Settings-Version 1.0, Klassifizierungsregeln 1.0) und im Log sowie im Bericht
genannt (*Model Quality Assurance*, Zeile *Settings*).

### Filtern und Sortieren – jede Tabelle

- Eine **Filterzeile** direkt unter den Spaltenköpfen: ein Textfeld je
  Textspalte (zeigt Zeilen, die den Text enthalten, ohne Groß/Klein) und eine
  Auswahlliste je Kategoriespalte (*Status*, *In case*, *Rule*; *All* schaltet
  sie ab). Filter mehrerer Spalten gelten zusammen.
- Unter der Tabelle: *12 of 48 shown · Clear filters* (nur solange ein Filter
  aktiv ist).
- Ein **Klick auf einen Spaltenkopf** sortiert nach der Spalte, ein zweiter
  kehrt die Reihenfolge um (▲/▼ hinter der Überschrift); Zahlen nach Wert.
- Filtern und Sortieren ändern nur die Anzeige, nie die Konfiguration. Köpfe
  und Filter folgen der Tabellenbreite; auf schmalen Bildschirmen schrumpfen
  alle Spalten anteilig.

### Hilfe beim Überfahren mit der Maus

Bleibt die Maus etwa eine halbe Sekunde auf einem Bedienelement, erscheint
eine Erklärung, was es für die Berechnung bewirkt: jede Schaltfläche, *Run*, Name und Beschreibung, der Fallzähler, die Spaltenköpfe mit
Kategorien (*Status*, *In case*, *Outages*, *Priority*, *Rule*; jeder nennt auch das
Sortieren), jedes Filterfeld, die Legende der Zeitachse, die Regelauswahl,
n-0, n-1, (n-1)', der QDS-Zeitraum, die Statuszeile sowie jedes Feld und jede
Schaltfläche unter *Settings*. Die Verzögerung beträgt 450 ms; der Text
verschwindet beim Verlassen, bei einem Klick oder einer Taste. Bindungen werden
ergänzt (`add='+'`), nie ersetzt, und ein Tooltip startet nie eine Berechnung.
Die Texte stehen englisch in `HELP_TEXTS`, `SETTING_HELP` und `COLUMN_HELP` von
`gridlens_report.py` (Klasse `Tooltip`, nur Standardbibliothek); die Texte zu
n-0, n-1, (n-1)', Planned Outages, QDS-Zeitschritt, Contingency-Set,
Grenzwerten, Klassifizierung und Settings folgen dem Master-Prompt, ins
Englische übersetzt.

## Gestaltung und direkt sichtbare Hilfe

Eine dunkelblaue Kopfzeile kennzeichnet den Planungsbereich. Tabellen nutzen
einheitliche Blau-Grautöne, größere native Schriften, 26 Pixel hohe Zeilen und
eine deutliche Auswahl. Hinweise brechen passend zur Spaltenbreite um; die
Statuszeile steht über der Aktionszeile und verdrängt weder Cancel noch Start
calculation. Strg+Tab wechselt zwischen Reitern. Die erste Spalte der Falltabelle zeigt das Run-Häkchen (☑/☐). Ein Klick oder die Leertaste auf der fokussierten Zeile schaltet den Fall ein/aus. Abgewählte Fälle bleiben gespeichert und entfallen aus Berechnung und Bericht. Der separate Bereich Selected case entfällt. Die Regelauswahl ist beschriftet und passt sich der Breite an. Es
bleibt bei Standard-Tk/ttk, ohne neue Abhängigkeit oder Animation. Publisher und
eigenständiges GUI-Testskript zeigen dieselbe Gestaltung.

## Unabhängige Planungsfälle

Jeder Fall wird durch direkte Zuordnung seiner Freischaltungen gestaltet. Beispiel:

- C1: FS Nord.
- C2: FS Süd.
- C3: FS Nord und FS Süd, beide direkt zugeordnet.

Dieselbe Freischaltung darf in mehreren Fällen stehen. Kein Fall übernimmt
Freischaltungen eines anderen Falls oder setzt ihn voraus; Kombinationen werden
nicht durch Fallbeziehungen eingeschränkt. Für eine Variante einen Fall kopieren
und die Kopie anpassen. Löschen oder Ausschließen von C1 lässt C2 und C3 unverändert.

Gespeicherte Konfigurationen der Version 1 werden beim Öffnen im Speicher in
Version 2 überführt: bisher übernommene Freischaltungen und ihre wirksamen eigenen
Termine werden direkt zugeordnet; Voraussetzungen und Alternativbeziehungen
entfallen. Falls Beziehungen vorhanden waren, zeigt *Problems and warnings* einen Hinweis
zur Prüfung der Zuordnungen. Die ursprüngliche Datei bleibt bis zum Speichern
unverändert. Ungültige alte Verweise oder Kreise werden mit Dateipfad gemeldet,
statt Zuordnungen stillschweigend zu verlieren.

Die Regeln auf *Fixed background & rules* gelten zwischen zwei
**Freischaltungen** in jedem Fall: *must not overlap* (Fenster dürfen sich
nicht überschneiden), *second only after the first* (die zweite beginnt erst
nach dem Ende der ersten), *only together* (ein Fall mit der einen enthält
auch die andere, mit überlappenden Zeitfenstern). Ein Fall, der eine Regel bricht, wird
nicht gerechnet und gemeldet.

## Tastatur

Jede Liste lässt sich ohne Maus bedienen (`KEYBOARD_SHORTCUTS` in `gridlens_report.py`). Unter macOS wirkt Command wie Strg.

| Taste | Wo | Was |
|---|---|---|
| Entf / BackLeertaste | Fallliste | gewählten Fall löschen (fragt vorher) |
| Entf / BackLeertaste | FS des Falls | gewählte FS aus dem Fall entfernen |
| Entf / BackLeertaste | feste Hintergrund-FS | gewählte FS aus dem festen Hintergrund entfernen |
| Entf / BackLeertaste | Regeln | gewählte Regeln entfernen |
| Leertaste | Fallliste | Run-Flag des fokussierten Falls umschalten |
| Leertaste | verfügbare FS | fokussierte FS an- oder abhaken |
| Enter | verfügbare FS | alle gewählten FS dem Fall hinzufügen |
| F2 / Enter | Fallliste | Fall direkt umbenennen |
| Strg+A | jede Tabelle | alle angezeigten Zeilen wählen |
| Strg+N | Fenster | neuer Fall |
| Strg+F | Fenster | verfügbare FS durchsuchen |
| Strg+S | Fenster | Konfiguration speichern |
| Strg+O | Fenster | gespeicherte Konfiguration laden |
| Strg+Enter | Fenster | Berechnung starten |
| Esc | Fenster | direkte Bearbeitung beenden, sonst abbrechen |

## Was ein Klick bewirkt

| Aktion | Wirkung |
|---|---|
| Klick auf einen Fall rechts (`<<TreeviewSelect>>`) | die Mitte zeigt sofort seine Freischaltungen; links sind sie als `in case` markiert; Beschreibung, Zeitachse, die anderen Reiter und die Statuszeile folgen. Kein weiteres Fenster. |
| Text in ein Filterfeld tippen / Filterliste wählen | die Tabelle zeigt sofort nur passende Zeilen; *Clear filters* zeigt wieder alle |
| Klick auf einen Spaltenkopf | sortiert nach der Spalte; ein zweiter Klick kehrt die Reihenfolge um |
| Klick auf einen Fall in einer Beziehungsliste | wählt ihn aus (hervorgehoben) oder hebt die Auswahl auf; die Beziehung gilt sofort |
| Maus auf einem Bedienelement ruhen lassen | nach etwa einer halben Sekunde erscheint eine Erklärung; sie schließt beim Verlassen oder bei einem Klick |
| Klick auf die Statuszeile | öffnet *Case Manager* |
| Eingabe in ein *Settings*-Feld | sofort geprüft: rot mit Grund, wenn ungültig; *edited, not applied*, bis übernommen |
| *Apply settings* / *Save settings* / *Restore defaults* | prüft und übernimmt / speichert zusätzlich die Konfigurationsdatei / entfernt jeden Override |
| *Show calculation preview* | öffnet oder schließt die schreibgeschützte Vorschau unter den Problemen |
| Häkchen in der ersten Spalte der linken Liste setzen oder entfernen (oder Leertaste) | genau diese FS kommt sofort in den gewählten Fall oder verlässt ihn; eine feste FS lässt sich nicht anhaken und nennt den Grund |
| *Add to case* oder Enter in der linken Liste | die gewählten FS werden zugeordnet; Falltabelle, Zahl der FS, Markierungen und Vorschau aktualisieren sich sofort. Eine FS, die schon im Fall oder fest ist, wird mit Grund abgelehnt. |
| *Remove from case* oder Entf-Taste in der Mitte | nur die Zuordnung endet; die Freischaltung in PowerFactory bleibt unberührt. |
| Doppelklick in der Mitte oder *Details* | ein kompaktes Fenster mit den PowerFactory-Daten der FS (Objekt, Klasse, Betriebsmittel, Schalthandlungen, Fenster, Priorität, Status, verwendet in Fällen) und ihren eigenen Terminen in diesem Fall. |
| *Set as fixed background* | die FS wird Teil der Referenz und jedes Falls (Rfix). Abgelehnt, solange sie einem Fall zugeordnet ist – sie wirkt so nie doppelt. |
| *New* | legt *Case n* mit der nächsten generierten ID an (C1 … C5) und wählt ihn aus; kein weiteres Fenster. Bei fünf Fällen gesperrt. |
| *Copy* | neue generierte ID, Name *… (copy)*, gleiche FS und eigene Termine; vollständig unabhängig. Bei fünf Fällen gesperrt. |
| Doppelklick auf einen Fall (oder F2 / Enter) in der Fallliste | der Name wird direkt in seiner Zeile bearbeitbar; Enter oder ein Klick daneben übernimmt, Escape bricht nur die Bearbeitung ab; ein leerer Name behält den alten. Die generierte ID für Ergebnisobjekte bleibt. |
| Doppelklick auf die Beschreibung neben dem Fallnamen in der Mitte | die Beschreibung wird ebenso direkt bearbeitbar; ohne Beschreibung steht dort *(double-click to add a description)* |
| Doppelklick auf eine Zeile der linken Liste | das Detailfenster dieser Freischaltung |
| *Delete* | fragt einmal nach und entfernt nur den gewählten Fall. Andere Fälle und die Freischaltungen in PowerFactory bleiben unverändert. |
| *One case per planned outage* | ersetzt die Fälle durch einen je FS im simulierten Zeitraum, höchstens fünf (mit Hinweis, wenn FS übrig bleiben); ignorierte und feste FS bekommen keinen. |
| *Save configuration* / *Load saved configuration* | schreibt / liest die JSON-Datei des Projekts mit Revision, Benutzer und Zeit; das Projekt bleibt unberührt. |
| *Cancel*, Escape, Fenster schließen | beendet den Lauf: nichts gerechnet, gespeichert oder publiziert, nichts im Projekt geändert. Der Abbruch wird an den aufrufenden Reportablauf weitergegeben; die Erweiterung endet nicht normal zur anschließenden Berichtserzeugung. Das IntReport-Verhalten muss noch in PowerFactory geprüft werden. |
| *Start calculation* | prüft (siehe unten), schließt das Fenster und übergibt die Konfiguration an GridLens; danach laufen die bestehende Berechnung und PDF-Publikation. Es folgt kein Ergebnisfenster. |

## Zeitachse

Die Zeitachse dient nur der Planungskontrolle (keine Lastfluss-, Spannungs-
oder sonstigen Ergebnisse). Eine Zeile je Fall-FS (blau) und je feste FS
(grau); hellblau schattiert sind Zeiten, in denen mehr als eine FS aktiv ist.
Sich überlappende FS sind normale Planung, weder Warnung noch Fehler. Die
Zeitachse zeigt keine Daten und keine Zahlen, nur Reihenfolge und Überlappung. Ein langer leerer
Zeitraum (z. B. zwischen KW10 und KW40) erscheint als schmales helles Band,
damit weit auseinanderliegende FS lesbar bleiben (`timeline_scale`).

## Berechnungsoptionen

- **n-0 – Referenz-QDS**: der Grundzustand ohne geplante Freischaltungen und
  ohne zusätzliche Fehlerfälle, mit den Last- und Einspeiseprofilen des
  ComStatsim. Wird immer gerechnet: Der Bericht baut darauf auf.
- **n-1 – Referenz-Ausfallanalyse** und **(n-1)' – Ausfallanalyse mit
  FS-Szenarien**: gerechnet mit der Contingency Analysis (ComSimoutage) des
  aktiven Study Case, zu den QDS-Zeitschritten in den FS-Fenstern jedes Falls
  (GridLens schreibt sie für den Lauf in `studyTime`). n-1 rechnet nur mit den
  festen FS, (n-1)' mit den FS des Falls; jedes Ergebnis von (n-1)' wird gegen
  n-1 zum selben Zeitpunkt und Fehlerfall eingestuft. Ohne Contingency Analysis
  im aktiven Study Case (z. B. dem QDS-Study-Case) legt GridLens dort
  `GridLens_<Stempel>_N1` an, mit je einem Fehlerfall pro Leitung/Zweig,
  Transformator, Drossel, Kompensationsanlage und FACTS-Element der aktivierten
  Contingency-Grids – keine Erzeuger, Lasten oder Sammelschienen – und behält sie
  nach dem Lauf. Ein Fehlerfall, dessen
  Betriebsmittel der Fall schon ausschaltet, ist NOT_APPLICABLE. Bis der Bericht
  n-1-Kapitel hat (Teil 4), steht das Ergebnis im Log und als Zeile *n-1 <Fall>*
  auf der Seite Model Quality Assurance.
- **QDS-Zeitraum**: aus dem aktiven ComStatsim, nur angezeigt (auch unter
  *Settings → QDS time base*). Es gibt keine Zeitoptimierung: kein verkürztes
  Fenster, keine Segmentierung, keine zusätzlichen Zeitpunkte, kein geänderter
  Zeitschritt; jeder Lauf deckt den ganzen ComStatsim-Zeitraum ab.

## Prüfungen bei *Start calculation*

1. Die Konfiguration ist gültig (IDs, FS-Pfade, eigene Termine, FS-Regeln).
2. Mindestens ein Fall ist rechenbar; sonst fragt GridLens, ob nur die
   Referenz gerechnet werden soll.
3. Nicht rechenbare Fälle (fehlende FS, verletzte
   Regel, außerhalb des Zeitraums, eigene Termine) werden mit Grund genannt;
   GridLens fragt, ob es weitergehen soll, und meldet sie als
   NOT EVALUATED / NOT SIMULATED.
4. Es wird nur n-0 verlangt.
5. Jede Einstellung ist gültig (geänderte Werte werden zuerst übernommen);
   sonst öffnet sich *Settings* mit der Liste der Probleme, und nichts startet.

## Übergabe an GridLens

```mermaid
flowchart LR
    W["Fall-Manager (CaseManagerDialog)"] -- "jeder Klick" --> E["CaseEditor: Kopie der Konfiguration"]
    E -- "Start calculation" --> C["Konfiguration (Fälle, Hintergrund, Beziehungen, Regeln, Bewertungen)"]
    C --> R["resolve_request: geprüfte Planungsfälle, Referenztyp"]
    R --> G["execute_gridlens: REF + eine QDS je Fall (unverändert)"]
    G --> P["publish_report: Tabellen für das PDF (unverändert)"]
    W -- "Cancel" --> X(["Ende, nichts geändert"])
```

Trennung im Code: `CaseManagerDialog` ist das Fenster und hält nur den
Auswahlzustand; `CaseEditor` enthält jede Bearbeitungsregel und die Kopie der
Konfiguration (ohne Fenster getestet); die PowerFactory-Referenzen sind die
Datensätze, die GridLens vor dem Öffnen gelesen hat; `resolve_request` macht
aus der Konfiguration den Berechnungsauftrag; `execute_gridlens` rechnet,
`publish_report` publiziert. Das Fenster schaltet nie Betriebsmittel, schreibt
nie in PowerFactory und startet nie eine QDS.

## Woher die Fälle kommen

| `CASE_SOURCE` | Verhalten |
|---|---|
| `'gui'` (Standard) | das Fenster, vorbelegt mit der gespeicherten Konfiguration. Kann `tkinter` es nicht öffnen oder lässt es sich nicht aufbauen: die gespeicherte Konfiguration; ohne sie je FS ein Fall. Der Bericht nennt die Quelle. |
| `'saved'` | die gespeicherte Konfiguration, ohne Fenster |
| `'per_outage'` | je Freischaltung im simulierten Zeitraum ein Fall |

Konfigurationsdatei: `CASE_CONFIG_DIR` (Standard `~/GridLens/cases`), eine je
Projekt, gespeichert als `<Projekt>_<Hash>.v2.json`. Die Schema-1-Datei
`<Projekt>_<Hash>.json` des ausgelieferten gridlens-powerfactory-Skripts wird nur
gelesen (solange es keine `.v2.json` gibt) und nie überschrieben; beide Versionen
arbeiten so am selben Projekt. Der Hinweis zur Umstellung auf unabhängige Fälle
erscheint nur, bis die geprüften Fälle gespeichert sind. Neue Felder seit der Überarbeitung: `assessments` (`["n-0"]`), je
Fall `enabled` (true/false) und `settings` (nur Overrides, vorläufig). Das Feld
`mode` früherer Versionen (Zeitoptimierung) wird beim Lesen ignoriert und nicht
mehr gespeichert. Eine gespeicherte oder von Hand bearbeitete
Konfiguration mit mehr als fünf Fällen (z. B. von GridLens 8.0 gespeichert)
öffnet sich trotzdem im Fallmanager, zeigt *6 of 5 cases* in Rot und den Grund
unter *Problems and warnings*, damit Fälle gelöscht werden können; Rechnen, Speichern
und `CASE_SOURCE = 'saved'` lehnen sie mit diesem Grund ab; nur
`CASE_SOURCE = 'per_outage'` (ohne Fenster) legt weiterhin je FS einen Fall ohne
Grenze an. Ein mit *Run* ausgeschlossener Fall (`excluded`) wird weder gerechnet noch
berichtet; andere Fälle bleiben unverändert.

## Was sich gegenüber dem bisherigen Fenster geändert hat

| Erhalten | Geändert |
|---|---|
| Fälle: neu, kopieren, umbenennen, löschen, Beschreibung, je FS ein Fall | Fallliste als filterbare Tabelle mit FS-Zahl und Status, **höchstens 5 Fälle**, **IDs generiert (C1 … C5), nie getippt**; neuer Fall ohne Dialog; Umbenennen im Feld; Löschen betrifft nur den gewählten Fall |
| Zuordnung von FS, eine FS in mehreren Fällen | Zuordnung aus einer eigenen Liste verfügbarer FS mit Suche, Filter und *Add to case*; die Falltabelle zeigt nur die FS des Falls |
| feste Hintergrund-FS (Rfix) | eigener Abschnitt und eigene Schaltfläche; eine feste FS kann nicht zugleich Fall-FS sein |
| – | **entfernt:** Beziehungen zwischen Fällen; FS direkt unabhängigen Fällen zuordnen |
| Regeln `not_overlap`, `order`, `together` | über drei Auswahllisten statt getippter Textzeilen |
| eigene Termine je Fall (erfasst, nicht angewendet) | im Detailfenster der FS |
| Konfiguration speichern, Vorschau, Abbrechen, OK | Vorschau in kurzen Zeilen; *Load saved configuration*; OK heißt jetzt *Start calculation* |
| – | **entfernt:** Auswahl Conservative/Optimized und der Vorschlag kürzerer Fenster |
| – | **neu:** Filterzeile und Sortieren per Spaltenkopf in jeder Tabelle, Statuszeile, Problemliste, Zeitachse, *Run* je Fall |
| drei Reiter (Workspace, Fixed background & rules, Review & start) | **seit Teil 2:** genau zwei Reiter, *Case Manager* (Arbeitsbereich, Berechnungsauswahl, Probleme, einklappbare Vorschau) und *Settings* (Grenzwerte, Klassifizierung, Contingency Analysis schreibgeschützt, QDS-Zeitbasis, Fixed background & rules); Auswahl n-0 / n-1 / (n-1)'; Tooltips an jeder Einstellung |

## In PowerFactory ausprobieren

`tools/FS_CaseManager_GUI_Test_PowerFactory2026.py` ist ein **eigenständiges
Skript**: Es lädt und importiert `gridlens_report.py` nicht und wird allein in
ein ComPython eingefügt. Es trägt eine eigene Kopie des Fallmanagers (Fenster
und was es braucht: Einlesen der Freischaltungen, Prüfen einer Konfiguration,
Vorschau), öffnet daher genau dieses Fenster mit den echten Freischaltungen des
aktiven Projekts, nur lesend, und gibt aus, was *Start calculation* zurückgibt,
statt zu rechnen. Speichern und Laden arbeiten auf einer temporären Kopie der
Konfiguration. Öffnet sich das Fenster dort nicht, die Fälle an einem
Arbeitsplatz konfigurieren, an dem es läuft, und `CASE_SOURCE = 'saved'` setzen.

Die Kopie ist in der Datei markiert und wird von `tools/sync_case_manager_copy.py`
geschrieben (Entwicklungswerkzeug, nicht Teil der Auslieferung). Wer den
Fallmanager in `gridlens_report.py` ändert, führt
`python3 tools/sync_case_manager_copy.py` aus;
`test_the_copied_case_manager_matches_gridlens_report` schlägt fehl, solange die
Kopie veraltet ist.

## Vorschau der Falleinstellungen

*Show calculation preview* im Reiter Case Manager öffnet eine schreibgeschützte,
scrollbare Vorschau unter den Problemen (standardmäßig zugeklappt). Sie aktualisiert sich bei Run-Häkchen und Änderungen an Fällen.
Jeder rechenbare Fall nennt Name, Beschreibung, FS mit wirksamen Zeitfenstern,
n-0, den vollständigen QDS-Zeitraum und den festen Hintergrund. Gemeinsame
Einstellungen nennen Referenz, Hintergrund-Fenster und FS-Regeln. Identische
Fälle nennen das zur Wiederverwendung vorgesehene Ergebnis. Nicht rechenbare
Fälle zeigen den Grund; abgewählte Fälle stehen gesondert als excluded. Die
Vorschau startet keine Berechnung.
