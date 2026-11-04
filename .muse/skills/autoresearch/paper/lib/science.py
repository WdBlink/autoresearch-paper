"""Evidence checks and deterministic statistics for the research workflow.

The supported numerical protocol is intentionally explicit: paired cases, seeds
averaged within each case, a frozen failure penalty, and descriptive inference.
General scientific interpretation remains an independent review obligation.
"""
from __future__ import annotations

import hashlib
import html
import io
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, stdev

from . import local_response, local_response_evidence

MAX_JSON_BYTES = 16 * 1024 * 1024
INTERVALS = {"none", "sd", "se", "ci95_normal"}
RUN_STATUSES = {"completed", "failed", "stopped", "unknown"}


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _text(value, label):
    _require(isinstance(value, str) and bool(value.strip()), f"{label} must be nonempty text")
    return value


def _number(value, label):
    _require(type(value) in (int, float) and math.isfinite(value), f"{label} must be finite")
    return value


def _list(value, label, nonempty=True):
    _require(isinstance(value, list) and (bool(value) or not nonempty), f"{label} must be a list")
    return value


def _mapping(value, label):
    _require(isinstance(value, dict), f"{label} must be an object")
    return value


def _timestamp(value, label):
    _text(value, label)
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"{label} must be an ISO timestamp") from error
    _require(result.tzinfo is not None, f"{label} needs a timezone")
    return result


def publication_bounds(value):
    """Year-only source metadata is an interval, never an invented calendar day."""
    if isinstance(value, str) and re.fullmatch(r'[0-9]{4}', value):
        year = int(value)
        _require(1 <= year <= 9999, 'invalid publication year')
        return datetime(year, 1, 1, tzinfo=timezone.utc), datetime(year, 12, 31, 23, 59, 59, 999999, tzinfo=timezone.utc)
    timestamp = _timestamp(value, 'source publication time')
    return timestamp, timestamp


def _path(root, value):
    _text(value, "artifact path")
    relative = Path(value)
    _require(not relative.is_absolute() and ".." not in relative.parts,
             "artifact path must be relative to the run")
    root = Path(root).resolve()
    path = root / relative
    _require(path.resolve().is_relative_to(root), "artifact escapes run root")
    return path


def _read(root, value, maximum=None):
    path = _path(root, value)
    _require(path.is_file(), f"artifact is missing: {value}")
    if maximum is not None:
        _require(path.stat().st_size <= maximum, f"structured artifact exceeds size bound: {value}")
    return path.read_bytes()


def _sha(value):
    return hashlib.sha256(value).hexdigest()


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode("utf-8")


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        _require(key not in result, f"duplicate JSON key: {key}")
        result[key] = value
    return result


def strict_json(root, value):
    def reject_constant(constant):
        raise ValueError(f"nonfinite JSON constant: {constant}")
    return json.loads(_read(root, value, MAX_JSON_BYTES), object_pairs_hook=_unique_object,
                      parse_constant=reject_constant)


def _artifact_paths(packet):
    paths = set(_list(packet.get("artifacts"), "packet artifacts"))
    for previous in packet.get("_history", {}).values():
        if isinstance(previous, dict):
            paths.update(previous.get("artifacts", []))
    return paths


def _bound(packet, path):
    _text(path, "evidence path")
    _require(path in _artifact_paths(packet), f"unbound science evidence: {path}")
    return path


def _design(root, path):
    design = _mapping(strict_json(root, path), "experiment design")
    if design.get("protocol") == local_response.PROTOCOL:
        local_response.validate_design(design, root, require_resolved=True)
        return design
    _require("protocol" not in design or design["protocol"] == "paired_case_mean",
             "unsupported scientific protocol")
    for field in ("experiment_id", "claim_id", "hypothesis", "independent_variable",
                  "dependent_variable"):
        _text(design.get(field), field)
    for control in _list(design.get("control_variables"), "control_variables"):
        _text(control, "control variable")
    metric = _mapping(design.get("metric"), "metric")
    _text(metric.get("name"), "metric name")
    _text(metric.get("unit"), "metric unit")
    _require(metric.get("direction") in {"lower", "higher"}, "unknown metric direction")
    _require(design.get("statistical_unit") == "case", "only independent case units are supported")
    cases = _list(design.get("cases"), "cases")
    for case in cases:
        _text(case, "case ID")
    _require(len(cases) == len(set(cases)), "duplicate cases")
    seeds = _list(design.get("seeds"), "seeds")
    _require(all(type(seed) is int and 0 <= seed < 2**32 for seed in seeds), "invalid seeds")
    _require(len(seeds) == len(set(seeds)), "duplicate seeds")
    conditions = _list(design.get("conditions"), "conditions")
    for condition in conditions:
        _require(isinstance(condition, str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,95}", condition),
                 "condition must be a stable named identifier")
    _require(len(conditions) >= 2 and len(conditions) == len(set(conditions)), "need distinct named conditions")
    _require(len(cases) * len(seeds) * len(conditions) <= 100000, "planned experiment exceeds record bound")
    _require(design.get("failure_policy") == "penalty", "only a frozen penalty failure policy is supported")
    _number(design.get("failure_value"), "failure penalty")
    stats = _mapping(design.get("statistics"), "statistics plan")
    _require(stats.get("estimator") == "mean", "unsupported estimator")
    _require(stats.get("interval") in INTERVALS, "unsupported interval")
    _require(stats.get("paired") is True, "paired case comparison is required")
    if conditions != ["baseline", "candidate"] or "contrasts" in stats:
        contrasts = _list(stats.get("contrasts"), "preregistered contrasts")
        ids, pairs = set(), set()
        for contrast in contrasts:
            _mapping(contrast, "contrast")
            name = contrast.get("id")
            _require(isinstance(name, str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,95}", name),
                     "contrast needs a stable named identifier")
            left, right = contrast.get("minuend"), contrast.get("subtrahend")
            _require(isinstance(left, str) and isinstance(right, str) and left in conditions and right in conditions and left != right,
                     "contrast must name two distinct planned conditions")
            _require(name not in ids and (left, right) not in pairs, "duplicate contrast")
            ids.add(name); pairs.add((left, right))
    _require(stats["interval"] == "none" or len(cases) >= 2,
             "uncertainty estimates need at least two independent cases")
    for role in _list(design.get("data_roles"), "data_roles"):
        _mapping(role, "data role")
        _text(role.get("id"), "data role ID")
        _require(role.get("role") in {"development", "train", "validation", "holdout", "test"},
                 "unknown data role")
        _require(type(role.get("used_for_selection")) is bool, "declare data exposure")
        _require(role["role"] not in {"holdout", "test"} or not role["used_for_selection"],
                 "holdout/test data cannot be used for method selection")
    _timestamp(design.get("planned_at"), "planned_at")
    if "evaluator" in design:
        evaluator = _mapping(design["evaluator"], "evaluator")
        _require(_sha(_read(root, evaluator.get("path"))) == evaluator.get("sha256"),
                 "frozen evaluator bytes changed")
    return design


