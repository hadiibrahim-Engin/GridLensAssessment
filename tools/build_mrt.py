"""Generate powerfactory/MASTER_GRIDLENS.mrt, the Stimulsoft template of the GridLens report.

Development tool, not part of the delivery. It rewrites the template from
`gridlens_report.TABLES` (the data sources) and from the building blocks below
(the landscape pages of GridLens_Template_Optimiert_v2.pdf). It keeps three
things of the existing file: the SQLite database definition, the embedded logo
and everything after the page list, so it can run on its own output.

    python3 tools/build_mrt.py
"""

from __future__ import annotations

import hashlib
import importlib.util
import re
import sys
from pathlib import Path
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parents[1]
MRT = ROOT / "powerfactory" / "MASTER_GRIDLENS.mrt"
SCRIPT = ROOT / "powerfactory" / "gridlens_report.py"

spec = importlib.util.spec_from_file_location("gridlens_report_build", SCRIPT)
gl = importlib.util.module_from_spec(spec)
sys.modules["gridlens_report_build"] = gl
spec.loader.exec_module(gl)

PAGE_W, PAGE_H = 29.7, 21.0
MARGIN_X, MARGIN_Y = 1.5, 1.2
W = round(PAGE_W - 2 * MARGIN_X, 2)  # content width
BODY_H = round(PAGE_H - 2 * MARGIN_Y, 2)
RED = "[181:18:62]"
RED_RGB = "181, 18, 62"
GREY_RGB = "140, 150, 160"
INK = "[55:55:55]"
MUTED = "[90:90:90]"
LINE = "[155:155:155]"
HEADER_FILL = "[120:120:120]"
BORDER_ALL = "All;[155:155:155];0.5;Solid;False;4;Black"
BORDER_NONE = "None;Transparent;0;None;False;4;Black"
FONT = "Segoe UI"
# One colour per case slot, REF first. Colour is identity only, never severity.
SLOT_COLOURS = ("140, 150, 160", "181, 18, 62", "31, 119, 180", "217, 140, 31", "44, 160, 101", "112, 72, 160", "60, 60, 60")
FOOTER_TEXT = "PRE-ASSESSMENT | NOT FOR OPERATIONAL USE"
# Row pitch of the table of contents: 19 entries must fit between page header and footer.
TOC_PITCH = 0.7
META = "ScriptedReportMeta"


def name_encode(value: str) -> str:
    """Stimulsoft's XML-name encoding used inside condition and filter strings."""
    out = []
    for index, char in enumerate(value):
        valid = char.isalpha() or char == "_" or (index > 0 and (char.isdigit() or char in ".-"))
        out.append(char if valid else "_x{:04X}_".format(ord(char)))
    return "".join(out)


class Builder:
    def __init__(self, first_ref: int):
        self.n = first_ref
        self.page_ref = 0
        self.names: set[str] = set()

    def ref(self) -> int:
        self.n += 1
        return self.n

    def unique(self, name: str) -> str:
        assert name not in self.names, name
        self.names.add(name)
        return name


def esc(text: str) -> str:
    return escape(text)


def conditions_xml(conditions):
    if not conditions:
        return '<Conditions isList="true" count="0" />'
    items = "".join("<value>{}</value>".format(esc(item)) for item in conditions)
    return '<Conditions isList="true" count="{}">{}</Conditions>'.format(len(conditions), items)


def condition(field: str, operator: str, value: str, kind: str, text_colour: str, back_colour: str, font: str) -> str:
    return "{},{},{},,{},{},{},{},True,False,".format(
        field, operator, name_encode(value), kind, text_colour, back_colour, name_encode(font))


def violation_conditions(source: str, bold_size="8"):
    return [
        condition(source + ".violation", "EqualTo", "1", "Numeric", "[145:13:48]", "[255:232:237]", "{},{},Bold".format(FONT, bold_size)),
        condition(source + ".violation", "EqualTo", "2", "Numeric", "[122:86:0]", "[255:243:205]", "{},{}".format(FONT, bold_size)),
    ]


def text(b: Builder, parent: int, name: str, x, y, w, h, value: str, *, font=None, colour=INK, fill="Transparent", border=BORDER_NONE,
         align=None, valign="Center", margins="0.12,0.12,0,0", grow=False, grow_to_height=False, bookmark=None, hyperlink=None,
         conditions=None) -> str:
    ref = b.ref()
    name = b.unique(name)
    font = font or "{},9".format(FONT)
    lines = [
        '<{} Ref="{}" type="Text" isKey="true">'.format(name, ref),
        "<Border>{}</Border>".format(border),
    ]
    if bookmark:
        lines.insert(1, "<Bookmark>{}</Bookmark>".format(bookmark))
    lines += [
        "<Brush>{}</Brush>".format(fill),
        "<CanGrow>True</CanGrow>" if grow else "",
        "<ClientRectangle>{},{},{},{}</ClientRectangle>".format(x, y, w, h),
        conditions_xml(conditions),
        '<Expressions isList="true" count="0" />',
        "<Font>{}</Font>".format(font),
        "<HorAlignment>{}</HorAlignment>".format(align) if align else "",
        "<Hyperlink>{}</Hyperlink>".format(hyperlink) if hyperlink else "",
        "<Margins>{}</Margins>".format(margins),
        "<Name>{}</Name>".format(name),
        '<Page isRef="{}" />'.format(b.page_ref),
        '<Parent isRef="{}" />'.format(parent),
        "<Pointer>{}</Pointer>".format(bookmark) if bookmark else "",
        "<Text>{}</Text>".format(esc(value)),
        "<TextBrush>{}</TextBrush>".format(colour),
        "<TextOptions>,,,,WordWrap=True,A=0</TextOptions>",
        "<VertAlignment>{}</VertAlignment>".format(valign),
        "<GrowToHeight>True</GrowToHeight>" if grow_to_height else "",
        "</{}>".format(name),
    ]
    return "".join(line for line in lines if line)


def image(b: Builder, parent: int, name: str, x, y, w, h, data: str) -> str:
    ref = b.ref()
    name = b.unique(name)
    return ('<{n} Ref="{r}" type="Image" isKey="true"><AspectRatio>True</AspectRatio><Brush>Transparent</Brush>'
            "<ClientRectangle>{x},{y},{w},{h}</ClientRectangle>{c}"
            '<Expressions isList="true" count="0" /><IconColor>68, 114, 196</IconColor><ImageBytes>{d}</ImageBytes><Stretch>True</Stretch>'
            '<Name>{n}</Name><Page isRef="{p}" /><Parent isRef="{q}" /></{n}>').format(
        n=name, r=ref, x=x, y=y, w=w, h=h, c=conditions_xml(None), d=data, p=b.page_ref, q=parent)


def band(b: Builder, kind: str, name: str, ref: int, y, h, children: list[str], *, source=None, new_page=False, can_break=None,
         print_on_all=None, filters=None, extra="") -> str:
    name = b.unique(name)
    parts = ['<{} Ref="{}" type="{}" isKey="true">'.format(name, ref, kind), "<Brush>Transparent</Brush>"]
    if kind == "DataBand":
        parts.append('<BusinessObjectGuid isNull="true" />')
    if can_break is not None:
        parts.append("<CanBreak>{}</CanBreak>".format(can_break))
    parts.append("<ClientRectangle>0,{},{},{}</ClientRectangle>".format(y, W, h))
    parts.append('<Components isList="true" count="{}">{}</Components>'.format(len(children), "".join(children)))
    parts.append(extra)
    parts.append(conditions_xml(None))
    if source:
        parts.append("<DataSourceName>{}</DataSourceName>".format(source))
    parts.append('<Expressions isList="true" count="0" />')
    if kind == "DataBand":
        if filters:
            parts.append('<Filters isList="true" count="{}">{}</Filters>'.format(
                len(filters), "".join("<value>{}</value>".format(name_encode(item)) for item in filters)))
        else:
            parts.append('<Filters isList="true" count="0" />')
    parts.append("<Name>{}</Name>".format(name))
    if new_page:
        parts.append("<NewPageBefore>True</NewPageBefore>")
    parts.append('<Page isRef="{}" /><Parent isRef="{}" />'.format(b.page_ref, b.page_ref))
    if print_on_all is not None:
        parts.append("<PrintOnAllPages>{}</PrintOnAllPages>".format(print_on_all))
    if kind == "DataBand":
        parts.append('<Sort isList="true" count="0" />')
    parts.append("</{}>".format(name))
    return "".join(parts)


