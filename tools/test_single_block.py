"""
Single-block test run of the full Experiment 1 block flow (real trials, real tables).

    phase instruction → trials 1–7 (forced first choice) → middle appraisal
    → trials 8–15 → end appraisal
    → baseline performance ranking → probe 1 → "change no longer applies" → probe 2
    → end (no other blocks, no ending screen)

The block itself is main.run_block, the same function the experiment loops over, so
the phase, animals, trial schedule, forced first choices, appraisal type, ranking
domain and probe order all come from the chosen original block ID (0–5).

Test-only differences from main.py
    - only --block runs: block-order counterbalancing is bypassed (presentation_pos 0,
      shown as block 1 / 1, no break screen, counterbalance_group left empty)
    - windowed; LabJack and Neon off unless --labjack / --neon
    - no subject dialog: --subject (default 'test')
    - output: data/test_single_block/block{N}_{session}/sub-{id}/  (never data/sub-{id}/)
    - the ranking runs after the end appraisal, which main.py does not do yet

PROBE CONDITIONS ARE PLACEHOLDERS. The real counterfactual probe conditions are not
decided (see tools/analyze_counterfactuals.py for the candidates). The probes reuse
tools/preview_ranking._placeholder_conditions — the same competence and synergy change
for every block — and the run prints which values are still missing.

Usage (from the project root)
-----------------------------
    python -m tools.test_single_block --block 0
    python -m tools.test_single_block --block 1 --eng
    python -m tools.test_single_block --block 3 --subject pilot01 --labjack --neon

After the run, the saved trials, appraisals and rankings are checked against the schedules.
"""

import argparse
import csv
import json
from datetime import datetime

from psychopy import core

from config import settings as S
from config.appraisal import APPRAISAL_CHECKPOINTS
from config.paths import DATA_DIR

TEST_DATA_DIR = DATA_DIR / "test_single_block"


# ── probe conditions ─────────────────────────────────────────────────────────

def _probe_condition_report(block_id: int, conditions) -> list:
    """Lines describing this block's probe slots and what is still undecided for each."""
    from task.ranking.schedule import probe_order, ranking_domain

    domain = ranking_domain(block_id)
    lines = [f"Block {block_id} ({S.BLOCK_PHASES[block_id]}), ranking domain {domain}, "
             f"probe order {' > '.join(probe_order(block_id))}"]
    for position, kind in enumerate(probe_order(block_id), start=1):
        condition = conditions[kind]
        if kind == 'competence':
            target = f"which animal (role) and its new {domain} competence value"
        else:
            target = "which pair (roles) and its new synergy value"
        lines.append(f"  probe {position} {kind:10s} MISSING: {target}; "
                     f"placeholder used: roles {'+'.join(condition.roles)} → {condition.value}")
    return lines


# ── setup ─────────────────────────────────────────────────────────────────────

def _check_schedules(block_id: int) -> None:
    """Stop before the window opens if the ranking schedules are invalid (same checks as the previews)."""
    from config.ranking import PERFORMANCE_RANKING_DOMAINS, PROBE_ORDERS
    from task.ranking.schedule import probe_order_problems, ranking_domain_problems

    problems = ranking_domain_problems(PERFORMANCE_RANKING_DOMAINS, S.BLOCK_PHASES, S.DOMAINS)
    problems += probe_order_problems(PROBE_ORDERS, S.BLOCK_PHASES, PERFORMANCE_RANKING_DOMAINS)
    if problems:
        raise SystemExit("Ranking schedule check failed:\n  " + "\n  ".join(problems))


def _redirect_output(run_dir) -> None:
    """Every writer that goes through recording.writers.get_subject_dir now writes under run_dir."""
    from recording import writers
    writers.DATA_DIR = run_dir


def _connect_hardware(win, args, subject_id: str, session_id: str):
    """(labjack handle, neon client, neon recording id, apriltags). Both off unless requested."""
    from hardware.labjack import init_labjack
    from hardware.neon import NullNeonClient
    from task.session import _connect_neon

    handle = None
    if args.labjack:
        handle = init_labjack(S.LABJACK_DEVICE)
    if not args.neon:
        return handle, NullNeonClient(), None, []
    neon_client, recording_id, apriltags = _connect_neon(win, subject_id, session_id)
    return handle, neon_client, recording_id, apriltags


