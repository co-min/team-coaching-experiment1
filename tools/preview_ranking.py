"""
Standalone preview of the end-of-block rankings (no learning trials, no hardware).

For each requested block (shared-baseline design):
    baseline performance ranking (once)
    → hypothetical change 1 → revised ranking 1 (starts from the baseline)
    → "change no longer applies" screen
    → hypothetical change 2 → revised ranking 2 (starts from the baseline again)
The ranking domain and probe order come from config/ranking.py
(PERFORMANCE_RANKING_DOMAINS, PROBE_ORDERS), looked up by original block ID.

Blocks run in the subject's counterbalance order (config/settings.py BLOCK_ORDERS:
group A = odd subject ID, group B = even), restricted to --blocks.
presentation_pos is the block's position in that full order.

The latent-attribute estimate (High / Medium / Low, after trials 7 / 15) is a
separate module still to be written and is not run here.

Usage (from the project root)
-----------------------------
    python -m tools.preview_ranking                        # blocks 0 and 1, group A
    python -m tools.preview_ranking 002 --blocks 0,1,2,3,4,5   # whole schedule, group B order
    python -m tools.preview_ranking --group B --blocks 2,3
    python -m tools.preview_ranking --blocks 2 --eng       # English text
    python -m tools.preview_ranking --fullscr

Output: data/preview/sub-{id}/{session}/  (rankings.csv, ranking_events.csv, rankings/*.json)
Keys: config/ranking.py RANKING_KEYS. [Esc] aborts (the current ranking is saved as 'aborted').

Checks
    before the first screen : domain, probe-order and block-order schedules are valid
                              (refuses to start otherwise)
    after the run           : the saved rankings.csv rows follow the schedules and
                              both revisions start from the shared baseline

The probe conditions in _placeholder_conditions below are placeholders — the actual
candidate schedule is not decided yet. They carry no domain or position; each is
bound to the block's ranking domain and probe order at run time.
"""

import argparse
from datetime import datetime

from psychopy import core, monitors, visual

from config import settings as S
from config.paths import DATA_DIR
from recording.stimuli_loader import load_stimuli


# Placeholder probe conditions (role codes, original-table scale). Not the experiment's conditions.
def _placeholder_conditions():
    from task.ranking.assessments import ProbeCondition
    return {
        'competence': ProbeCondition('competence', ('C',), 8.5),     # C's skill in the block's domain → high
        'synergy':    ProbeCondition('synergy', ('B', 'C'), 1.4),    # B–C teamwork → high
    }


def _resolve_group(subject_id, group_arg):
    """--group if given, else the subject ID's parity. A non-numeric ID without --group runs as group A."""
    from task.schedule import counterbalance_group
    if group_arg:
        return group_arg
    try:
        return counterbalance_group(subject_id)
    except ValueError:
        print(f"Subject ID {subject_id!r} has no trailing number; previewing as group A (use --group).")
        return 'A'


def _check_schedule(block_indices, group):
    """Startup check. Stops the preview if a schedule is invalid or a requested block
    does not exist; otherwise prints the schedule in presentation order."""
    from config.ranking import PERFORMANCE_RANKING_DOMAINS, PROBE_ORDERS
    from task.ranking.schedule import probe_order, probe_order_problems, ranking_domain, ranking_domain_problems
    from task.schedule import block_order, block_order_problems, presentation_order_problems

    n_blocks = len(S.BLOCK_PHASES)
    problems = ranking_domain_problems(PERFORMANCE_RANKING_DOMAINS, S.BLOCK_PHASES, S.DOMAINS)
    problems += probe_order_problems(PROBE_ORDERS, S.BLOCK_PHASES, PERFORMANCE_RANKING_DOMAINS)
    order_problems = block_order_problems(S.BLOCK_ORDERS, n_blocks)
    if not order_problems:   # the presentation check needs valid block IDs (same as main.py)
        order_problems = presentation_order_problems(S.BLOCK_ORDERS, S.BLOCK_PHASES)
    problems += order_problems

    for block_index in block_indices:
        if block_index < 0 or block_index >= n_blocks:
            problems.append(f"--blocks {block_index} outside 0–{n_blocks - 1}")

    if problems:
        message = "Ranking schedule check failed:"
        for problem in problems:
            message += "\n  " + problem
        raise SystemExit(message)

    print(f"Ranking schedule, group {group} presentation order (check passed)")
    for position, block_index in enumerate(block_order(group)):
        phase = S.BLOCK_PHASES[block_index]
        order = ' > '.join(probe_order(block_index))
        if block_index in block_indices:
            mark = "  <- run"
        else:
            mark = ""
        print(f"  pos {position}  block {block_index}  {phase}  {ranking_domain(block_index):10s} {order}{mark}")


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
    print(f"{'ranking_id':24s} {'pos':>3s} {'phase':8s} {'domain':10s} {'change':22s} {'status':9s} "
          f"{'rt':>7s} {'keys':>4s}  {'initial (roles)':18s} {'final (roles)':18s} {'true order':18s} rho")
    for row in rows:
        print(f"{row['ranking_id']:24s} {row['presentation_pos']:>3s} {row['phase']:8s} {row['domain']:10s} "
              f"{_change_text(row):22s} {row['status']:9s} {row['total_rt']:>7.7s} {row['n_keypresses']:>4s}  "
              f"{row['initial_ranking']:18s} {row['final_ranking']:18s} {row['true_order']:18s} "
              f"{row['spearman_true']}")
        print(f"{'':24s} {row['final_ranking_animals']}   true values: {row['true_values']}")