class Flow:
    """Collects the bands of the page; y positions only keep them apart in the designer."""

    def __init__(self, b: Builder):
        self.b = b
        self.y = 0.0
        self.parts: list[str] = []
        self.sections: list[tuple[str, str]] = []

    def add(self, builder, height):
        """`builder(parent_ref, y)` returns the band XML; the band's own ref is allocated first."""
        ref = self.b.ref()
        self.parts.append(builder(ref, round(self.y, 2)))
        self.y += height + 0.1


def section_title(f: Flow, key: str, number: str, title: str, subtitle: str, *, new_page=True):
    b = f.b
    marker = "section-" + key
    f.sections.append((marker, number + "  " + title))

    def make(ref, y):
        kids = [
            text(b, ref, key + "_Accent", 0, 0.35, 0.28, 1.05, "", fill=RED),
            text(b, ref, key + "_Title", 0.55, 0.3, W - 0.55, 1.15, title, font="{},20,Bold".format(FONT), colour=INK, bookmark=marker),
            text(b, ref, key + "_Subtitle", 0.55, 1.45, W - 0.55, 0.6, subtitle, font="{},9".format(FONT), colour=MUTED, grow=True),
        ]
        return band(b, "DataBand", key + "_TitleBand", ref, y, 2.25, kids, source=META, new_page=new_page, can_break=False)

    f.add(make, 2.25)


def note_box(f: Flow, key: str, value: str, *, fill="[247:248:250]", border="All;[190:195:205];0.5;Solid;False;4;Black", colour=INK, height=1.3, source=META,
             font=None, filters=None):
    b = f.b

    def make(ref, y):
        kids = [text(b, ref, key + "_Text", 0.2, 0.1, W - 0.4, height - 0.2, value, fill=fill, border=border, colour=colour, grow=True,
                     font=font or "{},9".format(FONT), margins="0.3,0.3,0.1,0.1")]
        return band(b, "DataBand", key + "_Band", ref, y, height, kids, source=source, can_break=False, filters=filters)

    f.add(make, height)


def table(f: Flow, key: str, source: str, columns: list[dict], *, row_h=0.62, header_h=0.62, subheading=None, conditions=None, group=None,
          header_expressions=False, filters=None, print_on_all="True"):
    """A header band and a data band; `group` makes the header repeat for every value of the condition."""
    b = f.b
    if subheading:
        def make_sub(ref, y):
            kids = [text(b, ref, key + "_SubheadingText", 0, 0.2, W, 0.6, subheading, font="{},11,Bold".format(FONT), colour=INK)]
            return band(b, "HeaderBand", key + "_SubheadingBand", ref, y, 0.9, kids, print_on_all="False")
        f.add(make_sub, 0.9)

    def header_cells(ref, top=0.0):
        cells, x = [], 0.0
        for index, column in enumerate(columns):
            label = column["header"]
            cells.append(text(b, ref, "{}_H{}".format(key, index), x, top, column["width"], header_h, label, border=BORDER_ALL, fill=HEADER_FILL,
                              font="{},8.5,Bold".format(FONT), colour="White", align=column.get("align"), grow=True, grow_to_height=True))
            x += column["width"]
        return cells

    if group:
        def make_group(ref, y):
            kids, top = [], 0.0
            if group.get("title"):
                kids.append(text(b, ref, key + "_GroupTitle", 0, 0.15, W, 0.6, group["title"], font="{},10.5,Bold".format(FONT), colour=INK, grow=True))
                top += 0.8
            if group.get("note"):
                kids.append(text(b, ref, key + "_GroupNote", 0, top, W, 0.55, group["note"], font="{},8".format(FONT), colour=MUTED, grow=True))
                top += 0.6
            kids += header_cells(ref, top)
            return band(b, "GroupHeaderBand", key + "_GroupHeaderBand", ref, y, top + header_h, kids,
                        extra="<Condition>{}</Condition><KeepGroupTogether>True</KeepGroupTogether>".format(esc(group["condition"])))
        f.add(make_group, 2.0)
    else:
        def make_header(ref, y):
            return band(b, "HeaderBand", key + "_HeaderBand", ref, y, header_h, header_cells(ref), print_on_all=print_on_all)
        f.add(make_header, header_h)

    def make_data(ref, y):
        cells, x = [], 0.0
        for index, column in enumerate(columns):
            cells.append(text(b, ref, "{}_C{}".format(key, index), x, 0, column["width"], row_h, column["expr"], border=BORDER_ALL,
                              font="{},{}".format(FONT, column.get("size", "8.5")), align=column.get("align"), grow=True, grow_to_height=True,
                              conditions=column["conditions"] if "conditions" in column else conditions))
            x += column["width"]
        return band(b, "DataBand", key + "_DataBand", ref, y, row_h, cells, source=source, can_break=True, filters=filters)
    f.add(make_data, row_h)


def col(header, field, width, source, align=None, size="8.5"):
    return {"header": header, "expr": "{{{}.{}}}".format(source, field), "width": width, "align": align, "size": size}


# ---------------------------------------------------------------------------
# Charts
# ---------------------------------------------------------------------------
AXIS = "140, 140, 140"


def _axis_title(b, parent_ref, area_ref, kind, text_value, direction):
    return ('<Title Ref="{}" type="Stimulsoft.Report.Chart.StiAxisTitle" isKey="true"><Color>{}</Color><Direction>{}</Direction>'
            "<Font>{},9,Bold</Font><Text>{}</Text></Title>").format(b.ref(), AXIS, direction, FONT, esc(text_value))


def _labels(b, axis_ref, fmt=None, step=None, angle=None, hidden=False):
    return ('<Labels Ref="{}" type="Stimulsoft.Report.Chart.StiAxisLabels" isKey="true"><Axis isRef="{}" />{}<Color>{}</Color>'
            "<Font>{},8</Font>{}{}{}</Labels>").format(
        b.ref(), axis_ref, "<Angle>{}</Angle>".format(angle) if angle else "", AXIS, FONT,
        "<Format>{}</Format>".format(fmt) if fmt else "", "<Placement>None</Placement>" if hidden else "",
        "<Step>{}</Step>".format(step) if step else "")


