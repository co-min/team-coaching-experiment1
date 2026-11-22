"""Shared trial utilities used across Phase 1 and Phase 2."""

from psychopy import event, core

from hardware.events import callonflip_trial_start, callonflip_forced_first_onset


def stamp_on_flip(win, global_clock, onsets: dict, *keys: str) -> None:
    """Store global_clock time of the next win.flip() in onsets[key] for each key."""
    win.callOnFlip(lambda: onsets.update(dict.fromkeys(keys, global_clock.getTime())))


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


def mark_forced_first(win, handle, phase: int, neon_client, trial_index, animal: str) -> None:
    """Forced mode: register the assignment events for the Choice 2 onset flip.

    There is no separate forced display — Choice 2 opens with the assigned
    animal already locked and the hints shown, so the assignment and the
    participant's own choice are distinguishable from the first frame.
    The caller stamps forced_first_onset together with choice2_onset (same flip).
    """
    callonflip_forced_first_onset(win, neon_client, handle, phase, trial_index, animal)
