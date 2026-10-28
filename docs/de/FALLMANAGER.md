# GridLens Fallmanager – Bedienungsanleitung

Englische Fassung: [../CASE_MANAGER.md](../CASE_MANAGER.md)

Der Fallmanager ist das Fenster, das GridLens öffnet, wenn das ComPython mit
`CASE_SOURCE = 'gui'` läuft. Es **konfiguriert** nur die Rechnung: welche
Planungsfälle, welche festen Hintergrund-Außerbetriebnahmen und Regeln, welche
Bewertungen und welche Einstellungen. Es zeigt keine Ergebnisse; die stehen im
Bericht. PowerFactory wartet, solange das Fenster offen ist, und vor **Start
calculation** wird im Projekt nichts gerechnet oder geändert.

`main.py` zeichnet das Fenster mit tkinter/ttk, `main_qt.py` mit PyQt6 oder
PyQt5 (wählbar mit `QT_BINDING`). Beide bieten dieselben Funktionen und
übergeben GridLens dieselbe Konfiguration.

## Aufbau

Zwei Seiten, *Case Manager* und *Settings*. Eine Statuszeile und die
Aktionsleiste (*Save configuration*, *Load saved configuration*, *Cancel*,
*Start calculation*) bleiben auf beiden sichtbar.

```
 [ Case Manager (1) ] [ Settings ]
+--------------------------------------+------------------------------------+------------------------+
| Available planned outages            | Case C1 - Sommermaßnahmen          | Planning cases  2 of 5 |
| In case  Planned outage Equip. Start | 2 case outages · 1 fixed backgr.   | Run Planning case Stat.|
| ☑        FS Bedarf 1    NE_L1  ...   | FS Bedarf 1    NE_L1  ...          | ☑   Sommer       ready |
| ☐        FS Bedarf 3    NE_L7  ...   | FS Bedarf 2    NE_L2  ...          | ☑   Nordost      ready |
| [Add to case] [Set as fixed] [Det.]  | [Remove from case] [Details]       | [New][Copy][Delete]    |
|                                      | Timeline of the case               |                        |
+--------------------------------------+------------------------------------+------------------------+
| Calculation                                  | Problems and warnings                                 |
| n-0 always                                   | Where        Problem                                  |
| [ ] n-1 - reference contingency analysis     | C3           Not calculated: no planned outage ...    |
| [ ] (n-1)' - ... planned-outage scenarios    |                                                       |
| QDS ...   Results: Calculate now             |                                                       |
| Show calculation preview                     |                                                       |
+----------------------------------------------+-------------------------------------------------------+
 QDS ... · n-0 · 2 of 3 cases ready · 1 problem or warning · default settings
 [Save configuration] [Load saved configuration]                       [Cancel] [Start calculation]
```

### Seite *Case Manager*

Die drei Bereiche folgen dem Weg einer Außerbetriebnahme: aus der Bibliothek
(links) in den gewählten Fall (Mitte), der rechts ausgewählt wird. Die Trenner
lassen sich ziehen.

- **Available planned outages** (links): jede `IntPlannedout` des Projekts mit
  *In case, Planned outage, Equipment, Start, End, Status*.
  - *In case* ist ein Kontrollkästchen: ankreuzen (Klick oder Leertaste), und
    die Außerbetriebnahme gehört zum gewählten Fall; Haken entfernen, und die
    Zuordnung endet. Eine feste Hintergrund-Außerbetriebnahme zeigt *fixed*
    und lässt sich nicht ankreuzen.
  - *Status*: *in simulated period*, *outside simulated period* (in diesem
    Lauf ohne Wirkung) oder *Ignored in PowerFactory* (nur in einem Fall
    angewendet, der sie enthält).
  - *Add to case* (oder Enter) ordnet alle markierten Zeilen zu, *Set as fixed
    background* macht sie fest, *Details* (oder Doppelklick) öffnet das
    Detailfenster.
  - Lastverlagerungen (`IntOutage`) werden nicht gelistet: sie verschieben
    Last und schalten keine Betriebsmittel.
- **Der gewählte Fall** (Mitte): sein Name, die Beschreibung (Doppelklick in
  `main.py`, Klick in `main_qt.py`), die Zählzeile *n case outages · m fixed
  background outages*, seine Außerbetriebnahmen mit *Planned outage,
  Equipment, Start, End, Priority*, *Remove from case*, *Details* und die
  Zeitleiste.
