"""
flow.py
-------
Run one ranking screen and return a RankingResult (state + event log).

    run_sequential_ranking   baseline / attribute rankings
    show_change_screen       hypothetical change announcement
    run_revised_ranking      counterfactual ranking, starts from a previous ranking

Every key press becomes one event row; the time base is the screen's onset
flip (rt) plus the session global_clock (t_global = onset_global + rt).
Nothing is written to disk here — see task/ranking/record.py.
"""

from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Sequence

from psychopy import core, event

from config import ranking as R
from task.ranking.items import RankItem, RankingSpec
from task.ranking.state import RevisedRanking, SequentialRanking
from task.ranking.view import ChangeDisplay, RankingView, change_screen_stims, key_names
from task.trials.common import stamp_on_flip

# Status values written to rankings.csv
COMPLETE, TIMEOUT, ABORTED = 'complete', 'timeout', 'aborted'


@dataclass
class RankingResult:
    spec:          RankingSpec
    display_order: List[RankItem]           # sequential: option slots top→bottom; revised: initial
    initial:       List[RankItem]           # revised: the ranking it started from; sequential: []
    final:         List[RankItem]           # best first (partial if not complete)
    status:        str = COMPLETE
    onset_global:  Optional[float] = None
    end_rt:        Optional[float] = None   # rt of the confirm / timeout / quit
    key_backend:   str = ''
    events:        List[Dict] = field(default_factory=list)
    n_relocations: int = 0
    change_onset_global: Optional[float] = None
    change_rt:     Optional[float] = None

    @property
    def aborted(self) -> bool:
        return self.status == ABORTED


class _EventLog:
    def __init__(self):
        self.rows: List[Dict] = []

    def add(self, event_name: str, rt: Optional[float], state: Sequence[RankItem], key=None, action=None,
            item: Optional[RankItem] = None, rank_pos=None, from_pos=None, to_pos=None, detail=None):
        self.rows.append({
            'event_idx': len(self.rows), 'event': event_name, 'key': key, 'action': action,
            'rt': None if rt is None else round(rt, 5),
            'item': item.key if item else None, 'item_animals': item.label if item else None,
            'rank_pos': rank_pos, 'from_pos': from_pos, 'to_pos': to_pos,
            'ranking_state': '|'.join(it.key for it in state), 'detail': detail,
        })


_EVENT_COLUMNS = ('item', 'rank_pos', 'from_pos', 'to_pos')


def _fields(outcome: Dict) -> Dict:
    """State outcome → _EventLog.add kwargs; anything extra goes to 'detail'."""
    extra = {k: (v.key if isinstance(v, RankItem) else v) for k, v in outcome.items()
             if k not in _EVENT_COLUMNS and k != 'event'}
    return {**{k: outcome[k] for k in _EVENT_COLUMNS if k in outcome},
            'detail': ';'.join(f"{k}={v}" for k, v in extra.items()) or None}


def _run_screen(win, global_clock, source, draw: Callable[[bool], None],
                handle: Callable[[str, float], Optional[Dict]], snapshot: Callable[[], List[RankItem]],
                can_confirm: Callable[[], bool]) -> Dict:
    """Shared flip/poll loop. Returns {'status', 'onset', 'end_rt', 'rows'}.

    handle(action, rt) applies an action and returns its outcome dict, or None
    if the action is not allowed now (logged as 'invalid').
    """
    log = _EventLog()
    onsets = {'onset': None}
    event.clearEvents()
    source.start(win)
    stamp_on_flip(win, global_clock, onsets, 'onset')
    draw(False)
    win.flip()
    log.add('onset', 0.0, snapshot())

    status, end_rt = None, None
    while status is None:
        for press in source.poll():
            a = press.action
            if a is None:
                log.add('unmapped', press.rt, snapshot(), key=press.key)
            elif a == 'quit':
                status, end_rt = ABORTED, press.rt
                log.add('quit', press.rt, snapshot(), key=press.key, action=a)
            elif a == 'confirm':
                if can_confirm():
                    status, end_rt = COMPLETE, press.rt
                    log.add('confirm', press.rt, snapshot(), key=press.key, action=a)
                else:
                    log.add('invalid', press.rt, snapshot(), key=press.key, action=a)
            else:
                out = handle(a, press.rt)
                if out is None:
                    log.add('invalid', press.rt, snapshot(), key=press.key, action=a)
                else:
                    log.add(out['event'], press.rt, snapshot(), key=press.key, action=a, **_fields(out))
            if status is not None:
                break   # presses after confirm / quit in the same poll are not applied

        if status is None and R.RANKING_MAX_TIME and source.time() > R.RANKING_MAX_TIME:
            status, end_rt = TIMEOUT, source.time()
            log.add('timeout', end_rt, snapshot())

        if status is None:
            draw(False)
            win.flip()

    if status == COMPLETE:
        clock = core.Clock()
        while clock.getTime() < R.CONFIRM_FEEDBACK_S:
            draw(True)
            win.flip()
    event.clearEvents()
    return {'status': status, 'onset': onsets['onset'], 'end_rt': end_rt, 'rows': log.rows}


