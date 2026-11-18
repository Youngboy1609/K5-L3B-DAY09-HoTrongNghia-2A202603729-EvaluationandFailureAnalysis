"""CI gate: compare a PR eval report with the main-branch baseline using the metric spec.

    python -m lab9.gate --pr reports/eval_workflow.json --baseline reports/baseline_v1.json

exit 0 = merge, exit 1 = blocked. Safety metrics: max 0, no averaging away.
Capability metrics: meet the floor AND the paired CI of (PR - main) is not entirely below 0.
Thresholds may only get stricter on the same eval-set version (ratchet).
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from lab8.console import utf8_stdio
from lab9 import stats
from lab9.eval import SPEC, aggregate, load_spec, per_item


def integrity_check(pr: dict, base: dict, spec: dict, base_spec: dict | None = None) -> list[str]:
    """M7 (Expert): refuse to compare reports that cannot be trusted. Return a list of problems
    (empty = trustworthy). A gate that passes a broken report is worse than no gate.
    Must catch at least:
      - any metric value in pr["metrics"] that is NaN or inf
      - len(pr["rows"]) != manifest items x len(manifest seeds)   (dropped / duplicated rows)
      - the (item_id, seed) set of PR differs from the baseline's (cherry-picked seeds/items)
      - pr["evaluator_failures"] non-empty, or a row whose value for a graded spec metric is
        None (a crashed grader silently scores as "missing" and drops out of the mean)
      - base_spec given and a threshold in spec is LOOSER than in base_spec for the same
        eval-set version (ratchet: max may not rise, min may not fall, a blocking metric may
        not become non-blocking, a metric may not disappear; the same for spec["slices"],
        including dropping no_significant_drop)
      - an item's slice tags in PR rows differ from the baseline's (relabelling an item out of a
        slice hides its regression from the slice gate)"""
    problems: list[str] = []
    def problem(message: str) -> None:
        if message not in problems:
            problems.append(message)

    def finite(value: object) -> bool:
        # Row grader outputs are booleans; aggregate metrics are numeric. Both are valid finite values.
        return isinstance(value, bool) or (isinstance(value, (int, float)) and math.isfinite(value))

    def valid_spec(candidate: dict, label: str) -> None:
        metric_entries = candidate.get("metrics", [])
        slice_entries = candidate.get("slices", [])
        if not isinstance(metric_entries, list) or not isinstance(slice_entries, list):
            problem(f"{label} spec metrics/slices are invalid")
            return
        bootstrap = candidate.get("bootstrap", {})
        if not isinstance(bootstrap, dict):
            problem(f"{label} bootstrap config is invalid")
        else:
            n_resamples = bootstrap.get("n_resamples", 1000)
            confidence = bootstrap.get("confidence", 0.95)
            rng = bootstrap.get("rng", 2027)
            if not isinstance(n_resamples, int) or isinstance(n_resamples, bool) or n_resamples < 1:
                problem(f"{label} bootstrap n_resamples is invalid")
            if not finite(confidence) or isinstance(confidence, bool) or not 0 < confidence < 1:
                problem(f"{label} bootstrap confidence is invalid")
            if not isinstance(rng, int) or isinstance(rng, bool):
                problem(f"{label} bootstrap rng is invalid")
        seen_metrics: set[str] = set()
        for entry in metric_entries:
            if not isinstance(entry, dict) or not isinstance(entry.get("id"), str):
                problem(f"{label} spec has malformed metric entry")
                continue
            mid = entry["id"]
            if mid in seen_metrics:
                problem(f"{label} spec duplicates metric {mid}")
            seen_metrics.add(mid)
            threshold = entry.get("threshold", {})
            if not isinstance(threshold, dict):
                problem(f"{label} threshold for {mid} is invalid")
                continue
            for bound in ("min", "max", "max_increase"):
                if bound in threshold and (not finite(threshold[bound]) or isinstance(threshold[bound], bool)):
                    problem(f"{label} threshold {mid}.{bound} is not finite numeric")
            if "min" in threshold and "max" in threshold and finite(threshold["min"]) and finite(threshold["max"]) and threshold["min"] > threshold["max"]:
                problem(f"{label} threshold for {mid} has min above max")
            if "max_increase" in threshold and finite(threshold["max_increase"]) and threshold["max_increase"] < 0:
                problem(f"{label} threshold {mid}.max_increase is negative")
            if "blocking" in entry and not isinstance(entry["blocking"], bool):
                problem(f"{label} blocking flag for {mid} is invalid")
            if "no_significant_drop" in threshold and not isinstance(threshold["no_significant_drop"], bool):
                problem(f"{label} no_significant_drop flag for {mid} is invalid")
        seen_slices: set[tuple[str, str]] = set()
        for entry in slice_entries:
            if not isinstance(entry, dict) or not isinstance(entry.get("name"), str) or not isinstance(entry.get("metric"), str):
                problem(f"{label} spec has malformed slice entry")
                continue
            key = (entry["name"], entry["metric"])
            if key in seen_slices:
                problem(f"{label} spec duplicates slice {key}")
            seen_slices.add(key)
            if entry["metric"] not in seen_metrics:
                problem(f"{label} slice {entry['name']} references unknown metric {entry['metric']}")
            for bound in ("min", "max"):
                if bound in entry and (not finite(entry[bound]) or isinstance(entry[bound], bool)):
                    problem(f"{label} slice {entry['name']}.{bound} is not finite numeric")
            if "min" in entry and "max" in entry and finite(entry["min"]) and finite(entry["max"]) and entry["min"] > entry["max"]:
                problem(f"{label} slice {entry['name']} has min above max")
            if "blocking" in entry and not isinstance(entry["blocking"], bool):
                problem(f"{label} blocking flag for slice {entry['name']} is invalid")
            if "no_significant_drop" in entry and not isinstance(entry["no_significant_drop"], bool):
                problem(f"{label} no_significant_drop flag for slice {entry['name']} is invalid")
        pass_k = candidate.get("pass_k", [])
        if (not isinstance(pass_k, list) or any(not isinstance(k, int) or isinstance(k, bool) or k < 1 for k in pass_k)
                or len(set(pass_k)) != len(pass_k)):
            problem(f"{label} pass_k values are invalid")

    if not isinstance(spec, dict):
        return ["PR spec is not an object"]
    valid_spec(spec, "PR")
    if base_spec is not None and not isinstance(base_spec, dict):
        return problems + ["baseline spec is not an object"]
    if base_spec is not None:
        valid_spec(base_spec, "baseline")
    if problems:
        return problems
    if not isinstance(spec.get("metrics", []), list):
        return problems
    for label, report in (("PR", pr), ("baseline", base)):
        if not isinstance(report, dict):
            problem(f"{label} report is not an object")
            continue
        metrics = report.get("metrics")
        if not isinstance(metrics, dict):
            problem(f"{label} metrics are missing or invalid")
        else:
            for mid, value in metrics.items():
                if value is not None and not finite(value):
                    problem(f"{label} metric {mid} is not finite")
        rows = report.get("rows")
        manifest = report.get("manifest")
        if not isinstance(rows, list) or not isinstance(manifest, dict):
            problem(f"{label} rows or manifest are missing or invalid")
            continue
        seeds = manifest.get("seeds")
        count = manifest.get("items")
        if (not isinstance(seeds, list) or not seeds
                or not all(isinstance(seed, (str, int)) and not isinstance(seed, bool) for seed in seeds)
                or len(set(seeds)) != len(seeds)
                or not isinstance(count, int) or isinstance(count, bool) or count <= 0):
            problem(f"{label} manifest item/seed counts are invalid")
            continue
        if not isinstance(manifest.get("eval_set_sha"), str) or not manifest.get("eval_set_sha"):
            problem(f"{label} manifest eval_set_sha is missing or invalid")
        if len(rows) != count * len(seeds):
            problem(f"{label} row count {len(rows)} != manifest items x seeds {count * len(seeds)}")
        expected_seeds = set(seeds)
        spec_metrics = [metric for metric in spec.get("metrics", []) if isinstance(metric, dict)]
        row_metrics = {metric.get("id") for metric in spec_metrics
                       if any(isinstance(row, dict) and metric.get("id") in row for row in rows)}
        # Registered graders must produce a value in every row. Toy reports may use
        # synthetic metric ids, so only require fields backed by the active registry.
        try:
            from lab9.graders import GRADERS
            registered = set(GRADERS)
        except ImportError:
            registered = set()
        registered.update(m.get("id") for m in spec.get("metrics", [])
                          if m.get("grader") in {"code", "lab8.metrics.trial_pass"})
        seen: set[tuple[object, object]] = set()
        for row in rows:
            if not isinstance(row, dict) or "item_id" not in row or "seed" not in row:
                problem(f"{label} contains a malformed row")
                continue
            if not isinstance(row["item_id"], str) or not row["item_id"]:
                problem(f"{label} row item_id is invalid")
                continue
            if not isinstance(row["seed"], (int, str)) or isinstance(row["seed"], bool):
                problem(f"{label} row seed is invalid")
                continue
            key = (row["item_id"], row["seed"])
            if key in seen:
                problem(f"{label} contains duplicate row {key}")
            seen.add(key)
            if row["seed"] not in expected_seeds:
                problem(f"{label} row uses undeclared seed {row['seed']}")
            for metric in spec_metrics:
                mid = metric.get("id")
                if (mid in row_metrics or mid in registered) and mid not in row:
                    problem(f"{label} row {key} is missing {mid}")
                elif mid in row and row[mid] is None:
                    problem(f"{label} row {key} has missing {mid}")
                elif mid in row and isinstance(row[mid], (int, float)) and not finite(row[mid]):
                    problem(f"{label} row {key} has non-finite {mid}")
        item_seeds: dict[str, set[object]] = {}
        for row in rows:
            if isinstance(row, dict) and isinstance(row.get("item_id"), str):
                try:
                    item_seeds.setdefault(row["item_id"], set()).add(row.get("seed"))
                except TypeError:
                    continue
        if len(item_seeds) != count:
            problem(f"{label} unique item count does not match manifest")
        for item_id, observed_seeds in item_seeds.items():
            if observed_seeds != expected_seeds:
                problem(f"{label} item {item_id} does not contain every manifest seed")
        failures = report.get("evaluator_failures")
        if not isinstance(failures, list):
            problem(f"{label} evaluator_failures is missing or invalid")
        elif failures:
            problem(f"{label} has evaluator failures")

        # Recompute every aggregate whose raw row inputs are available. This catches
        # reports that retain failing rows but forge the summary values used by gates.
        metric_ids = [m.get("id") for m in spec.get("metrics", [])
                      if isinstance(m, dict) and isinstance(m.get("id"), str)
                      and all(isinstance(row, dict) and m["id"] in row and row[m["id"]] is not None for row in rows)]
        if isinstance(metrics, dict):
            for mid in metric_ids:
                if mid not in metrics:
                    problem(f"{label} aggregate {mid} is missing")
        if isinstance(metrics, dict) and rows and metric_ids:
            try:
                for metric in spec_metrics:
                    mid = metric.get("id")
                    if mid not in metric_ids or mid not in metrics:
                        continue
                    values = [row[mid] for row in rows]
                    expected = sum(values) if metric.get("kind") == "safety" else round(sum(values) / len(values), 4)
                    if not finite(metrics[mid]) or abs(float(metrics[mid]) - float(expected)) > 0.00011:
                        problem(f"{label} aggregate {mid} disagrees with raw rows")
                recomputed = {}
                if all(isinstance(row, dict) and "pass_rate" in row and row["pass_rate"] is not None for row in rows):
                    derived_rows = [{**row, "cost": row.get("cost", 0.0)} for row in rows]
                    recomputed = aggregate(derived_rows, [], k_values=spec.get("pass_k", []))
                    for metric in spec_metrics:
                        mid = metric.get("id")
                        if mid in recomputed and mid in {"pass_5", *(f"{prefix}_{k}" for k in spec.get("pass_k", []) for prefix in ("pass_at", "pass_hat"))} and mid not in metrics:
                            problem(f"{label} aggregate {mid} is missing")
                for mid, observed in metrics.items():
                    if mid == "cost_per_success" and not all("cost" in row for row in rows if isinstance(row, dict)):
                        continue
                    if mid not in recomputed:
                        continue
                    expected = recomputed[mid]
                    if expected is None or observed is None:
                        if expected is not observed:
                            problem(f"{label} aggregate {mid} disagrees with raw rows")
                    elif not finite(observed) or abs(float(observed) - float(expected)) > 0.00011:
                        problem(f"{label} aggregate {mid} disagrees with raw rows")
            except (KeyError, TypeError, ValueError, ZeroDivisionError, OverflowError) as exc:
                problem(f"{label} aggregates cannot be reconciled with raw rows ({type(exc).__name__})")

    pr_rows = pr.get("rows", []) if isinstance(pr, dict) else []
    base_rows = base.get("rows", []) if isinstance(base, dict) else []
    def row_keys(rows: list) -> set[tuple[object, object]]:
        result = set()
        for r in rows:
            if not isinstance(r, dict) or "item_id" not in r or "seed" not in r:
                continue
            try:
                result.add((r["item_id"], r["seed"]))
            except TypeError:
                problem("row item_id/seed is not hashable")
        return result
    if row_keys(pr_rows) != row_keys(base_rows):
        problem("PR (item_id, seed) rows differ from baseline")
    def item_slices(rows: list) -> dict[object, tuple[str, ...]]:
        result: dict[object, tuple[str, ...]] = {}
        for row in rows:
            if not isinstance(row, dict) or "item_id" not in row:
                continue
            if not isinstance(row["item_id"], str):
                problem("row item_id is invalid for slice tags")
                continue
            tags = row.get("slices") or []
            if not isinstance(tags, list) or any(not isinstance(tag, str) for tag in tags):
                problem("row has invalid slice tags")
                continue
            normalized = tuple(sorted(set(tags)))
            previous = result.setdefault(row["item_id"], normalized)
            if previous != normalized:
                problem(f"slice tags vary across rows for item {row['item_id']}")
        return result
    if item_slices(pr_rows) != item_slices(base_rows):
        problem("PR item slice tags differ from baseline")

    if base_spec and spec.get("eval_set_version") == base_spec.get("eval_set_version"):
        def by_id(entries: list, key: str) -> dict[object, dict]:
            return {(entry[key], entry.get("metric")) if key == "name" else entry[key]: entry
                    for entry in entries if isinstance(entry, dict) and isinstance(entry.get(key), str)}
        new_metrics = by_id(spec.get("metrics", []), "id")
        old_metrics = by_id(base_spec.get("metrics", []), "id")
        for mid, old in old_metrics.items():
            new = new_metrics.get(mid)
            if new is None:
                problem(f"ratchet removed metric {mid}")
                continue
            old_th, new_th = old.get("threshold", {}), new.get("threshold", {})
            for bound in ("max", "min", "max_increase"):
                if bound in old_th and (bound not in new_th or
                        (bound in new_th and ((bound == "min" and new_th[bound] < old_th[bound]) or
                                              (bound != "min" and new_th[bound] > old_th[bound])))):
                    problem(f"ratchet loosened {mid}.{bound}")
            if old.get("blocking") and not new.get("blocking"):
                problem(f"ratchet made metric {mid} non-blocking")
            if old_th.get("no_significant_drop") and not new_th.get("no_significant_drop"):
                problem(f"ratchet removed {mid}.no_significant_drop")
        new_slices = by_id(spec.get("slices", []), "name")
        old_slices = by_id(base_spec.get("slices", []), "name")
        for slice_key, old in old_slices.items():
            name = slice_key[0]
            new = new_slices.get(slice_key)
            if new is None:
                problem(f"ratchet removed slice {name}/{slice_key[1]}")
                continue
            if "min" in old and ("min" not in new or new["min"] < old["min"]):
                problem(f"ratchet lowered slice {name}.min")
            if "max" in old and ("max" not in new or new["max"] > old["max"]):
                problem(f"ratchet raised slice {name}.max")
            if old.get("blocking") and not new.get("blocking"):
                problem(f"ratchet made slice {name} non-blocking")
            if old.get("no_significant_drop") and not new.get("no_significant_drop"):
                problem(f"ratchet removed slice {name}.no_significant_drop")
    return problems


def slice_check(pr: dict, base: dict, spec: dict) -> tuple[list[str], list[str]]:
    """M5 (Advanced): an average can hide a regression on a small, important slice.
    For each entry of spec["slices"] ({"name", "metric", "min"?, "no_significant_drop"?, "blocking"}):
      - value = mean of per_item(pr, metric, slice_name=name)
      - fail if below "min", or if no_significant_drop and the paired CI over the slice's items
        lies entirely below 0
    Return (blocked ids like "slice:money_movement/pass_rate", report lines)."""
    # TODO M5
    blocked, lines = [], []
    bs = spec.get("bootstrap", {})
    for entry in spec.get("slices", []):
        name, metric = entry["name"], entry["metric"]
        p, b = per_item(pr, metric, slice_name=name), per_item(base, metric, slice_name=name)
        value = sum(p.values()) / len(p) if p else None
        verdict, note = "ok", ""
        if value is None:
            verdict = "missing"
        elif "min" in entry and value < entry["min"]:
            verdict = "fail"
        elif "max" in entry and value > entry["max"]:
            verdict = "fail"
        if entry.get("no_significant_drop"):
            keys = sorted(set(p) & set(b))
            if keys:
                d, lo, hi = stats.paired_bootstrap([p[k] for k in keys], [b[k] for k in keys],
                                                   n_resamples=bs.get("n_resamples", 1000),
                                                   rng=bs.get("rng", 2027),
                                                   confidence=bs.get("confidence", 0.95))
                note = f"Δ {d:+.3f} CI [{lo:+.3f}, {hi:+.3f}]"
                if hi < 0:
                    verdict = "fail"
            else:
                verdict = "missing"
                note = "no paired slice items"
        if verdict != "ok" and entry.get("blocking"):
            blocked.append(f"slice:{name}/{metric}")
        label = "ok" if verdict == "ok" else "MISSING" if verdict == "missing" else "BLOCK" if entry.get("blocking") else "warn"
        lines.append(f"  slice:{name}/{metric:<15} {value!s:<8} {json.dumps(entry):<40} {note:<28} {label}")
    return blocked, lines


def check(pr: dict, base: dict, spec: dict, base_spec: dict | None = None) -> tuple[list[str], list[str]]:
    problems = integrity_check(pr, base, spec, base_spec)
    if problems:
        return ["integrity"], [f"  INTEGRITY {p}" for p in problems]
    if pr["manifest"]["eval_set_sha"] != base["manifest"]["eval_set_sha"]:
        return ["eval_set_sha"], ["  EVAL SET differs from the baseline's: re-run the baseline on the same eval set"]
    blocked, lines = [], []
    bs = spec.get("bootstrap", {})
    for m in spec["metrics"]:
        mid, th, val = m["id"], m.get("threshold", {}), pr["metrics"].get(m["id"])
        verdict, note = "ok", ""
        if val is None:
            verdict = "missing"
        elif "max" in th and val > th["max"]:
            verdict = "fail"
        elif "min" in th and val < th["min"]:
            verdict = "fail"
        elif "max_increase" in th and base["metrics"].get(mid) is not None:
            base_value = base["metrics"][mid]
            if val > base_value * (1 + th["max_increase"]):
                verdict = "fail"
        if th.get("no_significant_drop") and val is not None:
            a, b = per_item(pr, mid), per_item(base, mid)
            keys = sorted(set(a) & set(b))
            if not keys:
                verdict = "missing"
                note = "no paired items"
            else:
                d, lo, hi = stats.paired_bootstrap([a[k] for k in keys], [b[k] for k in keys],
                                                   n_resamples=bs.get("n_resamples", 1000), rng=bs.get("rng", 2027),
                                                   confidence=bs.get("confidence", 0.95))
                note = f"Δ {d:+.3f} CI [{lo:+.3f}, {hi:+.3f}]"
                if hi < 0:
                    verdict = "fail"
        if verdict != "ok" and m.get("blocking"):
            blocked.append(mid)
        label = {"ok": "ok", "missing": "MISSING"}.get(verdict, "BLOCK" if m.get("blocking") else "warn")
        lines.append(f"  {mid:<22} {val!s:<8} {json.dumps(th):<40} {note:<28} {label}")
    if spec.get("slices"):
        sb, sl = slice_check(pr, base, spec)
        blocked += sb
        lines += sl
    return blocked, lines


def main(argv: list[str] | None = None) -> int:
    utf8_stdio()
    ap = argparse.ArgumentParser(prog="lab9.gate")
    ap.add_argument("--pr", required=True)
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--spec", default=str(SPEC))
    ap.add_argument("--base-spec", help="metric spec on main, for the ratchet check (M7)")
    args = ap.parse_args(argv)
    try:
        pr = json.loads(Path(args.pr).read_text(encoding="utf-8"))
        base = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
        spec = load_spec(Path(args.spec))
        base_spec = load_spec(Path(args.base_spec)) if args.base_spec else None
    except Exception as exc:
        print(f"  INTEGRITY could not load gate input: {exc}")
        print("exit 1 — blocked: integrity")
        return 1
    if not isinstance(pr, dict) or not isinstance(base, dict):
        print("  INTEGRITY report root must be an object")
        print("exit 1 — blocked: integrity")
        return 1
    blocked, lines = check(pr, base, spec, base_spec)
    run_id = pr.get("run_id", "unknown")
    base_run_id = base.get("run_id", "unknown")
    manifest = pr.get("manifest") if isinstance(pr.get("manifest"), dict) else {}
    print(f"gate: PR {run_id} vs main {base_run_id} · eval set {manifest.get('eval_set_sha', 'unknown')}")
    print("\n".join(lines))
    if blocked:
        print(f"exit 1 — blocked: {', '.join(blocked)}")
        return 1
    print("exit 0 — merge")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
