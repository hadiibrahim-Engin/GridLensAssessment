from __future__ import annotations

import importlib.util
import re
from xml.etree import ElementTree as ET

import pytest


from _paths import delivered, report_files, report_folder, report_text, report_tree
# The two reports as the repository keeps them: a .dct dictionary and one .pg file per page each.
TEMPLATES = {"main": "MASTER_GRIDLENS", "detail": "MASTER_GRIDLENS_DETAIL"}
SCRIPT = delivered("main.py")
SPEC = importlib.util.spec_from_file_location("gridlens_report_mrt", SCRIPT)
gl = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(gl)

both = pytest.mark.parametrize("report", sorted(TEMPLATES))


def _root(report="main"):
    return report_tree(TEMPLATES[report])


def _text(report="main"):
    return report_text(TEMPLATES[report])


def _decode(text):
    return re.sub(r"_x([0-9A-Fa-f]{4})_", lambda m: chr(int(m[1], 16)), text)


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


@both
def test_mrt_data_sources_exactly_match_python_contract(report):
    # Both templates read the same data contract; each shows its own chapters.
    assert _data_sources(_root(report)) == dict(gl.TABLES)


@both
def test_mrt_structure_and_release_invariants(report):
    root = _root(report)
    # Refs restart in every file (dictionary and each page); 0 is the page or dictionary itself.
    for part in [root.find("Dictionary")] + list(root.find("Pages")):
        refs = [element.attrib["Ref"] for element in part.iter() if "Ref" in element.attrib]
        assert len(refs) == len(set(refs)), part.tag
        assert {element.attrib["isRef"] for element in part.iter() if "isRef" in element.attrib} <= set(refs) | {"0"}, part.tag
    assert root.findall(".//ImageBytes")
    assert root.findall(".//Bookmark")
    for chart in _charts(root):
        assert len(chart.findall("Style")) == 1, chart.tag
    names = [element.findtext("Name") for element in root.iter() if element.findtext("Name")]
    assert len(names) == len(set(names)), "component names must be unique"


def _charts(root):
    return [element for element in root.iter() if element.get("type", "").endswith("StiChart")]


def _components(root):
    """The bands of every page, in page order."""
    return [item for page in root.find("Pages") for item in page.find("Components")]


def _page(root):
    return root.find("Pages")[0]


def _sources_used(root):
    return {element.findtext("DataSourceName") for element in root.iter() if len(element) and element.findtext("DataSourceName")}


CHAPTER_PAGES = {
    "main": ["PageCover", "PageContents", "PageOverall", "PageQuality", "PageCases", "PageCasedef", "PageReference", "PageComparison",
             "PageMetrics", "PageCritical", "PageContingency", "PageTime", "PageEvidence"],
    "detail": ["PageCover", "PageContents", "PageScope", "PageRegister", "PageBasefindings", "PageLines", "PageTransformers",
               "PageVoltagelow", "PageVoltagehigh", "PageClassification", "PageContingencies", "PageEvents", "PageEpisodes",
               "PageQualityregister", "PageProvenance", "PageMethod", "PageAppendix", "PageAppa", "PageAppb", "PageAppc"]}


@both
def test_the_report_has_one_landscape_page_per_chapter_in_the_order_of_the_template(report):
    root = _root(report)
    pages = CHAPTER_PAGES[report]
    # The file names keep the order: Open Page in the designer in file order gives the report.
    assert [page.tag for page in root.find("Pages")] == pages
    assert [path.name[:2] for path in report_files(TEMPLATES[report])[1]] == ["{:02d}".format(i) for i in range(len(pages))]
    for page in root.find("Pages"):
        # Stimulsoft stores the page name with its unit: the sizes are centimetres whatever the designer's unit is.
        assert page.findtext("Orientation") == "Landscape"
        assert page.findtext("Name") == page.tag + ":Unit:Stimulsoft.Report.Units.StiCentimetersUnit"
        assert float(page.findtext("PageWidth")) > float(page.findtext("PageHeight"))
        # Every component of a page refers to that page (ref 0 in a page file).
        refs = {element.get("isRef") for element in page.find("Components").iter("Page")}
        assert refs == {"0"}, page.tag
    assert len({page.findtext("Guid") for page in root.find("Pages")}) == len(pages)
    order = [item.tag for item in _components(root)]
    sequence = ["BandCover", "BandTableOfContents"] + [page[len("Page"):].lower() + "_TitleBand" for page in pages[2:]]
    positions = [order.index(name) for name in sequence]
    assert positions == sorted(positions)