def _xy_area(b, chart_ref: int, area_kind: str, *, x_title="", y_title="", y_format=None, x_format=None, x_angle=30, x_step=None, y_hidden=False,
             bars=False, start_from_zero=False, x_start_zero=False):
    area_ref = b.ref()
    x_ref, y_ref, yr_ref, xt_ref = b.ref(), b.ref(), b.ref(), b.ref()
    grid = ('<GridLinesHor Ref="{}" type="Stimulsoft.Report.Chart.StiGridLinesHor" isKey="true"><Area isRef="{}" /><Color>225, 225, 225</Color>'
            "<MinorColor>240, 240, 240</MinorColor></GridLinesHor>").format(b.ref(), area_ref)
    grid_v = ('<GridLinesVert Ref="{}" type="Stimulsoft.Report.Chart.StiGridLinesVert" isKey="true"><Area isRef="{}" /><Color>225, 225, 225</Color>'
              "<MinorColor>240, 240, 240</MinorColor></GridLinesVert>").format(b.ref(), area_ref)
    hidden_right = ('<GridLinesHorRight Ref="{}" type="Stimulsoft.Report.Chart.StiGridLinesHor" isKey="true"><Area isRef="{}" /><Color>Silver</Color>'
                    "<MinorColor>Gainsboro</MinorColor><Visible>False</Visible></GridLinesHorRight>").format(b.ref(), area_ref)
    xml = ('<Area Ref="{a}" type="Stimulsoft.Report.Chart.{k}" isKey="true"><BorderColor>Transparent</BorderColor><Brush>[255:255:255]</Brush>'
           '<Chart isRef="{c}" />{g}{gr}{gv}'
           '<XAxis Ref="{x}" type="Stimulsoft.Report.Chart.StiXBottomAxis" isKey="true"><Area isRef="{a}" />{xl}<LineColor>{ax}</LineColor>'
           "{xstep}<StartFromZero>{xz}</StartFromZero>{xt}</XAxis>"
           '<XTopAxis Ref="{xt_ref}" type="Stimulsoft.Report.Chart.StiXTopAxis" isKey="true"><Area isRef="{a}" /><Visible>False</Visible></XTopAxis>'
           '<YAxis Ref="{y}" type="Stimulsoft.Report.Chart.StiYLeftAxis" isKey="true"><Area isRef="{a}" /><LineColor>{ax}</LineColor>'
           "<StartFromZero>{sz}</StartFromZero>{yt}{yl}</YAxis>"
           '<YRightAxis Ref="{yr}" type="Stimulsoft.Report.Chart.StiYRightAxis" isKey="true"><Area isRef="{a}" /><Visible>False</Visible></YRightAxis>'
           "</Area>").format(
        a=area_ref, k=area_kind, c=chart_ref, g=grid, gr=hidden_right, gv=grid_v, x=x_ref, ax=AXIS,
        xl=_labels(b, x_ref, fmt=x_format, angle=x_angle, step=x_step), xstep=("<Step>{}</Step>".format(x_step) if x_step else "") + "<ShowEdgeValues>True</ShowEdgeValues>",
        xt=_axis_title(b, chart_ref, area_ref, "x", x_title, "LeftToRight"), xt_ref=xt_ref, y=y_ref,
        sz="True" if start_from_zero else "False", xz="True" if x_start_zero else "False", yt=_axis_title(b, chart_ref, area_ref, "y", y_title, "BottomToTop"),
        yl=_labels(b, y_ref, fmt=y_format, hidden=y_hidden), yr=yr_ref)
    return xml


def _legend(b, chart_ref, *, vert="TopOutside", hor="Right", columns=None):
    return ('<Legend Ref="{}" type="Stimulsoft.Report.Chart.StiLegend" isKey="true"><BorderColor>Transparent</BorderColor><Brush>[255:255:255]</Brush>'
            '<Chart isRef="{}" />{}<Direction>LeftToRight</Direction><Font>{},8.5</Font><HorAlignment>{}</HorAlignment><LabelsColor>70, 70, 70</LabelsColor>'
            "<MarkerSize>10, 10</MarkerSize><ShowShadow>False</ShowShadow><VertAlignment>{}</VertAlignment></Legend>").format(
        b.ref(), chart_ref, "<Columns>{}</Columns>".format(columns) if columns else "", FONT, hor, vert)


def _labels_none(b, chart_ref, kind="StiNoneLabels"):
    return ('<SeriesLabels Ref="{}" type="Stimulsoft.Report.Chart.{}" isKey="true"><Chart isRef="{}" /><MarkerSize>8, 6</MarkerSize>'
            "<ValueTypeSeparator>-</ValueTypeSeparator><Width>0</Width></SeriesLabels>").format(b.ref(), kind, chart_ref)


def _series_labels(b, chart_ref, kind, visible=True):
    return ('<SeriesLabels Ref="{}" type="Stimulsoft.Report.Chart.{}" isKey="true"><BorderColor>Transparent</BorderColor><Brush>[119:255:255:255]</Brush>'
            '<Chart isRef="{}" /><Font>{},8</Font><LabelColor>50, 58, 69</LabelColor><MarkerSize>8, 6</MarkerSize>'
            "<ValueTypeSeparator>-</ValueTypeSeparator>{}<Width>0</Width></SeriesLabels>").format(
        b.ref(), kind, chart_ref, FONT, "" if visible else "<Visible>False</Visible>")


def _chart_wrap(b, parent, name, x, y, w, h, source, area_xml, series_xml, series_count, legend_xml, title, chart_ref, *, constants="", labels_kind=None,
                chart_title_font="9,Bold"):
    name = b.unique(name)
    return ('<{n} Ref="{r}" type="Stimulsoft.Report.Chart.StiChart" isKey="true">{area}<Border>{border}</Border><Brush>[255:255:255]</Brush>'
            '<ClientRectangle>{x},{y},{w},{h}</ClientRectangle>{cond}{const}<CustomStyleName />'
            '<DataSourceName>{src}</DataSourceName><Expressions isList="true" count="0" /><Filters isList="true" count="0" />{legend}'
            '<Name>{n}</Name><Page isRef="{p}" /><Parent isRef="{q}" /><Series isList="true" count="{sc}">{series}</Series>{sl}'
            '<SeriesLabelsConditions isList="true" count="0" /><Sort isList="true" count="0" /><Strips isList="true" count="0" />'
            '<Style Ref="{sr}" type="Stimulsoft.Report.Chart.StiStyle29" isKey="true"><Conditions isList="true" count="0" /><Name /></Style>'
            '<Title Ref="{tr}" type="Stimulsoft.Report.Chart.StiChartTitle" isKey="true"><Font>{fnt},{ts}</Font><Text>{title}</Text>'
            "<Visible>{tv}</Visible></Title></{n}>").format(
        n=name, r=chart_ref, area=area_xml, border=BORDER_NONE, x=x, y=y, w=w, h=h, cond=conditions_xml(None),
        const=constants or '<ConstantLines isList="true" count="0" />', src=source, legend=legend_xml, p=b.page_ref, q=parent,
        sc=series_count, series=series_xml,
        sl=_series_labels(b, chart_ref, labels_kind) if labels_kind else _labels_none(b, chart_ref), sr=b.ref(), tr=b.ref(), fnt=FONT, ts=chart_title_font,
        title=esc(title), tv="True" if title else "False")


def constant_line(b, value, text_value, orientation):
    return ('<ConstantLines isList="true" count="1"><Item1 Ref="{}" type="Stimulsoft.Report.Chart.StiConstantLines" isKey="true">'
            "<AxisValue>{}</AxisValue><Font>{},7</Font><LineColor>85, 85, 85</LineColor><LineStyle>Dash</LineStyle><LineWidth>1.5</LineWidth>"
            "<Orientation>{}</Orientation><ShowInLegend>False</ShowInLegend><Text>{}</Text></Item1></ConstantLines>").format(
        b.ref(), value, FONT, orientation, esc(text_value))


def line_series(b, chart_ref, source, arg, value, title, colour, *, width=2, marker=False, labels=False, series_name=None):
    return ('<{n} Ref="{r}" type="Stimulsoft.Report.Chart.StiLineSeries" isKey="true"><AllowApplyStyle>False</AllowApplyStyle>'
            "<ArgumentDataColumn>{src}.{arg}</ArgumentDataColumn>"
            '<Chart isRef="{c}" /><Conditions isList="true" count="0" /><Filters isList="true" count="0" /><Lighting>False</Lighting>'
            "<LineColor>{col}</LineColor><LineColorNegative>Firebrick</LineColorNegative><LineWidth>{w}</LineWidth>"
            '<Marker Ref="{mr}" type="Stimulsoft.Report.Chart.StiMarker" isKey="true"><BorderColor>{col}</BorderColor><Brush>[{mb}]</Brush>'
            "<Visible>{mv}</Visible></Marker>{sl}<ShowShadow>False</ShowShadow><ShowZeros>True</ShowZeros><Title>{title}</Title>"
            '<TrendLines isList="true" count="0" /><ValueDataColumn>{src}.{val}</ValueDataColumn></{n}>').format(
        n=series_name, r=b.ref(), src=source, arg=arg, c=chart_ref, col=colour, w=width,
        mr=b.ref(), mb=colour.replace(", ", ":"), mv="True" if marker else "False",
        sl=_series_labels(b, chart_ref, "StiOutsideEndAxisLabels", visible=labels), title=esc(title), val=value)


