# Outage Assessment Assessment

Outage Assessment ist ein Python-Skript für DIgSILENT PowerFactory 2026. Im Fallmanager
werden Planungsfälle aus Planned Outages zusammengestellt; Outage Assessment rechnet je
Fall eine quasi-dynamische Simulation (QDS) und auf Wunsch die Contingency
Analysis (n-1), vergleicht jeden Fall zum selben Zeitschritt mit einer Referenz
und übergibt die Auswertung als Tabellen an einen PowerFactory-Bericht
(Haupt- und Detailbericht).

Das Ergebnis ist eine technische Vorprüfung, keine Freigabe einer
Außerbetriebnahme und kein Nachweis für n-1-Sicherheit, Versorgungssicherheit,
Schutzkoordination oder sichere elektrische Trennung.

## Dokumentation

| Dokument | Inhalt |
|---|---|
| [docs/de/ARCHITEKTUR.md](docs/de/ARCHITEKTUR.md) | wie das Werkzeug arbeitet: Voraussetzungen, die sieben Schritte eines Laufs, was in PowerFactory geändert und zurückgesetzt wird, Planungsfälle, Bewertung, n-1, Einstellungen, Fehlerbehandlung |
| [docs/de/FALLMANAGER.md](docs/de/FALLMANAGER.md) | Bedienung des Fallmanager-Fensters |
| [docs/de/BERECHNUNG_UND_AUSWERTUNG.md](docs/de/BERECHNUNG_UND_AUSWERTUNG.md) | Formeln und Regeln der Bewertung im Detail |
| [docs/de/POWERFACTORY.md](docs/de/POWERFACTORY.md) | jedes PowerFactory-Objekt und -Attribut, das Outage Assessment liest oder schreibt |
| [docs/de/BERICHTSTABELLEN.md](docs/de/BERICHTSTABELLEN.md) | die 38 Berichtstabellen, ihre Felder und Kapitel |
| [docs/de/STOLPERSTELLEN.md](docs/de/STOLPERSTELLEN.md) | Stolperstellen aus echten Läufen (Ausbaustufen, QDS-Zeitraum, fehlende Werte, Ergebnisobjekte, Berichtsengine) und wie das Tool sie behandelt |

Englische Fassungen stehen unter [docs/](docs).

## In PowerFactory einrichten

1. Ein Projekt und einen Studienfall aktivieren. `ComStatsim` mit Zeitraum,
   Zeitschritt und Ergebnisvariablen für Auslastungen und Spannungen konfigurieren.
2. [outage-assessment/main.py](outage-assessment/main.py) als
   `ComPython` ausführen. Für die Veröffentlichung der Tabellen muss das Skript
   unter dem zugehörigen `IntReport` liegen.
3. Im Fallmanager Freischaltungen, Referenz, Berechnungsarten und Netzfilter
   prüfen. Die Vorschau zeigt den Umfang vor dem Start.
4. Im Stimulsoft-Designer für jeden Bericht zuerst das `.dct`-Dictionary und
   danach die `.pg`-Seiten in Dateinamenreihenfolge importieren:
   [MASTER_OUTAGE_ASSESSMENT](designer-pages/MASTER_OUTAGE_ASSESSMENT) und
   [MASTER_OUTAGE_ASSESSMENT_DETAIL](designer-pages/MASTER_OUTAGE_ASSESSMENT_DETAIL).
5. Nach erfolgreicher Veröffentlichung den Bericht über `IntReport` erzeugen.

Die Laufzeit benötigt die Python-Standardbibliothek, das PowerFactory-Modul
und für den Fallmanager `tkinter`. Statt `main.py` lässt sich
[outage-assessment/main_qt.py](outage-assessment/main_qt.py) verwenden: gleiche
Rechnung, Fallmanager in PyQt6 oder PyQt5 (`QT_BINDING`), PyQt muss dann in der
Python-Umgebung von PowerFactory installiert sein. Die Entwicklungspakete werden
nur für die Tests benötigt. Ein eigenständiger Skriptlauf berechnet und
validiert die Tabellen, veröffentlicht sie aber nicht. Das PDF wird über
PowerFactory erzeugt.

## Konfiguration und Ergebnisse

Die Standardeinstellungen stehen am Anfang des Skripts. Die GUI und die
Fallkonfiguration steuern die einzelnen Läufe. Konfigurationen liegen
standardmäßig unter `~/OutageAssessment/cases`; `CASE_CONFIG_DIR` überschreibt diesen
Ordner. Berechnete `ElmRes`-Kopien bleiben im Studienfall und tragen den Präfix
`OA_<Zeitstempel>_`.

Bei der erneuten Auswertung werden die Fingerabdrücke der gespeicherten
Ergebnisse geprüft. Fehlende oder abweichende Fingerabdrücke erfordern eine
Neuberechnung. Bei festen Hintergrundfreischaltungen gehört auch deren
Zeitfenster zur Identität der Referenz.

