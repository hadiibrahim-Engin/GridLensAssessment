"""Deep, read-only ElmRes inspection for PowerFactory; standard library only.

Paste this entire file into a separate ComPython, set RESULT_NAME below and
run it in PowerFactory. A short name is searched in the active study case
first, then the active project. A full GetFullName() path is also accepted.
With RESULT_NAME empty, available result objects are listed instead.

Exports every row and column, including GetValue return codes, without
sampling. Large results can take time and disk space. The PowerFactory output
window shows progress and the report location; report.txt and the accompanying
JSON/CSV files contain the details. No third-party Python package is needed.

Nothing is calculated, activated, created, edited or deleted in PowerFactory.
Load/Release only open and close result-data access. All exported model names,
paths, attribute values and result values stay in local files. Object metadata
describes the model as it exists NOW; it is not a historical network snapshot.
No API can promise inaccessible or undocumented internal storage: discovery
sources, unsupported methods and every failed read are reported explicitly.
"""

# --------------------------- EDIT THIS NAME ---------------------------------
RESULT_NAME = ""  # e.g. "OA_261024-103000_C1" or its full PowerFactory path
# ---------------------------------------------------------------------------
OUTPUT_DIRECTORY = ""  # empty: ~/OutageAssessment/result_inspections
EXPORT_ALL_VALUES = True  # False still scans ALL cells for complete statistics
INSPECT_SUBRESULTS = True
RESOLVE_OBJECT_CELLS = True  # also resolve object-valued cells (e.g. contingency references)
PROGRESS_SECONDS = 5.0
INSPECTOR_VERSION = "1.0"

import csv
import hashlib
import json
import math
import os
import re
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


TIME_UNITS = {"s": 1, "sec": 1, "seconds": 1, "min": 60, "minutes": 60,
              "h": 3600, "hr": 3600, "hours": 3600, "d": 86400, "days": 86400}
TIME_VARIABLES = {"b:tnow", "t", "time"}
KNOWN_ATTRIBUTES = (
    "loc_name", "desc", "outserv", "calTp", "calTpSub", "f_name", "filename",
    "file_name", "iopt_rd", "iopt_wr", "iopt_file", "iopt_loc", "iopt_sep",
    "cnttime", "pResElm", "p_rescnt", "p_rescntDC", "results", "pResult",
    "cpGrid", "uknom", "systype", "typ_id", "obj_id", "cuser", "cdate",
    "moduser", "moddate", "varList", "vars", "variables", "objList",
)
STATUS_MEANING = {"0": "read successfully", "1": "row out of range",
                  "2": "column out of range", "3": "not recorded (sparse / recording limits)"}


def attr(obj, name, default=None):
    try:
        return getattr(obj, name)
    except Exception:
        return default


def obj_ref(obj):
    """A reference only: never follow links into an entire network recursively."""
    if obj is None or not callable(attr(obj, "GetClassName")):
        return None
    result = {"name": str(attr(obj, "loc_name", ""))}
    for key, method in (("class", "GetClassName"), ("path", "GetFullName")):
        try:
            result[key] = str(getattr(obj, method)())
        except Exception as exc:
            result[key] = ""
            result[key + "_error"] = "{}: {}".format(type(exc).__name__, exc)
    return result


def identity(obj):
    ref = obj_ref(obj) or {}
    return ref.get("path") or "{}@{}".format(ref.get("class", "object"), id(obj))


def encode(value, depth=0, seen=None):
    """JSON-safe values, explicit non-finite numbers and cycle/depth markers."""
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else {"non_finite": repr(value)}
    ref = obj_ref(value)
    if ref is not None:
        return {"object_reference": ref}
    if depth >= 20:
        return {"not_expanded": "metadata nesting exceeds 20 levels", "repr": repr(value)}
    seen = set() if seen is None else seen
    if id(value) in seen:
        return {"not_expanded": "cyclic Python value"}
    if isinstance(value, (list, tuple, dict, set)):
        seen = seen | {id(value)}
        if isinstance(value, dict):
            return {str(k): encode(v, depth + 1, seen) for k, v in value.items()}
        return [encode(v, depth + 1, seen) for v in value]
    return {"python_type": type(value).__name__, "repr": repr(value)}


def write_json(path, value):
    with path.open("w", encoding="utf-8") as stream:
        json.dump(encode(value), stream, ensure_ascii=False, indent=2, allow_nan=False)


def csv_value(value):
    if value is None:
        return ""
    if isinstance(value, (str, int, float, bool)):
        return str(value)
    return json.dumps(encode(value), ensure_ascii=False, allow_nan=False)


def finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def unpack(raw):
    if isinstance(raw, (tuple, list)):
        if len(raw) < 2:
            return "MALFORMED_RETURN", raw
        code, value = raw[0], raw[1]
        return str(int(code)) if finite(code) and int(code) == code else str(code), value
    # Some API wrappers return the value without an explicit status code.
    return "0", raw


class Reader:
    """Only explicitly named reading methods are ever invoked."""

    def __init__(self, error_stream):
        self.error_stream = error_stream
        self.error_count = 0

    def error(self, obj, method, args, exc):
        self.error_count += 1
        entry = {"object": obj_ref(obj), "method": method, "arguments": encode(args),
                 "error_type": type(exc).__name__, "error": str(exc)}
        self.error_stream.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return {"error": entry["error_type"] + ": " + entry["error"]}

    def call(self, obj, method, *args):
        fn = attr(obj, method)
        if not callable(fn):
            return {"unavailable": method}
        try:
            return fn(*args)
        except Exception as exc:
            return self.error(obj, method, args, exc)

    def read_attr(self, obj, name):
        getter = attr(obj, "GetAttribute")
        try:
            return getter(name) if callable(getter) else getattr(obj, name)
        except Exception as exc:
            return self.error(obj, "GetAttribute", (name,), exc)

    def children(self, obj):
        fn = attr(obj, "GetContents")
        if not callable(fn):
            return {"unavailable": "GetContents"}
        try:
            return fn("*", 0)
        except TypeError:
            return self.call(obj, "GetContents", "*")
        except Exception as exc:
            return self.error(obj, "GetContents", ("*", 0), exc)


def failed(value):
    return isinstance(value, dict) and ("error" in value or "unavailable" in value)


def contents(obj, recursive=0, pattern="*"):
    """Discovery fails visibly rather than selecting an incomplete candidate list."""
    fn = attr(obj, "GetContents")
    if not callable(fn):
        return []
    try:
        found = fn(pattern, recursive)
    except TypeError:
        if recursive:
            found, todo, visited = [], [obj], set()
            while todo:
                parent = todo.pop()
                key = identity(parent)
                if key in visited:
                    continue
                visited.add(key)
                children = list(parent.GetContents("*") or ())
                found.extend(children)
                todo.extend(child for child in children if callable(attr(child, "GetContents")))
            if pattern == "*.ElmRes":
                found = [child for child in found if (obj_ref(child) or {}).get("class") == "ElmRes"]
        else:
            found = fn(pattern)
    return list(found or ())


def find_result(app, name):
    """Exact names only. Duplicate matches require a full path."""
    wanted = name.strip()
    available = {}
    for scope in (app.GetActiveStudyCase(), app.GetActiveProject()):
        if scope is None:
            continue
        candidates = [obj for obj in contents(scope, 1, "*.ElmRes") if (obj_ref(obj) or {}).get("class") == "ElmRes"]
        for obj in candidates:
            available[identity(obj)] = obj
        matches = []
        for obj in candidates:
            ref = obj_ref(obj)
            if wanted in (ref["name"], ref["name"] + ".ElmRes") or wanted.replace("/", "\\") == ref["path"].replace("/", "\\"):
                matches.append(obj)
        matches = list({identity(obj): obj for obj in matches}.values())
        if len(matches) > 1:
            raise ValueError("More than one ElmRes matches {!r}. Use its full path:\n{}".format(
                name, "\n".join("  " + identity(obj) for obj in matches)))
        if matches:
            return matches[0], list(available.values())
    return None, sorted(available.values(), key=identity)


def names_from(value):
    """Recognise common attribute-list formats, retaining originals separately."""
    if isinstance(value, str):
        try:
            return names_from(json.loads(value))
        except (ValueError, TypeError):
            return [value] if re.fullmatch(r"[A-Za-z_][\w:.]*", value) else []
    if isinstance(value, (list, tuple)):
        return [name for item in value for name in names_from(item)]
    if isinstance(value, dict):
        for key in ("name", "Name", "attribute", "attribute_name", "AttributeName"):
            if isinstance(value.get(key), str):
                return names_from(value[key])
        for key in ("attributes", "Attributes"):
            if key in value:
                return names_from(value[key])
        return [key for key in value if re.fullmatch(r"[A-Za-z_][\w:.]*", str(key))]
    return []


