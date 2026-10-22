# GridLens Case Manager – Operating Guide

German version: [de/FALLMANAGER.md](de/FALLMANAGER.md)

The case manager is the window GridLens opens when the ComPython runs
(`CASE_SOURCE = 'gui'`). It only **configures** the calculation. It shows no
results: results, violations and charts are in the PDF report that the
existing GridLens publication produces after the calculation. PowerFactory
waits while the window is open; nothing is calculated or changed before
**Start calculation**.

Technology: `tkinter` / `ttk` of the Python that PowerFactory runs, styled
with `ttk.Style` (theme `clam`); `tk.Canvas` only for the timeline. No other
package.

## Layout

The window opens centred at about 86 % of the screen (at most 1480 × 860, never larger than the screen).
Three tabs; a status line and the action bar stay visible on every tab:

```
 [ Workspace ] [ Fixed background & rules ] [ Review & start (1) ]
+--------------------------------------+------------------------------------+------------------------+
| Available planned outages            | Case A - Summer measures           | Planning cases  2 of 5 |
| In case  Planned outage Equip. Start | 2 case outages · 1 fixed backgr.   | Planning case Outg Stat|
| [All  v][            ][     ][     ] | Planned outage Equip. Start End Pr | [            ][  ][ v ]|
| ☑ in case FS Bedarf 1 NE_L1  ...     | [          ][     ][    ][   ][  ] | Summer         2  ready|
| ☐       FS Bedarf 3    NE_L7  ...    | FS Bedarf 1    NE_L1  ...          | North-east     1  ready|
| fixed   FS Hintergrund NE_L5  ...    | FS Bedarf 2    NE_L2  ...          | 4 shown                |
| 48 shown                             | 2 shown                            | [New][Copy][Delete]    |
|                                      | [Remove from case] [Details]       | Selected case          |
| [Add to case] [Set as fixed] [Det.]  | Timeline of the case               |  [x] Include           |
|                                      |                                    |                        |
+--------------------------------------+------------------------------------+------------------------+
 [Save configuration] [Load saved]   QDS ... · n-0 · 3 of 4 cases ready · 1 problem  [Cancel] [Start calculation]
```

- **Workspace** – three panes, about 40 % / 38 % / 22 %, dividers draggable.
  Left to right the way an outage travels: from the library, into the
  selected case, which is chosen on the right.
  - **Available planned outages** (left): every planned outage (`IntPlannedout`)
    of the library. The first column *In case* is a **check box**: tick it
    (click or Space) and the outage belongs to the selected case, untick it and
    the assignment ends; `☑ in case`, `☐` free, `fixed` (cannot be ticked), also
    as row colour. Then *Planned outage, Equipment, Start, End, Status*;
    *Add to case* (or Enter) adds all selected rows at once, *Set as fixed
    background*, *Details* (also double-click on a row). Demand transfers
    (`IntOutage`) are not read: they move load and switch no equipment.
  - **The selected case** (centre): title *Case A - name*, the count line *n case outages ·
    m fixed background outages*, the table *Planned outage, Equipment, Start, End,
    Priority*, *Remove from case*, *Details*, and the timeline of the case.
  - **Planning cases** (right) – **at most 5**, the counter *2 of 5 cases* stands above
    the table; at five, *New* and *Copy* are locked. Table *Planning case, Outages*
    (number of outages), *Status* (`ready`, `not calculated`, `excluded`).
    Nobody types an ID: GridLens numbers the cases itself (C1 … C5, the lowest
    free number) and uses that ID only internally (result objects
    `GridLens_<stamp>_C1`, report). Below: *New, Copy, Delete*, *One case
    per planned outage* (creates at most five), and for the selected case
    *Run*. Every case contains only the outages assigned
    directly to it. Copying, editing or deleting a case leaves the others unchanged.
- **Fixed background & rules** – visible explanations show when to use each optional section, the T1 / North / South example and what each rule checks. Leave both empty for independent cases with no shared outages or extra rules. Left: the fixed background outages (Rfix) with
  *Remove from fixed background*; right the rules between planned outages with three
  drop-downs (*outage, rule, outage*; a name that occurs twice in the project
  carries its PowerFactory path), *Add rule*, *Remove rule*.
