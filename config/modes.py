"""
modes.py
--------
MISSION_MODE presets. This is the only place that branches on the mode;
everything downstream reads the resulting ExperimentConfig.

MODE 1 : 3 domains, 18 trials/block, raw score table
MODE 2 : 2 domains, 16 trials/block, raw score table (4-level competence colours)
MODE 3 : phase 1 = 3 domains × 18 trials / phase 2 = 2 domains × 16 trials
MODE 4 : 3 domains, 15 trials/block, ranked score table          ← current
MODE 5 : 3 domains, 18 trials/block, ranked score table, 4 blocks  (v3 "else" branch)
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List

from config.paths import TABLES_DIR

_D3_COMP         = TABLES_DIR / 'competence_d3.csv'
_D3_SCORE        = TABLES_DIR / 'score_d3.csv'
_D3_RANKED_SCORE = TABLES_DIR / 'score_ranked_d3.csv'
_D2_COMP         = TABLES_DIR / 'competence_d2.csv'
_D2_SCORE        = TABLES_DIR / 'score_d2.csv'

_DOMAINS_3 = ['cooking', 'repairing', 'tennis']
_DOMAINS_2 = ['cooking', 'repairing']

_COLOR_3 = {1: '#F44336', 2: '#FFEB3B', 3: '#4CAF50'}                  # 3-level
_COLOR_4 = {1: '#F44336', 2: '#FF9800', 3: '#FFEB3B', 4: '#4CAF50'}    # 4-level

_ALTERNATING_6 = ['phase_1', 'phase_2'] * 3
_ALTERNATING_4 = ['phase_1', 'phase_2'] * 2


@dataclass(frozen=True)
class PhaseSpec:
    """What one phase's blocks look like: trial count, domains, and score table."""
    n_trials:  int
    domains:   List[str]
    score_csv: Path


@dataclass(frozen=True)
class ExperimentConfig:
    mode:             int
    competence_csv:   Path
    competence_color: Dict[int, str]
    block_phases:     List[str]
    phases:           Dict[str, PhaseSpec]

    @property
    def domains(self) -> List[str]:
        """Phase 1 domains — the full domain set (superset of phase 2's)."""
        return self.phases['phase_1'].domains

    def phase(self, phase: str) -> PhaseSpec:
        return self.phases[phase]


def _same_both(n_trials, domains, score_csv) -> Dict[str, PhaseSpec]:
    spec = PhaseSpec(n_trials, domains, score_csv)
    return {'phase_1': spec, 'phase_2': spec}


_MODES: Dict[int, ExperimentConfig] = {
    1: ExperimentConfig(
        mode=1, competence_csv=_D3_COMP, competence_color=_COLOR_3,
        block_phases=_ALTERNATING_6,
        phases=_same_both(18, _DOMAINS_3, _D3_SCORE),
    ),
    2: ExperimentConfig(
        mode=2, competence_csv=_D2_COMP, competence_color=_COLOR_4,
        block_phases=_ALTERNATING_6,
        phases=_same_both(16, _DOMAINS_2, _D2_SCORE),
    ),
    3: ExperimentConfig(
        mode=3, competence_csv=_D3_COMP, competence_color=_COLOR_3,
        block_phases=_ALTERNATING_6,
        phases={
            'phase_1': PhaseSpec(18, _DOMAINS_3, _D3_SCORE),
            'phase_2': PhaseSpec(16, _DOMAINS_2, _D2_SCORE),
        },
    ),
    4: ExperimentConfig(
        mode=4, competence_csv=_D3_COMP, competence_color=_COLOR_3,
        block_phases=_ALTERNATING_6,
        phases=_same_both(15, _DOMAINS_3, _D3_RANKED_SCORE),
    ),
    5: ExperimentConfig(
        mode=5, competence_csv=_D3_COMP, competence_color=_COLOR_3,
        block_phases=_ALTERNATING_4,
        phases=_same_both(18, _DOMAINS_3, _D3_RANKED_SCORE),
    ),
}


def get_config(mode: int) -> ExperimentConfig:
    if mode not in _MODES:
        raise ValueError(f"Unknown MISSION_MODE {mode!r}; choose one of {sorted(_MODES)}")
    return _MODES[mode]
