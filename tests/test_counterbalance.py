"""
Block-order counterbalancing tests.

    python -m unittest tests.test_counterbalance -v

No window is opened. The session tests run the real main.run_blocks and
task.block.run_block_trials with fake trial and estimate screens, then read
what was written to a temporary data folder.

Two numbers describe a block (see main.py):
    block_id         original block (phase, animals, trials, forced first choices, estimate, ranking)
    presentation_pos where the subject sees it (block number on screen, breaks)
"""

import csv
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from psychopy import core

import main as main_mod
import recording.writers as writers
import task.block as block_mod
from config import settings as S
from config.paths import FORCED_FIRST_CSV, ROOT_DIR
from config.ranking import PERFORMANCE_RANKING_DOMAINS, PROBE_ORDERS
from config.strings import t
from recording.stimuli_loader import load_stimuli
from task.estimate.items import estimate_type_for_phase
from task.block import BlockEnv
from task.forced_first import attach_forced_first, read_schedule_csv
from task.ranking.schedule import probe_order, ranking_domain
from task.schedule import block_order, block_order_problems, generate_block_schedules, presentation_order_problems

STIM = load_stimuli()
AGREED = {'A': (0, 1, 2, 3, 4, 5), 'B': (1, 0, 5, 4, 3, 2)}


def _read_csv(path):
    with open(path, newline='', encoding='utf-8') as f:
        return list(csv.DictReader(f))


# ── the orders themselves ─────────────────────────────────────────────────────

class TestAgreedOrders(unittest.TestCase):
    def test_groups_use_the_agreed_orders(self):
        self.assertEqual(block_order('A'), AGREED['A'])
        self.assertEqual(block_order('B'), AGREED['B'])
        self.assertEqual(sorted(S.BLOCK_ORDERS), ['A', 'B'])

    def test_each_original_block_appears_exactly_once(self):
        for group in ('A', 'B'):
            self.assertEqual(sorted(block_order(group)), list(range(len(S.BLOCK_PHASES))), group)
        self.assertEqual(block_order_problems(S.BLOCK_ORDERS, len(S.BLOCK_PHASES)), [])

    def test_phases_alternate_and_each_group_starts_as_agreed(self):
        for group in ('A', 'B'):
            hidden = [estimate_type_for_phase(S.BLOCK_PHASES[b]) for b in block_order(group)]
            for position in range(1, len(hidden)):
                self.assertNotEqual(hidden[position], hidden[position - 1], (group, position))
            if group == 'A':
                self.assertEqual(hidden[0], 'synergy')       # A starts synergy-hidden (phase_1)
            else:
                self.assertEqual(hidden[0], 'competence')    # B starts competence-hidden (phase_2)

    def test_group_b_ranking_domains(self):
        domains = [PERFORMANCE_RANKING_DOMAINS[b] for b in block_order('B')]
        self.assertEqual(domains, ['repairing', 'cooking', 'tennis', 'repairing', 'cooking', 'tennis'])

    def test_startup_check_accepts_the_config(self):
        self.assertEqual(presentation_order_problems(S.BLOCK_ORDERS, S.BLOCK_PHASES), [])
        main_mod._check_block_orders()                        # does not raise

    def test_startup_check_rejects_broken_orders(self):
        same_phase = {'A': (0, 2, 1, 3, 4, 5)}                # phase_1, phase_1, ...
        problems = presentation_order_problems(same_phase, S.BLOCK_PHASES)
        self.assertTrue(any('both phase_1' in p for p in problems), problems)

        with mock.patch.object(S, 'BLOCK_ORDERS', same_phase):
            with self.assertRaises(SystemExit):
                main_mod._check_block_orders()
        with mock.patch.object(S, 'BLOCK_ORDERS', {'A': (0, 1, 2, 3, 4, 4)}):
            with self.assertRaises(SystemExit):
                main_mod._check_block_orders()

    def test_ranking_schedule_stays_attached_to_the_original_block(self):
        for group in ('A', 'B'):
            for block_id in block_order(group):
                self.assertEqual(ranking_domain(block_id), PERFORMANCE_RANKING_DOMAINS[block_id])
                self.assertEqual(probe_order(block_id), PROBE_ORDERS[block_id])


