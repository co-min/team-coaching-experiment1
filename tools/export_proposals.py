"""
export_proposals.py
-------------------
OFFLINE export of the proposed counterfactual probe configurations (not imported by the task).
Writes the six proposals (P1-P4, E-a, E-b; 12 probes each) with their ranking metrics, mapped
to the repo's candidate IDs (cf001-cf148).

    python -m tools.export_proposals                 # → docs/counterfactual/
    python -m tools.export_proposals --out some/dir

Inputs (all inside the repository)
    docs/counterfactual/source/candidates_artifact_data.json
        Data embedded in the *Counterfactual Probe Candidates* artifact
        (claude.ai/artifact/6GWy6wtFVfkGyaVvoU8v7a), saved verbatim on 2026-11-25:
        artifact probe IDs (C01-C44, S13-S48), their metrics, and the ranked P1-P4 sets.
    E_A / E_B below
        Transcribed from section 3 of the *Counterfactual Probe Reassessment* artifact
        (claude.ai/artifact/L48PaNghMKbVu6HpuxSPm7).
    stimulus tables (via tools.analyze_counterfactuals)
        The cf candidate table and the 12-slot schedule are rebuilt in process, so the gitignored
        data/analysis/counterfactual/ CSVs are not needed.

Output
    proposed_combinations.csv      72 rows: 6 configurations × 12 probe slots
    selected_configuration_p1.csv  the 12 P1 rows, same columns

Checks
    The artifact's attribute values equal the stimulus tables; every P1-P4 probe reproduces the
    artifact's Kendall distance, footrule and revised gaps; P1 matches the selection notes.

"P1" is a configuration ID (proposal 1, distance-matched). It is unrelated to phase_1.
"""

import argparse
import csv
import json
from collections import Counter
from itertools import combinations
from pathlib import Path
from typing import Dict, List, Sequence

from config.paths import ROOT_DIR
from recording.stimuli_loader import load_stimuli
from tools.analyze_counterfactuals import analyze, exact_attributes, schedule_schema

DOCS_DIR = ROOT_DIR / "docs" / "counterfactual"
SOURCE_JSON = DOCS_DIR / "source" / "candidates_artifact_data.json"

ROLES = "ABCD"
TEAMS = [a + "+" + b for a, b in combinations(ROLES, 2)]
NEAR = 0.5   # adjacent revised gap below this counts as a near-tie (provisional cut-off)

P_NAMES = {"P1_distance_matched": ("P1", "Distance-matched"), "P2_fewer_extremes": ("P2", "Fewest extremes"),
           "P3_distinct_targets": ("P3", "Distinct targets"), "P4_mixed_direction_blocks": ("P4", "Mixed direction")}
P_SOURCE = "Counterfactual Probe Candidates artifact (6GWy6wtFVfkGyaVvoU8v7a), rank-1 set"

# E-a / E-b: the Reassessment block table, in probe order. "X->v" = competence, "X+Y" = synergy.
E_SOURCE = "Counterfactual Probe Reassessment artifact (L48PaNghMKbVu6HpuxSPm7), section 3"
SYN_DIR = {"A+C": 0.8, "B+D": 0.8, "A+D": 1.4, "B+C": 1.4}   # High pairs go to Low, Low pairs to High
E_A = [(0, ["C->7.0", "A+C"]), (1, ["D->6.3", "A+D"]), (2, ["B+C", "B->8.2"]),
       (3, ["A+D", "D->2.2"]), (4, ["B+D", "B->2.3"]), (5, ["C->1.9", "A+C"])]
E_B = [(0, ["D->2.9", "A+C"]), (1, ["D->6.1", "A+C"]), (2, ["A+C", "B->6.7"]),
       (3, ["A+D", "D->2.2"]), (4, ["A+D", "D->6.3"]), (5, ["C->1.3", "B+C"])]


