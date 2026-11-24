"""
items.py
--------
What the attribute estimate asks, in which order, and the true answer to each question.
No PsychoPy here, so the tests can import it without opening a window.

    checkpoint_after_trial    'middle' / 'end' / None for a learning-trial number
    estimate_type_for_phase   which attribute a block asks about (always the hidden one)
    EstimateItem              one question: a pair (synergy) or one animal in one domain (competence)
    synergy_items             the 6 pairs of a block's 4 animals
    competence_items          each animal on its own, for each configured domain
    ordered_items             reproducible random presentation order
    build_estimate_items      all of the above for one block and checkpoint
    is_correct                response vs true level

The two attributes are different kinds of things, so they are asked differently:
    synergy    S(i, j)  belongs to a PAIR and does not depend on the domain
    competence C_i(d)   belongs to ONE animal and depends on the domain
Competence is never asked for two animals together (no C_i + C_j sums).

True values come from the original tables (task.ranking.items.load_attributes,
decimals kept, e.g. 8.5). True levels use the task's own colour rules
(StimulusSet.competence_level / synergy_level), not new thresholds.

Animals are handled by role code (A–D) internally, as in task/ranking.
Role codes are only logged; the screen shows animal images.
"""

import random
from dataclasses import dataclass, replace
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

from config.estimate import ESTIMATE_CHECKPOINTS, COMPETENCE_ESTIMATE_DOMAINS
from recording.stimuli_loader import StimulusSet
from task.forced_first import BLOCK_TYPE
from task.ranking.items import Attributes, pair_items, role_map

SYNERGY, COMPETENCE = 'synergy', 'competence'


# ── when and what ─────────────────────────────────────────────────────────────

def checkpoint_after_trial(trial_number: int,
                           checkpoints: Mapping[int, str] = ESTIMATE_CHECKPOINTS) -> Optional[str]:
    """Checkpoint name to run after learning trial `trial_number` (1-based), or None.

    With the default config: 7 → 'middle', 15 → 'end', anything else → None.
    """
    return checkpoints.get(trial_number)


def estimate_type_for_phase(phase: str) -> str:
    """The attribute to estimate in a block = the one that block hides.

    phase_1 shows competence (coloured borders) → synergy is hidden → 'synergy'
    phase_2 shows synergy (coloured blocks)     → competence is hidden → 'competence'
    Uses the same block-type labels as the trial output (task.forced_first.BLOCK_TYPE).
    """
    block_type = BLOCK_TYPE.get(phase)
    if block_type == 'competence_visible':
        return SYNERGY
    elif block_type == 'synergy_visible':
        return COMPETENCE
    else:
        raise ValueError(f"no estimate defined for phase {phase!r}")


def estimate_id(block_index: int, checkpoint: str) -> str:
    """Name of one estimate in the output, e.g. 'b0_middle'. Also part of the order seed."""
    return f"b{block_index}_{checkpoint}"


# ── one question ──────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class EstimateItem:
    """One estimate question. Frozen (cannot be changed after it is made).

    estimate_type   : 'synergy' or 'competence'
    roles           : sorted role codes. ('A', 'C') for a pair, ('B',) for one animal
    animals         : animal names, same order as roles
    domain          : competence only. None for synergy, which is domain-independent
    true_value      : the original table value, e.g. 1.4 (synergy) or 8.5 (competence)
    true_level      : 'low' / 'mid' / 'high' by the task's colour rules
    display_animals : animal names left → right on screen (set by ordered_items)

    The screen code never receives this object, only display_animals and domain,
    so it cannot show the true value or level by accident.
    """
    estimate_type:   str
    roles:           Tuple[str, ...]
    animals:         Tuple[str, ...]
    domain:          Optional[str]
    true_value:      float
    true_level:      str
    display_animals: Tuple[str, ...] = ()

    @property
    def pair_id(self) -> Optional[str]:
        """'A+C' for a synergy question, None for a competence question."""
        if self.estimate_type == SYNERGY:
            return '+'.join(self.roles)
        return None

    @property
    def animal_id(self) -> Optional[str]:
        """'B' for a competence question, None for a synergy question."""
        if self.estimate_type == COMPETENCE:
            return self.roles[0]
        return None


