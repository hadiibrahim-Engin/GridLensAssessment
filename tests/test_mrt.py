from __future__ import annotations

import importlib.util
import re
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest


ROOT = Path(__file__).resolve().parents[1]
MRT = ROOT / "powerfactory" / "MASTER_GRIDLENS.mrt"
SCRIPT = ROOT / "powerfactory" / "gridlens_report.py"
SPEC = importlib.util.spec_from_file_location("gridlens_report_mrt", SCRIPT)
gl = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(gl)


def _root():
    return ET.parse(MRT).getroot()


def _data_sources(root):
    sources = {}
    container = root.find(".//DataSources")
    assert container is not None
    for source in list(container):
        columns = source.find("Columns")
        assert columns is not None
        parsed = []
        for value in columns.findall("value"):
            name, dotnet_type = (value.text or "").split(",", 1)
            kind = {
                "System.String": "string",
                "System.Int32": "integer",
                "System.Double": "number",
            }[dotnet_type]
            parsed.append((name, kind))
        sources[source.tag] = tuple(parsed)
    return sources


def test_mrt_data_sources_exactly_match_python_contract():
    assert _data_sources(_root()) == dict(gl.TABLES)


def test_mrt_structure_and_release_invariants():
    root = _root()
    refs = [element.attrib["Ref"] for element in root.iter() if "Ref" in element.attrib]
    reference_targets = [element.attrib["isRef"] for element in root.iter()
                         if "isRef" in element.attrib]
    assert len(refs) == len(set(refs))
    assert set(reference_targets) <= set(refs) | {"0"}
    report_file = root.find("ReportFile")
    assert report_file is not None and not (report_file.text or "").strip()
    assert root.findall(".//ImageBytes")
    assert root.findall(".//Bookmark")
    charts = _charts(root)
    assert len(charts) > 20
    for chart in charts:
        assert len(chart.findall("Style")) == 1, chart.tag
    names = [element.findtext("Name") for element in root.iter() if element.findtext("Name")]
    assert len(names) == len(set(names)), "component names must be unique"


def _charts(root):
    return [element for element in root.iter() if element.get("type", "").endswith("StiChart")]


def _components(root):
    return list(root.find(".//PageMain").find("Components"))


def test_the_report_is_one_landscape_page_in_the_order_of_the_template():
    root = _root()
    assert [page.tag for page in root.find("Pages")] == ["PageMain"]
    page = root.find(".//PageMain")
    assert page.findtext("Orientation") == "Landscape"
    assert float(page.findtext("PageWidth")) > float(page.findtext("PageHeight"))
    order = [item.tag for item in _components(root)]
    sequence = ["BandCover", "BandTableOfContents", "quality_TitleBand", "cases_TitleBand", "casedef_TitleBand",
                "reference_TitleBand", "metrics_TitleBand", "summary_TitleBand", "comparison_TitleBand", "radar_TitleBand",
                "toplines_TitleBand", "trendmost_TitleBand", "trenddelta_TitleBand", "topcase_TitleBand",
                "evidence_TitleBand", "appendix_TitleBand", "appa_TitleBand", "appb_TitleBand", "appc_TitleBand"]
    positions = [order.index(name) for name in sequence]
    assert positions == sorted(positions)
    assert order[0] == "BandPageHeader" and order[-1] == "BandPageFooter"


def test_every_chapter_starts_on_its_own_page_and_prints_without_rows():
    root = _root()
    for item in _components(root):
        if not item.tag.endswith("_TitleBand"):
            continue
        assert item.get("type") == "DataBand", item.tag
        assert item.findtext("DataSourceName") == "ScriptedReportMeta", item.tag
        assert item.findtext("NewPageBefore") == "True", item.tag
        assert not list(item.find("Filters")), item.tag


def test_header_footer_and_cover_follow_the_template():
    root = _root()
    texts = {element.text for element in root.findall(".//Text")}
    assert "NETWORK STATE AND PLANNED OUTAGE ANALYSIS" in texts
    assert "PRE-ASSESSMENT | NOT FOR OPERATIONAL USE" in texts
    assert "{ScriptedReportMeta.assessment_status}" in texts
    assert "{ScriptedReportMeta.generated_by}" in texts
    assert "{ScriptedReportMeta.run_mode}" in texts
    assert "Network State and\nPlanned Outage Analysis" in texts
    assert root.find(".//BandPageHeader").findtext("PrintOn") == "ExceptFirstPage"
    assert "SYNTHETIC" not in MRT.read_text(encoding="utf-8").upper()