def _experiment(root, design_path, results_path, frozen_hash=None):
    design = _design(root, design_path)
    if design.get("protocol") == local_response.PROTOCOL:
        design, results, stats, _ = local_response_evidence.load(root, design_path, results_path, frozen_hash)
        return design, results, stats["input_hashes"]["raw"]
    design_hash = _sha(_read(root, design_path))
    if frozen_hash is not None:
        _require(design_hash == frozen_hash, "experiment design differs from the frozen plan")
    results = _mapping(strict_json(root, results_path), "experiment results")
    if "design_id" in results:
        _require(results["design_id"] == design["experiment_id"], "result design identity mismatch")
    _require(results.get('execution_status', 'completed') == 'completed',
             'operation failures cannot become scientific measurements, including errors after the last score')
    _require(results.get("design") == design_path, "result design path mismatch")
    _require(results.get("design_sha256") == design_hash, "result design hash mismatch")
    _require(_timestamp(results.get("started_at"), "started_at") >=
             _timestamp(design["planned_at"], "planned_at"), "results predate the recorded design")
    _require(results.get("outcome") in {"positive", "negative", "inconclusive"}, "unknown research outcome")
    expected = {(case, seed, condition) for case in design["cases"] for seed in design["seeds"]
                for condition in design["conditions"]}
    _require(type(results.get("reported_denominator")) is int and
             results["reported_denominator"] == len(expected), "failure-inclusive denominator mismatch")
    _require(not results.get("excluded_runs"), "success-only filtering is not supported")
    rows = _list(results.get("runs"), "runs")
    _require(len(rows) == len(expected), "all planned runs, including failures and stops, must remain recorded")
    seen_keys, seen_ids, seen_raw = set(), set(), set()
    raw_hashes = {}
    for row in rows:
        _mapping(row, "run")
        _require(type(row.get("seed")) is int, "run seed must be an integer")
        _text(row.get("case_id"), "run case ID")
        _text(row.get("condition"), "run condition")
        identity = (row.get("case_id"), row.get("seed"), row.get("condition"))
        _require(identity in expected and identity not in seen_keys, "duplicate or unplanned run identity")
        seen_keys.add(identity)
        _text(row.get("id"), "run ID")
        _require(row["id"] not in seen_ids, "duplicate run ID")
        seen_ids.add(row["id"])
        _require(row.get("status") in RUN_STATUSES, "unknown run status")
        _require(row["status"] != "unknown", "unknown external outcome requires reconciliation")
        if row["status"] == "completed":
            _number(row.get("value"), "measurement")
        else:
            _require(row.get("value") is None, "failed/stopped runs cannot report a successful value")
            _text(row.get("reason"), "failure/stop reason")
            _require(row.get("failure_kind") == "measurement",
                     "operation failures cannot become scientific negative measurements; declare measurement failure_kind")
        raw_path = _text(row.get("raw"), "raw measurement path")
        _require(raw_path not in seen_raw, "each run needs its own raw record")
        seen_raw.add(raw_path)
        raw = _mapping(strict_json(root, raw_path), "raw record")
        if "design_id" in results:
            _require(raw.get("design_id") == results["design_id"] and raw.get("design_sha256") == design_hash,
                     "raw design identity/hash mismatch")
        _require(type(raw.get("seed")) is int, "raw seed must be an integer")
        if row["status"] == "completed":
            _number(raw.get("value"), "raw measurement")
        else:
            _require(raw.get("value") is None, "raw failed value must be null")
        for record in (row, raw):
            _require(record.get("attempted", True) is True, "unstarted slots cannot become scientific measurements")
            _require(record.get("failure_kind") != "operation", "operation failures cannot become scientific measurements")
        for key in ("case_id", "seed", "condition", "status", "value"):
            _require(key in raw and raw[key] == row.get(key), f"raw measurement differs in {key}: {row['id']}")
        if row["status"] != "completed":
            for key in ("reason", "failure_kind"):
                _require(raw.get(key) == row[key], f"raw failure classification differs in {key}: {row['id']}")
        raw_hashes[raw_path] = _sha(_read(root, raw_path))
    _require(seen_keys == expected, "paired case and seed coverage differs from the plan")
    complete = [row["value"] for row in rows if row["status"] == "completed"]
    _require(bool(complete), "no measured results; operation failures are not a scientific negative result")
    penalty = design["failure_value"]
    if any(row["status"] != "completed" for row in rows):
        _require(penalty >= max(complete) if design["metric"]["direction"] == "lower" else penalty <= min(complete),
                 "failure penalty makes failed runs better than measurements")
    return design, results, raw_hashes


def _summary(values, interval):
    average = mean(values)
    deviation = stdev(values) if len(values) >= 2 else None
    error = deviation / math.sqrt(len(values)) if deviation is not None else None
    spread = {"none": None, "sd": deviation, "se": error,
              "ci95_normal": 1.96 * error if error is not None else None}[interval]
    return {"mean": average, "sd": deviation, "se": error,
            "interval": [average - spread, average + spread] if spread is not None else None}


def _statistics(root, design_path, results_path, frozen_hash=None):
    if strict_json(root, design_path).get("protocol") == local_response.PROTOCOL:
        return local_response_evidence.load(root, design_path, results_path, frozen_hash)[2]
    design, results, raw_hashes = _experiment(root, design_path, results_path, frozen_hash)
    values = {(row["case_id"], row["seed"], row["condition"]):
              row["value"] if row["status"] == "completed" else design["failure_value"]
              for row in results["runs"]}
    case_values = {condition: [mean(values[(case, seed, condition)] for seed in design["seeds"])
                              for case in design["cases"]] for condition in design["conditions"]}
    interval = design["statistics"]["interval"]
    condition_stats = {condition: _summary(values, interval) for condition, values in case_values.items()}
    legacy = "contrasts" not in design["statistics"] and design["conditions"] == ["baseline", "candidate"]
    contrast_plan = design["statistics"].get("contrasts", [
        {"id": "delta", "minuend": "candidate", "subtrahend": "baseline"}])
    sign = -1 if design["metric"]["direction"] == "lower" else 1
    contrasts = {}
    for contrast in contrast_plan:
        differences = [left - right for left, right in zip(
            case_values[contrast["minuend"]], case_values[contrast["subtrahend"]])]
        contrasts[contrast["id"]] = {**contrast, **_summary(differences, interval),
            "case_differences": differences,
            "adverse_case_ids": [case for case, difference in zip(design["cases"], differences)
                                 if sign * difference < 0]}
    _require(legacy or results["outcome"] == "inconclusive",
             "explicit contrasts support descriptive summaries only; overall outcome must remain inconclusive")
    delta = contrasts[contrast_plan[0]["id"]]
    improving = sign * delta["mean"] > 0
    _require(results["outcome"] != "positive" or improving,
             "positive outcome contradicts the observed paired mean")
    _require(results["outcome"] != "negative" or not improving,
             "negative outcome contradicts the observed paired mean; use inconclusive for uncertain evidence")
    rows = results["runs"]
    result = {
        "schema_version": 1 if legacy else 2,
        "experiment_id": design["experiment_id"], "claim_id": design["claim_id"],
        "input_hashes": {"design": _sha(_read(root, design_path)),
                         "results": _sha(_read(root, results_path)), "raw": raw_hashes},
        "metric": design["metric"], "statistical_unit": "case", "n_cases": len(design["cases"]),
        "seeds_per_case": len(design["seeds"]), "planned_runs": results["reported_denominator"],
        "observed_runs": sum(row["status"] == "completed" for row in rows),
        "failed_runs": sum(row["status"] == "failed" for row in rows),
        "stopped_runs": sum(row["status"] == "stopped" for row in rows),
        "failure_policy": "penalty", "failure_value": design["failure_value"],
        "included_run_ids": [row["id"] for row in rows], "case_ids": design["cases"],
        "case_values": case_values,
        "interval_type": interval, "conditions": condition_stats,
        "adverse_case_ids": [case for case in design["cases"]
                             if any(case in contrast["adverse_case_ids"] for contrast in contrasts.values())],
        "outcome": results["outcome"],
        "limitations": ["descriptive_case_summary"] +
                       (["normal_approximation_not_confirmatory"] if interval == "ci95_normal" else []),
    }
    if legacy:
        result.update(delta={key: delta[key] for key in ("mean", "sd", "se", "interval")},
                      case_differences=delta["case_differences"])
    else:
        result.update(contrasts=contrasts, condition_order=design["conditions"],
                      contrast_order=[contrast["id"] for contrast in contrast_plan])
        result["limitations"].append("multiple_contrasts_descriptive_no_multiplicity_adjustment")
    return result


def _caption(stats):
    if stats.get("protocol") == local_response.PROTOCOL:
        return local_response_evidence.caption(stats)
    label = {"sd": "SD", "se": "SE", "ci95_normal": "exploratory normal 95% CI", "none": "no interval"}
    caption = (f"{stats['metric']['name']} ({stats['metric']['unit']}; {stats['metric']['direction']} is better). "
            f"Points show case means; summary intervals show {label[stats['interval_type']]}. "
            f"n={stats['n_cases']} paired cases, {stats['seeds_per_case']} seeds averaged within each case. "
            f"Denominator={stats['planned_runs']} planned runs; {stats['failed_runs']} failed and "
            f"{stats['stopped_runs']} stopped runs. ")
    if stats['failed_runs'] or stats['stopped_runs']:
        caption += f"Measurement failures/stops retain the frozen penalty {stats['failure_value']} in this denominator. "
    if stats['interval_type'] == 'sd':
        caption += "Bounds are mean plus/minus sample SD (ddof=1), not confidence limits or feasible-value ranges. "
    if "contrasts" in stats:
        caption += "Preregistered contrasts: " + "; ".join(
            f"{name} = {stats['contrasts'][name]['minuend']} minus {stats['contrasts'][name]['subtrahend']}"
            for name in stats["contrast_order"]) + ". No multiplicity-adjusted or confirmatory inference. "
    else:
        caption += "Delta is candidate minus baseline. "
    return caption + "These are descriptive case results."


def _tex(value):
    replacements = {"\\": r"\textbackslash{}", "&": r"\&", "%": r"\%", "$": r"\$", "#": r"\#",
                    "_": r"\_", "{": r"\{", "}": r"\}", "~": r"\textasciitilde{}", "^": r"\textasciicircum{}"}
    return "".join(replacements.get(character, character) for character in str(value))


