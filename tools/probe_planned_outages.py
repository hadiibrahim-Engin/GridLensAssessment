"""GridLens probe: report how PowerFactory 2026 models planned outages.

This is a diagnostic tool, not part of the GridLens delivery. Install it as a
separate ComPython script anywhere in the active study case and run it once.

By default the probe only reads. It writes nothing, starts no calculation and
leaves the project untouched. Setting RUN_EXPERIMENT to True additionally runs
the single controlled experiment described under "Experiment" below; that pass
records every value it writes, restores it in reverse order and verifies the
restoration before it returns.

What the probe answers:

1. Which attributes an IntPlannedout actually carries, with the type, unit and
   the description PowerFactory itself shows for each one.
2. Which equipment an outage points at, resolved to readable names.
3. What the quasi-dynamic command's calculation options are called in
   PowerFactory's own words - in particular whether iopt_maint is the switch
   that makes PowerFactory honour planned outages.
"""

import time

OUTAGE_CLASSES = ("IntPlannedout", "IntOutage")

# Attributes worth resolving into referenced objects rather than printing raw.
REFERENCE_ATTRIBUTES = ("components", "contents", "charact", "recsettings")

# Set to True to run the controlled apply experiment. See "Experiment" below.
RUN_EXPERIMENT = False

# Calculation option the experiment toggles. Change it once the descriptions
# printed by the read-only pass identify the correct switch.
EXPERIMENT_OPTION = "iopt_maint"

MAX_VALUE_LENGTH = 200

# Values at or above 1980-01-01 are absolute epoch seconds, not elapsed time.
EPOCH_THRESHOLD_SECONDS = 315532800.0


def emit(app, message):
    printer = getattr(app, "PrintPlain", None)
    if callable(printer):
        try:
            printer(message)
            return
        except Exception:
            pass
    print(message, flush=True)


def call(method, *args):
    """Call a PowerFactory method, tolerating its argument-count variants."""
    try:
        return method(*args)
    except TypeError:
        try:
            return method(*(args + (0,)))
        except Exception:
            return None
    except Exception:
        return None


def safe(obj, name, default=None):
    try:
        value = getattr(obj, name)
    except Exception:
        return default
    return default if value is None else value


def class_of(obj):
    try:
        return str(obj.GetClassName())
    except Exception:
        return ""


def name_of(obj):
    value = safe(obj, "loc_name", "")
    if value:
        return str(value)
    try:
        return str(obj.GetFullName()).rsplit("\\", 1)[-1]
    except Exception:
        return "<unnamed>"


def render(value):
    if isinstance(value, (list, tuple)):
        parts = []
        for item in value:
            if hasattr(item, "GetClassName"):
                parts.append("{} '{}'".format(class_of(item), name_of(item)))
            else:
                parts.append(str(item))
        text = "[{}]".format(", ".join(parts)) if parts else "[]"
    elif hasattr(value, "GetClassName"):
        text = "{} '{}'".format(class_of(value), name_of(value))
    else:
        text = str(value)
    if len(text) > MAX_VALUE_LENGTH:
        text = text[:MAX_VALUE_LENGTH] + " ...(truncated)"
    return text


def attribute_names(obj, app=None):
    """Attribute names, preferring PowerFactory's own accessor over dir()."""
    for getter_name in ("GetAttributes", "GetAttributeNames"):
        getter = safe(obj, getter_name)
        if not callable(getter):
            continue
        try:
            returned = getter()
        except TypeError:
            try:
                returned = getter(0)
            except Exception as exc:
                if app:
                    emit(app, "    (note: {}() needs other arguments: {})".format(
                        getter_name, exc))
                continue
        except Exception as exc:
            if app:
                emit(app, "    (note: {}() failed: {})".format(getter_name, exc))
            continue
        try:
            names = sorted({str(item).strip() for item in returned or ()
                            if str(item).strip()})
        except TypeError:
            names = []
        if names:
            return names
        if app:
            emit(app, "    (note: {}() returned {}; falling back to dir())"
                 .format(getter_name, render(returned)))
    names = []
    try:
        candidates = sorted(dir(obj))
    except Exception:
        candidates = []
    for name in candidates:
        if name.startswith("_"):
            continue
        value = safe(obj, name)
        if value is None or callable(value):
            continue
        names.append(name)
    return names


