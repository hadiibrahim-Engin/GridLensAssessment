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
     shared outages, independent cases, rules, hover help and the timeline work with
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
# GridLens 8.0.0: 166 definitions.
import re
import hashlib
import math
from datetime import datetime


TOP_N = 10


MAX_PLOT_POINTS = 200


LOADING_MAX = 100.0


LOADING_WARNING = 80.0


LOADING_DELTA_TOLERANCE = 0.1


VOLTAGE_DELTA_TOLERANCE = 0.001


LOADING_APPENDIX_DELTA = 1.0


VOLTAGE_APPENDIX_DELTA = 0.005


VOLTAGE_MIN = 0.95


VOLTAGE_MAX = 1.05


ENERGIZED_MIN_PU = 0.1


MAX_N1_TIMES = 2000


PUBLISHER_VERSION = '8.0.0'


RUN_REFERENCE_CASE = True


CASE_CONFIG_DIR = ''


MAX_CASES = 5


CASE_CONFIG_SCHEMA = 'gridlens.cases'


CASE_CONFIG_SCHEMA_VERSION = 2


N1_REFERENCE, N1_PRIME = 'n-1', "(n-1)'"


ASSESSMENTS = ('n-0', N1_REFERENCE, N1_PRIME)


ALLOW_OUTAGE_TIME_OVERRIDE = False


GRID_NAME_FILTER = ''


SNAPSHOT_PREFIX = 'GridLens_'


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


def element_grid_name(obj):
    """Name of the grid an element belongs to; '' when it has none.

    PowerFactory shows the grid as the attribute "Grid" (cpGrid). Where that is
    not readable, the ElmNet folder in the element's own path is used.
    """
    grid = safe_attr(obj, 'cpGrid')
    if grid is not None and not isinstance(grid, (str, int, float, bool)):
        name = object_name(grid)
        if name:
            return name
    for part in reversed(object_key(obj).split('\\')):
        if part.endswith('.ElmNet'):
            return part[:-len('.ElmNet')]
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


def format_limit(value):
    return '{:g}'.format(value)


SOURCE_GRIDLENS, SOURCE_POWERFACTORY, SOURCE_USER = 'GridLens', 'PowerFactory', 'user'


CATEGORY_EVALUATION, CATEGORY_CALCULATION = 'A', 'B'


N1_LIMITS_POWERFACTORY, N1_LIMITS_GLOBAL = 'powerfactory', 'global'


N1_LIMIT_CHOICES = ((N1_LIMITS_POWERFACTORY, 'use PowerFactory limits'), (N1_LIMITS_GLOBAL, 'global assessment limit'))


ON_OFF_CHOICES = ((True, 'on'), (False, 'off'))


COUNT_LIMITS = {'top_n': 50, 'max_plot_points': 2000, 'max_n1_times': 20000, 'max_cases': 20}


NOT_VERIFIED = 'not verified yet'


PART3_NOTE = ('Read only: set in the contingency analysis (ComSimoutage) of the study case; GridLens reads it '
              'and does not change it.')


NUMERIC_TOLERANCE = 1e-9


def _setting(key, section, label, unit, default, kind, category=CATEGORY_EVALUATION, editable=True, applies='n-0',
             source=SOURCE_GRIDLENS, note='', choices=None):
    return {'key': key, 'section': section, 'label': label, 'unit': unit, 'default': default, 'kind': kind,
            'category': category, 'editable': editable, 'applies': applies, 'source': source, 'note': note,
            'choices': choices or (N1_LIMIT_CHOICES if kind == 'choice' else None)}


def _contingency_setting(key, label):
    return _setting(key, 'Contingency analysis', label, '', None, 'text', CATEGORY_CALCULATION, False, "n-1, (n-1)'",
                    SOURCE_POWERFACTORY, PART3_NOTE)


SETTINGS = (
    _setting('monitoring_grids', 'Network scope', 'Assessed equipment: grids', '', (), 'grids', applies="n-0, n-1, (n-1)'",
             note='no grid selected: every grid (or GRID_NAME_FILTER in the script)'),
    _setting('contingency_grids', 'Network scope', 'Contingencies: grids of the outaged equipment', '', None, 'grids',
             CATEGORY_CALCULATION, applies="n-1, (n-1)'", source=SOURCE_GRIDLENS,
             note='applied to the n-1 run by setting ComOutage "Not analysed" (outserv) for the run and restoring it'),
    _setting('line_warning', 'Thermal limits', 'Warning threshold, lines', '%', LOADING_WARNING, 'limit'),
    _setting('transformer_warning', 'Thermal limits', 'Warning threshold, transformers', '%', LOADING_WARNING, 'limit'),
    _setting('line_limit', 'Thermal limits', 'Maximum loading for n-0, lines', '%', LOADING_MAX, 'limit'),
    _setting('transformer_limit', 'Thermal limits', 'Maximum loading for n-0, transformers', '%', LOADING_MAX, 'limit'),
    _setting('n1_limit_mode', 'Thermal limits', "Limits for n-1 and (n-1)'", '', N1_LIMITS_POWERFACTORY, 'choice',
             applies="n-1, (n-1)'"),
    _setting('n1_limit_global', 'Thermal limits', "Global assessment limit for n-1 and (n-1)'", '%', LOADING_MAX, 'limit',
             applies="n-1, (n-1)'", note='only used with a global assessment limit'),
    _setting('voltage_min_pu', 'Voltage limits', 'Minimum voltage, every voltage level', 'p.u.', VOLTAGE_MIN, 'pu',
             note='GridLens proposal, to be confirmed by the engineer'),
    _setting('voltage_max_pu', 'Voltage limits', 'Maximum voltage, every voltage level', 'p.u.', VOLTAGE_MAX, 'pu',
             note='GridLens proposal, to be confirmed by the engineer'),
    _setting('energized_min_pu', 'Voltage limits', 'De-energised below', 'p.u.', ENERGIZED_MIN_PU, 'pu',
             note='a node below this voltage counts as de-energised at that time step, not as a value'),
    _setting('post_fault_voltage', 'Voltage limits', 'Post-fault voltage limits', '', None, 'text', editable=False,
             applies="n-1, (n-1)'", source=SOURCE_POWERFACTORY, note=PART3_NOTE),
    _setting('loading_change_tolerance', 'Classification', 'n-0 change tolerance, loading', '%-points',
             LOADING_DELTA_TOLERANCE, 'tolerance'),
    _setting('voltage_change_tolerance', 'Classification', 'n-0 change tolerance, voltage', 'p.u.',
             VOLTAGE_DELTA_TOLERANCE, 'tolerance'),
    _setting('limit_tolerance_loading', 'Classification', 'Limit tolerance, loading', '%-points', 0.0, 'tolerance',
             applies="n-1, (n-1)'"),
    _setting('limit_tolerance_voltage', 'Classification', 'Limit tolerance, voltage', 'p.u.', 0.0, 'tolerance',
             applies="n-1, (n-1)'"),
    _setting('numeric_tolerance', 'Classification', 'Numerical comparison tolerance', 'unit of the value',
             NUMERIC_TOLERANCE, 'tolerance', applies="n-1, (n-1)'"),
    _setting('worsened_tolerance_loading', 'Classification', 'WORSENED versus PRE_EXISTING, loading', '%-points',
             LOADING_DELTA_TOLERANCE, 'tolerance', applies="n-1, (n-1)'"),
    _setting('worsened_tolerance_voltage', 'Classification', 'WORSENED versus PRE_EXISTING, voltage', 'p.u.',
             VOLTAGE_DELTA_TOLERANCE, 'tolerance', applies="n-1, (n-1)'"),
    _setting('improved_tolerance_loading', 'Classification', 'IMPROVED versus PRE_EXISTING, loading', '%-points',
             LOADING_DELTA_TOLERANCE, 'tolerance', applies="n-1, (n-1)'"),
    _setting('improved_tolerance_voltage', 'Classification', 'IMPROVED versus PRE_EXISTING, voltage', 'p.u.',
             VOLTAGE_DELTA_TOLERANCE, 'tolerance', applies="n-1, (n-1)'"),
    _setting('margin_warning_loading', 'Classification', 'Reduced margin warning from, loading', '%', LOADING_WARNING,
             'limit', applies="n-1, (n-1)'"),
    _setting('loading_appendix_delta', 'Report', 'Appendix: also list a loading change from', '%-points',
             LOADING_APPENDIX_DELTA, 'tolerance', note='lines and transformers below the warning threshold'),
    _setting('voltage_appendix_delta', 'Report', 'Appendix: also list a voltage change from', 'p.u.',
             VOLTAGE_APPENDIX_DELTA, 'tolerance', note='nodes without a violation'),
    _setting('top_n', 'Report', 'Rows of the Top-N lists', 'rows', TOP_N, 'count'),
    _setting('max_plot_points', 'Report', 'Points per time plot, at most', 'points', MAX_PLOT_POINTS, 'count',
             note='longer series are drawn on an even grid that is the same for every case'),
    _setting('run_reference', 'Run', 'Reference case (REF)', '', RUN_REFERENCE_CASE, 'choice', choices=ON_OFF_CHOICES,
             note='off: no comparison with a reference, every violation counts as found in the case'),
    _setting('max_cases', 'Run', 'Planning cases, at most', 'cases', MAX_CASES, 'count',
             note='every case is one more QDS run over the complete period'),
    _setting('max_n1_times', 'Run', 'n-1 study times per case, at most', 'study times', MAX_N1_TIMES, 'count',
             applies="n-1, (n-1)'", note='every study time calculates every contingency'),
    _contingency_setting('contingency_set', 'Contingency set'),
    _contingency_setting('contingency_categories', 'Equipment categories with contingencies'),
    _contingency_setting('monitored_scope', 'Monitored equipment and network areas'),
    _contingency_setting('calculation_method', 'Load flow method (AC / DC)'),
    _contingency_setting('islanding', 'Islanding'),
    _contingency_setting('unsupplied_load', 'Unsupplied load'),
    _contingency_setting('load_shedding', 'Load shedding'),
    _contingency_setting('post_fault_phases', 'Post-fault time phases'),
    _contingency_setting('remedial_actions', 'Remedial actions'),
)


SETTINGS_BY_KEY = {setting['key']: setting for setting in SETTINGS}


SAME_AS_ASSESSMENT = 'same grids as the assessed equipment'


_ORDERED_PAIRS = (('energized_min_pu', 'voltage_min_pu'), ('voltage_min_pu', 'voltage_max_pu'))


_WARNING_PAIRS = (('line_warning', 'line_limit'), ('transformer_warning', 'transformer_limit'))


def default_settings():
    """The editable values as GridLens ships them."""
    return {setting['key']: setting['default'] for setting in SETTINGS if setting['editable']}


def parse_setting(key, text):
    """(value, None) for a valid entry of one field, or (None, message)."""
    setting = SETTINGS_BY_KEY.get(key)
    if setting is None:
        return None, 'unknown setting {!r}'.format(key)
    if not setting['editable']:
        return None, '{} is read only: {}'.format(setting['label'], setting['note'] or NOT_VERIFIED)
    if setting['kind'] == 'grids':
        return parse_grids(key, text)
    if setting['kind'] == 'choice':
        return (text, None) if any(text == value and type(text) is type(value) for value, _ in setting['choices']) else (
            None, '{}: choose one of {}'.format(setting['label'], ', '.join(label for _, label in setting['choices'])))
    value = text if isinstance(text, (int, float)) and not isinstance(text, bool) else None
    if isinstance(text, str) and re.match(r'^\s*[+-]?(\d+([.,]\d*)?|[.,]\d+)([eE][+-]?\d+)?\s*$', text):
        value = float(text.strip().replace(',', '.'))
    if value is None or not math.isfinite(float(value)):
        return None, '{}: enter a finite number in {}'.format(setting['label'], setting['unit'] or 'its unit')
    value = float(value)
    if setting['kind'] in ('limit', 'kv', 'pu') and value <= 0:
        return None, '{} must be greater than 0 {}'.format(setting['label'], setting['unit']).rstrip()
    if setting['kind'] == 'tolerance' and value < 0:
        return None, '{} must not be negative'.format(setting['label'])
    if setting['kind'] == 'count':
        if value != int(value) or not 1 <= value <= COUNT_LIMITS[key]:
            return None, '{}: enter a whole number from 1 to {}'.format(setting['label'], COUNT_LIMITS[key])
        return int(value), None
    return value, None


def parse_grids(key, value):
    """A grid selection: a list of distinct grid names; None for the contingencies means 'as the assessment'."""
    if value is None and key == 'contingency_grids':
        return None, None
    if not isinstance(value, (list, tuple)) or not all(isinstance(name, str) and name.strip() for name in value):
        return None, '{}: a list of grid names is needed'.format(SETTINGS_BY_KEY[key]['label'])
    names = tuple(name.strip() for name in value)
    if len(set(names)) != len(names):
        return None, '{}: a grid is selected twice'.format(SETTINGS_BY_KEY[key]['label'])
    return tuple(sorted(names, key=str.casefold)), None


def validate_settings(overrides):
    """(key, message) for every problem of a set of overrides; [] when they can be used."""
    if not isinstance(overrides, dict):
        return [('settings', 'settings must be an object of overrides')]
    problems = []
    values = default_settings()
    for key, value in overrides.items():
        parsed, problem = parse_setting(key, value)
        if problem:
            problems.append((key, problem))
        else:
            values[key] = parsed
    if problems:
        return problems
    for lower, upper in _ORDERED_PAIRS:
        if values[lower] >= values[upper]:
            problems.append((lower, '{} ({} {}) must be below {} ({} {})'.format(
                SETTINGS_BY_KEY[lower]['label'], format_limit(values[lower]), SETTINGS_BY_KEY[lower]['unit'],
                SETTINGS_BY_KEY[upper]['label'], format_limit(values[upper]), SETTINGS_BY_KEY[upper]['unit'])))
    for warning, limit in _WARNING_PAIRS:
        if values[warning] > values[limit]:
            problems.append((warning, '{} ({} %) must not exceed {} ({} %)'.format(
                SETTINGS_BY_KEY[warning]['label'], format_limit(values[warning]), SETTINGS_BY_KEY[limit]['label'],
                format_limit(values[limit]))))
    return problems


def effective_settings(overrides=None):
    """Every editable value with the overrides applied; raises GridLensError for invalid overrides."""
    overrides = overrides or {}
    problems = validate_settings(overrides)
    if problems:
        raise GridLensError('The settings cannot be used: {}.'.format('; '.join(message for _, message in problems)))
    values = default_settings()
    for key, value in overrides.items():
        values[key] = parse_setting(key, value)[0]
    return values


def clean_overrides(values):
    """Only the values that differ from the GridLens default; equal values are no override."""
    defaults = default_settings()
    return {key: value for key, value in values.items() if key in defaults and value != defaults[key]}


def setting_source(key, overrides=None):
    return SOURCE_USER if key in (overrides or {}) else SETTINGS_BY_KEY[key]['source']


def setting_text(key, value):
    setting = SETTINGS_BY_KEY[key]
    if setting['kind'] == 'grids':
        if value is None:
            return SAME_AS_ASSESSMENT
        return ', '.join(value) if value else 'every grid'
    if value is None:
        return NOT_VERIFIED
    if setting['kind'] == 'choice':
        return dict(setting['choices']).get(value, str(value))
    return '{} {}'.format(format_limit(value) if setting['kind'] != 'tolerance' else '{:g}'.format(value),
                          setting['unit']).strip()


def overrides_text(overrides):
    """'line limit 110 % (GridLens 100 %); ...' or 'GridLens defaults'."""
    if not overrides:
        return 'GridLens defaults, no user override'
    return '; '.join('{} = {} (GridLens default {})'.format(
        SETTINGS_BY_KEY[key]['label'], setting_text(key, value), setting_text(key, SETTINGS_BY_KEY[key]['default']))
        for key, value in sorted(overrides.items()))


_ACTIVE_SETTINGS = None


def active_overrides():
    """The overrides of the active settings; {} with the GridLens defaults."""
    return clean_overrides(_ACTIVE_SETTINGS or {})


_SETTING_CONSTANTS = {'top_n': 'TOP_N', 'max_plot_points': 'MAX_PLOT_POINTS', 'energized_min_pu': 'ENERGIZED_MIN_PU',
                      'loading_appendix_delta': 'LOADING_APPENDIX_DELTA', 'voltage_appendix_delta': 'VOLTAGE_APPENDIX_DELTA',
                      'run_reference': 'RUN_REFERENCE_CASE', 'max_cases': 'MAX_CASES', 'max_n1_times': 'MAX_N1_TIMES'}


def setting_value(key, overrides=None):
    """A setting of _SETTING_CONSTANTS: the override of `overrides` (default: the active settings), else the constant."""
    found = active_overrides() if overrides is None else overrides
    if key in found:
        value, problem = parse_setting(key, found[key])
        if problem is None:
            return value
    return globals()[_SETTING_CONSTANTS[key]]


CLASSIFICATION_VERSION = '1.0'


MAX_CONTINGENCY_ELEMENTS = 200


def _contents(obj, pattern):
    try:
        return list(obj.GetContents(pattern) or [])
    except Exception:
        return []


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


QDS_CORE_SETTINGS = (
    ("Time period", "calcPeriod"),
    ("Step size", "stepSize"),
    ("Step unit", "stepUnit"),
)


class GridLensError(RuntimeError):
    """Expected runtime error with an actionable user-facing message.

    `details` are the facts behind it (objects, values read back, what was
    found), one line each; `hint` is what the engineer can do. Both appear in
    the failure report.
    """

    def __init__(self, message='', details=(), hint=''):
        super().__init__(message)
        self.details = [str(line) for line in details or ()]
        self.hint = hint


RUN_CONTEXT = {}


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
        if level in ("WARNING", "ERROR") and stage != "FAILED":
            _remember_warning(message)
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
        RUN_CONTEXT['step'] = "STEP {}/{} \u00b7 {}".format(number, TOTAL_STEPS, title)
        RUN_CONTEXT['case'] = ''
        self.section(RUN_CONTEXT['step'])

    def case(self, title):
        RUN_CONTEXT['case'] = title
        head = ".. " + title + " "
        self._plain(head + "." * max(3, self.WIDTH - len(head)))

    def detail(self, message, level="INFO"):
        if level == "WARNING":
            _remember_warning(message)
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


def _remember_warning(message):
    warnings = RUN_CONTEXT.setdefault('warnings', [])
    if len(warnings) < 200:
        warnings.append(((RUN_CONTEXT.get('case') or '') + ': ' if RUN_CONTEXT.get('case') else '') + message.strip())