def test_the_two_reports_share_one_contract_and_split_its_chapters():
    main, detail = _sources_used(_root("main")), _sources_used(_root("detail"))
    tables = set(dict(gl.TABLES))
    # Every table is shown by at least one report.
    assert tables - main - detail == set()
    assert not {name for name in main if name.startswith(("ScriptedDetail", "ScriptedClassification"))}
    assert not {"ScriptedContingencyEpisodes", "ScriptedQualityRegister", "ScriptedScope", "ScriptedContingencyRegister"} & main
    assert not {name for name in detail if name.startswith(("ScriptedCritical", "ScriptedTime", "ScriptedPie"))}
    # Both reports print the same statistics for the same run: coverage, events, findings, settings and provenance.
    assert {"ScriptedCoverage", "ScriptedContingencyEvents", "ScriptedReferenceFindings", "ScriptedAssessmentSettings",
            "ScriptedResultProvenance", "ScriptedOutageWindows", "ScriptedModelQuality", "ScriptedCalculationRuns"} <= main & detail


@both
def test_every_chapter_is_its_own_page_and_prints_without_rows(report):
    root = _root(report)
    for page in list(root.find("Pages"))[2:]:
        bands = [item for item in page.find("Components") if item.get("type") == "DataBand"]
        title = bands[0]
        assert title.tag.endswith("_TitleBand") and title.tag[:-len("_TitleBand")].capitalize() == page.tag[len("Page"):]
        assert title.findtext("DataSourceName") == "ScriptedReportMeta", title.tag
        assert not list(title.find("Filters")), title.tag
        assert sum(1 for item in bands if item.tag.endswith("_TitleBand")) == 1, page.tag
    assert not list(root.iter("NewPageBefore")), "the pages break the chapters, no band does"


@both
def test_header_footer_and_cover_follow_the_template(report):
    root = _root(report)
    texts = {element.text for element in root.findall(".//Text")}
    assert "NETWORK STATE AND PLANNED OUTAGE ANALYSIS" in texts
    assert "PRE-ASSESSMENT | NOT FOR OPERATIONAL USE" in texts
    assert "{ScriptedReportMeta.assessment_status}" in texts
    assert "{ScriptedReportMeta.generated_by}" in texts
    assert "{ScriptedReportMeta.run_mode}" in texts
    assert "Network State and\nPlanned Outage Analysis" in texts
    # The cover keeps its design without the Study ID; the header names the run.
    assert "Study ID" not in texts and not [text for text in texts if text and "study_id" in text]
    assert any(text and "{ScriptedReportMeta.run_id}" in text for text in texts)
    labels = [root.find(".//CoverRow{}_L".format(index)).findtext("Text") for index in range(10)]
    assert labels == ["Study case", "Network model", "Model version", "Simulation period", "Time step", "Generated at", "Generated by",
                      "Run mode", "Result source", "Assessment scope"]
    # Every page has a footer, every page but the cover a header.
    for index, page in enumerate(root.find("Pages")):
        kinds = [item.get("type") for item in page.find("Components")]
        assert kinds.count("PageFooterBand") == 1, page.tag
        assert kinds.count("PageHeaderBand") == (0 if index == 0 else 1), page.tag
    assert "SYNTHETIC" not in _text(report).upper()


def test_the_two_covers_differ_only_in_their_subtitle():
    def cover(report):
        band = _root(report).find(".//BandCover")
        return [(item.tag, item.findtext("ClientRectangle"), item.findtext("Text")) for item in band.find("Components")]
    main, detail = cover("main"), cover("detail")
    assert [item[:2] for item in main] == [item[:2] for item in detail]
    assert [item for item in main if item not in detail] == [("CoverSubtitle", main[2][1], main[2][2])]


