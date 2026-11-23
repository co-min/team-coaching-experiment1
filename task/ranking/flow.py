"""
flow.py
-------
순위 화면 하나를 실행하고 RankingResult(최종 상태 + 이벤트 로그)를 돌려줍니다.

    run_sequential_ranking   기준(baseline) 순위 / 속성 순위: 1위부터 차례로 고르기
    show_change_screen       가상 변화 안내 화면
    run_revised_ranking      수정(counterfactual) 순위: 이전 순위에서 출발해 고치기

시간 기준
    rt       : 그 화면이 처음 나타난 flip(onset) 부터의 초 (키 입력 장치가 잼)
    t_global : 세션 전체 시계(global_clock) 기준 = onset_global + rt
키 입력 하나하나가 이벤트 로그 한 줄이 됩니다.
여기서는 파일을 쓰지 않습니다 — 저장은 record.py / recording/ranking_writers.py.
"""

from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Sequence

from psychopy import core, event

from config import ranking as R
from task.ranking.items import RankItem, RankingSpec
from task.ranking.state import RevisedRanking, SequentialRanking
from task.ranking.view import ChangeDisplay, RankingView, change_screen_stims, key_names
from task.trials.common import stamp_on_flip

# rankings.csv 의 status 열 값
COMPLETE, TIMEOUT, ABORTED = 'complete', 'timeout', 'aborted'


@dataclass
class RankingResult:
    """순위 화면 하나의 결과."""
    spec:          RankingSpec
    display_order: List[RankItem]           # sequential: 선택지 칸 순서(위→아래) / revised: 출발 순위
    initial:       List[RankItem]           # revised: 출발한 순위 / sequential: []
    final:         List[RankItem]           # 최종 순위, 1위가 맨 앞 (완료 전이면 일부만)
    status:        str = COMPLETE
    onset_global:  Optional[float] = None   # 화면이 나타난 global_clock 시각
    end_rt:        Optional[float] = None   # 제출 / 시간 초과 / 중단 시점의 rt
    key_backend:   str = ''
    events:        List[Dict] = field(default_factory=list)
    n_relocations: int = 0
    change_onset_global: Optional[float] = None   # revised 만: 가상 변화 화면이 나타난 시각
    change_rt:     Optional[float] = None         # revised 만: 가상 변화 화면에서 넘어간 rt

    @property
    def aborted(self) -> bool:
        return self.status == ABORTED


# ── 이벤트 로그 ───────────────────────────────────────────────────────────────

class _EventLog:
    """화면 하나의 이벤트 행 목록. 행의 열 순서가 곧 출력 파일의 열 순서입니다."""

    def __init__(self):
        self.rows: List[Dict] = []

    def add(self, event_name: str, rt: Optional[float], state: Sequence[RankItem], key=None, action=None,
            item: Optional[RankItem] = None, rank_pos=None, from_pos=None, to_pos=None, detail=None):
        """이벤트 한 줄을 추가합니다.

        event_name : 'onset', 'select', 'invalid', 'confirm' 등
        rt         : onset 부터의 초 (소수 5자리로 반올림해 저장)
        state      : 이 이벤트 "직후"의 순위 (ranking_state 열에 'A+B|C+D|...' 로 기록)
        key/action : 눌린 키와 그 동작 (키 입력이 아닌 이벤트면 None)
        item 등     : 동작의 대상과 위치 (state.py 의 outcome 에서 옴)
        """
        if rt is None:
            rounded_rt = None
        else:
            rounded_rt = round(rt, 5)

        if item:
            item_key = item.key
            item_animals = item.label
        else:
            item_key = None
            item_animals = None

        ranking_state = '|'.join(ranked_item.key for ranked_item in state)

        self.rows.append({
            'event_idx': len(self.rows), 'event': event_name, 'key': key, 'action': action,
            'rt': rounded_rt,
            'item': item_key, 'item_animals': item_animals,
            'rank_pos': rank_pos, 'from_pos': from_pos, 'to_pos': to_pos,
            'ranking_state': ranking_state, 'detail': detail,
        })


# outcome 사전에서 로그의 고유 열로 바로 가는 키들. 나머지는 'detail' 열로 갑니다.
_EVENT_COLUMNS = ('item', 'rank_pos', 'from_pos', 'to_pos')


def _fields(outcome: Dict) -> Dict:
    """state.py 의 outcome 사전 → _EventLog.add 에 넘길 키워드 인자.

    예) {'event': 'move', 'item': X, 'from_pos': 2, 'to_pos': 1, 'displaced': Y}
        → {'item': X, 'from_pos': 2, 'to_pos': 1, 'detail': 'displaced=A+B'}
    정해진 열이 아닌 키는 'key=value;key=value' 로 이어 붙여 detail 에 넣습니다.
    RankItem 값은 역할 키('A+B')로 바꿉니다. detail 이 비면 None.
    """
    log_fields = {}
    for column in _EVENT_COLUMNS:
        if column in outcome:
            log_fields[column] = outcome[column]

    detail_parts = []
    for name, value in outcome.items():
        if name in _EVENT_COLUMNS or name == 'event':
            continue
        if isinstance(value, RankItem):
            value = value.key
        detail_parts.append(f"{name}={value}")

    log_fields['detail'] = ';'.join(detail_parts) or None
    return log_fields


