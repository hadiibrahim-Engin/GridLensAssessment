# -*- coding: utf-8 -*-
"""
GridLens Case Manager - GUI test for DIgSILENT PowerFactory 2026 (no calculation).

A separate, self-contained script: it does not load or import the production
script powerfactory/gridlens_report.py. It contains its own copy of the case
manager window (the block marked "copy of powerfactory/gridlens_report.py"
below), so it shows exactly the window GridLens shows before a calculation,
with the planned outages of the active project:

  1. Does tkinter with Tcl/Tk work in this PowerFactory installation?
  2. Does the case manager open from a ComPython and react to clicks?
  3. Does a click on a case show its planned outages; do add, remove, copy,
     fixed outages, relations, rules, hover help and the timeline work with
     real data?
  4. Does "Start calculation" hand the configuration back to Python?

Read-only: this script writes no PowerFactory attribute, starts no QDS and
switches nothing. "Save configuration" and "Load saved configuration" in the
window work on a temporary copy, so not even the GridLens case configuration in
~/GridLens/cases changes. After "Start calculation" the configuration and the
preview are printed to the output window; nothing is calculated.

Paste the whole file into a ComPython and run it. Dependencies: Python
standard library and the PowerFactory module only.

The copied block is written by tools/sync_case_manager_copy.py (development
tool, not delivered); do not edit it by hand.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import time
import traceback

# Start from the case configuration GridLens saved for this project (read only).
USE_SAVED_CONFIGURATION = True

PREFIX = "[CASE-MANAGER-TEST] "
H, D = 3600.0, 86400.0


# >>> copy of powerfactory/gridlens_report.py, written by tools/sync_case_manager_copy.py - do not edit >>>
# GridLens 8.0.0: 94 definitions.
import re
import hashlib
import math
from datetime import datetime


PUBLISHER_VERSION = '8.0.0'


RUN_REFERENCE_CASE = True


CASE_CONFIG_DIR = ''


MAX_CASES = 5


CASE_CONFIG_SCHEMA = 'gridlens.cases'


CASE_CONFIG_SCHEMA_VERSION = 1


ASSESSMENTS = ('n-0', 'n-1')


AVAILABLE_ASSESSMENTS = ('n-0',)


QDS_WINDOW_MODE = 'conservative'


WINDOW_WARMUP_HOURS = 24.0


WINDOW_MERGE_GAP_HOURS = 48.0


ALLOW_OUTAGE_TIME_OVERRIDE = False


MAX_LABEL_LENGTH = 80


MAX_DIAGNOSTIC_LENGTH = 4000


def safe_attr(obj, name, default=None):
    try:
        value = getattr(obj, name)
        return default if value is None else value
    except Exception:
        return default


def clip_text(value, limit):
    """Shorten to `limit` characters with a visible ellipsis, nothing else."""
    text = str(value)
    if len(text) <= limit:
        return text
    return text[:max(0, limit - 1)] + '\u2026'


def object_key(obj):
    try:
        value = obj.GetFullName()
        if value:
            return str(value)
    except Exception:
        pass
    return str(safe_attr(obj, 'loc_name', 'unknown'))


def object_name(obj):
    value = safe_attr(obj, 'loc_name', '')
    return str(value) if value else object_key(obj).rsplit('\\', 1)[-1]


def object_description(obj):
    value = safe_attr(obj, 'desc', '')
    if isinstance(value, (list, tuple)):
        return ' '.join((str(item) for item in value if item))
    return str(value or '')


def class_name(obj):
    try:
        return str(obj.GetClassName())
    except Exception:
        return ''


def finite_number(value):
    if isinstance(value, (tuple, list)):
        return None
    if value is None or type(value) is bool:
        return None
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return None
        if ',' in value and '.' not in value and (value.count(',') == 1):
            value = value.replace(',', '.')
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if math.isfinite(result) else None


def merge_intervals(intervals):
    """Sorted, non-overlapping union of half-open (start, end) intervals."""
    merged = []
    for start, end in sorted(interval for interval in intervals if interval[1] > interval[0]):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


REFERENCE_ID = 'REF'


def _counted(count, singular, plural):
    return '{} {}'.format(count, singular if count == 1 else plural)


def _key_discriminator(key):
    digest = hashlib.sha256(str(key).encode('utf-8')).hexdigest()
    return digest[:6]


def period_text(start, end):
    """'2026-10-15 00:00 - 05:00' when both ends lie on the same day."""
    if not start and not end:
        return ''
    if start[:10] and start[:10] == end[:10] and len(end) > 11:
        return '{} - {}'.format(start, end[11:])
    return '{} - {}'.format(start, end)


TOTAL_STEPS = 7


OUTAGE_CLASSES = ("IntPlannedout",)


OUTAGE_CONSIDERED = "CONSIDERED"


PLAN_READY = "READY"


PLAN_NOT_SIMULATED = "NOT SIMULATED"


PLAN_NOT_EVALUATED = "NOT EVALUATED"


OUTAGE_SKIPPED = "SKIPPED"


OUTAGE_START_ATTRIBUTES = (
    "starttime", "tStart", "t_start", "date_start", "time_start")


OUTAGE_END_ATTRIBUTES = (
    "endtime", "tEnd", "t_end", "date_end", "time_end")


OUTAGE_EQUIPMENT_ATTRIBUTES = (
    "components", "p_target", "pTarget", "pObject", "p_object", "obj_id",
    "pDevice", "cpObject", "pElm", "p_target1", "p_target2")


QDS_PERIOD_ATTRIBUTES = (("startTime", "endTime"), ("starttime", "endtime"))


class GridLensError(RuntimeError):
    """Expected runtime error with an actionable user-facing message."""


class RunLogger:
    """Structured progress output for the PowerFactory output window.

    Three levels keep a long run readable:

        ====================================  section: one step of the run
         STEP 4/7 · Calculation
        ====================================
        .. Case OUT01 · NE_L1 ..............  case: one QDS run
            indented lines                     details of the current block
    """

    WIDTH = 78

    def __init__(self, app):
        self.app = app
        self.started = time.monotonic()

    def _emit(self, line):
        printer = getattr(self.app, "PrintPlain", None)
        if callable(printer):
            try:
                printer(line)
                return
            except Exception:
                pass
        print(line, flush=True)

    def write(self, stage, message, step=None, level="INFO"):
        position = "--/{}".format(TOTAL_STEPS)
        if step is not None:
            position = "{:02d}/{}".format(step, TOTAL_STEPS)
        elapsed = time.monotonic() - self.started
        self._emit("[GridLens][{}][{}][{}][{:7.1f}s] {}".format(
            position, level, stage, elapsed, message))

    def _plain(self, text, level="INFO"):
        self._emit("[GridLens]{} {}".format(
            "" if level == "INFO" else "[" + level + "]", text))

    def section(self, title):
        self._emit("")
        self._plain("=" * self.WIDTH)
        self._plain(" " + title)
        self._plain("=" * self.WIDTH)

    def step(self, number, title):
        self.section("STEP {}/{} \u00b7 {}".format(number, TOTAL_STEPS, title))

    def case(self, title):
        head = ".. " + title + " "
        self._plain(head + "." * max(3, self.WIDTH - len(head)))

    def detail(self, message, level="INFO"):
        self._plain("    " + message, level)

    def table(self, header, rows, level="INFO"):
        """Rows of strings in aligned columns; the last column is not padded."""
        lines = ([tuple(header)] if header else []) + [
            tuple(str(cell) for cell in row) for row in rows]
        if not lines:
            return
        widths = [max(len(line[i]) for line in lines) for i in range(len(lines[0]))]
        for number, line in enumerate(lines):
            self.detail("  ".join(
                cell.ljust(widths[i]) if i < len(line) - 1 else cell
                for i, cell in enumerate(line)), level)
            if header and number == 0:
                self.detail("  ".join(
                    "-" * widths[i] if i < len(line) - 1 else "-" * min(widths[i], 40)
                    for i in range(len(line))))


def _call_without_or_with_zero(method):
    try:
        return method()
    except TypeError:
        return method(0)


def _declared_attributes(obj):
    """Name and value of every attribute the object itself declares."""
    names = []
    for getter_name in ("GetAttributes", "GetAttributeNames"):
        getter = safe_attr(obj, getter_name)
        if not callable(getter):
            continue
        try:
            returned = _call_without_or_with_zero(getter)
        except Exception:
            continue
        names = sorted({str(item).strip() for item in returned or ()
                        if str(item).strip()})
        if names:
            break
    described = []
    for name in names:
        value = safe_attr(obj, name)
        if callable(value):
            continue
        described.append("{}={}".format(
            name, clip_text(value, MAX_LABEL_LENGTH) if value is not None else ""))
    return described


def describe_object_api(obj):
    """Report which callables and parameters a PowerFactory object exposes."""
    methods = []
    parameters = []
    try:
        names = sorted(dir(obj))
    except Exception:
        names = []
    for name in names:
        if name.startswith("_"):
            continue
        member = safe_attr(obj, name)
        if member is None:
            continue
        target = methods if callable(member) else parameters
        target.append(name)
    parts = [
        "class={}".format(class_name(obj) or "unknown"),
        "methods: {}".format(", ".join(methods) or "none visible"),
        "parameters: {}".format(", ".join(parameters) or "none visible"),
    ]
    declared = _declared_attributes(obj)
    if declared:
        parts.append("declared attributes: {}".format(", ".join(declared)))
    return clip_text("; ".join(parts), MAX_DIAGNOSTIC_LENGTH)


def _as_objects(value):
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [item for item in value if item is not None]
    return [value]


def _format_pf_time(value):
    if value is None or value == "":
        return ""
    if isinstance(value, str):
        return value.strip()
    numeric = finite_number(value)
    if numeric is None:
        return str(value)
    if numeric > 315532800:
        # Compact local time: the report cells are narrow and the time-axis
        # labels already read this way.
        try:
            return datetime.fromtimestamp(numeric).strftime("%Y-%m-%d %H:%M")
        except (OSError, OverflowError, ValueError):
            pass
    return "{:g}".format(numeric)


def _first_attribute(obj, names):
    for name in names:
        value = safe_attr(obj, name)
        if value not in (None, "", []):
            return value
    return None


def _outage_details(outage):
    """Collect display-only outage context without exposing full PF paths."""
    related = []
    for attribute in OUTAGE_EQUIPMENT_ATTRIBUTES:
        related.extend(_as_objects(safe_attr(outage, attribute)))
    try:
        children = outage.GetContents("*", 1) or []
    except TypeError:
        try:
            children = outage.GetContents("*") or []
        except Exception:
            children = []
    except Exception:
        children = []
    actions = []
    for child in children:
        child_class = class_name(child)
        child_name = object_name(child)
        if child_class.startswith(("Evt", "Sta", "Int")):
            actions.append("{} {}".format(child_class, child_name).strip())
        for attribute in OUTAGE_EQUIPMENT_ATTRIBUTES:
            related.extend(_as_objects(safe_attr(child, attribute)))
    equipment = []
    seen = set()
    for item in related:
        if isinstance(item, (str, int, float, bool)):
            continue
        key = object_key(item)
        if key in seen or item is outage:
            continue
        seen.add(key)
        equipment.append((class_name(item), object_name(item)))
    equipment.sort(key=lambda entry: (entry[1].casefold(), entry[0]))
    equipment_names = ", ".join(name for _, name in equipment)
    equipment_types = ", ".join(sorted({kind for kind, _ in equipment if kind}))
    action_text = "; ".join(sorted(set(actions)))
    if not action_text:
        action_text = object_description(outage)
    start = _first_attribute(outage, OUTAGE_START_ATTRIBUTES)
    end = _first_attribute(outage, OUTAGE_END_ATTRIBUTES)
    return equipment_names, equipment_types, action_text, _format_pf_time(start), _format_pf_time(end)


def _find_project_outages(app):
    """Return unique planned outages from the operational-library folder."""
    roots = []
    getter = getattr(app, "GetProjectFolder", None)
    if callable(getter):
        for key in ("outage", "outages"):
            try:
                roots.extend(_as_objects(getter(key)))
            except Exception:
                pass
    try:
        roots.extend(_as_objects(app.GetActiveProject()))
    except Exception:
        pass
    found = []
    successful_queries = 0
    for root in roots:
        for outage_class in OUTAGE_CLASSES:
            pattern = "*.{}".format(outage_class)
            try:
                values = root.GetContents(pattern, 1) or []
                successful_queries += 1
            except TypeError:
                try:
                    values = root.GetContents(pattern) or []
                    successful_queries += 1
                except Exception:
                    values = []
            except Exception:
                values = []
            found.extend(values)
    if successful_queries == 0:
        raise GridLensError(
            "Planned-outage discovery could not query the operational library "
            "or active project. No calculation was started.")
    unique = {}
    for outage in found:
        if class_name(outage) in OUTAGE_CLASSES:
            unique[object_key(outage)] = outage
    return sorted(unique.values(), key=lambda item: (
        object_name(item).casefold(), class_name(item), object_key(item)))


BRANCH_CLASSES = ("ElmLne", "ElmTr2", "ElmTr3", "ElmCoup")


def outage_branches(outage):
    """Branches an outage switches off, from its components and its actions."""
    related = []
    holders = [outage]
    try:
        holders += list(outage.GetContents("*", 1) or [])
    except Exception:
        pass
    for holder in holders:
        for attribute in OUTAGE_EQUIPMENT_ATTRIBUTES:
            related.extend(_as_objects(safe_attr(holder, attribute)))
    unique = {}
    for item in related:
        if class_name(item) in BRANCH_CLASSES:
            unique[object_key(item)] = item
    return list(unique.values())


def outage_component_keys(outage):
    """Keys of every object the outage or its actions name as components."""
    holders = [outage]
    try:
        holders += list(outage.GetContents("*", 1) or [])
    except Exception:
        pass
    keys = set()
    for holder in holders:
        for attribute in OUTAGE_EQUIPMENT_ATTRIBUTES:
            for item in _as_objects(safe_attr(holder, attribute)):
                if not isinstance(item, (str, int, float, bool)) and item is not outage:
                    keys.add(object_key(item))
    return sorted(keys)


def _outage_record(outage):
    equipment, equipment_type, actions, start, end = _outage_details(outage)
    branches = outage_branches(outage)
    return {
        "branches": branches,
        "equipment_keys": [object_key(item) for item in branches],
        "component_keys": outage_component_keys(outage),
        "key": object_key(outage),
        "originally_ignored": finite_number(safe_attr(outage, "outserv", 0)) == 1.0,
        "id": object_name(outage),
        "name": object_name(outage),
        "source_class": class_name(outage),
        "status": "PENDING",
        "skip_reason": "",
        "equipment_name": equipment,
        "equipment_type": equipment_type,
        "switching_actions": actions,
        "start_time": start,
        "end_time": end,
        "priority": finite_number(safe_attr(outage, "priority", 0)) or 0,
        "window": outage_window(outage),
        "_object": outage,
    }


def outage_window(outage):
    """The outage's (start, end) in epoch seconds, where PowerFactory has them."""
    start = finite_number(_first_attribute(outage, OUTAGE_START_ATTRIBUTES))
    end = finite_number(_first_attribute(outage, OUTAGE_END_ATTRIBUTES))
    return start, end


def window_overlaps_period(window, period):
    """True or False when both are readable, None when the answer is unknown."""
    start, end = window
    begin, finish = period
    if begin is None or finish is None:
        return None
    if start is None and end is None:
        return None
    if start is not None and start > finish:
        return False
    if end is not None and end < begin:
        return False
    return True


