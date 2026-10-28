# CI-Sicherheit und Desktop-Testumgebung

Die Repository-Konfiguration und die Azure-DevOps-Berechtigungen bilden
gemeinsam den Schutz der Pipeline. Die folgenden Azure-Einstellungen sind
Einrichtungsschritte; sie wurden durch Änderungen an diesem Repository nicht
im Azure-Projekt gesetzt oder überprüft.

## Geprüfte lokale Eigenschaften

- `azure-pipelines.yml` führt Tests ohne Desktop-Interaktion auf einem frischen
  Microsoft-gehosteten Windows-Agent aus. Branches und PRs erhalten keine
  in der YAML referenzierten geheimen Variablen, Secure Files oder Service
  Connections. Bereits im Azure-Projekt konfigurierte Freigaben müssen separat
  überprüft werden.
- Beide Schritte für Paketbau und Veröffentlichung verlangen einen erfolgreichen
  Lauf, `Build.SourceBranch == refs/heads/main` und einen Laufgrund ungleich
  `PullRequest`. Das Artefakt ist ein Release-Kandidat; es gibt keine automatische
  Installation in PowerFactory und keine automatische Desktop-Abnahme.
- `persistCredentials: false` verhindert, dass der Checkout sein OAuth-Token
  für spätere Git-Befehle in der Git-Konfiguration hinterlässt. Das begrenzt
  nicht alle Rechte des Build-Service-Kontos.
