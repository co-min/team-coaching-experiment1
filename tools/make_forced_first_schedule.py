"""
make_forced_first_schedule.py
-----------------------------
OFFLINE generator for stimuli/tables/forced_first_schedule.csv (not imported by the task).

    python -m tools.make_forced_first_schedule            # report on the committed CSV
    python -m tools.make_forced_first_schedule --write    # (re)generate it  (+ --force to overwrite)

The CSV is the single source of truth at runtime; this script only exists to
reproduce / audit it. Generation is deterministic (GENERATOR_SEED + exhaustive
search), and uses the task's own seeded domain schedule, so the CSV matches the
domain sequence every subject sees.

Design (positions = char codes A–D; 6 blocks × 15 trials, 5 trials per domain per block)
----------------------------------------------------------------------------------------
Every domain-in-block has 5 trials over 4 positions → each position once + one
"double". The 3 doubles of a block go to 3 distinct positions, the 4th position is
the block's "short" (3 assignments). All frequency targets then become counts of
shorts / doubles:

  block    3–4      ⇔ the 3 doubles of a block are distinct positions
  global   22–23    ⇔ each position is short in 1 or 2 blocks
  type     11–12    ⇔ shorts are distinct within each block type
  domain   7–8      ⇔ each (domain, position) is doubled in 1 or 2 blocks
  type×domain 3–4   ⇔ (extra) doubles distinct within each (type, domain)

Step 1 picks shorts/doubles satisfying all of the above (hard).
Step 2 orders each block's 15 trials by exhaustive search (hard: no immediate
repeat of a position; soft: spread over early/middle/late thirds, few A-x-A
patterns, forced animal's screen slot balanced).
"""

import argparse
import itertools
import random
import sys
from collections import Counter
from typing import Dict, List, Tuple

from config import settings as S
from config.paths import FORCED_FIRST_CSV
from recording.stimuli_loader import load_stimuli
from task.forced_first import (
    BLOCK_TYPE, balance_problems, read_schedule_csv, schedule_version,
    sync_problems, write_schedule_csv,
)
from task.schedule import generate_block_schedules

GENERATOR_SEED = 2026

SLOT_NAMES = ['up', 'down', 'right', 'left']


# ── step 1: shorts and doubles ────────────────────────────────────────────────

def _type_configs(positions, domains):
    """All (shorts, doubles) for the 3 blocks of one block type that satisfy the per-type rules."""
    out = []
    for shorts in itertools.permutations(positions, 3):              # distinct shorts in type
        per_block = [
            [dict(zip(domains, perm)) for perm in itertools.permutations([p for p in positions if p != s])]
            for s in shorts
        ]
        for doubles in itertools.product(*per_block):
            if all(len({dbl[d] for dbl in doubles}) == len(doubles) for d in domains):
                out.append((shorts, doubles))
    return out


def choose_shorts_and_doubles(positions, domains, block_types, rng):
    types = list(dict.fromkeys(block_types))
    assert len(types) == 2 and all(block_types.count(t) == 3 for t in types), "design assumption: 2 types × 3 blocks"
    configs = _type_configs(positions, domains)
    rng.shuffle(configs)

    def assemble(cfg_a, cfg_b):
        it = {types[0]: iter(zip(*cfg_a)), types[1]: iter(zip(*cfg_b))}
        return [next(it[t]) for t in block_types]          # [(short, doubles), ...] in block order

    best, best_cost = None, None
    for cfg_a in configs[:400]:
        for cfg_b in configs:
            blocks = assemble(cfg_a, cfg_b)
            shorts = Counter(s for s, _ in blocks)
            if not all(1 <= shorts[p] <= 2 for p in positions):
                continue
            dbl = Counter((d, dd[d]) for _, dd in blocks for d in domains)
            if not all(1 <= dbl[(d, p)] <= 2 for d in domains for p in positions):
                continue
            # soft: consecutive blocks should not share the short position
            cost = sum(a[0] == b[0] for a, b in zip(blocks, blocks[1:]))
            if best_cost is None or cost < best_cost:
                best, best_cost = blocks, cost
                if cost == 0:
                    return best
    if best is None:
        sys.exit("No shorts/doubles assignment satisfies the hard constraints.")
    return best


# ── step 2: within-block order ────────────────────────────────────────────────