class RunStats:
    """Time and calls per service and the number of calculations of one run, for the summary at its end."""

    # Order of the summary; services not listed follow in the order they were first used.
    COUNT_LABELS = (
        ('qds_runs', 'QDS runs (ComStatsim.Execute)'), ('qds_steps', 'QDS time steps calculated'),
        ('reused_cases', 'cases reused without a QDS run'), ('series', 'result series read'),
        ('values', 'result values read'), ('columns_bulk', 'result columns read in one call (GetColumnValues)'),
        ('values_cellwise', 'result values read one by one (GetValue, slow)'), ('n1_created', 'contingency analyses created'),
        ('n1_sweeps', 'contingency analysis runs (ComSimoutage.Execute)'), ('n1_times', 'n-1 study times calculated'),
        ('n1_loadflows', 'contingency load flows (study time x contingency)'),
        ('n1_classified', 'n-1 results classified'), ('report_rows', 'report table rows built'))

    def __init__(self):
        self.started = time.monotonic()
        self.services = {}
        self.counts = {}

    def add(self, service, seconds, calls=1):
        entry = self.services.setdefault(service, [0, 0.0])
        entry[0] += calls
        entry[1] += max(0.0, seconds)

    def count(self, name, number=1):
        self.counts[name] = self.counts.get(name, 0) + number

    def measure(self, service):
        """with RUN_STATS.measure('...'): adds the time of the block to the service."""
        stats = self

        class _Block:
            def __enter__(self):
                self.started = time.monotonic()
                return self

            def __exit__(self, *_unused):
                stats.add(service, time.monotonic() - self.started)
                return False
        return _Block()

    def rows(self):
        total = time.monotonic() - self.started
        rows = [(service, str(calls), '{:.1f}'.format(seconds), '{:.0f} %'.format(100.0 * seconds / total) if total else '-')
                for service, (calls, seconds) in self.services.items()]
        measured = sum(seconds for _, seconds in self.services.values())
        rows.append(('other (logging, checks, waiting)', '-', '{:.1f}'.format(max(0.0, total - measured)), '-'))
        rows.append(('total', '-', '{:.1f}'.format(total), '100 %'))
        return rows

    def count_rows(self):
        return [(label, '{:,}'.format(self.counts[key]).replace(',', ' ')) for key, label in self.COUNT_LABELS
                if self.counts.get(key)]


RUN_STATS = RunStats()


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


def _outage_parts(outage):
    """(actions, {key: object}) of an outage, read once: its children and the equipment that it and they name."""
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
    related = {}
    for holder in [outage] + list(children):
        if holder is not outage:
            holder_class = class_name(holder)
            if holder_class.startswith(("Evt", "Sta", "Int")):
                actions.append("{} {}".format(holder_class, object_name(holder)).strip())
        for attribute in OUTAGE_EQUIPMENT_ATTRIBUTES:
            for item in _as_objects(safe_attr(holder, attribute)):
                if not isinstance(item, (str, int, float, bool)) and item is not outage:
                    related.setdefault(object_key(item), item)
    return actions, related


def _outage_details(outage, parts=None):
    """Collect display-only outage context without exposing full PF paths."""
    actions, related = parts or _outage_parts(outage)
    equipment = [(class_name(item), object_name(item)) for item in related.values()]
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
    """Return unique planned outages from the operational-library folder.

    The whole active project is searched only when the outage folder yields
    none, because a recursive search of a large project is expensive.
    """
    folders = []
    getter = getattr(app, "GetProjectFolder", None)
    if callable(getter):
        for key in ("outage", "outages"):
            try:
                folders.extend(_as_objects(getter(key)))
            except Exception:
                pass
    found, queries = _outages_below(folders)
    if not found:
        try:
            project = _as_objects(app.GetActiveProject())
        except Exception:
            project = []
        more, more_queries = _outages_below(project)
        found, queries = found + more, queries + more_queries
    if queries == 0:
        raise GridLensError(
            "Planned-outage discovery could not query the operational library "
            "or active project. No calculation was started.")
    unique = {}
    for outage in found:
        if class_name(outage) in OUTAGE_CLASSES:
            unique[object_key(outage)] = outage
    return sorted(unique.values(), key=lambda item: (
        object_name(item).casefold(), class_name(item), object_key(item)))


def _outages_below(roots):
    """(outages, successful queries) of a recursive search below each root."""
    found, queries = [], 0
    for root in roots:
        for outage_class in OUTAGE_CLASSES:
            pattern = "*.{}".format(outage_class)
            try:
                values = root.GetContents(pattern, 1) or []
                queries += 1
            except TypeError:
                try:
                    values = root.GetContents(pattern) or []
                    queries += 1
                except Exception:
                    values = []
            except Exception:
                values = []
            found.extend(values)
    return found, queries


BRANCH_CLASSES = ("ElmLne", "ElmTr2", "ElmTr3", "ElmCoup")


def _outage_record(outage):
    parts = _outage_parts(outage)
    equipment, equipment_type, actions, start, end = _outage_details(outage, parts)
    _, related = parts
    branches = [item for key, item in related.items() if class_name(item) in BRANCH_CLASSES]
    return {
        "branches": branches,
        "equipment_keys": [key for key, item in related.items() if class_name(item) in BRANCH_CLASSES],
        "component_keys": sorted(related),
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


def data_attributes_text(obj, limit=40):
    """'name=value' of the data attributes an object shows (dir(); GetAttributes fails on data objects)."""
    try:
        names = [name for name in dir(obj) if not name.startswith("_")]
    except Exception:
        return "not readable"
    parts = []
    for name in sorted(names):
        value = safe_attr(obj, name)
        if callable(value) or value is None:
            continue
        if class_name(value):
            shown = "'{}' ({})".format(object_name(value), class_name(value))
        elif isinstance(value, (list, tuple)):
            shown = "[{}]".format(", ".join(object_name(item) if class_name(item) else clip_text(str(item), 20)
                                            for item in value[:6]) + (", ..." if len(value) > 6 else ""))
        elif name.lower().endswith("time") and finite_number(value) is not None:
            shown = _format_pf_time(value)
        else:
            shown = clip_text(str(value), 40)
        parts.append("{}={}".format(name, shown))
    return "; ".join(parts[:limit]) + (" and {} more".format(len(parts) - limit) if len(parts) > limit else "")


def outage_contents_text(outage):
    """What an outage object holds below itself (switching and other actions), with their data, one line each."""
    try:
        children = list(outage.GetContents("*") or [])
    except Exception:
        children = []
    return ["{} '{}': {}".format(class_name(child), object_name(child), data_attributes_text(child, 20))
            for child in children]


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
    logger.detail("What each outage object holds (its data and the actions below it):")
    for number, record in enumerate(records, 1):
        logger.detail("{} {}: {}".format(number, record["name"], data_attributes_text(record["_object"])))
        contents = outage_contents_text(record["_object"])
        for line in contents:
            logger.detail("    below it: " + line)
        if not contents:
            logger.detail("    below it: nothing (no own switching actions; PowerFactory isolates the components itself)")
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
            'project': project_key, 'saved_at': '', 'saved_by': '', 'assessments': ['n-0'], 'background': [],
            'cases': [], 'rules': [], 'settings': {}}


def _occurrence_window(record, plan_case):
    override = (plan_case.get('overrides') or {}).get(record['key'])
    if override:
        return finite_number(override[0]), finite_number(override[1])
    return record['window']


def upgrade_case_config(config):
    """Read version 1 as independent cases, without changing the saved file.

    Formerly inherited outages become direct assignments once. The old
    parent-first order preserves duplicate handling and effective own dates.
    Dependencies and alternative groups no longer restrict any case.
    """
    if not isinstance(config, dict) or config.get('schema') != CASE_CONFIG_SCHEMA or config.get('schema_version') != 1:
        return config
    upgraded = json.loads(json.dumps(config))
    upgraded['schema_version'] = CASE_CONFIG_SCHEMA_VERSION
    cases = upgraded.get('cases', [])
    if not isinstance(cases, list) or not all(isinstance(case, dict) for case in cases):
        return upgraded  # Structural validation supplies the precise error.
    for case in cases:
        for field in ('includes', 'requires'):
            if not _is_text_list(case.get(field, [])):
                raise GridLensError('Cannot upgrade case {!r}: {} must be a list of case ids.'.format(case.get('id'), field))
    # Check the ordinary fields before walking the legacy references.
    plain = dict(upgraded, cases=[{key: value for key, value in case.items() if key not in ('includes', 'requires')}
                                 for case in cases])
    plain.pop('exclusive_groups', None)
    problems = validate_case_config(plain, max_cases=None)
    if problems:
        raise GridLensError('Cannot upgrade case configuration: {}.'.format('; '.join(problems)))
    by_id = {case['id']: case for case in cases}

    def collect(case_id, trail=()):
        if case_id in trail:
            raise GridLensError('Cannot upgrade cases that include each other: {}.'.format(' -> '.join(trail + (case_id,))))
        if case_id not in by_id:
            raise GridLensError('Cannot upgrade: included case {!r} does not exist.'.format(case_id))
        part = by_id[case_id]
        yield part
        for child in part.get('includes') or ():
            yield from collect(child, trail + (case_id,))

    for original, case in zip(cases, plain['cases']):
        outages, overrides = [], dict(original.get('overrides') or {})
        for part in collect(original['id']):
            for key in part.get('outages') or ():
                if key not in outages:
                    outages.append(key)
                    # A parent's unused override must not override a child's date.
                    overrides.pop(key, None)
                    if key in (part.get('overrides') or {}):
                        overrides[key] = part['overrides'][key]
        case.update(outages=outages, overrides=overrides)
    if config.get('exclusive_groups') or any(case.get('includes') or case.get('requires') for case in cases):
        plain['migration_note'] = ('Cases are now independent. Previously shared outages were assigned directly; '
                                   'case dependencies and alternatives were removed. Review the case assignments before starting.')
    return plain


def plan_fingerprint(plan, background):
    """Identity of a calculation: the same active outages with the same windows give the same result."""
    parts = sorted('{}|{}|{}'.format(record['key'], *plan['windows'].get(record['key'], (None, None))) for record in plan['members'])
    parts += sorted('F|{}|{}|{}'.format(record['key'], *record['window']) for record in background)
    return hashlib.sha256('\n'.join(parts).encode('utf-8')).hexdigest()[:16]


def case_limit(config):
    """Most planning cases of a configuration: its 'Planning cases, at most' setting, else MAX_CASES."""
    settings = config.get('settings') if isinstance(config, dict) else None
    return setting_value('max_cases', settings if isinstance(settings, dict) else {})


def assessments_text(assessments):
    """'n-0 quasi-dynamic simulation, n-1, (n-1)'' for preview and log."""
    return ', '.join('n-0 quasi-dynamic simulation' if item == 'n-0' else item for item in assessments or ['n-0'])


def _is_text_list(value):
    return isinstance(value, list) and all(isinstance(item, str) and item for item in value)


