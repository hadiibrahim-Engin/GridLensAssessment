"""GridLens assessment and report publication for DIgSILENT PowerFactory 2026.

Run this file as a ComPython in an active study case with a configured
ComStatsim and result variables. As a child of an IntReport it publishes
the report tables; a standalone run builds the tables without publishing.
PDF rendering is handled by PowerFactory.

The runtime uses Python's standard library, PowerFactory's Python module
and tkinter for the optional case manager. No repository modules are required.
Configuration defaults are defined below and can be overridden in the case
manager or the saved case configuration.

Calculation, state restoration, result evaluation and report publication
run sequentially on the PowerFactory thread. Kept ElmRes copies support
subsequent evaluation without recalculation.
"""

from __future__ import annotations

import bisect
import getpass
import hashlib
import heapq
import json
import math
import os
import re
import textwrap
import time
from array import array
from datetime import datetime


# ---------------------------------------------------------------------------
# Runtime configuration and report data contract
# ---------------------------------------------------------------------------

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
TEMPLATE_VERSION = '7.0.0'
DATA_CONTRACT_VERSION = '7.0'
RUN_REFERENCE_CASE = True
# Where the planning cases come from:
#   'gui'        open the case manager; without tkinter use the saved
#                configuration, without one fall back to 'per_outage'
#   'saved'      the configuration saved for this project, no dialog
#   'per_outage' one case per planned outage in the simulated period
CASE_SOURCE = 'gui'
# Folder of the saved case configurations; '' is ~/GridLens/cases.
CASE_CONFIG_DIR = ''
# Default planning-case limit, adjustable in Settings -> Report and run.
# Cases receive IDs C1, C2, ...; the engineer supplies their names.
MAX_CASES = 5
CASE_CONFIG_SCHEMA = 'gridlens.cases'
CASE_CONFIG_SCHEMA_VERSION = 2
# Available assessments; (n-1)' requires the n-1 reference.
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
VARIABLES = {
    'line': ('c:loading', 'm:loading'),
    'transformer': ('c:loading', 'm:loading'),
    'voltage': ('m:u', 'm:u1'),
}
CLASS_CATEGORIES = {
    'ElmLne': ('line',),
    'ElmTr2': ('transformer',),
    'ElmTr3': ('transformer',),
    'ElmTerm': ('voltage',),
}
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
_LABEL_FIELDS = (
    'unit', 'variable', 'status', 'reason', 'action', 'timestamp', 'metric_name',
    'check_name', 'ranking_type', 'simulation_status', 'simulation_start',
    'simulation_end', 'simulation_time_step', 'generation_date', 'assessment_status',
)

# Lists of names that must stay readable in full.
_LONG_LABEL_FIELDS = ('equipment_name',)


def text_limit(field):
    if field in _LONG_LABEL_FIELDS:
        return MAX_TEXT_LENGTH
    if field in _LABEL_FIELDS or field.endswith(_LABEL_SUFFIXES):
        return MAX_LABEL_LENGTH
    return MAX_TEXT_LENGTH


CASE_SLOTS = 6
# The detail report shows three scenarios per block (repeated element and n-1 columns).
DETAIL_SLOTS = 3
SERIES_SLOTS = CASE_SLOTS + 1


# Slot names use letters to keep the tables visible in the PowerFactory report
# database. Numeric slot names are incompatible with that interface. Slot 0 is REF.
SLOT_KEYS = ('ref', 'a', 'b', 'c', 'd', 'e', 'f')


def case_text_field(slot):
    return 'case_{}_text'.format(SLOT_KEYS[slot])


def case_name_field(slot):
    return 'case_{}_name'.format(SLOT_KEYS[slot])


def series_name_field(slot):
    return 'series_{}_name'.format(SLOT_KEYS[slot])


def series_value_field(slot):
    return 'value_{}'.format(SLOT_KEYS[slot])


def _slot_fields(field, kind, first=1, last=CASE_SLOTS):
    return tuple((field(index), kind) for index in range(first, last + 1))


# Tables that compare REF with up to CASE_SLOTS cases side by side. Further cases
# continue in the next block; the headers travel with every row so that no data
# relation is needed.
MATRIX_FIELDS = (
    (("block", "integer"), ("row_order", "integer"), ("element_name", "string"), ("ref_text", "string"))
    + _slot_fields(case_text_field, "string") + _slot_fields(case_name_field, "string")
    + (("col_count", "integer"), ("violation", "integer")))
# Charts that draw REF and up to CASE_SLOTS cases: one fixed series per slot.
SERIES_NAME_FIELDS = _slot_fields(series_name_field, "string", 0)
SERIES_VALUE_FIELDS = _slot_fields(series_value_field, "number", 0)
# The time course of H09 draws two series: the n-1 reference (slot ref) and (n-1)' over every scenario (slot a).
TIME_COURSE_FIELDS = (
    (("time_label", "string"), ("timestamp", "number"), ("chart_title", "string"), ("unit", "string"))
    + SERIES_NAME_FIELDS[:2] + SERIES_VALUE_FIELDS[:2])

TABLES = (
    ("ScriptedReportMeta", (
        ("run_id", "string"), ("study_name", "string"), ("study_description", "string"),
        ("model_name", "string"), ("model_version", "string"), ("simulation_start", "string"),
        ("simulation_end", "string"), ("simulation_time_step", "string"), ("generation_date", "string"),
        ("generated_by", "string"), ("run_mode", "string"), ("template_name", "string"),
        ("template_version", "string"), ("data_contract_version", "string"), ("result_name", "string"),
        ("assessment_scope", "string"), ("assessment_status", "string"), ("voltage_limits", "string"),
        ("has_cases", "string"), ("case_source_text", "string"), ("reference_text", "string"), ("qds_mode_text", "string"),
        ("coverage_statement", "string"), ("has_contingency", "string"), ("contingency_text", "string"),
        ("overall_text", "string"), ("critical_note", "string"), ("events_note", "string"), ("empty_tables", "string"))),
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
    ("ScriptedCaseCounts", (
        ("case_order", "integer"), ("case_name", "string"), ("line_count", "integer"),
        ("transformer_count", "integer"), ("node_count", "integer"))),
    ("ScriptedLineLoadingBars", (
        ("rank", "integer"), ("element_name", "string"), ("max_value", "number"), ("case_name", "string"))),
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
    # --- contract 7.0: statistics of the reporting core (main report H02-H10, detail report D01-D12)
    ("ScriptedCaseStatistics", (
        ("case_order", "integer"), ("case_name", "string"), ("level", "string"), ("assessment", "string"),
        ("critical_lines", "integer"), ("critical_transformers", "integer"), ("critical_nodes", "integer"),
        ("new_elements", "integer"), ("worsened_elements", "integer"), ("new_events", "integer"), ("worsened_events", "integer"),
        ("preexisting_events", "integer"), ("improved_events", "integer"), ("resolved_events", "integer"),
        ("quality_events", "integer"), ("critical_contingencies", "integer"), ("critical_times", "integer"),
        ("episodes", "integer"), ("events_text", "string"), ("contingencies_text", "string"), ("times_text", "string"),
        ("completeness_text", "string"), ("violation", "integer"))),
    ("ScriptedCaseStatusCounts", (
        ("case_order", "integer"), ("case_name", "string"), ("new_count", "integer"), ("worsened_count", "integer"),
        ("improved_count", "integer"), ("resolved_count", "integer"))),
    ("ScriptedCoverage", (
        ("case_order", "integer"), ("case_name", "string"), ("level", "string"), ("times_requested", "integer"),
        ("times_calculated", "integer"), ("contingencies_defined", "integer"), ("contingencies_applicable", "integer"),
        ("pairs_examined", "integer"), ("pairs_not_applicable", "integer"), ("pairs_failed", "integer"),
        ("pairs_missing", "integer"), ("cells_required", "integer"), ("cells_evaluated", "integer"),
        ("failed_cells", "integer"), ("not_evaluated_cells", "integer"), ("not_applicable_cells", "integer"),
        ("not_comparable_cells", "integer"), ("coverage_text", "string"), ("violation", "integer"))),
    ("ScriptedScope", (
        ("case_order", "integer"), ("case_name", "string"), ("level", "string"), ("grid_name", "string"),
        ("voltage_level", "string"), ("element_class", "string"), ("monitored", "integer"), ("critical", "integer"),
        ("incomplete", "integer"))),
    ("ScriptedOutageWindows", (
        ("row_order", "integer"), ("case_order", "integer"), ("case_name", "string"), ("outage_name", "string"),
        ("outage_path", "string"), ("equipment_name", "string"), ("start_text", "string"), ("end_text", "string"),
        ("start_hours", "number"), ("end_hours", "number"), ("gantt_label", "string"))),
    ("ScriptedReferenceFindings", (
        ("row_order", "integer"), ("level", "string"), ("criterion_order", "integer"), ("main_rank", "integer"),
        ("element_name", "string"), ("element_type", "string"), ("grid_name", "string"), ("criterion", "string"),
        ("value_text", "string"), ("limit_text", "string"), ("violation_text", "string"), ("time_label", "string"),
        ("contingency_name", "string"), ("status", "string"), ("source_text", "string"), ("violation", "integer"))),
    ("ScriptedCriticalLines", MATRIX_FIELDS),
    ("ScriptedCriticalTransformers", MATRIX_FIELDS),
    ("ScriptedCriticalNodes", MATRIX_FIELDS),
    ("ScriptedDetailLines", MATRIX_FIELDS),
    ("ScriptedDetailTransformers", MATRIX_FIELDS),
    ("ScriptedDetailVoltageLow", MATRIX_FIELDS),
    ("ScriptedDetailVoltageHigh", MATRIX_FIELDS),
    ("ScriptedClassificationMatrix", MATRIX_FIELDS),
    ("ScriptedContingencyRegister", (
        ("case_order", "integer"), ("case_name", "string"), ("row_order", "integer"), ("level", "string"),
        ("contingency_name", "string"), ("equipment_name", "string"), ("examined_times", "integer"),
        ("not_applicable_times", "integer"), ("failed_times", "integer"), ("missing_times", "integer"),
        ("affected_elements", "integer"), ("critical_times", "integer"), ("new_events", "integer"),
        ("worsened_events", "integer"), ("violation_events", "integer"), ("worst_text", "string"), ("violation", "integer"))),
    ("ScriptedContingencyRanking", (("rank", "integer"), ("contingency_name", "string"), ("finding_count", "integer"))),
    ("ScriptedContingencyEvents", (
        ("case_order", "integer"), ("case_name", "string"), ("row_order", "integer"), ("level", "string"),
        ("main_rank", "integer"), ("criterion_order", "integer"), ("time_label", "string"), ("contingency_name", "string"),
        ("phase", "string"), ("element_name", "string"), ("element_type", "string"), ("criterion", "string"), ("unit", "string"),
        ("reference_text", "string"), ("scenario_text", "string"), ("limit_text", "string"), ("violation_text", "string"),
        ("change_text", "string"), ("status", "string"), ("source_text", "string"),
        ("violation", "integer"))),
    ("ScriptedContingencyEpisodes", (
        ("case_order", "integer"), ("case_name", "string"), ("row_order", "integer"), ("level", "string"),
        ("contingency_name", "string"), ("element_name", "string"), ("element_type", "string"), ("criterion", "string"),
        ("phase", "string"), ("status", "string"), ("first_text", "string"), ("last_text", "string"), ("points", "integer"),
        ("peak_text", "string"), ("peak_time", "string"), ("source_text", "string"), ("violation", "integer"))),
    ("ScriptedQualityRegister", (
        ("row_order", "integer"), ("case_order", "integer"), ("case_name", "string"), ("level", "string"),
        ("status", "string"), ("cause", "string"), ("contingency_name", "string"), ("time_text", "string"),
        ("cells", "integer"), ("violation", "integer"))),
    ("ScriptedTimeCriticality", TIME_COURSE_FIELDS),
    ("ScriptedTimeMatrix", MATRIX_FIELDS),
    ("ScriptedAssessmentSettings", (
        ("row_order", "integer"), ("section", "string"), ("setting_key", "string"), ("label", "string"),
        ("value_text", "string"), ("unit", "string"), ("origin", "string"), ("status", "string"))),
    ("ScriptedResultProvenance", (
        ("row_order", "integer"), ("level", "string"), ("case_name", "string"), ("object_name", "string"),
        ("object_path", "string"), ("content_text", "string"), ("status", "string"))),
)
REQUIRED_FIELDS = {
    "ScriptedReportMeta": (
        "run_id", "study_name", "model_name", "model_version", "generation_date", "generated_by", "run_mode",
        "template_name", "template_version", "data_contract_version", "result_name", "assessment_scope",
        "assessment_status", "voltage_limits", "has_cases", "case_source_text", "reference_text",
        "qds_mode_text", "coverage_statement", "has_contingency", "contingency_text"),
    "ScriptedModelQuality": ("check_id", "check_name", "status", "message"),
    "ScriptedCases": ("case_order", "case_id", "case_name", "is_reference", "simulation_status", "assessment",
                      "violation"),
    "ScriptedCaseMetrics": ("case_order", "case_name", "max_line_text", "coincident_delta_text",
                            "maxima_difference_text", "voltage_range_text"),
    "ScriptedKpis": ("highest_text", "highest_caption", "delta_text", "delta_caption"),
    "ScriptedPieLines": ("sort_order", "class_label", "element_count"),
    "ScriptedPieTransformers": ("sort_order", "class_label", "element_count"),
    "ScriptedCaseCounts": ("case_order", "case_name", "line_count", "transformer_count", "node_count"),
    "ScriptedLineLoadingBars": ("rank", "element_name", "max_value"),
    "ScriptedCaseComparison": ("block", "row_order", "element_name", "ref_text", "col_count", "violation"),
    "ScriptedCalculationRuns": ("run_order", "run_id", "run_kind", "case_name", "status"),
    "ScriptedTopLinesByCase": ("block", "row_order", "element_name", "ref_text", "col_count", "violation"),
    "ScriptedAppendixLine": ("block", "row_order", "element_name", "ref_text", "col_count", "violation"),
    "ScriptedAppendixTransformer": ("block", "row_order", "element_name", "ref_text", "col_count", "violation"),
    "ScriptedAppendixVoltage": ("block", "row_order", "element_name", "ref_text", "col_count", "violation"),
    "ScriptedCaseStatistics": ("case_order", "case_name", "level", "assessment", "violation"),
    "ScriptedCaseStatusCounts": ("case_order", "case_name"),
    "ScriptedCoverage": ("case_order", "case_name", "level", "coverage_text"),
    "ScriptedScope": ("case_order", "case_name", "level", "element_class"),
    "ScriptedOutageWindows": ("row_order", "case_name", "outage_name"),
    "ScriptedReferenceFindings": ("row_order", "level", "element_name", "criterion", "status"),
    "ScriptedCriticalLines": ("block", "row_order", "element_name", "ref_text", "col_count", "violation"),
    "ScriptedCriticalTransformers": ("block", "row_order", "element_name", "ref_text", "col_count", "violation"),
    "ScriptedCriticalNodes": ("block", "row_order", "element_name", "ref_text", "col_count", "violation"),
    "ScriptedDetailLines": ("block", "row_order", "element_name", "ref_text", "col_count", "violation"),
    "ScriptedDetailTransformers": ("block", "row_order", "element_name", "ref_text", "col_count", "violation"),
    "ScriptedDetailVoltageLow": ("block", "row_order", "element_name", "ref_text", "col_count", "violation"),
    "ScriptedDetailVoltageHigh": ("block", "row_order", "element_name", "ref_text", "col_count", "violation"),
    "ScriptedClassificationMatrix": ("block", "row_order", "element_name", "ref_text", "col_count", "violation"),
    "ScriptedTimeMatrix": ("block", "row_order", "element_name", "ref_text", "col_count", "violation"),
    "ScriptedContingencyRegister": ("case_order", "case_name", "row_order", "contingency_name"),
    "ScriptedContingencyRanking": ("rank", "contingency_name", "finding_count"),
    "ScriptedContingencyEvents": ("case_order", "case_name", "row_order", "element_name", "status"),
    "ScriptedContingencyEpisodes": ("case_order", "case_name", "row_order", "element_name", "status"),
    "ScriptedQualityRegister": ("row_order", "case_name", "status", "cause"),
    "ScriptedTimeCriticality": ("time_label", "timestamp", "series_ref_name"),
    "ScriptedAssessmentSettings": ("row_order", "setting_key", "label"),
    "ScriptedResultProvenance": ("row_order", "level", "case_name", "object_name"),
}

# Fields the builders compute for the script itself (summaries, log, checks) that no template shows: they are not
# declared to PowerFactory and never written, so the report database holds only what the two reports print.
DETAIL_MATRICES = ("ScriptedDetailLines", "ScriptedDetailTransformers", "ScriptedDetailVoltageLow", "ScriptedDetailVoltageHigh",
                   "ScriptedClassificationMatrix")
UNPUBLISHED_FIELDS = {
    "ScriptedReportMeta": ("study_description", "voltage_limits", "has_cases", "has_contingency"),
    "ScriptedModelQuality": ("check_id",),
    "ScriptedCases": ("case_id", "is_reference", "simulation_status", "case_description", "windows_text"),
    "ScriptedCaseMetrics": ("coverage_text",),
    "ScriptedLineLoadingBars": ("case_name",),
    "ScriptedCalculationRuns": ("reference_text", "period_text", "provenance_text"),
    "ScriptedTopLinesByCase": ("violation",),
    "ScriptedCaseStatistics": ("new_events", "worsened_events", "preexisting_events", "improved_events", "resolved_events",
                               "quality_events", "critical_contingencies", "critical_times", "episodes"),
    "ScriptedCoverage": ("pairs_examined", "pairs_not_applicable", "pairs_failed", "pairs_missing", "cells_required",
                         "cells_evaluated"),
    "ScriptedReferenceFindings": ("status", "source_text"),
    "ScriptedContingencyRegister": ("violation_events",),
    "ScriptedContingencyEvents": ("phase", "unit", "source_text", "element_type"),
    "ScriptedContingencyEpisodes": ("phase", "source_text", "element_type"),
    "ScriptedTimeCriticality": ("chart_title", "unit"),
    "ScriptedAssessmentSettings": ("setting_key",),
}
UNPUBLISHED_FIELDS.update({name: tuple(field(slot) for slot in range(DETAIL_SLOTS + 1, CASE_SLOTS + 1)
                                       for field in (case_text_field, case_name_field)) for name in DETAIL_MATRICES})
TABLES = tuple((name, tuple(item for item in fields if item[0] not in UNPUBLISHED_FIELDS.get(name, ()))) for name, fields in TABLES)
REQUIRED_FIELDS = {name: tuple(field for field in fields if field not in UNPUBLISHED_FIELDS.get(name, ()))
                   for name, fields in REQUIRED_FIELDS.items()}

# ---------------------------------------------------------------------------
# PowerFactory object access, result extraction and time-series utilities
# ---------------------------------------------------------------------------


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
    """Return a finite float, accepting decimal commas; invalid values return None."""
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
    """Normalize a PowerFactory return code; None means success, invalid codes remain unknown."""
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
    """Read one finite result value; read errors and nonzero cell codes return None."""
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
    aliases = {
        's': 's',
        'sec': 's',
        'second': 's',
        'seconds': 's',
        'min': 'min',
        'minute': 'min',
        'minutes': 'min',
        'h': 'h',
        'hr': 'h',
        'hour': 'h',
        'hours': 'h',
        'd': 'd',
        'day': 'd',
        'days': 'd',
    }
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


# An IntVec that ElmRes.GetColumnValues(vector, column) fills with a whole column in one call; without it
# every value is one GetValue call. Created in the running ComPython for the run and deleted afterwards.
COLUMN_BUFFER = None
COLUMN_BUFFER_NAME = 'GridLens_column_buffer'


def open_column_buffer(app):
    """Create the IntVec for column reads in the running script; None (cell by cell) when that is not possible."""
    global COLUMN_BUFFER
    try:
        script = app.GetCurrentScript()
        vector = script.CreateObject('IntVec', COLUMN_BUFFER_NAME) if script is not None else None
    except Exception:
        vector = None
    COLUMN_BUFFER = vector if class_name(vector) == 'IntVec' else None
    return COLUMN_BUFFER


def close_column_buffer():
    global COLUMN_BUFFER
    vector, COLUMN_BUFFER = COLUMN_BUFFER, None
    if vector is not None:
        try:
            vector.Delete()
        except Exception:
            pass


def read_column(elmres, column, rows, buffer=None):
    """All `rows` values of one column: one GetColumnValues call into the IntVec, else one GetValue per cell."""
    vector = buffer if buffer is not None else COLUMN_BUFFER
    if vector is not None:
        try:
            code = finite_number(elmres.GetColumnValues(vector, column))
            values = safe_attr(vector, 'V')
        except Exception:
            code, values = None, None
        if code == 0.0 and _is_sequence(values):
            if len(values) != rows:
                raise RuntimeError('ElmRes column {} returned {} values instead of {}.'.format(column, len(values), rows))
            RUN_STATS.count('columns_bulk')
            return [finite_number(value) for value in values]
    RUN_STATS.count('values_cellwise', rows)
    return [result_value(elmres, row, column) for row in range(rows)]



def _is_sequence(value):
    return isinstance(value, (list, tuple))



def collect_series(elmres, counters=None):
    """Read supported in-scope series from an already loaded ElmRes.

    Keep full-resolution arrays for assessment and sampled points for plots.
    Validate the time axis and result size before extracting series. The caller
    owns Load/Release; optional counters receive extraction diagnostics.
    """
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
    # Without a grid selection every element is assessed, so its grid is not read at all.
    filtered = bool(current_setting('monitoring_grids') or GRID_NAME_FILTER)
    by_class, by_variable = {}, {}
    for column in range(columns):
        try:
            obj = elmres.GetObject(column)
            variable = str(elmres.GetVariable(column))
            category = result_category(obj, variable)
        except Exception:
            continue
        if column != t_column:
            kind = class_name(obj) or 'unknown'
            by_class[kind] = by_class.get(kind, 0) + 1
            by_variable[variable] = by_variable.get(variable, 0) + 1
        if not category or variable not in VARIABLES[category]:
            if column != t_column:
                name = '{} {}'.format(class_name(obj) or 'unknown object', variable)
                recorded[name] = recorded.get(name, 0) + 1
            continue
        # Before the full path is fetched and before any value is read.
        if filtered:
            grid_name = element_grid_name(obj)
            in_scope = grid_in_scope(grid_name)
            counted = grids.setdefault(grid_name or '(no grid)', [0, in_scope])
            counted[0] += 1
            if not in_scope:
                out_of_scope += 1
                continue
        identity = object_key(obj)
        if category == 'voltage' and is_dc_terminal(obj):
            dc_nodes.add(identity)
            continue
        key = (category, identity)
        priority = VARIABLES[category].index(variable)
        if key not in chosen or priority < chosen[key][0]:
            chosen[key] = (priority, column, obj, variable)
    if counters is not None:
        counters['columns'], counters['rows'] = columns, rows
        counters['columns_by_class'], counters['columns_by_variable'] = by_class, by_variable
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
        series.append({
            'category': category,
            'object': obj,
            'key': object_key(obj),
            'element_id': object_id(obj),
            'element_name': object_name(obj),
            'voltage_level': voltage_level(obj),
            'nominal_kv': nominal,
            'limits': voltage_band(nominal) if category == 'voltage' else None,
            'variable_id': variable,
            'variable': 'Voltage magnitude' if category == 'voltage' else 'Loading',
            'unit': unit,
            'points': [(labels[row], plot_times[row], values[row]) for row in plot_rows],
            'statistics': array_statistics(array_values, labels),
            'values': array_values,
        })
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
    return {
        'min': minimum,
        'max': maximum,
        'mean': sum(values) / len(values),
        'time_min': next((label for label, value in points if value == minimum)),
        'time_max': next((label for label, value in points if value == maximum)),
    }



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
# Category A changes result evaluation only. Category B affects calculation
# scope or describes PowerFactory calculation settings. Settings marked
# editable=False are read only. Overrides are stored in the case configuration
# under 'settings'; native storage in the PowerFactory project is not verified.
# ---------------------------------------------------------------------------
SETTINGS_VERSION = '1.0'
SOURCE_GRIDLENS, SOURCE_POWERFACTORY, SOURCE_USER = 'GridLens', 'PowerFactory', 'user'
CATEGORY_EVALUATION, CATEGORY_CALCULATION = 'A', 'B'
N1_LIMITS_POWERFACTORY, N1_LIMITS_GLOBAL = 'powerfactory', 'global'
N1_LIMIT_CHOICES = ((N1_LIMITS_POWERFACTORY, 'use PowerFactory limits'), (N1_LIMITS_GLOBAL, 'global assessment limit'))
ON_OFF_CHOICES = ((True, 'on'), (False, 'off'))
# Upper bounds of the count settings: beyond them a run takes hours or the report gets unreadable.
COUNT_LIMITS = {'top_n': 50, 'max_plot_points': 2000, 'max_n1_times': 20000, 'max_cases': 20}
# The most planning cases a run can have: the templates hold a band pair for every block up to this number.
MAX_PLANNING_CASES = COUNT_LIMITS['max_cases']
NOT_VERIFIED = 'not verified yet'
CONTINGENCY_SETTINGS_NOTE = (
    'Read only: set in the contingency analysis (ComSimoutage) of the study case; GridLens reads it '
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
                    SOURCE_POWERFACTORY, CONTINGENCY_SETTINGS_NOTE)


SETTINGS = (
    _setting('monitoring_grids', 'Network scope', 'Report filter: assessed equipment, grids', '', (), 'grids',
             applies="n-0, n-1, (n-1)'",
             note='evaluation only, also in a re-evaluation; no grid selected: every grid (or GRID_NAME_FILTER)'),
    _setting('contingency_grids', 'Network scope', 'n-1 filter: grids of the outaged equipment', '', None, 'grids',
             CATEGORY_CALCULATION, applies="n-1, (n-1)'", source=SOURCE_GRIDLENS,
             note='calculation: the other contingencies are "Not analysed" (outserv) for the run; none: every grid'),
    _setting('contingency_elements', 'Network scope', 'n-1 filter: outaged elements', '', (), 'elements',
             CATEGORY_CALCULATION, applies="n-1, (n-1)'", source=SOURCE_GRIDLENS,
             note='calculation: only contingencies outaging a selected element are analysed, the others are "Not '
                  'analysed" for the run; none selected: every element'),
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
             applies="n-1, (n-1)'", source=SOURCE_POWERFACTORY, note=CONTINGENCY_SETTINGS_NOTE),
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
SAME_AS_ASSESSMENT = 'every grid (no n-1 grid filter)'
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
    if setting['kind'] == 'elements':
        return parse_elements(key, text)
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


