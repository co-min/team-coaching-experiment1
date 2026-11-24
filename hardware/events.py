"""
events.py
---------
Unified event dispatcher — fires LabJack TTL and Neon section events from a
single call site so both timelines stay aligned.

Functions prefixed 'callonflip_' register callbacks for the next win.flip().
Functions prefixed 'on_' fire immediately (key-press responses, boundaries).

Phase integer mapping: 1 = phase_1, 2 = phase_2
"""

from typing import Optional

from hardware.labjack import (
    send_trigger,
    ANIMAL_IDX,
    TRIG_TASK_START,
    TRIG_P1_BLOCK_START, TRIG_P2_BLOCK_START,
    TRIG_P1_TRIAL_START, TRIG_P2_TRIAL_START,
    TRIG_P1_TRIAL_END,   TRIG_P2_TRIAL_END,
    TRIG_P1_CHOICE_ONSET, TRIG_P2_CHOICE_ONSET,
    TRIG_P1_CHOICE1, TRIG_P1_CHOICE2,
    TRIG_P2_CHOICE1, TRIG_P2_CHOICE2,
    TRIG_P1_FEEDBACK, TRIG_P2_FEEDBACK,
    TRIG_P1_ESTIMATE_START,    TRIG_P2_ESTIMATE_START,
    TRIG_P1_ESTIMATE_QUESTION, TRIG_P2_ESTIMATE_QUESTION,
    TRIG_P1_ESTIMATE_RESPONSE, TRIG_P2_ESTIMATE_RESPONSE,
    TRIG_P1_ESTIMATE_END,      TRIG_P2_ESTIMATE_END,
)
from hardware.neon import section_start_events, section_end_events

# ── Lookup tables ─────────────────────────────────────────────────────────────

PHASE_INT = {'phase_1': 1, 'phase_2': 2}

_BLOCK_START_TRIG = {'phase_1': TRIG_P1_BLOCK_START, 'phase_2': TRIG_P2_BLOCK_START}
_TRIAL_START_TRIG = {1: TRIG_P1_TRIAL_START, 2: TRIG_P2_TRIAL_START}
_TRIAL_END_TRIG   = {1: TRIG_P1_TRIAL_END,   2: TRIG_P2_TRIAL_END}
_FEEDBACK_TRIG    = {1: TRIG_P1_FEEDBACK,    2: TRIG_P2_FEEDBACK}

# (phase, slot) → LJ onset code. Missing keys = no LJ trigger (choice2 onset).
_CHOICE_ONSET_TRIG = {
    (1, 1): TRIG_P1_CHOICE_ONSET,
    (2, 1): TRIG_P2_CHOICE_ONSET,
}
_CHOICE_BASE = {
    (1, 1): TRIG_P1_CHOICE1, (1, 2): TRIG_P1_CHOICE2,
    (2, 1): TRIG_P2_CHOICE1, (2, 2): TRIG_P2_CHOICE2,
}


def choice_trigger_code(phase: int, slot: int, animal: str) -> Optional[int]:
    """Animal-encoded choice trigger code, or None if phase/slot/animal is unknown."""
    base = _CHOICE_BASE.get((phase, slot))
    idx  = ANIMAL_IDX.get(animal)
    if base is None or idx is None:
        return None
    return base + idx


# ── Session / Task ────────────────────────────────────────────────────────────

def on_task_start(neon, lj_handle) -> None:
    send_trigger(lj_handle, TRIG_TASK_START)
    neon.enqueue_events("TASK_START", metadata={"task_type": "experiment"})


# ── Block ─────────────────────────────────────────────────────────────────────

def on_block_start(neon, lj_handle, phase: str, block_index: int) -> None:
    """phase is 'phase_1' or 'phase_2'."""
    send_trigger(lj_handle, _BLOCK_START_TRIG.get(phase, 0))
    neon.enqueue_events(
        f"P{PHASE_INT.get(phase, 0)}_BLOCK_{block_index:02d}_START",
        metadata={"task_type": "block", "phase": phase, "trial_index": block_index},
    )


# ── Trial ─────────────────────────────────────────────────────────────────────