def test_table_of_contents_links_to_existing_bookmarks():
    root = _root()
    bookmarks = {element.text for element in root.findall(".//Bookmark")}
    links = [element.text[1:] for element in root.findall(".//Hyperlink")]
    assert len(links) >= 15
    assert set(links) <= bookmarks
    toc = root.find(".//BandTableOfContents")
    assert toc is not None and toc.findtext("NewPageBefore") == "True"
    last = max(toc.find("Components"), key=lambda item: float(item.findtext("ClientRectangle").split(",")[1]))
    bottom = float(last.findtext("ClientRectangle").split(",")[1]) + float(last.findtext("ClientRectangle").split(",")[3])
    page = root.find(".//PageMain")
    available = float(page.findtext("PageHeight")) - sum(float(v) for v in page.findtext("Margins").split(",")[1::2])
    assert bottom < available - 1.0, "the table of contents must fit on its page"


def test_model_quality_table_marks_warnings_in_the_status_cell_only():
    root = _root()
    header = [root.find(".//Quality_H{}".format(i)).findtext("Text") for i in range(4)]
    assert header == ["Check", "Status", "Details", "Equipment"]
    status = root.find(".//Quality_C1")
    assert [value.text.split(",", 2)[:2] for value in status.find("Conditions")] == [
        ["ScriptedModelQuality.status", "EqualTo"]] * 2
    assert not list(root.find(".//Quality_C0").find("Conditions"))


def test_cases_table_reads_as_an_assessment_and_highlights_violations():
    root = _root()
    headings = [root.find(".//Cases_H{}".format(i)).findtext("Text") for i in range(6)]
    assert headings == ["Case", "Outage periods", "Prio", "Equipment out of service", "Assessment",
                        "Findings at the same time steps as Reference"]
    fields = [root.find(".//Cases_C{}".format(i)).findtext("Text") for i in range(6)]
    assert fields == ["{ScriptedCases.%s}" % name for name in (
        "case_name", "period_text", "priority", "equipment_name", "assessment", "assessment_detail")]
    conditions = root.find(".//Cases_C4").find("Conditions")
    assert [value.text.split(",", 2)[:2] for value in conditions] == [
        ["ScriptedCases.violation", "EqualTo"], ["ScriptedCases.violation", "EqualTo"]]


def test_table_columns_fill_the_page_width_exactly():
    root = _root()
    page = root.find(".//PageMain")
    width = float(page.findtext("PageWidth")) - sum(float(v) for v in page.findtext("Margins").split(",")[0::2])
    checked = 0
    for band in root.iter():
        if not (band.tag.endswith("_DataBand") or band.tag.endswith("_HeaderBand") or band.tag.endswith("_GroupHeaderBand")):
            continue
        cells = [cell for cell in band.find("Components") if "_H" in cell.tag or "_C" in cell.tag]
        if not cells:
            continue
        edge = 0.0
        for cell in cells:
            left, _, size, _ = (float(value) for value in cell.findtext("ClientRectangle").split(","))
            assert left == pytest.approx(edge), cell.tag
            edge += size
        if not any(key in band.tag for key in ("TopCase", "App", "Summary")):
            assert edge == pytest.approx(width), band.tag
        else:
            assert edge <= width + 0.01, band.tag
        checked += 1
    assert checked > 20


def _bands_of(root, prefix):
    return [item for item in _components(root) if item.tag.startswith(prefix)]


def test_matrix_tables_exist_once_per_number_of_case_columns_and_filter_on_it():
    root = _root()
    for key, source in (("TopCase", "ScriptedTopLinesByCase"), ("Appa", "ScriptedAppendixLine"),
                        ("Appb", "ScriptedAppendixTransformer"), ("Appc", "ScriptedAppendixVoltage")):
        data = [item for item in _bands_of(root, key) if item.tag.endswith("_DataBand")]
        assert [item.tag for item in data] == ["{}{}_DataBand".format(key, n) for n in range(6, -1, -1)]
        for count, band in zip(range(6, -1, -1), data):
            assert band.findtext("DataSourceName") == source
            (flt,) = band.find("Filters")
            decoded = re.sub(r"_x([0-9A-Fa-f]{4})_", lambda m: chr(int(m[1], 16)), flt.text)
            assert decoded == "{}.col_count == {}".format(source, count)
            cells = [cell for cell in band.find("Components")]
            assert len(cells) == 2 + count
        headers = [item for item in _bands_of(root, key) if item.tag.endswith("_GroupHeaderBand")]
        assert len(headers) == 7
        for header in headers:
            assert header.findtext("Condition") == "{%s.block}" % source