def parse_elements(key, value):
    """An element selection: a list of distinct element keys (full PowerFactory names)."""
    if not isinstance(value, (list, tuple)) or not all(isinstance(name, str) and name.strip() for name in value):
        return None, '{}: a list of elements is needed'.format(SETTINGS_BY_KEY[key]['label'])
    names = tuple(name.strip() for name in value)
    if len(set(names)) != len(names):
        return None, '{}: an element is selected twice'.format(SETTINGS_BY_KEY[key]['label'])
    return tuple(sorted(names, key=str.casefold)), None


def parse_grids(key, value):
    """A grid selection: a list of distinct grid names; None for the contingencies means every grid (no filter)."""
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
    if setting['kind'] == 'elements':
        return ', '.join(element_label(key) for key in value) if value else 'every element'
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
    return {
        'settings_version': SETTINGS_VERSION,
        'classification_version': CLASSIFICATION_VERSION,
        'values': values,
        'sources': {key: setting_source(key, overrides) for key in values},
        'overrides': clean_overrides(dict((key, values[key]) for key in overrides)),
        'calculation_parameters': {setting['key']: NOT_VERIFIED if not setting['editable'] else
                                       setting_text(setting['key'], values[setting['key']]) + ' (stored, not applied yet)'
                                       for setting in SETTINGS if setting['category'] == CATEGORY_CALCULATION},
        'storage': 'provisional: case configuration file (JSON); native PowerFactory storage not verified yet',
    }


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
_SETTING_CONSTANTS = {
    'top_n': 'TOP_N',
    'max_plot_points': 'MAX_PLOT_POINTS',
    'energized_min_pu': 'ENERGIZED_MIN_PU',
    'loading_appendix_delta': 'LOADING_APPENDIX_DELTA',
    'voltage_appendix_delta': 'VOLTAGE_APPENDIX_DELTA',
    'run_reference': 'RUN_REFERENCE_CASE',
    'max_cases': 'MAX_CASES',
    'max_n1_times': 'MAX_N1_TIMES',
}


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
CLASSIFICATION_STATUSES = (
    (0, 'OK'),
    (1, 'NEW'),
    (2, 'WORSENED'),
    (3, 'PRE_EXISTING'),
    (4, 'IMPROVED'),
    (5, 'RESOLVED'),
    (90, 'FAILED'),
    (91, 'NOT_EVALUATED'),
    (92, 'NOT_APPLICABLE'),
    (93, 'NOT_COMPARABLE'),
)
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
# n-1 and (n-1)' with the native contingency analysis
#
# ComSimoutage.Execute() runs the time sweep. With calcPeriod=4, startTime,
# endTime and stepSize/stepUnit define its time grid; studyTime is ignored.
# p_rescnt holds one ElmRes per study time (cnttime) with one row per
# contingency (GetObjectValue -> ComOutage) and one column per element and
# variable; GetValue code 3 means "not written, inside the recording limits".
# isPlannedOutages applies every planned outage that is not Ignored and whose
# window contains the study time, per study time; a contingency whose
# equipment such an outage already switches off has no row (NOT_APPLICABLE).
# ComOutage.outserv ("Not analysed") removes a contingency.
# ---------------------------------------------------------------------------
N1_COMMAND_CLASS = 'ComSimoutage'
# ComOutage.GetObject(line) is read for at most this many lines per contingency.
MAX_CONTINGENCY_ELEMENTS = 200
N1_PLANNED_OPTION = 'isPlannedOutages'
N1_TIMES_ATTRIBUTE, N1_IGNORE_ATTRIBUTE = 'studyTime', 'bIgnoreTime'
# The time sweep as a period: with calcPeriod 4 PowerFactory 2026 calculates from startTime to endTime (exclusive)
# in steps of stepSize/stepUnit and ignores studyTime. GridLens writes that period.
N1_PERIOD_ATTRIBUTE, N1_PERIOD_MODE = 'calcPeriod', 4
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


def read_n1_results(source, in_scope=element_in_scope, recording_limits=None):
    """{study time: {(contingency key, element key, quantity): value or None}} plus the element and contingency names.

    None marks code 3, a value inside the recording limits. Only the
    variables of N1_VARIABLES of elements in scope are read; a value that is
    neither written nor marked code 3 is left out (no artificial zero).
    """
    found = {
        'times': {},
        'elements': {},
        'contingencies': {},
        'categories': {},
        'nominal_kv': {},
        'grids': {},
        'present': {},
    }
    from_command = class_name(source) == N1_COMMAND_CLASS
    result = safe_attr(source, N1_RESULT_ATTRIBUTE) if from_command else source
    subs = [item for item in (_contents(result, '*.ElmRes') if result is not None else []) if class_name(item) == 'ElmRes']
    wanted = {variable: quantity for quantity, variables in N1_VARIABLES.items() for variable in variables}
    for sub in subs:
        moment = finite_number(safe_attr(sub, 'cnttime'))
        if moment is None:
            continue
        present, values, _absent = _read_n1_sub(sub, wanted, in_scope, found, keep_unrecorded=True)
        found['times'].setdefault(moment, {}).update(values)
        found['present'][moment] = present
    found['recording_limits'] = _recording_limits(source) if from_command else (recording_limits or {})
    return found


_ABSENT = object()


def _read_n1_sub(sub, wanted, in_scope, meta, keep_unrecorded=False):
    """One sub-result (one study time): (contingencies with a row, values, unreadable cells).

    `values` maps (contingency, element, quantity) to the value; with
    `keep_unrecorded` a value inside the recording limits (code 3) is kept as
    None, otherwise it is left out and stands for itself (the streaming path
    counts such cells without storing them). Cells that could not be read at
    all are returned as unreadable keys, never as values. Element and
    contingency names, categories, nominal voltages and grids go into `meta`
    the first time an object is seen.
    """
    values, present, absent = {}, set(), set()
    try:
        sub.Load()
        columns = []
        for column in range(int(sub.GetNumberOfColumns())):
            obj = sub.GetObject(column)
            quantity = wanted.get(str(sub.GetVariable(column)))
            if obj is None or quantity is None or not in_scope(obj):
                continue
            key = object_key(obj)
            if key not in meta['elements']:
                meta['elements'][key] = object_name(obj)
                meta['categories'][key] = 'voltage' if quantity == 'voltage' else (
                    CLASS_CATEGORIES.get(class_name(obj)) or ('line',))[0]
                meta.setdefault('grids', {})[key] = element_grid_name(obj)
                if quantity == 'voltage':
                    meta['nominal_kv'][key] = finite_number(safe_attr(obj, 'uknom'))
            columns.append((column, key, quantity))
        rows = int(sub.GetNumberOfRows())
        contingencies = []
        for row in range(rows):
            code, outage = _status_pair(sub.GetObjectValue(row))
            contingency = object_key(outage) if code == 0 and outage is not None else None
            if contingency is not None:
                meta['contingencies'].setdefault(contingency, object_name(outage))
                present.add(contingency)
            contingencies.append(contingency)
        for column, key, quantity in columns:
            for row, value in enumerate(_n1_column(sub, column, rows, quantity)):
                contingency = contingencies[row]
                if contingency is None:
                    continue
                if value is _ABSENT:
                    absent.add((contingency, key, quantity))
                elif value is not None or keep_unrecorded:
                    values[(contingency, key, quantity)] = value
    finally:
        try:
            sub.Release()
        except Exception:
            pass
    return present, values, absent


class SweepReader:
    """A kept n-1 result (or a contingency analysis) read one study time at a time.

    `times` are the study times of its sub-results; `read(moment)` returns
    (contingencies with a row, explicit values, unreadable cells) of that study
    time only, so a whole sweep is never held in memory. `meta` collects the
    names, categories, nominal voltages and grids of every object read.
    """

    def __init__(self, source, in_scope=element_in_scope, recording_limits=None):
        result = safe_attr(source, N1_RESULT_ATTRIBUTE) if class_name(source) == N1_COMMAND_CLASS else source
        self._subs = {}
        for item in _contents(result, '*.ElmRes') if result is not None else []:
            moment = finite_number(safe_attr(item, 'cnttime'))
            if class_name(item) == 'ElmRes' and moment is not None:
                self._subs[moment] = item
        self.times = sorted(self._subs)
        self.meta = {'elements': {}, 'contingencies': {}, 'categories': {}, 'nominal_kv': {}, 'grids': {}}
        self.recording_limits = recording_limits or {}
        self._in_scope = in_scope
        self._wanted = {variable: quantity for quantity, variables in N1_VARIABLES.items() for variable in variables}

    def read(self, moment):
        return _read_n1_sub(self._subs[moment], self._wanted, self._in_scope, self.meta)


class LoadedSweep:
    """n-1 data already read by read_n1_results/load_n1, offered like a SweepReader (times, read, meta).

    Code 3 cells (None, inside the recording limits) are left out, as the
    streaming reader leaves them out; only the study times of the data exist.
    """

    def __init__(self, data):
        self._data = data
        self.times = sorted(data['times'])
        self.meta = {name: data.get(name) or {} for name in ('elements', 'contingencies', 'categories', 'nominal_kv', 'grids')}
        self.recording_limits = data.get('recording_limits') or {}

    def read(self, moment):
        values = self._data['times'].get(moment) or {}
        present = self._data.get('present', {}).get(moment)
        if present is None:
            present = {key[0] for key in values}
        return set(present), {key: value for key, value in values.items() if value is not None}, set()


def _n1_column(sub, column, rows, quantity='loading'):
    """One column of an n-1 sub-result: a value, None for code 3 (inside the recording limits) or _ABSENT.

    The whole column comes in one GetColumnValues call when it holds a value
    in every row; otherwise each cell is read to tell code 3 from a missing
    value. What the bulk read puts into a code-3 cell is not verified: 0 % is
    harmless for loading (inside the recording limit anyway), but a voltage
    column with a 0 is read cell by cell.
    """
    vector = COLUMN_BUFFER
    if vector is not None:
        try:
            code = finite_number(sub.GetColumnValues(vector, column))
            bulk = safe_attr(vector, 'V')
        except Exception:
            code, bulk = None, None
        if code == 0.0 and _is_sequence(bulk) and len(bulk) == rows:
            numbers = [finite_number(value) for value in bulk]
            if all(number is not None and (quantity == 'loading' or number > 0.0) for number in numbers):
                RUN_STATS.count('columns_bulk')
                return numbers
    RUN_STATS.count('values_cellwise', rows)
    found = []
    for row in range(rows):
        code, value = _status_pair(sub.GetValue(row, column))
        found.append(finite_number(value) if code == 0 and finite_number(value) is not None
                     else None if code == CODE_NOT_RECORDED else _ABSENT)
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
    identity = {
        'time': moment,
        'contingency': contingency,
        'element': element,
        'quantity': quantity,
        'phase': 'post-fault',
    }
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
    not_applicable = set()
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
            if outcome['status'] == 'NOT_APPLICABLE':
                not_applicable.add(reference['contingencies'].get(contingency, contingency))
            entry = elements.setdefault((element, quantity), {'element': element, 'quantity': quantity,
                                                              'name': reference['elements'].get(element, element),
                                                              'category': category, 'worst': None})
            worst = entry['worst']
            if worst is None or N1_SEVERITY.index(outcome['status']) < N1_SEVERITY.index(worst['status']) or (
                    outcome['status'] == worst['status'] and (outcome['delta'] or 0.0) > (worst['delta'] or 0.0)):
                entry['worst'] = dict(outcome, contingency_name=reference['contingencies'].get(contingency, contingency),
                                      reference_value=ref_side.get('value'), scenario_value=case_side.get('value'))
    return {'elements': elements, 'counts': counts, 'not_applicable': sorted(not_applicable, key=str.casefold)}


def n1_summary(comparison):
    """'NEW 2, WORSENED 1, OK 140' style text of the classification counts, most severe first."""
    counts = comparison['counts']
    return ', '.join('{} {}'.format(status, counts[status]) for status in N1_SEVERITY if counts.get(status)) or 'nothing compared'


# ---------------------------------------------------------------------------
# Reporting core: criteria, streaming n-1
# comparison and the statistics of the main and the detail report.
#
# n-0 is the QDS of the base network, n-1 the time-sweep contingency analysis
# of the base network, (n-1)' the same sweep per planning case with its active
# planned outages. A comparison needs the same study time, contingency,
# element, criterion and post-fault phase. Voltage is two criteria: below the
# band and above it. Every statistic is computed over the complete result
# before any report selection; quality statuses never count as OK, and a
# missing or unrecorded value never becomes 0 %.
# ---------------------------------------------------------------------------
CRITERIA = ('loading', 'voltage_low', 'voltage_high')
CRITERION_QUANTITY = {'loading': 'loading', 'voltage_low': 'voltage', 'voltage_high': 'voltage'}
CRITERION_UNIT = {'loading': '%', 'voltage_low': 'p.u.', 'voltage_high': 'p.u.'}
QUANTITY_CRITERIA = {'loading': ('loading',), 'voltage': ('voltage_low', 'voltage_high')}
VIOLATION_STATUSES = ('NEW', 'WORSENED', 'PRE_EXISTING', 'IMPROVED')
# Statuses whose n-1 reference value violates the limit.
REFERENCE_VIOLATED = ('WORSENED', 'PRE_EXISTING', 'IMPROVED', 'RESOLVED')
QUALITY_STATUSES = ('FAILED', 'NOT_EVALUATED', 'NOT_APPLICABLE', 'NOT_COMPARABLE')
# Report priority: caused findings first, then quality problems, then findings already in n-1.
STATUS_PRIORITY = ('NEW', 'WORSENED', 'FAILED', 'NOT_EVALUATED', 'NOT_COMPARABLE', 'NOT_APPLICABLE', 'PRE_EXISTING',
                   'IMPROVED', 'RESOLVED', 'OK')
STATUS_RANK = {status: rank for rank, status in enumerate(STATUS_PRIORITY)}
STATE_NOT_RECORDED_CELL = 'not_recorded'
STATE_MISSING = 'missing'
POST_FAULT_PHASE = 'post-fault'
REPORT_CATEGORY = {'line': 'line', 'transformer': 'transformer', 'voltage': 'node'}


def criterion_thresholds(quantity, limit):
    """[(criterion, threshold)] of a limit definition: loading its maximum, voltage each band edge on its own."""
    if not isinstance(limit, dict):
        return []
    if quantity == 'loading':
        return [('loading', _measured(limit.get('max')))]
    return [('voltage_low', _measured(limit.get('min'))), ('voltage_high', _measured(limit.get('max')))]


def criterion_violation(criterion, value, threshold):
    """How far a value lies beyond the threshold, in the criterion's unit; negative inside, None if not computable."""
    value, threshold = _measured(value), _measured(threshold)
    if value is None or threshold is None:
        return None
    return threshold - value if criterion == 'voltage_low' else value - threshold


def _inside_recording(criterion, bounds, threshold, margin):
    """Whether a value PowerFactory did not record (inside its recording limits) is certainly no violation."""
    if not bounds or threshold is None:
        return False
    bound = bounds[-1] if criterion == 'voltage_high' else bounds[0]
    if bound is None:
        return False
    return bound >= threshold - margin if criterion == 'voltage_low' else bound <= threshold + margin


def classify_criterion(criterion, threshold, reference, scenario, parameters=None, recording=None):
    """Classify one criterion of one element at one study time and contingency: (n-1)' against n-1.

    `reference` and `scenario` are (state, value) with state 'ok', 'failed',
    'not_applicable', 'not_recorded' (inside the recording limits) or
    'missing'. `threshold` is one value, or (reference threshold, scenario
    threshold). Decision order as in classify_comparison(): FAILED,
    NOT_APPLICABLE, NOT_COMPARABLE (thresholds differ), NOT_EVALUATED
    (threshold or value missing, unrecorded value not proven inside the
    limit), then the violation sizes. `change` is the coincident change of
    the violation (positive: worse), `delta` the coincident difference of the
    values (scenario minus reference); both only when both values are known.
    """
    parameters = parameters or classification_parameters()
    quantity = CRITERION_QUANTITY[criterion]
    tolerance, numeric = parameters[quantity], parameters['numeric']
    result = {'criterion': criterion, 'indicators': [], 'change': None, 'delta': None,
              'reference_violation': None, 'scenario_violation': None}

    def done(status):
        return dict(result, status=status, code=CLASSIFICATION_CODES[status])
    states = (reference[0], scenario[0])
    if STATE_FAILED in states:
        return done('FAILED')
    if STATE_NOT_APPLICABLE in states:
        return done('NOT_APPLICABLE')
    pair = threshold if isinstance(threshold, (tuple, list)) else (threshold, threshold)
    if _measured(pair[0]) is not None and _measured(pair[1]) is not None and abs(pair[0] - pair[1]) > numeric:
        return done('NOT_COMPARABLE')
    limit = _measured(pair[1])
    if limit is None:
        return done('NOT_EVALUATED')
    margin = tolerance['limit'] + numeric
    sizes = []
    for state, value in (reference, scenario):
        if state == STATE_NOT_RECORDED_CELL:
            if not _inside_recording(criterion, (recording or {}).get(quantity), limit, margin):
                return done('NOT_EVALUATED')
            sizes.append(None)
        elif state == STATE_OK and _measured(value) is not None:
            sizes.append(criterion_violation(criterion, value, limit))
        else:
            return done('NOT_EVALUATED')
    result['reference_violation'], result['scenario_violation'] = sizes
    in_reference = sizes[0] is not None and sizes[0] > margin
    in_scenario = sizes[1] is not None and sizes[1] > margin
    if None not in sizes:
        result['change'] = sizes[1] - sizes[0]
        result['delta'] = float(scenario[1]) - float(reference[1])
    if in_scenario and not in_reference:
        return done('NEW')
    if in_scenario:
        change = result['change']
        return done('WORSENED' if change > tolerance['worsened'] + numeric else
                    'IMPROVED' if -change > tolerance['improved'] + numeric else 'PRE_EXISTING')
    if in_reference:
        return done('RESOLVED')
    if result['change'] is not None and result['change'] > tolerance['worsened'] + numeric and (
            quantity != 'loading' or float(scenario[1]) >= parameters['margin_warning_loading']):
        result['indicators'].append(INDICATOR_MARGIN_REDUCED)
    return done('OK')


def element_thresholds(meta, element):
    """{criterion: threshold} of an element from its category and nominal voltage (n1_limit)."""
    category = meta['categories'].get(element, 'line')
    quantity = 'voltage' if category == 'voltage' else 'loading'
    return dict(criterion_thresholds(quantity, n1_limit(quantity, category, meta['nominal_kv'].get(element))))