def classify_planned_outages(app, logger, period=(None, None)):
    """Report which planned outages PowerFactory will apply for this period.

    GridLens never applies an outage itself. PowerFactory does that during the
    calculation once PLANNED_OUTAGE_OPTION is set, driven by each outage's own
    time window. This pass only decides what to tell the reader, and whether an
    outage run is worth starting at all.
    """
    objects = _find_project_outages(app)
    records = [_outage_record(item) for item in objects]
    names = {}
    for record in records:
        names[record["name"]] = names.get(record["name"], 0) + 1
    for record in records:
        if names[record["name"]] > 1:
            record["id"] = "{} ({})".format(
                record["name"], _key_discriminator(object_key(record["_object"])))
    logger.write(
        "OUTAGES", "Found {} planned outage object(s).".format(len(records)), 3)
    candidates = []
    for index, record in enumerate(records, 1):
        outage = record["_object"]
        prefix = "Outage {}/{} '{}': ".format(index, len(records), record["name"])
        if finite_number(safe_attr(outage, "outserv", 0)) == 1.0:
            record["status"] = OUTAGE_SKIPPED
            record["skip_reason"] = "Outage object is disabled (outserv=1)."
            logger.write("OUTAGES", prefix + record["skip_reason"], 3, "WARNING")
            continue
        window = outage_window(outage)
        overlap = window_overlaps_period(window, period)
        if overlap is False:
            record["status"] = OUTAGE_SKIPPED
            record["skip_reason"] = (
                "Outage window {} to {} lies outside the simulated period "
                "{} to {}.".format(
                    _format_pf_time(window[0]), _format_pf_time(window[1]),
                    _format_pf_time(period[0]), _format_pf_time(period[1])))
            logger.write("OUTAGES", prefix + record["skip_reason"], 3, "WARNING")
            continue
        record["status"] = OUTAGE_CONSIDERED
        if overlap is True:
            record["skip_reason"] = ""
            logger.write(
                "OUTAGES",
                prefix + "window {} to {} overlaps the simulated period; "
                "PowerFactory will apply it.".format(
                    _format_pf_time(window[0]), _format_pf_time(window[1])), 3)
        else:
            record["skip_reason"] = (
                "The outage window could not be compared with the simulated "
                "period; PowerFactory decides whether it applies.")
            logger.write("OUTAGES", prefix + record["skip_reason"], 3, "WARNING")
            logger.write(
                "DIAGNOSTIC", prefix + describe_object_api(outage), 3, "WARNING")
        candidates.append(record)
    logger.table(
        ("#", "Planned outage", "Class", "Status", "Window", "Equipment"),
        [(number, record["name"], record["source_class"], record["status"],
          period_text(record["start_time"], record["end_time"]) or "unknown",
          clip_text(record["equipment_name"] or "none listed", 60))
         for number, record in enumerate(records, 1)])
    logger.detail("Where each outage object is stored (project path):")
    logger.table(
        ("#", "Planned outage", "Location"),
        [(number, record["name"], object_key(record["_object"]))
         for number, record in enumerate(records, 1)])
    return records, candidates


CASE_ID_PATTERN = re.compile(r'^[A-Za-z0-9_-]{1,16}$')


RULE_KINDS = ('not_overlap', 'order', 'together')


def interval_relation(first, second):
    """Allen relation of two half-open windows as T01..T13."""
    a1, b1 = first
    a2, b2 = second
    if b1 < a2:
        return 'T01'
    if b2 < a1:
        return 'T02'
    if b1 == a2:
        return 'T03'
    if b2 == a1:
        return 'T04'
    if a1 == a2 and b1 == b2:
        return 'T13'
    if a1 == a2:
        return 'T07' if b1 < b2 else 'T08'
    if b1 == b2:
        return 'T11' if a1 > a2 else 'T12'
    if a1 < a2 and b1 < b2:
        return 'T05'
    if a2 < a1 and b2 < b1:
        return 'T06'
    return 'T09' if a2 < a1 else 'T10'


def windows_overlap(first, second):
    return first[0] < second[1] and second[0] < first[1]


def network_states(windows):
    """Elementary intervals (start, end, active keys) from the first start to the last end.

    `windows` maps an occurrence key to its half-open (start, end). Any number
    of occurrences works the same way: every start and end is a boundary, and
    between two boundaries the active set does not change. Intervals without
    any active occurrence are kept (the empty set), neighbours with the same
    set are merged.
    """
    known = {key: window for key, window in windows.items()
             if window[0] is not None and window[1] is not None and window[1] > window[0]}
    points = sorted({point for window in known.values() for point in window})
    states = []
    for lo, hi in zip(points, points[1:]):
        active = frozenset(key for key, (start, end) in known.items() if start <= lo < end)
        if states and states[-1][2] == active and states[-1][1] == lo:
            states[-1] = (states[-1][0], hi, active)
        else:
            states.append((lo, hi, active))
    return states


def calculation_windows(windows, warmup_hours=WINDOW_WARMUP_HOURS, merge_gap_hours=WINDOW_MERGE_GAP_HOURS):
    """Shortest QDS periods that contain every window plus its warm-up.

    Windows closer than the merge gap share one period, because a second
    initialisation costs more than the steps in between. Only a proposal: it
    may be executed only when the time-coupled state is shown to be equal.
    """
    spans = merge_intervals([(start - warmup_hours * 3600.0, end) for start, end in windows
                             if start is not None and end is not None and end > start])
    merged = []
    for start, end in spans:
        if merged and start - merged[-1][1] < merge_gap_hours * 3600.0:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def assign_definitions(records):
    """Group occurrences that switch the same components into one technical outage."""
    groups = {}
    for record in records:
        components = tuple(record.get('component_keys') or ()) or (record['key'],)
        groups.setdefault(components, []).append(record)
    for components, members in groups.items():
        identifier = 'D' + hashlib.sha256('|'.join(components).encode('utf-8')).hexdigest()[:6]
        for record in members:
            record['definition_id'] = identifier
            record['definition_size'] = len(members)
    return records


def empty_case_config(project_key=''):
    return {'schema': CASE_CONFIG_SCHEMA, 'schema_version': CASE_CONFIG_SCHEMA_VERSION, 'revision': 0,
            'project': project_key, 'saved_at': '', 'saved_by': '', 'mode': QDS_WINDOW_MODE,
            'assessments': ['n-0'], 'background': [], 'cases': [], 'exclusive_groups': [], 'rules': []}


def _occurrence_window(record, plan_case):
    override = (plan_case.get('overrides') or {}).get(record['key'])
    if override:
        return finite_number(override[0]), finite_number(override[1])
    return record['window']


def _case_tree(case_id, by_id, trail=()):
    """Every case a case consists of, itself first; raises on a cycle."""
    if case_id in trail:
        raise ValueError('cases include each other: {}'.format(' -> '.join(trail + (case_id,))))
    case = by_id.get(case_id)
    if case is None:
        raise ValueError('included case {!r} does not exist'.format(case_id))
    found = [case_id]
    for child in case.get('includes') or ():
        for item in _case_tree(child, by_id, trail + (case_id,)):
            if item not in found:
                found.append(item)
    return found


def plan_fingerprint(plan, background):
    """Identity of a calculation: the same active outages with the same windows give the same result."""
    parts = sorted('{}|{}|{}'.format(record['key'], *plan['windows'].get(record['key'], (None, None))) for record in plan['members'])
    parts += sorted('F|{}|{}|{}'.format(record['key'], *record['window']) for record in background)
    return hashlib.sha256('\n'.join(parts).encode('utf-8')).hexdigest()[:16]


def _is_text_list(value):
    return isinstance(value, list) and all(isinstance(item, str) and item for item in value)


def validate_case_config(config, max_cases=MAX_CASES):
    """Structural problems of a configuration, as messages; [] when it can be used.

    `max_cases` limits the number of planning cases (None: no limit, for the
    one-case-per-outage mode that runs without the case manager).

    A configuration may come from a hand-edited file, so every field is
    checked for its type before anything reads it.
    """
    if not isinstance(config, dict):
        return ['the configuration is not an object']
    problems = []
    if config.get('schema') != CASE_CONFIG_SCHEMA:
        problems.append('unknown schema {!r}'.format(config.get('schema')))
    if config.get('schema_version') != CASE_CONFIG_SCHEMA_VERSION:
        problems.append('schema version {!r} is not {}'.format(config.get('schema_version'), CASE_CONFIG_SCHEMA_VERSION))
    if config.get('mode', QDS_WINDOW_MODE) not in ('conservative', 'optimized'):
        problems.append('unknown calculation mode {!r}'.format(config.get('mode')))
    assessments = config.get('assessments', ['n-0'])
    if not _is_text_list(assessments) or not assessments or set(assessments) - set(ASSESSMENTS):
        problems.append('assessments must name at least one of {}'.format(', '.join(ASSESSMENTS)))
    elif set(assessments) - set(AVAILABLE_ASSESSMENTS):
        problems.append('the n-1 contingency analysis is not part of this GridLens version; only the n-0 quasi-dynamic '
                        'assessment can be calculated')
    if not _is_text_list(config.get('background', [])):
        problems.append('background must be a list of planned outage paths')
    cases = config.get('cases', [])
    if not isinstance(cases, list) or not all(isinstance(case, dict) for case in cases):
        return problems + ['cases must be a list of objects']
    if max_cases is not None and len(cases) > max_cases:
        problems.append('at most {} planning cases are allowed, the configuration has {}'.format(max_cases, len(cases)))
    seen = set()
    for number, case in enumerate(cases, 1):
        identifier = case.get('id')
        label = 'case {}'.format(identifier if isinstance(identifier, str) and identifier else '#{}'.format(number))
        if not isinstance(identifier, str) or not CASE_ID_PATTERN.match(identifier) or identifier.upper() == REFERENCE_ID:
            problems.append('{}: id {!r} is not allowed (letters, digits, _ and -, up to 16 characters, not REF)'.format(label, identifier))
        elif identifier in seen:
            problems.append('{}: id is used twice'.format(label))
        seen.add(identifier)
        if not isinstance(case.get('name', ''), str) or not isinstance(case.get('description', ''), str):
            problems.append('{}: name and description must be text'.format(label))
        if not isinstance(case.get('enabled', True), bool):
            problems.append('{}: enabled must be true or false'.format(label))
        for field in ('outages', 'includes', 'requires'):
            if not _is_text_list(case.get(field, [])):
                problems.append('{}: {} must be a list of texts'.format(label, field))
        overrides = case.get('overrides', {})
        if not isinstance(overrides, dict):
            problems.append('{}: overrides must be an object'.format(label))
            continue
        for key, window in overrides.items():
            numbers = [finite_number(value) for value in window] if isinstance(window, list) else []
            if len(numbers) != 2 or None in numbers or numbers[1] <= numbers[0]:
                problems.append('{}: own dates of {!r} must be [start, end] in epoch seconds with end after start'.format(label, key))
    groups = config.get('exclusive_groups', [])
    if not isinstance(groups, list) or not all(_is_text_list(group) for group in groups):
        problems.append('exclusive_groups must be a list of lists of case ids')
    rules = config.get('rules', [])
    if not isinstance(rules, list) or not all(isinstance(rule, dict) for rule in rules):
        problems.append('rules must be a list of objects')
    else:
        for rule in rules:
            if rule.get('kind') not in RULE_KINDS:
                problems.append('unknown rule {!r}'.format(rule.get('kind')))
            elif not all(isinstance(rule.get(side), str) and rule.get(side) for side in ('first', 'second')):
                problems.append('rule {} needs a first and a second planned outage'.format(rule['kind']))
    return problems


def resolve_request(config, records, period=(None, None), source='gui', source_text=''):
    """Turn a case configuration into checked planning cases.

    Each case lists its occurrences (included cases resolved, every
    occurrence once), their effective windows, the network states and the
    proposed calculation windows. A case that breaks a rule gets the status
    NOT EVALUATED with the reason; nothing is combined automatically.
    """
    problems = validate_case_config(config, None if source == 'per_outage' else MAX_CASES)
    if problems:
        raise GridLensError('The case configuration cannot be used: {}.'.format('; '.join(problems)))
    by_key = {record['key']: record for record in records}
    by_name = {record['id']: record for record in records}
    lookup = lambda key: by_key.get(key) or by_name.get(key)
    cases_by_id = {case['id']: case for case in config.get('cases') or ()}
    background = []
    request_warnings = []
    for key in config.get('background') or ():
        record = lookup(key)
        if record is None:
            request_warnings.append('fixed outage {!r} no longer exists in the project and is left out of the reference'.format(key))
        elif record not in background:
            background.append(record)
            if record.get('originally_ignored'):
                request_warnings.append('fixed outage {} is set to Ignored in PowerFactory; GridLens applies it in the reference and every case'.format(record['name']))
    background_keys = {record['key'] for record in background}
    plans = []
    # A case excluded in the case manager is neither calculated nor
    # reported; it can still be part of another case through `includes`.
    disabled = [case['id'] for case in config.get('cases') or () if case.get('enabled', True) is False]
    for case in config.get('cases') or ():
        if case['id'] in disabled:
            continue
        plan = {'id': case['id'], 'name': str(case.get('name') or case['id']), 'description': str(case.get('description') or ''),
                'members': [], 'windows': {}, 'status': PLAN_READY, 'reason': '', 'warnings': [], 'states': [],
                'calc_windows': [], 'relations': [], 'overridden': [], 'includes': list(case.get('includes') or ())}
        errors = []
        try:
            tree = _case_tree(case['id'], cases_by_id)
        except ValueError as exc:
            errors.append(str(exc))
            tree = [case['id']]
        for case_id in tree:
            part = cases_by_id[case_id]
            for key in part.get('outages') or ():
                record = lookup(key)
                if record is None:
                    errors.append('planned outage {!r} no longer exists in the project'.format(key))
                    continue
                if record in plan['members']:
                    continue
                plan['members'].append(record)
                plan['windows'][record['key']] = _occurrence_window(record, part)
                if (part.get('overrides') or {}).get(record['key']):
                    plan['overridden'].append(record)
        for required in case.get('requires') or ():
            if required not in tree:
                errors.append('case {} may only be evaluated together with case {}; define a joint case that includes both'.format(case['id'], required))
        for group in config.get('exclusive_groups') or ():
            chosen = [case_id for case_id in tree if case_id in group]
            if len(chosen) > 1:
                errors.append('cases {} are alternatives and must not be combined'.format(' and '.join(chosen)))
        if not plan['members']:
            errors.append('no planned outage is assigned')
        if plan['overridden'] and not ALLOW_OUTAGE_TIME_OVERRIDE:
            errors.append('own dates for {} are not applied: writing IntPlannedout start and end times is not verified '
                          '(ALLOW_OUTAGE_TIME_OVERRIDE is off); create a planned outage with these dates instead'.format(
                              ', '.join(record['name'] for record in plan['overridden'])))
        windows = plan['windows']
        for rule in config.get('rules') or ():
            first, second = lookup(rule.get('first')), lookup(rule.get('second'))
            if first is None or second is None:
                continue
            here = [record['key'] for record in (first, second) if record['key'] in windows]
            a, b = windows.get(first['key']), windows.get(second['key'])
            if rule['kind'] == 'together' and len(here) == 1:
                errors.append('{} and {} may only take place together'.format(first['name'], second['name']))
            if len(here) < 2 or None in (a or (None,)) + (b or (None,)):
                continue
            if rule['kind'] == 'not_overlap' and windows_overlap(a, b):
                errors.append('{} and {} must not overlap'.format(first['name'], second['name']))
            if rule['kind'] == 'order' and b[0] < a[1]:
                errors.append('{} may only start after {} has ended'.format(second['name'], first['name']))
            if rule['kind'] == 'together' and not windows_overlap(a, b):
                errors.append('{} and {} must take place at the same time'.format(first['name'], second['name']))
        members = plan['members']
        for index, left in enumerate(members):
            for right in members[index + 1:]:
                a, b = windows[left['key']], windows[right['key']]
                if None in a + b:
                    continue
                # Overlapping outages are normal planning, not a problem: only
                # their relation is recorded for the report.
                plan['relations'].append((left['name'], right['name'], interval_relation(a, b)))
        for record in members:
            window = windows[record['key']]
            if None not in window and window[1] <= window[0]:
                errors.append('the window of {} ends before it starts'.format(record['name']))
            if record['key'] in background_keys:
                plan['warnings'].append('{} is a fixed outage of the reference too; it adds nothing to this case'.format(record['name']))
            if record.get('originally_ignored'):
                plan['warnings'].append('{} is set to Ignored in PowerFactory; GridLens applies it for this case only'.format(record['name']))
            if None in window:
                plan['warnings'].append('the window of {} is not readable; the complete period is assessed'.format(record['name']))
        known = [window for window in windows.values() if None not in window]
        begin, finish = period
        if known and begin is not None and finish is not None:
            inside = [window for window in known if window[0] < finish and window[1] > begin]
            if not inside and len(known) == len(windows):
                plan['status'] = PLAN_NOT_SIMULATED
                plan['reason'] = 'No outage of this case falls into the simulated period {} to {}.'.format(
                    _format_pf_time(begin), _format_pf_time(finish))
            elif any(window[0] < begin or window[1] > finish for window in known):
                plan['warnings'].append('part of the outage time lies outside the simulated period and is not assessed')
        if errors:
            plan['status'] = PLAN_NOT_EVALUATED
            plan['reason'] = 'Not calculated: ' + '; '.join(errors) + '.'
        plan['states'] = network_states(windows)
        plan['calc_windows'] = calculation_windows(known)
        plan['fingerprint'] = plan_fingerprint(plan, background)
        plans.append(plan)
    mode = config.get('mode', QDS_WINDOW_MODE)
    return {'source': source, 'source_text': source_text or source, 'revision': config.get('revision'), 'mode': mode,
            'background': background, 'cases': plans, 'skipped': [], 'records': list(records), 'config': config,
            'optimization': None, 'warnings': request_warnings, 'disabled': disabled,
            'assessments': list(config.get('assessments') or ['n-0'])}