def test_charts_with_case_series_exist_once_per_number_of_drawn_cases():
    root = _root()
    for prefix, table in (("RadarChart", "ScriptedRadar"), ("trendmostChart", "ScriptedTrendMostLoaded"),
                          ("trenddeltaChart", "ScriptedTrendLargestDelta")):
        bands = [item for item in _components(root) if re.fullmatch(prefix + r"\d_Band", item.tag)]
        assert [item.tag for item in bands] == ["{}{}_Band".format(prefix, n) for n in range(1, 8)]
        for count, band in zip(range(1, 8), bands):
            chart = next(element for element in band.iter() if element.get("type", "").endswith("StiChart"))
            assert chart.findtext("DataSourceName") == table
            series = list(chart.find("Series"))
            assert len(series) == count
            assert [item.findtext("Title") for item in series] == ["{%s.s%d_name}" % (table, i) for i in range(count)]
            assert [item.findtext("ValueDataColumn") for item in series] == ["%s.v%d" % (table, i) for i in range(count)]
            assert series[0].findtext("LineColor") == "140, 150, 160", "REF is grey"
            decoded = [re.sub(r"_x([0-9A-Fa-f]{4})_", lambda m: chr(int(m[1], 16)), v.text) for v in band.find("Filters")]
            assert decoded[0] == 'ScriptedReportMeta.chart_cases == "{}"'.format(count)


def test_case_comparison_charts_read_the_case_counts_in_data_order():
    root = _root()
    band = root.find(".//CaseCounts_Band")
    charts = [element for element in band.iter() if element.get("type", "").endswith("StiChart")]
    assert [chart.findtext("DataSourceName") for chart in charts] == ["ScriptedCaseCounts"] * 3
    fields = [next(iter(chart.find("Series"))).findtext("ValueDataColumn") for chart in charts]
    assert fields == ["ScriptedCaseCounts." + name for name in ("line_count", "transformer_count", "node_count")]
    for chart in charts:
        # The categories keep the order of the cases; they are not sorted by name.
        assert next(iter(chart.find("Series"))).findtext("ArgumentDataColumn") == "ScriptedCaseCounts.case_name"


def test_reference_pies_have_fixed_colours_and_name_their_classes():
    root = _root()
    for name, table in (("ReferenceLinesPie", "ScriptedPieLines"), ("ReferenceTransformersPie", "ScriptedPieTransformers")):
        chart = root.find(".//" + name)
        assert chart.findtext("DataSourceName") == table
        (series,) = list(chart.find("Series"))
        assert series.get("type").endswith("StiPieSeries")
        assert len(series.find("Conditions")) == 3
        labels = chart.find("SeriesLabels")
        assert labels.findtext("LegendValueType") == "Argument"
        assert labels.findtext("Visible") != "False"


def test_top_lines_chart_is_a_single_series_bar_with_the_100_percent_line():
    chart = _root().find(".//TopLinesBarChart")
    (series,) = list(chart.find("Series"))
    assert series.findtext("ArgumentDataColumn") == "ScriptedLineLoadingBars.element_name"
    assert series.findtext("ValueDataColumn") == "ScriptedLineLoadingBars.max_value"
    assert series.findtext("SortBy") == "None"
    (limit,) = list(chart.find("ConstantLines"))
    assert limit.findtext("AxisValue") == "100"


def test_no_lodf_remains_in_the_template():
    text = MRT.read_text(encoding="utf-8")
    assert "LODF" not in text.upper()
    assert "ScriptedLodfRanking" not in text


def test_case_definition_shows_outages_states_coverage_and_provenance():
    root = _root()
    fields = [root.find(".//CaseDef_C{}".format(i)).findtext("Text") for i in range(6)]
    assert fields == ["{ScriptedCases.%s}" % name for name in (
        "case_name", "outage_names", "reference_text", "states_text", "coverage_text", "provenance_text")]
    texts = {element.text for element in root.findall(".//Text")}
    assert "{ScriptedReportMeta.coverage_statement}" in texts


def test_summary_matrix_and_evidence_table():
    root = _root()
    data = [item for item in _bands_of(root, "Summary") if item.tag.endswith("_DataBand")]
    assert [item.tag for item in data] == ["Summary{}_DataBand".format(n) for n in range(6, -1, -1)]
    assert all(item.findtext("DataSourceName") == "ScriptedCaseComparison" for item in data)
    evidence = [root.find(".//Evidence_H{}".format(i)).findtext("Text") for i in range(8)]
    assert "Result object in PowerFactory" in evidence
    assert root.find(".//Evidence_DataBand").findtext("DataSourceName") == "ScriptedCalculationRuns"