class ScenarioAggregate:
    """Streaming comparison of one (n-1)' scenario with n-1 and every statistic the reports need.

    add_time() takes the reference and the scenario of one study time (from
    SweepReader.read() or a synthetic source) and keeps only aggregates:
    nothing grows with time x contingency x element except the findings
    themselves. Cells inside the recording limits are counted, not stored.
    Elements the scenario's planned outages switch off are left out (they
    are no finding and no OK). Call finish() once for the statistics.
    """

    def __init__(self, run_id, scenario_id, meta, contingencies, requested_times, switched_off=(),
                 contingency_elements=None, recording=None, parameters=None, event_limit=500):
        self.run_id, self.scenario_id = run_id, scenario_id
        self.meta = meta
        self._contingencies = list(contingencies or ())
        self.requested_times = sorted(requested_times)
        self.switched_off = set(switched_off)
        self.contingency_elements = contingency_elements or {}
        self.recording = recording or {}
        self.parameters = parameters or classification_parameters()
        self.event_limit = event_limit
        self.thresholds = {}
        self.events = {status: 0 for status in STATUS_PRIORITY}
        self.element_status = {}
        self.element_extremes = {}
        self.new_elements, self.worsened_elements, self.critical_elements = set(), set(), set()
        self.critical_contingencies, self.critical_times = set(), set()
        self.max_violation, self.max_worsening = {}, {}
        self.register = {}
        self.time_rows = []
        self.quality = {}
        self.episodes, self._open = [], {}
        self._top, self.events_listed = [], 0
        self.examined_pairs = self.pairs_not_applicable = self.pairs_failed = self.pairs_missing_time = 0
        self.unreadable = 0
        self.times_calculated, self.contingencies_applicable = [], set()
        self._group_counts, self._group_size = None, -1

    @property
    def contingencies(self):
        """The contingencies defined: as given, else every contingency the sources have named so far."""
        return self._contingencies or list(self.meta['contingencies'])

    # --- helpers --------------------------------------------------------------------
    def _monitored(self):
        return [element for element in self.meta['elements'] if element not in self.switched_off]

    def _groups(self):
        """{(criterion, threshold): monitored elements} to count unrecorded cells without visiting elements."""
        if self._group_counts is None or self._group_size != len(self.meta['elements']):
            self._group_size = len(self.meta['elements'])
            groups = {}
            for element in self._monitored():
                for criterion, threshold in self._thresholds(element).items():
                    groups[(criterion, threshold)] = groups.get((criterion, threshold), 0) + 1
            self._group_counts = groups
        return self._group_counts

    def _thresholds(self, element):
        found = self.thresholds.get(element)
        if found is None:
            found = self.thresholds[element] = element_thresholds(self.meta, element)
        return found

    def _cells(self):
        return sum(self._groups().values())

    def _quality(self, moment, contingency, status, cause, cells):
        key = (moment, contingency, status, cause)
        self.quality[key] = self.quality.get(key, 0) + cells

    def _register(self, contingency):
        entry = self.register.get(contingency)
        if entry is None:
            entry = self.register[contingency] = {'examined': 0, 'not_applicable': 0, 'failed': 0, 'missing': 0,
                                                  'critical_times': set(), 'elements': set(), 'worst': None,
                                                  'events': {status: 0 for status in VIOLATION_STATUSES}}
        return entry

    # --- one study time -----------------------------------------------------------------
    def add_time(self, index, moment, reference, scenario):
        """One study time; `reference`/`scenario` are (contingencies, values, unreadable) or None when not calculated."""
        cells = self._cells()
        if reference is None or scenario is None:
            side = 'n-1 reference' if reference is None else "(n-1)' scenario"
            self.pairs_missing_time += len(self.contingencies)
            self.events['NOT_EVALUATED'] += len(self.contingencies) * cells
            self._quality(moment, '*', 'NOT_EVALUATED', 'study time not calculated in the ' + side,
                          len(self.contingencies) * cells)
            for contingency in self.contingencies:
                self._register(contingency)['missing'] += 1
            self._close_episodes(index)
            return
        self.times_calculated.append(moment)
        ref_present, ref_values, ref_absent = reference
        scen_present, scen_values, scen_absent = scenario
        examined = ref_present & scen_present
        for contingency in ref_present - scen_present:
            applicable = not (self.contingency_elements.get(contingency, set()) & self.switched_off)
            status = 'FAILED' if applicable else 'NOT_APPLICABLE'
            self.events[status] += cells
            if applicable:
                self.pairs_failed += 1
                self._register(contingency)['failed'] += 1
                self._quality(moment, contingency, status, 'contingency without a result row in the scenario', cells)
            else:
                self.pairs_not_applicable += 1
                self._register(contingency)['not_applicable'] += 1
                self._quality(moment, contingency, status, "the contingency's equipment is switched off by the scenario's "
                              "planned outages", cells)
        for contingency in set(self.contingencies) - ref_present - scen_present:
            self.events['FAILED'] += cells
            self.pairs_failed += 1
            self._register(contingency)['failed'] += 1
            self._quality(moment, contingency, 'FAILED', 'contingency without a result row in n-1 and (n-1)\'', cells)
        for contingency in scen_present - ref_present:
            self.events['FAILED'] += cells
            self.pairs_failed += 1
            self._register(contingency)['failed'] += 1
            self._quality(moment, contingency, 'FAILED', 'contingency without a result row in the n-1 reference', cells)
        for contingency in examined:
            self._register(contingency)['examined'] += 1
        self.contingencies_applicable |= examined
        self.examined_pairs += len(examined)
        time_elements, time_contingencies, time_caused, time_reference = set(), set(), set(), set()
        explicit_groups = {}
        unreadable = (ref_absent | scen_absent)
        keys = set(ref_values) | set(scen_values) | unreadable
        seen = set()
        for contingency, element, quantity in keys:
            if contingency not in examined or element in self.switched_off or element not in self.meta['elements']:
                continue
            for criterion in QUANTITY_CRITERIA[quantity]:
                threshold = self._thresholds(element).get(criterion)
                if (contingency, element, criterion) in seen:
                    continue
                seen.add((contingency, element, criterion))
                explicit_groups[(criterion, threshold)] = explicit_groups.get((criterion, threshold), 0) + 1
                key = (contingency, element, quantity)
                if key in unreadable:
                    outcome = {'status': 'NOT_EVALUATED', 'change': None, 'delta': None,
                               'reference_violation': None, 'scenario_violation': None, 'indicators': []}
                    self.unreadable += 1
                    self._quality(moment, contingency, 'NOT_EVALUATED', 'result cell not readable', 1)
                    ref_value = scen_value = None
                else:
                    ref_value, scen_value = ref_values.get(key), scen_values.get(key)
                    outcome = classify_criterion(
                        criterion, threshold,
                        (STATE_OK, ref_value) if ref_value is not None else (STATE_NOT_RECORDED_CELL, None),
                        (STATE_OK, scen_value) if scen_value is not None else (STATE_NOT_RECORDED_CELL, None),
                        self.parameters, self.recording)
                self._record(index, moment, contingency, element, criterion, threshold, ref_value, scen_value, outcome,
                             time_elements, time_contingencies, time_caused, time_reference)
        # Cells not recorded on either side: inside the recording limits, counted by threshold group.
        for (criterion, threshold), members in self._groups().items():
            implicit = members * len(examined) - explicit_groups.get((criterion, threshold), 0)
            if implicit <= 0:
                continue
            margin = self.parameters[CRITERION_QUANTITY[criterion]]['limit'] + self.parameters['numeric']
            if _inside_recording(criterion, self.recording.get(CRITERION_QUANTITY[criterion]), threshold, margin):
                self.events['OK'] += implicit
            else:
                self.events['NOT_EVALUATED'] += implicit
                self._quality(moment, '*', 'NOT_EVALUATED', 'values inside the recording limits do not prove the {} '
                              'limit'.format(criterion.replace('_', ' ')), implicit)
        self._close_episodes(index)
        self.time_rows.append({'time': moment, 'critical_elements': len(time_elements),
                               'critical_contingencies': len(time_contingencies), 'caused_elements': len(time_caused),
                               'reference_elements': len(time_reference), 'critical_set': time_elements,
                               'caused_set': time_caused, 'reference_set': time_reference})

    def _record(self, index, moment, contingency, element, criterion, threshold, ref_value, scen_value, outcome,
                time_elements, time_contingencies, time_caused, time_reference):
        status = outcome['status']
        if status in REFERENCE_VIOLATED:
            time_reference.add(element)
        self.events[status] += 1
        counts = self.element_status.setdefault(element, {})
        counts[(criterion, status)] = counts.get((criterion, status), 0) + 1
        for side, value in (('reference', ref_value), ('scenario', scen_value)):
            if value is None:
                continue
            size = criterion_violation(criterion, value, threshold)
            extremes = self.element_extremes.setdefault(element, {})
            current = extremes.get((criterion, side))
            if size is not None and (current is None or size > current[0]):
                extremes[(criterion, side)] = (size, value, moment, contingency)
        if status not in VIOLATION_STATUSES:
            return
        violation = outcome['scenario_violation']
        self.critical_elements.add(element)
        self.critical_contingencies.add(contingency)
        self.critical_times.add(moment)
        time_elements.add(element)
        time_contingencies.add(contingency)
        if status == 'NEW':
            self.new_elements.add(element)
            time_caused.add(element)
        elif status == 'WORSENED':
            self.worsened_elements.add(element)
            time_caused.add(element)
        register = self._register(contingency)
        register['critical_times'].add(moment)
        register['elements'].add(element)
        register['events'][status] += 1
        finding = (STATUS_RANK[status], -(violation or 0.0), element, moment)
        if register['worst'] is None or finding < register['worst'][0]:
            register['worst'] = (finding, status, element, criterion, moment, violation)
        best = self.max_violation.get(criterion)
        if violation is not None and (best is None or violation > best['violation']):
            self.max_violation[criterion] = self._key(moment, contingency, element, criterion, threshold, ref_value,
                                                      scen_value, outcome)
        change = outcome['change']
        best = self.max_worsening.get(criterion)
        if change is not None and change > 0 and (best is None or change > best['change']):
            self.max_worsening[criterion] = self._key(moment, contingency, element, criterion, threshold, ref_value,
                                                      scen_value, outcome)
        self._episode(index, moment, contingency, element, criterion, status, violation)
        self.events_listed += 1
        priority = (-STATUS_RANK[status], violation or 0.0, abs(change or 0.0))
        item = (priority, self.events_listed, (moment, contingency, element, criterion, threshold, ref_value, scen_value,
                                               status, violation, change))
        if len(self._top) < self.event_limit:
            heapq.heappush(self._top, item)
        elif item > self._top[0]:
            heapq.heapreplace(self._top, item)

    def _key(self, moment, contingency, element, criterion, threshold, ref_value, scen_value, outcome):
        """A finding with its complete comparison key, for extremes and the event register."""
        return {
            'run_id': self.run_id,
            'scenario_id': self.scenario_id,
            'time': moment,
            'contingency': contingency,
            'phase': POST_FAULT_PHASE,
            'element': element,
            'criterion': criterion,
            'unit': CRITERION_UNIT[criterion],
            'threshold': threshold,
            'reference_value': ref_value,
            'scenario_value': scen_value,
            'violation': outcome.get('scenario_violation'),
            'change': outcome.get('change'),
            'delta': outcome.get('delta'),
            'status': outcome['status'],
        }

    # --- episodes: consecutive examined study times with the same finding ---------------------
    def _episode(self, index, moment, contingency, element, criterion, status, violation):
        key = (contingency, element, criterion, status)
        episode = self._open.get(key)
        if episode is not None and episode['last_index'] == index - 1:
            episode.update(last_index=index, last=moment, points=episode['points'] + 1)
            if (violation or 0.0) > (episode['peak'] or 0.0):
                episode.update(peak=violation, peak_time=moment)
            return
        if episode is not None:
            self.episodes.append(episode)
        self._open[key] = {'scenario_id': self.scenario_id, 'contingency': contingency, 'element': element,
                           'criterion': criterion, 'phase': POST_FAULT_PHASE, 'status': status, 'first': moment,
                           'last': moment, 'last_index': index, 'points': 1, 'peak': violation, 'peak_time': moment}

    def _close_episodes(self, index):
        for key in [key for key, episode in self._open.items() if episode['last_index'] < index]:
            self.episodes.append(self._open.pop(key))

    # --- result -----------------------------------------------------------------------------
    def finish(self):
        """Every statistic of the scenario; counts of distinct elements are never sums of event counts."""
        for episode in self._open.values():
            self.episodes.append(episode)
        self._open = {}
        categories = self.meta['categories']
        grids = self.meta.get('grids', {})

        def by_category(elements):
            counted = {category: 0 for category in ('line', 'transformer', 'node')}
            for element in elements:
                counted[REPORT_CATEGORY.get(categories.get(element), 'line')] += 1
            return counted
        monitored = self._monitored()
        scope = {}
        for element in monitored:
            kv = self.meta.get('nominal_kv', {}).get(element)
            key = (grids.get(element) or '', '{} kV'.format(format_limit(kv)) if kv else '-',
                   REPORT_CATEGORY.get(categories.get(element), 'line'))
            entry = scope.setdefault(key, {'monitored': 0, 'critical': 0, 'incomplete': 0})
            entry['monitored'] += 1
            entry['critical'] += element in self.critical_elements
            entry['incomplete'] += any(status in QUALITY_STATUSES for _, status in self.element_status.get(element, {}))
        cells = self._cells()
        required = len(self.requested_times) * len(self.contingencies) * cells
        return {
            'run_id': self.run_id, 'scenario_id': self.scenario_id, 'level': "(n-1)'", 'meta': self.meta,
            'switched_off_keys': sorted(self.switched_off), 'contingency_elements': self.contingency_elements,
            'monitored': by_category(monitored), 'switched_off': len(self.switched_off),
            'critical': by_category(self.critical_elements), 'new_elements': by_category(self.new_elements),
            'worsened_elements': by_category(self.worsened_elements),
            'events': dict(self.events), 'critical_contingencies': len(self.critical_contingencies),
            'critical_times': len(self.critical_times), 'episodes': len(self.episodes),
            'max_violation': dict(self.max_violation), 'max_worsening': dict(self.max_worsening),
            'coverage': {
                'times_requested': len(self.requested_times),
                'times_calculated': len(self.times_calculated),
                'times_missing': sorted(set(self.requested_times) - set(self.times_calculated)),
                'contingencies_defined': len(self.contingencies),
                'contingencies_applicable': len(self.contingencies_applicable),
                'pairs_examined': self.examined_pairs,
                'pairs_not_applicable': self.pairs_not_applicable,
                'pairs_failed': self.pairs_failed,
                'pairs_missing_time': self.pairs_missing_time,
                'cells_required': required,
                'cells_evaluated': sum(self.events[s] for s in VIOLATION_STATUSES + ('RESOLVED', 'OK')),
                'cells_quality': {status: self.events[status] for status in QUALITY_STATUSES},
            },
            'scope': scope,
            'element_status': self.element_status, 'element_extremes': self.element_extremes,
            'element_pairs': {'examined': self.examined_pairs, 'not_applicable': self.pairs_not_applicable,
                              'failed': self.pairs_failed, 'missing_time': self.pairs_missing_time},
            'register': self.register, 'time_criticality': self.time_rows,
            'episode_list': sorted(self.episodes, key=lambda item: (item['element'], item['contingency'], item['first'])),
            'events_top': [self._key(*item[2][:7], {'status': item[2][7], 'scenario_violation': item[2][8],
                                                    'change': item[2][9]})
                           for item in sorted(self._top, reverse=True)],
            'events_listed': self.events_listed,
            'quality': [{'time': key[0], 'contingency': key[1], 'status': key[2], 'cause': key[3], 'cells': value}
                        for key, value in sorted(self.quality.items(), key=lambda entry: (str(entry[0][0]), entry[0][1:]))],
        }


def element_counters(statistics, element, criterion):
    """Status counters of one element and criterion, including the unrecorded OK and the quality cells of the scenario.

    Every examined (study time, contingency) pair contributes one cell per
    criterion: explicitly classified cells are counted as such, the rest of
    the examined pairs are inside the recording limits (OK when the
    recording limit proves it), and pairs without a scenario or reference row
    or study time count as their quality status for every element.
    """
    explicit = {status: count for (crit, status), count in statistics['element_status'].get(element, {}).items()
                if crit == criterion}
    pairs = statistics['element_pairs']
    counters = {status: explicit.get(status, 0) for status in STATUS_PRIORITY}
    counters['OK'] += max(0, pairs['examined'] - sum(explicit.values()))
    counters['NOT_APPLICABLE'] += pairs['not_applicable']
    counters['FAILED'] += pairs['failed']
    counters['NOT_EVALUATED'] += pairs['missing_time']
    return counters


def compare_scenario(run_id, scenario_id, reference, scenario, requested_times, switched_off=(), contingency_elements=None,
                     contingencies=None, parameters=None, event_limit=500):
    """Stream one (n-1)' scenario against the n-1 reference over the requested study times; the statistics.

    `reference` and `scenario` are SweepReader-like sources: `times`,
    `read(moment)`, `meta` and `recording_limits`. Each study time is read,
    classified and dropped before the next one is read.
    """
    meta = {name: {} for name in ('elements', 'contingencies', 'categories', 'nominal_kv', 'grids')}
    times = sorted(set(requested_times))
    aggregate = ScenarioAggregate(run_id, scenario_id, meta, contingencies, times, switched_off, contingency_elements,
                                  scenario.recording_limits or reference.recording_limits, parameters, event_limit)
    ref_times, scen_times = set(reference.times), set(scenario.times)
    for index, moment in enumerate(times):
        ref_step = reference.read(moment) if moment in ref_times else None
        scen_step = scenario.read(moment) if moment in scen_times else None
        for name in meta:
            meta[name].update(reference.meta.get(name, {}))
            meta[name].update(scenario.meta.get(name, {}))
        aggregate.add_time(index, moment, ref_step, scen_step)
    return aggregate.finish()


def level_statistics(run_id, level, reader, requested_times=None, parameters=None):
    """Absolute statistics of one sweep on its own (the n-1 reference): critical elements, contingencies and times.

    A value counts as violated when it lies beyond its criterion's threshold
    by more than the limit tolerance; unrecorded cells are inside the
    recording limits and are no violation only when the limits prove it.
    """
    parameters = parameters or classification_parameters()
    times = sorted(set(requested_times if requested_times is not None else reader.times))
    available = set(reader.times)
    critical, contingencies, critical_times, monitored = set(), set(), set(), set()
    maximum, events, calculated = {}, 0, 0
    for moment in times:
        if moment not in available:
            continue
        calculated += 1
        present, values, _absent = reader.read(moment)
        monitored.update(reader.meta['elements'])
        for (contingency, element, quantity), value in values.items():
            if value is None:
                continue
            for criterion in QUANTITY_CRITERIA[quantity]:
                threshold = element_thresholds(reader.meta, element).get(criterion)
                size = criterion_violation(criterion, value, threshold)
                margin = parameters[CRITERION_QUANTITY[criterion]]['limit'] + parameters['numeric']
                if size is None or size <= margin:
                    continue
                events += 1
                critical.add(element)
                contingencies.add(contingency)
                critical_times.add(moment)
                best = maximum.get(criterion)
                if best is None or size > best['violation']:
                    maximum[criterion] = {'run_id': run_id, 'level': level, 'time': moment, 'contingency': contingency,
                                          'phase': POST_FAULT_PHASE, 'element': element, 'criterion': criterion,
                                          'unit': CRITERION_UNIT[criterion], 'threshold': threshold, 'value': value,
                                          'violation': size}
    categories = reader.meta['categories']

    def by_category(elements):
        counted = {category: 0 for category in ('line', 'transformer', 'node')}
        for element in elements:
            counted[REPORT_CATEGORY.get(categories.get(element), 'line')] += 1
        return counted
    return {
        'run_id': run_id,
        'level': level,
        'monitored': by_category(monitored),
        'critical': by_category(critical),
        'critical_contingencies': len(contingencies),
        'critical_times': len(critical_times),
        'violation_events': events,
        'max_violation': maximum,
        'times_requested': len(times),
        'times_calculated': calculated,
        'critical_set': critical,
        'contingency_set': contingencies,
        'time_set': critical_times,
        'monitored_set': monitored,
    }


def qds_level_statistics(run_id, result):
    """n-0 statistics of a QDS result (REF): monitored and critical elements per class, critical time steps, extremes."""
    critical, critical_rows, maximum = set(), set(), {}
    monitored = {category: 0 for category in ('line', 'transformer', 'node')}
    labels = result.get('labels') or []
    for category in ('line', 'transformer', 'voltage'):
        for item, _stats in result['by_category'].get(category, ()):
            values = item.get('values')
            if values is None:
                continue
            monitored[REPORT_CATEGORY[category]] += 1
            if category == 'voltage':
                lower, upper = voltage_limits(item)
                checks = (('voltage_low', lower), ('voltage_high', upper))
            else:
                checks = (('loading', loading_limit(category)),)
            for criterion, threshold in checks:
                for row, value in enumerate(values):
                    if value is None or value == MISSING:
                        continue
                    size = criterion_violation(criterion, value, threshold)
                    if size is None or size <= NUMERIC_TOLERANCE:
                        continue
                    critical.add(item['key'])
                    critical_rows.add(row)
                    best = maximum.get(criterion)
                    if best is None or size > best['violation']:
                        maximum[criterion] = {
                            'run_id': run_id,
                            'level': 'n-0',
                            'time': labels[row] if row < len(labels) else row,
                            'element': item['key'],
                            'name': item['element_name'],
                            'criterion': criterion,
                            'unit': CRITERION_UNIT[criterion],
                            'threshold': threshold,
                            'value': value,
                            'violation': size,
                        }
    counted = {category: 0 for category in ('line', 'transformer', 'node')}
    for category in ('line', 'transformer', 'voltage'):
        for item, _stats in result['by_category'].get(category, ()):
            if item['key'] in critical:
                counted[REPORT_CATEGORY[category]] += 1
    return {'run_id': run_id, 'level': 'n-0', 'monitored': monitored, 'critical': counted,
            'critical_times': len(critical_rows), 'max_violation': maximum, 'times_calculated': len(labels)}


# ---------------------------------------------------------------------------
# QDS case results, reference comparison and assessment
# ---------------------------------------------------------------------------

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
    return {
        'id': case['id'],
        'name': case['name'],
        'kind': case.get('kind', 'case'),
        'description': case.get('description', ''),
        'status': case.get('status', CONVERGED),
        'error_code': case.get('error_code'),
        'message': case.get('message', ''),
        'counters': dict(case.get('counters') or {}),
        'is_reference': 1 if case['id'] == REFERENCE_ID else 0,
        'labels': list(labels),
        'plot_times': list(plot_times),
        'hours': list(case.get('hours') or plot_times),
        'absolute': bool(case.get('absolute')),
        'time_unit': time_unit,
        'by_category': by_category,
        'stats_by_key': stats_by_key,
        'item_by_key': item_by_key,
        'plan': case.get('plan'),
        'comparison': None,
        'assessment': None,
        'provenance': case.get('provenance', 'CALCULATED'),
        'elapsed': case.get('elapsed'),
        'result_object': case.get('result_object', ''),
    }



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


# Loading in % below which an outaged branch counts as switched off; above it in REF it carried load.
OFF_LOADING = 0.5
OUTAGE_APPLIED, OUTAGE_EFFECT, OUTAGE_NO_EFFECT, OUTAGE_UNCHECKED = 'APPLIED', 'EFFECT SEEN', 'NO EFFECT', 'NOT CHECKABLE'


def outage_effects(result, reference, plan):
    """For every outage of a case: did it take effect in the results? [(outage name, status, reason)].

    APPLIED: inside its window a recorded component carries no load in the
    case while it does in REF. EFFECT SEEN: its components are not recorded,
    but the network differs from REF inside the window. NO EFFECT: the case
    equals REF inside the window - the outage was most likely not applied.
    NOT CHECKABLE: no REF, no absolute time axis or no result row in the window.
    """
    checks = []
    hours = result.get('hours') or []
    case_items, ref_items = result.get('item_by_key') or {}, (reference or {}).get('item_by_key') or {}
    comparable = reference is not None and _same_time_axis(reference, result)
    for record in plan['members']:
        window = plan['windows'][record['key']]
        rows = window_rows(hours, [window]) if result.get('absolute') and window != (None, None) else []
        if not comparable or not rows:
            checks.append((record['name'], OUTAGE_UNCHECKED, 'no reference on the same time axis'
                           if not comparable else 'no result row inside its window'))
            continue
        components = set(record.get('component_keys') or ())
        recorded = [(case_items[key], ref_items[key]) for key in case_items
                    if key[0] != 'voltage' and key[1] in components and key in ref_items
                    and 'values' in case_items[key] and 'values' in ref_items[key]]
        off = [name for case_item, ref_item in recorded
               if max((abs(case_item['values'][row] or 0.0) for row in rows), default=0.0) <= OFF_LOADING
               and max((abs(ref_item['values'][row] or 0.0) for row in rows), default=0.0) > OFF_LOADING
               for name in [case_item['element_name']]]
        if off:
            checks.append((record['name'], OUTAGE_APPLIED, 'without load in its window: ' + clip_text(', '.join(off), 120)))
            continue
        changed = any(
            any(case_item['values'][row] != ref_items[key]['values'][row] for row in rows)
            for key, case_item in case_items.items()
            if key in ref_items and 'values' in case_item and 'values' in ref_items[key])
        if recorded and not changed:
            checks.append((record['name'], OUTAGE_NO_EFFECT, 'its components carry the same load as in REF inside its window'))
        elif changed:
            checks.append((record['name'], OUTAGE_EFFECT, 'components not recorded; the network differs from REF inside its window'
                           if not recorded else 'the network differs from REF inside its window'))
        else:
            checks.append((record['name'], OUTAGE_NO_EFFECT, 'nothing differs from REF inside its window'))
    return checks


def outage_persistence(result, reference, plan):
    """Per outage: does it stay in effect after its window? [(name, hours, total hours, until, back)].

    Counted are the time steps from the window end on in which a recorded
    component of the outage carries no load in the case while it does in REF.
    `hours` is the unbroken stretch right after the window end, `total` every
    such step after it; `until` labels the last step of the stretch and `back`
    the first step in service again ('' when it never is). Outages without a
    recorded component or without REF on the same time axis are left out.
    """
    hours = result.get('hours') or []
    if reference is None or not hours or not result.get('absolute') or not _same_time_axis(reference, result):
        return []
    labels, steps = result.get('labels') or [], row_steps(hours)
    case_items, ref_items = result.get('item_by_key') or {}, reference.get('item_by_key') or {}
    found = []
    for record in plan['members']:
        end = plan['windows'][record['key']][1]
        components = set(record.get('component_keys') or ())
        pairs = [(case_items[key]['values'], ref_items[key]['values']) for key in case_items
                 if key[0] != 'voltage' and key[1] in components and key in ref_items
                 and 'values' in case_items[key] and 'values' in ref_items[key]]
        if end is None or not pairs:
            continue
        first = bisect.bisect_left(hours, end / 3600.0)
        off = [any(abs(case[row] or 0.0) <= OFF_LOADING < abs(ref[row] or 0.0) for case, ref in pairs)
               for row in range(first, len(hours))]
        stretch = next((index for index, value in enumerate(off) if not value), len(off))
        found.append((record['name'], sum(steps[first + index] for index in range(stretch)),
                      sum(steps[first + index] for index, value in enumerate(off) if value),
                      labels[first + stretch - 1] if stretch else '', labels[first + stretch] if stretch < len(off) else ''))
    return found


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
            row = {
                'block': block_number,
                'row_order': order,
                'element_name': name,
                'ref_text': ref_text,
                'col_count': len(block),
                'violation': violation,
            }
            for slot, case in enumerate(block, 1):
                row[case_name_field(slot)] = case['name']
                row[case_text_field(slot)] = texts.get(case['id'], 'n/a')
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
        payload['ScriptedCaseCounts'].append({
            'case_order': order,
            'case_name': _result_name(result),
            'line_count': lines,
            'transformer_count': transformers,
            'node_count': nodes,
        })



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



def _line_bars(payload, results):
    best = {}
    for result in converged(results):
        for item, stats in result['by_category']['line']:
            current = best.get(item['key'])
            if current is None or stats['max'] > current[1]:
                best[item['key']] = (item['element_name'], stats['max'], _result_name(result))
    for rank, (name, value, case_name) in enumerate(sorted(best.values(), key=lambda entry: (-entry[1], entry[0].casefold()))[:setting_value('top_n')], 1):
        payload['ScriptedLineLoadingBars'].append({'rank': rank, 'element_name': name, 'max_value': value, 'case_name': case_name})



def _line_pairs(results, case):
    return [record for record in paired(results, 'line', case, True) if record['ref'] is not None and record['outage'] is not None]



def _case_metrics(payload, results):
    reference = find_reference(results)
    rows = []
    if reference is not None and reference['by_category']['line']:
        top = max(reference['by_category']['line'], key=lambda entry: (entry[1]['max'], -len(entry[0]['element_name'])))
        voltages = [stats for _, stats in reference['by_category']['voltage']]
        rows.append({
            'order': 0,
            'name': REFERENCE_NAME,
            'max': top[1]['max'],
            'element': top[0]['element_name'],
            'delta': None,
            'delta_element': '',
            'difference': None,
            'hours': None,
            'coverage': None,
            'voltage': voltages and (min(s['min'] for s in voltages), max(s['max'] for s in voltages)),
        })
    for order, case in enumerate(outage_cases(results), 1):
        pairs = _line_pairs(results, case)
        lines = [record for record in paired(results, 'line', case, True) if record['outage'] is not None]
        top = max(lines, key=lambda record: (record['outage']['max'], -len(_by_name(record))), default=None)
        rising = max((record for record in pairs if _loading_delta(record) is not None), key=_loading_delta, default=None)
        nodes = [record['outage'] for record in paired(results, 'voltage', case, True) if record['outage'] is not None]
        assessment = case.get('assessment') or {}
        rows.append({
            'order': order,
            'name': case['name'],
            'max': top['outage']['max'] if top else None,
            'element': top['item']['element_name'] if top else '-',
            'delta': _loading_delta(rising) if rising else None,
            'delta_element': rising['item']['element_name'] if rising else '',
            'difference': _maxima_difference(rising) if rising else None,
            'hours': assessment.get('caused_hours'),
            'coverage': assessment.get('coverage'),
            'voltage': nodes and (min(s['min'] for s in nodes), max(s['max'] for s in nodes)),
        })
    for row in rows:
        payload['ScriptedCaseMetrics'].append({
            'case_order': row['order'],
            'case_name': row['name'],
            'max_line_text': loading_text(row['max']),
            'max_line_element': row['element'],
            'coincident_delta_text': '-' if row['delta'] is None else '{} - {}'.format(delta_text(row['delta']), row['delta_element']),
            'maxima_difference_text': delta_text(row['difference']),
            'violation_hours_text': hours_text(row['hours']),
            'voltage_range_text': '{:.3f}-{:.3f} p.u.'.format(*row['voltage']) if row['voltage'] else 'n/a',
            'coverage_text': percent_text(row['coverage']) if row['order'] else 'full period',
        })
    named = [row for row in rows if row['max'] is not None]
    if named:
        top = max(named, key=lambda row: row['max'])
        pair = max((row for row in rows if row['delta'] is not None and row['delta'] > change_tolerance('line')), key=lambda row: row['delta'], default=None)
        payload['ScriptedKpis'].append({
            'highest_text': '{} · {}'.format(loading_text(top['max']), top['element']),
            'highest_caption': 'Highest observed line loading across all cases',
            'highest_violation': 1 if top['max'] > loading_limit('line') else 0,
            'delta_text': '{} · {}'.format(delta_text(pair['delta']), pair['name']) if pair else 'no increase',
            'delta_caption': 'Largest coincident loading increase compared with Reference at the same time step' if pair
            else 'No line loads more than in Reference at the same time step',
        })



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
    outage_quality(payload, results)
    persistence_quality(payload, results)
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
            'case_order': 0,
            'case_id': REFERENCE_ID,
            'case_name': REFERENCE_NAME,
            'is_reference': 1,
            'simulation_status': reference_result['status'],
            'period_text': period_text(labels[0], labels[-1]) if labels else '',
            'priority': 0,
            'equipment_name': 'No planned outage' if not background else 'Fixed outages: ' + ', '.join(record['name'] for record in background),
            'assessment': 'BASELINE' if reference is not None else ASSESSMENT_NO_DATA,
            'assessment_detail': _reference_detail(reference) if reference is not None else reference_result['message'],
            'violation': 0,
            'case_description': 'Comparison basis of every case.',
            'outage_names': ', '.join(record['name'] for record in background) or '-',
            'reference_text': ref_text,
            'states_text': '',
            'windows_text': 'QDS: complete ComStatsim period',
            'coverage_text': 'full period',
            'provenance_text': reference_result.get('provenance', 'CALCULATED'),
        })
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
            'case_order': order,
            'case_id': plan['id'],
            'case_name': plan['name'],
            'is_reference': 0,
            'simulation_status': status,
            'period_text': _plan_period(plan),
            'priority': int(max([record.get('priority') or 0 for record in plan['members']] or [0])),
            'equipment_name': _plan_equipment(plan),
            'assessment': values['assessment'],
            'assessment_detail': detail,
            'violation': values.get('violation', 0),
            'case_description': plan.get('description') or '-',
            'outage_names': ', '.join(record['name'] for record in plan['members']) or '-',
            'reference_text': ref_text,
            'states_text': states_text(plan) or '-',
            'windows_text': _windows_text(plan, request),
            'coverage_text': coverage,
            'provenance_text': provenance,
        })
    for record in request.get('skipped') or ():
        order += 1
        payload['ScriptedCases'].append({
            'case_order': order,
            'case_id': 'N/A',
            'case_name': record['name'],
            'is_reference': 0,
            'simulation_status': record['status'],
            'period_text': period_text(record.get('start_time', ''), record.get('end_time', '')),
            'priority': int(record.get('priority') or 0),
            'equipment_name': record.get('equipment_name') or '-',
            'assessment': ASSESSMENT_SKIPPED,
            'assessment_detail': record.get('skip_reason', ''),
            'violation': 0,
            'case_description': '-',
            'outage_names': record['name'],
            'reference_text': ref_text,
            'states_text': '-',
            'windows_text': '-',
            'coverage_text': '-',
            'provenance_text': 'NOT CALCULATED',
        })


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
            'run_order': order,
            'run_id': result['id'],
            'run_kind': kind if provenance == 'CALCULATED' else kind + ' (reused)',
            'case_name': _result_name(result),
            'reference_text': _reference_text(request) if kind == 'REFERENCE' else REFERENCE_ID if find_reference(results) else 'none',
            'period_text': period_text(labels[0], labels[-1]) if labels else '-',
            'time_steps': len(labels),
            'elapsed_text': '{:.1f} s'.format(result['elapsed']) if result.get('elapsed') is not None and provenance == 'CALCULATED' else '-',
            'status': result['status'],
            'provenance_text': provenance,
            'result_object': result.get('result_object') or '-',
            'note': result.get('run_note') or result.get('message') or '-',
        })
    for plan in request.get('cases') or ():
        if plan['id'] in by_id:
            continue
        order += 1
        payload['ScriptedCalculationRuns'].append({
            'run_order': order,
            'run_id': plan['id'],
            'run_kind': 'NOT RUN',
            'case_name': plan['name'],
            'reference_text': '-',
            'period_text': '-',
            'time_steps': 0,
            'elapsed_text': '-',
            'status': plan['status'],
            'provenance_text': 'NOT CALCULATED',
            'result_object': '-',
            'note': plan.get('reason') or '-',
        })



