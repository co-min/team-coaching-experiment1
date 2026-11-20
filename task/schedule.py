"""Per-block trial schedules (seeded, so every subject sees the same sequence)."""

import random
from typing import Dict, List

from config import settings as S

Trial = Dict[str, object]   # {'domain': str, 'char_order': list[str]}


def generate_block_schedules(animal_groups: List[List[str]]) -> List[List[Trial]]:
    """One schedule per block; block i uses animal_groups[i]."""
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