def line_chart(b, parent, name, x, y, w, h, source, arg, series, *, y_title, y_format="0;-0;0", x_angle=30, x_step=None, const=None, legend=True,
               title="", marker=False, labels=False, y_hidden=False, start_from_zero=False, sort_none=True):
    chart_ref = b.ref()
    area = _xy_area(b, chart_ref, "StiLineArea", y_title=y_title, y_format=y_format, x_angle=x_angle, x_step=x_step, y_hidden=y_hidden,
                    start_from_zero=start_from_zero)
    xml_series = "".join(line_series(b, chart_ref, source, arg, value, label, colour, width=width, marker=marker, labels=labels,
                                     series_name="Series{}{}".format(name, index))
                         for index, (value, label, colour, width) in enumerate(series))
    constants = constant_line(b, const[0], const[1], const[2]) if const else ""
    return _chart_wrap(b, parent, name, x, y, w, h, source, area, xml_series, len(series),
                       _legend(b, chart_ref) if legend else _legend(b, chart_ref).replace("<Brush>", "<Visible>False</Visible><Brush>", 1),
                       title, chart_ref, constants=constants, labels_kind="StiOutsideEndAxisLabels" if labels else None)


def bar_chart(b, parent, name, x, y, w, h, source, arg, value, colour, *, y_title, const=None, title=""):
    chart_ref = b.ref()
    area = _xy_area(b, chart_ref, "StiClusteredBarArea", y_title="", x_title=y_title, y_format=None, x_format="0;-0;0", x_angle=0, bars=True,
                    start_from_zero=False, x_start_zero=True)
    series = ('<Series{n} Ref="{r}" type="Stimulsoft.Report.Chart.StiClusteredBarSeries" isKey="true"><AllowApplyBrushNegative>False</AllowApplyBrushNegative>'
              "<AllowApplyStyle>False</AllowApplyStyle><ArgumentDataColumn>{src}.{arg}</ArgumentDataColumn>"
              '<Brush>[{col}]</Brush><BorderColor>{bc}</BorderColor><Chart isRef="{c}" /><Conditions isList="true" count="0" />'
              '<Filters isList="true" count="0" />{sl}<SortBy>None</SortBy><Title>{t}</Title><ValueDataColumn>{src}.{val}</ValueDataColumn></Series{n}>').format(
        n=name, r=b.ref(), src=source, arg=arg, col=colour.replace(", ", ":"), bc=colour, c=chart_ref,
        sl=_series_labels(b, chart_ref, "StiInsideEndAxisLabels", visible=True), t=esc(title or "Maximum loading"), val=value)
    constants = constant_line(b, const[0], const[1], const[2]) if const else ""
    legend = _legend(b, chart_ref).replace("<Brush>", "<Visible>False</Visible><Brush>", 1)
    return _chart_wrap(b, parent, name, x, y, w, h, source, area, series, 1, legend, "", chart_ref, constants=constants)


def pie_chart(b, parent, name, x, y, w, h, source, title, colours):
    chart_ref = b.ref()
    area = ('<Area Ref="{}" type="Stimulsoft.Report.Chart.StiPieArea" isKey="true"><BorderColor>Transparent</BorderColor><Brush>[255:255:255]</Brush>'
            '<Chart isRef="{}" /></Area>').format(b.ref(), chart_ref)
    conditions = [colour + ",Argument,String,EqualTo," + name_encode(label) + ",Circle,0" for label, colour in colours]
    series = ('<Series{n} Ref="{r}" type="Stimulsoft.Report.Chart.StiPieSeries" isKey="true"><AllowApplyStyle>True</AllowApplyStyle>'
              "<ValueDataColumn>{src}.element_count</ValueDataColumn><ArgumentDataColumn>{src}.class_label</ArgumentDataColumn>"
              '<BorderColor>White</BorderColor><Chart isRef="{c}" />{cond}<Filters isList="true" count="0" />'
              '<SeriesLabels Ref="{sl}" type="Stimulsoft.Report.Chart.StiCenterPieLabels" isKey="true"><BorderColor>Transparent</BorderColor>'
              '<Brush>[245:245:245]</Brush><Chart isRef="{c}" /><Font>{f},8</Font><LabelColor>70, 70, 70</LabelColor><MarkerSize>8, 6</MarkerSize>'
              "<ValueTypeSeparator>-</ValueTypeSeparator></SeriesLabels><Title>{t}</Title></Series{n}>").format(
        n=name, r=b.ref(), src=source, c=chart_ref, cond=conditions_xml(conditions).replace("<Conditions", "<Conditions", 1), sl=b.ref(), f=FONT,
        t=esc(title))
    legend = ('<Legend Ref="{}" type="Stimulsoft.Report.Chart.StiLegend" isKey="true"><BorderColor>Transparent</BorderColor><Brush>[255:255:255]</Brush>'
              '<Chart isRef="{}" /><Font>{},8.5</Font><HorAlignment>Center</HorAlignment><HorSpacing>12</HorSpacing><LabelsColor>70, 70, 70</LabelsColor>'
              "<MarkerSize>8, 8</MarkerSize><ShowShadow>False</ShowShadow><VertSpacing>1</VertSpacing><Visible>True</Visible>"
              "<VertAlignment>BottomOutside</VertAlignment></Legend>").format(b.ref(), chart_ref, FONT)
    chart = _chart_wrap(b, parent, name, x, y, w, h, source, area, series, 1, legend, title, chart_ref, chart_title_font="10,Bold")
    chart_labels = ('<SeriesLabels Ref="{}" type="Stimulsoft.Report.Chart.StiCenterPieLabels" isKey="true"><BorderColor>Transparent</BorderColor>'
                    "<Brush>[245:245:245]</Brush><Chart isRef=\"{}\" /><Font>{},8</Font><LabelColor>70, 70, 70</LabelColor>"
                    "<LegendValueType>Argument</LegendValueType><MarkerSize>8, 6</MarkerSize><ValueTypeSeparator>-</ValueTypeSeparator></SeriesLabels>").format(
        b.ref(), chart_ref, FONT)
    # the legend names the classes: chart-level labels with LegendValueType=Argument replace the none-labels
    return re.sub(r'<SeriesLabels Ref="\d+" type="Stimulsoft.Report.Chart.StiNoneLabels".*?</SeriesLabels>', lambda m: chart_labels, chart, count=1,
                  flags=re.S)


