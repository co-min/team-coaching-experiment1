"""
items.py
--------
What gets ranked, and the ground truth it is scored against.

    RankItem    one animal or one pair, identified internally by role codes (A–D)
    Attributes  competence + synergy for one block, with Performance(i, j, d)
    Change      one hypothetical attribute change (counterfactual probe)

Role codes never reach the screen — the view only uses RankItem.animals.
Pure stdlib (no psychopy) so tests can import it without a window.
"""

import csv
import itertools
from dataclasses import dataclass, field
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

from config.paths import COMPETENCE_CSV

Pair = Tuple[str, str]

# Ranking "attribute" → what the participant orders items by
ATTRIBUTE_ITEM_KIND = {'synergy': 'pair', 'competence': 'animal', 'performance': 'pair'}


@dataclass(frozen=True)
class RankItem:
    roles:   Tuple[str, ...]   # ('C',) or ('A', 'C'), sorted
    animals: Tuple[str, ...]   # same order as roles

    @property
    def key(self) -> str:
        """Role key used in logs, e.g. 'A+C'."""
        return '+'.join(self.roles)

    @property
    def label(self) -> str:
        """Animal label used in logs, e.g. 'duck+panda'."""
        return '+'.join(self.animals)


def role_map(group: Sequence[str], char_code: Mapping[str, str]) -> Dict[str, str]:
    """Role code → animal for one block's group."""
    return {char_code[a]: a for a in group}


def animal_items(group: Sequence[str], char_code: Mapping[str, str]) -> List[RankItem]:
    roles = role_map(group, char_code)
    return [RankItem((r,), (roles[r],)) for r in sorted(roles)]


def pair_items(group: Sequence[str], char_code: Mapping[str, str]) -> List[RankItem]:
    roles = role_map(group, char_code)
    return [RankItem((a, b), (roles[a], roles[b])) for a, b in itertools.combinations(sorted(roles), 2)]


def items_for(attribute: str, group: Sequence[str], char_code: Mapping[str, str]) -> List[RankItem]:
    builder = pair_items if ATTRIBUTE_ITEM_KIND[attribute] == 'pair' else animal_items
    return builder(group, char_code)


# ── attributes / counterfactual changes ───────────────────────────────────────

@dataclass(frozen=True)
class Change:
    """Hypothetical change applied to the original attributes of one probe.

    kind   : 'competence' (roles = (r,), domain required) or 'synergy' (roles = (r1, r2))
    value  : the new attribute value (same scale as the stimulus tables)
    """
    kind:   str
    roles:  Tuple[str, ...]
    value:  float
    domain: Optional[str] = None

    def __post_init__(self):
        object.__setattr__(self, 'roles', tuple(sorted(self.roles)))
        if self.kind == 'competence' and (len(self.roles) != 1 or self.domain is None):
            raise ValueError(f"competence change needs one role and a domain: {self}")
        if self.kind == 'synergy' and len(self.roles) != 2:
            raise ValueError(f"synergy change needs two roles: {self}")
        if self.kind not in ('competence', 'synergy'):
            raise ValueError(f"unknown change kind {self.kind!r}")


@dataclass(frozen=True)
class Attributes:
    competence: Mapping[str, Mapping[str, float]]   # role → {domain: value}
    synergy:    Mapping[Pair, float]                # sorted role pair → value

    def performance(self, roles: Sequence[str], domain: str) -> float:
        """Performance(i, j, d) = Synergy(i, j) × (Competence(i, d) + Competence(j, d))."""
        a, b = sorted(roles)
        return self.synergy[(a, b)] * (self.competence[a][domain] + self.competence[b][domain])

    def with_change(self, change: Change) -> 'Attributes':
        """A new Attributes with *change* applied; self is never modified,
        so every probe starts from the original attributes."""
        competence = {r: dict(levels) for r, levels in self.competence.items()}
        synergy = dict(self.synergy)
        if change.kind == 'competence':
            competence[change.roles[0]][change.domain] = change.value
        else:
            synergy[change.roles] = change.value
        return Attributes(competence, synergy)

    def value(self, attribute: str, item: RankItem, domain: Optional[str]) -> float:
        if attribute == 'synergy':
            return self.synergy[item.roles]
        if attribute == 'competence':
            return self.competence[item.roles[0]][domain]
        if attribute == 'performance':
            return self.performance(item.roles, domain)
        raise ValueError(f"unknown attribute {attribute!r}")