@both
def test_table_of_contents_links_to_existing_bookmarks(report):
    root = _root(report)
    bookmarks = {element.text for element in root.findall(".//Bookmark")}
    links = [element.text[1:] for element in root.findall(".//Hyperlink")]
    assert len(links) == len(CHAPTER_PAGES[report]) - 2
    assert set(links) <= bookmarks
    toc = root.find(".//BandTableOfContents")
    assert toc is not None and toc in list(root.find("Pages/PageContents/Components"))
    page = root.find("Pages/PageContents")
    available = float(page.findtext("PageHeight")) - sum(float(v) for v in page.findtext("Margins").split(",")[1::2])
    # Rendered height: page header, table of contents and footer (bands stack; their designer positions do not count).
    used = sum(float(item.findtext("ClientRectangle").split(",")[3]) for item in page.find("Components"))
    assert used <= available, "the table of contents must fit on its page"


@both
def test_model_quality_table_marks_warnings_in_the_status_cell_only(report):
    root = _root(report)
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


# Matrix tables narrow their scenario columns to at most 4 cm, so they may end before the right margin.
MATRIX_KEYS = ("TopCase", "App", "Summary", "Critical", "Lines", "Transformers", "Voltagelow", "Voltagehigh", "Classification",
               "TimeMatrix")


@both
def test_table_columns_fill_the_page_width_exactly(report):
    root = _root(report)
    page = _page(root)
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
        if not band.tag.startswith(MATRIX_KEYS):
            assert edge == pytest.approx(width), band.tag
        else:
            assert edge <= width + 0.01, band.tag
        checked += 1
    assert checked > 20


def _bands_of(root, prefix):
    return [item for item in _components(root) if re.fullmatch(prefix + r"\d(B\d+)?_(DataBand|HeaderBand)", item.tag)]


MATRICES = {
    "main": [("Summary", "ScriptedCaseComparison", 6), ("CriticalLines", "ScriptedCriticalLines", 6),
             ("CriticalTransformers", "ScriptedCriticalTransformers", 6), ("CriticalNodes", "ScriptedCriticalNodes", 6),
             ("TimeMatrix", "ScriptedTimeMatrix", 6)],
    "detail": [("Lines", "ScriptedDetailLines", 3), ("Transformers", "ScriptedDetailTransformers", 3),
               ("Voltagelow", "ScriptedDetailVoltageLow", 3), ("Voltagehigh", "ScriptedDetailVoltageHigh", 3),
               ("Classification", "ScriptedClassificationMatrix", 3), ("TopCase", "ScriptedTopLinesByCase", 6),
               ("Appa", "ScriptedAppendixLine", 6), ("Appb", "ScriptedAppendixTransformer", 6), ("Appc", "ScriptedAppendixVoltage", 6)]}


