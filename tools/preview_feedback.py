"""
Standalone preview of the feedback (monkey narrator) screen — no trials, no hardware.

By default every stage 1–6 is shown in turn for the domain (each for FB_TIME seconds),
with the raw score chosen from the domain's score range so the stage matches.

Usage (from the project root)
-----------------------------
    python -m tools.preview_feedback                          # cooking, stages 1–6
    python -m tools.preview_feedback --domain tennis
    python -m tools.preview_feedback --stages 1,6             # only stages 1 and 6
    python -m tools.preview_feedback --score 7.5              # one screen with this raw score
    python -m tools.preview_feedback --block 2 --eng --fullscr

Esc quits immediately.
"""

import argparse

from psychopy import monitors, visual

from config import settings as S


def _make_window(fullscr: bool) -> visual.Window:
    mon = monitors.Monitor("testMonitor")
    mon.setSizePix(S.WINDOW_SIZE)
    return visual.Window(size=S.WINDOW_SIZE, fullscr=fullscr, color=S.BACKGROUND_COLOR, colorSpace="hex",
                         units="pix", monitor=mon, allowGUI=True, winType="pyglet")


def _score_for_stage(stage: int, lo: float, hi: float) -> float:
    """Raw score at the centre of a stage's bin (inverse of score_to_stage)."""
    return round(lo + (stage - 1) / 5 * (hi - lo), 1)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--domain", default=S.DOMAINS[0], choices=S.DOMAINS)
    p.add_argument("--stages", default="1,2,3,4,5,6", help="comma-separated stages 1–6")
    p.add_argument("--score", type=float, help="show a single screen with this raw score instead")
    p.add_argument("--block", type=int, default=0, help="block whose animal group is shown as the choice pair")
    p.add_argument("--eng", action="store_true", help="English strings (MODE_ENG)")
    p.add_argument("--fullscr", action="store_true")
    args = p.parse_args()

    if args.eng:
        S.MODE_ENG = True

    # Imported after MODE_ENG is set so the strings pick up the language.
    from hardware.neon import NullNeonClient
    from recording.stimuli_loader import load_stimuli
    from task.screens.feedback import run_feedback, score_to_stage

    stim = load_stimuli()
    lo, hi = stim.score_ranges[args.domain]
    animals = stim.animal_groups[args.block % len(stim.animal_groups)]

    if args.score is not None:
        scores = [args.score]
    else:
        scores = [_score_for_stage(int(s), lo, hi) for s in args.stages.split(",")]

    win = _make_window(args.fullscr)
    neon = NullNeonClient()
    cumulative = 0.0
    for i, score in enumerate(scores):
        cumulative += score
        print(f"[{i + 1}/{len(scores)}] {args.domain} score={score:g} "
              f"(range {lo:g}–{hi:g}) → stage {score_to_stage(score, args.domain, stim.score_ranges)}")
        run_feedback(
            win, score, args.domain, stim.score_ranges,
            block_score=cumulative,
            handle=None, phase=1, trial_index=i,
            animal1=animals[0], animal2=animals[1], neon_client=neon,
        )
    win.close()


if __name__ == "__main__":
    main()
