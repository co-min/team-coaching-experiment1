"""
run.py
------
Runs one appraisal (the middle or end appraisal of one block) and saves every answer.

    AppraisalEnv        what an appraisal needs from the session (window, clock, keys, output folder)
    make_appraisal_env  builds an AppraisalEnv with the real keyboard and the original attribute tables
    ItemResponse        what happened on one question
    AppraisalResult     all questions of one appraisal
    run_appraisal       intro screen → each question → its row is saved right away
    build_appraisal_row ItemResponse → one appraisals.csv row

One question, step by step (_run_question)
    1. show the stimulus and the question; nothing is highlighted yet
    2. an arrow key highlights LOW / MEDIUM / HIGH (can be changed any number of times)
    3. Space confirms the highlighted response (ignored while nothing is highlighted)
    4. the confirmed button stays filled in for CONFIRM_FEEDBACK_S, the same for right and wrong answers
    5. the row is saved and the next question starts. There is no way back.

Timing (same as task/ranking/flow.py)
    rt     : seconds since the question first appeared on screen (its first flip),
             measured by the key source (PsychoPy Keyboard, PTB backend when available)
    global : session clock time = onset_global + rt

LabJack / Neon events (hardware/events.py, codes P1 / P2 from the ORIGINAL block's phase)
    intro screen flip        151 / 152   ..._APPRAISAL_{CHECKPOINT}_START
    question's first flip    161 / 162   ..._Q{nn}_ONSET          (same flip as onset_global)
    Space confirms           171 / 172   ..._Q{nn}_{LOW|MID|HIGH}_CONFIRM
    timeout / Esc            Neon only   ..._Q{nn}_TIMEOUT / ..._Q{nn}_ABORTED
    appraisal over           181 / 182   ..._END_COMPLETE / ..._END_ABORTED
"""

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from psychopy import core, event

from config import appraisal as A
from config import settings as S
from config.strings import domain_name, t
from hardware.events import (
    PHASE_INT, callonflip_appraisal_question, callonflip_appraisal_start, on_appraisal_confirm, on_appraisal_end,
    on_appraisal_no_response,
)
from hardware.neon import NullNeonClient
from recording.appraisal_writers import append_appraisal_row
from recording.stimuli_loader import LEVELS, StimulusSet
from task.appraisal.items import (
    SYNERGY, AppraisalItem, appraisal_id, appraisal_type_for_phase, build_appraisal_items, is_correct, item_counter,
)
from task.appraisal.view import AppraisalView
from task.forced_first import BLOCK_TYPE
from task.ranking.items import Attributes, load_attributes
from task.ranking.view import key_names
from task.screens.instructions import show_instructions
from task.trials.common import stamp_on_flip

# Values of the 'status' column
COMPLETE, TIMEOUT, ABORTED = 'complete', 'timeout', 'aborted'


@dataclass
class AppraisalEnv:
    """Everything an appraisal needs from the running session. Not changed by the appraisal.

    source    : key input, task.ranking.inputs.KeySource (or ScriptedSource in tests),
                built with config.appraisal.APPRAISAL_KEYS
    attrs     : original attribute values (decimals kept), the ground truth
    lj_handle : LabJack handle; None sends no TTL (hardware.labjack.send_trigger)
    neon      : NeonEventClient, or NullNeonClient (the default) to send no Neon events
    """
    win:          Any
    global_clock: Any
    source:       Any
    stim:         StimulusSet
    attrs:        Attributes
    subject_id:   str
    subject_dir:  Path                      # appraisals.csv is written here
    session_id:   Optional[str] = None
    lj_handle:    Any = None
    neon:         Any = field(default_factory=NullNeonClient)
    counterbalance_group: Optional[str] = None   # 'A' | 'B' (task.schedule.counterbalance_group)


