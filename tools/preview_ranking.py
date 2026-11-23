"""
Standalone preview of the end-of-block rankings (no learning trials, no hardware).

For each requested block, per probe:
    baseline performance ranking → hypothetical change → revised ranking
Both rankings use the block's domain from config/ranking.py
PERFORMANCE_RANKING_DOMAINS (block 0 cooking, 1 repairing, 2 tennis, 3 cooking, ...).

The latent-attribute appraisal (High / Medium / Low, after trials 7 / 15) is a
separate module still to be written and is not run here.

Usage (from the project root)
-----------------------------
    python -m tools.preview_ranking                    # blocks 0 (competence-visible) and 1 (synergy-visible)
    python -m tools.preview_ranking --blocks 0,1,2,3,4,5   # whole domain schedule
    python -m tools.preview_ranking --blocks 2 --eng   # one block, English text
    python -m tools.preview_ranking --fullscr

Output: data/preview/sub-{id}/{session}/  (rankings.csv, ranking_events.csv, rankings/*.json)
Keys: config/ranking.py RANKING_KEYS. [Esc] aborts (the current ranking is saved as 'aborted').

Checks
    before the first screen : the domain schedule is balanced (refuses to start otherwise)
    after the run           : the saved rankings.csv rows follow the schedule

The probe conditions in _demo_conditions below are placeholders — the actual
probe conditions are not decided yet. They carry no domain; each is bound to
the block's ranking domain at run time.
"""

import argparse
from datetime import datetime

from psychopy import core, monitors, visual

from config import settings as S
from config.paths import DATA_DIR
from recording.stimuli_loader import load_stimuli


# Placeholder probe conditions (role codes, original-table scale). Not the experiment's conditions.
def _demo_conditions():
    from task.ranking.assessments import ProbeCondition
    return [
        ProbeCondition(1, 'competence', ('C',), 8.5),        # C's skill in the block's domain → high
        ProbeCondition(2, 'synergy',    ('B', 'C'), 1.4),    # B–C teamwork → high
    ]


def _check_schedule(block_indices):
    """Startup check. Stops the preview if the domain schedule is unbalanced or a
    requested block does not exist; otherwise prints the schedule."""
    from config.ranking import PERFORMANCE_RANKING_DOMAINS
    from task.ranking.schedule import ranking_domain, ranking_domain_problems

    problems = ranking_domain_problems(PERFORMANCE_RANKING_DOMAINS, S.BLOCK_PHASES, S.DOMAINS)

    n_blocks = len(S.BLOCK_PHASES)
    for block_index in block_indices:
        if block_index < 0 or block_index >= n_blocks:
            problems.append(f"--blocks {block_index} outside 0–{n_blocks - 1}")

    if problems:
        message = "Performance ranking schedule check failed:"
        for problem in problems:
            message += "\n  " + problem
        raise SystemExit(message)

    print("Performance ranking domain schedule (check passed)")
    for block_index in range(n_blocks):
        phase = S.BLOCK_PHASES[block_index]
        domain = ranking_domain(block_index)
        if block_index in block_indices:
            mark = "  <- run"
        else:
            mark = ""
        print(f"  block {block_index}  {phase}  {domain}{mark}")


def _make_window(fullscr: bool) -> visual.Window:
    mon = monitors.Monitor("testMonitor")
    mon.setSizePix(S.WINDOW_SIZE)
    return visual.Window(size=S.WINDOW_SIZE, fullscr=fullscr, color=S.BACKGROUND_COLOR, colorSpace="hex",
                         units="pix", monitor=mon, allowGUI=True, winType="pyglet")


def _print_summary(subject_dir):
    """After the run: print every saved ranking, then check the saved rows against the schedule."""
    import csv

    path = subject_dir / "rankings.csv"
    if not path.exists():
        return
    with open(path, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    print(f"\nSaved to {subject_dir}")
    _print_rankings_table(rows)
    _print_saved_data_check(rows)


def _change_text(row) -> str:
    """Short description of a row's hypothetical change, e.g. 'competence:C:tennis' or 'synergy:B+C:-'."""
    if row['change_kind'] == '':
        return ''                      # baseline rankings have no change
    change_domain = row['change_domain']
    if change_domain == '':
        change_domain = '-'            # synergy changes have no domain
    return f"{row['change_kind']}:{row['change_roles']}:{change_domain}"


def _print_rankings_table(rows):
    print(f"{'ranking_id':24s} {'phase':8s} {'domain':10s} {'change':22s} {'status':9s} {'rt':>7s} "
          f"{'keys':>4s}  {'final (roles)':18s} {'true order':18s} rho")
    for row in rows:
        print(f"{row['ranking_id']:24s} {row['phase']:8s} {row['domain']:10s} {_change_text(row):22s} "
              f"{row['status']:9s} {row['total_rt']:>7.7s} {row['n_keypresses']:>4s}  "
              f"{row['final_ranking']:18s} {row['true_order']:18s} {row['spearman_true']}")
        print(f"{'':24s} {row['final_ranking_animals']}   true values: {row['true_values']}")


def _print_saved_data_check(rows):
    """Check the saved rows with task.ranking.schedule.saved_ranking_problems and print the result."""
    from config.ranking import PERFORMANCE_RANKING_DOMAINS
    from task.ranking.schedule import saved_ranking_problems

    problems = saved_ranking_problems(rows, PERFORMANCE_RANKING_DOMAINS, S.BLOCK_PHASES)

    if problems:
        print("\nSaved-data check FAILED:")
        for problem in problems:
            print("  " + problem)
    else:
        print("\nSaved-data check passed")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("subject_id", nargs="?", default="preview")
    ap.add_argument("--blocks", default="0,1", help="comma-separated block indices (default 0,1)")
    ap.add_argument("--eng", action="store_true", help="English text")
    ap.add_argument("--fullscr", action="store_true")
    args = ap.parse_args()
    if args.eng:
        S.MODE_ENG = True
    block_indices = [int(b) for b in args.blocks.split(",")]
    _check_schedule(block_indices)

    # Imported after MODE_ENG is set (text is looked up at call time, but keep it explicit).
    from config.ranking_strings import rt
    from task.ranking.assessments import RankingEnv, run_counterfactual_probe
    from task.ranking.inputs import KeySource
    from task.ranking.items import load_attributes
    from task.ranking.schedule import ranking_domain
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
        for block_index in block_indices:
            phase = S.BLOCK_PHASES[block_index]
            domain = ranking_domain(block_index)
            show_instructions(win, f"[Preview] Block {block_index + 1} — {phase} — {domain}\n"
                                   f"{', '.join(stim.animal_groups[block_index])}\n\n"
                                   f"(learning trials skipped)\n\n[Space]", advance_key=start_key)
            show_instructions(win, rt("rank_intro_performance", key=names['select']), advance_key=start_key)
            for condition in _demo_conditions():
                results = run_counterfactual_probe(env, block_index, phase, condition.for_domain(domain))
                if len(results) < 2 or results[-1].aborted:
                    return
    finally:
        win.close()
        _print_summary(subject_dir)
        core.quit()


if __name__ == "__main__":
    main()
