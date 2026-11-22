"""
forced_first.py
---------------
Fixed, version-controlled forced-first-choice schedule (FIRST_CHOICE_MODE='forced').

The schedule lives in stimuli/tables/forced_first_schedule.csv and is generated
offline by tools/make_forced_first_schedule.py. At runtime it is only loaded and
checked — never regenerated or shuffled — so every subject gets the same
90-trial sequence of forced first animals.

"Position" = char code (A–D): the within-block animal identity that repeats
across animal groups. Balance is defined on positions, not animal names.

Pure stdlib (no psychopy / pandas) so it can be imported by tools and tests.
"""

import csv
import hashlib
from collections import Counter
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from config import settings as S
from config.paths import FORCED_FIRST_CSV

CSV_FIELDS = ['block', 'trial', 'block_type', 'domain', 'forced_first_code', 'forced_first']

# BLOCK_PHASES entry → block-type label written to the CSV
BLOCK_TYPE = {'phase_1': 'competence_visible', 'phase_2': 'synergy_visible'}


class ScheduleError(ValueError):
    """The forced-first schedule is malformed, unbalanced, or out of sync with the task."""


def schedule_version(path: Path = FORCED_FIRST_CSV) -> str:
    """'<file name>@<sha256[:12]>' — changes whenever the CSV content changes.

    Line endings are normalised so a git CRLF checkout gives the same version.
    """
    digest = hashlib.sha256(Path(path).read_bytes().replace(b'\r\n', b'\n')).hexdigest()[:12]
    return f"{Path(path).name}@{digest}"


def read_schedule_csv(path: Path = FORCED_FIRST_CSV) -> List[Dict[str, object]]:
    with open(path, newline='', encoding='utf-8') as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        r['block'] = int(r['block'])
        r['trial'] = int(r['trial'])
    return rows


def write_schedule_csv(rows: Sequence[Dict[str, object]], path: Path = FORCED_FIRST_CSV) -> None:
    with open(path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS, lineterminator='\n')
        writer.writeheader()
        writer.writerows(rows)


# ── validation ────────────────────────────────────────────────────────────────

def _within(counts: Counter, keys, lo: int, hi: int) -> bool:
    return all(lo <= counts.get(k, 0) <= hi for k in keys)


def balance_problems(rows: Sequence[Dict[str, object]], positions: Sequence[str],
                     n_blocks: int, n_trials: int, domains: Sequence[str]) -> List[str]:
    """Return every violated hard constraint (empty list = schedule is valid).

    Bounds are floor/ceil of the even split, so they adapt to the design sizes
    (15 trials, 4 positions, 3 domains, 6 blocks → 3–4 / 22–23 / 7–8 / 11–12).
    """
    problems: List[str] = []
    n_pos = len(positions)

    def bounds(total: int):
        return total // n_pos, -(-total // n_pos)

    ids = [(r['block'], r['trial']) for r in rows]
    expected = {(b, t) for b in range(n_blocks) for t in range(n_trials)}
    dup = [k for k, c in Counter(ids).items() if c > 1]
    if dup:
        problems.append(f"duplicate block/trial ids: {sorted(dup)}")
    if set(ids) != expected:
        problems.append(f"missing ids: {sorted(expected - set(ids))}; "
                        f"unexpected ids: {sorted(set(ids) - expected)}")
    bad_pos = sorted({r['forced_first_code'] for r in rows} - set(positions))
    if bad_pos:
        problems.append(f"unknown positions: {bad_pos}")
    if problems:
        return problems

    # within block
    for b in range(n_blocks):
        block_rows = sorted((r for r in rows if r['block'] == b), key=lambda r: r['trial'])
        c = Counter(r['forced_first_code'] for r in block_rows)
        lo, hi = bounds(len(block_rows))
        if not _within(c, positions, lo, hi):
            problems.append(f"block {b}: position counts {dict(c)} outside {lo}–{hi}")
        for d in domains:
            dom_rows = [r for r in block_rows if r['domain'] == d]
            dc = Counter(r['forced_first_code'] for r in dom_rows)
            if len(dom_rows) >= n_pos and not _within(dc, positions, 1, len(dom_rows)):
                problems.append(f"block {b} / {d}: not every position assigned ({dict(dc)})")
        for prev, cur in zip(block_rows, block_rows[1:]):
            if prev['forced_first_code'] == cur['forced_first_code']:
                problems.append(f"block {b}: position {cur['forced_first_code']} repeated "
                                f"on trials {prev['trial']}–{cur['trial']}")

    # global
    c = Counter(r['forced_first_code'] for r in rows)
    lo, hi = bounds(len(rows))
    if not _within(c, positions, lo, hi):
        problems.append(f"global: position counts {dict(c)} outside {lo}–{hi}")

    # domain × position
    for d in domains:
        dom_rows = [r for r in rows if r['domain'] == d]
        dc = Counter(r['forced_first_code'] for r in dom_rows)
        lo, hi = bounds(len(dom_rows))
        if not _within(dc, positions, lo, hi):
            problems.append(f"domain {d}: position counts {dict(dc)} outside {lo}–{hi}")

    # block type × position
    for bt in sorted({r['block_type'] for r in rows}):
        bt_rows = [r for r in rows if r['block_type'] == bt]
        bc = Counter(r['forced_first_code'] for r in bt_rows)
        lo, hi = bounds(len(bt_rows))
        if not _within(bc, positions, lo, hi):
            problems.append(f"block type {bt}: position counts {dict(bc)} outside {lo}–{hi}")

    return problems


