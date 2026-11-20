"""
stimuli_loader.py
-----------------
Loads every stimulus CSV for the active mode into one StimulusSet.
Called once from main(); nothing here runs at import time.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple

import pandas as pd

from config.modes import ExperimentConfig
from config.paths import SYNERGY_CSV, SYNERGY_COLOR_CSV

Pair = Tuple[str, str]


@dataclass
class StimulusSet:
    animal_groups: List[List[str]]                 # one 4-animal group per block
    char_code:     Dict[str, str]                  # animal name → char code
    competence:    Dict[str, Dict[str, int]]       # char code → {domain: level}
    synergy:       Dict[Pair, float]               # sorted code pair → synergy score
    synergy_color: Dict[float, str]                # synergy score → block fill colour
    scores:        Dict[str, Dict[Pair, Dict[str, float]]]   # phase → pair → {domain: score}
    score_ranges:  Dict[str, Dict[str, Tuple[float, float]]] # phase → {domain: (min, max)}
    competence_color: Dict[int, str]

    def comp_color(self, score: float) -> str:
        """Competence level → border colour (low ≤3 / middle ≤6 / high)."""
        if score <= 3.0:
            return self.competence_color[1]
        elif score <= 6.0:
            return self.competence_color[2]
        return self.competence_color[3]


def pair_key(a: str, b: str) -> Pair:
    return tuple(sorted([str(a).strip(), str(b).strip()]))


def _read(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, skipinitialspace=True)


def load_score_table(path: Path, domains: List[str]) -> Dict[Pair, Dict[str, float]]:
    df = _read(path)
    return {
        pair_key(row['char1'], row['char2']): {d: float(row[f'sc_{d}']) for d in domains}
        for _, row in df.iterrows()
    }


def load_score_ranges(path: Path, domains: List[str]) -> Dict[str, Tuple[float, float]]:
    df = _read(path)
    return {d: (float(df[f'sc_{d}'].min()), float(df[f'sc_{d}'].max())) for d in domains}


def load_stimuli(cfg: ExperimentConfig) -> StimulusSet:
    comp_df = _read(cfg.competence_csv)
    animals = comp_df['animal'].str.strip()
    codes   = comp_df['char_ani'].str.strip()

    competence = {
        code: {d: int(row[d]) for d in cfg.domains}
        for code, (_, row) in zip(codes, comp_df.iterrows())
    }

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

    scores, score_ranges = {}, {}
    for phase, spec in cfg.phases.items():
        scores[phase]       = load_score_table(spec.score_csv, spec.domains)
        score_ranges[phase] = load_score_ranges(spec.score_csv, spec.domains)

    return StimulusSet(
        animal_groups=animal_groups,
        char_code=dict(zip(animals, codes)),
        competence=competence,
        synergy=synergy,
        synergy_color=synergy_color,
        scores=scores,
        score_ranges=score_ranges,
        competence_color=cfg.competence_color,
    )