def inspect_metadata(reader, app, obj):
    ref = obj_ref(obj)
    discovered, sources = set(), []
    for target, method, args in ((obj, "GetAttributeNames", ()), (obj, "GetAttributes", ()),
                                 (app, "GetAvailableAttributes", (ref["class"],)),
                                 (app, "GetAvailableAttributesAsJson", (ref["class"],))):
        if not callable(attr(target, method)):
            continue
        raw = reader.call(target, method, *args)
        names = [] if failed(raw) else names_from(raw)
        discovered.update(names)
        sources.append({"method": method, "names_found": names, "raw_return": encode(raw)})
    try:
        public = [name for name in dir(obj) if not name.startswith("_")]
    except Exception as exc:
        reader.error(obj, "dir", (), exc)
        public = []
    methods = {}
    for name in public:
        value = attr(obj, name)
        if callable(value):
            methods[name] = attr(value, "__doc__", None)
        else:
            discovered.add(name)
    # Static names supplement discovery, but only if HasAttribute confirms them.
    has = attr(obj, "HasAttribute")
    for name in KNOWN_ATTRIBUTES:
        try:
            if (callable(has) and has(name)) or (not callable(has) and attr(obj, name) is not None):
                discovered.add(name)
        except Exception as exc:
            reader.error(obj, "HasAttribute", (name,), exc)
    attributes = {}
    for name in sorted(discovered):
        if name.startswith("_") or callable(attr(obj, name)):
            continue
        value = reader.read_attr(obj, name)
        entry = {"value": encode(value)}
        for key, method in (("type", "GetAttributeType"), ("unit", "GetAttributeUnit"),
                            ("description", "GetAttributeDescription"), ("shape", "GetAttributeShape")):
            if callable(attr(obj, method)):
                entry[key] = encode(reader.call(obj, method, name))
        attributes[name] = entry
    parent = reader.call(obj, "GetParent")
    return {"object": ref, "parent": encode(parent), "attributes": attributes,
            "attribute_discovery": sources, "methods_not_executed": methods,
            "discovery_note": "API-enumerated attributes plus public dir() fields and confirmed known fields; "
                              "not a guarantee of undocumented/internal attribute coverage."}


class Stats:
    def __init__(self):
        self.n = self.zeros = self.positive = self.negative = self.non_finite = self.non_numeric = 0
        self.mean = self.m2 = 0.0
        self.minimum = self.maximum = self.first = self.last = None
        self.status = Counter()

    def add(self, code, value, row):
        self.status[code] += 1
        if code != "0":
            return
        if not finite(value):
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                self.non_finite += 1
            else:
                self.non_numeric += 1
            return
        self.n += 1
        item = {"row": row, "value": value}
        if self.minimum is None or value < self.minimum["value"]:
            self.minimum = item
        if self.maximum is None or value > self.maximum["value"]:
            self.maximum = item
        if self.first is None:
            self.first = item
        self.last = item
        self.zeros += value == 0
        self.positive += value > 0
        self.negative += value < 0
        delta = value - self.mean
        self.mean += delta / self.n
        self.m2 += delta * (value - self.mean)

    def report(self):
        return {"finite_values": self.n, "non_finite_values": self.non_finite, "non_numeric_values": self.non_numeric,
                "status_counts": dict(self.status), "zero_values": self.zeros, "positive_values": self.positive,
                "negative_values": self.negative, "minimum": self.minimum, "maximum": self.maximum,
                "first_finite": self.first, "last_finite": self.last,
                "mean": self.mean if self.n else None,
                "population_stddev": math.sqrt(max(0.0, self.m2 / self.n)) if self.n else None}