def sync_problems(rows: Sequence[Dict[str, object]], block_schedules: List[List[dict]],
                  animal_groups: List[List[str]], char_code: Dict[str, str],
                  block_phases: Sequence[str]) -> List[str]:
    """Check the CSV against the live task schedule (domains, animals, block types)."""
    problems: List[str] = []
    by_id = {(r['block'], r['trial']): r for r in rows}
    for b, (block, group, phase) in enumerate(zip(block_schedules, animal_groups, block_phases)):
        for t, trial in enumerate(block):
            r = by_id.get((b, t))
            if r is None:
                problems.append(f"block {b} trial {t}: no schedule row")
                continue
            if r['domain'] != trial['domain']:
                problems.append(f"block {b} trial {t}: CSV domain {r['domain']!r} != "
                                f"task domain {trial['domain']!r}")
            if r['block_type'] != BLOCK_TYPE[phase]:
                problems.append(f"block {b}: CSV block_type {r['block_type']!r} != {BLOCK_TYPE[phase]!r}")
            if r['forced_first'] not in group:
                problems.append(f"block {b} trial {t}: {r['forced_first']!r} not in block animals {group}")
            elif char_code[r['forced_first']] != r['forced_first_code']:
                problems.append(f"block {b} trial {t}: {r['forced_first']!r} has code "
                                f"{char_code[r['forced_first']]!r}, CSV says {r['forced_first_code']!r}")
    n_task = sum(len(b) for b in block_schedules)
    if len(rows) != n_task:
        problems.append(f"CSV has {len(rows)} rows, task has {n_task} learning trials")
    return problems


# ── runtime entry point ───────────────────────────────────────────────────────

def attach_forced_first(block_schedules: List[List[dict]], animal_groups: List[List[str]],
                        char_code: Dict[str, str], path: Path = FORCED_FIRST_CSV) -> str:
    """Load + validate the fixed schedule and set trial['forced_first'] on every trial.

    Raises ScheduleError instead of silently running an unbalanced or
    mismatched schedule. Returns the schedule version string for logging.
    """
    rows = read_schedule_csv(path)
    positions = sorted(set(char_code.values()))
    problems = (
        balance_problems(rows, positions, len(block_schedules), S.N_TRIALS_PER_BLOCK, S.DOMAINS)
        + sync_problems(rows, block_schedules, animal_groups, char_code, S.BLOCK_PHASES)
    )
    if problems:
        raise ScheduleError(f"{Path(path).name} is invalid:\n  " + "\n  ".join(problems))

    by_id = {(r['block'], r['trial']): r['forced_first'] for r in rows}
    for b, block in enumerate(block_schedules):
        for t, trial in enumerate(block):
            trial['forced_first'] = by_id[(b, t)]
    return schedule_version(path)


def forced_first_for(trial_info: dict) -> Optional[str]:
    """Forced animal for this trial, or None in free mode.

    KeyError in forced mode if attach_forced_first() was never called — never
    fall back to free choice silently.
    """
    return trial_info['forced_first'] if S.FIRST_CHOICE_MODE == 'forced' else None