def validate_case_config(config, max_cases=-1):
    """Structural problems of a configuration, as messages; [] when it can be used.

    `max_cases` limits the number of planning cases (None: no limit, for the
    one-case-per-outage mode that runs without the case manager).

    A configuration may come from a hand-edited file, so every field is
    checked for its type before anything reads it.
    """
    if not isinstance(config, dict):
        return ['the configuration is not an object']
    if max_cases == -1:
        max_cases = case_limit(config)
    problems = []
    if config.get('schema') != CASE_CONFIG_SCHEMA:
        problems.append('unknown schema {!r}'.format(config.get('schema')))
    if config.get('schema_version') != CASE_CONFIG_SCHEMA_VERSION:
        problems.append('schema version {!r} is not {}'.format(config.get('schema_version'), CASE_CONFIG_SCHEMA_VERSION))
    # 'mode' is a field of earlier versions (time optimisation); it is ignored and no longer saved.
    if config.get('mode', 'conservative') not in ('conservative', 'optimized'):
        problems.append('unknown calculation mode {!r}'.format(config.get('mode')))
    assessments = config.get('assessments', ['n-0'])
    if not _is_text_list(assessments) or not assessments or set(assessments) - set(ASSESSMENTS):
        problems.append('assessments must name at least one of {}'.format(', '.join(ASSESSMENTS)))
    elif 'n-0' not in assessments:
        problems.append('the n-0 quasi-dynamic assessment is always calculated: the report is built on it')
    elif N1_PRIME in assessments and N1_REFERENCE not in assessments:
        problems.append("(n-1)' is compared with n-1, so it needs n-1")
    if not _is_text_list(config.get('background', [])):
        problems.append('background must be a list of planned outage paths')
    problems += ['settings: ' + problem for _, problem in validate_settings(config.get('settings', {}))]
    if not isinstance(config.get('migration_note', ''), str):
        problems.append('migration_note must be text')
    if 'exclusive_groups' in config:
        problems.append('case alternatives are no longer supported; assign planned outages directly to each case')
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
        if not _is_text_list(case.get('outages', [])):
            problems.append('{}: outages must be a list of texts'.format(label))
        if 'includes' in case or 'requires' in case:
            problems.append('{}: case relations are no longer supported; assign planned outages directly'.format(label))
        overrides = case.get('overrides', {})
        if not isinstance(overrides, dict):
            problems.append('{}: overrides must be an object'.format(label))
            continue
        for key, window in overrides.items():
            numbers = [finite_number(value) for value in window] if isinstance(window, list) else []
            if len(numbers) != 2 or None in numbers or numbers[1] <= numbers[0]:
                problems.append('{}: own dates of {!r} must be [start, end] in epoch seconds with end after start'.format(label, key))
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

    Each case lists only its directly assigned occurrences (each once),
    their effective windows, the network states and the
    proposed calculation windows. A case that breaks a rule gets the status
    NOT EVALUATED with the reason; nothing is combined automatically.
    """
    problems = validate_case_config(config, None if source == 'per_outage' else case_limit(config))
    if problems:
        raise GridLensError('The case configuration cannot be used: {}.'.format('; '.join(problems)))
    by_key = {record['key']: record for record in records}
    by_name = {record['id']: record for record in records}
    lookup = lambda key: by_key.get(key) or by_name.get(key)
    background = []
    request_warnings = [config['migration_note']] if config.get('migration_note') else []
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
    # An excluded case is neither calculated nor reported.
    disabled = [case['id'] for case in config.get('cases') or () if case.get('enabled', True) is False]
    for case in config.get('cases') or ():
        if case['id'] in disabled:
            continue
        plan = {'id': case['id'], 'name': str(case.get('name') or case['id']), 'description': str(case.get('description') or ''),
                'members': [], 'windows': {}, 'status': PLAN_READY, 'reason': '', 'warnings': [], 'states': [],
                'relations': [], 'overridden': []}
        errors = []
        for key in case.get('outages') or ():
            record = lookup(key)
            if record is None:
                errors.append('planned outage {!r} no longer exists in the project'.format(key))
                continue
            if record in plan['members']:
                continue
            plan['members'].append(record)
            plan['windows'][record['key']] = _occurrence_window(record, case)
            if (case.get('overrides') or {}).get(record['key']):
                plan['overridden'].append(record)
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
        plan['fingerprint'] = plan_fingerprint(plan, background)
        plans.append(plan)
    return {'source': source, 'source_text': source_text or source, 'revision': config.get('revision'),
            'background': background, 'cases': plans, 'skipped': [], 'records': list(records), 'config': config,
            'warnings': request_warnings, 'disabled': disabled, 'assessments': list(config.get('assessments') or ['n-0']),
            'settings': dict(config.get('settings') or {})}


def legacy_case_config_path(project_key):
    """Where GridLens 8.0 (schema 1) keeps the cases of a project; this version only reads that file."""
    folder = CASE_CONFIG_DIR or os.path.join(os.path.expanduser('~'), 'GridLens', 'cases')
    stem = re.sub(r'[^A-Za-z0-9_.-]+', '_', project_key.rsplit('\\', 1)[-1])[:40] or 'project'
    digest = hashlib.sha256(project_key.encode('utf-8')).hexdigest()[:8]
    return os.path.join(folder, '{}_{}.json'.format(stem, digest))


def case_config_path(project_key):
    """The file this version saves to. It has its own name, so a schema-2 file never replaces the
    schema-1 file that the delivered gridlens-powerfactory script reads for the same project."""
    stem, extension = os.path.splitext(legacy_case_config_path(project_key))
    return '{}.v{}{}'.format(stem, CASE_CONFIG_SCHEMA_VERSION, extension)


def _legacy_sibling(path):
    """The schema-1 file next to a versioned path, or None."""
    marker = '.v{}.json'.format(CASE_CONFIG_SCHEMA_VERSION)
    return path[:-len(marker)] + '.json' if path.endswith(marker) else None


def load_case_config(path):
    """The saved configuration, or None when there is none; a damaged file raises.

    Only the structure is checked here, not the number of cases: a file with
    more cases than MAX_CASES (e.g. saved by GridLens 8.0) must still open in
    the case manager, where cases can be deleted. Calculating and saving it is
    refused with the reason (resolve_request, save_case_config).
    """
    if not os.path.isfile(path):
        # Not saved by this version yet: start from the GridLens 8.0 file, read only.
        legacy = _legacy_sibling(path)
        if legacy is None or not os.path.isfile(legacy):
            return None
        path = legacy
    try:
        with open(path, 'r', encoding='utf-8') as handle:
            config = json.load(handle)
    except (OSError, ValueError) as exc:
        raise GridLensError('The saved case configuration {} cannot be read: {}'.format(path, exc)) from None
    try:
        config = upgrade_case_config(config)
    except GridLensError as exc:
        raise GridLensError('The saved case configuration {} cannot be upgraded: {}'.format(path, exc)) from None
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
    # The upgrade note is a one-time hint; once saved, the cases are the reviewed ones.
    stored.pop('migration_note', None)
    stored.pop('mode', None)
    folder = os.path.dirname(path)
    if folder:
        os.makedirs(folder, exist_ok=True)
    temporary = path + '.tmp'
    with open(temporary, 'w', encoding='utf-8') as handle:
        json.dump(stored, handle, indent=2, sort_keys=True)
    os.replace(temporary, path)
    config['revision'] = stored['revision']
    config.pop('migration_note', None)
    return stored


class CaseManagerUnavailable(GridLensError):
    """tkinter or Tcl/Tk cannot open a window in this PowerFactory installation."""


MARK_IN_CASE, MARK_FIXED, MARK_FREE = '\u2611 in case', 'fixed', '\u2610'


RULE_LABELS = (('not_overlap', 'must not overlap'), ('order', 'second only after the first'), ('together', 'only together'))


OUTAGE_FILTERS = ('All planned outages', 'Not in this case', 'In simulated period', 'Ignored in PowerFactory')


SETTINGS_INTRO = ('Limits and classification parameters (category A) only interpret calculated results; they never '
                  'change a load flow, a rating or the network model. Calculation parameters (category B) stay read '
                  'only until the PowerFactory contingency interface is verified. Settings are stored provisionally '
                  'in the case configuration file of this project, not yet inside the PowerFactory project.')


CONTINGENCIES_NOT_READ = 'not read'


N1_NOTE = ("Calculated with the contingency analysis (ComSimoutage) of the active study case, at the QDS time steps "
           "inside the outage windows of each case. Until the report chapters for n-1 exist (part 4), the result "
           "appears in the log and on the Model Quality Assurance page.")


HELP_TEXTS = {
    'description': "Double-click to write or change the description of the case: Enter or a click elsewhere "
                   "applies, Escape cancels.",
    'enabled': "Run flag: include this case in the calculation\n"
               "Ticked: the case is calculated and reported, in its own QDS run with the result object "
               "GridLens_<stamp>_<case>. A case with exactly the same outages and windows as another is calculated "
               "once and reported as REUSED.\n"
               "Unticked: status 'excluded'. The case stays in the configuration but is neither calculated nor "
               "reported. Other cases stay unchanged.",
    'case_limit': "At most the number of planning cases set in Settings -> Report and run (GridLens default {}). Each "
                  "case is one more QDS run over the complete period.".format(MAX_CASES),
    'New': "Creates the next case (C1, C2, ...) with the name 'Case n'. Double-click it to rename it. Key: Ctrl+N.",
    'Copy': "New independent case with the same planned outages and own dates. Changes affect only the copy.",
    'Delete': "Removes only the selected case after confirmation. Other cases and the planned outages in PowerFactory "
              "stay unchanged. Key: Delete in the case list.",
    'one_per_outage': "Replaces all cases by one case per planned outage in the simulated period (GridLens 7 "
                      "behaviour), up to the case limit of the Settings. Ignored and fixed outages get none. Asks "
                      "before replacing.",
    'add': "Assigns all selected planned outages to the selected case at once. Same as Enter. For one outage, "
           "tick its box in the first column.\n"
           "An outage already in the case or fixed is refused with the reason.",
    'fix': "Makes the selected planned outages fixed background outages: active in the reference (Rfix) and in "
           "every case. Not possible while an outage is assigned to a case, so it never acts twice.",
    'details': "What PowerFactory holds for the planned outage: object, equipment, window, priority, status and "
               "the cases that use it. Own dates per case are entered there. Same as a double-click on the row.",
    'remove': "Ends only the assignment to this case; the planned outage in PowerFactory stays unchanged. "
              "Same as the Delete key.",
    'unfix': "The selected outages are no longer fixed; the reference becomes R0 when none is left. Key: Delete.",
    'timeline': "Planning check only, no load flow and no dates: which outages of this case are active at the same "
                "time and in which order. Blue: case outage, "
                "grey: fixed background outage, shaded: several outages at the same time (normal, no problem), light band: a "
                "long empty period drawn short.",
    'rule_kind': "must not overlap: a case with both outages is refused if their windows overlap.\n"
                 "second only after the first: the second may only start after the first has ended.\n"
                 "only together: a case with one of them must contain the other, at the same time.\n"
                 "Rules apply to every case; a case that breaks one is not calculated and is reported.",
    'n0': "n-0 - reference QDS\nCalculates the time-dependent base state of the network without planned outages and "
          "without additional contingencies. Loads and infeeds change as in the quasi-dynamic simulation.",
    'n1': "n-1 - reference contingency analysis\nAssesses the security of the base network without planned outages. "
          "Every defined unplanned single contingency is assessed at the chosen points in time.\n" + N1_NOTE,
    'n1_prime': "(n-1)' - contingency analysis with planned-outage scenarios\nAssesses a planned-outage scenario with "
                "the planned outages valid at each point in time and one additional unplanned contingency. The results "
                "are compared with n-1. Needs n-1.\n" + N1_NOTE,
    'planned_outages': "Planned outages from the PowerFactory Outage Management library. Their validity in time and "
                       "their switching effect are taken into account in the assigned scenarios.",
    'qds': "The time step is taken from PowerFactory. With a QDS time step of two hours, n-1 and (n-1)' are assessed "
           "at the same points in time. Every run covers the complete ComStatsim period; GridLens changes neither "
           "the period nor the time step.",
    'results': "Calculate now: every case is calculated into a new kept result object GridLens_<stamp>_<case>, then "
               "evaluated.\nRe-evaluate a kept run: nothing is calculated and PowerFactory is not changed; the result "
               "objects of that run are read again and assessed with the current settings (limits, tolerances, grids). "
               "A case whose outages or windows changed since that run is reported as NOT EVALUATED.",
    'status_line': "Click to open the Case Manager tab: what will be calculated and every problem or warning.",
    'preview': "Shows or hides the calculation preview: which cases are calculated, with which reference, settings and "
               "planned outages. It never calculates anything.",
    'save': "Writes the configuration file of this project (cases, fixed outages, rules and settings, with revision, "
            "user and time). The project is not touched. Key: Ctrl+S.",
    'load': "Reads the saved configuration file again; unsaved changes in the window are replaced. Key: Ctrl+O.",
    'start': "Checks the configuration and the settings, closes the window and runs the selected PowerFactory "
             "calculations: the reference and one QDS run per case. The results stay in PowerFactory as result objects "
             "and are published to the GridLens report tables; the PDF report is created in PowerFactory as a separate "
             "step. Key: Ctrl+Enter.",
    'cancel': "Closes the window: nothing is calculated, saved or changed in the project. Key: Escape.",
}


SETTING_HELP = {
    'line_warning': "From this loading GridLens marks a line as conspicuous (pie chart class, appendix). The warning "
                    "threshold does not change the physical capability of the equipment.",
    'transformer_warning': "From this loading GridLens marks a transformer as conspicuous (pie chart class, appendix). "
                           "The warning threshold does not change the physical capability of the equipment.",
    'line_limit': "Maximum n-0 loading of lines: limit for assessing the undisturbed base network. The default comes "
                  "from the existing GridLens configuration (100 %). Loading above it is a violation; exactly on it is none.",
    'transformer_limit': "Maximum n-0 loading of transformers: limit for assessing the undisturbed base network. The "
                         "default comes from the existing GridLens configuration (100 %).",
    'n1_limit_mode': "Maximum n-1 loading: limit for assessing equipment after an additional unplanned outage. n-1 and "
                     "(n-1)' must use a comparable limit definition. 'use PowerFactory limits' keeps the equipment "
                     "ratings modelled in PowerFactory; a global assessment limit only changes the assessment, never a "
                     "rating, a model parameter or the load flow.",
    'n1_limit_global': "Assessment limit for n-1 and (n-1)' when 'global assessment limit' is chosen. It is an "
                       "assessment limit only: ratings and thermal data in PowerFactory stay unchanged.",
    'voltage_min_pu': "Lower permitted voltage in p.u. of the nominal voltage, the same for every voltage level. "
                      "Voltages below it are assessed as a limit violation. GridLens proposal, to be confirmed.",
    'voltage_max_pu': "Upper permitted voltage in p.u. of the nominal voltage, the same for every voltage level. "
                      "Voltages above it are assessed as a limit violation. GridLens proposal, to be confirmed.",
    'energized_min_pu': "Below this voltage a node counts as de-energised at that time step: it is no measured value "
                        "and the node is reported as DE-ENERGISED, not as a voltage violation.",
    'loading_appendix_delta': "The appendix lists every line and transformer from the warning threshold on, and "
                              "below it every element whose loading changes by at least this much against REF.",
    'voltage_appendix_delta': "The appendix lists every node with a violation, and every node whose voltage changes "
                              "by at least this much against REF.",
    'top_n': "Number of rows of the Top-N lists (most loaded lines, strongly loaded lines by case).",
    'max_plot_points': "Time plots draw every time step up to this number; longer series are drawn on an even grid "
                       "that is the same for REF and every case. The assessment always uses every time step.",
    'run_reference': "On: GridLens calculates the reference REF (R0 or Rfix) and compares every case with it. Off: "
                     "no reference; violations cannot be split into new and pre-existing.",
    'max_cases': "Most planning cases one run may hold. Every case is one more QDS run over the complete period, "
                 "so the run time grows with each case.",
    'max_n1_times': "Most n-1 study times per case. Every study time calculates every contingency twice (n-1 and "
                    "(n-1)'); a case with more study times is not evaluated and says so.",
    'post_fault_voltage': "Post-fault voltage limits per post-fault time phase. PowerFactory's post-fault phases are "
                          "not verified yet, so no separate limit can be set.",
    'loading_change_tolerance': "n-0 QDS: a loading change smaller than this (in %-points) counts as unchanged when a "
                                "case is compared with the reference at the same time step.",
    'voltage_change_tolerance': "n-0 QDS: a voltage change smaller than this (in p.u.) counts as unchanged when a case "
                                "is compared with the reference at the same time step.",
    'limit_tolerance': "n-1 / (n-1)' classification: a value counts as a violation only when it lies more than this "
                       "beyond the limit. 0 keeps the rule 'exactly on the limit is no violation'.",
    'numeric_tolerance': "Numerical comparison tolerance for rounding noise of the results; far below any meaningful "
                         "difference. It is added to every other tolerance of the classification.",
    'worsened_tolerance': "Classification tolerance: from which numerical increase an existing limit violation counts "
                          "as WORSENED instead of PRE_EXISTING.",
    'improved_tolerance': "Classification tolerance: from which numerical decrease an existing limit violation counts "
                          "as IMPROVED instead of PRE_EXISTING.",
    'margin_warning_loading': "Marks an OK result with MARGIN_REDUCED when its loading reaches at least this value and "
                              "its reserve to the limit shrank by more than the WORSENED tolerance.",
    'contingency_set': "Defines which additional unplanned equipment outages are analysed in PowerFactory.",
    'contingency_categories': "Equipment categories for which PowerFactory creates contingencies.",
    'monitored_scope': "Equipment and network areas whose results the contingency analysis monitors.",
    'calculation_method': "AC or DC load flow of the contingency analysis. GridLens prefers an AC load flow for the "
                          "final security assessment.",
    'islanding': "Takes into account whether an additional outage splits the network into electrically separate parts.",
    'unsupplied_load': "Takes into account supply interruptions, i.e. the load that can no longer be supplied after a "
                       "fault, as far as PowerFactory can determine it.",
    'load_shedding': "How load shedding after a contingency is treated.",
    'post_fault_phases': "The post-fault time phases defined in PowerFactory.",
    'remedial_actions': "The remedial actions defined in PowerFactory. They can change the calculated result.",
    'limits': "Defines from when GridLens assesses a calculated state as critical. Changing assessment limits does not "
              "change the physical network model.",
    'classification': "Compares n-1 and (n-1)' at the same point in time, for the same contingency and the same "
                      "monitored equipment. Rules version " + CLASSIFICATION_VERSION + ".",
    'calculation_parameters': "Category B: these parameters can change what PowerFactory calculates. " + PART3_NOTE,
    'restore_defaults': "Removes the user overrides and loads the valid default values of GridLens (and of PowerFactory, "
                        "once those are read).",
    'apply_settings': "Checks the entries and uses the settings for the next selected calculations.",
    'save_settings': "Checks the entries and saves the settings for later use. Provisional: they are written into the "
                     "case configuration file of this project (JSON), not yet into the PowerFactory project; the "
                     "project itself is not touched.",
    'monitoring_grids': "Only lines, transformers and terminals in the selected grids are assessed: their QDS results "
                        "and the monitored elements of n-1 and (n-1)'. Every other element is ignored as "
                        "foreign network. No grid selected: every grid. The selection only filters the assessment; "
                        "PowerFactory still calculates the whole network.",
    'contingency_grids': "Only contingencies whose outaged equipment lies in the selected grids are analysed. 'Same "
                         "grids as the assessed equipment' follows the left selection. This changes what PowerFactory "
                         "calculates (category B): the other contingencies are set to 'Not analysed' for the n-1 run "
                         "and restored afterwards.",
    'contingency_preview': "How many contingencies of the study case's contingency analysis the selection would keep. "
                           "Their equipment is read with ComOutage.GetObject; nothing is changed.",
    'grid_buttons': "Selects every grid, or clears the selection so that every grid is assessed. Takes effect at once.",
    'source': "Origin of the value: GridLens (GridLens default), PowerFactory (read from the model or the calculation "
              "configuration) or user (changed by you). 'edited, not applied' means the entry differs from the applied "
              "value until you apply or save the settings.",
}


def setting_help(key):
    """The hover text of one setting, with the reason when it is read only."""
    setting = SETTINGS_BY_KEY[key]
    family = key
    for prefix in ('limit_tolerance', 'worsened_tolerance', 'improved_tolerance'):
        if key.startswith(prefix):
            family = prefix
    text = SETTING_HELP.get(family, setting['label'])
    details = ['Applies to: {}.'.format(setting['applies'])]
    if setting['note'] and setting['note'] not in text:
        details.append(setting['note'])
    if setting['category'] == CATEGORY_CALCULATION:
        details.insert(0, 'Category B (calculation parameter).')
    return text + '\n' + ' '.join(details)


COLUMN_HELP = {
    'case_name': "Double-click a case (or press F2) to rename it in place: Enter or a click elsewhere applies, "
                 "Escape cancels. The generated case ID stays.",
    'case_status': "ready: will be calculated.\n"
                   "not calculated: reported as NOT EVALUATED or NOT SIMULATED, e.g. no planned outage assigned, "
                   "an outage missing in the project, own dates, a broken outage rule, or outside the "
                   "simulated period. The reason is under Problems and warnings.\n"
                   "excluded: the Run flag is unticked.",
    'case_count': "Number of planned outages assigned to this case.",
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

    def __init__(self, records, config, period, qds_text='', qds_info=None, grids=None, contingencies=CONTINGENCIES_NOT_READ,
                 kept=()):
        self.records = list(records)
        # Stamps of earlier runs whose result objects are kept in the study case (kept_stamps), newest first,
        # and the one chosen for a re-evaluation without calculation (None: calculate now).
        self.kept_stamps = list(kept or ())
        self.evaluate_stamp = None
        # Names of the active grids (None: not read) and the contingencies of the study case
        # (read_contingencies; None: there is no ComSimoutage), both read before the window opened.
        # A grid is a name or (name, active); a bare name counts as active.
        pairs = None if grids is None else [(grid, True) if isinstance(grid, str) else (grid[0], bool(grid[1])) for grid in grids]
        self.grids = None if pairs is None else [name for name, _ in pairs]
        self.inactive_grids = {name for name, active in pairs or () if not active}
        self.contingencies = contingencies
        self.by_key = {record['key']: record for record in self.records}
        self.period = period
        self.qds_text = qds_text or qds_period_text(period)
        # (label, value) lines of the ComStatsim time base, shown read only.
        self.qds_info = list(qds_info or qds_time_info(None, period))
        self._checked_state = None
        self._outage_choices = None
        self.load(config)

    def load(self, config):
        """Replace the edited configuration, e.g. by the saved one."""
        self.config = json.loads(json.dumps(upgrade_case_config(config)))
        for name in ('cases', 'background', 'rules'):
            self.config.setdefault(name, [])
        self.config.setdefault('assessments', ['n-0'])
        # No time optimisation: every run covers the complete ComStatsim period,
        # so the field of earlier versions is dropped.
        self.config.pop('mode', None)
        self.config.setdefault('settings', {})

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
        """Why no further case can be created; None while fewer than the case limit exist."""
        if len(self.config['cases']) >= case_limit(self.config):
            return 'At most {} planning cases are possible. Delete or reuse a case first, or raise the limit in ' \
                   'Settings -> Report and run.'.format(case_limit(self.config))
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
                                     'enabled': True, 'outages': [], 'overrides': {}})
        return identifier, None

    def rename_case(self, case_id, name):
        """Only the name changes; the ID used for result objects stays."""
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
        """A new independent case with the same planned outages and own dates; (id, None) or (None, problem)."""
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
        return identifier, None

    def delete_case(self, case_id):
        """Remove only this case; other cases and PowerFactory outages stay unchanged."""
        case = self.case(case_id)
        if case is not None:
            self.config['cases'].remove(case)

    def one_case_per_outage(self):
        """One case per planned outage in the simulated period, up to the case limit; a note when outages were left out."""
        limit = case_limit(self.config)
        candidates = [record for record in self.records if self.outage_status(record) == 'in simulated period'
                      and record['key'] not in self.config['background']]
        self.config['cases'] = []
        for record in candidates[:limit]:
            identifier, _ = self.add_case(record['id'])
            self.case(identifier)['outages'] = [record['key']]
        if len(candidates) > limit:
            return 'Only the first {} of {} planned outages got a case (at most {} cases).'.format(limit, len(candidates), limit)
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
        background = set(self.config['background'])
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
            mark = MARK_IN_CASE if record['key'] in members else MARK_FIXED if record['key'] in background else MARK_FREE
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

    # --- rules between planned outages -------------------------------------------
    def outage_choices(self):
        """(label, key) of every planned outage, sorted; the PowerFactory path is added where names repeat.

        The records do not change while the window is open, so the list is built once.
        """
        if self._outage_choices is not None:
            return self._outage_choices
        counts = {}
        for record in self.records:
            counts[record['id']] = counts.get(record['id'], 0) + 1
        choices = [(record['id'] if counts[record['id']] == 1 else '{} ({})'.format(record['id'], record['key']), record['key'])
                   for record in self.records]
        self._outage_choices = sorted(choices, key=lambda item: item[0].casefold())
        return self._outage_choices

    def rule_rows(self):
        if not self.config['rules']:
            return []
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

    # --- settings ----------------------------------------------------------------
    def settings_overrides(self):
        return dict(self.config.get('settings') or {})

    def settings_rows(self):
        """(key, label, unit, value text, source, category, editable) of every setting, in SETTINGS order."""
        overrides = self.settings_overrides()
        values = default_settings()
        values.update({key: value for key, value in overrides.items() if key in values})
        return [(setting['key'], setting['label'], setting['unit'],
                 setting_text(setting['key'], values.get(setting['key'], setting['default'])),
                 setting_source(setting['key'], overrides), setting['category'], setting['editable'])
                for setting in SETTINGS]

    def set_settings(self, values):
        """Take the edited values of the Settings tab; [(key, problem)] and nothing changes when one is invalid."""
        parsed, problems = {}, []
        try:
            current = effective_settings(self.settings_overrides())
        except GridLensError:
            current = default_settings()
        for key, value in values.items():
            number, problem = parse_setting(key, value)
            if problem:
                problems.append((key, problem))
            else:
                parsed[key] = number
        if problems:
            return problems
        overrides = clean_overrides(dict(current, **parsed))
        problems = validate_settings(overrides)
        if not problems:
            self.config['settings'] = overrides
        return problems

    def restore_default_settings(self):
        """Remove every user override; the GridLens defaults apply again."""
        self.config['settings'] = {}

    # --- network scope ---------------------------------------------------------------
    def selected_grids(self, key):
        """The grid selection of 'monitoring_grids' or 'contingency_grids'; None: as the assessed equipment."""
        value = self.settings_overrides().get(key, SETTINGS_BY_KEY[key]['default'])
        return None if value is None else tuple(value)

    def grid_choices(self):
        """The grids to choose from: every grid of the model, plus selected ones the project no longer has."""
        chosen = set(self.selected_grids('monitoring_grids')) | set(self.selected_grids('contingency_grids') or ())
        return sorted(set(self.grids or ()) | chosen, key=str.casefold)

    def set_grids(self, key, names):
        """Select grids at once (no Apply needed); None for the contingencies means 'as assessed'. A problem or None."""
        value, problem = parse_grids(key, None if names is None else list(names))
        if problem:
            return problem
        try:
            current = effective_settings(self.settings_overrides())
        except GridLensError:
            current = default_settings()
        current[key] = value
        self.config['settings'] = clean_overrides(current)
        return None

    def grid_problems(self):
        """(where, warning) for selected grids that are missing or inactive in the project."""
        if self.grids is None:
            return []
        known = set(self.grids)
        rows = []
        for key, what in (('monitoring_grids', 'assessed equipment'), ('contingency_grids', 'contingencies')):
            for name in self.selected_grids(key) or ():
                if name not in known:
                    rows.append(('network scope', 'Warning: grid {!r} of the {} no longer exists in the project; '
                                                  'it selects nothing'.format(name, what)))
                elif name in self.inactive_grids:
                    rows.append(('network scope', 'Warning: grid {!r} of the {} is not active in this study case; '
                                                  'its equipment is not calculated'.format(name, what)))
        return rows

    def contingency_preview(self):
        if self.contingencies == CONTINGENCIES_NOT_READ:
            return 'contingencies not read in this window'
        return contingency_scope_text(self.contingencies, self.selected_grids('contingency_grids'),
                                      self.selected_grids('monitoring_grids'))

    def monitoring_text(self):
        grids = self.selected_grids('monitoring_grids')
        if grids:
            return ', '.join(grids)
        return 'every grid' + (' named *{}*'.format(GRID_NAME_FILTER) if GRID_NAME_FILTER else '')

    # --- assessment and preview ------------------------------------------------
    def set_assessments(self, n0, n1=False, n1_prime=False):
        """The requested assessments; a problem as text, else None."""
        if not n0 and not n1 and not n1_prime:
            return 'Select at least one assessment.'
        if not n0:
            return 'n-0 is always calculated: the report is built on it.'
        if n1_prime and not n1:
            return "(n-1)' is compared with n-1, so it needs n-1."
        self.config['assessments'] = ['n-0'] + ([N1_REFERENCE] if n1 else []) + ([N1_PRIME] if n1_prime else [])
        return None

    def request(self):
        request = resolve_request(self.config, self.records, self.period, 'gui')
        request['evaluate_stamp'] = self.evaluate_stamp
        return request

    def result_choices(self):
        """(label, stamp) of the Results choice: calculate now, or re-evaluate a kept run."""
        return [(RESULTS_CALCULATE, None)] + [('Re-evaluate the kept run of ' + stamp_text(stamp), stamp)
                                              for stamp in self.kept_stamps]

    def set_evaluate_stamp(self, stamp):
        """Choose a kept run to re-evaluate (None: calculate now); a problem as text, else None."""
        if stamp is not None and stamp not in self.kept_stamps:
            return 'No kept run {} in this study case.'.format(stamp)
        self.evaluate_stamp = stamp
        return None

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
        rows += [('configuration' if warning == self.config.get('migration_note') else 'fixed outages', warning)
                 for warning in request['warnings']]
        rows += self.grid_problems()
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

    def calculation_preview(self):
        """Read-only plan of ready cases and their effective settings; never calculates."""
        problems, request = self.checked()
        if problems:
            return 'Fix the configuration problems below before starting.'
        def window_text(window):
            return ' to '.join(_format_pf_time(value) if value is not None else '?' for value in window)
        background = request['background']
        fixed = ', '.join(record['name'] for record in background) or 'none'
        lines = ['Results: ' + (RESULTS_CALCULATE if not self.evaluate_stamp else
                                'Re-evaluate the kept run of {} (no calculation)'.format(stamp_text(self.evaluate_stamp))),
                 'Assessment: ' + assessments_text(self.config.get('assessments')),
                 'QDS period: ' + self.qds_text,
                 'Reference: ' + (('Rfix' if background else 'R0') if setting_value('run_reference', self.settings_overrides())
                                  else 'off'),
                 'Shared background: ' + fixed,
                 'Assessed equipment: ' + self.monitoring_text(),
                 'Contingencies: ' + self.contingency_preview(),
                 'Settings: ' + overrides_text(self.settings_overrides())]
        for record in background:
            lines.append('  {}: {}'.format(record['name'], window_text(record['window'])))
        for _, (first, rule, second) in self.rule_rows():
            lines.append('Rule: {} / {} / {}'.format(first, rule, second))
        calculated = {}
        ready = [plan for plan in request['cases'] if plan['status'] == PLAN_READY]
        for plan in ready:
            source = calculated.setdefault(plan['fingerprint'], plan['id'])
            reused = source != plan['id']
            lines += ['', '{} ({})'.format(plan['name'], plan['id']),
                      '  n-0; complete QDS period; ' + ('reuse result from ' + source if reused else 'separate QDS run'),
                      '  Shared background: ' + fixed]
            if plan['description']:
                lines.append('  Description: ' + plan['description'])
            for record in plan['members']:
                lines.append('  {}: {}'.format(record['name'], window_text(plan['windows'][record['key']])))
        if not ready:
            lines += ['', 'No planning case is ready to calculate.']
        for plan in request['cases']:
            if plan['status'] != PLAN_READY:
                lines += ['', 'Not calculated: {} — {}'.format(plan['name'], plan['reason'])]
        if request['disabled']:
            lines += ['', 'Excluded (Run flag off): ' + ', '.join(self.case_label(item) for item in request['disabled'])]
        return '\n'.join(lines)

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
            ('Assessment', assessments_text(self.config.get('assessments'))),
            ('Assessed equipment', self.monitoring_text()),
            ('Settings', overrides_text(self.settings_overrides())),
            ('Calculation runs', '{} reference + {} case run(s){}'.format(
                1 if setting_value('run_reference', self.settings_overrides()) else 0, len(ready) - reused,
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
    BACKGROUND, BORDER = '#FFFFFF', '#DCE5EC'

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
                 foreground='#203449', relief='solid', borderwidth=1, highlightbackground=self.BORDER,
                 font='TkDefaultFont', padx=12, pady=10).pack()
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
    HEADER_HEIGHT, FILTER_HEIGHT = 34, 38

    def __init__(self, dialog, parent, columns, height=8, selectmode='extended', tag_column=None, tips=None):
        """`columns`: (id, heading, width, stretch, choices); choices None for text, else labels or (label, value) pairs.

        `tips`: hover text per column id, shown on the heading together with how sorting works.
        """
        tk, ttk = dialog.tk, dialog.ttk
        self.dialog = dialog
        self.columns = columns
        self.rows = []
        self._rendered = {}
        self._visible_keys = None
        self.sort_column, self.descending = None, False
        self.tag_column = tag_column
        self._pending = None
        self.HEADER_HEIGHT = round(34 * dialog.ui_scale)
        self.FILTER_HEIGHT = round(38 * dialog.ui_scale)
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
        self.scroll = ttk.Scrollbar(self.frame, orient='vertical', command=self.tree.yview)
        self.tree.configure(yscrollcommand=self._yscroll)
        self.horizontal = ttk.Scrollbar(self.frame, orient='horizontal', command=self.tree.xview)
        self.horizontal.grid(row=3, column=0, sticky='ew')
        self.tree.configure(xscrollcommand=self._xscroll)
        self.empty = ttk.Label(self.tree, text='No entries', style='Muted.TLabel', anchor='center', wraplength=240)
        footer = ttk.Frame(self.frame, style='Card.TFrame')
        footer.grid(row=4, column=0, columnspan=2, sticky='ew', pady=(6, 0))
        self.count = ttk.Label(footer, text='', style='Muted.TLabel')
        self.count.grid(row=0, column=0, sticky='w')
        self.clear = ttk.Button(footer, text='Clear filters', style='Link.TButton', command=self.clear_filters)
        self.clear.grid(row=0, column=1, sticky='w', padx=(10, 0))
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
        # Keep dates, flags and filters readable. Narrow panes scroll horizontally
        # instead of squeezing every field down to a few characters.
        scale = self.dialog.ui_scale
        minimum = [round(max(50, min(base, 140))*scale) for _, _, base, _, _ in self.columns]
        widths = column_widths([(round(base*scale), stretch) for _, _, base, stretch, _ in self.columns],
                               max(width, sum(minimum)))
        widths = [max(value, least) for value, least in zip(widths, minimum)]
        self._column_sizes = widths
        for index, (name, _, _, _, _) in enumerate(self.columns):
            column_width = widths[index]
            self.tree.column(name, width=column_width, minwidth=20, stretch=False)
        self._place_headers()

    def _place_headers(self):
        widths = getattr(self, '_column_sizes', [])
        first = self.tree.xview()[0]
        icon_width = int(self.tree.column('#0', 'width')) if 'tree' in self.tree.cget('show') else 0
        x = icon_width - round(first * (sum(widths) + icon_width))
        for index, column_width in enumerate(widths):
            self.labels[index].place(x=x, y=0, width=column_width, height=self.HEADER_HEIGHT)
            self.inputs[index].place(x=x + 2, y=3, width=max(26, column_width - 4), height=self.FILTER_HEIGHT - 6)
            x += column_width

    def _xscroll(self, first, last):
        self.horizontal.set(first, last)
        if float(first) <= 0 and float(last) >= 1:
            self.horizontal.grid_remove()
        else:
            self.horizontal.grid()
        self._place_headers()

    def _yscroll(self, first, last):
        self.scroll.set(first, last)
        if float(first) <= 0 and float(last) >= 1:
            self.scroll.grid_remove()
        else:
            self.scroll.grid(row=2, column=1, sticky='ns')

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
        if rows == self.rows and self._visible_keys is not None:
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
        keep = self.tree.selection()
        # Keep native rows alive across case changes and filtering. With
        # thousands of outages, deleting/reinserting the entire table for one
        # changed checkbox blocks Tk and also resets the scroll position.
        data_keys = {str(key) for key, _ in self.rows}
        removed = self._rendered.keys() - data_keys
        if removed:
            self.tree.delete(*removed)
            for key in removed:
                del self._rendered[key]
        visible = []
        for key, cells in rows:
            key = str(key)
            visible.append(key)
            tag = cells[self.tag_column] if self.tag_column is not None and cells[self.tag_column] else None
            tags = (tag,) if tag else ()
            state = (tuple(cells), tags)
            if key not in self._rendered:
                self.tree.insert('', 'end', iid=key, values=cells, tags=tags)
            elif self._rendered[key] != state:
                self.tree.item(key, values=cells, tags=tags)
            self._rendered[key] = state
        visible = tuple(visible)
        if visible != self._visible_keys:
            # One call orders the visible rows and detaches filtered rows;
            # clearing a filter can reattach them without rebuilding them.
            self.tree.set_children('', *visible)
            self._visible_keys = visible
        visible_keys = set(visible)
        still = tuple(key for key in keep if key in visible_keys)
        if still != self.tree.selection():
            self.tree.selection_set(still)
        if self.tree.focus() not in visible_keys:
            self.tree.focus('')  # Space must never toggle an outage hidden by a filter.
        self.count.configure(text='{} of {} shown'.format(len(rows), len(self.rows)) if filters else '{} shown'.format(len(rows)))
        if rows:
            self.empty.place_forget()
        else:
            if filters:
                text = 'No matching entries'
            else:
                text = getattr(self, 'empty_text', 'No entries')
            self.empty.configure(text=text)
            self.empty.place(relx=0.5, rely=0.5, anchor='center', relwidth=0.95)
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

    Exactly two tabs. "Case Manager": left to right every available planned
    outage, the planned outages of the selected case and the planning cases;
    below them the calculation choice (n-0, n-1, (n-1)'), the problems and a
    collapsible calculation preview. "Settings": limits, classification,
    contingency analysis (read only), the QDS time base (read only) and the
    fixed background outages and rules. A status line and the action bar stay
    visible on both tabs. Every table filters per column. The window only
    configures the calculation; there is no results tab, results are the
    PowerFactory result objects and the report.
    """

    # Presentation tokens only; no calculation or configuration defaults live here.
    BACKGROUND, CARD, TEXT, MUTED = '#F3F7FA', '#FFFFFF', '#203449', '#64788B'
    ACCENT, ACCENT_ACTIVE, SELECTED, PROBLEM = '#087F9C', '#06677F', '#E5F3FA', '#DC3545'
    HEADER, FILTER, BORDER = '#EDF3F7', '#F7FAFC', '#DCE5EC'
    MASTHEAD, MASTHEAD_MUTED, INSET = '#16384F', '#C5DCE8', '#EFF7FA'
    FIXED, OVERLAP, GAP = '#64788B', '#DCEEF4', '#EDF1F5'
    WARNING, SUCCESS = '#D97706', '#16835D'
    TAB_CASES, TAB_SETTINGS = 'Case Manager', 'Settings'
    SETTINGS_PAGES = (('Network scope', ('Network scope',)), ('Limits', ('Thermal limits', 'Voltage limits')),
                      ('Classification', ('Classification',)), ('Report and run', ('Report', 'Run')),
                      ('Contingency analysis', ('Contingency analysis',)))
    PAGE_TIME, PAGE_FIXED = 'QDS time base', 'Fixed background & rules'
    ZOOM_LEVELS = (75, 90, 100, 110, 125, 150, 175, 200)

    def __init__(self, root, editor, config_path, user, tk_modules):
        self.root = root
        self.editor = editor
        self.config_path = config_path
        self.user = user
        self.tk, self.ttk, self.messagebox, self.simpledialog = tk_modules
        self.selected = None
        self.outcome = None
        self._preview_labels = []
        self.inline_edit = None
        self.tooltips = []
        self.bold_font = 'TkDefaultFont'
        # Settings tab: entry variable, entry, source label and message label per setting.
        self.setting_vars, self.setting_inputs, self.setting_sources, self.setting_messages = {}, {}, {}, {}
        self.preview_visible = False
        self.ui_zoom = 1.0
        self._flow_layouts = []

    def tip(self, widget, text):
        """Explain `widget` on hover; returns the Tooltip."""
        tooltip = Tooltip(self.tk, widget, text)
        self.tooltips.append(tooltip)
        return tooltip

    def tip_text(self, widget):
        return '\n'.join(tooltip.text for tooltip in self.tooltips if tooltip.widget is widget)

    # --- window -----------------------------------------------------------------
    def build(self):
        with RUN_STATS.measure("case manager: build window"):
            self._build()

    def _build(self):
        ttk, root = self.ttk, self.root
        self._style()
        root.title('GridLens {} - Case Manager'.format(PUBLISHER_VERSION))
        root.geometry(window_geometry(root.winfo_screenwidth(), root.winfo_screenheight(), share=0.94, largest=(1720, 1020)))
        root.minsize(*minimum_window_size(root.winfo_screenwidth(), root.winfo_screenheight()))
        root.configure(background=self.BACKGROUND)
        root.columnconfigure(0, weight=1)
        root.rowconfigure(1, weight=1)
        masthead = ttk.Frame(root, style='Masthead.TFrame', padding=(24, 16))
        masthead.grid(row=0, column=0, sticky='ew')
        masthead.columnconfigure(1, weight=1)
        ttk.Label(masthead, text='GridLens', style='Brand.TLabel').grid(row=0, column=0, sticky='w', padx=(0, 32))
        ttk.Label(masthead, text= PUBLISHER_VERSION, style='MastheadHint.TLabel').grid(row=1, column=0, sticky='w')
        self.page_title = ttk.Label(masthead, text='Planning case manager', style='MastheadTitle.TLabel', wraplength=300)
        self.page_title.grid(row=0, column=1, sticky='w')
        self.page_hint = ttk.Label(masthead, text='Build independent cases. Check the settings. Start the calculation.',
                                   style='MastheadHint.TLabel', wraplength=440)
        self.page_hint.grid(row=1, column=1, sticky='w', pady=(4, 0))
        def fit_header(event):
            width = max(120, event.width - 250*self.ui_zoom)
            self.page_title.configure(wraplength=width)
            self.page_hint.configure(wraplength=width)
        masthead.bind('<Configure>', fit_header, add='+')
        self._bind_zoom_keys()
        self.notebook = ttk.Notebook(root)
        self.notebook.enable_traversal()
        self.notebook.grid(row=1, column=0, sticky='nsew', padx=20, pady=(14, 0))
        self.cases_tab = ttk.Frame(self.notebook, padding=(0, 8, 0, 0))
        self.settings_tab = ttk.Frame(self.notebook, padding=(0, 8, 0, 0))
        self.notebook.add(self.cases_tab, text=self.TAB_CASES)
        self.notebook.add(self.settings_tab, text=self.TAB_SETTINGS)
        self.notebook.bind('<<NotebookTabChanged>>', self._on_page_change)
        self._build_case_manager(self.cases_tab)
        self._build_settings(self.settings_tab)
        bottom = ttk.Frame(root, padding=(20, 8, 20, 16))
        bottom.grid(row=2, column=0, sticky='ew')
        bottom.columnconfigure(0, weight=1)
        ttk.Separator(bottom).grid(row=0, column=0, sticky='ew', pady=(0, 8))
        self.status_line = self._wrapped_label(bottom, '', style='Status.TLabel', row=1, column=0, pady=(0, 10))
        self.status_line.configure(cursor='hand2')
        self.status_line.bind('<Button-1>', lambda _event: self.notebook.select(self.cases_tab))
        self.tip(self.status_line, HELP_TEXTS['status_line'])
        left_actions, right_actions = ttk.Frame(bottom), ttk.Frame(bottom)
        left_actions.grid(row=2, column=0, sticky='w')
        right_actions.grid(row=2, column=0, sticky='e')
        for parent, actions in ((left_actions, (('Save configuration', self.save, 'save', 'TButton'),
                                               ('Load saved configuration', self.load_saved, 'load', 'TButton'))),
                                (right_actions, (('Cancel', self.cancel, 'cancel', 'TButton'),
                                                 ('Start calculation', self.start, 'start', 'Accent.TButton')))):
            for column, (text, command, key, style) in enumerate(actions):
                button = ttk.Button(parent, text=text, style=style, command=command)
                button.grid(row=0, column=column, padx=(0, 8) if column == 0 else 0)
                self.tip(button, HELP_TEXTS[key])
        def fit_actions(event):
            stacked = left_actions.winfo_reqwidth() + right_actions.winfo_reqwidth() + 32 > event.width
            right_actions.grid(row=3 if stacked else 2, column=0, sticky='e', pady=(8, 0) if stacked else 0)
        bottom.bind('<Configure>', fit_actions, add='+')
        root.protocol('WM_DELETE_WINDOW', self.cancel)
        root.bind('<Escape>', self.on_escape)
        self._bind_window_keys()
        ids = self.editor.case_ids()
        self.refresh_all(ids[0] if ids else None)
        self.root.update_idletasks()
        self.place_dividers()

    def _on_page_change(self, _event=None):
        settings = self.notebook.select() == str(self.settings_tab)
        self.page_title.configure(text='Settings' if settings else 'Planning case manager')
        self.page_hint.configure(text='Configure network scope, evaluation limits and calculation settings.' if settings else
                                 'Build independent cases. Check the settings. Start the calculation.')

    def _bind_zoom_keys(self):
        modifiers = ['Control']
        if self.root.tk.call('tk', 'windowingsystem') == 'aqua':
            modifiers.append('Command')
        for modifier in modifiers:
            for key in ('plus', 'equal', 'KP_Add'):
                self.root.bind('<{}-{}>'.format(modifier, key), lambda _event: self.step_zoom(1), add='+')
            for key in ('minus', 'KP_Subtract'):
                self.root.bind('<{}-{}>'.format(modifier, key), lambda _event: self.step_zoom(-1), add='+')
            self.root.bind('<{}-0>'.format(modifier), lambda _event: self.set_zoom(100), add='+')

    def step_zoom(self, direction):
        current = round(self.ui_zoom * 100)
        choices = [value for value in self.ZOOM_LEVELS if (value > current if direction > 0 else value < current)]
        return self.set_zoom((min(choices) if direction > 0 else max(choices)) if choices else current)

    def set_zoom(self, percent):
        """Session-only display scaling, independent of OS DPI and saved settings."""
        percent = max(75, min(200, int(str(percent).rstrip('%'))))
        self.ui_zoom = percent / 100.0
        for font, points in self.ui_fonts.values():
            font.configure(size=round(points * self.ui_zoom))
        self.device_scale = max(1.0, float(self.root.tk.call('tk', 'scaling')) / (96.0 / 72.0))
        self.ui_scale = self.device_scale * self.ui_zoom
        style = self.ttk.Style(self.root)
        style.configure('Treeview', rowheight=round(32 * self.ui_scale))
        style.configure('TButton', padding=(round(12*self.ui_zoom), round(8*self.ui_zoom)))
        style.configure('Accent.TButton', padding=(round(20*self.ui_zoom), round(9*self.ui_zoom)))
        for name in ('case_table', 'member_table', 'available_table', 'problem_table', 'fixed_table', 'rule_table'):
            table = getattr(self, name)
            table.HEADER_HEIGHT = round(34*self.ui_scale)
            table.FILTER_HEIGHT = round(38*self.ui_scale)
            table.header.configure(height=table.HEADER_HEIGHT)
            table.filter_bar.configure(height=table.FILTER_HEIGHT)
            table.layout()
        self._size_settings_tabs()
        for layout in self._flow_layouts:
            layout()
        self.draw_timeline()
        return 'break'

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
        """One ttk theme, with point-sized fonts and DPI-scaled widget metrics."""
        style = self.ttk.Style(self.root)
        if 'clam' in style.theme_names():
            style.theme_use('clam')
        families = set(self.tk.font.families(self.root))
        default = self.tk.font.nametofont('TkDefaultFont').actual()['family']
        family = next((name for name in ('Segoe UI', 'SF Pro Text', 'Helvetica Neue', 'DejaVu Sans') if name in families), default)
        sizes = {'body': (11, 'normal'), 'bold': (11, 'bold'), 'small': (10, 'normal'),
                 'brand': (23, 'bold'), 'page': (15, 'bold'), 'title': (12, 'bold'), 'user': (10, 'bold')}
        self.ui_fonts = {name: (self.tk.font.Font(root=self.root, family=family, size=points, weight=weight), points)
                         for name, (points, weight) in sizes.items()}
        self.body_font, self.bold_font, self.small_font = [self.ui_fonts[name][0] for name in ('body', 'bold', 'small')]
        # Tk scaling is pixels per point. Keep the OS scaling; don't reset it.
        self.device_scale = max(1.0, float(self.root.tk.call('tk', 'scaling')) / (96.0 / 72.0))
        self.ui_scale = self.device_scale
        self.tk.font.nametofont('TkDefaultFont').configure(family=family, size=11)
        self.tk.font.nametofont('TkTextFont').configure(family=family, size=11)
        style.configure('.', background=self.BACKGROUND, foreground=self.TEXT, font=self.body_font)
        for name, color in (('TFrame', self.BACKGROUND), ('Card.TFrame', self.CARD),
                            ('Inset.TFrame', self.INSET), ('Masthead.TFrame', self.MASTHEAD)):
            style.configure(name, background=color)
        style.configure('Panel.TFrame', background=self.CARD, borderwidth=1, relief='solid', bordercolor=self.BORDER)
        for name, background, foreground, font in (
                ('TLabel', self.CARD, self.TEXT, self.body_font),
                ('Brand.TLabel', self.MASTHEAD, self.CARD, self.ui_fonts['brand'][0]),
                ('MastheadTitle.TLabel', self.MASTHEAD, self.CARD, self.ui_fonts['page'][0]),
                ('MastheadHint.TLabel', self.MASTHEAD, self.MASTHEAD_MUTED, self.small_font),
                ('Inset.TLabel', self.INSET, self.TEXT, self.body_font),
                ('InsetTitle.TLabel', self.INSET, self.ACCENT, self.bold_font),
                ('Optional.TLabel', self.INSET, self.MUTED, self.small_font),
                ('Muted.TLabel', self.CARD, self.MUTED, self.small_font),
                ('Link.TLabel', self.CARD, self.ACCENT, self.body_font),
                ('Status.TLabel', self.BACKGROUND, self.MUTED, self.small_font),
                ('Title.TLabel', self.CARD, self.TEXT, self.ui_fonts['title'][0]),
                ('Section.TLabel', self.CARD, self.TEXT, self.bold_font),
                ('Problem.TLabel', self.CARD, self.PROBLEM, self.small_font),
                ('Source.TLabel', self.CARD, self.MUTED, self.small_font),
                ('User.TLabel', self.CARD, self.ACCENT, self.ui_fonts['user'][0]),
                ('Success.TLabel', self.CARD, self.SUCCESS, self.small_font)):
            style.configure(name, background=background, foreground=foreground, font=font)
        style.configure('Optional.TLabel', padding=(8, 3))
        style.configure('TLabelframe', background=self.CARD, bordercolor=self.BORDER, relief='solid', borderwidth=1)
        style.configure('TLabelframe.Label', background=self.CARD, foreground=self.TEXT, font=self.bold_font)
        for name in ('TCheckbutton', 'TRadiobutton'):
            style.configure(name, background=self.CARD, foreground=self.TEXT, padding=(0, 4), focuscolor=self.ACCENT)
            style.map(name, background=[('active', self.INSET)], foreground=[('disabled', self.MUTED)],
                      indicatorbackground=[('disabled', self.HEADER), ('selected', self.ACCENT)],
                      indicatorforeground=[('selected', self.CARD)])
        style.configure('TButton', padding=(12, 8), background=self.CARD, foreground=self.TEXT,
                        borderwidth=1, bordercolor=self.BORDER, lightcolor=self.CARD, darkcolor=self.CARD,
                        focuscolor=self.ACCENT, focusthickness=1)
        style.map('TButton', background=[('disabled', self.FILTER), ('pressed', self.SELECTED), ('active', self.INSET)],
                  foreground=[('disabled', self.MUTED)], bordercolor=[('focus', self.ACCENT), ('active', self.ACCENT)])
        style.configure('Accent.TButton', background=self.ACCENT, foreground=self.CARD, bordercolor=self.ACCENT,
                        lightcolor=self.ACCENT, darkcolor=self.ACCENT, padding=(20, 9), font=self.bold_font)
        style.map('Accent.TButton', background=[('disabled', self.BORDER), ('pressed', self.ACCENT_ACTIVE), ('active', self.ACCENT_ACTIVE)],
                  foreground=[('disabled', self.MUTED), ('!disabled', self.CARD)],
                  bordercolor=[('focus', self.MASTHEAD), ('!disabled', self.ACCENT)])
        style.configure('Link.TButton', padding=(4, 0), foreground=self.ACCENT, borderwidth=0)
        style.configure('TNotebook', background=self.BACKGROUND, borderwidth=0, tabmargins=(0, 0, 0, 0))
        style.configure('TNotebook.Tab', padding=(22, 10), font=self.bold_font, background=self.BACKGROUND,
                        foreground=self.MUTED, bordercolor=self.BORDER)
        style.map('TNotebook.Tab', background=[('selected', self.CARD), ('active', self.INSET)],
                  foreground=[('selected', self.ACCENT)])
        style.configure('Settings.TNotebook.Tab', padding=(12, 10), font=self.small_font)
        style.configure('Settings.TNotebook', tabposition='wn')
        for name in ('TEntry', 'TCombobox'):
            style.configure(name, fieldbackground=self.CARD, background=self.FILTER, foreground=self.TEXT,
                            padding=(8, 6), bordercolor=self.BORDER, lightcolor=self.BORDER, darkcolor=self.BORDER,
                            arrowcolor=self.MUTED, selectbackground=self.SELECTED, selectforeground=self.TEXT)
            style.map(name, bordercolor=[('focus', self.ACCENT)],
                      fieldbackground=[('disabled', self.HEADER), ('readonly', self.CARD)],
                      foreground=[('disabled', self.MUTED)], background=[('active', self.SELECTED)])
        style.configure('Filter.TEntry', padding=(5, 4), font=self.small_font)
        style.configure('Filter.TCombobox', padding=(5, 4), font=self.small_font)
        style.configure('Invalid.TEntry', fieldbackground='#FFF0F1', foreground=self.PROBLEM, bordercolor=self.PROBLEM)
        style.configure('Treeview', rowheight=round(32 * self.ui_scale), font=self.body_font,
                        background=self.CARD, fieldbackground=self.CARD, borderwidth=0,
                        lightcolor=self.CARD, darkcolor=self.CARD)
        style.map('Treeview', background=[('selected', self.SELECTED)], foreground=[('selected', self.TEXT)])
        for orient in ('Vertical', 'Horizontal'):
            name = orient + '.TScrollbar'
            style.configure(name, arrowsize=12, background=self.BORDER, troughcolor=self.FILTER,
                            borderwidth=0, gripcount=0, lightcolor=self.BORDER, darkcolor=self.BORDER)
            style.map(name, background=[('pressed', self.ACCENT), ('active', self.MUTED)])
        style.configure('TPanedwindow', background=self.BACKGROUND)
        style.configure('Sash', sashthickness=10)
        style.configure('TSeparator', background=self.BORDER)
        self.root.option_add('*TCombobox*Listbox.font', self.body_font)
        self.root.option_add('*TCombobox*Listbox.background', self.CARD)
        self.root.option_add('*TCombobox*Listbox.foreground', self.TEXT)
        self.root.option_add('*TCombobox*Listbox.selectBackground', self.SELECTED)
        self.root.option_add('*TCombobox*Listbox.selectForeground', self.TEXT)


    def _card(self, parent, **grid):
        frame = self.ttk.Frame(parent, style='Panel.TFrame', padding=16)
        frame.grid(**grid)
        return frame

    def _wrapped_label(self, parent, text, style='Muted.TLabel', **grid):
        """Wrap help to its panel width, only when that width changes."""
        label = self.ttk.Label(parent, text=text, style=style, wraplength=320)
        label.grid(sticky='ew', **grid)
        previous = [None]

        def resize(event):
            width = max(100, event.width - 32)
            if width != previous[0]:
                previous[0] = width
                label.configure(wraplength=width)
        parent.bind('<Configure>', resize, add='+')
        return label

    def _flow(self, parent, widgets, gap=6):
        """Wrap a small action/legend row without changing its widgets or callbacks."""
        def layout(_event=None):
            available = max(1, parent.winfo_width())
            row, column, used = 0, 0, 0
            for widget in widgets:
                width = widget.winfo_reqwidth() + gap
                if column and used + width > available:
                    row, column, used = row + 1, 0, 0
                widget.grid(row=row, column=column, sticky='w', padx=(0, gap), pady=(0, 4))
                column, used = column + 1, used + width
            ancestor = parent
            while ancestor is not None and not hasattr(ancestor, '_fit_viewport'):
                ancestor = getattr(ancestor, 'master', None)
            if ancestor is not None:
                self.root.after_idle(ancestor._fit_viewport)
        parent.bind('<Configure>', layout, add='+')
        self._flow_layouts.append(layout)

    # --- tab "Case Manager" ------------------------------------------------------
    def _build_case_manager(self, tab):
        """A scrolling workspace; the root's status and action bar never scroll."""
        content = self._scrolled(tab)
        self.case_content = content
        content.columnconfigure(0, weight=1)
        content.rowconfigure(0, weight=3)
        workspace = self.ttk.Frame(content)
        workspace.grid(row=0, column=0, sticky='nsew')
        self._build_workspace(workspace)
        self._build_timeline(content)
        strip = self.ttk.Frame(content)
        strip.grid(row=2, column=0, sticky='nsew', pady=(12, 0))
        self._build_calculation(strip)


    def _build_workspace(self, tab):
        ttk = self.ttk
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(0, weight=1)
        self.panes = ttk.Panedwindow(tab, orient='horizontal')
        self.panes.grid(row=0, column=0, sticky='nsew')
        # Left to right the way an outage travels: available, into the case, the cases.
        left, centre, right = (ttk.Frame(self.panes, style='Panel.TFrame', padding=14) for _ in range(3))
        self.panes.add(left, weight=40)
        self.panes.add(centre, weight=38)
        self.panes.add(right, weight=22)
        self._build_available(left)
        self._build_case_outages(centre)
        self._build_cases(right)

    def _build_cases(self, pane):
        ttk = self.ttk
        pane.columnconfigure(0, weight=1)
        pane.rowconfigure(1, weight=1, minsize=140)
        title = ttk.Frame(pane, style='Card.TFrame')
        title.grid(row=0, column=0, sticky='ew', pady=(0, 6))
        title.columnconfigure(0, weight=1)
        ttk.Label(title, text='Planning cases', style='Title.TLabel').grid(row=0, column=0, sticky='w')
        self.case_limit_label = ttk.Label(title, text='', style='Muted.TLabel')
        self.case_limit_label.grid(row=0, column=1, sticky='e')
        self.tip(self.case_limit_label, HELP_TEXTS['case_limit'])
        self.case_table = FilterTable(self, pane, (
            ('enabled', 'Run', 42, False, (('included', '\u2611'), ('excluded', '\u2610'))),
            ('name', 'Planning case', 150, True, None), ('count', 'Outages', 56, False, None),
            ('status', 'Status', 100, False, ('ready', 'not calculated', 'excluded'))), height=4, selectmode='browse',
            tips={'enabled': HELP_TEXTS['enabled'], 'name': COLUMN_HELP['case_name'], 'count': COLUMN_HELP['case_count'], 'status': COLUMN_HELP['case_status']})
        self.case_table.grid(row=1, column=0, sticky='nsew')
        self.case_table.empty_text = 'Create your first planning case with "New"'
        self.case_tree = self.case_table.tree
        self.case_tree.bind('<<TreeviewSelect>>', self.on_case_select)
        self.case_tree.bind('<Button-1>', self.on_case_flag_click)
        self.case_tree.bind('<space>', lambda _event: self.toggle_case_enabled(self.case_tree.focus()) or 'break')
        self.case_tree.bind('<Double-1>', self.on_case_double_click)
        self.case_tree.bind('<F2>', lambda _event: self.rename_in_place())
        self.case_tree.bind('<Return>', lambda _event: self.rename_in_place())
        self._bind_delete(self.case_tree, self.delete_case)
        buttons = ttk.Frame(pane, style='Card.TFrame')
        buttons.grid(row=2, column=0, sticky='ew', pady=(6, 0))
        self.case_buttons = {}
        for column, (label, command) in enumerate((('New', self.new_case), ('Copy', self.copy_case),
                                                   ('Delete', self.delete_case))):
            buttons.columnconfigure(column, weight=1)
            self.case_buttons[label] = ttk.Button(buttons, text=label, command=command, width=6)
            self.case_buttons[label].grid(row=0, column=column, sticky='ew', padx=(0, 4) if column < 2 else 0)
            self.tip(self.case_buttons[label], HELP_TEXTS[label])
        self._flow(buttons, list(self.case_buttons.values()))
        per_outage = ttk.Button(pane, text='One case per planned outage', command=self.one_case_per_outage)
        per_outage.grid(row=3, column=0, sticky='ew', pady=(4, 8))
        self.tip(per_outage, HELP_TEXTS['one_per_outage'])
        self._wrapped_label(pane, 'Run: ☑ included · ☐ excluded. Click the flag or press Space. '
                            'Excluded cases stay saved but are omitted from calculation and report.',
                            row=4, column=0, pady=(2, 0))

    def _build_case_outages(self, pane):
        ttk = self.ttk
        pane.columnconfigure(0, weight=1)
        pane.rowconfigure(2, weight=1)
        heading = ttk.Frame(pane, style='Card.TFrame')
        heading.grid(row=0, column=0, sticky='ew')
        heading.columnconfigure(0, weight=1)
        self.case_title = ttk.Label(heading, text='', style='Title.TLabel', wraplength=280)
        self.case_title.grid(row=0, column=0, sticky='ew')
        heading.bind('<Configure>', lambda event: self.case_title.configure(wraplength=max(120, event.width)), add='+')
        self.case_heading = heading
        self.case_description = self._wrapped_label(heading, '', row=1, column=0, pady=(4, 0))
        self.case_description.configure(cursor='xterm')
        self.case_description.bind('<Double-1>', lambda _event: self.describe_in_place())
        self.tip(self.case_description, HELP_TEXTS['description'])
        self.counts_label = self._wrapped_label(pane, '', row=1, column=0, pady=(4, 12))
        self.member_table = FilterTable(self, pane, (
            ('fs', 'Planned outage', 170, True, None), ('equipment', 'Equipment', 160, True, None),
            ('start', 'Start', 128, False, None), ('end', 'End', 128, False, None), ('prio', 'Priority', 70, False, None)), height=4,
            tips={'prio': COLUMN_HELP['prio']})
        self.member_table.empty_text = 'No planned outages assigned to this case'
        self.member_table.grid(row=2, column=0, sticky='nsew')
        self.member_tree = self.member_table.tree
        self.member_tree.bind('<Double-1>', lambda _event: self.show_details(self.member_tree))
        self._bind_delete(self.member_tree, self.remove_selected)
        buttons = ttk.Frame(pane, style='Card.TFrame')
        buttons.grid(row=3, column=0, sticky='ew', pady=(10, 0))
        for column, (text, command, key) in enumerate((
                ('Remove from case', self.remove_selected, 'remove'),
                ('Details', lambda: self.show_details(self.member_tree), 'details'))):
            button = ttk.Button(buttons, text=text, command=command)
            button.grid(row=0, column=column, padx=(0, 6))
            self.tip(button, HELP_TEXTS[key])
        self._flow(buttons, buttons.winfo_children())
        self._wrapped_label(pane, 'Removes only the assignment.', row=4, column=0, pady=(8, 0))

    def _build_timeline(self, parent):
        timeline = self._card(parent, row=1, column=0, sticky='nsew', pady=(12, 0))
        timeline.columnconfigure(0, weight=1)
        timeline.rowconfigure(2, weight=1)
        title = self.ttk.Label(timeline, text='Timeline of the case', style='Title.TLabel')
        title.grid(row=0, column=0, sticky='w')
        self.tip(title, HELP_TEXTS['timeline'])
        legend = self.ttk.Frame(timeline, style='Card.TFrame')
        legend.grid(row=1, column=0, columnspan=2, sticky='ew', pady=(8, 6))
        for column, (color, text) in enumerate(((self.ACCENT, 'Case outage'), (self.FIXED, 'Shared outage'),
                                               (self.OVERLAP, 'Overlapping windows'), (self.GAP, 'Shortened gap'))):
            item = self.ttk.Frame(legend, style='Card.TFrame')
            self.tk.Label(item, text='  ', background=color).grid(row=0, column=0, padx=(0, 6))
            self.ttk.Label(item, text=text, style='Muted.TLabel').grid(row=0, column=1, padx=(0, 12))
        self._flow(legend, legend.winfo_children())
        self.canvas = self.tk.Canvas(timeline, height=78, background=self.CARD, highlightthickness=0)
        scroll = self.ttk.Scrollbar(timeline, orient='vertical', command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=lambda first, last: self._scrollbar(scroll, first, last))
        self.canvas.grid(row=2, column=0, sticky='nsew')
        scroll.grid(row=2, column=1, sticky='ns')
        self.canvas.bind('<Configure>', lambda _event: self.draw_timeline())
        self._timeline_axis = self.ttk.Frame(timeline, style='Card.TFrame')
        self._timeline_axis.grid(row=3, column=0, sticky='ew', pady=(4, 0))
        self._timeline_axis.columnconfigure(1, weight=1)
        self.timeline_start = self.ttk.Label(self._timeline_axis, style='Muted.TLabel')
        self.timeline_start.grid(row=0, column=0, sticky='w')
        self.timeline_end = self.ttk.Label(self._timeline_axis, style='Muted.TLabel')
        self.timeline_end.grid(row=0, column=2, sticky='e')
        self.tip(self._timeline_axis, 'Planning windows only. Light bands compress long gaps; bar lengths across those gaps are not to scale.')


    def _build_available(self, pane):
        ttk = self.ttk
        pane.columnconfigure(0, weight=1)
        pane.rowconfigure(1, weight=1)
        title = ttk.Label(pane, text='Available planned outages', style='Title.TLabel')
        title.grid(row=0, column=0, sticky='w', pady=(0, 6))
        self.tip(title, HELP_TEXTS['planned_outages'])
        self.available_table = FilterTable(self, pane, (
            ('mark', 'In case', 78, False, (('in case', MARK_IN_CASE), ('free', MARK_FREE), ('fixed', MARK_FIXED))),
            ('fs', 'Planned outage', 140, True, None), ('equipment', 'Equipment', 110, True, None),
            ('start', 'Start', 106, False, None), ('end', 'End', 106, False, None),
            ('status', 'Status', 132, False, ('in simulated period', 'outside simulated period', 'Ignored in PowerFactory'))),
            height=4, tag_column=0, tips={'mark': COLUMN_HELP['mark'], 'status': COLUMN_HELP['outage_status']})
        self.available_table.empty_text = 'No planned outages available'
        self.available_table.grid(row=1, column=0, sticky='nsew')
        self.available_tree = self.available_table.tree
        self.available_tree.tag_configure(MARK_IN_CASE, background=self.INSET)
        self.available_tree.tag_configure(MARK_FIXED, background=self.HEADER)
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
        self._flow(buttons, buttons.winfo_children())
        self._wrapped_label(pane, 'Tick to add an outage to the selected case; untick to remove it. '
                            '"Add to case" or Enter adds all selected rows.', row=3, column=0, pady=(6, 0))

    # --- tab "Fixed background & rules" -------------------------------------------
    def _build_fixed_and_rules(self, tab):
        ttk = self.ttk
        tab = self._scrolled(tab, horizontal='zoom')
        tab.columnconfigure(0, weight=1, uniform='overview')
        tab.columnconfigure(1, weight=1, uniform='overview')
        tab.rowconfigure(1, weight=1)
        self._wrapped_label(tab, 'Optional settings: leave both sections empty to compare only the outages you assign to each case.',
                            style='Status.TLabel', row=0, column=0, columnspan=2, pady=(0, 8))
        fixed = self._card(tab, row=1, column=0, sticky='nsew', padx=(0, 5))
        fixed.columnconfigure(0, weight=1)
        fixed.rowconfigure(3, weight=1)
        title = ttk.Frame(fixed, style='Card.TFrame')
        title.grid(row=0, column=0, sticky='ew')
        title.columnconfigure(0, weight=1)
        ttk.Label(title, text='Fixed background outages', style='Title.TLabel').grid(row=0, column=0, sticky='w')
        ttk.Label(title, text='Optional', style='Optional.TLabel').grid(row=0, column=1, sticky='e')
        self._wrapped_label(fixed, 'Use this for outages that are already planned and should be shared by the reference '
                            'and every case. Each outage still follows its own time window.',
                            row=1, column=0, pady=(6, 10))
        example = ttk.Frame(fixed, style='Inset.TFrame', padding=10)
        example.grid(row=2, column=0, sticky='ew', pady=(0, 10))
        example.columnconfigure(0, weight=1)
        self._wrapped_label(example, 'Example: transformer T1 is already under maintenance',
                            style='InsetTitle.TLabel', row=0, column=0, pady=(0, 5))
        self._wrapped_label(example, 'Reference: T1\nCase A: T1 + line North\nCase B: T1 + line South',
                            style='Inset.TLabel', row=1, column=0)
        self.fixed_table = FilterTable(self, fixed, (
            ('fs', 'Planned outage', 170, True, None), ('equipment', 'Equipment', 150, True, None), ('start', 'Start', 118, False, None),
            ('end', 'End', 118, False, None), ('status', 'Status', 150, False,
                                               ('in simulated period', 'outside simulated period', 'Ignored in PowerFactory'))), height=6,
            tips={'status': COLUMN_HELP['outage_status']})
        self.fixed_table.grid(row=3, column=0, sticky='nsew')
        self.fixed_tree = self.fixed_table.tree
        self.fixed_tree.bind('<Double-1>', lambda _event: self.show_details(self.fixed_tree))
        self._bind_delete(self.fixed_tree, self.unfix_selected)
        self._wrapped_label(fixed, 'Add a shared outage on the Case Manager tab with "Set as fixed background".',
                            row=4, column=0, pady=(8, 4))
        unfix = ttk.Button(fixed, text='Remove from fixed background', command=self.unfix_selected)
        unfix.grid(row=5, column=0, sticky='w')
        self.tip(unfix, HELP_TEXTS['unfix'])

        rules = self._card(tab, row=1, column=1, sticky='nsew', padx=(5, 0))
        rules.columnconfigure(0, weight=1)
        rules.rowconfigure(3, weight=1)
        title = ttk.Frame(rules, style='Card.TFrame')
        title.grid(row=0, column=0, sticky='ew')
        title.columnconfigure(0, weight=1)
        ttk.Label(title, text='Rules between planned outages', style='Title.TLabel').grid(row=0, column=0, sticky='w')
        ttk.Label(title, text='Optional', style='Optional.TLabel').grid(row=0, column=1, sticky='e')
        self._wrapped_label(rules, 'Use this to check which outage combinations are allowed. A case that breaks a rule '
                            'is reported but not calculated. Rules never create cases or change outage dates.',
                            row=1, column=0, pady=(6, 10))
        guide = ttk.Frame(rules, style='Inset.TFrame', padding=10)
        guide.grid(row=2, column=0, sticky='ew', pady=(0, 10))
        guide.columnconfigure(0, weight=1)
        self._wrapped_label(guide, 'What the checks mean', style='InsetTitle.TLabel', row=0, column=0, pady=(0, 5))
        self._wrapped_label(guide, 'must not overlap: their time windows must not overlap.\n'
                            'second only after the first: the second starts after the first ends.\n'
                            'only together: both belong to the case and their windows overlap.',
                            style='Inset.TLabel', row=1, column=0)
        self.rule_table = FilterTable(self, rules, (
            ('first', 'First outage', 170, True, None), ('rule', 'Rule', 190, False, tuple(label for _, label in RULE_LABELS)),
            ('second', 'Second outage', 170, True, None)), height=5, tips={'rule': HELP_TEXTS['rule_kind']})
        self.rule_table.grid(row=3, column=0, sticky='nsew')
        self.rule_tree = self.rule_table.tree
        self._bind_delete(self.rule_tree, self.remove_rule)
        editor_row = ttk.Frame(rules, style='Card.TFrame')
        editor_row.grid(row=4, column=0, sticky='ew', pady=(8, 0))
        for column, text in enumerate(('First outage', 'Rule', 'Second outage')):
            editor_row.columnconfigure(column, weight=1, uniform='rule_fields')
            ttk.Label(editor_row, text=text, style='Muted.TLabel').grid(row=0, column=column, sticky='w', pady=(0, 3))
        names = [label for label, _ in self.editor.outage_choices()]
        self.rule_first = ttk.Combobox(editor_row, values=names, state='readonly', width=8)
        self.rule_kind = ttk.Combobox(editor_row, values=[label for _, label in RULE_LABELS], state='readonly', width=8)
        self.rule_second = ttk.Combobox(editor_row, values=names, state='readonly', width=8)
        for column, widget in enumerate((self.rule_first, self.rule_kind, self.rule_second)):
            widget.grid(row=1, column=column, sticky='ew', padx=(0, 4) if column < 2 else 0)
        self.tip(self.rule_first, 'The first planned outage to check. Choose a rule and the second outage, then Add rule.')
        self.tip(self.rule_kind, HELP_TEXTS['rule_kind'])
        self.tip(self.rule_second, 'The second planned outage to check. For an order rule, this outage must start after the first ends.')
        actions = ttk.Frame(rules, style='Card.TFrame')
        actions.grid(row=5, column=0, sticky='w', pady=(6, 0))
        ttk.Button(actions, text='Add rule', command=self.add_rule).grid(row=0, column=0, padx=(0, 6))
        ttk.Button(actions, text='Remove rule', command=self.remove_rule).grid(row=0, column=1)

    def _build_calculation(self, strip):
        """Calculation choice, problems and the collapsible preview, below the three panes."""
        tk, ttk = self.tk, self.ttk
        strip.columnconfigure(0, weight=1, uniform='calculation')
        strip.columnconfigure(1, weight=1, uniform='calculation')
        options = self._card(strip, row=0, column=0, sticky='nsew', padx=(0, 4))
        options.columnconfigure(0, weight=1)
        ttk.Label(options, text='Calculation', style='Title.TLabel').grid(row=0, column=0, sticky='w', pady=(0, 4))
        # n-0 (the QDS of REF and every case) is always calculated, so it has no control here.
        self.n1_var = tk.BooleanVar(value=N1_REFERENCE in self.editor.config['assessments'])
        self.n1_prime_var = tk.BooleanVar(value=N1_PRIME in self.editor.config['assessments'])
        check_style = dict(background=self.CARD, foreground=self.TEXT, activebackground=self.INSET,
                           activeforeground=self.TEXT, selectcolor=self.CARD, font=self.body_font,
                           borderwidth=0, highlightthickness=1, highlightbackground=self.CARD,
                           highlightcolor=self.ACCENT, anchor='w', justify='left', padx=0, pady=4)
        n1 = tk.Checkbutton(options, text='n-1 - reference contingency analysis', variable=self.n1_var,
                            command=self.apply_assessments, **check_style)
        n1.grid(row=2, column=0, sticky='w')
        self.tip(n1, HELP_TEXTS['n1'])
        prime = tk.Checkbutton(options, text="(n-1)' - contingency analysis with planned-outage scenarios",
                               variable=self.n1_prime_var, command=self.apply_assessments, **check_style)
        prime.grid(row=3, column=0, sticky='w')
        options.bind('<Configure>', lambda event: [widget.configure(wraplength=max(180, event.width - 58))
                                                   for widget in (n1, prime)], add='+')
        self.tip(prime, HELP_TEXTS['n1_prime'])
        note = self._wrapped_label(options, "n-1 and (n-1)': results in the log and on the QA page until part 4",
                                   row=4, column=0, padx=(22, 0))
        self.tip(note, N1_NOTE)
        results = ttk.Frame(options, style='Card.TFrame')
        results.grid(row=6, column=0, sticky='ew', pady=(6, 0))
        results.columnconfigure(1, weight=1)
        ttk.Label(results, text='Results:').grid(row=0, column=0, sticky='w', padx=(0, 6))
        choices = self.editor.result_choices()
        self.results_var = tk.StringVar(value=choices[0][0])
        self.results_box = ttk.Combobox(results, textvariable=self.results_var, values=[label for label, _ in choices],
                                        state='readonly' if len(choices) > 1 else 'disabled', width=20)
        self.results_box.grid(row=0, column=1, sticky='ew')
        self.results_box.bind('<<ComboboxSelected>>', lambda _event: self.apply_results_choice())
        self.tip(self.results_box, HELP_TEXTS['results'])
        footer = ttk.Frame(options, style='Card.TFrame')
        footer.grid(row=5, column=0, sticky='ew', pady=(6, 0))
        footer.columnconfigure(0, weight=1)
        qds = self._wrapped_label(footer, 'QDS: ' + self.editor.qds_text, style='Section.TLabel', row=0, column=0)
        self.tip(qds, HELP_TEXTS['qds'])
        self.preview_button = ttk.Button(footer, text='Show calculation preview', command=self.toggle_preview)
        self.preview_button.grid(row=1, column=0, sticky='w', pady=(8, 0))
        self.tip(self.preview_button, HELP_TEXTS['preview'])
        problems = self._card(strip, row=0, column=1, sticky='nsew', padx=(4, 0))
        problems.columnconfigure(0, weight=1)
        problems.rowconfigure(1, weight=1)
        ttk.Label(problems, text='Problems and warnings', style='Title.TLabel').grid(row=0, column=0, sticky='w', pady=(0, 4))
        self.problem_table = FilterTable(self, problems, (('where', 'Where', 130, False, None), ('problem', 'Problem', 600, True, None)),
                                         height=3)
        self.problem_table.grid(row=1, column=0, sticky='nsew')
        self.problem_table.empty_text = 'No problems or warnings'
        self.problem_table.tree.tag_configure('warning', foreground=self.WARNING)
        self.problem_table.tree.tag_configure('error', foreground=self.PROBLEM)
        self.preview_card = self._card(strip, row=1, column=0, columnspan=2, sticky='nsew', pady=(8, 0))
        self.preview_card.columnconfigure(0, weight=1)
        self.preview_card.rowconfigure(2, weight=1)
        ttk.Label(self.preview_card, text='What will be calculated (no results)', style='Title.TLabel').grid(
            row=0, column=0, columnspan=2, sticky='w', pady=(0, 4))
        self.preview_frame = ttk.Frame(self.preview_card, style='Card.TFrame')
        self.preview_frame.grid(row=1, column=0, columnspan=2, sticky='ew')
        self.preview_frame.columnconfigure(1, weight=1)
        self.case_preview = tk.Text(self.preview_card, height=6, width=1, wrap='word', relief='flat', borderwidth=0,
                                    background=self.CARD, foreground=self.TEXT, font=self.body_font,
                                    padx=4, pady=4, state='disabled', takefocus=True)
        self.case_preview.grid(row=2, column=0, sticky='nsew', pady=(4, 0))
        scroll = ttk.Scrollbar(self.preview_card, orient='vertical', command=self.case_preview.yview)
        scroll.grid(row=2, column=1, sticky='ns', pady=(4, 0))
        self.case_preview.configure(yscrollcommand=scroll.set)
        self._case_preview_text = None
        self.preview_card.grid_remove()

    def toggle_preview(self, show=None):
        """Show or hide the calculation preview below the problems; it is refreshed either way."""
        self.preview_visible = (not self.preview_visible) if show is None else bool(show)
        if self.preview_visible:
            self.preview_card.grid()
        else:
            self.preview_card.grid_remove()
        self.preview_button.configure(text='Hide calculation preview' if self.preview_visible else 'Show calculation preview')
        self.case_content._stick_bottom = self.preview_visible
        if self.preview_visible:
            def reveal():
                self.root.update_idletasks()
                canvas = self.case_content._viewport
                canvas.configure(scrollregion=canvas.bbox('all'))
                self.case_content._viewport.yview_moveto(1.0)
            self.root.after_idle(reveal)

    # --- tab "Settings" -------------------------------------------------------------
    def _build_settings(self, tab):
        ttk = self.ttk
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(1, weight=1)
        self.settings_book = ttk.Notebook(tab, style='Settings.TNotebook')
        self.settings_book.grid(row=1, column=0, sticky='nsew')
        for title, sections in self.SETTINGS_PAGES:
            page = ttk.Frame(self.settings_book, padding=(0, 6, 0, 0))
            self.settings_book.add(page, text=title)
            self._build_setting_page(page, sections)
        time_page = ttk.Frame(self.settings_book, padding=(0, 6, 0, 0))
        self.settings_book.add(time_page, text=self.PAGE_TIME)
        self._build_time_page(time_page)
        fixed_page = ttk.Frame(self.settings_book, padding=(0, 6, 0, 0))
        self.settings_book.add(fixed_page, text=self.PAGE_FIXED)
        self.fixed_page = fixed_page
        self._build_fixed_and_rules(fixed_page)
        self._size_settings_tabs()
        bar = ttk.Frame(tab, padding=(0, 0, 0, 6))
        bar.grid(row=0, column=0, sticky='ew')
        bar.columnconfigure(3, weight=1)
        for column, (text, command, key) in enumerate((
                ('Restore defaults', self.restore_default_settings, 'restore_defaults'),
                ('Apply settings', self.apply_settings, 'apply_settings'),
                ('Save settings', self.save_settings, 'save_settings'))):
            button = ttk.Button(bar, text=text, command=command)
            button.grid(row=0, column=column, padx=(0, 6))
            self.tip(button, SETTING_HELP[key])
        self.settings_state = self._wrapped_label(bar, '', style='Status.TLabel', row=1, column=0,
                                                  columnspan=4, pady=(8, 6))

    def _size_settings_tabs(self):
        font = self.small_font
        labels = [(page, self.settings_book.tab(page, 'text')) for page in self.settings_book.tabs()]
        longest = max(font.measure(text) for _, text in labels)
        for page, text in labels:
            self.settings_book.tab(page, padding=(14, 12, 14 + longest - font.measure(text), 12))

    @staticmethod
    def _scrollbar(scroll, first, last):
        scroll.set(first, last)
        if float(first) <= 0 and float(last) >= 1:
            scroll.grid_remove()
        else:
            scroll.grid()

    def _scrolled(self, parent, horizontal=False):
        """Fill the viewport, scrolling only when the content no longer fits."""
        canvas = self.tk.Canvas(parent, background=self.BACKGROUND, highlightthickness=0, borderwidth=0)
        scroll = self.ttk.Scrollbar(parent, orient='vertical', command=canvas.yview)
        across = self.ttk.Scrollbar(parent, orient='horizontal', command=canvas.xview)
        across.grid(row=1, column=0, sticky='ew')
        inner = self.ttk.Frame(canvas)
        window = canvas.create_window(0, 0, anchor='nw', window=inner)
        canvas.configure(yscrollcommand=lambda first, last: self._scrollbar(scroll, first, last))
        canvas.configure(xscrollcommand=lambda first, last: self._scrollbar(across, first, last))
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(0, weight=1)
        canvas.grid(row=0, column=0, sticky='nsew')
        scroll.grid(row=0, column=1, sticky='ns')
        def fit(_event=None):
            allow_horizontal = horizontal and (horizontal != 'zoom' or self.ui_zoom > 1)
            natural_height = inner.winfo_reqheight() if horizontal != 'zoom' or self.ui_zoom > 1 else 1
            canvas.itemconfigure(window, width=max(inner.winfo_reqwidth() if allow_horizontal else 1, canvas.winfo_width()),
                                 height=max(natural_height, canvas.winfo_height()))
            canvas.configure(scrollregion=canvas.bbox('all'))
            if getattr(inner, '_stick_bottom', False):
                canvas.yview_moveto(1.0)
        inner.bind('<Configure>', fit, add='+')
        canvas.bind('<Configure>', fit, add='+')
        def wheel(event):
            if event.state & 4:  # the root handles Ctrl+wheel as zoom
                return
            inner._stick_bottom = False
            target = event.widget
            if target.winfo_class() in ('Treeview', 'Listbox', 'Text', 'TCombobox'):
                return  # keep the native scrolling/selection behaviour
            if event.num in (4, 5):
                delta = -1 if event.num == 4 else 1
            else:
                delta = -int(event.delta / 120) if abs(event.delta) >= 120 else -int(event.delta)
            if canvas.yview() != (0.0, 1.0):
                canvas.yview_scroll(delta, 'units')
        def bind_wheel(widget):
            for sequence in ('<MouseWheel>', '<Button-4>', '<Button-5>'):
                widget.bind(sequence, wheel, add='+')
            for child in widget.winfo_children():
                bind_wheel(child)
        self.root.after_idle(lambda: bind_wheel(inner) if inner.winfo_exists() else None)
        inner._viewport = canvas
        inner._fit_viewport = fit
        return inner


    def _build_setting_page(self, page, sections):
        ttk = self.ttk
        inner = self._scrolled(page, horizontal=True)
        inner.columnconfigure(0, weight=1)
        if sections == ('Network scope',):
            inner.rowconfigure(1, weight=1)
        self._wrapped_label(inner, SETTINGS_INTRO, style='Status.TLabel', row=0, column=0, pady=(0, 6))
        for row, section in enumerate(sections, 1):
            frame = ttk.Frame(inner) if section == 'Network scope' else ttk.Labelframe(inner, text=section, padding=16)
            frame.grid(row=row, column=0, sticky='nsew', pady=(0, 12), padx=(0, 4))
            if section == 'Network scope':
                self._build_scope_section(frame)
                continue
            frame.columnconfigure(0, weight=2)
            frame.columnconfigure(5, weight=1)
            for column, text in enumerate(('Setting', 'Value', 'Unit', 'Source', 'Category')):
                header = ttk.Label(frame, text=text, style='Muted.TLabel')
                header.grid(row=0, column=column, sticky='w', padx=(0, 10), pady=(0, 4))
                if text == 'Source':
                    self.tip(header, SETTING_HELP['source'])
            if section == 'Classification':
                self.tip(frame, SETTING_HELP['classification'])
            elif section == 'Contingency analysis':
                self.tip(frame, SETTING_HELP['calculation_parameters'])
            else:
                self.tip(frame, SETTING_HELP['limits'])
            keys = [setting['key'] for setting in SETTINGS if setting['section'] == section]
            for line, key in enumerate(keys, 1):
                self._build_setting_row(frame, line, key)

    def _build_setting_row(self, frame, row, key):
        ttk, tk = self.ttk, self.tk
        setting = SETTINGS_BY_KEY[key]
        help_text = setting_help(key)
        label = ttk.Label(frame, text=setting['label'], wraplength=260)
        label.grid(row=row, column=0, sticky='w', padx=(0, 14), pady=8)
        self.tip(label, help_text)
        variable = tk.StringVar(value='')
        if setting['kind'] == 'choice':
            widget = ttk.Combobox(frame, textvariable=variable, values=[text for _, text in setting['choices']],
                                  state='readonly', width=18)
        else:
            widget = ttk.Entry(frame, textvariable=variable, width=12 if setting['editable'] else 18)
        widget.grid(row=row, column=1, sticky='w', padx=(0, 10), pady=1)
        self.tip(widget, help_text)
        ttk.Label(frame, text=setting['unit'], style='Muted.TLabel').grid(row=row, column=2, sticky='w', padx=(0, 10))
        source = ttk.Label(frame, text='', style='Source.TLabel')
        source.grid(row=row, column=3, sticky='w', padx=(0, 10))
        self.tip(source, SETTING_HELP['source'])
        category = ttk.Label(frame, text='A · evaluation' if setting['category'] == CATEGORY_EVALUATION else 'B · calculation',
                             style='Source.TLabel')
        category.grid(row=row, column=4, sticky='w', padx=(0, 10))
        self.tip(category, SETTING_HELP['limits'] if setting['category'] == CATEGORY_EVALUATION
                 else SETTING_HELP['calculation_parameters'])
        message = ttk.Label(frame, text='', style='Problem.TLabel', wraplength=180)
        message.grid(row=row, column=5, sticky='w')
        self.setting_vars[key], self.setting_inputs[key] = variable, widget
        self.setting_sources[key], self.setting_messages[key] = source, message
        self.fill_setting(key)
        if setting['editable']:
            variable.trace_add('write', lambda *_args, name=key: self.on_setting_edit(name))
        else:
            widget.state(['disabled'])

    def _build_scope_section(self, frame):
        """Searchable grid lists; filtering never changes a saved selection."""
        tk, ttk = self.tk, self.ttk
        frame.columnconfigure(0, weight=1, uniform='scope')
        frame.columnconfigure(1, weight=1, uniform='scope')
        frame.rowconfigure(0, weight=1)
        self.grid_lists, self.grid_search, self.grid_visible, self.grid_empty = {}, {}, {}, {}
        left = self._card(frame, row=0, column=0, sticky='nsew', padx=(0, 6))
        right = self._card(frame, row=0, column=1, sticky='nsew', padx=(6, 0))
        for parent in (left, right):
            parent.columnconfigure(0, weight=1)
            parent.rowconfigure(1, minsize=70)
            parent.rowconfigure(4, weight=1)
            parent.rowconfigure(5, minsize=60)
            parent.rowconfigure(6, minsize=40)
        title = ttk.Label(left, text='Assessed equipment', style='Title.TLabel')
        title.grid(row=0, column=0, columnspan=2, sticky='w')
        self.tip(title, setting_help('monitoring_grids'))
        self._wrapped_label(left, 'Choose the grids whose equipment is assessed.', row=1, column=0, columnspan=2, pady=(6, 10))
        self._grid_search_field(left, 'monitoring_grids', row=3)
        self._grid_listbox(left, 'monitoring_grids', row=4)
        self.monitoring_note = self._wrapped_label(left, '', row=5, column=0, columnspan=2, pady=(10, 0))
        buttons = ttk.Frame(left, style='Card.TFrame')
        buttons.grid(row=6, column=0, columnspan=2, sticky='ew', pady=(10, 0))
        for column, (text, command) in enumerate((('Select all grids', lambda: self.select_grids('monitoring_grids', True)),
                                               ('Clear selection', lambda: self.select_grids('monitoring_grids', False)))):
            button = ttk.Button(buttons, text=text, command=command)
            button.grid(row=0, column=column, sticky='w', padx=(0, 6))
            self.tip(button, SETTING_HELP['grid_buttons'])
        self._flow(buttons, buttons.winfo_children())
        title = ttk.Label(right, text='Contingencies', style='Title.TLabel')
        title.grid(row=0, column=0, columnspan=2, sticky='w')
        self.tip(title, setting_help('contingency_grids'))
        self.contingency_mode = tk.StringVar(value='same')
        choices = ttk.Frame(right, style='Card.TFrame')
        choices.grid(row=1, column=0, columnspan=2, sticky='ew', pady=(6, 10))
        for row, (value, text) in enumerate((('same', 'Same grids as the assessed equipment'), ('own', 'Own selection'))):
            radio = ttk.Radiobutton(choices, text=text, value=value, variable=self.contingency_mode,
                                    command=self.on_contingency_mode)
            radio.grid(row=row, column=0, sticky='w')
            self.tip(radio, setting_help('contingency_grids'))
        self._grid_search_field(right, 'contingency_grids', row=3)
        self._grid_listbox(right, 'contingency_grids', row=4)
        self.contingency_note = self._wrapped_label(right, '', row=5, column=0, columnspan=2, pady=(10, 0))
        self.tip(self.contingency_note, SETTING_HELP['contingency_preview'])
        self.refresh_scope()

    def _grid_search_field(self, parent, key, row):
        self.grid_search[key] = self.tk.StringVar()
        field = self.ttk.Frame(parent, style='Card.TFrame')
        field.grid(row=row, column=0, columnspan=2, sticky='ew', pady=(0, 6))
        field.columnconfigure(0, weight=1)
        self.ttk.Label(field, text='Search grids', style='Muted.TLabel').grid(row=0, column=0, sticky='w', pady=(0, 4))
        entry = self.ttk.Entry(field, textvariable=self.grid_search[key], width=12)
        entry.grid(row=1, column=0, sticky='ew')
        self.grid_search[key].trace_add('write', lambda *_args: self.refresh_scope())
        self.tip(entry, 'Filter the visible grid names. Selected grids remain selected when hidden by the search.')


    def _grid_listbox(self, parent, key, row):
        tk, ttk = self.tk, self.ttk
        box = tk.Listbox(parent, selectmode='multiple', exportselection=False, height=10, width=12, activestyle='dotbox',
                         background=self.CARD, foreground=self.TEXT, selectbackground=self.SELECTED,
                         selectforeground=self.TEXT, disabledforeground=self.MUTED,
                         highlightthickness=1, highlightcolor=self.ACCENT,
                         highlightbackground=self.BORDER, relief='flat', font=self.body_font,
                         borderwidth=0)
        box.grid(row=row, column=0, sticky='nsew', pady=(4, 0))
        scroll = ttk.Scrollbar(parent, orient='vertical', command=box.yview)
        scroll.grid(row=row, column=1, sticky='ns', pady=(4, 0))
        box.configure(yscrollcommand=lambda first, last: self._scrollbar(scroll, first, last))
        box.bind('<<ListboxSelect>>', lambda _event, name=key: self.on_grid_select(name), add='+')
        self.tip(box, setting_help(key))
        self.grid_lists[key] = box
        empty = ttk.Label(parent, text='No grids available', style='Muted.TLabel', anchor='center', wraplength=220)
        self.grid_empty[key] = (empty, row)


    def refresh_scope(self):
        """Render the view without changing the editor's complete grid selection."""
        if not getattr(self, 'grid_lists', None):
            return
        choices = self.editor.grid_choices()
        contingency = self.editor.selected_grids('contingency_grids')
        self.contingency_mode.set('same' if contingency is None else 'own')
        for key, box in self.grid_lists.items():
            query = self.grid_search[key].get().strip().casefold()
            visible = [name for name in choices if query in name.casefold()]
            self.grid_visible[key] = visible
            selected = set(self.editor.selected_grids(key) or ())
            if key == 'contingency_grids' and contingency is None:
                selected = set(self.editor.selected_grids('monitoring_grids'))
            scroll = box.yview()
            box.configure(state='normal', background=self.CARD)
            box.delete(0, 'end')
            for name in visible:
                missing = self.editor.grids is not None and name not in self.editor.grids
                box.insert('end', name + ('  (not in the project)' if missing else
                                          '  (inactive)' if name in self.editor.inactive_grids else ''))
                if name in selected:
                    box.selection_set('end')
            if scroll:
                box.yview_moveto(scroll[0])
            if key == 'contingency_grids' and contingency is None:
                box.configure(state='disabled', background=self.FILTER)
            empty, row = self.grid_empty[key]
            if visible:
                empty.grid_remove()
            else:
                empty.configure(text='No matching grids' if choices else 'No grids available in this model')
                empty.grid(row=row, column=0, sticky='ew', padx=10)
        if not choices:
            self.monitoring_note.configure(text='No grid could be read from the model; every element is assessed.')
        else:
            self.monitoring_note.configure(text='Assessed: ' + self.editor.monitoring_text() +
                                           '. No grid selected: every grid is assessed.')
        self.contingency_note.configure(text=self.editor.contingency_preview())


    def on_grid_select(self, key):
        box = self.grid_lists[key]
        if str(box.cget('state')) == 'disabled':
            return
        visible = self.grid_visible[key]
        selected = [name for name in self.editor.selected_grids(key) or () if name not in visible]
        selected += [visible[index] for index in box.curselection()]
        problem = self.editor.set_grids(key, selected)
        if problem:
            self.messagebox.showerror('Network scope', problem, parent=self.root)
        self.after_scope_change()


    def select_grids(self, key, everything):
        problem = self.editor.set_grids(key, self.editor.grid_choices() if everything else [])
        if problem:
            self.messagebox.showerror('Network scope', problem, parent=self.root)
        self.after_scope_change()

    def on_contingency_mode(self):
        if self.contingency_mode.get() == 'same':
            self.editor.set_grids('contingency_grids', None)
        else:
            self.editor.set_grids('contingency_grids', self.editor.selected_grids('monitoring_grids'))
        self.after_scope_change()

    def after_scope_change(self):
        self.refresh_scope()
        self.refresh_cases(self.selected)
        self.refresh_overview()

    def _build_time_page(self, page):
        ttk = self.ttk
        page.columnconfigure(0, weight=1)
        inner = self._scrolled(page)
        inner.columnconfigure(0, weight=1)
        card = self._card(inner, row=0, column=0, sticky='new')
        card.columnconfigure(1, weight=1)
        title = ttk.Label(card, text='QDS time base (read only)', style='Title.TLabel')
        title.grid(row=0, column=0, columnspan=2, sticky='w', pady=(0, 6))
        self.tip(title, HELP_TEXTS['qds'])
        for row, (label, value) in enumerate(self.editor.qds_info, 1):
            caption = ttk.Label(card, text=label, style='Muted.TLabel')
            caption.grid(row=row, column=0, sticky='nw', padx=(0, 14), pady=8)
            shown = ttk.Label(card, text=value, wraplength=520)
            shown.grid(row=row, column=1, sticky='w', pady=1)
            self.tip(shown, HELP_TEXTS['qds'])
        self._wrapped_label(card, 'Change the period and the time step in PowerFactory (ComStatsim). n-1 and (n-1)\' will '
                            'use the same points in time once they are available.', row=len(self.editor.qds_info) + 1,
                            column=0, columnspan=2, pady=(8, 0))

    # --- settings -------------------------------------------------------------------
    def setting_entry_text(self, key):
        """The applied value of a setting as the entry shows it."""
        setting = SETTINGS_BY_KEY[key]
        if not setting['editable']:
            return NOT_VERIFIED
        value = self.editor.settings_overrides().get(key, setting['default'])
        if setting['kind'] == 'choice':
            return dict(setting['choices']).get(value, str(value))
        return format_limit(value)

    def fill_setting(self, key):
        self.setting_vars[key].set(self.setting_entry_text(key))
        self.on_setting_edit(key)

    def setting_value(self, key):
        """What the entry holds, as parse_setting expects it."""
        text = self.setting_vars[key].get()
        if SETTINGS_BY_KEY[key]['kind'] == 'choice':
            return {label: value for value, label in SETTINGS_BY_KEY[key]['choices']}.get(text, text)
        return text

    def on_setting_edit(self, key):
        """Check one field while it is typed: red when invalid, 'edited, not applied' when it differs."""
        setting = SETTINGS_BY_KEY[key]
        widget, message, source = self.setting_inputs[key], self.setting_messages[key], self.setting_sources[key]
        problem = None
        if setting['editable']:
            _, problem = parse_setting(key, self.setting_value(key))
            if setting['kind'] != 'choice':
                widget.configure(style='Invalid.TEntry' if problem else 'TEntry')
        message.configure(text=problem or '')
        if not setting['editable']:
            source.configure(text=setting['source'] + ' · ' + NOT_VERIFIED, style='Source.TLabel')
        elif self.setting_vars[key].get() != self.setting_entry_text(key):
            source.configure(text='edited, not applied', style='User.TLabel')
        else:
            origin = setting_source(key, self.editor.settings_overrides())
            source.configure(text=origin, style='User.TLabel' if origin == SOURCE_USER else 'Source.TLabel')
        self.refresh_settings_state()

    def pending_settings(self):
        """Keys whose entry differs from the applied value."""
        return [key for key in self.setting_vars if SETTINGS_BY_KEY[key]['editable']
                and self.setting_vars[key].get() != self.setting_entry_text(key)]

    def refresh_settings_state(self):
        if not hasattr(self, 'settings_state'):
            return
        invalid = [key for key in self.setting_vars if self.setting_messages[key].cget('text')]
        pending = self.pending_settings()
        overrides = self.editor.settings_overrides()
        parts = ['{} user override(s)'.format(len(overrides)) if overrides else 'GridLens defaults']
        if pending:
            parts.append('{} edited, not applied'.format(len(pending)))
        if invalid:
            parts.append('{} invalid'.format(len(invalid)))
        self.settings_state.configure(text='Settings: ' + ', '.join(parts),
                                      foreground=self.PROBLEM if invalid else self.MUTED)
        self.notebook.tab(self.settings_tab, text=self.TAB_SETTINGS + (' (!)' if invalid else ' *' if pending else ''))

    def apply_settings(self, quiet=False):
        """Validate every entry and take them for the next calculation; False when one is invalid."""
        values = {key: self.setting_value(key) for key in self.setting_vars if SETTINGS_BY_KEY[key]['editable']}
        problems = self.editor.set_settings(values)
        for key in self.setting_vars:
            self.setting_messages[key].configure(text='')
        for key, problem in problems:
            if key in self.setting_messages:
                self.setting_messages[key].configure(text=problem)
                if SETTINGS_BY_KEY[key]['kind'] != 'choice':
                    self.setting_inputs[key].configure(style='Invalid.TEntry')
        if problems:
            self.refresh_settings_state()
            if not quiet:
                self.messagebox.showerror('Settings', 'The settings were not applied:\n' + '\n'.join(
                    problem for _, problem in problems), parent=self.root)
            return False
        for key in self.setting_vars:
            self.fill_setting(key)
        self.refresh_cases(self.selected)
        self.refresh_overview()
        return True

    def restore_default_settings(self):
        self.editor.restore_default_settings()
        for key in self.setting_vars:
            self.fill_setting(key)
        self.refresh_scope()
        self.refresh_cases(self.selected)
        self.refresh_overview()

    def save_settings(self):
        if self.apply_settings():
            self.save()

    # --- showing the editor state ---------------------------------------------------
    def refresh_all(self, select=None):
        self.refresh_cases(select)
        self.refresh_selected()

    def refresh_cases(self, select=None):
        statuses = self.editor.case_statuses()
        self.case_table.set_rows([(case_id, ('\u2611' if enabled else '\u2610', self.editor.case_label(case_id), count, statuses.get(case_id, '')))
                                  for case_id, enabled, _, count in self.editor.case_rows()])
        full = self.editor.limit_problem() is not None
        self.case_limit_label.configure(text='{} of {} cases'.format(len(self.editor.case_ids()), case_limit(self.editor.config)),
                                        style='Problem.TLabel' if full else 'Muted.TLabel')
        for label in ('New', 'Copy'):
            self.case_buttons[label].state(['disabled'] if full else ['!disabled'])
        self.selected = select if self.editor.case(select) is not None else None
        if self.selected is not None and self.selected in self.case_tree.get_children():
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
        self.member_table.set_rows(self.editor.member_rows(self.selected))
        self.refresh_available()
        self.draw_timeline()
        self.refresh_overview()

    def refresh_available(self):
        self.available_table.set_rows(self.editor.available_rows(self.selected))

    def refresh_overview(self):
        """Fixed background and rules, the calculation preview, the problems, the status line and the tab labels."""
        with RUN_STATS.measure("case manager: refresh after an edit"):
            self._refresh_overview()

    def _refresh_overview(self):
        self.fixed_table.set_rows(self.editor.fixed_rows())
        self.rule_table.set_rows([(str(index), cells) for index, cells in self.editor.rule_rows()])
        lines, _ = self.editor.summary()
        # Keep the overview compact; outage windows and settings are shown in
        # the scrollable case preview below, including on a small screen.
        lines = [(label, text) for label, text in lines
                 if label in ('Cases selected', 'Valid cases', 'Reference', 'Calculation runs', 'QDS period')]
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
        text = self.editor.calculation_preview()
        if text != self._case_preview_text:
            scroll = self.case_preview.yview()
            self.case_preview.configure(state='normal')
            self.case_preview.delete('1.0', 'end')
            self.case_preview.insert('1.0', text)
            self.case_preview.configure(state='disabled')
            if scroll:
                self.case_preview.yview_moveto(scroll[0])
            self._case_preview_text = text
        problems = self.editor.problem_rows()
        self.problem_table.set_rows([(str(index), cells) for index, cells in enumerate(problems)])
        self.problem_table.tree.configure(show='tree', displaycolumns=('where', 'problem'))
        self.problem_table.tree.column('#0', width=28, minwidth=28, stretch=False)
        for index, (_, message) in enumerate(problems):
            warning = message.startswith('Warning:')
            self.problem_table.tree.item(str(index), text='△' if warning else '!', tags=('warning' if warning else 'error',))
        self.notebook.tab(self.cases_tab, text=self.TAB_CASES + (' ({})'.format(len(problems)) if problems else ''))
        statuses = self.editor.case_statuses()
        ready = sum(1 for status in statuses.values() if status == 'ready')
        overrides = self.editor.settings_overrides()
        self.status_line.configure(
            text='QDS {}  ·  n-0  ·  {} of {} cases ready  ·  {}  ·  {}'.format(
                self.editor.qds_text, ready, len(self.editor.config['cases']),
                _counted(len(problems), 'problem or warning', 'problems or warnings') if problems else 'no problems',
                _counted(len(overrides), 'settings override', 'settings overrides') if overrides else 'default settings'),
            foreground=self.PROBLEM if problems else self.MUTED)
        self.refresh_settings_state()

    def refresh_preview(self):
        self.refresh_overview()

    def draw_timeline(self):
        canvas = self.canvas
        canvas.delete('all')
        items, overlaps = self.editor.timeline(self.selected)
        width = max(canvas.winfo_width(), 360)
        label_width, row_height, top = 180, round(30 * self.ui_scale), 8
        self.timeline_start.configure(text='')
        self.timeline_end.configure(text='')
        if not items:
            canvas.configure(height=36)
            canvas.create_text(10, 20, anchor='w', fill=self.MUTED, font=self.body_font, text='No planned outage with a readable window in this case.')
            canvas.configure(scrollregion=(0, 0, width, 36))
            return
        canvas.configure(height=78)
        self.timeline_start.configure(text='Window start: ' + _format_pf_time(min(item[1] for item in items)))
        self.timeline_end.configure(text='Window end: ' + _format_pf_time(max(item[2] for item in items)))
        position, breaks = timeline_scale([(start, end) for _, start, end, _ in items], width - label_width - 14)
        x = lambda moment: label_width + position(moment)
        bottom = top + row_height * len(items)
        for left, right in breaks:
            canvas.create_rectangle(label_width + left, top - 4, label_width + right, bottom, fill=self.GAP, outline='')
        for start, end in overlaps:
            canvas.create_rectangle(x(start), top - 4, x(end), bottom, fill=self.OVERLAP, outline='')
        for index, (name, start, end, kind) in enumerate(items):
            y = top + index * row_height
            canvas.create_text(4, y + row_height / 2, anchor='w', text=clip_text(name, 26), fill=self.TEXT, font=self.body_font)
            left = x(start)
            canvas.create_rectangle(left, y + 4, max(x(end), left + 3), y + row_height - 4,
                                    fill=self.ACCENT if kind == 'case' else self.FIXED, outline='')
        # The same compressed scale and intervals; endpoint dates sit below the canvas.
        canvas.create_line(label_width, bottom + 2, width - 14, bottom + 2, fill=self.MUTED)
        canvas.configure(scrollregion=(0, 0, width, bottom + 8))

    # --- cases -------------------------------------------------------------------
    def on_case_select(self, _event=None):
        chosen = self.case_tree.selection()
        identifier = chosen[0] if chosen else None
        if identifier is not None and identifier != self.selected:
            self.selected = identifier
            self.refresh_selected()

    def on_case_flag_click(self, event):
        tree = self.case_tree
        if tree.identify_region(event.x, event.y) != 'cell' or tree.identify_column(event.x) != '#1':
            return None
        self.toggle_case_enabled(tree.identify_row(event.y))
        return 'break'

    def toggle_case_enabled(self, case_id):
        case = self.editor.case(case_id)
        if case is None:
            return
        self.finish_editing()
        self.editor.set_enabled(case_id, not case.get('enabled', True))
        self.refresh_all(case_id)

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
        if self.on_case_flag_click(event) == 'break':
            return 'break'
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
        box = (left, label.winfo_y(), max(heading.winfo_width() - left, 200), max(label.winfo_height(), 26))

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

    def _bind_delete(self, tree, command):
        for sequence in ('<Delete>', '<BackSpace>'):
            tree.bind(sequence, lambda _event: (command(), 'break')[1])

    def _bind_window_keys(self):
        """Ctrl shortcuts for the whole window (on macOS also Command); see KEYBOARD_SHORTCUTS."""
        modifiers = ['Control']
        try:
            if self.root.tk.call('tk', 'windowingsystem') == 'aqua':
                modifiers.append('Command')
        except Exception:
            pass
        for key, command in (('n', self.new_case), ('s', self.save), ('o', self.load_saved),
                             ('Return', self.start), ('f', self.focus_search)):
            for modifier in modifiers:
                self.root.bind('<{}-{}>'.format(modifier, key), lambda _event, run=command: (run(), 'break')[1])
        for table in (self.case_table, self.member_table, self.available_table, self.fixed_table, self.rule_table,
                      self.problem_table):
            for modifier in modifiers:
                table.tree.bind('<{}-a>'.format(modifier), lambda _event, tree=table.tree: (
                    tree.selection_set(tree.get_children()), 'break')[1])

    def focus_search(self):
        """Ctrl+F: the name filter of the available planned outages, on the Case Manager tab."""
        self.notebook.select(self.cases_tab)
        search = self.available_table.inputs[1]
        search.focus_set()
        search.select_range(0, 'end')

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
        if not self.messagebox.askyesno('Delete case', 'Delete case {}?\nOther cases and the planned outages stay unchanged.'.format(
                self.editor.case_label(self.selected)), parent=self.root):
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
        window.geometry(window_geometry(window.winfo_screenwidth(), window.winfo_screenheight(), share=0.65, largest=(900, 760)))
        window.minsize(min(560, window.winfo_screenwidth()), min(400, window.winfo_screenheight()))
        inner = self._scrolled(window, horizontal=True)
        inner.columnconfigure(0, weight=1)
        frame = self.ttk.Frame(inner, style='Card.TFrame', padding=20)
        frame.grid(row=0, column=0, sticky='nsew')
        frame.columnconfigure(1, weight=1)
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
    def apply_results_choice(self):
        self.editor.set_evaluate_stamp(dict(self.editor.result_choices()).get(self.results_var.get()))
        self.refresh_overview()

    def apply_assessments(self):
        if self.n1_prime_var.get() and not self.n1_var.get():
            # (n-1)' is compared with n-1: ticking (n-1)' ticks n-1, unticking n-1 unticks (n-1)'.
            if self.n1_prime_var.get() and self.editor.config['assessments'].count(N1_PRIME):
                self.n1_prime_var.set(False)
            else:
                self.n1_var.set(True)
        self.editor.set_assessments(True, self.n1_var.get(), self.n1_prime_var.get())
        self.refresh_overview()

    def _settings_ready(self, title):
        """Apply edited settings first; False (with the reason shown) when one is invalid."""
        if not self.pending_settings() and not any(self.setting_messages[key].cget('text') for key in self.setting_messages):
            return True
        if self.apply_settings(quiet=True):
            return True
        self.notebook.select(self.settings_tab)
        self.messagebox.showerror(title, 'Invalid settings:\n' + '\n'.join(
            '{}: {}'.format(SETTINGS_BY_KEY[key]['label'], self.setting_messages[key].cget('text'))
            for key in self.setting_messages if self.setting_messages[key].cget('text')), parent=self.root)
        return False

    def save(self):
        self.finish_editing()
        if not self._settings_ready('Save configuration'):
            return
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
        self.n1_var.set(N1_REFERENCE in self.editor.config['assessments'])
        self.n1_prime_var.set(N1_PRIME in self.editor.config['assessments'])
        for key in self.setting_vars:
            self.fill_setting(key)
        self.refresh_scope()
        for table in (self.case_table, self.member_table, self.available_table, self.fixed_table, self.rule_table, self.problem_table):
            table.clear_filters()
        ids = self.editor.case_ids()
        self.refresh_all(ids[0] if ids else None)

    def start(self):
        """Check the configuration and hand it to GridLens; the calculation starts after the window closes."""
        self.finish_editing()
        if not self._settings_ready('Start calculation'):
            return
        problem = self.editor.set_assessments(True, self.n1_var.get(), self.n1_prime_var.get())
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
        self.outcome = dict(self.editor.config)
        if self.editor.evaluate_stamp:
            # Only for this run, never saved: re-evaluate a kept run instead of calculating.
            self.outcome['evaluate_stamp'] = self.editor.evaluate_stamp
        self.root.destroy()

    def cancel(self):
        self.outcome = None
        self.root.destroy()


