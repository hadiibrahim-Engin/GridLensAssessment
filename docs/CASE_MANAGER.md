# GridLens Case Manager – Operating Guide

German version: [de/FALLMANAGER.md](de/FALLMANAGER.md)

The case manager is the window GridLens opens when the ComPython runs with
`CASE_SOURCE = 'gui'`. It only **configures** the calculation: which planning
cases, which fixed background outages and rules, which assessments and which
settings. It shows no results; those are in the report. PowerFactory waits
while the window is open, and nothing is calculated or changed in the project
before **Start calculation**.

`main.py` draws the window with tkinter/ttk, `main_qt.py` with PyQt6 or PyQt5
(selectable with `QT_BINDING`). Both offer the same functions and hand the same
configuration to GridLens.

## Layout

Two pages, *Case Manager* and *Settings*. A status line and the action bar
(*Save configuration*, *Load saved configuration*, *Cancel*, *Start
calculation*) stay visible on both.

```
 [ Case Manager (1) ] [ Settings ]
+--------------------------------------+------------------------------------+------------------------+
| Available planned outages            | Case C1 - Summer measures          | Planning cases  2 of 5 |
| In case  Planned outage Equip. Start | 2 case outages · 1 fixed backgr.   | Run Planning case Stat.|
| ☑        FS Bedarf 1    NE_L1  ...   | FS Bedarf 1    NE_L1  ...          | ☑   Summer       ready |
| ☐        FS Bedarf 3    NE_L7  ...   | FS Bedarf 2    NE_L2  ...          | ☑   North-east   ready |
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

### Page *Case Manager*

The three panes follow the way an outage travels: from the library (left)
into the selected case (centre), which is chosen on the right. The dividers
can be dragged.

- **Available planned outages** (left): every `IntPlannedout` of the project
  with *In case, Planned outage, Equipment, Start, End, Status*.
  - *In case* is a check box: tick it (click or Space) and the outage belongs
    to the selected case; untick it and the assignment ends. A fixed
    background outage shows *fixed* and cannot be ticked.
  - *Status*: *in simulated period*, *outside simulated period* (no effect in
    this run) or *Ignored in PowerFactory* (applied only in a case that
    contains it).
  - *Add to case* (or Enter) assigns all selected rows, *Set as fixed
    background* makes them fixed, *Details* (or double-click) opens the
    details window.
  - Demand transfers (`IntOutage`) are not listed: they move load and switch
    no equipment.
- **The selected case** (centre): its name, the description (double-click in
  `main.py`, click in `main_qt.py`), the count *n case outages · m fixed
  background outages*, its outages with *Planned outage, Equipment, Start,
  End, Priority*, *Remove from case*, *Details* and the timeline.
- **Planning cases** (right): at most as many as *Settings → Report and run →
  Planning cases, at most* allows (default 5, up to 20); the counter *2 of 5
  cases* turns red at the limit and *New*/*Copy* are locked.
  - *Run* (first column): ticked = calculated and reported; empty = excluded,
    kept in the configuration but neither calculated nor reported.
  - *Planning case*: the name; double-click, F2 or Enter edits it in place.
  - *Outages*: the number of assigned outages.
  - *Status*: *ready*, *not calculated* (the reason is under *Problems and
    warnings*) or *excluded*.
  - *New*, *Copy*, *Delete*, *One case per planned outage*.
  - IDs (`C1`, `C2`, …) are generated, never typed. They name the result
    objects (`GridLens_<stamp>_C1`) and stay when a case is renamed.
- **Calculation** (bottom left):
  - n-0 (the QDS of REF and every case) is always calculated.
  - *n-1 – reference contingency analysis* and *(n-1)' – contingency analysis
    with planned-outage scenarios*. (n-1)' needs n-1: ticking (n-1)' ticks
    n-1, unticking n-1 unticks (n-1)'.
  - The QDS period of the active ComStatsim.
  - *Results*: *Calculate now*, or *Re-evaluate the kept run of <date time>*.
    The re-evaluation calculates nothing; it reads that run's result objects
    with the current settings. The choice is not saved.
  - *Show calculation preview*: the read-only preview of what will be calculated.
- **Problems and warnings** (bottom right): everything that stops or limits
  the calculation, with where it occurs. The page tab shows the number, e.g.
  *Case Manager (1)*.

### Page *Settings*

An action bar (*Restore defaults*, *Apply settings*, *Save settings*, the
state of the settings) and seven sections:

| Section | Content |
|---|---|
| Network scope | *Report filter: assessed equipment* (grids whose lines, transformers and terminals are assessed; none selected = every grid; no effect on the calculation); *n-1 filter: contingencies by grid* (*Every grid* or *Own selection*, with the number of contingencies in scope); *n-1 filter: outaged elements* (only contingencies outaging a selected element are calculated). A selection takes effect at once. |
| Limits | warning thresholds and n-0 limits (lines and transformers separately), the n-1 limit handling, the voltage band in p.u. for every voltage level, the de-energised threshold; post-fault voltage limits read only |
| Classification | n-0 change tolerances and the n-1 / (n-1)' classification parameters |
| Report and run | appendix thresholds, Top-N rows, points per time plot, REF on/off, the case limit, n-1 study times per case |
| Contingency analysis | contingency set, categories, monitored scope, AC/DC, islanding, unsupplied load, load shedding, post-fault phases, remedial actions – read only |
| QDS time base | start, end, time step of the active ComStatsim, read only |
| Fixed background & rules | the fixed background outages and the rules between planned outages |

Every settings row shows *Setting, Value, Unit, Source, Category* and a
message:

- *Source*: `GridLens` (default), `PowerFactory` (read from the model), `user`
  (an applied override) or `edited, not applied`.
- *Category*: `A · evaluation` interprets results and never changes a load
  flow, a rating or the model. `B · calculation` would change what
  PowerFactory calculates and is read only.

Each value is checked while it is typed: a finite number, positive limits,
non-negative tolerances, a value from the list. *Apply* also checks
de-energised threshold < minimum < maximum voltage and warning ≤ limit. An
invalid field turns red with its message and the page tab reads *Settings
(!)*; *Start calculation* and *Save* refuse until it is fixed. *Start
calculation* and *Save* apply edited values first. *Restore defaults* removes
every override. Defaults and meaning of every setting:
[ARCHITECTURE.md, section 9](ARCHITECTURE.md#9-settings).

### Status line

QDS period, assessments, ready cases, number of problems (red) and settings
overrides. A click opens the *Case Manager* page.

## Working with cases

Every case contains only the outages assigned directly to it. The same outage
may be in several cases. Example:

- C1: FS North.
- C2: FS South.
- C3: FS North and FS South, both assigned directly – the joint plan.

No case inherits from another, depends on it or excludes a combination. To
create a variant, copy a case and change the copy; deleting or excluding C1
leaves C2 and C3 unchanged.

**Fixed background outages** (*Settings → Fixed background & rules*) are
active in the reference (then Rfix) and in every case. An outage that is
assigned to a case cannot be made fixed, so it never acts twice.

**Rules** apply in every case: *must not overlap* (windows must not overlap),
*second only after the first* (the second starts after the first has ended),
*only together* (a case with one contains the other, overlapping in time). A
case that breaks a rule is not calculated and is reported.

**Own dates per outage** can be entered in the details window. They are
recorded only and not applied; such a case is reported NOT EVALUATED. For
another date, create a planned outage with that date in PowerFactory.

## Every table: filter and sort

- A filter row directly under the column headings: a text field per text
  column (contains the text, any case) and a drop-down per category column
  (*All* switches it off). Filters of several columns combine.
- Under the table: *12 of 48 shown · Clear filters* while a filter is active.
- A click on a heading sorts by that column; a second click reverses it.
  Numbers sort by value.
- Filtering and sorting change only what is shown, never the configuration.
  A filtered-out row is never changed by Space.

## Hover help

Resting the mouse on a control for about half a second shows what it does to
the calculation: every button, *Run*, the name and description, the case
counter, the column headings, every filter, the timeline, the rule fields,
n-0, n-1, (n-1)', the QDS period, the status line and every setting. The
texts are `HELP_TEXTS`, `SETTING_HELP` and `COLUMN_HELP` in the script.

## Timeline

A planning check only, without load flow or result. One row per case outage
(blue) and per fixed outage (grey); shading marks times when more than one is
active. Overlapping outages are normal planning, neither warning nor error. A
long empty period (e.g. between week 10 and week 40) is drawn short, so
far-apart outages stay readable; bar lengths across such a gap are not to scale.

## Keyboard

On macOS Command works like Ctrl.

| Key | Where | What |
|---|---|---|
| Delete / BackSpace | case list | delete the selected case (asks first) |
| Delete / BackSpace | outages of the case | remove the selected outages from the case |
| Delete / BackSpace | fixed background outages | remove them from the fixed background |
| Delete / BackSpace | rules | remove the selected rules |
| Space | case list | switch the *Run* flag of the focused case |
| Space | available outages | tick or untick the focused outage |
| Enter | available outages | add all selected outages to the case |
| F2 / Enter | case list | rename the case in place |
| Ctrl+A | any table | select every shown row |
| Ctrl+N | window | new case |
| Ctrl+F | window | search the available outages |
| Ctrl+S | window | save configuration |
| Ctrl+O | window | load saved configuration |
| Ctrl+Enter | window | start calculation |
| Ctrl + / Ctrl − / Ctrl 0 | window | zoom the window for this session |
| Escape | window | end an in-place edit (in `main_qt.py` also clear a filter field), otherwise cancel |

## What a click does

| Action | Effect |
|---|---|
| select a case on the right | the centre shows its outages, the left marks them; description, timeline, preview and status line follow |
| tick / untick in the left list | that outage is added to or removed from the selected case at once; a fixed outage is refused with the reason |
| *Add to case* / Enter | all selected outages are assigned; an outage already in the case or fixed is refused with the reason |
| *Remove from case* / Delete in the centre | only the assignment ends; the planned outage in PowerFactory is untouched |
| *Details* / double-click on an outage | what PowerFactory holds for it (object, class, equipment, switching actions, window, priority, status, cases using it) and its own dates in this case |
| *Set as fixed background* | the outage joins the reference and every case; refused while it is in a case |
| *New* | creates *Case n* with the next free ID and selects it |
| *Copy* | new ID, name *… (copy)*, same outages and own dates; fully independent |
| *Delete* | asks once and removes only the selected case |
| *One case per planned outage* | asks, then replaces all cases by one per outage in the simulated period, up to the case limit; *Ignored* and fixed outages get none |
| *Show calculation preview* | opens or closes the read-only preview |
| *Apply settings* / *Save settings* / *Restore defaults* | checks and takes the values / also saves the file / removes every override |
| *Save configuration* / *Load saved configuration* | writes / reads the project's configuration file; *Load* asks before replacing what is on screen |
| *Cancel*, Escape, closing the window | ends the run: nothing calculated, saved or published, nothing in the project changed; the cancellation is passed on to the caller |
| *Start calculation* | applies edited settings, runs the checks below, closes the window and hands the configuration to GridLens |

## Checks on *Start calculation*

1. Every setting is valid; otherwise the *Settings* page opens with the list
   of problems and nothing starts.
2. The assessments are consistent ((n-1)' only with n-1).
3. The configuration is valid (IDs, outage paths, rules, dates).
4. If no case can be calculated, GridLens asks whether to calculate the
   reference only.
5. Cases that cannot be calculated are listed with their reason; GridLens asks
   whether to continue and reports them as NOT EVALUATED or NOT SIMULATED.

## Calculation preview

*Show calculation preview* opens a read-only, scrollable summary below the
problems. It updates with every change and lists: the results choice, the
assessments, the QDS period, the reference (R0, Rfix or off), the fixed
background outages with their windows, the report filter, the contingencies in
scope, the rules, the settings overrides, and for every ready case its name,
description, outages with effective windows and whether it gets its own QDS
run or reuses an identical case. Blocked cases show their reason, excluded
cases are listed separately. The preview never calculates.

## Where the cases come from

| `CASE_SOURCE` | Behaviour |
|---|---|
| `'gui'` (default) | the window, pre-filled with the saved configuration. If the window cannot open or cannot be built: the saved configuration; without one, one case per outage. The report states the source. |
| `'saved'` | the saved configuration, no window |
| `'per_outage'` | one case per planned outage in the simulated period, no window, no case limit |

Configuration file: `~/GridLens/cases/<project>_<hash>.v2.json` (folder
`CASE_CONFIG_DIR`). It holds `cases` (each with `id`, `name`, `description`,
`enabled`, `outages`, `overrides`), `background`, `rules`, `assessments` and
`settings` (overrides only), with schema, revision, user and time. A file with
more cases than the limit still opens, shows the counter in red and the
reason, so cases can be deleted; calculating, saving and `CASE_SOURCE =
'saved'` refuse it.

## Trying the window without calculating

`ui/preview_case_manager.py` is a separate script with its own copy of the
case manager. Pasted alone into a ComPython it opens the same window with the
real planned outages of the active project, read only, and prints what *Start
calculation* would hand over instead of calculating. Save and load work on a
temporary copy of the configuration. After a change to the case manager in
`main.py`, `python3 ui/sync_case_manager_copy.py` updates the copy; a test
fails while it is out of date.