def make_appraisal_env(win, global_clock, stim: StimulusSet, subject_id: str, subject_dir: Path,
                       session_id: Optional[str] = None, lj_handle=None, neon=None,
                       counterbalance_group: Optional[str] = None) -> AppraisalEnv:
    """AppraisalEnv with the real keyboard and the ground truth read from the original tables."""
    from task.ranking.inputs import KeySource
    if neon is None:
        neon = NullNeonClient()
    return AppraisalEnv(win=win, global_clock=global_clock, source=KeySource(A.APPRAISAL_KEYS), stim=stim,
                        attrs=load_attributes(stim.synergy), subject_id=subject_id, subject_dir=subject_dir,
                        session_id=session_id, lj_handle=lj_handle, neon=neon,
                        counterbalance_group=counterbalance_group)


@dataclass
class ItemResponse:
    """What happened on one question.

    status            : 'complete' (confirmed), 'timeout', or 'aborted' (Esc)
    response          : confirmed 'low' / 'mid' / 'high' (None unless complete)
    response_rt       : rt of the confirm key press (None unless complete)
    first_press_rt    : rt of the first arrow key press (None if no arrow was pressed)
    selection_history : every highlight in order, e.g. ['low@1.2034', 'mid@1.8521']
    onset_global      : session-clock time the question appeared
    end_rt            : rt at which the question ended (confirm, timeout or Esc)
    """
    status:            str
    response:          Optional[str] = None
    response_rt:       Optional[float] = None
    first_press_rt:    Optional[float] = None
    selection_history: List[str] = field(default_factory=list)
    onset_global:      Optional[float] = None
    end_rt:            Optional[float] = None


@dataclass
class AppraisalResult:
    """All questions of one appraisal. responses[i] belongs to items[i].

    responses is shorter than items if the participant aborted (Esc).
    """
    appraisal_id:   str
    appraisal_type: str
    checkpoint:     str
    items:          List[AppraisalItem]
    responses:      List[ItemResponse] = field(default_factory=list)
    aborted:        bool = False


# ── one question ──────────────────────────────────────────────────────────────

def _run_question(env: AppraisalEnv, view: AppraisalView,
                  phase: int, block_index: int, checkpoint: str, question_number: int) -> ItemResponse:
    """Show the question prepared in `view` and wait until it is confirmed, times out or is aborted.

    phase, block_index, checkpoint, question_number only label the LabJack / Neon events
    (phase as an int, 1 or 2; question_number 1-based).
    """
    onsets = {'onset': None}
    selected = None
    first_press_rt = None
    history = []

    # First frame: drop keys pressed earlier, then on this one flip start the rt clock,
    # stamp onset_global and send the question-onset TTL + Neon event.
    event.clearEvents()
    env.source.start(env.win)
    stamp_on_flip(env.win, env.global_clock, onsets, 'onset')
    callonflip_appraisal_question(env.win, env.neon, env.lj_handle, phase, block_index, checkpoint,
                                  question_number)
    view.draw(selected)
    env.win.flip()

    while True:
        for press in env.source.poll():
            if press.action == 'quit':
                on_appraisal_no_response(env.neon, phase, block_index, checkpoint, question_number, ABORTED)
                return ItemResponse(ABORTED, first_press_rt=first_press_rt, selection_history=history,
                                    onset_global=onsets['onset'], end_rt=press.rt)

            if press.action in LEVELS:
                selected = press.action
                if first_press_rt is None:
                    first_press_rt = press.rt
                history.append(f"{press.action}@{press.rt:.4f}")

            elif press.action == 'confirm' and selected is not None:
                # Events first, so they are as close to the key press as possible.
                on_appraisal_confirm(env.neon, env.lj_handle, phase, block_index, checkpoint, question_number,
                                     selected)
                _show_confirmed(env.win, view, selected)
                return ItemResponse(COMPLETE, response=selected, response_rt=press.rt,
                                    first_press_rt=first_press_rt, selection_history=history,
                                    onset_global=onsets['onset'], end_rt=press.rt)

            # Anything else (an unmapped key, or confirm with nothing highlighted) is ignored.

        # Read from the module each time so tests can change the limit.
        if A.APPRAISAL_MAX_TIME and env.source.time() > A.APPRAISAL_MAX_TIME:
            on_appraisal_no_response(env.neon, phase, block_index, checkpoint, question_number, TIMEOUT)
            return ItemResponse(TIMEOUT, first_press_rt=first_press_rt, selection_history=history,
                                onset_global=onsets['onset'], end_rt=env.source.time())

        view.draw(selected)
        env.win.flip()