def describe_attribute(obj, name):
    """Return 'name [type, unit] = value  -- PowerFactory description'."""
    value = safe(obj, name)
    if value is None:
        getter = safe(obj, "GetAttribute")
        if callable(getter):
            value = call(getter, name)
    kind = ""
    for getter_name in ("GetAttributeType", "AttributeType"):
        getter = safe(obj, getter_name)
        if callable(getter):
            returned = call(getter, name)
            if returned is not None:
                kind = str(returned)
                break
    unit = ""
    getter = safe(obj, "GetAttributeUnit")
    if callable(getter):
        returned = call(getter, name)
        if returned:
            unit = str(returned)
    description = ""
    getter = safe(obj, "GetAttributeDescription")
    if callable(getter):
        returned = call(getter, name)
        if returned:
            description = str(returned)
    signature = ", ".join(part for part in (kind, unit) if part)
    line = "    {}{} = {}".format(
        name, " [{}]".format(signature) if signature else "", render(value))
    if description:
        line += "   -- {}".format(description)
    return line


def report_object(app, obj, heading):
    emit(app, "")
    emit(app, "  {}".format(heading))
    emit(app, "  class: {}".format(class_of(obj) or "<unknown>"))
    try:
        emit(app, "  path : {}".format(obj.GetFullName()))
    except Exception:
        pass
    names = attribute_names(obj, app)
    if not names:
        emit(app, "    <the object declares no attributes through GetAttributes>")
        return
    emit(app, "  attributes ({}):".format(len(names)))
    for name in names:
        emit(app, describe_attribute(obj, name))
    for name in REFERENCE_ATTRIBUTES:
        value = safe(obj, name)
        objects = value if isinstance(value, (list, tuple)) else [value]
        resolved = [item for item in objects if hasattr(item, "GetClassName")]
        if resolved:
            emit(app, "  {} resolves to:".format(name))
            for item in resolved:
                emit(app, "      {} '{}' (out of service: {})".format(
                    class_of(item), name_of(item), safe(item, "outserv", "?")))
    getter = safe(obj, "GetReferences")
    if callable(getter):
        references = call(getter) or []
        if references:
            emit(app, "  referenced by:")
            for item in references:
                emit(app, "      {} '{}'".format(class_of(item), name_of(item)))
    children = call(safe(obj, "GetContents"), "*", 1) or []
    if children:
        emit(app, "  children:")
        for child in children:
            emit(app, "      {} '{}'".format(class_of(child), name_of(child)))


def find_outages(app):
    roots = []
    getter = safe(app, "GetProjectFolder")
    if callable(getter):
        for key in ("outage", "outages"):
            folder = call(getter, key)
            if folder is not None:
                roots.append(folder)
    try:
        project = app.GetActiveProject()
        if project is not None:
            roots.append(project)
    except Exception:
        pass
    found = {}
    for root in roots:
        for outage_class in OUTAGE_CLASSES:
            for item in call(safe(root, "GetContents"),
                             "*.{}".format(outage_class), 1) or []:
                if class_of(item) in OUTAGE_CLASSES:
                    try:
                        found[str(item.GetFullName())] = item
                    except Exception:
                        found[name_of(item)] = item
    return [found[key] for key in sorted(found)]