def n1_value_text(quantity, value):
    if value is None:
        return 'inside recording limits'
    return '{:.1f} %'.format(value) if quantity == 'loading' else '{:.3f} p.u.'.format(value)


def n1_limit_text(limit):
    if not isinstance(limit, dict):
        return '-'
    if limit.get('quantity') == 'loading':
        return 'max {} %'.format(format_limit(limit['max'])) if limit.get('max') is not None else '-'
    if limit.get('min') is None or limit.get('max') is None:
        return '-'
    return '{}-{} p.u.'.format(format_limit(limit['min']), format_limit(limit['max']))


# ---------------------------------------------------------------------------
# Main and detail report tables
# ---------------------------------------------------------------------------
# Both templates read the same tables; each shows its chapters. Every count is taken from the complete
# statistics before any display limit, and both reports print the same numbers for the same run ID.
MAIN_ELEMENT_LIMITS = (('line', 20), ('transformer', 15), ('node', 20))
MAIN_EVENTS_PER_CRITERION = 10
MAIN_REFERENCE_ROWS = 10
RANKING_ROWS = 10
CRITERION_LABELS = {'loading': 'Loading', 'voltage_low': 'Voltage low', 'voltage_high': 'Voltage high'}
CATEGORY_TYPES = {'line': 'Line', 'transformer': 'Transformer', 'node': 'Node', 'voltage': 'Node'}
STATUS_LETTERS = (('NEW', 'N'), ('WORSENED', 'W'), ('PRE_EXISTING', 'P'), ('IMPROVED', 'I'), ('RESOLVED', 'R'))
LEVEL_N0 = 'n-0'


def status_text(status):
    return status.replace('_', '-')


def status_violation(status):
    """Row colour of a status: 1 red (NEW, WORSENED), 2 yellow (other violations, quality), 0 neutral."""
    if status in ('NEW', 'WORSENED'):
        return 1
    return 2 if status in ('PRE_EXISTING', 'IMPROVED') + QUALITY_STATUSES else 0


def criterion_value_text(criterion, value):
    if value is None:
        return '-'
    return '{:.1f} %'.format(value) if criterion == 'loading' else '{:.3f} p.u.'.format(value)


def criterion_limit_text(criterion, threshold):
    if threshold is None:
        return '-'
    if criterion == 'loading':
        return 'max {} %'.format(format_limit(threshold))
    return '{} {} p.u.'.format('min' if criterion == 'voltage_low' else 'max', format_limit(threshold))


def violation_amount_text(criterion, size):
    """How far a value lies beyond its limit (pp for loading, p.u. for voltage); '-' within the limit."""
    if size is None or size <= 0:
        return '-'
    return '{:.1f} pp'.format(size) if criterion == 'loading' else '{:.3f} p.u.'.format(size)


def change_amount_text(criterion, change):
    if change is None:
        return '-'
    return '{:+.1f} pp'.format(change) if criterion == 'loading' else '{:+.3f} p.u.'.format(change)


def _time_text(moment):
    return _format_pf_time(moment) or '-'


def _count_text(count, singular, plural=None):
    return '{} {}'.format(count, singular if count == 1 else plural or singular + 's')


def planning_results(results):
    """(order, result) of every planning case in run order, calculated or not: one numbering for every table."""
    return list(enumerate((result for result in results if result['id'] != REFERENCE_ID), 1))


def _n1_cases(results):
    """(order, case, n-1 entry) of every case whose n-1 was evaluated by the reporting core."""
    return [(order, case, case['n1']) for order, case in planning_results(results)
            if (case.get('n1') or {}).get('status') == 'EVALUATED' and case['n1'].get('statistics')]


def _n1_failed(results):
    """(order, case, n-1 entry) of every case whose n-1 was requested but not evaluated."""
    return [(order, case, case['n1']) for order, case in planning_results(results)
            if case.get('n1') and case['n1'].get('status') != 'EVALUATED']


def _names(entry):
    return entry['statistics'].get('meta') or {name: {} for name in ('elements', 'contingencies', 'categories', 'grids',
                                                                     'nominal_kv')}


def _element_type(meta, element):
    return CATEGORY_TYPES.get(meta['categories'].get(element), 'Element')


def _element_group(meta, element):
    category = meta['categories'].get(element)
    return REPORT_CATEGORY.get(category, 'line')


def _voltage_level_text(meta, element):
    kv = meta['nominal_kv'].get(element)
    return '{} kV'.format(format_limit(kv)) if kv else '-'


def _source_text(entry, level):
    for kind, obj in entry.get('result_objects') or ():
        if kind == level and obj is not None:
            return object_name(obj)
    return 'read at once (not kept)'


def _n0_case_statistics(result, reference):
    """n-0 figures of a QDS case against REF: critical elements per class and distinct NEW/WORSENED elements."""
    lines, transformers, nodes = _violation_counts(result)
    statuses = [record['status'] for records in (result.get('comparison') or {}).values() for record in records]
    return {'critical': {'line': lines, 'transformer': transformers, 'node': nodes},
            'new': statuses.count(STATUS_NEW), 'worsened': statuses.count(STATUS_WORSENED)}


def _case_statistics(payload, results, request):
    """H02/H06: one row per case and level with distinct elements, events, contingencies, time points and completeness."""
    table = payload['ScriptedCaseStatistics']
    reference = find_reference(results)
    if reference is not None:
        n0 = qds_level_statistics(request.get('run_id') or '', reference)
        table.append(_statistics_row(0, REFERENCE_NAME, LEVEL_N0, n0['critical'], 0, 0, None, None, None,
                                     '{} of {} QDS steps'.format(n0['times_calculated'], n0['times_calculated']), 'BASELINE'))
    for order, case in planning_results(results):
        if case['status'] != CONVERGED:
            table.append(_statistics_row(order, case['name'], LEVEL_N0, {'line': 0, 'transformer': 0, 'node': 0}, 0, 0, None, None,
                                         None, case.get('message') or 'no result', ASSESSMENT_NOT_EVALUATED))
            continue
        figures = _n0_case_statistics(case, reference)
        assessment = (judged(results, case) or {}).get('assessment') or ASSESSMENT_NO_DATA if reference is not None else 'NO REFERENCE'
        table.append(_statistics_row(order, case['name'], LEVEL_N0, figures['critical'], figures['new'], figures['worsened'],
                                     None, None, None, coverage_text_of(case), assessment))
    union = {'critical': set(), 'contingencies': set(), 'times': set(), 'monitored': set(), 'requested': set(),
             'calculated': 0}
    for order, case, entry in _n1_cases(results):
        level = entry['reference_statistics']
        union['critical'] |= level['critical_set']
        union['contingencies'] |= level['contingency_set']
        union['times'] |= level['time_set']
        union['requested'] |= set(entry.get('requested_times') or ())
        union['meta'] = _names(entry)
    if union['requested']:
        meta = union['meta']
        critical = {'line': 0, 'transformer': 0, 'node': 0}
        for element in union['critical']:
            critical[_element_group(meta, element)] += 1
        table.append(_statistics_row(0, REFERENCE_NAME, N1_REFERENCE, critical, 0, 0, None, len(union['contingencies']),
                                     len(union['times']), '{} study times in the outage windows'.format(len(union['requested'])),
                                     'BASELINE'))
    for order, case, entry in _n1_cases(results):
        stats = entry['statistics']
        if stats['level'] != N1_PRIME:
            continue
        coverage = stats['coverage']
        events = stats['events']
        quality = sum(events[status] for status in QUALITY_STATUSES)
        caused = events['NEW'] + events['WORSENED']
        verdict = ('NEW OR WORSENED FINDINGS' if caused else 'INCOMPLETE COVERAGE' if quality - events['NOT_APPLICABLE'] > 0
                   else 'NO ADDITIONAL VIOLATION' if events['PRE_EXISTING'] + events['IMPROVED'] else 'NO LIMIT EXCEEDED')
        row = _statistics_row(order, case['name'], N1_PRIME, stats['critical'], sum(stats['new_elements'].values()),
                              sum(stats['worsened_elements'].values()), events, stats['critical_contingencies'],
                              stats['critical_times'], _pair_coverage_text(coverage), verdict)
        row['episodes'] = stats['episodes']
        table.append(row)
    for order, case, entry in _n1_failed(results):
        table.append(_statistics_row(order, case['name'], entry.get('kind') or N1_REFERENCE, {'line': 0, 'transformer': 0, 'node': 0},
                                     0, 0, None, None, None, entry.get('reason') or 'not evaluated', ASSESSMENT_NOT_EVALUATED))


def _statistics_row(order, name, level, critical, new, worsened, events, contingencies, times, completeness, verdict):
    events = events or {}
    quality = sum(events.get(status, 0) for status in QUALITY_STATUSES)
    violation = (1 if new or worsened or events.get('NEW') or events.get('WORSENED') else
                 2 if any(critical.values()) or quality or verdict in ('INCOMPLETE COVERAGE', ASSESSMENT_NOT_EVALUATED) else 0)
    return {
        'case_order': order,
        'case_name': name,
        'level': level,
        'assessment': verdict,
        'critical_lines': critical['line'],
        'critical_transformers': critical['transformer'],
        'critical_nodes': critical['node'],
        'new_elements': new,
        'worsened_elements': worsened,
        'new_events': events.get('NEW', 0),
        'worsened_events': events.get('WORSENED', 0),
        'preexisting_events': events.get('PRE_EXISTING', 0),
        'improved_events': events.get('IMPROVED', 0),
        'resolved_events': events.get('RESOLVED', 0),
        'quality_events': quality,
        'critical_contingencies': contingencies or 0,
        'critical_times': times or 0,
        'episodes': 0,
        'events_text': '{} NEW · {} WORSENED'.format(events.get('NEW', 0), events.get('WORSENED', 0)) if events else
                        'time steps, see the n-0 chapters' if level == LEVEL_N0 else '-',
        'contingencies_text': '-' if contingencies is None else str(contingencies),
        'times_text': '-' if times is None else str(times),
        'completeness_text': completeness or '-',
        'violation': violation,
    }


def coverage_text_of(case):
    coverage = (case.get('assessment') or {}).get('coverage')
    return 'outage time covered: ' + percent_text(coverage) if coverage is not None else 'whole simulated period'


def _pair_coverage_text(coverage):
    required = coverage['cells_required']
    share = coverage['cells_evaluated'] / required if required else None
    return '{} of {} study times; {} of {} contingencies applicable; {} of cells evaluated'.format(
        coverage['times_calculated'], coverage['times_requested'], coverage['contingencies_applicable'],
        coverage['contingencies_defined'], percent_text(share) if share is not None else 'none')


def _coverage(payload, results):
    """H03/D01: requested against calculated study times, contingencies and cells per case and level (three axes)."""
    reference = find_reference(results)
    table = payload['ScriptedCoverage']
    steps = len(reference['labels']) if reference is not None else 0
    if reference is not None:
        table.append(_coverage_row(0, REFERENCE_NAME, LEVEL_N0, steps, steps, {}, 'whole simulated period'))
    for order, case in planning_results(results):
        if case['status'] == CONVERGED:
            table.append(_coverage_row(order, case['name'], LEVEL_N0, steps, len(case['labels']), {}, coverage_text_of(case)))
        else:
            table.append(_coverage_row(order, case['name'], LEVEL_N0, steps, 0, {},
                                       'not evaluated: ' + (case.get('message') or 'no result')))
    for order, case, entry in _n1_cases(results):
        stats = entry['statistics']
        table.append(_coverage_row(order, case['name'], stats['level'], None, None, stats['coverage'],
                                   _pair_coverage_text(stats['coverage'])))
    for order, case, entry in _n1_failed(results):
        table.append(_coverage_row(order, case['name'], entry.get('kind') or N1_REFERENCE, entry.get('times') or 0, 0, {},
                                   'not evaluated: ' + (entry.get('reason') or 'no reason given')))


def _coverage_row(order, name, level, requested, calculated, coverage, text):
    quality = coverage.get('cells_quality') or {}
    missing = (coverage.get('times_requested', requested or 0) - coverage.get('times_calculated', calculated or 0))
    return {
        'case_order': order,
        'case_name': name,
        'level': level,
        'times_requested': coverage.get('times_requested', requested or 0),
        'times_calculated': coverage.get('times_calculated', calculated or 0),
        'contingencies_defined': coverage.get('contingencies_defined', 0),
        'contingencies_applicable': coverage.get('contingencies_applicable', 0),
        'pairs_examined': coverage.get('pairs_examined', 0),
        'pairs_not_applicable': coverage.get('pairs_not_applicable', 0),
        'pairs_failed': coverage.get('pairs_failed', 0),
        'pairs_missing': coverage.get('pairs_missing_time', 0),
        'cells_required': coverage.get('cells_required', 0),
        'cells_evaluated': coverage.get('cells_evaluated', 0),
        'failed_cells': quality.get('FAILED', 0),
        'not_evaluated_cells': quality.get('NOT_EVALUATED', 0),
        'not_applicable_cells': quality.get('NOT_APPLICABLE', 0),
        'not_comparable_cells': quality.get('NOT_COMPARABLE', 0),
        'coverage_text': text,
        'violation': 2 if missing > 0 or text.startswith('not evaluated') or any(
            quality.get(status) for status in ('FAILED', 'NOT_EVALUATED', 'NOT_COMPARABLE')) else 0,
    }


def _scope(payload, results):
    """D01: monitored, critical and not completely evaluable elements per level, grid, voltage level and class."""
    table = payload['ScriptedScope']
    reference = find_reference(results)
    if reference is not None:
        n0 = {}
        for category in ('line', 'transformer', 'voltage'):
            for item, stats in reference['by_category'].get(category, ()):
                kv = item.get('nominal_kv') if category == 'voltage' else None
                key = (element_grid_name(item.get('object')) or '-', '{} kV'.format(format_limit(kv)) if kv else '-',
                       REPORT_CATEGORY[category])
                entry = n0.setdefault(key, [0, 0, 0])
                entry[0] += 1
                entry[1] += bool(stats is not None and is_critical(item, stats))
                entry[2] += stats is None
        for (grid, level_text, category), (monitored, critical, incomplete) in sorted(n0.items()):
            table.append({
                'case_order': 0,
                'case_name': REFERENCE_NAME,
                'level': LEVEL_N0,
                'grid_name': grid,
                'voltage_level': level_text,
                'element_class': CATEGORY_TYPES[category],
                'monitored': monitored,
                'critical': critical,
                'incomplete': incomplete,
            })
    for order, case, entry in _n1_cases(results):
        stats = entry['statistics']
        for (grid, level_text, category), counts in sorted(stats['scope'].items()):
            table.append({
                'case_order': order,
                'case_name': case['name'],
                'level': stats['level'],
                'grid_name': grid or '-',
                'voltage_level': level_text,
                'element_class': CATEGORY_TYPES[category],
                'monitored': counts['monitored'],
                'critical': counts['critical'],
                'incomplete': counts['incomplete'],
            })


def _outage_windows(payload, request):
    """H04/D02: every planned outage of every case with its PowerFactory object, equipment and window (Gantt rows)."""
    order = 0
    origin = None
    rows = []
    for case_order, plan in enumerate(request.get('cases') or (), 1):
        for record in plan['members']:
            start, end = plan['windows'].get(record['key'], (None, None))
            rows.append((case_order, plan, record, start, end))
            if start is not None:
                origin = start if origin is None else min(origin, start)
    for case_order, plan, record, start, end in rows:
        order += 1
        payload['ScriptedOutageWindows'].append({
            'row_order': order, 'case_order': case_order, 'case_name': plan['name'], 'outage_name': record['name'],
            'outage_path': record['key'], 'equipment_name': record.get('equipment_name') or '-',
            'start_text': _time_text(start), 'end_text': _time_text(end),
            'start_hours': (start - origin) / 3600.0 if start is not None and origin is not None else 0.0,
            'end_hours': (end - origin) / 3600.0 if end is not None and origin is not None else 0.0,
            'gantt_label': '{} · {}'.format(plan['name'], record['name'])})


def _element_view(results):
    """Per element and criterion: the n-1 reference extreme over every case and the (n-1)' extreme and counters per case."""
    view = {}
    for order, case, entry in _n1_cases(results):
        stats = entry['statistics']
        meta = _names(entry)
        prime = stats['level'] == N1_PRIME
        switched = set(stats.get('switched_off_keys') or ())
        elements = set(stats['element_extremes']) | set(stats['element_status'])
        for element in elements:
            group = _element_group(meta, element)
            for criterion in (('loading',) if group != 'node' else ('voltage_low', 'voltage_high')):
                record = view.setdefault((element, criterion), {
                    'element': element,
                    'criterion': criterion,
                    'group': group,
                    'name': meta['elements'].get(element, element),
                    'grid': meta['grids'].get(element) or '-',
                    'voltage_level': _voltage_level_text(meta, element),
                    'threshold': element_thresholds(meta, element).get(criterion),
                    'reference': None,
                    'cases': {},
                    'statuses': set(),
                    'quality': False,
                })
                extremes = stats['element_extremes'].get(element, {})
                found = extremes.get((criterion, 'reference'))
                if found is not None and (record['reference'] is None or found[0] > record['reference'][0]):
                    record['reference'] = found
                explicit = {status: count for (crit, status), count in stats['element_status'].get(element, {}).items()
                            if crit == criterion}
                if not prime:
                    explicit = {}
                record['statuses'] |= {status for status, count in explicit.items() if count}
                record['quality'] |= any(explicit.get(status) for status in QUALITY_STATUSES)
                if prime:
                    record['cases'][case['id']] = {'extreme': extremes.get((criterion, 'scenario')), 'counts': explicit,
                                                   'switched_off': element in switched}
        for element in switched:
            for criterion in CRITERIA:
                record = view.get((element, criterion))
                if record is not None and prime:
                    record['cases'][case['id']] = {'extreme': None, 'counts': {}, 'switched_off': True}
    # An element without a value beyond the recording limits in an examined scenario lies inside them there.
    examined = [case['id'] for _order, case, entry in _n1_cases(results)
                if entry['statistics']['level'] == N1_PRIME and entry['statistics']['coverage']['pairs_examined']]
    for record in view.values():
        for case_id in examined:
            record['cases'].setdefault(case_id, {'extreme': None, 'counts': {}, 'switched_off': False})
    return view


def _conspicuous(record):
    """An element and criterion the detail report lists: a finding, a quality problem, a reference violation or a warning."""
    if record['statuses'] - {'OK'} or record['quality']:
        return True
    sizes = [record['reference']] + [entry['extreme'] for entry in record['cases'].values()]
    if any(found is not None and found[0] > 0 for found in sizes):
        return True
    if record['criterion'] == 'loading':
        warning = loading_warning(record['group'])
        return any(found is not None and found[1] >= warning for found in sizes)
    return False


def _rank(record):
    """Main-report order: NEW/WORSENED first, then absolute violations and quality, then the rest; worst first."""
    group = 0 if record['statuses'] & {'NEW', 'WORSENED'} else 1 if (
        record['statuses'] & {'PRE_EXISTING', 'IMPROVED'} or record['quality'] or
        (record['reference'] is not None and record['reference'][0] > 0)) else 2
    sizes = [found[0] for found in [record['reference']] + [entry['extreme'] for entry in record['cases'].values()]
             if found is not None]
    return (group, -(max(sizes) if sizes else float('-inf')), record['name'].casefold())


def _counter_text(counts):
    parts = ['{} {}'.format(letter, counts[status]) for status, letter in STATUS_LETTERS if counts.get(status)]
    quality = sum(counts.get(status, 0) for status in QUALITY_STATUSES)
    if quality:
        parts.append('Q {}'.format(quality))
    return ' · '.join(parts)


def _extreme_text(criterion, found, with_key=False):
    if found is None:
        return 'inside recording limits'
    text = criterion_value_text(criterion, found[1])
    if with_key:
        text += '\n{} · {}'.format(_time_text(found[2]), element_label(found[3]) if found[3] else '-')
    return text


def _case_cell(record, case_id, with_key=False, counters=True):
    entry = record['cases'].get(case_id)
    if entry is None:
        return 'n/a'
    if entry['switched_off']:
        return 'switched off by the case'
    text = _extreme_text(record['criterion'], entry['extreme'], with_key)
    counted = _counter_text(entry['counts']) if counters else ''
    return text + ('\n' + counted if counted else '')


def _record_violation(record):
    if record['statuses'] & {'NEW', 'WORSENED'}:
        return 1
    return 2 if record['statuses'] & {'PRE_EXISTING', 'IMPROVED'} or record['quality'] or (
        record['reference'] is not None and record['reference'][0] > 0) else 0


def _prime_columns(results):
    return [(case['id'], case['name']) for _order, case, entry in _n1_cases(results) if entry['statistics']['level'] == N1_PRIME]


def _block_rows(payload, table, columns, entries, slots, priority=None):
    """entries (name, ref text, {column id: text}, violation) as blocks of `slots` scenario columns; any number of blocks.

    When the blocks together would exceed MAX_TABLE_ROWS, every block keeps the
    same rows: the most severe by `priority` (one sort key per entry), in their
    order; the cut is named in the model quality, the statistics stay complete.
    """
    blocks = [columns[start:start + slots] for start in range(0, len(columns), slots)] or [[]]
    room = MAX_TABLE_ROWS // len(blocks)
    if len(entries) > room:
        order = sorted(range(len(entries)), key=lambda index: priority[index]) if priority else range(len(entries))
        keep = set(list(order)[:room])
        _table_cut(payload, table, '{} of {} rows in each of the {} scenario block(s), the most severe first'.format(
            room, len(entries), len(blocks)))
        entries = [entry for index, entry in enumerate(entries) if index in keep]
    for number, block in enumerate(blocks, 1):
        for order, (name, ref_text, texts, violation) in enumerate(entries, 1):
            row = {
                'block': number,
                'row_order': order,
                'element_name': name,
                'ref_text': ref_text,
                'col_count': len(block),
                'violation': violation,
            }
            for slot, column in enumerate(block, 1):
                row[case_name_field(slot)] = column[1]
                row[case_text_field(slot)] = texts.get(column[0], 'n/a')
            payload[table].append(row)


def _table_cut(payload, table, text):
    _quality(payload, 'table_limit_' + table, 'Table limit ' + table, 'FAIL',
             'Published: {} (MAX_TABLE_ROWS {}). The register is incomplete in print; every count and statistic includes '
             'the rows left out.'.format(text, MAX_TABLE_ROWS))


