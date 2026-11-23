"""
Standalone preview of the end-of-block rankings (no learning trials, no hardware).

For each requested block, per probe:
    baseline performance ranking → hypothetical change → revised ranking

The latent-attribute appraisal (High / Medium / Low, after trials 7 / 15) is a
separate module still to be written and is not run here.

Usage (from the project root)
-----------------------------
    python -m tools.preview_ranking                    # blocks 0 (competence-visible) and 1 (synergy-visible)
    python -m tools.preview_ranking --blocks 2 --eng   # one block, English text
    python -m tools.preview_ranking --fullscr

Output: data/preview/sub-{id}/{session}/  (rankings.csv, ranking_events.csv, rankings/*.json)
Keys: config/ranking.py RANKING_KEYS. [Esc] aborts (the current ranking is saved as 'aborted').

The probes in _demo_probes below are placeholders — the repository has no
counterfactual schedule yet.
"""

import argparse
from datetime import datetime

from psychopy import core, monitors, visual

from config import settings as S
from config.paths import DATA_DIR
from recording.stimuli_loader import load_stimuli


# Placeholder schedule (role codes, original-table scale). Not the experiment's schedule.
def _demo_probes():
    from task.ranking.assessments import Probe
    from task.ranking.items import Change
    return [
        Probe(1, 'cooking', Change('competence', ('C',), 8.5, domain='cooking')),   # C cooking low → high
        Probe(2, 'tennis',  Change('synergy',    ('B', 'C'), 1.4)),                 # B–C teamwork low → high
    ]


def _make_window(fullscr: bool) -> visual.Window:
    mon = monitors.Monitor("testMonitor")
    mon.setSizePix(S.WINDOW_SIZE)
    return visual.Window(size=S.WINDOW_SIZE, fullscr=fullscr, color=S.BACKGROUND_COLOR, colorSpace="hex",
                         units="pix", monitor=mon, allowGUI=True, winType="pyglet")


def _print_summary(subject_dir):
    import csv
    path = subject_dir / "rankings.csv"
    if not path.exists():
        return
    print(f"\nSaved to {subject_dir}")
    print(f"{'ranking_id':24s} {'status':9s} {'rt':>7s} {'keys':>4s}  {'final (roles)':18s} "
          f"{'true order':18s} rho")
    with open(path, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            print(f"{r['ranking_id']:24s} {r['status']:9s} {r['total_rt'] or '':>7.7s} {r['n_keypresses']:>4s}  "
                  f"{r['final_ranking']:18s} {r['true_order']:18s} {r['spearman_true']}")
            print(f"{'':24s} {r['final_ranking_animals']}   true values: {r['true_values']}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("subject_id", nargs="?", default="preview")
    ap.add_argument("--blocks", default="0,1", help="comma-separated block indices (default 0,1)")
    ap.add_argument("--eng", action="store_true", help="English text")
    ap.add_argument("--fullscr", action="store_true")
    args = ap.parse_args()
    if args.eng:
        S.MODE_ENG = True

    # Imported after MODE_ENG is set (text is looked up at call time, but keep it explicit).
    from config.ranking_strings import rt
    from task.ranking.assessments import RankingEnv, run_counterfactual_probe
    from task.ranking.inputs import KeySource
    from task.ranking.items import load_attributes
    from task.ranking.view import key_names
    from task.screens.instructions import show_instructions

    stim = load_stimuli()
    session_id = datetime.now().strftime("%Y%m%dT%H%M%S")
    subject_dir = DATA_DIR / "preview" / f"sub-{args.subject_id}" / session_id

    win = _make_window(args.fullscr)
    env = RankingEnv(win=win, global_clock=core.Clock(), source=KeySource(), stim=stim,
                     attrs=load_attributes(stim.synergy), subject_id=args.subject_id,
                     subject_dir=subject_dir, session_id=session_id)
    print(f"Key backend: {env.source.backend}")
    start_key = 'space'
    names = key_names()

    try:
        for block_index in (int(b) for b in args.blocks.split(",")):
            phase = S.BLOCK_PHASES[block_index]
            show_instructions(win, f"[Preview] Block {block_index + 1} — {phase}\n"
                                   f"{', '.join(stim.animal_groups[block_index])}\n\n"
                                   f"(learning trials skipped)\n\n[Space]", advance_key=start_key)
            show_instructions(win, rt("rank_intro_performance", key=names['select']), advance_key=start_key)
            for probe in _demo_probes():
                results = run_counterfactual_probe(env, block_index, phase, probe)
                if len(results) < 2 or results[-1].aborted:
                    return
    finally:
        win.close()
        _print_summary(subject_dir)
        core.quit()


if __name__ == "__main__":
    main()