@both
def test_matrix_tables_have_a_band_pair_per_block_and_filter_on_it(report):
    # The main report shows up to six scenarios per block, the detail report three; any number of cases up to the limit.
    # Every full block has its own pair (block and column count), the one partial block a pair per column count;
    # each header reads the case names of the first row of its band.
    assert gl.CASE_SLOTS == 6 and gl.DETAIL_SLOTS == 3 and gl.MAX_PLANNING_CASES == 20
    root = _root(report)
    for key, source, slots in MATRICES[report]:
        full = -(-gl.MAX_PLANNING_CASES // slots)
        expected = [(slots, block) for block in range(1, full + 1)] + [(n, None) for n in range(slots - 1, -1, -1)]
        data = [item for item in _bands_of(root, key) if item.tag.endswith("_DataBand")]
        assert [item.tag for item in data] == ["{}{}{}_DataBand".format(key, n, "B{}".format(block) if block else "")
                                               for n, block in expected]
        for (count, block), band in zip(expected, data):
            assert band.findtext("DataSourceName") == source
            filters = [_decode(value.text) for value in band.find("Filters")]
            assert filters == ["{}.col_count == {}".format(source, count)] + (
                ["{}.block == {}".format(source, block)] if block else [])
            assert len(list(band.find("Components"))) == 2 + count
        headers = [item for item in _bands_of(root, key) if item.tag.endswith("_HeaderBand")]
        # Stimulsoft leaves default values out of a page file: no PrintOnAllPages means True (repeated on every sheet).
        assert len(headers) == len(expected) and all(item.findtext("PrintOnAllPages") in (None, "True") for item in headers)


def test_no_radar_and_no_time_plot_with_more_than_two_series():
    # The assignment removes radar plots and the time plots of Reference with up to six cases.
    root = _root()
    for chart in _charts(root):
        area = chart.find("Area").get("type")
        assert "Radar" not in area, chart.tag
        if area.endswith("StiLineArea"):
            assert len(chart.find("Series")) <= 2, chart.tag
    text = _text("main") + _text("detail")
    for removed in ("ScriptedRadar", "ScriptedTrend", "chart_cases", "radar_note"):
        assert removed not in text, removed
    assert not _charts(_root("detail")), "the detail report holds registers, no charts"


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
    assert series.findtext("SortBy") in (None, "None"), "default (None) is left out of a page file"
    (limit,) = list(chart.find("ConstantLines"))
    assert limit.findtext("AxisValue") == "100"


@both
def test_no_lodf_remains_in_the_template(report):
    text = _text(report)
    assert "LODF" not in text.upper()
    assert "ScriptedLodfRanking" not in text


def test_case_definition_shows_outages_states_coverage_and_provenance():
    root = _root()
    fields = [root.find(".//CaseDef_C{}".format(i)).findtext("Text") for i in range(6)]
    assert fields == ["{ScriptedCases.%s}" % name for name in (
        "case_name", "outage_names", "reference_text", "states_text", "coverage_text", "provenance_text")]
    texts = {element.text for element in root.findall(".//Text")}
    assert "{ScriptedReportMeta.coverage_statement}" in texts


@both
def test_evidence_table_names_the_result_objects(report):
    root = _root(report)
    evidence = [root.find(".//Evidence_H{}".format(i)).findtext("Text") for i in range(8)]
    assert "Result object in PowerFactory" in evidence
    assert root.find(".//Evidence_DataBand").findtext("DataSourceName") == "ScriptedCalculationRuns"
    provenance = [root.find(".//Provenance_H{}".format(i)).findtext("Text") for i in range(6)]
    assert "PowerFactory path" in provenance


def test_metric_view_names_both_deltas():
    root = _root()
    headings = [root.find(".//Metrics_H{}".format(i)).findtext("Text") for i in range(7)]
    assert "Max. coincident increase vs REF" in headings and "Difference of maxima" in headings


@both
def test_every_data_source_is_read_in_a_stable_order(report):
    unordered = {"ScriptedReportMeta", "ScriptedModelQuality", "ScriptedKpis"}
    for source in _root(report).find(".//DataSources"):
        if source.tag not in unordered:
            assert "ORDER BY" in source.findtext("SqlCommand"), source.tag


def test_levels_are_ordered_n0_n1_and_n1_prime_and_events_per_report():
    def command(report, name):
        return next(source.findtext("SqlCommand") for source in _root(report).find(".//DataSources") if source.tag == name)
    for name in ("ScriptedCaseStatistics", "ScriptedCoverage"):
        assert "WHEN 'n-0' THEN 0 WHEN 'n-1' THEN 1 ELSE 2" in command("main", name)
    # The main report ranks the events per criterion, the detail report lists them per scenario.
    assert command("main", "ScriptedContingencyEvents").endswith('ORDER BY "criterion_order", "main_rank"')
    assert command("detail", "ScriptedContingencyEvents").endswith('ORDER BY "case_order", "row_order"')


@both
def test_mrt_contains_no_local_paths_or_obsolete_sources(report):
    text = _text(report)
    forbidden = (
        "/Users/", "/home/", "file://", "C:\\", "C:/",
        "ScriptedScenarios", "ScriptedOutages", "ScriptedScenario",
        "scenario_id", "scenario_name",
    )
    assert not [value for value in forbidden if value in text]


@both
def test_visible_report_text_is_english(report):
    root = _root(report)
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


def test_the_method_page_is_text_without_formulas():
    root = _root("detail")
    page = root.find("Pages/PageMethod")
    texts = [element.text or "" for element in page.iter("Text") if (element.text or "").strip()]
    assert len(texts) >= 7
    assert not [text for text in texts if re.search(r"[=∑Σ√]|max_t|\bmin\(|\bmax\(", text)]


@both
def test_no_chart_depends_on_a_data_relation(report):
    # PowerFactory's report engine ignores relations on charts and drew the
    # points of every plot into one chart. Charts must read their own table.
    root = _root(report)
    relations = root.find(".//Relations")
    assert relations is not None and len(relations) == 0
    for chart in _charts(root):
        assert not (chart.findtext("DataRelationName") or "").strip(), chart.tag
        assert chart.find("MasterComponent") is None, chart.tag
    charts = _charts(_root("main"))
    sources = [chart.findtext("DataSourceName") for chart in charts]
    assert len(charts) >= 9
    # One table per chart (the three case counts share theirs, one series each; the pies have their own).
    shared = {source for source in sources if sources.count(source) > 1}
    assert shared == {"ScriptedCaseCounts"}


@both
def test_every_declared_list_count_matches_its_children(report):
    # Stimulsoft allocates lists from the declared count; a mismatch was
    # introduced once by a band whose tiles each hold two text fields.
    mismatches = []
    for element in _root(report).iter():
        if element.get("isList") == "true":
            declared = int(element.get("count"))
            if declared != len(element):
                mismatches.append("{} declares {} but holds {}".format(
                    element.tag, declared, len(element)))
    assert mismatches == []


@both
def test_empty_lists_are_self_closing(report):
    # Stimulsoft 2025.3 reads the whitespace inside
    # <Components isList="true" count="0">...</Components> as a string item;
    # the designer then fails with "Unable to cast object of type
    # 'System.String' to type 'StiComponent'". An XML parser hides this, so
    # the raw text is checked.
    text = _text(report)
    offenders = re.findall(r'<(\w+) isList="true" count="0">\s*</\1>', text)
    assert offenders == []


@both
def test_table_rows_keep_their_grid_when_a_cell_wraps(report):
    # Wrapped names used to stretch one cell and leave the others short.
    root = _root(report)
    for band in root.iter():
        if band.get("type") != "DataBand" or not band.tag.endswith("DataBand"):
            continue
        if band.findtext("DataSourceName") == "ScriptedReportMeta":
            continue
        for cell in band.find("Components"):
            assert cell.findtext("GrowToHeight") == "True", cell.tag


@both
def test_no_number_depends_on_the_windows_culture(report):
    # PowerFactory runs on German Windows and printed 1,127 next to 1.127.
    # The report culture (en-US) is set when the report is assembled from its pages (see the reporting audit).
    root = _root(report)
    for fmt in root.iter("TextFormat"):
        if fmt.get("type") == "NumberFormat":
            assert fmt.findtext("UseLocalSetting") == "False"
    # Charts are drawn at export time with the thread culture, which the
    # report culture does not reach: no axis may print a culture decimal.
    for chart in _charts(root):
        area = chart.find("Area")
        if area.get("type").endswith("PieArea"):
            continue
        value_axis = "XAxis" if area.get("type").endswith(("BarArea", "GanttArea")) else "YAxis"
        labels = area.find(value_axis).find("Labels")
        assert labels is not None, chart.tag
        assert labels.findtext("Format") in ("0;-0;0", "0'.'000") or labels.findtext("Placement") == "None", chart.tag


@both
def test_the_template_carries_no_database_connection_or_local_path(report):
    text = _text(report)
    database = _root(report).find("Dictionary/Databases/SQLite")
    assert database is not None and database.findtext("ConnectionStringEncrypted") in (None, "")
    assert "<ConnectionStringEncrypted />" in text
    for fragment in ("Data Source", "C:\\", "AppData", "\\Temp\\", ".db;"):
        assert fragment not in text, fragment


@both
def test_empty_tables_show_a_note_instead_of_an_orphaned_header(report):
    root = _root(report)
    notes = [band for band in _components(root) if band.tag.endswith("None_Band")]
    assert len(notes) >= 6
    names = set(dict(gl.TABLES))
    for band in notes:
        (first, *_rest) = band.find("Filters")
        match = re.fullmatch(r'ScriptedReportMeta\.empty_tables\.Contains\(",(\w+),"\)', _decode(first.text))
        assert match and match[1] in names, band.tag


def test_new_main_charts_draw_the_planning_statistics():
    root = _root()
    gantt = root.find(".//OutageGanttChart")
    (series,) = list(gantt.find("Series"))
    assert gantt.find("Area").get("type").endswith("StiGanttArea") and series.get("type").endswith("StiGanttSeries")
    assert (series.findtext("ValueDataColumn"), series.findtext("ValueDataColumnEnd")) == (
        "ScriptedOutageWindows.start_hours", "ScriptedOutageWindows.end_hours")
    counts = root.find(".//ScenarioCountsColumns")
    assert counts.findtext("DataSourceName") == "ScriptedCaseStatusCounts"
    assert counts.find("Area").get("type").endswith("StiStackedColumnArea")
    assert [item.findtext("Title") for item in counts.find("Series")] == ["NEW", "WORSENED", "IMPROVED", "RESOLVED"]
    assert [item.findtext("Brush") for item in counts.find("Series")] == ["[181:18:62]", "[217:140:31]", "[31:119:180]", "[44:160:101]"]
    assert counts.find("Area/XAxis").find("ShowEdgeValues") is None, "categories in the middle of their slots"
    ranking = root.find(".//ContingencyRankingChart")
    assert ranking.findtext("DataSourceName") == "ScriptedContingencyRanking"
    assert [item.findtext("ValueDataColumn") for item in ranking.find("Series")] == ["ScriptedContingencyRanking.finding_count"]
    course = root.find(".//TimeCourseChart")
    series = list(course.find("Series"))
    assert course.findtext("DataSourceName") == "ScriptedTimeCriticality" and len(series) == 2
    assert series[0].findtext("LineColor") == "140, 150, 160", "the n-1 reference is grey"
    assert [item.findtext("ValueDataColumn") for item in series] == [
        "ScriptedTimeCriticality." + gl.series_value_field(0), "ScriptedTimeCriticality." + gl.series_value_field(1)]


def test_the_main_report_lists_top_findings_and_the_detail_report_every_listed_one():
    def filters(report, prefix):
        band = next(item for item in _components(_root(report)) if item.tag == prefix + "_DataBand")
        return [_decode(value.text) for value in band.find("Filters")]
    assert filters("main", "TopEvents") == ["ScriptedContingencyEvents.main_rank > 0"]
    assert filters("detail", "Events") == []
    assert filters("main", "ReferenceFindings") == ["ScriptedReferenceFindings.main_rank > 0"]
    assert filters("detail", "BaseFindings") == ['ScriptedReferenceFindings.level == "n-0"']


@both
def test_no_group_bands_because_powerfactory_cannot_compile_their_conditions(report):
    # PowerFactory compiles the report and stopped with "The name 'ScriptedCaseComparison' does not exist in the current
    # context" for every group condition (26 Oct 2026). Tables show the case as a column; blocks are band pairs.
    root = _root(report)
    assert not [band.tag for band in root.iter() if band.get("type") == "GroupHeaderBand"]
    assert not list(root.iter("Condition"))
def test_every_declared_field_is_printed_by_a_template():
    # Only what a report prints is declared and written to PowerFactory; the script's own figures stay unpublished
    # (UNPUBLISHED_FIELDS). A declared field nobody shows only costs writes and confuses the designer.
    used = ""
    for report in TEMPLATES:
        text = re.sub(r"<Columns isList.*?</Columns>", "", _text(report), flags=re.S)
        used += _decode(text)
    unused = [(name, field) for name, fields in gl.TABLES for field, _ in fields
              if not re.search(r'({}\.{}\b)|("{}")'.format(name, field, field), used)]
    assert unused == []


@both
def test_every_field_a_template_uses_is_declared(report):
    # A field the report reads but the contract does not declare stops the export in PowerFactory ("Missing field").
    declared = {(name, field) for name, fields in gl.TABLES for field, _ in fields}
    text = _decode(_text(report))
    assert sorted(set(re.findall(r"\b(Scripted[A-Za-z]+)\.([a-z_]+)\b", text)) - declared) == []


def test_the_pages_are_the_only_source_of_the_reports():
    # Hadi assembles each report in the designer: dictionary, then Open Page in file order. No .mrt in the delivery.
    for report, name in TEMPLATES.items():
        folder = report_folder(name)
        assert len(list(folder.glob("*.dct"))) == 1 and len(list(folder.glob("*.pg"))) == len(CHAPTER_PAGES[report])
        assert not list(folder.glob("*.mrt")) and not delivered(name + ".mrt").exists()
