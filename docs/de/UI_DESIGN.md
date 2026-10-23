# GridLens – Desktop-Oberfläche

Die Oberfläche bleibt Teil der bestehenden `CaseManagerDialog`-Klasse in
`powerfactory/gridlens_report.py`. Sie verwendet Tkinter und `ttk.Style` ohne
zusätzliche Bibliothek. `FilterTable` und `Tooltip` teilen das Designsystem.
Fachliche Einstellungen, Dateiformate und PowerFactory-Berechnungen gehören
weiterhin zur bestehenden Fachlogik.

## Fenster und Bedienung

- Die Kopfzeile zeigt Marke, Version und den aktuellen Hauptbereich.
- Case Manager: drei verschiebbare Tabellenbereiche, darunter die Timeline
  über die volle Breite, anschließend Calculation und Problems and warnings.
- Settings: alle sieben bestehenden Bereiche als seitliche Tabs gleicher Breite.
- Netzbereiche können nach Namen gesucht werden. Ausgeblendete Auswahlen
  bleiben erhalten. „Select all grids“ und „Clear selection“ betreffen weiterhin
  die vollständige Auswahl, unabhängig vom Suchtext.
- Schmale Tabellen scrollen horizontal; Spaltenüberschriften und Filter folgen
  den Daten. Leere Tabellen und Listen zeigen einen verständlichen Leerzustand.
- Inhalte scrollen bei Platzmangel. Statuszeile und Hauptaktionen bleiben im
  Fenster sichtbar; Aktionsleisten brechen bei Bedarf um.
- Die normale Größenänderung des Betriebssystemfensters bleibt verfügbar.

## Zoom ausschließlich über die Tastatur

| Aktion | Windows / Linux | Zusätzlich auf macOS |
|---|---|---|
| Vergrößern | Strg + Plus oder Strg + Gleichheitszeichen | ⌘ + Plus / Gleichheitszeichen |
| Verkleinern | Strg + Minus | ⌘ + Minus |
| Zurück auf 100 % | Strg + 0 | ⌘ + 0 |

Auch die Plus- und Minus-Tasten des Ziffernblocks werden unterstützt.
Zoomstufen: 75, 90, 100, 110, 125, 150, 175 und 200 Prozent.
Es gibt keine sichtbare Zoomleiste und keine Zoombelegung des Mausrads.
Der Zoom gilt nur für das aktuelle Fenster und wird nicht in der fachlichen
Konfiguration gespeichert. Schriftgrößen, Tabellenzeilen und Filterhöhen
berücksichtigen zusätzlich die vorhandene Tk-/Betriebssystem-Skalierung.

## Designsystem

| Verwendung | Farbe |
|---|---|
| Hintergrund | `#F3F7FA` |
| Inhaltsflächen | `#FFFFFF` |
| Primärfarbe | `#087F9C` |
| Kopfzeile | `#16384F` |
| Text / Sekundärtext | `#203449` / `#64788B` |
| Rahmen | `#DCE5EC` |
| Auswahl | `#E5F3FA` |
| Warnung / Fehler / Erfolg | `#D97706` / `#DC3545` / `#16835D` |

Die Schrift wird aus vorhandenen Systemschriften gewählt, bevorzugt Segoe UI,
SF Pro Text oder Helvetica Neue. Gemeinsam verwendete Tk-Schriftobjekte erlauben
den Zoom ohne Neuaufbau der Oberfläche oder Verlust von Eingaben und Auswahlen.

## Wartung und Prüfung

Nach Änderungen die eigenständige PowerFactory-GUI-Testkopie synchronisieren:

```sh
.venv/bin/python tools/sync_case_manager_copy.py
.venv/bin/python -m pytest -q
```

Die GUI-Tests benötigen eine echte Tk-Desktop-Sitzung. Sie prüfen unter anderem
Filter, Auswahl, Fallbearbeitung, Validierung, Konfigurationen, Netzsuche,
Tastaturzoom und Fenstergrößen von 1000 × 620 bis 1920 × 1080.
Die Demovorschau ersetzt keinen Integrationstest im installierten PowerFactory.