def case_config_path(project_key):
    folder = CASE_CONFIG_DIR or os.path.join(os.path.expanduser('~'), 'GridLens', 'cases')
    stem = re.sub(r'[^A-Za-z0-9_.-]+', '_', project_key.rsplit('\\', 1)[-1])[:40] or 'project'
    digest = hashlib.sha256(project_key.encode('utf-8')).hexdigest()[:8]
    return os.path.join(folder, '{}_{}.json'.format(stem, digest))


def load_case_config(path):
    """The saved configuration, or None when there is none; a damaged file raises.

    Only the structure is checked here, not the number of cases: a file with
    more cases than MAX_CASES (e.g. saved by GridLens 8.0) must still open in
    the case manager, where cases can be deleted. Calculating and saving it is
    refused with the reason (resolve_request, save_case_config).
    """
    if not os.path.isfile(path):
        return None
    try:
        with open(path, 'r', encoding='utf-8') as handle:
            config = json.load(handle)
    except (OSError, ValueError) as exc:
        raise GridLensError('The saved case configuration {} cannot be read: {}'.format(path, exc)) from None
    problems = validate_case_config(config, max_cases=None)
    if problems:
        raise GridLensError('The saved case configuration {} is invalid: {}'.format(path, '; '.join(problems)))
    return config


def save_case_config(path, config, user=''):
    """Write the configuration with the next revision; the project itself is not touched."""
    problems = validate_case_config(config)
    if problems:
        raise GridLensError('The case configuration was not saved: {}'.format('; '.join(problems)))
    stored = dict(config, revision=int(config.get('revision') or 0) + 1,
                  saved_at=datetime.now().astimezone().strftime('%Y-%m-%d %H:%M:%S %z'), saved_by=user)
    folder = os.path.dirname(path)
    if folder:
        os.makedirs(folder, exist_ok=True)
    temporary = path + '.tmp'
    with open(temporary, 'w', encoding='utf-8') as handle:
        json.dump(stored, handle, indent=2, sort_keys=True)
    os.replace(temporary, path)
    config['revision'] = stored['revision']
    return stored


class CaseManagerUnavailable(GridLensError):
    """tkinter or Tcl/Tk cannot open a window in this PowerFactory installation."""


MARK_IN_CASE, MARK_FIXED, MARK_FREE = '\u2611 in case', 'fixed', '\u2610'


RELATION_LABELS = (('includes', 'Also contains'), ('requires', 'Only valid with'), ('alternatives', 'Alternative to'))


RULE_LABELS = (('not_overlap', 'must not overlap'), ('order', 'second only after the first'), ('together', 'only together'))


OUTAGE_FILTERS = ('All planned outages', 'Not in this case', 'In simulated period', 'Ignored in PowerFactory')


HELP_TEXTS = {
    'includes': "Also contains (joint plan)\n"
                "This case also contains every planned outage of the cases selected here (and what those contain). "
                "All of them are applied together in the one QDS run of this case.\n"
                "Example: case 'Joint' also contains 'Line north' and 'Line south': one run with both lines out.\n"
                "The selected cases keep their own runs unless they are excluded. Change their outages once and "
                "this case follows.\n"
                "Click a case to select it (highlighted), click again to deselect; several are allowed.",
    'requires': "Only valid with (condition)\n"
                "This case makes sense only together with the cases selected here, for example a switching measure "
                "that is only allowed while another line is out.\n"
                "The case is calculated only if it also contains them: select them under 'Also contains' too, directly "
                "or through another case. Otherwise it is reported as NOT EVALUATED with the reason; GridLens never "
                "adds them on its own. Deleting a required case excludes this case.\n"
                "Click a case to select it (highlighted), click again to deselect.",
    'alternatives': "Alternative to (either - or)\n"
                    "This case and the cases selected here are alternative plans for the same work, for example the "
                    "same outage in week 10 or in week 40. Each is calculated on its own.\n"
                    "A case that contains two alternatives through 'Also contains' is not calculated and is "
                    "reported with the reason.\n"
                    "Works both ways: selecting B here also marks this case under B.\n"
                    "Click a case to select it (highlighted), click again to deselect.",
    'description': "Double-click to write or change the description of the case: Enter or a click elsewhere "
                   "applies, Escape cancels.",
    'relations': "Relations to other planning cases. Select a case in the table above, then click cases in these "
                 "lists to select or deselect them. Hover over a heading for its meaning.",
    'enabled': "Include in the calculation\n"
               "Ticked: the case is calculated and reported, in its own QDS run with the result object "
               "GridLens_<stamp>_<case>. A case with exactly the same outages and windows as another is calculated "
               "once and reported as REUSED.\n"
               "Unticked: status 'excluded'. The case stays in the configuration but is neither calculated nor "
               "reported; other cases can still contain it through 'Also contains'.",
    'case_limit': "At most {} planning cases. Each case is one more QDS run over the complete period.".format(MAX_CASES),
    'New': "Creates the next case (C1 ... C{}) with the name 'Case n'. Double-click it to rename it.".format(MAX_CASES),
    'Copy': "New case with the same planned outages, own dates and relations (also contains, only valid with, "
            "alternative to); independent afterwards.",
    'Delete': "Removes the case and every reference to it in other cases; asks first and names the cases that "
              "change. A case that is only valid with it is excluded. The planned outages stay in PowerFactory.",
    'one_per_outage': "Replaces all cases by one case per planned outage in the simulated period (GridLens 7 "
                      "behaviour), at most {}. Ignored and fixed outages get none. Asks before replacing.".format(MAX_CASES),
    'add': "Assigns all selected planned outages to the selected case at once. Same as Enter. For one outage, "
           "tick its box in the first column.\n"
           "An outage already in the case or fixed is refused with the reason.",
    'fix': "Makes the selected planned outages fixed background outages: active in the reference (Rfix) and in "
           "every case. Not possible while an outage is assigned to a case, so it never acts twice.",
    'details': "What PowerFactory holds for the planned outage: object, equipment, window, priority, status and "
               "the cases that use it. Own dates per case are entered there. Same as a double-click on the row.",
    'remove': "Ends only the assignment to this case; the planned outage in PowerFactory stays unchanged. "
              "Same as the Delete key.",
    'unfix': "The selected outages are no longer fixed; the reference becomes R0 when none is left.",
    'timeline': "Planning check only, no load flow: when the outages of this case are active. Blue: case outage, "
                "grey: fixed background outage, shaded: several outages at the same time (normal, no problem), light band: a "
                "long empty period drawn short.",
    'rule_kind': "must not overlap: a case with both outages is refused if their windows overlap.\n"
                 "second only after the first: the second may only start after the first has ended.\n"
                 "only together: a case with one of them must contain the other, at the same time.\n"
                 "Rules apply to every case; a case that breaks one is not calculated and is reported.",
    'n1': "Not available: this GridLens version has no contingency analysis. Only n-0 (QDS) is calculated.",
    'qds': "Period and time step of the active ComStatsim. Every run covers the complete period; GridLens does "
           "not change it.",
    'status_line': "Click to open Review & start: what will be calculated and every problem or warning.",
    'save': "Writes the configuration file of this project (with revision, user and time). The project is not touched.",
    'load': "Reads the saved configuration file again; unsaved changes in the window are replaced.",
    'start': "Checks the configuration, closes the window and starts the reference and one QDS run per case.",
    'cancel': "Closes the window: nothing is calculated, saved or changed in the project.",
}


COLUMN_HELP = {
    'case_name': "Double-click a case (or press F2) to rename it in place: Enter or a click elsewhere applies, "
                 "Escape cancels. The generated case ID stays.",
    'case_status': "ready: will be calculated.\n"
                   "not calculated: reported as NOT EVALUATED or NOT SIMULATED, e.g. no planned outage assigned, "
                   "an outage missing in the project, own dates, a broken relation or rule, or outside the "
                   "simulated period. The reason is on Review & start.\n"
                   "excluded: 'Include in the calculation' is unticked.",
    'case_count': "Number of planned outages assigned directly to the case (without those it also contains).",
    'mark': "Check box: tick to add the planned outage to the selected case, untick to remove it (also Space).\n"
            "\u2611 in case: part of the selected case.\n\u2610: free.\nfixed: fixed background outage of every case, "
            "cannot be ticked.",
    'outage_status': "in simulated period: the window lies in the ComStatsim period.\n"
                     "outside simulated period: has no effect in this run.\n"
                     "Ignored in PowerFactory: set to Ignored there; GridLens applies it only for a case that "
                     "contains it.",
    'prio': "Priority of the planned outage in PowerFactory.",
}


def _parse_time(text):
    """'YYYY-MM-DD HH:MM' in local time -> epoch seconds."""
    return time.mktime(datetime.strptime(text.strip(), '%Y-%m-%d %H:%M').timetuple())


def timeline_scale(windows, width, gap_share=0.12):
    """Axis of the case timeline: x(t) for the given windows, long empty gaps shortened.

    Busy periods keep their true proportions; a gap gets at most `gap_share`
    of the busy time, so FS1 in KW10 and FS2 in KW40 both stay readable. Returns
    (x, breaks): the mapping and the x ranges where the axis was shortened.
    """
    spans = merge_intervals([(start, end) for start, end in windows if start is not None and end is not None and end > start])
    if not spans or width <= 0:
        return None, []
    busy = sum(end - start for start, end in spans)
    cap = busy * gap_share
    pieces = []
    for index, (start, end) in enumerate(spans):
        pieces.append((start, end, float(end - start), False))
        if index + 1 < len(spans):
            gap = spans[index + 1][0] - end
            pieces.append((end, spans[index + 1][0], float(min(gap, cap)), gap > cap))
    scale = width / sum(weight for _, _, weight, _ in pieces)
    edges, breaks, position = [], [], 0.0
    for start, end, weight, shortened in pieces:
        edges.append((start, end, position, position + weight * scale))
        if shortened:
            breaks.append((position, position + weight * scale))
        position += weight * scale

    def x(moment):
        if moment <= edges[0][0]:
            return 0.0
        for start, end, left, right in edges:
            if moment <= end:
                return left + (moment - start) / float(end - start) * (right - left) if end > start else left
        return float(width)
    return x, breaks


def _sort_key(value):
    """Numbers by value, everything else alphabetically, numbers first."""
    number = finite_number(value) if not isinstance(value, str) or value.strip() else None
    if number is not None:
        return (0, number, '')
    return (1, 0, str(value).casefold())


def filter_rows(rows, filters):
    """The (key, cells) rows that match every filter.

    `filters` maps a column index to ('contains', text) - the cell contains
    the text, ignoring case - or ('equals', value) - the cell is exactly the
    value. Filtering never changes the rows themselves.
    """
    def matches(cells):
        for column, (mode, wanted) in filters.items():
            cell = str(cells[column])
            if mode == 'equals' and cell != str(wanted):
                return False
            if mode == 'contains' and str(wanted).casefold() not in cell.casefold():
                return False
        return True
    return [row for row in rows if matches(row[1])]


def sort_rows(rows, column, descending=False):
    """Rows sorted by one column; equal cells keep their order."""
    return sorted(rows, key=lambda row: _sort_key(row[1][column]), reverse=descending)