def time_summary(values, unit, variable, row_classes, is_explicit):
    """Raw axis facts first; time interpretation is conditional, never assumed."""
    numbers = [value for value in values if finite(value)]
    differences = [b - a for a, b in zip(values, values[1:]) if finite(a) and finite(b)]
    positive = [step for step in differences if step > 0]
    steps = Counter(round(step, 9) for step in differences)
    unit = str(unit or "").strip().lower()
    factor = TIME_UNITS.get(unit)
    contingency = row_classes.get("ComOutage", 0) > 0
    is_time = factor is not None and not contingency and (is_explicit or variable.lower() in TIME_VARIABLES or
                                                        (len(numbers) == len(values) and all(d > 0 for d in differences)))
    result = {"row_count": len(values), "readable_numeric_rows": len(numbers), "unit": unit,
              "variable": variable, "explicit_time_column": is_explicit,
              "interpretation": "time axis" if is_time and is_explicit else "candidate implicit time axis" if is_time else
                                "contingency/index axis" if contingency else "unclassified index (no hours inferred)",
              "first": values[0] if values else None, "last": values[-1] if values else None,
              "minimum": min(numbers) if numbers else None, "maximum": max(numbers) if numbers else None,
              "duplicate_numeric_values": len(numbers) - len(set(numbers)),
              "descending_steps": sum(step < 0 for step in differences),
              "step_histogram": [{"step": step, "count": n} for step, n in sorted(steps.items())],
              "strictly_increasing_complete_axis": bool(values) and len(numbers) == len(values) and all(d > 0 for d in differences)}
    if not is_time:
        return result
    result["interpretation_basis"] = "time variable and recognised unit" if is_explicit else "recognised time unit and increasing numeric index; inference only"
    if numbers:
        result["span_hours"] = (max(numbers) - min(numbers)) * factor / 3600.0
        for key in ("first", "last", "minimum", "maximum"):
            value = result[key]
            if finite(value) and value * factor >= 315532800:
                try:
                    stamp = datetime.fromtimestamp(value * factor, timezone.utc)
                    result[key + "_epoch_candidate_utc"] = stamp.isoformat()
                    result[key + "_epoch_candidate_local"] = stamp.astimezone().isoformat()
                except (ValueError, OverflowError, OSError):
                    pass
    if positive:
        base_step = min(positive)
        uniform = len(numbers) == len(values) and all(math.isclose(step, base_step, rel_tol=1e-8, abs_tol=1e-8) for step in differences)
        result.update(minimum_positive_step_hours=base_step * factor / 3600.0,
                      maximum_step_hours=max(positive) * factor / 3600.0, uniform_steps=uniform)
        result["gap_candidates"] = [{"after_row": i, "step": b-a, "step_hours": (b-a)*factor/3600.0}
                                    for i, (a,b) in enumerate(zip(values, values[1:])) if finite(a) and finite(b)
                                    and b-a > base_step * (1+1e-8)]
        if uniform:
            result["nominal_interval_hours_if_each_row_covers_one_step"] = len(values) * base_step * factor / 3600.0
    result["duration_note"] = ("span_hours is last/maximum minus first/minimum. Row count is NOT a duration. "
                               "Row-count x step is conditional interval coverage, not proof of simulation end time. "
                               "UTC/local dates assume the large values are POSIX epoch times.")
    return result


def equipment(ref):
    cls = (ref or {}).get("class", "")
    return (cls.startswith("Elm") and cls != "ElmRes") or cls == "StaCubic"


