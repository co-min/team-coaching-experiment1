"""Block-level trial orchestration — schedule execution, scoring, and I/O."""

import threading
from dataclasses import dataclass
from typing import Any, Callable, Dict, List

from config.modes import PhaseSpec
from hardware.events import on_block_start, PHASE_INT
from recording.frame_logger import make_frame_log, get_rows
from recording.stimuli_loader import StimulusSet, pair_key
from recording.summary import save_experiment_summary
from recording.writers import (
    build_trial_record, build_trial_save_dir, save_trial_metadata,
    save_frame_log, append_trial_row, append_frame_rows,
)
from task.screens.feedback import run_feedback
from task.screens.iti import run_gaussian_iti
from task.trials.phase1 import run_phase1_trial
from task.trials.phase2 import run_phase2_trial
from task.visuals import VisualObjectFactory

TRIAL_RUNNERS: Dict[str, Callable] = {
    'phase_1': run_phase1_trial,
    'phase_2': run_phase2_trial,
}


@dataclass
class BlockEnv:
    """Everything that stays fixed across blocks within one session."""
    win:          Any
    global_clock: Any
    factory:      VisualObjectFactory
    stim:         StimulusSet
    subject_id:   str
    handle:       Any
    neon_client:  Any


# ── helpers ───────────────────────────────────────────────────────────────────

def _persist_trial(subject_id, record, rows, save_dir):
    """Flush one trial's data to disk — called from a background daemon thread."""
    append_trial_row(subject_id, record)
    append_frame_rows(subject_id, rows)
    save_frame_log(rows, save_dir)


def _score_and_feedback(env: BlockEnv, result, phase, spec: PhaseSpec, domain, char_order,
                        cumulative, trial_index, n_per_domain, frame_log) -> float:
    """Update cumulative scores and show feedback. Returns the trial score (0 if no response)."""
    if not result:
        return 0

    score = env.stim.scores[phase].get(pair_key(result['choice1'], result['choice2']), {}).get(domain, 0)
    cumulative['total'] += score
    cumulative['phase'] += score
    cumulative[domain]  += score

    # Char codes (A–D) repeat across animal groups, so resolve within this trial's animals only.
    code_to_animal = {env.stim.char_code[a]: a for a in char_order}
    run_feedback(
        env.win, score, domain,
        score_ranges=env.stim.score_ranges[phase],
        block_domains=spec.domains,
        cumulative_score=cumulative['total'],
        phase_score=cumulative['phase'],
        domain_scores={d: cumulative[d] for d in spec.domains},
        n_trials_per_domain=n_per_domain,
        handle=env.handle,
        phase=PHASE_INT[phase],
        trial_index=trial_index,
        animal1=code_to_animal.get(result['choice1']),
        animal2=code_to_animal.get(result['choice2']),
        neon_client=env.neon_client,
        frame_log=frame_log,
        global_clock=env.global_clock,
    )
    return score


# ── entry point ───────────────────────────────────────────────────────────────

def run_block_trials(env: BlockEnv, block_index: int, phase: str, spec: PhaseSpec,
                     block_schedule: List[dict], cumulative: dict) -> None:
    """
    Run all trials for one block.

    block_schedule : list of {'domain': str, 'char_order': list[str]}
    cumulative     : {'total', 'phase', <domain>...} running scores (mutated)
    File I/O is offloaded to a background thread during the following ITI.
    """
    trial_runner = TRIAL_RUNNERS[phase]
    n_per_domain = len(block_schedule) // len(spec.domains)
    slot_info    = env.factory.get_slot_info()
    win_size     = (int(env.win.size[0]), int(env.win.size[1]))
    save_thread  = None

    on_block_start(env.neon_client, env.handle, phase, block_index)

    for trial_index, trial_info in enumerate(block_schedule):
        domain       = trial_info['domain']
        char_order   = trial_info['char_order']
        stim_pair_id = f"block{block_index}_{phase}_t{trial_index:02d}"
        frame_log    = make_frame_log(phase=phase, trial_id=trial_index, stim_pair_id=stim_pair_id)

        run_gaussian_iti(env.win, env.global_clock, frame_log)
        if save_thread:
            save_thread.join()

        result = trial_runner(
            env.win, env.global_clock, frame_log, env.factory, env.stim, domain, char_order,
            env.handle, neon_client=env.neon_client,
        )

        fb_score = _score_and_feedback(
            env, result, phase, spec, domain, char_order, cumulative,
            trial_index, n_per_domain, frame_log,
        )

        record = build_trial_record(
            subject_id=env.subject_id, block_i=block_index, phase=phase, domain=domain,
            trial_id=trial_index, stim_pair_id=stim_pair_id,
            char_order=char_order, char_code=env.stim.char_code,
            result=result, feedback_score=fb_score,
            elapsed_time=env.global_clock.getTime(),
            session_id=getattr(env.neon_client, 'session_id', None),
            neon_recording_id=getattr(env.neon_client, 'recording_id', None),
            win_size=win_size,
            slot_coords=slot_info['slot_coords'],
            animal_size_px=slot_info['animal_size_px'],
        )
        save_dir = build_trial_save_dir(env.subject_id, block_index, phase, domain, stim_pair_id)
        save_trial_metadata(save_dir, record)

        save_thread = threading.Thread(
            target=_persist_trial,
            args=(env.subject_id, record, get_rows(frame_log), save_dir),
            daemon=True,
        )
        save_thread.start()

    if save_thread:
        save_thread.join()

    save_experiment_summary(env.subject_id)
