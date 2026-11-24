"""
analyze_counterfactuals.py
--------------------------
OFFLINE analysis of every possible counterfactual probe (not imported by the task).
Reads only the original stimulus tables and writes candidate tables for review;
it does not choose the final 12 probes.

    python -m tools.analyze_counterfactuals                    # → data/analysis/counterfactual/
    python -m tools.analyze_counterfactuals --out some/dir

Output
    counterfactual_candidates.csv    one row per candidate change
    counterfactual_rank_details.csv  six rows (teams) per candidate
    counterfactual_schedule.csv      proposed 12-slot schema, candidate columns left empty
    counterfactual_summary.csv       candidate counts by value rule × domain × kind × change size

Ground truth
    Performance(i, j, d) = S(i, j) × (C_i(d) + C_j(d)) on the exact table values
    (parsed as fractions, so ties are exact). The mapped 10–60 feedback scores
    (recording.stimuli_loader.compute_scores) and the integer competence levels in
    StimulusSet.competence are not used. Each change is applied on its own to the
    original attributes (Attributes.with_change), as in the shared-baseline design:
    both probes of a block are compared with the same baseline.

Candidates
    competence : one animal's competence in the ranking domain → another level
                 (a change within the same level is not shown to participants, so it
                 is not a candidate). Value rules, see COMPETENCE_VALUE_RULES.
    synergy    : one pair's synergy → another of the table's three values. Synergy does
                 not depend on the domain, so each change is evaluated in every domain.
    Animal groups share role-code profiles, so candidates are listed per role code and
    ranking domain; they apply to every block with that domain.

Levels come from the task's own rules (StimulusSet.competence_level / synergy_level).
"""

import argparse
import csv
import itertools
from collections import Counter
from fractions import Fraction
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

from config import settings as S
from config.paths import COMPETENCE_CSV, DATA_DIR, SYNERGY_CSV
from config.ranking import PERFORMANCE_RANKING_DOMAINS, PROBE_ORDERS
from recording.stimuli_loader import LEVELS, load_stimuli
from task.ranking.items import Attributes, Change, load_attributes

DEFAULT_OUT = DATA_DIR / "analysis" / "counterfactual"

# Design ranges of the competence levels (StimulusSet.competence_level docstring).
# The task only classifies values; which value represents a hypothetical level is
# not defined yet, so the candidates are listed under each proposed rule below.
COMPETENCE_LEVEL_RANGES = {
    'low':  (Fraction('1.0'), Fraction('3.0')),
    'mid':  (Fraction('3.5'), Fraction('6.0')),
    'high': (Fraction('6.5'), Fraction('9.0')),
}
COMPETENCE_VALUE_RULES = {
    'domain':   "a value another animal already has at that level in the same domain",
    'table':    "any value at that level anywhere in competence_d3.csv",
    'midpoint': "the midpoint of the level's design range",
}

# Change size by Kendall distance (proposed labels, only used for the summary).
CHANGE_SIZES = ((0, 'none'), (1, 'one_swap'), (3, 'moderate'), (15, 'large'))


# ── exact stimulus values ─────────────────────────────────────────────────────

def _rows(path: Path) -> List[Dict[str, str]]:
    with open(path, newline='', encoding='utf-8') as f:
        return [{k.strip(): v.strip() for k, v in row.items()} for row in csv.DictReader(f, skipinitialspace=True)]


def exact_attributes() -> Attributes:
    """Attributes with every value as a Fraction of its CSV text (8.5 → 17/2)."""
    competence: Dict[str, Dict[str, Fraction]] = {}
    for row in _rows(COMPETENCE_CSV):
        competence.setdefault(row['char_ani'], {d: Fraction(row[d]) for d in S.DOMAINS})
    synergy = {tuple(sorted((r['char1'], r['char2']))): Fraction(r['synergy_score']) for r in _rows(SYNERGY_CSV)}
    return Attributes(competence, synergy)


def _num(value: Fraction) -> float:
    return round(float(value), 4)


# ── rankings ──────────────────────────────────────────────────────────────────

def team_keys(attrs: Attributes) -> List[Tuple[str, str]]:
    return list(itertools.combinations(sorted(attrs.competence), 2))


def performances(attrs: Attributes, domain: str) -> Dict[Tuple[str, str], Fraction]:
    return {team: attrs.performance(team, domain) for team in team_keys(attrs)}