def _table(stats):
    if stats.get("protocol") == local_response.PROTOCOL:
        return local_response_evidence.table(stats)
    label = {"none": "No interval", "sd": r"Mean $\pm$ SD bounds", "se": r"Mean $\pm$ SE bounds", "ci95_normal": r"Exploratory normal 95\% CI"}[stats["interval_type"]]
    lines = [r"\begin{minipage}{\linewidth}\centering", r"\begin{tabular}{lrr}", "Condition & Mean (" + _tex(stats["metric"]["unit"]) + ") & " + label + r" \\", r"\hline"]
    entries = [(name, stats["conditions"][name]) for name in stats.get("condition_order", ["baseline", "candidate"])]
    entries += ([("contrast " + name, stats["contrasts"][name]) for name in stats["contrast_order"]]
                if "contrasts" in stats else [("delta", stats["delta"])])
    for name, values in entries:
        interval = values["interval"]
        display = "none" if interval is None else f"[{interval[0]:.6f}, {interval[1]:.6f}]"
        lines.append(f"{_tex(name)} & {values['mean']:.6f} & {display} " + r"\\")
    lines.extend([r"\end{tabular}", r"\par\smallskip\footnotesize\raggedright " + _tex(_caption(stats)), r"\end{minipage}"])
    return "\n".join(lines) + "\n"


def _svg(stats):
    digest = _sha(_canonical(stats))
    values = [v for group in stats["case_values"].values() for v in group]
    for summary in stats["conditions"].values():
        if summary["interval"]:
            values.extend(summary["interval"])
    low, high = min(values + [0]), max(values + [0])
    pad = max((high - low) * 0.12, 0.5)
    low, high = low - pad, high + pad
    def y(value):
        return 315 - (value - low) / (high - low) * 255
    width = max(640, 160 * len(stats["conditions"]) + 120)
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="420" viewBox="0 0 {width} 420">',
             f'<desc>statistics sha256:{digest}; {html.escape(_caption(stats))}</desc>',
             f'<rect width="{width}" height="420" fill="white"/>',
             '<g font-family="sans-serif" font-size="14" fill="#202020">',
             f'<text x="24" y="26">{html.escape(stats["metric"]["name"])} ({html.escape(stats["metric"]["unit"])})</text>',
             f'<path d="M80 50 V315 H{width-40}" fill="none" stroke="#202020"/>']
    for index in range(6):
        value = low + (high - low) * index / 5
        parts.append(f'<text x="12" y="{y(value)+5:.3f}">{value:.3f}</text>')
    for index, condition in enumerate(stats.get("condition_order", ["baseline", "candidate"])):
        x = 80 + (index + 0.5) * (width - 120) / len(stats["conditions"])
        color = ("#0072B2", "#D55E00")[index % 2]
        for offset, value in enumerate(stats["case_values"][condition]):
            shift = (offset - (stats["n_cases"] - 1) / 2) * min(12, 80 / stats["n_cases"])
            if index == 0:
                parts.append(f'<circle cx="{x+shift:.3f}" cy="{y(value):.3f}" r="4" fill="none" stroke="{color}"/>')
            else:
                parts.append(f'<rect x="{x+shift-4:.3f}" y="{y(value)-4:.3f}" width="8" height="8" fill="none" stroke="{color}"/>')
        summary = stats["conditions"][condition]
        if summary["interval"]:
            a, b = map(y, summary["interval"])
            parts.append(f'<path d="M{x} {a:.3f} V{b:.3f} M{x-8} {a:.3f} H{x+8} M{x-8} {b:.3f} H{x+8}" stroke="{color}" stroke-width="2" fill="none"/>')
        parts.append(f'<path d="M{x-15} {y(summary["mean"]):.3f} H{x+15}" stroke="{color}" stroke-width="3"/>')
        parts.append(f'<text x="{x-40}" y="343">{html.escape(condition)}</text>')
    parts.extend([f'<text x="80" y="374">n={stats["n_cases"]} paired cases; {stats["interval_type"]}; failures={stats["failed_runs"]}; stops={stats["stopped_runs"]}</text>',
                  '<text x="80" y="399">Case points and mean; descriptive summary.</text>', '</g></svg>'])
    return ("\n".join(parts) + "\n").encode()


def _pdf(stats):
    try:
        import matplotlib
        matplotlib.use("Agg")
        from matplotlib.figure import Figure
    except ImportError as error:
        raise ValueError("PDF statistics rendering needs installed Matplotlib; SVG works without it") from error
    with matplotlib.rc_context({"text.usetex": False, "font.family": "DejaVu Sans", "pdf.fonttype": 42}):
        figure = Figure(figsize=(max(6.4, 1.6 * len(stats["conditions"])), 4.2), layout="constrained")
        axis = figure.subplots()
        for index, condition in enumerate(stats.get("condition_order", ["baseline", "candidate"])):
            color, marker = (("#0072B2", "o"), ("#D55E00", "s"))[index % 2]
            points = stats["case_values"][condition]
            positions = [index + (i - (len(points) - 1) / 2) * min(0.04, 0.35 / len(points))
                         for i in range(len(points))]
            axis.scatter(positions, points, color=color, marker=marker, facecolors="none", zorder=3)
            summary = stats["conditions"][condition]
            average = summary["mean"]
            if summary["interval"] is not None:
                lo, hi = summary["interval"]
                axis.errorbar([index], [average], yerr=[[average-lo], [hi-average]],
                              fmt="_", markersize=20, color=color, capsize=6, linewidth=1.8)
            else:
                axis.plot([index], [average], "_", markersize=20, color=color)
        axis.set_xticks(list(range(len(stats["conditions"]))), stats.get("condition_order", ["baseline", "candidate"]))
        axis.set_xlim(-0.5, len(stats["conditions"]) - 0.5)
        axis.set_ylabel(f"{stats['metric']['name']} ({stats['metric']['unit']})")
        axis.set_title(f"Paired case means; {stats['metric']['direction']} is better")
        axis.grid(axis="y", alpha=0.2)
        failure_note = ' (measurement penalty retained)' if stats['failed_runs'] or stats['stopped_runs'] else ''
        figure.supxlabel(f"n={stats['n_cases']} cases; {stats['interval_type']}; "
                         f"failed={stats['failed_runs']}, stopped={stats['stopped_runs']}" + failure_note, fontsize=9)
        output = io.BytesIO()
        figure.savefig(output, format="pdf", metadata={"Creator": "autoresearch evidence renderer v2",
                       "CreationDate": None, "ModDate": None,
                       "Subject": "statistics sha256:" + _sha(_canonical(stats))})
        return output.getvalue()


def _figure(stats, suffix):
    if stats.get("protocol") == local_response.PROTOCOL:
        return local_response_evidence.figure(stats, suffix)
    _require(suffix in {".svg", ".pdf"}, "statistics figure must be .svg or .pdf")
    return _svg(stats) if suffix == ".svg" else _pdf(stats)


