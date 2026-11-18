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
from lab9.graders import GRADERS


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
    pm, bm = pr.get("manifest") or {}, base.get("manifest") or {}
    rows, brows = pr.get("rows") or [], base.get("rows") or []

    # 1. Metric values must be real numbers (NaN < min is False, so a naive gate passes NaN).
    for name, rep in (("PR", pr), ("baseline", base)):
        for k, v in (rep.get("metrics") or {}).items():
            if not _finite_or_none(v):
                problems.append(f"{name} metric {k} = {v!r} is not a finite number")

    # 2. Graders must have run on every row: a crash is not a pass and not "missing".
    for name, rep in (("PR", pr), ("baseline", base)):
        fails = rep.get("evaluator_failures")
        if fails:
            problems.append(f"{name} has {len(fails)} evaluator failure(s), first: {str(fails[0])[:80]}")
    graded = [m["id"] for m in spec.get("metrics", []) if m["id"] in GRADERS]
    graded += [sl["metric"] for sl in spec.get("slices") or [] if sl.get("metric") in GRADERS]
    graded = list(dict.fromkeys(graded))
    for name, rr in (("PR", rows), ("baseline", brows)):
        bad: dict[str, int] = {}
        for r in rr:
            for m in graded:
                if not isinstance(r.get(m), bool):        # None, NaN, a float, or the key gone
                    bad[m] = bad.get(m, 0) + 1
        problems += [f"{name}: {n} row(s) have no boolean value for graded metric {m}" for m, n in bad.items()]

    # 3. Row count and (item, seed) coverage: no dropped, duplicated or cherry-picked rows.
    if not rows:
        problems.append("PR report has no rows")
    want_rows = _int(pm.get("items")) * len(pm.get("seeds") or [])
    if len(rows) != want_rows:
        problems.append(f"PR has {len(rows)} rows, manifest says {pm.get('items')} items x "
                        f"{len(pm.get('seeds') or [])} seeds = {want_rows}")
    keys = [(r.get("item_id"), r.get("seed")) for r in rows]
    bkeys = [(r.get("item_id"), r.get("seed")) for r in brows]
    dup = len(keys) - len(set(keys))
    if dup:
        problems.append(f"PR has {dup} duplicated (item, seed) row(s)")
    if len(bkeys) != len(set(bkeys)):
        problems.append(f"baseline has {len(bkeys) - len(set(bkeys))} duplicated (item, seed) row(s)")
    if set(keys) != set(bkeys):
        miss, extra = set(bkeys) - set(keys), set(keys) - set(bkeys)
        problems.append(f"(item, seed) set differs from the baseline's: {len(miss)} missing, {len(extra)} extra"
                        + (f", e.g. missing {sorted(miss, key=str)[0]}" if miss else ""))
    if list(pm.get("seeds") or []) != list(bm.get("seeds") or []):
        problems.append(f"seeds {pm.get('seeds')} differ from the baseline's {bm.get('seeds')}")
    if pm.get("items") != bm.get("items"):
        problems.append(f"manifest items {pm.get('items')} differ from the baseline's {bm.get('items')}")
    n_items = len({k[0] for k in keys})
    if rows and n_items != _int(pm.get("items")):
        problems.append(f"rows cover {n_items} items, manifest says {pm.get('items')}")
    if pm.get("eval_set_sha") != bm.get("eval_set_sha"):
        problems.append("eval_set_sha differs from the baseline's")

    # 4. Reported metrics must be what the rows say (no hand-edited numbers).
    if rows and not problems:
        problems += _recheck_metrics(pr, spec)

    # 5. Slice tags are derived from labels; a PR may not move an item out of a slice.
    tags = _slices_by_item(rows)
    btags = _slices_by_item(brows)
    for item, t in tags.items():
        if len(t) > 1:
            problems.append(f"{item}: rows disagree on slice tags {sorted(map(sorted, t))}")
        if item in btags and t != btags[item]:
            problems.append(f"{item}: slice tags {sorted(map(sorted, t))} differ from the baseline's "
                            f"{sorted(map(sorted, btags[item]))}")

    # 6. Ratchet: on the same eval set, a spec may only get stricter.
    if base_spec is not None and (spec.get("eval_set_version") == base_spec.get("eval_set_version")
                                  or pm.get("eval_set_sha") == bm.get("eval_set_sha")):
        problems += ratchet_check(spec, base_spec)
    return problems


