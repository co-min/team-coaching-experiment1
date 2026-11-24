"""
view.py
-------
Draws the estimate screen with PsychoPy. Holds no experiment state and makes no decisions:
run.py tells it what to show (set_question) and what is highlighted (draw).

It is never given an EstimateItem, only display text, animal names and a
domain, so it has no way to show a true value, a true level, or "correct".

Layout (pix, origin = screen centre, all sizes proportional to win.size)

                 SYNERGY ESTIMATE             ← title
                    [domain image]            ← competence only
                      COOKING
                     Pair 1 / 6               ← counter
                 [animal] + [animal]          ← one animal for competence
          How would you rate the synergy ...  ← question
           [ LOW ]   [ MEDIUM ]   [ HIGH ]    ← response buttons
              ←          ↓           →        ← keys
           Choose with ← ↓ →   ·   [Space] Confirm
"""

from typing import Dict, Optional, Sequence

from psychopy import visual

from config import estimate as E
from config import settings as S
from config.paths import animal_image, domain_image
from config.strings import domain_name, t
from recording.stimuli_loader import LEVELS
from task.ranking.view import key_names


class EstimateView:
    """All visual stimuli of the estimate screen, created once (creating them every frame is slow).

    win     : PsychoPy window
    animals : the block's animals (their images are preloaded)
    domains : domains that may be shown (their images are preloaded)

    State it keeps: only the stimuli and the text of the current question.
    Methods that change it: set_question (once per question). draw() only draws.
    """

    def __init__(self, win, animals: Sequence[str], domains: Sequence[str], key_map=E.ESTIMATE_KEYS):
        self.win = win
        W, H = (int(v) for v in win.size)
        self.W, self.H = W, H
        self._keys = key_names(key_map)        # e.g. {'low': '←', 'confirm': 'Space', ...}
        text_height = max(int(H * 0.030), 16)

        # ── top: title, domain image + name, counter ──
        self.title = visual.TextStim(win, text='', font=S.FONT, height=int(text_height * 1.2), color='white',
                                     pos=(0, H * 0.42), units='pix', bold=True)
        domain_size = int(H * 0.11)
        self.domain_images: Dict[str, visual.ImageStim] = {}
        for domain in domains:
            self.domain_images[domain] = visual.ImageStim(win, image=domain_image(domain), pos=(0, H * 0.30),
                                                          size=(domain_size, domain_size), units='pix')
        self.domain_text = visual.TextStim(win, text='', font=S.FONT, height=text_height, color='white',
                                           pos=(0, H * 0.215), units='pix', bold=True)
        self.counter = visual.TextStim(win, text='', font=S.FONT, height=int(text_height * 0.9),
                                       color=E.DIM_TEXT_COLOR, pos=(0, H * 0.16), units='pix')

        # ── middle: animal image(s) ──
        self.animal_size = int(H * 0.20)
        self.animal_images: Dict[str, visual.ImageStim] = {}
        for animal in animals:
            self.animal_images[animal] = visual.ImageStim(win, image=animal_image(animal),
                                                          size=(self.animal_size, self.animal_size), units='pix')
        self.animal_y = H * 0.02
        self.plus = visual.TextStim(win, text='+', font=S.FONT, height=int(self.animal_size * 0.35), color='white',
                                    pos=(0, self.animal_y), units='pix')

        # ── question ──
        self.question = visual.TextStim(win, text='', font=S.FONT, height=text_height, color='white',
                                        pos=(0, -H * 0.165), wrapWidth=W * 0.7, alignText='center', units='pix',
                                        bold=True)

        # ── response buttons LOW / MEDIUM / HIGH (left → right), each with its key below ──
        button_w, button_h = int(W * 0.13), int(H * 0.075)
        button_y = -H * 0.29
        self.buttons = {}
        self.button_labels = {}
        self.button_keys = {}
        for level, x in zip(LEVELS, (-W * 0.17, 0, W * 0.17)):
            self.buttons[level] = visual.Rect(win, width=button_w, height=button_h, pos=(x, button_y), units='pix',
                                              fillColor=E.BUTTON_COLOR, lineColor=E.BUTTON_LINE, lineWidth=2)
            self.button_labels[level] = visual.TextStim(win, text=t(f"estimate_level_{level}"), font=S.FONT,
                                                        height=text_height, color='white', pos=(x, button_y),
                                                        units='pix', bold=True)
            self.button_keys[level] = visual.TextStim(win, text=self._keys[level], font=S.FONT,
                                                      height=int(text_height * 0.9), color=E.DIM_TEXT_COLOR,
                                                      pos=(x, button_y - button_h * 0.5 - text_height), units='pix')

        # ── bottom: how to answer, and the confirm key (dim until a response is highlighted) ──
        hint_y = -H * 0.5 + H * 0.055
        self.choose_hint = visual.TextStim(
            win, text=t("estimate_hint_choose", low=self._keys['low'], mid=self._keys['mid'], high=self._keys['high']),
            font=S.FONT, height=int(text_height * 0.85), color=E.DIM_TEXT_COLOR, pos=(-W * 0.12, hint_y), units='pix')
        self.confirm_hint = visual.TextStim(win, text=t("estimate_hint_confirm", confirm=self._keys['confirm']),
                                            font=S.FONT, height=int(text_height * 0.85), color=E.DIM_TEXT_COLOR,
                                            pos=(W * 0.12, hint_y), units='pix', bold=True)

        # What set_question chose to show
        self._display_animals: Sequence[str] = ()
        self._domain: Optional[str] = None

    # ── per question ──────────────────────────────────────────────────────────

    def set_question(self, title: str, counter: str, question: str, display_animals: Sequence[str],
                     domain: Optional[str]) -> None:
        """Prepare the screen for a new question. Text is only set here, not every frame.

        display_animals : one animal (competence) or two, left → right (synergy)
        domain          : shown at the top for competence; None for synergy
        """
        self.title.text = title
        self.counter.text = counter
        self.question.text = question
        self._display_animals = list(display_animals)
        self._domain = domain
        if domain:
            self.domain_text.text = domain_name(domain)

        # Place the animal image(s): one in the centre, or two either side of a '+'
        if len(self._display_animals) == 1:
            self.animal_images[self._display_animals[0]].pos = (0, self.animal_y)
        else:
            offset = self.animal_size * 0.7
            left_animal, right_animal = self._display_animals
            self.animal_images[left_animal].pos = (-offset, self.animal_y)
            self.animal_images[right_animal].pos = (offset, self.animal_y)

    # ── every frame ───────────────────────────────────────────────────────────

    def draw(self, selected: Optional[str], confirmed: bool = False) -> None:
        """Draw the current question.

        selected  : highlighted response 'low' / 'mid' / 'high', or None
        confirmed : True right after the confirm key. The chosen button is filled in.
                    This looks the same whether the answer is right or wrong (no feedback).
        """
        self.title.draw()
        if self._domain:
            self.domain_images[self._domain].draw()
            self.domain_text.draw()
        self.counter.draw()

        for animal in self._display_animals:
            self.animal_images[animal].draw()
        if len(self._display_animals) == 2:
            self.plus.draw()
        self.question.draw()

        for level in LEVELS:
            self._draw_button(level, selected, confirmed)

        if not confirmed:
            self.choose_hint.draw()
            if selected is None:
                self.confirm_hint.color = E.DIM_TEXT_COLOR
            else:
                self.confirm_hint.color = 'white'
            self.confirm_hint.draw()

    def _draw_button(self, level: str, selected: Optional[str], confirmed: bool) -> None:
        """One response button: plain, highlighted (outline), or confirmed (filled)."""
        button = self.buttons[level]
        label = self.button_labels[level]

        if level == selected and confirmed:
            button.fillColor = E.SELECTED_COLOR
            button.lineColor = E.SELECTED_COLOR
            button.lineWidth = 6
            label.color = S.BACKGROUND_COLOR
        elif level == selected:
            button.fillColor = E.BUTTON_COLOR
            button.lineColor = E.SELECTED_COLOR
            button.lineWidth = 6
            label.color = E.SELECTED_COLOR
        else:
            button.fillColor = E.BUTTON_COLOR
            button.lineColor = E.BUTTON_LINE
            button.lineWidth = 2
            label.color = 'white'

        button.draw()
        label.draw()
        self.button_keys[level].draw()
