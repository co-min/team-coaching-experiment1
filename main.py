"""
Team-managing task — entry point.

    session setup → (practice) → blocks (phase_1 / phase_2 alternating) → ending

Mode, language, timing and hardware switches: config/settings.py
Mode presets (tables, domains, trial counts, block order): config/modes.py
"""

from psychopy import core

from config import settings as S
from config.modes import get_config
from config.strings import t
from hardware.events import on_task_start
from hardware.frame_marker import init_marker
from hardware.labjack import close_labjack
from hardware.neon import save_neon_event_log
from recording.stimuli_loader import load_stimuli
from recording.writers import get_subject_dir, save_session_metadata
from task.block import BlockEnv, run_block_trials
from task.practice.practice import run_practice
from task.schedule import generate_block_schedules
from task.screens.ending import run_ending
from task.screens.instructions import show_instructions
from task.session import start_session
from task.visuals import VisualObjectFactory


def main() -> None:
    cfg  = get_config(S.MISSION_MODE)
    stim = load_stimuli(cfg)

    ctx = start_session()
    win = ctx.win
    global_clock = core.Clock()
    init_marker(win)

    if S.PRACTICE_MODE:
        run_practice(win, cfg.competence_color, stim.synergy_color)

    factory = VisualObjectFactory(win, stim.animal_groups, cfg.domains)
    save_session_metadata(
        subject_id=ctx.subject_id,
        session_id=ctx.session_id,
        win_size=(int(win.size[0]), int(win.size[1])),
        mission_mode=cfg.mode,
        win_fullscr=S.WINDOW_FULLSCR,
        monitor_name=S.MONITOR_NAME,
        frame_rate=S.FRAME_RATE,
        slot_info=factory.get_slot_info(),
        neon_recording_id=ctx.neon_recording_id,
    )

    env = BlockEnv(
        win=win, global_clock=global_clock, factory=factory, stim=stim,
        subject_id=ctx.subject_id, handle=ctx.handle, neon_client=ctx.neon_client,
    )
    block_schedules = generate_block_schedules(cfg, stim.animal_groups)
    cumulative = {'total': 0, 'phase': 0, **{d: 0 for d in cfg.domains}}
    n_blocks = len(cfg.block_phases)

    try:
        on_task_start(ctx.neon_client, ctx.handle)

        for block_index, (phase, schedule) in enumerate(zip(cfg.block_phases, block_schedules)):
            if (block_index + 1) in S.BREAK_BEFORE_BLOCKS:
                show_instructions(win, t("inst_break"), advance_key="t")
            instruction = t("inst_phase1") if phase == 'phase_1' else t("inst_phase2")
            show_instructions(win, instruction.format(block_num=block_index + 1, total_blocks=n_blocks))

            cumulative['phase'] = 0
            for d in cfg.domains:
                cumulative[d] = 0

            run_block_trials(env, block_index, phase, cfg.phase(phase), schedule, cumulative)

        run_ending(win, ctx.subject_id, cumulative['total'],
                   score_csv=cfg.phase('phase_1').score_csv,
                   elapsed_seconds=global_clock.getTime())
    finally:
        ctx.neon_client.close(S.NEON_SHUTDOWN_FLUSH_TIMEOUT_S)
        save_neon_event_log(get_subject_dir(ctx.subject_id), ctx.neon_client.event_log)
        close_labjack(ctx.handle)

    win.close()
    core.quit()


if __name__ == "__main__":
    main()
