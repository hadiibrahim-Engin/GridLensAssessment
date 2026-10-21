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
LOADING_MAX = 100.0
# Loading classes and the appendix start here.
LOADING_WARNING = 80.0
# Smaller changes count as unchanged: %-points for loading, p.u. for voltage.
LOADING_DELTA_TOLERANCE = 0.1
VOLTAGE_DELTA_TOLERANCE = 0.001
# The appendix also lists elements that change at least this much.
LOADING_APPENDIX_DELTA = 1.0
VOLTAGE_APPENDIX_DELTA = 0.005
# Permitted voltage band per nominal voltage, in kV:
# (lowest nominal, nominal below which the row applies, minimum, maximum).
# Any other nominal voltage uses VOLTAGE_MIN to VOLTAGE_MAX in p.u.
VOLTAGE_LIMITS_KV = ((300.0, 450.0, 360.0, 420.0), (200.0, 300.0, 198.0, 245.0), (100.0, 150.0, 99.0, 123.0))
VOLTAGE_MIN = 0.95
VOLTAGE_MAX = 1.05
# Below this a node counts as de-energised at that time step, not as a value.
ENERGIZED_MIN_PU = 0.1
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
CASE_CONFIG_SCHEMA = 'gridlens.cases'
CASE_CONFIG_SCHEMA_VERSION = 1
# 'conservative' calculates the complete ComStatsim period for every run.
# 'optimized' only proposes shorter calculation windows in the preview and
# the report; they are not executed, because writing ComStatsim.startTime /
# endTime and the initial state of time-coupled models are not verified yet.
QDS_WINDOW_MODE = 'conservative'
WINDOW_WARMUP_HOURS = 24.0
WINDOW_MERGE_GAP_HOURS = 48.0
# Models with a state carried from step to step. One of them in the active
# grid makes shorter calculation windows inadmissible.
TIME_COUPLED_CLASSES = ('ElmQdsl',)
# A case may give a planned outage a date of its own. Applying it means
# writing IntPlannedout.starttime / endtime for the run; this is off until it
# is verified in PowerFactory, and such a case is reported NOT EVALUATED.
ALLOW_OUTAGE_TIME_OVERRIDE = False
# Optional. An empty string (the default) assesses every element. With a text,
# only elements whose grid (PowerFactory attribute "Grid", cpGrid) has a name
# containing it are assessed and every other element is ignored as foreign
# network, e.g. 'D7' for the Europe model.
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
    return not GRID_NAME_FILTER or GRID_NAME_FILTER in grid_name

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
    for column in range(columns):
        try:
            obj = elmres.GetObject(column)
            variable = str(elmres.GetVariable(column))
            category = result_category(obj, variable)
        except Exception:
            continue
        if not category or variable not in VARIABLES[category]:
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
            'No result series belongs to an element whose grid name contains '
            '{!r} ({} series were out of scope). Grids in the result: {}. Set '
            'GRID_NAME_FILTER at the top of gridlens_report.py to part of one of '
            'these names, or to an empty string to assess every element.'.format(
                GRID_NAME_FILTER, out_of_scope, _grid_listing(grids)))
    cells = rows * len(chosen)
    if cells > MAX_RESULT_CELLS:
        raise RuntimeError('ElmRes contains {} evaluated cells ({} rows x {} series) and exceeds the limit of {} (MAX_RESULT_CELLS).'.format(cells, rows, len(chosen), MAX_RESULT_CELLS))
    series = []
    plot_rows = sample_rows(rows)
    for (_, _), (_, column, obj, variable) in sorted(chosen.items()):
        values = []
        category = result_category(obj, variable)
        dark = 0
        for row, value in enumerate(read_column(elmres, column, rows)):
            if value is None and category != 'voltage':
                raise RuntimeError('Invalid result value in ElmRes cell ({}, {}) for {} {}.'.format(row, column, object_name(obj), variable))
            if category == 'voltage' and (value is None or value < ENERGIZED_MIN_PU):
                # A node an outage cuts off is reported as 0 or as NaN: both mean
                # de-energised, no value. A loading that is not a number still stops the run.
                value = None
                dark += 1
            values.append(value)
        if counters is not None:
            counters['deenergized_steps'] += dark
        if dark == len(values):
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
        raise RuntimeError('ElmRes contains no completely readable supported result series.')
    return (series, labels, plot_times, time_unit, absolute, origin)

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
    if len(points) <= MAX_PLOT_POINTS:
        return points
    return [points[index] for index in sample_rows(len(points))]

def sample_rows(count):
    """Row indices of the plot: all up to MAX_PLOT_POINTS, otherwise a grid that depends only on `count`."""
    if count <= MAX_PLOT_POINTS:
        return list(range(count))
    return sorted({int(round(sample * (count - 1) / float(MAX_PLOT_POINTS - 1))) for sample in range(MAX_PLOT_POINTS)})

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

def voltage_band(nominal_kv):
    """Permitted voltage in p.u. of the nominal voltage (lower, upper)."""
    if nominal_kv:
        for lowest, highest, minimum, maximum in VOLTAGE_LIMITS_KV:
            if lowest <= nominal_kv < highest:
                return minimum / nominal_kv, maximum / nominal_kv
    return VOLTAGE_MIN, VOLTAGE_MAX