def _fair_cut(payload, table, group, priority):
    """At most MAX_TABLE_ROWS rows of `table`, shared between the groups (cases): small groups keep everything, the
    others an equal share of the rest; each group keeps its most severe rows (`priority`), in their order."""
    rows = payload[table]
    if len(rows) <= MAX_TABLE_ROWS:
        return
    groups = {}
    for row in rows:
        groups.setdefault(group(row), []).append(row)
    remaining, kept = MAX_TABLE_ROWS, set()
    for position, (_key, members) in enumerate(sorted(groups.items(), key=lambda item: len(item[1]))):
        take = min(len(members), remaining // (len(groups) - position))
        kept.update(id(row) for row in sorted(members, key=priority)[:take])
        remaining -= take
    _table_cut(payload, table, '{} of {} rows, shared between {} group(s), the most severe first'.format(
        len(kept), len(rows), len(groups)))
    payload[table][:] = [row for row in rows if id(row) in kept]


def _critical_elements(payload, results, view, notes):
    """H07: up to 20 lines, 15 transformers and 20 nodes, most critical first; 'shown x of y' from the full count."""
    columns = _prime_columns(results)
    tables = {'line': 'ScriptedCriticalLines', 'transformer': 'ScriptedCriticalTransformers', 'node': 'ScriptedCriticalNodes'}
    for group, limit in MAIN_ELEMENT_LIMITS:
        if group == 'node':
            records = _node_records(view)
        else:
            records = [record for record in view.values() if record['group'] == group and _conspicuous(record)]
        records.sort(key=_rank)
        notes[group] = (min(limit, len(records)), len(records))
        entries = []
        for record in records[:limit]:
            if group == 'node':
                low, high = record['low'], record['high']
                ref_text = '{} / {}'.format(_extreme_text('voltage_low', low['reference'] if low else None).split(' p.u.')[0],
                                            _extreme_text('voltage_high', high['reference'] if high else None))
                texts = {case_id: _node_cell(low, high, case_id) for case_id, _ in columns}
            else:
                ref_text = '{} ({})'.format(_extreme_text(record['criterion'], record['reference']),
                                            criterion_limit_text(record['criterion'], record['threshold']))
                texts = {case_id: _case_cell(record, case_id) for case_id, _ in columns}
            entries.append((record['name'], ref_text, texts, _record_violation(record)))
        _block_rows(payload, tables[group], columns, entries, CASE_SLOTS)


def _node_records(view):
    """Nodes with their low and high voltage records side by side (H07 shows both directions in one row)."""
    nodes = {}
    for (element, criterion), record in view.items():
        if record['group'] != 'node':
            continue
        nodes.setdefault(element, {'low': None, 'high': None})['low' if criterion == 'voltage_low' else 'high'] = record
    merged = []
    for element, pair in nodes.items():
        parts = [part for part in (pair['low'], pair['high']) if part is not None]
        if not any(_conspicuous(part) for part in parts):
            continue
        ranked = min(parts, key=_rank)
        merged.append(dict(ranked, low=pair['low'], high=pair['high'], statuses=set().union(*(p['statuses'] for p in parts)),
                           quality=any(p['quality'] for p in parts)))
    return merged


def _node_cell(low, high, case_id):
    entries = [(record, record['cases'].get(case_id)) for record in (low, high) if record is not None]
    if not any(entry for _, entry in entries):
        return 'n/a'
    if any(entry and entry['switched_off'] for _, entry in entries):
        return 'switched off by the case'
    values, counts = [], {}
    for record, entry in entries:
        if entry is None:
            continue
        values.append(_extreme_text(record['criterion'], entry['extreme']).replace(' p.u.', ''))
        for status, count in entry['counts'].items():
            counts[status] = counts.get(status, 0) + count
    counted = _counter_text(counts)
    return ' / '.join(values) + ' p.u.' * ('inside' not in ' '.join(values)) + ('\n' + counted if counted else '')


def _detail_matrices(payload, results, view):
    """D04-D06b: every conspicuous element, blocks of three scenarios, each extreme with its study time and contingency."""
    columns = _prime_columns(results)
    for table, group, criterion in (('ScriptedDetailLines', 'line', 'loading'),
                                    ('ScriptedDetailTransformers', 'transformer', 'loading'),
                                    ('ScriptedDetailVoltageLow', 'node', 'voltage_low'),
                                    ('ScriptedDetailVoltageHigh', 'node', 'voltage_high')):
        records = [record for record in view.values()
                   if record['group'] == group and record['criterion'] == criterion and _conspicuous(record)]
        records.sort(key=lambda record: (record['grid'].casefold(), record['voltage_level'], record['name'].casefold()))
        entries = []
        for record in records:
            # The name is shortened, not the second line: grid, voltage level and limit stay readable.
            name = '{}\n{}'.format(clip_text(record['name'], MAX_LABEL_LENGTH // 2), ' · '.join(part for part in (
                record['grid'], record['voltage_level'], criterion_limit_text(criterion, record['threshold'])) if part and part != '-'))
            texts = {case_id: _case_cell(record, case_id, with_key=True, counters=False) for case_id, _ in columns}
            entries.append((name, _extreme_text(criterion, record['reference'], with_key=True), texts,
                            _record_violation(record)))
        _block_rows(payload, table, columns, entries, DETAIL_SLOTS, [_rank(record) for record in records])


def _classification(payload, results, view):
    """D07: element x scenario status counters, as text in blocks of three and as full integer counters."""
    columns = _prime_columns(results)
    by_case = {case['id']: (order, case, entry) for order, case, entry in _n1_cases(results)}
    records = sorted((record for record in view.values() if _conspicuous(record)),
                     key=lambda record: (record['group'] != 'line', record['group'] != 'transformer', record['grid'].casefold(),
                                         record['name'].casefold(), record['criterion']))
    entries = []
    for record in records:
        texts = {}
        for case_id, case_name in columns:
            order, case, entry = by_case[case_id]
            cell = record['cases'].get(case_id)
            if cell is None:
                texts[case_id] = 'n/a'
                continue
            if cell['switched_off']:
                texts[case_id] = 'switched off by the case'
                continue
            counters = element_counters(entry['statistics'], record['element'], record['criterion'])
            texts[case_id] = _counter_text(counters) or 'OK only'
        entries.append((record['name'], '{} ({})'.format(CRITERION_LABELS[record['criterion']], CRITERION_UNIT[record['criterion']]),
                        texts, _record_violation(record)))
    _block_rows(payload, 'ScriptedClassificationMatrix', columns, entries, DETAIL_SLOTS, [_rank(record) for record in records])


def _reference_findings(payload, results):
    """H05/D03: n-0 base findings from the QDS REF and n-1 reference findings, thermal and voltage kept apart."""
    rows = []
    reference = find_reference(results)
    if reference is not None:
        for category in ('line', 'transformer', 'voltage'):
            for item, stats in reference['by_category'].get(category, ()):
                if stats is None:
                    continue
                if category == 'voltage':
                    lower, upper = voltage_limits(item)
                    checks = (('voltage_low', stats['min'], lower, stats['time_min']), ('voltage_high', stats['max'], upper, stats['time_max']))
                else:
                    checks = (('loading', stats['max'], loading_limit(category), stats['time_max']),)
                for criterion, value, threshold, moment in checks:
                    size = criterion_violation(criterion, value, threshold)
                    warning = criterion == 'loading' and value >= loading_warning(category)
                    if (size is None or size <= NUMERIC_TOLERANCE) and not warning:
                        continue
                    status = 'VIOLATED' if size is not None and size > NUMERIC_TOLERANCE else 'WARNING'
                    rows.append((LEVEL_N0, criterion, size or 0.0, {
                        'level': LEVEL_N0,
                        'element_name': item['element_name'],
                        'element_type': CATEGORY_TYPES[category],
                        'grid_name': element_grid_name(item.get('object')) or '-',
                        'criterion': CRITERION_LABELS[criterion],
                        'value_text': criterion_value_text(criterion, value),
                        'limit_text': criterion_limit_text(criterion, threshold),
                        'violation_text': violation_amount_text(criterion, size),
                        'time_label': moment or '-',
                        'contingency_name': '-',
                        'status': status,
                        'source_text': reference.get('result_object') or REFERENCE_ID,
                        'violation': 2 if status == 'VIOLATED' else 0,
                    }))
    view = _element_view(results)
    sources = {}
    for _order, _case, entry in _n1_cases(results):
        sources.setdefault('n-1', _source_text(entry, N1_REFERENCE))
    for record in view.values():
        found = record['reference']
        if found is None:
            continue
        criterion = record['criterion']
        warning = criterion == 'loading' and found[1] >= loading_warning(record['group'])
        if found[0] <= NUMERIC_TOLERANCE and not warning:
            continue
        status = 'VIOLATED' if found[0] > NUMERIC_TOLERANCE else 'WARNING'
        rows.append((N1_REFERENCE, criterion, found[0], {
            'level': N1_REFERENCE,
            'element_name': record['name'],
            'element_type': CATEGORY_TYPES[record['group']],
            'grid_name': record['grid'],
            'criterion': CRITERION_LABELS[criterion],
            'value_text': criterion_value_text(criterion, found[1]),
            'limit_text': criterion_limit_text(criterion, record['threshold']),
            'violation_text': violation_amount_text(criterion, found[0]),
            'time_label': _time_text(found[2]),
            'contingency_name': element_label(found[3]) if found[3] else '-',
            'status': status,
            'source_text': sources.get('n-1', '-'),
            'violation': 2 if status == 'VIOLATED' else 0,
        }))
    rows.sort(key=lambda row: (row[0] != LEVEL_N0, CRITERIA.index(row[1]), -row[2], row[3]['element_name'].casefold()))
    ranks, order = {}, 0
    for level, criterion, _size, row in rows:
        key = (level, criterion)
        ranks[key] = ranks.get(key, 0) + 1
        if level != LEVEL_N0 and ranks[key] > MAIN_REFERENCE_ROWS:
            continue  # n-1 reference rows appear only in the main report's top list (the detail report shows n-0, D03)
        order += 1
        row.update(row_order=order, criterion_order=CRITERIA.index(criterion), main_rank=ranks[key] if ranks[key] <= MAIN_REFERENCE_ROWS else 0)
        payload['ScriptedReferenceFindings'].append(row)


def _case_status_counts(payload, results):
    """H06 chart: findings (study time x contingency x element x criterion) per scenario and status."""
    for order, case, entry in _n1_cases(results):
        stats = entry['statistics']
        if stats['level'] != N1_PRIME:
            continue
        events = stats['events']
        payload['ScriptedCaseStatusCounts'].append({
            'case_order': order,
            'case_name': case['name'],
            'new_count': events['NEW'],
            'worsened_count': events['WORSENED'],
            'improved_count': events['IMPROVED'],
            'resolved_count': events['RESOLVED'],
        })


def _contingency_register(payload, results):
    """D08 and the H08 ranking: per scenario and contingency, examined/applicable/failed study times and findings."""
    totals = {}
    for order, case, entry in _n1_cases(results):
        stats = entry['statistics']
        meta = _names(entry)
        outaged = stats.get('contingency_elements') or {}
        rows = []
        for contingency, register in stats['register'].items():
            events = sum(register['events'].values())
            if not (events or register['not_applicable'] or register['failed']):
                continue
            name = meta['contingencies'].get(contingency, element_label(contingency))
            worst = register['worst']
            worst_text = '-'
            if worst is not None:
                _finding, status, element, criterion, moment, violation = worst
                worst_text = '{} {} {} {} at {}'.format(status_text(status), meta['elements'].get(element, element),
                                                        CRITERION_LABELS[criterion].lower(),
                                                        violation_amount_text(criterion, violation), _time_text(moment))
            rows.append((-events, name.casefold(), {
                'case_order': order,
                'case_name': case['name'],
                'level': stats['level'],
                'contingency_name': name,
                'equipment_name': ', '.join(sorted(meta['elements'].get(key, element_label(key)) for key in outaged.get(contingency, ()))) or '-',
                'examined_times': register['examined'],
                'not_applicable_times': register['not_applicable'],
                'failed_times': register['failed'],
                'missing_times': register['missing'],
                'affected_elements': len(register['elements']),
                'critical_times': len(register['critical_times']),
                'new_events': register['events']['NEW'],
                'worsened_events': register['events']['WORSENED'],
                'violation_events': events,
                'worst_text': worst_text,
                'violation': 1 if register['events']['NEW'] + register['events']['WORSENED'] else 2 if events or register['failed'] else 0,
            }))
            if stats['level'] == N1_PRIME or not _prime_columns(results):
                totals[name] = totals.get(name, 0) + events
        for row_order, (_events, _name, row) in enumerate(sorted(rows, key=lambda item: item[:2]), 1):
            row['row_order'] = row_order
            payload['ScriptedContingencyRegister'].append(row)
    ranked = sorted(((count, name) for name, count in totals.items() if count), key=lambda item: (-item[0], item[1].casefold()))
    for rank, (count, name) in enumerate(ranked[:RANKING_ROWS], 1):
        payload['ScriptedContingencyRanking'].append({'rank': rank, 'contingency_name': name, 'finding_count': count})


def _contingency_events(payload, results, notes):
    """H08 top findings per criterion and the D09 selection of single findings with their complete key."""
    main = []
    listed = total = 0
    for order, case, entry in _n1_cases(results):
        stats = entry['statistics']
        meta = _names(entry)
        source = _source_text(entry, stats['level'] if stats['level'] == N1_PRIME else N1_REFERENCE)
        listed += len(stats['events_top'])
        total += stats['events_listed']
        for row_order, event in enumerate(stats['events_top'], 1):
            criterion = event['criterion']
            row = {
                'case_order': order,
                'case_name': case['name'],
                'row_order': row_order,
                'level': stats['level'],
                'time_label': _time_text(event['time']),
                'contingency_name': meta['contingencies'].get(event['contingency'], event['contingency']),
                'phase': event['phase'],
                'element_name': meta['elements'].get(event['element'], event['element']),
                'element_type': _element_type(meta, event['element']),
                'criterion': CRITERION_LABELS[criterion],
                'criterion_order': CRITERIA.index(criterion),
                'unit': event['unit'],
                'reference_text': criterion_value_text(criterion, event['reference_value']) if event['reference_value'] is not None else 'inside recording limits',
                'scenario_text': criterion_value_text(criterion, event['scenario_value']) if event['scenario_value'] is not None else 'inside recording limits',
                'limit_text': criterion_limit_text(criterion, event['threshold']),
                'violation_text': violation_amount_text(criterion, event['violation']),
                'change_text': change_amount_text(criterion, event['change']),
                'status': status_text(event['status']),
                'source_text': source,
                'main_rank': 0,
                'violation': status_violation(event['status']),
            }
            payload['ScriptedContingencyEvents'].append(row)
            main.append(row)
    ranks = {}
    for row in sorted(main, key=lambda row: (row['criterion_order'], STATUS_RANK[row['status'].replace('-', '_')],
                                             -(_amount(row['violation_text'])), row['case_order'], row['row_order'])):
        ranks[row['criterion_order']] = ranks.get(row['criterion_order'], 0) + 1
        if ranks[row['criterion_order']] <= MAIN_EVENTS_PER_CRITERION:
            row['main_rank'] = ranks[row['criterion_order']]
    notes['events'] = (listed, total)


def _amount(text):
    try:
        return float(text.split()[0])
    except (ValueError, IndexError):
        return 0.0


def _episodes(payload, results):
    """D10: every critical episode (consecutive examined study times with the same finding)."""
    for order, case, entry in _n1_cases(results):
        stats = entry['statistics']
        meta = _names(entry)
        source = _source_text(entry, N1_PRIME if stats['level'] == N1_PRIME else N1_REFERENCE)
        for row_order, episode in enumerate(stats['episode_list'], 1):
            criterion = episode['criterion']
            payload['ScriptedContingencyEpisodes'].append({
                'case_order': order,
                'case_name': case['name'],
                'row_order': row_order,
                'level': stats['level'],
                'contingency_name': meta['contingencies'].get(episode['contingency'], episode['contingency']),
                'element_name': meta['elements'].get(episode['element'], episode['element']),
                'element_type': _element_type(meta, episode['element']),
                'criterion': CRITERION_LABELS[criterion],
                'phase': episode['phase'],
                'status': status_text(episode['status']),
                'first_text': _time_text(episode['first']),
                'last_text': _time_text(episode['last']),
                'points': episode['points'],
                'peak_text': violation_amount_text(criterion, episode['peak']),
                'peak_time': _time_text(episode['peak_time']),
                'source_text': source,
                'violation': status_violation(episode['status']),
            })


def _quality_register(payload, results):
    """D11: every quality status with cause and scope, grouped per cause and contingency; cases not evaluated as a whole."""
    order = 0
    for case_order, case, entry in _n1_cases(results):
        stats = entry['statistics']
        meta = _names(entry)
        grouped = {}
        for item in stats['quality']:
            key = (item['status'], item['cause'], item['contingency'])
            found = grouped.setdefault(key, {'times': set(), 'cells': 0})
            found['times'].add(item['time'])
            found['cells'] += item['cells']
        for (status, cause, contingency), found in sorted(grouped.items(), key=lambda entry: (STATUS_RANK[entry[0][0]], entry[0][1], entry[0][2])):
            order += 1
            times = sorted(found['times'], key=lambda value: (value is None, value))
            payload['ScriptedQualityRegister'].append({
                'row_order': order,
                'case_order': case_order,
                'case_name': case['name'],
                'level': stats['level'],
                'status': status_text(status),
                'cause': cause,
                'contingency_name': 'every contingency' if contingency == '*' else meta['contingencies'].get(contingency, contingency),
                'time_text': '{} to {} ({})'.format(_time_text(times[0]), _time_text(times[-1]), _count_text(len(times), 'study time'))
                if times else '-',
                'cells': found['cells'],
                'violation': 0 if status == 'NOT_APPLICABLE' else 2,
            })
    for case_order, case, entry in _n1_failed(results):
        order += 1
        payload['ScriptedQualityRegister'].append({
            'row_order': order,
            'case_order': case_order,
            'case_name': case['name'],
            'level': entry.get('kind') or N1_REFERENCE,
            'status': 'NOT-EVALUATED',
            'cause': entry.get('reason') or 'not evaluated',
            'contingency_name': 'every contingency',
            'time_text': 'every study time of the case',
            'cells': 0,
            'violation': 2,
        })
    for case_order, case in planning_results(results):
        if case['status'] != CONVERGED:
            order += 1
            payload['ScriptedQualityRegister'].append({
                'row_order': order, 'case_order': case_order, 'case_name': case['name'], 'level': LEVEL_N0,
                'status': 'FAILED', 'cause': case.get('message') or 'no QDS result', 'contingency_name': '-',
                'time_text': 'every time step of the case', 'cells': 0, 'violation': 2})


def _time_criticality(payload, results, notes):
    """H09: distinct critical elements per actual study time (n-1 reference and (n-1)' over every scenario) and per scenario."""
    columns = _prime_columns(results)
    per_time = {}
    for order, case, entry in _n1_cases(results):
        stats = entry['statistics']
        prime = stats['level'] == N1_PRIME
        for row in stats['time_criticality']:
            found = per_time.setdefault(row['time'], {'reference': set(), 'scenario': set(), 'caused': set(), 'cases': {}})
            found['reference'] |= row['reference_set'] if prime else row['critical_set']
            if prime:
                found['scenario'] |= row['critical_set']
                found['caused'] |= row['caused_set']
                found['cases'][case['id']] = row
    entries = []
    for moment in sorted(per_time):
        found = per_time[moment]
        payload['ScriptedTimeCriticality'].append({
            'time_label': _time_text(moment),
            'timestamp': float(moment),
            'chart_title': 'Distinct critical elements per study time',
            'unit': 'elements',
            series_name_field(0): 'n-1 reference',
            series_value_field(0): float(len(found['reference'])),
            series_name_field(1): "(n-1)' all scenarios",
            series_value_field(1): float(len(found['scenario'])),
        })
        texts = {}
        for case_id, _name in columns:
            row = found['cases'].get(case_id)
            texts[case_id] = ('E {} · C {}'.format(row['critical_elements'], row['critical_contingencies'])
                              if row is not None else 'not assessed')
        entries.append((_time_text(moment), str(len(found['reference'])), texts,
                        1 if found['caused'] else 2 if found['scenario'] or found['reference'] else 0))
    _block_rows(payload, 'ScriptedTimeMatrix', columns, entries, CASE_SLOTS)
    notes['times'] = len(per_time)


def _assessment_settings(payload):
    """H10/D12: every setting of the run with its value, unit, origin and whether it is applied."""
    snapshot = settings_snapshot(active_overrides())
    for order, setting in enumerate(SETTINGS, 1):
        key = setting['key']
        if key not in snapshot['values']:
            value, origin, status = NOT_VERIFIED, setting['source'], 'not applied (' + NOT_VERIFIED + ')'
        else:
            value, origin = setting_text(key, snapshot['values'][key]), snapshot['sources'][key]
            status = ('applied' if setting['category'] != CATEGORY_CALCULATION else
                      snapshot['calculation_parameters'].get(key, NOT_VERIFIED))
        payload['ScriptedAssessmentSettings'].append({
            'row_order': order, 'section': setting['section'], 'setting_key': key, 'label': setting['label'],
            'value_text': value, 'unit': setting.get('unit') or '-', 'origin': origin, 'status': status})


def _result_provenance(payload, results):
    """H10/D12: every result object the report rests on, with its PowerFactory path where it is known."""
    order = 0
    for result in results:
        order += 1
        payload['ScriptedResultProvenance'].append({
            'row_order': order,
            'level': LEVEL_N0,
            'case_name': _result_name(result),
            'object_name': result.get('result_object') or '-',
            'object_path': result.get('result_path') or '-',
            'content_text': '{} QDS time steps'.format(len(result.get('labels') or ())),
            'status': result['status'],
        })
    for _order, case, entry in _n1_cases(results):
        for kind, obj in entry.get('result_objects') or ():
            order += 1
            payload['ScriptedResultProvenance'].append({
                'row_order': order,
                'level': kind,
                'case_name': case['name'],
                'object_name': object_name(obj) if obj is not None else 'read at once (not kept)',
                'object_path': object_key(obj) if obj is not None else '-',
                'content_text': '{} study times requested'.format(len(entry.get('requested_times') or ())),
                'status': 'EVALUATED',
            })


def _reporting_tables(payload, results, request):
    """Every contract 7.0 table built from the reporting core; returns the notes for ScriptedReportMeta."""
    notes = {}
    _case_statistics(payload, results, request)
    _coverage(payload, results)
    _scope(payload, results)
    _outage_windows(payload, request)
    view = _element_view(results)
    _critical_elements(payload, results, view, notes)
    _detail_matrices(payload, results, view)
    _classification(payload, results, view)
    _reference_findings(payload, results)
    _case_status_counts(payload, results)
    _contingency_register(payload, results)
    _contingency_events(payload, results, notes)
    _episodes(payload, results)
    _quality_register(payload, results)
    _time_criticality(payload, results, notes)
    _assessment_settings(payload)
    _result_provenance(payload, results)
    # Long registers are cut fairly between the cases, never by case order; the statistics above stay complete.
    def by_case(row):
        return row['case_order']

    def severity(row):
        return (STATUS_RANK.get(row['status'].replace('-', '_'), len(STATUS_RANK)),
                -_amount(row.get('peak_text') or row.get('violation_text') or '0'), row['row_order'])

    _fair_cut(payload, 'ScriptedContingencyEpisodes', by_case, severity)
    _fair_cut(payload, 'ScriptedContingencyEvents', by_case, lambda row: row['row_order'])
    _fair_cut(payload, 'ScriptedContingencyRegister', by_case, lambda row: row['row_order'])
    _fair_cut(payload, 'ScriptedQualityRegister', by_case, lambda row: row['row_order'])
    _fair_cut(payload, 'ScriptedReferenceFindings', lambda row: (row['level'], row['criterion']), lambda row: row['row_order'])
    return notes


def critical_note(notes):
    parts = []
    for group, singular, plural in (('line', 'line', 'lines'), ('transformer', 'transformer', 'transformers'), ('node', 'node', 'nodes')):
        shown, total = notes.get(group, (0, 0))
        parts.append('{} of {} {}'.format(shown, total, singular if total == 1 else plural))
    return ('Shown: ' + ', '.join(parts) + ' (conspicuous elements, most critical first; the counts come from the complete '
            'evaluation, the detail report lists every one).')


def events_note(notes):
    listed, total = notes.get('events', (0, 0))
    return ('Top findings per criterion across every scenario. The detail report lists {} of {} critical single findings '
            '(a prioritised selection per scenario); every count comes from the complete evaluation.'.format(listed, total))


def overall_text(payload):
    """H02: what the statistics say, without a security release."""
    rows = [row for row in payload['ScriptedCaseStatistics'] if row['level'] == N1_PRIME and row['assessment'] != ASSESSMENT_NOT_EVALUATED]
    failed = [row['case_name'] for row in payload['ScriptedCaseStatistics']
              if row['assessment'] == ASSESSMENT_NOT_EVALUATED and row['level'] != LEVEL_N0]
    failed_n0 = [row['case_name'] for row in payload['ScriptedCaseStatistics']
                 if row['assessment'] == ASSESSMENT_NOT_EVALUATED and row['level'] == LEVEL_N0]
    missing = ''
    if failed_n0:
        missing += 'The QDS of {} case(s) could not be evaluated: {}. '.format(len(failed_n0), clip_text(', '.join(failed_n0), 200))
    if failed:
        missing += 'The contingency analysis of {} case(s) was requested but could not be evaluated: {}. '.format(
            len(failed), clip_text(', '.join(failed), 200))
    if not rows:
        return (missing + ('No (n-1)\' scenario could be assessed; there is no n-1 result to rely on. ' if failed else
                           'No (n-1)\' scenario was assessed in this run; the n-0 chapters compare the planning cases with Reference. ')
                + 'This pre-assessment is no release and no proof of n-1 security.')
    caused = [row['case_name'] for row in rows if row['new_events'] or row['worsened_events']]
    incomplete = [row['case_name'] for row in rows if row['assessment'] == 'INCOMPLETE COVERAGE']
    text = '{} scenario(s) assessed against the n-1 reference. '.format(len(rows))
    text += ('NEW or WORSENED findings in: {}. '.format(clip_text(', '.join(caused), 200)) if caused
             else 'No scenario adds or worsens a violation in the assessed study times. ')
    if incomplete:
        text += 'Incomplete evaluation in: {}; their results are no clearance. '.format(clip_text(', '.join(incomplete), 200))
    return text + missing + 'This pre-assessment is no release and no proof of n-1 security.'


def empty_tables(payload):
    """',Table,Table,' of every table without rows: the templates show their empty-state notes by it."""
    return ',' + ','.join(name for name, _ in TABLES if not payload.get(name)) + ','