def ranks(perf: Dict[Tuple[str, str], Fraction]) -> Dict[Tuple[str, str], float]:
    """1 = best; tied teams share the average rank."""
    out = {}
    for team, value in perf.items():
        higher = sum(1 for v in perf.values() if v > value)
        equal = sum(1 for v in perf.values() if v == value)
        out[team] = higher + (equal + 1) / 2
    return out


def ranking_text(perf: Dict[Tuple[str, str], Fraction]) -> str:
    """'B+D>A+C>…', with '=' between tied teams."""
    ordered = sorted(perf, key=lambda t: (-perf[t], t))
    text = '+'.join(ordered[0])
    for prev, team in zip(ordered, ordered[1:]):
        text += ('=' if perf[team] == perf[prev] else '>') + '+'.join(team)
    return text


def compare(base: Dict, revised: Dict) -> Dict[str, object]:
    """Pairwise comparison of two team-score tables.

    kendall_distance    : pairs whose strict order is reversed
    min_reversal_margin : smallest revised score gap among reversed pairs
                          (how clearly the reversal holds; empty if none)
    n_new_ties          : pairs strictly ordered in the baseline but tied after the change
    """
    reversed_gaps, new_ties = [], 0
    for t1, t2 in itertools.combinations(base, 2):
        before, after = base[t1] - base[t2], revised[t1] - revised[t2]
        if before * after < 0:
            reversed_gaps.append(abs(after))
        elif before != 0 and after == 0:
            new_ties += 1
    values = sorted(revised.values(), reverse=True)
    return {
        'kendall_distance': len(reversed_gaps),
        'min_reversal_margin': _num(min(reversed_gaps)) if reversed_gaps else '',
        'n_new_ties': new_ties,
        'min_adjacent_gap_revised': _num(min(a - b for a, b in zip(values, values[1:]))),
    }


def change_size(kendall: int) -> str:
    for upper, label in CHANGE_SIZES:
        if kendall <= upper:
            return label
    return CHANGE_SIZES[-1][1]


# ── competence value rules and level robustness ───────────────────────────────

def competence_values_by_rule(attrs: Attributes, stim, domain: str, role: str, level: str) -> Dict[Fraction, List[str]]:
    """{candidate value: [rules that propose it]} for changing role's competence in domain to level."""
    proposals: Dict[Fraction, List[str]] = {}

    def add(value, rule):
        if rule not in proposals.setdefault(value, []):
            proposals[value].append(rule)

    for other, by_domain in attrs.competence.items():
        if other != role and stim.competence_level(float(by_domain[domain])) == level:
            add(by_domain[domain], 'domain')
    for by_domain in attrs.competence.values():
        for value in by_domain.values():
            if stim.competence_level(float(value)) == level:
                add(value, 'table')
    lo, hi = COMPETENCE_LEVEL_RANGES[level]
    add((lo + hi) / 2, 'midpoint')
    return dict(sorted(proposals.items()))


def observed_level_ranges(attrs: Attributes, stim) -> Dict[str, Tuple[Fraction, Fraction]]:
    """{level: (lowest, highest) value at that level anywhere in competence_d3.csv}."""
    by_level: Dict[str, List[Fraction]] = {}
    for by_domain in attrs.competence.values():
        for value in by_domain.values():
            by_level.setdefault(stim.competence_level(float(value)), []).append(value)
    return {level: (min(v), max(v)) for level, v in by_level.items()}


def level_breakpoints(attrs: Attributes, domain: str, role: str,
                      lo: Fraction, hi: Fraction) -> Tuple[List[Fraction], int]:
    """Values in [lo, hi] where two teams tie, and how many distinct strict rankings
    that range produces. Participants only see the level, so one ranking (no
    breakpoints) means the correct answer does not depend on the value chosen."""
    # Each team score is linear in the changed value: slope × x + intercept
    lines = {}
    for team in team_keys(attrs):
        syn = attrs.synergy[team]
        if role in team:
            other = team[1] if team[0] == role else team[0]
            lines[team] = (syn, syn * attrs.competence[other][domain])
        else:
            lines[team] = (Fraction(0), attrs.performance(team, domain))
    points = set()
    for (a1, b1), (a2, b2) in itertools.combinations(lines.values(), 2):
        if a1 != a2:
            x = (b2 - b1) / (a1 - a2)
            if lo <= x <= hi:
                points.add(x)
    points = sorted(points)
    probes = [lo, hi] + points + [(p + q) / 2 for p, q in zip([lo] + points, points + [hi])]
    orderings = set()
    for x in probes:
        perf = {t: a * x + b for t, (a, b) in lines.items()}
        if len(set(perf.values())) == len(perf):          # strict orderings only
            orderings.add(ranking_text(perf))
    return points, len(orderings)


