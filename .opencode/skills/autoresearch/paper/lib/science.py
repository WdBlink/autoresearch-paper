"""Evidence checks and deterministic statistics for the paper command.

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
from datetime import datetime
from pathlib import Path
from statistics import mean, stdev

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


def _path(root, value):
    _text(value, "artifact path")
    relative = Path(value)
    _require(not relative.is_absolute() and ".." not in relative.parts,
             "artifact path must be relative to the run")
    root = Path(root).resolve()
    path = root / relative
    _require(path.resolve().is_relative_to(root), "artifact escapes run root")
    return path


def _read(root, value):
    path = _path(root, value)
    _require(path.is_file(), f"artifact is missing: {value}")
    _require(path.stat().st_size <= MAX_JSON_BYTES, f"artifact exceeds size bound: {value}")
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
    return json.loads(_read(root, value), object_pairs_hook=_unique_object,
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
    _require(design.get("conditions") == ["baseline", "candidate"],
             "conditions must be baseline and candidate in that order")
    _require(len(cases) * len(seeds) * 2 <= 100000, "planned experiment exceeds record bound")
    _require(design.get("failure_policy") == "penalty", "only a frozen penalty failure policy is supported")
    _number(design.get("failure_value"), "failure penalty")
    stats = _mapping(design.get("statistics"), "statistics plan")
    _require(stats.get("estimator") == "mean", "unsupported estimator")
    _require(stats.get("interval") in INTERVALS, "unsupported interval")
    _require(stats.get("paired") is True, "paired case comparison is required")
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
    design_hash = _sha(_read(root, design_path))
    if frozen_hash is not None:
        _require(design_hash == frozen_hash, "experiment design differs from the frozen plan")
    results = _mapping(strict_json(root, results_path), "experiment results")
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
    design, results, raw_hashes = _experiment(root, design_path, results_path, frozen_hash)
    values = {(row["case_id"], row["seed"], row["condition"]):
              row["value"] if row["status"] == "completed" else design["failure_value"]
              for row in results["runs"]}
    case_values = {condition: [mean(values[(case, seed, condition)] for seed in design["seeds"])
                              for case in design["cases"]] for condition in design["conditions"]}
    interval = design["statistics"]["interval"]
    condition_stats = {condition: _summary(values, interval) for condition, values in case_values.items()}
    differences = [candidate - baseline for baseline, candidate in
                   zip(case_values["baseline"], case_values["candidate"])]
    delta = _summary(differences, interval)
    sign = -1 if design["metric"]["direction"] == "lower" else 1
    improving = sign * delta["mean"] > 0
    _require(results["outcome"] != "positive" or improving,
             "positive outcome contradicts the observed paired mean")
    _require(results["outcome"] != "negative" or not improving,
             "negative outcome contradicts the observed paired mean; use inconclusive for uncertain evidence")
    rows = results["runs"]
    return {
        "schema_version": 1,
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
        "case_values": case_values, "case_differences": differences,
        "interval_type": interval, "conditions": condition_stats, "delta": delta,
        "adverse_case_ids": [case for case, difference in zip(design["cases"], differences)
                             if sign * difference < 0],
        "outcome": results["outcome"],
        "limitations": ["descriptive_case_summary"] +
                       (["normal_approximation_not_confirmatory"] if interval == "ci95_normal" else []),
    }


def _caption(stats):
    label = {"sd": "SD", "se": "SE", "ci95_normal": "exploratory normal 95% CI", "none": "no interval"}
    return (f"{stats['metric']['name']} ({stats['metric']['unit']}; {stats['metric']['direction']} is better). "
            f"Points show case means; summary intervals show {label[stats['interval_type']]}. "
            f"n={stats['n_cases']} paired independent cases, {stats['seeds_per_case']} seeds averaged within each case. "
            f"Denominator={stats['planned_runs']} planned runs; {stats['failed_runs']} failed and "
            f"{stats['stopped_runs']} stopped runs retain the frozen penalty {stats['failure_value']}. "
            "Delta is candidate minus baseline. These are descriptive case results.")


def _tex(value):
    replacements = {"\\": r"\textbackslash{}", "&": r"\&", "%": r"\%", "$": r"\$", "#": r"\#",
                    "_": r"\_", "{": r"\{", "}": r"\}", "~": r"\textasciitilde{}", "^": r"\textasciicircum{}"}
    return "".join(replacements.get(character, character) for character in str(value))


def _table(stats):
    label = {"none": "No interval", "sd": r"Mean $\pm$ SD bounds", "se": r"Mean $\pm$ SE bounds", "ci95_normal": r"Exploratory normal 95\% CI"}[stats["interval_type"]]
    lines = [r"\begin{minipage}{\linewidth}\centering", r"\begin{tabular}{lrr}", "Condition & Mean (" + _tex(stats["metric"]["unit"]) + ") & " + label + r" \\", r"\hline"]
    for name in ("baseline", "candidate", "delta"):
        values = stats["delta"] if name == "delta" else stats["conditions"][name]
        interval = values["interval"]
        display = "none" if interval is None else f"[{interval[0]:.6f}, {interval[1]:.6f}]"
        lines.append(f"{name} & {values['mean']:.6f} & {display} " + r"\\")
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
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="640" height="420" viewBox="0 0 640 420">',
             f'<desc>statistics sha256:{digest}; {html.escape(_caption(stats))}</desc>',
             '<rect width="640" height="420" fill="white"/>',
             '<g font-family="sans-serif" font-size="14" fill="#202020">',
             f'<text x="24" y="26">{html.escape(stats["metric"]["name"])} ({html.escape(stats["metric"]["unit"])})</text>',
             '<path d="M80 50 V315 H600" fill="none" stroke="#202020"/>']
    for index in range(6):
        value = low + (high - low) * index / 5
        parts.append(f'<text x="12" y="{y(value)+5:.3f}">{value:.3f}</text>')
    for index, condition in enumerate(("baseline", "candidate")):
        x = 225 + index * 230
        color = ("#0072B2", "#D55E00")[index]
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
        parts.append(f'<text x="{x-40}" y="343">{condition}</text>')
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
        figure = Figure(figsize=(6.4, 4.2), layout="constrained")
        axis = figure.subplots()
        for index, condition in enumerate(("baseline", "candidate")):
            color, marker = (("#0072B2", "o"), ("#D55E00", "s"))[index]
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
        axis.set_xticks([0, 1], ["baseline", "candidate"])
        axis.set_xlim(-0.5, 1.5)
        axis.set_ylabel(f"{stats['metric']['name']} ({stats['metric']['unit']})")
        axis.set_title(f"Paired case means; {stats['metric']['direction']} is better")
        axis.grid(axis="y", alpha=0.2)
        figure.supxlabel(f"n={stats['n_cases']} cases; {stats['interval_type']}; "
                         f"failed={stats['failed_runs']}, stopped={stats['stopped_runs']} (penalty retained)", fontsize=9)
        output = io.BytesIO()
        figure.savefig(output, format="pdf", metadata={"Creator": "autoresearch-paper evidence renderer v1",
                       "CreationDate": None, "ModDate": None,
                       "Subject": "statistics sha256:" + _sha(_canonical(stats))})
        return output.getvalue()


def _figure(stats, suffix):
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
    raw_inputs = {row["raw"] for row in results["runs"]}
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
        publication = _timestamp(candidate.get("published_at"), "source publication time")
        _require(candidate.get("exposure") in {"prospective", "retrospective"}, "declare literature exposure")
        _require(candidate["exposure"] == "retrospective" or publication <= question_time,
                 "post-question source cannot be represented as prospective inspiration")
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


def _validate_experiment(packet, root):
    design_path = _bound(packet, packet.get("design"))
    results_path = _bound(packet, packet.get("results"))
    frozen = _mapping(packet.get("_plan"), "frozen plan").get("experiment_design_sha256")
    _require(isinstance(frozen, str) and len(frozen) == 64, "frozen plan must bind experiment design hash")
    design, results, _ = _experiment(root, design_path, results_path, frozen)
    summary = _read(root, _bound(packet, packet.get("summary"))).decode("utf-8")
    _require(bool(summary.strip()), "experiment summary is empty")
    for row in results["runs"]:
        _bound(packet, row["raw"])
        if row["status"] != "completed":
            _require(row["id"] in summary, "experiment summary omits failed/stopped run: " + row["id"])
    if "evaluator" in design:
        _bound(packet, design["evaluator"]["path"])
    _statistics(root, design_path, results_path, frozen)


def _validate_figures(packet, root):
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
    manuscript = _read(root, _bound(packet, packet.get("manuscript"))).decode("utf-8")
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
        stats_path = _bound(packet, record.get("statistics"))
        stats = _mapping(strict_json(root, stats_path), "assertion statistics")
        figures = packet.get("_history", {}).get("figures", {})
        _require(figures.get("statistics") == stats_path, "assertion does not use accepted figure statistics")
        frozen = _mapping(packet.get("_plan"), "frozen plan").get("experiment_design_sha256")
        _require(isinstance(frozen, str) and len(frozen) == 64, "writing needs frozen design")
        computed = _statistics(root, figures.get("design"), figures.get("results"), frozen)
        _require(_canonical(computed) == _canonical(stats), "writing statistics differ from raw evidence")
        _require(record.get("claim_id") == stats.get("claim_id"), "assertion claim identity mismatch")
        _require(record.get("kind") in {"numeric", "comparison"}, "causal interpretation needs an additional supported protocol")
        _require(record.get("strength") == "descriptive", "unsupported conclusion strength; sample summaries are descriptive")
        _require(record.get("condition") == "all-planned-cases", "assertion changes the comparison condition")
        _require(record.get("unit") == stats.get("metric", {}).get("unit"), "assertion metric unit mismatch")
        _require(type(record.get("denominator")) is int and record["denominator"] == stats.get("n_cases"),
                 "assertion denominator mismatch")
        measure = record.get("measure")
        _require(measure in {"baseline.mean", "candidate.mean", "delta.mean"}, "unsupported assertion measure")
        expected = stats["delta"]["mean"] if measure == "delta.mean" else stats["conditions"][measure.split(".")[0]]["mean"]
        _number(record.get("value"), "assertion value")
        _require(math.isclose(record["value"], expected, rel_tol=1e-10, abs_tol=1e-10), "assertion number differs from recorded statistics")
        tokens = re.findall(r"(?<![\w.])[-+]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][-+]?[0-9]+)?", text)
        _require(any(math.isclose(float(token), expected, rel_tol=1e-6, abs_tol=5e-6) for token in tokens),
                 "assertion prose does not contain its bound numerical value")
        _require(record["unit"] in text, "assertion prose omits its measured unit")
        all_stats.append(stats)
    limitations = _list(document.get("limitations"), "manuscript limitations")
    kinds = set()
    for limitation in limitations:
        _mapping(limitation, "limitation")
        kinds.add(_text(limitation.get("kind"), "limitation kind"))
        _require(_text(limitation.get("text"), "limitation text") in manuscript,
                 "limitation is absent from the manuscript")
    _require("scope" in kinds, "manuscript must state measured scope")
    if any(stats["n_cases"] < 5 for stats in all_stats):
        _require("small_sample" in kinds, "small independent sample requires a manuscript limitation")
    if any(stats["failed_runs"] or stats["stopped_runs"] for stats in all_stats):
        _require("failure" in kinds, "failed/stopped measurements need a manuscript limitation")
    if any(stats["adverse_case_ids"] for stats in all_stats):
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
    validator = {"literature": _validate_literature, "experiment": _validate_experiment,
                 "figures": _validate_figures, "write": _validate_write}.get(stage)
    if validator is None:
        return []
    try:
        _mapping(packet, "science packet")
        validator(packet, Path(root))
    except (ValueError, OSError, UnicodeError, TypeError, KeyError, RecursionError) as error:
        return [f"{stage}: {error}"]
    return []
