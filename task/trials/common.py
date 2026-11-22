"""Shared trial utilities used across Phase 1 and Phase 2."""

from psychopy import event, core

from hardware.events import (
    callonflip_trial_start, callonflip_forced_first_onset, on_forced_first_end_neon,
)


def stamp_on_flip(win, global_clock, onsets: dict, key: str) -> None:
    """Store global_clock time of the next win.flip() in onsets[key]."""
    win.callOnFlip(lambda: onsets.__setitem__(key, global_clock.getTime()))


def show_domain_onset(
    win, factory, recorder, handle,
    phase: int,
    neon_client, trial_index,
    duration,
):
    """Domain 이미지만 표시하는 onset 구간.

    첫 flip에서 LabJack TRIAL_START + Neon DOMAIN_ONSET 섹션을 동시에 등록.
    duration 경과 후 이벤트 버퍼를 비우고 반환.
    """
    clock = core.Clock()
    _pending = True

    recorder.start_segment("DOMAIN_ONSET")

    while clock.getTime() < duration:
        factory.draw_domain_only()
        if _pending:
            callonflip_trial_start(win, neon_client, handle, phase, trial_index)
            _pending = False
        recorder.flip_and_log(win)

    event.clearEvents()


def show_forced_first(
    win, factory, keyboard, recorder, handle,
    phase: int,
    neon_client, trial_index,
    forced_idx: int,
    duration,
    global_clock, onsets: dict,
):
    """Forced mode: show all animals with the assigned first animal already locked.

    Replaces the Choice 1 response loop. The animal is locked (overlay + arrow
    marked) from the first frame and keys are ignored; any key pressed during
    the display is discarded so it cannot leak into Choice 2.
    First flip: LJ choice-onset code + Neon FORCED_FIRST section, and
    onsets['forced_first_onset'] (global clock).
    """
    animal     = factory.char_list[forced_idx]
    phase_type = f'phase{phase}'
    clock      = core.Clock()
    _pending   = True

    recorder.start_segment("FORCED_FIRST")
    factory.set_animal_locked(animal, True)
    keyboard.reset_colors()
    keyboard.set_excluded(forced_idx)

    while clock.getTime() < duration:
        if event.getKeys(keyList=['escape']):
            win.close()
            core.quit()
        factory.draw_base_scene(phase_type=phase_type)
        keyboard.draw()
        if _pending:
            callonflip_forced_first_onset(win, neon_client, handle, phase, trial_index)
            stamp_on_flip(win, global_clock, onsets, 'forced_first_onset')
            _pending = False
        recorder.flip_and_log(win)

    on_forced_first_end_neon(neon_client, phase, trial_index, animal)
    event.clearEvents()