def _with_global(rows: List[Dict], onset: Optional[float]) -> List[Dict]:
    for r in rows:
        r['t_global'] = None if onset is None or r['rt'] is None else round(onset + r['rt'], 5)
    return rows


def run_sequential_ranking(win, global_clock, source, spec: RankingSpec, options: Sequence[RankItem],
                           prompt: str) -> RankingResult:
    """Pick from highest to lowest. *options* is the display order (top → bottom)."""
    state = SequentialRanking(options)
    view = RankingView(win, len(options), 'pair' if len(options[0].roles) == 2 else 'animal',
                       spec.group, spec.domain, prompt, mode='sequential')

    def handle(action, _rt):
        if action == 'up':
            return state.move(-1)
        if action == 'down':
            return state.move(+1)
        if action == 'select':
            return state.place()
        if action == 'undo':
            return state.undo()
        return None

    out = _run_screen(win, global_clock, source,
                      draw=lambda confirmed: view.draw_sequential(state, confirmed),
                      handle=handle, snapshot=lambda: list(state.ranking),
                      can_confirm=lambda: state.complete)
    return RankingResult(spec=spec, display_order=list(options), initial=[], final=list(state.ranking),
                         status=out['status'], onset_global=out['onset'], end_rt=out['end_rt'],
                         key_backend=source.backend, events=_with_global(out['rows'], out['onset']))


def run_revised_ranking(win, global_clock, source, spec: RankingSpec, initial: Sequence[RankItem],
                        prompt: str, change: ChangeDisplay) -> RankingResult:
    """Start from *initial* (best first); submitting unchanged is allowed."""
    state = RevisedRanking(initial)
    view = RankingView(win, len(initial), 'pair' if len(initial[0].roles) == 2 else 'animal',
                       spec.group, spec.domain, prompt, mode='revised', change=change)

    def handle(action, _rt):
        if action == 'up':
            return state.move(-1)
        if action == 'down':
            return state.move(+1)
        if action == 'select':
            return state.toggle_hold()
        if action == 'undo':
            return state.undo()
        return None

    out = _run_screen(win, global_clock, source,
                      draw=lambda confirmed: view.draw_revised(state, confirmed),
                      handle=handle, snapshot=lambda: list(state.order),
                      can_confirm=lambda: not state.held)
    return RankingResult(spec=spec, display_order=list(initial), initial=list(initial), final=list(state.order),
                         status=out['status'], onset_global=out['onset'], end_rt=out['end_rt'],
                         key_backend=source.backend, events=_with_global(out['rows'], out['onset']),
                         n_relocations=state.n_relocations)


def show_change_screen(win, global_clock, source, change: ChangeDisplay, domain: Optional[str]) -> Dict:
    """Announce the hypothetical change; continue on select or confirm.

    Returns {'onset': global time, 'rt': continue time, 'aborted': bool}.
    """
    names = key_names()
    stims = change_screen_stims(win, change, domain, continue_key=names['select'])
    onsets = {'onset': None}
    event.clearEvents()
    source.start(win)
    stamp_on_flip(win, global_clock, onsets, 'onset')
    while True:
        for press in source.poll():
            if press.action in ('select', 'confirm', 'quit'):
                event.clearEvents()
                return {'onset': onsets['onset'], 'rt': round(press.rt, 5), 'aborted': press.action == 'quit'}
        for s in stims:
            s.draw()
        win.flip()