- **Planning cases** (rechts): höchstens so viele, wie *Settings → Report and
  run → Planning cases, at most* erlaubt (Standard 5, bis 20); der Zähler *2 of
  5 cases* wird an der Grenze rot, *New*/*Copy* sind dann gesperrt.
  - *Run* (erste Spalte): angekreuzt = gerechnet und berichtet; leer =
    ausgeschlossen, bleibt in der Konfiguration, wird aber weder gerechnet noch
    berichtet.
  - *Planning case*: der Name; Doppelklick, F2 oder Enter bearbeitet ihn direkt
    in der Zeile.
  - *Outages*: die Zahl der zugeordneten Außerbetriebnahmen.
  - *Status*: *ready*, *not calculated* (der Grund steht unter *Problems and
    warnings*) oder *excluded*.
  - *New*, *Copy*, *Delete*, *One case per planned outage*.
  - IDs (`C1`, `C2`, …) werden erzeugt, nie eingetippt. Sie benennen die
    Ergebnisobjekte (`GridLens_<stamp>_C1`) und bleiben beim Umbenennen.
- **Calculation** (unten links):
  - n-0 (die QDS von REF und jedem Fall) wird immer gerechnet.
  - *n-1 – reference contingency analysis* und *(n-1)' – contingency analysis
    with planned-outage scenarios*. (n-1)' braucht n-1: Ankreuzen von (n-1)'
    kreuzt n-1 an, Abwählen von n-1 wählt (n-1)' ab.
  - Der QDS-Zeitraum des aktiven ComStatsim.
  - *Results*: *Calculate now* oder *Re-evaluate the kept run of <Datum Zeit>*.
    Die Neuauswertung rechnet nichts; sie liest die Ergebnisobjekte dieses
    Laufs mit den aktuellen Einstellungen. Die Auswahl wird nicht gespeichert.
  - *Show calculation preview*: die schreibgeschützte Vorschau dessen, was
    gerechnet wird.
- **Problems and warnings** (unten rechts): alles, was die Rechnung stoppt oder
  einschränkt, mit dem Ort. Der Seitenreiter zeigt die Zahl, z. B. *Case
  Manager (1)*.

### Seite *Settings*

Eine Aktionsleiste (*Restore defaults*, *Apply settings*, *Save settings*, der
Zustand der Einstellungen) und sieben Bereiche:

| Bereich | Inhalt |
|---|---|
| Network scope | *Report filter: assessed equipment* (Netze, deren Leitungen, Transformatoren und Knoten bewertet werden; keine Auswahl = jedes Netz; ohne Wirkung auf die Rechnung); *n-1 filter: contingencies by grid* (*Every grid* oder *Own selection*, mit der Zahl der Fehlerfälle im Umfang); *n-1 filter: outaged elements* (nur Fehlerfälle, die ein gewähltes Element ausfallen lassen, werden gerechnet). Eine Auswahl wirkt sofort. |
| Limits | Warnschwellen und n-0-Grenzen (Leitungen und Transformatoren getrennt), die n-1-Grenzbehandlung, das Spannungsband in p.u. für jede Spannungsebene, die Spannungslos-Schwelle; Post-Fault-Spannungsgrenzen nur lesend |
| Classification | n-0-Änderungstoleranzen und die Klassifikationsparameter für n-1 / (n-1)' |
| Report and run | Anhangsschwellen, Top-N-Zeilen, Punkte je Zeitplot, REF an/aus, die Fallgrenze, n-1-Studienzeitpunkte je Fall |
| Contingency analysis | Contingency Set, Kategorien, überwachter Umfang, AC/DC, Inselbildung, nicht versorgte Last, Lastabwurf, Post-Fault-Phasen, Abhilfemaßnahmen – nur lesend |
| QDS time base | Beginn, Ende, Zeitschritt des aktiven ComStatsim, nur lesend |
| Fixed background & rules | die festen Hintergrund-Außerbetriebnahmen und die Regeln zwischen Planned Outages |

Jede Einstellungszeile zeigt *Setting, Value, Unit, Source, Category* und eine
Meldung:

- *Source*: `GridLens` (Standard), `PowerFactory` (aus dem Modell gelesen),
  `user` (eine übernommene Abweichung) oder `edited, not applied`.
- *Category*: `A · evaluation` interpretiert Ergebnisse und ändert nie einen
  Lastfluss, eine Bemessung oder das Modell. `B · calculation` würde ändern,
  was PowerFactory rechnet, und ist nur lesend.

Jeder Wert wird beim Tippen geprüft: endliche Zahl, positive Grenzen,
nicht-negative Toleranzen, ein Wert aus der Liste. *Apply* prüft zusätzlich
Spannungslos-Schwelle < Minimum < Maximum und Warnung ≤ Grenze. Ein ungültiges
Feld wird rot mit seiner Meldung, der Seitenreiter zeigt *Settings (!)*;
*Start calculation* und *Save* lehnen ab, bis es behoben ist. *Start
calculation* und *Save* übernehmen bearbeitete Werte zuerst. *Restore
defaults* entfernt jede Abweichung. Standardwerte und Bedeutung jeder
Einstellung: [ARCHITEKTUR.md, Abschnitt 9](ARCHITEKTUR.md#9-einstellungen).

### Statuszeile

QDS-Zeitraum, Bewertungen, bereite Fälle, Zahl der Probleme (rot) und
Einstellungsabweichungen. Ein Klick öffnet die Seite *Case Manager*.

## Mit Fällen arbeiten

Jeder Fall enthält nur die ihm direkt zugeordneten Außerbetriebnahmen.
Dieselbe Außerbetriebnahme kann in mehreren Fällen stehen. Beispiel:

- C1: FS Nord.
- C2: FS Süd.
- C3: FS Nord und FS Süd, beide direkt zugeordnet – die gemeinsame Planung.

Kein Fall erbt von einem anderen, hängt von ihm ab oder schließt eine
Kombination aus. Für eine Variante einen Fall kopieren und die Kopie ändern;
Löschen oder Ausschließen von C1 lässt C2 und C3 unverändert.

**Feste Hintergrund-Außerbetriebnahmen** (*Settings → Fixed background &
rules*) sind in der Referenz (dann Rfix) und in jedem Fall aktiv. Eine
Außerbetriebnahme, die einem Fall zugeordnet ist, kann nicht fest werden; so
wirkt sie nie doppelt.

**Regeln** gelten in jedem Fall: *must not overlap* (Fenster dürfen sich nicht
überlappen), *second only after the first* (die zweite beginnt erst, wenn die
erste geendet hat), *only together* (ein Fall mit einer enthält die andere,
zeitlich überlappend). Ein Fall, der eine Regel verletzt, wird nicht gerechnet
und berichtet.

**Eigene Termine je Außerbetriebnahme** lassen sich im Detailfenster eingeben.
Sie werden nur erfasst, nicht angewendet; ein solcher Fall wird NOT EVALUATED
berichtet. Für einen anderen Termin in PowerFactory eine Planned Outage mit
diesem Termin anlegen.

## Jede Tabelle: filtern und sortieren

- Eine Filterzeile direkt unter den Spaltenköpfen: ein Textfeld je Textspalte
  (enthält den Text, Groß-/Kleinschreibung egal) und eine Auswahlliste je
  Kategoriespalte (*All* schaltet sie ab). Filter mehrerer Spalten wirken
  zusammen.
- Unter der Tabelle: *12 of 48 shown · Clear filters*, solange ein Filter
  aktiv ist.
- Ein Klick auf einen Spaltenkopf sortiert nach dieser Spalte; ein zweiter
  kehrt die Reihenfolge um. Zahlen sortieren nach Wert.
- Filtern und Sortieren ändern nur die Anzeige, nie die Konfiguration. Eine
  ausgefilterte Zeile wird von der Leertaste nie geändert.

## Hover-Hilfe

Ruht die Maus etwa eine halbe Sekunde auf einem Element, erscheint, was es an
der Rechnung bewirkt: jede Schaltfläche, *Run*, Name und Beschreibung, der
Fallzähler, die Spaltenköpfe, jeder Filter, die Zeitleiste, die Regelfelder,
n-0, n-1, (n-1)', der QDS-Zeitraum, die Statuszeile und jede Einstellung. Die
Texte stehen in `HELP_TEXTS`, `SETTING_HELP` und `COLUMN_HELP` im Skript.

## Zeitleiste

Nur eine Planungsprüfung, ohne Lastfluss oder Ergebnis. Eine Zeile je
Außerbetriebnahme des Falls (blau) und je fester Außerbetriebnahme (grau);
Schattierung markiert Zeiten, in denen mehr als eine aktiv ist. Überlappende
Außerbetriebnahmen sind normale Planung, weder Warnung noch Fehler. Ein langer
leerer Zeitraum (z. B. zwischen KW 10 und KW 40) wird kurz gezeichnet, damit
weit auseinanderliegende Außerbetriebnahmen lesbar bleiben; Balkenlängen über
eine solche Lücke sind nicht maßstäblich.

## Tastatur

Unter macOS wirkt Command wie Ctrl.

| Taste | Wo | Was |
|---|---|---|
| Entf / Rücktaste | Fallliste | gewählten Fall löschen (fragt vorher) |
| Entf / Rücktaste | Außerbetriebnahmen des Falls | gewählte aus dem Fall entfernen |
| Entf / Rücktaste | feste Hintergrund-Außerbetriebnahmen | aus dem festen Hintergrund entfernen |
| Entf / Rücktaste | Regeln | gewählte Regeln entfernen |
| Leertaste | Fallliste | Flag *Run* des fokussierten Falls umschalten |
| Leertaste | verfügbare Außerbetriebnahmen | fokussierte ankreuzen oder abwählen |
| Enter | verfügbare Außerbetriebnahmen | alle markierten dem Fall zuordnen |
| F2 / Enter | Fallliste | Fall direkt umbenennen |
| Ctrl+A | jede Tabelle | jede angezeigte Zeile markieren |
| Ctrl+N | Fenster | neuer Fall |
| Ctrl+F | Fenster | verfügbare Außerbetriebnahmen durchsuchen |
| Ctrl+S | Fenster | Konfiguration speichern |
| Ctrl+O | Fenster | gespeicherte Konfiguration laden |
| Ctrl+Enter | Fenster | Rechnung starten |
| Ctrl + / Ctrl − / Ctrl 0 | Fenster | Fenster für diese Sitzung zoomen |
| Escape | Fenster | eine direkte Bearbeitung beenden (in `main_qt.py` auch ein Filterfeld leeren), sonst abbrechen |

## Was ein Klick bewirkt

| Aktion | Wirkung |
|---|---|
| rechts einen Fall wählen | die Mitte zeigt seine Außerbetriebnahmen, links werden sie markiert; Beschreibung, Zeitleiste, Vorschau und Statuszeile folgen |
| links ankreuzen / abwählen | diese Außerbetriebnahme wird sofort dem gewählten Fall hinzugefügt oder aus ihm entfernt; eine feste wird mit Grund abgelehnt |
| *Add to case* / Enter | alle markierten werden zugeordnet; eine schon zugeordnete oder feste wird mit Grund abgelehnt |
| *Remove from case* / Entf in der Mitte | nur die Zuordnung endet; die Planned Outage in PowerFactory bleibt unberührt |
| *Details* / Doppelklick auf eine Außerbetriebnahme | was PowerFactory dazu hält (Objekt, Klasse, Betriebsmittel, Schalthandlungen, Fenster, Priorität, Status, Fälle, die sie nutzen) und ihre eigenen Termine in diesem Fall |
| *Set as fixed background* | die Außerbetriebnahme kommt in die Referenz und jeden Fall; abgelehnt, solange sie in einem Fall steht |
| *New* | legt *Case n* mit der nächsten freien ID an und wählt ihn |
| *Copy* | neue ID, Name *… (copy)*, dieselben Außerbetriebnahmen und eigenen Termine; völlig unabhängig |
| *Delete* | fragt einmal und entfernt nur den gewählten Fall |
| *One case per planned outage* | fragt, ersetzt dann alle Fälle durch je einen pro Außerbetriebnahme im simulierten Zeitraum, bis zur Fallgrenze; *Ignored* und feste erhalten keinen |
| *Show calculation preview* | öffnet oder schließt die schreibgeschützte Vorschau |
| *Apply settings* / *Save settings* / *Restore defaults* | prüft und übernimmt die Werte / speichert zusätzlich die Datei / entfernt jede Abweichung |
| *Save configuration* / *Load saved configuration* | schreibt / liest die Konfigurationsdatei des Projekts; *Load* fragt, bevor es die Anzeige ersetzt |
| *Cancel*, Escape, Fenster schließen | beendet den Lauf: nichts gerechnet, gespeichert oder veröffentlicht, nichts im Projekt geändert; der Abbruch wird an den Aufrufer weitergegeben |
| *Start calculation* | übernimmt bearbeitete Einstellungen, führt die Prüfungen unten aus, schließt das Fenster und übergibt die Konfiguration an GridLens |

## Prüfungen bei *Start calculation*

1. Jede Einstellung ist gültig; sonst öffnet sich die Seite *Settings* mit der
   Liste der Probleme, und nichts startet.
2. Die Bewertungen sind stimmig ((n-1)' nur mit n-1).
3. Die Konfiguration ist gültig (IDs, Pfade der Außerbetriebnahmen, Regeln,
   Termine).
4. Kann kein Fall gerechnet werden, fragt GridLens, ob nur die Referenz
   gerechnet werden soll.
5. Fälle, die nicht gerechnet werden können, werden mit Grund gelistet;
   GridLens fragt, ob es weitergehen soll, und berichtet sie als NOT EVALUATED
   oder NOT SIMULATED.

## Vorschau der Rechnung

*Show calculation preview* öffnet unter den Problemen eine schreibgeschützte,
scrollbare Zusammenfassung. Sie aktualisiert sich bei jeder Änderung und
nennt: die Ergebnisauswahl, die Bewertungen, den QDS-Zeitraum, die Referenz
(R0, Rfix oder aus), die festen Außerbetriebnahmen mit ihren Fenstern, den
Berichtsfilter, die Fehlerfälle im Umfang, die Regeln, die
Einstellungsabweichungen und für jeden bereiten Fall Name, Beschreibung,
Außerbetriebnahmen mit wirksamen Fenstern und ob er einen eigenen QDS-Lauf
erhält oder einen gleichen Fall wiederverwendet. Blockierte Fälle zeigen ihren
Grund, ausgeschlossene Fälle stehen getrennt. Die Vorschau rechnet nie.

## Woher die Fälle kommen

| `CASE_SOURCE` | Verhalten |
|---|---|
| `'gui'` (Standard) | das Fenster, vorbelegt mit der gespeicherten Konfiguration. Kann es nicht öffnen oder nicht aufgebaut werden: die gespeicherte Konfiguration; ohne sie je Außerbetriebnahme ein Fall. Der Bericht nennt die Quelle. |
| `'saved'` | die gespeicherte Konfiguration, ohne Fenster |
| `'per_outage'` | je Planned Outage im simulierten Zeitraum ein Fall, ohne Fenster, ohne Fallgrenze |

Konfigurationsdatei: `~/GridLens/cases/<Projekt>_<Hash>.v2.json` (Ordner
`CASE_CONFIG_DIR`). Sie enthält `cases` (jeweils `id`, `name`,
`description`, `enabled`, `outages`, `overrides`), `background`, `rules`,
`assessments` und `settings` (nur Abweichungen), mit Schema, Revision, Benutzer
und Zeit. Eine Datei mit mehr Fällen als die Grenze öffnet trotzdem, zeigt den
Zähler rot und den Grund, damit sich Fälle löschen lassen; Rechnen, Speichern
und `CASE_SOURCE = 'saved'` lehnen sie ab.

## Das Fenster ausprobieren, ohne zu rechnen

`ui/preview_case_manager.py` ist ein eigenes Skript mit einer eigenen Kopie
des Fallmanagers. Allein in ein ComPython eingefügt, öffnet es dasselbe
Fenster mit den echten Planned Outages des aktiven Projekts, nur lesend, und
gibt aus, was *Start calculation* übergeben würde, statt zu rechnen. Speichern
und Laden arbeiten auf einer temporären Kopie der Konfiguration. Nach einer
Änderung am Fallmanager in `main.py` aktualisiert
`python3 ui/sync_case_manager_copy.py` die Kopie; ein Test schlägt fehl, solange
sie veraltet ist.
