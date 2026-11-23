"""
view.py
-------
순위 화면을 PsychoPy 로 그립니다. 순위 상태는 갖고 있지 않습니다.
draw_* 메서드는 넘겨받은 상태 객체(state.py)를 "보이는 그대로" 그리기만 합니다.
(키 처리·상태 변경은 flow.py / state.py 의 일)

화면 배치 (단위 pix, 원점 = 화면 중앙, 모든 크기는 win.size 에 비례)

    [domain]          prompt (2줄)

        나의 순위                 선택지              ← sequential (차례로 고르기)
     1위 [ card ]               [ card ]
     2위 [ card ]               [  --  ]   (이미 고른 칸)
     ...                         ...

        나의 순위                 가상 변화           ← revised (수정 순위)
     1위 [ card ]               [ 이미지 + 색 ]
     ...                          설명 문장

                     키 안내 (hint)

파일 구성
    ChangeDisplay        가상 변화 하나를 화면에 보여 줄 정보
    key_names            동작 → 화면에 표시할 키 이름
    RankingView          순위 화면 (배치 계산 → 자극 생성 → 그리기)
    ChangePanel          가상 변화 패널 (동물 이미지 + 새 단계의 색 + 문장)
    change_screen_stims  수정 순위 전에 보여 주는 가상 변화 안내 화면 전체
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
    """가상 변화 하나 중 참가자에게 보이는 부분 (역할 코드는 없음)."""
    kind:    str              # 'competence' | 'synergy'
    animals: Sequence[str]    # 바뀌는 동물 이름 (1마리 또는 2마리)
    color:   str              # 새 단계의 색: competence 는 테두리, synergy 는 아래 막대
    text:    str              # 예: "이 동물의 요리 실력이 높아진다면?"


def key_names(key_map=R.RANKING_KEYS) -> Dict[str, str]:
    """{동작: 화면에 표시할 키 이름}. 동작마다 첫 번째 키를 씁니다.

    예) {'select': 'Space', 'confirm': 'Enter', 'up': '↑', ...}
    """
    names = {}
    for action, keys in key_map.items():
        if not keys:
            continue
        first_key = keys[0]
        names[action] = R.KEY_DISPLAY.get(first_key, first_key)
    return names


def domain_label(domain: Optional[str]) -> str:
    """도메인의 참가자용 이름 (예: '요리'). 도메인이 없으면 빈 문자열."""
    if domain:
        return domain_name(domain)
    return ''


def _domain_image_stim(win, domain: str) -> visual.ImageStim:
    """화면 왼쪽 위 구석에 놓는 도메인 아이콘."""
    W, H = (int(v) for v in win.size)
    icon_size = int(H * 0.12)
    position = (-W * 0.5 + icon_size * 0.5 + W * 0.04, H * 0.5 - icon_size * 0.5 - H * 0.03)
    return visual.ImageStim(win, image=domain_image(domain), size=(icon_size, icon_size), units='pix',
                            pos=position)


# ── 순위 화면 ─────────────────────────────────────────────────────────────────

class RankingView:
    """순위 화면 하나의 모든 시각 자극.

    win       : PsychoPy 창
    n_items   : 대상(팀) 수 (= 줄 수)
    animals   : 이 블록의 동물들 (이미지를 미리 불러 둠)
    domain    : 왼쪽 위 아이콘으로 보여 줄 도메인 (없으면 None)
    prompt    : 맨 위 안내 문장
    mode      : 'sequential' 또는 'revised' (오른쪽 열의 위치·내용이 다름)
    change    : revised 화면 오른쪽에 보여 줄 가상 변화
    """

    def __init__(self, win, n_items: int, animals: Sequence[str], domain: Optional[str], prompt: str, mode: str,
                 change: Optional[ChangeDisplay] = None, key_map=R.RANKING_KEYS):
        self.win = win
        self.n = n_items
        self.mode = mode
        self.change = change
        W, H = (int(v) for v in win.size)
        self.W, self.H = W, H
        self._keys = key_names(key_map)

        self._compute_layout(n_items, mode)
        self._create_stimuli(win, animals, domain, prompt, change)

    # ── 배치 계산 ────────────────────────────────────────────────────────────

    def _compute_layout(self, n_items: int, mode: str) -> None:
        """줄 위치, 카드·이미지 크기, 두 열의 x 위치를 계산해 self 에 저장합니다."""
        W, H = self.W, self.H

        # 줄들이 들어갈 세로 구간 (위쪽은 안내 문장, 아래쪽은 키 안내 자리를 비워 둠)
        top = H * 0.5 - H * 0.27
        bottom = -H * 0.5 + H * 0.15
        self._top = top

        # 줄 간격: 구간을 고르게 나누되, 대상이 적어도 너무 벌어지지 않게 최대값을 둠
        self.spacing = min((top - bottom) / max(n_items - 1, 1), H * 0.16)
        self.row_y = []
        for row in range(n_items):
            self.row_y.append(top - row * self.spacing)

        # 동물 이미지 크기와 카드 크기 (카드 하나 = 이미지 두 장)
        self.img = int(min(H * 0.085, self.spacing * 0.78))
        gap = int(self.img * 0.35)
        self._pair_dx = (self.img + gap) / 2          # 두 이미지가 카드 중앙에서 떨어진 거리
        self.card_w = 2 * self.img + gap + 24
        self.card_h = self.img + 14

        # 왼쪽 열(나의 순위)과 오른쪽 열(선택지 또는 가상 변화)의 x 위치
        if mode == 'sequential':
            self.rank_x, self.option_x = -W * 0.16, W * 0.16
        else:
            # revised: 오른쪽 가상 변화 패널이 넓으므로 조금 더 바깥으로
            self.rank_x, self.option_x = -W * 0.17, W * 0.22

    # ── 자극 생성 ────────────────────────────────────────────────────────────

    def _create_stimuli(self, win, animals: Sequence[str], domain: Optional[str], prompt: str,
                        change: Optional[ChangeDisplay]) -> None:
        """화면에 쓰는 PsychoPy 자극을 한 번만 만들어 둡니다 (매 프레임 만들면 느림)."""
        W, H = self.W, self.H
        header_y = self._top + self.card_h / 2 + H * 0.035
        text_height = max(int(H * 0.026), 16)

        # 카드 그리기용: 동물 이미지, 팀의 '+' 표시, 카드 배경, 카드 테두리
        self.images = {}
        for animal in animals:
            self.images[animal] = visual.ImageStim(win, image=animal_image(animal), size=(self.img, self.img),
                                                   units='pix')
        self.plus = visual.TextStim(win, text='+', height=int(self.img * 0.32), color='white',
                                    font=S.FONT, units='pix')
        self.card = visual.Rect(win, width=self.card_w, height=self.card_h, units='pix',
                                fillColor=R.CARD_COLOR, lineColor=None)
        self.outline = visual.Rect(win, width=self.card_w + 10, height=self.card_h + 10, units='pix',
                                   fillColor=None, lineColor=R.SLOT_COLOR, lineWidth=2)

        # 위쪽: 도메인 아이콘, 안내 문장, 열 제목
        self.domain_img = None
        if domain:
            self.domain_img = _domain_image_stim(win, domain)
        self.prompt = visual.TextStim(win, text=prompt, font=S.FONT, height=int(text_height * 1.15), color='white',
                                      pos=(0, H * 0.5 - H * 0.095), wrapWidth=W * 0.70, alignText='center',
                                      units='pix', bold=True)
        self.header_rank = visual.TextStim(win, text=rt("rank_header_ranking"), font=S.FONT, height=text_height,
                                           color=R.DIM_TEXT_COLOR, pos=(self.rank_x, header_y), units='pix')
        self.header_opt = visual.TextStim(win, text=rt("rank_header_options"), font=S.FONT, height=text_height,
                                          color=R.DIM_TEXT_COLOR, pos=(self.option_x, header_y), units='pix')

        # 왼쪽: "1위", "2위" ... 순위 표시와 "가장 높음 / 가장 낮음" 설명
        label_x = self.rank_x - self.card_w / 2 - H * 0.06
        self.rank_labels = []
        for row, y in enumerate(self.row_y):
            self.rank_labels.append(visual.TextStim(win, text=rt("rank_label", n=row + 1), font=S.FONT,
                                                    height=int(text_height * 1.1), color='white', pos=(label_x, y),
                                                    units='pix', bold=True))
        caption_height = max(int(text_height * 0.75), 12)
        self.captions = [
            visual.TextStim(win, text=rt("rank_top_caption"), font=S.FONT, height=caption_height,
                            color=R.DIM_TEXT_COLOR, pos=(label_x, self.row_y[0] - text_height * 1.1), units='pix'),
            visual.TextStim(win, text=rt("rank_bottom_caption"), font=S.FONT, height=caption_height,
                            color=R.DIM_TEXT_COLOR, pos=(label_x, self.row_y[-1] - text_height * 1.1), units='pix'),
        ]

        # 아래쪽: 키 안내 (글자는 그릴 때마다 상태에 맞게 바꿈)
        self.hint = visual.TextStim(win, text='', font=S.FONT, height=text_height, color='white',
                                    pos=(0, -H * 0.5 + H * 0.055), wrapWidth=W * 0.9, units='pix')

        # 제출 직후 잠깐 보이는 "확정됨" 문구
        self.status = visual.TextStim(win, text='', font=S.FONT, height=int(text_height * 1.2),
                                      color=R.CONFIRMED_COLOR, pos=(self.option_x, 0), units='pix', bold=True)

        # revised 화면 오른쪽의 가상 변화 패널
        self.change_panel = None
        if change:
            self.change_panel = ChangePanel(win, change, center=(self.option_x, H * 0.02), scale=0.9)

    # ── 그리기 기본 도구 ──────────────────────────────────────────────────────

    def _draw_card(self, item: RankItem, pos, fill=R.CARD_COLOR) -> None:
        """팀 카드 하나 (배경 + 동물 이미지 두 장, 가운데 '+')."""
        self.card.fillColor = fill
        self.card.pos = pos
        self.card.draw()

        x, y = pos
        self.plus.pos = (x, y)
        self.plus.draw()
        for animal, dx in zip(item.animals, (-self._pair_dx, self._pair_dx)):
            image = self.images[animal]
            image.pos = (x + dx, y)
            image.draw()

    def _draw_outline(self, pos, color, width) -> None:
        """카드 둘레의 테두리 (커서·빈칸·확정 표시에 사용)."""
        self.outline.lineColor = color
        self.outline.lineWidth = width
        self.outline.pos = pos
        self.outline.draw()

    def _draw_frame(self, hint: str) -> None:
        """두 화면에 공통인 부분: 도메인 아이콘, 안내 문장, 왼쪽 열 제목·순위 표시, 키 안내."""
        if self.domain_img:
            self.domain_img.draw()
        self.prompt.draw()
        self.header_rank.draw()
        for label in self.rank_labels:
            label.draw()
        for caption in self.captions:
            caption.draw()
        self.hint.text = hint
        self.hint.draw()

    # ── 화면별 그리기 ─────────────────────────────────────────────────────────

    def draw_sequential(self, state, confirmed: bool = False) -> None:
        """차례로 고르는 화면 (state: SequentialRanking).

        confirmed=True 이면 제출 직후의 확인 화면 (초록 테두리 + "확정" 문구).
        """
        keys = self._keys
        if confirmed:
            hint = ''
        elif state.complete:
            hint = rt("hint_sequential_done", confirm=keys['confirm'], undo=keys['undo'])
        else:
            hint = rt("hint_sequential", up=keys['up'], down=keys['down'], select=keys['select'], undo=keys['undo'])
        self._draw_frame(hint)
        self.header_opt.draw()

        # 왼쪽 열: 지금까지 고른 순위. 테두리로 상태를 표시합니다.
        next_rank = len(state.ranking)
        for row, y in enumerate(self.row_y):
            pos = (self.rank_x, y)
            if row < len(state.ranking):
                self._draw_card(state.ranking[row], pos)

            if confirmed:
                self._draw_outline(pos, R.CONFIRMED_COLOR, 4)   # 제출됨
            elif state.complete:
                self._draw_outline(pos, R.CURSOR_COLOR, 3)      # 다 골랐음, 제출 대기
            elif row == next_rank:
                self._draw_outline(pos, 'white', 3)             # 다음에 채워질 칸
            else:
                self._draw_outline(pos, R.SLOT_COLOR, 2)        # 그 밖의 칸

        # 오른쪽 열: 선택지. 이미 고른 칸은 흐린 빈 테두리만.
        for row, (item, y) in enumerate(zip(state.options, self.row_y)):
            pos = (self.option_x, y)
            if item is None:
                self._draw_outline(pos, R.SLOT_COLOR, 1)
                continue
            self._draw_card(item, pos)
            if row == state.cursor:
                self._draw_outline(pos, R.CURSOR_COLOR, 6)

        if confirmed:
            self.status.text = rt("rank_confirmed")
            self.status.draw()

    def draw_revised(self, state, confirmed: bool = False) -> None:
        """수정 순위 화면 (state: RevisedRanking).

        집은 카드는 오른쪽으로 살짝 튀어나오고, 더 밝은 배경과 주황 테두리로 표시됩니다.
        """
        keys = self._keys
        if confirmed:
            hint = ''
        elif state.held:
            hint = rt("hint_revised_held", up=keys['up'], down=keys['down'], select=keys['select'])
        else:
            hint = rt("hint_revised", up=keys['up'], down=keys['down'], select=keys['select'],
                      undo=keys['undo'], confirm=keys['confirm'])
        self._draw_frame(hint)
        if self.change_panel:
            self.change_panel.draw()

        held_card_shift = self.W * 0.025
        for row, (item, y) in enumerate(zip(state.order, self.row_y)):
            is_held = state.held and row == state.cursor
            if is_held:
                pos = (self.rank_x + held_card_shift, y)
                self._draw_card(item, pos, fill='#5a5a5a')
            else:
                pos = (self.rank_x, y)
                self._draw_card(item, pos, fill=R.CARD_COLOR)

            if confirmed:
                self._draw_outline(pos, R.CONFIRMED_COLOR, 4)
            elif is_held:
                self._draw_outline(pos, R.HELD_COLOR, 6)
            elif row == state.cursor:
                self._draw_outline(pos, R.CURSOR_COLOR, 6)

        if confirmed:
            self.status.text = rt("rank_confirmed")
            self.status.pos = (self.option_x, -self.H * 0.30)
            self.status.draw()


# ── 가상 변화 ─────────────────────────────────────────────────────────────────

class ChangePanel:
    """가상 변화 패널: 바뀌는 동물 이미지 + 새 단계의 색 + 설명 문장.

    색은 학습 과제와 같은 색 규칙을 따릅니다.
        competence : 동물 이미지 둘레의 색 테두리 (phase 1 에서 본 것과 같음)
        synergy    : 두 동물 아래의 색 막대   (phase 2 에서 본 것과 같음)

    center : 패널 중심 위치
    scale  : 크기 배율 (순위 화면 옆에서는 작게, 안내 화면에서는 크게)
    title  : 맨 위에 "가상 변화" 제목을 붙일지
    wrap   : 문장 줄바꿈 폭 (화면 너비에 대한 비율)
    """

    def __init__(self, win, change: ChangeDisplay, center=(0, 0), scale: float = 1.0,
                 title: bool = True, wrap: float = 0.34):
        W, H = (int(v) for v in win.size)
        center_x, center_y = center
        image_size = int(H * 0.15 * scale)
        text_height = max(int(H * 0.028 * scale), 14)
        gap = int(image_size * 0.25)
        if len(change.animals) == 1:
            image_xs = [center_x]
        else:
            image_xs = [center_x - (image_size + gap) / 2, center_x + (image_size + gap) / 2]
        image_y = center_y + image_size * 0.35

        # 그리는 순서대로 담습니다 (뒤에 담은 것이 위에 그려짐).
        self.stims: List = []
        if title:
            self.stims.append(visual.TextStim(win, text=rt("change_title"), font=S.FONT, height=text_height,
                                              color=R.HELD_COLOR,
                                              pos=(center_x, image_y + image_size * 0.5 + text_height * 2),
                                              units='pix', bold=True))
        if change.kind == 'synergy':
            bar_width = 2 * image_size + gap + 20
            self.stims.append(visual.Rect(win, width=bar_width, height=int(H * 0.05 * scale), units='pix',
                                          pos=(center_x, image_y - image_size * 0.5 - H * 0.03 * scale),
                                          fillColor=change.color, lineColor=None))
        for animal, x in zip(change.animals, image_xs):
            self.stims.append(visual.ImageStim(win, image=animal_image(animal), size=(image_size, image_size),
                                               pos=(x, image_y), units='pix'))
            if change.kind == 'competence':
                self.stims.append(visual.Rect(win, width=image_size + 10, height=image_size + 10, pos=(x, image_y),
                                              units='pix', lineWidth=int(14 * scale), lineColor=change.color,
                                              fillColor=None))

        # 위쪽 기준(anchorVert='top')으로 두어, 문장이 두 줄이 되면 아래로 늘어나게 합니다.
        text_y = image_y - image_size * 0.5 - H * 0.08 * scale
        self.stims.append(visual.TextStim(win, text=change.text, font=S.FONT, height=text_height, color='white',
                                          pos=(center_x, text_y), wrapWidth=W * wrap, units='pix', bold=True,
                                          anchorVert='top', alignText='center'))
        self.stims.append(visual.TextStim(win, text=rt("change_rest_same"), font=S.FONT,
                                          height=int(text_height * 0.8), color=R.DIM_TEXT_COLOR,
                                          pos=(center_x, text_y - text_height * 3.2), wrapWidth=W * wrap,
                                          units='pix', anchorVert='top', alignText='center'))

    def draw(self) -> None:
        for stim in self.stims:
            stim.draw()


def change_screen_stims(win, change: ChangeDisplay, domain: Optional[str], continue_key: str) -> List:
    """수정 순위 전에 전체 화면으로 보여 주는 가상 변화 안내의 자극 목록.

    continue_key : 화면 아래 "[키]를 눌러 계속" 에 표시할 키 이름
    반환          : 순서대로 draw() 하면 되는 자극 목록
    """
    W, H = (int(v) for v in win.size)
    stims: List = [ChangePanel(win, change, center=(0, H * 0.08), scale=1.4, wrap=0.7)]
    if domain:
        stims.append(_domain_image_stim(win, domain))
    stims.append(visual.TextStim(win, text=rt("change_continue", key=continue_key), font=S.FONT,
                                 height=max(int(H * 0.026), 16), color='white', pos=(0, -H * 0.5 + H * 0.055),
                                 units='pix'))
    return stims
