#!/usr/bin/env bash
# Open the Qt Case Manager with fictitious data. No calculation is started.
# Usage: ./show_gui.sh
# Optional interpreter override: OUTAGE_ASSESSMENT_PYTHON=/path/to/python ./show_gui.sh
set -euo pipefail

project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
gui_script="$project_dir/ui/preview_case_manager_qt.py"

if [[ ! -f "$gui_script" ]]; then
    printf 'Outage Assessment GUI script not found: %s\n' "$gui_script" >&2
    exit 1
fi

if [[ -n "${OUTAGE_ASSESSMENT_PYTHON:-}" ]]; then
    candidates=("$OUTAGE_ASSESSMENT_PYTHON")
else
    candidates=("$project_dir/.venv/bin/python" "$project_dir/../.venv/bin/python" python3.11 python3 python)
fi

for candidate in "${candidates[@]}"; do
    if command -v "$candidate" >/dev/null 2>&1 &&
       "$candidate" -c 'import importlib.util; import sys; sys.exit(not any(importlib.util.find_spec(m) for m in ("PyQt6", "PyQt5")))' >/dev/null 2>&1; then
        printf 'Opening Qt Outage Assessment Case Manager with %s\n' "$candidate"
        exec "$candidate" -u "$gui_script" "$@"
    fi
done

printf '%s\n' \
    'No Python interpreter with PyQt6 or PyQt5 was found.' \
    'Install PyQt6: .venv/bin/python -m pip install PyQt6' \
    'Or set OUTAGE_ASSESSMENT_PYTHON to a Python installation with PyQt.' >&2
exit 1
