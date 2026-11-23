"""
assessments.py
--------------
One call per assessment, each writing its own output:

    run_counterfactual_probe  end of block: baseline performance ranking →
                            hypothetical change → revised ranking
    run_attribute_ranking   NOT USED — superseded by the High / Medium / Low
                            appraisal pages (pair synergy, or pair competence
                            C_i(d) + C_j(d)), to be added as a separate module

Ground truth is Performance(i, j, d) = S(i, j) × (C_i(d) + C_j(d)) from the
raw stimulus tables (items.load_attributes), not the rank-scaled trial scores.

Option display order is shuffled with a seed from (subject, ranking_id), so it
is reproducible and logged. Every probe applies its change to the original
attributes (Attributes.with_change copies), so changes never accumulate.
"""

import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Sequence

from config.ranking_strings import rt
from config.settings import COMPETENCE_COLOR
from recording.ranking_writers import save_ranking
from recording.stimuli_loader import StimulusSet
from task.ranking.flow import RankingResult, run_revised_ranking, run_sequential_ranking, show_change_screen
from task.ranking.items import Attributes, Change, RankingSpec, items_for, role_map
from task.ranking.record import build_ranking_record
from task.ranking.view import ChangeDisplay, domain_label

LEVELS = ('low', 'mid', 'high')
ATTRIBUTE_BY_PHASE = {'phase_1': 'synergy', 'phase_2': 'competence'}


@dataclass
class RankingEnv:
    win:          Any
    global_clock: Any
    source:       Any            # task.ranking.inputs.KeySource (or ScriptedSource)
    stim:         StimulusSet
    attrs:        Attributes     # original (unchanged) attributes
    subject_id:   str
    subject_dir:  Path
    session_id:   Optional[str] = None


@dataclass(frozen=True)
class Probe:
    probe_id: int
    domain:   str
    change:   Change


def _spec(env: RankingEnv, block_index: int, phase: str, ranking_id: str, **kw) -> RankingSpec:
    group = tuple(env.stim.animal_groups[block_index])
    return RankingSpec(ranking_id=ranking_id, block_index=block_index, phase=phase, group=group,
                       roles=role_map(group, env.stim.char_code), **kw)


def _shuffled(env: RankingEnv, spec: RankingSpec):
    items = items_for(spec.attribute, spec.group, env.stim.char_code)
    random.Random(f"{env.subject_id}|{spec.ranking_id}").shuffle(items)
    return items


def _save(env: RankingEnv, result: RankingResult, change_level: Optional[str] = None) -> RankingResult:
    record, events = build_ranking_record(result, env.attrs, env.subject_id, env.session_id, change_level)
    save_ranking(env.subject_dir, record, events)
    return result


def change_level(stim: StimulusSet, change: Change) -> tuple:
    """(level name, colour) of the changed value in the task's colour code."""
    if change.kind == 'competence':
        color = stim.comp_color(change.value)
        level = {c: i for i, c in COMPETENCE_COLOR.items()}[color] - 1
        return LEVELS[level], color
    values = sorted(stim.synergy_color)
    if change.value not in stim.synergy_color:
        raise ValueError(f"synergy change value {change.value} not in synergy table {values}")
    return LEVELS[values.index(change.value)], stim.synergy_color[change.value]


def change_display(env: RankingEnv, spec: RankingSpec, change: Change) -> tuple:
    level, color = change_level(env.stim, change)
    animals = [spec.roles[r] for r in change.roles]
    if change.kind == 'competence':
        text = rt("change_competence", domain=domain_label(change.domain), level=rt(f"level_{level}"))
    else:
        text = rt("change_synergy", level=rt(f"level_{level}"))
    return ChangeDisplay(change.kind, animals, color, text), level


# ── entry points ──────────────────────────────────────────────────────────────

def run_attribute_ranking(env: RankingEnv, block_index: int, phase: str, after_trial: int,
                          domain: Optional[str] = None) -> RankingResult:
    attribute = ATTRIBUTE_BY_PHASE[phase]
    if attribute == 'competence' and domain is None:
        raise ValueError("competence ranking (synergy-visible block) needs a domain")
    spec = _spec(env, block_index, phase, f"b{block_index}_attr_t{after_trial:02d}",
                 ranking_type='attribute', attribute=attribute, after_trial=after_trial,
                 domain=domain if attribute == 'competence' else None)
    prompt = (rt("rank_prompt_synergy") if attribute == 'synergy'
              else rt("rank_prompt_competence", domain=domain_label(domain)))
    result = run_sequential_ranking(env.win, env.global_clock, env.source, spec, _shuffled(env, spec), prompt)
    return _save(env, result)


def run_counterfactual_probe(env: RankingEnv, block_index: int, phase: str,
                             probe: Probe) -> Sequence[RankingResult]:
    """Baseline → change → revised. Returns the results run (stops early if aborted)."""
    base_spec = _spec(env, block_index, phase, f"b{block_index}_p{probe.probe_id}_baseline",
                      ranking_type='performance', attribute='performance', domain=probe.domain,
                      probe_id=probe.probe_id)
    baseline = run_sequential_ranking(env.win, env.global_clock, env.source, base_spec, _shuffled(env, base_spec),
                                      rt("rank_prompt_performance", domain=domain_label(probe.domain)))
    _save(env, baseline)
    if baseline.aborted:
        return [baseline]

    rev_spec = _spec(env, block_index, phase, f"b{block_index}_p{probe.probe_id}_revised",
                     ranking_type='counterfactual', attribute='performance', domain=probe.domain,
                     probe_id=probe.probe_id, change=probe.change, baseline_id=base_spec.ranking_id)
    display, level = change_display(env, rev_spec, probe.change)
    shown = show_change_screen(env.win, env.global_clock, env.source, display, probe.domain)
    if shown['aborted']:
        return [baseline]

    # An incomplete (timed-out) baseline is completed in display order so the
    # revised screen always has a full list; status 'timeout' flags it.
    initial = baseline.final + [it for it in baseline.display_order if it not in baseline.final]
    revised = run_revised_ranking(env.win, env.global_clock, env.source, rev_spec, initial,
                                rt("rank_prompt_revised", domain=domain_label(probe.domain)), display)
    revised.change_onset_global = None if shown['onset'] is None else round(shown['onset'], 5)
    revised.change_rt = shown['rt']
    _save(env, revised, change_level=level)
    return [baseline, revised]
