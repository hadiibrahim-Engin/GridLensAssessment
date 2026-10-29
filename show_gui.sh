#!/usr/bin/env bash
# Open the existing Outage Assessment Case Manager preview. No calculation is started.
# Usage: ./show_gui.sh
# Optional interpreter override: OUTAGE_ASSESSMENT_PYTHON=/path/to/python ./show_gui.sh
set -euo pipefail

project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
gui_script="$project_dir/ui/FS_CaseManager_GUI_Test_PowerFactory2026.py"

if [[ ! -f "$gui_script" ]]; then
    printf 'Outage Assessment GUI script not found: %s\n' "$gui_script" >&2
    exit 1
fi

if [[ -n "${OUTAGE_ASSESSMENT_PYTHON:-}" ]]; then
    candidates=("$OUTAGE_ASSESSMENT_PYTHON")
else
    candidates=("$project_dir/.venv/bin/python" python3.11 python3 python)
fi

for candidate in "${candidates[@]}"; do
    if command -v "$candidate" >/dev/null 2>&1 &&
       "$candidate" -c 'import tkinter, tkinter.ttk, tkinter.font' >/dev/null 2>&1; then
        printf 'Opening Outage Assessment Case Manager with %s\n' "$candidate"
        exec "$candidate" -u "$gui_script"
    fi
done

printf '%s\n' \
    'No Python interpreter with Tkinter was found.' \
    'Set OUTAGE_ASSESSMENT_PYTHON to a Python installation that includes Tcl/Tk.' >&2
exit 1