## Tests ausführen

Die Qt-Oberfläche lässt sich ohne PowerFactory mit fiktiven Freischaltungen öffnen:

```sh
.venv/bin/python -m pip install PyQt6
./show_gui.sh
```

Der Launcher verwendet bevorzugt `.venv` im Projekt oder im übergeordneten
Verzeichnis. Mit `OUTAGE_ASSESSMENT_PYTHON=/pfad/zu/python ./show_gui.sh`
lässt sich ein anderer Interpreter mit PyQt6 oder PyQt5 wählen.
Die Vorschau startet keine Berechnung; gespeicherte Vorschau-Konfigurationen
liegen nur in einem temporären Ordner und werden beim Schließen entfernt.

Die virtuelle Umgebung wird manuell im übergeordneten Verzeichnis erstellt:

```text
nahriva_works/
├── .venv/
└── Outage AssessmentAssessment/
    ├── outage-assessment/   main.py (tkinter), main_qt.py (PyQt), __init__.py
    ├── designer-pages/      MASTER_OUTAGE_ASSESSMENT, MASTER_OUTAGE_ASSESSMENT_DETAIL (.dct + .pg)
    ├── powerfactory_tests/  manuelle Proben und Prüfskripte für PowerFactory
    ├── tests/               automatische Tests (pytest)
    ├── ui/                  Fallmanager-Vorschau, Sync- und Render-Skripte
    ├── pyproject.toml       Testwerkzeuge (Gruppe dev), pytest, Ruff
    └── run_tests.ps1
```

Die Testwerkzeuge stehen als Gruppe `dev` in [pyproject.toml](pyproject.toml),
ohne feste Versionen (pip 25.1 oder neuer):

```powershell
..\.venv\Scripts\python.exe -m pip install --upgrade pip
..\.venv\Scripts\python.exe -m pip install --group dev
```

Anschließend die Tests über PowerShell starten:

```powershell
.\run_tests.ps1
.\run_tests.ps1 -NoGui
.\run_tests.ps1 -GuiOnly
.\run_tests.ps1 -PyQtOnly
.\run_tests.ps1 -PytestArgs @('-k', 'n1', '--maxfail=1')
```

Der Runner verwendet ausschließlich `../.venv`. Er erstellt keine Umgebung und
installiert keine Pakete. Der Aufruf funktioniert auch aus einem anderen
Arbeitsverzeichnis; der Rückgabecode von pytest wird übernommen.

Alle Tests laufen ohne Benutzereingaben. Azure CI führt für Tk und Qt die
Fachlogik mit `-m "not gui"` aus und protokolliert jeden Testnamen. In diesen
Tests darf kein natives GUI-Fenster geöffnet werden. Unerwartete Eingabe-,
Dateiauswahl- und Meldungsdialoge führen in allen Tests sofort zu einem Fehler,
auch ohne `gui`-Markierung. Erwartete Antworten müssen die Tests selbst vorgeben.
Auch der normale lokale Testlauf öffnet keine Fenster: Native GUI-Tests werden
standardmäßig übersprungen. Sie müssen mit `-GuiOnly`, `-PyQtOnly` oder bei
direktem pytest-Aufruf mit `--run-gui` ausdrücklich aktiviert werden.

`-GuiOnly` prüft die Tk-Oberfläche getrennt mit automatisierten Aktionen;
ein Klick durch einen Menschen ist auch hier nicht vorgesehen. Ein nicht
automatisierter Tk-Ereignisloop wird abgewiesen, angelegte Tk-Fenster werden
am Testende geschlossen. Jeder Test hat standardmäßig 60 Sekunden Zeit. Bei
einem blockierten Test beendet der Watchdog den gesamten pytest-Prozess mit
einem Stacktrace. Die Grenze lässt sich mit `-GuiTimeoutSeconds 120` anpassen.

Die Tk-GUI-Tests benötigen Tcl/Tk und eine grafische Sitzung. Für `-PyQtOnly`
muss PyQt in der virtuellen Umgebung installiert sein. Die GUI-Aktionen werden
vom Testcode ausgeführt; es sind keine manuellen Eingaben erforderlich.

Unter macOS und Linux:

```sh
../.venv/bin/python -m pip install --upgrade pip
../.venv/bin/python -m pip install --group dev
../.venv/bin/python -m pytest -q
```

Die Tests prüfen die Fachlogik mit nachgebildeten PowerFactory-Aufrufen und
beide Berichtssätze gegen den Datenvertrag. Die ausdrücklich aktivierten
GUI-Tests prüfen zusätzlich die Bedienung. Ob `main.py` in
PowerFactory seine Aufgabe erfüllt, zeigt der Einsatz dort; Probleme werden
gemeldet und behoben.

Nach Änderungen am Fallmanager dessen eigenständige Kopie aktualisieren (ein
Test schlägt sonst fehl):

```powershell
..\.venv\Scripts\python.exe ui/sync_case_manager_copy.py
```

