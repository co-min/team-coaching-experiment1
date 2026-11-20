"""
stimuli_loader.py
-----------------
Loads the competence and synergy tables into one StimulusSet and derives the
pair score table from them. Called once from main(); nothing here runs at
import time.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple

import pandas as pd

from config.paths import COMPETENCE_CSV, SYNERGY_CSV, SYNERGY_COLOR_CSV
from config.settings import COMPETENCE_COLOR, DOMAINS

Pair = Tuple[str, str]


@dataclass
class StimulusSet:
    animal_groups: List[List[str]]                 # one 4-animal group per block
    char_code:     Dict[str, str]                  # animal name → char code
    competence:    Dict[str, Dict[str, int]]       # char code → {domain: level}
    synergy:       Dict[Pair, float]               # sorted code pair → synergy score
    synergy_color: Dict[float, str]                # synergy score → block fill colour
    scores:        Dict[Pair, Dict[str, float]]    # pair → {domain: score}
    score_ranges:  Dict[str, Tuple[float, float]]  # {domain: (min, max)}

    @property
    def max_trial_score(self) -> float:
        """Best possible single-trial score across all domains (a "perfect" trial)."""
        return max(hi for _, hi in self.score_ranges.values())

    def comp_color(self, score: float) -> str:
        """Competence level → border colour (low ≤3 / middle ≤6 / high)."""
        if score <= 3.0:
            return COMPETENCE_COLOR[1]
        elif score <= 6.0:
            return COMPETENCE_COLOR[2]
        return COMPETENCE_COLOR[3]


def pair_key(a: str, b: str) -> Pair:
    return tuple(sorted([str(a).strip(), str(b).strip()]))


def _read(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, skipinitialspace=True)


def compute_scores(competence: Dict[str, Dict[str, float]],
                   synergy: Dict[Pair, float]) -> Dict[Pair, Dict[str, float]]:
    """
    Raw pair score = synergy × (competence_1 + competence_2), per domain.
    Each domain is then replaced by its rank among pairs (1 = lowest) × 10;
    ties keep synergy.csv row order.
    """
    raw = {
        (a, b): {d: round(syn * (competence[a][d] + competence[b][d]), 2) for d in DOMAINS}
        for (a, b), syn in synergy.items()
    }
    scores: Dict[Pair, Dict[str, float]] = {pair: {} for pair in raw}
    for d in DOMAINS:
        for rank, pair in enumerate(sorted(raw, key=lambda p: raw[p][d]), start=1):
            scores[pair][d] = float(rank * 10)
    return scores


def load_stimuli() -> StimulusSet:
    comp_df = _read(COMPETENCE_CSV)
    animals = comp_df['animal'].str.strip()
    codes   = comp_df['char_ani'].str.strip()

    # Every animal sharing a char code has the same profile; the first row wins.
    comp_raw = {}
    for code, (_, row) in zip(codes, comp_df.iterrows()):
        comp_raw.setdefault(code, {d: float(row[d]) for d in DOMAINS})

    n_chars  = codes.nunique()
    n_groups = len(comp_df) // n_chars
    animal_groups = [list(animals.iloc[g * n_chars:(g + 1) * n_chars]) for g in range(n_groups)]

    syn_df  = _read(SYNERGY_CSV)
    synergy = {pair_key(r['char1'], r['char2']): float(r['synergy_score']) for _, r in syn_df.iterrows()}

    color_df = _read(SYNERGY_COLOR_CSV)
    synergy_color = dict(zip(
        sorted(syn_df['synergy_score'].unique()),
        color_df.sort_values('id')['color'].str.strip().tolist(),
    ))

    scores = compute_scores(comp_raw, synergy)
    score_ranges = {
        d: (min(s[d] for s in scores.values()), max(s[d] for s in scores.values()))
        for d in DOMAINS
    }

    return StimulusSet(
        animal_groups=animal_groups,
        char_code=dict(zip(animals, codes)),
        competence={code: {d: int(v) for d, v in levels.items()} for code, levels in comp_raw.items()},
        synergy=synergy,
        synergy_color=synergy_color,
        scores=scores,
        score_ranges=score_ranges,
    )
