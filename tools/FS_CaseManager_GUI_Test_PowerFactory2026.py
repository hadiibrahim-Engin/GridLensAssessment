# -*- coding: utf-8 -*-
"""
FS-Case-Manager: sicherer GUI-Funktionstest für DIgSILENT PowerFactory 2026.

Abhängigkeiten: ausschließlich Python-Standardbibliothek (+ optionale
PowerFactory-API, sofern innerhalb von PowerFactory gestartet).

WICHTIG: Dieses Skript schreibt KEINE PowerFactory-Attribute, führt KEINE QDS
und KEINE Schalthandlungen aus, legt KEINE Projektobjekte an und speichert
KEINE Projektdateien. Nach OK wird die Fallzuordnung nur im Output ausgegeben.

Testziele:
  1. Funktioniert import tkinter samt Tcl/Tk?
  2. Öffnet sich ein Fenster aus einem PowerFactory-ComPython heraus?
  3. Können mehrere Fälle erzeugt und Planned Outages zugeordnet werden?
  4. Kommt die bestätigte Auswahl korrekt in Python zurück?

Einfügen: PowerFactory > ComPython > Skripttext einfügen und ausführen.
Nicht in das produktive GridLens-Skript integrieren, bevor der Test bestanden ist.
"""

from __future__ import annotations

import json
import sys
import traceback


DEMO_OUTAGES = [
    {"id": "demo-FS-001", "name": "FS-001 – Leitung L100", "period": "KW 10"},
    {"id": "demo-FS-002", "name": "FS-002 – Transformator T200", "period": "KW 40"},
    {"id": "demo-FS-003", "name": "FS-003 – Leitung L300", "period": "KW 10"},
    {"id": "demo-FS-004", "name": "FS-004 – Leitung L400", "period": "KW 20"},
]


def log(app, msg):
    message = "[FS-GUI-TEST] " + str(msg)
    if app is not None:
        try:
            app.PrintPlain(message)
            return
        except Exception:
            pass
    print(message, flush=True)


def read_attr(obj, name, default=""):
    try:
        value = getattr(obj, name)
        return default if value is None else value
    except Exception:
        return default


def full_key(obj):
    try:
        value = obj.GetFullName()
        if value:
            return str(value)
    except Exception:
        pass
    return str(read_attr(obj, "loc_name", "Unbekannte FS"))


def object_name(obj):
    return str(read_attr(obj, "loc_name", "Unbekannte FS"))


def find_outages(app):
    """Read-only discovery. Avoid an expensive recursive scan of the full grid.

    The project folder key depends on the installed PowerFactory version and
    configuration. If it cannot be read, run the GUI in unmistakable demo mode.
    """
    if app is None:
        return [], "PowerFactory-API nicht verfügbar"

    roots = []
    get_folder = getattr(app, "GetProjectFolder", None)
    if callable(get_folder):
        for key in ("outage", "outages"):
            try:
                folder = get_folder(key)
                if folder is not None and all(folder is not x for x in roots):
                    roots.append(folder)
            except Exception:
                continue

    if not roots:
        return [], "Outage-Projektordner nicht über GetProjectFolder gefunden"

    found = {}
    for root in roots:
        for cls in ("IntPlannedout",):
            try:
                members = list(root.GetContents("*." + cls, 1) or [])
            except TypeError:
                try:
                    members = list(root.GetContents("*." + cls) or [])
                except Exception:
                    members = []
            except Exception:
                members = []
            for obj in members:
                key = full_key(obj)
                if key not in found:
                    # Dates shown as raw values deliberately: no unverified
                    # PowerFactory-specific time conversion is applied here.
                    start = read_attr(obj, "startTime", "")
                    end = read_attr(obj, "endTime", "")
                    period = "{} – {}".format(start, end) if start != "" or end != "" else "Zeitraum in PowerFactory"
                    found[key] = {"id": key, "name": object_name(obj), "period": period}
    return sorted(found.values(), key=lambda x: (x["name"].casefold(), x["id"])), ""


def launch_dialog(tk, ttk, simpledialog, app, outages, source):
    """Edit the same in-memory assignments in a matrix or a single-case view."""
    root = tk.Tk()
    try:
        return _run_dialog(root, tk, ttk, simpledialog, app, outages, source)
    finally:
        root.destroy()


