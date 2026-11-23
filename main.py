"""
Team-managing task — entry point.

    session setup → blocks (phase_1 / phase_2 alternating) → ending

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
from task.schedule import generate_block_schedules
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


def main() -> None:
    stim = load_stimuli()
    # Before opening the window: an invalid forced-first CSV aborts here.
    block_schedules, schedule_version = _build_schedules(stim)

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
    )

    env = BlockEnv(
        win=win, global_clock=global_clock, factory=factory, stim=stim,
        subject_id=ctx.subject_id, handle=ctx.handle, neon_client=ctx.neon_client,
        schedule_version=schedule_version,
    )
    cumulative = {'total': 0, 'phase': 0, **{d: 0 for d in S.DOMAINS}}
    n_blocks = len(S.BLOCK_PHASES)

    try:
        on_task_start(ctx.neon_client, ctx.handle)

        for block_index, (phase, schedule) in enumerate(zip(S.BLOCK_PHASES, block_schedules)):
            if (block_index + 1) in S.BREAK_BEFORE_BLOCKS:
                show_instructions(win, t("inst_break"), advance_key="t")
            instruction = t("inst_phase1") if phase == 'phase_1' else t("inst_phase2")
            forced_note = t("inst_forced_note") if S.FIRST_CHOICE_MODE == 'forced' else ""
            show_instructions(win, instruction.format(block_num=block_index + 1, total_blocks=n_blocks,
                                                    forced_note=forced_note))

            cumulative['phase'] = 0
            for d in S.DOMAINS:
                cumulative[d] = 0

            run_block_trials(env, block_index, phase, schedule, cumulative)

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
