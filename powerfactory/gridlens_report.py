"""GridLens single-file runtime for DIgSILENT PowerFactory 2026."""

from __future__ import annotations

import bisect
import json
import re
from array import array
import getpass
import hashlib
import math
import os
import time
from datetime import datetime

HOST_TABLE_PREFIX = 'Scripted'
TOP_N = 10
MAX_PLOT_POINTS = 200
MAX_VOLTAGE_ROWS = 30
# Defaults of the Settings tab (SETTINGS); a run uses the active settings
# through loading_limit(), voltage_band(), setting_value() and the other
# helpers, never these names directly (a constant is the default of its setting).
LOADING_MAX = 100.0
# Loading classes and the appendix start here.
LOADING_WARNING = 80.0
# Smaller changes count as unchanged: %-points for loading, p.u. for voltage.
LOADING_DELTA_TOLERANCE = 0.1
VOLTAGE_DELTA_TOLERANCE = 0.001
# The appendix also lists elements that change at least this much.
LOADING_APPENDIX_DELTA = 1.0
VOLTAGE_APPENDIX_DELTA = 0.005
# Permitted voltage band in p.u. of the nominal voltage, the same for every voltage level.
VOLTAGE_MIN = 0.95
VOLTAGE_MAX = 1.05
# Below this a node counts as de-energised at that time step, not as a value.
ENERGIZED_MIN_PU = 0.1
# Upper bound of n-1 study times per case: every study time calculates every contingency.
MAX_N1_TIMES = 2000
TIME_UNIT_FALLBACK = 'h'
PUBLISHER_VERSION = '8.0.0'
TEMPLATE_NAME = 'MASTER_GRIDLENS'
TEMPLATE_VERSION = '6.0.0'
DATA_CONTRACT_VERSION = '6.0'
RUN_REFERENCE_CASE = True
# Where the planning cases come from:
#   'gui'        open the case manager; without tkinter use the saved
#                configuration, without one fall back to 'per_outage'
#   'saved'      the configuration saved for this project, no dialog
#   'per_outage' one case per planned outage in the simulated period (7.x)
CASE_SOURCE = 'gui'
# Folder of the saved case configurations; '' is ~/GridLens/cases.
CASE_CONFIG_DIR = ''
# At most this many planning cases in the case manager and in a saved
# configuration. Cases get generated IDs C1 ... C5; the engineer only names them.
MAX_CASES = 5
CASE_CONFIG_SCHEMA = 'gridlens.cases'
CASE_CONFIG_SCHEMA_VERSION = 2
# Assessments a configuration may ask for. Only the quasi-dynamic n-0
# assessment exists in the calculation pipeline; n-1 is named so that the
# case manager can show it as unavailable instead of hiding the question.
N1_REFERENCE, N1_PRIME = 'n-1', "(n-1)'"
ASSESSMENTS = ('n-0', N1_REFERENCE, N1_PRIME)
AVAILABLE_ASSESSMENTS = ASSESSMENTS
# The time base is the active ComStatsim: every run covers its complete period
# with its own time step. GridLens shortens no window, adds no time step and
# never changes the time step (there is no time optimisation).
# A case may give a planned outage a date of its own. Applying it means
# writing IntPlannedout.starttime / endtime for the run; this is off until it
# is verified in PowerFactory, and such a case is reported NOT EVALUATED.
ALLOW_OUTAGE_TIME_OVERRIDE = False
# Optional. An empty string (the default) assesses every element. With a text,
# only elements whose grid (PowerFactory attribute "Grid", cpGrid) has a name
# containing it are assessed and every other element is ignored as foreign
# network, e.g. 'D7' for the Europe model. Grids chosen in the case manager
# (Settings -> Network scope) take precedence over this text.
GRID_NAME_FILTER = ''
VARIABLES = {'line': ('c:loading', 'm:loading'), 'transformer': ('c:loading', 'm:loading'), 'voltage': ('m:u', 'm:u1')}
CLASS_CATEGORIES = {'ElmLne': ('line',), 'ElmTr2': ('transformer',), 'ElmTr3': ('transformer',), 'ElmTerm': ('voltage',)}
MAX_RESULT_ROWS = 35040
MAX_RESULT_CELLS = 20000000
MAX_RUN_CELLS = 120000000
MAX_TABLE_ROWS = 5000
PUBLICATION_LOG_INTERVAL_SECONDS = 5.0
SNAPSHOT_PREFIX = 'GridLens_'

FIELD_TYPES = {'string': 0, 'integer': 1, 'number': 2}
MAX_LABEL_LENGTH = 80
MAX_TEXT_LENGTH = 500
MAX_DIAGNOSTIC_LENGTH = 4000
ABSOLUTE_TIME_THRESHOLD_HOURS = 87600.0
_LABEL_SUFFIXES = ('_id', '_name', '_label', '_type', '_level', '_time')
_LABEL_FIELDS = ('unit', 'variable', 'status', 'reason', 'action', 'timestamp', 'metric_name', 'check_name', 'ranking_type', 'simulation_status', 'simulation_start', 'simulation_end', 'simulation_time_step', 'generation_date', 'assessment_status')

# Lists of names that must stay readable in full.
_LONG_LABEL_FIELDS = ('equipment_name',)

def text_limit(field):
    if field in _LONG_LABEL_FIELDS:
        return MAX_TEXT_LENGTH
    if field in _LABEL_FIELDS or field.endswith(_LABEL_SUFFIXES):
        return MAX_LABEL_LENGTH
    return MAX_TEXT_LENGTH
CASE_SLOTS = 6
SERIES_SLOTS = CASE_SLOTS + 1


def _slot_fields(pattern, kind, first=1, last=CASE_SLOTS):
    return tuple((pattern.format(index), kind) for index in range(first, last + 1))


# Tables that compare REF with up to CASE_SLOTS cases side by side. Further cases
# continue in the next block; the headers travel with every row so that no data
# relation is needed.
MATRIX_FIELDS = (
    (("block", "integer"), ("row_order", "integer"), ("element_name", "string"), ("ref_text", "string"))
    + _slot_fields("c{}_text", "string") + _slot_fields("h{}_name", "string") + (("col_count", "integer"), ("violation", "integer")))
# Charts that draw REF and up to CASE_SLOTS cases: one fixed series per slot.
SERIES_NAME_FIELDS = _slot_fields("s{}_name", "string", 0)
SERIES_VALUE_FIELDS = _slot_fields("v{}", "number", 0)
TREND_FIELDS = (
    (("time_label", "string"), ("timestamp", "number"), ("element_name", "string"), ("chart_title", "string"),
     ("unit", "string")) + SERIES_NAME_FIELDS + SERIES_VALUE_FIELDS)

TABLES = (
    ("ScriptedReportMeta", (
        ("study_id", "string"), ("study_name", "string"), ("study_description", "string"),
        ("model_name", "string"), ("model_version", "string"), ("simulation_start", "string"),
        ("simulation_end", "string"), ("simulation_time_step", "string"), ("generation_date", "string"),
        ("generated_by", "string"), ("run_mode", "string"), ("template_name", "string"),
        ("template_version", "string"), ("data_contract_version", "string"), ("result_name", "string"),
        ("assessment_scope", "string"), ("assessment_status", "string"), ("voltage_limits", "string"),
        ("has_cases", "string"), ("chart_cases", "string"), ("radar_note", "string"),
        ("case_source_text", "string"), ("reference_text", "string"), ("qds_mode_text", "string"),
        ("coverage_statement", "string"))),
    ("ScriptedModelQuality", (
        ("check_id", "string"), ("check_name", "string"), ("status", "string"), ("message", "string"),
        ("affected_element", "string"))),
    ("ScriptedCases", (
        ("case_order", "integer"), ("case_id", "string"), ("case_name", "string"), ("is_reference", "integer"),
        ("simulation_status", "string"), ("period_text", "string"), ("priority", "integer"),
        ("equipment_name", "string"), ("assessment", "string"), ("assessment_detail", "string"),
        ("violation", "integer"), ("case_description", "string"), ("outage_names", "string"),
        ("reference_text", "string"), ("states_text", "string"), ("windows_text", "string"),
        ("coverage_text", "string"), ("provenance_text", "string"))),
    ("ScriptedCaseMetrics", (
        ("case_order", "integer"), ("case_name", "string"), ("max_line_text", "string"),
        ("max_line_element", "string"), ("coincident_delta_text", "string"), ("maxima_difference_text", "string"),
        ("violation_hours_text", "string"), ("voltage_range_text", "string"), ("coverage_text", "string"))),
    ("ScriptedKpis", (
        ("highest_text", "string"), ("highest_caption", "string"), ("highest_violation", "integer"),
        ("delta_text", "string"), ("delta_caption", "string"))),
    ("ScriptedPieLines", (("sort_order", "integer"), ("class_label", "string"), ("element_count", "integer"))),
    ("ScriptedPieTransformers", (
        ("sort_order", "integer"), ("class_label", "string"), ("element_count", "integer"))),
    ("ScriptedReferenceExceeded", (
        ("rank", "integer"), ("type_label", "string"), ("element_name", "string"), ("grid_name", "string"),
        ("max_text", "string"))),
    ("ScriptedCaseCounts", (
        ("case_order", "integer"), ("case_name", "string"), ("line_count", "integer"),
        ("transformer_count", "integer"), ("node_count", "integer"))),
    ("ScriptedRadar", (
        (("metric_order", "integer"), ("metric_label", "string"), ("note", "string"))
        + SERIES_NAME_FIELDS + SERIES_VALUE_FIELDS)),
    ("ScriptedLineLoadingBars", (
        ("rank", "integer"), ("element_name", "string"), ("max_value", "number"), ("case_name", "string"))),
    ("ScriptedTrendMostLoaded", TREND_FIELDS),
    ("ScriptedTrendLargestDelta", TREND_FIELDS),
    ("ScriptedCaseComparison", MATRIX_FIELDS),
    ("ScriptedCalculationRuns", (
        ("run_order", "integer"), ("run_id", "string"), ("run_kind", "string"), ("case_name", "string"),
        ("reference_text", "string"), ("period_text", "string"), ("time_steps", "integer"),
        ("elapsed_text", "string"), ("status", "string"), ("provenance_text", "string"), ("result_object", "string"),
        ("note", "string"))),
    ("ScriptedTopLinesByCase", MATRIX_FIELDS),
    ("ScriptedAppendixLine", MATRIX_FIELDS),
    ("ScriptedAppendixTransformer", MATRIX_FIELDS),
    ("ScriptedAppendixVoltage", MATRIX_FIELDS),
)
REQUIRED_FIELDS = {
    "ScriptedReportMeta": (
        "study_id", "study_name", "model_name", "model_version", "generation_date", "generated_by", "run_mode",
        "template_name", "template_version", "data_contract_version", "result_name", "assessment_scope",
        "assessment_status", "voltage_limits", "has_cases", "chart_cases", "case_source_text", "reference_text",
        "qds_mode_text", "coverage_statement"),
    "ScriptedModelQuality": ("check_id", "check_name", "status", "message"),
    "ScriptedCases": ("case_order", "case_id", "case_name", "is_reference", "simulation_status", "assessment",
                      "violation"),
    "ScriptedCaseMetrics": ("case_order", "case_name", "max_line_text", "coincident_delta_text",
                            "maxima_difference_text", "voltage_range_text"),
    "ScriptedKpis": ("highest_text", "highest_caption", "delta_text", "delta_caption"),
    "ScriptedPieLines": ("sort_order", "class_label", "element_count"),
    "ScriptedPieTransformers": ("sort_order", "class_label", "element_count"),
    "ScriptedReferenceExceeded": ("rank", "type_label", "element_name", "max_text"),
    "ScriptedCaseCounts": ("case_order", "case_name", "line_count", "transformer_count", "node_count"),
    "ScriptedRadar": ("metric_order", "metric_label", "s0_name"),
    "ScriptedLineLoadingBars": ("rank", "element_name", "max_value"),
    "ScriptedTrendMostLoaded": ("time_label", "timestamp", "element_name", "chart_title", "unit", "s0_name"),
    "ScriptedTrendLargestDelta": ("time_label", "timestamp", "element_name", "chart_title", "unit", "s0_name"),
    "ScriptedCaseComparison": ("block", "row_order", "element_name", "ref_text", "col_count", "violation"),
    "ScriptedCalculationRuns": ("run_order", "run_id", "run_kind", "case_name", "status"),
    "ScriptedTopLinesByCase": ("block", "row_order", "element_name", "ref_text", "col_count", "violation"),
    "ScriptedAppendixLine": ("block", "row_order", "element_name", "ref_text", "col_count", "violation"),
    "ScriptedAppendixTransformer": ("block", "row_order", "element_name", "ref_text", "col_count", "violation"),
    "ScriptedAppendixVoltage": ("block", "row_order", "element_name", "ref_text", "col_count", "violation"),
}
# One table per chart: every table below feeds exactly one chart, which reads it without a data relation.
TREND_TABLES = ("ScriptedTrendMostLoaded", "ScriptedTrendLargestDelta")

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

def object_id(obj):
    return object_name(obj)

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

def grid_in_scope(grid_name):
    """Whether equipment of this grid is assessed: the grids chosen in Settings, else GRID_NAME_FILTER."""
    grids = current_setting('monitoring_grids')
    if grids:
        return grid_name in grids
    return not GRID_NAME_FILTER or GRID_NAME_FILTER in grid_name


def grid_scope_text():
    """How the assessed equipment is chosen, for log and report."""
    grids = current_setting('monitoring_grids')
    if grids:
        return 'elements in the grid{} {}'.format('s' if len(grids) > 1 else '', ', '.join(grids))
    if GRID_NAME_FILTER:
        return 'elements in grids named *{}*'.format(GRID_NAME_FILTER)
    return 'all elements'

def element_in_scope(obj):
    return grid_in_scope(element_grid_name(obj))

def result_category(obj, variable):
    for category in CLASS_CATEGORIES.get(class_name(obj), ()):
        if variable in VARIABLES[category]:
            return category
    return None

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

def return_code(value):
    if value is None:
        return 0.0
    if isinstance(value, (tuple, list)):
        if not value:
            return None
        value = value[0]
    if isinstance(value, (tuple, list)):
        return None
    return finite_number(value)

def result_value(elmres, row, column):
    try:
        raw = elmres.GetValue(row, column)
    except Exception:
        return None
    if isinstance(raw, (tuple, list)):
        if len(raw) < 2:
            return None
        error_code = finite_number(raw[0])
        if error_code is None or error_code != 0.0:
            return None
        raw = raw[1]
    return finite_number(raw)

def normalize_time_unit(unit):
    text = str(unit or '').strip().lower().replace(' ', '')
    aliases = {'s': 's', 'sec': 's', 'second': 's', 'seconds': 's', 'min': 'min', 'minute': 'min', 'minutes': 'min', 'h': 'h', 'hr': 'h', 'hour': 'h', 'hours': 'h', 'd': 'd', 'day': 'd', 'days': 'd'}
    return aliases.get(text, text or TIME_UNIT_FALLBACK)

def time_in_hours(value, unit, row):
    numeric = finite_number(value)
    if numeric is None:
        return float(row)
    factor = {'s': 1.0 / 3600.0, 'min': 1.0 / 60.0, 'h': 1.0, 'd': 24.0}.get(normalize_time_unit(unit), 1.0)
    return numeric * factor

def format_clock(hours):
    sign = '-' if hours < 0 else ''
    total_seconds = int(round(abs(hours) * 3600.0))
    days, remainder = divmod(total_seconds, 86400)
    hour, remainder = divmod(remainder, 3600)
    minute, second = divmod(remainder, 60)
    clock = '{:02d}:{:02d}'.format(hour, minute)
    if second:
        clock += ':{:02d}'.format(second)
    if days:
        return '{}{} d {}'.format(sign, days, clock)
    return sign + clock

def is_absolute_time_axis(hours):
    """True when the axis holds absolute epoch time instead of elapsed time.

    PowerFactory 2026 reports the implicit quasi-dynamic time scale in 's'
    but fills it with absolute epoch seconds. No quasi-dynamic study spans
    the decade that separates the two interpretations.
    """
    return bool(hours) and hours[0] >= ABSOLUTE_TIME_THRESHOLD_HOURS

def format_absolute_time(hours):
    try:
        return time.strftime('%Y-%m-%d %H:%M', time.localtime(hours * 3600.0))
    except (ValueError, OverflowError, OSError):
        return format_clock(hours)

def format_time(value, row, unit):
    if isinstance(value, (tuple, list)):
        value = value[1] if len(value) >= 2 else value[0] if value else None
    if finite_number(value) is not None:
        return format_clock(time_in_hours(value, unit, row))
    if value is not None and str(value).strip():
        return str(value)
    return 'Time step {}'.format(row)

def format_time_step(hours):
    if hours < 1.0 / 60.0:
        return '{:g} s'.format(hours * 3600.0)
    if hours < 1.0:
        return '{:g} min'.format(hours * 60.0)
    if hours < 24.0:
        return '{:g} h'.format(hours)
    return '{:g} d'.format(hours / 24.0)

def time_column(elmres, column_count, row_count):
    candidates = ('b:tnow', 't', 'time')
    inspected = []
    for column in range(column_count):
        try:
            variable = str(elmres.GetVariable(column)).lower()
        except Exception:
            continue
        inspected.append(variable)
        if variable in candidates:
            return column
    for candidate in candidates:
        try:
            column = elmres.FindColumn(candidate)
            if isinstance(column, int) and column >= 0:
                return column
        except Exception:
            pass
    scale_rows = [0] if row_count == 1 else [0, row_count - 1]
    scale_values = [result_value(elmres, row, -1) for row in scale_rows]
    if all(value is not None for value in scale_values):
        if len(scale_values) == 1 or scale_values[1] > scale_values[0]:
            return -1
    variables = ', '.join(inspected) if inspected else 'unreadable'
    raise RuntimeError(
        'ElmRes exposes neither an explicit time column (b:tnow, t or time) '
        'nor a readable implicit time scale at column -1. Inspected result '
        'variables: {}.'.format(variables))

def nominal_voltage(obj):
    """Nominal voltage in kV of the element or of the terminal it connects to."""
    candidates = [obj]
    for attribute in ('bus1', 'bus2', 'bushv', 'buslv', 'busmv'):
        cubicle = safe_attr(obj, attribute)
        terminal = safe_attr(cubicle, 'cterm') if cubicle else None
        if terminal:
            candidates.append(terminal)
    for item in candidates:
        nominal = finite_number(safe_attr(item, 'uknom'))
        if nominal is not None and nominal > 0:
            return nominal
    return None

def voltage_level(obj):
    nominal = nominal_voltage(obj)
    return '{:g} kV'.format(nominal) if nominal is not None else ''

def is_dc_terminal(obj):
    """ElmTerm.systype 1 marks a DC terminal; its voltage is no AC magnitude."""
    return class_name(obj) == 'ElmTerm' and finite_number(safe_attr(obj, 'systype')) == 1.0

def read_column(elmres, column, rows):
    reader = getattr(elmres, 'GetColumnValues', None)
    if reader is not None:
        try:
            raw = reader(column)
        except Exception:
            raw = None
        if raw is not None:
            if isinstance(raw, tuple) and len(raw) == 2 and _is_sequence(raw[1]):
                code = finite_number(raw[0])
                raw = raw[1] if code == 0.0 else None
        if raw is not None:
            if not _is_sequence(raw):
                raw = None
            elif len(raw) != rows:
                raise RuntimeError('ElmRes column {} returned {} values instead of {}.'.format(column, len(raw), rows))
            else:
                return [finite_number(value) for value in raw]
    return [result_value(elmres, row, column) for row in range(rows)]

def _is_sequence(value):
    return isinstance(value, (list, tuple))

def collect_series(elmres, counters=None):
    rows = int(elmres.GetNumberOfRows())
    columns = int(elmres.GetNumberOfColumns())
    if rows <= 0:
        raise RuntimeError('ElmRes contains no result rows.')
    if columns <= 0:
        raise RuntimeError('ElmRes contains no result columns.')
    if rows > MAX_RESULT_ROWS:
        raise RuntimeError('ElmRes has {} rows and exceeds the limit of {} (MAX_RESULT_ROWS).'.format(rows, MAX_RESULT_ROWS))
    t_column = time_column(elmres, columns, rows)
    try:
        time_unit = normalize_time_unit(elmres.GetUnit(t_column))
    except Exception as exc:
        raise RuntimeError('The ElmRes time-column unit could not be read: {}'.format(exc)) from exc
    if time_unit not in {'s', 'min', 'h', 'd'}:
        raise RuntimeError('Unsupported ElmRes time-column unit: {}'.format(time_unit or TIME_UNIT_FALLBACK))
    raw_times = []
    hours = []
    for row, raw in enumerate(read_column(elmres, t_column, rows)):
        if raw is None:
            raise RuntimeError('Invalid time value in ElmRes cell ({}, {}).'.format(row, t_column))
        raw_times.append(raw)
        hours.append(time_in_hours(raw, time_unit, row))
    if any((current <= previous for previous, current in zip(hours, hours[1:]))):
        raise RuntimeError('The ElmRes time axis is not strictly increasing.')
    absolute = is_absolute_time_axis(hours)
    origin = hours[0] if absolute else None
    if absolute:
        labels = unique_time_labels(hours)
        plot_times = [value - hours[0] for value in hours]
    else:
        labels = [format_time(raw, row, time_unit) for row, raw in enumerate(raw_times)]
        plot_times = list(hours)
    chosen = {}
    out_of_scope = 0
    grids = {}
    dc_nodes = set()
    recorded = {}  # what the result object records that GridLens does not assess, for the error message
    for column in range(columns):
        try:
            obj = elmres.GetObject(column)
            variable = str(elmres.GetVariable(column))
            category = result_category(obj, variable)
        except Exception:
            continue
        if not category or variable not in VARIABLES[category]:
            if column != t_column:
                name = '{} {}'.format(class_name(obj) or 'unknown object', variable)
                recorded[name] = recorded.get(name, 0) + 1
            continue
        # Before the full path is fetched and before any value is read.
        grid_name = element_grid_name(obj)
        in_scope = grid_in_scope(grid_name)
        counted = grids.setdefault(grid_name or '(no grid)', [0, in_scope])
        counted[0] += 1
        if not in_scope:
            out_of_scope += 1
            continue
        if category == 'voltage' and is_dc_terminal(obj):
            dc_nodes.add(object_key(obj))
            continue
        key = (category, object_key(obj))
        priority = VARIABLES[category].index(variable)
        if key not in chosen or priority < chosen[key][0]:
            chosen[key] = (priority, column, obj, variable)
    if counters is not None:
        counters['out_of_scope'] = out_of_scope
        counters['grids'] = {name: tuple(value) for name, value in grids.items()}
        counters['dc_nodes'] = len(dc_nodes)
        counters['deenergized_nodes'] = 0
        counters['deenergized_steps'] = 0
        counters['dark_keys'] = set()
    if not chosen and out_of_scope:
        raise RuntimeError(
            'No result series belongs to the assessed equipment ({}; {} series were out of scope). Grids in the '
            'result: {}. Choose one of these grids in Settings -> Network scope, or clear the selection (and '
            'GRID_NAME_FILTER) to assess every element.'.format(grid_scope_text(), out_of_scope, _grid_listing(grids)))
    cells = rows * len(chosen)
    if cells > MAX_RESULT_CELLS:
        raise RuntimeError('ElmRes contains {} evaluated cells ({} rows x {} series) and exceeds the limit of {} (MAX_RESULT_CELLS).'.format(cells, rows, len(chosen), MAX_RESULT_CELLS))
    series = []
    dark_series = 0
    plot_rows = sample_rows(rows)
    energized = setting_value('energized_min_pu')
    for (_, _), (_, column, obj, variable) in sorted(chosen.items()):
        values = []
        category = result_category(obj, variable)
        dark = 0
        for row, value in enumerate(read_column(elmres, column, rows)):
            if value is None and category != 'voltage':
                raise RuntimeError('Invalid result value in ElmRes cell ({}, {}) for {} {}.'.format(row, column, object_name(obj), variable))
            if category == 'voltage' and (value is None or value < energized):
                # A node an outage cuts off is reported as 0 or as NaN: both mean
                # de-energised, no value. A loading that is not a number still stops the run.
                value = None
                dark += 1
            values.append(value)
        if counters is not None:
            counters['deenergized_steps'] += dark
        if dark == len(values):
            dark_series += 1
            if counters is not None:
                counters['deenergized_nodes'] += 1
                counters['dark_keys'].add(object_key(obj))
            continue
        try:
            unit = str(elmres.GetUnit(column) or '')
        except Exception:
            unit = ''
        if not unit:
            unit = 'p.u.' if category == 'voltage' else '%'
        nominal = nominal_voltage(obj)
        # Every time step stays available for the comparison with the
        # reference at the same instant; only the plot is sampled, and only
        # the plotted points are built as (label, time, value) tuples.
        array_values = value_array(values)
        series.append({'category': category, 'object': obj, 'key': object_key(obj), 'element_id': object_id(obj), 'element_name': object_name(obj), 'voltage_level': voltage_level(obj), 'nominal_kv': nominal, 'limits': voltage_band(nominal) if category == 'voltage' else None, 'variable_id': variable, 'variable': 'Voltage magnitude' if category == 'voltage' else 'Loading', 'unit': unit,
                       'points': [(labels[row], plot_times[row], values[row]) for row in plot_rows],
                       'statistics': array_statistics(array_values, labels), 'values': array_values})
    if not series:
        raise RuntimeError(missing_series_message(recorded, dark_series))
    return (series, labels, plot_times, time_unit, absolute, origin)


def missing_series_message(recorded, dark_series=0):
    """Why a result object yields nothing to assess, and what the engineer can do about it."""
    needed = ('the loading of lines and transformers (c:loading or m:loading) and the voltage of terminals '
              '(m:u or m:u1)')
    if dark_series:
        return ('The result object has no usable result: all {} recorded terminal voltages are 0 or not a number '
                '(de-energised) and no line or transformer loading is recorded. GridLens needs {}. Check the study '
                'case and the network state of the quasi-dynamic simulation.'.format(dark_series, needed))
    ordered = sorted(recorded.items(), key=lambda entry: (-entry[1], entry[0]))
    found = ', '.join('{} ({} column{})'.format(name, count, '' if count == 1 else 's') for name, count in ordered[:8])
    if len(ordered) > 8:
        found += ' and {} more'.format(len(ordered) - 8)
    return ('The result object records none of the results GridLens assesses. GridLens needs {}. Recorded are: {}. '
            'Add these variables to the result variables of the quasi-dynamic simulation (ComStatsim, '
            '"Result Variables") or choose a study case that records them, then run GridLens again.'.format(
                needed, found or 'no result variables at all'))

def _grid_listing(grids):
    ordered = sorted(grids.items(), key=lambda entry: (-entry[1][0], entry[0]))
    return '; '.join('{!r} ({} series)'.format(name, value[0]) for name, value in ordered[:8]) or 'none'

def check_run_budget(results):
    """Cells held in memory; a reused case shares its source's data and costs nothing."""
    cells = 0
    for result in results:
        if str(result.get('provenance', '')).startswith('REUSED'):
            continue
        rows = len(result['labels'])
        for category in result['by_category']:
            cells += rows * len(result['by_category'][category])
    if cells > MAX_RUN_CELLS:
        raise GridLensError('The run contains {} result cells across {} cases and exceeds the limit of {} (MAX_RUN_CELLS). Reduce cases, time range or model scope.'.format(cells, len(results), MAX_RUN_CELLS))
    return cells