def load_attributes(synergy: Mapping[Pair, float], path=COMPETENCE_CSV) -> Attributes:
    """Raw (unrounded) competence per role from the CSV + the loaded synergy table.

    StimulusSet.competence holds int levels for the border colours; ground
    truth needs the original values, so they are re-read here.
    """
    competence: Dict[str, Dict[str, float]] = {}
    with open(path, newline='', encoding='utf-8') as f:
        for row in csv.DictReader(f, skipinitialspace=True):
            values = {k.strip(): v for k, v in row.items()}
            role = values.pop('char_ani').strip()
            # Every animal sharing a role has the same profile; the first row wins.
            competence.setdefault(role, {
                d: float(v) for d, v in values.items() if d not in ('id', 'animal', 'img_file')
            })
    return Attributes(competence, dict(synergy))


# ── ground truth / agreement ──────────────────────────────────────────────────

def true_values(attrs: Attributes, attribute: str, items: Sequence[RankItem],
                domain: Optional[str]) -> Dict[str, float]:
    """item key → value, in role order (independent of display order)."""
    return {it.key: round(attrs.value(attribute, it, domain), 4) for it in sorted(items, key=lambda i: i.roles)}


def _average_ranks(values: Sequence[float]) -> List[float]:
    """1 = largest; tied values share their mean rank."""
    order = sorted(range(len(values)), key=lambda i: -values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        for k in range(i, j + 1):
            ranks[order[k]] = (i + j) / 2 + 1
        i = j + 1
    return ranks


def spearman(ranking: Sequence[str], truth: Mapping[str, float]) -> Optional[float]:
    """Spearman rho between a participant ranking (keys, best first) and true values.

    None if the ranking is incomplete or the truth has no variance.
    """
    if sorted(ranking) != sorted(truth):
        return None
    given = [float(ranking.index(k) + 1) for k in truth]
    true  = _average_ranks(list(truth.values()))
    mg, mt = sum(given) / len(given), sum(true) / len(true)
    cov = sum((g - mg) * (t - mt) for g, t in zip(given, true))
    vg  = sum((g - mg) ** 2 for g in given)
    vt  = sum((t - mt) ** 2 for t in true)
    return round(cov / (vg * vt) ** 0.5, 4) if vg and vt else None


def kendall_distance(a: Sequence[str], b: Sequence[str]) -> Optional[int]:
    """Number of discordant item pairs between two complete rankings of the same items."""
    if sorted(a) != sorted(b):
        return None
    pos = {k: i for i, k in enumerate(b)}
    return sum(1 for i, j in itertools.combinations(range(len(a)), 2) if pos[a[i]] > pos[a[j]])


# ── one ranking's definition ──────────────────────────────────────────────────

@dataclass
class RankingSpec:
    """Everything that identifies one ranking screen in the logs."""
    ranking_id:   str
    ranking_type: str                   # 'attribute' | 'performance' | 'counterfactual'
    attribute:    str                   # 'synergy' | 'competence' | 'performance'
    block_index:  int
    phase:        str
    group:        Tuple[str, ...]       # the block's animal set
    roles:        Dict[str, str]        # role → animal
    domain:       Optional[str] = None
    after_trial:  Optional[int] = None  # attribute rankings: 1-indexed learning trial
    probe_id:     Optional[int] = None  # performance / counterfactual
    change:       Optional[Change] = None
    baseline_id:  Optional[str] = None  # counterfactual → its baseline ranking
    extra:        Dict[str, object] = field(default_factory=dict)