def report_command_options(app, command, heading):
    """Print every calculation option with PowerFactory's own description."""
    emit(app, "")
    emit(app, "  {}".format(heading))
    names = attribute_names(command, app)
    options = [name for name in names if name.startswith("iopt_")]
    if not options:
        options = [name for name in dir(command) if name.startswith("iopt_")]
    if not options:
        emit(app, "    <no iopt_* options exposed>")
        return
    emit(app, "  calculation options ({}):".format(len(options)))
    for name in sorted(set(options)):
        emit(app, describe_attribute(command, name))
    interesting = [name for name in names
                   if any(token in name.lower() for token in
                          ("maint", "outag", "plan", "sched", "time", "date"))]
    if interesting:
        emit(app, "  time- and outage-related attributes:")
        for name in sorted(set(interesting)):
            emit(app, describe_attribute(command, name))


def to_number(value):
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def study_clock_from_epoch(seconds):
    """Return (cDate, cTime) in PowerFactory's YYYYMMDD / HHMMSSxx encoding."""
    stamp = time.localtime(seconds)
    date = stamp.tm_year * 10000 + stamp.tm_mon * 100 + stamp.tm_mday
    clock = stamp.tm_hour * 10000 + stamp.tm_min * 100 + stamp.tm_sec
    return date, clock


def experiment(app, qds, outages):
    """Toggle one calculation option and report what changes.

    The experiment sets the study case clock into the first outage's window,
    switches EXPERIMENT_OPTION on, runs the quasi-dynamic command once and
    reports whether the affected equipment reports itself out of service.
    Every written value is restored afterwards and the restoration is verified.
    """
    emit(app, "")
    emit(app, "=== EXPERIMENT: does {} apply planned outages? ===".format(
        EXPERIMENT_OPTION))
    if not outages:
        emit(app, "  No planned outage found; the experiment was skipped.")
        return
    outage = outages[0]
    start = safe(outage, "starttime")
    emit(app, "  Outage under test: '{}' starttime={} endtime={}".format(
        name_of(outage), render(start), render(safe(outage, "endtime"))))
    study_time = None
    getter = safe(app, "GetFromStudyCase")
    if callable(getter):
        study_time = call(getter, "SetTime")
    if study_time is None:
        emit(app, "  The study case clock is not reachable; nothing was changed.")
        return

    written = []

    def write(obj, attribute, value):
        previous = safe(obj, attribute)
        # SetTime.cDate and cTime are strings in PowerFactory 2026, so offer
        # the new value in whatever type the attribute already holds.
        candidates = [value]
        if isinstance(previous, str) and not isinstance(value, str):
            candidates.insert(0, str(value))
        elif not isinstance(previous, str) and isinstance(value, str):
            candidates.insert(0, type(previous)(value))
        last_error = None
        for candidate in candidates:
            try:
                setattr(obj, attribute, candidate)
            except Exception as exc:
                last_error = exc
                continue
            written.append((obj, attribute, previous))
            emit(app, "  set {} from {} to {}".format(
                attribute, render(previous), render(candidate)))
            return True
        emit(app, "  Could not set {} = {}: {}".format(
            attribute, value, last_error))
        return False

    try:
        components = safe(outage, "components")
        affected = [item for item in
                    (components if isinstance(components, (list, tuple))
                     else [components])
                    if hasattr(item, "GetClassName")]
        emit(app, "  Equipment state before: {}".format(
            ", ".join("{}={}".format(name_of(item), safe(item, "outserv", "?"))
                      for item in affected) or "<no equipment resolved>"))
        begin = to_number(start)
        finish = to_number(safe(outage, "endtime"))
        if begin is not None and begin >= EPOCH_THRESHOLD_SECONDS:
            target = (begin + finish) / 2.0 if finish and finish > begin else begin
            date, clock = study_clock_from_epoch(target)
            emit(app, "  Moving the study clock into the outage window: {}".format(
                time.strftime("%Y-%m-%d %H:%M", time.localtime(target))))
            write(study_time, "cDate", date)
            write(study_time, "cTime", clock)
        else:
            emit(app, "  starttime={} is not absolute epoch time, so the study "
                      "clock was left alone. Set it into the outage window by "
                      "hand before rerunning the experiment.".format(render(start)))
        if not write(qds, EXPERIMENT_OPTION, 1):
            return
        emit(app, "  Running the quasi-dynamic command once ...")
        returned = call(safe(qds, "Execute"))
        emit(app, "  Execute returned {}".format(render(returned)))
        emit(app, "  Equipment state after: {}".format(
            ", ".join("{}={}".format(name_of(item), safe(item, "outserv", "?"))
                      for item in affected) or "<no equipment resolved>"))
        for item in affected:
            checker = safe(item, "IsOutOfService")
            if callable(checker):
                emit(app, "  {}.IsOutOfService() = {}".format(
                    name_of(item), render(call(checker))))
    finally:
        emit(app, "  Restoring every value the experiment wrote ...")
        failures = []
        for obj, attribute, previous in reversed(written):
            try:
                setattr(obj, attribute, previous)
            except Exception as exc:
                failures.append("{}: {}".format(attribute, exc))
                continue
            if safe(obj, attribute) != previous:
                failures.append("{} did not take the restored value".format(
                    attribute))
        if failures:
            emit(app, "  RESTORE FAILED: {}".format("; ".join(failures)))
            emit(app, "  Check the study case manually before calculating again.")
        else:
            emit(app, "  Restore verified; the project is back in its prior state.")