def voltage_limits(item):
    return item.get('limits') or (VOLTAGE_MIN, VOLTAGE_MAX)

def is_critical(item, stats):
    if stats is None:
        return False
    if item['category'] in ('line', 'transformer'):
        return stats['max'] > LOADING_MAX
    if item['category'] == 'voltage':
        lower, upper = voltage_limits(item)
        return stats['min'] < lower or stats['max'] > upper
    return False
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
        limit = LOADING_MAX
        return lambda value: value - limit if value > limit else 0.0
    lower, upper = voltage_limits(item)
    return lambda value: lower - value if value < lower else value - upper if value > upper else 0.0

def excess(item, value):
    """How far a value lies beyond its limit; 0 on or inside the limit."""
    return excess_function(item)(value)

def _tolerance(item):
    return LOADING_DELTA_TOLERANCE if item['category'] in LOADING_CATEGORIES else VOLTAGE_DELTA_TOLERANCE

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
    if item['category'] in LOADING_CATEGORIES:
        return outage['max'] - ref['max'] > LOADING_DELTA_TOLERANCE
    lower, upper = voltage_limits(item)
    return ((outage['min'] < lower and outage['min'] < ref['min'] - VOLTAGE_DELTA_TOLERANCE)
            or (outage['max'] > upper and outage['max'] > ref['max'] + VOLTAGE_DELTA_TOLERANCE))

def _better(item, ref, outage):
    if item['category'] in LOADING_CATEGORIES:
        return ref['max'] - outage['max'] > LOADING_DELTA_TOLERANCE
    lower, upper = voltage_limits(item)
    return max(lower - outage['min'], outage['max'] - upper) < max(lower - ref['min'], ref['max'] - upper) - VOLTAGE_DELTA_TOLERANCE

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

LOADING_CLASSES = (('up to 80 %', lambda value: value <= LOADING_WARNING), ('80 to 100 %', lambda value: value <= LOADING_MAX), ('above 100 %', lambda value: True))
CATEGORY_LABELS = (('line', 'Line loading', 'line', 'lines'), ('transformer', 'Transformer loading', 'transformer', 'transformers'), ('voltage', 'Voltage magnitude', 'node', 'nodes'))
REFERENCE_NAME = 'Reference'
MAX_REFERENCE_ROWS = 30

def voltage_limits_text():
    bands = ['{} to {} kV for a nominal voltage from {} kV up to {} kV'.format(format_limit(minimum), format_limit(maximum), format_limit(lowest), format_limit(highest)) for lowest, highest, minimum, maximum in VOLTAGE_LIMITS_KV]
    return 'Permitted voltage band: {}; {} to {} p.u. for any other nominal voltage. Values on the band limit are no violation.'.format('; '.join(bands), format_limit(VOLTAGE_MIN), format_limit(VOLTAGE_MAX))

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
        if max(peaks) < LOADING_WARNING and not any(abs(delta) >= LOADING_APPENDIX_DELTA for delta in deltas):
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
        if all(status == STATUS_OK for status in statuses) and change < VOLTAGE_APPENDIX_DELTA:
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
        ordered = sorted(entries.values(), key=lambda entry: (-entry[1]['max'], entry[0]['element_name'].casefold()))[:TOP_N]
        ranked[result_id] = ['{} - {}'.format(item['element_name'], loading_text(stats['max'])) for item, stats in ordered]
    cases = outage_cases(results)
    rows = []
    for rank in range(1, TOP_N + 1):
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
        counts = [0] * len(LOADING_CLASSES)
        if reference is not None:
            for _, stats in reference['by_category'][category]:
                counts[next(index for index, (_, fits) in enumerate(LOADING_CLASSES) if fits(stats['max']))] += 1
        for order, ((label, _), count) in enumerate(zip(LOADING_CLASSES, counts), 1):
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
    for rank, (name, value, case_name) in enumerate(sorted(best.values(), key=lambda entry: (-entry[1], entry[0].casefold()))[:TOP_N], 1):
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
    if largest is not None and largest[0] > LOADING_DELTA_TOLERANCE:
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
        pair = max((row for row in rows if row['delta'] is not None and row['delta'] > LOADING_DELTA_TOLERANCE), key=lambda row: row['delta'], default=None)
        payload['ScriptedKpis'].append({
            'highest_text': '{} · {}'.format(loading_text(top['max']), top['element']), 'highest_caption': 'Highest observed line loading across all cases',
            'highest_violation': 1 if top['max'] > LOADING_MAX else 0,
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
                 '{} defined ({}); {} ready, {} not calculated.'.format(
                     _counted(len(plans), 'case', 'cases'), request.get('source_text', ''), len(plans) - len(blocked), len(blocked)),
                 ', '.join(plan['name'] for plan in blocked[:5]) or '-')
    for number, warning in enumerate(request.get('warnings') or (), 1):
        _quality(payload, 'request_warning_{}'.format(number), 'Fixed outages', 'WARNING', warning)
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
                     _counted(counters.get('deenergized_steps', 0), 'time step', 'time steps'), format_limit(ENERGIZED_MIN_PU)))
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
    _quality(payload, 'security_scope', 'Assessment scope', 'WARNING',
             'N-0 assessment of the planned network states. N-1 security, security of supply, protection coordination and safe isolation are not assessed.')
    _quality(payload, 'limit_loading', 'Loading limit', 'INFO', 'Violation when loading > {} %.'.format(format_limit(LOADING_MAX)))
    _quality(payload, 'limit_voltage', 'Voltage limits', 'INFO', voltage_limits_text())