def n1_meta_text(results):
    """What the n-1 chapter shows, for the report; ('1' or '0', text)."""
    kinds = {case['n1'].get('kind') for case in outage_cases(results) if case.get('n1', {}).get('status') == 'EVALUATED'}
    if not kinds:
        assessed = any(case.get('n1') for _order, case in planning_results(results))
        return '0', ('n-1 was requested but could not be evaluated; see the quality register and the model quality page.'
                     if assessed else 'n-1 was not assessed in this run (tick n-1 in the case manager).')
    return '1', ("Contingency analysis of the study case at the QDS time steps inside each case's outage windows. "
                 + ("(n-1)' (with the case's planned outages) is classified against n-1 (without them) per study time, "
                    "contingency and element; an element counts with its worst result. " if N1_PRIME in kinds else
                    "Only the n-1 reference was calculated: its violations are shown as PRE-EXISTING. ")
                 + n1_filter_text() + '.')


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
    payload['ScriptedReportMeta'].append({
        'run_id': request.get('run_id') or '-',
        'study_name': object_name(study_case),
        'study_description': object_description(study_case),
        'model_name': project_name,
        'model_version': 'PowerFactory 2026',
        'simulation_start': start,
        'simulation_end': end,
        'simulation_time_step': time_step or 'ElmRes row interval',
        'generation_date': datetime.now().astimezone().strftime('%Y-%m-%d %H:%M'),
        'generated_by': generated_by,
        'run_mode': run_mode,
        'template_name': TEMPLATE_NAME,
        'template_version': TEMPLATE_VERSION,
        'data_contract_version': DATA_CONTRACT_VERSION,
        'result_name': result_name,
        'assessment_scope': '{} planning case(s); reference: {}; {}'.format(len(request.get('cases') or ()), reference['name'] if reference else 'none', grid_scope_text()),
        'assessment_status': 'PRE-ASSESSMENT - NOT AN OPERATIONAL RELEASE',
        'voltage_limits': voltage_limits_text(),
        'has_cases': '1' if cases else '0',
        'case_source_text': request.get('source_text') or 'not stated',
        'reference_text': _reference_text(request),
        'qds_mode_text': qds_mode_text(request),
        'coverage_statement': coverage_statement(results, request),
        'has_contingency': n1_meta_text(results)[0],
        'contingency_text': n1_meta_text(results)[1],
    })
    _case_rows(payload, results, request)
    records = request.get('records') or []
    used = {record['key'] for plan in request.get('cases') or () for record in plan['members']}
    _quality(payload, 'planned_outages', 'Planned outages', 'PASS' if used else 'WARNING',
             '{} found; {} assigned to a planning case; {} not calculated.'.format(len(records), len(used), len(records) - len(used)))
    _model_quality(payload, results, request)
    _case_metrics(payload, results)
    _pies(payload, results)
    _case_counts(payload, results)
    _line_bars(payload, results)
    _case_comparison(payload, results)
    _calculation_runs(payload, results, request)
    _top_lines_by_case(payload, results)
    _loading_appendix(payload, results, 'line', 'ScriptedAppendixLine')
    _loading_appendix(payload, results, 'transformer', 'ScriptedAppendixTransformer')
    _voltage_appendix(payload, results)
    notes = _reporting_tables(payload, results, request)
    meta = payload['ScriptedReportMeta'][0]
    meta.update(overall_text=overall_text(payload), critical_note=critical_note(notes), events_note=events_note(notes))
    _enforce_table_limits(payload)
    meta['empty_tables'] = empty_tables(payload)
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


# ---------------------------------------------------------------------------
# Report validation and PowerFactory publication
# ---------------------------------------------------------------------------


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
        field_names = {field for field, _ in fields} | set(UNPUBLISHED_FIELDS.get(name, ()))
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


# ---------------------------------------------------------------------------
# Runtime errors, diagnostics and PowerFactory outage discovery
# ---------------------------------------------------------------------------

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
    """Expected runtime error with an actionable user-facing message.

    `details` are the facts behind it (objects, values read back, what was
    found), one line each; `hint` is what the engineer can do. Both appear in
    the failure report.
    """

    def __init__(self, message='', details=(), hint=''):
        super().__init__(message)
        self.details = [str(line) for line in details or ()]
        self.hint = hint


class RecordingError(GridLensError):
    """The kept result object records none of the assessed variables; every further run would do the same."""


# Where the run is and what it has done, for the failure report; reset at the start of every run.
RUN_CONTEXT = {}


def reset_run_context():
    RUN_CONTEXT.clear()
    RUN_CONTEXT.update(step='before step 1', case='', warnings=[], restore='not reached: nothing was changed yet',
                       kept=[], recording_checked=False)


reset_run_context()


def log_error_details(logger, exc, level="ERROR"):
    """The detail lines and the hint of a GridLensError below its message."""
    for line in getattr(exc, 'details', None) or ():
        logger.detail("  " + line, level)
    if getattr(exc, 'hint', ''):
        logger.detail("  What to do: " + exc.hint, level)


def _cause_chain(exc):
    chain, current, seen = [], exc, set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        chain.append(current)
        current = current.__cause__ or (None if current.__suppress_context__ else current.__context__)
    return chain


def log_failure(logger, exc):
    """The failure report: what failed, where, why, what PowerFactory holds now and what to do."""
    logger.section("FAILURE REPORT · the run stopped")

    def block(title, lines):
        lines = [line for line in lines if line not in (None, '')]
        if not lines:
            return
        logger.detail(title + ":", "ERROR")
        for line in lines:
            for part in textwrap.wrap(str(line), 104) or ['']:
                logger.detail("    " + part, "ERROR")

    chain = _cause_chain(exc)
    block("Error", ["{}: {}".format(type(exc).__name__, str(exc).strip() or "(no message)")])
    step, case = RUN_CONTEXT.get('failed_at') or (RUN_CONTEXT.get('step'), RUN_CONTEXT.get('case'))
    block("Where", [step, "case: " + case if case else ''])
    block("Caused by", ["{}: {}".format(type(cause).__name__, str(cause).strip()) for cause in chain[1:]])
    block("Details", [line for cause in chain for line in getattr(cause, 'details', None) or ()])
    frames, link = [], exc.__traceback__
    while link is not None:
        frames.append("{}() line {}".format(link.tb_frame.f_code.co_name, link.tb_lineno))
        link = link.tb_next
    block("Code location in gridlens_report.py (innermost last)", frames[-6:])
    block("PowerFactory state", [RUN_CONTEXT.get('restore')])
    block("Result objects kept in the study case", RUN_CONTEXT.get('kept') or ["none"])
    block("Warnings before the failure", (RUN_CONTEXT.get('warnings') or [])[-6:])
    block("What to do", [next((cause.hint for cause in chain if getattr(cause, 'hint', '')),
                              "Correct the reported condition, verify the active study case, and run GridLens again.")])


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


def outage_branches(outage, parts=None):
    """Branches an outage switches off, from its components and its actions."""
    _, related = parts or _outage_parts(outage)
    return [item for item in related.values() if class_name(item) in BRANCH_CLASSES]


def outage_component_keys(outage, parts=None):
    """Keys of every object the outage or its actions name as components."""
    _, related = parts or _outage_parts(outage)
    return sorted(related)


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


def attribute_label(obj, attribute):
    """PowerFactory's own label of an attribute (GetAttributeDescription), '' when it gives none."""
    describe = getattr(obj, "GetAttributeDescription", None)
    if not callable(describe):
        return ""
    try:
        text = describe(attribute)
    except Exception:
        return ""
    return str(text).strip() if isinstance(text, str) else ""


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


SWITCH_CLASSES = ("ElmCoup", "StaSwitch")


def switch_states(app):
    """{key: (name, on_off)} of every calculation-relevant switch; {} when they cannot be read."""
    found = {}
    for kind in SWITCH_CLASSES:
        try:
            switches = list(app.GetCalcRelevantObjects("*." + kind) or [])
        except Exception:
            switches = []
        for switch in switches:
            state = finite_number(safe_attr(switch, "on_off"))
            if state is not None:
                found[object_key(switch)] = (object_name(switch), state)
    return found


def switch_changes_text(before, after):
    """The switches whose state differs between two snapshots, e.g. "CB1 closed -> open"."""
    word = {0.0: "open", 1.0: "closed"}
    changed = ["{} {} -> {}".format(name, word.get(state, state), word.get(after[key][1], after[key][1]))
               for key, (name, state) in sorted(before.items(), key=lambda entry: entry[1][0])
               if key in after and after[key][1] != state]
    return changed


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
# Allen interval relations between two half-open outage windows [start, end).
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
        plan = {
            'id': case['id'],
            'name': str(case.get('name') or case['id']),
            'description': str(case.get('description') or ''),
            'members': [],
            'windows': {},
            'status': PLAN_READY,
            'reason': '',
            'warnings': [],
            'states': [],
            'relations': [],
            'overridden': [],
        }
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
    return {
        'source': source,
        'source_text': source_text or source,
        'revision': config.get('revision'),
        'background': background,
        'cases': plans,
        'skipped': [],
        'records': list(records),
        'config': config,
        'warnings': request_warnings,
        'disabled': disabled,
        'assessments': list(config.get('assessments') or ['n-0']),
        'settings': dict(config.get('settings') or {}),
    }


def per_outage_config(candidates, project_key=''):
    """One case per planned outage in the simulated period."""
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
           "inside the outage windows of each case. Results appear in the log and in the contingency and quality "
           "sections of the reports.")
# Case-manager help texts describing each control's effect on the calculation.
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
    'calculation_parameters': "Category B: these parameters can change what PowerFactory calculates. " + CONTINGENCY_SETTINGS_NOTE,
    'restore_defaults': "Removes the user overrides and loads the valid default values of GridLens (and of PowerFactory, "
                        "once those are read).",
    'apply_settings': "Checks the entries and uses the settings for the next selected calculations.",
    'save_settings': "Checks the entries and saves the settings for later use. Provisional: they are written into the "
                     "case configuration file of this project (JSON), not yet into the PowerFactory project; the "
                     "project itself is not touched.",
    'monitoring_grids': "Report filter. Only lines, transformers and terminals in the selected grids are assessed: "
                        "their QDS results and the monitored elements of n-1 and (n-1)'. Every other element is "
                        "left out of the report. No grid selected: every grid. It never changes the calculation "
                        "(PowerFactory calculates the whole network) and applies in full when a kept run is "
                        "re-evaluated.",
    'contingency_grids': "n-1 filter for the calculation. Only contingencies whose outaged equipment lies in the "
                         "selected grids are analysed; the others are set to 'Not analysed' for the n-1 run and "
                         "restored afterwards. 'Every grid' analyses every contingency. In a re-evaluation it leaves "
                         "contingencies out of the evaluation; it cannot add ones that were not calculated.",
    'contingency_elements': "n-1 filter for the calculation. Choose the elements that are outaged in n-1 and (n-1)': "
                            "only contingencies that outage at least one selected element are analysed, every other is "
                            "set to 'Not analysed' for the n-1 run (or not created when GridLens defines the "
                            "contingencies). None selected: every element is outaged. The loading of every element is "
                            "still assessed under the analysed contingencies. In a re-evaluation it leaves the other "
                            "contingencies out of the evaluation.",
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
                 kept=(), elements=()):
        self.records = list(records)
        # [(key, name, class, grid)] the n-1 element filter offers (contingency_element_choices).
        self.element_choices = [tuple(item) for item in elements or ()]
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
        self.config['cases'].append({
            'id': identifier,
            'name': name.strip() or 'Case ' + identifier[1:],
            'description': '',
            'enabled': True,
            'outages': [],
            'overrides': {},
        })
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

    def selected_elements(self):
        """The element keys of the n-1 element filter."""
        return tuple(self.settings_overrides().get('contingency_elements', ()))

    def element_text(self, key):
        """'name (class, grid)' of an element key, from the choices; the short name when it is no longer offered."""
        for item in self.element_choices:
            if item[0] == key:
                return '{} ({}{})'.format(item[1], item[2], ', ' + item[3] if item[3] else '')
        return element_label(key) + ' (no longer in a contingency)'

    def set_elements(self, keys):
        """Select the elements outaged in n-1 at once (no Apply needed; none: every element). A problem or None."""
        value, problem = parse_elements('contingency_elements', list(keys))
        if problem:
            return problem
        try:
            current = effective_settings(self.settings_overrides())
        except GridLensError:
            current = default_settings()
        current['contingency_elements'] = value
        self.config['settings'] = clean_overrides(current)
        return None

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
        text = contingency_scope_text(self.contingencies, self.selected_grids('contingency_grids'),
                                      self.selected_grids('monitoring_grids'))
        elements = self.selected_elements()
        if elements:
            text += ' Outaged elements only: {}.'.format(', '.join(self.element_text(key) for key in elements))
        return text

    def filter_note(self):
        """What the filters do for the chosen results: a calculation, or a re-evaluation of a kept run."""
        if not self.evaluate_stamp:
            return ('Calculate now: the report filter acts on the evaluation only; the n-1 filters decide which '
                    'contingencies PowerFactory calculates.')
        return ('Re-evaluate the kept run of {}: the report filter applies in full. The n-1 filters leave '
                'contingencies out of the evaluation; contingencies that were not calculated then cannot be added '
                'without calculating again.'.format(stamp_text(self.evaluate_stamp)))

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
                 'Report filter: ' + self.monitoring_text(),
                 'Contingencies: ' + self.contingency_preview(),
                 'Filters: ' + self.filter_note(),
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
        root.geometry(window_geometry(root.winfo_screenwidth(), root.winfo_screenheight(), share=0.82, largest=(1200, 760)))
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
        note = self._wrapped_label(options, "n-1 and (n-1)': results in the log and reports",
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
        title = ttk.Label(left, text='Report filter: assessed equipment', style='Title.TLabel')
        title.grid(row=0, column=0, columnspan=2, sticky='w')
        self.tip(title, setting_help('monitoring_grids'))
        self._wrapped_label(left, 'Choose the grids whose equipment is assessed in the report. No effect on the '
                            'calculation; also applies when a kept run is re-evaluated.', row=1, column=0, columnspan=2,
                            pady=(6, 10))
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
        title = ttk.Label(right, text='n-1 filter: contingencies by grid', style='Title.TLabel')
        title.grid(row=0, column=0, columnspan=2, sticky='w')
        self.tip(title, setting_help('contingency_grids'))
        self.contingency_mode = tk.StringVar(value='same')
        choices = ttk.Frame(right, style='Card.TFrame')
        choices.grid(row=1, column=0, columnspan=2, sticky='ew', pady=(6, 10))
        for row, (value, text) in enumerate((('same', 'Every grid (no filter)'), ('own', 'Own selection'))):
            radio = ttk.Radiobutton(choices, text=text, value=value, variable=self.contingency_mode,
                                    command=self.on_contingency_mode)
            radio.grid(row=row, column=0, sticky='w')
            self.tip(radio, setting_help('contingency_grids'))
        self._grid_search_field(right, 'contingency_grids', row=3)
        self._grid_listbox(right, 'contingency_grids', row=4)
        self.contingency_note = self._wrapped_label(right, '', row=5, column=0, columnspan=2, pady=(10, 0))
        self.tip(self.contingency_note, SETTING_HELP['contingency_preview'])
        self._build_element_filter(right, first_row=7)
        self.refresh_scope()

    def _build_element_filter(self, card, first_row):
        """The n-1 element filter below the grid filter of the same card: a searchable list of the elements the
        contingencies outage. Its list shares the flexible height with the grid list, so the page still fits."""
        tk, ttk = self.tk, self.ttk
        row = lambda offset: first_row + offset
        card.rowconfigure(row(4), weight=1)
        title = ttk.Label(card, text='n-1 filter: outaged elements', style='Title.TLabel')
        title.grid(row=row(0), column=0, columnspan=2, sticky='w', pady=(16, 0))
        self.tip(title, setting_help('contingency_elements'))
        self._wrapped_label(card, 'Select the elements that are outaged in n-1 and (n-1)\'. Only contingencies that '
                            'outage a selected element are calculated. None selected: every element.', row=row(1),
                            column=0, columnspan=2, pady=(6, 10))
        self.element_search = tk.StringVar()
        ttk.Label(card, text='Search elements', style='Muted.TLabel').grid(row=row(2), column=0, sticky='w', pady=(0, 4))
        entry = ttk.Entry(card, textvariable=self.element_search, width=12)
        entry.grid(row=row(3), column=0, columnspan=2, sticky='ew', pady=(0, 6))
        self.element_search.trace_add('write', lambda *_args: self.refresh_elements())
        self.tip(entry, 'Filter the visible elements by name, class or grid. Selected elements remain selected when '
                        'hidden by the search.')
        box = tk.Listbox(card, selectmode='multiple', exportselection=False, height=4, width=12, activestyle='dotbox',
                         background=self.CARD, foreground=self.TEXT, selectbackground=self.SELECTED,
                         selectforeground=self.TEXT, highlightthickness=1, highlightcolor=self.ACCENT,
                         highlightbackground=self.BORDER, relief='flat', font=self.body_font, borderwidth=0)
        box.grid(row=row(4), column=0, sticky='nsew')
        scroll = ttk.Scrollbar(card, orient='vertical', command=box.yview)
        scroll.grid(row=row(4), column=1, sticky='ns')
        box.configure(yscrollcommand=lambda first, last: self._scrollbar(scroll, first, last))
        box.bind('<<ListboxSelect>>', lambda _event: self.on_element_select(), add='+')
        self.tip(box, setting_help('contingency_elements'))
        self.element_list, self.element_visible = box, []
        self.element_note = self._wrapped_label(card, '', row=row(5), column=0, columnspan=2, pady=(10, 0))
        button = ttk.Button(card, text='Clear selection', command=lambda: self.select_elements([]))
        button.grid(row=row(6), column=0, sticky='w', pady=(10, 0))
        self.tip(button, 'No element selected: every element is outaged in n-1 again. Takes effect at once.')

    def refresh_elements(self):
        """Render the element list without changing the selection."""
        box = getattr(self, 'element_list', None)
        if box is None:
            return
        query = self.element_search.get().strip().casefold()
        selected = set(self.editor.selected_elements())
        choices = [item[0] for item in self.editor.element_choices]
        visible = [key for key in choices + sorted(selected - set(choices)) if query in self.editor.element_text(key).casefold()]
        self.element_visible = visible
        scroll = box.yview()
        box.delete(0, 'end')
        for key in visible:
            box.insert('end', self.editor.element_text(key))
            if key in selected:
                box.selection_set('end')
        if scroll:
            box.yview_moveto(scroll[0])
        count = len(selected)
        self.element_note.configure(text='Only {} selected element(s) are outaged. {}'.format(count, self.editor.filter_note())
                                    if count else 'No selection: every element is outaged. ' + self.editor.filter_note())

    def on_element_select(self):
        visible = self.element_visible
        selected = [key for key in self.editor.selected_elements() if key not in visible]
        selected += [visible[index] for index in self.element_list.curselection()]
        self.select_elements(selected)

    def select_elements(self, keys):
        problem = self.editor.set_elements(keys)
        if problem:
            self.messagebox.showerror('Network scope', problem, parent=self.root)
        self.after_scope_change()

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
                selected = set()
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
        self.refresh_elements()


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
            self.editor.set_grids('contingency_grids', [])
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
                     contingencies=CONTINGENCIES_NOT_READ, kept=(), elements=()):
    """Show the case manager; the edited configuration on "Start calculation", None on Cancel."""
    try:
        import tkinter as tk
        import tkinter.font
        from tkinter import messagebox, simpledialog, ttk
        root = tk.Tk()
    except Exception as exc:
        raise CaseManagerUnavailable('The case manager cannot open a window: {}'.format(_friendly_exception(exc))) from None
    dialog = CaseManagerDialog(root, CaseEditor(records, config, period, qds_text, qds_info, grids, contingencies, kept, elements),
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


# ---------------------------------------------------------------------------
# QDS execution, kept results and state restoration
# ---------------------------------------------------------------------------


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
            PLANNED_OUTAGE_OPTION, _format_setting_value(original)), 5)
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
    """The kept copy of a calculated result object, in the study case, named for its case."""
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
            "PowerFactory could not copy the result object of {} after its run, so the run cannot be kept; the "
            "next run would overwrite it.".format(case_id),
            details=["Result object to copy: {}".format(object_key(template) if template is not None else "none"),
                     "Study case: {}".format(object_key(study_case))])
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


ASSESSED_VARIABLES = frozenset(variable for variables in VARIABLES.values() for variable in variables)


def monitor_definitions(elmres):
    """The variable selection of a result object: one (monitored object or class, variables) per IntMon."""
    found = []
    for monitor in _contents(elmres, '*.IntMon') if elmres is not None else []:
        target = safe_attr(monitor, 'obj_id')
        variables = safe_attr(monitor, 'vars')
        where = "{} ({})".format(object_name(target), class_name(target)) if target is not None else (
            str(safe_attr(monitor, 'classnm') or '') or object_name(monitor))
        found.append((where, ", ".join(str(item) for item in variables) if isinstance(variables, (list, tuple))
                      else "variables unreadable"))
    return found


def monitor_text(elmres, limit=6):
    found = monitor_definitions(elmres)
    if not found:
        return "no variable selection (no IntMon inside)"
    text = "; ".join("{}: {}".format(where, clip_text(variables, 80) or "none") for where, variables in found[:limit])
    return "{} variable set(s) (IntMon): {}{}".format(
        len(found), text, " and {} more".format(len(found) - limit) if len(found) > limit else "")


def recorded_variables(elmres):
    """{variable: columns} a result object holds, or None when it cannot be loaded."""
    try:
        elmres.Load()
        counted = {}
        for column in range(int(elmres.GetNumberOfColumns())):
            variable = str(elmres.GetVariable(column))
            counted[variable] = counted.get(variable, 0) + 1
        return counted
    except Exception:
        return None


def recorded_text(counted, limit=10):
    if counted is None:
        return "not readable (Load or GetVariable failed)"
    if not counted:
        return "no column"
    ordered = sorted(counted.items(), key=lambda entry: (entry[0] not in ASSESSED_VARIABLES, -entry[1], entry[0]))
    text = ", ".join("{} x{}".format(variable, number) for variable, number in ordered[:limit])
    return "{} column(s): {}{}".format(sum(counted.values()), text,
                                       " and {} more variable(s)".format(len(ordered) - limit) if len(ordered) > limit else "")


def check_recording(snapshot, produced, qds, case_id, logger):
    """Right after the first run: does its kept result object record what GridLens assesses? Else stop at once.

    `produced` is the result object PowerFactory wrote the run into and
    `snapshot` GridLens' copy of it. Without the assessed variables every
    further run would be wasted; the error names what both record and the
    variable selection of the QDS result object.
    """
    counted = recorded_variables(snapshot)
    assessed = {variable: number for variable, number in (counted or {}).items() if variable in ASSESSED_VARIABLES}
    logger.detail("Recorded in '{}': {}.".format(object_name(snapshot), recorded_text(counted)))
    release = getattr(snapshot, 'Release', None)
    if callable(release):
        try:
            release()
        except Exception:
            pass
    if assessed:
        return
    produced_counted = recorded_variables(produced) if produced is not None else None
    if any(variable in ASSESSED_VARIABLES for variable in produced_counted or {}):
        cause = ("PowerFactory's result object records the assessed variables, its copy does not: the copy lost them.")
        hint = "Send this report; the copy of a calculated result object is then not complete."
    else:
        cause = ("The variable selection of the quasi-dynamic simulation's result object contains none of the assessed "
                 "variables.")
        hint = ("Open ComStatsim > Result Variables and select c:loading for lines and transformers and m:u for "
                "terminals, then run GridLens again.")
    raise RecordingError(
        "{} was calculated, but its kept result object '{}' records none of the variables GridLens assesses ({}). "
        "Every further run would record the same, so GridLens stopped after the first run.".format(
            case_id, object_name(snapshot), ", ".join(sorted(ASSESSED_VARIABLES))),
        details=["Kept result object (copy made after the run): {} ({})".format(object_name(snapshot), object_key(snapshot)),
                 "Recorded in the kept result object: " + recorded_text(counted),
                 "Result object '{}' wrote the run into: {} ({})".format(object_name(qds), object_name(produced), object_key(produced)),
                 "Recorded there: " + recorded_text(produced_counted),
                 "Its variable selection: " + monitor_text(produced),
                 "Probable cause: " + cause],
        hint=hint)


def _calculate_qds(app, study_case, qds, case_id, name, original_result, logger, result_objects,
                   fingerprint='', announce=True):
    """Phase 1 for one run: the QDS as configured, then a kept copy of its result object. Returns the run.

    PowerFactory writes a QDS into its own result object of the study case
    (it creates one with its default variable selection when the bound object
    has none) and overwrites it with the next run. GridLens therefore keeps
    every run as a copy made right after it, named GridLens_<stamp>_<case>.
    Nothing is read here.
    """
    if announce:
        logger.case("Case {} \u00b7 {}".format(case_id, name))
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
    with RUN_STATS.measure("read switch states"):
        switches_before = switch_states(app)
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
    produced = safe_attr(qds, "results")
    if produced is None or class_name(produced) != "ElmRes":
        raise GridLensError(
            "{} was calculated, but ComStatsim.results names no result object afterwards.".format(case_id),
            details=["ComStatsim.results after the run: {}".format(
                "none" if produced is None else "{} ({})".format(object_name(produced), class_name(produced)))])
    logger.write(
        "CALCULATION", "{} completed successfully in {:.1f}s.".format(
            case_id, elapsed), 4)
    with RUN_STATS.measure("read switch states"):
        changed = switch_changes_text(switches_before, switch_states(app))
    if changed:
        logger.detail("Switches in another state after the QDS than before it ({}): {}. PowerFactory left them so; "
                      "GridLens does not change switches.".format(len(changed), clip_text(", ".join(changed), 400)),
                      "WARNING")
    elif switches_before:
        logger.detail("Switch states after the QDS: all {} switches as before it.".format(len(switches_before)))
    else:
        logger.detail("Switch states could not be read (no ElmCoup/StaSwitch with on_off).")
    with RUN_STATS.measure("keep a copy of each QDS result"):
        snapshot = _case_result_object(study_case, produced, case_id, result_objects.name_for(case_id))
    result_objects.append(snapshot, case_id)
    logger.detail("PowerFactory wrote {} into '{}'; kept as '{}' ({}).".format(
        case_id, object_name(produced), object_name(snapshot), monitor_text(snapshot)))
    mark_result_object(snapshot, case_id, fingerprint)
    if not RUN_CONTEXT.get('recording_checked'):
        RUN_CONTEXT['recording_checked'] = True
        check_recording(snapshot, produced, qds, case_id, logger)
    return {"id": case_id, "name": name, "snapshot": snapshot, "elapsed": elapsed,
            "result_object": object_name(snapshot)}