def main():
    try:
        import powerfactory
    except ImportError:
        print("Run this probe from DIgSILENT PowerFactory 2026.", flush=True)
        return
    app = powerfactory.GetApplication()
    if app is None:
        print("PowerFactory returned no application object.", flush=True)
        return

    emit(app, "=== GridLens planned-outage probe (read-only) ===")
    try:
        project = app.GetActiveProject()
        emit(app, "Project    : {}".format(name_of(project) if project else "<none>"))
    except Exception:
        emit(app, "Project    : <unreadable>")
    study_case = None
    try:
        study_case = app.GetActiveStudyCase()
        emit(app, "Study case : {}".format(
            name_of(study_case) if study_case else "<none>"))
    except Exception:
        emit(app, "Study case : <unreadable>")
    study_time = call(safe(app, "GetFromStudyCase"), "SetTime")
    if study_time is not None:
        emit(app, "Study time : cDate={} cTime={}".format(
            render(safe(study_time, "cDate")), render(safe(study_time, "cTime"))))
        report_object(app, study_time, "STUDY CASE CLOCK")

    outages = find_outages(app)
    emit(app, "")
    emit(app, "=== PLANNED OUTAGES ({}) ===".format(len(outages)))
    for index, outage in enumerate(outages, 1):
        report_object(app, outage, "OUTAGE {}/{}: '{}'".format(
            index, len(outages), name_of(outage)))

    qds = call(safe(app, "GetFromStudyCase"), "ComStatsim")
    emit(app, "")
    emit(app, "=== CALCULATION COMMANDS ===")
    if qds is None:
        emit(app, "  No ComStatsim in the active study case.")
    else:
        report_command_options(app, qds, "ComStatsim '{}'".format(name_of(qds)))
        for attribute in ("p_ldf", "pLdf", "ldf", "c_butldf"):
            embedded = safe(qds, attribute)
            if embedded is not None and hasattr(embedded, "GetClassName"):
                report_command_options(
                    app, embedded, "Embedded {} '{}' [{}]".format(
                        class_of(embedded), name_of(embedded), attribute))
                break
    load_flow = call(safe(app, "GetFromStudyCase"), "ComLdf")
    if load_flow is not None:
        report_command_options(
            app, load_flow, "ComLdf '{}'".format(name_of(load_flow)))

    if RUN_EXPERIMENT and qds is not None:
        experiment(app, qds, outages)
    else:
        emit(app, "")
        emit(app, "Read-only pass finished. Nothing in the project was changed.")
        emit(app, "Set RUN_EXPERIMENT = True to run the controlled apply test.")


if __name__ == "__main__":
    main()
