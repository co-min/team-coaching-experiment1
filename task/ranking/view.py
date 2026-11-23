"""
view.py
-------
PsychoPy drawing for the ranking screens. Holds no ranking state: every
draw_* call renders the state object it is given.

Layout (pix, origin = centre; all sizes scale with win.size)

    [domain]          prompt (2 lines)

        Your ranking               Options            ← sequential
     1위 [ card ]               [ card ]
     2위 [ card ]               [  --  ]   (placed)
     ...                         ...

        Your ranking               Hypothetical change  ← revised
     1위 [ card ]               [ images + colour ]
     ...                          text

                     key hints
"""

from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence

from psychopy import visual

from config import settings as S
from config import ranking as R
from config.paths import animal_image, domain_image
from config.ranking_strings import rt
from config.strings import domain_name
from task.ranking.items import RankItem


@dataclass
class ChangeDisplay:
    """What the participant sees of one hypothetical change (no role codes)."""
    kind:    str              # 'competence' | 'synergy'
    animals: Sequence[str]
    color:   str              # border (competence) / block (synergy) colour of the new level
    text:    str              # e.g. "What if this animal's cooking skill became high?"


def key_names(key_map=R.RANKING_KEYS) -> Dict[str, str]:
    """action → display name of its first key, for the on-screen hints."""
    return {a: R.KEY_DISPLAY.get(keys[0], keys[0]) for a, keys in key_map.items() if keys}