class CaseEditor:
    """Every editing step of the case manager, without a window.

    The dialog only shows this state and forwards clicks, so the editing
    rules can be tested without Tk. The configuration is a private copy; it
    reaches the caller only through "Start calculation".
    """

    def __init__(self, records, config, period, qds_text=''):
        self.records = list(records)
        self.by_key = {record['key']: record for record in self.records}
        self.period = period
        self.qds_text = qds_text or qds_period_text(period)
        self._checked_state = None
        self.load(config)

    def load(self, config):
        """Replace the edited configuration, e.g. by the saved one."""
        self.config = json.loads(json.dumps(config))
        for name in ('cases', 'background', 'rules', 'exclusive_groups'):
            self.config.setdefault(name, [])
        self.config.setdefault('assessments', ['n-0'])
        # The case manager offers no time optimisation: every run covers the
        # complete ComStatsim period.
        self.config['mode'] = 'conservative'

    # --- cases ---------------------------------------------------------------
    def case(self, case_id):
        return next((case for case in self.config['cases'] if case['id'] == case_id), None)

    def case_ids(self):
        return [case['id'] for case in self.config['cases']]

    def case_rows(self):
        """(id, include in calculation, name, number of planned outages) per case."""
        return [(case['id'], case.get('enabled', True), case.get('name', ''), len(case.get('outages') or ()))
                for case in self.config['cases']]

    def next_case_id(self):
        """The generated ID of the next case: the lowest free C1, C2, ...; the engineer never types one."""
        used = set(self.case_ids())
        number = 1
        while 'C{}'.format(number) in used:
            number += 1
        return 'C{}'.format(number)

    def limit_problem(self):
        """Why no further case can be created; None while fewer than MAX_CASES exist."""
        if len(self.config['cases']) >= MAX_CASES:
            return 'At most {} planning cases are possible. Delete or reuse a case first.'.format(MAX_CASES)
        return None

    def case_label(self, case_id):
        """The name a person sees; the generated ID only where two cases share a name."""
        case = self.case(case_id)
        if case is None:
            return case_id or ''
        name = case.get('name') or case_id
        twins = sum(1 for other in self.config['cases'] if (other.get('name') or other['id']) == name)
        return name if twins == 1 else '{} ({})'.format(name, case_id)

    def add_case(self, name=''):
        """A new case with a generated ID; (id, None), or (None, problem) at the limit."""
        problem = self.limit_problem()
        if problem:
            return None, problem
        identifier = self.next_case_id()
        self.config['cases'].append({'id': identifier, 'name': name.strip() or 'Case ' + identifier[1:], 'description': '',
                                     'enabled': True, 'outages': [], 'includes': [], 'requires': [], 'overrides': {}})
        return identifier, None

    def rename_case(self, case_id, name):
        """Only the name changes; the ID that relations and result objects use stays."""
        case = self.case(case_id)
        if case is not None and name.strip():
            case['name'] = name.strip()

    def set_description(self, case_id, text):
        case = self.case(case_id)
        if case is not None:
            case['description'] = text.strip()

    def set_enabled(self, case_id, enabled):
        case = self.case(case_id)
        if case is not None:
            case['enabled'] = bool(enabled)

    def copy_case(self, case_id):
        """A new case with the same planned outages, own dates and relations; (id, None) or (None, problem)."""
        case = self.case(case_id)
        if case is None:
            return None, 'Select a planning case first.'
        problem = self.limit_problem()
        if problem:
            return None, problem
        identifier = self.next_case_id()
        copy = json.loads(json.dumps(case))
        copy.update(id=identifier, name=case.get('name', '') + ' (copy)')
        self.config['cases'].append(copy)
        self.set_alternatives(identifier, self.alternatives(case_id))
        return identifier, None

    def delete_effects(self, case_id):
        """What deleting `case_id` changes in other cases, as lines for the confirmation."""
        lines = []
        for field, one, many in (('includes', 'no longer contains its planned outages', 'no longer contain its planned outages'),
                                 ('requires', 'is only valid with it and will be excluded from the calculation',
                                  'are only valid with it and will be excluded from the calculation')):
            names = [self.case_label(other['id']) for other in self.config['cases'] if case_id in (other.get(field) or ())]
            if names:
                lines.append('{} {}.'.format(', '.join(names), one if len(names) == 1 else many))
        alternatives = [self.case_label(item) for item in self.alternatives(case_id)]
        if alternatives:
            lines.append('{} {} it as alternative.'.format(', '.join(alternatives), 'loses' if len(alternatives) == 1 else 'lose'))
        return lines

    def delete_case(self, case_id):
        """Remove a case and every reference to it; the planned outages themselves are untouched.

        A case that is only valid with the deleted one is excluded instead of
        becoming valid on its own: its condition can no longer be met.
        """
        case = self.case(case_id)
        if case is None:
            return
        for other in self.config['cases']:
            if case_id in (other.get('requires') or ()):
                other['enabled'] = False
        self.config['cases'].remove(case)
        for other in self.config['cases']:
            for field in ('includes', 'requires'):
                other[field] = [item for item in other.get(field) or () if item != case_id]
        self._set_groups([[item for item in group if item != case_id] for group in self.config['exclusive_groups']])

    def one_case_per_outage(self):
        """One case per planned outage in the simulated period, at most MAX_CASES; a note when outages were left out."""
        candidates = [record for record in self.records if self.outage_status(record) == 'in simulated period'
                      and record['key'] not in self.config['background']]
        self.config['cases'] = []
        self.config['exclusive_groups'] = []
        for record in candidates[:MAX_CASES]:
            identifier, _ = self.add_case(record['id'])
            self.case(identifier)['outages'] = [record['key']]
        if len(candidates) > MAX_CASES:
            return 'Only the first {} of {} planned outages got a case (at most {} cases).'.format(MAX_CASES, len(candidates), MAX_CASES)
        return None

    # --- planned outages of a case ---------------------------------------------
    def members(self, case_id):
        case = self.case(case_id)
        return [self.by_key[key] for key in (case.get('outages') or ()) if key in self.by_key] if case else []

    def unknown_members(self, case_id):
        """Keys of the case that no longer exist in the project."""
        case = self.case(case_id)
        return [key for key in (case.get('outages') or ()) if key not in self.by_key] if case else []

    def window_text(self, case, record):
        override = (case.get('overrides') or {}).get(record['key']) if case else None
        if override:
            return _format_pf_time(override[0]) + ' *', _format_pf_time(override[1]) + ' *'
        return record.get('start_time') or '?', record.get('end_time') or '?'

    def member_rows(self, case_id):
        """(key, cells) of the case's planned outages: name, equipment, start, end, priority."""
        case = self.case(case_id)
        rows = []
        for record in self.members(case_id):
            start, end = self.window_text(case, record)
            rows.append((record['key'], (record['id'], clip_text(record.get('equipment_name') or '-', 60), start, end,
                                         int(record.get('priority') or 0))))
        return rows

    def add_outage(self, case_id, key):
        """Assign a planned outage to a case; a problem as text, else None."""
        case = self.case(case_id)
        if case is None:
            return 'Select a planning case first.'
        if key not in self.by_key:
            return 'This planned outage no longer exists in the project.'
        name = self.by_key[key]['id']
        if key in (case.get('outages') or ()):
            return '{} is already part of {}.'.format(name, self.case_label(case_id))
        if key in self.config['background']:
            return '{} is a fixed background outage and already active in every case.'.format(name)
        case.setdefault('outages', []).append(key)
        return None

    def toggle_outage(self, case_id, key):
        """The check box in the outage list: adds the outage to the case, or removes it when it is part of it.

        A problem as text (no case, fixed outage, missing outage), else None.
        """
        case = self.case(case_id)
        if case is not None and key in (case.get('outages') or ()):
            self.remove_outage(case_id, key)
            return None
        return self.add_outage(case_id, key)

    def remove_outage(self, case_id, key):
        """Remove the assignment only; the planned outage in PowerFactory stays as it is."""
        case = self.case(case_id)
        if case is not None and key in (case.get('outages') or ()):
            case['outages'].remove(key)
            (case.get('overrides') or {}).pop(key, None)

    def set_own_dates(self, case_id, key, start_text, end_text):
        """Record own dates ('YYYY-MM-DD HH:MM'); an empty start removes them. A problem as text, else None."""
        case = self.case(case_id)
        if case is None or key not in (case.get('outages') or ()):
            return 'Select a planned outage that belongs to the selected case.'
        overrides = case.setdefault('overrides', {})
        if not start_text.strip():
            overrides.pop(key, None)
            return None
        try:
            window = [_parse_time(start_text), _parse_time(end_text or '')]
        except (ValueError, OverflowError):
            return 'Use the format YYYY-MM-DD HH:MM.'
        if window[1] <= window[0]:
            return 'The end must lie after the start.'
        overrides[key] = window
        return None

    # --- fixed background outages ------------------------------------------------
    def fixed(self):
        return [self.by_key[key] for key in self.config['background'] if key in self.by_key]

    def cases_with(self, key):
        return [case['id'] for case in self.config['cases'] if key in (case.get('outages') or ())]

    def set_fixed(self, key, fixed):
        """Mark or unmark a fixed background outage; a problem as text, else None."""
        if key not in self.by_key:
            return 'This planned outage no longer exists in the project.'
        background = self.config['background']
        if not fixed:
            if key in background:
                background.remove(key)
            return None
        if key in background:
            return None
        cases = self.cases_with(key)
        if cases:
            return ('{} is assigned to {}. A fixed outage is active in every case; remove it from {} first.'.format(
                self.by_key[key]['id'], ', '.join(self.case_label(item) for item in cases), 'that case' if len(cases) == 1 else 'those cases'))
        background.append(key)
        return None

    def counts_text(self, case_id):
        count, fixed = len(self.members(case_id)), len(self.fixed())
        return '{} · {}'.format(_counted(count, 'case outage', 'case outages'),
                                _counted(fixed, 'fixed background outage', 'fixed background outages'))

    # --- available planned outages -----------------------------------------------
    def outage_status(self, record):
        begin, finish = self.period
        start, end = record['window']
        if record.get('originally_ignored'):
            return 'Ignored in PowerFactory'
        if begin is not None and start is not None and end is not None and (end <= begin or start >= finish):
            return 'outside simulated period'
        return 'in simulated period'

    def available_rows(self, case_id, search='', show=OUTAGE_FILTERS[0]):
        """(key, cells) of every planned outage matching the search: mark, name, equipment, start, end, status."""
        case = self.case(case_id)
        members = set(case.get('outages') or ()) if case else set()
        needle = search.strip().casefold()
        rows = []
        for record in self.records:
            text = '{} {}'.format(record['id'], record.get('equipment_name') or '').casefold()
            if needle and needle not in text:
                continue
            status = self.outage_status(record)
            if show == OUTAGE_FILTERS[1] and record['key'] in members:
                continue
            if show == OUTAGE_FILTERS[2] and status != 'in simulated period':
                continue
            if show == OUTAGE_FILTERS[3] and status != 'Ignored in PowerFactory':
                continue
            mark = MARK_IN_CASE if record['key'] in members else MARK_FIXED if record['key'] in self.config['background'] else MARK_FREE
            rows.append((record['key'], (mark, record['id'], clip_text(record.get('equipment_name') or '-', 60),
                                         record.get('start_time') or '?', record.get('end_time') or '?', status)))
        return rows

    def details(self, key):
        """(label, value) lines about one planned outage, as read from PowerFactory."""
        record = self.by_key[key]
        return [('Planned outage', record['id']), ('PowerFactory object', key), ('Class', record.get('source_class') or '-'),
                ('Equipment', record.get('equipment_name') or '-'), ('Equipment types', record.get('equipment_type') or '-'),
                ('Switching actions', record.get('switching_actions') or '-'), ('Start', record.get('start_time') or '?'),
                ('End', record.get('end_time') or '?'), ('Priority', str(int(record.get('priority') or 0))),
                ('Status', self.outage_status(record)), ('Fixed background outage', 'yes' if key in self.config['background'] else 'no'),
                ('Used in cases', ', '.join(self.case_label(item) for item in self.cases_with(key)) or 'none')]

    # --- relations between cases -----------------------------------------------
    def relation_options(self, case_id):
        """(id, name) of every other case."""
        return [(case['id'], self.case_label(case['id'])) for case in self.config['cases'] if case['id'] != case_id]

    def includes(self, case_id):
        return list((self.case(case_id) or {}).get('includes') or ())

    def requires(self, case_id):
        return list((self.case(case_id) or {}).get('requires') or ())

    def set_includes(self, case_id, ids):
        case = self.case(case_id)
        if case is not None:
            case['includes'] = [item for item in ids if item != case_id and self.case(item) is not None]

    def set_requires(self, case_id, ids):
        case = self.case(case_id)
        if case is not None:
            case['requires'] = [item for item in ids if item != case_id and self.case(item) is not None]

    def alternatives(self, case_id):
        """Cases that are alternatives to `case_id` (share an exclusive group with it)."""
        found = []
        for group in self.config['exclusive_groups']:
            if case_id in group:
                found.extend(item for item in group if item != case_id and item not in found)
        return found

    def set_alternatives(self, case_id, ids):
        """Make exactly `ids` the alternatives of `case_id`; groups of other cases keep their meaning."""
        groups = [[item for item in group if item != case_id] for group in self.config['exclusive_groups']]
        groups += [[case_id, item] for item in ids if item != case_id and self.case(item) is not None]
        self._set_groups(groups)

    def _set_groups(self, groups):
        unique = []
        for group in groups:
            members = list(dict.fromkeys(group))
            if len(members) >= 2 and sorted(members) not in [sorted(item) for item in unique]:
                unique.append(members)
        self.config['exclusive_groups'] = unique

    # --- rules between planned outages -------------------------------------------
    def outage_choices(self):
        """(label, key) of every planned outage, sorted; the PowerFactory path is added where names repeat."""
        counts = {}
        for record in self.records:
            counts[record['id']] = counts.get(record['id'], 0) + 1
        choices = [(record['id'] if counts[record['id']] == 1 else '{} ({})'.format(record['id'], record['key']), record['key'])
                   for record in self.records]
        return sorted(choices, key=lambda item: item[0].casefold())

    def rule_rows(self):
        labels = dict(RULE_LABELS)
        names = {key: label for label, key in self.outage_choices()}
        name = lambda key: names.get(key, key)
        return [(index, (name(rule['first']), labels.get(rule['kind'], rule['kind']), name(rule['second'])))
                for index, rule in enumerate(self.config['rules'])]

    def add_rule(self, kind, first, second):
        """A rule between two planned outages; a problem as text, else None."""
        if kind not in RULE_KINDS:
            return 'Choose a rule.'
        if first not in self.by_key or second not in self.by_key:
            return 'Choose two planned outages.'
        if first == second:
            return 'A rule needs two different planned outages.'
        rule = {'kind': kind, 'first': first, 'second': second}
        if rule in self.config['rules']:
            return 'This rule exists already.'
        self.config['rules'].append(rule)
        return None

    def remove_rule(self, index):
        if 0 <= index < len(self.config['rules']):
            del self.config['rules'][index]

    # --- assessment and preview ------------------------------------------------
    def set_assessments(self, n0, n1):
        """The requested assessments; a problem as text, else None."""
        if not n0 and not n1:
            return 'Select at least one assessment.'
        if n1:
            return 'The n-1 contingency analysis is not available in this GridLens version.'
        self.config['assessments'] = ['n-0']
        return None

    def request(self):
        return resolve_request(self.config, self.records, self.period, 'gui')

    def checked(self):
        """(problems, request or None) of the configuration as it is now; resolved once per change.

        Every refresh reads statuses, problems and the preview; they share one
        resolution instead of resolving the whole configuration each.
        """
        snapshot = json.dumps(self.config, sort_keys=True)
        if self._checked_state is None or self._checked_state[0] != snapshot:
            problems = validate_case_config(self.config)
            self._checked_state = (snapshot, problems, None if problems else self.request())
        return self._checked_state[1], self._checked_state[2]

    def case_statuses(self):
        """Case id -> 'ready', 'not calculated' or 'excluded', as the calculation would see it."""
        problems, request = self.checked()
        if problems:
            return {case['id']: 'excluded' if case.get('enabled', True) is False else 'not calculated'
                    for case in self.config['cases']}
        statuses = {plan['id']: 'ready' if plan['status'] == PLAN_READY else 'not calculated' for plan in request['cases']}
        statuses.update({identifier: 'excluded' for identifier in request['disabled']})
        return statuses

    def problem_rows(self):
        """(where, problem) for everything that stops or limits the calculation."""
        problems, request = self.checked()
        if problems:
            return [('configuration', problem) for problem in problems]
        rows = [(self.case_label(plan['id']), plan['reason']) for plan in request['cases'] if plan['status'] != PLAN_READY]
        rows += [(self.case_label(plan['id']), 'Warning: ' + warning) for plan in request['cases'] for warning in plan['warnings']]
        rows += [('fixed outages', warning) for warning in request['warnings']]
        return rows

    def fixed_rows(self):
        """(key, cells) of the fixed background outages: name, equipment, start, end, status."""
        return [(record['key'], (record['id'], clip_text(record.get('equipment_name') or '-', 60), record.get('start_time') or '?',
                                 record.get('end_time') or '?', self.outage_status(record))) for record in self.fixed()]

    def timeline(self, case_id):
        """(name, start, end, kind) of the case's and the fixed outages with readable windows, and the overlaps."""
        case = self.case(case_id)
        items = []
        for record in self.members(case_id):
            start, end = _occurrence_window(record, case)
            if start is not None and end is not None and end > start:
                items.append((record['id'], start, end, 'case'))
        for record in self.fixed():
            start, end = record['window']
            if start is not None and end is not None and end > start:
                items.append((record['id'], start, end, 'fixed'))
        windows = {index: (start, end) for index, (_, start, end, _) in enumerate(items)}
        overlaps = [(start, end) for start, end, active in network_states(windows) if len(active) > 1]
        return items, overlaps

    def summary(self):
        """Short (label, value) lines of what "Start calculation" would calculate, and the problems found."""
        problems, request = self.checked()
        if problems:
            return [('QDS period', self.qds_text + ' (from the active ComStatsim)')], problems
        plans = request['cases']
        ready = [plan for plan in plans if plan['status'] == PLAN_READY]
        problems = ['{}: {}'.format(self.case_label(plan['id']), plan['reason']) for plan in plans if plan['status'] != PLAN_READY]
        problems += request['warnings']
        reused = len(ready) - len({plan['fingerprint'] for plan in ready})
        outages = {record['key'] for plan in plans for record in plan['members']}
        background = request['background']
        lines = [
            ('Cases selected', '{} of {}{}'.format(len(plans), len(self.config['cases']),
                                                   ': ' + ', '.join(self.case_label(plan['id']) for plan in plans) if plans else '')),
            ('Valid cases', str(len(ready))),
            ('Planned outages in cases', str(len(outages))),
            ('Fixed background outages', ', '.join(record['id'] for record in background) or 'none'),
            ('Reference', 'Rfix - with the fixed background outages' if background else 'R0 - no planned outage'),
            ('QDS period', self.qds_text + ' (from the active ComStatsim)'),
            ('Assessment', 'n-0 quasi-dynamic simulation'),
            ('Calculation runs', '{} reference + {} case run(s){}'.format(
                1 if RUN_REFERENCE_CASE else 0, len(ready) - reused,
                ', {} identical case(s) reused'.format(reused) if reused else '')),
        ]
        return lines, problems