def synergy_items(group: Sequence[str], stim: StimulusSet, attrs: Attributes) -> List[EstimateItem]:
    """All 6 pairs of the block's 4 animals (AB, AC, AD, BC, BD, CD), in role order."""
    items = []
    for pair in pair_items(group, stim.char_code):
        value = attrs.synergy[pair.roles]
        items.append(EstimateItem(
            estimate_type=SYNERGY,
            roles=pair.roles,
            animals=pair.animals,
            domain=None,
            true_value=value,
            true_level=stim.synergy_level(value),
        ))
    return items


def competence_items(group: Sequence[str], stim: StimulusSet, attrs: Attributes,
                     domains: Sequence[str] = COMPETENCE_ESTIMATE_DOMAINS) -> List[EstimateItem]:
    """Each animal on its own, for each domain in `domains` (4 animals × 3 domains = 12).

    Grouped by domain, in role order within a domain.
    """
    roles = role_map(group, stim.char_code)
    items = []
    for domain in domains:
        for role in sorted(roles):
            if domain not in attrs.competence[role]:
                raise ValueError(f"competence estimate domain {domain!r} is not in the competence table")
            value = attrs.competence[role][domain]
            items.append(EstimateItem(
                estimate_type=COMPETENCE,
                roles=(role,),
                animals=(roles[role],),
                domain=domain,
                true_value=value,
                true_level=stim.competence_level(value),
            ))
    return items


# ── presentation order ────────────────────────────────────────────────────────

def ordered_items(items: Sequence[EstimateItem], seed: str) -> List[EstimateItem]:
    """Reproducible random presentation order. Every item appears exactly once.

    seed : any string; the same seed always gives the same order.
           random.Random(seed) is a private generator, so other random numbers
           in the experiment are not affected.

    synergy    : the 6 pairs are shuffled, and so is which animal of each pair is on the left
                 (so position on screen carries no information).
    competence : questions stay grouped by domain (as requested: 4 animals per domain).
                 The order of the domains and the animals within each domain are shuffled.
    """
    rng = random.Random(seed)

    if all(item.estimate_type == SYNERGY for item in items):
        shuffled = list(items)
        rng.shuffle(shuffled)
        result = []
        for item in shuffled:
            left_to_right = list(item.animals)
            rng.shuffle(left_to_right)
            result.append(replace(item, display_animals=tuple(left_to_right)))
        return result

    if all(item.estimate_type == COMPETENCE for item in items):
        # Domains in the order they first appear, then shuffled.
        domain_order = []
        for item in items:
            if item.domain not in domain_order:
                domain_order.append(item.domain)
        rng.shuffle(domain_order)

        result = []
        for domain in domain_order:
            items_in_domain = [item for item in items if item.domain == domain]
            rng.shuffle(items_in_domain)
            for item in items_in_domain:
                result.append(replace(item, display_animals=item.animals))
        return result

    raise ValueError("one estimate must contain only synergy or only competence questions")


def build_estimate_items(estimate_type: str, group: Sequence[str], stim: StimulusSet, attrs: Attributes,
                          seed: str, domains: Sequence[str] = COMPETENCE_ESTIMATE_DOMAINS
                          ) -> List[EstimateItem]:
    """The questions of one estimate, in presentation order.

    Middle and end of a block ask the same questions (same function, same inputs);
    only the order differs, because the seed includes the checkpoint name.
    """
    if estimate_type == SYNERGY:
        items = synergy_items(group, stim, attrs)
    elif estimate_type == COMPETENCE:
        items = competence_items(group, stim, attrs, domains)
    else:
        raise ValueError(f"unknown estimate type {estimate_type!r}")
    return ordered_items(items, seed)


# ── scoring ───────────────────────────────────────────────────────────────────

def is_correct(response: Optional[str], true_level: Optional[str]) -> Optional[bool]:
    """True / False, or None when there is no response (timeout, abort) or no true level."""
    if response is None or true_level is None:
        return None
    return response == true_level


def item_counter(items: Sequence[EstimateItem], position: int) -> Dict[str, int]:
    """Progress numbers shown on screen for items[position] (0-based).

    synergy    : 'Pair n / 6' over the whole estimate
    competence : 'Animal n / 4' within the current domain
    Returns {'n': ..., 'total': ...}.
    """
    item = items[position]
    if item.estimate_type == SYNERGY:
        return {'n': position + 1, 'total': len(items)}

    same_domain = [index for index, other in enumerate(items) if other.domain == item.domain]
    return {'n': same_domain.index(position) + 1, 'total': len(same_domain)}
