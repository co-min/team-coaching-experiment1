"""
state.py
--------
Input-independent ranking state machines. Screens translate key presses into
these method calls; each call returns an outcome dict (logged as one event)
or None when the action is not allowed in the current state.

    SequentialRanking  pick items from highest to lowest, with undo
    RevisedRanking     start from a previous ranking, pick up / move / put down
"""

from typing import Dict, List, Optional, Sequence

from task.ranking.items import RankItem

Outcome = Optional[Dict[str, object]]


class SequentialRanking:
    """Options keep their display slots; a placed option leaves an empty slot."""

    def __init__(self, options: Sequence[RankItem]):
        self.options: List[Optional[RankItem]] = list(options)
        self._origin: Dict[RankItem, int] = {it: i for i, it in enumerate(options)}
        self.ranking: List[RankItem] = []
        self.cursor: Optional[int] = 0 if options else None

    @property
    def n(self) -> int:
        return len(self._origin)

    @property
    def complete(self) -> bool:
        return len(self.ranking) == self.n

    def _next_available(self, start: int, step: int) -> Optional[int]:
        """First non-empty slot from *start* (inclusive) moving by *step*, wrapping."""
        for k in range(self.n):
            i = (start + step * k) % self.n
            if self.options[i] is not None:
                return i
        return None

    def move(self, step: int) -> Outcome:
        if self.cursor is None:
            return None
        new = self._next_available(self.cursor + step, step)
        if new is None or new == self.cursor:
            return None
        self.cursor = new
        return {'event': 'cursor', 'item': self.options[new], 'from_pos': None, 'to_pos': new + 1}

    def place(self) -> Outcome:
        if self.cursor is None:
            return None
        item = self.options[self.cursor]
        self.options[self.cursor] = None
        self.ranking.append(item)
        self.cursor = self._next_available(self.cursor, 1)
        return {'event': 'select', 'item': item, 'rank_pos': len(self.ranking)}

    def undo(self) -> Outcome:
        if not self.ranking:
            return None
        item = self.ranking.pop()
        slot = self._origin[item]
        self.options[slot] = item
        self.cursor = slot
        return {'event': 'undo', 'item': item, 'rank_pos': len(self.ranking) + 1}


class RevisedRanking:
    """A cursor over the ranking; a held item swaps one step per up/down."""

    def __init__(self, initial: Sequence[RankItem]):
        self.initial: List[RankItem] = list(initial)
        self.order: List[RankItem] = list(initial)
        self.cursor = 0
        self.held = False
        self._history: List[tuple] = []   # (from_index, to_index, hold_episode) per one-step move
        self._episode = 0
        self._pickup_index: Optional[int] = None
        self.n_relocations = 0            # put-downs that left the item somewhere new

    @property
    def changed(self) -> bool:
        return self.order != self.initial

    def move(self, step: int) -> Outcome:
        new = self.cursor + step
        if not 0 <= new < len(self.order):
            return None
        if not self.held:
            self.cursor = new
            return {'event': 'cursor', 'item': self.order[new], 'to_pos': new + 1}
        old = self.cursor
        self.order[old], self.order[new] = self.order[new], self.order[old]
        self.cursor = new
        self._history.append((old, new, self._episode))
        return {'event': 'move', 'item': self.order[new], 'from_pos': old + 1, 'to_pos': new + 1,
                'displaced': self.order[old]}

    def toggle_hold(self) -> Outcome:
        item = self.order[self.cursor]
        if not self.held:
            self.held, self._pickup_index = True, self.cursor
            self._episode += 1
            return {'event': 'pick_up', 'item': item, 'rank_pos': self.cursor + 1}
        self.held = False
        moved = self.cursor != self._pickup_index
        self.n_relocations += moved
        out = {'event': 'put_down', 'item': item, 'from_pos': self._pickup_index + 1,
               'to_pos': self.cursor + 1, 'relocated': moved}
        self._pickup_index = None
        return out

    def undo(self) -> Outcome:
        """Revert the last one-step move; the cursor (and hold, if any) follows the item.

        While holding, only moves of the current pick-up can be undone.
        """
        if not self._history or (self.held and self._history[-1][2] != self._episode):
            return None
        old, new, _ = self._history.pop()
        self.order[old], self.order[new] = self.order[new], self.order[old]
        self.cursor = old
        return {'event': 'undo', 'item': self.order[old], 'from_pos': new + 1, 'to_pos': old + 1}