def radar_chart(b, parent, name, x, y, w, h, source, series):
    chart_ref = b.ref()
    area_ref = b.ref()
    area = ('<Area Ref="{a}" type="Stimulsoft.Report.Chart.StiRadarAreaArea" isKey="true"><BorderColor>Transparent</BorderColor>'
            '<BorderThickness>1</BorderThickness><Brush>EmptyBrush</Brush><Chart isRef="{c}" />'
            '<GridLinesHor Ref="{g1}" type="Stimulsoft.Report.Chart.StiRadarGridLinesHor" isKey="true"><Area isRef="{a}" /><Color>90, 105, 105, 105</Color></GridLinesHor>'
            '<GridLinesVert Ref="{g2}" type="Stimulsoft.Report.Chart.StiRadarGridLinesVert" isKey="true"><Area isRef="{a}" /><Color>90, 105, 105, 105</Color></GridLinesVert>'
            '<XAxis Ref="{x}" type="Stimulsoft.Report.Chart.StiXRadarAxis" isKey="true"><Area isRef="{a}" />'
            '<Labels Ref="{xl}" type="Stimulsoft.Report.Chart.StiRadarAxisLabels" isKey="true"><BorderColor>Black</BorderColor><Brush>EmptyBrush</Brush>'
            "<Color>70, 70, 70</Color><Font>{f},9,Bold</Font></Labels></XAxis>"
            '<YAxis Ref="{y}" type="Stimulsoft.Report.Chart.StiYRadarAxis" isKey="true"><Area isRef="{a}" />'
            '<Labels Ref="{yl}" type="Stimulsoft.Report.Chart.StiAxisLabels" isKey="true"><Color>140, 140, 140</Color><Font>{f},7</Font>'
            "<Placement>None</Placement></Labels><LineColor>140, 140, 140</LineColor></YAxis></Area>").format(
        a=area_ref, c=chart_ref, g1=b.ref(), g2=b.ref(), x=b.ref(), xl=b.ref(), y=b.ref(), yl=b.ref(), f=FONT)
    xml_series = []
    for index, (value, label, colour) in enumerate(series):
        xml_series.append(
            ('<Series{nm}{i} Ref="{r}" type="Stimulsoft.Report.Chart.StiRadarLineSeries" isKey="true"><AllowApplyStyle>False</AllowApplyStyle>'
             "<ArgumentDataColumn>{src}.metric_label</ArgumentDataColumn><Chart isRef=\"{c}\" /><Conditions isList=\"true\" count=\"0\" />"
             '<Filters isList="true" count="0" /><LineColor>{col}</LineColor><LineWidth>2</LineWidth>'
             '<Marker Ref="{mr}" type="Stimulsoft.Report.Chart.StiMarker" isKey="true"><BorderColor>{col}</BorderColor><Brush>[{mb}]</Brush></Marker>'
             "{sl}<ShowShadow>False</ShowShadow><SortBy>None</SortBy><Title>{t}</Title><ValueDataColumn>{src}.{v}</ValueDataColumn></Series{nm}{i}>").format(
                nm=name, i=index, r=b.ref(), src=source, c=chart_ref, col=colour, mr=b.ref(), mb=colour.replace(", ", ":"),
                sl=_series_labels(b, chart_ref, "StiCenterAxisLabels", visible=False), t=esc(label), v=value))
    return _chart_wrap(b, parent, name, x, y, w, h, source, area, "".join(xml_series), len(series), _legend(b, chart_ref, vert="BottomOutside", hor="Center"),
                       "", chart_ref)


def chart_band(f: Flow, key: str, height: float, charts, *, source=META, filters=None, new_page=False, title=None):
    """`charts` is a list of callables (builder, ref) -> xml, placed in one band that cannot break."""
    b = f.b

    def make(ref, y):
        kids = []
        if title:
            kids.append(text(b, ref, key + "_Title", 0, 0.1, W, 0.6, title, font="{},10,Bold".format(FONT), colour=INK))
        kids += [chart(b, ref) for chart in charts]
        return band(b, "DataBand", key + "_Band", ref, y, height, kids, source=source, can_break=False, filters=filters, new_page=new_page)

    f.add(make, height)


# ---------------------------------------------------------------------------
# Template
# ---------------------------------------------------------------------------
def kv_row(b, parent, key, y, label, expression, label_w=5.2):
    return [text(b, parent, key + "_L", 0.4, y, label_w, 0.55, label, font="{},9".format(FONT), colour=MUTED),
            text(b, parent, key + "_V", 0.4 + label_w, y, W - 0.8 - label_w, 0.55, expression, font="{},9".format(FONT), colour=INK, grow=True)]


