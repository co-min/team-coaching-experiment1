"""Per-block trial schedules (seeded, so every subject sees the same sequence)."""

import random
from typing import Dict, List

from config import settings as S
from config.modes import ExperimentConfig

Trial = Dict[str, object]   # {'domain': str, 'char_order': list[str]}


def generate_block_schedules(cfg: ExperimentConfig, animal_groups: List[List[str]]) -> List[List[Trial]]:
    """One schedule per block; block i uses animal_groups[i]."""
    rng = random.Random(S.SCHEDULE_SEED)
    schedules = []
    for group, phase in zip(animal_groups, cfg.block_phases):
        spec = cfg.phase(phase)
        trials_per_domain = spec.n_trials // len(spec.domains)
        if S.DOMAIN_ORDER == 'sequential':
            domain_sequence = [d for d in spec.domains for _ in range(trials_per_domain)]
        else:
            domain_sequence = spec.domains * trials_per_domain
            rng.shuffle(domain_sequence)

        schedules.append([
            {'domain': d, 'char_order': rng.sample(group, len(group))}
            for d in domain_sequence
        ])
    return schedules
