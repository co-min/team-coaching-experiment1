"""Block-level trial orchestration — schedule execution, scoring, I/O, and the
attribute estimates between trials (after trial 7 and after the last trial).

Two numbers describe a block; keep them apart:
    block_index      original block ID (0–5). Decides the phase, animals, trial
                     schedule, forced first choices, estimate type, and every
                     label / folder name that says "block".
    presentation_pos where this subject sees the block (0-based, from
                     config.settings.BLOCK_ORDERS). Only logged here; main.py
                     uses it for the block number on screen and the breaks.
"""

import threading
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

from psychopy import core

from hardware.events import on_block_start, PHASE_INT
from recording.frame_logger import make_frame_log, get_rows
from recording.stimuli_loader import StimulusSet, pair_key
from recording.summary import save_experiment_summary
from recording.writers import (
    build_trial_record, build_trial_save_dir, save_trial_metadata,
    save_frame_log, append_trial_row, append_frame_rows, get_subject_dir,
)
from task.estimate.items import checkpoint_after_trial
from task.estimate.run import make_estimate_env, run_estimate
from task.forced_first import forced_first_for
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
    schedule_version: Optional[str] = None   # forced-first CSV version (forced mode)
    session_id:   Optional[str] = None        # written to estimates.csv
    counterbalance_group: Optional[str] = None   # 'A' | 'B' (task.schedule.counterbalance_group)


# ── helpers ───────────────────────────────────────────────────────────────────

def _persist_trial(subject_id, record, rows, save_dir):
    """Flush one trial's data to disk — called from a background daemon thread."""
    append_trial_row(subject_id, record)
    append_frame_rows(subject_id, rows)
    save_frame_log(rows, save_dir)


def _score_and_feedback(env: BlockEnv, result, phase, domain, char_order,
                        cumulative, trial_index, frame_log) -> float:
    """Update cumulative scores and show feedback. Returns the trial score (0 if no response)."""
    if not result:
        return 0

    score = env.stim.scores.get(pair_key(result['choice1'], result['choice2']), {}).get(domain, 0)
    cumulative['total'] += score
    cumulative['phase'] += score
    cumulative[domain]  += score

    # Char codes (A–D) repeat across animal groups, so resolve within this trial's animals only.
    code_to_animal = {env.stim.char_code[a]: a for a in char_order}
    run_feedback(
        env.win, score, domain,
        score_ranges=env.stim.score_ranges,
        block_score=cumulative['phase'],
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


def run_block_estimate(env: BlockEnv, block_index: int, phase: str, checkpoint: str, trial_after: int,
                        presentation_pos: Optional[int] = None) -> None:
    """Middle / end attribute estimate (task/estimate). Answers go to data/sub-{id}/estimates.csv.

    LabJack / Neon events are sent through env.handle / env.neon_client.
    Esc during the estimate ends the session, the same as Esc during a trial:
    core.quit() raises SystemExit, so main()'s finally block still flushes Neon
    and closes the LabJack (the estimate-end event is already queued by then).
    """
    estimate_env = make_estimate_env(env.win, env.global_clock, env.stim, env.subject_id,
                                       get_subject_dir(env.subject_id), env.session_id,
                                       lj_handle=env.handle, neon=env.neon_client,
                                       counterbalance_group=env.counterbalance_group)
    result = run_estimate(estimate_env, block_index, phase, checkpoint, trial_after,
                           presentation_pos=presentation_pos)
    if result.aborted:
        env.win.close()
        core.quit()


# ── entry point ───────────────────────────────────────────────────────────────

def run_block_trials(env: BlockEnv, block_index: int, phase: str,
                     block_schedule: List[dict], cumulative: dict,
                     presentation_pos: Optional[int] = None) -> None:
    """
    Run all trials for one block.

    block_index      : original block ID (phase and block_schedule must be this block's)
    presentation_pos : this block's position for this subject (0-based), for the log
    block_schedule : list of {'domain': str, 'char_order': list[str]
                              [, 'forced_first': str]}  (see task/forced_first.py)
    cumulative     : {'total', 'phase', <domain>...} running scores (mutated)
    File I/O is offloaded to a background thread during the following ITI.
    After the trials listed in config.estimate.ESTIMATE_CHECKPOINTS (7 and the
    last one) the attribute estimate runs before the next ITI; the end estimate
    is therefore the last thing a block does before returning to main().
    """
    trial_runner = TRIAL_RUNNERS[phase]
    slot_info    = env.factory.get_slot_info()
    win_size     = (int(env.win.size[0]), int(env.win.size[1]))
    save_thread  = None

    on_block_start(env.neon_client, env.handle, phase, block_index)

    for trial_index, trial_info in enumerate(block_schedule):
        domain       = trial_info['domain']
        char_order   = trial_info['char_order']
        forced_first = forced_first_for(trial_info)
        stim_pair_id = f"block{block_index}_{phase}_t{trial_index:02d}"
        frame_log    = make_frame_log(phase=phase, trial_id=trial_index, stim_pair_id=stim_pair_id)

        run_gaussian_iti(env.win, env.global_clock, frame_log)
        if save_thread:
            save_thread.join()

        result = trial_runner(
            env.win, env.global_clock, frame_log, env.factory, env.stim, domain, char_order,
            env.handle, neon_client=env.neon_client, forced_first=forced_first,
        )

        fb_score = _score_and_feedback(
            env, result, phase, domain, char_order, cumulative,
            trial_index, frame_log,
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
            first_choice_mode='forced' if forced_first is not None else 'free',
            forced_first_animal=forced_first,
            schedule_version=env.schedule_version,
            presentation_pos=presentation_pos,
            counterbalance_group=env.counterbalance_group,
        )
        save_dir = build_trial_save_dir(env.subject_id, block_index, phase, domain, stim_pair_id)
        save_trial_metadata(save_dir, record)

        save_thread = threading.Thread(
            target=_persist_trial,
            args=(env.subject_id, record, get_rows(frame_log), save_dir),
            daemon=True,
        )
        save_thread.start()

        # Attribute estimate after trial 7 (middle) and after the last trial (end).
        trial_number = trial_index + 1
        checkpoint = checkpoint_after_trial(trial_number)
        if checkpoint is not None:
            save_thread.join()      # this trial is on disk before the estimate starts
            save_thread = None
            run_block_estimate(env, block_index, phase, checkpoint, trial_number,
                                presentation_pos=presentation_pos)

    if save_thread:
        save_thread.join()

    save_experiment_summary(env.subject_id)