def qds_mode_text(request):
    mode = (request or {}).get('mode', QDS_WINDOW_MODE)
    text = 'Conservative: every run covers the complete ComStatsim period; no time window is skipped.'
    if mode == 'optimized':
        proposed = (request or {}).get('optimization') or {}
        text += ' Optimized windows were proposed ({}) but not executed: {}'.format(
            proposed.get('summary', 'none'), proposed.get('reason', 'shorter QDS periods are not verified in PowerFactory yet.'))
    return text

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
        if values.get('delta') is not None and values['delta'] > LOADING_DELTA_TOLERANCE:
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
    text = 'QDS: complete ComStatsim period'
    proposed = plan.get('calc_windows') or []
    if (request or {}).get('mode') == 'optimized' and proposed:
        text += '; proposed (not executed): ' + '; '.join(period_text(_format_pf_time(start), _format_pf_time(end)) for start, end in proposed)
    return text

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
        'assessment_scope': '{} planning case(s); reference: {}; {}'.format(len(request.get('cases') or ()), reference['name'] if reference else 'none', 'elements in grids named *{}*'.format(GRID_NAME_FILTER) if GRID_NAME_FILTER else 'all elements'),
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
OUTAGE_CLASSES = ("IntPlannedout", "IntOutage")
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
            'background': [], 'cases': [], 'exclusive_groups': [], 'rules': []}


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