class Explorer:
    def __init__(self, app, folder, export_values=True, subresults=True):
        self.app, self.folder = app, folder
        self.export_values, self.subresults = export_values, subresults
        self.errors = (folder / "read_errors.jsonl").open("w", encoding="utf-8")
        self.reader = Reader(self.errors)
        self.printer = attr(app, "PrintPlain", print)
        self.last_progress = 0.0
        self.equipment = {}
        self.recorded_objects = {}
        self.owner_details = {}
        self.grids = {}
        self.row_objects = {}
        self.scanned = 0

    def progress(self, message, force=False):
        now = time.monotonic()
        if force or now - self.last_progress >= PROGRESS_SECONDS:
            self.printer("[RESULT EXPLORER] " + message)
            self.last_progress = now

    def read_cell(self, obj, row, column, objects=False):
        method = "GetObjectValue" if objects else "GetValue"
        raw = self.reader.call(obj, method, row, column)
        if failed(raw):
            return "UNAVAILABLE" if "unavailable" in raw else "EXCEPTION", raw
        return unpack(raw)

    def inspect(self, root):
        self.progress("Inspecting {}. Full cell scan; no sampling.".format(identity(root)), True)
        todo, seen, hierarchy, results = [(root, None)], set(), [], []
        try:
            while todo:
                obj, parent_id = todo.pop()
                key = identity(obj)
                if key in seen:
                    continue
                seen.add(key)
                index = len(hierarchy) + 1
                node_dir = self.folder / "objects" / "{:05d}_{}".format(index, slug(attr(obj, "loc_name", "object")))
                node_dir.mkdir(parents=True)
                metadata = inspect_metadata(self.reader, self.app, obj)
                write_json(node_dir / "metadata.json", metadata)
                ref = obj_ref(obj)
                entry = {"id": index, "parent_id": parent_id, "object": ref,
                         "folder": str(node_dir.relative_to(self.folder))}
                hierarchy.append(entry)
                if ref["class"] == "ElmRes":
                    results.append(self.inspect_result(obj, entry, node_dir))
                children = self.reader.children(obj)
                if failed(children):
                    entry["children_read"] = children
                else:
                    entry["children_read"] = "all direct children"
                    for child in reversed(list(children or ())):
                        if obj_ref(child) is None:
                            entry.setdefault("uninspectable_children", []).append(encode(child))
                            continue
                        if (obj_ref(child) or {}).get("class") == "ElmRes" and not self.subresults:
                            entry.setdefault("excluded_subresults", []).append(obj_ref(child))
                        else:
                            todo.append((child, index))
            summary = self.summarise(root, hierarchy, results)
            write_json(self.folder / "summary.json", summary)
            write_json(self.folder / "hierarchy.json", hierarchy)
            self.write_report(summary, results)
            for key in ("result_objects", "scanned_results", "unique_equipment", "equipment_by_class", "variable_names_count",
                        "data_cells", "finite_values", "cell_status_counts", "read_exceptions"):
                self.progress("{}: {}".format(key, summary[key]), True)
            for result in results:
                if result["status"] == "SCANNED":
                    axis = result["axis"]
                    self.progress("{}: {} rows, {} columns; {}; span_hours={}.".format(
                        result["object"]["name"], result["rows"], result["columns"], axis["interpretation"],
                        axis.get("span_hours", "not inferred")), True)
            self.progress("Finished. {} result object(s), {} equipment objects, {} data cells. Report: {}".format(
                len(results), len(self.equipment), self.scanned, self.folder / "report.txt"), True)
            return summary
        finally:
            self.errors.close()

    def inspect_result(self, obj, entry, folder):
        reader = self.reader
        result = {"object": obj_ref(obj), "folder": entry["folder"], "status": "UNREADABLE"}
        study_time = attr(obj, "cnttime")
        if finite(study_time):
            result["cnttime"] = study_time
            result["cnttime_is_subresult"] = entry["parent_id"] is not None
        loaded = False
        try:
            code = reader.call(obj, "Load")
            result["load_return"] = encode(code)
            if failed(code) or (isinstance(code, (int, float)) and code != 0):
                return result
            loaded = True
            raw_rows, raw_cols = reader.call(obj, "GetNumberOfRows"), reader.call(obj, "GetNumberOfColumns")
            if not all(isinstance(n, int) and not isinstance(n, bool) and n >= 0 for n in (raw_rows, raw_cols)):
                result["dimension_error"] = {"rows": encode(raw_rows), "columns": encode(raw_cols)}
                return result
            rows, ncols = raw_rows, raw_cols
            self.progress("{}: {} rows x {} columns.".format(entry["folder"], rows, ncols), True)
            columns = [self.column(obj, col) for col in range(ncols)]
            explicit = [col for col in columns if col["variable"].lower() in TIME_VARIABLES]
            axis_col = explicit[0]["column"] if explicit else -1
            axis_meta = columns[axis_col] if axis_col >= 0 else self.column(obj, -1)
            write_json(folder / "columns.json", columns)
            self.column_csv(folder, columns)
            stats, axis, row_classes = [Stats() for _ in columns], [], Counter()
            rows_file = (folder / "rows.csv").open("w", encoding="utf-8-sig", newline="")
            data_file = codes_file = object_file = None
            object_status = Counter()
            resolved_cells = 0
            can_read_objects = RESOLVE_OBJECT_CELLS and callable(attr(obj, "GetObjectValue"))
            try:
                row_writer = csv.writer(rows_file)
                row_writer.writerow(["row", "implicit_index_status", "implicit_index_value", "row_object_status", "row_object_class", "row_object_name", "row_object_path", "axis_column", "axis_value"])
                if can_read_objects:
                    object_file = (folder / "object_cells.jsonl").open("w", encoding="utf-8")
                if self.export_values:
                    data_file = (folder / "data_values.csv").open("w", encoding="utf-8-sig", newline="")
                    codes_file = (folder / "data_codes.csv").open("w", encoding="utf-8-sig", newline="")
                    data_writer, code_writer = csv.writer(data_file), csv.writer(codes_file)
                    header = ["row"] + [col["key"] for col in columns]
                    data_writer.writerow(header)
                    code_writer.writerow(header)
                for row in range(rows):
                    index_code, index_value = self.read_cell(obj, row, -1)
                    object_code, row_object = self.read_cell(obj, row, -1, objects=True)
                    ref = obj_ref(row_object) if object_code == "0" else None
                    if ref is not None:
                        self.row_objects[identity(row_object)] = ref
                        row_classes[ref["class"]] += 1
                    row_values, row_codes = [], []
                    time_value = index_value if index_code == "0" else None
                    for col in columns:
                        status, value = self.read_cell(obj, row, col["column"])
                        stats[col["column"]].add(status, value, row)
                        if col["column"] == axis_col:
                            time_value = value if status == "0" else None
                        if can_read_objects:
                            ocode, oval = self.read_cell(obj, row, col["column"], objects=True)
                            object_status[ocode] += 1
                            oref = obj_ref(oval) if ocode == "0" else None
                            if oref:
                                resolved_cells += 1
                                object_file.write(json.dumps({"row": row, "column": col["column"],
                                                              "status": ocode, "object": oref}, ensure_ascii=False)+"\n")
                        if self.export_values:
                            row_values.append(csv_value(value))
                            row_codes.append(status)
                        if col["column"] % 256 == 255:
                            self.progress("{}: row {}/{}, column {}/{}.".format(entry["folder"], row+1, rows,
                                                                                 col["column"]+1, ncols))
                    axis.append(time_value)
                    row_writer.writerow([row, index_code, csv_value(index_value), object_code,
                                         (ref or {}).get("class", ""), (ref or {}).get("name", ""), (ref or {}).get("path", ""),
                                         axis_col, csv_value(time_value)])
                    if self.export_values:
                        data_writer.writerow([row] + row_values)
                        code_writer.writerow([row] + row_codes)
                    self.scanned += ncols
                    self.progress("{}: row {}/{}; {} data cells read so far.".format(entry["folder"], row+1, rows, self.scanned))
            finally:
                for stream in (rows_file, data_file, codes_file, object_file):
                    if stream is not None:
                        stream.close()
            statistics = [dict(col, statistics=stat.report()) for col, stat in zip(columns, stats)]
            for col in statistics:
                for name in ("minimum", "maximum", "first_finite", "last_finite"):
                    item = col["statistics"][name]
                    if item:
                        item["axis_value"] = axis[item["row"]]
            write_json(folder / "statistics.json", statistics)
            self.statistics_csv(folder, statistics)
            totals = Counter()
            for stat in stats:
                totals.update(stat.status)
            duplicates = {}
            for col in columns:
                owner = col["owner"] or {}
                duplicates.setdefault((owner.get("path", ""), col["variable"]), []).append(col["column"])
            owners = {col["owner"]["path"]: col["owner"] for col in columns if col["owner"] and col["owner"]["path"]}
            result.update(status="SCANNED", rows=rows, columns=ncols, data_cells=rows*ncols,
                          finite_values=sum(stat.n for stat in stats), non_finite_values=sum(stat.non_finite for stat in stats),
                          non_numeric_values=sum(stat.non_numeric for stat in stats), cell_status_counts=dict(totals),
                          variables=dict(Counter(col["variable"] for col in columns)),
                          unique_recorded_objects=len(owners),
                          unique_equipment=sum(equipment(ref) for ref in owners.values()),
                          equipment_by_class=dict(Counter(ref["class"] for ref in owners.values() if equipment(ref))),
                          recorded_objects_by_class=dict(Counter(ref["class"] for ref in owners.values())),
                          columns_without_readable_owner=sum(not col["owner"] for col in columns),
                          row_object_classes=dict(row_classes),
                          object_cell_scan_enabled=can_read_objects, object_cell_status_counts=dict(object_status),
                          resolved_object_cells=resolved_cells,
                          duplicate_object_variable_columns=[{"owner_path": k[0], "variable": k[1], "columns": v} for k,v in duplicates.items() if len(v)>1 and k[0]],
                          axis_column=axis_col, implicit_index_metadata=axis_meta if axis_col == -1 else self.column(obj, -1),
                          axis=time_summary(axis, axis_meta["unit"], axis_meta["variable"], row_classes, axis_col>=0),
                          raw_values_exported=self.export_values,
                          raw_values_note="Every cell exported; inspect data_codes.csv before interpreting data_values.csv." if self.export_values else "All cells scanned for statistics; raw-value export explicitly disabled.")
            return result
        finally:
            if loaded:
                result["release_return"] = encode(reader.call(obj, "Release"))
            write_json(folder / "result_summary.json", result)

    def column(self, obj, col):
        reader = self.reader
        raw = {name: reader.call(obj, method, col) for name, method in
               (("variable", "GetVariable"), ("unit", "GetUnit"), ("description", "GetDescription"), ("owner", "GetObject"))}
        owner = None if failed(raw["owner"]) else obj_ref(raw["owner"])
        if owner:
            key = identity(raw["owner"])
            self.recorded_objects[key] = owner
            if key not in self.owner_details:
                details = {"object": owner, "context": "current model metadata; not archived result values", "attributes": {}}
                for name in ("cpGrid", "uknom", "typ_id", "outserv", "desc"):
                    value = attr(raw["owner"], name)
                    if value is not None:
                        details["attributes"][name] = encode(value)
                        grid = obj_ref(value) if name == "cpGrid" else None
                        if grid:
                            self.grids[identity(value)] = grid
                self.owner_details[key] = details
            if equipment(owner):
                self.equipment[key] = owner
        owner_type = None
        if owner and not failed(raw["variable"]) and callable(attr(raw["owner"], "GetAttributeType")):
            owner_type = encode(reader.call(raw["owner"], "GetAttributeType", str(raw["variable"] or "")))
        return {"column": col, "key": "c{:06d}".format(col) if col >= 0 else "implicit_index",
                "variable": "" if failed(raw["variable"]) else str(raw["variable"] or ""),
                "unit": "" if failed(raw["unit"]) else str(raw["unit"] or ""),
                "description": encode(raw["description"]), "owner": owner,
                "variable_type_from_current_owner": owner_type,
                "metadata_returns": {key: encode(value) for key, value in raw.items()}}

    def column_csv(self, folder, columns):
        with (folder / "columns.csv").open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(["key", "column", "variable", "unit", "description", "object_class", "object_name", "object_path"])
            for col in columns:
                ref = col["owner"] or {}
                writer.writerow([col["key"], col["column"], col["variable"], col["unit"], csv_value(col["description"]),
                                 ref.get("class", ""), ref.get("name", ""), ref.get("path", "")])

    def statistics_csv(self, folder, columns):
        fields = ["column", "variable", "unit", "owner_path", "finite_values", "minimum", "minimum_row", "minimum_axis",
                  "maximum", "maximum_row", "maximum_axis", "mean", "population_stddev", "zero_values",
                  "positive_values", "negative_values", "non_finite_values", "non_numeric_values", "status_counts"]
        with (folder / "statistics.csv").open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            for col in columns:
                stat = col["statistics"]
                row = {key: csv_value(stat[key]) for key in fields if key in stat and key not in ("minimum", "maximum")}
                row.update(column=col["column"], variable=col["variable"], unit=col["unit"], owner_path=(col["owner"] or {}).get("path", ""))
                for key in ("minimum", "maximum"):
                    point = stat[key] or {}
                    row[key] = csv_value(point.get("value"))
                    row[key+"_row"] = point.get("row", "")
                    row[key+"_axis"] = csv_value(point.get("axis_value"))
                writer.writerow(row)

    def summarise(self, root, hierarchy, results):
        scanned = [r for r in results if r["status"] == "SCANNED"]
        status_counts = Counter()
        for result in scanned:
            status_counts.update(result["cell_status_counts"])
        variables = Counter()
        for result in scanned:
            variables.update(result["variables"])
        study_times = sorted({r["cnttime"] for r in scanned if "cnttime" in r and
                              (r.get("cnttime_is_subresult") or r["row_object_classes"].get("ComOutage"))})
        write_json(self.folder / "equipment.json", list(self.equipment.values()))
        write_json(self.folder / "recorded_objects.json", list(self.recorded_objects.values()))
        write_json(self.folder / "recorded_object_context.json", list(self.owner_details.values()))
        write_json(self.folder / "grids.json", list(self.grids.values()))
        write_json(self.folder / "row_objects.json", list(self.row_objects.values()))
        return {"inspector_version": INSPECTOR_VERSION, "created_utc": datetime.now(timezone.utc).isoformat(),
                "selected_result": obj_ref(root), "output_directory": str(self.folder),
                "discovered_objects": len(hierarchy), "result_objects": len(results), "scanned_results": len(scanned),
                "unreadable_results": len(results)-len(scanned), "results": results,
                "rows_summed_across_results": sum(r["rows"] for r in scanned),
                "columns_summed_across_results": sum(r["columns"] for r in scanned),
                "data_cells": self.scanned, "cell_status_counts": dict(status_counts),
                "variable_names_count": len(variables), "variable_columns_across_results": dict(variables),
                "finite_values": sum(r["finite_values"] for r in scanned),
                "non_finite_values": sum(r["non_finite_values"] for r in scanned),
                "non_numeric_values": sum(r["non_numeric_values"] for r in scanned),
                "counting_notes": "data_cells = rows x reported columns, excluding implicit column -1 and object-lookup probes. "
                                  "Finite/non-finite/non-numeric counts apply only to code-0 cells; nonzero statuses are counted separately.",
                "unique_recorded_objects": len(self.recorded_objects), "unique_equipment": len(self.equipment),
                "equipment_by_class": dict(Counter(ref["class"] for ref in self.equipment.values())),
                "unique_grids_from_current_column_owners": len(self.grids),
                "unique_row_objects": len(self.row_objects),
                "row_objects_by_class": dict(Counter(ref["class"] for ref in self.row_objects.values())),
                "subresult_study_times": time_summary(study_times, "s", "cnttime", {}, True) if study_times else None,
                "subresult_study_times_note": "Unique cnttime values of result children (or selected contingency sub-result); "
                                               "interpreted in seconds, as used by Outage Assessment PowerFactory 2026. No hours inferred from contingency row counts.",
                "time_axes": [{"object_path": r["object"]["path"], "axis": r["axis"]} for r in scanned],
                "read_exceptions": self.reader.error_count,
                "environment": {"python": sys.version, "platform": sys.platform,
                                "local_timezone": str(datetime.now().astimezone().tzinfo)},
                "coverage": {"all_rows_and_columns_scanned": len(scanned)==len(results),
                             "all_cell_read_statuses_valid_or_sparse": len(scanned)==len(results) and set(status_counts)<={"0", "3"},
                             "object_cell_scan_requested": RESOLVE_OBJECT_CELLS,
                             "subresults_enabled": self.subresults, "raw_values_exported": self.export_values,
                             "subresult_discovery": "GetContents tree; GetSubElmRes selectors are never changed.",
                             "equipment_definition": "Unique readable column-owner paths of Elm* classes except ElmRes, plus StaCubic. See recorded_objects.json for ALL owner classes.",
                             "not_guaranteed": "Undocumented attributes, external files, inaccessible result objects and references outside the selected object tree are not recursively inspected."},
                "status_code_legend": STATUS_MEANING}

    def write_report(self, summary, results):
        with (self.folder / "report.txt").open("w", encoding="utf-8") as stream:
            def out(text=""):
                stream.write(str(text)+"\n")
            out("POWERFACTORY RESULT OBJECT EXPLORER " + INSPECTOR_VERSION)
            out("="*76)
            out("Selected result: " + summary["selected_result"]["path"])
            out("All data cells scanned; no sampling. Current object metadata is not a historical snapshot.")
            for key in ("result_objects", "scanned_results", "unreadable_results", "discovered_objects",
                        "unique_equipment", "equipment_by_class", "unique_recorded_objects", "unique_row_objects",
                        "variable_names_count", "variable_columns_across_results", "subresult_study_times",
                        "rows_summed_across_results", "columns_summed_across_results", "data_cells", "finite_values",
                        "non_finite_values", "cell_status_counts", "read_exceptions"):
                out("{}: {}".format(key, summary[key]))
            out("\nImportant: rows of different sub-results can represent repeated times or contingencies. Do not add them as hours.")
            for result in results:
                out("\n" + "-"*76)
                out(result["object"]["path"])
                out("Folder: " + result["folder"])
                for key, value in result.items():
                    if key not in ("object", "folder"):
                        out("{}: {}".format(key, json.dumps(encode(value), ensure_ascii=False)))
                folder = self.folder / result["folder"]
                path = folder / "statistics.json"
                if path.exists():
                    out("\nEVERY RECORDED COLUMN AND ITS FULL STATISTICS")
                    for col in json.loads(path.read_text(encoding="utf-8")):
                        out(json.dumps(col, ensure_ascii=False))
            out("\nALL CONTAINED OBJECTS, RECORDING DEFINITIONS, ATTRIBUTES AND METHODS")
            for node in json.loads((self.folder / "hierarchy.json").read_text(encoding="utf-8")):
                out("\n" + node["object"]["path"])
                metadata = (self.folder / node["folder"] / "metadata.json").read_text(encoding="utf-8")
                out(metadata)
            out("\nCOMPLETENESS AND LIMITATIONS")
            out(json.dumps(summary["coverage"], ensure_ascii=False, indent=2))
            out("\nCode 3 is not recorded, NOT a measured zero. Nonzero codes and non-finite values are excluded from numeric statistics.")
            out("Missing method metadata and every read exception are preserved in metadata.json and read_errors.jsonl.")