# ── enumeration ───────────────────────────────────────────────────────────────

def enumerate_changes(attrs: Attributes, stim):
    """Yields (domain, Change, original value, value rules, level robustness or None).

    level robustness: {'design': (breakpoints, n rankings), 'observed': (…)} over the
    level's design range and over the range of values the table uses at that level.
    """
    observed = observed_level_ranges(attrs, stim)
    for domain in S.DOMAINS:
        for role in sorted(attrs.competence):
            original = attrs.competence[role][domain]
            original_level = stim.competence_level(float(original))
            for level in LEVELS:
                if level == original_level:
                    continue
                breakpoints = {
                    'design': level_breakpoints(attrs, domain, role, *COMPETENCE_LEVEL_RANGES[level]),
                    'observed': level_breakpoints(attrs, domain, role, *observed[level]),
                }
                for value, rules in competence_values_by_rule(attrs, stim, domain, role, level).items():
                    yield domain, Change('competence', (role,), value, domain=domain), original, rules, breakpoints
        for pair in sorted(attrs.synergy):
            original = attrs.synergy[pair]
            for value in sorted(set(attrs.synergy.values())):
                if value != original:
                    yield domain, Change('synergy', pair, value), original, ['synergy_table'], None


def _level(stim, kind: str, value: Fraction) -> str:
    if kind == 'competence':
        return stim.competence_level(float(value))
    return stim.synergy_level(float(value))


def analyze(attrs: Attributes, stim):
    candidates, details = [], []
    baselines = {d: performances(attrs, d) for d in S.DOMAINS}
    for n, (domain, change, original, rules, breakpoints) in enumerate(enumerate_changes(attrs, stim), start=1):
        cid = f"cf{n:03d}"
        base = baselines[domain]
        revised = performances(attrs.with_change(change), domain)
        base_ranks, revised_ranks = ranks(base), ranks(revised)
        affected = [t for t in base if revised[t] != base[t]]
        base_top = [t for t in base if base_ranks[t] == min(base_ranks.values())]
        revised_top = [t for t in revised if revised_ranks[t] == min(revised_ranks.values())]
        old_level, new_level = _level(stim, change.kind, original), _level(stim, change.kind, change.value)
        step = LEVELS.index(new_level) - LEVELS.index(old_level)

        row = {
            'candidate_id': cid,
            'ranking_domain': domain,
            'change_kind': change.kind,
            'target_roles': '+'.join(change.roles),
            'original_value': _num(original),
            'original_level': old_level,
            'new_value': _num(change.value),
            'new_level': new_level,
            'level_step': f"{step:+d}",
            'value_rules': '|'.join(rules),
            'baseline_ranking': ranking_text(base),
            'revised_ranking': ranking_text(revised),
            **compare(base, revised),
            'n_affected_teams': len(affected),
            'affected_teams': '|'.join('+'.join(t) for t in affected),
            'n_teams_rank_changed': sum(1 for t in base if base_ranks[t] != revised_ranks[t]),
            'baseline_top': '|'.join('+'.join(t) for t in base_top),
            'revised_top': '|'.join('+'.join(t) for t in revised_top),
            'top_changed': int(base_top != revised_top),
        }
        for span in ('design', 'observed'):
            if breakpoints is None:       # synergy: the level is a single exact value
                points, n_rankings = [], 1
            else:
                points, n_rankings = breakpoints[span]
            row[f'level_breakpoints_{span}'] = '|'.join(str(_num(p)) for p in points)
            row[f'n_rankings_in_level_{span}'] = n_rankings
        row['change_size'] = change_size(row['kendall_distance'])
        candidates.append(row)

        for team in base:
            details.append({
                'candidate_id': cid,
                'ranking_domain': domain,
                'change_kind': change.kind,
                'team': '+'.join(team),
                'contains_target': int(bool(set(team) & set(change.roles)) if change.kind == 'competence'
                                       else tuple(team) == change.roles),
                'original_performance': _num(base[team]),
                'revised_performance': _num(revised[team]),
                'performance_delta': _num(revised[team] - base[team]),
                'score_changed': int(team in affected),
                'original_rank': base_ranks[team],
                'revised_rank': revised_ranks[team],
                'rank_shift': base_ranks[team] - revised_ranks[team],   # + = moved up
            })
    return candidates, details