def validate_case_config(config):
    """Structural problems of a configuration, as messages; [] when it can be used.

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
    if not _is_text_list(config.get('background', [])):
        problems.append('background must be a list of planned outage paths')
    cases = config.get('cases', [])
    if not isinstance(cases, list) or not all(isinstance(case, dict) for case in cases):
        return problems + ['cases must be a list of objects']
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
    problems = validate_case_config(config)
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
    for case in config.get('cases') or ():
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
                plan['relations'].append((left['name'], right['name'], interval_relation(a, b)))
                shared = set(left.get('component_keys') or ()) & set(right.get('component_keys') or ())
                if shared and windows_overlap(a, b):
                    plan['warnings'].append('{} and {} switch the same equipment at the same time; PowerFactory switches it once and '
                                            'the earlier end may put it back into service'.format(left['name'], right['name']))
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
            'optimization': None, 'warnings': request_warnings}


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


def optimization_summary(request, period, app=None):
    """What shorter calculation windows would save; never executed in this version."""
    begin, finish = period
    full = (finish - begin) / 3600.0 if begin is not None and finish is not None else None
    proposed = [window for plan in request['cases'] if plan['status'] == PLAN_READY for window in plan['calc_windows']]
    hours = sum((min(end, finish) - max(start, begin)) / 3600.0 for start, end in proposed) if full is not None else None
    coupled = []
    if app is not None:
        for class_pattern in TIME_COUPLED_CLASSES:
            try:
                found = app.GetCalcRelevantObjects('*.' + class_pattern) or []
            except Exception:
                found = []
            if found:
                coupled.append('{} {}'.format(len(found), class_pattern))
    reason = ('the active grid contains time-coupled models ({}), whose state at a window start differs from a continuous run'.format(', '.join(coupled))
              if coupled else 'writing the QDS period and the initial state of time-coupled models are not verified in PowerFactory yet')
    summary = '{} window(s), {} h instead of {} h per case'.format(
        len(proposed), '{:.0f}'.format(hours) if hours is not None else '?', '{:.0f}'.format(full) if full is not None else '?')
    return {'summary': summary, 'reason': reason, 'admissible': False, 'time_coupled': coupled, 'executed': False}


def case_config_path(project_key):
    folder = CASE_CONFIG_DIR or os.path.join(os.path.expanduser('~'), 'GridLens', 'cases')
    stem = re.sub(r'[^A-Za-z0-9_.-]+', '_', project_key.rsplit('\\', 1)[-1])[:40] or 'project'
    digest = hashlib.sha256(project_key.encode('utf-8')).hexdigest()[:8]
    return os.path.join(folder, '{}_{}.json'.format(stem, digest))


def load_case_config(path):
    """The saved configuration, or None when there is none; a damaged file raises."""
    if not os.path.isfile(path):
        return None
    try:
        with open(path, 'r', encoding='utf-8') as handle:
            config = json.load(handle)
    except (OSError, ValueError) as exc:
        raise GridLensError('The saved case configuration {} cannot be read: {}'.format(path, exc)) from None
    problems = validate_case_config(config)
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


def preview_text(request, period=(None, None)):
    """What OK would calculate, as plain text for the case manager and the log."""
    lines = ['Reference: {}'.format(_reference_text(request)),
             'Calculation mode: {}'.format(request['mode']),
             'Simulated period: {} to {}'.format(_format_pf_time(period[0]) or '?', _format_pf_time(period[1]) or '?'), '']
    ready = [plan for plan in request['cases'] if plan['status'] == PLAN_READY]
    groups = {}
    for plan in ready:
        groups.setdefault(plan['fingerprint'], []).append(plan['id'])
    runs = len(groups) + (1 if RUN_REFERENCE_CASE else 0)
    lines.append('{} case(s), {} ready; QDS runs: {} ({} reference){}.'.format(
        len(request['cases']), len(ready), runs, 1 if RUN_REFERENCE_CASE else 0,
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
        if plan['calc_windows']:
            lines.append('   proposed QDS windows: ' + '; '.join(
                period_text(_format_pf_time(start), _format_pf_time(end)) for start, end in plan['calc_windows']))
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


CHECKED, UNCHECKED = '[x]', '[ ]'


def _parse_rules(text, records):
    """'not_overlap: FS1, FS2' per line -> rule dictionaries keyed by outage path."""
    by_id = {record['id']: record for record in records}
    rules, problems = [], []
    for number, line in enumerate(text.splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        kind, _, rest = line.partition(':')
        names = [name.strip() for name in rest.split(',') if name.strip()]
        if kind.strip() not in RULE_KINDS or len(names) != 2:
            problems.append('line {}: write "<{}>: <outage>, <outage>"'.format(number, '|'.join(RULE_KINDS)))
            continue
        missing = [name for name in names if name not in by_id]
        if missing:
            problems.append('line {}: unknown outage {}'.format(number, ', '.join(missing)))
            continue
        rules.append({'kind': kind.strip(), 'first': by_id[names[0]]['key'], 'second': by_id[names[1]]['key']})
    return rules, problems


def _rules_text(rules, records):
    by_key = {record['key']: record['id'] for record in records}
    return '\n'.join('{}: {}, {}'.format(rule['kind'], by_key.get(rule['first'], rule['first']), by_key.get(rule['second'], rule['second']))
                     for rule in rules)


def _parse_time(text):
    """'YYYY-MM-DD HH:MM' in local time -> epoch seconds."""
    return time.mktime(datetime.strptime(text.strip(), '%Y-%m-%d %H:%M').timetuple())


class CaseEditor:
    """Every editing step of the case manager, without a window.

    The dialog only shows this state and forwards clicks, so the editing
    rules can be tested without Tk. The configuration is a private copy; it
    reaches the caller only through OK.
    """

    def __init__(self, records, config, period):
        self.records = list(records)
        self.by_key = {record['key']: record for record in self.records}
        self.config = json.loads(json.dumps(config))
        for name in ('cases', 'background', 'rules', 'exclusive_groups'):
            self.config.setdefault(name, [])
        self.period = period

    def case(self, case_id):
        return next((case for case in self.config['cases'] if case['id'] == case_id), None)

    def suggested_id(self):
        count = len(self.config['cases'])
        return chr(ord('A') + count) if count < 26 else ''

    def id_problem(self, identifier):
        """Why `identifier` cannot be used for a new case; None when it can."""
        if not CASE_ID_PATTERN.match(identifier) or identifier.upper() == REFERENCE_ID:
            return 'The ID is not allowed: letters, digits, _ and -, up to 16 characters, not REF.'
        if self.case(identifier) is not None:
            return 'The ID {} is already used.'.format(identifier)
        return None

    def add_case(self, identifier, name):
        self.config['cases'].append({'id': identifier, 'name': name or identifier, 'description': '', 'outages': [],
                                     'includes': [], 'requires': [], 'overrides': {}})

    def rename_case(self, case_id, name):
        case = self.case(case_id)
        if case is not None and name.strip():
            case['name'] = name.strip()

    def copy_case(self, case_id, identifier):
        case = self.case(case_id)
        if case is None:
            return
        copy = json.loads(json.dumps(case))
        copy.update(id=identifier, name=case.get('name', '') + ' (copy)')
        self.config['cases'].append(copy)

    def delete_case(self, case_id):
        case = self.case(case_id)
        if case is not None:
            self.config['cases'].remove(case)

    def one_case_per_outage(self):
        candidates = [record for record in self.records if not record.get('originally_ignored')]
        self.config['cases'] = per_outage_config(candidates)['cases']

    def toggle_member(self, case_id, key):
        case = self.case(case_id)
        if case is None or key not in self.by_key:
            return
        outages = case.setdefault('outages', [])
        if key in outages:
            outages.remove(key)
            (case.get('overrides') or {}).pop(key, None)
        else:
            outages.append(key)

    def toggle_fixed(self, key):
        if key not in self.by_key:
            return
        fixed = self.config['background']
        if key in fixed:
            fixed.remove(key)
        else:
            fixed.append(key)

    def set_own_dates(self, case_id, key, start_text, end_text):
        """Record own dates ('YYYY-MM-DD HH:MM'); an empty start removes them. A problem as text, else None."""
        case = self.case(case_id)
        if case is None or key not in (case.get('outages') or ()):
            return 'Select an outage that belongs to the selected case.'
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

    def set_details(self, case_id, description, includes_text, requires_text):
        case = self.case(case_id)
        if case is not None:
            case['description'] = description.strip()
            case['includes'] = [item.strip() for item in includes_text.split(',') if item.strip()]
            case['requires'] = [item.strip() for item in requires_text.split(',') if item.strip()]

    def set_request(self, rules_text, exclusive_text, mode):
        """Rules, alternatives and mode as typed; every problem as a message."""
        parsed, problems = _parse_rules(rules_text, self.records)
        if problems:
            return problems
        self.config['rules'] = parsed
        self.config['exclusive_groups'] = [[item.strip() for item in group.split('|') if item.strip()]
                                           for group in exclusive_text.split(';') if group.strip()]
        self.config['mode'] = mode
        return validate_case_config(self.config)

    def rules_text(self):
        return _rules_text(self.config['rules'], self.records)

    def exclusive_text(self):
        return '; '.join('|'.join(group) for group in self.config['exclusive_groups'])

    def case_labels(self):
        return ['{}  {}  ({} outage(s))'.format(case['id'], case.get('name', ''), len(case.get('outages') or ()))
                for case in self.config['cases']]

    def outage_status(self, record):
        begin, finish = self.period
        start, end = record['window']
        if record.get('originally_ignored'):
            return 'Ignored in PowerFactory'
        if begin is not None and start is not None and end is not None and (end <= begin or start >= finish):
            return 'outside simulated period'
        return 'in simulated period'

    def outage_rows(self, case_id):
        """(key, cells) of the outage table for the selected case."""
        case = self.case(case_id)
        members = set(case.get('outages') or ()) if case else set()
        fixed = set(self.config['background'])
        rows = []
        for record in self.records:
            override = (case.get('overrides') or {}).get(record['key']) if case else None
            rows.append((record['key'], (
                CHECKED if record['key'] in members else UNCHECKED, CHECKED if record['key'] in fixed else UNCHECKED,
                record['id'], clip_text(record.get('equipment_name') or '-', 60),
                _format_pf_time(override[0]) + ' *' if override else record.get('start_time') or '?',
                _format_pf_time(override[1]) + ' *' if override else record.get('end_time') or '?',
                int(record.get('priority') or 0), self.outage_status(record))))
        return rows

    def request(self):
        return resolve_request(self.config, self.records, self.period, 'gui')


class CaseManagerDialog:
    """The tkinter window of the case manager; all state lives in a CaseEditor."""

    OUTAGE_COLUMNS = (('in_case', 'Case', 50), ('fixed', 'Fixed', 50), ('name', 'Planned outage', 190),
                      ('equipment', 'Equipment', 230), ('start', 'Start', 120), ('end', 'End', 120),
                      ('priority', 'Prio', 45), ('status', 'Status', 150))

    def __init__(self, root, editor, config_path, user, tk_modules):
        self.root = root
        self.editor = editor
        self.config_path = config_path
        self.user = user
        self.tk, self.ttk, self.messagebox, self.simpledialog = tk_modules
        self.selected = None
        self.outcome = None

    # --- window -------------------------------------------------------------
    def build(self):
        tk, ttk, root = self.tk, self.ttk, self.root
        root.title('GridLens {} - planning cases'.format(PUBLISHER_VERSION))
        root.geometry('1280x820')
        root.minsize(1000, 640)
        # Areas 1 and 3: planned outages and the assignment of the selected case.
        top = ttk.Panedwindow(root, orient='horizontal')
        top.pack(fill='both', expand=True, padx=8, pady=(8, 4))
        left = ttk.Labelframe(top, text='Planned outages - double-click assigns to / removes from the selected case')
        right = ttk.Labelframe(top, text='Planning cases')
        top.add(left, weight=3)
        top.add(right, weight=1)
        self.tree = ttk.Treeview(left, columns=[column for column, _, _ in self.OUTAGE_COLUMNS], show='headings', selectmode='browse')
        for column, label, width in self.OUTAGE_COLUMNS:
            self.tree.heading(column, text=label)
            self.tree.column(column, width=width, stretch=column in ('name', 'equipment'))
        scroll = ttk.Scrollbar(left, orient='vertical', command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side='left', fill='both', expand=True)
        scroll.pack(side='right', fill='y')
        # Area 2: planning cases.
        self.case_list = tk.Listbox(right, exportselection=False, height=12)
        self.case_list.pack(fill='both', expand=True, padx=4, pady=4)
        buttons = ttk.Frame(right)
        buttons.pack(fill='x', padx=4)
        details = ttk.Frame(right)
        details.pack(fill='x', padx=4, pady=4)
        self.description, self.includes, self.requires = tk.StringVar(), tk.StringVar(), tk.StringVar()
        for row, (label, variable) in enumerate((('Description', self.description), ('Includes cases (IDs)', self.includes),
                                                 ('Only together with (IDs)', self.requires))):
            ttk.Label(details, text=label).grid(row=row, column=0, sticky='w')
            ttk.Entry(details, textvariable=variable).grid(row=row, column=1, sticky='ew')
        details.columnconfigure(1, weight=1)
        # Areas 4 to 6: relations, mode and preview.
        bottom = ttk.Frame(root)
        bottom.pack(fill='both', expand=True, padx=8, pady=4)
        settings = ttk.Labelframe(bottom, text='Assessment request')
        settings.pack(side='left', fill='y')
        self.exclusive = tk.StringVar(value=self.editor.exclusive_text())
        self.mode = tk.StringVar(value=self.editor.config.get('mode', QDS_WINDOW_MODE))
        ttk.Label(settings, text='Alternative cases, never combined (A|B; C|D)').pack(anchor='w', padx=4)
        ttk.Entry(settings, textvariable=self.exclusive, width=42).pack(fill='x', padx=4)
        ttk.Label(settings, text='Rules, one per line: not_overlap / order / together: FS1, FS2').pack(anchor='w', padx=4, pady=(6, 0))
        self.rules = tk.Text(settings, height=5, width=42)
        self.rules.insert('1.0', self.editor.rules_text())
        self.rules.pack(fill='x', padx=4)
        ttk.Label(settings, text='QDS period').pack(anchor='w', padx=4, pady=(6, 0))
        ttk.Radiobutton(settings, text='Conservative - complete ComStatsim period', variable=self.mode, value='conservative').pack(anchor='w', padx=4)
        ttk.Radiobutton(settings, text='Optimized - propose shorter windows (preview only)', variable=self.mode, value='optimized').pack(anchor='w', padx=4)
        ttk.Label(settings, text='Saved as: ' + self.config_path, wraplength=330).pack(anchor='w', padx=4, pady=(8, 0))
        preview_frame = ttk.Labelframe(bottom, text='Calculation preview - nothing is calculated here')
        preview_frame.pack(side='left', fill='both', expand=True, padx=(8, 0))
        self.preview = tk.Text(preview_frame, height=14, wrap='word', font=('Consolas', 9))
        self.preview.pack(fill='both', expand=True)
        for label, command in (('New', self.add_case), ('Rename', self.rename_case), ('Copy', self.copy_case),
                               ('Delete', self.delete_case), ('One case per outage', self.one_case_per_outage)):
            ttk.Button(buttons, text=label, command=command).pack(side='left', padx=1)
        actions = ttk.Frame(root)
        actions.pack(fill='x', padx=8, pady=(4, 8))
        for label, command in (('Assign / remove', self.toggle_member), ('Fixed outage (reference)', self.toggle_fixed),
                               ('Own dates', self.set_own_dates)):
            ttk.Button(actions, text=label, command=command).pack(side='left', padx=2)
        for label, command in (('Cancel', self.cancel), ('OK - calculate', self.confirm), ('Save configuration', self.save),
                               ('Preview', self.show_preview)):
            ttk.Button(actions, text=label, command=command).pack(side='right', padx=2)
        self.case_list.bind('<<ListboxSelect>>', self.on_select)
        self.tree.bind('<Double-1>', self.toggle_member)
        self.tree.bind('<space>', self.toggle_member)
        root.protocol('WM_DELETE_WINDOW', self.cancel)
        cases = self.editor.config['cases']
        self.refresh_cases(cases[0]['id'] if cases else None)
        self.show_preview()

    def report_error(self, kind, value, _trace):
        # Tk swallows exceptions of button callbacks; show them instead, the
        # dialog stays open and nothing has been calculated.
        try:
            self.messagebox.showerror('GridLens case manager', '{}: {}'.format(kind.__name__, value), parent=self.root)
        except Exception:
            pass

    # --- showing the editor state --------------------------------------------
    def store_details(self):
        self.editor.set_details(self.selected, self.description.get(), self.includes.get(), self.requires.get())

    def refresh_outages(self):
        self.tree.delete(*self.tree.get_children())
        for key, cells in self.editor.outage_rows(self.selected):
            self.tree.insert('', 'end', iid=key, values=cells)

    def refresh_cases(self, select=None):
        self.case_list.delete(0, 'end')
        for label in self.editor.case_labels():
            self.case_list.insert('end', label)
        identifiers = [case['id'] for case in self.editor.config['cases']]
        if select in identifiers:
            self.case_list.selection_set(identifiers.index(select))
        self.selected = select if select in identifiers else None
        case = self.editor.case(self.selected)
        self.description.set(case.get('description', '') if case else '')
        self.includes.set(', '.join(case.get('includes') or ()) if case else '')
        self.requires.set(', '.join(case.get('requires') or ()) if case else '')
        self.refresh_outages()

    def on_select(self, _event=None):
        self.store_details()
        chosen = self.case_list.curselection()
        self.refresh_cases(self.editor.config['cases'][chosen[0]]['id'] if chosen else None)

    # --- buttons ---------------------------------------------------------------
    def ask_id(self, title, initial=''):
        while True:
            value = self.simpledialog.askstring(title, 'Case ID (letters, digits, _ and -, up to 16):', initialvalue=initial, parent=self.root)
            if value is None:
                return None
            problem = self.editor.id_problem(value.strip())
            if problem is None:
                return value.strip()
            self.messagebox.showerror('Case ID', problem, parent=self.root)

    def add_case(self):
        self.store_details()
        identifier = self.ask_id('New case', self.editor.suggested_id())
        if identifier is None:
            return
        name = self.simpledialog.askstring('New case', 'Name:', initialvalue='Case ' + identifier, parent=self.root)
        self.editor.add_case(identifier, name or identifier)
        self.refresh_cases(identifier)

    def rename_case(self):
        case = self.editor.case(self.selected)
        if case is None:
            return
        name = self.simpledialog.askstring('Rename case', 'Name:', initialvalue=case.get('name', ''), parent=self.root)
        if name:
            self.editor.rename_case(case['id'], name)
            self.refresh_cases(case['id'])

    def copy_case(self):
        self.store_details()
        if self.editor.case(self.selected) is None:
            return
        identifier = self.ask_id('Copy case', self.selected + '_copy')
        if identifier is not None:
            self.editor.copy_case(self.selected, identifier)
            self.refresh_cases(identifier)

    def delete_case(self):
        if self.editor.case(self.selected) is not None and self.messagebox.askyesno(
                'Delete case', 'Delete case {}?'.format(self.selected), parent=self.root):
            self.editor.delete_case(self.selected)
            self.refresh_cases(None)

    def one_case_per_outage(self):
        if self.editor.config['cases'] and not self.messagebox.askyesno(
                'One case per outage', 'Replace the cases by one case per planned outage?', parent=self.root):
            return
        self.editor.one_case_per_outage()
        cases = self.editor.config['cases']
        self.refresh_cases(cases[0]['id'] if cases else None)

    def toggle_member(self, _event=None):
        key = self.tree.focus()
        if not key:
            return
        if self.selected is None:
            self.messagebox.showinfo('Planning case', 'Select or create a case first.', parent=self.root)
            return
        self.editor.toggle_member(self.selected, key)
        self.refresh_cases(self.selected)
        self.tree.focus(key)
        self.tree.selection_set(key)

    def toggle_fixed(self):
        key = self.tree.focus()
        if key:
            self.editor.toggle_fixed(key)
            self.refresh_outages()

    def set_own_dates(self):
        key = self.tree.focus()
        case = self.editor.case(self.selected)
        if case is None or key not in (case.get('outages') or ()):
            self.messagebox.showinfo('Own dates', 'Select an outage that belongs to the selected case.', parent=self.root)
            return
        record = self.editor.by_key[key]
        start = self.simpledialog.askstring('Own dates', 'Start in this case (YYYY-MM-DD HH:MM), empty for the original:',
                                            initialvalue=record.get('start_time', ''), parent=self.root)
        if start is None:
            return
        end = ''
        if start.strip():
            end = self.simpledialog.askstring('Own dates', 'End in this case (YYYY-MM-DD HH:MM):',
                                              initialvalue=record.get('end_time', ''), parent=self.root) or ''
        problem = self.editor.set_own_dates(self.selected, key, start, end)
        if problem:
            self.messagebox.showerror('Own dates', problem, parent=self.root)
            return
        if start.strip() and not ALLOW_OUTAGE_TIME_OVERRIDE:
            self.messagebox.showwarning('Own dates', 'Own dates are recorded, but this version does not apply them: the case will be '
                                        'reported NOT EVALUATED. Create a planned outage with these dates for a calculation.', parent=self.root)
        self.refresh_outages()

    def collect(self):
        """True when the typed rules, alternatives and mode are valid; otherwise the problems are shown."""
        self.store_details()
        problems = self.editor.set_request(self.rules.get('1.0', 'end'), self.exclusive.get(), self.mode.get())
        if problems:
            self.messagebox.showerror('Case configuration', '\n'.join(problems), parent=self.root)
            return False
        return True

    def show_preview(self):
        if not self.collect():
            return None
        request = self.editor.request()
        self.preview.delete('1.0', 'end')
        self.preview.insert('1.0', preview_text(request, self.editor.period))
        return request

    def save(self):
        if not self.collect():
            return
        try:
            stored = save_case_config(self.config_path, self.editor.config, self.user)
        except (OSError, GridLensError) as exc:
            self.messagebox.showerror('Save configuration', str(exc), parent=self.root)
            return
        self.messagebox.showinfo('Save configuration', 'Saved revision {} to\n{}'.format(stored['revision'], self.config_path), parent=self.root)

    def confirm(self):
        request = self.show_preview()
        if request is None:
            return
        ready = [plan for plan in request['cases'] if plan['status'] == PLAN_READY]
        blocked = [plan for plan in request['cases'] if plan['status'] != PLAN_READY]
        if not ready and not self.messagebox.askyesno('Start GridLens', 'No case can be calculated. Calculate the reference only?', parent=self.root):
            return
        if blocked and ready and not self.messagebox.askyesno(
                'Start GridLens', '{} case(s) cannot be calculated and will be reported with their reason. Continue?'.format(len(blocked)),
                parent=self.root):
            return
        self.outcome = self.editor.config
        self.root.destroy()

    def cancel(self):
        self.outcome = None
        self.root.destroy()


def run_case_manager(records, config, period, config_path, user=''):
    """Show the dialog; the edited configuration on OK, None on Cancel."""
    try:
        import tkinter as tk
        from tkinter import messagebox, simpledialog, ttk
        root = tk.Tk()
    except Exception as exc:
        raise CaseManagerUnavailable('The case manager cannot open a window: {}'.format(_friendly_exception(exc))) from None
    dialog = CaseManagerDialog(root, CaseEditor(records, config, period), config_path, user, (tk, ttk, messagebox, simpledialog))
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
        raise GridLensError(
            "{} calculation was interrupted or failed: {}".format(
                case_id, _friendly_exception(exc))) from None
    elapsed = time.monotonic() - started
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
        snapshot.Load()
        counters = {}
        series, labels, plot_times, unit, absolute, origin = collect_series(
            snapshot, counters)
        if GRID_NAME_FILTER:
            logger.write(
                "EXTRACTION",
                "Grid scope {!r}: {} series assessed, {} out of scope and "
                "not read.".format(GRID_NAME_FILTER, len(series),
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
            "{} completed, but its ElmRes could not be evaluated: {}".format(
                case_id, _friendly_exception(exc))) from None
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


def obtain_case_request(app, records, candidates, period, logger):
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
        config = run_case_manager(records, saved or empty_case_config(project_key), period, path, _generated_by())
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
                                    for name in ("cases", "background", "rules", "exclusive_groups", "mode"))
    return resolve_request(config, records, period, "gui", "case manager, configuration revision {}{}".format(
        config.get("revision") or 0, " with unsaved changes" if unsaved else ""))


def _log_plan(logger, request):
    logger.detail("Planning cases from: {}".format(request["source_text"]))
    logger.detail("Reference: {}".format(_reference_text(request)))
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
    logger.detail("Grid scope: {}".format(
        "grids whose name contains {!r}".format(GRID_NAME_FILTER)
        if GRID_NAME_FILTER else "every element"))
    logger.detail("Reference case: {} | case source: {} | QDS period: {}".format(
        "on" if RUN_REFERENCE_CASE else "off", CASE_SOURCE, QDS_WINDOW_MODE))


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


def execute_gridlens(app):
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
    report = script.GetParent()
    if report is None or class_name(report) != "IntReport":
        raise GridLensError(
            "Place this ComPython directly below the target IntReport and retry.")
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
                object_name(original_result), RUN_REFERENCE_CASE), 2)
    _log_context(app, study_case, qds, original_result, logger)
    logger.step(2, "ComStatsim settings")
    _log_qds_settings(qds, original_result, study_time_state, logger)
    results = []
    result_objects = ResultStore()
    state_errors = []
    period = qds_period(qds)
    logger.step(3, "Planned outages and planning cases")
    records, candidates = classify_planned_outages(app, logger, period)
    assign_definitions(records)
    request = obtain_case_request(app, records, candidates, period, logger)
    if request["mode"] == "optimized":
        request["optimization"] = optimization_summary(request, period, app)
    _log_plan(logger, request)
    ready = [plan for plan in request["cases"] if plan["status"] == PLAN_READY]
    logger.step(4, "Calculation and extraction (log steps 4 and 5)")
    try:
        reference = None
        if RUN_REFERENCE_CASE:
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
    finally:
        logger.step(6, "Restore and clean-up")
        logger.write("RESTORE", "Restoring the original PowerFactory state.", 6)
        state_errors.extend(_restore_study_time(study_time_state, logger))
        state_errors.extend(
            _restore_planned_outage_option(qds, original_option, logger))
        state_errors.extend(_restore_results_binding(qds, original_result))
        _log_kept_results(result_objects, logger)
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
    if ready and RUN_REFERENCE_CASE:
        run_mode = "REFERENCE + PLANNING CASES"
    elif ready:
        run_mode = "PLANNING CASES ONLY"
    elif RUN_REFERENCE_CASE:
        run_mode = "REFERENCE ONLY - NO PLANNING CASE TO CALCULATE"
    else:
        run_mode = "NO CALCULATION - NO PLANNING CASE TO CALCULATE"
    payload = build_cases_payload(
        study_case, results,
        object_name(project) if project else "Active PowerFactory model",
        "{} result object(s) kept in study case '{}': {}".format(
            len(result_objects), object_name(study_case), result_objects.name_for("*"))
        if result_objects else "No calculation executed",
        request, _generated_by(), run_mode)
    _log_findings(logger, payload)
    logger.write(
        "REPORT", "Preparing publication of {} report tables.".format(len(TABLES)), 7)
    counts = publish_report(report, payload, log=lambda message: logger.write(
        "REPORT", message, 7))
    logger.write(
        "COMPLETE",
        "Report published successfully: {} table(s), {} planning case(s), "
        "{} calculated case(s).".format(
            len(counts), len(request["cases"]), len(results)), 7)
    logger.table(
        ("Table", "Rows"),
        [(name, count) for name, count in counts.items() if count])
    return counts


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
        logger.write("CANCELLED", str(exc), level="INFO")
        return False
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
            "active study case, and run GridLens again.".format(
                _friendly_exception(exc)), level="ERROR")
    return False


if __name__ == "__main__":
    main()