def _show_confirmed(win, view: AppraisalView, selected: str) -> None:
    """Keep the confirmed response on screen briefly (key presses during this time are dropped)."""
    clock = core.Clock()
    while clock.getTime() < A.CONFIRM_FEEDBACK_S:
        view.draw(selected, confirmed=True)
        win.flip()


def _question_texts(item: AppraisalItem, items: List[AppraisalItem], position: int) -> Dict[str, str]:
    """Title, progress counter and question for items[position], in the current language."""
    counter = item_counter(items, position)
    if item.appraisal_type == SYNERGY:
        return {
            'title':    t("appraisal_title_synergy"),
            'counter':  t("appraisal_counter_pair", n=counter['n'], total=counter['total']),
            'question': t("appraisal_question_synergy"),
        }
    return {
        'title':    t("appraisal_title_competence"),
        'counter':  t("appraisal_counter_animal", n=counter['n'], total=counter['total']),
        'question': t("appraisal_question_competence", domain=domain_name(item.domain)),
    }


def _show_intro(win, appraisal_type: str, checkpoint: str) -> None:
    """Instruction screen before the first question. Advances with the confirm key."""
    keys = key_names(A.APPRAISAL_KEYS)
    text = t(f"appraisal_intro_{appraisal_type}", checkpoint=t(f"appraisal_checkpoint_{checkpoint}"),
             low=keys['low'], mid=keys['mid'], high=keys['high'], confirm=keys['confirm'])
    show_instructions(win, text, advance_key=A.APPRAISAL_KEYS['confirm'][0])


# ── saving ────────────────────────────────────────────────────────────────────

def _rounded(value: Optional[float]) -> Optional[float]:
    if value is None:
        return None
    return round(value, 5)


def build_appraisal_row(env: AppraisalEnv, block_index: int, phase: str, checkpoint: str, trial_after: int,
                        items: List[AppraisalItem], position: int, response: ItemResponse,
                        presentation_pos: Optional[int] = None) -> Dict[str, Any]:
    """One appraisals.csv row for items[position]. Column order: recording/appraisal_writers.py.

    block_idx is the original block ID; presentation_pos is where this participant saw
    the block (0-based, None when run outside the block loop, e.g. the preview).

    Not-applicable cells are None (empty in the CSV):
        synergy    → domain, animal_id, animal_name
        competence → pair_id, pair_animals
    """
    item = items[position]

    if item.appraisal_type == SYNERGY:
        animal_name = None
        pair_animals = '+'.join(item.animals)
    else:
        animal_name = item.animals[0]
        pair_animals = None

    if response.status == COMPLETE and response.onset_global is not None:
        confirm_global = _rounded(response.onset_global + response.response_rt)
    else:
        confirm_global = None

    return {
        "subject_id":         env.subject_id,
        "session_id":         env.session_id,
        "counterbalance_group": env.counterbalance_group,
        "appraisal_id":       appraisal_id(block_index, checkpoint),
        "block_idx":          block_index,
        "presentation_pos":   presentation_pos,
        "phase":              phase,
        "block_type":         BLOCK_TYPE.get(phase, phase),
        "checkpoint":         checkpoint,
        "trial_after":        trial_after,
        "appraisal_type":     item.appraisal_type,
        "n_items":            len(items),
        "presentation_order": position + 1,
        "domain":             item.domain,
        "animal_id":          item.animal_id,
        "animal_name":        animal_name,
        "pair_id":            item.pair_id,
        "pair_animals":       pair_animals,
        "display_animals":    '|'.join(item.display_animals),
        "status":             response.status,
        "response":           response.response,
        "response_rt":        _rounded(response.response_rt),
        "first_press_rt":     _rounded(response.first_press_rt),
        "n_presses":          len(response.selection_history),
        "selection_history":  ';'.join(response.selection_history) or None,
        "onset_global":       _rounded(response.onset_global),
        "confirm_global":     confirm_global,
        "key_backend":        env.source.backend,
        "true_attribute_value": item.true_value,
        "true_attribute_level": item.true_level,
        "correct":            is_correct(response.response, item.true_level),
        "timestamp":          datetime.now().isoformat(timespec='seconds'),
    }