class Model:
    """Performance(i, j, d) = S(i, j) × (C_i(d) + C_j(d)), one change applied to the baseline."""

    def __init__(self, competence, synergy):
        self.comp, self.syn = competence, synergy

    def scores(self, domain, comp, syn):
        return {t: round(syn[t] * (comp[t[0]][domain] + comp[t[2]][domain]), 6) for t in TEAMS}

    def evaluate(self, domain, kind, target, new):
        comp = {r: dict(self.comp[r]) for r in ROLES}
        syn = dict(self.syn)
        if kind == "competence":
            comp[target][domain] = new
        else:
            syn[target] = new
        base, rev = self.scores(domain, self.comp, self.syn), self.scores(domain, comp, syn)
        bo, ro = _order(base), _order(rev)
        vals = sorted(rev.values(), reverse=True)
        gaps = [round(vals[i] - vals[i + 1], 4) for i in range(5)]
        br, rr = {t: i + 1 for i, t in enumerate(bo)}, {t: i + 1 for i, t in enumerate(ro)}
        kendall = sum((br[a] - br[b]) * (rr[a] - rr[b]) < 0 for a, b in combinations(TEAMS, 2))
        affected = [t for t in TEAMS if rev[t] != base[t]]
        return dict(base=base, rev=rev, bo=bo, ro=ro, gaps=gaps, kendall=kendall,
                    footrule=sum(abs(br[t] - rr[t]) for t in TEAMS), affected=affected,
                    to_first=[t for t in affected if rr[t] == 1 and br[t] != 1],
                    to_last=[t for t in affected if rr[t] == 6 and br[t] != 6], tie=min(gaps) == 0)

    def grid_robustness(self, domain, target, new_level):
        """Reassessment grid: Low 1.0-3.0, High 6.1-9.0, 0.1 steps; exact ties excluded."""
        lo, hi = (10, 30) if new_level == "low" else (61, 90)
        rankings = Counter()
        for k in range(lo, hi + 1):
            e = self.evaluate(domain, "competence", target, k / 10)
            if not e["tie"]:
                rankings[">".join(e["ro"])] += 1
        n = sum(rankings.values())
        return len(rankings), round(max(rankings.values()) / n, 2)


def _order(sc):
    return sorted(TEAMS, key=lambda t: -sc[t])


def _level(kind, v):
    if kind == "synergy":
        return {0.8: "low", 1.0: "mid", 1.4: "high"}[v]
    return "low" if v <= 3.0 else "mid" if v <= 6.0 else "high"


def _check_tables(data) -> None:
    """The artifact must have been computed on the current stimulus tables."""
    attrs = exact_attributes()
    comp = {r: {d: float(v) for d, v in ds.items()} for r, ds in attrs.competence.items()}
    syn = {"+".join(p): float(v) for p, v in attrs.synergy.items()}
    if comp != data["competence"] or syn != data["synergy"]:
        raise SystemExit("artifact attribute values differ from the stimulus tables")


def _e_blocks(spec):
    out = []
    for blk, items in spec:
        probes = []
        for it in items:
            if "+" in it:
                probes.append(("synergy", it, SYN_DIR[it], ""))
            else:
                r, v = it.split("->")
                probes.append(("competence", r, float(v), ""))
        out.append((blk, probes))
    return out


def configurations(data):
    """[(cfg_id, name, source, set_cost, [(block, [(kind, target, new, artifact_id)] in probe order)])]"""
    art = {c["id"]: c for c in data["candidates"]}
    configs = []
    for key, (cid, name) in P_NAMES.items():
        s = data["sets"][key][0]
        blocks = []
        for b in s["blocks"]:
            probes = []
            for kind in b["order"]:
                a = art[b["comp"] if kind == "competence" else b["syn"]]
                probes.append((kind, a["target"], a["new"], a["id"]))
            blocks.append((b["block"], probes))
        configs.append((cid, name, P_SOURCE, s["cost"], blocks))
    configs.append(("E-a", "No repeated role", E_SOURCE, "", _e_blocks(E_A)))
    configs.append(("E-b", "Repeats allowed", E_SOURCE, "", _e_blocks(E_B)))
    return configs