def run_case_manager(records, config, period, config_path, user='', qds_text='', qds_info=None, grids=None,
                     contingencies=CONTINGENCIES_NOT_READ, kept=()):
    """Show the case manager; the edited configuration on "Start calculation", None on Cancel."""
    try:
        import tkinter as tk
        import tkinter.font
        from tkinter import messagebox, simpledialog, ttk
        root = tk.Tk()
    except Exception as exc:
        raise CaseManagerUnavailable('The case manager cannot open a window: {}'.format(_friendly_exception(exc))) from None
    dialog = CaseManagerDialog(root, CaseEditor(records, config, period, qds_text, qds_info, grids, contingencies, kept),
                               config_path, user,
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


def counts_text(counted, limit=8):
    ordered = sorted(counted.items(), key=lambda entry: (-entry[1], entry[0]))
    return ", ".join("{} {}".format(name, number) for name, number in ordered[:limit]) + (
        " and {} more".format(len(ordered) - limit) if len(ordered) > limit else "") or "none"


def _read_setting(obj, attribute):
    try:
        return True, getattr(obj, attribute)
    except Exception:
        getter = getattr(obj, "GetAttribute", None)
        if callable(getter):
            try:
                return True, getter(attribute)
            except Exception:
                pass
    return False, None


def _format_setting_value(value):
    if type(value) is bool:
        return "true" if value else "false"
    numeric = finite_number(value)
    if numeric is not None:
        return "{:g}".format(numeric)
    if class_name(value):
        return "'{}' ({})".format(object_name(value), class_name(value))
    if isinstance(value, (list, tuple)):
        return "[{}]".format(
            ", ".join(_format_setting_value(item) for item in value))
    return str(value)


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


def project_grids(app):
    """Every grid (ElmNet) of the model as (name, active), sorted by name; read only, [] when none can be read.

    Active grids come from GetCalcRelevantObjects, the others from the project's
    network data, so that every grid of the model can be chosen; equipment of
    an inactive grid is not calculated and is labelled so. The summary grid of
    a study case is no grid of the model and is left out.
    """
    found = {}
    try:
        for grid in app.GetCalcRelevantObjects('*.ElmNet') or []:
            if class_name(grid) == 'ElmNet' and object_name(grid) and not is_summary_grid(grid):
                found[object_name(grid)] = True
    except Exception:
        pass
    try:
        folder = app.GetProjectFolder('netdat') or app.GetActiveProject()
        for grid in folder.GetContents('*.ElmNet', 1) or []:
            if class_name(grid) == 'ElmNet' and object_name(grid) and not is_summary_grid(grid):
                found.setdefault(object_name(grid), False)
    except Exception:
        pass
    return sorted(found.items(), key=lambda item: item[0].casefold())


def is_summary_grid(grid):
    """The "Summary Grid" every study case carries (an ElmNet stored in the IntCase); it holds no equipment."""
    try:
        return class_name(grid.GetParent()) == 'IntCase'
    except Exception:
        return False


def read_contingencies(study_case):
    """The contingencies of the study case's ComSimoutage with their equipment and grids, read only.

    None when the study case has no contingency analysis. The equipment of a
    contingency is read with ComOutage.GetObject(line), line 0, 1, ... until
    None ("interrupted components"); nothing is executed or changed.
    """
    try:
        commands = [item for item in study_case.GetContents('*.ComSimoutage') or [] if class_name(item) == 'ComSimoutage']
    except Exception:
        commands = []
    if not commands:
        return None
    command = commands[0]
    try:
        outages = [item for item in command.GetContents('*.ComOutage') or [] if class_name(item) == 'ComOutage']
    except Exception:
        outages = []
    found = []
    for outage in outages:
        elements = []
        getter = getattr(outage, 'GetObject', None)
        for line in range(MAX_CONTINGENCY_ELEMENTS if callable(getter) else 0):
            try:
                element = getter(line)
            except Exception:
                break
            if element is None:
                break
            elements.append(element)
        found.append({'name': object_name(outage), 'number': safe_attr(outage, 'number'),
                      'analysed': safe_attr(outage, 'outserv', 0) in (0, False),
                      'elements': [object_name(element) for element in elements],
                      'grids': sorted({element_grid_name(element) or '(no grid)' for element in elements}, key=str.casefold)})
    return {'command': object_name(command), 'contingencies': found}


def contingency_scope(info, contingency_grids, monitoring_grids=()):
    """Which contingencies the selection keeps. None for the contingency grids means the assessed grids.

    A contingency is in scope when all of its equipment lies in the selected
    grids, partly in scope when only some does, outside when none does; with
    no grid selected every contingency is in scope. The n-1 run sets the contingencies outside to 'Not analysed'.
    """
    grids = tuple(monitoring_grids if contingency_grids is None else contingency_grids)
    scope = {'grids': grids, 'in': [], 'partly': [], 'outside': [], 'unknown': [], 'not_analysed': []}
    for contingency in (info or {}).get('contingencies') or ():
        if not contingency['analysed']:
            scope['not_analysed'].append(contingency['name'])
            continue
        if not contingency['grids']:
            scope['unknown'].append(contingency['name'])
            continue
        inside = [grid in grids for grid in contingency['grids']] if grids else [True]
        scope['in' if all(inside) else 'partly' if any(inside) else 'outside'].append(contingency['name'])
    return scope


def contingency_scope_text(info, contingency_grids, monitoring_grids=()):
    """One line for preview, log and report."""
    if info is None:
        return 'no contingency analysis (ComSimoutage) in the active study case'
    scope = contingency_scope(info, contingency_grids, monitoring_grids)
    total = len(info['contingencies'])
    parts = ['{} of {} contingencies of {!r} in scope ({})'.format(
        len(scope['in']), total, info['command'], ', '.join(scope['grids']) if scope['grids'] else 'every grid')]
    for key, label in (('partly', 'partly outside'), ('outside', 'outside'), ('unknown', 'equipment not readable'),
                       ('not_analysed', 'already "Not analysed"')):
        if scope[key]:
            parts.append('{} {}'.format(len(scope[key]), label))
    return '; '.join(parts) + ". Applied to the n-1 run: the contingencies outside are 'Not analysed' for the run."


def qds_time_info(qds, period):
    """(label, value) lines of the ComStatsim time base for the Settings tab; read only, nothing is written."""
    start, end = period
    lines = [('QDS start', _format_pf_time(start) if start is not None else 'not readable'),
             ('QDS end', _format_pf_time(end) if end is not None else 'not readable')]
    if qds is not None:
        parts = []
        for label, attribute in QDS_CORE_SETTINGS:
            found, value = _read_setting(qds, attribute)
            parts.append('{} [{}] = {}'.format(label, attribute, _format_setting_value(value) if found else 'not exposed'))
        lines.append(('QDS time step', '; '.join(parts)))
    else:
        lines.append(('QDS time step', 'as set in the active ComStatsim (not passed to this window)'))
    lines += [('Time definition', 'ComStatsim startTime / endTime in epoch seconds, shown in the local time of this computer'),
              ('Calculated period', 'the complete ComStatsim period with its time step, in every run; nothing is shortened')]
    return lines


def qds_period_text(period):
    """'2016-07-01 00:00 - 2016-08-01 00:00' for the ComStatsim period, as the case manager shows it."""
    start, end = period
    if start is None or end is None:
        return 'not readable from ComStatsim'
    return '{} - {}'.format(_format_pf_time(start), _format_pf_time(end))


RESULTS_CALCULATE = 'Calculate now'


def stamp_text(stamp):
    """'261023-120000' as '2026-10-23 12:00:00'."""
    try:
        return datetime.strptime(stamp, "%y%m%d-%H%M%S").strftime("%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError):
        return str(stamp)


KEPT_STAMP = re.compile(r'^' + re.escape(SNAPSHOT_PREFIX) + r'(\d{6}-\d{6})_')


def kept_stamps(study_case):
    """The stamps of earlier GridLens runs whose result objects are kept in the study case, newest first."""
    stamps = set()
    for obj in _contents(study_case, '*.ElmRes'):
        match = KEPT_STAMP.match(object_name(obj))
        if match:
            stamps.add(match.group(1))
    return sorted(stamps, reverse=True)


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


# Grids and contingencies read by read_project (None / not read in demo mode).
SCOPE = {"grids": None, "contingencies": CONTINGENCIES_NOT_READ}


def read_project(app):
    """Planned outages, simulated period, source and the ComStatsim, read only; demo data where PowerFactory has none."""
    if app is None:
        return None, None, "DEMO", "PowerFactory is not available", None
    # GetContents, not GetFromStudyCase: the latter creates a ComStatsim when the study case has none.
    try:
        study_case = app.GetActiveStudyCase()
        found = [item for item in study_case.GetContents("*.ComStatsim") or [] if item.GetClassName() == "ComStatsim"]
        qds = found[0] if found else None
    except Exception:
        study_case, qds = None, None
    # Read only, for Settings -> Network scope.
    SCOPE["grids"] = project_grids(app)
    SCOPE["contingencies"] = read_contingencies(study_case) if study_case is not None else None
    period = qds_period(qds) if qds is not None else (None, None)
    try:
        records, _ = classify_planned_outages(app, RunLogger(app), period)
    except Exception as exc:
        return None, period, "DEMO", "planned outages could not be read: {}".format(_friendly_exception(exc)), qds
    if not records:
        return None, period, "DEMO", "the project has no planned outage", qds
    assign_definitions(records)
    return records, period, "PowerFactory", "", qds


def starting_configuration(app, scratch):
    """The saved configuration of the project, copied to `scratch`; save and load in the window use the copy."""
    try:
        project_key = object_key(app.GetActiveProject()) if app is not None else "demo project"
    except Exception:
        project_key = "project"
    copy = os.path.join(scratch, "cases.json")
    if USE_SAVED_CONFIGURATION and app is not None:
        real = case_config_path(project_key)
        if not os.path.isfile(real):
            real = legacy_case_config_path(project_key)  # the GridLens 8.0 file, read only
        if os.path.isfile(real):
            shutil.copyfile(real, copy)
            try:
                return load_case_config(copy), copy, "saved configuration " + real
            except GridLensError as exc:
                # A damaged file must not stop the GUI test; GridLens itself would report it.
                os.remove(copy)
                return empty_case_config(project_key), copy, "empty configuration ({})".format(exc)
    return empty_case_config(project_key), copy, "empty configuration"


PRIVACY_NOTE = "PRIVACY: LOCAL USE ONLY. The output of this tool contains project, grid and equipment names, paths and values; do not pass it on. For output that may be shared use tools/probe_contingency.py (strict privacy)."


def run(app):
    log(app, PRIVACY_NOTE)
    log(app, "Python {}; this test changes nothing in PowerFactory and calculates nothing.".format(sys.version.split()[0]))
    try:
        import tkinter as tk
        log(app, "tkinter imported: Tcl {}, Tk {}.".format(tk.TclVersion, tk.TkVersion))
    except Exception as exc:
        log(app, "FAIL: tkinter cannot be imported: {!r}. This Python has no Tcl/Tk; GridLens would fall back to the saved "
                 "configuration or one case per planned outage.".format(exc))
        return False
    log(app, "Case manager copied from GridLens {} (standalone, gridlens_report.py is not used).".format(PUBLISHER_VERSION))
    records, period, source, reason, qds = read_project(app)
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
                                       qds_text=qds_period_text(period), qds_info=qds_time_info(qds, period),
                                       grids=SCOPE["grids"], contingencies=SCOPE["contingencies"])
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