# ── schedule schema and summary ───────────────────────────────────────────────

SCHEDULE_CANDIDATE_COLUMNS = ('candidate_id', 'target_roles', 'original_value', 'original_level', 'new_value',
                              'new_level', 'value_rules', 'kendall_distance', 'top_changed', 'min_reversal_margin',
                              'n_rankings_in_level_design', 'n_rankings_in_level_observed')


def schedule_schema(candidates) -> List[Dict[str, object]]:
    """12 slots (block × probe position) from the fixed domain and probe-order schedules.
    Candidate columns are left empty: the final choice is made after review."""
    rows = []
    for block_id, (domain, order) in enumerate(zip(PERFORMANCE_RANKING_DOMAINS, PROBE_ORDERS)):
        phase = S.BLOCK_PHASES[block_id]
        for probe_pos, kind in enumerate(order, start=1):
            row = {
                'slot_id': f"b{block_id}_probe{probe_pos}",
                'block_id': block_id,
                'phase': phase,
                'visible_attribute': 'competence' if phase == 'phase_1' else 'synergy',
                'ranking_domain': domain,
                'probe_pos': probe_pos,
                'change_kind': kind,
                'changes_visible_attribute': int((phase == 'phase_1') == (kind == 'competence')),
                **{f"presentation_pos_{g}": S.BLOCK_ORDERS[g].index(block_id) for g in sorted(S.BLOCK_ORDERS)},
                'n_eligible_candidates': sum(1 for c in candidates
                                             if c['ranking_domain'] == domain and c['change_kind'] == kind),
            }
            row.update({col: '' for col in SCHEDULE_CANDIDATE_COLUMNS})
            rows.append(row)
    return rows


def summary(candidates) -> List[Dict[str, object]]:
    """Counts per value rule × domain × kind × change size. Synergy candidates are in every rule."""
    rows = []
    for rule in COMPETENCE_VALUE_RULES:
        pool = [c for c in candidates
                if c['change_kind'] == 'synergy' or rule in c['value_rules'].split('|')]
        groups = Counter((c['ranking_domain'], c['change_kind'], c['change_size']) for c in pool)
        for (domain, kind, size), n in sorted(groups.items()):
            sub = [c for c in pool if (c['ranking_domain'], c['change_kind'], c['change_size']) == (domain, kind, size)]
            margins = [c['min_reversal_margin'] for c in sub if c['min_reversal_margin'] != '']
            rows.append({
                'value_rule': rule, 'ranking_domain': domain, 'change_kind': kind, 'change_size': size,
                'n_candidates': n,
                'n_top_changed': sum(c['top_changed'] for c in sub),
                'n_level_robust_design': sum(1 for c in sub if c['n_rankings_in_level_design'] == 1),
                'n_level_robust_observed': sum(1 for c in sub if c['n_rankings_in_level_observed'] == 1),
                'n_with_new_ties': sum(1 for c in sub if c['n_new_ties']),
                'min_reversal_margin_min': min(margins) if margins else '',
                'min_reversal_margin_max': max(margins) if margins else '',
            })
    return rows


def _write(path: Path, rows: Sequence[Dict[str, object]]) -> None:
    with open(path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(f"  {path}  ({len(rows)} rows)")


def _check_against_task(attrs: Attributes, stim) -> None:
    """The exact baseline must rank teams the same way as the task's float ground truth."""
    task_attrs = load_attributes(stim.synergy)
    for d in S.DOMAINS:
        exact = sorted(team_keys(attrs), key=lambda t: -attrs.performance(t, d))
        task = sorted(team_keys(attrs), key=lambda t: -task_attrs.performance(t, d))
        if exact != task:
            raise SystemExit(f"{d}: exact baseline {exact} differs from task ground truth {task}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--out', type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    stim = load_stimuli()
    attrs = exact_attributes()
    _check_against_task(attrs, stim)
    candidates, details = analyze(attrs, stim)

    args.out.mkdir(parents=True, exist_ok=True)
    print("Written:")
    _write(args.out / "counterfactual_candidates.csv", candidates)
    _write(args.out / "counterfactual_rank_details.csv", details)
    _write(args.out / "counterfactual_schedule.csv", schedule_schema(candidates))
    _write(args.out / "counterfactual_summary.csv", summary(candidates))


if __name__ == '__main__':
    main()
