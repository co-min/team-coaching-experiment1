"""
Phase 2 – Synergy Task

Trial flow
----------
domain onset → Choice 1 → Choice 1 locked, remaining animals coloured by
synergy with Choice 1 → Choice 2.
Forced mode replaces the Choice 1 response with a fixed-duration display of the
assigned (already locked) first animal.
"""

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


def _apply_synergy_colors(factory, char_list, pivot_idx, pivot_code, stim, also_hide_idx=None):
    """Color every non-pivot block by its synergy score with the pivot animal."""
    for i, char_name in enumerate(char_list):
        factory.border_stims[char_name].opacity = 0
        if i == pivot_idx or i == also_hide_idx:
            factory.block_stims[char_name].opacity = 0
            continue
        other_code = stim.char_code[char_name]
        score = stim.synergy.get(tuple(sorted([pivot_code, other_code])), 0)
        color = stim.synergy_color.get(score, 'white')
        factory.block_stims[char_name].setFillColor(color)
        factory.block_stims[char_name].opacity = 1


def _run_choice_loop(
    win, factory, keyboard, recorder, char_list, stim, handle,
    phase, slot, trial_index,
    excluded_idx=None,
    freeze_colors=False, confirm_freeze=0.15, show_confirm_overlay=False,
    neon_client=None,
):
    """Arrow-key preview + space-to-confirm loop.

    Fires callonflip_choice_onset on the first frame (LJ + Neon onset).
    Fires on_choice_lj + on_choice_neon immediately on space-press (response).
    Returns (chosen_idx, char_code, rt) or (None, None, None) on timeout.
    """
    response_clock  = core.Clock()
    preview_idx     = None
    _onset_pending  = True

    while True:
        confirmed_idx = confirmed_code = confirmed_rt = None

        for pressed, t in event.getKeys(keyList=keyboard.valid_keys + ['space', 'escape'], timeStamped=response_clock):
            if pressed == 'escape':
                win.close()
                core.quit()
            if pressed == 'space':
                if preview_idx is not None:
                    confirmed_idx  = preview_idx
                    confirmed_code = stim.char_code[char_list[preview_idx]]
                    confirmed_rt   = t
                    on_choice_lj(handle, phase, slot, char_list[preview_idx])
            else:
                keyboard.reset_colors()
                arrow_idx = keyboard.select(pressed, excluded_idx=excluded_idx)
                if arrow_idx is not None:
                    preview_idx = arrow_idx
                    if not freeze_colors:
                        _apply_synergy_colors(
                            factory, char_list, arrow_idx, stim.char_code[char_list[arrow_idx]], stim,
                            also_hide_idx=excluded_idx,
                        )
                    factory.border_stims[char_list[arrow_idx]].opacity = 0

        if confirmed_code is not None:
            on_choice_neon(neon_client, phase, trial_index, slot, char_list[confirmed_idx])
            factory.border_stims[char_list[confirmed_idx]].opacity = 0
            if show_confirm_overlay:
                factory.set_animal_locked(char_list[confirmed_idx], True)
            factory.draw_base_scene(phase_type='phase2')
            keyboard.draw()
            win.flip()
            core.wait(confirm_freeze)
            event.clearEvents()
            factory.draw_base_scene(phase_type='phase2')
            keyboard.draw()
            recorder.log_final(win, {'response': True})
            return confirmed_idx, confirmed_code, confirmed_rt

        if MAX_RESPONSE_TIME and response_clock.getTime() > MAX_RESPONSE_TIME:
            on_choice_neon(neon_client, phase, trial_index, slot, "", outcome="TIMEOUT")
            recorder.log_final(win, {'response': False})
            return None, None, None

        factory.draw_base_scene(phase_type='phase2')
        keyboard.draw()
        if _onset_pending:
            callonflip_choice_onset(win, neon_client, handle, phase, trial_index, slot)
            _onset_pending = False
        recorder.flip_and_log(win)


def run_phase2_trial(win, global_clock, frame_log, factory, stim, domain, char_order,
                     handle=None, neon_client=None, forced_first=None):
    """
    Run one Phase 2 trial.

    Parameters
    ----------
    win          : psychopy.visual.Window
    global_clock : psychopy.core.Clock  (experiment-wide)
    frame_log    : FrameLog dict (mutated in-place via FrameRecorder)
    factory      : task.visuals.VisualObjectFactory
    stim         : StimulusSet (uses synergy, synergy_color, char_code)
    domain       : str   'cooking' | 'repairing' | 'tennis'
    char_order   : list  [up_animal, down_animal, right_animal, left_animal]
    neon_client  : NeonEventClient | NullNeonClient (optional)
    forced_first : animal name → forced mode (Choice 1 is assigned, rt1 = None);
                   None → free mode

    Returns
    -------
    dict  {'choice1': char_code, 'choice2': char_code, 'rt1': float | None, 'rt2': float,
           'forced_first_onset': float | None, 'choice2_onset': float}
    or None on timeout
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
        phase=2,
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
            win, factory, keyboard, recorder, char_list, stim,
            handle, phase=2, slot=1, trial_index=trial_index,
            freeze_colors=True,
            neon_client=neon_client,
        )
        if choice1_code is None:
            on_trial_end(neon_client, handle, 2, trial_index)
            return None
    else:
        choice1_idx, choice1_code, rt1 = char_list.index(forced_first), stim.char_code[forced_first], None
        show_forced_first(
            win, factory, keyboard, recorder, handle,
            phase=2, neon_client=neon_client, trial_index=trial_index,
            forced_idx=choice1_idx, duration=FORCED_FIRST_DURATION,
            global_clock=global_clock, onsets=onsets,
        )

    # Lock Choice 1; seed synergy colours for Choice 2 resting state
    factory.set_animal_locked(char_list[choice1_idx], True)
    _apply_synergy_colors(factory, char_list, choice1_idx, choice1_code, stim)

    # ── Choice 2 ──────────────────────────────────────────────────────────────
    recorder.start_segment("CHOICE2")
    keyboard.reset_colors()
    keyboard.set_excluded(choice1_idx)
    stamp_on_flip(win, global_clock, onsets, 'choice2_onset')
    _, choice2_code, rt2 = _run_choice_loop(
        win, factory, keyboard, recorder, char_list, stim,
        handle, phase=2, slot=2, trial_index=trial_index,
        excluded_idx=choice1_idx,
        freeze_colors=True,
        confirm_freeze=1.0,
        show_confirm_overlay=True,
        neon_client=neon_client,
    )
    if choice2_code is None:
        on_trial_end(neon_client, handle, 2, trial_index)
        return None

    on_trial_end(neon_client, handle, 2, trial_index)
    return {'choice1': choice1_code, 'choice2': choice2_code, 'rt1': rt1, 'rt2': rt2, **onsets}