def build_page(b: Builder, logo: str) -> str:
    flow = Flow(b)
    HAS_CASES = META + '.has_cases == "1"'

    # --- cover
    def cover(ref, y):
        kids = [
            text(b, ref, "CoverAccent", 0.4, 2.2, 0.45, 2.7, "", fill=RED),
            text(b, ref, "CoverTitle", 1.4, 2.1, 18.5, 3.0, "Network State and\nPlanned Outage Analysis", font="{},30,Bold".format(FONT), colour=INK),
            text(b, ref, "CoverSubtitle", 1.4, 5.2, W - 3, 0.9, "Quasi-dynamic assessment of reference and outage cases", font="{},13".format(FONT), colour=MUTED,
                 border="Bottom;[200:200:200];0.8;Solid;False;4;Black"),
            image(b, ref, "DigSilentLogoCover", W - 4.2, 2.1, 3.6, 3.6, logo),
        ]
        rows = [("Study case", "{ScriptedReportMeta.study_name}"), ("Study ID", "{ScriptedReportMeta.study_id}"),
                ("Network model", "{ScriptedReportMeta.model_name}"), ("Model version", "{ScriptedReportMeta.model_version}"),
                ("Simulation period", "{ScriptedReportMeta.simulation_start} - {ScriptedReportMeta.simulation_end}"),
                ("Time step", "{ScriptedReportMeta.simulation_time_step}"), ("Generated at", "{ScriptedReportMeta.generation_date}"),
                ("Generated by", "{ScriptedReportMeta.generated_by}"), ("Run mode", "{ScriptedReportMeta.run_mode}"),
                ("Result source", "{ScriptedReportMeta.result_name}"), ("Assessment scope", "{ScriptedReportMeta.assessment_scope}")]
        for index, (label, expression) in enumerate(rows):
            kids += kv_row(b, ref, "CoverRow{}".format(index), 6.7 + index * 0.62, label, expression)
        kids.append(text(b, ref, "CoverBanner", 0.4, 13.9, W - 0.8, 1.6, "{ScriptedReportMeta.assessment_status}", fill="[248:222:230]",
                         border="All;[181:18:62];0.8;Solid;False;4;Black", colour="[145:13:48]", font="{},11,Bold".format(FONT), margins="0.5,0.5,0,0"))
        kids.append(text(b, ref, "CoverBannerNote", W - 8.2, 13.9, 7.6, 1.6, "Technical pre-check, not a release", colour=MUTED,
                         font="{},7.5".format(FONT), align="Right", margins="0.2,0.4,0,0"))
        return band(b, "DataBand", "BandCover", ref, y, 16.0, kids, source=META, can_break=False)
    flow.add(cover, 16.0)

    # --- table of contents (filled below, after the sections are known)
    toc_slot = len(flow.parts)
    flow.parts.append("")

    # --- model quality
    section_title(flow, "quality", "3", "Model Quality Assurance", "Completeness of result data and applied limits.")
    status_cond = [condition("ScriptedModelQuality.status", "EqualTo", "FAIL", "String", "[145:13:48]", "Transparent", FONT + ",8.5,Bold"),
                   condition("ScriptedModelQuality.status", "EqualTo", "WARNING", "String", "[145:13:48]", "Transparent", FONT + ",8.5,Bold")]
    table(flow, "Quality", "ScriptedModelQuality", [
        col("Check", "check_name", 6.4, "ScriptedModelQuality"), dict(col("Status", "status", 2.4, "ScriptedModelQuality"), conditions=status_cond),
        col("Details", "message", 13.8, "ScriptedModelQuality"), col("Equipment", "affected_element", 4.1, "ScriptedModelQuality")])

    # --- calculated cases
    section_title(flow, "cases", "4", "Calculated Cases and Planned Outages",
                  "One row per planning case with its outage periods, equipment, assessment and the findings compared with Reference at the "
                  "same time steps.")
    table(flow, "Cases", "ScriptedCases", [
        col("Case", "case_name", 4.2, "ScriptedCases"), col("Outage periods", "period_text", 4.6, "ScriptedCases"),
        col("Prio", "priority", 1.2, "ScriptedCases", align="Center"), col("Equipment out of service", "equipment_name", 6.0, "ScriptedCases"),
        col("Assessment", "assessment", 3.4, "ScriptedCases"), col("Findings at the same time steps as Reference", "assessment_detail", 7.3, "ScriptedCases")],
        conditions=violation_conditions("ScriptedCases"))
    note_box(flow, "CoverageStatement", "{ScriptedReportMeta.coverage_statement}", height=1.9, font="{},8.5".format(FONT))

    # --- case definition
    section_title(flow, "casedef", "5", "Case Definition and Network States",
                  "Which planned outages each case combines, the reference it is compared with, the sequence of active outages and how much "
                  "of the outage time the results cover.")
    table(flow, "CaseDef", "ScriptedCases", [
        col("Case", "case_name", 4.2, "ScriptedCases"), col("Planned outages", "outage_names", 5.5, "ScriptedCases"),
        col("Reference", "reference_text", 3.6, "ScriptedCases"), col("Network states (active outages from)", "states_text", 8.0, "ScriptedCases"),
        col("Coverage", "coverage_text", 2.0, "ScriptedCases", align="Center"), col("Result", "provenance_text", 3.4, "ScriptedCases")])
    note_box(flow, "CaseSource", "Planning cases: {ScriptedReportMeta.case_source_text}. Reference: {ScriptedReportMeta.reference_text}.",
             height=1.1, font="{},8.5".format(FONT))

    # --- reference disclaimer
    section_title(flow, "reference", "6", "Reference Case - Base State Disclaimer",
                  "Baseline loading distribution before any planned outage is applied. Classification uses the maximum loading within the complete "
                  "Reference simulation window.")
    note_box(flow, "ReferenceNote", "Important: These values describe the unchanged Reference case and are not caused by a planned outage.",
             fill="[255:244:246]", border="All;[181:18:62];0.6;Solid;False;4;Black", colour="[145:13:48]", font="{},9,Bold".format(FONT), height=1.1)
    pie_colours = [("up to 80 %", "[140:150:160]"), ("80 to 100 %", "[217:140:31]"), ("above 100 %", "[181:18:62]")]
    chart_band(flow, "ReferencePies", 6.6, [
        lambda bb, ref: pie_chart(bb, ref, "ReferenceLinesPie", 0.5, 0.2, 12.4, 6.3, "ScriptedPieLines", "Reference - Lines", pie_colours),
        lambda bb, ref: pie_chart(bb, ref, "ReferenceTransformersPie", 13.8, 0.2, 12.4, 6.3, "ScriptedPieTransformers", "Reference - Transformers",
                                  pie_colours)])
    table(flow, "ReferenceExceeded", "ScriptedReferenceExceeded", [
        col("Type", "type_label", 4.0, "ScriptedReferenceExceeded"), col("Equipment", "element_name", 10.0, "ScriptedReferenceExceeded"),
        col("Grid", "grid_name", 7.5, "ScriptedReferenceExceeded"), col("Max. loading", "max_text", 5.2, "ScriptedReferenceExceeded")],
        subheading="Equipment above 100 % in the Reference case", row_h=0.6)

    # --- metric view
    section_title(flow, "metrics", "7", "Metric View - Key Results",
                  "Consolidated case view. Cases show their outage windows; the delta compares each line with itself in Reference at the same time step.")
    table(flow, "Metrics", "ScriptedCaseMetrics", [
        col("Case", "case_name", 4.6, "ScriptedCaseMetrics"), col("Max. line loading", "max_line_text", 3.0, "ScriptedCaseMetrics"),
        col("Line with maximum loading", "max_line_element", 5.2, "ScriptedCaseMetrics"),
        col("Max. coincident increase vs REF", "coincident_delta_text", 5.6, "ScriptedCaseMetrics"),
        col("Difference of maxima", "maxima_difference_text", 2.6, "ScriptedCaseMetrics", align="Right"),
        col("Caused violations", "violation_hours_text", 2.4, "ScriptedCaseMetrics", align="Right"),
        col("Node voltage range", "voltage_range_text", 3.3, "ScriptedCaseMetrics")])

    def cards(ref, y):
        kpi = "ScriptedKpis"
        cond = [condition(kpi + ".highest_violation", "EqualTo", "1", "Numeric", "[145:13:48]", "[248:222:230]", FONT + ",16,Bold")]
        kids = [
            text(b, ref, "KpiHighest", 1.0, 0.8, 11.8, 2.2, "{ScriptedKpis.highest_text}", fill="[243:244:248]", border="All;[190:195:205];0.6;Solid;False;4;Black",
                 font="{},16,Bold".format(FONT), colour=INK, margins="0.6,0.4,0.2,0", conditions=cond, valign="Top"),
            text(b, ref, "KpiHighestCaption", 1.0, 3.0, 11.8, 1.0, "{ScriptedKpis.highest_caption}", fill="[243:244:248]",
                 border="All;[190:195:205];0.6;Solid;False;4;Black", font="{},9".format(FONT), colour=MUTED, margins="0.6,0.4,0,0", valign="Top"),
            text(b, ref, "KpiDelta", 14.0, 0.8, 11.8, 2.2, "{ScriptedKpis.delta_text}", fill="[243:244:248]", border="All;[190:195:205];0.6;Solid;False;4;Black",
                 font="{},16,Bold".format(FONT), colour=INK, margins="0.6,0.4,0.2,0", valign="Top"),
            text(b, ref, "KpiDeltaCaption", 14.0, 3.0, 11.8, 1.0, "{ScriptedKpis.delta_caption}", fill="[243:244:248]",
                 border="All;[190:195:205];0.6;Solid;False;4;Black", font="{},9".format(FONT), colour=MUTED, margins="0.6,0.4,0,0", valign="Top"),
        ]
        return band(b, "DataBand", "KpiBand", ref, y, 4.6, kids, source="ScriptedKpis", can_break=False)
    flow.add(cards, 4.6)
    note_box(flow, "MetricsNote",
             "Coincident increase = largest increase of a line's loading against Reference at the same time step. Difference of maxima = maximum "
             "in the case minus maximum in Reference over the same rows; it can be much smaller because the two maxima may occur at different "
             "times. Caused violations = time during which the case adds or worsens a violation.", height=1.6, font="{},8.5".format(FONT))

    def matrix_table(key, source, label, conditions=None, row_h=0.55):
        """One header/data pair per number of case columns (6..0); a row carries the column count of its block."""
        for n in range(gl.CASE_SLOTS, -1, -1):
            slot = min(4.0, (W - 11.5) / n) if n else 0
            columns = [col(label, "element_name", 7.5, source), col("Reference", "ref_text", 4.0, source)] + [
                col("{%s.h%d_name}" % (source, i), "c%d_text" % i, round(slot, 2), source) for i in range(1, n + 1)]
            table(flow, "{}{}".format(key, n), source, columns, conditions=conditions, row_h=row_h,
                  group={"condition": "{%s.block}" % source}, filters=["{}.col_count == {}".format(source, n)])

    # --- case comparison summary
    section_title(flow, "summary", "8", "Case Comparison Summary",
                  "Key figures of every planning case side by side; each case is compared with Reference at the same time steps.")
    matrix_table("Summary", "ScriptedCaseComparison", "Key figure", conditions=violation_conditions("ScriptedCaseComparison"))

    # --- case comparison
    section_title(flow, "comparison", "9", "Assessment Overview - Case Comparison",
                  "Reference and all outage cases compared using the same three assessment metrics.")

    def count_chart(bb, ref, name, x, field, label, y_title):
        return line_chart(bb, ref, name, x, 0.3, 8.6, 7.4, "ScriptedCaseCounts", "case_name",
                          [(field, label, RED_RGB, 2)], y_title=y_title, y_format="0;-0;0", marker=True, labels=True, y_hidden=True, legend=False,
                          title=label, start_from_zero=True, x_angle=30, x_step=1)
    chart_band(flow, "CaseCounts", 8.0, [
        lambda bb, ref: count_chart(bb, ref, "LinesCountChart", 0.2, "line_count", "Lines > 100 %", "Count"),
        lambda bb, ref: count_chart(bb, ref, "TransformersCountChart", 9.1, "transformer_count", "Transformers > 100 %", "Count"),
        lambda bb, ref: count_chart(bb, ref, "NodesCountChart", 18.0, "node_count", "Nodes outside voltage band", "Count")])

    # --- radar
    section_title(flow, "radar", "10", "Assessment Overview - Radar Comparison", "Reference and all outage cases shown as profiles across Lines, Transformers and Nodes.")
    note_box(flow, "RadarNote", "{ScriptedRadar.note}", source="ScriptedRadar", height=0.9, font="{},8".format(FONT), filters=["ScriptedRadar.metric_order == 1"])
    # One chart per number of drawn cases (REF plus 0..6), so that the legend lists exactly the cases that exist.
    for n in range(1, len(SLOT_COLOURS) + 1):
        radar_series = [("v{}".format(i), "{ScriptedRadar.s%d_name}" % i, SLOT_COLOURS[i]) for i in range(n)]
        chart_band(flow, "RadarChart{}".format(n), 9.0, [
            lambda bb, ref, n=n, radar_series=radar_series: radar_chart(bb, ref, "ViolationRadar{}".format(n), 6.5, 0.2, 13.5, 8.6, "ScriptedRadar",
                                                                       radar_series)],
                   filters=['{}.chart_cases == "{}"'.format(META, n)])
    table(flow, "RadarCounts", "ScriptedCaseCounts", [
        col("Case", "case_name", 8.7, "ScriptedCaseCounts"), col("Lines > 100 %", "line_count", 6.0, "ScriptedCaseCounts"),
        col("Transformers > 100 %", "transformer_count", 6.0, "ScriptedCaseCounts"), col("Nodes outside band", "node_count", 6.0, "ScriptedCaseCounts")],
        row_h=0.55)

    # --- top 10 lines
    section_title(flow, "toplines", "11", "Top 10 Maximum Loaded Lines", "Ranking across the complete simulation window and all cases.")
    chart_band(flow, "TopLinesChart", 11.0, [
        lambda bb, ref: bar_chart(bb, ref, "TopLinesBarChart", 0.2, 0.2, W - 0.4, 10.4, "ScriptedLineLoadingBars", "element_name", "max_value", RED_RGB,
                                  y_title="Maximum loading [%]", const=(100, "100 %", "Vertical"))])

    # --- trends
    def trend(key, number, title, subtitle, table_name, chart_name):
        section_title(flow, key, number, title, subtitle)
        for n in range(1, len(SLOT_COLOURS) + 1):
            series = [("v{}".format(i), "{%s.s%d_name}" % (table_name, i), SLOT_COLOURS[i], 2.2 if i else 1.8) for i in range(n)]
            filters = ['{}.chart_cases == "{}"'.format(META, n)] + ([HAS_CASES] if key != "trendmost" else [])
            chart_band(flow, "{}Chart{}".format(key, n), 11.2, [
                lambda bb, ref, n=n, series=series: line_chart(bb, ref, "{}{}".format(chart_name, n), 0.2, 0.9, W - 0.4, 10.2, table_name, "time_label",
                                                               series, y_title="Loading [%]", x_step=None, const=(100, "100 %", "Horizontal"))],
                       filters=filters, title="{%s.chart_title}" % table_name)
    trend("trendmost", "12", "Most Loaded Line - Time Plot", "Reference and every case for the line with the highest absolute loading.",
          "ScriptedTrendMostLoaded", "MostLoadedChart")
    trend("trenddelta", "13", "Largest Coincident Delta vs Reference - Time Plot",
          "Line with the greatest increase against Reference at the same time step, Reference and every case.",
          "ScriptedTrendLargestDelta", "DeltaTrendChart")
    none_filter = [META + '.has_cases == "0"']
    note_box(flow, "TrendDeltaNone", "No planned outage case was calculated, so there is no change against Reference to show.", filters=none_filter,
             height=1.1, font="{},9,Bold".format(FONT))

    # --- top 10 by case
    section_title(flow, "topcase", "14", "Top 10 Strongly Loaded Lines by Case", "Case-specific top-10 ranking for direct comparison.")
    matrix_table("TopCase", "ScriptedTopLinesByCase", "Rank", row_h=0.6)

    # --- calculation evidence
    section_title(flow, "evidence", "15", "Calculation Evidence",
                  "Every QDS run: what was calculated, what was reused, and the result object each case keeps in PowerFactory.")
    table(flow, "Evidence", "ScriptedCalculationRuns", [
        col("Run", "run_id", 2.6, "ScriptedCalculationRuns"), col("Kind", "run_kind", 2.8, "ScriptedCalculationRuns"),
        col("Case", "case_name", 4.0, "ScriptedCalculationRuns"), col("Steps", "time_steps", 1.6, "ScriptedCalculationRuns", align="Right"),
        col("Time", "elapsed_text", 1.8, "ScriptedCalculationRuns", align="Right"), col("Status", "status", 2.6, "ScriptedCalculationRuns"),
        col("Result object in PowerFactory", "result_object", 5.3, "ScriptedCalculationRuns"), col("Note", "note", 6.0, "ScriptedCalculationRuns")],
        row_h=0.55)
    note_box(flow, "EvidenceNote", "{ScriptedReportMeta.qds_mode_text}", height=1.3, font="{},8.5".format(FONT))

    # --- appendix
    section_title(flow, "appendix", "16", "Appendix - Detailed Case Tables",
                  "One separate comparison table per element type. Rows are element names; columns are Reference and outage cases.")
    note_box(flow, "AppendixIndexText",
             "A  Lines - maximum loading within the simulation window [%]\nB  Transformers - maximum loading within the simulation window [%]\n"
             "C  Terminals / busbars - minimum node voltage within the simulation window [p.u.]", height=2.4, font="{},10".format(FONT))
    note_box(flow, "AppendixConvention",
             "Each value is derived from the same quasi-dynamic simulation window. Out-of-service or unavailable results are displayed as n/a. "
             "Loading tables list the elements that reach 80 % or change by 1 percentage point; voltage tables list the nodes outside their band or "
             "changing by 0.005 p.u. or more.", height=1.8, font="{},8.5".format(FONT))
    for key, letter, title, subtitle, source, label in (
            ("appa", "A", "Line Loading", "Maximum line loading [%] for Reference and every planned outage case.", "ScriptedAppendixLine", "Line"),
            ("appb", "B", "Transformer Loading", "Maximum transformer loading [%] for Reference and every planned outage case.", "ScriptedAppendixTransformer",
             "Transformer"),
            ("appc", "C", "Terminal and Busbar Voltages", "Minimum node voltage [p.u.] for Reference and every planned outage case.",
             "ScriptedAppendixVoltage", "Terminal / busbar")):
        section_title(flow, key, "", "Appendix {} - {}".format(letter, title), subtitle)
        matrix_table(key.capitalize(), source, label, conditions=violation_conditions(source))

    # fill the table of contents
    entries = [("Report Metadata", None), ("Table of Contents", None)] + [(title.split("  ", 1)[-1], marker) for marker, title in flow.sections]

    def toc(ref, y):
        kids = [text(b, ref, "TocAccent", 0, 0.35, 0.28, 1.05, "", fill=RED),
                text(b, ref, "TocTitle", 0.55, 0.3, W - 0.55, 1.15, "Table of Contents", font="{},20,Bold".format(FONT), colour=INK),
                text(b, ref, "TocSubtitle", 0.55, 1.45, W - 0.55, 0.6, "Select a section to navigate directly to it.", font="{},9".format(FONT), colour=MUTED)]
        for index, (title, marker) in enumerate(entries, 1):
            top = 2.4 + (index - 1) * TOC_PITCH
            kids.append(text(b, ref, "TocNumber{}".format(index), 0.4, top, 1.2, TOC_PITCH - 0.06, str(index), font="{},10,Bold".format(FONT), colour=RED))
            kids.append(text(b, ref, "TocLink{}".format(index), 1.7, top, W - 2.4, TOC_PITCH - 0.06, title, font="{},10".format(FONT), colour=INK,
                             hyperlink="#" + marker if marker else None))
        return band(b, "DataBand", "BandTableOfContents", ref, y, 2.4 + len(entries) * TOC_PITCH + 0.3, kids, source=META, new_page=True, can_break=False)
    toc_ref = b.ref()
    flow.parts[toc_slot] = toc(toc_ref, 17.0)

    page_header_ref, footer_ref = b.ref(), b.ref()
    header_kids = [
        image(b, page_header_ref, "DigSilentLogo", 0, 0.05, 0.68, 0.68, logo),
        text(b, page_header_ref, "HeaderLeft", 0.82, 0, 14.0, 0.85, "NETWORK STATE AND PLANNED OUTAGE ANALYSIS", font="{},8.5,Bold".format(FONT), colour=INK),
        text(b, page_header_ref, "HeaderRight", W - 12.0, 0, 12.0, 0.85, "Study: {ScriptedReportMeta.study_name}  |  Model: {ScriptedReportMeta.model_name}",
             font="{},8".format(FONT), colour=MUTED, align="Right"),
        text(b, page_header_ref, "HeaderRule", 0, 0.85, W, 0.15, "", border="Bottom;{};0.5;Solid;False;4;Black".format(LINE)),
    ]
    header = band(b, "PageHeaderBand", "BandPageHeader", page_header_ref, 0.4, 1.0, header_kids, extra="<PrintOn>ExceptFirstPage</PrintOn>")
    footer_kids = [
        text(b, footer_ref, "FooterRule", 0, 0, W, 0.15, "", border="Top;{};0.5;Solid;False;4;Black".format(LINE)),
        text(b, footer_ref, "FooterLeft", 0, 0.15, 16.0, 0.75, FOOTER_TEXT, font="{},7.5".format(FONT), colour=MUTED),
        text(b, footer_ref, "FooterRight", W - 6.0, 0.15, 6.0, 0.75, "Page {PageNumber}", font="{},7.5".format(FONT), colour=MUTED, align="Right"),
    ]
    footer = band(b, "PageFooterBand", "BandPageFooter", footer_ref, BODY_H - 0.9, 0.9, footer_kids)
    components = [header] + flow.parts + [footer]
    return components