def _order_cost(seq, slots):
    n = len(seq)
    thirds = [seq[i * n // 3:(i + 1) * n // 3] for i in range(3)]
    positions = set(seq)
    third_cost = sum((Counter(th)[p] - len(th) / len(positions)) ** 2 for th in thirds for p in positions)
    aba = sum(seq[i] == seq[i + 2] for i in range(n - 2))
    sc = Counter(slots)
    slot_cost = sum((sc[s] - n / 4) ** 2 for s in range(4))
    return third_cost + 0.25 * aba + 0.5 * slot_cost


def order_block(domain_seq, doubles, positions, slot_of):
    """Exhaustive DFS over position sequences; returns the minimum-cost one.

    slot_of[t][p] = screen slot index (0–3) of position p on trial t.
    """
    remaining = {d: Counter({p: 1 for p in positions}) for d in set(domain_seq)}
    for d, p in doubles.items():
        remaining[d][p] += 1

    best = {'cost': None, 'seq': None}
    seq: List[str] = []

    def dfs(t):
        if t == len(domain_seq):
            cost = _order_cost(seq, [slot_of[i][p] for i, p in enumerate(seq)])
            if best['cost'] is None or cost < best['cost'] - 1e-9:
                best['cost'], best['seq'] = cost, list(seq)
            return
        rem = remaining[domain_seq[t]]
        for p in positions:
            if rem[p] == 0 or (seq and seq[-1] == p):
                continue
            rem[p] -= 1
            seq.append(p)
            dfs(t + 1)
            seq.pop()
            rem[p] += 1

    dfs(0)
    if best['seq'] is None:
        sys.exit("No within-block order avoids immediate repeats.")
    return best['seq'], best['cost']


# ── build / report ────────────────────────────────────────────────────────────

def _task_context():
    stim = load_stimuli()
    schedules = generate_block_schedules(stim.animal_groups)
    code_to_animal = [{stim.char_code[a]: a for a in g} for g in stim.animal_groups]
    return stim, schedules, code_to_animal


def build_rows():
    stim, schedules, code_to_animal = _task_context()
    positions = sorted(set(stim.char_code.values()))
    block_types = [BLOCK_TYPE[p] for p in S.BLOCK_PHASES]
    rng = random.Random(GENERATOR_SEED)

    plan = choose_shorts_and_doubles(positions, S.DOMAINS, block_types, rng)
    rows = []
    for b, (block, (short, doubles)) in enumerate(zip(schedules, plan)):
        domain_seq = [t['domain'] for t in block]
        slot_of = [{p: t['char_order'].index(code_to_animal[b][p]) for p in positions} for t in block]
        seq, cost = order_block(domain_seq, doubles, positions, slot_of)
        print(f"block {b}: short={short} doubles={doubles} order cost={cost:.2f}")
        for t, p in enumerate(seq):
            rows.append({
                'block': b, 'trial': t, 'block_type': block_types[b], 'domain': domain_seq[t],
                'forced_first_code': p, 'forced_first': code_to_animal[b][p],
            })
    return rows


def _table(title, row_keys, col_keys, cell):
    print(f"\n{title}")
    print("  " + f"{'':<20}" + "".join(f"{c:>6}" for c in col_keys) + f"{'total':>7}")
    for r in row_keys:
        vals = [cell(r, c) for c in col_keys]
        print("  " + f"{str(r):<20}" + "".join(f"{v:>6}" for v in vals) + f"{sum(vals):>7}")


def report(rows):
    stim, schedules, code_to_animal = _task_context()
    positions = sorted(set(stim.char_code.values()))
    n_blocks = len(schedules)

    c = Counter((r['block'], r['forced_first_code']) for r in rows)
    _table("Per-block assignment counts (block × position)", range(n_blocks), positions,
           lambda b, p: c[(b, p)])
    g = Counter(r['forced_first_code'] for r in rows)
    _table("Global assignment counts", ['all blocks'], positions, lambda _, p: g[p])
    dc = Counter((r['domain'], r['forced_first_code']) for r in rows)
    _table("Domain × position", S.DOMAINS, positions, lambda d, p: dc[(d, p)])
    types = list(dict.fromkeys(r['block_type'] for r in rows))
    tc = Counter((r['block_type'], r['forced_first_code']) for r in rows)
    _table("Block type × position", types, positions, lambda t, p: tc[(t, p)])
    tdc = Counter((r['block_type'], r['domain'], r['forced_first_code']) for r in rows)
    _table("Block type × domain × position (extra)", [(t, d) for t in types for d in S.DOMAINS],
           positions, lambda td, p: tdc[(td[0], td[1], p)])
    bdc = Counter((r['block'], r['domain'], r['forced_first_code']) for r in rows)
    _table("Block × domain × position", [(b, d) for b in range(n_blocks) for d in S.DOMAINS],
           positions, lambda bd, p: bdc[(bd[0], bd[1], p)])
    th = Counter((r['trial'] * 3 // S.N_TRIALS_PER_BLOCK, r['forced_first_code']) for r in rows)
    _table("Early / middle / late third × position (all blocks)", ['early', 'middle', 'late'],
           positions, lambda name, p: th[(['early', 'middle', 'late'].index(name), p)])
    slot = Counter(schedules[r['block']][r['trial']]['char_order'].index(r['forced_first']) for r in rows)
    _table("Screen slot of forced animal", ['all blocks'], SLOT_NAMES,
           lambda _, s: slot[SLOT_NAMES.index(s)])

    print("\nSequences (position per trial):")
    for b in range(n_blocks):
        seq = [r for r in rows if r['block'] == b]
        seq.sort(key=lambda r: r['trial'])
        print(f"  block {b} [{seq[0]['block_type']:<18}] "
              + " ".join(f"{r['domain'][0]}{r['forced_first_code']}" for r in seq))

    problems = (balance_problems(rows, positions, n_blocks, S.N_TRIALS_PER_BLOCK, S.DOMAINS)
                + sync_problems(rows, schedules, stim.animal_groups, stim.char_code, S.BLOCK_PHASES))
    print("\nValidation:", "PASS" if not problems else "FAIL")
    for p in problems:
        print("  -", p)
    return not problems


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--write', action='store_true', help='generate and write the CSV')
    ap.add_argument('--force', action='store_true', help='allow overwriting an existing CSV')
    args = ap.parse_args(argv)

    if args.write:
        if FORCED_FIRST_CSV.exists() and not args.force:
            sys.exit(f"{FORCED_FIRST_CSV} exists (version-controlled). Pass --force to overwrite.")
        rows = build_rows()
        write_schedule_csv(rows)
        print(f"\nwrote {FORCED_FIRST_CSV}")
    if not FORCED_FIRST_CSV.exists():
        sys.exit(f"{FORCED_FIRST_CSV} not found — run with --write.")
    rows = read_schedule_csv()
    print(f"schedule_version = {schedule_version()}")
    return 0 if report(rows) else 1


if __name__ == '__main__':
    sys.exit(main())