- **Review & start** – *Calculation* (n-0, n-1 disabled, QDS period of the
  active ComStatsim), *What will be calculated* in short lines, and the table
  *Problems and warnings*. The tab label shows the number of problems, e.g.
  *Review & start (1)*.
- **Status line** (every tab): QDS period, assessment, ready cases, problem
  count in red; a click opens *Review & start*.

### Filtering and sorting – every table

- A **filter row** directly under the column headers: a text field per text
  column (keeps rows that contain the text, any case) and a drop-down per
  category column (*Status*, *In case*, *Rule*; *All* switches it off).
  Filters of several columns combine.
- Under the table: *12 of 48 shown · Clear filters* (only while a filter is
  active).
- A **click on a header** sorts by that column, a second click reverses it
  (▲/▼ after the heading); numbers sort by value.
- Filtering and sorting change only what is shown, never the configuration.
  Header and filter widths follow the table width; on narrow screens every
  column shrinks in proportion.

### Hover help

Resting the mouse on a control for about half a second shows what it does to
the calculation: every button, *Run*, the name and description fields, the case
counter, the column headings with categories (*Status*, *In case*, *Outages*,
*Priority*, *Rule*; each also says how sorting works), every filter field, the
timeline legend, the rule drop-down, n-1, the QDS period and the status line.
The texts are in `HELP_TEXTS` and `COLUMN_HELP` of `gridlens_report.py`
(class `Tooltip`, standard library only).

## Window design and visible guidance

A navy header identifies the planning workspace. The tables use a shared blue-grey
palette, larger native text, 26-pixel rows and distinct selected rows. Instructions
wrap to the pane width; the status line sits above the action row so it cannot
push Cancel or Start calculation out of the window. Ctrl+Tab navigates the tabs.
The first case-table column is a Run flag (☑/☐). Click it or press Space on a focused row to include or exclude that case. Excluded cases remain saved and are omitted from calculation and report. The separate Selected case checkbox panel is removed. The rule editor has labelled,
flexible-width fields. All widgets remain standard Tk/ttk; no new dependency or
animation was added. Both the publisher and standalone GUI test use the same design.

## Independent planning cases

Build every case by assigning its planned outages directly. For example:

- C1: FS North.
- C2: FS South.
- C3: FS North and FS South, both assigned directly.

The same outage can belong to several cases. No case inherits outages from
another case, depends on it or excludes a combination. To create a variant,
copy a case and change the copy. Deleting or excluding C1 leaves C2 and C3 unchanged.

Saved version 1 configurations are converted to version 2 in memory when opened:
formerly inherited outages and their effective own dates become direct assignments;
case dependencies and alternatives are removed. Review & start shows a migration
notice if relations were present; saving drops the notice, so it appears only until
the reviewed cases are saved. The original file stays unchanged even then (see below).
Invalid legacy references or cycles are reported with the file path rather than
silently losing assignments.

The rules on *Fixed background & rules* apply between two
**planned outages** in every case: *must not overlap* (windows must not
overlap), *second only after the first* (the second starts after the first
has ended), *only together* (a case with one contains the other and their windows overlap). A case that breaks a rule is not calculated and is reported.

## Keyboard

Every list can be used without the mouse (`KEYBOARD_SHORTCUTS` in `gridlens_report.py`). On macOS Command works like Ctrl.

| Key | Where | What |
|---|---|---|
| Delete / BackSpace | case list | delete the selected case (asks first) |
| Delete / BackSpace | outages of the case | remove the selected outages from the case |
| Delete / BackSpace | fixed background outages | remove the selected outages from the fixed background |
| Delete / BackSpace | rules | remove the selected rules |
| Space | case list | switch the Run flag of the focused case |
| Space | available outages | tick or untick the focused outage |
| Enter | available outages | add all selected outages to the case |
| F2 / Enter | case list | rename the case in place |
| Ctrl+A | any table | select every shown row |
| Ctrl+N | window | new case |
| Ctrl+F | window | search the available outages |
| Ctrl+S | window | save configuration |
| Ctrl+O | window | load saved configuration |
| Ctrl+Enter | window | start calculation |
| Escape | window | end an in-place edit, otherwise cancel |

## What a click does

