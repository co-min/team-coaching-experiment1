"""
Standalone preview of the attribute appraisal (no learning trials, no hardware).

The appraisal type comes from the block's phase (config/settings.py BLOCK_PHASES):
    phase_1 (competence visible) → Synergy appraisal:    6 pairs
    phase_2 (synergy visible)    → Competence appraisal: 4 animals × COMPETENCE_APPRAISAL_DOMAINS
so the default --blocks 0,1 shows one of each.

For each requested block, each requested checkpoint runs in order (middle, then end).
With --with-ranking, the block's performance + counterfactual ranking follows the end
appraisal, as in the planned block flow (placeholder probe conditions, see tools/preview_ranking.py).

Usage (from the project root)
-----------------------------
    python -m tools.preview_appraisal                          # block 0 (synergy) + block 1 (competence), middle
    python -m tools.preview_appraisal --blocks 1 --checkpoints middle,end
    python -m tools.preview_appraisal --blocks 0 --checkpoints end --with-ranking
    python -m tools.preview_appraisal --eng --fullscr

Keys: ← LOW, ↓ MEDIUM, → HIGH, Space confirm, Esc abort (config/appraisal.py APPRAISAL_KEYS).
Output: data/preview/sub-{id}/{session}/appraisals.csv (+ rankings.csv with --with-ranking).
After the run, the saved rows are printed with their true values (never shown on screen).
"""

import argparse
import csv
from datetime import datetime

from psychopy import core, monitors, visual

from config import settings as S
from config.appraisal import APPRAISAL_CHECKPOINTS
from config.paths import DATA_DIR
from recording.stimuli_loader import load_stimuli


def _make_window(fullscr: bool) -> visual.Window:
    mon = monitors.Monitor("testMonitor")
    mon.setSizePix(S.WINDOW_SIZE)
    return visual.Window(size=S.WINDOW_SIZE, fullscr=fullscr, color=S.BACKGROUND_COLOR, colorSpace="hex",
                         units="pix", monitor=mon, allowGUI=True, winType="pyglet")


def _trial_after(checkpoint: str) -> int:
    """The learning-trial number a checkpoint follows in the real task (7 for 'middle', 15 for 'end')."""
    for trial_number, name in APPRAISAL_CHECKPOINTS.items():
        if name == checkpoint:
            return trial_number
    raise SystemExit(f"unknown checkpoint {checkpoint!r}; expected one of {sorted(APPRAISAL_CHECKPOINTS.values())}")


def _run_ranking(win, stim, subject_id, subject_dir, session_id, block_index) -> bool:
    """The block's performance + counterfactual ranking. Returns True if aborted with Esc."""
    from config.ranking_strings import rt
    from task.ranking.assessments import RankingEnv, run_block_rankings
    from task.ranking.inputs import KeySource
    from task.ranking.items import load_attributes
    from task.ranking.view import key_names
    from task.screens.instructions import show_instructions
    from tools.preview_ranking import _placeholder_conditions

    env = RankingEnv(win=win, global_clock=core.Clock(), source=KeySource(), stim=stim,
                     attrs=load_attributes(stim.synergy), subject_id=subject_id, subject_dir=subject_dir,
                     session_id=session_id)
    show_instructions(win, rt("rank_intro_performance", key=key_names()['select']), advance_key='space')
    return run_block_rankings(env, block_index, block_index, _placeholder_conditions()).aborted


def _print_summary(subject_dir) -> None:
    """Print every saved appraisal row, including the ground truth the participant never saw."""
    path = subject_dir / "appraisals.csv"
    if not path.exists():
        print("No appraisal rows saved.")
        return
    with open(path, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    print(f"\nSaved {len(rows)} appraisal rows to {path}")
    print(f"{'appraisal':12s} {'#':>2s} {'type':10s} {'domain':10s} {'item':6s} {'animals':16s} "
          f"{'status':9s} {'resp':5s} {'rt':>7s} {'true':>5s} {'level':5s} correct")
    for row in rows:
        if row['appraisal_type'] == 'synergy':
            item = row['pair_id']
            animals = row['pair_animals']
        else:
            item = row['animal_id']
            animals = row['animal_name']
        print(f"{row['appraisal_id']:12s} {row['presentation_order']:>2s} {row['appraisal_type']:10s} "
              f"{row['domain'] or '-':10s} {item:6s} {animals:16s} {row['status']:9s} {row['response']:5s} "
              f"{row['response_rt']:>7.7s} {row['true_attribute_value']:>5s} {row['true_attribute_level']:5s} "
              f"{row['correct']}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("subject_id", nargs="?", default="preview")
    ap.add_argument("--blocks", default="0,1", help="comma-separated original block IDs (default 0,1)")
    ap.add_argument("--checkpoints", default="middle", help="comma-separated: middle, end (default middle)")
    ap.add_argument("--with-ranking", action="store_true",
                    help="after the 'end' appraisal, run the block's ranking (placeholder probes)")
    ap.add_argument("--eng", action="store_true", help="English text")
    ap.add_argument("--fullscr", action="store_true")
    args = ap.parse_args()
    if args.eng:
        S.MODE_ENG = True

    block_indices = [int(b) for b in args.blocks.split(",")]
    checkpoints = [c.strip() for c in args.checkpoints.split(",")]
    for block_index in block_indices:
        if block_index < 0 or block_index >= len(S.BLOCK_PHASES):
            raise SystemExit(f"--blocks {block_index} outside 0–{len(S.BLOCK_PHASES) - 1}")
    for checkpoint in checkpoints:
        _trial_after(checkpoint)                 # stops here on an unknown name

    from task.appraisal.items import appraisal_type_for_phase
    from task.appraisal.run import make_appraisal_env, run_appraisal
    from task.screens.instructions import show_instructions

    stim = load_stimuli()
    session_id = datetime.now().strftime("%Y%m%dT%H%M%S")
    subject_dir = DATA_DIR / "preview" / f"sub-{args.subject_id}" / session_id

    win = _make_window(args.fullscr)
    env = make_appraisal_env(win, core.Clock(), stim, args.subject_id, subject_dir, session_id)
    print(f"Key backend: {env.source.backend}")

    try:
        for block_index in block_indices:
            phase = S.BLOCK_PHASES[block_index]
            appraisal_type = appraisal_type_for_phase(phase)
            for checkpoint in checkpoints:
                trial_after = _trial_after(checkpoint)
                show_instructions(win, f"[Preview] block {block_index} — {phase} — {appraisal_type} appraisal\n"
                                       f"{checkpoint} (after trial {trial_after})\n"
                                       f"{', '.join(stim.animal_groups[block_index])}\n\n"
                                       f"(learning trials skipped)\n\n[Space]", advance_key='space')
                result = run_appraisal(env, block_index, phase, checkpoint, trial_after)
                if result.aborted:
                    return
                if checkpoint == 'end' and args.with_ranking:
                    if _run_ranking(win, stim, args.subject_id, subject_dir, session_id, block_index):
                        return
    finally:
        win.close()
        _print_summary(subject_dir)
        core.quit()


if __name__ == "__main__":
    main()