- Die Abhängigkeitsgruppe `dev` in `pyproject.toml` (PEP 735) pinnt direkte und
  transitive Abhängigkeiten für Python 3.11 auf exakte Versionen, einschließlich
  `colorama` unter Windows. Die Installation (`pip install --group dev`, pip 25.1
  oder neuer) verwendet ausschließlich Wheels. Eine Abhängigkeitsgruppe kann
  keine SHA-256-Hashes tragen: Anders als die frühere `requirements-dev.txt` mit
  `--require-hashes` prüft die CI die Dateien nicht mehr gegen festgelegte Hashes,
  sondern vertraut dem Paketindex für die gepinnte Version. Bei Paketupdates die
  Installation in einer frischen Umgebung testen. Siehe
  [pip: Secure installs](https://pip.pypa.io/en/stable/topics/secure-installs/).
- `ui/build_release.py` liest die Lieferdateien aus einer begrenzten
  Dateiauswahl, verweigert Symlinks auf Lieferdateien und aufgelöste Pfade außerhalb
  des Repositorys und erzeugt Manifest und SHA-256-Prüfsummen. Die Version wird
  mittels AST und `literal_eval` gelesen. Die Laufzeitskripte werden dabei nicht
  ausgeführt. Die Git-Aufrufe verwenden Argumentlisten ohne Shell. In der CI
  verlangt `--require-clean` zusätzlich eine unveränderte Arbeitskopie.
- `ui/sync_case_manager_copy.py --check` vergleicht den gespeicherten Block
  mit dem aus dem AST erzeugten Text. Dieser Aufruf schreibt keine Kopie neu
  und führt den gelesenen PowerFactory-Code nicht aus.
- Zeilen- und Verzweigungsabdeckung sind in `pyproject.toml` aktiviert;
  zusätzlich setzt die Pipeline `--cov-branch`. Fehlende Test- und
  Coverage-Berichte lassen die jeweiligen Veröffentlichungsschritte scheitern.

## Schutz in Azure DevOps einrichten

1. Unter **Repos → Branches → main → Branch policies** erfolgreiche automatische
   Build-Validierung und einen verpflichtenden Review verlangen. Direkte Pushes,
   Force-Pushes und das Umgehen von Policies auf den erforderlichen Personenkreis
   beschränken. Änderungen an YAML, Requirements und Build-Werkzeugen besonders
   prüfen: Wer die YAML ändern kann, kann auch ihre Bedingungen ändern.
2. Unter **Organization settings → Pipelines → Settings**, alternativ auf
   Projektebene, **Limit job authorization scope to current project for
   non-release pipelines** und **Protect access to repositories in YAML
   pipelines** aktivieren. Berechtigungen des projektspezifischen Build-Service
   auf die tatsächlich erforderlichen Repositorys und Aktionen begrenzen.
   Siehe [Microsoft: Job access tokens](https://learn.microsoft.com/en-us/azure/devops/pipelines/process/access-tokens?view=azure-devops).
3. Rechte zum Bearbeiten und Starten von Pipelines, Variablengruppen, Service
   Connections und Agent-Pools prüfen. Keine Geheimnisse oder privilegierten
   Ressourcen für nicht vertrauenswürdige PR- oder Branch-Läufe freigeben.
   Kein `System.AccessToken` als Umgebungsvariable an die Tests übergeben.
4. Einen späteren Deployment-Prozess separat schützen. Seine Ressourcen müssen
   den erlaubten Branch und dessen Schutz außerhalb der veränderbaren YAML
   kontrollieren. Die bloße Erzeugung eines ZIPs ist keine Produktionsfreigabe.

## Separate Desktop-Pipeline aktivieren

Die Tk-Tests rufen unter anderem `focus_force()` und `event_generate()` auf.
Ein erfolgreicher `Tk()`-Aufruf allein belegt dafür keine geeignete Umgebung.
Microsoft unterstützt sichtbare UI-Tests auf gehosteten Agents nicht; dafür
ist ein interaktiv gestarteter Windows-Agent erforderlich.
Siehe [Microsoft: UI testing considerations](https://learn.microsoft.com/en-us/azure/devops/pipelines/test/ui-testing-considerations?view=azure-devops).

1. Einen isolierten Windows-Testrechner oder eine dafür vorgesehene VM mit
   Python 3.11 und Tk bereitstellen. Der Rechner enthält keine produktiven
   Zugangsdaten oder Projekte und sollte aus einem bekannten Zustand
   wiederherstellbar sein. Den Azure-Agent interaktiv starten, nicht als
   Windows-Dienst. Eine aktive Desktop-Sitzung für Fokus- und Tastaturtests
   sicherstellen.
2. Den Pool **GridLens-GUI** einrichten und dem Agent die benutzerdefinierte
   Capability **GridLensInteractive=true** geben. Diese Capability ist eine
   administrative Kennzeichnung; die Pipeline prüft zusätzlich tatsächlich
   den Fensterfokus.
3. **Vor dem ersten Lauf** die Pipelineberechtigungen des Pools auf die neue
   Desktop-Pipeline begrenzen, offenen Zugriff für alle Pipelines deaktivieren
   und unter **Approvals and checks → Branch control** ausschließlich
   `refs/heads/main` erlauben. Branch-Schutz verlangen und bei unbekanntem
   Schutzstatus ablehnen. Diese Prüfung ist außerhalb der YAML gespeichert.
   Siehe [Microsoft: Branch control](https://learn.microsoft.com/en-us/azure/devops/pipelines/process/approvals?view=azure-devops#branch-control).
4. Eine neue Pipeline mit `/azure-pipelines-gui.yml` anlegen. Sie hat keine
   Push- oder PR-Trigger. Startrechte auf vertrauenswürdige Benutzer begrenzen
   und nur den geschützten `main` auswählen. Die YAML-Bedingung allein schützt
   den privaten Agent nicht gegen eine veränderte Pipeline-Datei.
5. Vor einer fachlichen Freigabe den GUI-Lauf und den Hosted-Lauf anhand der
   vollständigen Commit-ID dem gleichen Kandidaten zuordnen. Die GUI-Pipeline
   veröffentlicht ihre Ergebnisse separat und erzeugt kein Release-Artefakt.
   Der PyQt-Smoke-Test benötigt zusätzlich ein separat verwaltetes PyQt-Paket;
   die normale Tk-Abnahme erfordert dieses nicht. Native PowerFactory-Prüfungen
   bleiben ein weiterer Abnahmeschritt.