def mark_result_object(obj, case_id, fingerprint=''):
    """Write case and fingerprint into the description of a kept result object, for a later re-evaluation."""
    try:
        obj.desc = ["GridLens {}; case {}; fingerprint {}".format(PUBLISHER_VERSION, case_id, fingerprint or '-')]
    except Exception:
        pass


def result_fingerprint(obj):
    """The fingerprint mark_result_object() wrote, or None."""
    match = re.search(r'fingerprint (\S+)', object_description(obj))
    return match.group(1) if match and match.group(1) != '-' else None


def counts_text(counted, limit=8):
    ordered = sorted(counted.items(), key=lambda entry: (-entry[1], entry[0]))
    return ", ".join("{} {}".format(name, number) for name, number in ordered[:limit]) + (
        " and {} more".format(len(ordered) - limit) if len(ordered) > limit else "") or "none"


def result_object_text(elmres, counters, labels, plot_times):
    """What a QDS result object holds: time steps, period, step, columns by class and by variable."""
    step = (plot_times[1] - plot_times[0]) if len(plot_times) > 1 else 0.0
    return ("Result object '{}': {} time step(s) from {} to {} (step {:g} h, span {:g} h); {} column(s) by class: {}; "
            "by variable: {}.".format(object_name(elmres), len(labels), labels[0], labels[-1], step,
                                      plot_times[-1] - plot_times[0], counters.get('columns', 0),
                                      counts_text(counters.get('columns_by_class') or {}),
                                      counts_text(counters.get('columns_by_variable') or {})))


def outage_component_lines(result, reference, plan):
    """Per outage and recorded component: time steps without load inside and outside its window, case and REF."""
    lines = []
    hours = result.get('hours') or []
    case_items, ref_items = result.get('item_by_key') or {}, (reference or {}).get('item_by_key') or {}
    for record in plan['members']:
        window = plan['windows'][record['key']]
        inside = set(window_rows(hours, [window])) if result.get('absolute') and window != (None, None) else set()
        recorded = False
        for key, item in sorted(case_items.items()):
            if key[0] == 'voltage' or key[1] not in set(record.get('component_keys') or ()) or 'values' not in item:
                continue
            recorded = True
            values = item['values']
            off = [row for row in range(len(values)) if abs(values[row] or 0.0) <= OFF_LOADING]
            ref_values = (ref_items.get(key) or {}).get('values')
            ref_off = sum(1 for value in ref_values if abs(value or 0.0) <= OFF_LOADING) if ref_values else None
            lines.append("Outage '{}', component '{}' ({}, {}): without load in {} of {} step(s) inside its window and "
                         "in {} of {} outside it; REF: {}.".format(
                             record['name'], item['element_name'], class_name(item['object']), item['variable_id'],
                             sum(1 for row in off if row in inside), len(inside),
                             sum(1 for row in off if row not in inside), len(values) - len(inside),
                             "without load in {} of {} step(s)".format(ref_off, len(ref_values))
                             if ref_values else "not recorded"))
        if not recorded:
            lines.append("Outage '{}': none of its {} component(s) is recorded as loading in the result object.".format(
                record['name'], len(record.get('component_keys') or ())))
    return lines


def evaluate_qds(run, description, plan, logger):
    """Phase 2 for one run: read and validate its kept ElmRes into a case result."""
    case_id, name, snapshot, elapsed = run["id"], run["name"], run["snapshot"], run.get("elapsed", 0.0)
    logger.write("EXTRACTION", "Reading and validating {} results from '{}'.".format(case_id, object_name(snapshot)), 6)
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
                                   counters.get('out_of_scope', 0)), 6)
        logger.write(
            "EXTRACTION",
            "Validated {} supported series across {} time point(s); time unit '{}'."
            .format(len(series), len(labels), unit), 6)
        logger.write(
            "EXTRACTION",
            "Time axis: {} scale, unit '{}'; first {}; last {}; span {}."
            .format("absolute" if absolute else "relative",
                    unit, labels[0], labels[-1],
                    '{:g} h'.format(plot_times[-1] - plot_times[0])), 6)
        logger.detail(result_object_text(snapshot, counters, labels, plot_times))
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
        "message": "Completed in {:.1f}s.".format(elapsed) if elapsed else "Evaluated from the kept result object.",
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
        logger.write("RESULTS", "Kept result object '{}' in the study case.".format(object_name(obj)), 5)
        RUN_CONTEXT.setdefault('kept', []).append(object_name(obj))


def _log_results_binding(qds, original_result, logger):
    """GridLens does not bind ComStatsim.results. PowerFactory may bind its own result object during a QDS (in place
    of a temporary one without variable selection), as a run by hand does; that binding is left as it is."""
    now = safe_attr(qds, "results")
    if not _same_object(now, original_result):
        logger.write("RESTORE", "PowerFactory bound its own result object '{}' to ComStatsim.results during the QDS "
                     "(before: '{}'), as a run by hand does; left as it is.".format(
                         object_name(now), object_name(original_result)), 5)


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


def _restore_study_time(state, logger, stage="RESTORE", step=5):
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
                "SETTINGS", "{} [{}] = {}".format(
                    attribute_label(qds, attribute) or "Planned outages", attribute,
                    _format_setting_value(value)), 2)
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


def applied_text(command, records, option=PLANNED_OUTAGE_OPTION):
    """What PowerFactory will apply, read back from the objects: the option and every outage not Ignored."""
    found, value = _read_setting(command, option)
    if found and finite_number(value) == 0.0:
        applied = 'none, the option is off'
    else:
        applied = ', '.join(record['name'] for record in records
                            if finite_number(safe_attr(record['_object'], 'outserv', 1)) == 0.0) or 'none'
    return "Read back before the calculation: 'Planned outages' [{}] = {}; planned outages applied: {}.".format(
        option, _format_setting_value(value) if found else 'unreadable', applied)


def _active_text(plan, background):
    names = [record["name"] for record in plan["members"]] if plan else []
    text = "active: " + (", ".join(names) or "none")
    if background:
        text += "; fixed: " + ", ".join(record["name"] for record in background)
    return text + "; every other planned outage Ignored"


def _calculate_reference(app, study_case, qds, request, records, original_result, logger,
                         result_objects, study_time_state):
    """Phase 1 for REF: R0 without planned outages, or Rfix with exactly the fixed outages."""
    background = request["background"]
    name = REFERENCE_NAME if not background else "Reference (fixed outages)"
    if not background:
        if not _set_scalar_attribute(qds, PLANNED_OUTAGE_OPTION, 0):
            raise GridLensError(
                "The 'Planned Outages' option [{}] could not be switched off, so a reference free of planned "
                "outages could not be guaranteed. No calculation was started.".format(PLANNED_OUTAGE_OPTION))
        result = _calculate_qds(app, study_case, qds, REFERENCE_CASE_ID, name, original_result, logger, result_objects,
                                reference_fingerprint(request))
        result.update(description="Network state without planned outages.", run_note="iopt_maint=0: no planned outage applied")
    else:
        if not _set_scalar_attribute(qds, PLANNED_OUTAGE_OPTION, 1):
            raise GridLensError("The 'Planned Outages' option [{}] could not be switched on for the reference with "
                                "fixed outages. No calculation was started.".format(PLANNED_OUTAGE_OPTION))
        logger.case("Case {} · {}".format(REFERENCE_CASE_ID, name))
        logger.detail("Fixed outages active in the reference and in every case: {}".format(
            ", ".join(record["name"] for record in background)))
        with StateGuard() as guard:
            _isolate_outages(guard, {record["key"] for record in background}, records, "the reference")
            logger.detail(applied_text(qds, records))
            result = _calculate_qds(app, study_case, qds, REFERENCE_CASE_ID, name, original_result, logger,
                                    result_objects, reference_fingerprint(request), announce=False)
        result.update(description="Network state with the fixed planned outages.",
                      run_note="iopt_maint=1; " + _active_text(None, background))
    clock_errors = _restore_study_time(study_time_state, logger, "CALCULATION", 4)
    if clock_errors:
        raise GridLensError("The initial Study Case time could not be restored after REF: {}. The case runs were "
                            "not started.".format("; ".join(clock_errors)))
    return result


def reference_fingerprint(request):
    """What decides REF: the fixed background outages."""
    return hashlib.sha1("|".join(sorted(record["key"] for record in request["background"])).encode("utf-8")).hexdigest()[:12]


def _case_info(plan):
    return {"id": plan["id"], "name": plan["name"], "kind": "planning_case", "plan": plan,
            "description": plan.get("description") or "Planned outages: {}.".format(
                ", ".join(record["name"] for record in plan["members"]))}


def _calculate_case(app, study_case, qds, plan, request, records, original_result, logger, result_objects,
                    study_time_state):
    """Phase 1 for one planning case with all its outages: the run, or a failed run with its reason.

    A state that cannot be restored stops the whole run.
    """
    background = request["background"]
    info = _case_info(plan)
    logger.case("Case {} · {}".format(plan["id"], plan["name"]))
    logger.detail("Outages: {}".format("; ".join("{} ({})".format(
        record["name"], period_text(*(_format_pf_time(value) for value in plan["windows"][record["key"]])) or "unknown window")
        for record in plan["members"])))
    if plan.get("states"):
        logger.detail("Network states: {}".format(clip_text(states_text(plan), 300)))
    active = {record["key"] for record in plan["members"]} | {record["key"] for record in background}
    note = "iopt_maint=1; " + _active_text(plan, background)
    try:
        with StateGuard() as guard:
            _isolate_outages(guard, active, records, "case " + plan["id"])
            _apply_overrides(guard, plan)
            logger.detail(applied_text(qds, records))
            run = _calculate_qds(app, study_case, qds, plan["id"], plan["name"], original_result, logger,
                                 result_objects, plan["fingerprint"], announce=False)
        run.update(info, run_note=note)
    except (StateRestoreError, RecordingError):
        raise
    except GridLensError as exc:
        logger.write("CALCULATION", "{} could not be calculated: {}".format(plan["id"], exc), 4, "ERROR")
        log_error_details(logger, exc)
        run = dict(info, failed=str(exc), run_note=note, result_object=result_objects.by_case.get(plan["id"], ""))
    clock_errors = _restore_study_time(study_time_state, logger, "CALCULATION", 4)
    if clock_errors:
        raise GridLensError(
            "The initial Study Case time could not be restored after {}: {}. "
            "The next case was not started.".format(plan["id"], "; ".join(clock_errors)))
    return run


def evaluate_case(run, reference, logger):
    """Phase 2 for one planning case: read its kept ElmRes and compare it with REF; a failure becomes a failed case."""
    plan = run["plan"]
    info = _case_info(plan)
    logger.case("Evaluation · Case {} · {}".format(plan["id"], plan["name"]))
    if run.get("failed"):
        result = failed_case(info, run["failed"])
        result.update(result_object=run.get("result_object", ""), run_note=run.get("run_note", ""))
        return result
    try:
        result = evaluate_qds(run, info["description"], plan, logger)
        result["run_note"] = run.get("run_note", "")
        try:
            result["outage_checks"] = outage_effects(result, reference, plan)
        except Exception as exc:
            result["outage_checks"] = [(record["name"], OUTAGE_UNCHECKED, "check failed: " + _friendly_exception(exc))
                                       for record in plan["members"]]
        for name, status, reason in result["outage_checks"]:
            logger.detail("Outage '{}': {} - {}.".format(name, status, reason),
                          "WARNING" if status == OUTAGE_NO_EFFECT else "INFO")
        try:
            for line in outage_component_lines(result, reference, plan):
                logger.detail(line)
        except Exception as exc:
            logger.detail("The components of the outages could not be listed: {}.".format(_friendly_exception(exc)),
                          "WARNING")
        try:
            result["outage_persistence"] = outage_persistence(result, reference, plan)
        except Exception as exc:
            result["outage_persistence"] = []
            logger.detail("Whether the outages stay in effect after their windows could not be checked: {}.".format(
                _friendly_exception(exc)), "WARNING")
        for name, stretch, total, until, back in result["outage_persistence"]:
            if stretch:
                logger.detail(
                    "Outage '{}' stays in effect after its window: its components carry no load for {:g} h from the "
                    "window end (until {}), while REF carries load; {}. The switching state of the outage persists "
                    "after its window in the QDS.".format(
                        name, stretch, until, "back in service at " + back if back else
                        "not back in service until the end of the period"), "WARNING")
            else:
                logger.detail("Outage '{}': back in service right at its window end{}.".format(
                    name, "" if not total else " ({:g} h later without load again)".format(total)))
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
        return result
    except GridLensError as exc:
        logger.write("EXTRACTION", "{} could not be evaluated: {}".format(plan["id"], exc), 6, "ERROR")
        result = failed_case(info, str(exc))
        result.update(result_object=run.get("result_object", ""), run_note=run.get("run_note", ""))
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


# ---------------------------------------------------------------------------
# Native contingency calculation and evaluation
# ---------------------------------------------------------------------------


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
    chosen = set(current_setting('contingency_elements'))
    elements = [element for element in contingency_candidates(app, grids) if not chosen or object_key(element) in chosen]
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


N1_SWEEP_ATTRIBUTES = ('iEnableTS', 'calcPeriod', 'startTime', 'endTime', 'stepSize', 'stepUnit', 'stepNumber',
                       N1_TIMES_ATTRIBUTE, N1_IGNORE_ATTRIBUTE, N1_PLANNED_OPTION)


def times_text(moments, limit=12):
    labels = [_format_pf_time(moment) for moment in sorted(moments)]
    return "{} ({}){}".format(", ".join(labels[:limit]) or "none", len(labels),
                              " and {} more".format(len(labels) - limit) if len(labels) > limit else "")


def sweep_settings_text(command):
    """The time-sweep settings of the contingency analysis as PowerFactory holds them now."""
    parts = []
    for attribute in N1_SWEEP_ATTRIBUTES:
        found, value = _read_setting(command, attribute)
        if not found:
            parts.append(attribute + " unreadable")
        elif attribute in ('startTime', 'endTime'):
            parts.append("{} = {}".format(attribute, _format_pf_time(value)))
        elif attribute == N1_TIMES_ATTRIBUTE and isinstance(value, (list, tuple)):
            parts.append("{} = {}".format(attribute, times_text(value)))
        else:
            parts.append("{} = {}".format(attribute, clip_text(_format_setting_value(value), 80)))
    return "; ".join(parts)


def step_setting(step):
    """(stepSize, stepUnit) of a step in seconds, in the largest unit that divides it."""
    for unit in sorted(STEP_UNIT_SECONDS, key=lambda key: -STEP_UNIT_SECONDS[key]):
        size = step / STEP_UNIT_SECONDS[unit]
        if size >= 1 and abs(size - round(size)) < 1e-9:
            return int(round(size)), unit
    return int(round(step)), 0


def sweep_period(times, step, limit=None):
    """Every QDS step from the first to the last study time: what one sweep over a period calculates.

    Outage windows that lie apart make the period longer than the windows;
    the steps outside them are calculated but not assessed.
    """
    limit = setting_value('max_n1_times') if limit is None else limit
    first, last = min(times), max(times)
    count = int(round((last - first) / step)) + 1
    if count > limit:
        raise GridLensError(
            "The n-1 time sweep from the first to the last study time of the outage windows covers {} QDS steps, more "
            "than {}; every one calculates every contingency.".format(count, limit),
            details=["Study times inside the windows: " + times_text(times)],
            hint="Split the case into cases whose outage windows lie close together, or raise 'max n-1 study times' "
                 "in Settings.")
    return [first + index * step for index in range(count)]


def calculated_times(command):
    """The study times of the sub-results the last sweep wrote (cnttime), without loading them."""
    result = safe_attr(command, N1_RESULT_ATTRIBUTE)
    return sorted(moment for moment in (finite_number(safe_attr(sub, 'cnttime'))
                                        for sub in _contents(result, '*.ElmRes') if class_name(sub) == 'ElmRes')
                  if moment is not None) if result is not None else []


def _missing_times(wanted, found, tolerance=1.0):
    return [moment for moment in wanted if not any(abs(moment - other) <= tolerance for other in found)]


def _same_times(found, wanted, tolerance=1.0):
    return len(found) == len(wanted) and all(abs(a - b) <= tolerance for a, b in zip(sorted(found), sorted(wanted)))