def test_metric_view_names_both_deltas():
    root = _root()
    headings = [root.find(".//Metrics_H{}".format(i)).findtext("Text") for i in range(7)]
    assert "Max. coincident increase vs REF" in headings and "Difference of maxima" in headings


def test_every_data_source_is_read_in_a_stable_order():
    root = _root()
    ordered = {"ScriptedCases", "ScriptedCaseComparison", "ScriptedCalculationRuns", "ScriptedTopLinesByCase", "ScriptedAppendixLine",
               "ScriptedTrendMostLoaded", "ScriptedLineLoadingBars", "ScriptedRadar", "ScriptedPieLines"}
    for source in root.find(".//DataSources"):
        if source.tag in ordered:
            assert "ORDER BY" in source.findtext("SqlCommand"), source.tag


def test_mrt_contains_no_local_paths_or_obsolete_sources():
    text = MRT.read_text(encoding="utf-8")
    forbidden = (
        "/Users/", "/home/", "file://", "C:\\", "C:/",
        "ScriptedScenarios", "ScriptedOutages", "ScriptedScenario",
        "scenario_id", "scenario_name",
    )
    assert not [value for value in forbidden if value in text]


def test_visible_report_text_is_english():
    root = _root()
    visible = "\n".join(
        element.text or "" for element in root.findall(".//Text")
        if "{" not in (element.text or ""))
    german = re.compile(
        r"\b(Szenario|Studie|Auslastung|Spannung|Zeitpunkt|Ergebnis|"
        r"Grenzwert|Modell|Untersuchung|Referenz|Leitung|Transformator|"
        r"Knoten|Einheit|Beschreibung|Erstellt|Außerbetriebnahme)\b",
        re.IGNORECASE,
    )
    assert german.search(visible) is None


def test_no_chart_depends_on_a_data_relation():
    # PowerFactory's report engine ignores relations on charts and drew the
    # points of every plot into one chart. Charts must read their own table.
    root = _root()
    relations = root.find(".//Relations")
    assert relations is not None and len(relations) == 0
    charts = [element for element in root.iter()
              if element.get("type", "").endswith("StiChart")]
    assert charts
    for chart in charts:
        assert not (chart.findtext("DataRelationName") or "").strip(), chart.tag
        assert chart.find("MasterComponent") is None, chart.tag


def test_every_declared_list_count_matches_its_children():
    # Stimulsoft allocates lists from the declared count; a mismatch was
    # introduced once by a band whose tiles each hold two text fields.
    mismatches = []
    for element in _root().iter():
        if element.get("isList") == "true":
            declared = int(element.get("count"))
            if declared != len(element):
                mismatches.append("{} declares {} but holds {}".format(
                    element.tag, declared, len(element)))
    assert mismatches == []


def test_empty_lists_are_self_closing():
    # Stimulsoft 2025.3 reads the whitespace inside
    # <Components isList="true" count="0">...</Components> as a string item;
    # the designer then fails with "Unable to cast object of type
    # 'System.String' to type 'StiComponent'". An XML parser hides this, so
    # the raw text is checked.
    text = MRT.read_text(encoding="utf-8")
    offenders = re.findall(r'<(\w+) isList="true" count="0">\s*</\1>', text)
    assert offenders == []


def test_table_rows_keep_their_grid_when_a_cell_wraps():
    # Wrapped names used to stretch one cell and leave the others short.
    root = _root()
    for band in root.iter():
        if band.get("type") != "DataBand" or not band.tag.endswith("DataBand"):
            continue
        if band.findtext("DataSourceName") == "ScriptedReportMeta":
            continue
        for cell in band.find("Components"):
            assert cell.findtext("GrowToHeight") == "True", cell.tag


def test_no_number_depends_on_the_windows_culture():
    # PowerFactory runs on German Windows and printed 1,127 next to 1.127.
    root = _root()
    assert root.findtext("Culture") == "en-US"
    for fmt in root.iter("TextFormat"):
        if fmt.get("type") == "NumberFormat":
            assert fmt.findtext("UseLocalSetting") == "False"
    # Charts are drawn at export time with the thread culture, which the
    # report culture does not reach: no axis may print a culture decimal.
    for chart in root.iter():
        if not chart.get("type", "").endswith("StiChart") or chart.find("Area").get("type").endswith("PieArea"):
            continue
        area = chart.find("Area")
        value_axis = "XAxis" if area.get("type").endswith("BarArea") else "YAxis"
        labels = area.find(value_axis).find("Labels")
        assert labels is not None, chart.tag
        assert labels.findtext("Format") in ("0;-0;0", "0'.'000") or labels.findtext("Placement") == "None", chart.tag