class RankingView:
    def __init__(self, win, n_items: int, item_kind: str, animals: Sequence[str],
                 domain: Optional[str], prompt: str, mode: str,
                 change: Optional[ChangeDisplay] = None, key_map=R.RANKING_KEYS):
        self.win, self.n, self.mode, self.change = win, n_items, mode, change
        W, H = (int(v) for v in win.size)
        self.W, self.H = W, H
        self._keys = key_names(key_map)

        # ── geometry ────────────────────────────────────────────────────────
        top, bottom = H * 0.5 - H * 0.27, -H * 0.5 + H * 0.15
        self.spacing = min((top - bottom) / max(n_items - 1, 1), H * 0.16)
        self.row_y = [top - i * self.spacing for i in range(n_items)]
        self.img = int(min(H * 0.085, self.spacing * 0.78))
        gap = int(self.img * 0.35)
        self._pair_dx = (self.img + gap) / 2
        width_imgs = 2 * self.img + gap if item_kind == 'pair' else self.img
        self.card_w, self.card_h = width_imgs + 24, self.img + 14

        left, right = (-W * 0.16, W * 0.16) if mode == 'sequential' else (-W * 0.17, W * 0.22)
        self.rank_x, self.option_x = left, right
        header_y = top + self.card_h / 2 + H * 0.035
        txt_h = max(int(H * 0.026), 16)

        # ── stimuli ─────────────────────────────────────────────────────────
        self.images = {a: visual.ImageStim(win, image=animal_image(a), size=(self.img, self.img), units='pix')
                       for a in animals}
        self.plus = visual.TextStim(win, text='+', height=int(self.img * 0.32), color='white',
                                    font=S.FONT, units='pix')
        self.card = visual.Rect(win, width=self.card_w, height=self.card_h, units='pix',
                                fillColor=R.CARD_COLOR, lineColor=None)
        self.outline = visual.Rect(win, width=self.card_w + 10, height=self.card_h + 10, units='pix',
                                   fillColor=None, lineColor=R.SLOT_COLOR, lineWidth=2)
        self.domain_img = None
        if domain:
            ds = int(H * 0.12)
            self.domain_img = visual.ImageStim(win, image=domain_image(domain), size=(ds, ds), units='pix',
                                               pos=(-W * 0.5 + ds * 0.5 + W * 0.04, H * 0.5 - ds * 0.5 - H * 0.03))
        self.prompt = visual.TextStim(win, text=prompt, font=S.FONT, height=int(txt_h * 1.15), color='white',
                                      pos=(0, H * 0.5 - H * 0.095), wrapWidth=W * 0.70, alignText='center',
                                      units='pix', bold=True)
        self.header_rank = visual.TextStim(win, text=rt("rank_header_ranking"), font=S.FONT, height=txt_h,
                                           color=R.DIM_TEXT_COLOR, pos=(self.rank_x, header_y), units='pix')
        self.header_opt = visual.TextStim(win, text=rt("rank_header_options"), font=S.FONT, height=txt_h,
                                          color=R.DIM_TEXT_COLOR, pos=(self.option_x, header_y), units='pix')
        label_x = self.rank_x - self.card_w / 2 - H * 0.06
        self.rank_labels = [visual.TextStim(win, text=rt("rank_label", n=i + 1), font=S.FONT,
                                            height=int(txt_h * 1.1), color='white', pos=(label_x, y),
                                            units='pix', bold=True)
                            for i, y in enumerate(self.row_y)]
        cap_h = max(int(txt_h * 0.75), 12)
        self.captions = [
            visual.TextStim(win, text=rt("rank_top_caption"), font=S.FONT, height=cap_h, color=R.DIM_TEXT_COLOR,
                            pos=(label_x, self.row_y[0] - txt_h * 1.1), units='pix'),
            visual.TextStim(win, text=rt("rank_bottom_caption"), font=S.FONT, height=cap_h, color=R.DIM_TEXT_COLOR,
                            pos=(label_x, self.row_y[-1] - txt_h * 1.1), units='pix'),
        ]
        self.hint = visual.TextStim(win, text='', font=S.FONT, height=txt_h, color='white',
                                    pos=(0, -H * 0.5 + H * 0.055), wrapWidth=W * 0.9, units='pix')
        self.status = visual.TextStim(win, text='', font=S.FONT, height=int(txt_h * 1.2), color=R.CONFIRMED_COLOR,
                                      pos=(self.option_x, 0), units='pix', bold=True)
        self.change_panel = ChangePanel(win, change, center=(self.option_x, H * 0.02), scale=0.9) if change else None

    # ── primitives ────────────────────────────────────────────────────────────

    def _draw_card(self, item: RankItem, pos, fill=R.CARD_COLOR) -> None:
        self.card.fillColor = fill
        self.card.pos = pos
        self.card.draw()
        x, y = pos
        if len(item.animals) == 1:
            offsets = [0]
        else:
            offsets = [-self._pair_dx, self._pair_dx]
            self.plus.pos = (x, y)
            self.plus.draw()
        for animal, dx in zip(item.animals, offsets):
            stim = self.images[animal]
            stim.pos = (x + dx, y)
            stim.draw()

    def _draw_outline(self, pos, color, width) -> None:
        self.outline.lineColor = color
        self.outline.lineWidth = width
        self.outline.pos = pos
        self.outline.draw()

    def _draw_frame(self, hint: str) -> None:
        if self.domain_img:
            self.domain_img.draw()
        self.prompt.draw()
        self.header_rank.draw()
        for label in self.rank_labels:
            label.draw()
        for cap in self.captions:
            cap.draw()
        self.hint.text = hint
        self.hint.draw()

    # ── screens ───────────────────────────────────────────────────────────────

    def draw_sequential(self, state, confirmed: bool = False) -> None:
        k = self._keys
        if confirmed:
            hint = ''
        elif state.complete:
            hint = rt("hint_sequential_done", confirm=k['confirm'], undo=k['undo'])
        else:
            hint = rt("hint_sequential", up=k['up'], down=k['down'], select=k['select'], undo=k['undo'])
        self._draw_frame(hint)
        self.header_opt.draw()

        next_rank = len(state.ranking)
        for i, y in enumerate(self.row_y):
            pos = (self.rank_x, y)
            if i < len(state.ranking):
                self._draw_card(state.ranking[i], pos)
            if confirmed:
                self._draw_outline(pos, R.CONFIRMED_COLOR, 4)
            elif state.complete:
                self._draw_outline(pos, R.CURSOR_COLOR, 3)
            elif i == next_rank:
                self._draw_outline(pos, 'white', 3)
            else:
                self._draw_outline(pos, R.SLOT_COLOR, 2)

        for i, (item, y) in enumerate(zip(state.options, self.row_y)):
            pos = (self.option_x, y)
            if item is None:
                self._draw_outline(pos, R.SLOT_COLOR, 1)
                continue
            self._draw_card(item, pos)
            if i == state.cursor:
                self._draw_outline(pos, R.CURSOR_COLOR, 6)

        if confirmed:
            self.status.text = rt("rank_confirmed")
            self.status.draw()

    def draw_revised(self, state, confirmed: bool = False) -> None:
        k = self._keys
        if confirmed:
            hint = ''
        elif state.held:
            hint = rt("hint_revised_held", up=k['up'], down=k['down'], select=k['select'])
        else:
            hint = rt("hint_revised", up=k['up'], down=k['down'], select=k['select'],
                      undo=k['undo'], confirm=k['confirm'])
        self._draw_frame(hint)
        if self.change_panel:
            self.change_panel.draw()

        lift = self.W * 0.025
        for i, (item, y) in enumerate(zip(state.order, self.row_y)):
            held = state.held and i == state.cursor
            pos = (self.rank_x + (lift if held else 0), y)
            self._draw_card(item, pos, fill='#5a5a5a' if held else R.CARD_COLOR)
            if confirmed:
                self._draw_outline(pos, R.CONFIRMED_COLOR, 4)
            elif held:
                self._draw_outline(pos, R.HELD_COLOR, 6)
            elif i == state.cursor:
                self._draw_outline(pos, R.CURSOR_COLOR, 6)

        if confirmed:
            self.status.text = rt("rank_confirmed")
            self.status.pos = (self.option_x, -self.H * 0.30)
            self.status.draw()