def run_n1_sweep(command, times, step, active_keys, records, excluded, label, keep=None):
    """Phase 1: one contingency analysis over the period of `times` with exactly `active_keys` applied.

    `times` are the QDS steps inside the outage windows, `step` the QDS step in
    seconds. Written temporarily and restored verified (StateGuard): the time
    sweep as a period (calcPeriod, step, startTime, endTime, stepNumber),
    isPlannedOutages (0 without any active outage, else 1),
    the 'Ignored' flag of every planned outage, and 'Not analysed' of the
    contingencies outside the contingency grids. With `keep` = (study case,
    name, mark) the result object is kept as a copy for phase 2; without it,
    or when the copy fails, the results are read at once, before restoring.
    A failed calculation raises GridLensError.
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
        period = sweep_period(times, step)
        size, unit = step_setting(step)
        for attribute, value in ((N1_PERIOD_ATTRIBUTE, N1_PERIOD_MODE), ('stepUnit', unit), ('stepSize', size),
                                 ('startTime', int(round(period[0]))), ('endTime', int(round(period[-1] + step)))):
            if not guard.set(command, attribute, value, "time sweep [{}] of the contingency analysis".format(attribute)):
                found, current = _read_setting(command, attribute)
                raise GridLensError(
                    "The time sweep of the contingency analysis could not be set for {}: [{}] did not take the "
                    "value.".format(label, attribute),
                    details=["Wanted: {} = {}".format(attribute, _format_pf_time(value) if attribute.endswith('Time')
                                                      else value),
                             "Read back: {}".format(_format_setting_value(current) if found else 'unreadable'),
                             "Time-sweep settings now: " + sweep_settings_text(command)])
        if _read_setting(command, 'stepNumber')[0]:
            # Derived by PowerFactory in some versions; written where it is not, so both agree on the period.
            guard.set(command, 'stepNumber', len(period), "time sweep [stepNumber] of the contingency analysis")
        applied = applied_text(command, records, N1_PLANNED_OPTION)
        settings = sweep_settings_text(command)
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
            raise GridLensError("The contingency analysis for {} ended with error code {}.".format(label, code),
                                details=["Settings before the run: " + settings, applied],
                                hint="Read the PowerFactory messages of the contingency analysis just above.")
        calculated = calculated_times(command)
        missing = _missing_times(times, calculated)
        if missing:
            raise GridLensError(
                "The contingency analysis for {} did not calculate {} of the {} study times inside the outage windows, "
                "so its results cannot be placed in the windows.".format(label, len(missing), len(times)),
                details=["Wanted (QDS steps inside the outage windows): " + times_text(times),
                         "Missing: " + times_text(missing),
                         "Written period: {} to {} (exclusive), {} step(s)".format(
                             _format_pf_time(period[0]), _format_pf_time(period[-1] + step), len(period)),
                         "Calculated by PowerFactory (cnttime of the sub-results): " + times_text(calculated),
                         "Time-sweep settings read back before the run: " + settings,
                         "Time-sweep settings now: " + sweep_settings_text(command)],
                hint="Compare the lists: the time sweep of '{}' follows another time definition than calcPeriod {} "
                     "(startTime to endTime). Send this report.".format(object_name(command), N1_PERIOD_MODE))
        limits = _recording_limits(command)
        kept = None
        if keep is not None:
            study_case, name, mark = keep
            kept = keep_copy(study_case, safe_attr(command, N1_RESULT_ATTRIBUTE), name,
                             mark + recording_text(limits) + '; ' + n1_filter_text())
        if kept is not None:
            found = {'kept': kept, 'recording_limits': limits}
        else:
            with RUN_STATS.measure("read n-1 results"):
                found = read_n1_results(command)
    return dict(found, written_times=period, window_times=list(times), applied=applied, settings=settings,
                calculated_times=calculated)


def keep_copy(study_case, obj, name, mark):
    """A copy of `obj` named `name` in the study case, kept after the run; None when PowerFactory refuses it."""
    if obj is None:
        return None
    try:
        copies = _as_objects(study_case.AddCopy(obj))
        copy = copies[0] if copies else None
    except Exception:
        copy = None
    if copy is None:
        return None
    try:
        copy.loc_name = name
    except Exception:
        pass
    try:
        copy.desc = [mark]
    except Exception:
        pass
    return copy


def recording_text(limits):
    values = [value for quantity in ('loading', 'voltage') for value in (limits.get(quantity) or ())]
    return '; recording ' + ','.join('{:g}'.format(value) for value in values) if len(values) == 3 else ''


def recording_limits_of(obj):
    """The recording limits a kept n-1 copy names in its description, {} when it names none."""
    match = re.search(r'recording ([0-9.eE+-]+),([0-9.eE+-]+),([0-9.eE+-]+)', object_description(obj))
    if not match:
        return {}
    loading, low, high = (float(value) for value in match.groups())
    return {'loading': (loading,), 'voltage': (low, high)}


def n1_filter_of(obj):
    """The n-1 filter a kept n-1 result was calculated with, from its description; '' when it carries none."""
    match = re.search(r'(n-1 filter: .*)$', object_description(obj))
    return match.group(1) if match else ''


def drop_contingencies(data, keys):
    """The n-1 data without the contingencies `keys`; (data, names of those actually dropped)."""
    present = {key[0] for values in data['times'].values() for key in values}
    dropped = sorted(data['contingencies'].get(key, key) for key in present & set(keys))
    if not dropped:
        return data, []
    times = {moment: {key: value for key, value in values.items() if key[0] not in keys}
             for moment, values in data['times'].items()}
    present = {moment: set(found) - set(keys) for moment, found in (data.get('present') or {}).items()}
    return dict(data, times=times, present=present), dropped


def load_n1(found):
    """Phase 2: the n-1 results of a sweep, read from its kept copy (or as read at once); checks the study times."""
    if 'times' in found:
        data = found
    else:
        with RUN_STATS.measure("read n-1 results"):
            data = read_n1_results(found['kept'], recording_limits=found.get('recording_limits'))
    data = dict(data, calculated_count=len(data['times']))
    wanted = found.get('window_times')
    if wanted is not None:
        missing = _missing_times(wanted, list(data['times']))
        if missing:
            raise GridLensError("the n-1 result lacks {} of the {} study times inside the outage windows".format(
                len(missing), len(wanted)), details=["Missing: " + times_text(missing),
                                                     "Held: " + times_text(data['times'])])
        # The steps between windows that lie apart were calculated with the period; only the windows are assessed.
        data = dict(data, times={moment: values for moment, values in data['times'].items()
                                 if not _missing_times([moment], wanted)})
    if not data['times']:
        raise GridLensError("the kept n-1 result holds no study time")
    RUN_STATS.count("n1_times", len(data['times']))
    RUN_STATS.count("n1_loadflows", len({(moment, key[0]) for moment, values in data['times'].items() for key in values}))
    return data


def n1_data_text(kind, found, data, qds_steps=None, reference=None):
    """What a kept n-1 result holds: study times, contingencies x equipment per time, values and code 3."""
    kept = found.get('kept')
    per_time = []
    for moment in sorted(data['times']):
        values = data['times'][moment]
        per_time.append("{} {} x {}".format(_format_pf_time(moment), len({key[0] for key in values}),
                                            len({key[1] for key in values})))
    cells = [value for values in data['times'].values() for value in values.values()]
    text = ("{} result '{}': {} study time(s) assessed ({} calculated{}); contingencies x equipment with a value per "
            "study time: {}; {} value(s), {} inside the recording limits (code 3).".format(
                kind, object_name(kept) if kept is not None else 'read at once', len(data['times']),
                data.get('calculated_count', len(data['times'])),
                ", of {} QDS steps in the period; the others are not calculated".format(qds_steps) if qds_steps else "",
                clip_text("; ".join(per_time), 300) or "none", len(cells), sum(1 for value in cells if value is None)))
    if reference is not None:
        mine = {key[0] for values in data['times'].values() for key in values}
        theirs = {key[0] for values in reference['times'].values() for key in values}
        missing = sorted(reference['contingencies'].get(key, key) for key in theirs - mine)
        text += " Contingencies of n-1 missing here: {}.".format(
            clip_text(", ".join(missing), 200) + " (their equipment is switched off by the case)" if missing else "none")
    return text


def _n1_reference_text(comparison):
    """Elements with a violation in the n-1 reference (PRE_EXISTING when compared with itself)."""
    violated = sum(1 for entry in comparison['elements'].values() if entry['worst']['status'] == 'PRE_EXISTING')
    return '{} element(s) with a post-fault violation'.format(violated)


def calculate_n1_case(command, plan, request, records, grid, excluded, prime, references, keep=None, label=None):
    """Phase 1 for one planning case: n-1 (fixed outages only) and, when `prime`, (n-1)' (with the case's outages).

    Both use the QDS steps inside the case's outage windows. `references`
    caches the n-1 sweep per set of study times, so cases with the same times
    share one reference calculation. `keep` = (study case, name prefix, stamp
    text) keeps every result as a copy named <prefix>_N1 and <prefix>_N1P.
    """
    label = label or 'case ' + plan['id']
    times = n1_study_times([plan['windows'][record['key']] for record in plan['members']], grid)
    if not times:
        return {'status': 'NOT EVALUATED', 'reason': 'no QDS time step lies inside the outage windows', 'times': 0}
    mark = 'GridLens {}; case {} {{}}; fingerprint {}'.format(PUBLISHER_VERSION, plan['id'], plan['fingerprint'])
    background = {record['key'] for record in request['background']}
    key = tuple(times)
    reference = references.get(key)
    if reference is None:
        reference = references[key] = run_n1_sweep(
            command, times, grid[2], background, records, excluded, 'the n-1 reference of ' + label,
            (keep[0], keep[1] + '_N1', mark.format('n-1')) if keep else None)
    elif keep and reference.get('kept') is not None:
        copied = keep_copy(keep[0], reference['kept'], keep[1] + '_N1', mark.format('n-1') + recording_text(
            reference.get('recording_limits') or {}) + '; ' + n1_filter_text())
        reference = dict(reference, kept=copied) if copied is not None else reference
    entry = {'status': 'CALCULATED', 'times': len(times), 'reference': reference, 'scenario': None,
             'kind': N1_PRIME if prime else N1_REFERENCE,
             'qds_steps': int(round((grid[1] - grid[0]) / grid[2])) if grid[1] is not None else None}
    if prime:
        active = background | {record['key'] for record in plan['members']}
        entry['scenario'] = run_n1_sweep(
            command, times, grid[2], active, records, excluded, "the (n-1)' scenario of " + label,
            (keep[0], keep[1] + '_N1P', mark.format("(n-1)'")) if keep else None)
    return entry


def evaluate_n1_case(entry, plan, elements_of, run_id=''):
    """Phase 2 for one planning case: read the kept n-1 results and classify (n-1)' against n-1.

    Besides the comparison used by logs and model quality, the entry carries the
    statistics of the reporting core: 'statistics' (compare_scenario of the
    case, or of n-1 with itself when only n-1 was calculated) and
    'reference_statistics' (level_statistics of the n-1 reference), both over
    the study times inside the case's outage windows.
    """
    if entry.get('status') != 'CALCULATED':
        return entry
    reference, dropped = drop_contingencies(load_n1(entry['reference']), entry.get('filtered_out') or {})
    notes = []
    if entry.get('calculated_with'):
        notes.append("Kept n-1 result calculated with the {}; now: the {}.".format(
            entry['calculated_with'][len('n-1 filter: '):] if entry['calculated_with'].startswith('n-1 filter: ')
            else entry['calculated_with'], n1_filter_text()))
    if dropped:
        notes.append("Left out of the evaluation by the current n-1 filters: {} contingenc{} ({}). Contingencies that "
                     "were 'Not analysed' at the calculation can only be added by calculating again.".format(
                         len(dropped), 'y' if len(dropped) == 1 else 'ies', clip_text(', '.join(dropped), 300)))
    result = {'status': 'EVALUATED', 'times': len(reference['times']), 'contingencies': len(reference['contingencies']),
              'kind': entry['kind'],
              'details': notes + [n1_data_text(N1_REFERENCE, entry['reference'], reference, entry.get('qds_steps'))]}
    requested = sorted(entry['reference'].get('window_times') or reference['times'])
    reference_source = LoadedSweep(reference)
    with RUN_STATS.measure("n-1 statistics"):
        result['reference_statistics'] = level_statistics(run_id, N1_REFERENCE, reference_source, requested)
    result['requested_times'] = requested
    result['result_objects'] = [(N1_REFERENCE, entry['reference'].get('kept'))]
    if entry['kind'] != N1_PRIME or entry.get('scenario') is None:
        result.update(kind=N1_REFERENCE, comparison=compare_n1(reference, reference))
        result['summary'] = 'n-1 reference: ' + _n1_reference_text(result['comparison'])
        with RUN_STATS.measure("n-1 statistics"):
            result['statistics'] = dict(compare_scenario(run_id, plan['id'], reference_source, reference_source, requested,
                                                         contingency_elements=elements_of), level=N1_REFERENCE)
        return result
    scenario, _ = drop_contingencies(load_n1(entry['scenario']), entry.get('filtered_out') or {})
    result['details'].append(n1_data_text(N1_PRIME, entry['scenario'], scenario, entry.get('qds_steps'), reference))
    switched_off = {component for record in plan['members'] for component in record.get('component_keys') or ()}
    with RUN_STATS.measure("classify (n-1)' against n-1"):
        result['comparison'] = compare_n1(reference, scenario, switched_off, elements_of)
    RUN_STATS.count("n1_classified", sum(result['comparison']['counts'].values()))
    result['summary'] = "(n-1)' against n-1: " + n1_summary(result['comparison'])
    result['result_objects'].append((N1_PRIME, entry['scenario'].get('kept')))
    with RUN_STATS.measure("n-1 statistics"):
        result['statistics'] = compare_scenario(run_id, plan['id'], reference_source, LoadedSweep(scenario), requested,
                                                switched_off, elements_of)
    return result


def run_n1_case(command, plan, request, records, grid, excluded, elements_of, prime, references, label=None):
    """Both phases at once for one case (no kept copies): used where nothing has to be kept."""
    return evaluate_n1_case(calculate_n1_case(command, plan, request, records, grid, excluded, prime, references,
                                              label=label), plan, elements_of)


# ---------------------------------------------------------------------------
# Network scope, calculation requests and run logging
# ---------------------------------------------------------------------------


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
        found.append({
            'name': object_name(outage),
            'number': safe_attr(outage, 'number'),
            'analysed': safe_attr(outage, 'outserv', 0) in (0, False),
            'elements': [object_name(element) for element in elements],
            'element_items': [(object_key(element), object_name(element), class_name(element),
                                         element_grid_name(element)) for element in elements],
            'grids': sorted({element_grid_name(element) or '(no grid)' for element in elements}, key=str.casefold),
        })
    return {'command': object_name(command), 'contingencies': found}


def contingency_element_choices(app, info):
    """[(key, name, class, grid)] the n-1 element filter offers: the equipment of the contingencies of the study
    case, else the elements GridLens would define contingencies for; sorted by name."""
    found = {}
    if isinstance(info, dict):
        for contingency in info.get('contingencies') or ():
            for item in contingency.get('element_items') or ():
                found.setdefault(item[0], tuple(item))
    elif app is not None:
        for element in contingency_candidates(app, ()):
            found.setdefault(object_key(element), (object_key(element), object_name(element), class_name(element),
                                                  element_grid_name(element)))
    return sorted(found.values(), key=lambda item: (item[1].casefold(), item[0]))


def contingency_scope(info, contingency_grids, monitoring_grids=()):
    """Which contingencies the grid selection keeps. None or empty for the contingency grids means every grid.

    A contingency is in scope when all of its equipment lies in the selected
    grids, partly in scope when only some does, outside when none does; with
    no grid selected every contingency is in scope. The n-1 run sets the contingencies outside to 'Not analysed'.
    """
    grids = tuple(contingency_grids or ())
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
                        contingencies=CONTINGENCIES_NOT_READ, kept=(), elements=()):
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
                                  contingencies=contingencies, kept=kept, elements=elements)
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
    config = dict(config)
    stamp = config.pop("evaluate_stamp", None)
    request = resolve_request(config, records, period, "gui", "case manager, configuration revision {}{}".format(
        config.get("revision") or 0, " with unsaved changes" if unsaved else ""))
    request["evaluate_stamp"] = stamp
    return request


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
    """The grids whose contingencies are analysed (empty: every grid). Independent of the report filter."""
    return tuple(current_setting('contingency_grids') or ())


def element_label(key):
    """The short name of an element key: the last part of its full name, without the class."""
    return key.split('\\')[-1].rsplit('.', 1)[0] if key else key


def excluded_contingencies(equipment, grids=None, elements=None):
    """{contingency key: reason} of the contingencies the n-1 filters leave out.

    `equipment` is [(ComOutage, [element])]. A contingency is left out when
    none of its equipment lies in the selected grids (no grid selected: every
    grid) or, with elements selected, when it outages none of them.
    Contingencies without readable equipment stay in.
    """
    grids = contingency_grid_selection() if grids is None else tuple(grids)
    elements = set(current_setting('contingency_elements') if elements is None else elements)
    found = {}
    for outage, items in equipment:
        if not items:
            continue
        if elements and not any(object_key(item) in elements for item in items):
            found[object_key(outage)] = 'outages no selected element'
        elif grids and not any(element_grid_name(item) in grids for item in items):
            found[object_key(outage)] = 'outside the n-1 grids'
    return found


def n1_filter_text():
    """The n-1 filters of the current settings, for log, report and the kept result objects."""
    grids, elements = contingency_grid_selection(), current_setting('contingency_elements')
    return "n-1 filter: grids {}; outaged elements: {}".format(
        ', '.join(grids) if grids else 'every grid', ', '.join(element_label(key) for key in elements) or 'every element')


def _n1_command(app, study_case, grid, logger):
    """(contingency analysis, reason): the one of the study case, else one GridLens defines and keeps."""
    command = contingency_analysis(study_case)
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
            return None, str(exc)
    if command is None:
        return None, 'the active study case holds more than one contingency analysis (ComSimoutage)'
    if grid is None:
        return None, 'the ComStatsim time step is not readable'
    return command, None


def _equipment_map(commands):
    """Contingency key -> keys of its equipment, over every given contingency analysis."""
    found = {}
    for command in commands:
        for outage, elements in contingency_equipment(command):
            found[object_key(outage)] = {object_key(element) for element in elements}
    return found


# ---------------------------------------------------------------------------
# Calculation and evaluation orchestration
# ---------------------------------------------------------------------------


def calculate_n1(app, study_case, qds, request, records, ready, logger, study_time_state, result_objects):
    """Phase 1 of n-1 and, if requested, (n-1)' for every ready planning case: {case id: entry}.

    Every sweep is kept as a copy (GridLens_<stamp>_<case>_N1 and _N1P) and
    read in phase 2. A case that cannot be calculated gets status NOT
    EVALUATED with the reason and the others continue; a state that cannot be
    restored stops the run. Cases with the same outages and windows share one
    calculation.
    """
    prime = N1_PRIME in (request.get('assessments') or ())
    grid = qds_grid(qds)
    command, reason = _n1_command(app, study_case, grid, logger)
    if reason:
        logger.write("CALCULATION", "n-1 is not evaluated: {}.".format(reason), 4, "WARNING")
        return {plan['id']: {'status': 'NOT EVALUATED', 'reason': reason, 'times': 0} for plan in ready}
    equipment = contingency_equipment(command)
    filtered = excluded_contingencies(equipment)
    excluded = [outage for outage, _ in equipment
                if object_key(outage) in filtered and safe_attr(outage, 'outserv', 0) in (0, False)]
    elements_of = {object_key(outage): {object_key(element) for element in elements} for outage, elements in equipment}
    logger.write("CALCULATION", "{} with contingency analysis '{}': {} contingencies, {} set to 'Not analysed' for the "
                 "run by the {}.".format(N1_PRIME + " against n-1" if prime else N1_REFERENCE, object_name(command),
                                         len(equipment), len(excluded), n1_filter_text()), 4)
    if excluded:
        logger.detail("Not analysed for the run: {}.".format(clip_text(", ".join(
            "{} ({})".format(object_name(outage), filtered[object_key(outage)]) for outage in excluded), 600)))
    entries, references, done = {}, {}, {}
    for plan in ready:
        if plan['fingerprint'] in done:
            entries[plan['id']] = done[plan['fingerprint']]
            continue
        logger.case("n-1 · Case {} · {}".format(plan['id'], plan['name']))
        started = time.monotonic()
        try:
            entry = calculate_n1_case(command, plan, request, records, grid, excluded, prime, references,
                                      (study_case, result_objects.name_for(plan['id'])))
        except StateRestoreError:
            raise
        except GridLensError as exc:
            entry = {'status': 'NOT EVALUATED', 'reason': str(exc), 'times': 0, 'error': exc}
        clock_errors = _restore_study_time(study_time_state, logger, "CALCULATION", 4)
        if clock_errors:
            raise GridLensError("The initial Study Case time could not be restored after the n-1 run of {}: {}.".format(
                plan['id'], "; ".join(clock_errors)))
        if entry['status'] == 'CALCULATED':
            entry['elements_of'] = elements_of
            entry['filtered_out'] = dict(filtered)
            for kind, sweep in ((N1_REFERENCE, entry['reference']), (N1_PRIME, entry['scenario'])):
                if sweep and sweep.get('applied'):
                    logger.detail("{}: {}".format(kind, sweep['applied']))
                    logger.detail("{}: time sweep read back before the run: {}".format(kind, sweep.get('settings', '-')))
                    logger.detail("{}: study times calculated: {}".format(kind, times_text(sweep.get('calculated_times') or ())))
            logger.detail("Calculated at {} study time(s) in {:.1f}s.".format(entry['times'], time.monotonic() - started))
        else:
            logger.detail("n-1 not evaluated: {}".format(entry['reason']), "WARNING")
            log_error_details(logger, entry.pop('error', None), "WARNING")
        entries[plan['id']] = done[plan['fingerprint']] = entry
    return entries


def evaluate_n1(entries, request, ready, results, logger):
    """Phase 2 of n-1: read every kept n-1 result and classify; the entry goes to result['n1']."""
    by_id = {result['id']: result for result in results}
    done = {}
    for plan in ready:
        entry = entries.get(plan['id'])
        result = by_id.get(plan['id'])
        if entry is None or result is None:
            continue
        if id(entry) not in done:
            if entry.get('status') == 'CALCULATED':
                logger.case("n-1 evaluation · Case {} · {}".format(plan['id'], plan['name']))
            try:
                done[id(entry)] = evaluate_n1_case(entry, plan, entry.get('elements_of') or {}, request.get('run_id') or '')
            except GridLensError as exc:
                done[id(entry)] = {'status': 'NOT EVALUATED', 'reason': str(exc), 'times': 0}
            evaluated = done[id(entry)]
            for line in evaluated.get('details') or ():
                logger.detail(line)
            if evaluated['status'] == 'EVALUATED':
                logger.detail("{} at {} study time(s).".format(evaluated['summary'], evaluated['times']))
            elif entry.get('status') == 'CALCULATED':
                logger.detail("n-1 not evaluated: {}".format(evaluated['reason']), "WARNING")
        result['n1'] = dict(done[id(entry)])


def evaluate_runs(runs, request, logger):
    """Phase 2 of the QDS: REF first, then every case from its kept result object, compared with REF."""
    results, by_id, reference = [], {}, None
    for run in runs:
        if run['id'] == REFERENCE_CASE_ID:
            logger.case("Evaluation · {} · {}".format(REFERENCE_CASE_ID, run.get('name', REFERENCE_NAME)))
            if run.get('failed'):
                raise GridLensError(run['failed'])
            reference = evaluate_qds(run, run.get('description', ''), None, logger)
            reference['run_note'] = run.get('run_note', '')
            results.append(reference)
            check_run_budget(results)
            continue
        if run.get('reuse_of'):
            source = by_id.get(run['reuse_of'])
            if source is not None and source['status'] == CONVERGED:
                logger.case("Evaluation · Case {} · {}".format(run['id'], run['plan']['name']))
                logger.detail("Same outages and windows as {}; its result is reused.".format(source['id']))
                results.append(_reused_result(source, run['plan'], request))
                continue
            run = dict(run, failed='the case it shares its result with ({}) could not be evaluated'.format(run['reuse_of']))
        result = evaluate_case(run, reference, logger)
        by_id[run['id']] = result
        results.append(result)
        check_run_budget(results)
    return results


# ---------------------------------------------------------------------------
# Kept-run lookup and result quality checks
# ---------------------------------------------------------------------------

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


def kept_runs(study_case, stamp, request, ready, logger, grid=None):
    """Phase 1 without a calculation: the runs and n-1 entries from the result objects of an earlier run.

    Every object is found by its name GridLens_<stamp>_<case>; a case whose
    outages or windows changed since (another fingerprint) or whose object is
    missing is not evaluated, with the reason. A changed REF stops the run.
    """
    objects = {object_name(obj): obj for obj in _contents(study_case, '*.ElmRes')}
    prefix = "{}{}_".format(SNAPSHOT_PREFIX, stamp)
    logger.write("CALCULATION", "Re-evaluating the kept results of the run {}: no calculation, PowerFactory is not "
                 "changed.".format(stamp), 4)
    runs = []
    if setting_value('run_reference'):
        obj = objects.get(prefix + REFERENCE_CASE_ID)
        if obj is None:
            raise GridLensError("The run {} kept no reference result object '{}'.".format(stamp, prefix + REFERENCE_CASE_ID))
        if result_fingerprint(obj) not in (None, reference_fingerprint(request)):
            raise GridLensError("The fixed background outages changed since the run {}, so its reference does not fit "
                                "the cases any more. Calculate again.".format(stamp))
        runs.append({'id': REFERENCE_CASE_ID, 'name': REFERENCE_NAME, 'snapshot': obj, 'elapsed': 0.0,
                     'result_object': object_name(obj), 'description': 'Kept reference of the run {}.'.format(stamp),
                     'run_note': 'evaluated from the kept result object'})
    found_by_fingerprint = {}
    n1 = {}
    prime = N1_PRIME in (request.get('assessments') or ())
    commands = _contents(study_case, '*.' + N1_COMMAND_CLASS)
    elements_of = _equipment_map(commands)
    filtered = excluded_contingencies([pair for command in commands for pair in contingency_equipment(command)])
    for plan in ready:
        info = _case_info(plan)
        obj = objects.get(prefix + plan['id'])
        if obj is None and plan['fingerprint'] in found_by_fingerprint:
            runs.append({'id': plan['id'], 'plan': plan, 'reuse_of': found_by_fingerprint[plan['fingerprint']]})
            n1[plan['id']] = n1.get(found_by_fingerprint[plan['fingerprint']], {'status': 'NOT EVALUATED',
                                                                                'reason': 'no kept n-1 result', 'times': 0})
            continue
        if obj is None:
            runs.append(dict(info, failed="the run {} kept no result object '{}'".format(stamp, prefix + plan['id'])))
        elif result_fingerprint(obj) not in (None, plan['fingerprint']):
            runs.append(dict(info, failed="its outages or windows changed since the run {}; calculate again".format(stamp),
                             result_object=object_name(obj)))
        else:
            found_by_fingerprint[plan['fingerprint']] = plan['id']
            runs.append(dict(info, snapshot=obj, elapsed=0.0, result_object=object_name(obj),
                             run_note='evaluated from the kept result object of the run {}'.format(stamp)))
        if N1_REFERENCE in (request.get('assessments') or ()):
            reference, scenario = objects.get(prefix + plan['id'] + '_N1'), objects.get(prefix + plan['id'] + '_N1P')
            if reference is None or (prime and scenario is None):
                n1[plan['id']] = {'status': 'NOT EVALUATED', 'times': 0,
                                  'reason': "the run {} kept no {} result for this case".format(
                                      stamp, N1_REFERENCE if reference is None else N1_PRIME)}
            else:
                window_times = n1_study_times([plan['windows'][record['key']] for record in plan['members']],
                                              grid) if grid else None
                n1[plan['id']] = {'status': 'CALCULATED', 'times': 0, 'elements_of': elements_of,
                                  'filtered_out': filtered, 'calculated_with': n1_filter_of(reference),
                                  'kind': N1_PRIME if prime else N1_REFERENCE,
                                  'reference': {'kept': reference, 'recording_limits': recording_limits_of(reference),
                                                'window_times': window_times},
                                  'scenario': {'kept': scenario, 'recording_limits': recording_limits_of(scenario),
                                               'window_times': window_times} if prime else None}
    return runs, n1


def outage_quality(payload, results):
    """One Model Quality row per case: did each of its planned outages take effect in the results?"""
    for result in results:
        checks = result.get('outage_checks')
        if not checks:
            continue
        doubtful = [(name, status) for name, status, _ in checks if status in (OUTAGE_NO_EFFECT, OUTAGE_UNCHECKED)]
        counts = ', '.join('{} {}'.format(sum(1 for _, found, _ in checks if found == status), status)
                           for status in (OUTAGE_APPLIED, OUTAGE_EFFECT, OUTAGE_NO_EFFECT, OUTAGE_UNCHECKED)
                           if any(found == status for _, found, _ in checks))
        detail = '; '.join('{}: {}'.format(clip_text(name, 40), status) for name, status in doubtful[:3])
        _quality(payload, 'outages_' + result['id'], 'Outages applied ' + result['id'],
                 'WARNING' if doubtful else 'PASS', counts + ('. ' + detail + '.' if detail else '.'), result['id'])


def persistence_quality(payload, results):
    """One Model Quality row per case whose outages stay in effect after their windows."""
    for result in results:
        lasting = [entry for entry in result.get('outage_persistence') or () if entry[1]]
        if lasting:
            _quality(payload, 'outages_after_' + result['id'], 'Outage in effect after its window ' + result['id'],
                     'WARNING', '; '.join('{}: {:g} h after its window end{}'.format(
                         clip_text(name, 40), stretch, ', until the end of the period' if not back else '')
                         for name, stretch, _total, _until, back in lasting[:3])
                     + '. The switching state persists in the QDS; time steps after the window are assessed as '
                       'effect outside the window.', result['id'])


def n1_quality(payload, results):
    """One Model Quality row per case with an n-1 entry."""
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


# ---------------------------------------------------------------------------
# Application entry points
# ---------------------------------------------------------------------------


def execute_gridlens(app):
    """Execute one assessment in the active PowerFactory study case.

    Resolve and validate the request before calculation. Keep native results,
    restore written settings, then evaluate and publish the report tables.
    Return table row counts; a standalone run returns the built counts without
    publication. Cancellation and runtime failures propagate to the entry point.
    """
    global RUN_STATS
    RUN_STATS = RunStats()
    reset_run_context()
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
        # The QDS writes into the bound result object; a kept run would be overwritten.
        raise GridLensError(
            "ComStatsim.results is bound to '{}', a kept result object of an earlier GridLens run; the QDS would "
            "overwrite it. No calculation was started.".format(object_name(original_result)),
            details=["Bound result object: " + object_key(original_result)],
            hint="Bind ComStatsim.results to another result object, or run the quasi-dynamic simulation once by hand "
                 "so that PowerFactory binds its own, then run GridLens again.")
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
        elements = contingency_element_choices(app, contingencies) if CASE_SOURCE == "gui" else []
        kept = kept_stamps(study_case)
    case_manager = time.monotonic()
    request = obtain_case_request(app, records, candidates, period, logger, qds_time_info(qds, period), grids,
                                  contingencies, kept, elements)
    RUN_STATS.add("case manager (window open, incl. your time)", time.monotonic() - case_manager)
    # The settings are fixed here, after the case manager has closed, and apply to the whole run.
    request["settings_snapshot"] = activate_settings(request.get("settings"))
    logger.write("SETTINGS", "Settings {} with classification rules {}: {}.".format(
        SETTINGS_VERSION, CLASSIFICATION_VERSION, overrides_text(request["settings_snapshot"]["overrides"])), 3)
    request["contingency_scope"] = contingency_scope_text(contingencies, current_setting("contingency_grids"),
                                                          current_setting("monitoring_grids"))
    logger.write("SETTINGS", "Report filter: {}. Contingencies: {} {}.".format(
        grid_scope_text(), request["contingency_scope"], n1_filter_text()), 3)
    _log_plan(logger, request)
    ready = [plan for plan in request["cases"] if plan["status"] == PLAN_READY]
    logger.step(4, "Calculation (phase 1): every run into its kept result object")
    runs = []
    n1_runs = {}
    evaluate_stamp = request.get("evaluate_stamp")
    # The run ID of both reports: the stamp of the result objects the run keeps (or re-evaluates).
    request["run_id"] = evaluate_stamp or result_objects.stamp
    try:
        if evaluate_stamp:
            runs, n1_runs = kept_runs(study_case, evaluate_stamp, request, ready, logger, qds_grid(qds))
        else:
            if setting_value('run_reference'):
                runs.append(_calculate_reference(app, study_case, qds, request, records, original_result, logger,
                                                 result_objects, study_time_state))
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
                    if source is not None and not source.get("failed"):
                        logger.case("Case {} · {}".format(plan["id"], plan["name"]))
                        logger.detail("Same outages and windows as {}; its result is reused, no QDS run.".format(source["id"]))
                        runs.append({"id": plan["id"], "plan": plan, "reuse_of": source["id"]})
                        RUN_STATS.count("reused_cases")
                        continue
                    run = _calculate_case(app, study_case, qds, plan, request, records, original_result, logger,
                                          result_objects, study_time_state)
                    calculated.setdefault(plan["fingerprint"], run)
                    runs.append(run)
            else:
                logger.write(
                    "CALCULATION",
                    "No planning case can be calculated; the case runs were skipped.", 4, "WARNING")
            if N1_REFERENCE not in (request.get("assessments") or ()):
                logger.write("CALCULATION", "n-1 is not calculated: it is not ticked in the case manager "
                             "(Assessments: n-1, (n-1)').", 4)
            elif not ready:
                logger.write("CALCULATION", "n-1 is not calculated: no planning case can be calculated.", 4, "WARNING")
            else:
                n1_runs = calculate_n1(app, study_case, qds, request, records, ready, logger, study_time_state,
                                       result_objects)
    except BaseException:
        # The restore step follows; the failure report names where the run was when it failed.
        RUN_CONTEXT['failed_at'] = (RUN_CONTEXT.get('step'), RUN_CONTEXT.get('case'))
        raise
    finally:
        logger.step(5, "Restore and clean-up")
        restoring = time.monotonic()
        logger.write("RESTORE", "Restoring the original PowerFactory state.", 5)
        state_errors.extend(_restore_study_time(study_time_state, logger))
        state_errors.extend(
            _restore_planned_outage_option(qds, original_option, logger))
        _log_results_binding(qds, original_result, logger)
        _log_kept_results(result_objects, logger)
        RUN_CONTEXT['restore'] = ("NOT fully restored: " + "; ".join(state_errors)) if state_errors else (
            "restored and verified (Study Case time, 'Planned Outages' option, every value GridLens wrote)")
        RUN_STATS.add("restore PowerFactory state", time.monotonic() - restoring)
    if state_errors:
        raise GridLensError(
            "GridLens could not fully restore PowerFactory state: {}. Stop and "
            "verify the study case manually before continuing.".format(
                "; ".join(state_errors)))
    logger.write("RESTORE", "Original PowerFactory state restored and verified.", 5)
    logger.step(6, "Evaluation (phase 2): reading and comparing the kept result objects")
    if open_column_buffer(app) is None:
        logger.write("EXTRACTION", "No IntVec could be created in this ComPython, so results are read value by value "
                     "(slow). The run summary counts these reads.", 6, "WARNING")
    try:
        results = evaluate_runs(runs, request, logger)
        if n1_runs:
            evaluate_n1(n1_runs, request, ready, results, logger)
    finally:
        close_column_buffer()
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
    """Connect to PowerFactory, report failures and reset the active settings."""
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
        log_failure(logger, exc)
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