def _int(v) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return -1


def _finite_or_none(v) -> bool:
    if v is None or isinstance(v, bool):
        return True
    if isinstance(v, (int, float)):
        return math.isfinite(v)
    return False


def _slices_by_item(rows: list[dict]) -> dict[str, set[tuple[str, ...]]]:
    out: dict[str, set[tuple[str, ...]]] = {}
    for r in rows:
        out.setdefault(r.get("item_id"), set()).add(tuple(sorted(r.get("slices") or [])))
    return out


def _recheck_metrics(pr: dict, spec: dict) -> list[str]:
    ids = [m for m in GRADERS if all(m in r for r in pr["rows"])]
    has_cost = all(isinstance(r.get("cost"), (int, float)) for r in pr["rows"])
    rows = [r if has_cost else {**r, "cost": 0.0} for r in pr["rows"]]
    try:
        again = aggregate(rows, ids, k_values=spec.get("pass_k", []))
    except Exception as exc:                      # malformed rows: refuse, do not crash the gate
        return [f"cannot recompute metrics from rows: {exc!r}"]
    if not has_cost:
        again.pop("cost_per_success", None)
    out = []
    for k, v in again.items():
        got = pr["metrics"].get(k, "absent")
        if k not in pr["metrics"]:
            if any(m["id"] == k for m in spec.get("metrics", [])):
                out.append(f"metric {k} absent from the report but the spec grades it")
            continue
        if v is None or got is None:
            if v != got:
                out.append(f"metric {k} = {got!r}, rows give {v!r}")
        elif abs(float(got) - float(v)) > 1e-3:
            out.append(f"metric {k} = {got!r}, rows give {v!r} (hand-edited report?)")
    for m in spec.get("metrics", []):
        if m["id"] not in pr["metrics"] and m["id"] not in again:
            out.append(f"spec metric {m['id']} is absent from the report")
    return out


def _th_looser(where: str, new: dict, old: dict) -> list[str]:
    out = []
    for key in ("max", "max_increase"):
        if key in old and (key not in new or new[key] > old[key]):
            out.append(f"{where}: {key} {old[key]} -> {new.get(key, 'removed')} (looser)")
    if "min" in old and ("min" not in new or new["min"] < old["min"]):
        out.append(f"{where}: min {old['min']} -> {new.get('min', 'removed')} (looser)")
    if old.get("no_significant_drop") and not new.get("no_significant_drop"):
        out.append(f"{where}: no_significant_drop removed")
    return out


def ratchet_check(spec: dict, base_spec: dict) -> list[str]:
    """Same eval-set version: thresholds may only get stricter. Returns the loosenings found."""
    out = []
    new = {m["id"]: m for m in spec.get("metrics", [])}
    for m in base_spec.get("metrics", []):
        mid = m["id"]
        if mid not in new:
            out.append(f"ratchet: metric {mid} removed from the spec")
            continue
        if m.get("blocking") and not new[mid].get("blocking"):
            out.append(f"ratchet: metric {mid} no longer blocking")
        out += [f"ratchet: {x}" for x in _th_looser(f"metric {mid}", new[mid].get("threshold") or {},
                                                     m.get("threshold") or {})]
    key = lambda sl: (sl.get("name"), sl.get("metric"))
    new_sl = {key(sl): sl for sl in spec.get("slices") or []}
    for sl in base_spec.get("slices") or []:
        k = key(sl)
        where = f"slice {k[0]}/{k[1]}"
        if k not in new_sl:
            out.append(f"ratchet: {where} removed from the spec")
            continue
        if sl.get("blocking") and not new_sl[k].get("blocking"):
            out.append(f"ratchet: {where} no longer blocking")
        out += [f"ratchet: {x}" for x in _th_looser(where, new_sl[k], sl)]
    ob, nb = base_spec.get("bootstrap") or {}, spec.get("bootstrap") or {}
    if nb.get("n_resamples", 1000) < ob.get("n_resamples", 1000):
        out.append("ratchet: bootstrap n_resamples lowered")
    for k in ("rng", "confidence", "method"):
        if k in ob and nb.get(k) != ob.get(k):
            out.append(f"ratchet: bootstrap {k} changed {ob[k]!r} -> {nb.get(k)!r} (re-rolling the CI)")
    if list(spec.get("seeds") or []) != list(base_spec.get("seeds") or []):
        out.append(f"ratchet: seeds changed {base_spec.get('seeds')} -> {spec.get('seeds')}")
    if spec.get("eval_set") != base_spec.get("eval_set") or spec.get("labels") != base_spec.get("labels"):
        out.append("ratchet: eval_set/labels path changed on the same eval-set version")
    return out