def callonflip_trial_start(win, neon, lj_handle, phase: int, trial_index: int) -> None:
    """Register trial-start events for the next win.flip() (domain-onset frame)."""
    win.callOnFlip(send_trigger, lj_handle, _TRIAL_START_TRIG[phase])
    neon.call_on_flip(
        win,
        section_start_events(trial_index, f"P{phase}_DOMAIN_ONSET", first=True),
        task_type="trial", phase=phase, trial_index=trial_index,
    )


def on_trial_end(neon, lj_handle, phase: int, trial_index: int) -> None:
    """Fire immediately after the last choice (or on timeout)."""
    send_trigger(lj_handle, _TRIAL_END_TRIG[phase])
    neon.enqueue_events(
        f"TRIAL_{trial_index:03d}_P{phase}_END",
        metadata={"task_type": "trial", "phase": phase, "trial_index": trial_index},
    )


# ── Choice onset (stimulus appears on screen) ─────────────────────────────────

def callonflip_choice_onset(win, neon, lj_handle, phase: int, trial_index: int, slot: int) -> None:
    """Register choice-onset events for the next win.flip().

    LabJack trigger is only sent for (phase, slot) entries in _CHOICE_ONSET_TRIG.
    """
    lj_code = _CHOICE_ONSET_TRIG.get((phase, slot))
    if lj_code is not None:
        win.callOnFlip(send_trigger, lj_handle, lj_code)
    neon.call_on_flip(
        win,
        section_start_events(trial_index, f"P{phase}_CHOICE{slot}"),
        task_type="trial", phase=phase, trial_index=trial_index,
    )


# ── Forced first choice (FIRST_CHOICE_MODE='forced') ──────────────────────────

def callonflip_forced_first_onset(win, neon, lj_handle, phase: int, trial_index: int, animal: str) -> None:
    """Register forced-first onset events for the next win.flip().

    In forced mode the animals first appear on the Choice 2 onset frame, with the
    assigned animal already locked, so that frame carries the existing
    choice-onset LJ code (P1 201 / P2 202) exactly as Choice 1 onset does in
    free mode. Neon gets a single assignment marker (no section of its own);
    register this before the Choice 2 onset so the marker precedes it.
    No animal-encoded choice code is ever sent for the assignment —
    it is not a participant response.
    """
    win.callOnFlip(send_trigger, lj_handle, _CHOICE_ONSET_TRIG[(phase, 1)])
    neon.call_on_flip(
        win,
        (f"TRIAL_{trial_index:03d}_P{phase}_FORCED_FIRST_{animal.upper()}_ASSIGNED",),
        task_type="trial", phase=phase, trial_index=trial_index,
    )


# ── Choice response ───────────────────────────────────────────────────────────

def on_choice_lj(lj_handle, phase: int, slot: int, animal: str) -> None:
    """Send LabJack animal-encoded choice trigger. Call immediately on key press."""
    send_trigger(lj_handle, _CHOICE_BASE[(phase, slot)] + ANIMAL_IDX[animal])


def on_choice_neon(
    neon, phase: int, trial_index: int, slot: int, animal: str,
    outcome: str = "RESPONSE",
) -> None:
    """Enqueue Neon choice+animal event immediately (no flip needed)."""
    label = f"P{phase}_CHOICE{slot}_{animal.upper()}_{outcome}"
    neon.enqueue_events(
        section_end_events(trial_index, label),
        metadata={"task_type": "trial", "phase": phase, "trial_index": trial_index},
    )


# ── Feedback ──────────────────────────────────────────────────────────────────

def callonflip_feedback(win, neon, lj_handle, phase: int, trial_index: int) -> None:
    """Register feedback-onset events for the next win.flip()."""
    win.callOnFlip(send_trigger, lj_handle, _FEEDBACK_TRIG.get(phase, 0))
    neon.call_on_flip(
        win,
        section_start_events(trial_index, f"P{phase}_FEEDBACK", first=True),
        task_type="feedback", phase=phase, trial_index=trial_index,
    )


