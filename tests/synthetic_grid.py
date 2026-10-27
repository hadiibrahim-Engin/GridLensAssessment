"""SYNTHETIC TEST DATA – fictitious contingency results for the GridLens reporting tests (no PowerFactory).

Every name starts with "TEST" and every grid is a "TEST area". The results are
produced study time by study time, the way the reporting core reads a kept
contingency result: per study time the contingencies that have a row and the
values beyond the recording limits (loading above 80 %, voltage outside
0.95–1.05 p.u.); every other cell is inside the recording limits and is not
stored. Nothing is materialised as a dense time x contingency x element array.
The default profile is the minimum test profile of the reporting assignment:
5,000 nodes, 3,400 lines, 210 transformers, 320 contingencies, 6 planning
scenarios, 84 study times at 2 hours. By default every branch and node can
carry a recorded value, so nearly every element becomes critical (a stress
profile); `weak=N` lets only N branches and N nodes leave the recording limits,
closer to a real network.
"""

import math
import random

EPOCH = 1767225600.0  # 2026-01-01 00:00 UTC
AREAS = ("TEST area North", "TEST area East", "TEST area South", "TEST area West", "TEST area Centre")
RECORDING = {"loading": (80.0,), "voltage": (0.95, 1.05)}


class Grid:
    """The fictitious network: elements, contingencies (one line each), study times and scenarios."""

    def __init__(self, nodes=5000, lines=3400, transformers=210, contingencies=320, times=84, step_hours=2,
                 scenarios=6, seed=7, long_names=False, weak=None):
        self.seed = seed
        self.lines = ["TEST\\Lines\\L{:04d}.ElmLne".format(i) for i in range(1, lines + 1)]
        self.transformers = ["TEST\\Transformers\\T{:03d}.ElmTr2".format(i) for i in range(1, transformers + 1)]
        self.nodes = ["TEST\\Nodes\\N{:04d}.ElmTerm".format(i) for i in range(1, nodes + 1)]
        suffix = " with a deliberately long equipment designation for the layout test" if long_names else ""
        self.meta = {"elements": {}, "categories": {}, "nominal_kv": {}, "grids": {}, "contingencies": {}}
        for index, key in enumerate(self.lines + self.transformers + self.nodes):
            name = key.split("\\")[-1].split(".")[0]
            self.meta["elements"][key] = "TEST " + name + (suffix if index % 97 == 0 else "")
            self.meta["categories"][key] = ("line" if key.endswith("ElmLne") else
                                            "transformer" if key.endswith("ElmTr2") else "voltage")
            self.meta["grids"][key] = AREAS[index % len(AREAS)]
            if key.endswith("ElmTerm"):
                self.meta["nominal_kv"][key] = (380.0, 220.0, 110.0)[index % 3]
        self.contingency_list = ["TEST\\Contingencies\\C{:03d}.ComOutage".format(i) for i in range(1, contingencies + 1)]
        self.contingency_elements = {}
        for index, contingency in enumerate(self.contingency_list):
            self.meta["contingencies"][contingency] = "TEST C{:03d}".format(index + 1)
            self.contingency_elements[contingency] = {self.lines[index % len(self.lines)]}
        self.times = [EPOCH + index * step_hours * 3600.0 for index in range(times)]
        self.loaded = self.lines + self.transformers
        self.weak_nodes = self.nodes
        self.weak = weak
        if weak:
            picker = random.Random(seed + 1)
            self.loaded = sorted(picker.sample(self.loaded, min(weak, len(self.loaded))))
            self.weak_nodes = sorted(picker.sample(self.nodes, min(weak, len(self.nodes))))
        rng = random.Random(seed)
        self.scenarios = {}
        for number in range(1, scenarios + 1):
            outages = []
            for _ in range(1 + number % 3):
                line = self.lines[rng.randrange(min(len(self.lines), contingencies))]
                start = rng.randrange(0, max(1, times - 8))
                outages.append((line, self.times[start], self.times[min(times - 1, start + rng.randrange(4, 24))]))
            self.scenarios["TEST S{:02d}".format(number)] = outages

    def switched_off(self, scenario):
        return {line for line, _start, _end in self.scenarios.get(scenario, ())}

    def active(self, scenario, moment):
        """The outages of a scenario active at a study time: half-open windows [start, end)."""
        return {line for line, start, end in self.scenarios.get(scenario, ()) if start <= moment < end}

    def sweep(self, scenario=None, times=None, drop_times=(), failed=()):
        return Sweep(self, scenario, times, drop_times, failed)


