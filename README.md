# GridLens Assessment

GridLens ist ein Python-Skript für DIgSILENT PowerFactory. Über den Fallmanager
werden Planungsfälle ausgewählt, QDS- und n-1-Berechnungen ausgeführt und die
Ergebnisse mit einer Referenz verglichen. Die Auswertung wird als Bericht an
PowerFactory übergeben.

## In PowerFactory einrichten

1. Ein Projekt und einen Studienfall aktivieren. `ComStatsim` mit Zeitraum,
   Zeitschritt und Ergebnisvariablen für Auslastungen und Spannungen konfigurieren.
2. [powerfactory/gridlens_report.py](powerfactory/gridlens_report.py) als
   `ComPython` ausführen. Für die Veröffentlichung der Tabellen muss das Skript
   unter dem zugehörigen `IntReport` liegen.
3. Im Fallmanager Freischaltungen, Referenz, Berechnungsarten und Netzfilter
   prüfen. Die Vorschau zeigt den Umfang vor dem Start.
4. Im Stimulsoft-Designer für jeden Bericht zuerst das `.dct`-Dictionary und
   danach die `.pg`-Seiten in Dateinamenreihenfolge importieren:
   [MASTER_GRIDLENS](powerfactory/pages/MASTER_GRIDLENS) und
   [MASTER_GRIDLENS_DETAIL](powerfactory/pages/MASTER_GRIDLENS_DETAIL).
5. Nach erfolgreicher Veröffentlichung den Bericht über `IntReport` erzeugen.

Die Laufzeit benötigt die Python-Standardbibliothek, das PowerFactory-Modul
und für den Fallmanager `tkinter`. Die Entwicklungspakete werden nur für die
Tests benötigt. Ein eigenständiger Skriptlauf berechnet und validiert die
Tabellen, veröffentlicht sie aber nicht. Das PDF wird über PowerFactory erzeugt.

## Konfiguration und Ergebnisse

Die Standardeinstellungen stehen am Anfang des Skripts. Die GUI und die
Fallkonfiguration steuern die einzelnen Läufe. Konfigurationen liegen
standardmäßig unter `~/GridLens/cases`; `CASE_CONFIG_DIR` überschreibt diesen
Ordner. Berechnete `ElmRes`-Kopien bleiben im Studienfall und tragen den Präfix
`GridLens_<Zeitstempel>_`.

Bei der erneuten Auswertung werden die Fingerabdrücke der gespeicherten
Ergebnisse geprüft. Fehlende oder abweichende Fingerabdrücke erfordern eine
Neuberechnung. Bei festen Hintergrundfreischaltungen gehört auch deren
Zeitfenster zur Identität der Referenz.

## Tests ausführen

Die virtuelle Umgebung wird manuell im übergeordneten Verzeichnis erstellt:

```text
nahriva_works/
├── .venv/
└── GridLensAssessment/
    ├── run_tests.ps1
    ├── requirements-dev.txt
    └── tests/
```

Die Entwicklungsabhängigkeiten werden ebenfalls manuell installiert. Unter
Windows, aus dem Projektverzeichnis:

```powershell
..\.venv\Scripts\python.exe -m pip install -r .\requirements-dev.txt
```

Anschließend die Tests über PowerShell starten:

```powershell
.\run_tests.ps1
.\run_tests.ps1 -PyQtOnly
.\run_tests.ps1 -PytestArgs @('-k', 'n1', '--maxfail=1')
```

Der Runner verwendet ausschließlich `../.venv`. Er erstellt keine Umgebung und
installiert keine Pakete. Der Aufruf funktioniert auch aus einem anderen
Arbeitsverzeichnis; der Rückgabecode von pytest wird übernommen.

Die Tk-GUI-Tests benötigen Tcl/Tk und eine grafische Sitzung. Für `-PyQtOnly`
muss PyQt in der virtuellen Umgebung installiert sein. Im vollständigen Lauf
wird der optionale PyQt-GUI-Test ohne PyQt übersprungen; `-PyQtOnly` meldet die
fehlende Abhängigkeit.

Unter macOS und Linux kann dieselbe Umgebung direkt verwendet werden:

```sh
../.venv/bin/python -m pip install -r requirements-dev.txt
../.venv/bin/python -m pytest -q
```

Die Tests prüfen die Fachlogik mit nachgebildeten PowerFactory-Aufrufen, die
GUI-Bedienung und beide Berichtssätze gegen den Datenvertrag. Sie ersetzen
keine Integrationsprüfung in PowerFactory.

Nach Änderungen am Fallmanager dessen eigenständige Testkopie aktualisieren:

```powershell
..\.venv\Scripts\python.exe tools/sync_case_manager_copy.py
..\.venv\Scripts\python.exe tools/sync_case_manager_copy.py --check
```

## PyQt-Testfenster

[tools/testPYQt.py](tools/testPYQt.py) kann als vollständiges Skript in einem
`ComPython` gestartet werden. Die GUI läuft bei jedem Aufruf in einem eigenen
Python-Prozess. Das Skript installiert keine Pakete; PyQt muss im verwendeten
Interpreter vorhanden sein. Bei Bedarf wird dessen Pfad über
`PYTHON_EXECUTABLE` gesetzt. Protokolle liegen unter `~/GridLens/logs`.

## Einsatzgrenzen

Vor dem produktiven Einsatz sind vollständige Berechnungsläufe, die
Wiederherstellung der Einstellungen nach Abbruch, die erneute Auswertung
und das Rendern beider Berichte in PowerFactory zu prüfen.

Eigene Zeitüberschreibungen für Freischaltungen sind deaktiviert. Die
Betriebsmittel eines Planungsfalls werden fallweit als freigeschaltet behandelt;
bei unterschiedlichen Freischaltungsfenstern ist das bei der Interpretation
zu berücksichtigen. Native n-1-Ergebnisse werden vollständig eingelesen;
Speicherbedarf und Laufzeit sind deshalb am verwendeten Modell zu prüfen.
Tabellenbegrenzungen werden im Bericht ausgewiesen. Die vollständigen
Statistiken werden vor der Begrenzung berechnet.

Weitere Informationen zur Fachlogik stehen in [docs](docs). Die dortigen
Entwurfs- und Migrationsdokumente enthalten auch historische Entwicklungsstände.
