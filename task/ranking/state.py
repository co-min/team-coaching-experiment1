"""
state.py
--------
순위 화면의 "상태"를 관리합니다. 키보드나 화면과는 무관합니다.

화면(flow.py)이 키 입력을 아래 메서드 호출로 바꿔 줍니다. 각 메서드는
    - 동작이 성공하면: 무엇이 일어났는지 담은 outcome 사전 (로그 한 줄이 됨)
    - 지금 할 수 없는 동작이면: None (로그에 'invalid' 로 기록됨)
을 돌려줍니다.

    SequentialRanking  1위부터 차례로 하나씩 골라 순위를 채움 (되돌리기 가능)
    RevisedRanking     이전 순위에서 출발해, 대상을 집어서 옮기고 내려놓음

outcome 사전의 키 이름(event, item, rank_pos, from_pos, to_pos 및 그 밖의 키)은
그대로 로그 열이 되므로 바꾸면 안 됩니다. 정해진 열에 없는 키(예: displaced,
relocated)는 로그의 'detail' 열에 'key=value' 형태로 들어갑니다.
위치(rank_pos, from_pos, to_pos)는 로그에서 1부터 셉니다 (내부 인덱스 + 1).
"""

from typing import Dict, List, Optional, Sequence

from task.ranking.items import RankItem

# 메서드 반환값: 로그용 사전, 또는 허용되지 않은 동작이면 None
Outcome = Optional[Dict[str, object]]


class SequentialRanking:
    """1위부터 차례대로 하나씩 고르는 순위.

    화면 오른쪽 "선택지" 열의 각 대상은 처음 표시된 칸(slot)에 고정되어 있습니다.
    대상을 고르면 그 칸은 빈칸(None)이 되고, 대상은 왼쪽 "나의 순위" 맨 뒤에 붙습니다.

    options : 칸별 대상 목록. 이미 고른 칸은 None
    ranking : 지금까지 고른 순위 (1위가 맨 앞)
    cursor  : 커서가 가리키는 칸 번호. 고를 대상이 없으면 None
    """

    def __init__(self, options: Sequence[RankItem]):
        self.options: List[Optional[RankItem]] = list(options)

        # 되돌리기(undo) 때 대상을 원래 칸으로 돌려놓기 위해 처음 칸 번호를 기억합니다.
        self._origin: Dict[RankItem, int] = {}
        for slot, item in enumerate(options):
            self._origin[item] = slot

        self.ranking: List[RankItem] = []

        if options:
            self.cursor: Optional[int] = 0
        else:
            self.cursor = None

    @property
    def n(self) -> int:
        """전체 대상 수."""
        return len(self._origin)

    @property
    def complete(self) -> bool:
        """모든 대상을 다 골랐는지."""
        return len(self.ranking) == self.n

    def _next_available(self, start: int, step: int) -> Optional[int]:
        """start 칸(포함)부터 step 방향으로 가며 처음 만나는 빈칸이 아닌 칸.

        끝에 닿으면 반대쪽 끝으로 돌아갑니다(wrap). 남은 대상이 없으면 None.
        """
        for k in range(self.n):
            slot = (start + step * k) % self.n
            if self.options[slot] is not None:
                return slot
        return None

    def move(self, step: int) -> Outcome:
        """커서를 위(-1) 또는 아래(+1)로 옮깁니다. 빈칸은 건너뜁니다.

        움직일 곳이 없으면(남은 대상이 0개 또는 1개) None.
        """
        if self.cursor is None:
            return None
        new_cursor = self._next_available(self.cursor + step, step)
        if new_cursor is None or new_cursor == self.cursor:
            return None
        self.cursor = new_cursor
        return {'event': 'cursor', 'item': self.options[new_cursor], 'from_pos': None, 'to_pos': new_cursor + 1}

    def place(self) -> Outcome:
        """커서 아래 대상을 다음 순위로 확정합니다.

        커서는 아래쪽으로 다음 남은 대상으로 이동합니다 (맨 아래면 맨 위로).
        """
        if self.cursor is None:
            return None
        item = self.options[self.cursor]
        self.options[self.cursor] = None
        self.ranking.append(item)
        self.cursor = self._next_available(self.cursor, 1)
        return {'event': 'select', 'item': item, 'rank_pos': len(self.ranking)}

    def undo(self) -> Outcome:
        """마지막으로 고른 대상을 원래 칸으로 되돌리고, 커서도 그 칸으로 옮깁니다."""
        if not self.ranking:
            return None
        item = self.ranking.pop()
        original_slot = self._origin[item]
        self.options[original_slot] = item
        self.cursor = original_slot
        # rank_pos: 되돌리기 전에 이 대상이 있던 순위
        return {'event': 'undo', 'item': item, 'rank_pos': len(self.ranking) + 1}