def sampled_plot_points(item):
    """Every point up to MAX_PLOT_POINTS, otherwise an evenly spaced grid.

    The grid depends only on the number of points, so REF and OUTAGE on the
    same time axis are sampled at identical times. Per-series extremes are not
    added: they differ between the cases and gave the two lines different
    axes. Exact extremes remain in the statistics.
    """
    points = item['points']
    if len(points) <= setting_value('max_plot_points'):
        return points
    return [points[index] for index in sample_rows(len(points))]

def sample_rows(count):
    """Row indices of the plot: all up to MAX_PLOT_POINTS, otherwise a grid that depends only on `count`."""
    limit = setting_value('max_plot_points')
    if count <= limit:
        return list(range(count))
    return sorted({int(round(sample * (count - 1) / float(max(limit - 1, 1)))) for sample in range(limit)})

def unique_time_labels(hours):
    """Calendar labels; where a clock change repeats a local time, with the UTC offset."""
    labels = [format_absolute_time(value) for value in hours]
    if len(set(labels)) == len(labels):
        return labels
    try:
        return [time.strftime('%Y-%m-%d %H:%M %z', time.localtime(value * 3600.0)) for value in hours]
    except (ValueError, OverflowError, OSError):
        return ['{} #{}'.format(label, row) for row, label in enumerate(labels)]

# A missing value (de-energised node) inside a value array. -inf compares equal
# to itself, so two identical arrays compare equal at C speed; no measured
# value can be -inf because finite_number rejects it.
MISSING = float('-inf')

def value_array(values):
    return array('d', (MISSING if value is None else value for value in values))

def array_value(values, row):
    value = values[row]
    return None if value == MISSING else value

def merge_intervals(intervals):
    """Sorted, non-overlapping union of half-open (start, end) intervals."""
    merged = []
    for start, end in sorted(interval for interval in intervals if interval[1] > interval[0]):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged

def window_rows(hours, windows):
    """Rows whose time lies in at least one half-open window [start, end).

    `hours` is the absolute axis in hours, windows are epoch seconds. A side
    PowerFactory does not expose (None) is open towards that end of the axis.
    """
    rows = set()
    for start, end in windows:
        lo = 0 if start is None else bisect.bisect_left(hours, start / 3600.0)
        hi = len(hours) if end is None else bisect.bisect_left(hours, end / 3600.0)
        rows.update(range(lo, hi))
    return sorted(rows)

def row_steps(hours):
    """Duration in hours each time step stands for: up to the next step; the last repeats the one before."""
    steps = [later - earlier for earlier, later in zip(hours, hours[1:])]
    return steps + steps[-1:] if steps else [0.0]

def window_coverage(hours, steps, windows):
    """Share of the window time that result rows stand for; None for an empty or unknown window."""
    known = [(start, end) for start, end in windows if start is not None and end is not None]
    if len(known) != len(windows):
        return None
    union = merge_intervals([(start / 3600.0, end / 3600.0) for start, end in known])
    total = sum(end - start for start, end in union)
    if total <= 0:
        return None
    covered = 0.0
    for start, end in union:
        lo = bisect.bisect_left(hours, start)
        hi = bisect.bisect_left(hours, end)
        for row in range(lo, hi):
            covered += max(0.0, min(steps[row], end - hours[row]))
    return min(1.0, covered / total)

def row_statistics(values, labels, rows):
    """min, max, mean and their times over the given rows; None without a value."""
    chunk = [(labels[row], values[row]) for row in rows if values[row] != MISSING]
    if not chunk:
        return None
    minimum = min(value for _, value in chunk)
    maximum = max(value for _, value in chunk)
    return {'min': minimum, 'max': maximum, 'mean': sum(value for _, value in chunk) / len(chunk),
            'time_min': next(label for label, value in chunk if value == minimum),
            'time_max': next(label for label, value in chunk if value == maximum)}

def statistics(series):
    points = [(label, value) for label, _, value in series['points'] if value is not None]
    if not points:
        return None
    values = [value for _, value in points]
    minimum = min(values)
    maximum = max(values)
    return {'min': minimum, 'max': maximum, 'mean': sum(values) / len(values), 'time_min': next((label for label, value in points if value == minimum)), 'time_max': next((label for label, value in points if value == maximum))}

def array_statistics(values, labels):
    """statistics() of a value array: the same numbers and first times of the extremes, at C speed."""
    present = [value for value in values if value != MISSING]
    if not present:
        return None
    minimum = min(present)
    maximum = max(present)
    return {'min': minimum, 'max': maximum, 'mean': sum(present) / len(present),
            'time_min': labels[values.index(minimum)], 'time_max': labels[values.index(maximum)]}

def format_limit(value):
    return '{:g}'.format(value)

def has_time_variation(item):
    stats = item.get('statistics')
    if stats is not None:
        spread = stats['max'] - stats['min']
    else:
        values = [value for _, _, value in item['points'] if value is not None]
        if len(values) < 2:
            return False
        spread = max(values) - min(values)
    tolerance = {'line': 0.1, 'transformer': 0.1, 'voltage': 0.001}.get(item['category'], 1e-06)
    return spread > tolerance

def empty_payload():
    return {name: [] for name, _ in TABLES}

def voltage_band(nominal_kv=None):
    """Permitted voltage in p.u. of the nominal voltage (lower, upper): one band for every voltage level."""
    return default_voltage_limits()

def voltage_limits(item):
    return item.get('limits') or default_voltage_limits()

def is_critical(item, stats):
    if stats is None:
        return False
    if item['category'] in ('line', 'transformer'):
        return stats['max'] > loading_limit(item['category'])
    if item['category'] == 'voltage':
        lower, upper = voltage_limits(item)
        return stats['min'] < lower or stats['max'] > upper
    return False


# ---------------------------------------------------------------------------
# Settings: limits, restrictions and classification parameters
#
# Category A (evaluation) only interprets calculated results and never
# changes a load flow. Category B (calculation) would change what PowerFactory
# calculates; it stays read only until its PowerFactory interface is verified
# (tools/probe_contingency.py). Only overrides are stored, in the case
# configuration under 'settings'. That JSON file is a provisional store until
# a native storage inside the PowerFactory project is verified.
# ---------------------------------------------------------------------------
SETTINGS_VERSION = '1.0'
SOURCE_GRIDLENS, SOURCE_POWERFACTORY, SOURCE_USER = 'GridLens', 'PowerFactory', 'user'
CATEGORY_EVALUATION, CATEGORY_CALCULATION = 'A', 'B'
N1_LIMITS_POWERFACTORY, N1_LIMITS_GLOBAL = 'powerfactory', 'global'
N1_LIMIT_CHOICES = ((N1_LIMITS_POWERFACTORY, 'use PowerFactory limits'), (N1_LIMITS_GLOBAL, 'global assessment limit'))
ON_OFF_CHOICES = ((True, 'on'), (False, 'off'))
# Upper bounds of the count settings: beyond them a run takes hours or the report gets unreadable.
COUNT_LIMITS = {'top_n': 50, 'max_plot_points': 2000, 'max_n1_times': 20000, 'max_cases': 20}
NOT_VERIFIED = 'not verified yet'
PART3_NOTE = ('Read only: set in the contingency analysis (ComSimoutage) of the study case; GridLens reads it '
              'and does not change it.')
# A floating-point result that lies this close to a limit is treated as on the limit: PowerFactory writes
# results in single or double precision, and 1e-9 is far below any meaningful %-point or p.u. difference.
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
SETTING_SECTIONS = ('Network scope', 'Thermal limits', 'Voltage limits', 'Classification', 'Report', 'Run',
                    'Contingency analysis')
SAME_AS_ASSESSMENT = 'same grids as the assessed equipment'
# (lower, upper) pairs that must keep lower < upper; (warning, limit) pairs that must keep warning <= limit.
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


def settings_snapshot(overrides=None):
    """The immutable record of the settings one run uses: values, sources, overrides and versions.

    It is built once at the start of a run, after the case manager has closed;
    later changes in the window cannot change what a published result meant.
    """
    overrides = dict(overrides or {})
    values = effective_settings(overrides)
    return {'settings_version': SETTINGS_VERSION, 'classification_version': CLASSIFICATION_VERSION,
            'values': values, 'sources': {key: setting_source(key, overrides) for key in values},
            'overrides': clean_overrides(dict((key, values[key]) for key in overrides)),
            'calculation_parameters': {setting['key']: NOT_VERIFIED if not setting['editable'] else
                                       setting_text(setting['key'], values[setting['key']]) + ' (stored, not applied yet)'
                                       for setting in SETTINGS if setting['category'] == CATEGORY_CALCULATION},
            'storage': 'provisional: case configuration file (JSON); native PowerFactory storage not verified yet'}


# The settings of the running assessment; None means the GridLens defaults.
_ACTIVE_SETTINGS = None


def activate_settings(overrides=None):
    """Use these settings for the assessment that follows; returns the snapshot."""
    global _ACTIVE_SETTINGS
    snapshot = settings_snapshot(overrides)
    _ACTIVE_SETTINGS = dict(snapshot['values'])
    return snapshot


def reset_settings():
    global _ACTIVE_SETTINGS
    _ACTIVE_SETTINGS = None


def active_overrides():
    """The overrides of the active settings; {} with the GridLens defaults."""
    return clean_overrides(_ACTIVE_SETTINGS or {})


# Settings whose default is a script constant: setting_value() reads the user override, else the constant.
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


def current_setting(key):
    if _ACTIVE_SETTINGS is not None and key in _ACTIVE_SETTINGS:
        return _ACTIVE_SETTINGS[key]
    return SETTINGS_BY_KEY[key]['default']


def loading_limit(category):
    return current_setting('transformer_limit' if category == 'transformer' else 'line_limit')


def loading_warning(category):
    return current_setting('transformer_warning' if category == 'transformer' else 'line_warning')


def default_voltage_limits():
    return current_setting('voltage_min_pu'), current_setting('voltage_max_pu')


def change_tolerance(category):
    """The n-0 change tolerance: %-points for loading, p.u. for voltage."""
    return current_setting('voltage_change_tolerance' if category == 'voltage' else 'loading_change_tolerance')


def loading_limits_text():
    line, transformer = loading_limit('line'), loading_limit('transformer')
    if line == transformer:
        return 'Violation when loading > {} %.'.format(format_limit(line))
    return 'Violation when loading > {} % (lines) or > {} % (transformers).'.format(format_limit(line), format_limit(transformer))


# ---------------------------------------------------------------------------
# Classification of n-1 against (n-1)', version CLASSIFICATION_VERSION
#
# One pure function for every scenario. It compares the n-1 reference with
# the planned-outage scenario (n-1)' for the same time step, contingency,
# monitored element, quantity, post-fault phase and limit definition. The
# n-0 QDS keeps its own statuses (step_status: PRE-EXISTING, DE-ENERGISED);
# nothing here changes them. Codes are GridLens codes, not PowerFactory values.
# ---------------------------------------------------------------------------
CLASSIFICATION_VERSION = '1.0'
CLASSIFICATION_STATUSES = ((0, 'OK'), (1, 'NEW'), (2, 'WORSENED'), (3, 'PRE_EXISTING'), (4, 'IMPROVED'),
                           (5, 'RESOLVED'), (90, 'FAILED'), (91, 'NOT_EVALUATED'), (92, 'NOT_APPLICABLE'),
                           (93, 'NOT_COMPARABLE'))
CLASSIFICATION_CODES = {status: code for code, status in CLASSIFICATION_STATUSES}
INDICATOR_MARGIN_REDUCED = 'MARGIN_REDUCED'
# What must be identical for a comparison; 'limit' is compared separately.
COMPARISON_IDENTITY = ('time', 'contingency', 'element', 'quantity', 'phase')
STATE_OK, STATE_FAILED, STATE_NOT_APPLICABLE = 'ok', 'failed', 'not_applicable'
QUANTITIES = ('loading', 'voltage')


def classification_parameters(values=None):
    """The tolerances of the classification, from the given or the active settings."""
    read = (lambda key: values[key]) if values is not None else current_setting
    parameters = {quantity: {'limit': read('limit_tolerance_' + quantity), 'worsened': read('worsened_tolerance_' + quantity),
                             'improved': read('improved_tolerance_' + quantity)} for quantity in QUANTITIES}
    parameters.update(numeric=read('numeric_tolerance'), margin_warning_loading=read('margin_warning_loading'))
    return parameters


def comparison_limit(quantity, category='line', minimum=None, maximum=None, values=None):
    """The limit definition both sides of a comparison must share.

    Loading uses the n-1 limit setting: 'use PowerFactory limits' means 100 %
    of the rating PowerFactory relates the loading to (whether that is the
    post-fault rating is still to be verified); a global assessment limit is
    a value of its own. Voltage takes the band of the element.
    """
    read = (lambda key: values[key]) if values is not None else current_setting
    if quantity == 'loading':
        if read('n1_limit_mode') == N1_LIMITS_GLOBAL:
            return {'quantity': 'loading', 'max': float(read('n1_limit_global')), 'source': 'GridLens global assessment limit'}
        return {'quantity': 'loading', 'max': 100.0, 'source': 'PowerFactory rating (100 % loading)'}
    return {'quantity': 'voltage', 'min': minimum, 'max': maximum, 'source': 'voltage band of the element'}