| Action | Effect |
|---|---|
| Click a case on the right (`<<TreeviewSelect>>`) | the centre shows its planned outages at once; the left marks them `in case`; name, description, timeline, the other tabs and the status line follow. No extra window. |
| Type into a filter field / choose in a filter list | the table shows only matching rows at once; *Clear filters* shows all again |
| Click a column header | sorts by that column; a second click reverses the order |
| Click a case in a relation list | selects (highlights) or deselects it; the relation applies at once |
| Rest the mouse on a control | after about half a second an explanation appears; it closes when the mouse leaves or on a click |
| Click the status line | opens *Review & start* |
| Tick or untick the box in the first column of the left list (or Space) | that one outage is added to or removed from the selected case at once; a fixed outage cannot be ticked and says why |
| *Add to case* or Enter in the left list | the selected outages are assigned; centre table, outage count, marks and preview update at once. An outage already in the case or fixed is refused with the reason. |
| *Remove from case* or Delete key in the centre | only the assignment ends; the planned outage in PowerFactory is untouched. |
| Double-click in the centre or *Details* | a compact window with what PowerFactory holds for the outage (object, class, equipment, actions, window, priority, status, cases it is used in) and its own dates in this case. |
| *Set as fixed background* | the outage becomes part of the reference and of every case (Rfix). Refused while the outage is assigned to a case, so it never acts twice. |
| *New* | creates *Case n* with the next generated ID (C1 … C5) and selects it; no extra window. Locked at five cases. |
| *Copy* | new generated ID, name *… (copy)*, same outages and own dates; fully independent. Locked at five cases. |
| Double-click a case (or F2 / Enter) in the case list | the name becomes editable right in its row; Enter or a click elsewhere applies, Escape cancels only the edit; an empty name keeps the old one. The generated ID used for result objects stays. |
| Double-click the description next to the case name in the centre | the description becomes editable in place, the same way; without one it reads *(double-click to add a description)* |
| Double-click a row in the left list | the details window of that planned outage |
| *Delete* | asks once and removes only the selected case. Other cases and the PowerFactory planned outages stay unchanged. |
| *One case per planned outage* | replaces the cases by one per outage in the simulated period, at most five (and says so when outages are left out); ignored and fixed outages get none. |
| *Save configuration* / *Load saved configuration* | writes / reads the project's JSON file with revision, user and time; the project is not touched. |
| *Cancel*, Escape, window close | ends the run: nothing calculated, saved or published, nothing in the project changed. The cancellation is passed to the report caller; the extension does not finish normally and hand control back for rendering. IntReport behaviour still needs verification in PowerFactory. |
| *Start calculation* | checks (see below), closes the window and hands the configuration to GridLens; then the existing calculation and PDF publication run. No result window follows. |

## Timeline

The timeline is a planning check only (no load flow, voltage or other
result). One row per case outage (blue) and per fixed outage (grey); light blue
shading marks times when more than one is active. Overlapping outages are
normal planning: they are neither a warning nor an error. The timeline shows
no dates and no numbers, only the order and the overlap. A long empty period (e.g. between KW10 and KW40)
is drawn as a short light band, so far-apart outages stay readable
(`timeline_scale`).

## Calculation options

- **n-0 – quasi-dynamic simulation (QDS)**: always on; it is the only
  assessment GridLens has.
- **n-1 – contingency analysis**: shown but disabled, with the note that this
  GridLens version has no contingency analysis. A configuration file that
  asks for n-1 is refused with that reason instead of being ignored.
- **QDS period**: taken from the active ComStatsim and shown only. There is
  no time-optimisation option and no shortened calculation window; every run
  covers the complete ComStatsim period.

## Checks on Start calculation

1. The configuration is valid (IDs, outage paths, own dates, outage rules).
2. At least one case can be calculated; otherwise GridLens asks whether to
   calculate the reference only.
3. Cases that cannot be calculated (missing planned outage, broken outage
   rule, outside the period, own dates) are listed with
   their reason; GridLens asks whether to continue and reports them as
   NOT EVALUATED / NOT SIMULATED.
4. Only n-0 is requested.

## Hand-over to GridLens

```mermaid
flowchart LR
    W["Case manager (CaseManagerDialog)"] -- "every click" --> E["CaseEditor: configuration copy"]
    E -- "Start calculation" --> C["configuration (cases, background, rules, assessments)"]
    C --> R["resolve_request: checked planning cases, reference type"]
    R --> G["execute_gridlens: REF + one QDS per case (unchanged)"]
    G --> P["publish_report: tables for the PDF (unchanged)"]
    W -- "Cancel" --> X(["stop, nothing changed"])
```