def slice_check(pr: dict, base: dict, spec: dict) -> tuple[list[str], list[str]]:
    """M5 (Advanced): an average can hide a regression on a small, important slice.
    For each entry of spec["slices"] ({"name", "metric", "min"?, "no_significant_drop"?, "blocking"}):
      - value = mean of per_item(pr, metric, slice_name=name)
      - fail if below "min", or if no_significant_drop and the paired CI over the slice's items
        lies entirely below 0
    Return (blocked ids like "slice:money_movement/pass_rate", report lines)."""
    blocked: list[str] = []
    lines: list[str] = []
    bs = spec.get("bootstrap", {})
    for sl in spec.get("slices") or []:
        name, metric = sl["name"], sl["metric"]
        sid = f"slice:{name}/{metric}"
        a, b = per_item(pr, metric, slice_name=name), per_item(base, metric, slice_name=name)
        verdict, note, val = "ok", "", None
        if not a:
            verdict, note = "fail", "no PR rows carry this slice"
        else:
            val = round(sum(a.values()) / len(a), 4)
            if "min" in sl and val < sl["min"]:
                verdict = "fail"
            if "max" in sl and val > sl["max"]:
                verdict = "fail"
            if sl.get("no_significant_drop"):
                keys = sorted(set(a) & set(b))
                if keys:
                    d, lo, hi = stats.paired_bootstrap([a[k] for k in keys], [b[k] for k in keys],
                                                       n_resamples=bs.get("n_resamples", 1000),
                                                       rng=bs.get("rng", 2027))
                    note = f"Δ {d:+.3f} CI [{lo:+.3f}, {hi:+.3f}] n={len(keys)}"
                    if hi < 0:
                        verdict = "fail"
                else:
                    verdict, note = "fail", "no items shared with the baseline"
        if verdict != "ok" and sl.get("blocking"):
            blocked.append(sid)
        label = "ok" if verdict == "ok" else ("BLOCK" if sl.get("blocking") else "warn")
        th = {k: sl[k] for k in ("min", "max", "no_significant_drop") if k in sl}
        lines.append(f"  {sid:<34} {val!s:<8} {json.dumps(th):<40} {note:<28} {label}")
    return blocked, lines


def check(pr: dict, base: dict, spec: dict, base_spec: dict | None = None) -> tuple[list[str], list[str]]:
    if pr["manifest"]["eval_set_sha"] != base["manifest"]["eval_set_sha"]:
        return ["eval_set_sha"], ["  EVAL SET differs from the baseline's: re-run the baseline on the same eval set"]
    problems = integrity_check(pr, base, spec, base_spec)
    if problems:
        return ["integrity"], [f"  INTEGRITY {p}" for p in problems]
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
        elif "max_increase" in th and base["metrics"].get(mid):
            if val > base["metrics"][mid] * (1 + th["max_increase"]):
                verdict = "fail"
        if th.get("no_significant_drop") and val is not None:
            a, b = per_item(pr, mid), per_item(base, mid)
            keys = sorted(set(a) & set(b))
            d, lo, hi = stats.paired_bootstrap([a[k] for k in keys], [b[k] for k in keys],
                                               n_resamples=bs.get("n_resamples", 1000), rng=bs.get("rng", 2027))
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
    pr = json.loads(Path(args.pr).read_text(encoding="utf-8"))
    base = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
    base_spec = load_spec(Path(args.base_spec)) if args.base_spec else None
    blocked, lines = check(pr, base, load_spec(Path(args.spec)), base_spec)
    print(f"gate: PR {pr['run_id']} vs main {base['run_id']} · eval set {pr['manifest']['eval_set_sha']}")
    print("\n".join(lines))
    if blocked:
        print(f"exit 1 — blocked: {', '.join(blocked)}")
        return 1
    print("exit 0 — merge")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
