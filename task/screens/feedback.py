"""
Feedback screen — domain-specific score display with monkey narrator.

The raw pair score is normalised to stage 1–6 using the domain's (min, max)
from the active score table; the stage picks the bubble colour and comment.
"""

from psychopy import visual, core, event

from config.paths import MONKEY_IMAGE, animal_image, domain_image
from config.settings import FB_TIME, FONT
from config.strings import t, domain_name, monkey_comment
from hardware.events import callonflip_feedback
from hardware.frame_marker import get_shared_marker
from recording.frame_logger import FrameLog, FrameRecorder
from task.screens.instructions import check_escape

# ── Layout constants ──────────────────────────────────────────────────────────

_MONKEY_SIZE     = (250, 250)
_MONKEY_POS      = (-240,   0)
_BUBBLE_POS      = ( 250,   0)
_BUBBLE_TAIL_POS = (   5,   0)

_CHOICE_ANIMAL_SIZE = (150, 150)
_CHOICE_L_POS       = ( 165, 250)   # bubble-center x, left
_CHOICE_R_POS       = ( 335, 250)

_DOMAIN_IMG_SIZE = (150, 150)
_DOMAIN_IMG_POS  = (-200, 250)

_monkey_stim_cache: dict = {}

# 6-step color ramp (red → green)
_RESULT_COLORS = ["#F44336", "#FF5722", "#FF9800", "#FFEB3B", "#8BC34A", "#4CAF50"]


def score_to_stage(score: float, domain: str, score_ranges: dict) -> int:
    """Normalise raw score to stage 1–6 using domain min/max from the score table."""
    lo, hi = score_ranges.get(domain, (3.0, 9.0))
    if hi == lo:
        return 3
    return max(1, min(6, int(1 + (score - lo) / (hi - lo) * 5 + 0.5)))


# ── Stim builders ─────────────────────────────────────────────────────────────

def _monkey_text(score: float, stage: int, domain: str, score_ranges: dict) -> str:
    _, hi = score_ranges.get(domain, (0.0, 10.0))
    max_score = int(hi) if hi == int(hi) else hi
    return t("feedback_bubble", max_score=max_score, score=f"{score:g}",
             comment=monkey_comment(domain, stage))


def _get_monkey_stim(win: visual.Window) -> 'visual.ImageStim | None':
    wid = id(win)
    if wid not in _monkey_stim_cache:
        try:
            _monkey_stim_cache[wid] = visual.ImageStim(
                win, image=str(MONKEY_IMAGE), size=_MONKEY_SIZE, pos=_MONKEY_POS
            )
        except Exception:
            _monkey_stim_cache[wid] = None
    return _monkey_stim_cache[wid]


def _build_domain_img_stims(win: visual.Window, domain: str) -> list:
    try:
        return [visual.ImageStim(win, image=domain_image(domain),
                                 pos=_DOMAIN_IMG_POS, size=_DOMAIN_IMG_SIZE)]
    except Exception:
        return []


def _build_choice_animal_stims(win: visual.Window, animal1: str = None, animal2: str = None) -> list:
    stims = []
    for animal, pos in [(animal1, _CHOICE_L_POS), (animal2, _CHOICE_R_POS)]:
        if not animal:
            continue
        try:
            stims.append(visual.ImageStim(win, image=animal_image(animal),
                                          pos=pos, size=_CHOICE_ANIMAL_SIZE))
        except Exception:
            pass
    return stims


def _build_monkey_stims(win: visual.Window, stage: int, score: float, domain: str,
                        score_ranges: dict) -> list:
    bubble_text  = _monkey_text(score, stage, domain, score_ranges)
    bubble_color = _RESULT_COLORS[stage - 1]
    stims = []
    monkey = _get_monkey_stim(win)
    if monkey is not None:
        stims.append(monkey)
    stims += [
        visual.Rect(win, width=480, height=280, pos=_BUBBLE_POS,
                    fillColor=bubble_color, lineColor=bubble_color),
        visual.ShapeStim(win, vertices=[(-45, 0), (18, 25), (18, -25)],
                         pos=_BUBBLE_TAIL_POS, fillColor=bubble_color, lineColor=bubble_color),
        visual.TextStim(win, text=bubble_text,
                        pos=_BUBBLE_POS, color='#222222', height=44, bold=True,
                        font=FONT, wrapWidth=450),
    ]
    return stims


def _make_domain_xs(domains: list) -> dict:
    n_domains = len(domains)
    x_spacing = 300 if n_domains <= 2 else 250
    return {d: int(-x_spacing * (n_domains - 1) / 2 + i * x_spacing) for i, d in enumerate(domains)}


# ── Public entry point ────────────────────────────────────────────────────────

def run_feedback(
    win: visual.Window,
    score: float,
    domain: str,
    score_ranges: dict,
    block_domains: list,
    cumulative_score: float = 0,
    phase_score: float = 0,
    domain_scores: dict = None,
    n_trials_per_domain: int = 18,
    handle=None,
    phase: int = 0,
    trial_index: int = 0,
    animal1: str = None,
    animal2: str = None,
    neon_client=None,
    frame_log: FrameLog = None,
    global_clock=None,
) -> None:
    """Display domain-specific feedback with monkey narrator for FB_TIME seconds.

    score_ranges  : {domain: (min, max)} for the phase being run
    block_domains : domains shown in the per-domain score row
    frame_log     : when given (with global_clock), frames are logged under "FEEDBACK"
    """
    stage     = score_to_stage(score, domain, score_ranges)
    domain_xs = _make_domain_xs(block_domains)
    max_score_per_trial = max(hi for _, hi in score_ranges.values())
    max_phase = n_trials_per_domain * len(domain_xs) * max_score_per_trial

    domain_score_stims = []
    if domain_scores:
        for d, x in domain_xs.items():
            val   = float(domain_scores.get(d, 0))
            color = "#FF9800" if d == domain else "#AAAAAA"
            domain_score_stims.append(visual.TextStim(
                win, text=t("feedback_domain_score", domain=domain_name(d), score=val),
                pos=(x, -225), color=color, height=38, font=FONT, bold=(d == domain),
            ))

    stims = (
        _build_domain_img_stims(win, domain)
        + _build_choice_animal_stims(win, animal1, animal2)
        + _build_monkey_stims(win, stage, score, domain, score_ranges)
        + domain_score_stims
        + [
            visual.TextStim(win, text=t("feedback_phase_score", cur=int(phase_score), max=int(max_phase)),
                            pos=(0, -285), color="#AAAAAA", height=40, font=FONT, bold=False),
            visual.TextStim(win, text=t("feedback_total_score", score=float(cumulative_score)),
                            pos=(0, -340), color="#FFD700", height=48, font=FONT, bold=True),
        ]
    )

    recorder = None
    if frame_log is not None and global_clock is not None:
        recorder = FrameRecorder(frame_log, global_clock, photodiode=get_shared_marker())
        recorder.start_segment("FEEDBACK")

    event.clearEvents()
    clock        = core.Clock()
    trigger_sent = False
    while clock.getTime() < FB_TIME:
        for stim in stims:
            stim.draw()
        if not trigger_sent:
            callonflip_feedback(win, neon_client, handle, phase, trial_index)
            trigger_sent = True
        if recorder is not None:
            recorder.flip_and_log(win)
        else:
            win.flip()
        check_escape(win)

    event.clearEvents()