class ChangePanel:
    """Images of the changed animal(s) + the new level in the task's colour code:
    a coloured border (competence, as in phase 1) or a coloured block under
    the pair (synergy, as in phase 2)."""

    def __init__(self, win, change: ChangeDisplay, center=(0, 0), scale: float = 1.0,
                 title: bool = True, wrap: float = 0.34):
        W, H = (int(v) for v in win.size)
        cx, cy = center
        img = int(H * 0.15 * scale)
        txt_h = max(int(H * 0.028 * scale), 14)
        gap = int(img * 0.25)
        xs = [cx] if len(change.animals) == 1 else [cx - (img + gap) / 2, cx + (img + gap) / 2]
        img_y = cy + img * 0.35

        self.stims: List = []
        if title:
            self.stims.append(visual.TextStim(win, text=rt("change_title"), font=S.FONT, height=txt_h,
                                              color=R.HELD_COLOR, pos=(cx, img_y + img * 0.5 + txt_h * 2),
                                              units='pix', bold=True))
        if change.kind == 'synergy':
            block_w = 2 * img + gap + 20
            self.stims.append(visual.Rect(win, width=block_w, height=int(H * 0.05 * scale), units='pix',
                                          pos=(cx, img_y - img * 0.5 - H * 0.03 * scale),
                                          fillColor=change.color, lineColor=None))
        for animal, x in zip(change.animals, xs):
            self.stims.append(visual.ImageStim(win, image=animal_image(animal), size=(img, img),
                                               pos=(x, img_y), units='pix'))
            if change.kind == 'competence':
                self.stims.append(visual.Rect(win, width=img + 10, height=img + 10, pos=(x, img_y), units='pix',
                                              lineWidth=int(14 * scale), lineColor=change.color, fillColor=None))
        # Top-anchored so a wrapped (2-line) sentence grows downward into reserved space.
        text_y = img_y - img * 0.5 - H * 0.08 * scale
        self.stims.append(visual.TextStim(win, text=change.text, font=S.FONT, height=txt_h, color='white',
                                          pos=(cx, text_y), wrapWidth=W * wrap, units='pix', bold=True,
                                          anchorVert='top', alignText='center'))
        self.stims.append(visual.TextStim(win, text=rt("change_rest_same"), font=S.FONT,
                                          height=int(txt_h * 0.8), color=R.DIM_TEXT_COLOR,
                                          pos=(cx, text_y - txt_h * 3.2), wrapWidth=W * wrap, units='pix',
                                          anchorVert='top', alignText='center'))

    def draw(self) -> None:
        for s in self.stims:
            s.draw()


def change_screen_stims(win, change: ChangeDisplay, domain: Optional[str], continue_key: str) -> List:
    """Full-screen hypothetical-change announcement shown before the revised ranking."""
    W, H = (int(v) for v in win.size)
    stims: List = [ChangePanel(win, change, center=(0, H * 0.08), scale=1.4, wrap=0.7)]
    if domain:
        ds = int(H * 0.12)
        stims.append(visual.ImageStim(win, image=domain_image(domain), size=(ds, ds), units='pix',
                                      pos=(-W * 0.5 + ds * 0.5 + W * 0.04, H * 0.5 - ds * 0.5 - H * 0.03)))
    stims.append(visual.TextStim(win, text=rt("change_continue", key=continue_key), font=S.FONT,
                                 height=max(int(H * 0.026), 16), color='white', pos=(0, -H * 0.5 + H * 0.055),
                                 units='pix'))
    return stims


def domain_label(domain: Optional[str]) -> str:
    return domain_name(domain) if domain else ''
