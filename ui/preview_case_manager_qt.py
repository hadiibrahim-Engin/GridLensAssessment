"""Open the production Qt case manager with fictitious outages, without PowerFactory."""

from __future__ import annotations

import importlib.util
import tempfile
from datetime import datetime, timedelta
from pathlib import Path


def main():
    script = Path(__file__).resolve().parents[1] / "outage-assessment" / "main_qt.py"
    spec = importlib.util.spec_from_file_location("outage_assessment_qt_preview", script)
    runtime = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runtime)

    start = datetime(2026, 11, 9, 8)
    records = []
    for index, (name, equipment, day, duration) in enumerate([
        ("Line maintenance", "Line 110 kV North", 0, 48),
        ("Transformer inspection", "Transformer T1", 1, 24),
        ("Busbar maintenance", "Busbar West", 3, 12),
        ("Cable replacement", "Cable South", 4, 48),
    ], 1):
        begin = start + timedelta(days=day)
        end = begin + timedelta(hours=duration)
        records.append({
            "key": f"Demo/Outages/{index}.IntPlannedout", "id": str(index),
            "name": name, "window": (begin.timestamp(), end.timestamp()),
            "component_keys": [f"Demo/{equipment}"], "equipment_name": equipment,
            "start_time": begin.strftime("%Y-%m-%d %H:%M"),
            "end_time": end.strftime("%Y-%m-%d %H:%M"), "priority": 1,
            "originally_ignored": False, "status": runtime.OUTAGE_CONSIDERED,
        })
    config = runtime.empty_case_config("Fictitious preview project")
    config["cases"] = [
        {"id": "C1", "name": "North maintenance", "outages": [r["key"] for r in records[:2]]},
        {"id": "C2", "name": "West and South maintenance", "outages": [r["key"] for r in records[2:]]},
    ]
    period = (start.timestamp(), (start + timedelta(days=7)).timestamp())
    # Save/load in this preview uses disposable files, independent of real cases.
    with tempfile.TemporaryDirectory(prefix="outage-qt-preview-") as directory:
        print("Qt preview: fictitious data. Start calculation closes the preview; nothing is calculated.", flush=True)
        outcome = runtime.run_case_manager(
            records, config, period, str(Path(directory) / "cases.json"),
            user="Preview", qds_text="Fictitious data · 9–16 November 2026",
            grids=["Demo 110 kV"], contingencies=None,
        )
        print("Preview closed." if outcome is None else "Configuration accepted. No calculation was started.")


if __name__ == "__main__":
    main()
