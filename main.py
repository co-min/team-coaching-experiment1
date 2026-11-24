"""
Team-managing task — entry point.

    session setup → blocks in the subject's counterbalance order → ending
    each block: trials 1–7 → middle estimate → trials 8–15 → end estimate

Block order: group A (odd subject ID) / B (even) from config.settings.BLOCK_ORDERS.
    presentation_pos (0–5) → block number on screen, BREAK_BEFORE_BLOCKS
    block_id         (0–5) → phase, animals, trials, forced first choices,
                             estimate type, ranking domain, probe order

Task design, language, timing and hardware switches: config/settings.py
"""

from psychopy import core

from config import settings as S
from config.strings import t
from hardware.events import on_task_start
from hardware.frame_marker import init_marker
from hardware.labjack import close_labjack
from hardware.neon import save_neon_event_log
from recording.stimuli_loader import load_stimuli
from recording.writers import get_subject_dir, save_session_metadata
from task.block import BlockEnv, run_block_trials
from task.forced_first import attach_forced_first
from task.schedule import block_order, block_order_problems, generate_block_schedules, presentation_order_problems
from task.screens.ending import run_ending
from task.screens.instructions import show_instructions
from task.session import start_session
from task.visuals import VisualObjectFactory


def _build_schedules(stim):
    """Seeded block schedules (+ fixed forced-first CSV in forced mode) and its version."""
    block_schedules = generate_block_schedules(stim.animal_groups)
    if S.FIRST_CHOICE_MODE == 'free':
        return block_schedules, None
    if S.FIRST_CHOICE_MODE == 'forced':
        return block_schedules, attach_forced_first(block_schedules, stim.animal_groups, stim.char_code)
    raise ValueError(f"FIRST_CHOICE_MODE must be 'free' or 'forced', got {S.FIRST_CHOICE_MODE!r}")


def _check_block_orders() -> None:
    """Stop before the window opens if a group's block order breaks a counterbalancing rule."""
    problems = block_order_problems(S.BLOCK_ORDERS, len(S.BLOCK_PHASES))
    if not problems:   # the next check needs valid block IDs
        problems = presentation_order_problems(S.BLOCK_ORDERS, S.BLOCK_PHASES)
    if problems:
        raise SystemExit("Block order check failed:\n  " + "\n  ".join(problems))


def run_blocks(env: BlockEnv, block_schedules, cumulative: dict) -> None:
    """Run every block in this subject's counterbalance order.

    block_schedules is indexed by the ORIGINAL block ID, so it is looked up with
    block_id, never with presentation_pos.
    """
    order = block_order(env.counterbalance_group)
    for presentation_pos, block_id in enumerate(order):
        run_block(env, block_id, presentation_pos, len(order), block_schedules[block_id], cumulative)
        # Performance + counterfactual ranking go here, after the end estimate
        # (task.ranking.assessments.run_block_rankings(..., block_id, presentation_pos)).
        # Not wired in yet: the probe conditions are still placeholders (tools/preview_ranking.py).


def run_block(env: BlockEnv, block_id: int, presentation_pos: int, n_blocks: int,
              schedule, cumulative: dict) -> None:
    """One block: break / phase instruction → trials 1–7 → middle estimate → trials 8–15 → end estimate.

    schedule must be block_schedules[block_id]. Also used by tools/test_single_block.py.
    """
    phase = S.BLOCK_PHASES[block_id]           # from the original block
    block_number = presentation_pos + 1        # what the participant sees: 1 … n_blocks

    if block_number in S.BREAK_BEFORE_BLOCKS:
        show_instructions(env.win, t("inst_break"), advance_key="t")
    if phase == 'phase_1':
        instruction = t("inst_phase1")
    else:
        instruction = t("inst_phase2")
    if S.FIRST_CHOICE_MODE == 'forced':
        forced_note = t("inst_forced_note")
    else:
        forced_note = ""
    show_instructions(env.win, instruction.format(block_num=block_number, total_blocks=n_blocks,
                                                  forced_note=forced_note))

    cumulative['phase'] = 0
    for d in S.DOMAINS:
        cumulative[d] = 0

    # Trials 1–7 → middle estimate → trials 8–15 → end estimate (all inside run_block_trials)
    run_block_trials(env, block_id, phase, schedule, cumulative, presentation_pos=presentation_pos)


def main() -> None:
    stim = load_stimuli()
    # Before opening the window: an invalid forced-first CSV or block order aborts here.
    block_schedules, schedule_version = _build_schedules(stim)
    _check_block_orders()

    ctx = start_session()
    win = ctx.win
    global_clock = core.Clock()
    init_marker(win)

    factory = VisualObjectFactory(win, stim.animal_groups, S.DOMAINS)
    save_session_metadata(
        subject_id=ctx.subject_id,
        session_id=ctx.session_id,
        win_size=(int(win.size[0]), int(win.size[1])),
        mission_mode=4,   # legacy field kept for v3-compatible output; modes were removed
        win_fullscr=S.WINDOW_FULLSCR,
        monitor_name=S.MONITOR_NAME,
        frame_rate=S.FRAME_RATE,
        slot_info=factory.get_slot_info(),
        neon_recording_id=ctx.neon_recording_id,
        first_choice_mode=S.FIRST_CHOICE_MODE,
        schedule_version=schedule_version,
        counterbalance_group=ctx.counterbalance_group,
        block_order=list(block_order(ctx.counterbalance_group)),
    )

    env = BlockEnv(
        win=win, global_clock=global_clock, factory=factory, stim=stim,
        subject_id=ctx.subject_id, handle=ctx.handle, neon_client=ctx.neon_client,
        schedule_version=schedule_version, session_id=ctx.session_id,
        counterbalance_group=ctx.counterbalance_group,
    )
    cumulative = {'total': 0, 'phase': 0, **{d: 0 for d in S.DOMAINS}}

    try:
        on_task_start(ctx.neon_client, ctx.handle)
        run_blocks(env, block_schedules, cumulative)
        run_ending(win, ctx.subject_id, cumulative['total'],
                    max_trial_score=stim.max_trial_score,
                    elapsed_seconds=global_clock.getTime())
    finally:
        ctx.neon_client.close(S.NEON_SHUTDOWN_FLUSH_TIMEOUT_S)
        save_neon_event_log(get_subject_dir(ctx.subject_id), ctx.neon_client.event_log)
        close_labjack(ctx.handle)

    win.close()
    core.quit()


if __name__ == "__main__":
    main()