class RevisedRanking:
    """이전 순위에서 출발해 고치는 순위 (가상 변화 뒤의 수정 순위).

    두 가지 모드가 있습니다.
        집지 않음(held=False) : 위/아래 키로 커서만 이동
        집음(held=True)       : 위/아래 키를 누를 때마다 집은 대상이 이웃과
                                자리를 한 칸 바꿉니다 (커서도 대상을 따라감)

    "집기 구간(episode)" = 한 번 집었다가 내려놓을 때까지.
    되돌리기(undo)는 한 칸 이동을 하나씩 취소합니다.

    initial       : 출발한 순위 (바뀌지 않음)
    order         : 현재 순위 (1위가 맨 앞)
    cursor        : 커서 위치 (0부터)
    held          : 지금 대상을 집고 있는지
    n_relocations : 내려놓았을 때 집은 자리와 다른 곳에 놓인 횟수
    """

    def __init__(self, initial: Sequence[RankItem]):
        self.initial: List[RankItem] = list(initial)
        self.order: List[RankItem] = list(initial)
        self.cursor = 0
        self.held = False

        # 한 칸 이동마다 (출발 인덱스, 도착 인덱스, 집기 구간 번호)를 기록합니다.
        self._history: List[tuple] = []
        self._episode = 0                         # 지금까지 집은 횟수 = 현재 집기 구간 번호
        self._pickup_index: Optional[int] = None  # 지금 집은 대상을 집었던 위치
        self.n_relocations = 0

    @property
    def changed(self) -> bool:
        """처음 순위와 달라졌는지."""
        return self.order != self.initial

    def move(self, step: int) -> Outcome:
        """위(-1)/아래(+1) 키. 맨 위·맨 아래를 넘어가면 None (돌아가지 않음).

        집지 않았으면 커서만 움직이고('cursor'),
        집었으면 대상을 이웃과 맞바꿉니다('move').
        """
        new_index = self.cursor + step
        if new_index < 0 or new_index >= len(self.order):
            return None

        if not self.held:
            self.cursor = new_index
            return {'event': 'cursor', 'item': self.order[new_index], 'to_pos': new_index + 1}

        old_index = self.cursor
        self._swap(old_index, new_index)
        self.cursor = new_index
        self._history.append((old_index, new_index, self._episode))
        return {'event': 'move', 'item': self.order[new_index], 'from_pos': old_index + 1,
                'to_pos': new_index + 1, 'displaced': self.order[old_index]}

    def toggle_hold(self) -> Outcome:
        """선택 키. 집고 있지 않으면 집고('pick_up'), 집고 있으면 내려놓습니다('put_down')."""
        item = self.order[self.cursor]

        if not self.held:
            self.held = True
            self._pickup_index = self.cursor
            self._episode += 1
            return {'event': 'pick_up', 'item': item, 'rank_pos': self.cursor + 1}

        self.held = False
        # 집었던 자리와 다른 곳에 내려놓았을 때만 "재배치"로 셉니다.
        relocated = self.cursor != self._pickup_index
        if relocated:
            self.n_relocations += 1
        outcome = {'event': 'put_down', 'item': item, 'from_pos': self._pickup_index + 1,
                   'to_pos': self.cursor + 1, 'relocated': relocated}
        self._pickup_index = None
        return outcome

    def undo(self) -> Outcome:
        """마지막 한 칸 이동을 되돌립니다. 커서(와 집기 상태)는 대상을 따라갑니다.

        대상을 집고 있는 동안에는 "지금 집기 구간"의 이동만 되돌릴 수 있습니다.
        (예전에 내려놓은 다른 대상을 몰래 옮기지 않도록)
        """
        if not self._history:
            return None
        last_episode = self._history[-1][2]
        if self.held and last_episode != self._episode:
            return None

        old_index, new_index, _ = self._history.pop()
        self._swap(old_index, new_index)
        self.cursor = old_index
        return {'event': 'undo', 'item': self.order[old_index], 'from_pos': new_index + 1,
                'to_pos': old_index + 1}

    def _swap(self, first_index: int, second_index: int) -> None:
        """order 의 두 자리를 맞바꿉니다."""
        first_item = self.order[first_index]
        self.order[first_index] = self.order[second_index]
        self.order[second_index] = first_item
