"""Regression checks for native-result quality and production failure paths."""

import importlib.util
import json
from datetime import datetime

import pytest

from _paths import delivered
import test_n1_core as native
import test_cases as cases
import test_gridlens_report as runtime
import test_reporting_core as reporting


SPEC = importlib.util.spec_from_file_location('gridlens_production', delivered('gridlens_report.py'))
gl = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gl)


@pytest.fixture(autouse=True)
def defaults():
    gl.reset_settings()
    yield
    gl.reset_settings()


def test_native_unreadable_cells_survive_the_loaded_sweep_adapter():
    found = gl.read_n1_results(native.command({native.START: {(0, 0): (7, 0.0), (0, 1): (3, 0.0)}}))
    present, values, absent = gl.LoadedSweep(found).read(native.START)
    unreadable = (gl.object_key(native.C1), gl.object_key(native.LINE_A), 'loading')
    unrecorded = (gl.object_key(native.C1), gl.object_key(native.LINE_B), 'loading')
    assert gl.object_key(native.C1) in present
    assert unreadable in absent and unreadable not in values
    assert unrecorded not in absent and unrecorded not in values
    assert gl.compare_n1(found, found)['counts']['NOT_EVALUATED'] >= 1


def test_a_zero_from_a_sparse_bulk_read_is_not_a_measured_loading(monkeypatch):
    monkeypatch.setattr(gl, 'COLUMN_BUFFER', native.Vector())
    result = native.BulkSub(native.START, [native.C1, native.C2], native.COLUMNS,
                            {(0, 0): (0, 0.0), (1, 0): (3, 0.0)})
    assert gl._n1_column(result, 0, 2, 'loading') == [0.0, None]


@pytest.mark.parametrize('outages', [[None], [native.C1, native.C1]])
def test_native_contingency_rows_must_have_unique_readable_identities(outages):
    with pytest.raises(gl.GridLensError, match='contingency row'):
        gl.read_n1_results(native.command({native.START: {}}, outages=outages))


def test_contingency_filters_also_remove_unreadable_rows_and_metadata():
    found = gl.read_n1_results(native.command({native.START: {}}))
    c1, c2 = gl.object_key(native.C1), gl.object_key(native.C2)
    filtered, dropped = gl.drop_contingencies(found, {c1})
    assert dropped == ['C1']
    present, _values, absent = gl.LoadedSweep(filtered).read(native.START)
    assert present == {c2}
    assert all(key[0] == c2 for key in absent)
    assert set(filtered['contingencies']) == {c2}
    assert set(found['contingencies']) == {c1, c2}


@pytest.mark.parametrize('reader', [gl.read_n1_results, gl.SweepReader])
@pytest.mark.parametrize('moment', [None, float('nan'), native.START])
def test_invalid_or_duplicate_native_study_times_are_rejected(reader, moment):
    first = native.Sub(native.START, [native.C1], native.COLUMNS, {})
    second = native.Sub(moment, [native.C1], native.COLUMNS, {})
    with pytest.raises(gl.GridLensError, match='study time'):
        reader(native.Folder([first, second]))


def test_per_element_implicit_counts_never_turn_unknown_cells_into_ok():
    gl.activate_settings({'n1_limit_mode': 'global', 'n1_limit_global': 70.0})
    source = reporting.Source({reporting.T0: ({reporting.C1, reporting.C2}, {})})
    statistics = gl.compare_scenario('RUN', 'C1', source, source, [reporting.T0], contingencies=[reporting.C1, reporting.C2])
    counters = gl.element_counters(statistics, reporting.LINE, 'loading')
    assert counters['NOT_EVALUATED'] == 2 and counters['OK'] == 0
    assert sum(row['incomplete'] for row in statistics['scope'].values()) == 2


@pytest.mark.parametrize('reference_limit,scenario_limit', [(120.0, 80.0), (80.0, 120.0)])
def test_sparse_comparisons_use_the_recording_limits_of_each_side(reference_limit, scenario_limit):
    reference = reporting.Source({reporting.T0: ({reporting.C1, reporting.C2}, {})})
    scenario = reporting.Source({reporting.T0: ({reporting.C1, reporting.C2}, {})})
    reference.recording_limits = dict(reference.recording_limits, loading=(reference_limit,))
    scenario.recording_limits = dict(scenario.recording_limits, loading=(scenario_limit,))
    statistics = gl.compare_scenario('RUN', 'C1', reference, scenario, [reporting.T0],
                                     contingencies=[reporting.C1, reporting.C2])
    assert gl.element_counters(statistics, reporting.LINE, 'loading')['NOT_EVALUATED'] == 2
    assert statistics['events']['NOT_EVALUATED'] == 4


