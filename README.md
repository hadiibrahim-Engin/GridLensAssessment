# GridLens Assessment

Python-Skript für DIgSILENT PowerFactory 2026: Planungsfälle über den bestehenden
Fallmanager auswählen, QDS und n-1 berechnen, Ergebnisse mit der Referenz
vergleichen und die Berichtstabellen an PowerFactory übergeben.

| Bestandteil | Version |
|---|---|
| Publisher (`gridlens_report.py`) | 8.0.1 |
| Berichtsvorlagen | 7.0.0 |
| Datenvertrag | 7.0, 38 Tabellen |
| Fallkonfiguration | Schema 2 |

## In PowerFactory einrichten

1. Ein Projekt und einen Studienfall aktivieren. `ComStatsim` mit Zeitraum,
   Zeitschritt und Ergebnisvariablen für Auslastungen und Spannungen konfigurieren.
2. [powerfactory/gridlens_report.py](powerfactory/gridlens_report.py) als
   `ComPython` ausführen. Für die Veröffentlichung der Tabellen muss das Skript
   unter dem zugehörigen `IntReport` liegen.
3. Im Fallmanager Freischaltungen, Referenz, Berechnungsarten und Netzfilter
   prüfen. Die Vorschau zeigt den Umfang vor dem Start.
4. Für jeden Bericht im Stimulsoft-Designer zuerst das `.dct`-Dictionary und
   danach die `.pg`-Seiten in Dateinamenreihenfolge importieren:
   [MASTER_GRIDLENS](powerfactory/pages/MASTER_GRIDLENS) und
   [MASTER_GRIDLENS_DETAIL](powerfactory/pages/MASTER_GRIDLENS_DETAIL).
5. Nach erfolgreicher Veröffentlichung den Bericht über `IntReport` erzeugen.
   Ein eigenständiger Skriptlauf berechnet und validiert die Tabellen; er
   veröffentlicht sie nicht. Das Skript rendert selbst kein PDF.

Die Laufzeit benötigt nur die Python-Standardbibliothek, das PowerFactory-Modul
und für den Fallmanager `tkinter`. Repository-Module und Entwicklungspakete
müssen auf dem PowerFactory-Rechner nicht installiert werden. Für n-1 verwendet
GridLens die Kontingenzanalyse des Studienfalls oder legt sie an, wenn keine
vorhanden ist. Mehrere vorhandene Analysen müssen vor dem Lauf bereinigt werden.

## Einstellungen und gespeicherte Ergebnisse

Die Standardeinstellungen stehen am Anfang des Skripts. Die GUI und die
gespeicherte Fallkonfiguration steuern die einzelnen Läufe. Fallkonfigurationen
liegen standardmäßig unter `~/GridLens/cases`; `CASE_CONFIG_DIR` überschreibt
diesen Ordner. Berechnete `ElmRes`-Kopien bleiben im Studienfall und tragen den
Präfix `GridLens_<Zeitstempel>_`.

8.0.1 berücksichtigt bei der Identität einer Referenz mit festen
Hintergrundfreischaltungen auch deren Zeitfenster. Solche Referenzen aus älteren
Versionen müssen neu berechnet werden. Gespeicherte Ergebnisse ohne lesbaren
Fingerabdruck werden ebenfalls zurückgewiesen. Eine Referenz ohne
Hintergrundfreischaltungen behält ihre bisherige Identität.

Konfigurationen werden zunächst in eine eigene temporäre Datei im selben Ordner
geschrieben, synchronisiert und anschließend atomar ersetzt. Ein fehlgeschlagenes
Ersetzen lässt die vorhandene Konfiguration und ihre Revision unverändert.

## Änderungen in 8.0.1

- Native n-1-Lesefehler bleiben in Vergleich, Abdeckung und Detailauswertung
  sichtbar. Ein fehlender Wert wird nicht als gemessene Null gewertet.
- Nicht aufgezeichnete Werte werden anhand der Aufzeichnungsgrenzen beider
  Vergleichsseiten geprüft. Unzureichender Nachweis bleibt `NOT_EVALUATED`.
- Ungültige oder doppelte Studienzeiten und Kontingenzzeilen werden abgelehnt.
  Kontingenzfilter entfernen auch unlesbare Zellen und zugehörige Metadaten.
- QDS-Referenzkennzahlen bleiben nach dem Freigeben der Zeitreihen erhalten.
- Neue Laufnamen berücksichtigen bereits vorhandene Ergebnisobjekte.
- Beschädigte Konfigurationen liefern verständliche Validierungsfehler.
- Die Einstellungen im Fallmanager bleiben bei normalem Zoom scrollbar und
  erreichbar; die vorhandene Fensterstruktur und Gestaltung bleiben erhalten.
- Auch eigenständige Läufe prüfen den Datenvertrag vor der Erfolgsmeldung.

QDS-Zeitraster, Berechnungsaufrufe, Grenzwertvorgaben, Statuscodes und der
Berichtsdatenvertrag bleiben erhalten. Die Korrekturen können die Auswertung
betroffener Fehlerfälle ändern: insbesondere werden unbelegte Ergebnisse nicht
mehr als unauffällig gezählt.

## Entwicklung und Prüfung

Für die lokale Prüfung wird Python 3.11 mit funktionsfähigem Tk verwendet.
Die Entwicklungspakete sind in `requirements-dev.txt` festgelegt:

```sh
python3.11 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
```

Die GUI-Tests öffnen echte Tk-Fenster und benötigen eine grafische Sitzung.
PowerFactory-Aufrufe werden in den automatischen Tests nachgebildet. Die Suite
prüft außerdem beide Berichtssätze gegen den Datenvertrag und führt ihre
SQL-Abfragen gegen erzeugte Berichtstabellen aus.

Prüfstand 27. Oktober 2026: **684 Tests bestanden**, einschließlich aller
**42 GUI-Tests** mit echten Tk-Fenstern.

Nach Änderungen am Fallmanager dessen eigenständige Testkopie aktualisieren:

```sh
.venv/bin/python tools/sync_case_manager_copy.py
.venv/bin/python tools/sync_case_manager_copy.py --check
```

## Einsatzgrenzen und Abnahme

Die Änderungen von 8.0.1 müssen noch mit einer echten PowerFactory-2026-Sitzung
unter Windows abgenommen werden. Dazu gehören ein vollständiger QDS-/n-1-Lauf,
ein abgebrochener Lauf mit Prüfung der wiederhergestellten Einstellungen,
die erneute Auswertung gespeicherter Ergebnisse und das Rendern beider Berichte.
Die automatischen Tests ersetzen diese Integrationsabnahme nicht.

Bestehende fachliche Grenzen bleiben bestehen: Eigene Zeitüberschreibungen für
Freischaltungen sind deaktiviert. Die Betriebsmittel eines Planungsfalls werden
fallweit als freigeschaltet behandelt; bei mehreren unterschiedlichen
Freischaltungsfenstern ist das bei der Interpretation zu berücksichtigen.
Native n-1-Ergebnisse werden für die Auswertung vollständig eingelesen; große
Modelle müssen deshalb auf Speicherbedarf und Laufzeit geprüft werden.
Tabellenbegrenzungen werden im Bericht ausgewiesen; die vollständigen
Statistiken werden vor der Begrenzung berechnet.

Die älteren Dokumente in [docs](docs) beschreiben die Fachlogik und frühere
Entwicklungsstände. Angaben zu alten MRT-Dateien, Generatoren und Testzahlen
sind historisch; für den aktuellen Lieferumfang und Betrieb gilt diese README.