def _with_global(rows: List[Dict], onset: Optional[float]) -> List[Dict]:
    """각 행에 t_global(= onset + rt, 소수 5자리) 열을 덧붙입니다. rows 를 직접 고칩니다."""
    for row in rows:
        if onset is None or row['rt'] is None:
            row['t_global'] = None
        else:
            row['t_global'] = round(onset + row['rt'], 5)
    return rows


# ── 공통 화면 루프 ────────────────────────────────────────────────────────────

def _process_key_press(press, log: _EventLog, handle: Callable[[str, float], Optional[Dict]],
                       snapshot: Callable[[], List[RankItem]], can_confirm: Callable[[], bool]) -> Optional[str]:
    """키 입력 하나를 처리하고 로그에 한 줄 남깁니다.

    반환: 이 입력으로 화면이 끝나면 그 status (COMPLETE 또는 ABORTED), 아니면 None.

    처리 규칙
        대응표에 없는 키         → 'unmapped' 로그만
        quit (Esc)               → 'quit' 로그, 화면 중단 (ABORTED)
        confirm (Enter)          → 제출 가능하면 'confirm' 로그 후 완료 (COMPLETE)
                                   아니면 'invalid' 로그
        그 밖의 동작(up/down/...) → handle() 로 상태를 바꾸고 그 outcome 을 로그.
                                   지금 할 수 없는 동작이면(None) 'invalid' 로그
    """
    action = press.action

    if action is None:
        log.add('unmapped', press.rt, snapshot(), key=press.key)
        return None

    if action == 'quit':
        log.add('quit', press.rt, snapshot(), key=press.key, action=action)
        return ABORTED

    if action == 'confirm':
        if can_confirm():
            log.add('confirm', press.rt, snapshot(), key=press.key, action=action)
            return COMPLETE
        log.add('invalid', press.rt, snapshot(), key=press.key, action=action)
        return None

    outcome = handle(action, press.rt)
    if outcome is None:
        log.add('invalid', press.rt, snapshot(), key=press.key, action=action)
    else:
        log.add(outcome['event'], press.rt, snapshot(), key=press.key, action=action, **_fields(outcome))
    return None


def _time_is_up(source) -> bool:
    """제한 시간(R.RANKING_MAX_TIME)이 정해져 있고, 그 시간이 지났는지.

    R.RANKING_MAX_TIME 이 None 이면 제한 없음. (테스트에서 바꿀 수 있도록 매번 R 에서 읽음)
    """
    if not R.RANKING_MAX_TIME:
        return False
    return source.time() > R.RANKING_MAX_TIME


def _show_confirmation_feedback(win, draw: Callable[[bool], None]) -> None:
    """제출 직후, 확정된 순위를 R.CONFIRM_FEEDBACK_S 초 동안 보여 줍니다 (이 동안 입력 무시)."""
    clock = core.Clock()
    while clock.getTime() < R.CONFIRM_FEEDBACK_S:
        draw(True)
        win.flip()


def _run_screen(win, global_clock, source, draw: Callable[[bool], None],
                handle: Callable[[str, float], Optional[Dict]], snapshot: Callable[[], List[RankItem]],
                can_confirm: Callable[[], bool]) -> Dict:
    """두 순위 화면이 함께 쓰는 "그리기 → 키 읽기" 반복 루프.

    draw(confirmed)  : 현재 상태를 그림 (confirmed=True 면 제출 확인 모습)
    handle(action, rt): 동작을 상태에 적용하고 outcome 을 반환. 할 수 없는 동작이면 None
    snapshot()       : 현재 순위 목록 (로그의 ranking_state 열에 씀)
    can_confirm()    : 지금 제출할 수 있는지

    반환: {'status', 'onset', 'end_rt', 'rows'}
        onset  : 화면이 처음 나타난 flip 의 global_clock 시각
        end_rt : 화면을 끝낸 입력(제출/중단) 또는 시간 초과 시점의 rt
        rows   : 이벤트 로그 (t_global 은 아직 없음)

    타이밍: 첫 flip 순간에 (1) 키 입력 시계가 0 이 되고 (source.start)
            (2) onset 의 global 시각이 기록됩니다 (stamp_on_flip).
            그 뒤 매 반복마다 키를 읽고, 끝나지 않았으면 다시 그리고 flip 합니다.
    """
    log = _EventLog()
    onsets = {'onset': None}

    # ── 첫 화면 표시: 이전 화면의 키 입력을 버리고, 첫 flip 에 시계를 맞춤 ──
    event.clearEvents()
    source.start(win)
    stamp_on_flip(win, global_clock, onsets, 'onset')
    draw(False)
    win.flip()
    log.add('onset', 0.0, snapshot())

    # ── 반복: 키 읽기 → (시간 초과 확인) → 다시 그리기 ──
    status = None
    end_rt = None
    while status is None:
        for press in source.poll():
            status = _process_key_press(press, log, handle, snapshot, can_confirm)
            if status is not None:
                end_rt = press.rt
                # 같은 poll 에서 제출/중단 "뒤에" 들어온 입력은 적용하지 않습니다.
                break

        if status is None and _time_is_up(source):
            status = TIMEOUT
            end_rt = source.time()
            log.add('timeout', end_rt, snapshot())

        if status is None:
            draw(False)
            win.flip()

    # ── 끝: 제출했을 때만 확인 모습을 잠깐 보여 줌 ──
    if status == COMPLETE:
        _show_confirmation_feedback(win, draw)
    event.clearEvents()
    return {'status': status, 'onset': onsets['onset'], 'end_rt': end_rt, 'rows': log.rows}


