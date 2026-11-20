"""
keyboard.py
-----------
4-direction arrow display. Arrows highlight when the corresponding arrow key
is pressed; the trial loops read keys themselves and call select().
"""

from typing import Optional, List, Tuple

from psychopy import visual

import config.settings as cfg


# (offset_x, offset_y, orientation)  — index order: up, down, right, left
_ARROW_DEFS: List[Tuple[int, int, int]] = [
    (0,                  cfg.ARROW_OFFSET,  0  ),  # 0: up
    (0,                 -cfg.ARROW_OFFSET,  180),  # 1: down
    (cfg.ARROW_OFFSET,   0,                 90 ),  # 2: right
    (-cfg.ARROW_OFFSET,  0,                 270),  # 3: left
]

_KEY_TO_IDX: dict = {
    'up':    0,
    'down':  1,
    'right': 2,
    'left':  3,
}

_COLOR_IDLE      = '#0055ff'
_COLOR_SELECTED  = "#00d9ff"
_COLOR_CONFIRMED = "#00d9ff"


class ArrowKeyboard:
    """4-directional arrow stimuli (index order: up, down, right, left)."""

    def __init__(self, win: visual.Window, pos: Tuple[float, float] = (0, 0)):
        ox, oy = pos
        self.arrows: List[visual.Polygon] = [
            visual.Polygon(
                win,
                edges=3,
                radius=cfg.ARROW_RADIUS,
                pos=(ox + dx, oy + dy),
                ori=ori,
                fillColor=_COLOR_IDLE,
                lineColor=None,
            )
            for dx, dy, ori in _ARROW_DEFS
        ]
        self._confirmed_idx: Optional[int] = None

    @property
    def valid_keys(self) -> List[str]:
        return list(_KEY_TO_IDX.keys())

    def draw(self) -> None:
        for arrow in self.arrows:
            arrow.draw()

    def reset_colors(self) -> None:
        for i, arrow in enumerate(self.arrows):
            arrow.fillColor = _COLOR_CONFIRMED if i == self._confirmed_idx else _COLOR_IDLE

    def select(self, key: str, excluded_idx: Optional[int] = None) -> Optional[int]:
        """Highlight the arrow for *key* and return its index.

        Returns None if the key is not an arrow key or matches excluded_idx.
        """
        idx = _KEY_TO_IDX.get(key)
        if idx is None or idx == excluded_idx:
            return None
        self.arrows[idx].fillColor = _COLOR_SELECTED
        return idx

    def set_excluded(self, excluded_idx: int) -> None:
        """Mark the confirmed Choice 1 arrow orange and persist it through reset_colors()."""
        self._confirmed_idx = excluded_idx
        self.arrows[excluded_idx].fillColor = _COLOR_CONFIRMED