class TestForcedFirstFileUnchanged(unittest.TestCase):
    def test_csv_and_stimulus_tables_untouched(self):
        result = subprocess.run(['git', 'diff', '--quiet', 'HEAD', '--', str(FORCED_FIRST_CSV), 'stimuli/tables'],
                                cwd=ROOT_DIR, capture_output=True)
        if result.returncode not in (0, 1):
            self.skipTest('git not available')
        self.assertEqual(result.returncode, 0, 'forced-first CSV or stimulus tables differ from HEAD')


# ── a whole (fake) session ────────────────────────────────────────────────────

class TestSessionInPresentationOrder(unittest.TestCase):
    """main.run_blocks → run_block_trials → trials.csv / estimate calls / instruction screens."""

    def _run_session(self, tmp, group):
        schedules = generate_block_schedules(STIM.animal_groups)
        attach_forced_first(schedules, STIM.animal_groups, STIM.char_code)
        log = {'screens': [], 'trials': [], 'estimates': []}

        def fake_trial(win, clock, frame_log, factory, stim, domain, char_order, handle,
                       neon_client=None, forced_first=None):
            log['trials'].append((domain, tuple(char_order), forced_first))
            return None                                      # no response → no feedback screen

        def fake_run_estimate(env, block_id, phase, checkpoint, trial_after, presentation_pos=None):
            log['estimates'].append((block_id, phase, checkpoint, trial_after, presentation_pos,
                                      env.counterbalance_group, env.lj_handle, env.neon))
            return SimpleNamespace(aborted=False)

        def fake_show_instructions(win, text, advance_key='space'):
            log['screens'].append((text, advance_key))

        neon = SimpleNamespace(name='neon')
        env = BlockEnv(win=SimpleNamespace(size=(1000, 700)), global_clock=core.Clock(),
                       factory=SimpleNamespace(get_slot_info=lambda: {'slot_coords': {}, 'animal_size_px': 100}),
                       stim=STIM, subject_id='cb', handle='LJ', neon_client=neon, counterbalance_group=group)
        cumulative = {'total': 0, 'phase': 0, **{d: 0 for d in S.DOMAINS}}
        with mock.patch.object(writers, 'DATA_DIR', Path(tmp)), \
             mock.patch.dict(block_mod.TRIAL_RUNNERS, {'phase_1': fake_trial, 'phase_2': fake_trial}), \
             mock.patch.object(block_mod, 'make_estimate_env',
                               lambda *a, **k: SimpleNamespace(**k)), \
             mock.patch.object(block_mod, 'run_estimate', fake_run_estimate), \
             mock.patch.object(block_mod, 'run_gaussian_iti', lambda *a, **k: None), \
             mock.patch.object(block_mod, 'on_block_start', lambda *a, **k: None), \
             mock.patch.object(main_mod, 'show_instructions', fake_show_instructions):
            main_mod.run_blocks(env, schedules, cumulative)
        return schedules, log

    def test_both_groups(self):
        csv_forced = {(r['block'], r['trial']): r['forced_first'] for r in read_schedule_csv()}
        for group in ('A', 'B'):
            with self.subTest(group=group), tempfile.TemporaryDirectory() as tmp:
                schedules, log = self._run_session(tmp, group)
                order = block_order(group)
                rows = _read_csv(Path(tmp) / 'sub-cb' / 'trials.csv')
                self.assertEqual(len(rows), len(order) * S.N_TRIALS_PER_BLOCK)

                for position, block_id in enumerate(order):
                    block_rows = rows[position * S.N_TRIALS_PER_BLOCK:(position + 1) * S.N_TRIALS_PER_BLOCK]
                    for trial, row in enumerate(block_rows):
                        # identity from the original block
                        self.assertEqual(row['block'], f'block_{block_id}')
                        self.assertEqual(row['phase'], S.BLOCK_PHASES[block_id])
                        self.assertEqual(row['domain'], schedules[block_id][trial]['domain'])
                        self.assertEqual(row['forced_first_animal'], csv_forced[(block_id, trial)])
                        self.assertIn(row['forced_first_animal'], STIM.animal_groups[block_id])
                        self.assertEqual(row['block_trial_id'], str(trial))
                        # position from the presentation order
                        self.assertEqual(row['presentation_pos'], str(position))
                        self.assertEqual(row['counterbalance_group'], group)
                    trial_json = (Path(tmp) / 'sub-cb' / f'block_{block_id}' / S.BLOCK_PHASES[block_id] /
                                  block_rows[0]['domain'] / block_rows[0]['stim_pair_id'] / 'metadata.json')
                    with open(trial_json, encoding='utf-8') as f:
                        record = json.load(f)
                    self.assertEqual((record['presentation_pos'], record['counterbalance_group']), (position, group))

                # the trial screens got each original block's own schedule, in presentation order
                expected_trials = []
                for block_id in order:
                    for trial_info in schedules[block_id]:
                        expected_trials.append((trial_info['domain'], tuple(trial_info['char_order']),
                                                trial_info['forced_first']))
                self.assertEqual(log['trials'], expected_trials)

                # estimates: type from the original block's phase, position for the log, hardware passed on
                expected_estimates = []
                for position, block_id in enumerate(order):
                    phase = S.BLOCK_PHASES[block_id]
                    expected_estimates.append((block_id, phase, 'middle', 7, position, group, 'LJ', 'neon'))
                    expected_estimates.append((block_id, phase, 'end', 15, position, group, 'LJ', 'neon'))
                got = [a[:7] + (a[7].name,) for a in log['estimates']]
                self.assertEqual(got, expected_estimates)

                # screens: block number = position + 1, breaks before shown blocks 3 and 5
                expected_screens = []
                for position, block_id in enumerate(order):
                    block_number = position + 1
                    if block_number in S.BREAK_BEFORE_BLOCKS:
                        expected_screens.append((t('inst_break'), 't'))
                    if S.BLOCK_PHASES[block_id] == 'phase_1':
                        text = t('inst_phase1')
                    else:
                        text = t('inst_phase2')
                    forced_note = t('inst_forced_note') if S.FIRST_CHOICE_MODE == 'forced' else ''
                    expected_screens.append((text.format(block_num=block_number, total_blocks=len(order),
                                                         forced_note=forced_note), 'space'))
                self.assertEqual(log['screens'], expected_screens)

                # summary.json lists the blocks in presentation order with their position
                with open(Path(tmp) / 'sub-cb' / 'summary.json', encoding='utf-8') as f:
                    by_block = json.load(f)['by_block']
                self.assertEqual(list(by_block), [f'block_{b}' for b in order])
                self.assertEqual([by_block[f'block_{b}']['presentation_pos'] for b in order],
                                 [str(p) for p in range(len(order))])

    def test_session_metadata_records_group_and_order(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(writers, 'DATA_DIR', Path(tmp)):
            path = writers.save_session_metadata('cb', 'S', (100, 100), 4, False, 'm', 60,
                                                 counterbalance_group='B', block_order=list(block_order('B')))
            with open(path, encoding='utf-8') as f:
                record = json.load(f)
        self.assertEqual((record['counterbalance_group'], record['block_order']), ('B', [1, 0, 5, 4, 3, 2]))


class TestSessionCloses(unittest.TestCase):
    def test_esc_during_blocks_still_closes_neon_and_labjack(self):
        """Esc anywhere in a block → core.quit() → SystemExit; main()'s finally must still run."""
        neon = mock.Mock(event_log=[])
        ctx = SimpleNamespace(subject_id='002', session_id='S', win=mock.Mock(size=(100, 100)), handle='LJ',
                              neon_client=neon, neon_recording_id=None, counterbalance_group='B')
        factory = mock.Mock()
        factory.get_slot_info.return_value = {'slot_coords': {}, 'animal_size_px': 100}
        with mock.patch.object(main_mod, 'start_session', return_value=ctx), \
             mock.patch.object(main_mod, 'init_marker'), \
             mock.patch.object(main_mod, 'VisualObjectFactory', return_value=factory), \
             mock.patch.object(main_mod, 'save_session_metadata') as save_meta, \
             mock.patch.object(main_mod, 'on_task_start'), \
             mock.patch.object(main_mod, 'run_blocks', side_effect=SystemExit(0)), \
             mock.patch.object(main_mod, 'save_neon_event_log') as save_log, \
             mock.patch.object(main_mod, 'close_labjack') as close_lj:
            with self.assertRaises(SystemExit):
                main_mod.main()
        neon.close.assert_called_once()
        save_log.assert_called_once()
        close_lj.assert_called_once_with('LJ')
        self.assertEqual(save_meta.call_args.kwargs['block_order'], [1, 0, 5, 4, 3, 2])
        self.assertEqual(save_meta.call_args.kwargs['counterbalance_group'], 'B')


if __name__ == '__main__':
    unittest.main()