class Sweep:
    """One sweep (n-1 when `scenario` is None, else (n-1)' of the scenario), read study time by study time."""

    def __init__(self, grid, scenario, times, drop_times, failed):
        self.grid, self.scenario = grid, scenario
        self.times = [moment for moment in (times if times is not None else grid.times) if moment not in set(drop_times)]
        self.meta = grid.meta
        self.recording_limits = RECORDING
        self.failed = set(failed)
        self.reads = 0

    def read(self, moment):
        if self.grid.weak:
            return self._read_coherent(moment)
        grid, index = self.grid, self.grid.times.index(moment)
        self.reads += 1
        active = grid.active(self.scenario, moment) if self.scenario else set()
        present, values = set(), {}
        for number, contingency in enumerate(grid.contingency_list):
            if grid.contingency_elements[contingency] & active or contingency in self.failed:
                continue
            present.add(contingency)
            rng = random.Random((grid.seed * 1000003 + number) * 1009 + index)
            for _ in range(rng.randrange(0, 4)):
                element = grid.loaded[rng.randrange(len(grid.loaded))]
                value = 78.0 + rng.random() * 36.0
                if active and rng.random() < 0.7:
                    value += 2.0 + rng.random() * 10.0
                if value > RECORDING["loading"][0]:
                    values[(contingency, element, "loading")] = round(value, 3)
            if rng.random() < 0.3:
                node = grid.weak_nodes[rng.randrange(len(grid.weak_nodes))]
                value = 0.93 + rng.random() * 0.03 if rng.random() < 0.5 else 1.045 + rng.random() * 0.03
                if active and rng.random() < 0.5:
                    value += -0.01 if value < 1.0 else 0.01
                if not RECORDING["voltage"][0] <= value <= RECORDING["voltage"][1]:
                    values[(contingency, node, "voltage")] = round(value, 4)
            if active and rng.random() < 0.15:
                element = grid.loaded[rng.randrange(len(grid.loaded))]
                values[(contingency, element, "loading")] = round(101.0 + rng.random() * 15.0, 3)
        return present, values, set()

    def _read_coherent(self, moment):
        """`weak` profile: every contingency loads a fixed weak branch (and some a weak node) along a daily curve.

        A violation therefore lasts several consecutive study times, as in a
        real network; active planned outages raise the loading of their pairs.
        """
        grid, index = self.grid, self.grid.times.index(moment)
        self.reads += 1
        active = grid.active(self.scenario, moment) if self.scenario else set()
        hour = (moment - EPOCH) / 3600.0
        present, values = set(), {}
        for number, contingency in enumerate(grid.contingency_list):
            if grid.contingency_elements[contingency] & active or contingency in self.failed:
                continue
            present.add(contingency)
            pair = random.Random(grid.seed * 7919 + number)
            element = grid.loaded[pair.randrange(len(grid.loaded))]
            base, phase = 70.0 + pair.random() * 30.0, pair.random() * 24.0
            value = base + 10.0 * math.sin(2.0 * math.pi * (hour + phase) / 24.0)
            if active and pair.random() < 0.6:
                value += 4.0 + pair.random() * 8.0
            if value > RECORDING["loading"][0]:
                values[(contingency, element, "loading")] = round(value, 3)
            if pair.random() < 0.3:
                node = grid.weak_nodes[pair.randrange(len(grid.weak_nodes))]
                low = pair.random() < 0.5
                swing = 0.02 * math.sin(2.0 * math.pi * (hour + phase) / 24.0)
                value = (0.955 if low else 1.045) + (-swing if low else swing) + (pair.random() - 0.5) * 0.01
                if active and pair.random() < 0.5:
                    value += -0.01 if low else 0.01
                if not RECORDING["voltage"][0] <= value <= RECORDING["voltage"][1]:
                    values[(contingency, node, "voltage")] = round(value, 4)
        return present, values, set()