# ── entry point ───────────────────────────────────────────────────────────────

def run_appraisal(env: AppraisalEnv, block_index: int, phase: str, checkpoint: str, trial_after: int,
                  show_intro: bool = True, presentation_pos: Optional[int] = None) -> AppraisalResult:
    """Run one appraisal from the intro screen to the last question.

    block_index      : original block ID (picks the block's animals, labels the events)
    phase            : the original block's phase. It decides the appraisal type (the hidden
                       attribute) and the TTL codes (P1 / P2)
    checkpoint       : 'middle' or 'end' (config.appraisal.APPRAISAL_CHECKPOINTS)
    trial_after      : learning trial number this appraisal follows (7, 15), for the log
    show_intro       : False skips the instruction screen (tests); the start event then
                       goes out on the first question's flip
    presentation_pos : this block's position for this participant (0-based), for the log

    Side effect: each question's row is appended to appraisals.csv as soon as the
    question ends, so earlier answers are kept even if the session stops.
    Esc saves the current question as 'aborted' and stops (result.aborted = True);
    the caller decides what to do next.
    """
    appraisal_type = appraisal_type_for_phase(phase)
    group = env.stim.animal_groups[block_index]
    this_id = appraisal_id(block_index, checkpoint)
    # Seeded by subject and appraisal: reproducible, and different at middle and end.
    items = build_appraisal_items(appraisal_type, group, env.stim, env.attrs, seed=f"{env.subject_id}|{this_id}",
                                  domains=A.COMPETENCE_APPRAISAL_DOMAINS)

    phase_number = PHASE_INT[phase]
    view = AppraisalView(env.win, group, S.DOMAINS)

    # Start event on the next flip: the intro screen, or the first question without an intro.
    callonflip_appraisal_start(env.win, env.neon, env.lj_handle, phase_number, block_index, checkpoint)
    if show_intro:
        _show_intro(env.win, appraisal_type, checkpoint)

    result = AppraisalResult(appraisal_id=this_id, appraisal_type=appraisal_type, checkpoint=checkpoint,
                             items=items)
    for position, item in enumerate(items):
        texts = _question_texts(item, items, position)
        view.set_question(texts['title'], texts['counter'], texts['question'], item.display_animals, item.domain)

        question_number = position + 1
        response = _run_question(env, view, phase_number, block_index, checkpoint, question_number)
        row = build_appraisal_row(env, block_index, phase, checkpoint, trial_after, items, position, response,
                                  presentation_pos=presentation_pos)
        append_appraisal_row(env.subject_dir, row)
        result.responses.append(response)

        if response.status == ABORTED:
            result.aborted = True
            break

    # A timed-out question does not make the appraisal aborted: only Esc does.
    if result.aborted:
        outcome = ABORTED
    else:
        outcome = COMPLETE
    on_appraisal_end(env.neon, env.lj_handle, phase_number, block_index, checkpoint, outcome)

    event.clearEvents()
    return result