def data_sources(first_ref: int) -> tuple[str, int]:
    ref = first_ref
    parts = []
    order = {
        "ScriptedCases": '"case_order"', "ScriptedCaseMetrics": '"case_order"', "ScriptedPieLines": '"sort_order"', "ScriptedPieTransformers": '"sort_order"',
        "ScriptedReferenceExceeded": '"rank"', "ScriptedCaseCounts": '"case_order"', "ScriptedRadar": '"metric_order"', "ScriptedLineLoadingBars": '"rank"',
        "ScriptedTrendMostLoaded": '"timestamp"', "ScriptedTrendLargestDelta": '"timestamp"',
        "ScriptedCaseComparison": '"block", "row_order"', "ScriptedCalculationRuns": '"run_order"',
        "ScriptedTopLinesByCase": '"block", "row_order"', "ScriptedAppendixLine": '"block", "row_order"',
        "ScriptedAppendixTransformer": '"block", "row_order"', "ScriptedAppendixVoltage": '"block", "row_order"'}
    kinds = {"string": "System.String", "integer": "System.Int32", "number": "System.Double"}
    for name, fields in gl.TABLES:
        ref += 1
        columns = "".join("<value>{},{}</value>".format(field, kinds[kind]) for field, kind in fields)
        command = 'SELECT * FROM "{}"'.format(name) + (" ORDER BY " + order[name] if name in order else "")
        parts.append(
            ('<{n} Ref="{r}" type="Stimulsoft.Report.Dictionary.StiSQLiteSource" isKey="true"><Alias>{n}</Alias>'
             '<Columns isList="true" count="{c}">{cols}</Columns><CommandTimeout>30</CommandTimeout><Dictionary isRef="1" />'
             '<Key>{key}</Key><Name>{n}</Name><NameInSource>SQLite</NameInSource><Parameters isList="true" count="0" />'
             "<SqlCommand>{cmd}</SqlCommand></{n}>").format(
                n=name, r=ref, c=len(fields), cols=columns, key=hashlib.md5(name.encode()).hexdigest(), cmd=esc(command)))
    return '<DataSources isList="true" count="{}">{}</DataSources>'.format(len(parts), "".join(parts)), ref