def _print_saved_data_check(rows):
    """Check the saved rows with task.ranking.schedule.saved_ranking_problems and print the result."""
    from config.ranking import PERFORMANCE_RANKING_DOMAINS, PROBE_ORDERS
    from task.ranking.schedule import saved_ranking_problems

    problems = saved_ranking_problems(rows, PERFORMANCE_RANKING_DOMAINS, S.BLOCK_PHASES, PROBE_ORDERS)

    if problems:
        print("\nSaved-data check FAILED:")
        for problem in problems:
            print("  " + problem)
    else:
        print("\nSaved-data check passed")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("subject_id", nargs="?", default="preview")
    ap.add_argument("--blocks", default="0,1", help="comma-separated original block IDs (default 0,1)")
    ap.add_argument("--group", choices=sorted(S.BLOCK_ORDERS),
                    help="counterbalance group (default: from the subject ID's parity)")
    ap.add_argument("--eng", action="store_true", help="English text")
    ap.add_argument("--fullscr", action="store_true")
    args = ap.parse_args()
    if args.eng:
        S.MODE_ENG = True
    block_indices = [int(b) for b in args.blocks.split(",")]
    group = _resolve_group(args.subject_id, args.group)
    _check_schedule(block_indices, group)

    # Imported after MODE_ENG is set (text is looked up at call time, but keep it explicit).
    from config.ranking_strings import rt
    from task.ranking.assessments import RankingEnv, run_block_rankings
    from task.ranking.inputs import KeySource
    from task.ranking.items import load_attributes
    from task.ranking.schedule import ranking_domain
    from task.ranking.view import key_names
    from task.schedule import block_order
    from task.screens.instructions import show_instructions

    stim = load_stimuli()
    session_id = datetime.now().strftime("%Y%m%dT%H%M%S")
    subject_dir = DATA_DIR / "preview" / f"sub-{args.subject_id}" / session_id

    win = _make_window(args.fullscr)
    env = RankingEnv(win=win, global_clock=core.Clock(), source=KeySource(), stim=stim,
                     attrs=load_attributes(stim.synergy), subject_id=args.subject_id,
                     subject_dir=subject_dir, session_id=session_id, counterbalance_group=group)
    print(f"Key backend: {env.source.backend}")
    start_key = 'space'
    names = key_names()
    conditions = _placeholder_conditions()

    try:
        for position, block_index in enumerate(block_order(group)):
            if block_index not in block_indices:
                continue
            phase = S.BLOCK_PHASES[block_index]
            show_instructions(win, f"[Preview] group {group}, position {position + 1} — block {block_index} — "
                                   f"{phase} — {ranking_domain(block_index)}\n"
                                   f"{', '.join(stim.animal_groups[block_index])}\n\n"
                                   f"(learning trials skipped)\n\n[Space]", advance_key=start_key)
            show_instructions(win, rt("rank_intro_performance", key=names['select']), advance_key=start_key)
            if run_block_rankings(env, block_index, position, conditions).aborted:
                return
    finally:
        win.close()
        _print_summary(subject_dir)
        core.quit()


if __name__ == "__main__":
    main()
