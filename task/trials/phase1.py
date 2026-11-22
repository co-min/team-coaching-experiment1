"""Phase 1 – Competence Task (Arrow → animal mapping)"""

from psychopy import event, core

from config.settings import MAX_RESPONSE_TIME, DOMAIN_ONSET_DURATION, FORCED_FIRST_DURATION
from hardware.frame_marker import get_shared_marker
from recording.frame_logger import FrameRecorder
from task.keyboard import ArrowKeyboard
from hardware.events import (
    callonflip_choice_onset,
    on_choice_lj, on_choice_neon,
    on_trial_end,
)
from task.trials.common import show_domain_onset as _show_domain_onset, show_forced_first, stamp_on_flip


def _run_choice_loop(
    win, factory, keyboard, recorder, char_list, char_code, handle,
    phase, slot, trial_index,
    excluded_idx=None, locked_idx=None, confirm_wait=0.15, lock_on_confirm=False,
    show_hover_border=True,
    neon_client=None,
):
    """Arrow-key preview + space-to-confirm loop.

    Fires callonflip_choice_onset on the first frame (LJ + Neon onset).
    Fires on_choice_lj + on_choice_neon immediately on space-press (response).
    Returns (chosen_idx, char_code, rt) or (None, None, None) on timeout.
    """
    response_clock   = core.Clock()
    preview_idx      = None
    _onset_pending   = True

    while True:
        for pressed, t in event.getKeys(keyList=keyboard.valid_keys + ['space', 'escape'], timeStamped=response_clock):
            if pressed == 'escape':
                win.close()
                core.quit()
            if pressed == 'space':
                if preview_idx is not None:
                    animal      = char_list[preview_idx]
                    chosen_code = char_code[animal]
                    on_choice_lj(handle, phase, slot, animal)
                    on_choice_neon(neon_client, phase, trial_index, slot, animal)
                    if lock_on_confirm:
                        factory.set_animal_locked(animal, True)
                    factory.draw_base_scene(phase_type='phase1')
                    keyboard.draw()
                    win.flip()
                    core.wait(confirm_wait)
                    event.clearEvents()
                    factory.draw_base_scene(phase_type='phase1')
                    keyboard.draw()
                    recorder.log_final(win, {'response': True})
                    return preview_idx, chosen_code, t
            else:
                keyboard.reset_colors()
                arrow_idx = keyboard.select(pressed, excluded_idx=excluded_idx)
                if arrow_idx is not None:
                    preview_idx = arrow_idx
                    for name in char_list:
                        factory.hide_border(name)
                    if locked_idx is not None:
                        factory.show_border(char_list[locked_idx])
                    if show_hover_border:
                        factory.show_border(char_list[arrow_idx])

        if MAX_RESPONSE_TIME and response_clock.getTime() > MAX_RESPONSE_TIME:
            on_choice_neon(neon_client, phase, trial_index, slot, "", outcome="TIMEOUT")
            recorder.log_final(win, {'response': False})
            return None, None, None

        factory.draw_base_scene(phase_type='phase1')
        keyboard.draw()
        if _onset_pending:
            callonflip_choice_onset(win, neon_client, handle, phase, trial_index, slot)
            _onset_pending = False
        recorder.flip_and_log(win)


def run_phase1_trial(win, global_clock, frame_log, factory, stim, domain, char_order,
                     handle=None, neon_client=None, forced_first=None):
    """
    Run one Phase 1 trial.

    factory      : task.visuals.VisualObjectFactory
    stim         : recording.stimuli_loader.StimulusSet (uses competence, char_code)
    forced_first : animal name → forced mode (Choice 1 is assigned, rt1 = None);
                   None → free mode

    Returns dict {'choice1', 'choice2', 'rt1', 'rt2', 'forced_first_onset',
    'choice2_onset'} or None on timeout.
    """
    trial_index = frame_log.get("trial_id", 0)

    event.clearEvents()
    factory.apply_layout(char_order)
    char_list = factory.char_list
    factory.update_domain(domain)
    factory.reset_ui_states()

    keyboard = ArrowKeyboard(win, pos=(0, factory.center_y))
    recorder = FrameRecorder(frame_log, global_clock, photodiode=get_shared_marker())

    # ── Domain onset ──────────────────────────────────────────────────────────
    _show_domain_onset(
        win, factory, recorder, handle,
        phase=1,
        neon_client=neon_client,
        trial_index=trial_index,
        duration=DOMAIN_ONSET_DURATION,
    )
    onsets = {'forced_first_onset': None, 'choice2_onset': None}

    # ── Choice 1 ──────────────────────────────────────────────────────────────
    if forced_first is None:
        recorder.start_segment("CHOICE1")
        keyboard.reset_colors()
        choice1_idx, choice1_code, rt1 = _run_choice_loop(
            win, factory, keyboard, recorder, char_list, stim.char_code, handle,
            phase=1, slot=1, trial_index=trial_index,
            confirm_wait=0.15,
            show_hover_border=False,
            neon_client=neon_client,
        )
        if choice1_code is None:
            on_trial_end(neon_client, handle, 1, trial_index)
            return None
    else:
        choice1_idx, choice1_code, rt1 = char_list.index(forced_first), stim.char_code[forced_first], None
        show_forced_first(
            win, factory, keyboard, recorder, handle,
            phase=1, neon_client=neon_client, trial_index=trial_index,
            forced_idx=choice1_idx, duration=FORCED_FIRST_DURATION,
            global_clock=global_clock, onsets=onsets,
        )

    for char_name in char_list:
        score = stim.competence[stim.char_code[char_name]][domain]
        factory.set_border_color(char_name, stim.comp_color(score))
        factory.hide_border(char_name)

    # ── Choice 2 ──────────────────────────────────────────────────────────────
    factory.set_animal_locked(char_list[choice1_idx], True)
    recorder.start_segment("CHOICE2")
    keyboard.reset_colors()
    keyboard.set_excluded(choice1_idx)
    factory.show_border(char_list[choice1_idx])

    stamp_on_flip(win, global_clock, onsets, 'choice2_onset')
    _, choice2_code, rt2 = _run_choice_loop(
        win, factory, keyboard, recorder, char_list, stim.char_code, handle,
        phase=1, slot=2, trial_index=trial_index,
        excluded_idx=choice1_idx, locked_idx=choice1_idx,
        confirm_wait=1.0, lock_on_confirm=True,
        neon_client=neon_client,
    )
    if choice2_code is None:
        on_trial_end(neon_client, handle, 1, trial_index)
        return None

    on_trial_end(neon_client, handle, 1, trial_index)
    return {'choice1': choice1_code, 'choice2': choice2_code, 'rt1': rt1, 'rt2': rt2, **onsets}