## Azure DevOps CI

Die [azure-pipelines.yml](azure-pipelines.yml) prüft die Qualität, mehr nicht:
bei Pushes auf `main` und bei Pull Requests (Änderungen nur an `docs/` oder
`.md`-Dateien starten keinen Lauf) installiert sie auf einem
Microsoft-gehosteten Windows-Agent mit Python 3.11 die Gruppe `dev`, führt Ruff
aus und danach die Tests ohne Desktop (`-m "not gui"`), je einmal für
`main.py` (`OUTAGE_ASSESSMENT_TEST_RUNTIME=tk`) und `main_qt.py` (`qt`). Die
Ergebnisse erscheinen im Reiter **Tests** des Laufs. Es entstehen keine
Artefakte und keine Dateien im Repository. Die Python-Version steht als
Variable `pythonVersion` am Anfang der YAML.

Ruff prüft mit den Regeln `E9`, `F63`, `F7` und `F82` Syntaxfehler, fehlerhafte
Kontrollstrukturen und undefinierte Namen.

Einrichtung in Azure DevOps: unter **Pipelines → New pipeline** das Repository
und **Existing Azure Pipelines YAML file** mit `/azure-pipelines.yml` wählen.
Bei **Azure Repos Git** die Pipeline zusätzlich unter **Branch policies → Build
validation** für `main` eintragen; der YAML-`pr`-Trigger gilt nur für GitHub
und Bitbucket Cloud.

## Hilfsskripte für PowerFactory

Diese Skripte gehören nicht zur Auslieferung. Jedes wird vollständig in ein
eigenes `ComPython` eingefügt; ihre Ausgabe nennt Projektdaten und ist nur
lokal zu verwenden (Ausnahme: `inspect_contingency_interface.py`).

| Skript | Zweck |
|---|---|
| [ui/preview_case_manager.py](ui/preview_case_manager.py) | öffnet den Fallmanager mit den echten Planned Outages, nur lesend, und zeigt, was übergeben würde |
| [powerfactory_tests/preview_pyqt_dialog.py](powerfactory_tests/preview_pyqt_dialog.py) | prüft, ob ein PyQt-Fenster aus PowerFactory startet (eigener Prozess; `PYTHON_EXECUTABLE`, Protokolle unter `~/OutageAssessment/logs`) |
| [powerfactory_tests/inspect_planned_outages.py](powerfactory_tests/inspect_planned_outages.py) | zeigt, wie PowerFactory Planned Outages abbildet |
| [powerfactory_tests/inspect_network_scope.py](powerfactory_tests/inspect_network_scope.py) | zeigt, welche Elemente der Netzfilter bewertet und auslässt |
| [powerfactory_tests/inspect_result_data.py](powerfactory_tests/inspect_result_data.py) | liest ein `ElmRes` vollständig aus ([docs/RESULT_EXPLORER.md](docs/RESULT_EXPLORER.md)) |
| [powerfactory_tests/check_qds_recording.py](powerfactory_tests/check_qds_recording.py) | zeigt, wo die QDS ihre Variablen aufzeichnet |
| [powerfactory_tests/inspect_qds_period.py](powerfactory_tests/inspect_qds_period.py) | zeigt, welchen QDS-Zeitraum Outage Assessment liest und aus welchem `ComStatsim` |
| [powerfactory_tests/inspect_contingency_interface.py](powerfactory_tests/inspect_contingency_interface.py) | beschreibt die Contingency-Schnittstelle ohne Projektdaten |
| [powerfactory_tests/run_contingency_checks.py](powerfactory_tests/run_contingency_checks.py) | rechnet eine kleine Contingency Analysis auf einer Projektkopie; standardmäßig aus |
| [powerfactory_tests/benchmark_report_writes.py](powerfactory_tests/benchmark_report_writes.py) | misst, wie schnell ein `IntReport` Zellen schreibt |

## Grenzen der Aussage

- Eigene Termine je Außerbetriebnahme werden erfasst, aber nicht angewendet;
  ein solcher Fall wird NOT EVALUATED berichtet.
- Bei n-1 gelten die Betriebsmittel eines Planungsfalls für den ganzen Fall als
  freigeschaltet; bei unterschiedlichen Fenstern ist das bei der Interpretation
  zu berücksichtigen.
- n-1-Ergebnisse werden vollständig eingelesen; Speicherbedarf und Laufzeit
  hängen vom Modell ab.
- Tabellenbegrenzungen werden im Bericht ausgewiesen; die Statistik wird vor
  der Begrenzung berechnet.
- Das Spannungsband 0,95–1,05 p.u. ist ein Vorschlag und für das Netz zu
  bestätigen.
- Was in PowerFactory noch nicht in einem echten Lauf bestätigt ist, steht in
  [docs/de/ARCHITEKTUR.md, Abschnitt 15](docs/de/ARCHITEKTUR.md#15-worauf-in-powerfactory-zu-achten-ist).