def render_statistics(root, input_path, table_path, figure_path):
    """Render statistics from recorded measurements; never run an experiment."""
    results = _mapping(strict_json(root, input_path), "experiment results")
    stats = _statistics(root, results.get("design"), input_path)
    table = _table(stats).encode()
    figure = _figure(stats, Path(figure_path).suffix.lower())
    statistics_path = table_path + ".stats.json"
    trace_path = figure_path + ".trace.json"
    targets = [input_path, results["design"], table_path, figure_path, statistics_path, trace_path]
    _require(len(set(targets)) == len(targets), "render output paths overlap inputs or each other")
    raw_inputs = set(stats["input_hashes"]["raw"])
    _require(not ({table_path, figure_path, statistics_path, trace_path} & raw_inputs), "render would overwrite raw evidence")
    trace = {"schema_version": 1, "statistics_sha256": _sha(_canonical(stats)),
             "table": table_path, "table_sha256": _sha(table),
             "figure": figure_path, "figure_sha256": _sha(figure)}
    outputs = ((table_path, table), (figure_path, figure),
               (statistics_path, _canonical(stats) + b"\n"),
               (trace_path, _canonical(trace) + b"\n"))
    for path, data in outputs:
        destination = _path(root, path)
        _require(not destination.exists() or destination.read_bytes() == data,
                 f"render output exists with different content: {path}")
    for path, data in outputs:
        destination = _path(root, path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if not destination.exists():
            with destination.open("xb") as output:
                output.write(data)
    return {"statistics": stats, "statistics_path": statistics_path,
            "table": table_path, "figure": figure_path, "trace": trace_path,
            "caption": _caption(stats), "artifacts": [table_path, figure_path, statistics_path, trace_path]}


IDENTITY_FIELDS = ("title", "authors", "year", "venue", "identifier")
COMPLETION_ROLES = {"source", "pdf", "bibliography", "citation_plan", "citation_verification", "review", "revision", "snapshot"}


def _normalized(value):
    return re.sub(r"[\W_]+", "", str(value).casefold(), flags=re.UNICODE)


def _author_identity(author):
    text = author.strip()
    if text.startswith('{') and text.endswith('}'):
        return _normalized(text)
    parts = [part.strip() for part in text.split(',')]
    if len(parts) == 2:
        text = parts[1] + ' ' + parts[0]
    elif len(parts) == 3:
        text = parts[2] + ' ' + parts[0] + ' ' + parts[1]
    return _normalized(text)


def _bib_authors(text):
    # BibTeX's explicit commas/braces define structure; never guess a surname.
    parts, start, depth, index = [], 0, 0, 0
    while index < len(text):
        char = text[index]
        if char == '\\':
            index += 2
            continue
        if char == '{': depth += 1
        if char == '}': depth -= 1
        if depth == 0 and text[index:index+5].casefold() == ' and ':
            parts.append(text[start:index]); start = index + 5; index += 5
        else:
            index += 1
    parts.append(text[start:])
    return [_author_identity(author) for author in parts]


def _bib_entries(text):
    entries = {}
    position = 0
    while True:
        start = re.search(r"@([A-Za-z]+)\s*([({])", text[position:])
        if start is None:
            break
        kind = start.group(1).lower()
        open_char = start.group(2)
        closing = "}" if open_char == "{" else ")"
        begin = position + start.end()
        cursor, depth, quoted = begin, 1, False
        while cursor < len(text) and depth:
            character = text[cursor]
            if character == "\\":
                cursor += 2
                continue
            if character == '"':
                quoted = not quoted
            if not quoted:
                if character == open_char:
                    depth += 1
                elif character == closing:
                    depth -= 1
            cursor += 1
        _require(depth == 0, "unbalanced BibTeX entry")
        body = text[begin:cursor-1]
        position = cursor
        if kind in {"comment", "preamble"}:
            continue
        _require(kind != "string", "materialize BibTeX string macros before verification")
        key_match = re.match(r"\s*([^,\s]+)\s*,", body)
        _require(key_match is not None, "BibTeX entry lacks citation key")
        key = key_match.group(1)
        _require(key not in entries, "duplicate BibTeX key: " + key)
        fields, index = {}, key_match.end()
        while index < len(body):
            prefix = re.match(r"[\s,]*([A-Za-z][A-Za-z0-9_-]*)\s*=\s*", body[index:])
            if prefix is None:
                _require(not body[index:].strip(" \n\t\r,"), "unsupported BibTeX field syntax")
                break
            name = prefix.group(1).lower()
            _require(name not in fields, "duplicate BibTeX field: " + name)
            index += prefix.end()
            _require(index < len(body), "empty BibTeX field")
            delimiter = body[index]
            if delimiter in {'{', '"'}:
                end = index + 1
                depth = 1
                while end < len(body) and depth:
                    if body[end] == "\\":
                        end += 2
                        continue
                    if delimiter == "{" and body[end] == "{":
                        depth += 1
                    if body[end] == ("}" if delimiter == "{" else '"'):
                        depth -= 1
                    end += 1
                _require(depth == 0, "unbalanced BibTeX field")
                value = body[index+1:end-1]
                index = end
            else:
                end = body.find(",", index)
                end = len(body) if end < 0 else end
                value = body[index:end].strip()
                _require(bool(re.fullmatch(r"[0-9]+", value)), "materialize unresolved BibTeX macros")
                index = end
            _require(index >= len(body) or body[index:].lstrip().startswith(","),
                     "materialize concatenated BibTeX field values")
            fields[name] = value
        entries[key] = {"kind": kind, **fields}
    _require(bool(entries), "bibliography has no BibTeX entries")
    return entries


def _spans(packet, root, spans):
    paths = set()
    for span in _list(spans, "citation evidence spans"):
        _mapping(span, "citation evidence span")
        path = _bound(packet, span.get("path"))
        quote = _text(span.get("quote"), "citation evidence quote")
        _require(quote in _read(root, path).decode("utf-8"), "citation claim span differs from source bytes")
        paths.add(path)
    return paths


def _identity(record):
    _mapping(record, "citation identity")
    for field in ("title", "venue", "identifier"):
        _text(record.get(field), "citation " + field)
    for author in _list(record.get("authors"), "citation authors"):
        _text(author, "citation author")
    _require(type(record.get("year")) is int and 1 <= record["year"] <= 9999, "invalid citation year")
    return {key: record[key] for key in IDENTITY_FIELDS}


def _citation_state(packet, root, final=False):
    literature = packet if packet.get("catalog") else packet.get("_history", {}).get("literature", {})
    _mapping(literature, "accepted literature packet")
    for key in ("catalog", "bibliography", "citation_plan", "citation_verification"):
        _bound(packet, literature.get(key))
    catalog = _mapping(strict_json(root, literature["catalog"]), "citation source catalog")
    candidates = {candidate["id"]: candidate for candidate in _list(catalog.get("candidates"), "citation candidates")}
    bib = _bib_entries(_read(root, literature["bibliography"]).decode("utf-8"))
    plan = []
    for line in _read(root, literature["citation_plan"]).decode("utf-8").splitlines():
        if line.strip():
            plan.append(json.loads(line, object_pairs_hook=_unique_object))
    _require(bool(plan), "citation plan has no records")
    verification = _mapping(strict_json(root, literature["citation_verification"]), "citation verification")
    checks = {}
    for check in _list(verification.get("records"), "citation verification records", nonempty=False):
        _mapping(check, "citation verification record")
        key = _text(check.get("key"), "verified citation key")
        _require(key not in checks, "duplicate citation verification record")
        _require(check.get("status") in {"verified", "unresolved"}, "unknown citation verification status")
        _timestamp(check.get("checked_at"), "citation verification time")
        checks[key] = check
    by_key, claims, used_candidates = {}, {}, set()
    for record in plan:
        _mapping(record, "citation plan record")
        key = _text(record.get("key"), "citation key")
        _require(key not in by_key, "duplicate citation plan key")
        by_key[key] = record
        identity = _identity(record)
        candidate = candidates.get(record.get("candidate_id"))
        _require(candidate is not None, "citation candidate is absent from the source catalog")
        _require(record["candidate_id"] not in used_candidates, "one source candidate cannot inflate multiple citation keys")
        used_candidates.add(record["candidate_id"])
        _require(_normalized(identity["title"]) == _normalized(candidate["title"]), "citation title differs from candidate identity")
        _require(identity["year"] == publication_bounds(candidate.get("published_at"))[0].year,
                 "citation year differs from candidate identity")
        _require(record.get("url") == candidate.get("url"), "citation URL differs from catalog")
        _text(record.get("taxonomy_cell"), "citation taxonomy cell")
        _require(record.get("depth") in {"A", "B", "C", "D"}, "unknown citation depth")
        _require(record.get("status") in {"candidate", "read", "verified"}, "unknown citation reading status")
        if record["status"] in {"read", "verified"}:
            _require(candidate.get("read_status") == "read", "candidate registration is not a source reading")
        if record["depth"] != "D":
            _require(key in bib, "citation plan key has no BibTeX entry: " + key)
            _require(_normalized(bib[key].get("title", "")) == _normalized(identity["title"]), "BibTeX title identity mismatch")
            _require(str(identity["year"]) == bib[key].get("year"), "BibTeX year identity mismatch")
            _require(_bib_authors(bib[key].get("author", "")) == [_author_identity(author) for author in identity['authors']],
                     "BibTeX author identity mismatch")
            venue = bib[key].get("journal", bib[key].get("booktitle", bib[key].get("howpublished")))
            if venue is not None:
                _require(_normalized(venue) == _normalized(identity["venue"]), "BibTeX venue identity mismatch")
            identifier = identity["identifier"]
            if identifier.lower().startswith("doi:"):
                _require(_normalized(bib[key].get("doi", "")) == _normalized(identifier[4:]), "BibTeX DOI identity mismatch")
            if identifier.lower().startswith("arxiv:"):
                _require(_normalized(bib[key].get("eprint", "")) == _normalized(identifier[6:]), "BibTeX arXiv identity mismatch")
        if "lqs" in record:
            lqs = _mapping(record["lqs"], "LQS record")
            dimensions = _mapping(lqs.get("dimensions"), "LQS dimension inputs")
            weights = {"recency": .30, "impact": .25, "venue": .20, "institution": .10, "acceptance": .15}
            _require(set(dimensions) == set(weights), "LQS dimensions differ from the declared source weights")
            _read(root, _bound(packet, lqs.get("convention")))
            if any(value is None for value in dimensions.values()):
                _require(lqs.get("total") is None, "unknown LQS inputs cannot produce a fabricated total")
            else:
                for value in dimensions.values():
                    _require(0 <= _number(value, "LQS dimension score") <= 10, "LQS score outside [0,10]")
                expected_total = sum(dimensions[name] * weight for name, weight in weights.items())
                _require(math.isclose(_number(lqs.get("total"), "LQS total"), expected_total,
                                     rel_tol=1e-10, abs_tol=1e-10), "LQS arithmetic differs from source weights")
        acceptance = record.get("acceptance")
        if record["depth"] != "D" and bib.get(key, {}).get("kind") == "inproceedings":
            _require(isinstance(acceptance, dict) and acceptance.get("status") == "accepted",
                     "conference BibTeX upgrade requires verified acceptance evidence")
        if acceptance is not None:
            _mapping(acceptance, "citation acceptance")
            _require(acceptance.get("status") in {"accepted", "preprint", "under_review", "unknown"},
                     "unknown citation acceptance identity")
            if acceptance["status"] == "accepted":
                _require(acceptance.get("authority") in {"official_proceedings", "official_decision"},
                         "accepted citation needs official proceedings/decision authority")
                official = _read(root, _bound(packet, acceptance.get("evidence"))).decode("utf-8")
                _require(_normalized(identity["venue"]) in _normalized(official),
                         "acceptance evidence does not identify the cited venue")
                _text(acceptance.get("version"), "accepted publication version")
        source_claims = _list(record.get("claims"), "citation claims", nonempty=record["depth"] != "D")
        local_claim_ids = set()
        for claim in source_claims:
            _mapping(claim, "citation claim")
            claim_id = _text(claim.get("id"), "citation claim ID")
            _require(claim_id not in local_claim_ids, "duplicate claim in one citation")
            local_claim_ids.add(claim_id)
            claim_text = _text(claim.get("text"), "citation claim text")
            _spans(packet, root, claim.get("evidence_spans"))
            if claim_id in claims:
                _require(claims[claim_id]["text"] == claim_text, "same claim ID has contradictory text")
            else:
                claims[claim_id] = {"text": claim_text, "keys": set(), "supported_keys": set()}
            claims[claim_id]["keys"].add(key)
        check = checks.get(key)
        if record["status"] == "verified":
            _require(record["depth"] != "D" and candidate.get("decision") == "include",
                     "a dropped/excluded citation cannot certify a manuscript claim")
            _require(check is not None and check["status"] == "verified", "citation claims verified without a verification record")
            _require(_identity(check.get("identity")) == identity, "verified citation identity differs from plan")
            read_path = _bound(packet, candidate.get("read_path"))
            _require(check.get("source_sha256") == _sha(_read(root, read_path)), "citation verification is stale after source change")
            evidence_text = "\n".join(_read(root, _bound(packet, path)).decode("utf-8")
                                       for path in _list(check.get("evidence"), "citation identity evidence"))
            evidence_norm = _normalized(evidence_text)
            for value in [identity["title"], *identity["authors"], identity["year"], identity["venue"], identity["identifier"]]:
                _require(_normalized(value) in evidence_norm, "citation identity evidence omits a checked identity field")
            claim_checks = {}
            for claim_check in _list(check.get("claim_checks"), "citation claim checks"):
                _mapping(claim_check, "citation claim check")
                claim_id = _text(claim_check.get("claim_id"), "checked claim ID")
                _require(claim_id in local_claim_ids and claim_id not in claim_checks, "wrong/duplicate citation claim binding")
                _require(claim_check.get("status") in {"supported", "unsupported", "unresolved"}, "unknown citation claim verdict")
                _spans(packet, root, claim_check.get("evidence_spans"))
                claim_checks[claim_id] = claim_check
                if claim_check["status"] == "supported":
                    claims[claim_id]["supported_keys"].add(key)
            _require(set(claim_checks) == local_claim_ids, "citation verification omits a planned claim")
            if final:
                _require(all(check["status"] == "supported" for check in claim_checks.values()),
                         "final manuscript has unsupported/unresolved citation claims")
        elif final and record["depth"] != "D":
            raise ValueError("final manuscript has unresolved citation identity: " + key)
    _require(set(checks) <= set(by_key), "verification record has an unknown citation key")
    active_keys = [record["key"] for record in plan if record["depth"] != "D"]
    batches = _list(verification.get("batches"), "citation verification batches", nonempty=False)
    expected_blocks = [active_keys[index:index+20] for index in range(0, len(active_keys), 20)]
    # Batches record the twenty-citation cadence; final=True already checks every
    # active record and claim above, including a smaller trailing block.
    full_blocks = len(active_keys) // 20
    _require(full_blocks <= len(batches) <= len(expected_blocks), "every twenty accumulated citations needs a verification batch")
    for index, batch in enumerate(batches):
        _mapping(batch, "citation verification batch")
        _require(batch.get("keys") == expected_blocks[index], "citation verification batch skips or reorders citation keys")
        _timestamp(batch.get("checked_at"), "citation batch time")
        _require(bool(_read(root, _bound(packet, batch.get("evidence"))).strip()), "citation batch evidence is empty")
    return {"literature": literature, "plan": by_key, "claims": claims, "bib": bib}


def _source_bundle(packet, root):
    main = _bound(packet, packet.get("manuscript"))
    pending, sources = [main], {}
    while pending:
        name = pending.pop()
        if name in sources:
            continue
        _require(len(sources) < 1000, "manuscript source tree exceeds the file bound")
        content = _read(root, _bound(packet, name)).decode("utf-8")
        sources[name] = content
        uncommented = re.sub(r"(?m)(?<!\\)%.*$", "", content)
        directives = re.findall(r"\\(?:input|include)(?![A-Za-z])", uncommented)
        references = re.findall(r"\\(?:input|include)(?![A-Za-z])\s*(?:\{([^}]+)\}|([^\s%\\{}]+))", uncommented)
        _require(len(references) == len(directives), "dynamic TeX inputs must be materialized before source verification")
        for braced, unbraced in references:
            reference = braced or unbraced
            _require("\\" not in reference and not Path(reference).is_absolute(), "dynamic/absolute TeX input is unsupported")
            relative = Path(reference)
            if not relative.suffix:
                relative = relative.with_suffix(".tex")
            resolved = (_path(root, name).parent / relative).resolve()
            _require(resolved.is_relative_to(Path(root).resolve()), "manuscript input escapes run root")
            pending.append(resolved.relative_to(Path(root).resolve()).as_posix())
    return sources


def _cited_keys(text):
    content = re.sub(r"(?m)(?<!\\)%.*$", "", text)
    keys = set()
    for group in re.findall(r"\\(?:cite[A-Za-z]*|nocite)\*?(?:\[[^\]]*\])*\s*\{([^}]+)\}", content):
        for key in group.split(","):
            _require(key.strip() != "*", "expand wildcard citation keys before final verification")
            keys.add(key.strip())
    return keys


def _derived_tables(packet):
    figures = packet.get("_history", {}).get("figures", {})
    if "evidence_sets" in figures:
        return {row["table"] for row in figures["evidence_sets"]}
    return {figures["table"]} if figures.get("table") else set()


def _sections(packet, root, sources, assertions, citation_state):
    sections = _list(packet.get("section_packets"), "section_packets")
    claim_ids = {record["claim_id"] for record in assertions}
    seen_paths, seen_ids = set(), set()
    for section in sections:
        _mapping(section, "section packet")
        identity = _text(section.get("id"), "section ID")
        _require(identity not in seen_ids, "duplicate section ownership ID")
        seen_ids.add(identity)
        path = _bound(packet, section.get("path"))
        _require(path in sources and path not in seen_paths, "section path is absent or owned twice")
        seen_paths.add(path)
        _text(section.get("purpose"), "section reader purpose")
        _require(set(_list(section.get("claim_ids"), "section claims", nonempty=False)) <= claim_ids,
                 "section claim IDs lack writing assertions")
        for claim_id in section["claim_ids"]:
            _require(any(record["claim_id"] == claim_id and record["text"] in sources[path] for record in assertions),
                     "section claim is not located in its declared source")
        cited = _cited_keys(sources[path])
        declared_keys = _list(section.get("citation_keys"), "section citation keys", nonempty=False)
        _require(set(declared_keys) == cited, "section citations differ from the declared citation keys")
        for name in _list(section.get("evidence"), "section evidence"):
            _read(root, _bound(packet, name))
        baseline = section.get("baseline")
        if baseline is not None:
            _mapping(baseline, "section revision baseline")
            _require(_sha(_read(root, _bound(packet, baseline.get("path")))) == baseline.get("sha256"),
                     "section revision baseline changed")
        if path.endswith(".tex") and len(sources[path].splitlines()) > 300:
            _require(baseline is not None and section.get("line_limit_exception") is not None,
                     "new generated TeX exceeds 300 lines without a preserved existing-large-source deviation")
            exception = _mapping(section.get("line_limit_exception"), "existing large-source deviation")
            _text(exception.get("reason"), "large-source preservation reason")
            _require(baseline is not None and exception.get("baseline_sha256") == baseline.get("sha256"),
                     "new generated TeX above 300 lines lacks a preserved large baseline")
            _require(len(_read(root, baseline["path"]).decode("utf-8").splitlines()) > 300,
                     "large-source exception baseline was not already large")
    authored_sources = set(sources) - _derived_tables(packet)
    _require(authored_sources <= seen_paths, "included manuscript sections lack section packets")
    for path, content in sources.items():
        if path.endswith(".tex") and len(content.splitlines()) > 300 and path not in seen_paths:
            raise ValueError("generated derived TeX exceeds 300 lines: " + path)
    actual_citations = set().union(*(_cited_keys(text) for text in sources.values()))
    for key in actual_citations:
        record = citation_state["plan"].get(key)
        _require(record is not None and record["depth"] != "D" and record["status"] == "verified",
                 "manuscript cites an absent/dropped/unverified citation: " + key)


def _non_empirical(packet):
    brief = packet.get("_brief", {})
    return brief.get("paper_type") in {"review", "survey"} and bool(brief.get("not_applicable", {}).get("experiment"))


def _source_claim(record, citations):
    _require(record.get("strength") == "source_bounded", "source claim cannot exceed verified source scope")
    keys = _list(record.get("citation_keys"), "source assertion citation keys")
    claim = citations["claims"].get(record.get("claim_id"))
    _require(claim is not None and claim["text"] == record["text"], "source assertion differs from the planned claim")
    _require(set(keys) <= claim["supported_keys"], "source assertion lacks supported verified citation bindings")


def _validate_diagram(packet, root):
    _require(_non_empirical(packet), "evidence_diagram requires approved non-empirical review/survey scope")
    citations = _citation_state(packet, root, final=True)
    for key in ("figure", "table", "trace"):
        _bound(packet, packet.get(key))
    image = _read(root, packet["figure"])
    suffix = Path(packet["figure"]).suffix.lower()
    _require((suffix == ".pdf" and image.startswith(b"%PDF-")) or
             (suffix == ".svg" and b"<svg" in image[:1000]), "diagram must be an actual SVG/PDF artifact")
    _require(packet["table"].endswith(".tex") and bool(_read(root, packet["table"]).strip()),
             "evidence comparison table must be nonempty TeX")
    _text(packet.get("caption"), "source diagram caption")
    claim_ids = _list(packet.get("claim_ids"), "diagram claim IDs")
    keys = _list(packet.get("citation_keys"), "diagram citation keys")
    _require(all(key in citations["plan"] for key in keys), "diagram cites unknown sources")
    for claim_id in claim_ids:
        claim = citations["claims"].get(claim_id)
        _require(claim is not None and set(keys) & claim["supported_keys"], "diagram claim lacks verified source support")
    span_paths = _spans(packet, root, packet.get("evidence_spans"))
    trace = _mapping(strict_json(root, packet["trace"]), "source diagram trace")
    expected = {"kind": "evidence_diagram", "figure_sha256": _sha(image),
                "table_sha256": _sha(_read(root, packet["table"])),
                "source_hashes": {path: _sha(_read(root, path)) for path in span_paths},
                "claim_ids": claim_ids, "citation_keys": keys}
    _require(trace == expected, "source diagram trace has stale/mismatched source or assets")


def _validate_delivery(packet, root):
    completion = _mapping(packet.get("completion"), "final completion roles")
    _require(set(completion) == COMPLETION_ROLES, "final manuscript requires all eight completion roles")
    required = set()
    for role in COMPLETION_ROLES:
        paths = _list(completion[role], "completion " + role)
        _require(len(paths) == len(set(paths)), "duplicate paths in completion role " + role)
        for path in paths:
            _require(bool(_read(root, _bound(packet, path)).strip()), "completion evidence is empty: " + path)
            if role != "snapshot":
                required.add(path)
    for path in completion["source"]:
        _require(path.endswith(".tex"), "source completion needs actual TeX files")
    for path in completion["pdf"]:
        _require(path.endswith(".pdf") and _read(root, path).startswith(b"%PDF-"), "pdf completion needs actual compiled PDF")
    for path in completion["bibliography"]:
        _require(path.endswith(".bib"), "bibliography completion needs BibTeX")
    citations = _citation_state(packet, root, final=True)
    literature = citations["literature"]
    for role in ("bibliography", "citation_plan", "citation_verification"):
        _require(literature[role] in completion[role], "completion omits the accepted current " + role)
    accepted_review = packet.get("_history", {}).get("review", {})
    _require(set(completion["review"]) <= set(accepted_review.get("artifacts", [])),
             "review completion is not part of the accepted independent review evidence")
    write = packet.get("_history", {}).get("write", {})
    _require(write.get("manuscript") in completion["source"] and write.get("manuscript_pdf") in completion["pdf"],
             "completion differs from the accepted current manuscript")
    for path in completion["revision"]:
        document = _mapping(strict_json(root, path), "revision evidence")
        _require(document.get("status") in {"initial_draft", "revised"}, "unknown revision identity")
        changes = _list(document.get("changes"), "revision changes", nonempty=False)
        _require(bool(changes) == (document["status"] == "revised"), "revision history contradicts initial/revised status")
        for change in changes:
            _mapping(change, "revision change")
            baseline = _mapping(change.get("baseline"), "revision baseline")
            _require(_sha(_read(root, _bound(packet, baseline.get("path")))) == baseline.get("sha256"), "revision baseline is stale")
            _read(root, _bound(packet, change.get("after")))
            _text(change.get("reason"), "revision reason")
    snapshotted = set()
    for path in completion["snapshot"]:
        snapshot = _mapping(strict_json(root, path), "version snapshot")
        files = _mapping(snapshot.get("files"), "version snapshot files")
        _require(bool(files), "version snapshot is empty")
        for name, recorded_hash in files.items():
            _require(_sha(_read(root, _bound(packet, name))) == recorded_hash, "version snapshot has stale artifact: " + name)
            snapshotted.add(name)
    _require(required <= snapshotted, "version snapshot omits completion artifacts")
    _require(all(name in completion["source"] for name in _source_bundle({**packet, "manuscript": write["manuscript"]}, root)
                 if name not in _derived_tables(packet)),
             "source completion omits an included manuscript section")


def validate_delivery(packet: dict, root: Path) -> list[str]:
    return validate("delivery", packet, root)


def _validate_literature(packet, root):
    catalog = _mapping(strict_json(root, _bound(packet, packet.get("catalog"))), "literature catalog")
    question_time = _timestamp(catalog.get("question_formed_at"), "question formation time")
    candidates = _list(catalog.get("candidates"), "literature candidates")
    identities = set()
    decisions = {}
    for candidate in candidates:
        _mapping(candidate, "literature candidate")
        identity = _text(candidate.get("id"), "candidate ID")
        _require(identity not in identities, "duplicate literature candidate")
        identities.add(identity)
        for key in ("title", "url", "purpose"):
            _text(candidate.get(key), f"candidate {key}")
        _, publication_upper_bound = publication_bounds(candidate.get("published_at"))
        _require(candidate.get("exposure") in {"prospective", "retrospective"}, "declare literature exposure")
        _require(candidate["exposure"] == "retrospective" or publication_upper_bound <= question_time,
                 "post-question source or a publication-year interval overlapping the question cannot be represented as prospective inspiration")
        _require(candidate.get("decision") in {"include", "exclude"}, "declare candidate inclusion decision")
        _require(candidate.get("read_status") in {"read", "registered"}, "declare source read status")
        decisions[identity] = candidate["decision"]
        if candidate["decision"] == "include":
            _require(candidate["read_status"] == "read", "registered source cannot support an included claim")
            source_path = _bound(packet, candidate.get("read_path"))
            source = _read(root, source_path).decode("utf-8")
            _require(bool(source.strip()), "included source is empty")
            verification = _mapping(candidate.get("verification"), "source verification")
            _require(verification.get("status") == "primary_checked", "included source lacks primary verification")
            _require(bool(_read(root, _bound(packet, verification.get("evidence"))).strip()),
                     "source verification evidence is empty")
            for span in _list(candidate.get("evidence_spans"), "source evidence spans"):
                _mapping(span, "source evidence span")
                content = _read(root, _bound(packet, span.get("path"))).decode("utf-8")
                quote = _text(span.get("quote"), "source quote")
                _require(quote in content, "literature evidence span does not match source bytes")
        else:
            _text(candidate.get("exclusion_reason"), "candidate exclusion reason")
    for key in ("naive_baseline_ids", "hard_negative_ids"):
        selected = _list(catalog.get(key), key)
        _require(all(identity in identities for identity in selected), f"unresolved {key}")
        if key == "hard_negative_ids":
            _require(all(decisions[identity] == "exclude" for identity in selected),
                     "hard negatives must preserve exclusion decisions")
    searches = _list(catalog.get("searches"), "literature searches")
    baseline_results = set()
    for search in searches:
        _mapping(search, "search")
        _text(search.get("query"), "search query")
        _text(search.get("method"), "search method")
        _require(all(identity in identities for identity in _list(search.get("result_ids"), "search result IDs")),
                 "unresolved search candidate")
        if search["method"] == "keyword":
            baseline_results.update(search["result_ids"])
    _require(set(catalog["naive_baseline_ids"]) <= baseline_results,
             "naive literature baseline needs recorded keyword retrieval results")
    _citation_state(packet, root)


def _design_registry(plan, packet, root):
    """Resolve the frozen registry; each entry is a separate statistical population."""
    _require("experiment_design_sha256" not in plan, "cannot mix legacy and multiple designs")
    entries = _list(plan.get("experiment_designs"), "experiment_designs")
    registry, paths = {}, set()
    for entry in entries:
        _mapping(entry, "design registry entry")
        _require(set(entry) == {"id", "path", "sha256", "protocol", "claim_ids"}, "invalid design registry fields")
        identity = _text(entry.get("id"), "design ID")
        _require(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,95}", identity), "invalid design ID")
        path = _bound(packet, entry.get("path"))
        _require(identity not in registry and _path(root, path).resolve() not in paths, "duplicate design ID or path")
        _require(entry.get("protocol") in {"paired_case_mean", local_response.PROTOCOL}, "unsupported scientific protocol")
        _require(entry.get("sha256") == _sha(_read(root, path)), "registered design hash mismatch")
        claims = _list(entry.get("claim_ids"), "design claim IDs")
        for claim in claims:
            _text(claim, "claim ID")
        _require(len(claims) == len(set(claims)), "duplicate design claim ID")
        design = _design(root, path)
        _require(design["experiment_id"] == identity, "registered experiment identity mismatch")
        _require(design.get("protocol") == entry["protocol"], "design protocol mismatch")
        # This protocol has one measured claim; multi-claim synthesis needs a separate protocol.
        _require(claims == [design["claim_id"]], "registered claim identity mismatch")
        registry[identity] = entry
        paths.add(_path(root, path).resolve())
    return registry


def _validate_plan(packet, root):
    if "experiment_designs" in packet:
        _design_registry(packet, packet, root)
    elif "experiment_design_sha256" in packet:
        frozen = packet["experiment_design_sha256"]
        _require(isinstance(frozen, str) and re.fullmatch(r"[0-9a-f]{64}", frozen), "invalid frozen design hash")
        matches = [path for path in packet.get("artifacts", []) if _sha(_read(root, path)) == frozen]
        _require(len(matches) == 1, "frozen design must identify one bound artifact")
        _design(root, matches[0])
    else:
        _require(packet.get("_brief", {}).get("paper_type") != "original", "empirical plan needs a frozen experiment design")


def _collection(packet, key, registry):
    legacy = {"design", "results", "summary"} if key == "experiments" else {"design", "results", "statistics", "table", "figure", "trace", "caption"}
    _require(not legacy.intersection(packet), "cannot mix legacy and collection evidence")
    rows = _list(packet.get(key), key)
    seen, identities = set(), set()
    for row in rows:
        _mapping(row, key + " entry")
        design_id = _text(row.get("design_id"), "evidence design ID")
        _require(design_id in registry, "unregistered evidence design")
        if key == "experiments":
            _require(set(row) == {"design_id", "results", "summary"}, "invalid experiment entry fields")
            _require(design_id not in seen, "duplicate experiment design")
        else:
            _require(set(row) == {"id", "design_id", "results", "statistics", "table", "figure", "trace", "caption"}, "invalid evidence set fields")
            identity = _text(row.get("id"), "evidence set ID")
            _require(identity not in identities, "duplicate evidence set ID")
            identities.add(identity)
        seen.add(design_id)
    _require(seen == set(registry), "evidence omits registered designs")
    return rows


def _single_packet(packet, entry, row):
    return {**packet, **row, "design": entry["path"],
            "_plan": {"experiment_design_sha256": entry["sha256"]}}


def _validate_experiment(packet, root):
    plan = _mapping(packet.get("_plan"), "frozen plan")
    if "experiment_designs" not in plan:
        _require("experiments" not in packet, "multiple experiments need a frozen registry")
        return _validate_single_experiment(packet, root)
    registry = _design_registry(plan, packet, root)
    owners, provider_owners = {}, {}
    for row in _collection(packet, "experiments", registry):
        entry = registry[row["design_id"]]
        results = _mapping(strict_json(root, row["results"]), "experiment results")
        _require(results.get("design_id") == entry["id"], "result design identity mismatch")
        raw_paths = ([item["path"] for item in results.get("events", [])]
                     if entry["protocol"] == local_response.PROTOCOL else [run["raw"] for run in results.get("runs", [])])
        for path in [row["results"], row["summary"], *raw_paths]:
            resolved = _path(root, path).resolve()
            _require(resolved not in owners, "cross-design evidence path reuse")
            owners[resolved] = entry["id"]
        verified_events = _validate_single_experiment(_single_packet(packet, entry, row), root)
        for event in verified_events or []:
            receipt = event.get("data", {}).get("receipt", {})
            if event["kind"] == "terminal" and receipt.get("source") == "provider_receipt":
                identity = tuple(receipt[key] for key in ("provider", "model", "version", "provider_request_id"))
                _require(identity not in provider_owners, "cross-design provider request reuse")
                provider_owners[identity] = entry["id"]


def _validate_figures(packet, root):
    plan = _mapping(packet.get("_plan", {}), "frozen plan")
    if "experiment_designs" not in plan:
        _require("evidence_sets" not in packet, "multiple evidence sets need a frozen registry")
        return _validate_single_figures(packet, root)
    _require(packet.get("mode", "statistics") == "statistics", "multiple designs require statistical evidence sets")
    registry = _design_registry(plan, packet, root)
    accepted = _mapping(packet.get("_history", {}).get("experiment"), "accepted experiment packet")
    # Revalidate all accepted measurements, including design identity on every raw record.
    _validate_experiment({**accepted, "_plan": plan, "_history": packet.get("_history", {})}, root)
    experiments = {row["design_id"]: row for row in _collection(accepted, "experiments", registry)}
    paths = set()
    for row in _collection(packet, "evidence_sets", registry):
        entry = registry[row["design_id"]]
        _require(row["results"] == experiments[entry["id"]]["results"], "figures do not use accepted experiment results")
        for key in ("statistics", "table", "figure", "trace"):
            resolved = _path(root, row[key]).resolve()
            _require(resolved not in paths, "duplicate evidence set artifact")
            paths.add(resolved)
        _validate_single_figures(_single_packet(packet, entry, row), root)


def _validate_single_experiment(packet, root):
    design_path = _bound(packet, packet.get("design"))
    results_path = _bound(packet, packet.get("results"))
    frozen = _mapping(packet.get("_plan"), "frozen plan").get("experiment_design_sha256")
    _require(isinstance(frozen, str) and len(frozen) == 64, "frozen plan must bind experiment design hash")
    design, results, _ = _experiment(root, design_path, results_path, frozen)
    summary = _read(root, _bound(packet, packet.get("summary"))).decode("utf-8")
    _require(bool(summary.strip()), "experiment summary is empty")
    if design.get("protocol") == local_response.PROTOCOL:
        _, _, stats, events = local_response_evidence.load(root, design_path, results_path, frozen)
        _require(stats["assessment"] != "incomplete", "local acquisition is incomplete; retain failures and unstarted slots")
        for path in stats["input_hashes"]["raw"]:
            _bound(packet, path)
        for event in events:
            if event["kind"] == "terminal" and not event["data"]["valid"]:
                _require(event["data"]["slot_id"] in summary, "local summary omits invalid/failed slot")
        return events
    for row in results["runs"]:
        _bound(packet, row["raw"])
        if row["status"] != "completed":
            _require(row["id"] in summary, "experiment summary omits failed/stopped run: " + row["id"])
    if "evaluator" in design:
        _bound(packet, design["evaluator"]["path"])
    _statistics(root, design_path, results_path, frozen)


def _validate_single_figures(packet, root):
    if packet.get("mode") == "evidence_diagram":
        _validate_diagram(packet, root)
        return
    _require(packet.get("mode", "statistics") == "statistics", "unknown figure evidence mode")
    for key in ("design", "results", "statistics", "table", "figure", "trace"):
        _bound(packet, packet.get(key))
    frozen = _mapping(packet.get("_plan"), "frozen plan").get("experiment_design_sha256")
    _require(isinstance(frozen, str) and len(frozen) == 64, "figures need frozen experiment design")
    stats = _statistics(root, packet["design"], packet["results"], frozen)
    reported = _mapping(strict_json(root, packet["statistics"]), "figure statistics")
    _require(_canonical(stats) == _canonical(reported), "plotting statistics differ from raw measurements")
    _require(_read(root, packet["table"]) == _table(stats).encode(), "table values differ from recomputed statistics")
    expected_figure = _figure(stats, Path(packet["figure"]).suffix.lower())
    _require(_read(root, packet["figure"]) == expected_figure, "figure differs from evidence-bound renderer")
    trace = _mapping(strict_json(root, packet["trace"]), "figure trace")
    expected_trace = {"schema_version": 1, "statistics_sha256": _sha(_canonical(stats)),
                      "table": packet["table"], "table_sha256": _sha(_read(root, packet["table"])),
                      "figure": packet["figure"], "figure_sha256": _sha(expected_figure)}
    _require(trace == expected_trace, "figure trace differs from inputs or rendered assets")
    _require(packet.get("caption") == _caption(stats), "caption changes statistical unit, denominator, or uncertainty")
    for raw_path in stats["input_hashes"]["raw"]:
        _bound(packet, raw_path)


def _validate_write(packet, root):
    sources = _source_bundle(packet, root)
    manuscript = "\n".join(sources.values())
    citations = _citation_state(packet, root, final=True)
    _require(packet.get("bibliography") == citations["literature"]["bibliography"], "writing bibliography differs from accepted literature")
    bibliography = _read(root, _bound(packet, packet.get("bibliography"))).decode("utf-8")
    _require(bool(manuscript.strip()) and bool(bibliography.strip()), "manuscript/bibliography cannot be empty")
    document = _mapping(strict_json(root, _bound(packet, packet.get("assertions"))), "writing assertions")
    records = _list(document.get("assertions"), "writing assertions")
    identities, all_stats = set(), []
    for record in records:
        _mapping(record, "assertion")
        identity = _text(record.get("id"), "assertion ID")
        _require(identity not in identities, "duplicate assertion ID")
        identities.add(identity)
        text = _text(record.get("text"), "assertion text")
        _require(text in manuscript, "assertion text is absent from the manuscript")
        if record.get("kind") == "source_claim":
            _source_claim(record, citations)
            continue
        stats_path = _bound(packet, record.get("statistics"))
        stats = _mapping(strict_json(root, stats_path), "assertion statistics")
        figures = packet.get("_history", {}).get("figures", {})
        plan = _mapping(packet.get("_plan"), "frozen plan")
        if "experiment_designs" in plan:
            registry = _design_registry(plan, packet, root)
            _validate_figures({**figures, "_plan": plan, "_history": packet.get("_history", {})}, root)
            sets = {row["id"]: row for row in figures["evidence_sets"]}
            evidence = sets.get(record.get("evidence_set_id"))
            _require(evidence is not None and record.get("design_id") == evidence["design_id"], "assertion evidence/design identity mismatch")
            entry = registry[evidence["design_id"]]
            _require(record.get("claim_id") in entry["claim_ids"], "assertion registered claim mismatch")
            figures = {**evidence, "design": entry["path"]}
            frozen = entry["sha256"]
        else:
            _require("design_id" not in record and "evidence_set_id" not in record, "cannot mix legacy and collection assertions")
            frozen = plan.get("experiment_design_sha256")
        _require(figures.get("statistics") == stats_path, "assertion does not use accepted figure statistics")
        _require(isinstance(frozen, str) and len(frozen) == 64, "writing needs frozen design")
        computed = _statistics(root, figures.get("design"), figures.get("results"), frozen)
        _require(_canonical(computed) == _canonical(stats), "writing statistics differ from raw evidence")
        _require(record.get("claim_id") == stats.get("claim_id"), "assertion claim identity mismatch")
        _require(record.get("kind") in {"numeric", "comparison"}, "causal interpretation needs an additional supported protocol")
        _require(record.get("strength") == "descriptive", "unsupported conclusion strength; sample summaries are descriptive")
        if stats.get("protocol") == local_response.PROTOCOL:
            expected = local_response_evidence.assertion_value(record, stats)
        else:
            _require(record.get("condition") == "all-planned-cases", "assertion changes the comparison condition")
            _require(record.get("unit") == stats.get("metric", {}).get("unit"), "assertion metric unit mismatch")
            _require(type(record.get("denominator")) is int and record["denominator"] == stats.get("n_cases"),
                     "assertion denominator mismatch")
            measure = record.get("measure")
            measures = {"conditions." + name + ".mean": summary["mean"] for name, summary in stats["conditions"].items()}
            measures.update({"contrasts." + name + ".mean": summary["mean"] for name, summary in stats.get("contrasts", {}).items()})
            if "delta" in stats:
                measures.update({name + ".mean": stats["conditions"][name]["mean"] for name in ("baseline", "candidate")})
                measures["delta.mean"] = stats["delta"]["mean"]
            _require(isinstance(measure, str) and measure in measures, "unsupported assertion measure")
            expected = measures[measure]
        _number(record.get("value"), "assertion value")
        _require(math.isclose(record["value"], expected, rel_tol=1e-10, abs_tol=1e-10), "assertion number differs from recorded statistics")
        tokens = re.findall(r"(?<![\w.])[-+]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][-+]?[0-9]+)?", text)
        _require(any(math.isclose(float(token), expected, rel_tol=1e-6, abs_tol=5e-6) for token in tokens),
                 "assertion prose does not contain its bound numerical value")
        _require(record["unit"] in text, "assertion prose omits its measured unit")
        all_stats.append(stats)
    _sections(packet, root, sources, records, citations)
    limitations = _list(document.get("limitations"), "manuscript limitations")
    kinds = set()
    for limitation in limitations:
        _mapping(limitation, "limitation")
        kinds.add(_text(limitation.get("kind"), "limitation kind"))
        _require(_text(limitation.get("text"), "limitation text") in manuscript,
                 "limitation is absent from the manuscript")
    _require("scope" in kinds, "manuscript must state measured scope")
    if any(stats.get("n_cases", 3) < 5 for stats in all_stats):
        _require("small_sample" in kinds, "small independent sample requires a manuscript limitation")
    if any(stats.get("failed_runs", 0) or stats.get("stopped_runs", 0) or stats.get("counts", {}).get("invalid", 0) or stats.get("counts", {}).get("failed", 0) for stats in all_stats):
        _require("failure" in kinds, "failed/stopped measurements need a manuscript limitation")
    if any(stats.get("adverse_case_ids") or stats.get("assessment") == "local_prediction_failed" for stats in all_stats):
        _require("adverse" in kinds, "adverse paired cases must remain visible in the manuscript")
    for key in ("problem", "choice", "finding", "scope"):
        _text(_mapping(document.get("prose_review"), "reader-oriented prose review").get(key), "prose review " + key)
    required_facts = {"identity", "metric", "data", "baseline", "denominator", "unit", "interval", "strength"}
    for revision in _list(document.get("revisions"), "revision history", nonempty=False):
        _mapping(revision, "revision")
        for key in ("before", "after", "reason"):
            _text(revision.get(key), "revision " + key)
        _require(revision["after"] in manuscript, "revised prose is absent from manuscript")
        before = _mapping(revision.get("facts_before"), "revision facts before")
        after = _mapping(revision.get("facts_after"), "revision facts after")
        _require(required_facts <= set(before) and before == after,
                 "prose revision changes or omits factual relationships")


def validate(stage: str, packet: dict, root: Path) -> list[str]:
    """Return blocking issues, without modifying research state or invoking models."""
    validator = {"plan": _validate_plan, "literature": _validate_literature, "experiment": _validate_experiment,
                 "figures": _validate_figures, "write": _validate_write, "delivery": _validate_delivery}.get(stage)
    if validator is None:
        return []
    try:
        _mapping(packet, "science packet")
        validator(packet, Path(root))
    except (ValueError, OSError, UnicodeError, TypeError, KeyError, RecursionError) as error:
        return [f"{stage}: {error}"]
    return []