def _item_kind(items: Sequence[RankItem]) -> str:
    """대상이 팀(역할 2개)이면 'pair', 동물 한 마리면 'animal'."""
    if len(items[0].roles) == 2:
        return 'pair'
    return 'animal'


# ── 화면별 실행 함수 ──────────────────────────────────────────────────────────

def run_sequential_ranking(win, global_clock, source, spec: RankingSpec, options: Sequence[RankItem],
                           prompt: str) -> RankingResult:
    """1위부터 차례로 골라 순위를 매기는 화면을 실행합니다.

    win, global_clock : PsychoPy 창과 세션 시계
    source            : 키 입력 장치 (inputs.KeySource 또는 ScriptedSource)
    spec              : 이 순위의 식별 정보
    options           : 선택지 표시 순서 (위 → 아래). 이미 섞여 있어야 합니다.
    prompt            : 맨 위 안내 문장
    반환               : RankingResult (완료 전에 끝나면 final 은 일부만)

    키: up/down = 커서 이동, select = 고르기, undo = 마지막 고른 것 취소,
        confirm = 모두 고른 뒤에만 제출
    """
    state = SequentialRanking(options)
    view = RankingView(win, len(options), _item_kind(options), spec.group, spec.domain, prompt, mode='sequential')

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

    def draw(confirmed):
        view.draw_sequential(state, confirmed)

    def snapshot():
        return list(state.ranking)

    def can_confirm():
        return state.complete

    screen = _run_screen(win, global_clock, source, draw=draw, handle=handle, snapshot=snapshot,
                         can_confirm=can_confirm)
    return RankingResult(spec=spec, display_order=list(options), initial=[], final=list(state.ranking),
                         status=screen['status'], onset_global=screen['onset'], end_rt=screen['end_rt'],
                         key_backend=source.backend, events=_with_global(screen['rows'], screen['onset']))


def run_revised_ranking(win, global_clock, source, spec: RankingSpec, initial: Sequence[RankItem],
                        prompt: str, change: ChangeDisplay) -> RankingResult:
    """이전 순위(initial, 1위가 맨 앞)에서 출발해 고치는 화면을 실행합니다.

    아무것도 바꾸지 않고 그대로 제출해도 됩니다.
    change : 화면 오른쪽에 보여 줄 가상 변화

    키: up/down = 커서 이동 (집은 상태면 대상을 한 칸 이동),
        select = 집기/내려놓기, undo = 마지막 한 칸 이동 취소,
        confirm = 아무것도 집고 있지 않을 때만 제출
    """
    state = RevisedRanking(initial)
    view = RankingView(win, len(initial), _item_kind(initial), spec.group, spec.domain, prompt,
                       mode='revised', change=change)

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

    def draw(confirmed):
        view.draw_revised(state, confirmed)

    def snapshot():
        return list(state.order)

    def can_confirm():
        return not state.held

    screen = _run_screen(win, global_clock, source, draw=draw, handle=handle, snapshot=snapshot,
                         can_confirm=can_confirm)
    return RankingResult(spec=spec, display_order=list(initial), initial=list(initial), final=list(state.order),
                         status=screen['status'], onset_global=screen['onset'], end_rt=screen['end_rt'],
                         key_backend=source.backend, events=_with_global(screen['rows'], screen['onset']),
                         n_relocations=state.n_relocations)


def show_change_screen(win, global_clock, source, change: ChangeDisplay, domain: Optional[str]) -> Dict:
    """가상 변화를 알려 주는 화면. select 또는 confirm 키로 넘어갑니다.

    반환: {'onset': 화면이 나타난 global 시각, 'rt': 넘어간 rt(소수 5자리), 'aborted': Esc 로 중단했는지}
    이 화면은 이벤트 로그를 남기지 않고, onset 과 rt 만 수정 순위 기록에 들어갑니다.
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
        for stim in stims:
            stim.draw()
        win.flip()