def test_reference_counts_and_extremes_survive_releasing_value_arrays():
    result = cases._result('REF', 'Reference')
    before = gl.qds_level_statistics('RUN', result)
    gl.release_values(result)
    after = gl.qds_level_statistics('RUN', result)
    assert before['critical']['transformer'] == 1
    assert after == before
    assert all('values' not in item for item in result['item_by_key'].values())


@pytest.mark.parametrize('identifier', [[], {}, None])
def test_damaged_case_identifiers_produce_validation_messages(identifier):
    config = gl.empty_case_config()
    config['cases'] = [{'id': identifier, 'name': 'Broken', 'outages': []}]
    assert any('id' in message and 'not allowed' in message for message in gl.validate_case_config(config))


@pytest.mark.parametrize('revision', [-1, True, 'broken', 1.5])
def test_invalid_revisions_are_rejected_before_saving(revision):
    config = dict(gl.empty_case_config(), revision=revision)
    assert any('revision' in message for message in gl.validate_case_config(config))


def test_a_failed_config_replace_preserves_the_file_and_cleans_up(tmp_path, monkeypatch):
    path = str(tmp_path / 'cases.json')
    config = gl.empty_case_config()
    gl.save_case_config(path, config)
    before = (tmp_path / 'cases.json').read_bytes()
    revision = config['revision']
    monkeypatch.setattr(gl.os, 'replace', lambda *_: (_ for _ in ()).throw(OSError('replace refused')))
    with pytest.raises(gl.GridLensError, match='replace refused'):
        gl.save_case_config(path, config)
    assert (tmp_path / 'cases.json').read_bytes() == before
    assert config['revision'] == revision
    assert list(tmp_path.iterdir()) == [tmp_path / 'cases.json']


def test_fixed_outage_dates_are_part_of_the_reference_identity():
    first = {'key': 'Project\\Fixed.IntPlannedout', 'window': (100.0, 200.0)}
    second = dict(first, window=(100.0, 300.0))
    assert gl.reference_fingerprint({'background': [first]}) != gl.reference_fingerprint({'background': [second]})


def test_standalone_runs_validate_the_payload_before_reporting_success(tmp_path, monkeypatch):
    app = runtime.App([runtime.PlannedOutage('FS')])
    app.script.GetParent = lambda: None
    monkeypatch.setattr(gl, 'CASE_SOURCE', 'per_outage')
    monkeypatch.setattr(gl, 'CASE_CONFIG_DIR', str(tmp_path))
    monkeypatch.setattr(gl, 'build_cases_payload', lambda *a, **k: {'unexpected': []})
    with pytest.raises(ValueError, match='payload'):
        gl.execute_gridlens(app)
    assert app.report.reset_calls == 0


def test_bad_revision_in_a_saved_file_names_the_file(tmp_path):
    path = tmp_path / 'damaged.json'
    path.write_text(json.dumps(dict(gl.empty_case_config(), revision=[])))
    with pytest.raises(gl.GridLensError, match='damaged.json'):
        gl.load_case_config(str(path))


def test_a_new_run_avoids_existing_native_result_names(monkeypatch):
    now = datetime(2026, 10, 27, 12, 0, 0)

    class Clock:
        @staticmethod
        def now():
            return now

        fromtimestamp = staticmethod(datetime.fromtimestamp)
    monkeypatch.setattr(gl, 'datetime', Clock)
    old = native.Obj('GridLens_261027-120000_REF', 'ElmRes')
    store = gl.ResultStore(study_case=native.Folder([old]))
    assert store.stamp == '261027-120001'
    assert gl.ResultStore('chosen').stamp == 'chosen'


def test_a_kept_reference_without_provenance_is_not_reused():
    obj = native.Obj('GridLens_261027-120000_REF', 'ElmRes', desc=[])
    with pytest.raises(gl.GridLensError, match='no verifiable fingerprint'):
        gl.kept_runs(native.Folder([obj]), '261027-120000', {'background': []}, [], native.Logger())


def test_an_n1_copy_that_cannot_be_named_is_not_claimed_as_kept():
    class Locked(native.Obj):
        def __setattr__(self, name, value):
            if name == 'loc_name' and name in self.__dict__:
                return
            super().__setattr__(name, value)

        def Delete(self):
            self.deleted = True
    copied = Locked('Unchanged name', 'ElmRes')
    study = native.Obj('Study', 'IntCase')
    study.AddCopy = lambda _obj: copied
    assert gl.keep_copy(study, native.Obj('Native', 'ElmRes'), 'Wanted name', 'mark') is None
    assert copied.deleted