# ── Attribute estimate (task/estimate) ────────────────────────────────────────
#
# phase is the ORIGINAL block's phase as an int (1 or 2), so the TTL code never
# depends on where the block was presented. Every Neon label starts with
#     P{phase}_BLOCK_{block_id:02d}_ESTIMATE_{CHECKPOINT}
# e.g. P1_BLOCK_00_ESTIMATE_MIDDLE_START, ..._Q03_ONSET, ..._Q03_HIGH_CONFIRM.
# The question number is 1-based (= presentation_order in estimates.csv) and is
# also logged as trial_index in the Neon event log; task_type is "estimate".
#
#   event              LabJack (P1/P2)  when
#   start              151 / 152        flip that shows the intro screen
#   question onset     161 / 162        flip that first shows the question
#   response confirm   171 / 172        Space press that confirms an answer
#   question timeout   — (Neon only)    no answer before ESTIMATE_MAX_TIME
#   question aborted   — (Neon only)    Esc during a question
#   end                181 / 182        after the last question, or right after Esc

_ESTIMATE_START_TRIG    = {1: TRIG_P1_ESTIMATE_START,    2: TRIG_P2_ESTIMATE_START}
_ESTIMATE_QUESTION_TRIG = {1: TRIG_P1_ESTIMATE_QUESTION, 2: TRIG_P2_ESTIMATE_QUESTION}
_ESTIMATE_RESPONSE_TRIG = {1: TRIG_P1_ESTIMATE_RESPONSE, 2: TRIG_P2_ESTIMATE_RESPONSE}
_ESTIMATE_END_TRIG      = {1: TRIG_P1_ESTIMATE_END,      2: TRIG_P2_ESTIMATE_END}


def estimate_label(phase: int, block_id: int, checkpoint: str) -> str:
    """Common start of every Neon label of one estimate, e.g. 'P2_BLOCK_03_ESTIMATE_END'."""
    return f"P{phase}_BLOCK_{block_id:02d}_ESTIMATE_{checkpoint.upper()}"


def question_label(phase: int, block_id: int, checkpoint: str, question_number: int) -> str:
    """Common start of the Neon labels of one question, e.g. 'P1_BLOCK_00_ESTIMATE_MIDDLE_Q01'."""
    return f"{estimate_label(phase, block_id, checkpoint)}_Q{question_number:02d}"


def callonflip_estimate_start(win, neon, lj_handle, phase: int, block_id: int, checkpoint: str) -> None:
    """Register estimate-start events for the next win.flip() (the intro screen)."""
    win.callOnFlip(send_trigger, lj_handle, _ESTIMATE_START_TRIG[phase])
    neon.call_on_flip(
        win,
        f"{estimate_label(phase, block_id, checkpoint)}_START",
        task_type="estimate", phase=phase, trial_index=None,
    )


def callonflip_estimate_question(win, neon, lj_handle, phase: int, block_id: int, checkpoint: str,
                                  question_number: int) -> None:
    """Register question-onset events for the next win.flip() (the question's first frame)."""
    win.callOnFlip(send_trigger, lj_handle, _ESTIMATE_QUESTION_TRIG[phase])
    neon.call_on_flip(
        win,
        f"{question_label(phase, block_id, checkpoint, question_number)}_ONSET",
        task_type="estimate", phase=phase, trial_index=question_number,
    )


def on_estimate_confirm(neon, lj_handle, phase: int, block_id: int, checkpoint: str,
                         question_number: int, response: str) -> None:
    """Fire immediately when Space confirms a response ('low' / 'mid' / 'high')."""
    send_trigger(lj_handle, _ESTIMATE_RESPONSE_TRIG[phase])
    neon.enqueue_events(
        f"{question_label(phase, block_id, checkpoint, question_number)}_{response.upper()}_CONFIRM",
        metadata={"task_type": "estimate", "phase": phase, "trial_index": question_number},
    )


def on_estimate_no_response(neon, phase: int, block_id: int, checkpoint: str,
                             question_number: int, status: str) -> None:
    """Neon only: a question ended without a confirmed answer. status is 'timeout' or 'aborted'."""
    neon.enqueue_events(
        f"{question_label(phase, block_id, checkpoint, question_number)}_{status.upper()}",
        metadata={"task_type": "estimate", "phase": phase, "trial_index": question_number},
    )


def on_estimate_end(neon, lj_handle, phase: int, block_id: int, checkpoint: str, outcome: str) -> None:
    """Fire immediately when the estimate is over. outcome is 'complete' or 'aborted'."""
    send_trigger(lj_handle, _ESTIMATE_END_TRIG[phase])
    neon.enqueue_events(
        f"{estimate_label(phase, block_id, checkpoint)}_END_{outcome.upper()}",
        metadata={"task_type": "estimate", "phase": phase, "trial_index": None},
    )