def _run_dialog(root, tk, ttk, simpledialog, app, outages, source):
    root.title("GridLens - Case Manager (GUI test, no calculation)")
    root.geometry("1040x630")
    root.minsize(740, 460)

    result = {"confirmed": False, "cases": {}, "source": source}
    assignments = {"Case A": set()}
    case_counter = [1]
    active_case = tk.StringVar(value="Case A")
    view = tk.StringVar(value="matrix")
    summary = tk.StringVar(value="")
    variables = []
    count_labels = {}

    outer = ttk.Frame(root, padding=12)
    outer.pack(fill="both", expand=True)
    ttk.Label(outer, text="Case Manager - Assignment Matrix",
              font=("Segoe UI", 15, "bold")).pack(anchor="w")
    ttk.Label(outer, text="Test mode: no calculation or changes to Planned Outages or project state.").pack(
        anchor="w", pady=(4, 7))
    info = ("Source: REAL Planned Outages from PowerFactory" if source == "PowerFactory"
            else "Source: DEMO DATA - Outage Library unavailable or empty")
    ttk.Label(outer, text=info, foreground=("#14623e" if source == "PowerFactory" else "#a05a00")).pack(
        anchor="w", pady=(0, 11))

    toolbar = ttk.Frame(outer)
    toolbar.pack(fill="x", pady=(0, 10))
    ttk.Label(toolbar, text="View:").pack(side="left", padx=(0, 5))
    # Commands are connected after the table and callbacks have been created.
    matrix_button = ttk.Radiobutton(toolbar, text="Matrix", variable=view, value="matrix")
    matrix_button.pack(side="left", padx=(0, 8))
    single_button = ttk.Radiobutton(toolbar, text="Single case", variable=view, value="single")
    single_button.pack(side="left", padx=(0, 16))
    ttk.Label(toolbar, text="Selected case:").pack(side="left", padx=(0, 5))
    case_selector = ttk.Combobox(toolbar, textvariable=active_case, state="readonly", width=20)
    case_selector.pack(side="left", padx=(0, 10))
    actions = ttk.Frame(outer)
    actions.pack(fill="x", pady=(0, 10))

    body = ttk.LabelFrame(outer, text="Outage assignments", padding=8)
    body.pack(fill="both", expand=True)
    viewport = ttk.Frame(body)
    viewport.pack(fill="both", expand=True)
    viewport.grid_rowconfigure(0, weight=1)
    viewport.grid_columnconfigure(0, weight=1)
    canvas = tk.Canvas(viewport, borderwidth=0, highlightthickness=0)
    vertical = ttk.Scrollbar(viewport, orient="vertical", command=canvas.yview)
    horizontal = ttk.Scrollbar(viewport, orient="horizontal", command=canvas.xview)
    table = ttk.Frame(canvas)
    window_id = canvas.create_window((0, 0), window=table, anchor="nw")
    canvas.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
    canvas.grid(row=0, column=0, sticky="nsew")
    vertical.grid(row=0, column=1, sticky="ns")
    horizontal.grid(row=1, column=0, sticky="ew")
    def resize_table(_event=None):
        canvas.itemconfigure(window_id, width=max(canvas.winfo_width(), table.winfo_reqwidth()))
        canvas.configure(scrollregion=canvas.bbox("all"))

    table.bind("<Configure>", resize_table)
    canvas.bind("<Configure>", resize_table)

    def refresh_summary():
        for case, label in count_labels.items():
            label.set("{} selected".format(len(assignments[case])))
        total = sum(len(ids) for ids in assignments.values())
        if view.get() == "matrix":
            summary.set("{} outages | {} cases | {} assignments".format(
                len(outages), len(assignments), total))
        else:
            current = active_case.get()
            summary.set("{} of {} outages selected for {}".format(
                len(assignments[current]), len(outages), current))

    def refresh_table(_event=None):
        for widget in table.winfo_children():
            widget.destroy()
        variables.clear()
        count_labels.clear()
        names = list(assignments)
        if active_case.get() not in assignments:
            active_case.set(names[0])
        case_selector.configure(values=names)
        shown = names if view.get() == "matrix" else [active_case.get()]
        ttk.Label(table, text="Planned outage", width=34, anchor="w").grid(
            row=0, column=0, sticky="ew", padx=8, pady=(4, 10))
        ttk.Label(table, text="Period", width=22, anchor="w").grid(
            row=0, column=1, sticky="ew", padx=8, pady=(4, 10))
        for column, case in enumerate(shown, 2):
            ttk.Label(table, text=case, width=22, wraplength=160, anchor="center").grid(
                row=0, column=column, sticky="ew", padx=8, pady=(4, 10))
        for row, item in enumerate(outages, 1):
            ttk.Label(table, text=item["name"], wraplength=260, anchor="w").grid(
                row=row, column=0, sticky="ew", padx=8, pady=8)
            ttk.Label(table, text=str(item["period"]), wraplength=175, anchor="w").grid(
                row=row, column=1, sticky="ew", padx=8, pady=8)
            for column, case in enumerate(shown, 2):
                checked = tk.BooleanVar(value=item["id"] in assignments[case])
                variables.append(checked)

                def update(item_id=item["id"], flag=checked, name=case):
                    if flag.get():
                        assignments[name].add(item_id)
                    else:
                        assignments[name].discard(item_id)
                    # Keep the cell alive so keyboard focus stays in the matrix.
                    refresh_summary()

                ttk.Checkbutton(table, variable=checked, command=update).grid(
                    row=row, column=column, padx=8, pady=8)
        if not outages:
            ttk.Label(table, text="No outages available.").grid(
                row=1, column=0, columnspan=2 + len(shown), sticky="w", padx=8, pady=8)
        totals_row = len(outages) + 2
        for column, case in enumerate(shown, 2):
            count = tk.StringVar(value="")
            count_labels[case] = count
            ttk.Label(table, textvariable=count, anchor="center").grid(
                row=totals_row, column=column, sticky="ew", padx=8, pady=(10, 4))
        refresh_summary()
        # Recompute the canvas width after adding or removing case columns;
        # waiting for a window resize would leave new columns inaccessible.
        table.update_idletasks()
        resize_table()

    def add_case():
        case_counter[0] += 1
        ordinal = case_counter[0]
        suggested = "Case {}".format(chr(64 + ordinal)) if ordinal <= 26 else "Case {}".format(ordinal)
        while True:
            name = simpledialog.askstring("New case", "Name of the new assessment case:",
                                          initialvalue=suggested, parent=root)
            if name is None:
                return
            name = name.strip()
            if name and name not in assignments:
                break
            log(app, "The case name is empty or already exists; please try again.")
        assignments[name] = set()
        active_case.set(name)
        refresh_table()

    def remove_case():
        if len(assignments) == 1:
            log(app, "At least one case must remain.")
            return
        del assignments[active_case.get()]
        active_case.set(next(iter(assignments)))
        refresh_table()

    matrix_button.configure(command=refresh_table)
    single_button.configure(command=refresh_table)
    case_selector.bind("<<ComboboxSelected>>", refresh_table)
    ttk.Button(actions, text="+ Case", command=add_case).pack(side="left", padx=(0, 6))
    ttk.Button(actions, text="Delete case", command=remove_case).pack(side="left")
    ttk.Label(body, textvariable=summary).pack(anchor="w", pady=(8, 0))

    footer = ttk.Frame(outer)
    footer.pack(fill="x", pady=(12, 0))
    ttk.Label(footer, text="OK prints the assignments to the output window only.").pack(side="left")

    def confirm():
        result["confirmed"] = True
        result["cases"] = {case: sorted(ids) for case, ids in assignments.items()}
        root.quit()

    def cancel():
        result["confirmed"] = False
        result["cases"] = {}
        root.quit()

    ttk.Button(footer, text="OK (test only)", command=confirm).pack(side="right", padx=(7, 0))
    ttk.Button(footer, text="Cancel", command=cancel).pack(side="right")
    root.protocol("WM_DELETE_WINDOW", cancel)
    root.bind("<Escape>", lambda _event: cancel())
    root.after(150, root.lift)
    refresh_table()
    root.mainloop()
    return result



