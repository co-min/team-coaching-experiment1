"""
inputs.py
---------
Key input for the ranking screens, mapped to logical actions
(config/ranking.py RANKING_KEYS).

    KeySource       psychopy.hardware.keyboard.Keyboard (PTB backend when
                    available: key-down timestamps independent of the frame loop)
    ScriptedSource  replays (time, key) pairs for tests and automated previews

Both report KeyPress.rt in seconds relative to the screen onset flip:
start(win) resets the clock on the next win.flip(). An MRI response box only
needs another class with the same start()/poll()/backend interface.
"""

from dataclasses import dataclass
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from config.ranking import RANKING_KEYS

_EXCLUSIVE_WITH_CONFIRM = ('select', 'undo', 'up', 'down')


@dataclass(frozen=True)
class KeyPress:
    key:    str
    action: Optional[str]   # None → key not mapped to any action (still logged)
    rt:     float           # seconds since the onset flip


def action_map(key_map: Mapping[str, Sequence[str]] = RANKING_KEYS) -> Dict[str, str]:
    """key → action; refuses maps where confirm shares a key with another action."""
    out: Dict[str, str] = {}
    for action, keys in key_map.items():
        for k in keys:
            if k in out:
                raise ValueError(f"key {k!r} mapped to both {out[k]!r} and {action!r}")
            out[k] = action
    confirm = set(key_map.get('confirm', ()))
    for action in _EXCLUSIVE_WITH_CONFIRM:
        if confirm & set(key_map.get(action, ())):
            raise ValueError(f"'confirm' must not share keys with {action!r}")
    return out


class KeySource:
    def __init__(self, key_map: Mapping[str, Sequence[str]] = RANKING_KEYS, keyboard=None):
        from psychopy.hardware import keyboard as ptb_keyboard
        self._actions = action_map(key_map)
        self._kb = keyboard or ptb_keyboard.Keyboard()

    @property
    def backend(self) -> str:
        return str(self._kb.getBackend())

    def start(self, win) -> None:
        """Zero the response clock and drop stale presses on the next flip."""
        self._kb.clearEvents()
        win.callOnFlip(self._on_onset)

    def _on_onset(self) -> None:
        self._kb.clock.reset()
        self._kb.clearEvents()

    def time(self) -> float:
        return self._kb.clock.getTime()

    def poll(self) -> List[KeyPress]:
        # All keys are read (not just mapped ones) so every press is logged.
        return [KeyPress(k.name, self._actions.get(k.name), float(k.rt))
                for k in self._kb.getKeys(waitRelease=False)]


class ScriptedSource:
    """Replays *script* = [(rt, key), ...]; rt counts from the onset flip.

    Each start() begins the next screen's script from *scripts*. A press is
    delivered on the first poll after its rt has passed, with its scripted rt.
    """

    backend = 'scripted'

    def __init__(self, scripts: Iterable[Sequence[Tuple[float, str]]],
                 key_map: Mapping[str, Sequence[str]] = RANKING_KEYS):
        from psychopy import core
        self._actions = action_map(key_map)
        self._scripts = [list(s) for s in scripts]
        self._pending: List[Tuple[float, str]] = []
        self._clock = core.Clock()

    def start(self, win) -> None:
        self._pending = self._scripts.pop(0) if self._scripts else []
        win.callOnFlip(self._clock.reset)

    def time(self) -> float:
        return self._clock.getTime()

    def poll(self) -> List[KeyPress]:
        now = self._clock.getTime()
        due = [p for p in self._pending if p[0] <= now]
        self._pending = [p for p in self._pending if p[0] > now]
        return [KeyPress(k, self._actions.get(k), float(t)) for t, k in due]
