"""
inputs.py
---------
순위 화면의 키 입력. 실제로 눌린 키(예: 'space')를 논리적 동작(예: 'select')으로
바꿉니다. 키 ↔ 동작 대응표는 config/ranking.py 의 RANKING_KEYS 입니다.

    KeySource       psychopy.hardware.keyboard.Keyboard 사용.
                    PTB backend 가 있으면 키가 눌린 시각이 화면 갱신(flip) 주기와
                    무관하게 정확히 기록됩니다.
    ScriptedSource  미리 정한 (시각, 키) 목록을 재생합니다 (테스트·자동 미리보기용).

두 클래스 모두 KeyPress.rt 를 "화면이 처음 나타난 flip" 기준의 초 단위로 줍니다.
start(win) 을 부르면 다음 win.flip() 순간에 반응 시계가 0 으로 맞춰집니다.
MRI 응답 버튼 박스를 쓰려면 같은 start()/poll()/time()/backend 를 가진 클래스를
하나 더 만들기만 하면 됩니다.
"""

from dataclasses import dataclass
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from config.ranking import RANKING_KEYS

# 'confirm'(제출) 키는 이 동작들과 같은 키를 쓰면 안 됩니다.
# 같은 키라면 "고르기"를 하려다 의도치 않게 제출해 버릴 수 있기 때문입니다.
_EXCLUSIVE_WITH_CONFIRM = ('select', 'undo', 'up', 'down')


@dataclass(frozen=True)
class KeyPress:
    """키 입력 하나.

    key    : 실제 키 이름 (예: 'space')
    action : 대응하는 동작 이름. 대응표에 없는 키면 None (그래도 로그에는 남김)
    rt     : 화면이 나타난 flip 부터 키가 눌릴 때까지의 시간(초)
    """
    key:    str
    action: Optional[str]
    rt:     float


def action_map(key_map: Mapping[str, Sequence[str]] = RANKING_KEYS) -> Dict[str, str]:
    """{동작: [키, ...]} 대응표를 뒤집어 {키: 동작} 사전을 만듭니다.

    잘못된 대응표면 ValueError 를 냅니다.
        - 한 키가 두 동작에 쓰인 경우
        - 'confirm' 이 select / undo / up / down 과 키를 공유하는 경우
    """
    action_by_key: Dict[str, str] = {}
    for action, keys in key_map.items():
        for key in keys:
            if key in action_by_key:
                raise ValueError(f"key {key!r} mapped to both {action_by_key[key]!r} and {action!r}")
            action_by_key[key] = action

    confirm_keys = set(key_map.get('confirm', ()))
    for action in _EXCLUSIVE_WITH_CONFIRM:
        action_keys = set(key_map.get(action, ()))
        if confirm_keys & action_keys:
            raise ValueError(f"'confirm' must not share keys with {action!r}")
    return action_by_key


class KeySource:
    """실제 키보드 입력 (PsychoPy Keyboard)."""

    def __init__(self, key_map: Mapping[str, Sequence[str]] = RANKING_KEYS, keyboard=None):
        """key_map  : {동작: [키, ...]}
        keyboard : 테스트용으로 바꿔 끼울 Keyboard 객체. 없으면 새로 만듭니다.
        """
        from psychopy.hardware import keyboard as ptb_keyboard
        self._actions = action_map(key_map)
        self._kb = keyboard or ptb_keyboard.Keyboard()

    @property
    def backend(self) -> str:
        """사용 중인 키보드 backend 이름 (예: 'ptb'). 결과 파일에 기록됩니다."""
        return str(self._kb.getBackend())

    def start(self, win) -> None:
        """새 화면을 시작할 때 부릅니다.

        다음 win.flip() 순간에 반응 시계를 0 으로 맞추고, 그 전에 눌린 키를 버립니다.
        """
        self._kb.clearEvents()
        win.callOnFlip(self._on_onset)

    def _on_onset(self) -> None:
        """화면이 나타난 flip 순간에 호출됩니다."""
        self._kb.clock.reset()
        self._kb.clearEvents()

    def time(self) -> float:
        """화면이 나타난 뒤 지난 시간(초)."""
        return self._kb.clock.getTime()

    def poll(self) -> List[KeyPress]:
        """지난 poll 이후 눌린 키들을 순서대로 돌려줍니다.

        대응표에 없는 키도 모두 읽어서(action=None) 모든 입력이 로그에 남도록 합니다.
        waitRelease=False: 키를 "누른" 순간 바로 받습니다 (뗄 때까지 기다리지 않음).
        """
        presses = []
        for pressed_key in self._kb.getKeys(waitRelease=False):
            action = self._actions.get(pressed_key.name)
            presses.append(KeyPress(pressed_key.name, action, float(pressed_key.rt)))
        return presses


class ScriptedSource:
    """미리 정한 키 입력을 재생합니다 (테스트·자동 미리보기용).

    scripts : 화면별 스크립트의 목록. 각 스크립트는 [(rt, key), ...] 이고,
              rt 는 그 화면이 나타난 flip 부터의 초입니다.
    start() 를 부를 때마다 다음 화면의 스크립트를 하나 꺼내 씁니다.
    키는 rt 가 지난 뒤 처음 poll() 할 때 전달되며, rt 값은 스크립트의 값 그대로입니다.
    """

    backend = 'scripted'

    def __init__(self, scripts: Iterable[Sequence[Tuple[float, str]]],
                 key_map: Mapping[str, Sequence[str]] = RANKING_KEYS):
        from psychopy import core
        self._actions = action_map(key_map)
        self._scripts = [list(script) for script in scripts]
        self._pending: List[Tuple[float, str]] = []   # 현재 화면에서 아직 전달하지 않은 키
        self._clock = core.Clock()

    def start(self, win) -> None:
        """다음 화면의 스크립트를 꺼내고, 다음 flip 에 시계를 0 으로 맞춥니다."""
        if self._scripts:
            self._pending = self._scripts.pop(0)
        else:
            self._pending = []
        win.callOnFlip(self._clock.reset)

    def time(self) -> float:
        """화면이 나타난 뒤 지난 시간(초)."""
        return self._clock.getTime()

    def poll(self) -> List[KeyPress]:
        """rt 가 이미 지난 키들을 꺼내 돌려줍니다."""
        now = self._clock.getTime()
        due = []
        not_yet = []
        for scripted_rt, key in self._pending:
            if scripted_rt <= now:
                due.append((scripted_rt, key))
            else:
                not_yet.append((scripted_rt, key))
        self._pending = not_yet

        presses = []
        for scripted_rt, key in due:
            presses.append(KeyPress(key, self._actions.get(key), float(scripted_rt)))
        return presses