Separation in the code: `CaseManagerDialog` is the window and keeps only
the selection state; `CaseEditor` holds every editing rule and the
configuration copy (tested without a window); PowerFactory outage references
are the records GridLens read before the window opened; `resolve_request`
turns the configuration into the calculation request; `execute_gridlens`
calculates and `publish_report` publishes. The window never switches
equipment, never writes PowerFactory and never starts a QDS.

## Where the cases come from

| `CASE_SOURCE` | Behaviour |
|---|---|
| `'gui'` (default) | the window, pre-filled with the saved configuration. If `tkinter` cannot open it or it cannot be built: the saved configuration; without one: one case per outage. The report states the source. |
| `'saved'` | the saved configuration, no window |
| `'per_outage'` | one case per planned outage in the simulated period |

Configuration file: `CASE_CONFIG_DIR` (default `~/GridLens/cases`), one per
project, saved as `<project>_<hash>.v2.json`. The schema-1 file `<project>_<hash>.json`
of the delivered gridlens-powerfactory script is only read (as long as no `.v2.json`
exists) and never overwritten, so both versions keep working on the same project. New fields since the redesign: `assessments` (`["n-0"]`) and per case
`enabled` (true/false). A saved or hand-edited configuration with more than five
cases (e.g. saved by GridLens 8.0) still opens in the case manager, shows *6 of 5
cases* in red and the reason under *Review & start*, so cases can be deleted;
calculating, saving or `CASE_SOURCE = 'saved'` refuse it with that reason; only `CASE_SOURCE = 'per_outage'` (no window)
still creates one case per outage without a limit. A case excluded with *Run* is neither calculated nor
reported; other cases are unaffected.

## What changed against the previous window

| Kept | Changed |
|---|---|
| cases: new, copy, rename, delete, description, one case per outage | case list as a filterable table with FS count and status, **at most 5 cases**, **IDs generated (C1 … C5), never typed**; new case without dialog; rename in place; delete affects only the selected case |
| assignment of outages, an outage in several cases | assignment from a separate list of available outages with search, filter and *Add to case*; the case table shows only the case's outages |
| fixed background outages (Rfix) | own section and own button; a fixed outage cannot also be a case outage |
| – | **removed:** relations between cases; assign outages directly to independent cases |
| rules `not_overlap`, `order`, `together` | added with three drop-downs instead of typed text lines |
| own dates per case (recorded, not applied) | in the details window of the outage |
| save configuration, preview, Cancel, OK | preview as short lines; *Load saved configuration*; OK is now *Start calculation* |
| – | **removed:** Conservative/Optimized choice and the proposal of shorter windows |
| – | **new:** three tabs (Workspace, Fixed background & rules, Review & start), a filter row and header sorting in every table, status line, problem list, timeline, n-0/n-1 choice, per-case *Run* |

## Trying it in PowerFactory

`tools/FS_CaseManager_GUI_Test_PowerFactory2026.py` is a **separate script**:
it does not load or import `gridlens_report.py`. Paste it alone into a
ComPython. It carries its own copy of the case manager (the window and what it
needs: reading the planned outages, checking a configuration, the preview), so
it opens exactly this window with the real planned outages of the active
project, read only, and prints what *Start calculation* hands back instead of
calculating. Save and load work on a temporary copy of the configuration. If
the window does not open there, configure the cases where it does and set
`CASE_SOURCE = 'saved'`.

The copy is marked in the file and written by `tools/sync_case_manager_copy.py`
(development tool, not delivered). Whoever changes the case manager in
`gridlens_report.py` runs `python3 tools/sync_case_manager_copy.py`;
`test_the_copied_case_manager_matches_gridlens_report` fails while the copy is
out of date.

## Case settings preview

Review & start includes a read-only, scrollable Cases to calculate preview.
It updates immediately when Run flags or case settings change. Each ready case
lists its name, description, planned outages and effective time windows, n-0
assessment, full QDS period and shared background. The common settings name the
reference, background outage windows and planning rules. Identical cases show
which result is planned for reuse. Blocked cases show their reason; cases with
the Run flag off are listed separately as excluded. Previewing starts no calculation.