def slug(value):
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value)).strip("._")[:45] or "result"


def main(app=None):
    if app is None:
        try:
            import powerfactory
            app = powerfactory.GetApplication()
        except ImportError as exc:
            raise RuntimeError("Run this file as a ComPython inside PowerFactory.") from exc
    if app is None:
        raise RuntimeError("No running PowerFactory application is available.")
    printer = attr(app, "PrintPlain", print)
    result, available = find_result(app, RESULT_NAME)
    if result is None:
        printer("[RESULT EXPLORER] {}".format("Set RESULT_NAME to an exact name or full path." if not RESULT_NAME.strip() else
                                            "No result object matches {!r}.".format(RESULT_NAME)))
        printer("[RESULT EXPLORER] Available ElmRes objects in the active project:")
        for obj in available:
            printer("  " + identity(obj))
        if not available:
            printer("  No ElmRes found in the active study case or active project.")
        return None
    base = Path(os.path.expandvars(OUTPUT_DIRECTORY)).expanduser() if OUTPUT_DIRECTORY else Path.home()/"Outage Assessment"/"result_inspections"
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    suffix = hashlib.sha256(identity(result).encode("utf-8")).hexdigest()[:8]
    folder = base / (stamp + "_" + slug(attr(result, "loc_name", "result")) + "_" + suffix)
    folder.mkdir(parents=True, exist_ok=False)
    explorer = Explorer(app, folder, EXPORT_ALL_VALUES, INSPECT_SUBRESULTS)
    return explorer.inspect(result)


if __name__ == "__main__":
    main()