def window_geometry(screen_width, screen_height, share=0.86, largest=(1480, 860)):
    """'WxH+X+Y' of the case manager: a share of the screen, at most `largest`, centred."""
    width = max(min(int(screen_width * share), largest[0]), min(900, screen_width))
    height = max(min(int(screen_height * share), largest[1]), min(600, screen_height))
    width, height = min(width, screen_width), min(height, screen_height)
    return '{}x{}+{}+{}'.format(width, height, max((screen_width - width) // 2, 0), max((screen_height - height) // 2 - 20, 0))


def minimum_window_size(screen_width, screen_height):
    """The smallest useful window, never larger than the screen."""
    return min(1000, screen_width), min(620, screen_height)


def column_widths(columns, width, flexible_share=0.6):
    """Pixel width per column for a table `width` wide; columns are (base width, stretches).

    Fixed columns keep their base width and stretching columns share the rest,
    but a stretching column never gets less than `flexible_share` of its base:
    when the table is too narrow for that, every column shrinks in proportion.
    The widths add up to `width`.
    """
    fixed = sum(base for base, stretch in columns if not stretch)
    flexible = sum(base for base, stretch in columns if stretch)
    least = flexible * flexible_share
    if not flexible or width >= fixed + least:
        spare = width - fixed
        widths = [int(spare * base / flexible) if stretch else base for base, stretch in columns] if flexible else \
            [int(width * base / max(fixed, 1)) for base, _ in columns]
    else:
        scale = width / float(fixed + least)
        widths = [int(base * (flexible_share if stretch else 1.0) * scale) for base, stretch in columns]
    widths[-1] += width - sum(widths)
    return widths


class Tooltip:
    """A short explanation that appears while the mouse rests on a widget."""

    DELAY, WRAP = 450, 380
    BACKGROUND, BORDER = '#fffdf2', '#c9b977'

    def __init__(self, tk, widget, text):
        self.tk = tk
        self.widget = widget
        self.text = text
        self.window = None
        self._after = None
        widget.bind('<Enter>', self._schedule, add='+')
        widget.bind('<Leave>', self.hide, add='+')
        widget.bind('<ButtonPress>', self.hide, add='+')
        widget.bind('<KeyPress>', self.hide, add='+')

    def _schedule(self, _event=None):
        self._cancel()
        self._after = self.widget.after(self.DELAY, self.show)

    def _cancel(self):
        if self._after is not None:
            try:
                self.widget.after_cancel(self._after)
            except Exception:
                pass
            self._after = None

    def show(self):
        self._after = None
        if self.window is not None or not self.text:
            return
        tk = self.tk
        window = tk.Toplevel(self.widget)
        window.wm_overrideredirect(True)
        tk.Label(window, text=self.text, justify='left', anchor='w', wraplength=self.WRAP, background=self.BACKGROUND,
                 foreground='#1f2933', relief='solid', borderwidth=1, highlightbackground=self.BORDER,
                 padx=8, pady=6).pack()
        window.update_idletasks()
        # Below the widget, kept on the screen.
        x = min(self.widget.winfo_rootx() + 12, self.widget.winfo_screenwidth() - window.winfo_reqwidth() - 8)
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 4
        if y + window.winfo_reqheight() > self.widget.winfo_screenheight() - 8:
            y = self.widget.winfo_rooty() - window.winfo_reqheight() - 4
        window.wm_geometry('+{}+{}'.format(max(x, 0), max(y, 0)))
        self.window = window

    def hide(self, _event=None):
        self._cancel()
        if self.window is not None:
            try:
                self.window.destroy()
            except Exception:
                pass
            self.window = None


class FilterTable:
    """A table with a header that sorts on click and a filter row directly under it.

    The Treeview draws only the rows; header labels and filter inputs sit in
    two strips above it and are laid out on the same column widths, so a
    filter always stands under its column. A text column filters by "contains"
    (any case), a column with choices by an exact value. Filtering and sorting
    change only what is shown, never the rows.
    """

    ALL = 'All'
    HEADER_HEIGHT, FILTER_HEIGHT = 24, 28

    def __init__(self, dialog, parent, columns, height=8, selectmode='extended', tag_column=None, tips=None):
        """`columns`: (id, heading, width, stretch, choices); choices None for text, else labels or (label, value) pairs.

        `tips`: hover text per column id, shown on the heading together with how sorting works.
        """
        tk, ttk = dialog.tk, dialog.ttk
        self.dialog = dialog
        self.columns = columns
        self.rows = []
        self.sort_column, self.descending = None, False
        self.tag_column = tag_column
        self._pending = None
        self.frame = ttk.Frame(parent, style='Card.TFrame')
        self.frame.columnconfigure(0, weight=1)
        self.frame.rowconfigure(2, weight=1)
        self.header = tk.Frame(self.frame, background=dialog.HEADER, height=self.HEADER_HEIGHT, highlightthickness=0)
        self.header.grid(row=0, column=0, columnspan=2, sticky='ew')
        self.filter_bar = tk.Frame(self.frame, background=dialog.FILTER, height=self.FILTER_HEIGHT, highlightthickness=0)
        self.filter_bar.grid(row=1, column=0, columnspan=2, sticky='ew')
        self.tree = ttk.Treeview(self.frame, columns=[column[0] for column in columns], show='', height=height,
                                 selectmode=selectmode)
        self.tree.grid(row=2, column=0, sticky='nsew')
        scroll = ttk.Scrollbar(self.frame, orient='vertical', command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        scroll.grid(row=2, column=1, sticky='ns')
        footer = ttk.Frame(self.frame, style='Card.TFrame')
        footer.grid(row=3, column=0, columnspan=2, sticky='ew', pady=(3, 0))
        self.count = ttk.Label(footer, text='', style='Muted.TLabel')
        self.count.grid(row=0, column=0, sticky='w')
        self.clear = ttk.Label(footer, text='Clear filters', style='Link.TLabel', cursor='hand2')
        self.clear.grid(row=0, column=1, sticky='w', padx=(10, 0))
        self.clear.bind('<Button-1>', lambda _event: self.clear_filters())
        self.labels, self.inputs, self.values, self.choice_values = [], [], [], []
        for index, (_, heading, _, _, choices) in enumerate(columns):
            label = tk.Label(self.header, text=heading, anchor='w', background=dialog.HEADER, foreground=dialog.TEXT,
                             font=dialog.bold_font, padx=6, cursor='hand2')
            label.bind('<Button-1>', lambda _event, column=index: self.toggle_sort(column))
            variable = tk.StringVar(value=self.ALL if choices else '')
            if choices:
                pairs = [item if isinstance(item, tuple) else (item, item) for item in choices]
                widget = ttk.Combobox(self.filter_bar, textvariable=variable, values=[self.ALL] + [label_ for label_, _ in pairs],
                                      state='readonly', style='Filter.TCombobox')
                widget.bind('<<ComboboxSelected>>', lambda _event: self.render())
                self.choice_values.append(dict(pairs))
            else:
                widget = ttk.Entry(self.filter_bar, textvariable=variable, style='Filter.TEntry')
                variable.trace_add('write', lambda *_args: self._schedule())
                self.choice_values.append(None)
            tip = (tips or {}).get(columns[index][0])
            dialog.tip(label, (tip + '\n\n' if tip else '') + 'Click the heading to sort, click again to reverse.')
            dialog.tip(widget, 'Shows only rows with this {}.'.format(heading) if choices else
                       'Shows only rows whose {} contains this text (any case).'.format(heading))
            self.labels.append(label)
            self.inputs.append(widget)
            self.values.append(variable)
        self.tree.bind('<Configure>', lambda _event: self.layout())

    def grid(self, **options):
        self.frame.grid(**options)

    def layout(self):
        """Give the columns their widths and put each header label and filter exactly above its column."""
        width = self.tree.winfo_width()
        if width <= 1:
            return
        widths = column_widths([(base, stretch) for _, _, base, stretch, _ in self.columns], width)
        x = 0
        for index, (name, _, _, _, _) in enumerate(self.columns):
            column_width = widths[index]
            self.tree.column(name, width=column_width, minwidth=20, stretch=False)
            self.labels[index].place(x=x, y=0, width=column_width, height=self.HEADER_HEIGHT)
            self.inputs[index].place(x=x + 2, y=3, width=max(26, column_width - 4), height=self.FILTER_HEIGHT - 6)
            x += column_width

    def _schedule(self):
        # Filter after a short pause so that typing stays responsive with many rows.
        if self._pending is not None:
            try:
                self.dialog.root.after_cancel(self._pending)
            except Exception:
                pass
        self._pending = self.dialog.root.after(120, self.render)

    def active_filters(self):
        filters = {}
        for index, variable in enumerate(self.values):
            text = variable.get()
            choices = self.choice_values[index]
            if choices is None and text.strip():
                filters[index] = ('contains', text.strip())
            elif choices is not None and text and text != self.ALL:
                filters[index] = ('equals', choices.get(text, text))
        return filters

    def set_rows(self, rows):
        rows = list(rows)
        if rows == self.rows and self.tree.get_children():
            return  # nothing changed: keep the rows, the selection and the scroll position
        self.rows = rows
        self.render()

    def render(self):
        if self._pending is not None:
            # A direct render makes the debounced one pending from typing unnecessary.
            try:
                self.dialog.root.after_cancel(self._pending)
            except Exception:
                pass
            self._pending = None
        filters = self.active_filters()
        rows = filter_rows(self.rows, filters)
        if self.sort_column is not None:
            rows = sort_rows(rows, self.sort_column, self.descending)
        keep = set(self.tree.selection())
        self.tree.delete(*self.tree.get_children())
        for key, cells in rows:
            tag = cells[self.tag_column] if self.tag_column is not None and cells[self.tag_column] else None
            self.tree.insert('', 'end', iid=key, values=cells, tags=(tag,) if tag else ())
        still = [key for key in keep if self.tree.exists(key)]
        if still:
            self.tree.selection_set(still)
        self.count.configure(text='{} of {} shown'.format(len(rows), len(self.rows)) if filters else '{} shown'.format(len(rows)))
        if filters:
            self.clear.grid()
        else:
            self.clear.grid_remove()
        for index, label in enumerate(self.labels):
            arrow = '' if index != self.sort_column else (' ▼' if self.descending else ' ▲')
            label.configure(text=self.columns[index][1] + arrow)

    def toggle_sort(self, column):
        if self.sort_column == column:
            self.descending = not self.descending
        else:
            self.sort_column, self.descending = column, False
        self.render()

    def clear_filters(self):
        for index, variable in enumerate(self.values):
            variable.set(self.ALL if self.choice_values[index] is not None else '')
        self.render()

    def selection(self):
        return self.tree.selection()


class CaseManagerDialog:
    """The tkinter window of the case manager; all state lives in a CaseEditor.

    Three tabs: "Workspace" (left to right: every available planned outage,
    the planned outages of the selected case, the planning cases), "Fixed background & rules"
    and "Review & start". A status line and the action bar stay visible on
    every tab. Every table filters per column. The window only configures the
    calculation; results are the PDF report.
    """

    BACKGROUND, CARD, TEXT, MUTED = '#eef1f5', '#ffffff', '#1f2933', '#5f6b7a'
    ACCENT, ACCENT_ACTIVE, SELECTED, PROBLEM = '#2f6db3', '#245a96', '#d6e4f5', '#b42318'
    HEADER, FILTER, BORDER = '#e4e9f0', '#f6f8fa', '#d4dae2'
    FIXED, OVERLAP, GAP = '#8a94a3', '#dbe6f5', '#eceff3'
    TAB_FIXED, TAB_REVIEW = 'Fixed background & rules', 'Review & start'

    def __init__(self, root, editor, config_path, user, tk_modules):
        self.root = root
        self.editor = editor
        self.config_path = config_path
        self.user = user
        self.tk, self.ttk, self.messagebox, self.simpledialog = tk_modules
        self.selected = None
        self.outcome = None
        self._relation_lists = {}
        self._preview_labels = []
        self.inline_edit = None
        self.tooltips = []
        self.bold_font = 'TkDefaultFont'

    def tip(self, widget, text):
        """Explain `widget` on hover; returns the Tooltip."""
        tooltip = Tooltip(self.tk, widget, text)
        self.tooltips.append(tooltip)
        return tooltip

    def tip_text(self, widget):
        return '\n'.join(tooltip.text for tooltip in self.tooltips if tooltip.widget is widget)

    # --- window -----------------------------------------------------------------
    def build(self):
        ttk, root = self.ttk, self.root
        self._style()
        root.title('GridLens {} - Case Manager'.format(PUBLISHER_VERSION))
        root.geometry(window_geometry(root.winfo_screenwidth(), root.winfo_screenheight()))
        root.minsize(*minimum_window_size(root.winfo_screenwidth(), root.winfo_screenheight()))
        root.configure(background=self.BACKGROUND)
        root.columnconfigure(0, weight=1)
        root.rowconfigure(0, weight=1)
        self.notebook = ttk.Notebook(root)
        self.notebook.grid(row=0, column=0, sticky='nsew', padx=10, pady=(10, 0))
        workspace = ttk.Frame(self.notebook, padding=(0, 8, 0, 0))
        overview = ttk.Frame(self.notebook, padding=(0, 8, 0, 0))
        review = ttk.Frame(self.notebook, padding=(0, 8, 0, 0))
        self.notebook.add(workspace, text='Workspace')
        self.notebook.add(overview, text=self.TAB_FIXED)
        self.notebook.add(review, text=self.TAB_REVIEW)
        self.review_tab = review
        self._build_workspace(workspace)
        self._build_fixed_and_rules(overview)
        self._build_review(review)
        bottom = ttk.Frame(root, padding=(10, 8, 10, 10))
        bottom.grid(row=1, column=0, sticky='ew')
        bottom.columnconfigure(2, weight=1)
        for column, (text, command, key, style) in enumerate((
                ('Save configuration', self.save, 'save', 'TButton'), ('Load saved configuration', self.load_saved, 'load', 'TButton'),
                (None, None, None, None), ('Cancel', self.cancel, 'cancel', 'TButton'),
                ('Start calculation', self.start, 'start', 'Accent.TButton'))):
            if text is None:
                self.status_line = ttk.Label(bottom, text='', style='Status.TLabel', cursor='hand2')
                self.status_line.grid(row=0, column=column, sticky='e', padx=12)
                self.status_line.bind('<Button-1>', lambda _event: self.notebook.select(self.review_tab))
                self.tip(self.status_line, HELP_TEXTS['status_line'])
                continue
            button = ttk.Button(bottom, text=text, style=style, command=command)
            button.grid(row=0, column=column, padx=(0, 6) if column in (0, 3) else 0)
            self.tip(button, HELP_TEXTS[key])
        root.protocol('WM_DELETE_WINDOW', self.cancel)
        root.bind('<Escape>', self.on_escape)
        ids = self.editor.case_ids()
        self.refresh_all(ids[0] if ids else None)
        self.root.update_idletasks()
        self.place_dividers()

    def place_dividers(self):
        """Start with available outages : case outages : cases = 40 : 38 : 22; the engineer can drag them."""
        width = self.panes.winfo_width()
        if width > 100:
            self.panes.sashpos(0, int(width * 0.40))
            self.panes.sashpos(1, int(width * 0.78))

    def report_error(self, kind, value, _trace):
        # Tk swallows exceptions of button callbacks; show them instead, the
        # window stays open and nothing has been calculated.
        try:
            self.messagebox.showerror('GridLens Case Manager', '{}: {}'.format(kind.__name__, value), parent=self.root)
        except Exception:
            pass

    def _style(self):
        style = self.ttk.Style(self.root)
        if 'clam' in style.theme_names():
            style.theme_use('clam')
        try:
            family = self.tk.font.nametofont('TkDefaultFont').actual()['family']
        except Exception:
            family = 'TkDefaultFont'
        self.bold_font = (family, 9, 'bold')
        style.configure('.', background=self.BACKGROUND, foreground=self.TEXT)
        style.configure('TFrame', background=self.BACKGROUND)
        style.configure('Card.TFrame', background=self.CARD)
        style.configure('TLabel', background=self.CARD, foreground=self.TEXT)
        style.configure('Muted.TLabel', background=self.CARD, foreground=self.MUTED)
        style.configure('Link.TLabel', background=self.CARD, foreground=self.ACCENT)
        style.configure('Status.TLabel', background=self.BACKGROUND, foreground=self.MUTED)
        style.configure('Title.TLabel', background=self.CARD, font=(family, 12, 'bold'))
        style.configure('Section.TLabel', background=self.CARD, font=(family, 10, 'bold'))
        style.configure('Problem.TLabel', background=self.CARD, foreground=self.PROBLEM)
        style.configure('TLabelframe', background=self.CARD, bordercolor=self.BORDER)
        style.configure('TLabelframe.Label', background=self.CARD, foreground=self.TEXT, font=(family, 10, 'bold'))
        style.configure('TCheckbutton', background=self.CARD)
        style.configure('TButton', padding=(10, 4))
        style.configure('Accent.TButton', background=self.ACCENT, foreground='#ffffff', padding=(16, 6), font=(family, 10, 'bold'))
        style.map('Accent.TButton', background=[('active', self.ACCENT_ACTIVE), ('disabled', '#9aa5b1')])
        style.configure('TNotebook', background=self.BACKGROUND, borderwidth=0, tabmargins=(0, 0, 0, 0))
        style.configure('TNotebook.Tab', padding=(16, 6), font=(family, 10), background='#dde3ea', foreground=self.MUTED)
        style.map('TNotebook.Tab', background=[('selected', self.CARD)], foreground=[('selected', self.TEXT)],
                  font=[('selected', (family, 10, 'bold'))])
        style.configure('Filter.TEntry', fieldbackground=self.CARD, padding=(4, 1))
        style.configure('Filter.TCombobox', fieldbackground=self.CARD, padding=(4, 1))
        style.configure('Treeview', rowheight=22, background=self.CARD, fieldbackground=self.CARD, borderwidth=0)
        style.map('Treeview', background=[('selected', self.SELECTED)], foreground=[('selected', self.TEXT)])

    def _card(self, parent, **grid):
        frame = self.ttk.Frame(parent, style='Card.TFrame', padding=10)
        frame.grid(**grid)
        return frame

    # --- tab "Workspace" --------------------------------------------------------
    def _build_workspace(self, tab):
        ttk = self.ttk
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(0, weight=1)
        self.panes = ttk.Panedwindow(tab, orient='horizontal')
        self.panes.grid(row=0, column=0, sticky='nsew')
        # Left to right the way an outage travels: available, into the case, the cases.
        left, centre, right = (ttk.Frame(self.panes, style='Card.TFrame', padding=10) for _ in range(3))
        self.panes.add(left, weight=40)
        self.panes.add(centre, weight=38)
        self.panes.add(right, weight=22)
        self._build_available(left)
        self._build_case_outages(centre)
        self._build_cases(right)

    def _build_cases(self, pane):
        tk, ttk = self.tk, self.ttk
        pane.columnconfigure(0, weight=1)
        pane.rowconfigure(1, weight=1, minsize=170)
        title = ttk.Frame(pane, style='Card.TFrame')
        title.grid(row=0, column=0, sticky='ew', pady=(0, 6))
        title.columnconfigure(0, weight=1)
        ttk.Label(title, text='Planning cases', style='Title.TLabel').grid(row=0, column=0, sticky='w')
        self.case_limit_label = ttk.Label(title, text='', style='Muted.TLabel')
        self.case_limit_label.grid(row=0, column=1, sticky='e')
        self.tip(self.case_limit_label, HELP_TEXTS['case_limit'])
        self.case_table = FilterTable(self, pane, (
            ('name', 'Planning case', 150, True, None), ('count', 'Outages', 56, False, None),
            ('status', 'Status', 100, False, ('ready', 'not calculated', 'excluded'))), height=6, selectmode='browse',
            tips={'name': COLUMN_HELP['case_name'], 'count': COLUMN_HELP['case_count'], 'status': COLUMN_HELP['case_status']})
        self.case_table.grid(row=1, column=0, sticky='nsew')
        self.case_tree = self.case_table.tree
        self.case_tree.bind('<<TreeviewSelect>>', self.on_case_select)
        self.case_tree.bind('<Double-1>', self.on_case_double_click)
        self.case_tree.bind('<F2>', lambda _event: self.rename_in_place())
        self.case_tree.bind('<Return>', lambda _event: self.rename_in_place())
        buttons = ttk.Frame(pane, style='Card.TFrame')
        buttons.grid(row=2, column=0, sticky='ew', pady=(6, 0))
        self.case_buttons = {}
        for column, (label, command) in enumerate((('New', self.new_case), ('Copy', self.copy_case),
                                                   ('Delete', self.delete_case))):
            buttons.columnconfigure(column, weight=1)
            self.case_buttons[label] = ttk.Button(buttons, text=label, command=command)
            self.case_buttons[label].grid(row=0, column=column, sticky='ew', padx=1)
            self.tip(self.case_buttons[label], HELP_TEXTS[label])
        per_outage = ttk.Button(pane, text='One case per planned outage (up to {})'.format(MAX_CASES), command=self.one_case_per_outage)
        per_outage.grid(row=3, column=0, sticky='ew', pady=(4, 8))
        self.tip(per_outage, HELP_TEXTS['one_per_outage'])
        details = ttk.Labelframe(pane, text='Selected case', padding=8)
        details.grid(row=4, column=0, sticky='ew')
        details.columnconfigure(0, weight=1)
        # Name and description are edited in their own small window (double-click, Edit).
        self.enabled_var = tk.BooleanVar(value=True)
        enabled = ttk.Checkbutton(details, text='Include in the calculation', variable=self.enabled_var, command=self.apply_enabled)
        enabled.grid(row=4, column=0, sticky='w', pady=(4, 2))
        self.tip(enabled, HELP_TEXTS['enabled'])
        heading = ttk.Label(details, text='Relations to other cases  \u24d8', style='Section.TLabel')
        heading.grid(row=5, column=0, sticky='w', pady=(6, 0))
        self.tip(heading, HELP_TEXTS['relations'])
        relations = ttk.Frame(details, style='Card.TFrame')
        relations.grid(row=6, column=0, sticky='ew', pady=(2, 0))
        self.relation_labels = {}
        for column, (relation, label) in enumerate(RELATION_LABELS):
            relations.columnconfigure(column, weight=1, uniform='relations')
            pad = (0 if column == 0 else 4, 0)
            caption = ttk.Label(relations, text=label + ' \u24d8', wraplength=78, cursor='question_arrow')
            caption.grid(row=0, column=column, sticky='sw', padx=pad)
            box = tk.Listbox(relations, selectmode='multiple', height=4, width=8, exportselection=False, activestyle='none',
                             relief='solid', borderwidth=1, highlightthickness=0, selectbackground=self.SELECTED,
                             selectforeground=self.TEXT)
            box.grid(row=1, column=column, sticky='ew', padx=pad)
            box.bind('<<ListboxSelect>>', lambda _event, name=relation: self.apply_relation(name))
            self.tip(caption, HELP_TEXTS[relation])
            self.tip(box, HELP_TEXTS[relation])
            self._relation_lists[relation] = box
            self.relation_labels[relation] = caption
        ttk.Label(details, text='Click a case to select it, click again to deselect; hover over a heading for its meaning.', style='Muted.TLabel',
                  wraplength=260).grid(row=7, column=0, sticky='w', pady=(4, 0))

    def _build_case_outages(self, pane):
        tk, ttk = self.tk, self.ttk
        pane.columnconfigure(0, weight=1)
        pane.rowconfigure(2, weight=3, minsize=170)
        pane.rowconfigure(4, weight=2, minsize=150)
        heading = ttk.Frame(pane, style='Card.TFrame')
        heading.grid(row=0, column=0, sticky='ew')
        heading.columnconfigure(1, weight=1)
        self.case_title = ttk.Label(heading, text='', style='Title.TLabel')
        self.case_title.grid(row=0, column=0, sticky='w')
        self.case_heading = heading
        self.case_description = ttk.Label(heading, text='', style='Muted.TLabel', cursor='xterm')
        self.case_description.grid(row=0, column=1, sticky='w', padx=(10, 0))
        self.case_description.bind('<Double-1>', lambda _event: self.describe_in_place())
        self.tip(self.case_description, HELP_TEXTS['description'])
        self.counts_label = ttk.Label(pane, text='', style='Muted.TLabel')
        self.counts_label.grid(row=1, column=0, sticky='w', pady=(0, 6))
        self.member_table = FilterTable(self, pane, (
            ('fs', 'Planned outage', 170, True, None), ('equipment', 'Equipment', 160, True, None),
            ('start', 'Start', 118, False, None), ('end', 'End', 118, False, None), ('prio', 'Priority', 62, False, None)), height=7,
            tips={'prio': COLUMN_HELP['prio']})
        self.member_table.grid(row=2, column=0, sticky='nsew')
        self.member_tree = self.member_table.tree
        self.member_tree.bind('<Double-1>', lambda _event: self.show_details(self.member_tree))
        self.member_tree.bind('<Delete>', lambda _event: self.remove_selected())
        buttons = ttk.Frame(pane, style='Card.TFrame')
        buttons.grid(row=3, column=0, sticky='ew', pady=(6, 8))
        remove = ttk.Button(buttons, text='Remove from case', command=self.remove_selected)
        remove.grid(row=0, column=0, padx=(0, 6))
        details = ttk.Button(buttons, text='Details', command=lambda: self.show_details(self.member_tree))
        details.grid(row=0, column=1)
        self.tip(remove, HELP_TEXTS['remove'])
        self.tip(details, HELP_TEXTS['details'])
        ttk.Label(buttons, text='Removing ends only the assignment; the planned outage stays in PowerFactory.',
                  style='Muted.TLabel').grid(row=0, column=2, sticky='w', padx=10)
        timeline = ttk.Labelframe(pane, text='Timeline of the case (planning check only, no results)', padding=6)
        timeline.grid(row=4, column=0, sticky='nsew')
        timeline.columnconfigure(0, weight=1)
        timeline.rowconfigure(1, weight=1)
        legend = ttk.Label(timeline, text='blue: case outage   grey: fixed background outage   shaded: several at the same time   light band: shortened empty period',
                           style='Muted.TLabel')
        legend.grid(row=0, column=0, columnspan=2, sticky='w', pady=(0, 4))
        self.tip(legend, HELP_TEXTS['timeline'])
        self.canvas = tk.Canvas(timeline, height=110, background=self.CARD, highlightthickness=0)
        scroll = ttk.Scrollbar(timeline, orient='vertical', command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=scroll.set)
        self.canvas.grid(row=1, column=0, sticky='nsew')
        scroll.grid(row=1, column=1, sticky='ns')
        self.canvas.bind('<Configure>', lambda _event: self.draw_timeline())

    def _build_available(self, pane):
        ttk = self.ttk
        pane.columnconfigure(0, weight=1)
        pane.rowconfigure(1, weight=1)
        ttk.Label(pane, text='Available planned outages', style='Title.TLabel').grid(row=0, column=0, sticky='w', pady=(0, 6))
        self.available_table = FilterTable(self, pane, (
            ('mark', 'In case', 78, False, (('in case', MARK_IN_CASE), ('free', MARK_FREE), ('fixed', MARK_FIXED))),
            ('fs', 'Planned outage', 140, True, None), ('equipment', 'Equipment', 110, True, None),
            ('start', 'Start', 106, False, None), ('end', 'End', 106, False, None),
            ('status', 'Status', 132, False, ('in simulated period', 'outside simulated period', 'Ignored in PowerFactory'))),
            height=16, tag_column=0, tips={'mark': COLUMN_HELP['mark'], 'status': COLUMN_HELP['outage_status']})
        self.available_table.grid(row=1, column=0, sticky='nsew')
        self.available_tree = self.available_table.tree
        self.available_tree.tag_configure(MARK_IN_CASE, background='#e8f0fb')
        self.available_tree.tag_configure(MARK_FIXED, background='#f1f2f4')
        self.available_tree.bind('<Button-1>', self.on_available_click)
        self.available_tree.bind('<space>', lambda _event: self.toggle_outage(self.available_tree.focus()) or 'break')
        self.available_tree.bind('<Double-1>', self.on_available_double_click)
        self.available_tree.bind('<Return>', lambda _event: self.add_selected())
        buttons = ttk.Frame(pane, style='Card.TFrame')
        buttons.grid(row=2, column=0, sticky='ew', pady=(6, 0))
        for column, (text, command, key) in enumerate((
                ('Add to case', self.add_selected, 'add'), ('Set as fixed background', self.fix_selected, 'fix'),
                ('Details', lambda: self.show_details(self.available_tree), 'details'))):
            button = ttk.Button(buttons, text=text, command=command)
            button.grid(row=0, column=column, padx=(0, 6))
            self.tip(button, HELP_TEXTS[key])
        ttk.Label(pane, text='Tick the box to add an outage to the selected case, untick to remove it. '
                             '"Add to case" or Enter adds all selected rows.',
                  style='Muted.TLabel', wraplength=520).grid(row=3, column=0, sticky='w', pady=(4, 0))

    # --- tab "Fixed background & rules" -------------------------------------------
    def _build_fixed_and_rules(self, tab):
        ttk = self.ttk
        tab.columnconfigure(0, weight=1, uniform='overview')
        tab.columnconfigure(1, weight=1, uniform='overview')
        tab.rowconfigure(0, weight=1)
        fixed = self._card(tab, row=0, column=0, sticky='nsew', padx=(0, 4))
        fixed.columnconfigure(0, weight=1)
        fixed.rowconfigure(2, weight=1)
        ttk.Label(fixed, text='Fixed background outages', style='Title.TLabel').grid(row=0, column=0, sticky='w')
        ttk.Label(fixed, text='Active in the reference (Rfix) and in every case. Add them in the Workspace with '
                              '"Set as fixed background".', style='Muted.TLabel', wraplength=560).grid(row=1, column=0, sticky='w', pady=(2, 6))
        self.fixed_table = FilterTable(self, fixed, (
            ('fs', 'Planned outage', 170, True, None), ('equipment', 'Equipment', 150, True, None), ('start', 'Start', 118, False, None),
            ('end', 'End', 118, False, None), ('status', 'Status', 150, False,
                                               ('in simulated period', 'outside simulated period', 'Ignored in PowerFactory'))), height=10,
            tips={'status': COLUMN_HELP['outage_status']})
        self.fixed_table.grid(row=2, column=0, sticky='nsew')
        self.fixed_tree = self.fixed_table.tree
        self.fixed_tree.bind('<Double-1>', lambda _event: self.show_details(self.fixed_tree))
        unfix = ttk.Button(fixed, text='Remove from fixed background', command=self.unfix_selected)
        unfix.grid(row=3, column=0, sticky='w', pady=(6, 0))
        self.tip(unfix, HELP_TEXTS['unfix'])
        rules = self._card(tab, row=0, column=1, sticky='nsew', padx=(4, 0))
        rules.columnconfigure(0, weight=1)
        rules.rowconfigure(2, weight=1)
        ttk.Label(rules, text='Rules between planned outages', style='Title.TLabel').grid(row=0, column=0, sticky='w')
        ttk.Label(rules, text='Apply to every case; a case that breaks a rule is reported and not calculated.',
                  style='Muted.TLabel', wraplength=560).grid(row=1, column=0, sticky='w', pady=(2, 6))
        self.rule_table = FilterTable(self, rules, (
            ('first', 'Planned outage', 170, True, None), ('rule', 'Rule', 190, False, tuple(label for _, label in RULE_LABELS)),
            ('second', 'Planned outage', 170, True, None)), height=10, tips={'rule': HELP_TEXTS['rule_kind']})
        self.rule_table.grid(row=2, column=0, sticky='nsew')
        self.rule_tree = self.rule_table.tree
        editor_row = ttk.Frame(rules, style='Card.TFrame')
        editor_row.grid(row=3, column=0, sticky='ew', pady=(6, 0))
        names = [label for label, _ in self.editor.outage_choices()]
        self.rule_first = ttk.Combobox(editor_row, values=names, state='readonly', width=22)
        self.rule_kind = ttk.Combobox(editor_row, values=[label for _, label in RULE_LABELS], state='readonly', width=24)
        self.rule_second = ttk.Combobox(editor_row, values=names, state='readonly', width=22)
        for column, widget in enumerate((self.rule_first, self.rule_kind, self.rule_second)):
            widget.grid(row=0, column=column, padx=(0, 4))
        self.tip(self.rule_kind, HELP_TEXTS['rule_kind'])
        ttk.Button(editor_row, text='Add rule', command=self.add_rule).grid(row=0, column=3, padx=(0, 4))
        ttk.Button(editor_row, text='Remove rule', command=self.remove_rule).grid(row=0, column=4)

    # --- tab "Review & start" ------------------------------------------------------
    def _build_review(self, tab):
        tk, ttk = self.tk, self.ttk
        tab.columnconfigure(1, weight=1)
        tab.rowconfigure(1, weight=1)
        options = self._card(tab, row=0, column=0, sticky='nsew', padx=(0, 4), pady=(0, 8))
        ttk.Label(options, text='Calculation', style='Title.TLabel').grid(row=0, column=0, sticky='w', pady=(0, 6))
        self.n0_var, self.n1_var = tk.BooleanVar(value='n-0' in self.editor.config['assessments']), tk.BooleanVar(value=False)
        ttk.Checkbutton(options, text='n-0 - quasi-dynamic simulation (QDS)', variable=self.n0_var,
                        command=self.apply_assessments).grid(row=1, column=0, sticky='w')
        n1 = ttk.Checkbutton(options, text='n-1 - contingency analysis', variable=self.n1_var, state='disabled')
        n1.grid(row=2, column=0, sticky='w')
        self.tip(n1, HELP_TEXTS['n1'])
        ttk.Label(options, text='not available in this GridLens version (no contingency analysis)',
                  style='Muted.TLabel').grid(row=3, column=0, sticky='w', padx=(22, 0))
        qds = ttk.Label(options, text='QDS: ' + self.editor.qds_text, style='Section.TLabel')
        qds.grid(row=4, column=0, sticky='w', pady=(10, 0))
        self.tip(qds, HELP_TEXTS['qds'])
        ttk.Label(options, text='period and time step as set in the active ComStatsim', style='Muted.TLabel').grid(
            row=5, column=0, sticky='w')
        preview = self._card(tab, row=0, column=1, sticky='nsew', padx=(4, 0), pady=(0, 8))
        preview.columnconfigure(1, weight=1)
        ttk.Label(preview, text='What will be calculated (no results)', style='Title.TLabel').grid(
            row=0, column=0, columnspan=2, sticky='w', pady=(0, 6))
        self.preview_frame = ttk.Frame(preview, style='Card.TFrame')
        self.preview_frame.grid(row=1, column=0, columnspan=2, sticky='nsew')
        self.preview_frame.columnconfigure(1, weight=1)
        problems = self._card(tab, row=1, column=0, columnspan=2, sticky='nsew')
        problems.columnconfigure(0, weight=1)
        problems.rowconfigure(1, weight=1)
        ttk.Label(problems, text='Problems and warnings', style='Title.TLabel').grid(row=0, column=0, sticky='w', pady=(0, 6))
        self.problem_table = FilterTable(self, problems, (('where', 'Where', 130, False, None), ('problem', 'Problem', 600, True, None)),
                                         height=8)
        self.problem_table.grid(row=1, column=0, sticky='nsew')

    # --- showing the editor state ---------------------------------------------------
    def refresh_all(self, select=None):
        self.refresh_cases(select)
        self.refresh_selected()

    def refresh_cases(self, select=None):
        statuses = self.editor.case_statuses()
        self.case_table.set_rows([(case_id, (self.editor.case_label(case_id), count, statuses.get(case_id, '')))
                                  for case_id, _, _, count in self.editor.case_rows()])
        full = self.editor.limit_problem() is not None
        self.case_limit_label.configure(text='{} of {} cases'.format(len(self.editor.case_ids()), MAX_CASES),
                                        style='Problem.TLabel' if full else 'Muted.TLabel')
        for label in ('New', 'Copy'):
            self.case_buttons[label].state(['disabled'] if full else ['!disabled'])
        self.selected = select if self.editor.case(select) is not None else None
        if self.selected is not None and self.case_tree.exists(self.selected):
            self.case_tree.selection_set(self.selected)
            self.case_tree.focus(self.selected)
            self.case_tree.see(self.selected)

    def refresh_selected(self):
        """Everything that depends on the selected case, then the other tabs."""
        case = self.editor.case(self.selected)
        self.case_title.configure(text=self.editor.case_label(self.selected) if case else 'No case selected')
        counts = self.editor.counts_text(self.selected) if case else 'Create a case with "New" or select one on the right.'
        missing = self.editor.unknown_members(self.selected)
        if missing:
            counts += '   ({} assigned outage(s) no longer exist in the project)'.format(len(missing))
        self.counts_label.configure(text=counts)
        description = case.get('description', '') if case else ''
        self.case_description.configure(text=clip_text(description, 90) if description else
                                        ('(double-click to add a description)' if case else ''))
        self.enabled_var.set(case.get('enabled', True) if case else False)
        self.member_table.set_rows(self.editor.member_rows(self.selected))
        for relation, box in self._relation_lists.items():
            options = self.editor.relation_options(self.selected) if case else []
            chosen = set(getattr(self.editor, relation)(self.selected)) if case else set()
            box.delete(0, 'end')
            box.ids = [identifier for identifier, _ in options]
            for index, (identifier, label) in enumerate(options):
                box.insert('end', label)
                if identifier in chosen:
                    box.selection_set(index)
        self.refresh_available()
        self.draw_timeline()
        self.refresh_overview()

    def refresh_available(self):
        self.available_table.set_rows(self.editor.available_rows(self.selected))

    def refresh_overview(self):
        """The tabs "Fixed background & rules" and "Review & start", the status line and the tab label."""
        self.fixed_table.set_rows(self.editor.fixed_rows())
        self.rule_table.set_rows([(str(index), cells) for index, cells in self.editor.rule_rows()])
        lines, _ = self.editor.summary()
        if len(lines) != len(self._preview_labels):
            # The number of lines changes only between a valid and an invalid configuration.
            for child in self.preview_frame.winfo_children():
                child.destroy()
            self._preview_labels = []
            for row in range(len(lines)):
                caption = self.ttk.Label(self.preview_frame, style='Muted.TLabel')
                caption.grid(row=row, column=0, sticky='nw', padx=(0, 14), pady=1)
                value = self.ttk.Label(self.preview_frame, wraplength=640)
                value.grid(row=row, column=1, sticky='w', pady=1)
                self._preview_labels.append((caption, value))
        for (caption, value), (label, text) in zip(self._preview_labels, lines):
            caption.configure(text=label)
            value.configure(text=text)
        problems = self.editor.problem_rows()
        self.problem_table.set_rows([(str(index), cells) for index, cells in enumerate(problems)])
        self.notebook.tab(self.review_tab, text=self.TAB_REVIEW + (' ({})'.format(len(problems)) if problems else ''))
        statuses = self.editor.case_statuses()
        ready = sum(1 for status in statuses.values() if status == 'ready')
        self.status_line.configure(
            text='QDS {}  ·  n-0  ·  {} of {} cases ready  ·  {}'.format(
                self.editor.qds_text, ready, len(self.editor.config['cases']),
                _counted(len(problems), 'problem or warning', 'problems or warnings') if problems else 'no problems'),
            foreground=self.PROBLEM if problems else self.MUTED)

    def refresh_preview(self):
        self.refresh_overview()

    def draw_timeline(self):
        canvas = self.canvas
        canvas.delete('all')
        items, overlaps = self.editor.timeline(self.selected)
        width = max(canvas.winfo_width(), 360)
        label_width, row_height, top = 130, 20, 8
        if not items:
            canvas.create_text(10, 20, anchor='w', fill=self.MUTED, text='No planned outage with a readable window in this case.')
            canvas.configure(scrollregion=(0, 0, width, 40))
            return
        position, breaks = timeline_scale([(start, end) for _, start, end, _ in items], width - label_width - 14)
        x = lambda moment: label_width + position(moment)
        bottom = top + row_height * len(items)
        for left, right in breaks:
            canvas.create_rectangle(label_width + left, top - 4, label_width + right, bottom, fill=self.GAP, outline='')
        for start, end in overlaps:
            canvas.create_rectangle(x(start), top - 4, x(end), bottom, fill=self.OVERLAP, outline='')
        for index, (name, start, end, kind) in enumerate(items):
            y = top + index * row_height
            canvas.create_text(4, y + row_height / 2, anchor='w', text=clip_text(name, 20), fill=self.TEXT)
            left = x(start)
            canvas.create_rectangle(left, y + 4, max(x(end), left + 3), y + row_height - 4,
                                    fill=self.ACCENT if kind == 'case' else self.FIXED, outline='')
        canvas.create_line(label_width, bottom + 2, width - 14, bottom + 2, fill=self.MUTED)
        for start, end in merge_intervals([(start, end) for _, start, end, _ in items]):
            for moment, anchor in ((start, 'nw'), (end, 'ne')):
                canvas.create_text(x(moment), bottom + 6, anchor=anchor, fill=self.MUTED, text=_format_pf_time(moment)[:10])
        canvas.configure(scrollregion=(0, 0, width, bottom + 26))

    # --- cases -------------------------------------------------------------------
    def on_case_select(self, _event=None):
        chosen = self.case_tree.selection()
        identifier = chosen[0] if chosen else None
        if identifier is not None and identifier != self.selected:
            self.selected = identifier
            self.refresh_selected()

    def apply_enabled(self):
        if self.selected is not None:
            self.editor.set_enabled(self.selected, self.enabled_var.get())
            self.refresh_cases(self.selected)
            self.refresh_overview()

    def apply_relation(self, relation):
        if self.selected is None:
            return
        box = self._relation_lists[relation]
        ids = [box.ids[index] for index in box.curselection()]
        getattr(self.editor, 'set_' + relation)(self.selected, ids)
        self.refresh_cases(self.selected)
        self.refresh_overview()

    def new_case(self):
        identifier, problem = self.editor.add_case()
        if problem:
            self.messagebox.showinfo('New case', problem, parent=self.root)
            return
        self.case_table.clear_filters()
        self.refresh_all(identifier)

    def copy_case(self):
        if self.editor.case(self.selected) is None:
            return
        identifier, problem = self.editor.copy_case(self.selected)
        if problem:
            self.messagebox.showinfo('Copy case', problem, parent=self.root)
            return
        self.case_table.clear_filters()
        self.refresh_all(identifier)

    def on_case_double_click(self, event):
        row = self.case_tree.identify_row(event.y)
        if row:
            self.rename_in_place(row)
        return 'break'

    def rename_in_place(self, case_id=None):
        """An entry over the name cell of the case; Enter or a click elsewhere applies, Escape cancels."""
        case_id = case_id or self.selected
        case = self.editor.case(case_id)
        if case is None or not self.case_tree.exists(case_id):
            return None
        self.case_tree.see(case_id)
        self.root.update_idletasks()
        box = self.case_tree.bbox(case_id, 'name')
        if not box:
            return None

        def apply(value):
            if value.strip():
                self.editor.rename_case(case_id, value)
            self.refresh_cases(self.selected)
            self.refresh_selected()
        return self._edit_in_place(self.case_tree, box, case.get('name', ''), apply, 'name')

    def describe_in_place(self):
        """An entry over the description next to the case name in the centre."""
        case_id = self.selected
        case = self.editor.case(case_id)
        if case is None:
            return None
        self.root.update_idletasks()
        heading, label = self.case_heading, self.case_description
        left = label.winfo_x()
        box = (left, 0, max(heading.winfo_width() - left, 240), max(heading.winfo_height(), 24))

        def apply(value):
            self.editor.set_description(case_id, value)
            self.refresh_selected()
        return self._edit_in_place(heading, box, case.get('description', ''), apply, 'description')

    def _edit_in_place(self, parent, box, text, apply, what):
        """An entry laid over `box` (x, y, width, height) of `parent`; no extra window."""
        self.finish_editing()
        entry = self.ttk.Entry(parent)
        entry.insert(0, text)
        x, y, width, height = box
        entry.place(x=x, y=y, width=width, height=height)
        entry.focus_set()
        entry.select_range(0, 'end')
        state = {'entry': entry, 'what': what}

        def commit(_event=None):
            if self.inline_edit is not state:
                return
            value = entry.get()
            self.inline_edit = None
            entry.destroy()
            apply(value)

        def cancel(_event=None):
            # 'break' keeps Escape from reaching the window, where it would cancel the run;
            # the entry goes once this event is handled.
            if self.inline_edit is state:
                self.inline_edit = None
                entry.after_idle(entry.destroy)
            return 'break'
        for sequence in ('<Return>', '<KP_Enter>', '<FocusOut>'):
            entry.bind(sequence, commit)
        entry.bind('<Escape>', cancel)
        state.update(commit=commit, cancel=cancel)
        self.inline_edit = state
        return entry

    def on_escape(self, _event=None):
        # Escape first ends an open in-place edit; only without one it cancels the run.
        if self.inline_edit is not None:
            self.inline_edit['cancel']()
            return 'break'
        self.cancel()
        return 'break'

    def finish_editing(self):
        """Apply an open in-place edit, e.g. before saving or starting."""
        if self.inline_edit is not None:
            self.inline_edit['commit']()

    def delete_case(self):
        case = self.editor.case(self.selected)
        if case is None:
            return
        effects = self.editor.delete_effects(self.selected)
        if not self.messagebox.askyesno('Delete case', 'Delete case {}?\n{}The planned outages stay in PowerFactory.'.format(
                self.editor.case_label(self.selected), ''.join(line + '\n' for line in effects)), parent=self.root):
            return
        ids = self.editor.case_ids()
        position = ids.index(self.selected)
        self.editor.delete_case(self.selected)
        rest = self.editor.case_ids()
        self.refresh_all(rest[min(position, len(rest) - 1)] if rest else None)

    def one_case_per_outage(self):
        if self.editor.config['cases'] and not self.messagebox.askyesno(
                'One case per planned outage', 'Replace all cases by one case per planned outage?', parent=self.root):
            return
        note = self.editor.one_case_per_outage()
        ids = self.editor.case_ids()
        self.case_table.clear_filters()
        self.refresh_all(ids[0] if ids else None)
        if note:
            self.messagebox.showinfo('One case per planned outage', note, parent=self.root)

    # --- planned outages ---------------------------------------------------------
    def add_selected(self):
        if self.selected is None:
            self.messagebox.showinfo('Add to case', 'Select a planning case on the right first.', parent=self.root)
            return
        problems = [problem for problem in (self.editor.add_outage(self.selected, key) for key in self.available_tree.selection()) if problem]
        self.refresh_cases(self.selected)
        self.refresh_selected()
        if problems:
            self.messagebox.showinfo('Add to case', '\n'.join(problems), parent=self.root)

    def on_available_click(self, event):
        """A click into the check box column ticks or unticks that outage; elsewhere it selects as usual."""
        tree = self.available_tree
        if tree.identify_region(event.x, event.y) != 'cell' or tree.identify_column(event.x) != '#1':
            return None
        key = tree.identify_row(event.y)
        if key:
            self.toggle_outage(key)
        return 'break'

    def on_available_double_click(self, event):
        # Tk reports a quick second click as a double-click: in the box it ticks
        # again, elsewhere it opens the details.
        if self.on_available_click(event) == 'break':
            return 'break'
        self.show_details(self.available_tree)
        return 'break'

    def toggle_outage(self, key):
        if not key:
            return
        if self.selected is None:
            self.messagebox.showinfo('Add to case', 'Select a planning case on the right first.', parent=self.root)
            return
        problem = self.editor.toggle_outage(self.selected, key)
        self.refresh_cases(self.selected)
        self.refresh_selected()
        if problem:
            self.messagebox.showinfo('Add to case', problem, parent=self.root)

    def remove_selected(self):
        for key in self.member_tree.selection():
            self.editor.remove_outage(self.selected, key)
        self.refresh_cases(self.selected)
        self.refresh_selected()

    def fix_selected(self):
        problems = [problem for problem in (self.editor.set_fixed(key, True) for key in self.available_tree.selection()) if problem]
        self.refresh_cases(self.selected)
        self.refresh_selected()
        if problems:
            self.messagebox.showinfo('Fixed background outage', '\n'.join(problems), parent=self.root)

    def unfix_selected(self):
        for key in self.fixed_tree.selection():
            self.editor.set_fixed(key, False)
        self.refresh_cases(self.selected)
        self.refresh_selected()

    def add_rule(self):
        names = dict(self.editor.outage_choices())
        kinds = {label: kind for kind, label in RULE_LABELS}
        problem = self.editor.add_rule(kinds.get(self.rule_kind.get()), names.get(self.rule_first.get()), names.get(self.rule_second.get()))
        if problem:
            self.messagebox.showinfo('Rule', problem, parent=self.root)
        self.refresh_cases(self.selected)
        self.refresh_overview()

    def remove_rule(self):
        for index in sorted((int(item) for item in self.rule_tree.selection()), reverse=True):
            self.editor.remove_rule(index)
        self.refresh_cases(self.selected)
        self.refresh_overview()

    def show_details(self, tree):
        """A compact window with what PowerFactory holds for one planned outage, and its own dates in this case."""
        chosen = tree.selection()
        if not chosen or chosen[0] not in self.editor.by_key:
            return
        key = chosen[0]
        window = self.tk.Toplevel(self.root)
        window.title('Planned outage')
        window.configure(background=self.CARD)
        window.transient(self.root)
        frame = self.ttk.Frame(window, style='Card.TFrame', padding=12)
        frame.grid(row=0, column=0, sticky='nsew')
        details = self.editor.details(key)
        for row, (label, value) in enumerate(details):
            self.ttk.Label(frame, text=label, style='Muted.TLabel').grid(row=row, column=0, sticky='nw', padx=(0, 12), pady=1)
            self.ttk.Label(frame, text=value, wraplength=460).grid(row=row, column=1, sticky='w', pady=1)
        row = len(details)
        case = self.editor.case(self.selected)
        if case is not None and key in (case.get('outages') or ()):
            start, end = self.editor.window_text(case, self.editor.by_key[key])
            start_var, end_var = self.tk.StringVar(value=start.rstrip(' *')), self.tk.StringVar(value=end.rstrip(' *'))
            self.ttk.Label(frame, text='Own dates in {}'.format(self.editor.case_label(case['id'])), style='Section.TLabel').grid(
                row=row, column=0, columnspan=2, sticky='w', pady=(10, 2))
            self.ttk.Entry(frame, textvariable=start_var, width=18).grid(row=row + 1, column=0, sticky='w')
            self.ttk.Entry(frame, textvariable=end_var, width=18).grid(row=row + 1, column=1, sticky='w')
            note = ('Recorded only: this version does not apply own dates, the case is reported NOT EVALUATED. '
                    'Create a planned outage with these dates for a calculation. An empty start removes them.')
            self.ttk.Label(frame, text=note, style='Muted.TLabel', wraplength=460).grid(row=row + 2, column=0, columnspan=2, sticky='w')

            def apply_dates():
                problem = self.editor.set_own_dates(self.selected, key, start_var.get(), end_var.get())
                if problem:
                    self.messagebox.showerror('Own dates', problem, parent=window)
                    return
                self.refresh_cases(self.selected)
                self.refresh_selected()
                window.destroy()
            self.ttk.Button(frame, text='Apply own dates', command=apply_dates).grid(row=row + 3, column=0, sticky='w', pady=(6, 0))
            row += 4
        self.ttk.Button(frame, text='Close', command=window.destroy).grid(row=row, column=1, sticky='e', pady=(6, 0))
        window.bind('<Escape>', lambda _event: window.destroy())

    # --- calculation -----------------------------------------------------------
    def apply_assessments(self):
        if not self.n0_var.get():
            # n-1 is not available, so n-0 is the only assessment that can be chosen.
            self.n0_var.set(True)
            self.messagebox.showinfo('Assessment', 'At least one assessment is needed, and n-0 is the only one available.',
                                     parent=self.root)
        self.editor.set_assessments(self.n0_var.get(), self.n1_var.get())
        self.refresh_overview()

    def save(self):
        self.finish_editing()
        problems = validate_case_config(self.editor.config)
        if problems:
            self.messagebox.showerror('Save configuration', '\n'.join(problems), parent=self.root)
            return
        try:
            stored = save_case_config(self.config_path, self.editor.config, self.user)
        except (OSError, GridLensError) as exc:
            self.messagebox.showerror('Save configuration', str(exc), parent=self.root)
            return
        self.messagebox.showinfo('Save configuration', 'Saved revision {} to\n{}'.format(stored['revision'], self.config_path), parent=self.root)

    def load_saved(self):
        try:
            saved = load_case_config(self.config_path)
        except GridLensError as exc:
            self.messagebox.showerror('Load saved configuration', str(exc), parent=self.root)
            return
        if saved is None:
            self.messagebox.showinfo('Load saved configuration', 'No saved configuration exists yet at\n{}'.format(self.config_path), parent=self.root)
            return
        if not self.messagebox.askyesno('Load saved configuration', 'Replace the cases on screen by the saved revision {}?'.format(
                saved.get('revision')), parent=self.root):
            return
        self.editor.load(saved)
        self.n0_var.set('n-0' in self.editor.config['assessments'])
        for table in (self.case_table, self.member_table, self.available_table, self.fixed_table, self.rule_table, self.problem_table):
            table.clear_filters()
        ids = self.editor.case_ids()
        self.refresh_all(ids[0] if ids else None)

    def start(self):
        """Check the configuration and hand it to GridLens; the calculation starts after the window closes."""
        self.finish_editing()
        problem = self.editor.set_assessments(self.n0_var.get(), self.n1_var.get())
        problems = ([problem] if problem else []) + validate_case_config(self.editor.config)
        if problems:
            self.messagebox.showerror('Start calculation', '\n'.join(problems), parent=self.root)
            return
        request = self.editor.request()
        ready = [plan for plan in request['cases'] if plan['status'] == PLAN_READY]
        blocked = [plan for plan in request['cases'] if plan['status'] != PLAN_READY]
        if not ready and not self.messagebox.askyesno('Start calculation', 'No case can be calculated. Calculate the reference only?',
                                                      parent=self.root):
            return
        if blocked and ready and not self.messagebox.askyesno(
                'Start calculation', '{} case(s) cannot be calculated and will be reported with their reason:\n{}\n\nContinue?'.format(
                    len(blocked), '\n'.join('{}: {}'.format(self.editor.case_label(plan['id']), clip_text(plan['reason'], 140))
                                             for plan in blocked[:5])),
                parent=self.root):
            return
        self.outcome = self.editor.config
        self.root.destroy()

    def cancel(self):
        self.outcome = None
        self.root.destroy()


def run_case_manager(records, config, period, config_path, user='', qds_text=''):
    """Show the case manager; the edited configuration on "Start calculation", None on Cancel."""
    try:
        import tkinter as tk
        import tkinter.font
        from tkinter import messagebox, simpledialog, ttk
        root = tk.Tk()
    except Exception as exc:
        raise CaseManagerUnavailable('The case manager cannot open a window: {}'.format(_friendly_exception(exc))) from None
    dialog = CaseManagerDialog(root, CaseEditor(records, config, period, qds_text), config_path, user,
                               (tk, ttk, messagebox, simpledialog))
    root.report_callback_exception = dialog.report_error
    try:
        dialog.build()
    except Exception as exc:
        # Nothing has been shown yet: the same as a missing Tk.
        try:
            root.destroy()
        except Exception:
            pass
        raise CaseManagerUnavailable('The case manager could not be built: {}'.format(_friendly_exception(exc))) from None
    try:
        root.mainloop()
    except Exception as exc:
        raise GridLensError('The case manager stopped with an error: {}. Nothing was calculated.'.format(
            _friendly_exception(exc))) from None
    finally:
        try:
            root.destroy()
        except Exception:
            pass
    return dialog.outcome


def qds_period(qds):
    """The simulated period in epoch seconds, as ComStatsim declares it."""
    for start_name, end_name in QDS_PERIOD_ATTRIBUTES:
        start = finite_number(safe_attr(qds, start_name))
        end = finite_number(safe_attr(qds, end_name))
        if start is not None and end is not None and end >= start:
            return start, end
    return None, None


def _friendly_exception(exc):
    if exc is None:
        return "unknown error"
    messages = []
    current = exc
    seen = set()
    while current is not None and id(current) not in seen and len(messages) < 3:
        seen.add(id(current))
        text = str(current).strip()
        label = type(current).__name__
        messages.append("{}: {}".format(label, text) if text else label)
        if current.__cause__ is not None:
            current = current.__cause__
        elif not current.__suppress_context__:
            current = current.__context__
        else:
            current = None
    return " -> ".join(messages)


def qds_period_text(period):
    """'2016-07-01 00:00 - 2016-08-01 00:00' for the ComStatsim period, as the case manager shows it."""
    start, end = period
    if start is None or end is None:
        return 'not readable from ComStatsim'
    return '{} - {}'.format(_format_pf_time(start), _format_pf_time(end))


# <<< end of the copy <<<


# --- the test itself -------------------------------------------------------------
def log(app, message):
    text = PREFIX + str(message)
    printer = getattr(app, "PrintPlain", None) if app is not None else None
    if callable(printer):
        try:
            printer(text)
            return
        except Exception:
            pass
    print(text, flush=True)


def demo_records():
    """Clearly named demo outages when PowerFactory or its outages are not available."""
    start = time.mktime((2016, 7, 1, 0, 0, 0, 0, 0, -1))
    rows = (("DEMO FS 1", "DEMO line L100", 10, 35), ("DEMO FS 2", "DEMO line L200", 7, 32),
            ("DEMO FS 3", "DEMO transformer T300", 20, 27), ("DEMO FS 4", "DEMO line L400", 3, 8),
            ("DEMO FS KW10", "DEMO line L500", -116, -111), ("DEMO FS KW40", "DEMO line L500", 94, 99))
    records = []
    for name, equipment, first, last in rows:
        window = (start + first * D, start + last * D)
        records.append({"key": "DEMO\\" + name, "id": name, "name": name, "window": window,
                        "component_keys": ["DEMO\\" + equipment], "equipment_name": equipment, "equipment_type": "demo",
                        "switching_actions": "", "start_time": _format_pf_time(window[0]), "end_time": _format_pf_time(window[1]),
                        "priority": 1, "originally_ignored": False, "source_class": "demo", "status": "CONSIDERED"})
    return records, (start, start + 31 * D)


def read_project(app):
    """Planned outages, simulated period and source, read only; demo data where PowerFactory has none."""
    if app is None:
        return None, None, "DEMO", "PowerFactory is not available"
    try:
        qds = app.GetFromStudyCase("ComStatsim")
    except Exception:
        qds = None
    period = qds_period(qds) if qds is not None else (None, None)
    try:
        records, _ = classify_planned_outages(app, RunLogger(app), period)
    except Exception as exc:
        return None, period, "DEMO", "planned outages could not be read: {}".format(_friendly_exception(exc))
    if not records:
        return None, period, "DEMO", "the project has no planned outage"
    assign_definitions(records)
    return records, period, "PowerFactory", ""


def starting_configuration(app, scratch):
    """The saved configuration of the project, copied to `scratch`; save and load in the window use the copy."""
    try:
        project_key = object_key(app.GetActiveProject()) if app is not None else "demo project"
    except Exception:
        project_key = "project"
    copy = os.path.join(scratch, "cases.json")
    if USE_SAVED_CONFIGURATION and app is not None:
        real = case_config_path(project_key)
        if os.path.isfile(real):
            shutil.copyfile(real, copy)
            try:
                return load_case_config(copy), copy, "saved configuration " + real
            except GridLensError as exc:
                # A damaged file must not stop the GUI test; GridLens itself would report it.
                os.remove(copy)
                return empty_case_config(project_key), copy, "empty configuration ({})".format(exc)
    return empty_case_config(project_key), copy, "empty configuration"


def run(app):
    log(app, "Python {}; this test changes nothing in PowerFactory and calculates nothing.".format(sys.version.split()[0]))
    try:
        import tkinter as tk
        log(app, "tkinter imported: Tcl {}, Tk {}.".format(tk.TclVersion, tk.TkVersion))
    except Exception as exc:
        log(app, "FAIL: tkinter cannot be imported: {!r}. This Python has no Tcl/Tk; GridLens would fall back to the saved "
                 "configuration or one case per planned outage.".format(exc))
        return False
    log(app, "Case manager copied from GridLens {} (standalone, gridlens_report.py is not used).".format(PUBLISHER_VERSION))
    records, period, source, reason = read_project(app)
    if source == "DEMO":
        records, period = demo_records()
        log(app, "DEMO DATA: {}; {} demo planned outages are shown.".format(reason, len(records)))
    else:
        log(app, "{} planned outages read from PowerFactory (read only).".format(len(records)))
    scratch = tempfile.mkdtemp(prefix="gridlens_case_manager_test_")
    try:
        config, config_copy, origin = starting_configuration(app, scratch)
        log(app, "Starting from the {}; save and load in the window use the copy {}.".format(origin, config_copy))
        try:
            outcome = run_case_manager(records, config, period, config_copy, "case manager test",
                                       qds_text=qds_period_text(period))
        except CaseManagerUnavailable as exc:
            log(app, "FAIL: {}".format(exc))
            return False
        except Exception:
            log(app, "FAIL: the case manager stopped with an error:\n" + traceback.format_exc())
            return False
        if outcome is None:
            log(app, "Cancel: no configuration handed over; GridLens would stop here without any change.")
            return True
        lines, problems = CaseEditor(records, outcome, period).summary()
        log(app, "Start calculation: the configuration was handed back. GridLens would now calculate:")
        for label, value in lines:
            log(app, "  {:<26} {}".format(label, value))
        for problem in problems:
            log(app, "  problem: {}".format(problem))
        log(app, "Configuration (JSON):\n" + json.dumps(outcome, ensure_ascii=False, indent=2))
        log(app, "PASS: GUI test finished. Nothing was calculated and no PowerFactory object was changed.")
        return True
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def main():
    app = None
    try:
        import powerfactory
        app = powerfactory.GetApplication()
    except Exception as exc:
        print(PREFIX + "PowerFactory is not available ({}); demo data is used.".format(exc), flush=True)
    return run(app)


if __name__ == "__main__":
    main()