def build_rows(data) -> List[Dict[str, object]]:
    model = Model(data["competence"], data["synergy"])
    art = {c["id"]: c for c in data["candidates"]}
    stim = load_stimuli()
    cf_rows, _ = analyze(exact_attributes(), stim)
    sched = {(r["block_id"], r["probe_pos"]): r for r in schedule_schema(cf_rows)}
    block_meta = {b["block"]: b for b in data["blocks"]}

    def cf_lookup(domain, kind, target, old, new):
        m = [r for r in cf_rows if r["ranking_domain"] == domain and r["change_kind"] == kind
             and r["target_roles"] == target and r["original_value"] == old and r["new_value"] == new]
        return m[0] if m else None

    rows = []
    for cid, name, src, cost, blocks in configurations(data):
        for blk, probes in blocks:
            meta = block_meta[blk]
            domain = meta["domain"]
            evals = [model.evaluate(domain, k, t, v) for k, t, v, _ in probes]
            ks = [e["kendall"] for e in evals]
            gap_mm = round(sum(abs(a - b) for a, b in zip(evals[0]["gaps"], evals[1]["gaps"])) / 5, 3)
            for pos, ((kind, target, new, art_id), e) in enumerate(zip(probes, evals), start=1):
                old = model.comp[target][domain] if kind == "competence" else model.syn[target]
                ol, nl = _level(kind, old), _level(kind, new)
                # Cross-check against the artifact's own numbers
                if art_id:
                    a = art[art_id]
                    assert (a["kendall"], a["footrule"], a["old"]) == (e["kendall"], e["footrule"], old), art_id
                    assert all(abs(x - y) < 1e-6 for x, y in zip(a["gaps"], e["gaps"])), art_id
                cf = cf_lookup(domain, kind, target, old, new)
                if kind == "competence":
                    n_rank, modal = model.grid_robustness(domain, target, nl)
                else:
                    n_rank, modal = 1, 1.0
                sch = sched[(blk, pos)]
                assert sch["change_kind"] == kind and sch["ranking_domain"] == domain and sch["phase"] == meta["phase"]
                near = [f"g{i+1}={g:.2f}" for i, g in enumerate(e["gaps"]) if g < NEAR]
                mean = sum(e["gaps"]) / 5
                cv = round((sum((g - mean) ** 2 for g in e["gaps"]) / 5) ** 0.5 / mean, 3)
                rows.append({
                    "config_id": cid, "config_name": name, "config_source": src, "config_set_cost": cost,
                    "slot_id": sch["slot_id"], "block_id": blk, "phase": meta["phase"],
                    "visible_attribute": sch["visible_attribute"], "domain": domain, "probe_pos": pos,
                    "probe_type": kind.capitalize(), "changes_visible_attribute": sch["changes_visible_attribute"],
                    "candidate_id": cf["candidate_id"] if cf else "MISSING",
                    "candidate_id_status": "matched" if cf else "not in cf001-cf148 (value outside enumerated set)",
                    "artifact_probe_id": art_id or "n/a",
                    "target": target, "direction": f"{ol[0].upper()}->{nl[0].upper()}",
                    "original_level": ol, "original_value": old, "cf_level": nl, "cf_value": new,
                    "kendall_distance": e["kendall"], "footrule": e["footrule"],
                    "block_partner_kendall": ks[2 - pos], "block_kendall_abs_diff": abs(ks[0] - ks[1]),
                    "baseline_ranking": ">".join(e["bo"]), "revised_ranking": ">".join(e["ro"]),
                    "affected_teams": "|".join(e["affected"]),
                    "affected_baseline_scores": "|".join(f"{e['base'][t]:g}" for t in e["affected"]),
                    "affected_revised_scores": "|".join(f"{e['rev'][t]:g}" for t in e["affected"]),
                    "revised_gaps_g1_g5": " ".join(f"{g:.2f}" for g in e["gaps"]),
                    "min_adjacent_gap_revised": f"{min(e['gaps']):.2f}", "gap_cv": cv,
                    "block_gap_mismatch": gap_mm,
                    "min_reversal_margin": cf["min_reversal_margin"] if cf else "",
                    "baseline_top": e["bo"][0], "revised_top": e["ro"][0], "top_changed": int(e["bo"][0] != e["ro"][0]),
                    "affected_moved_to_first": "|".join(e["to_first"]), "affected_moved_to_last": "|".join(e["to_last"]),
                    "near_tie_lt_0.5": int(bool(near)), "near_tie_gaps": " ".join(near),
                    "n_rankings_in_level_observed_csv_range": cf["n_rankings_in_level_observed"] if cf else "",
                    "n_rankings_in_level_grid": n_rank, "modal_ranking_share_grid": modal,
                    "value_dependent_grid": int(n_rank > 1),
                })
    return rows


def _check_p1(p1: Sequence[Dict[str, object]]) -> None:
    """P1 must reproduce the figures in p1_selection_notes.md."""
    assert len(p1) == 12 and all(r["candidate_id"] != "MISSING" for r in p1)
    assert [r["block_kendall_abs_diff"] for r in p1[::2]] == [0, 2, 0, 0, 2, 0]
    assert sum(r["near_tie_lt_0.5"] for r in p1) == 6
    assert sum(r["value_dependent_grid"] for r in p1) == 4


def _write(path: Path, rows: Sequence[Dict[str, object]]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(f"  {path}  ({len(rows)} rows)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--out', type=Path, default=DOCS_DIR)
    args = parser.parse_args()

    with open(SOURCE_JSON, encoding="utf-8") as f:
        data = json.load(f)
    _check_tables(data)
    rows = build_rows(data)
    p1 = [r for r in rows if r["config_id"] == "P1"]
    _check_p1(p1)

    args.out.mkdir(parents=True, exist_ok=True)
    print("Written:")
    _write(args.out / "proposed_combinations.csv", rows)
    _write(args.out / "selected_configuration_p1.csv", p1)


if __name__ == '__main__':
    main()