def _save_test_note(subject_dir, args, session_id, conditions, report) -> None:
    """test_run.json next to the data, so placeholder probes are never mistaken for real ones."""
    record = {
        "test_mode": "single_block",
        "block_id": args.block,
        "phase": S.BLOCK_PHASES[args.block],
        "session_id": session_id,
        "counterbalancing": "bypassed (presentation_pos 0, counterbalance_group empty)",
        "labjack": args.labjack,
        "neon": args.neon,
        "probe_conditions_status": "placeholder",
        "probe_conditions_used": {kind: {"roles": list(c.roles), "value": c.value}
                                  for kind, c in conditions.items()},
        "probe_conditions_missing": report[1:],
    }
    subject_dir.mkdir(parents=True, exist_ok=True)
    with open(subject_dir / "test_run.json", "w", encoding="utf-8") as f:
        json.dump(record, f, indent=2, ensure_ascii=False)


# ── after the run ─────────────────────────────────────────────────────────────

def _read_csv(path) -> list:
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def saved_block_problems(subject_dir, block_id: int, schedule) -> list:
    """Problems in the saved trials.csv / appraisals.csv for one completed block (empty = passed)."""
    from task.appraisal.items import appraisal_type_for_phase
    from task.forced_first import forced_first_for

    phase = S.BLOCK_PHASES[block_id]
    problems = []

    trials = _read_csv(subject_dir / "trials.csv")
    if len(trials) != len(schedule):
        problems.append(f"trials.csv has {len(trials)} rows, expected {len(schedule)}")
    for row, trial_info in zip(trials, schedule):
        label = f"trial {row['trial_id']}"
        if row['block'] != f"block_{block_id}" or row['phase'] != phase:
            problems.append(f"{label}: block/phase {row['block']}/{row['phase']}, expected block_{block_id}/{phase}")
        if row['domain'] != trial_info['domain']:
            problems.append(f"{label}: domain {row['domain']}, schedule says {trial_info['domain']}")
        expected_first = forced_first_for(trial_info) or ''
        if row['forced_first_animal'] != expected_first:
            problems.append(f"{label}: forced first {row['forced_first_animal']!r}, schedule says {expected_first!r}")

    appraisals = _read_csv(subject_dir / "appraisals.csv")
    expected_type = appraisal_type_for_phase(phase)
    for trial_after, checkpoint in APPRAISAL_CHECKPOINTS.items():
        rows = [r for r in appraisals if r['checkpoint'] == checkpoint]
        if not rows:
            problems.append(f"no {checkpoint} appraisal rows")
            continue
        for row in rows:
            if row['trial_after'] != str(trial_after) or row['appraisal_type'] != expected_type \
                    or row['block_idx'] != str(block_id):
                problems.append(f"{row['appraisal_id']} #{row['presentation_order']}: after trial "
                                f"{row['trial_after']}, {row['appraisal_type']}, block {row['block_idx']}; "
                                f"expected {trial_after}, {expected_type}, block {block_id}")
                break
    return problems


def _print_results(subject_dir, block_id: int, schedule) -> None:
    from tools.preview_appraisal import _print_summary as print_appraisals
    from tools.preview_ranking import _print_summary as print_rankings

    print(f"\nTest output: {subject_dir}")
    print_appraisals(subject_dir)
    print_rankings(subject_dir)        # includes the saved-ranking schedule check

    problems = saved_block_problems(subject_dir, block_id, schedule)
    if problems:
        print("\nTrial / appraisal check FAILED (expected if the run was aborted):")
        for problem in problems:
            print("  " + problem)
    else:
        print("\nTrial / appraisal check passed")


# ── entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--block", type=int, required=True, choices=range(len(S.BLOCK_PHASES)),
                    metavar=f"0-{len(S.BLOCK_PHASES) - 1}", help="original block ID to run")
    ap.add_argument("--subject", default="test", help="subject ID written to the data (default 'test')")
    ap.add_argument("--labjack", action="store_true", help="send LabJack triggers (off by default)")
    ap.add_argument("--neon", action="store_true", help="connect the Neon eye tracker (off by default)")
    ap.add_argument("--eng", action="store_true", help="English text")
    args = ap.parse_args()

    S.WINDOW_FULLSCR = False
    S.USE_NEON = args.neon
    if args.eng:
        S.MODE_ENG = True

    import main as experiment
    from config.ranking_strings import rt
    from hardware.events import on_task_start
    from hardware.frame_marker import init_marker
    from hardware.labjack import close_labjack
    from hardware.neon import save_neon_event_log
    from recording.stimuli_loader import load_stimuli
    from recording.writers import get_subject_dir, save_session_metadata
    from task.block import BlockEnv
    from task.ranking.assessments import RankingEnv, run_block_rankings
    from task.ranking.inputs import KeySource
    from task.ranking.items import load_attributes
    from task.ranking.view import key_names
    from task.screens.instructions import show_instructions
    from task.session import create_window
    from task.visuals import VisualObjectFactory
    from tools.preview_ranking import _placeholder_conditions

    block_id = args.block
    stim = load_stimuli()
    # Before opening the window: an invalid forced-first CSV or ranking schedule aborts here.
    block_schedules, schedule_version = experiment._build_schedules(stim)
    schedule = block_schedules[block_id]
    _check_schedules(block_id)

    conditions = _placeholder_conditions()
    report = _probe_condition_report(block_id, conditions)
    print("WARNING: counterfactual probe conditions are not finalized — running with PLACEHOLDERS.")
    print("\n".join(report))

    session_id = datetime.now().strftime("%Y%m%dT%H%M%S")
    _redirect_output(TEST_DATA_DIR / f"block{block_id}_{session_id}")
    subject_dir = get_subject_dir(args.subject)
    _save_test_note(subject_dir, args, session_id, conditions, report)

    win = create_window()
    handle, neon_client, recording_id, apriltags = _connect_hardware(win, args, args.subject, session_id)
    global_clock = core.Clock()
    init_marker(win)

    factory = VisualObjectFactory(win, stim.animal_groups, S.DOMAINS)
    save_session_metadata(
        subject_id=args.subject, session_id=session_id,
        win_size=(int(win.size[0]), int(win.size[1])),
        mission_mode=4, win_fullscr=S.WINDOW_FULLSCR, monitor_name=S.MONITOR_NAME, frame_rate=S.FRAME_RATE,
        slot_info=factory.get_slot_info(), neon_recording_id=recording_id,
        first_choice_mode=S.FIRST_CHOICE_MODE, schedule_version=schedule_version,
        counterbalance_group=None, block_order=[block_id],
    )
    env = BlockEnv(win=win, global_clock=global_clock, factory=factory, stim=stim,
                   subject_id=args.subject, handle=handle, neon_client=neon_client,
                   schedule_version=schedule_version, session_id=session_id)
    ranking_env = RankingEnv(win=win, global_clock=global_clock, source=KeySource(), stim=stim,
                             attrs=load_attributes(stim.synergy), subject_id=args.subject,
                             subject_dir=subject_dir, session_id=session_id)
    cumulative = {'total': 0, 'phase': 0, **{d: 0 for d in S.DOMAINS}}

    try:
        on_task_start(neon_client, handle)
        # Trials 1–15 with the middle (after 7) and end (after 15) appraisals.
        experiment.run_block(env, block_id, 0, 1, schedule, cumulative)
        show_instructions(win, rt("rank_intro_performance", key=key_names()['select']), advance_key='space')
        run_block_rankings(ranking_env, block_id, 0, conditions)
    finally:
        neon_client.close(S.NEON_SHUTDOWN_FLUSH_TIMEOUT_S)
        save_neon_event_log(subject_dir, neon_client.event_log)
        close_labjack(handle)
        win.close()
        _print_results(subject_dir, block_id, schedule)
    core.quit()


if __name__ == "__main__":
    main()
