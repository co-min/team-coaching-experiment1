"""Per-block trial schedules (seeded, so every subject sees the same sequence)
and the between-subject block presentation order."""

import random
import re
from typing import Dict, List, Mapping, Sequence, Tuple

from config import settings as S

Trial = Dict[str, object]   # {'domain': str, 'char_order': list[str]}


def generate_block_schedules(animal_groups: List[List[str]]) -> List[List[Trial]]:
    """One schedule per block; block i uses animal_groups[i].

    Indexed by original block ID and generated in that order, independent of
    the presentation order — index it with the block ID, not the position.
    """
    rng = random.Random(S.SCHEDULE_SEED)
    schedules = []
    trials_per_domain = S.N_TRIALS_PER_BLOCK // len(S.DOMAINS)
    for group, _ in zip(animal_groups, S.BLOCK_PHASES):
        if S.DOMAIN_ORDER == 'sequential':
            domain_sequence = [d for d in S.DOMAINS for _ in range(trials_per_domain)]
        else:
            domain_sequence = S.DOMAINS * trials_per_domain
            rng.shuffle(domain_sequence)

        schedules.append([
            {'domain': d, 'char_order': rng.sample(group, len(group))}
            for d in domain_sequence
        ])
    return schedules


# ── block order counterbalancing ──────────────────────────────────────────────

def counterbalance_group(subject_id: str) -> str:
    """'A' for an odd subject ID, 'B' for an even one.

    The number is the trailing digits of the ID ('007' → 7, 'P12' → 12).
    An ID without trailing digits raises ValueError rather than guessing.
    """
    match = re.search(r'(\d+)$', str(subject_id).strip())
    if match is None:
        raise ValueError(f"subject ID {subject_id!r} has no trailing number for counterbalancing")
    if int(match.group(1)) % 2 == 1:
        return 'A'
    return 'B'


def block_order(group: str, orders: Mapping[str, Sequence[int]] = S.BLOCK_ORDERS) -> Tuple[int, ...]:
    """Original block IDs in presentation order for this group."""
    if group not in orders:
        raise ValueError(f"unknown counterbalance group {group!r}; expected one of {sorted(orders)}")
    return tuple(orders[group])


def block_order_problems(orders: Mapping[str, Sequence[int]], n_blocks: int) -> List[str]:
    """Every group's order must present each original block exactly once. Empty list = valid."""
    problems = []
    for group, order in sorted(orders.items()):
        if sorted(order) != list(range(n_blocks)):
            problems.append(f"group {group}: {list(order)} is not a permutation of blocks 0–{n_blocks - 1}")
    return problems


def presentation_order_problems(orders: Mapping[str, Sequence[int]], phases: Sequence[str],
                                ranking_domains: Sequence[str]) -> List[str]:
    """What the participant actually sees, block after block, for every group. Empty list = valid.

    orders          : S.BLOCK_ORDERS (original block IDs in presentation order)
    phases          : S.BLOCK_PHASES (phase of each original block)
    ranking_domains : config.ranking.PERFORMANCE_RANKING_DOMAINS (domain of each original block)

    Rules, checked between each pair of neighbouring presented blocks:
        1. the phase changes (synergy-hidden and competence-hidden blocks alternate)
        2. the ranking domain changes (no domain twice in a row)
    Run block_order_problems first: this check assumes every ID is a valid block.
    """
    problems = []
    for group, order in sorted(orders.items()):
        for position in range(1, len(order)):
            previous_block = order[position - 1]
            current_block = order[position]
            if phases[current_block] == phases[previous_block]:
                problems.append(f"group {group}: positions {position - 1} and {position} "
                                f"(blocks {previous_block}, {current_block}) are both {phases[current_block]}")
            if ranking_domains[current_block] == ranking_domains[previous_block]:
                problems.append(f"group {group}: positions {position - 1} and {position} "
                                f"(blocks {previous_block}, {current_block}) both rank "
                                f"{ranking_domains[current_block]}")
    return problems