def main():
    app = None
    try:
        import powerfactory
        app = powerfactory.GetApplication()
    except Exception as exc:
        print("[FS-GUI-TEST] Hinweis: PowerFactory nicht verfügbar: {}".format(exc))

    log(app, "Python-Version: {}".format(sys.version.split()[0]))
    log(app, "Dieser Test verändert weder Netz- noch QDS-Einstellungen.")
    try:
        import tkinter as tk
        from tkinter import ttk, simpledialog
        log(app, "Import tkinter / ttk / simpledialog erfolgreich.")
        log(app, "Tcl-Version: {}, Tk-Version: {}".format(tk.TclVersion, tk.TkVersion))
    except Exception as exc:
        log(app, "FEHLER: tkinter konnte nicht importiert werden: {}".format(repr(exc)))
        log(app, "Die benutzte Python-Installation enthält eventuell keine Tcl/Tk-Unterstützung.")
        return False

    outages, warning = find_outages(app)
    if warning:
        log(app, "Outage-Suche: {}".format(warning))
    if outages:
        source = "PowerFactory"
        log(app, "{} Planned Outages gefunden (nur gelesen).".format(len(outages)))
    else:
        source = "DEMO"
        outages = DEMO_OUTAGES
        log(app, "DEMO-MODUS: {} synthetische Planned Outages.".format(len(outages)))

    try:
        selection = launch_dialog(tk, ttk, simpledialog, app, outages, source)
    except Exception:
        log(app, "FEHLER beim Start oder Betrieb des Tk-Fensters:\n" + traceback.format_exc())
        return False

    if not selection["confirmed"]:
        log(app, "Abbrechen: keine Konfiguration übernommen, keine Berechnung gestartet.")
        return True

    log(app, "OK: Fallzuordnung erfolgreich zurückgegeben.")
    log(app, "Auswahl (JSON):\n" + json.dumps(selection, ensure_ascii=False, indent=2))
    log(app, "ERFOLG: GUI-Test abgeschlossen. Keine PowerFactory-Objekte geändert; keine QDS gestartet.")
    return True


if __name__ == "__main__":
    main()