def main() -> None:
    old = MRT.read_text(encoding="utf-8")
    databases = re.search(r"<Databases isList.*?</Databases>", old, re.S).group(0)
    logo = re.search(r"<ImageBytes>(.*?)</ImageBytes>", old, re.S).group(1)
    tail = old[old.index("</Pages>") + len("</Pages>"):]
    tail = re.sub(r"<ReportDescription>.*?</ReportDescription>",
                  "<ReportDescription>GridLens PowerFactory 2026 template: landscape report of engineer-defined planning cases, time-aligned "
                  "comparison with Reference, calculation evidence and appendix tables.</ReportDescription>", tail, flags=re.S)
    # Dictionary refs: 1 dictionary, 2 database (kept), then the data sources.
    sources, last = data_sources(2)
    b = Builder(last)
    b.page_ref = b.ref()
    components = build_page(b, logo)
    page = ('<PageMain Ref="{ref}" type="Page" isKey="true"><Border>None;Black;2;Solid;False;4;Black</Border><Brush>Transparent</Brush>'
            '<Components isList="true" count="{n}">{comps}</Components><Conditions isList="true" count="0" />'
            '<Expressions isList="true" count="0" /><Guid>db51b5ee95cc25e98c1709bd7710cbb6</Guid><Margins>{mx},{my},{mx},{my}</Margins>'
            '<Name>PageMain</Name><Orientation>Landscape</Orientation><PageHeight>{ph}</PageHeight><PageWidth>{pw}</PageWidth><Report isRef="0" /></PageMain>').format(
        ref=b.page_ref, n=len(components), comps="".join(components), mx=MARGIN_X, my=MARGIN_Y, ph=PAGE_H, pw=PAGE_W)
    head = ('<?xml version=\'1.0\' encoding=\'utf-8\'?>\n<StiSerializer version="1.02" type="Net" application="StiReport">\n'
            '  <Culture>en-US</Culture>\n  <Dictionary Ref="1" type="Dictionary" isKey="true">\n    <BusinessObjects isList="true" count="0" />\n    '
            + databases + "\n    " + sources + "\n"
            '    <Relations isList="true" count="0" />\n    <Report isRef="0" />\n    <Resources isList="true" count="0" />\n'
            '    <UserFunctions isList="true" count="0" />\n    <Variables isList="true" count="0" />\n  </Dictionary>\n'
            '  <EngineVersion>EngineV2</EngineVersion>\n  <GlobalizationStrings isList="true" count="0" />\n'
            "  <Key>4362d1185ecdc83b6c90c71bf080ebeb</Key>\n  <MetaTags isList=\"true\" count=\"0\" />\n  <Pages isList=\"true\" count=\"1\">")
    MRT.write_text(head + page + "</Pages>" + tail, encoding="utf-8")
    print("wrote", MRT, "refs:", b.n)


if __name__ == "__main__":
    main()