def _measured(value):
    """A finite number, or None: NaN, infinity, None, booleans and texts are no measured value."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) else None


def violation_size(quantity, value, limit):
    """V_L = max(0, L - L_lim) for loading, V_U = max(0, U_min - U, U - U_max) for voltage; None if not computable."""
    value = _measured(value)
    if value is None or not isinstance(limit, dict):
        return None
    upper = _measured(limit.get('max'))
    if quantity == 'loading':
        return None if upper is None else max(0.0, value - upper)
    lower = _measured(limit.get('min'))
    if lower is None or upper is None or lower >= upper:
        return None
    return max(0.0, lower - value, value - upper)


def _reserve(quantity, value, limit):
    if quantity == 'loading':
        return limit['max'] - value
    return min(value - limit['min'], limit['max'] - value)


def classify_comparison(reference, scenario, parameters=None):
    """Classify one n-1 result against the (n-1)' result of a planned-outage scenario.

    `reference` and `scenario` are dicts with 'state' ('ok', 'failed' or
    'not_applicable'; default 'ok'), 'value', 'limit' (comparison_limit()),
    the identity fields COMPARISON_IDENTITY and an optional 'reason'.
    Returns one main status with its code, the indicators, every reason
    found, the coincident delta (scenario - reference, same time step) and
    both violation sizes.

    Decision order (CLASSIFICATION_VERSION 1.0):
    1. a failed calculation on either side       -> FAILED
    2. the contingency is not applicable          -> NOT_APPLICABLE
    3. identity or limit definition differs       -> NOT_COMPARABLE
    4. a value or the limit is missing or invalid -> NOT_EVALUATED
    5. the violation sizes V of both sides decide:
       violated when V > limit tolerance + numeric tolerance;
       NEW, RESOLVED or OK when only one or neither side is violated;
       both violated: WORSENED when V_s - V_r > worsened tolerance + numeric,
       IMPROVED when V_r - V_s > improved tolerance + numeric, else PRE_EXISTING.
    Every non-numeric finding is kept in 'reasons', so the precedence never
    hides a second cause. MARGIN_REDUCED marks an OK result whose reserve
    to the limit shrank by more than the worsened tolerance; for loading only
    from the reduced-margin warning on. It is an indicator, never a status.
    Missing values are never replaced by zero.
    """
    parameters = parameters or classification_parameters()
    reference, scenario = dict(reference or {}), dict(scenario or {})
    reasons = []
    found = set()
    for side, label in ((reference, 'n-1 reference'), (scenario, "(n-1)' scenario")):
        state = side.get('state', STATE_OK)
        if state == STATE_FAILED:
            found.add('FAILED')
            reasons.append('{}: calculation failed{}'.format(label, ': ' + side['reason'] if side.get('reason') else ''))
        elif state == STATE_NOT_APPLICABLE:
            found.add('NOT_APPLICABLE')
            reasons.append('{}: contingency not applicable{}'.format(label, ': ' + side['reason'] if side.get('reason') else ''))
        elif state != STATE_OK:
            found.add('NOT_EVALUATED')
            reasons.append('{}: unknown calculation state {!r}'.format(label, state))
    different = [field for field in COMPARISON_IDENTITY if reference.get(field) != scenario.get(field)]
    if different:
        found.add('NOT_COMPARABLE')
        reasons.append('different {}'.format(', '.join(different)))
    quantity = scenario.get('quantity')
    if quantity not in QUANTITIES:
        found.add('NOT_COMPARABLE')
        reasons.append('unknown quantity {!r}'.format(quantity))
    elif reference.get('limit') != scenario.get('limit'):
        found.add('NOT_COMPARABLE')
        reasons.append('different limit definitions')
    sizes = {}
    for side, label, name in ((reference, 'n-1 reference', 'reference'), (scenario, "(n-1)' scenario", 'scenario')):
        if side.get('state', STATE_OK) != STATE_OK:
            continue
        if _measured(side.get('value')) is None:
            found.add('NOT_EVALUATED')
            reasons.append('{}: no valid value ({!r})'.format(label, side.get('value')))
        elif quantity in QUANTITIES:
            sizes[name] = violation_size(quantity, side['value'], side.get('limit'))
            if sizes[name] is None:
                found.add('NOT_EVALUATED')
                reasons.append('{}: limit definition missing or invalid'.format(label))
    result = {'classification_version': CLASSIFICATION_VERSION, 'indicators': [], 'reasons': reasons,
              'delta': None, 'reference_violation': sizes.get('reference'), 'scenario_violation': sizes.get('scenario'),
              'identity': {field: scenario.get(field) for field in COMPARISON_IDENTITY}, 'limit': scenario.get('limit')}
    for status in ('FAILED', 'NOT_APPLICABLE', 'NOT_COMPARABLE', 'NOT_EVALUATED'):
        if status in found:
            return dict(result, status=status, code=CLASSIFICATION_CODES[status])
    tolerance = parameters[quantity]
    numeric = parameters['numeric']
    in_reference = sizes['reference'] > tolerance['limit'] + numeric
    in_scenario = sizes['scenario'] > tolerance['limit'] + numeric
    result['delta'] = float(scenario['value']) - float(reference['value'])
    change = sizes['scenario'] - sizes['reference']
    if in_scenario and not in_reference:
        status = 'NEW'
    elif in_scenario:
        status = ('WORSENED' if change > tolerance['worsened'] + numeric else
                  'IMPROVED' if -change > tolerance['improved'] + numeric else 'PRE_EXISTING')
    elif in_reference:
        status = 'RESOLVED'
    else:
        status = 'OK'
        limit = scenario['limit']
        shrink = _reserve(quantity, float(reference['value']), limit) - _reserve(quantity, float(scenario['value']), limit)
        high = quantity != 'loading' or float(scenario['value']) >= parameters['margin_warning_loading']
        if shrink > tolerance['worsened'] + numeric and high:
            result['indicators'].append(INDICATOR_MARGIN_REDUCED)
    return dict(result, status=status, code=CLASSIFICATION_CODES[status])


# ---------------------------------------------------------------------------
# n-1 and (n-1)' with the native contingency analysis (part 3)
#
# Verified on a project copy (tools/test_contingency.py, 23 October 2026):
# ComSimoutage.Execute() runs the time sweep; the written studyTime vector
# (bIgnoreTime 0) decides the study times, also non-contiguous ones;
# p_rescnt holds one ElmRes per study time (cnttime) with one row per
# contingency (GetObjectValue -> ComOutage) and one column per element and
# variable; GetValue code 3 means "not written, inside the recording limits".
# isPlannedOutages applies every planned outage that is not Ignored and whose
# window contains the study time, per study time; a contingency whose
# equipment such an outage already switches off has no row (NOT_APPLICABLE).
# ComOutage.outserv ("Not analysed") removes a contingency.
# ---------------------------------------------------------------------------
N1_COMMAND_CLASS = 'ComSimoutage'
N1_PLANNED_OPTION = 'isPlannedOutages'
N1_TIMES_ATTRIBUTE, N1_IGNORE_ATTRIBUTE = 'studyTime', 'bIgnoreTime'
N1_RESULT_ATTRIBUTE = 'p_rescnt'
N1_VARIABLES = {'loading': ('c:loading',), 'voltage': ('m:u',)}
# Recording limits of the ComSimoutage: below loadmax, and inside vlmin..vlmax, nothing is written (code 3).
N1_RECORDING_LIMITS = {'loading': ('loadmax',), 'voltage': ('vlmin', 'vlmax')}
CODE_NOT_RECORDED = 3
STATE_NOT_RECORDED = 'not_recorded'
# ComStatsim stepUnit: 0 seconds, 1 minutes, 2 hours, 3 days.
STEP_UNIT_SECONDS = {0: 1.0, 1: 60.0, 2: 3600.0, 3: 86400.0}
# Severity of the n-1 statuses for the worst status of an element; the codes stay those of the classification.
N1_SEVERITY = ('NEW', 'WORSENED', 'FAILED', 'NOT_EVALUATED', 'NOT_COMPARABLE', 'PRE_EXISTING', 'IMPROVED',
               'RESOLVED', 'NOT_APPLICABLE', 'OK')


def qds_grid(qds):
    """(start, end, step) of the ComStatsim time grid in epoch seconds, or None when it is not readable."""
    start, end = qds_period(qds)
    size = finite_number(safe_attr(qds, 'stepSize'))
    unit = finite_number(safe_attr(qds, 'stepUnit'))
    if start is None or size is None or unit is None or int(unit) not in STEP_UNIT_SECONDS:
        return None
    step = size * STEP_UNIT_SECONDS[int(unit)]
    return (start, end, step) if step > 0 else None


def n1_study_times(windows, grid, limit=None):
    """The QDS steps that lie in at least one window [begin, end), inside the QDS period; sorted.

    A window that is not known (None) covers the whole QDS period, as for the
    n-0 assessment. More than `limit` study times raise GridLensError: the
    sweep would calculate every contingency at every one of them.
    """
    start, end, step = grid
    limit = setting_value('max_n1_times') if limit is None else limit
    times = set()
    for begin, finish in windows:
        begin = start if begin is None else max(begin, start)
        finish = end + step if finish is None else finish
        index = max(0, math.ceil((begin - start) / step - 1e-9))
        moment = start + index * step
        while moment < finish and moment <= end + 1e-6:
            times.add(moment)
            if len(times) > limit:
                raise GridLensError(
                    "The n-1 time sweep would need more than {} study times; every one calculates every "
                    "contingency. Shorten the outage windows or the QDS period.".format(limit))
            index += 1
            moment = start + index * step
    return sorted(times)


def _recording_limits(command):
    """The recording limits of the contingency analysis, None where not readable."""
    found = {}
    for quantity, attributes in N1_RECORDING_LIMITS.items():
        values = [finite_number(safe_attr(command, attribute)) for attribute in attributes]
        found[quantity] = None if any(value is None for value in values) else tuple(values)
    return found


def read_n1_results(command, in_scope=element_in_scope):
    """{study time: {(contingency key, element key, quantity): value or None}} plus the element and contingency names.

    None marks code 3, a value inside the recording limits. Only the
    variables of N1_VARIABLES of elements in scope are read; a value that is
    neither written nor marked code 3 is left out (no artificial zero).
    """
    found = {'times': {}, 'elements': {}, 'contingencies': {}, 'categories': {}, 'nominal_kv': {}}
    result = safe_attr(command, N1_RESULT_ATTRIBUTE)
    subs = [item for item in (_contents(result, '*.ElmRes') if result is not None else []) if class_name(item) == 'ElmRes']
    wanted = {variable: quantity for quantity, variables in N1_VARIABLES.items() for variable in variables}
    for sub in subs:
        moment = finite_number(safe_attr(sub, 'cnttime'))
        if moment is None:
            continue
        values = found['times'].setdefault(moment, {})
        try:
            sub.Load()
            columns = []
            for column in range(int(sub.GetNumberOfColumns())):
                obj = sub.GetObject(column)
                quantity = wanted.get(str(sub.GetVariable(column)))
                if obj is None or quantity is None or not in_scope(obj):
                    continue
                key = object_key(obj)
                category = 'voltage' if quantity == 'voltage' else (CLASS_CATEGORIES.get(class_name(obj)) or ('line',))[0]
                found['elements'][key] = object_name(obj)
                found['categories'][key] = category
                if quantity == 'voltage':
                    found['nominal_kv'][key] = finite_number(safe_attr(obj, 'uknom'))
                columns.append((column, key, quantity))
            for row in range(int(sub.GetNumberOfRows())):
                code, outage = _status_pair(sub.GetObjectValue(row))
                if code != 0 or outage is None:
                    continue
                contingency = object_key(outage)
                found['contingencies'][contingency] = object_name(outage)
                for column, key, quantity in columns:
                    code, value = _status_pair(sub.GetValue(row, column))
                    if code == 0 and finite_number(value) is not None:
                        values[(contingency, key, quantity)] = finite_number(value)
                    elif code == CODE_NOT_RECORDED:
                        values[(contingency, key, quantity)] = None
        finally:
            try:
                sub.Release()
            except Exception:
                pass
    found['recording_limits'] = _recording_limits(command)
    return found


def _contents(obj, pattern):
    try:
        return list(obj.GetContents(pattern) or [])
    except Exception:
        return []


def _status_pair(returned):
    """(code, value) of a PowerFactory [error, value] return, else (None, None)."""
    if isinstance(returned, (list, tuple)) and len(returned) >= 2:
        code = finite_number(returned[0])
        return (None if code is None else int(code)), returned[1]
    return None, None


def n1_limit(quantity, category, nominal_kv=None):
    """The limit definition of an element for the n-1 comparison."""
    if quantity == 'loading':
        return comparison_limit('loading', category)
    lower, upper = voltage_band(nominal_kv)
    return comparison_limit('voltage', minimum=lower, maximum=upper)


def _proves_within(quantity, bound, limit, parameters):
    """Whether a value inside the recording limits is certainly no violation of `limit`."""
    if bound is None or not isinstance(limit, dict):
        return False
    margin = parameters[quantity]['limit'] + parameters['numeric']
    if quantity == 'loading':
        return bound[0] <= limit['max'] + margin
    return bound[0] >= limit['min'] - margin and bound[1] <= limit['max'] + margin


def classify_n1(reference, scenario, parameters=None, recording=None):
    """classify_comparison() for n-1 results, where a side may hold no value because it lay inside the recording limits.

    A side with state STATE_NOT_RECORDED is no violation when the recording
    limit proves it (recording limit not above the assessment limit); then
    NEW, RESOLVED or OK follow without a delta. When the recording limit does
    not prove it, the result is NOT_EVALUATED: the value is unknown.
    """
    parameters = parameters or classification_parameters()
    reference, scenario = dict(reference or {}), dict(scenario or {})
    unrecorded = [side for side in (reference, scenario) if side.get('state') == STATE_NOT_RECORDED]
    if not unrecorded:
        return classify_comparison(reference, scenario, parameters)
    quantity, limit = scenario.get('quantity'), scenario.get('limit')
    bound = (recording or {}).get(quantity)
    base = {'classification_version': CLASSIFICATION_VERSION, 'indicators': [], 'delta': None,
            'identity': {field: scenario.get(field) for field in COMPARISON_IDENTITY}, 'limit': limit,
            'reference_violation': None, 'scenario_violation': None}
    probe = [dict(side, state=STATE_OK, value=0.0 if quantity == 'loading' else 1.0) if side.get('state') == STATE_NOT_RECORDED
             else side for side in (reference, scenario)]
    checked = classify_comparison(probe[0], probe[1], parameters)
    if checked['status'] in ('FAILED', 'NOT_APPLICABLE', 'NOT_COMPARABLE'):
        return checked
    if not _proves_within(quantity, bound, limit, parameters):
        return dict(base, status='NOT_EVALUATED', code=CLASSIFICATION_CODES['NOT_EVALUATED'],
                    reasons=['inside the recording limits of the contingency analysis, which do not prove the value '
                             'within the assessment limit'])
    sizes = []
    for side in (reference, scenario):
        if side.get('state') == STATE_NOT_RECORDED:
            sizes.append(0.0)
        else:
            size = violation_size(quantity, side.get('value'), side.get('limit'))
            if size is None:
                return dict(base, status='NOT_EVALUATED', code=CLASSIFICATION_CODES['NOT_EVALUATED'],
                            reasons=['no valid value ({!r})'.format(side.get('value'))])
            sizes.append(size)
    threshold = parameters[quantity]['limit'] + parameters['numeric']
    in_reference, in_scenario = sizes[0] > threshold, sizes[1] > threshold
    status = 'NEW' if in_scenario and not in_reference else 'RESOLVED' if in_reference and not in_scenario else (
        'PRE_EXISTING' if in_scenario else 'OK')
    return dict(base, status=status, code=CLASSIFICATION_CODES[status], reference_violation=sizes[0],
                scenario_violation=sizes[1], reasons=['a value inside the recording limits has no exact delta'])


def _n1_side(values, moment, contingency, element, quantity, limit, applicable=True):
    identity = {'time': moment, 'contingency': contingency, 'element': element, 'quantity': quantity, 'phase': 'post-fault'}
    if not applicable:
        return dict(identity, state=STATE_NOT_APPLICABLE, limit=limit,
                    reason='the planned outages of the case already switch off its equipment')
    key = (contingency, element, quantity)
    if key not in values:
        return dict(identity, state=STATE_FAILED, limit=limit, reason='no result row for this contingency')
    if values[key] is None:
        return dict(identity, state=STATE_NOT_RECORDED, limit=limit)
    return dict(identity, state=STATE_OK, value=values[key], limit=limit)


def compare_n1(reference, scenario, switched_off=(), contingency_elements=None, parameters=None):
    """Classify (n-1)' against n-1 for every study time, contingency, element and quantity of the reference.

    `contingency_elements` maps a contingency key to the keys of its
    equipment; a contingency missing in the scenario whose equipment lies in
    `switched_off` (the components of the case's planned outages) is
    NOT_APPLICABLE, any other missing one FAILED. Elements the case switches
    off are left out. Returns the per-element worst result and counts.
    """
    parameters = parameters or classification_parameters()
    switched_off = set(switched_off)
    contingency_elements = contingency_elements or {}
    elements = {}
    counts = {}
    for moment, ref_values in sorted(reference['times'].items()):
        case_values = scenario['times'].get(moment)
        present = {key[0] for key in (case_values or {})}
        for (contingency, element, quantity) in ref_values:
            if element in switched_off:
                continue
            category = reference['categories'].get(element, 'line')
            limit = n1_limit(quantity, category, reference['nominal_kv'].get(element))
            ref_side = _n1_side(ref_values, moment, contingency, element, quantity, limit)
            if case_values is None:
                case_side = dict(ref_side, state=STATE_FAILED, reason='the study time was not calculated')
            else:
                applicable = contingency in present or not (contingency_elements.get(contingency, set()) & switched_off)
                case_side = _n1_side(case_values, moment, contingency, element, quantity, limit, applicable)
            outcome = classify_n1(ref_side, case_side, parameters, scenario.get('recording_limits'))
            counts[outcome['status']] = counts.get(outcome['status'], 0) + 1
            entry = elements.setdefault((element, quantity), {'element': element, 'quantity': quantity,
                                                              'name': reference['elements'].get(element, element),
                                                              'worst': None})
            worst = entry['worst']
            if worst is None or N1_SEVERITY.index(outcome['status']) < N1_SEVERITY.index(worst['status']) or (
                    outcome['status'] == worst['status'] and (outcome['delta'] or 0.0) > (worst['delta'] or 0.0)):
                entry['worst'] = dict(outcome, contingency_name=reference['contingencies'].get(contingency, contingency))
    return {'elements': elements, 'counts': counts}


def n1_summary(comparison):
    """'NEW 2, WORSENED 1, OK 140' style text of the classification counts, most severe first."""
    counts = comparison['counts']
    return ', '.join('{} {}'.format(status, counts[status]) for status in N1_SEVERITY if counts.get(status)) or 'nothing compared'


REFERENCE_ID = 'REF'
CONVERGED = 'CONVERGED'
AXIS_MISMATCH = 'NOT EVALUATED'
CASE_FAILED = 'FAILED'
DELTA_KEYS = (('ref_min', 'delta_min', 'min'), ('ref_max', 'delta_max', 'max'), ('ref_mean', 'delta_mean', 'mean'))

def case_result(case, series, labels, plot_times, time_unit):
    by_category = {category: [] for category in VARIABLES}
    stats_by_key = {}
    item_by_key = {}
    for item in series:
        stats = dict(item.get('statistics') or statistics(item))
        for reference_key, delta_key, _ in DELTA_KEYS:
            stats[reference_key] = None
            stats[delta_key] = None
        by_category[item['category']].append((item, stats))
        stats_by_key[item['category'], item['key']] = stats
        item_by_key[item['category'], item['key']] = item
    return {'id': case['id'], 'name': case['name'], 'kind': case.get('kind', 'case'), 'description': case.get('description', ''),
            'status': case.get('status', CONVERGED), 'error_code': case.get('error_code'), 'message': case.get('message', ''),
            'counters': dict(case.get('counters') or {}), 'is_reference': 1 if case['id'] == REFERENCE_ID else 0,
            'labels': list(labels), 'plot_times': list(plot_times), 'hours': list(case.get('hours') or plot_times),
            'absolute': bool(case.get('absolute')), 'time_unit': time_unit, 'by_category': by_category,
            'stats_by_key': stats_by_key, 'item_by_key': item_by_key, 'plan': case.get('plan'),
            'comparison': None, 'assessment': None, 'provenance': case.get('provenance', 'CALCULATED'),
            'elapsed': case.get('elapsed'), 'result_object': case.get('result_object', '')}

def failed_case(case, message):
    """A case that produced no usable result; it stays in the report with its reason."""
    result = case_result(dict(case, status=CASE_FAILED, error_code=-1, message=message), [], [], [], '')
    return result

def find_reference(results, reference_id=REFERENCE_ID):
    for result in results:
        if result['id'] == reference_id and result['status'] == CONVERGED:
            return result
    return None

def _same_time_axis(anchor, result):
    if anchor['time_unit'] != result['time_unit']:
        return False
    if anchor['labels'] != result['labels']:
        return False
    left = anchor['plot_times']
    right = result['plot_times']
    return len(left) == len(right) and all((abs(a - b) <= 1e-09 for a, b in zip(left, right)))

def enforce_common_time_axis(results, reference_id=REFERENCE_ID):
    """Whole-period tables put cases side by side, so every case needs the reference axis."""
    ok = converged(results)
    if len(ok) < 2:
        return results
    anchor = find_reference(results, reference_id) or ok[0]
    for result in ok:
        if result is anchor or _same_time_axis(anchor, result):
            continue
        result['status'] = AXIS_MISMATCH
        result['error_code'] = -4
        result['message'] = 'Time axis differs from case {}; metrics and deltas were not evaluated.'.format(anchor['id'])
    return results

def apply_reference(results, reference_id=REFERENCE_ID):
    """Whole-period statistics of every case next to the reference: a difference of maxima, not a coincident delta."""
    for result in results:
        result['is_reference'] = 1 if result['id'] == reference_id else 0
    enforce_common_time_axis(results, reference_id)
    reference = find_reference(results, reference_id)
    if reference is None:
        return results
    for result in converged(results):
        for key, stats in result['stats_by_key'].items():
            reference_stats = reference['stats_by_key'].get(key)
            if reference_stats is None:
                continue
            for reference_key, delta_key, source in DELTA_KEYS:
                stats[reference_key] = reference_stats[source]
                stats[delta_key] = stats[source] - reference_stats[source]
    return results

def converged(results):
    return [result for result in results if result['status'] == CONVERGED]

def outage_cases(results):
    """The calculated planning cases in run order."""
    return [result for result in converged(results) if result['id'] != REFERENCE_ID]

def case_blocks(cases):
    """Cases in groups of CASE_SLOTS; always at least one (possibly empty) block."""
    return [cases[start:start + CASE_SLOTS] for start in range(0, len(cases), CASE_SLOTS)] or [[]]

def critical_keys(results, category):
    keys = set()
    for result in converged(results):
        for item, stats in result['by_category'][category]:
            if is_critical(item, stats):
                keys.add((category, item['key']))
    return keys

def evaluated_keys(results, category):
    return {item['key'] for result in converged(results) for item, _ in result['by_category'][category]}

# Each element is only ever compared with itself (same full PowerFactory path).
STATUS_NEW = 'NEW'
STATUS_WORSENED = 'WORSENED'
STATUS_PREEXISTING = 'PRE-EXISTING'
STATUS_IMPROVED = 'IMPROVED'
STATUS_RESOLVED = 'RESOLVED'
STATUS_EXCEEDED = 'EXCEEDED'
STATUS_DEENERGIZED = 'DE-ENERGISED'
STATUS_OUT_OF_SERVICE = 'OUT OF SERVICE'
STATUS_OK = 'OK'
CAUSED_STATUSES = (STATUS_NEW, STATUS_WORSENED, STATUS_EXCEEDED)
EXCEEDED_STATUSES = CAUSED_STATUSES + (STATUS_PREEXISTING, STATUS_IMPROVED)
# The status of an element is the most severe status of any of its time steps.
STATUS_PRECEDENCE = (STATUS_NEW, STATUS_WORSENED, STATUS_EXCEEDED, STATUS_DEENERGIZED, STATUS_PREEXISTING,
                     STATUS_IMPROVED, STATUS_RESOLVED, STATUS_OUT_OF_SERVICE, STATUS_OK)

def paired(results, category, case=None, windowed=False):
    """One record per element with its REF and case statistics.

    `windowed` returns the time-aligned comparison of the case inside its
    assessment rows (its outage windows and every step where it differs from
    the reference); otherwise whole-period statistics. Without a case only REF
    is read.
    """
    if windowed and case is not None and case.get('comparison') is not None:
        return list(case['comparison'].get(category, ()))
    reference = find_reference(results)
    records = {}
    for side, result in (('ref', reference), ('outage', case)):
        if result is None or result['status'] != CONVERGED:
            continue
        for item, stats in result['by_category'].get(category, ()):
            if stats is None:
                continue
            record = records.setdefault(item['key'], {'item': item, 'ref': None, 'outage': None})
            record[side] = stats
    return list(records.values())

def primary(record):
    """The case where it was calculated, otherwise REF."""
    return record['outage'] if record['outage'] is not None else record['ref']

def excess_function(item):
    """excess() of one element with its limits looked up once."""
    if item['category'] in LOADING_CATEGORIES:
        limit = loading_limit(item['category'])
        return lambda value: value - limit if value > limit else 0.0
    lower, upper = voltage_limits(item)
    return lambda value: lower - value if value < lower else value - upper if value > upper else 0.0

def excess(item, value):
    """How far a value lies beyond its limit; 0 on or inside the limit."""
    return excess_function(item)(value)

def _tolerance(item):
    return change_tolerance(item['category'])

def step_status(item, ref_value, case_value):
    """Classify one time step; both values belong to the same element at the same instant."""
    measure = excess_function(item)
    return _classify(item['category'] == 'voltage', None if ref_value is None else measure(ref_value),
                     None if case_value is None else measure(case_value), _tolerance(item))

def _classify(is_voltage, in_ref, in_case, tolerance):
    """Status of one time step from the two excesses; None stands for a missing value."""
    if in_case is None:
        return STATUS_DEENERGIZED if in_ref is not None and is_voltage else None
    if in_ref is None:
        return STATUS_EXCEEDED if in_case > 0 else STATUS_OK
    if in_case > 0 and in_ref == 0:
        return STATUS_NEW
    if in_case > 0:
        if in_case > in_ref + tolerance:
            return STATUS_WORSENED
        if in_case < in_ref - tolerance:
            return STATUS_IMPROVED
        return STATUS_PREEXISTING
    return STATUS_RESOLVED if in_ref > 0 else STATUS_OK

def _worst_status(statuses):
    present = set(statuses)
    return next((status for status in STATUS_PRECEDENCE if status in present), STATUS_OK)

def compare_element(item, case_values, ref_values, rows, steps, labels, out_of_service=False):
    """Time-aligned comparison of one element over `rows`.

    `case_values` or `ref_values` may be None when the element has no series
    there (a node without voltage during the whole case). The coincident delta
    max_t(case(t) - ref(t)) is what the case adds; the difference of the maxima
    is kept separately and must not be confused with it.
    """
    is_loading = item['category'] in LOADING_CATEGORIES
    measure = excess_function(item)
    tolerance = _tolerance(item)
    statuses = []
    caused_rows = []
    caused = violated = ref_violated = dark = 0.0
    best = None
    for row in rows:
        case_value = array_value(case_values, row) if case_values is not None else None
        ref_value = array_value(ref_values, row) if ref_values is not None else None
        if case_value is None and ref_value is None:
            continue
        in_case = None if case_value is None else measure(case_value)
        in_ref = None if ref_value is None else measure(ref_value)
        status = _classify(not is_loading, in_ref, in_case, tolerance)
        if status is None:
            continue
        statuses.append(status)
        weight = steps[row]
        if status in CAUSED_STATUSES:
            caused += weight
            caused_rows.append(row)
        if status == STATUS_DEENERGIZED:
            dark += weight
        if in_case is not None and in_case > 0:
            violated += weight
        if in_ref is not None and in_ref > 0:
            ref_violated += weight
        if case_value is not None and ref_value is not None:
            change = case_value - ref_value
            size = change if is_loading else abs(change)
            if best is None or size > best[0]:
                best = (size, change, labels[row])
    # Equipment the case itself switches off is no finding of the case.
    status = STATUS_OUT_OF_SERVICE if out_of_service else _worst_status(statuses)
    case_stats = row_statistics(case_values, labels, rows) if case_values is not None else None
    ref_stats = row_statistics(ref_values, labels, rows) if ref_values is not None else None
    difference = case_stats['max'] - ref_stats['max'] if case_stats and ref_stats else None
    return {'item': item, 'ref': ref_stats, 'outage': case_stats, 'status': status,
            'coincident_delta': best[1] if best else None, 'coincident_time': best[2] if best else '',
            'maxima_difference': difference, 'caused_hours': caused, 'violation_hours': violated,
            'ref_violation_hours': ref_violated, 'deenergized_hours': dark, 'out_of_service': out_of_service,
            'caused_rows': caused_rows if status != STATUS_OUT_OF_SERVICE else []}

def _spill_rows(case_items, ref_items, inside, row_count):
    """Rows outside the outage windows where the case differs from the reference.

    In a case only its own outages differ from the reference, so a difference
    outside their windows means PowerFactory applied them elsewhere (a shifted
    window, a switching state that outlasts the outage) and is assessed too.
    """
    outside = []
    start = None
    inside_set = set(inside)
    for row in range(row_count + 1):
        free = row < row_count and row not in inside_set
        if free and start is None:
            start = row
        elif not free and start is not None:
            outside.append((start, row))
            start = None
    spill = set()
    for key, item in case_items.items():
        reference = ref_items.get(key)
        if reference is None:
            continue
        case_values, ref_values = item['values'], reference['values']
        tolerance = _tolerance(item)
        for lo, hi in outside:
            if case_values[lo:hi] == ref_values[lo:hi]:
                continue
            for row in range(lo, hi):
                left, right = case_values[row], ref_values[row]
                if (left == MISSING) != (right == MISSING) or (left != MISSING and abs(left - right) > tolerance):
                    spill.add(row)
    return sorted(spill)

def compare_case(result, reference, windows, out_of_service_keys=()):
    """Compare a case with its reference at identical instants and judge it.

    `windows` are the effective (start, end) epoch-second windows of the case's
    outages. Sets result['comparison'] and result['assessment']; a case whose
    rows cannot be put next to the reference is marked NOT EVALUATED.
    """
    hours, labels = result['hours'], result['labels']
    steps = row_steps(hours) if hours else []
    mappable = result.get('absolute') and all(start is not None or end is not None for start, end in windows)
    inside = window_rows(hours, windows) if mappable and windows else list(range(len(hours)))
    assessment = {'window_rows': len(inside), 'spill_rows': 0, 'spill_hours': 0.0, 'coverage': None,
                  'mapped': bool(mappable), 'windows': merge_intervals([w for w in windows if None not in w]),
                  'reference_id': reference['id'] if reference else None}
    if mappable:
        assessment['coverage'] = window_coverage(hours, steps, windows)
    if reference is not None and not _same_time_axis(reference, result):
        result['status'] = AXIS_MISMATCH
        result['error_code'] = -4
        result['message'] = 'Time axis differs from {}; the case was not compared.'.format(reference['id'])
        result['comparison'] = {category: [] for category in VARIABLES}
        result['assessment'] = assessment
        return result
    case_items = {key: item for key, item in result['item_by_key'].items()}
    ref_items = {key: item for key, item in reference['item_by_key'].items()} if reference else {}
    missing = [item['element_name'] for item in list(case_items.values()) + list(ref_items.values()) if 'values' not in item]
    if missing:
        raise GridLensError('the time series of {} were already released; a case can only be compared right after '
                            'its extraction'.format(', '.join(missing[:3])))
    spill = _spill_rows(case_items, ref_items, inside, len(hours)) if reference is not None and mappable and windows else []
    rows = sorted(set(inside) | set(spill))
    assessment['spill_rows'] = len(spill)
    assessment['spill_hours'] = sum(steps[row] for row in spill)
    assessment['rows'] = len(rows)
    dark = set(result.get('counters', {}).get('dark_keys') or ())
    comparison = {category: [] for category in VARIABLES}
    for (category, key) in sorted(set(case_items) | set(ref_items)):
        item = case_items.get((category, key)) or ref_items[category, key]
        case_item = case_items.get((category, key))
        if case_item is None and key not in dark:
            continue
        ref_item = ref_items.get((category, key))
        comparison[category].append(compare_element(
            item, case_item['values'] if case_item else None, ref_item['values'] if ref_item else None,
            rows, steps, labels, key in out_of_service_keys))
    caused_rows = set()
    for records in comparison.values():
        for record in records:
            caused_rows.update(record.pop('caused_rows'))
    assessment['caused_hours'] = sum(steps[row] for row in caused_rows)
    result['comparison'] = comparison
    result['assessment'] = assessment
    return result

def release_values(result):
    """Drop the full-resolution arrays of a compared case; statistics and plot points stay."""
    for item in result['item_by_key'].values():
        item.pop('values', None)

def _worse(item, ref, outage):
    tolerance = change_tolerance(item['category'])
    if item['category'] in LOADING_CATEGORIES:
        return outage['max'] - ref['max'] > tolerance
    lower, upper = voltage_limits(item)
    return ((outage['min'] < lower and outage['min'] < ref['min'] - tolerance)
            or (outage['max'] > upper and outage['max'] > ref['max'] + tolerance))

def _better(item, ref, outage):
    tolerance = change_tolerance(item['category'])
    if item['category'] in LOADING_CATEGORIES:
        return ref['max'] - outage['max'] > tolerance
    lower, upper = voltage_limits(item)
    return max(lower - outage['min'], outage['max'] - upper) < max(lower - ref['min'], ref['max'] - upper) - tolerance

def limit_status(record):
    """What the planning case did to this element's limit.

    A time-aligned record carries its status; whole-period records (appendix
    tables) are judged from their extremes.
    """
    if record.get('status') is not None:
        return record['status']
    item, ref, outage = record['item'], record['ref'], record['outage']
    in_ref = is_critical(item, ref)
    in_outage = is_critical(item, outage)
    if ref is None or outage is None:
        return STATUS_EXCEEDED if in_ref or in_outage else STATUS_OK
    if in_outage and not in_ref:
        return STATUS_NEW
    if in_outage:
        if _worse(item, ref, outage):
            return STATUS_WORSENED
        return STATUS_IMPROVED if _better(item, ref, outage) else STATUS_PREEXISTING
    return STATUS_RESOLVED if in_ref else STATUS_OK

def highlight(status):
    """1 marks a violation caused or worsened by the case, 2 one already in REF."""
    return 1 if status in CAUSED_STATUSES else 2 if status in (STATUS_PREEXISTING, STATUS_IMPROVED) else 0

def _by_name(record):
    return record['item']['element_name'].casefold()

def _loading_delta(record):
    """Coincident delta of a time-aligned record, else the difference of the maxima."""
    if 'coincident_delta' in record:
        return record['coincident_delta']
    if record['ref'] is None or record['outage'] is None:
        return None
    return record['outage']['max'] - record['ref']['max']

def _maxima_difference(record):
    if record.get('maxima_difference') is not None:
        return record['maxima_difference']
    if record['ref'] is None or record['outage'] is None:
        return None
    return record['outage']['max'] - record['ref']['max']

def hours_text(value):
    return '-' if value is None else '{:.2f} h'.format(value) if value < 10 else '{:.1f} h'.format(value)

def percent_text(fraction):
    """Coverage as text; '100 %' only where the verdict treats it as complete."""
    if fraction is None:
        return 'n/a'
    if fraction >= COVERAGE_COMPLETE:
        return '100 %'
    if fraction <= 0:
        return '0 %'
    return '{:.1f} %'.format(min(99.9, max(0.1, 100.0 * fraction)))

def loading_text(value):
    return 'n/a' if value is None else '{:.1f} %'.format(value)

def voltage_text(value):
    return 'n/a' if value is None else '{:.3f}'.format(value)

def delta_text(value):
    return '-' if value is None else '{:+.1f} pp'.format(value)

def _counted(count, singular, plural):
    return '{} {}'.format(count, singular if count == 1 else plural)

def _status_breakdown(statuses, both_cases):
    """'1 new, 2 already in REF' for the exceeded statuses."""
    if not both_cases:
        return ''
    parts = []
    for status, label in ((STATUS_NEW, 'new'), (STATUS_WORSENED, 'worsened'), (STATUS_PREEXISTING, 'already in REF'),
                          (STATUS_IMPROVED, 'improved')):
        count = statuses.count(status)
        if count:
            parts.append('{} {}'.format(count, label))
    return ': ' + ', '.join(parts) if parts else ''

def _voltage_excess(record):
    lower, upper = voltage_limits(record['item'])
    stats = primary(record)
    return max(lower - stats['min'], stats['max'] - upper)

def _primary_counters(results):
    reference = find_reference(results)
    return reference.get('counters', {}) if reference else {}

def loading_classes(category):
    """The loading classes of the pie charts: up to the warning, up to the limit, above the limit."""
    warning, limit = loading_warning(category), loading_limit(category)
    return (('up to {} %'.format(format_limit(warning)), lambda value: value <= warning),
            ('{} to {} %'.format(format_limit(warning), format_limit(limit)), lambda value: value <= limit),
            ('above {} %'.format(format_limit(limit)), lambda value: True))
CATEGORY_LABELS = (('line', 'Line loading', 'line', 'lines'), ('transformer', 'Transformer loading', 'transformer', 'transformers'), ('voltage', 'Voltage magnitude', 'node', 'nodes'))
REFERENCE_NAME = 'Reference'
MAX_REFERENCE_ROWS = 30

def voltage_limits_text():
    lower, upper = default_voltage_limits()
    return ('Permitted voltage band: {} to {} p.u. of the nominal voltage, for every voltage level. Values on the band '
            'limit are no violation.'.format(format_limit(lower), format_limit(upper)))

def _result_name(result):
    return REFERENCE_NAME if result['id'] == REFERENCE_ID else result['name']

def _matrix_tables(payload, results, table, entries):
    """Write entries (name, REF text, {case id: text}, violation) as blocks of CASE_SLOTS cases."""
    cases = outage_cases(results)
    for block_number, block in enumerate(case_blocks(cases), 1):
        for order, (name, ref_text, texts, violation) in enumerate(entries, 1):
            row = {'block': block_number, 'row_order': order, 'element_name': name, 'ref_text': ref_text, 'col_count': len(block), 'violation': violation}
            for slot in range(1, CASE_SLOTS + 1):
                case = block[slot - 1] if slot <= len(block) else None
                row['h{}_name'.format(slot)] = case['name'] if case else ''
                row['c{}_text'.format(slot)] = texts.get(case['id'], 'n/a') if case else ''
            payload[table].append(row)

def _stats_by_result(results, category):
    """{result id: {element key: (item, stats)}} for REF and every calculated case."""
    ok = converged(results)
    return {result['id']: {item['key']: (item, stats) for item, stats in result['by_category'][category]} for result in ok}

def _violation_flag(item, ref_stats, case_stats_list):
    flags = [highlight(limit_status({'item': item, 'ref': ref_stats, 'outage': stats})) for stats in case_stats_list]
    if not flags:
        flags = [highlight(limit_status({'item': item, 'ref': ref_stats, 'outage': None}))]
    return 1 if 1 in flags else 2 if 2 in flags else 0

def _loading_appendix(payload, results, category, table):
    by_result = _stats_by_result(results, category)
    reference = by_result.get(REFERENCE_ID, {})
    cases = outage_cases(results)
    keys = {key for entries in by_result.values() for key in entries}
    listed = []
    for key in keys:
        found = [(case_id, entries[key]) for case_id, entries in by_result.items() if key in entries]
        item = found[0][1][0]
        ref_stats = reference.get(key, (None, None))[1]
        peaks = [stats['max'] for _, (_, stats) in found]
        deltas = [stats['max'] - ref_stats['max'] for case_id, (_, stats) in found if ref_stats is not None and case_id != REFERENCE_ID]
        if max(peaks) < loading_warning(category) and not any(abs(delta) >= setting_value('loading_appendix_delta') for delta in deltas):
            continue
        case_stats = [by_result[case['id']][key][1] for case in cases if key in by_result[case['id']]]
        texts = {case['id']: loading_text(by_result[case['id']][key][1]['max']) if key in by_result[case['id']] else 'n/a' for case in cases}
        listed.append((-max(peaks), item['element_name'].casefold(), item['element_name'], loading_text(ref_stats['max'] if ref_stats else None), texts, _violation_flag(item, ref_stats, case_stats)))
    _matrix_tables(payload, results, table, [entry[2:] for entry in sorted(listed, key=lambda entry: entry[:2])])

def _voltage_appendix(payload, results):
    by_result = _stats_by_result(results, 'voltage')
    reference = by_result.get(REFERENCE_ID, {})
    cases = outage_cases(results)
    keys = {key for entries in by_result.values() for key in entries}
    listed = []
    for key in keys:
        found = [entries[key] for entries in by_result.values() if key in entries]
        item = found[0][0]
        ref_stats = reference.get(key, (None, None))[1]
        case_stats = [by_result[case['id']][key][1] for case in cases if key in by_result[case['id']]]
        statuses = [limit_status({'item': item, 'ref': ref_stats, 'outage': stats}) for stats in case_stats] or [limit_status({'item': item, 'ref': ref_stats, 'outage': None})]
        change = max([abs(stats['min'] - ref_stats['min']) for stats in case_stats] or [0.0]) if ref_stats is not None else 0.0
        if all(status == STATUS_OK for status in statuses) and change < setting_value('voltage_appendix_delta'):
            continue
        lower, upper = voltage_limits(item)
        excess = max(max(lower - stats['min'], stats['max'] - upper) for _, stats in found)
        texts = {case['id']: voltage_text(by_result[case['id']][key][1]['min']) if key in by_result[case['id']] else 'n/a' for case in cases}
        listed.append((-excess, item['element_name'].casefold(), item['element_name'], voltage_text(ref_stats['min'] if ref_stats else None), texts, _violation_flag(item, ref_stats, case_stats)))
    _matrix_tables(payload, results, 'ScriptedAppendixVoltage', [entry[2:] for entry in sorted(listed, key=lambda entry: entry[:2])])

def _top_lines_by_case(payload, results):
    by_result = _stats_by_result(results, 'line')
    ranked = {}
    for result_id, entries in by_result.items():
        ordered = sorted(entries.values(), key=lambda entry: (-entry[1]['max'], entry[0]['element_name'].casefold()))[:setting_value('top_n')]
        ranked[result_id] = ['{} - {}'.format(item['element_name'], loading_text(stats['max'])) for item, stats in ordered]
    cases = outage_cases(results)
    rows = []
    for rank in range(1, setting_value('top_n') + 1):
        reference = ranked.get(REFERENCE_ID, [])
        texts = {case['id']: ranked[case['id']][rank - 1] if rank <= len(ranked.get(case['id'], [])) else 'n/a' for case in cases}
        if rank > len(reference) and all(text == 'n/a' for text in texts.values()):
            break
        rows.append((str(rank), reference[rank - 1] if rank <= len(reference) else 'n/a', texts, 0))
    _matrix_tables(payload, results, 'ScriptedTopLinesByCase', rows)

def _violation_counts(result):
    lines = sum(1 for item, stats in result['by_category']['line'] if is_critical(item, stats))
    transformers = sum(1 for item, stats in result['by_category']['transformer'] if is_critical(item, stats))
    nodes = sum(1 for item, stats in result['by_category']['voltage'] if is_critical(item, stats))
    return lines, transformers, nodes

def _case_counts(payload, results):
    reference = find_reference(results)
    ordered = ([reference] if reference else []) + outage_cases(results)
    for order, result in enumerate(ordered):
        lines, transformers, nodes = _violation_counts(result)
        payload['ScriptedCaseCounts'].append({'case_order': order, 'case_name': _result_name(result), 'line_count': lines, 'transformer_count': transformers, 'node_count': nodes})

def _radar(payload, results):
    reference = find_reference(results)
    cases = outage_cases(results)
    shown = ([reference] if reference else []) + cases[:CASE_SLOTS]
    if not shown:
        return
    counts = [_violation_counts(result) for result in shown]
    note = 'Axes use their own maximum; the table lists the absolute counts.'
    if len(cases) > CASE_SLOTS:
        note = 'The first {} of {} cases are drawn. '.format(CASE_SLOTS, len(cases)) + note
    for metric, label in enumerate(('Lines > 100 %', 'Transformers > 100 %', 'Nodes outside band')):
        values = [count[metric] for count in counts]
        peak = max(values) or 1
        row = {'metric_order': metric + 1, 'metric_label': label, 'note': note}
        for slot in range(SERIES_SLOTS):
            row['s{}_name'.format(slot)] = _result_name(shown[slot]) if slot < len(shown) else ' '
            row['v{}'.format(slot)] = 100.0 * values[slot] / peak if slot < len(shown) else None
        payload['ScriptedRadar'].append(row)

def _pies(payload, results):
    reference = find_reference(results)
    for category, table in (('line', 'ScriptedPieLines'), ('transformer', 'ScriptedPieTransformers')):
        classes = loading_classes(category)
        counts = [0] * len(classes)
        if reference is not None:
            for _, stats in reference['by_category'][category]:
                counts[next(index for index, (_, fits) in enumerate(classes) if fits(stats['max']))] += 1
        for order, ((label, _), count) in enumerate(zip(classes, counts), 1):
            payload[table].append({'sort_order': order, 'class_label': label, 'element_count': count})

def _reference_exceeded(payload, results):
    reference = find_reference(results)
    if reference is None:
        return
    rows = []
    for category, label in (('line', 'Line'), ('transformer', 'Transformer')):
        for item, stats in reference['by_category'][category]:
            if is_critical(item, stats):
                rows.append((-stats['max'], item['element_name'].casefold(), label, item['element_name'], element_grid_name(item['object']), stats['max']))
    for rank, (_, _, label, name, grid, value) in enumerate(sorted(rows)[:MAX_REFERENCE_ROWS], 1):
        payload['ScriptedReferenceExceeded'].append({'rank': rank, 'type_label': label, 'element_name': name, 'grid_name': grid or '-', 'max_text': loading_text(value)})

def _line_bars(payload, results):
    best = {}
    for result in converged(results):
        for item, stats in result['by_category']['line']:
            current = best.get(item['key'])
            if current is None or stats['max'] > current[1]:
                best[item['key']] = (item['element_name'], stats['max'], _result_name(result))
    for rank, (name, value, case_name) in enumerate(sorted(best.values(), key=lambda entry: (-entry[1], entry[0].casefold()))[:setting_value('top_n')], 1):
        payload['ScriptedLineLoadingBars'].append({'rank': rank, 'element_name': name, 'max_value': value, 'case_name': case_name})

def _trend_rows(payload, table, results, key, title):
    reference = find_reference(results)
    shown = ([reference] if reference else []) + outage_cases(results)[:CASE_SLOTS]
    items = [result['item_by_key'].get(('line', key)) for result in shown]
    axis = next((item for item in items if item is not None), None)
    if axis is None:
        return
    series = [{label: value for label, _, value in sampled_plot_points(item)} if item is not None else {} for item in items]
    for label, timestamp, _ in sampled_plot_points(axis):
        row = {'time_label': label, 'timestamp': timestamp, 'element_name': axis['element_name'], 'chart_title': title, 'unit': axis['unit']}
        for slot in range(SERIES_SLOTS):
            row['s{}_name'.format(slot)] = _result_name(shown[slot]) if slot < len(shown) else ' '
            row['v{}'.format(slot)] = series[slot].get(label) if slot < len(shown) else None
        payload[table].append(row)

def _trends(payload, results):
    best = None
    for result in converged(results):
        for item, stats in result['by_category']['line']:
            if best is None or stats['max'] > best[0]:
                best = (stats['max'], item['key'], item['element_name'])
    if best is not None:
        _trend_rows(payload, 'ScriptedTrendMostLoaded', results, best[1], 'Most loaded line: {}'.format(best[2]))
    largest = None
    for case in outage_cases(results):
        for record in paired(results, 'line', case, True):
            delta = _loading_delta(record)
            if delta is not None and (largest is None or delta > largest[0]):
                largest = (delta, record['item']['key'], record['item']['element_name'], case['name'])
    if largest is not None and largest[0] > change_tolerance('line'):
        _trend_rows(payload, 'ScriptedTrendLargestDelta', results, largest[1],
                    'Largest coincident delta: {} ({:+.1f} pp, {})'.format(largest[2], largest[0], largest[3]))

def _line_pairs(results, case):
    return [record for record in paired(results, 'line', case, True) if record['ref'] is not None and record['outage'] is not None]

def _case_metrics(payload, results):
    reference = find_reference(results)
    rows = []
    if reference is not None and reference['by_category']['line']:
        top = max(reference['by_category']['line'], key=lambda entry: (entry[1]['max'], -len(entry[0]['element_name'])))
        voltages = [stats for _, stats in reference['by_category']['voltage']]
        rows.append({'order': 0, 'name': REFERENCE_NAME, 'max': top[1]['max'], 'element': top[0]['element_name'], 'delta': None,
                     'delta_element': '', 'difference': None, 'hours': None, 'coverage': None,
                     'voltage': voltages and (min(s['min'] for s in voltages), max(s['max'] for s in voltages))})
    for order, case in enumerate(outage_cases(results), 1):
        pairs = _line_pairs(results, case)
        lines = [record for record in paired(results, 'line', case, True) if record['outage'] is not None]
        top = max(lines, key=lambda record: (record['outage']['max'], -len(_by_name(record))), default=None)
        rising = max((record for record in pairs if _loading_delta(record) is not None), key=_loading_delta, default=None)
        nodes = [record['outage'] for record in paired(results, 'voltage', case, True) if record['outage'] is not None]
        assessment = case.get('assessment') or {}
        rows.append({'order': order, 'name': case['name'], 'max': top['outage']['max'] if top else None,
                     'element': top['item']['element_name'] if top else '-', 'delta': _loading_delta(rising) if rising else None,
                     'delta_element': rising['item']['element_name'] if rising else '',
                     'difference': _maxima_difference(rising) if rising else None, 'hours': assessment.get('caused_hours'),
                     'coverage': assessment.get('coverage'),
                     'voltage': nodes and (min(s['min'] for s in nodes), max(s['max'] for s in nodes))})
    for row in rows:
        payload['ScriptedCaseMetrics'].append({
            'case_order': row['order'], 'case_name': row['name'], 'max_line_text': loading_text(row['max']), 'max_line_element': row['element'],
            'coincident_delta_text': '-' if row['delta'] is None else '{} - {}'.format(delta_text(row['delta']), row['delta_element']),
            'maxima_difference_text': delta_text(row['difference']), 'violation_hours_text': hours_text(row['hours']),
            'voltage_range_text': '{:.3f}-{:.3f} p.u.'.format(*row['voltage']) if row['voltage'] else 'n/a',
            'coverage_text': percent_text(row['coverage']) if row['order'] else 'full period'})
    named = [row for row in rows if row['max'] is not None]
    if named:
        top = max(named, key=lambda row: row['max'])
        pair = max((row for row in rows if row['delta'] is not None and row['delta'] > change_tolerance('line')), key=lambda row: row['delta'], default=None)
        payload['ScriptedKpis'].append({
            'highest_text': '{} · {}'.format(loading_text(top['max']), top['element']), 'highest_caption': 'Highest observed line loading across all cases',
            'highest_violation': 1 if top['max'] > loading_limit('line') else 0,
            'delta_text': '{} · {}'.format(delta_text(pair['delta']), pair['name']) if pair else 'no increase',
            'delta_caption': 'Largest coincident loading increase compared with Reference at the same time step' if pair
            else 'No line loads more than in Reference at the same time step'})

def _quality(payload, check_id, check_name, status, message, affected_element='-'):
    """One row of the model quality page."""
    payload['ScriptedModelQuality'].append({'check_id': check_id, 'check_name': check_name, 'status': status,
                                            'message': message, 'affected_element': affected_element})

def _model_quality(payload, results, request=None):
    request = request or {}
    ok = converged(results)
    total_series = sum((len(r['by_category'][c]) for r in ok for c, _, _, _ in CATEGORY_LABELS))
    cases_ok = bool(results) and len(ok) == len(results) and all((any((result['by_category'][category] for category, _, _, _ in CATEGORY_LABELS)) for result in ok))
    _quality(payload, 'cases', 'Evaluated cases', 'PASS' if cases_ok else 'FAIL',
             '{} of {} calculation(s) converged; {} result series.'.format(len(ok), len(results), total_series))
    for result in results:
        if result['status'] != CONVERGED:
            _quality(payload, 'case_' + result['id'], 'Calculation ' + result['id'], 'FAIL',
                     result['message'] or 'Calculation did not converge.', result['name'])
    plans = request.get('cases') or []
    blocked = [plan for plan in plans if plan['status'] != PLAN_READY]
    if plans:
        _quality(payload, 'case_configuration', 'Planning cases', 'WARNING' if blocked else 'PASS',
                 '{} defined ({}); {} ready, {} not calculated{}.'.format(
                     _counted(len(plans), 'case', 'cases'), request.get('source_text', ''), len(plans) - len(blocked), len(blocked),
                     '; {} excluded from the calculation in the case manager'.format(len(request['disabled'])) if request.get('disabled') else ''),
                 ', '.join(plan['name'] for plan in blocked[:5]) or '-')
    for number, warning in enumerate(request.get('warnings') or (), 1):
        label = 'Planning cases' if warning == (request.get('config') or {}).get('migration_note') else 'Fixed outages'
        _quality(payload, 'request_warning_{}'.format(number), label, 'WARNING', warning)
    for plan in plans:
        for warning in plan.get('warnings', ()):
            _quality(payload, 'case_warning_' + plan['id'], 'Case ' + plan['name'], 'WARNING', warning, plan['name'])
    cases = outage_cases(results)
    partial = [case for case in cases if (case.get('assessment') or {}).get('coverage') is not None and case['assessment']['coverage'] < COVERAGE_COMPLETE]
    if cases:
        _quality(payload, 'coverage', 'Outage window coverage', 'WARNING' if partial else 'PASS',
                 '{} of {} case(s) have result rows for less than the complete outage time (window outside the simulated period or between time steps).'.format(len(partial), len(cases)) if partial
                 else 'Every outage window of every calculated case is covered by result rows.',
                 ', '.join(case['name'] for case in partial[:5]) or '-')
        spilled = [case for case in cases if (case.get('assessment') or {}).get('spill_rows')]
        _quality(payload, 'outside_window', 'Effect outside the outage windows', 'WARNING' if spilled else 'PASS',
                 '{} case(s) differ from Reference outside their outage windows; these time steps were assessed as well. Check whether PowerFactory applies the windows shifted or a switching state outlasts the outage.'.format(len(spilled)) if spilled
                 else 'No case differs from Reference outside its outage windows.',
                 ', '.join(case['name'] for case in spilled[:5]) or '-')
    for category, label, singular, plural in CATEGORY_LABELS:
        evaluated = len(evaluated_keys(results, category))
        exceeded = len(critical_keys(results, category))
        message = '{} evaluated; {} the limit in at least one case.'.format(_counted(evaluated, singular, plural), _counted(exceeded, 'exceeds', 'exceed')) if evaluated else 'No {} evaluated.'.format(singular)
        _quality(payload, 'series_' + category, label, 'PASS' if evaluated else 'WARNING', message,
                 _counted(exceeded, singular, plural) if exceeded else '-')
    counters = _primary_counters(results)
    if counters.get('dc_nodes') or counters.get('deenergized_nodes') or counters.get('deenergized_steps'):
        _quality(payload, 'voltage_data', 'Voltage data', 'INFO',
                 'Reference: {} and {} left out; {} below {} p.u. count as de-energised, not as a voltage value.'.format(
                     _counted(counters.get('dc_nodes', 0), 'DC node', 'DC nodes'),
                     _counted(counters.get('deenergized_nodes', 0), 'node without voltage', 'nodes without voltage'),
                     _counted(counters.get('deenergized_steps', 0), 'time step', 'time steps'), format_limit(setting_value('energized_min_pu'))))
    dark_cases = [(case['name'], sum(1 for record in case['comparison']['voltage'] if record['status'] == STATUS_DEENERGIZED)) for case in cases if case.get('comparison')]
    dark_cases = [(name, count) for name, count in dark_cases if count]
    if dark_cases:
        _quality(payload, 'deenergized', 'Nodes de-energised by a case', 'WARNING',
                 '; '.join('{}: {}'.format(name, _counted(count, 'node', 'nodes')) for name, count in dark_cases[:8])
                 + '. They are reported separately and are no voltage value.')
    varying = sum((1 for r in ok for c, _, _, _ in CATEGORY_LABELS for item, _ in r['by_category'][c] if has_time_variation(item)))
    _quality(payload, 'time_variation', 'Time variation', 'PASS' if varying else 'WARNING',
             '{} of {} series change over the simulation period.'.format(varying, total_series) if varying
             else 'All {} series are constant; check QDS profiles and result recording.'.format(total_series))
    reference = find_reference(results)
    _quality(payload, 'reference_comparison', 'Reference comparison', 'PASS' if reference is not None else 'WARNING',
             'Every case is compared with Reference at the same time step; deltas compare each element with itself.' if reference is not None
             else 'No converged reference case; violations cannot be split into new and pre-existing.')
    _quality(payload, 'qds_mode', 'Calculation period', 'INFO', qds_mode_text(request))
    n1_kinds = {result['n1'].get('kind') for result in results if result.get('n1', {}).get('status') == 'EVALUATED'}
    if n1_kinds:
        _quality(payload, 'security_scope', 'Assessment scope', 'WARNING',
                 'N-0 assessment of the planned network states and {} with the contingency analysis of the study case at '
                 'the QDS time steps inside the outage windows (rows n-1 below). This is no proof of n-1 security; security '
                 'of supply, protection coordination and safe isolation are not assessed.'.format(
                     "(n-1)' against n-1" if N1_PRIME in n1_kinds else 'the n-1 reference'))
    else:
        _quality(payload, 'security_scope', 'Assessment scope', 'WARNING',
                 'N-0 assessment of the planned network states. N-1 security, security of supply, protection coordination and safe isolation are not assessed.')
    _quality(payload, 'limit_loading', 'Loading limit', 'INFO', loading_limits_text())
    _quality(payload, 'limit_voltage', 'Voltage limits', 'INFO', voltage_limits_text())
    # The settings the assessment actually used, i.e. the active ones.
    snapshot = settings_snapshot(active_overrides())
    _quality(payload, 'network_scope', 'Network scope', 'INFO', 'Assessed equipment: {}. Contingencies: {}'.format(
        grid_scope_text(), (request or {}).get('contingency_scope') or 'not read in this run.'))
    _quality(payload, 'settings', 'Settings', 'INFO' if not snapshot['overrides'] else 'WARNING',
             'Settings {}, classification rules {}: {}. Stored provisionally in the case configuration file.'.format(
                 snapshot['settings_version'], snapshot['classification_version'], overrides_text(snapshot['overrides'])))
    n1_quality(payload, results)

QDS_TIME_BASE_TEXT = ('Complete ComStatsim period: every run covers the whole simulated period with the ComStatsim time step; '
                      'GridLens shortens no window, adds no time step and changes no time step.')


def qds_mode_text(request=None):
    return QDS_TIME_BASE_TEXT

def _key_discriminator(key):
    digest = hashlib.sha256(str(key).encode('utf-8')).hexdigest()
    return digest[:6]

COVERAGE_COMPLETE = 0.999

def assess_case(results, case):
    """Judge one planning case by what it changes against Reference at the same time steps."""
    loading = [record for category in LOADING_CATEGORIES for record in paired(results, category, case, True)]
    voltage = paired(results, 'voltage', case, True)
    in_outage = [record for record in loading if record['outage'] is not None]
    nodes = [record for record in voltage if record['outage'] is not None]
    assessment = case.get('assessment') or {}
    if not in_outage and not nodes and not any(record['status'] == STATUS_DEENERGIZED for record in voltage):
        return None
    if case.get('comparison') is not None and not assessment.get('rows'):
        return None
    loading_statuses = [limit_status(record) for record in loading]
    voltage_statuses = [limit_status(record) for record in voltage]
    over = any(status in CAUSED_STATUSES for status in loading_statuses)
    band = any(status in CAUSED_STATUSES for status in voltage_statuses)
    dark = voltage_statuses.count(STATUS_DEENERGIZED)
    coverage = assessment.get('coverage')
    if over and band:
        verdict = ASSESSMENT_BOTH
    elif over:
        verdict = ASSESSMENT_LOADING
    elif band:
        verdict = ASSESSMENT_VOLTAGE
    elif dark:
        verdict = ASSESSMENT_DEENERGIZED
    elif coverage is not None and coverage < COVERAGE_COMPLETE:
        # Nothing found, but part of the outage time has no result rows:
        # that is no evidence of a secure state.
        verdict = ASSESSMENT_INCOMPLETE
    elif STATUS_PREEXISTING in loading_statuses + voltage_statuses or STATUS_IMPROVED in loading_statuses + voltage_statuses:
        verdict = ASSESSMENT_PREEXISTING
    else:
        verdict = ASSESSMENT_OK
    # Name the element the case pushes over the limit, not one that was
    # already overloaded in REF; fall back to the most loaded element.
    caused = [record for record, status in zip(loading, loading_statuses)
              if status in CAUSED_STATUSES and record['outage'] is not None]
    worst = max(caused or in_outage, key=lambda record: record['outage']['max'], default=None)
    low = min(nodes, key=lambda record: record['outage']['min'], default=None)
    high = max(nodes, key=lambda record: record['outage']['max'], default=None)
    rising = max((record for record in in_outage if _loading_delta(record) is not None), key=_loading_delta, default=None)
    return {
        'assessment': verdict,
        'violation': 1 if verdict in ASSESSMENT_CAUSED else 2 if verdict in ASSESSMENT_ATTENTION else 0,
        'max_loading': worst['outage']['max'] if worst else None,
        'max_loading_element': worst['item']['element_name'] if worst else '',
        'max_loading_time': worst['outage']['time_max'] if worst else '',
        'reference_max_loading': worst['ref']['max'] if worst and worst['ref'] else None,
        'delta': _loading_delta(rising) if rising else None,
        'delta_time': rising.get('coincident_time', '') if rising else '',
        'maxima_difference': _maxima_difference(rising) if rising else None,
        'delta_element': rising['item']['element_name'] if rising else '',
        'min_voltage': low['outage']['min'] if low else None,
        'max_voltage': high['outage']['max'] if high else None,
        'loading_statuses': loading_statuses,
        'voltage_statuses': voltage_statuses,
        'deenergized': dark,
        'caused_hours': assessment.get('caused_hours'),
        'coverage': coverage,
        'spill_hours': assessment.get('spill_hours') or 0.0,
        'mapped': assessment.get('mapped', True),
        'both_cases': find_reference(results) is not None,
    }

def judge_cases(results):
    """Store the verdict of every calculated case once, so log, case table and summary agree."""
    for case in outage_cases(results):
        case['judged'] = assess_case(results, case)
    return results

def judged(results, case):
    """The stored verdict of a case, or a fresh one where none is stored."""
    return case['judged'] if 'judged' in case else assess_case(results, case)

def _violation_text(statuses, singular, plural, both):
    exceeded = [status for status in statuses if status in EXCEEDED_STATUSES]
    if not exceeded:
        return 'no {}'.format(singular)
    return _counted(len(exceeded), singular, plural) + _status_breakdown(statuses, both)

def assessment_detail(values):
    """Readable sentences with the numbers behind the verdict, loading first."""
    parts = []
    both = values.get('both_cases', False)
    if values.get('max_loading') is not None:
        text = "Loading max {:.1f} % on {} at {}".format(
            values['max_loading'], values['max_loading_element'],
            values['max_loading_time'])
        if values.get('reference_max_loading') is not None:
            text += " (REF {:.1f} %)".format(values['reference_max_loading'])
        if values.get('delta') is not None and values['delta'] > change_tolerance('line'):
            text += ", largest coincident increase {:+.1f} pp on {}".format(values['delta'], values['delta_element'])
            if values.get('delta_time'):
                text += " at {}".format(values['delta_time'])
            if values.get('maxima_difference') is not None:
                text += " (difference of maxima {:+.1f} pp)".format(values['maxima_difference'])
        text += "; " + _violation_text(values.get('loading_statuses', []), 'overload', 'overloads', both)
        parts.append(text)
    if values.get('min_voltage') is not None and values.get('max_voltage') is not None:
        parts.append("Voltage {:.3f} to {:.3f} p.u.; {}".format(
            values['min_voltage'], values['max_voltage'],
            _violation_text(values.get('voltage_statuses', []), 'node outside the band', 'nodes outside the band', both)))
    if values.get('deenergized'):
        parts.append("{} de-energised by the case".format(_counted(values['deenergized'], 'node', 'nodes')))
    if values.get('caused_hours'):
        parts.append("Caused violations during {}".format(hours_text(values['caused_hours'])))
    if values.get('spill_hours'):
        parts.append("Differs from REF outside the outage windows during {}; assessed as well".format(hours_text(values['spill_hours'])))
    if values.get('coverage') is not None and values['coverage'] < COVERAGE_COMPLETE:
        parts.append("Result rows cover {} of the outage time".format(percent_text(values['coverage'])))
    if values.get('mapped') is False:
        parts.append("Outage windows could not be placed on the time axis; the complete period was assessed")
    return ". ".join(parts) + "." if parts else ""

def _reference_detail(reference):
    lines = reference['by_category']['line']
    nodes = [stats for _, stats in reference['by_category']['voltage']]
    parts = []
    if lines:
        top = max(lines, key=lambda entry: entry[1]['max'])
        parts.append('max line {:.1f} % on {}'.format(top[1]['max'], top[0]['element_name']))
    if nodes:
        parts.append('node voltage {:.3f}-{:.3f} p.u'.format(min(s['min'] for s in nodes), max(s['max'] for s in nodes)))
    return '; '.join(parts) + '.' if parts else ''

def period_text(start, end):
    """'2026-10-15 00:00 - 05:00' when both ends lie on the same day."""
    if not start and not end:
        return ''
    if start[:10] and start[:10] == end[:10] and len(end) > 11:
        return '{} - {}'.format(start, end[11:])
    return '{} - {}'.format(start, end)

def _plan_period(plan):
    texts = []
    for record in plan['members']:
        start, end = plan['windows'].get(record['key'], (None, None))
        texts.append(period_text(_format_pf_time(start), _format_pf_time(end)) or 'unknown window')
    return '; '.join(texts)

def _plan_equipment(plan):
    return '; '.join(record.get('equipment_name') or '-' for record in plan['members']) or '-'

def states_text(plan):
    """'2026-03-02 08:00 FS1 | 10:00 FS1 + FS2 | ...' for the network states of a case."""
    names = {record['key']: record['name'] for record in plan['members']}
    parts = []
    previous_day = None
    for start, _end, active in plan.get('states') or ():
        stamp = _format_pf_time(start)
        day = stamp[:10]
        label = stamp if day != previous_day else stamp[11:]
        previous_day = day
        parts.append('{} {}'.format(label, ' + '.join(sorted(names.get(key, key) for key in active)) if active else 'none'))
    return ' | '.join(parts)

def _windows_text(plan, request):
    return 'QDS: complete ComStatsim period'

def _reference_text(request):
    background = (request or {}).get('background') or []
    if not background:
        return 'R0: no planned outage'
    return 'Rfix: fixed outages ' + ', '.join(record['name'] for record in background)

def _case_rows(payload, results, request):
    reference = find_reference(results)
    reference_result = next((result for result in results if result['id'] == REFERENCE_ID), None)
    ref_text = _reference_text(request)
    if reference_result is not None:
        labels = reference_result['labels']
        background = request.get('background') or []
        payload['ScriptedCases'].append({
            'case_order': 0, 'case_id': REFERENCE_ID, 'case_name': REFERENCE_NAME, 'is_reference': 1,
            'simulation_status': reference_result['status'], 'period_text': period_text(labels[0], labels[-1]) if labels else '', 'priority': 0,
            'equipment_name': 'No planned outage' if not background else 'Fixed outages: ' + ', '.join(record['name'] for record in background),
            'assessment': 'BASELINE' if reference is not None else ASSESSMENT_NO_DATA,
            'assessment_detail': _reference_detail(reference) if reference is not None else reference_result['message'], 'violation': 0,
            'case_description': 'Comparison basis of every case.', 'outage_names': ', '.join(record['name'] for record in background) or '-',
            'reference_text': ref_text, 'states_text': '', 'windows_text': 'QDS: complete ComStatsim period',
            'coverage_text': 'full period', 'provenance_text': reference_result.get('provenance', 'CALCULATED')})
    by_case = {result['id']: result for result in results}
    order = 0
    for plan in request.get('cases') or ():
        order += 1
        result = by_case.get(plan['id'])
        values = {'assessment': ASSESSMENT_SKIPPED if plan['status'] == PLAN_NOT_SIMULATED else ASSESSMENT_NOT_EVALUATED, 'violation': 0}
        detail = plan.get('reason', '')
        status = plan['status']
        coverage = '-'
        provenance = 'NOT CALCULATED'
        if plan['status'] == PLAN_READY and result is not None:
            status = result['status']
            provenance = result.get('provenance', 'CALCULATED')
            if result['status'] != CONVERGED:
                values = {'assessment': AXIS_MISMATCH if result['status'] == AXIS_MISMATCH else ASSESSMENT_NOT_EVALUATED, 'violation': 0}
                detail = result['message']
            else:
                verdict = judged(results, result)
                if verdict is None:
                    values = {'assessment': ASSESSMENT_NO_DATA, 'violation': 0}
                    detail = 'No result rows fall inside the outage windows of this case, so it was not assessed.'
                else:
                    values = verdict
                    detail = assessment_detail(verdict)
                    coverage = percent_text(verdict['coverage']) if verdict['coverage'] is not None else 'whole axis'
        payload['ScriptedCases'].append({
            'case_order': order, 'case_id': plan['id'], 'case_name': plan['name'], 'is_reference': 0, 'simulation_status': status,
            'period_text': _plan_period(plan), 'priority': int(max([record.get('priority') or 0 for record in plan['members']] or [0])),
            'equipment_name': _plan_equipment(plan), 'assessment': values['assessment'], 'assessment_detail': detail,
            'violation': values.get('violation', 0), 'case_description': plan.get('description') or '-',
            'outage_names': ', '.join(record['name'] for record in plan['members']) or '-', 'reference_text': ref_text,
            'states_text': states_text(plan) or '-', 'windows_text': _windows_text(plan, request), 'coverage_text': coverage,
            'provenance_text': provenance})
    for record in request.get('skipped') or ():
        order += 1
        payload['ScriptedCases'].append({
            'case_order': order, 'case_id': 'N/A', 'case_name': record['name'], 'is_reference': 0, 'simulation_status': record['status'],
            'period_text': period_text(record.get('start_time', ''), record.get('end_time', '')), 'priority': int(record.get('priority') or 0),
            'equipment_name': record.get('equipment_name') or '-', 'assessment': ASSESSMENT_SKIPPED,
            'assessment_detail': record.get('skip_reason', ''), 'violation': 0, 'case_description': '-', 'outage_names': record['name'],
            'reference_text': ref_text, 'states_text': '-', 'windows_text': '-', 'coverage_text': '-', 'provenance_text': 'NOT CALCULATED'})

COMPARISON_ROWS = (
    ('New overloads', 'loading', (STATUS_NEW,)), ('Worsened overloads', 'loading', (STATUS_WORSENED,)),
    ('Pre-existing or improved overloads', 'loading', (STATUS_PREEXISTING, STATUS_IMPROVED)),
    ('Max. coincident loading increase', 'delta', None), ('New or worsened voltage violations', 'voltage', (STATUS_NEW, STATUS_WORSENED)),
    ('Nodes de-energised by the case', 'voltage', (STATUS_DEENERGIZED,)), ('Duration of caused violations', 'hours', None),
    ('Outage time covered by results', 'coverage', None), ('Assessment', 'verdict', None))

def _case_comparison(payload, results):
    """Key figures of every case side by side, REF in the first column."""
    cases = outage_cases(results)
    if not cases:
        return
    verdicts = {case['id']: judged(results, case) for case in cases}
    entries = []
    for label, kind, statuses in COMPARISON_ROWS:
        texts = {}
        caused = False
        for case in cases:
            values = verdicts[case['id']]
            if values is None:
                texts[case['id']] = 'n/a'
                continue
            if kind in ('loading', 'voltage'):
                pool = values['loading_statuses'] if kind == 'loading' else values['voltage_statuses']
                count = sum(1 for status in pool if status in statuses)
                caused = caused or (count and statuses[0] in CAUSED_STATUSES + (STATUS_DEENERGIZED,))
                texts[case['id']] = str(count)
            elif kind == 'delta':
                texts[case['id']] = delta_text(values['delta'])
            elif kind == 'hours':
                texts[case['id']] = hours_text(values['caused_hours'] or 0.0)
                caused = caused or bool(values['caused_hours'])
            elif kind == 'coverage':
                texts[case['id']] = percent_text(values['coverage']) if values['coverage'] is not None else 'whole axis'
            else:
                texts[case['id']] = values['assessment']
                caused = caused or values['violation'] == 1
        ref_text = 'BASELINE' if kind == 'verdict' else 'full period' if kind == 'coverage' else '-'
        entries.append((label, ref_text, texts, 1 if caused else 0))
    _matrix_tables(payload, results, 'ScriptedCaseComparison', entries)

def _calculation_runs(payload, results, request):
    """Evidence of every calculation: what ran, against which reference, for how long, and what was reused."""
    order = 0
    by_id = {result['id']: result for result in results}
    for result in results:
        order += 1
        labels = result['labels']
        kind = 'REFERENCE' if result['id'] == REFERENCE_ID else 'CASE'
        provenance = result.get('provenance', 'CALCULATED')
        payload['ScriptedCalculationRuns'].append({
            'run_order': order, 'run_id': result['id'], 'run_kind': kind if provenance == 'CALCULATED' else kind + ' (reused)',
            'case_name': _result_name(result), 'reference_text': _reference_text(request) if kind == 'REFERENCE' else REFERENCE_ID if find_reference(results) else 'none',
            'period_text': period_text(labels[0], labels[-1]) if labels else '-', 'time_steps': len(labels),
            'elapsed_text': '{:.1f} s'.format(result['elapsed']) if result.get('elapsed') is not None and provenance == 'CALCULATED' else '-',
            'status': result['status'], 'provenance_text': provenance, 'result_object': result.get('result_object') or '-',
            'note': result.get('run_note') or result.get('message') or '-'})
    for plan in request.get('cases') or ():
        if plan['id'] in by_id:
            continue
        order += 1
        payload['ScriptedCalculationRuns'].append({
            'run_order': order, 'run_id': plan['id'], 'run_kind': 'NOT RUN', 'case_name': plan['name'], 'reference_text': '-',
            'period_text': '-', 'time_steps': 0, 'elapsed_text': '-', 'status': plan['status'], 'provenance_text': 'NOT CALCULATED',
            'result_object': '-', 'note': plan.get('reason') or '-'})

def _enforce_table_limits(payload):
    for name in sorted(payload):
        if name == 'ScriptedModelQuality':
            continue
        rows = payload[name]
        limit = MAX_TABLE_ROWS
        if len(rows) <= limit:
            continue
        total = len(rows)
        del rows[limit:]
        _quality(payload, 'table_limit_' + name, 'Table limit ' + name, 'FAIL',
                 '{} rows generated, {} published. The report is incomplete; reduce the number of cases or the model scope (MAX_TABLE_ROWS).'.format(total, limit))

def coverage_statement(results, request):
    start_end = ''
    reference = find_reference(results)
    if reference is not None and reference['labels']:
        start_end = ' ({})'.format(period_text(reference['labels'][0], reference['labels'][-1]))
    return ('Statement A, effect of the planned outages: each case is compared with Reference inside its outage windows and wherever it '
            'differs from it; a case with results for less than its outage time is never reported free of violations. '
            'Statement B, absolute network state over the simulated period{}: only Reference describes it. A case that adds no '
            'violation does not prove the network permissible over the whole period.'.format(start_end))

def build_cases_payload(study_case, results, project_name, result_name, request, generated_by, run_mode):
    payload = empty_payload()
    request = request or {}
    enforce_common_time_axis(results)
    ok = converged(results)
    labels = ok[0]['labels'] if ok else results[0]['labels'] if results else []
    plot_times = ok[0]['plot_times'] if ok else []
    start = labels[0] if labels else ''
    end = labels[-1] if labels else ''
    time_step = ''
    if len(plot_times) >= 2:
        time_step = format_time_step(plot_times[1] - plot_times[0])
    reference = find_reference(results)
    cases = outage_cases(results)
    radar_note = ''
    if len(cases) > CASE_SLOTS:
        radar_note = 'Charts show the first {} of {} cases; every table lists all of them.'.format(CASE_SLOTS, len(cases))
    payload['ScriptedReportMeta'].append({
        'study_id': object_name(study_case), 'study_name': object_name(study_case), 'study_description': object_description(study_case),
        'model_name': project_name, 'model_version': 'PowerFactory 2026', 'simulation_start': start, 'simulation_end': end,
        'simulation_time_step': time_step or 'ElmRes row interval', 'generation_date': datetime.now().astimezone().strftime('%Y-%m-%d %H:%M'),
        'generated_by': generated_by, 'run_mode': run_mode, 'template_name': TEMPLATE_NAME, 'template_version': TEMPLATE_VERSION,
        'data_contract_version': DATA_CONTRACT_VERSION, 'result_name': result_name,
        'assessment_scope': '{} planning case(s); reference: {}; {}'.format(len(request.get('cases') or ()), reference['name'] if reference else 'none', grid_scope_text()),
        'assessment_status': 'PRE-ASSESSMENT - NOT AN OPERATIONAL RELEASE', 'voltage_limits': voltage_limits_text(),
        'has_cases': '1' if cases else '0', 'chart_cases': str(1 + min(len(cases), CASE_SLOTS) if reference is not None else min(len(cases), CASE_SLOTS)),
        'radar_note': radar_note, 'case_source_text': request.get('source_text') or 'not stated', 'reference_text': _reference_text(request),
        'qds_mode_text': qds_mode_text(request), 'coverage_statement': coverage_statement(results, request)})
    _case_rows(payload, results, request)
    records = request.get('records') or []
    used = {record['key'] for plan in request.get('cases') or () for record in plan['members']}
    _quality(payload, 'planned_outages', 'Planned outages', 'PASS' if used else 'WARNING',
             '{} found; {} assigned to a planning case; {} not calculated.'.format(len(records), len(used), len(records) - len(used)))
    _model_quality(payload, results, request)
    _case_metrics(payload, results)
    _pies(payload, results)
    _reference_exceeded(payload, results)
    _case_counts(payload, results)
    _radar(payload, results)
    _line_bars(payload, results)
    _trends(payload, results)
    _case_comparison(payload, results)
    _calculation_runs(payload, results, request)
    _top_lines_by_case(payload, results)
    _loading_appendix(payload, results, 'line', 'ScriptedAppendixLine')
    _loading_appendix(payload, results, 'transformer', 'ScriptedAppendixTransformer')
    _voltage_appendix(payload, results)
    _enforce_table_limits(payload)
    return payload

def coerce_value(value, kind, where, field=None):
    if value is None:
        return None
    if kind == 'string':
        return clip_text(value, text_limit(field) if field else MAX_TEXT_LENGTH)
    if type(value) is bool:
        raise ValueError(where + ': boolean is not a numeric value')
    if kind == 'integer':
        numeric = finite_number(value)
        if numeric is None or not numeric.is_integer():
            raise ValueError(where + ': invalid integer ' + repr(value))
        result = int(numeric)
        if not -2 ** 31 <= result < 2 ** 31:
            raise ValueError(where + ': integer outside 32-bit range')
        return result
    if kind == 'number':
        result = finite_number(value)
        if result is None:
            raise ValueError(where + ': invalid finite number ' + repr(value))
        return result
    raise ValueError(where + ': unsupported type ' + repr(kind))

def api_error_code(value):
    if value is None:
        return None
    if isinstance(value, (tuple, list)):
        value = value[0] if value else None
    code = finite_number(value)
    if code is None or code == 0.0:
        return None
    return code

def validate_payload(payload):
    expected = {name for name, _ in TABLES}
    if set(payload) != expected:
        raise ValueError('Internal table declaration and payload do not match.')
    if set(REQUIRED_FIELDS) != expected:
        raise ValueError('Required-field declaration does not cover all tables.')
    for name, fields in TABLES:
        rows = payload[name]
        if not isinstance(rows, list):
            raise ValueError(name + ': rows must be a list')
        if name == 'ScriptedReportMeta' and len(rows) != 1:
            raise ValueError(name + ': exactly one row is required')
        field_names = {field for field, _ in fields}
        for index, row in enumerate(rows):
            unknown = set(row) - field_names
            if unknown:
                raise ValueError(name + ': unknown fields ' + repr(sorted(unknown)))
            required = REQUIRED_FIELDS[name]
            for field, kind in fields:
                where = '{} row {}.{}'.format(name, index, field)
                if field in row and row[field] is not None:
                    row[field] = coerce_value(row[field], kind, where, field)
                if field not in required:
                    continue
                value = row.get(field)
                if value is None:
                    raise ValueError(where + ': required field is missing')
                if kind == 'string' and (not str(value).strip()):
                    raise ValueError(where + ': required text is empty')
    for table in TREND_TABLES:
        if len({row.get('element_name') for row in payload[table]}) > 1:
            raise ValueError('{} mixes several elements in one chart.'.format(table))

def _check(returned, context):
    code = api_error_code(returned)
    if code is not None:
        raise RuntimeError('{} returned error code {:g}'.format(context, code))

def publish_report(report, payload, log=None):
    started = time.monotonic()
    last_message = started

    def emit(message):
        nonlocal last_message
        if log:
            log(message)
        last_message = time.monotonic()

    def heartbeat(phase, table, completed, total, unit, rows=None):
        # Stay on the PowerFactory thread. A blocking API call must return
        # before progress can be reported; this is not a background timer.
        if not log:
            return
        now = time.monotonic()
        if now - last_message < PUBLICATION_LOG_INTERVAL_SECONDS:
            return
        row_progress = '{} / {} rows complete; '.format(*rows) if rows else ''
        emit('Publication heartbeat: {} [{}]; {}{} / {} {}; '
             '{:.1f}s since publication started.'.format(
                 table, phase, row_progress, completed, total, unit,
                 now - started))

    emit('Validating report tables before publication.')
    validate_payload(payload)
    emit('Report table validation completed in {:.1f}s.'.format(
        time.monotonic() - started))
    if report is None or class_name(report) != 'IntReport':
        raise RuntimeError('Run this ComPython as a child of an IntReport.')
    for method in ('Reset', 'CreateTable', 'CreateField', 'SetValue'):
        if not callable(getattr(report, method, None)):
            raise RuntimeError('IntReport is missing method ' + method)
    cell_counts = {
        name: sum(row.get(field) is not None
                  for row in payload[name] for field, _ in fields)
        for name, fields in TABLES
    }
    total_cells = sum(cell_counts.values())
    total_rows = sum(len(rows) for rows in payload.values())
    emit('Publishing {} validated report tables: {} rows, {} cell writes. '
         'Progress interval: {:g}s between API calls; a blocking call can '
         'delay the next message.'.format(
             len(TABLES), total_rows, total_cells,
             PUBLICATION_LOG_INTERVAL_SECONDS))
    context = 'Reset'
    try:
        emit('Resetting report database.')
        reset_started = time.monotonic()
        report.Reset()
        emit('Report database reset completed in {:.1f}s.'.format(
            time.monotonic() - reset_started))
        for table_index, (name, fields) in enumerate(TABLES, 1):
            if not name.startswith(HOST_TABLE_PREFIX):
                raise ValueError('Table lacks host prefix: ' + name)
            native_name = name[len(HOST_TABLE_PREFIX):]
            row_count = len(payload[name])
            cell_count = cell_counts[name]
            emit('Table {}/{}: {} -> {}: {} rows, {} cell writes; '
                 'creating table.'.format(
                     table_index, len(TABLES), native_name, name,
                     row_count, cell_count))
            table_started = time.monotonic()
            context = 'CreateTable({})'.format(native_name)
            _check(report.CreateTable(native_name), context)
            emit('Table {} created in {:.1f}s; creating {} fields.'.format(
                native_name, time.monotonic() - table_started, len(fields)))
            fields_started = time.monotonic()
            for field_index, (field, kind) in enumerate(fields, 1):
                context = 'CreateField({}.{})'.format(native_name, field)
                _check(report.CreateField(native_name, field, FIELD_TYPES[kind]), context)
                heartbeat('CREATE FIELDS', native_name, field_index,
                          len(fields), 'fields')
            emit('Table {} fields created in {:.1f}s; writing {} cells.'.format(
                native_name, time.monotonic() - fields_started, cell_count))
            write_started = time.monotonic()
            written = 0
            for index, row in enumerate(payload[name]):
                for field, _ in fields:
                    value = row.get(field)
                    if value is None:
                        continue
                    context = 'SetValue({}.{}, row {})'.format(native_name, field, index)
                    _check(report.SetValue(native_name, field, index, value), context)
                    written += 1
                    heartbeat('WRITE CELLS', native_name, written, cell_count,
                              'cells', rows=(index, row_count))
            write_seconds = time.monotonic() - write_started
            rate = '{:.1f} cells/s'.format(written / write_seconds) if written and write_seconds > 0 else 'n/a'
            emit('GridLens: {} -> {}: {} rows, {} cells; writes {:.1f}s '
                 '({}); table total {:.1f}s.'.format(
                     native_name, name, row_count, written, write_seconds,
                     rate, time.monotonic() - table_started))
    except Exception as exc:
        try:
            report.Reset()
        except Exception:
            pass
        raise RuntimeError('GridLens publication failed at ' + context) from exc
    emit('Publication finished: {} tables, {} rows, {} cells in {:.1f}s.'.format(
        len(TABLES), total_rows, total_cells, time.monotonic() - started))
    return {name: len(rows) for name, rows in payload.items()}


TOTAL_STEPS = 7
# Only planned outages are read. IntOutage is PowerFactory's obsolete outage
# class, which also holds demand transfers (load moved between loads); those
# switch no equipment out of service and are no outage case.
OUTAGE_CLASSES = ("IntPlannedout",)
# PowerFactory describes this ComStatsim option as "Planned Outages". Setting
# it is how planned outages are applied; IntPlannedout exposes no Apply method.
PLANNED_OUTAGE_OPTION = "iopt_maint"
OUTAGE_CONSIDERED = "CONSIDERED"
ASSESSMENT_OK = "NO LIMIT EXCEEDED"
ASSESSMENT_PREEXISTING = "NO ADDITIONAL VIOLATION"
ASSESSMENT_LOADING = "OVERLOAD"
ASSESSMENT_VOLTAGE = "VOLTAGE BAND"
ASSESSMENT_BOTH = "OVERLOAD + VOLTAGE BAND"
ASSESSMENT_SKIPPED = "NOT SIMULATED"
ASSESSMENT_NO_DATA = "NO RESULT DATA IN WINDOW"
ASSESSMENT_NOT_EVALUATED = "NOT EVALUATED"
ASSESSMENT_DEENERGIZED = "DE-ENERGISED NODES"
ASSESSMENT_INCOMPLETE = "INCOMPLETE COVERAGE"
ASSESSMENT_CAUSED = (ASSESSMENT_LOADING, ASSESSMENT_VOLTAGE, ASSESSMENT_BOTH)
ASSESSMENT_ATTENTION = (ASSESSMENT_PREEXISTING, ASSESSMENT_DEENERGIZED, ASSESSMENT_INCOMPLETE)
PLAN_READY = "READY"
PLAN_NOT_SIMULATED = "NOT SIMULATED"
PLAN_NOT_EVALUATED = "NOT EVALUATED"
LOADING_CATEGORIES = ("line", "transformer")
OUTAGE_SKIPPED = "SKIPPED"
OUTAGE_START_ATTRIBUTES = (
    "starttime", "tStart", "t_start", "date_start", "time_start")
OUTAGE_END_ATTRIBUTES = (
    "endtime", "tEnd", "t_end", "date_end", "time_end")
# PowerFactory labels IntPlannedout.components "Components"; it holds the
# equipment the outage switches. The remaining names are legacy fallbacks.
OUTAGE_EQUIPMENT_ATTRIBUTES = (
    "components", "p_target", "pTarget", "pObject", "p_object", "obj_id",
    "pDevice", "cpObject", "pElm", "p_target1", "p_target2")
# ComStatsim carries the simulated period as epoch seconds.
QDS_PERIOD_ATTRIBUTES = (("startTime", "endTime"), ("starttime", "endtime"))
REFERENCE_CASE_ID = "REF"
OUTAGE_CASE_PREFIX = "OUT"
QDS_CORE_SETTINGS = (
    ("Time period", "calcPeriod"),
    ("Step size", "stepSize"),
    ("Step unit", "stepUnit"),
)
QDS_OPTION_ATTRIBUTES = (
    "iopt_asht", "iopt_at", "iopt_circ", "iopt_cont", "iopt_ctrl",
    "iopt_event", "iopt_fast", "iopt_lim", "iopt_lod", "iopt_method",
    "iopt_net", "iopt_plim", "iopt_pq", "iopt_prot", "iopt_show",
    "iopt_stamode", "iopt_tem", "iopt_time",
)


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


class RunStats:
    """Time and calls per service and the number of calculations of one run, for the summary at its end."""

    # Order of the summary; services not listed follow in the order they were first used.
    COUNT_LABELS = (
        ('qds_runs', 'QDS runs (ComStatsim.Execute)'), ('qds_steps', 'QDS time steps calculated'),
        ('reused_cases', 'cases reused without a QDS run'), ('series', 'result series read'),
        ('values', 'result values read'), ('n1_created', 'contingency analyses created'),
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


def log_run_summary(logger, stats=None):
    """The time per service and the number of calculations, at the end of every run (also a failed one)."""
    stats = stats or RUN_STATS
    logger.section("RUN SUMMARY · time per service and calculations")
    logger.table(("Service", "Calls", "Time [s]", "Share"), stats.rows())
    counted = stats.count_rows()
    if counted:
        logger.detail("")
        logger.table(("Calculations", "Number"), counted)


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


def _same_object(left, right):
    if left is right:
        return True
    if left is None or right is None:
        return False
    return object_key(left) == object_key(right)


def _set_attribute(obj, name, value):
    try:
        setattr(obj, name, value)
    except Exception:
        setter = getattr(obj, "SetAttribute", None)
        if not callable(setter):
            return False
        setter(name, value)
    return _same_object(safe_attr(obj, name), value)


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


# ---------------------------------------------------------------------------
# Planning cases and time planner
#
# A planned outage object (IntPlannedout) is one occurrence: one execution of
# a technical outage with its own window. Occurrences that switch the same
# components belong to the same technical outage (definition). A planning case
# is a set of occurrences the engineer assigns; PowerFactory applies each of
# them in its own window, so one case passes through several network states.
# Everything in this section is read-only and runs before any calculation.
# ---------------------------------------------------------------------------
# Case ids end up in ElmRes names, which PowerFactory keeps short; a dot
# would read as the class separator of a PowerFactory name.
CASE_ID_PATTERN = re.compile(r'^[A-Za-z0-9_-]{1,16}$')
RULE_KINDS = ('not_overlap', 'order', 'together')
# Two occurrences of a case, (start, end) half-open; the code names the
# sequence of active sets in the documentation (docs/ARCHITECTURE.md).
INTERVAL_RELATIONS = {
    'T01': 'first ends before second starts', 'T02': 'second ends before first starts',
    'T03': 'first ends when second starts', 'T04': 'second ends when first starts',
    'T05': 'first starts earlier, both overlap', 'T06': 'second starts earlier, both overlap',
    'T07': 'same start, first ends earlier', 'T08': 'same start, second ends earlier',
    'T09': 'first inside second', 'T10': 'second inside first',
    'T11': 'same end, first starts later', 'T12': 'same end, second starts later',
    'T13': 'identical windows'}


class GridLensCancelled(GridLensError):
    """The engineer cancelled the case manager; nothing was calculated or changed."""


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


def per_outage_config(candidates, project_key=''):
    """The 7.x behaviour as a configuration: one case per planned outage in the simulated period."""
    config = empty_case_config(project_key)
    for number, record in enumerate(candidates, 1):
        config['cases'].append({'id': '{}{:02d}'.format(OUTAGE_CASE_PREFIX, number), 'name': record['name'],
                                'description': 'Only planned outage {} applied.'.format(record['name']),
                                'outages': [record['key']]})
    return config


def per_outage_request(records, candidates, period=(None, None), project_key=''):
    request = resolve_request(per_outage_config(candidates, project_key), records, period, 'per_outage',
                              'one case per planned outage in the simulated period')
    request['skipped'] = [record for record in records if record not in candidates]
    for plan, record in zip(request['cases'], candidates):
        record['case_id'] = plan['id']
    return request


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


def preview_text(request, period=(None, None)):
    """What OK would calculate, as plain text for the case manager and the log."""
    lines = ['Reference: {}'.format(_reference_text(request)),
             'Simulated period: {} to {}'.format(_format_pf_time(period[0]) or '?', _format_pf_time(period[1]) or '?'), '']
    ready = [plan for plan in request['cases'] if plan['status'] == PLAN_READY]
    groups = {}
    for plan in ready:
        groups.setdefault(plan['fingerprint'], []).append(plan['id'])
    reference = setting_value('run_reference', request.get('settings') or {})
    runs = len(groups) + (1 if reference else 0)
    lines.append('{} case(s), {} ready; QDS runs: {} ({} reference){}.'.format(
        len(request['cases']), len(ready), runs, 1 if reference else 0,
        '; identical cases calculated once: ' + ', '.join('/'.join(ids) for ids in groups.values() if len(ids) > 1)
        if any(len(ids) > 1 for ids in groups.values()) else ''))
    for plan in request['cases']:
        lines.append('')
        lines.append('[{}] {} - {}'.format(plan['id'], plan['name'], plan['status']))
        for record in plan['members']:
            start, end = plan['windows'][record['key']]
            lines.append('   {}  {}'.format(record['name'], period_text(_format_pf_time(start), _format_pf_time(end)) or 'unknown window'))
        for left, right, code in plan['relations']:
            lines.append('   {} / {}: {} ({})'.format(left, right, code, INTERVAL_RELATIONS[code]))
        if plan['states']:
            lines.append('   network states: ' + states_text(plan))
        for warning in plan['warnings']:
            lines.append('   warning: ' + warning)
        if plan['reason']:
            lines.append('   ' + plan['reason'])
    return '\n'.join(lines)


# ---------------------------------------------------------------------------
# Case manager dialog (tkinter / ttk, standard library only)
#
# Configuration only: the dialog reads the planned outages GridLens already
# collected and edits a configuration dictionary. It writes nothing into
# PowerFactory. Every QDS starts after the dialog is closed.
# ---------------------------------------------------------------------------
class CaseManagerUnavailable(GridLensError):
    """tkinter or Tcl/Tk cannot open a window in this PowerFactory installation."""


# The first column of the outage list is a check box: ticked = in the selected case.
MARK_IN_CASE, MARK_FIXED, MARK_FREE = '\u2611 in case', 'fixed', '\u2610'
RULE_LABELS = (('not_overlap', 'must not overlap'), ('order', 'second only after the first'), ('together', 'only together'))
OUTAGE_FILTERS = ('All planned outages', 'Not in this case', 'In simulated period', 'Ignored in PowerFactory')

# Keys of the case manager: (key sequence, where, what). Delete and BackSpace
# both work, so the key labelled "delete" on any keyboard does it.
KEYBOARD_SHORTCUTS = (
    ('Delete / BackSpace', 'case list', 'delete the selected case (asks first)'),
    ('Delete / BackSpace', 'outages of the case', 'remove the selected outages from the case'),
    ('Delete / BackSpace', 'fixed background outages', 'remove the selected outages from the fixed background'),
    ('Delete / BackSpace', 'rules', 'remove the selected rules'),
    ('Space', 'case list', 'switch the Run flag of the focused case'),
    ('Space', 'available outages', 'tick or untick the focused outage'),
    ('Enter', 'available outages', 'add all selected outages to the case'),
    ('F2 / Enter', 'case list', 'rename the case in place'),
    ('Ctrl+A', 'any table', 'select every shown row'),
    ('Ctrl+N', 'window', 'new case'),
    ('Ctrl+F', 'window', 'search the available outages'),
    ('Ctrl+S', 'window', 'save configuration'),
    ('Ctrl+O', 'window', 'load saved configuration'),
    ('Ctrl+Enter', 'window', 'start calculation'),
    ('Escape', 'window', 'end an in-place edit, otherwise cancel'),
)

SETTINGS_INTRO = ('Limits and classification parameters (category A) only interpret calculated results; they never '
                  'change a load flow, a rating or the network model. Calculation parameters (category B) stay read '
                  'only until the PowerFactory contingency interface is verified. Settings are stored provisionally '
                  'in the case configuration file of this project, not yet inside the PowerFactory project.')
CONTINGENCIES_NOT_READ = 'not read'
N1_NOTE = ("Calculated with the contingency analysis (ComSimoutage) of the active study case, at the QDS time steps "
           "inside the outage windows of each case. Until the report chapters for n-1 exist (part 4), the result "
           "appears in the log and on the Model Quality Assurance page.")
# Hover texts of the case manager. They explain what a control does to the
# calculation; the operating guide (docs/CASE_MANAGER.md) says the same.
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
# Hover texts of the Settings tab, per setting; a read-only setting adds why it is read only.
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

    def __init__(self, records, config, period, qds_text='', qds_info=None, grids=None, contingencies=CONTINGENCIES_NOT_READ):
        self.records = list(records)
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
        lines = ['Assessment: ' + assessments_text(self.config.get('assessments')),
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
    HEADER_HEIGHT, FILTER_HEIGHT = 28, 30

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

    BACKGROUND, CARD, TEXT, MUTED = '#eef3f7', '#ffffff', '#1c3244', '#5c7082'
    ACCENT, ACCENT_ACTIVE, SELECTED, PROBLEM = '#276a89', '#1b4e68', '#dcecf4', '#a83030'
    HEADER, FILTER, BORDER = '#e7eef4', '#f5f8fa', '#d0dce5'
    MASTHEAD, MASTHEAD_MUTED, INSET = '#18384c', '#c7d8e4', '#f0f6fa'
    FIXED, OVERLAP, GAP = '#8a94a3', '#dbe6f5', '#eceff3'
    TAB_CASES, TAB_SETTINGS = 'Case Manager', 'Settings'
    SETTINGS_PAGES = (('Network scope', ('Network scope',)), ('Limits', ('Thermal limits', 'Voltage limits')),
                      ('Classification', ('Classification',)), ('Report and run', ('Report', 'Run')),
                      ('Contingency analysis', ('Contingency analysis',)))
    PAGE_TIME, PAGE_FIXED = 'QDS time base', 'Fixed background & rules'

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
        root.geometry(window_geometry(root.winfo_screenwidth(), root.winfo_screenheight()))
        root.minsize(*minimum_window_size(root.winfo_screenwidth(), root.winfo_screenheight()))
        root.configure(background=self.BACKGROUND)
        root.columnconfigure(0, weight=1)
        root.rowconfigure(1, weight=1)
        masthead = ttk.Frame(root, style='Masthead.TFrame', padding=(18, 12))
        masthead.grid(row=0, column=0, sticky='ew')
        masthead.columnconfigure(1, weight=1)
        ttk.Label(masthead, text='GridLens', style='Brand.TLabel').grid(row=0, column=0, rowspan=2, sticky='w', padx=(0, 22))
        ttk.Label(masthead, text='Planning case manager', style='MastheadTitle.TLabel').grid(row=0, column=1, sticky='w')
        ttk.Label(masthead, text='Build independent cases. Check the settings. Start the calculation.',
                  style='MastheadHint.TLabel').grid(row=1, column=1, sticky='w', pady=(2, 0))
        self.notebook = ttk.Notebook(root)
        self.notebook.enable_traversal()
        self.notebook.grid(row=1, column=0, sticky='nsew', padx=14, pady=(12, 0))
        self.cases_tab = ttk.Frame(self.notebook, padding=(0, 8, 0, 0))
        self.settings_tab = ttk.Frame(self.notebook, padding=(0, 8, 0, 0))
        self.notebook.add(self.cases_tab, text=self.TAB_CASES)
        self.notebook.add(self.settings_tab, text=self.TAB_SETTINGS)
        self._build_case_manager(self.cases_tab)
        self._build_settings(self.settings_tab)
        bottom = ttk.Frame(root, padding=(14, 6, 14, 12))
        bottom.grid(row=2, column=0, sticky='ew')
        bottom.columnconfigure(2, weight=1)
        self.status_line = self._wrapped_label(bottom, '', style='Status.TLabel', row=0, column=0,
                                               columnspan=5, pady=(0, 6))
        self.status_line.configure(cursor='hand2')
        self.status_line.bind('<Button-1>', lambda _event: self.notebook.select(self.cases_tab))
        self.tip(self.status_line, HELP_TEXTS['status_line'])
        for column, (text, command, key, style) in enumerate((
                ('Save configuration', self.save, 'save', 'TButton'), ('Load saved configuration', self.load_saved, 'load', 'TButton'),
                (None, None, None, None), ('Cancel', self.cancel, 'cancel', 'TButton'),
                ('Start calculation', self.start, 'start', 'Accent.TButton'))):
            if text is None:
                continue
            button = ttk.Button(bottom, text=text, style=style, command=command)
            button.grid(row=1, column=column, padx=(0, 8) if column in (0, 3) else 0)
            self.tip(button, HELP_TEXTS[key])
        root.protocol('WM_DELETE_WINDOW', self.cancel)
        root.bind('<Escape>', self.on_escape)
        self._bind_window_keys()
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
        self.body_font = (family, 10)
        self.bold_font = (family, 10, 'bold')
        style.configure('.', background=self.BACKGROUND, foreground=self.TEXT, font=(family, 10))
        style.configure('TFrame', background=self.BACKGROUND)
        style.configure('Card.TFrame', background=self.CARD)
        style.configure('Inset.TFrame', background=self.INSET)
        style.configure('Masthead.TFrame', background=self.MASTHEAD)
        style.configure('Brand.TLabel', background=self.MASTHEAD, foreground=self.CARD, font=(family, 19, 'bold'))
        style.configure('MastheadTitle.TLabel', background=self.MASTHEAD, foreground=self.CARD, font=(family, 11, 'bold'))
        style.configure('MastheadHint.TLabel', background=self.MASTHEAD, foreground=self.MASTHEAD_MUTED, font=(family, 10))
        style.configure('TLabel', background=self.CARD, foreground=self.TEXT)
        style.configure('Inset.TLabel', background=self.INSET, foreground=self.TEXT)
        style.configure('InsetTitle.TLabel', background=self.INSET, foreground=self.ACCENT, font=(family, 10, 'bold'))
        style.configure('Optional.TLabel', background=self.HEADER, foreground=self.MUTED, padding=(7, 3), font=(family, 9))
        style.configure('Muted.TLabel', background=self.CARD, foreground=self.MUTED)
        style.configure('Link.TLabel', background=self.CARD, foreground=self.ACCENT)
        style.configure('Status.TLabel', background=self.BACKGROUND, foreground=self.MUTED)
        style.configure('Title.TLabel', background=self.CARD, font=(family, 12, 'bold'))
        style.configure('Section.TLabel', background=self.CARD, font=(family, 10, 'bold'))
        style.configure('Problem.TLabel', background=self.CARD, foreground=self.PROBLEM)
        style.configure('TLabelframe', background=self.CARD, bordercolor=self.BORDER)
        style.configure('TLabelframe.Label', background=self.CARD, foreground=self.TEXT, font=(family, 10, 'bold'))
        style.configure('TCheckbutton', background=self.CARD, focuscolor=self.ACCENT)
        style.map('TCheckbutton', background=[('active', self.INSET)])
        style.configure('TButton', padding=(10, 6), background=self.CARD, bordercolor=self.BORDER, focuscolor=self.ACCENT)
        style.map('TButton', background=[('active', self.HEADER)], bordercolor=[('focus', self.ACCENT)])
        style.configure('Accent.TButton', background=self.ACCENT, foreground=self.CARD, padding=(18, 7), font=(family, 10, 'bold'))
        style.map('Accent.TButton', background=[('active', self.ACCENT_ACTIVE), ('disabled', '#9aa5b1')])
        style.configure('TNotebook', background=self.BACKGROUND, borderwidth=0, tabmargins=(0, 0, 0, 0))
        style.configure('TNotebook.Tab', padding=(18, 9), font=(family, 10), background=self.BACKGROUND, foreground=self.MUTED)
        style.map('TNotebook.Tab', background=[('selected', self.CARD)], foreground=[('selected', self.TEXT)],
                  font=[('selected', (family, 10, 'bold'))])
        style.configure('Filter.TEntry', fieldbackground=self.CARD, padding=(4, 1))
        style.configure('Invalid.TEntry', fieldbackground='#fbe4e4', foreground=self.PROBLEM)
        style.configure('Source.TLabel', background=self.CARD, foreground=self.MUTED, font=(family, 9))
        style.configure('User.TLabel', background=self.CARD, foreground=self.ACCENT, font=(family, 9, 'bold'))
        style.configure('Filter.TCombobox', fieldbackground=self.CARD, padding=(4, 1))
        style.configure('Treeview', rowheight=26, background=self.CARD, fieldbackground=self.CARD, borderwidth=0,
                        lightcolor=self.CARD, darkcolor=self.CARD)
        style.configure('Vertical.TScrollbar', arrowsize=12, background=self.HEADER, troughcolor=self.FILTER, borderwidth=0)
        style.map('Treeview', background=[('selected', self.SELECTED)], foreground=[('selected', self.TEXT)])

    def _card(self, parent, **grid):
        frame = self.ttk.Frame(parent, style='Card.TFrame', padding=14)
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

    # --- tab "Case Manager" ------------------------------------------------------
    def _build_case_manager(self, tab):
        """The three panes on top; the calculation choice, problems and preview below them."""
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(0, weight=1)
        workspace = self.ttk.Frame(tab)
        workspace.grid(row=0, column=0, sticky='nsew')
        self._build_workspace(workspace)
        strip = self.ttk.Frame(tab)
        strip.grid(row=1, column=0, sticky='nsew', pady=(8, 0))
        self._build_calculation(strip)

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
        ttk = self.ttk
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
            ('enabled', 'Run', 42, False, (('included', '\u2611'), ('excluded', '\u2610'))),
            ('name', 'Planning case', 150, True, None), ('count', 'Outages', 56, False, None),
            ('status', 'Status', 100, False, ('ready', 'not calculated', 'excluded'))), height=6, selectmode='browse',
            tips={'enabled': HELP_TEXTS['enabled'], 'name': COLUMN_HELP['case_name'], 'count': COLUMN_HELP['case_count'], 'status': COLUMN_HELP['case_status']})
        self.case_table.grid(row=1, column=0, sticky='nsew')
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
            self.case_buttons[label] = ttk.Button(buttons, text=label, command=command)
            self.case_buttons[label].grid(row=0, column=column, sticky='ew', padx=1)
            self.tip(self.case_buttons[label], HELP_TEXTS[label])
        per_outage = ttk.Button(pane, text='One case per planned outage', command=self.one_case_per_outage)
        per_outage.grid(row=3, column=0, sticky='ew', pady=(4, 8))
        self.tip(per_outage, HELP_TEXTS['one_per_outage'])
        self._wrapped_label(pane, 'Run: ☑ included · ☐ excluded. Click the flag or press Space. '
                            'Excluded cases stay saved but are omitted from calculation and report.',
                            row=4, column=0, pady=(2, 0))

    def _build_case_outages(self, pane):
        tk, ttk = self.tk, self.ttk
        pane.columnconfigure(0, weight=1)
        pane.rowconfigure(2, weight=3, minsize=170)
        pane.rowconfigure(4, weight=2, minsize=90)
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
        self._bind_delete(self.member_tree, self.remove_selected)
        buttons = ttk.Frame(pane, style='Card.TFrame')
        buttons.grid(row=3, column=0, sticky='ew', pady=(6, 8))
        remove = ttk.Button(buttons, text='Remove from case', command=self.remove_selected)
        remove.grid(row=0, column=0, padx=(0, 6))
        details = ttk.Button(buttons, text='Details', command=lambda: self.show_details(self.member_tree))
        details.grid(row=0, column=1)
        self.tip(remove, HELP_TEXTS['remove'])
        self.tip(details, HELP_TEXTS['details'])
        buttons.columnconfigure(2, weight=1)
        hint = ttk.Label(buttons, text='Removes only the assignment.', style='Muted.TLabel', wraplength=150)
        hint.grid(row=0, column=2, sticky='w', padx=(10, 0))
        timeline = ttk.Labelframe(pane, text='Timeline of the case (planning check only, no results)', padding=6)
        timeline.grid(row=4, column=0, sticky='nsew')
        timeline.columnconfigure(0, weight=1)
        timeline.rowconfigure(1, weight=1)
        self.tip(timeline, HELP_TEXTS['timeline'])
        legend = self._wrapped_label(timeline, 'Blue: case outage · Grey: shared outage · Shaded: overlapping windows · Light band: shortened gap',
                                     row=0, column=0, columnspan=2, pady=(0, 4))
        self.tip(legend, HELP_TEXTS['timeline'])
        self.canvas = tk.Canvas(timeline, height=70, background=self.CARD, highlightthickness=0)
        scroll = ttk.Scrollbar(timeline, orient='vertical', command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=scroll.set)
        self.canvas.grid(row=1, column=0, sticky='nsew')
        scroll.grid(row=1, column=1, sticky='ns')
        self.canvas.bind('<Configure>', lambda _event: self.draw_timeline())

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
        self._wrapped_label(pane, 'Tick to add an outage to the selected case; untick to remove it. '
                            '"Add to case" or Enter adds all selected rows.', row=3, column=0, pady=(6, 0))

    # --- tab "Fixed background & rules" -------------------------------------------
    def _build_fixed_and_rules(self, tab):
        ttk = self.ttk
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
        strip.columnconfigure(1, weight=1)
        options = self._card(strip, row=0, column=0, sticky='nsew', padx=(0, 4))
        ttk.Label(options, text='Calculation', style='Title.TLabel').grid(row=0, column=0, sticky='w', pady=(0, 4))
        # n-0 (the QDS of REF and every case) is always calculated, so it has no control here.
        self.n1_var = tk.BooleanVar(value=N1_REFERENCE in self.editor.config['assessments'])
        self.n1_prime_var = tk.BooleanVar(value=N1_PRIME in self.editor.config['assessments'])
        n1 = ttk.Checkbutton(options, text='n-1 - reference contingency analysis', variable=self.n1_var,
                             command=self.apply_assessments)
        n1.grid(row=2, column=0, sticky='w')
        self.tip(n1, HELP_TEXTS['n1'])
        prime = ttk.Checkbutton(options, text="(n-1)' - contingency analysis with planned-outage scenarios",
                                variable=self.n1_prime_var, command=self.apply_assessments)
        prime.grid(row=3, column=0, sticky='w')
        self.tip(prime, HELP_TEXTS['n1_prime'])
        note = ttk.Label(options, text="n-1 and (n-1)': results in the log and on the QA page until part 4",
                         style='Muted.TLabel')
        note.grid(row=4, column=0, sticky='w', padx=(22, 0))
        self.tip(note, N1_NOTE)
        footer = ttk.Frame(options, style='Card.TFrame')
        footer.grid(row=5, column=0, sticky='ew', pady=(6, 0))
        footer.columnconfigure(0, weight=1)
        qds = ttk.Label(footer, text='QDS: ' + self.editor.qds_text, style='Section.TLabel')
        qds.grid(row=0, column=0, sticky='w')
        self.tip(qds, HELP_TEXTS['qds'])
        self.preview_button = ttk.Button(footer, text='Show calculation preview', command=self.toggle_preview)
        self.preview_button.grid(row=0, column=1, sticky='e', padx=(10, 0))
        self.tip(self.preview_button, HELP_TEXTS['preview'])
        problems = self._card(strip, row=0, column=1, sticky='nsew', padx=(4, 0))
        problems.columnconfigure(0, weight=1)
        problems.rowconfigure(1, weight=1)
        ttk.Label(problems, text='Problems and warnings', style='Title.TLabel').grid(row=0, column=0, sticky='w', pady=(0, 4))
        self.problem_table = FilterTable(self, problems, (('where', 'Where', 130, False, None), ('problem', 'Problem', 600, True, None)),
                                         height=3)
        self.problem_table.grid(row=1, column=0, sticky='nsew')
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

    # --- tab "Settings" -------------------------------------------------------------
    def _build_settings(self, tab):
        ttk = self.ttk
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(1, weight=1)
        self.settings_book = ttk.Notebook(tab)
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
        self.settings_state = ttk.Label(bar, text='', style='Status.TLabel')
        self.settings_state.grid(row=0, column=3, sticky='w', padx=(8, 0))

    def _scrolled(self, parent):
        """A vertically scrolling frame that fills `parent`; returns the inner frame."""
        canvas = self.tk.Canvas(parent, background=self.BACKGROUND, highlightthickness=0, borderwidth=0)
        scroll = self.ttk.Scrollbar(parent, orient='vertical', command=canvas.yview)
        inner = self.ttk.Frame(canvas)
        window = canvas.create_window(0, 0, anchor='nw', window=inner)
        canvas.configure(yscrollcommand=scroll.set)
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(0, weight=1)
        canvas.grid(row=0, column=0, sticky='nsew')
        scroll.grid(row=0, column=1, sticky='ns')
        inner.bind('<Configure>', lambda _event: canvas.configure(scrollregion=canvas.bbox('all')), add='+')
        canvas.bind('<Configure>', lambda event: canvas.itemconfigure(window, width=event.width), add='+')
        return inner

    def _build_setting_page(self, page, sections):
        ttk = self.ttk
        inner = self._scrolled(page)
        inner.columnconfigure(0, weight=1)
        self._wrapped_label(inner, SETTINGS_INTRO, style='Status.TLabel', row=0, column=0, pady=(0, 6))
        for row, section in enumerate(sections, 1):
            frame = ttk.Labelframe(inner, text=section, padding=10)
            frame.grid(row=row, column=0, sticky='ew', pady=(0, 8), padx=(0, 4))
            if section == 'Network scope':
                self._build_scope_section(frame)
                continue
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
        label = ttk.Label(frame, text=setting['label'])
        label.grid(row=row, column=0, sticky='w', padx=(0, 10), pady=1)
        self.tip(label, help_text)
        variable = tk.StringVar(value='')
        if setting['kind'] == 'choice':
            widget = ttk.Combobox(frame, textvariable=variable, values=[text for _, text in setting['choices']],
                                  state='readonly', width=24)
        else:
            widget = ttk.Entry(frame, textvariable=variable, width=14 if setting['editable'] else 24)
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
        message = ttk.Label(frame, text='', style='Problem.TLabel', wraplength=320)
        message.grid(row=row, column=5, sticky='w')
        self.setting_vars[key], self.setting_inputs[key] = variable, widget
        self.setting_sources[key], self.setting_messages[key] = source, message
        self.fill_setting(key)
        if setting['editable']:
            variable.trace_add('write', lambda *_args, name=key: self.on_setting_edit(name))
        else:
            widget.state(['disabled'])

    def _build_scope_section(self, frame):
        """Grid selections: assessed equipment (applies now) and contingencies (stored and previewed only)."""
        tk, ttk = self.tk, self.ttk
        frame.columnconfigure(0, weight=1, uniform='scope')
        frame.columnconfigure(1, weight=1, uniform='scope')
        self.grid_lists = {}
        left = ttk.Frame(frame, style='Card.TFrame')
        left.grid(row=0, column=0, sticky='nsew', padx=(0, 10))
        right = ttk.Frame(frame, style='Card.TFrame')
        right.grid(row=0, column=1, sticky='nsew')
        for parent in (left, right):
            parent.columnconfigure(0, weight=1)
        title = ttk.Label(left, text="Assessed equipment (n-0 now, n-1 and (n-1)' later)", style='Section.TLabel')
        title.grid(row=0, column=0, columnspan=2, sticky='w')
        self.tip(title, setting_help('monitoring_grids'))
        self._grid_listbox(left, 'monitoring_grids', row=1)
        self.monitoring_note = ttk.Label(left, text='', style='Muted.TLabel', wraplength=340)
        self.monitoring_note.grid(row=2, column=0, columnspan=2, sticky='w', pady=(4, 0))
        buttons = ttk.Frame(left, style='Card.TFrame')
        buttons.grid(row=3, column=0, columnspan=2, sticky='w', pady=(4, 0))
        for column, (text, command) in enumerate((('Select all grids', lambda: self.select_grids('monitoring_grids', True)),
                                                  ('Clear selection', lambda: self.select_grids('monitoring_grids', False)))):
            button = ttk.Button(buttons, text=text, command=command)
            button.grid(row=0, column=column, padx=(0, 6))
            self.tip(button, SETTING_HELP['grid_buttons'])
        title = ttk.Label(right, text='Contingencies: grids of the outaged equipment (category B)', style='Section.TLabel')
        title.grid(row=0, column=0, columnspan=2, sticky='w')
        self.tip(title, setting_help('contingency_grids'))
        self.contingency_mode = tk.StringVar(value='same')
        choices = ttk.Frame(right, style='Card.TFrame')
        choices.grid(row=1, column=0, columnspan=2, sticky='w')
        for column, (value, text) in enumerate((('same', 'Same grids as the assessed equipment'), ('own', 'Own selection'))):
            radio = ttk.Radiobutton(choices, text=text, value=value, variable=self.contingency_mode,
                                    command=self.on_contingency_mode)
            radio.grid(row=0, column=column, padx=(0, 10), sticky='w')
            self.tip(radio, setting_help('contingency_grids'))
        self._grid_listbox(right, 'contingency_grids', row=2)
        self.contingency_note = ttk.Label(right, text='', style='Muted.TLabel', wraplength=340)
        self.contingency_note.grid(row=3, column=0, columnspan=2, sticky='w', pady=(4, 0))
        self.tip(self.contingency_note, SETTING_HELP['contingency_preview'])
        self.refresh_scope()

    def _grid_listbox(self, parent, key, row):
        tk, ttk = self.tk, self.ttk
        box = tk.Listbox(parent, selectmode='multiple', exportselection=False, height=7, activestyle='none',
                         background=self.CARD, foreground=self.TEXT, selectbackground=self.SELECTED,
                         selectforeground=self.TEXT, highlightthickness=1, highlightcolor=self.ACCENT,
                         highlightbackground=self.BORDER, relief='flat', font=self.body_font)
        box.grid(row=row, column=0, sticky='nsew', pady=(4, 0))
        scroll = ttk.Scrollbar(parent, orient='vertical', command=box.yview)
        scroll.grid(row=row, column=1, sticky='ns', pady=(4, 0))
        box.configure(yscrollcommand=scroll.set)
        box.bind('<<ListboxSelect>>', lambda _event, name=key: self.on_grid_select(name), add='+')
        self.tip(box, setting_help(key))
        self.grid_lists[key] = box

    def refresh_scope(self):
        """Show the grid selections of the editor; nothing is applied to PowerFactory."""
        if not getattr(self, 'grid_lists', None):
            return
        choices = self.editor.grid_choices()
        contingency = self.editor.selected_grids('contingency_grids')
        self.contingency_mode.set('same' if contingency is None else 'own')
        for key, box in self.grid_lists.items():
            selected = set(self.editor.selected_grids(key) or ())
            box.configure(state='normal')
            box.delete(0, 'end')
            for name in choices:
                missing = self.editor.grids is not None and name not in self.editor.grids
                box.insert('end', name + ('  (not in the project)' if missing else
                                          '  (inactive)' if name in self.editor.inactive_grids else ''))
                if name in selected or (key == 'contingency_grids' and contingency is None
                                        and name in set(self.editor.selected_grids('monitoring_grids'))):
                    box.selection_set('end')
            if key == 'contingency_grids' and contingency is None:
                box.configure(state='disabled')
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
        choices = self.editor.grid_choices()
        problem = self.editor.set_grids(key, [choices[index] for index in box.curselection()])
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
        card = self._card(page, row=0, column=0, sticky='new')
        card.columnconfigure(1, weight=1)
        title = ttk.Label(card, text='QDS time base (read only)', style='Title.TLabel')
        title.grid(row=0, column=0, columnspan=2, sticky='w', pady=(0, 6))
        self.tip(title, HELP_TEXTS['qds'])
        for row, (label, value) in enumerate(self.editor.qds_info, 1):
            caption = ttk.Label(card, text=label, style='Muted.TLabel')
            caption.grid(row=row, column=0, sticky='nw', padx=(0, 14), pady=1)
            shown = ttk.Label(card, text=value, wraplength=620)
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
        # Only the order and the overlap matter here: no dates, no numbers.
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
        self.outcome = self.editor.config
        self.root.destroy()

    def cancel(self):
        self.outcome = None
        self.root.destroy()


def run_case_manager(records, config, period, config_path, user='', qds_text='', qds_info=None, grids=None,
                     contingencies=CONTINGENCIES_NOT_READ):
    """Show the case manager; the edited configuration on "Start calculation", None on Cancel."""
    try:
        import tkinter as tk
        import tkinter.font
        from tkinter import messagebox, simpledialog, ttk
        root = tk.Tk()
    except Exception as exc:
        raise CaseManagerUnavailable('The case manager cannot open a window: {}'.format(_friendly_exception(exc))) from None
    dialog = CaseManagerDialog(root, CaseEditor(records, config, period, qds_text, qds_info, grids, contingencies),
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


def _restore_planned_outage_option(qds, original, logger):
    if not _set_scalar_attribute(qds, PLANNED_OUTAGE_OPTION, original):
        return ["the 'Planned Outages' option ({}) could not be restored to {}"
                .format(PLANNED_OUTAGE_OPTION, _format_setting_value(original))]
    logger.write(
        "RESTORE", "Restored the 'Planned Outages' option [{}] to {}.".format(
            PLANNED_OUTAGE_OPTION, _format_setting_value(original)), 6)
    return []


class ResultStore:
    """The ElmRes of every run. They stay in the study case after the run, one per case.

    Names read GridLens_<yymmdd-HHMMSS>_<case id> (at most 39 characters), so the runs of one GridLens
    execution sort together and every case can be opened in PowerFactory.
    """

    def __init__(self, stamp=None):
        self.stamp = stamp or datetime.now().strftime("%y%m%d-%H%M%S")
        self.objects = []
        self.by_case = {}

    def name_for(self, case_id):
        return "{}{}_{}".format(SNAPSHOT_PREFIX, self.stamp, case_id)

    def append(self, obj, case_id=None):
        self.objects.append(obj)
        if case_id is not None:
            self.by_case[case_id] = object_name(obj)

    def __bool__(self):
        return bool(self.objects)

    def __len__(self):
        return len(self.objects)

    def __iter__(self):
        return iter(self.objects)


def _case_result_object(study_case, template, case_id, name=None):
    """A copy of the configured ElmRes for one case, with its variable selection."""
    name = name or "{}{}_{}".format(SNAPSHOT_PREFIX, datetime.now().strftime("%y%m%d-%H%M%S"), case_id)
    snapshot = None
    if template is not None:
        copier = getattr(study_case, "AddCopy", None)
        if callable(copier):
            try:
                copies = _as_objects(copier(template))
                snapshot = copies[0] if copies else None
            except Exception:
                snapshot = None
        if snapshot is None:
            copier = getattr(study_case, "CopyObject", None)
            if callable(copier):
                try:
                    copies = _as_objects(copier(template, name))
                    snapshot = copies[0] if copies else None
                except Exception:
                    snapshot = None
    if snapshot is None:
        raise GridLensError(
            "PowerFactory could not copy the configured ElmRes for case {}. "
            "The calculation was not started because a new empty ElmRes would "
            "lose the configured result-variable selection.".format(case_id))
    # A copy that cannot carry its name is removed again: it would be an
    # anonymous duplicate of the configured result object.
    try:
        snapshot.loc_name = name
    except Exception:
        try:
            snapshot.SetAttribute("loc_name", name)
        except Exception as exc:
            try:
                snapshot.Delete()
            except Exception:
                pass
            raise GridLensError(
                "PowerFactory could not name the result object of the case: {}".format(
                    _friendly_exception(exc))) from None
    if object_name(snapshot) != name:
        try:
            snapshot.Delete()
        except Exception:
            pass
        raise GridLensError("PowerFactory did not retain the name of the result object of the case.")
    return snapshot


def _run_calculation(app, study_case, qds, case_id, name, description,
                     original_result, logger, result_objects, plan=None,
                     announce=True):
    if announce:
        logger.case("Case {} \u00b7 {}".format(case_id, name))
    snapshot = _case_result_object(study_case, original_result, case_id, result_objects.name_for(case_id))
    result_objects.append(snapshot, case_id)
    if not _set_attribute(qds, "results", snapshot):
        raise GridLensError(
            "PowerFactory did not bind ComStatsim.results to the result object "
            "of the case. No calculation was started.")
    logger.write(
        "CALCULATION",
        "Starting {} with the active ComStatsim settings; only the "
        "'Planned Outages' option and the outages' 'Ignored' flags "
        "differ between the cases.".format(case_id), 4)
    logger.write(
        "CALCULATION",
        "PowerFactory is calculating {}. This blocking API call may take "
        "several minutes; intermediate progress is controlled by PowerFactory."
        .format(case_id), 4)
    started = time.monotonic()
    try:
        returned = qds.Execute()
    except Exception as exc:
        RUN_STATS.add("QDS calculation (PowerFactory)", time.monotonic() - started)
        raise GridLensError(
            "{} calculation was interrupted or failed: {}. {}".format(
                case_id, _friendly_exception(exc), REFUSED_HINT)) from None
    elapsed = time.monotonic() - started
    RUN_STATS.add("QDS calculation (PowerFactory)", elapsed)
    RUN_STATS.count("qds_runs")
    code = return_code(returned)
    if code is None or code != 0.0:
        raise GridLensError(
            "{} calculation ended after {:.1f}s with {}. Review the "
            "PowerFactory calculation messages and QDS configuration.".format(
                case_id, elapsed,
                "an unreadable return value" if code is None
                else "error code {:g}".format(code)))
    if not _same_object(safe_attr(qds, "results"), snapshot):
        raise GridLensError(
            "ComStatsim.results changed during {}. Results were rejected."
            .format(case_id))
    logger.write(
        "CALCULATION", "{} completed successfully in {:.1f}s.".format(
            case_id, elapsed), 4)
    logger.write("EXTRACTION", "Reading and validating {} results.".format(case_id), 5)
    try:
        reading = time.monotonic()
        snapshot.Load()
        counters = {}
        series, labels, plot_times, unit, absolute, origin = collect_series(
            snapshot, counters)
        RUN_STATS.add("read QDS results (ElmRes)", time.monotonic() - reading)
        RUN_STATS.count("qds_steps", len(labels))
        RUN_STATS.count("series", len(series))
        RUN_STATS.count("values", len(series) * len(labels))
        if current_setting("monitoring_grids") or GRID_NAME_FILTER:
            logger.write(
                "EXTRACTION",
                "Grid scope ({}): {} series assessed, {} out of scope and "
                "not read.".format(grid_scope_text(), len(series),
                                   counters.get('out_of_scope', 0)), 5)
        logger.write(
            "EXTRACTION",
            "Validated {} supported series across {} time point(s); time unit '{}'."
            .format(len(series), len(labels), unit), 5)
        logger.write(
            "EXTRACTION",
            "Time axis: {} scale, unit '{}'; first {}; last {}; span {}."
            .format("absolute" if absolute else "relative",
                    unit, labels[0], labels[-1],
                    '{:g} h'.format(plot_times[-1] - plot_times[0])), 5)
        _log_extraction_detail(logger, series, counters)
    except Exception as exc:
        raise GridLensError(
            "{} was calculated, but GridLens cannot use its result object {}: {}".format(
                case_id, object_name(snapshot), _friendly_exception(exc))) from None
    finally:
        try:
            snapshot.Release()
        except Exception:
            pass
    case = {
        "id": case_id,
        "name": name,
        "kind": "reference" if case_id == REFERENCE_CASE_ID else "planning_case",
        "description": description,
        "status": CONVERGED,
        "error_code": 0,
        "message": "Completed in {:.1f}s.".format(elapsed),
        "counters": counters,
        "plan": plan,
        "result_object": object_name(snapshot),
        "hours": [origin + value for value in plot_times] if absolute else list(plot_times),
        "absolute": absolute,
        "elapsed": elapsed,
    }
    result = case_result(case, series, labels, plot_times, unit)
    result["window"] = ((None, None) if origin is None else
                        (origin * 3600.0, (origin + plot_times[-1]) * 3600.0))
    return result


def _log_kept_results(results_store, logger):
    """The result objects stay in PowerFactory; name each one."""
    for obj in results_store:
        logger.write("RESULTS", "Kept result object '{}' in the study case.".format(object_name(obj)), 6)


def _restore_results_binding(qds, original_result):
    if not _set_attribute(qds, "results", original_result):
        return ["ComStatsim.results could not be restored to its original object."]
    return []


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


def _format_study_time(date_value, time_value):
    date_number = finite_number(date_value)
    time_number = finite_number(time_value)
    if date_number is None or time_number is None:
        return "date={}, time={}".format(date_value, time_value)
    date_text = "{:08d}".format(int(date_number))
    # PowerFactory stores SetTime.cTime as HHMMSS: 230000 is 23:00:00.
    time_text = "{:06d}".format(int(time_number))
    return "{}-{}-{} {}:{}:{}".format(
        date_text[0:4], date_text[4:6], date_text[6:8],
        time_text[0:2], time_text[2:4], time_text[4:6])


def _capture_study_time(app):
    try:
        study_time = app.GetFromStudyCase("SetTime")
    except Exception as exc:
        raise GridLensError(
            "The initial Study Case date/time could not be accessed: {}. No "
            "calculation was started.".format(_friendly_exception(exc))) from None
    if study_time is None:
        raise GridLensError(
            "No SetTime object was found in the active Study Case. GridLens "
            "cannot guarantee restoration of the Study Case clock, so no "
            "calculation was started.")
    date_found, date_value = _read_setting(study_time, "cDate")
    time_found, time_value = _read_setting(study_time, "cTime")
    if not date_found or not time_found:
        raise GridLensError(
            "SetTime.cDate or SetTime.cTime is unavailable. GridLens cannot "
            "guarantee restoration of the Study Case clock, so no calculation "
            "was started.")
    return {
        "object": study_time,
        "date": date_value,
        "time": time_value,
    }


def _set_scalar_attribute(obj, attribute, value):
    try:
        setattr(obj, attribute, value)
    except Exception:
        setter = getattr(obj, "SetAttribute", None)
        if not callable(setter):
            return False
        try:
            setter(attribute, value)
        except Exception:
            return False
    found, restored = _read_setting(obj, attribute)
    if not found:
        return False
    left = finite_number(restored)
    right = finite_number(value)
    if left is not None and right is not None:
        return left == right
    return restored == value


def _restore_study_time(state, logger, stage="RESTORE", step=6):
    errors = []
    study_time = state["object"]
    if not _set_scalar_attribute(study_time, "cDate", state["date"]):
        errors.append("SetTime.cDate could not be restored and verified.")
    if not _set_scalar_attribute(study_time, "cTime", state["time"]):
        errors.append("SetTime.cTime could not be restored and verified.")
    if not errors:
        logger.write(
            stage,
            "Restored Study Case time to {}.".format(
                _format_study_time(state["date"], state["time"])), step)
    return errors


def _log_qds_settings(qds, result, study_time_state, logger):
    logger.write(
        "SETTINGS",
        "Active ComStatsim settings; GridLens changes only the 'Planned "
        "Outages' option and restores it:", 2)
    for label, attribute in QDS_CORE_SETTINGS:
        found, value = _read_setting(qds, attribute)
        rendered = _format_setting_value(value) if found else "<not exposed>"
        logger.write(
            "SETTINGS",
            "{} [{}] = {}".format(label, attribute, rendered), 2)
    option_names = set(QDS_OPTION_ATTRIBUTES)
    try:
        option_names.update(
            name for name in dir(qds) if name.startswith("iopt_"))
    except Exception:
        pass
    options = []
    for attribute in sorted(option_names):
        found, value = _read_setting(qds, attribute)
        if found:
            options.append("{}={}".format(
                attribute, _format_setting_value(value)))
    logger.write(
        "SETTINGS",
        "Calculation options: {}".format(
            ", ".join(options) if options else "<no exposed iopt_* attributes>"),
        2)
    period_start, period_end = qds_period(qds)
    if period_start is not None:
        logger.write(
            "SETTINGS",
            "Simulated period [startTime..endTime] = {} .. {}".format(
                _format_pf_time(period_start), _format_pf_time(period_end)), 2)
    else:
        logger.write(
            "SETTINGS",
            "Simulated period is not exposed by this ComStatsim; planned "
            "outages will be judged against the reference time axis.", 2)
    for attribute in ("iopt_maint", "ciopt_maint", "iopt_action", "iopt_rep"):
        found, value = _read_setting(qds, attribute)
        if found:
            logger.write(
                "SETTINGS", "Planned outages [{}] = {}".format(
                    attribute, _format_setting_value(value)), 2)
    logger.write(
        "SETTINGS",
        "Result object [results] = '{}' ({})".format(
            object_name(result), class_name(result) or "ElmRes"), 2)
    logger.write(
        "SETTINGS",
        "Initial Study Case time: {}".format(_format_study_time(
            study_time_state["date"], study_time_state["time"])), 2)


# PowerFactory reports why it refused a command only in its output window; Python sees "method call failed".
REFUSED_HINT = ("PowerFactory names the cause in its own message just above this line, for example a licence that "
                "does not include the quasi-dynamic simulation or the contingency analysis. The result object of this "
                "run stays in the study case and may be empty.")


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


def _generated_by():
    try:
        value = getpass.getuser()
    except Exception:
        value = ""
    return value or os.environ.get("USERNAME") or os.environ.get("USER") or "Unknown user"


class StateRestoreError(GridLensError):
    """A setting changed by GridLens could not be put back."""


def _same_setting(current, original):
    left, right = finite_number(current), finite_number(original)
    return left == right if left is not None and right is not None else current == original


class StateGuard:
    """Change PowerFactory settings temporarily and always put them back.

    Every value is recorded before it is written. Leaving the block restores
    all of them in reverse order and reads each one back; a setting that cannot
    be restored raises StateRestoreError naming the expected and the found value.
    """

    def __init__(self):
        self._changes = []

    def set(self, obj, attribute, value, label):
        """Write `value`; False when it cannot be written and read back."""
        known, original = _read_setting(obj, attribute)
        if not known:
            return False
        self._changes.append((obj, attribute, original, label))
        return _set_scalar_attribute(obj, attribute, value)

    def restore(self):
        errors = []
        for obj, attribute, original, label in reversed(self._changes):
            known, current = _read_setting(obj, attribute)
            if known and _same_setting(current, original):
                continue
            if not _set_scalar_attribute(obj, attribute, original):
                known, current = _read_setting(obj, attribute)
                errors.append("{}: expected {}, read back {}".format(
                    label, _format_setting_value(original),
                    _format_setting_value(current) if known else "unreadable"))
        self._changes = []
        return errors

    def __enter__(self):
        return self

    def __exit__(self, kind, failure, _unused):
        errors = self.restore()
        if errors:
            message = ("PowerFactory state restoration failed. Verify the Study Case manually: "
                       + "; ".join(errors))
            if failure is not None:
                message += ". The calculation had stopped before with: " + _friendly_exception(failure)
            raise StateRestoreError(message) from failure
        return False


def _isolate_outages(guard, active_keys, records, label):
    """Let PowerFactory apply exactly `active_keys`: every other outage gets its 'Ignored' flag (outserv) set."""
    for record in records:
        wanted = 0 if record["key"] in active_keys else 1
        if not guard.set(record["_object"], "outserv", wanted, "'Ignored' flag of outage '{}'".format(record["name"])):
            raise GridLensError(
                "The 'Ignored' flag (outserv) of outage '{}' could not be set, so {} cannot be calculated "
                "with exactly its own planned outages.".format(record["name"], label))


def _apply_overrides(guard, plan):
    """Own dates of a case; only reached when ALLOW_OUTAGE_TIME_OVERRIDE is on."""
    for record in plan.get("overridden") or ():
        start, end = plan["windows"][record["key"]]
        for attribute, value in (("starttime", start), ("endtime", end)):
            if not guard.set(record["_object"], attribute, value, "{} of outage '{}'".format(attribute, record["name"])):
                raise GridLensError("{} of outage '{}' could not be set for case {}.".format(attribute, record["name"], plan["id"]))


def _active_text(plan, background):
    names = [record["name"] for record in plan["members"]] if plan else []
    text = "active: " + (", ".join(names) or "none")
    if background:
        text += "; fixed: " + ", ".join(record["name"] for record in background)
    return text + "; every other planned outage Ignored"


def _run_reference(app, study_case, qds, request, records, original_result, logger,
                   result_objects, study_time_state):
    """R0 without planned outages, or Rfix with exactly the fixed outages."""
    background = request["background"]
    name = REFERENCE_NAME if not background else "Reference (fixed outages)"
    if not background:
        if not _set_scalar_attribute(qds, PLANNED_OUTAGE_OPTION, 0):
            raise GridLensError(
                "The 'Planned Outages' option [{}] could not be switched off, so a reference free of planned "
                "outages could not be guaranteed. No calculation was started.".format(PLANNED_OUTAGE_OPTION))
        result = _run_calculation(app, study_case, qds, REFERENCE_CASE_ID, name, "Network state without planned outages.",
                                  original_result, logger, result_objects)
        result["run_note"] = "iopt_maint=0: no planned outage applied"
    else:
        if not _set_scalar_attribute(qds, PLANNED_OUTAGE_OPTION, 1):
            raise GridLensError("The 'Planned Outages' option [{}] could not be switched on for the reference with "
                                "fixed outages. No calculation was started.".format(PLANNED_OUTAGE_OPTION))
        logger.case("Case {} · {}".format(REFERENCE_CASE_ID, name))
        logger.detail("Fixed outages active in the reference and in every case: {}".format(
            ", ".join(record["name"] for record in background)))
        with StateGuard() as guard:
            _isolate_outages(guard, {record["key"] for record in background}, records, "the reference")
            result = _run_calculation(app, study_case, qds, REFERENCE_CASE_ID, name, "Network state with the fixed planned outages.",
                                      original_result, logger, result_objects, announce=False)
        result["run_note"] = "iopt_maint=1; " + _active_text(None, background)
    clock_errors = _restore_study_time(study_time_state, logger, "CALCULATION", 4)
    if clock_errors:
        raise GridLensError("The initial Study Case time could not be restored after REF: {}. The case runs were "
                            "not started.".format("; ".join(clock_errors)))
    return result


def _run_planning_case(app, study_case, qds, plan, request, records, reference,
                       original_result, logger, result_objects, study_time_state):
    """One planning case with all its outages; a failure becomes a failed case, a restore failure stops the run."""
    background = request["background"]
    case = {"id": plan["id"], "name": plan["name"], "kind": "planning_case",
            "description": plan.get("description") or "Planned outages: {}.".format(
                ", ".join(record["name"] for record in plan["members"])), "plan": plan}
    logger.case("Case {} · {}".format(plan["id"], plan["name"]))
    logger.detail("Outages: {}".format("; ".join("{} ({})".format(
        record["name"], period_text(*(_format_pf_time(value) for value in plan["windows"][record["key"]])) or "unknown window")
        for record in plan["members"])))
    if plan.get("states"):
        logger.detail("Network states: {}".format(clip_text(states_text(plan), 300)))
    active = {record["key"] for record in plan["members"]} | {record["key"] for record in background}
    try:
        with StateGuard() as guard:
            _isolate_outages(guard, active, records, "case " + plan["id"])
            _apply_overrides(guard, plan)
            result = _run_calculation(app, study_case, qds, plan["id"], plan["name"], case["description"],
                                      original_result, logger, result_objects, plan, announce=False)
        result["run_note"] = "iopt_maint=1; " + _active_text(plan, background)
        out_of_service = {key for record in plan["members"] for key in record.get("component_keys") or ()}
        started = time.monotonic()
        try:
            with RUN_STATS.measure("compare case with REF"):
                compare_case(result, reference, [plan["windows"][record["key"]] for record in plan["members"]], out_of_service)
        except Exception as exc:
            # The QDS ran and its ElmRes is kept; only this case's assessment is lost.
            raise GridLensError("{} was calculated, but its comparison with the reference failed: {}".format(
                plan["id"], _friendly_exception(exc))) from None
        finally:
            release_values(result)
        assessment = result.get("assessment") or {}
        if not assessment.get("mapped", True):
            logger.detail("The outage windows of {} cannot be placed on the time axis, so every time step of the "
                          "period is compared; this takes longer and is shown in the report.".format(plan["id"]), "WARNING")
        logger.detail("Compared with {} at {} time step(s) ({} inside the outage windows, {} outside where the case "
                      "differs) in {:.1f}s.".format(REFERENCE_ID if reference else "no reference", assessment.get("rows", 0),
                                                    assessment.get("window_rows", 0), assessment.get("spill_rows", 0),
                                                    time.monotonic() - started))
    except StateRestoreError:
        raise
    except GridLensError as exc:
        logger.write("CALCULATION", "{} could not be evaluated: {}".format(plan["id"], exc), 4, "ERROR")
        result = failed_case(case, str(exc))
        result["result_object"] = result_objects.by_case.get(plan["id"], "")
        result["run_note"] = "iopt_maint=1; " + _active_text(plan, background)
    clock_errors = _restore_study_time(study_time_state, logger, "CALCULATION", 4)
    if clock_errors:
        raise GridLensError(
            "The initial Study Case time could not be restored after {}: {}. "
            "The next case was not started.".format(plan["id"], "; ".join(clock_errors)))
    return result


def _reused_result(source, plan, request):
    """A case whose outages and windows equal an already calculated case: the same PowerFactory state, the same result."""
    result = dict(source)
    result.update(id=plan["id"], name=plan["name"], plan=plan, is_reference=0,
                  provenance="REUSED from {} (identical outages and windows)".format(source["id"]),
                  description=plan.get("description") or source.get("description", ""))
    result["run_note"] = "not recalculated; " + _active_text(plan, request["background"])
    result["result_object"] = "{} (shared with {})".format(source.get("result_object") or "-", source["id"])
    return result


def contingency_analysis(study_case):
    """The ComSimoutage of the study case, read with GetContents (never created); None if there is not exactly one."""
    commands = [item for item in _contents(study_case, '*.' + N1_COMMAND_CLASS) if class_name(item) == N1_COMMAND_CLASS]
    return commands[0] if len(commands) == 1 else None


def contingency_equipment(command):
    """[(ComOutage, [equipment])] of the contingency analysis, read with ComOutage.GetObject(line)."""
    found = []
    for outage in _contents(command, '*.ComOutage'):
        if class_name(outage) != 'ComOutage':
            continue
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
        found.append((outage, elements))
    return found


# Equipment GridLens defines contingencies for when the study case has no contingency analysis: branches,
# transformers, reactors, compensation and FACTS. Not: generators, loads, busbars and terminals.
N1_CONTINGENCY_CLASSES = ('ElmLne', 'ElmBranch', 'ElmZpu', 'ElmTr2', 'ElmTr3', 'ElmTr4', 'ElmSind', 'ElmScap',
                          'ElmShnt', 'ElmSvs', 'ElmVsc', 'ElmVscmono')
N1_SWEEP_OPTION = 'iEnableTS'


def contingency_candidates(app, grids):
    """Calculation-relevant equipment of N1_CONTINGENCY_CLASSES in `grids` (empty: every grid), one per contingency.

    A line inside a branch (ElmBranch) is left out: the branch is its contingency.
    """
    found, seen = [], set()
    for kind in N1_CONTINGENCY_CLASSES:
        try:
            objects = list(app.GetCalcRelevantObjects('*.' + kind) or [])
        except Exception:
            objects = []
        for obj in objects:
            if class_name(obj) != kind or object_key(obj) in seen:
                continue
            if kind == 'ElmLne':
                try:
                    if class_name(obj.GetParent()) == 'ElmBranch':
                        continue
                except Exception:
                    pass
            if grids and element_grid_name(obj) not in grids:
                continue
            seen.add(object_key(obj))
            found.append(obj)
    return found


def create_contingency_analysis(app, study_case, grids, name):
    """A new contingency analysis `name` in the study case with one contingency (ComOutage) per candidate.

    It is kept after the run, like the QDS result objects. Every contingency
    holds one element as its interrupted component (ComOutage.SetObjs); the
    time sweep is switched on. Returns (command, contingencies, refused).
    """
    elements = contingency_candidates(app, grids)
    if not elements:
        raise GridLensError("no branch, transformer, reactor, compensation or FACTS element is calculation relevant in "
                            "{}, so no contingency can be defined".format(', '.join(grids) if grids else 'the network'))
    try:
        command = study_case.CreateObject(N1_COMMAND_CLASS, name)
    except Exception as exc:
        raise GridLensError("the contingency analysis '{}' could not be created: {}".format(
            name, _friendly_exception(exc))) from None
    if command is None or class_name(command) != N1_COMMAND_CLASS:
        raise GridLensError("PowerFactory did not create the contingency analysis '{}'".format(name))
    if not _set_scalar_attribute(command, N1_SWEEP_OPTION, 1):
        raise GridLensError("the time sweep [{}] of the new contingency analysis '{}' could not be switched on".format(
            N1_SWEEP_OPTION, name))
    made, refused = 0, 0
    for element in elements:
        try:
            outage = command.CreateObject('ComOutage', object_name(element))
            done = outage is not None and finite_number(outage.SetObjs([element])) == 0
        except Exception:
            done = False
        if done:
            made += 1
        else:
            refused += 1
    if not made:
        raise GridLensError("no contingency could be defined in '{}' (ComOutage.SetObjs refused all {} elements)".format(
            name, len(elements)))
    return command, made, refused


def contingencies_outside(equipment, grids):
    """The analysed contingencies none of whose equipment lies in `grids`; they are set to 'Not analysed' for the run.

    No grid selected keeps every contingency. A contingency partly in the
    grids, or without readable equipment, stays analysed.
    """
    if not grids:
        return []
    return [outage for outage, elements in equipment
            if safe_attr(outage, 'outserv', 0) in (0, False) and elements
            and not any(element_grid_name(element) in grids for element in elements)]


def _same_times(found, wanted, tolerance=1.0):
    return len(found) == len(wanted) and all(abs(a - b) <= tolerance for a, b in zip(sorted(found), sorted(wanted)))


def run_n1_sweep(command, times, active_keys, records, excluded, label):
    """One contingency analysis over `times` with exactly `active_keys` applied; the results, read before restoring.

    Written temporarily and restored verified (StateGuard): studyTime and
    bIgnoreTime, isPlannedOutages (0 without any active outage, else 1),
    the 'Ignored' flag of every planned outage, and 'Not analysed' of the
    contingencies outside the contingency grids. A failed calculation, or
    study times that differ from the written ones, raise GridLensError.
    """
    with StateGuard() as guard:
        if not guard.set(command, N1_PLANNED_OPTION, 1 if active_keys else 0,
                         "'Planned outages' option of the contingency analysis"):
            raise GridLensError("The 'Planned outages' option [{}] of the contingency analysis could not be set for "
                                "{}.".format(N1_PLANNED_OPTION, label))
        if active_keys:
            _isolate_outages(guard, active_keys, records, label)
        for outage in excluded:
            if not guard.set(outage, 'outserv', 1, "'Not analysed' flag of contingency '{}'".format(object_name(outage))):
                raise GridLensError("Contingency '{}' could not be set to 'Not analysed' for the contingency grid "
                                    "selection.".format(object_name(outage)))
        if not guard.set(command, N1_TIMES_ATTRIBUTE, [float(moment) for moment in times], 'study times of the contingency analysis'):
            raise GridLensError("The study times [{}] of the contingency analysis could not be written for {}.".format(
                N1_TIMES_ATTRIBUTE, label))
        known, ignore = _read_setting(command, N1_IGNORE_ATTRIBUTE)
        if known and isinstance(ignore, (list, tuple)) and not guard.set(
                command, N1_IGNORE_ATTRIBUTE, [0.0] * len(times), 'ignored study times of the contingency analysis'):
            raise GridLensError("The ignored study times [{}] of the contingency analysis could not be cleared for "
                                "{}.".format(N1_IGNORE_ATTRIBUTE, label))
        started = time.monotonic()
        try:
            code = command.Execute()
        except Exception as exc:
            RUN_STATS.add("n-1 contingency analysis (PowerFactory)", time.monotonic() - started)
            raise GridLensError("The contingency analysis for {} stopped: {}. {}".format(
                label, _friendly_exception(exc), REFUSED_HINT.split(' The result object')[0])) from None
        RUN_STATS.add("n-1 contingency analysis (PowerFactory)", time.monotonic() - started)
        RUN_STATS.count("n1_sweeps")
        if finite_number(code) != 0:
            raise GridLensError("The contingency analysis for {} ended with error code {}.".format(label, code))
        with RUN_STATS.measure("read n-1 results"):
            found = read_n1_results(command)
        RUN_STATS.count("n1_times", len(found['times']))
        RUN_STATS.count("n1_loadflows", len({(moment, key[0]) for moment, values in found['times'].items() for key in values}))
    if not _same_times(list(found['times']), times):
        raise GridLensError("The contingency analysis for {} calculated {} study time(s) instead of the {} written "
                            "ones.".format(label, len(found['times']), len(times)))
    return found


def _n1_reference_text(comparison):
    """Elements with a violation in the n-1 reference (PRE_EXISTING when compared with itself)."""
    violated = sum(1 for entry in comparison['elements'].values() if entry['worst']['status'] == 'PRE_EXISTING')
    return '{} element(s) with a post-fault violation'.format(violated)


def run_n1_case(command, plan, request, records, grid, excluded, elements_of, prime, references, label=None):
    """n-1 (fixed outages only) and, when `prime`, (n-1)' (with the case's outages) for one planning case.

    Both use the QDS steps inside the case's outage windows. `references`
    caches the n-1 results per set of study times, so cases with the same
    times share one reference sweep. Returns the case's n-1 entry.
    """
    label = label or 'case ' + plan['id']
    times = n1_study_times([plan['windows'][record['key']] for record in plan['members']], grid)
    if not times:
        return {'status': 'NOT EVALUATED', 'reason': 'no QDS time step lies inside the outage windows', 'times': 0}
    background = {record['key'] for record in request['background']}
    key = tuple(times)
    reference = references.get(key)
    if reference is None:
        reference = references[key] = run_n1_sweep(command, times, background, records, excluded, 'the n-1 reference of ' + label)
    entry = {'status': 'EVALUATED', 'times': len(times), 'contingencies': len(reference['contingencies'])}
    if not prime:
        entry.update(kind='n-1', comparison=compare_n1(reference, reference))
        entry['summary'] = 'n-1 reference: ' + _n1_reference_text(entry['comparison'])
        return entry
    active = background | {record['key'] for record in plan['members']}
    scenario = run_n1_sweep(command, times, active, records, excluded, "the (n-1)' scenario of " + label)
    switched_off = {component for record in plan['members'] for component in record.get('component_keys') or ()}
    with RUN_STATS.measure("classify (n-1)' against n-1"):
        entry.update(kind="(n-1)'", comparison=compare_n1(reference, scenario, switched_off, elements_of))
    RUN_STATS.count("n1_classified", sum(entry['comparison']['counts'].values()))
    entry['summary'] = "(n-1)' against n-1: " + n1_summary(entry['comparison'])
    return entry


# ComOutage.GetObject(line) is read for at most this many lines per contingency.
MAX_CONTINGENCY_ELEMENTS = 200


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


def obtain_case_request(app, records, candidates, period, logger, qds_info=None, grids=None,
                        contingencies=CONTINGENCIES_NOT_READ):
    """The planning cases of this run: from the case manager, the saved configuration or one per outage."""
    try:
        project_key = object_key(app.GetActiveProject())
    except Exception:
        project_key = "project"
    path = case_config_path(project_key)
    if CASE_SOURCE == "per_outage":
        return per_outage_request(records, candidates, period, project_key)
    saved = load_case_config(path)
    if CASE_SOURCE == "saved":
        if saved is None:
            raise GridLensError("CASE_SOURCE is 'saved' but there is no saved case configuration at {}. Open the case "
                                "manager once (CASE_SOURCE = 'gui') and save the cases.".format(path))
        return resolve_request(saved, records, period, "saved",
                               "saved configuration revision {} ({})".format(saved.get("revision"), path))
    if CASE_SOURCE != "gui":
        raise GridLensError("CASE_SOURCE must be 'gui', 'saved' or 'per_outage', not {!r}.".format(CASE_SOURCE))
    logger.write("CASES", "Opening the case manager. PowerFactory waits until it is closed; nothing has been "
                 "changed or calculated yet.", 3)
    try:
        config = run_case_manager(records, saved or empty_case_config(project_key), period, path, _generated_by(),
                                  qds_text=qds_period_text(period), qds_info=qds_info, grids=grids,
                                  contingencies=contingencies)
    except CaseManagerUnavailable as exc:
        if saved is not None:
            logger.write("CASES", "{} Using the saved configuration revision {} instead.".format(exc, saved.get("revision")), 3, "WARNING")
            return resolve_request(saved, records, period, "saved",
                                   "saved configuration revision {} (case manager unavailable)".format(saved.get("revision")))
        logger.write("CASES", "{} No saved configuration exists, so every planned outage in the simulated period is "
                     "calculated as its own case.".format(exc), 3, "WARNING")
        request = per_outage_request(records, candidates, period, project_key)
        request["source_text"] += " (case manager unavailable)"
        return request
    if config is None:
        raise GridLensCancelled("Cancelled in the case manager. Nothing was calculated and nothing was changed.")
    try:
        latest = load_case_config(path)
    except GridLensError:
        latest = None
    unsaved = latest is None or any(latest.get(name) != config.get(name)
                                    for name in ("cases", "background", "rules", "settings"))
    return resolve_request(config, records, period, "gui", "case manager, configuration revision {}{}".format(
        config.get("revision") or 0, " with unsaved changes" if unsaved else ""))


def _log_plan(logger, request):
    logger.detail("Planning cases from: {}".format(request["source_text"]))
    logger.detail("Reference: {}".format(_reference_text(request)))
    logger.detail("Assessment: {}".format(", ".join(
        "n-0 quasi-dynamic simulation" if item == "n-0" else item for item in request.get("assessments") or ["n-0"])))
    if request.get("disabled"):
        logger.detail("Excluded from the calculation in the case manager: {}".format(", ".join(request["disabled"])))
    for warning in request.get("warnings") or ():
        logger.detail("Warning: " + warning, "WARNING")
    logger.table(("Case", "Name", "Outages", "States", "Status", "Note"), [
        (plan["id"], plan["name"], len(plan["members"]), len(plan["states"]), plan["status"],
         clip_text(plan["reason"] or "; ".join(plan["warnings"]) or "-", 90))
        for plan in request["cases"]])
    for plan in request["cases"]:
        for left, right, code in plan["relations"]:
            logger.detail("{}: {} / {} -> {} ({})".format(plan["id"], left, right, code, INTERVAL_RELATIONS[code]))


def _log_context(app, study_case, qds, original_result, logger):
    try:
        project = object_name(app.GetActiveProject())
    except Exception:
        project = "unknown"
    logger.detail("Project: {} | Study case: {} | ComStatsim: {}".format(
        project, object_name(study_case), object_name(qds)))
    logger.detail("Result object: {} ({})".format(
        object_name(original_result), class_name(original_result) or "ElmRes"))
    logger.detail("Grid scope of the script: {}".format(
        "grids whose name contains {!r}".format(GRID_NAME_FILTER)
        if GRID_NAME_FILTER else "every element (a grid selection in Settings takes precedence)"))
    logger.detail("Reference case: {} | case source: {} | time base: complete ComStatsim period".format(
        "on" if setting_value('run_reference') else "off", CASE_SOURCE))


def _series_overview(series):
    """Rows (category, series, highest value, element, limit violations) of one case."""
    rows = []
    for category, label, _, _ in CATEGORY_LABELS:
        items = [item for item in series if item["category"] == category]
        if not items:
            rows.append((label, "0", "-", "-", "-"))
            continue
        if category == "voltage":
            lowest = min(items, key=lambda item: item["statistics"]["min"] if item.get("statistics") else 9)
            stats = lowest.get("statistics")
            rows.append((label, str(len(items)),
                         "min {:.3f} p.u.".format(stats["min"]) if stats else "-",
                         lowest["element_name"],
                         str(sum(1 for item in items if is_critical(item, item.get("statistics"))))))
            continue
        top = max(items, key=lambda item: item["statistics"]["max"] if item.get("statistics") else -1)
        stats = top.get("statistics")
        rows.append((label, str(len(items)),
                     "max {:.1f} %".format(stats["max"]) if stats else "-",
                     top["element_name"],
                     str(sum(1 for item in items if is_critical(item, item.get("statistics"))))))
    return rows


def _log_extraction_detail(logger, series, counters):
    logger.table(("Result series", "Count", "Extreme", "Element", "Violating"),
                 _series_overview(series))
    grids = counters.get("grids") or {}
    if grids and not getattr(logger, "grids_shown", False):
        logger.grids_shown = True
        ordered = sorted(grids.items(), key=lambda entry: (-entry[1][0], entry[0]))
        logger.detail("Grids in the result file (series per grid):")
        logger.table(("Grid", "Series", "Scope"),
                     [(name, count, "assessed" if inside else "ignored")
                      for name, (count, inside) in ordered[:12]])
        if len(ordered) > 12:
            logger.detail("... and {} more grid(s).".format(len(ordered) - 12))
    skipped = []
    if counters.get("dc_nodes"):
        skipped.append("{} DC node(s)".format(counters["dc_nodes"]))
    if counters.get("deenergized_nodes"):
        skipped.append("{} node(s) without voltage".format(counters["deenergized_nodes"]))
    if skipped:
        logger.detail("Not assessed: {}.".format(", ".join(skipped)))


def _log_results(logger, results, request):
    rows = []
    for result in results:
        if result["id"] == REFERENCE_ID:
            verdict = "BASELINE" if result["status"] == CONVERGED else result["status"]
        elif result["status"] != CONVERGED:
            verdict = result["status"]
        else:
            values = judged(results, result)
            verdict = values["assessment"] if values else ASSESSMENT_NO_DATA
        lines, transformers, nodes = _violation_counts(result) if result["status"] == CONVERGED else (0, 0, 0)
        rows.append((result["id"], result["name"], result["status"],
                     "{:.1f}s".format(result["elapsed"]) if result.get("elapsed") is not None
                     and result.get("provenance", "CALCULATED") == "CALCULATED" else "reused" if result.get("provenance", "").startswith("REUSED") else "-",
                     verdict, lines, transformers, nodes))
    logger.table(("Case", "Name", "Status", "Time", "Assessment", "Lines>100", "Trafos>100", "Nodes out"), rows)
    for result in results:
        if result["status"] != CONVERGED:
            logger.detail("{}: {}".format(result["id"], result["message"]), "WARNING")
    for plan in request["cases"]:
        if plan["status"] != PLAN_READY:
            logger.detail("Not calculated '{}': {}".format(plan["name"], plan["reason"]), "WARNING")
    for record in request.get("skipped") or ():
        logger.detail("Skipped '{}': {}".format(record["name"], record.get("skip_reason", "")), "WARNING")


def _log_findings(logger, payload):
    metrics = [row for row in payload["ScriptedCaseMetrics"] if row["case_order"]]
    if metrics:
        logger.detail("Largest coincident loading increase per case (same time step as Reference):")
        logger.table(("Case", "Max line", "Coincident delta", "Difference of maxima", "Caused", "Coverage"),
                     [(row["case_name"], row["max_line_text"], row["coincident_delta_text"], row["maxima_difference_text"],
                       row["violation_hours_text"], row["coverage_text"]) for row in metrics])
    checks = [row for row in payload["ScriptedModelQuality"] if row["status"] in ("FAIL", "WARNING")]
    if checks:
        logger.detail("Model quality findings:")
        logger.table(("Status", "Check", "Details"),
                     [(row["status"], row["check_name"], clip_text(row["message"], 90)) for row in checks],
                     "WARNING" if any(row["status"] == "FAIL" for row in checks) else "INFO")


def contingency_grid_selection():
    """The grids whose contingencies are analysed: the contingency grids, else the assessed grids (empty: every grid)."""
    grids = current_setting('contingency_grids')
    return tuple(current_setting('monitoring_grids') if grids is None else grids)


def run_n1(app, study_case, qds, request, records, ready, results, logger, study_time_state):
    """n-1 and, if requested, (n-1)' for every ready planning case; the entry goes to result['n1'].

    A case that cannot be evaluated gets status NOT EVALUATED with the reason
    and the others continue; a state that cannot be restored stops the run.
    Cases with the same outages and windows share one evaluation.
    """
    prime = N1_PRIME in (request.get('assessments') or ())
    by_id = {result['id']: result for result in results}
    command = contingency_analysis(study_case)
    grid = qds_grid(qds)
    reason = None
    if command is None and not _contents(study_case, '*.' + N1_COMMAND_CLASS) and grid is not None:
        # No contingency analysis here (e.g. the QDS study case): GridLens defines one and keeps it.
        name = "{}{}_N1".format(SNAPSHOT_PREFIX, datetime.now().strftime("%y%m%d-%H%M%S"))
        try:
            with RUN_STATS.measure("n-1: define contingencies"):
                command, made, refused = create_contingency_analysis(app, study_case, contingency_grid_selection(), name)
            RUN_STATS.count("n1_created")
            logger.write("CALCULATION", "The study case holds no contingency analysis: GridLens created '{}' with {} "
                         "contingencies (one per branch, transformer, reactor, compensation and FACTS element in {}; no "
                         "generators, loads or busbars){}. It stays in the study case.".format(
                             name, made, ', '.join(contingency_grid_selection()) or 'every grid',
                             '; {} element(s) refused'.format(refused) if refused else ''), 4)
        except GridLensError as exc:
            command, reason = None, str(exc)
    if reason is None:
        reason = ('the active study case holds more than one contingency analysis (ComSimoutage)' if command is None
                  else 'the ComStatsim time step is not readable' if grid is None else None)
    if reason:
        logger.write("CALCULATION", "n-1 is not evaluated: {}.".format(reason), 4, "WARNING")
        for plan in ready:
            if plan['id'] in by_id:
                by_id[plan['id']]['n1'] = {'status': 'NOT EVALUATED', 'reason': reason, 'times': 0}
        return
    equipment = contingency_equipment(command)
    excluded = contingencies_outside(equipment, contingency_grid_selection())
    elements_of = {object_key(outage): {object_key(element) for element in elements} for outage, elements in equipment}
    logger.write("CALCULATION", "{} with contingency analysis '{}': {} contingencies, {} set to 'Not analysed' for the "
                 "contingency grids.".format(N1_PRIME + " against n-1" if prime else N1_REFERENCE, object_name(command),
                                             len(equipment), len(excluded)), 4)
    references, done = {}, {}
    for plan in ready:
        result = by_id.get(plan['id'])
        if result is None:
            continue
        if plan['fingerprint'] in done:
            result['n1'] = dict(done[plan['fingerprint']])
            continue
        logger.case("n-1 · Case {} · {}".format(plan['id'], plan['name']))
        started = time.monotonic()
        try:
            entry = run_n1_case(command, plan, request, records, grid, excluded, elements_of, prime, references)
        except StateRestoreError:
            raise
        except GridLensError as exc:
            entry = {'status': 'NOT EVALUATED', 'reason': str(exc), 'times': 0}
        clock_errors = _restore_study_time(study_time_state, logger, "CALCULATION", 4)
        if clock_errors:
            raise GridLensError("The initial Study Case time could not be restored after the n-1 run of {}: {}.".format(
                plan['id'], "; ".join(clock_errors)))
        if entry['status'] == 'EVALUATED':
            logger.detail("{} at {} study time(s) in {:.1f}s.".format(entry['summary'], entry['times'],
                                                                     time.monotonic() - started))
        else:
            logger.detail("n-1 not evaluated: {}".format(entry['reason']), "WARNING")
        result['n1'] = done[plan['fingerprint']] = entry


def n1_quality(payload, results):
    """One Model Quality row per case with an n-1 entry, until the report has n-1 chapters (part 4)."""
    for result in results:
        entry = result.get('n1')
        if not entry:
            continue
        if entry['status'] != 'EVALUATED':
            _quality(payload, 'n1_' + result['id'], 'n-1 ' + result['id'], 'WARNING',
                     'Not evaluated: {}'.format(entry['reason']), result['id'])
            continue
        counts = entry['comparison']['counts']
        worst = sorted((item['worst'] for item in entry['comparison']['elements'].values()),
                       key=lambda item: N1_SEVERITY.index(item['status']))
        caused = [item for item in worst if item['status'] in ('NEW', 'WORSENED')] if entry['kind'] == N1_PRIME else []
        status = 'FAIL' if caused else 'WARNING' if any(counts.get(key) for key in ('FAILED', 'NOT_EVALUATED', 'NOT_COMPARABLE')) else 'PASS'
        detail = '; '.join('{} {} ({}, contingency {})'.format(item['status'], clip_text(_element_name(item, entry), 40),
                                                                 item['identity']['quantity'], clip_text(item['contingency_name'], 40))
                           for item in caused[:3])
        _quality(payload, 'n1_' + result['id'], 'n-1 ' + result['id'], status,
                 '{} at {} study time(s), {} contingencies.{}'.format(entry['summary'], entry['times'], entry['contingencies'],
                                                                     ' Caused: ' + detail + '.' if detail else ''), result['id'])


def _element_name(item, entry):
    element = item['identity']['element']
    return entry['comparison']['elements'].get((element, item['identity']['quantity']), {}).get('name', element)


def execute_gridlens(app):
    global RUN_STATS
    RUN_STATS = RunStats()
    logger = RunLogger(app)
    logger.step(1, "Startup and context")
    logger.write(
        "STARTUP", "GridLens publisher {} started.".format(PUBLISHER_VERSION), 1)
    script = app.GetCurrentScript()
    study_case = app.GetActiveStudyCase()
    if script is None:
        raise GridLensError("No active ComPython script was found.")
    if study_case is None:
        raise GridLensError(
            "No active study case was found. Activate a study case and retry.")
    # Calculation and publication are separate: without an IntReport above the
    # script GridLens calculates, builds and checks every report table and logs
    # the results, but publishes nothing.
    report = script.GetParent()
    if report is None or class_name(report) != "IntReport":
        report = None
        logger.write("CONTEXT", "This ComPython is not below an IntReport: GridLens calculates and builds the report "
                     "tables but does not publish them (standalone run). Place it below the IntReport to publish.", 1)
    qds = app.GetFromStudyCase("ComStatsim")
    if qds is None:
        raise GridLensError(
            "No ComStatsim was found in the active study case. Configure the "
            "quasi-dynamic simulation before running GridLens.")
    original_result = safe_attr(qds, "results")
    if original_result is None:
        raise GridLensError(
            "ComStatsim.results is empty. Configure a result object and the "
            "required variables before running GridLens.")
    if object_name(original_result).startswith(SNAPSHOT_PREFIX):
        # An aborted run can leave this binding behind. The object still holds
        # the full variable selection and every case recalculates into a fresh
        # copy, so the stored settings are used as they are.
        logger.write(
            "CONTEXT",
            "ComStatsim.results is bound to '{}', a result object of an earlier "
            "GridLens run (left bound when that run was aborted). GridLens uses "
            "it as the configured result object and restores this binding "
            "afterwards; it is not changed. Bind ComStatsim.results to the "
            "intended ElmRes to avoid this.".format(
                object_name(original_result)), 2, "WARNING")
    option_found, original_option = _read_setting(qds, PLANNED_OUTAGE_OPTION)
    if not option_found:
        raise GridLensError(
            "The active ComStatsim does not expose the 'Planned Outages' "
            "option [{}]. GridLens cannot control whether PowerFactory applies "
            "planned outages, so no calculation was started.".format(
                PLANNED_OUTAGE_OPTION))
    study_time_state = _capture_study_time(app)
    logger.write(
        "CONTEXT",
        "Study case '{}'; QDS '{}'; result '{}'; reference flag {}."
        .format(object_name(study_case), object_name(qds),
                object_name(original_result), setting_value('run_reference')), 2)
    _log_context(app, study_case, qds, original_result, logger)
    logger.step(2, "ComStatsim settings")
    _log_qds_settings(qds, original_result, study_time_state, logger)
    results = []
    result_objects = ResultStore()
    state_errors = []
    period = qds_period(qds)
    logger.step(3, "Planned outages and planning cases")
    with RUN_STATS.measure("read planned outages"):
        records, candidates = classify_planned_outages(app, logger, period)
    assign_definitions(records)
    # Read only, for the network scope of the case manager.
    with RUN_STATS.measure("read grids and contingencies"):
        grids = project_grids(app)
        contingencies = read_contingencies(study_case)
    case_manager = time.monotonic()
    request = obtain_case_request(app, records, candidates, period, logger, qds_time_info(qds, period), grids,
                                  contingencies)
    RUN_STATS.add("case manager (window open, incl. your time)", time.monotonic() - case_manager)
    # The settings are fixed here, after the case manager has closed, and apply to the whole run.
    request["settings_snapshot"] = activate_settings(request.get("settings"))
    logger.write("SETTINGS", "Settings {} with classification rules {}: {}.".format(
        SETTINGS_VERSION, CLASSIFICATION_VERSION, overrides_text(request["settings_snapshot"]["overrides"])), 3)
    request["contingency_scope"] = contingency_scope_text(contingencies, current_setting("contingency_grids"),
                                                          current_setting("monitoring_grids"))
    logger.write("SETTINGS", "Assessed equipment: {}. Contingencies: {}".format(
        grid_scope_text(), request["contingency_scope"]), 3)
    _log_plan(logger, request)
    ready = [plan for plan in request["cases"] if plan["status"] == PLAN_READY]
    logger.step(4, "Calculation and extraction (log steps 4 and 5)")
    try:
        reference = None
        if setting_value('run_reference'):
            reference = _run_reference(app, study_case, qds, request, records, original_result, logger,
                                       result_objects, study_time_state)
            results.append(reference)
            check_run_budget(results)
        if ready:
            if not _set_scalar_attribute(qds, PLANNED_OUTAGE_OPTION, 1):
                raise GridLensError(
                    "The 'Planned Outages' option [{}] could not be switched "
                    "on, so no case run was started.".format(
                        PLANNED_OUTAGE_OPTION))
            logger.write(
                "CALCULATION",
                "Switched the 'Planned Outages' option [{}] on; every planning "
                "case is calculated with exactly its own planned outages, one "
                "after the other.".format(PLANNED_OUTAGE_OPTION), 4)
            calculated = {}
            for plan in ready:
                source = calculated.get(plan["fingerprint"])
                if source is not None and source["status"] == CONVERGED:
                    logger.case("Case {} · {}".format(plan["id"], plan["name"]))
                    logger.detail("Same outages and windows as {}; its result is reused, no QDS run.".format(source["id"]))
                    results.append(_reused_result(source, plan, request))
                    RUN_STATS.count("reused_cases")
                    continue
                result = _run_planning_case(app, study_case, qds, plan, request, records, reference,
                                            original_result, logger, result_objects, study_time_state)
                calculated.setdefault(plan["fingerprint"], result)
                results.append(result)
                # Stop before the next run rather than after the last one.
                check_run_budget(results)
        else:
            logger.write(
                "CALCULATION",
                "No planning case can be calculated; the case runs were skipped.", 4, "WARNING")
        if ready and N1_REFERENCE in (request.get("assessments") or ()):
            run_n1(app, study_case, qds, request, records, ready, results, logger, study_time_state)
    finally:
        logger.step(6, "Restore and clean-up")
        restoring = time.monotonic()
        logger.write("RESTORE", "Restoring the original PowerFactory state.", 6)
        state_errors.extend(_restore_study_time(study_time_state, logger))
        state_errors.extend(
            _restore_planned_outage_option(qds, original_option, logger))
        state_errors.extend(_restore_results_binding(qds, original_result))
        _log_kept_results(result_objects, logger)
        RUN_STATS.add("restore PowerFactory state", time.monotonic() - restoring)
    if state_errors:
        raise GridLensError(
            "GridLens could not fully restore PowerFactory state: {}. Stop and "
            "verify the study case manually before continuing.".format(
                "; ".join(state_errors)))
    logger.write("RESTORE", "Original PowerFactory state restored and verified.", 6)
    for result in results:
        release_values(result)
    check_run_budget(results)
    apply_reference(results)
    judge_cases(results)
    logger.step(7, "Results and report publication")
    _log_results(logger, results, request)
    try:
        project = app.GetActiveProject()
    except Exception:
        project = None
    if ready and setting_value('run_reference'):
        run_mode = "REFERENCE + PLANNING CASES"
    elif ready:
        run_mode = "PLANNING CASES ONLY"
    elif setting_value('run_reference'):
        run_mode = "REFERENCE ONLY - NO PLANNING CASE TO CALCULATE"
    else:
        run_mode = "NO CALCULATION - NO PLANNING CASE TO CALCULATE"
    building = time.monotonic()
    payload = build_cases_payload(
        study_case, results,
        object_name(project) if project else "Active PowerFactory model",
        "{} result object(s) kept in study case '{}': {}".format(
            len(result_objects), object_name(study_case), result_objects.name_for("*"))
        if result_objects else "No calculation executed",
        request, _generated_by(), run_mode)
    RUN_STATS.add("build report tables", time.monotonic() - building)
    RUN_STATS.count("report_rows", sum(len(payload.get(name) or []) for name, _ in TABLES))
    _log_findings(logger, payload)
    if report is None:
        counts = {name: len(payload.get(name) or []) for name, _ in TABLES}
        logger.write(
            "COMPLETE",
            "Standalone run finished: {} report table(s) built, none published; {} planning case(s), {} calculated "
            "case(s).".format(len(counts), len(request["cases"]), len(results)), 7)
        logger.table(("Table", "Rows (built, not published)"), [(name, count) for name, count in counts.items() if count])
        log_run_summary(logger)
        return counts
    logger.write(
        "REPORT", "Preparing publication of {} report tables.".format(len(TABLES)), 7)
    with RUN_STATS.measure("publish report tables"):
        counts = publish_report(report, payload, log=lambda message: logger.write(
            "REPORT", message, 7))
    logger.write(
        "COMPLETE",
        "Report published successfully: {} table(s), {} planning case(s), "
        "{} calculated case(s). Generate the report now from the IntReport "
        "'{}' that contains this script.".format(
            len(counts), len(request["cases"]), len(results), object_name(report)), 7)
    logger.table(
        ("Table", "Rows"),
        [(name, count) for name, count in counts.items() if count])
    log_run_summary(logger)
    return counts


# Said when a run fails without publication: generating the report then
# fails in PowerFactory with "exit with error, see ReportsNet.log" because the
# Scripted... tables do not exist.
NO_REPORT_DATA = ("No report tables were published in this run. GridLens ends with exit code {} so that "
                  "PowerFactory does not generate the report from them; generating it by hand would fail with "
                  "'Scripted... not found' (see ReportsNet.log). Generate the report only after a run that ends "
                  "with 'Report published successfully'.")
# Exit code of the ComPython when a run ends without publication (Cancel or an
# error): not 0, so that an IntReport does not go on to render its report.
NO_REPORT_EXIT_CODE = 1


def main():
    try:
        import powerfactory
    except ImportError:
        print(
            "[GridLens][ERROR][STARTUP] The PowerFactory Python module is not "
            "available. Run this file from DIgSILENT PowerFactory 2026.",
            flush=True)
        return False
    app = powerfactory.GetApplication()
    if app is None:
        print(
            "[GridLens][ERROR][STARTUP] PowerFactory did not return an "
            "application object.", flush=True)
        return False
    logger = RunLogger(app)
    try:
        execute_gridlens(app)
        return True
    except GridLensCancelled as exc:
        logger.write("CANCELLED", "{} Report generation cancelled.".format(exc), level="INFO")
        # This script can be an IntReport extension. Returning False here is
        # discarded by the top-level main() call and looks like a successful
        # extension to the host, which can then render missing or stale tables.
        # Let the cancellation reach the caller before it continues the report.
        raise
    except KeyboardInterrupt:
        logger.write(
            "ABORTED",
            "The run was cancelled. GridLens attempted to restore all state; "
            "review the RESTORE messages above before continuing.",
            level="ERROR")
    except BaseException as exc:
        logger.write(
            "FAILED",
            "{} Recommended action: correct the reported condition, verify the "
            "active study case, and run GridLens again. {}".format(
                _friendly_exception(exc), NO_REPORT_DATA.format(NO_REPORT_EXIT_CODE)), level="ERROR")
        log_run_summary(logger)
    finally:
        # The interpreter can outlive the run; the next run starts from the defaults.
        reset_settings()
    return False


def exit_code(published):
    """0 after a published report, otherwise NO_REPORT_EXIT_CODE: Cancel or an error stops the report."""
    return 0 if published else NO_REPORT_EXIT_CODE


if __name__ == "__main__":
    code = exit_code(main())
    if code:
        # Ends the ComPython with an error code; nothing was published, so
        # the report must not be generated.
        raise SystemExit(code)
