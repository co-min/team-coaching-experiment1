"""
Attribute appraisal tests (task/appraisal).

    python -m unittest tests.test_appraisal -v

The first classes need no window: checkpoints, appraisal type, questions,
ground truth, order, and the position of the appraisals in the block loop.
The Screen classes open a small PsychoPy window and answer with scripted keys.
"""

import csv
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from psychopy import core, visual

import recording.writers as writers
import task.block as block_mod
from config import appraisal as A
from config import settings as S
from config.paths import COMPETENCE_CSV, SYNERGY_CSV
from recording.appraisal_writers import APPRAISAL_FIELDS
from recording.stimuli_loader import load_stimuli
from task.appraisal.items import (
    appraisal_type_for_phase, build_appraisal_items, checkpoint_after_trial, competence_items, is_correct,
    item_counter, ordered_items, synergy_items,
)
from task.appraisal.run import AppraisalEnv, run_appraisal
from task.block import BlockEnv, run_block_trials
from task.forced_first import attach_forced_first
from task.ranking.inputs import ScriptedSource
from task.ranking.items import load_attributes
from task.schedule import generate_block_schedules

STIM = load_stimuli()
ATTRS = load_attributes(STIM.synergy)
SYNERGY_BLOCK = S.BLOCK_PHASES.index('phase_1')       # competence visible → synergy appraisal
COMPETENCE_BLOCK = S.BLOCK_PHASES.index('phase_2')    # synergy visible → competence appraisal


def _read_csv(path):
    with open(path, newline='', encoding='utf-8') as f:
        return list(csv.DictReader(f, skipinitialspace=True))


def _table_synergy():
    """{'A+B': 1.0, ...} read straight from synergy.csv (independent of the code under test)."""
    values = {}
    for row in _read_csv(SYNERGY_CSV):
        row = {key.strip(): cell.strip() for key, cell in row.items()}
        values['+'.join(sorted([row['char1'], row['char2']]))] = float(row['synergy_score'])
    return values


def _table_competence():
    """{('A', 'cooking'): 8.5, ...} read straight from competence_d3.csv."""
    values = {}
    for row in _read_csv(COMPETENCE_CSV):
        for domain in S.DOMAINS:
            values[(row['char_ani'].strip(), domain)] = float(row[domain])
    return values


def _script(*keys, t0=0.1, dt=0.05):
    """[(rt, key), ...] at t0, t0+dt, ..."""
    return [(round(t0 + i * dt, 3), key) for i, key in enumerate(keys)]


# ── no window ─────────────────────────────────────────────────────────────────

class TestCheckpoints(unittest.TestCase):
    def test_middle_after_trial_7_and_end_after_trial_15(self):
        found = {}
        for trial_number in range(1, S.N_TRIALS_PER_BLOCK + 1):
            checkpoint = checkpoint_after_trial(trial_number)
            if checkpoint is not None:
                found[trial_number] = checkpoint
        self.assertEqual(found, {7: 'middle', 15: 'end'})
        self.assertEqual(S.N_TRIALS_PER_BLOCK, 15)       # end = the last learning trial

    def test_type_follows_the_hidden_attribute_of_each_block(self):
        self.assertEqual(appraisal_type_for_phase('phase_1'), 'synergy')
        self.assertEqual(appraisal_type_for_phase('phase_2'), 'competence')
        for phase in S.BLOCK_PHASES:
            appraisal_type_for_phase(phase)                # every configured block has a type
        with self.assertRaises(ValueError):
            appraisal_type_for_phase('phase_3')


class TestSynergyItems(unittest.TestCase):
    def test_six_pairs_with_true_synergy(self):
        truth = _table_synergy()
        for group in STIM.animal_groups:
            items = synergy_items(group, STIM, ATTRS)
            self.assertEqual(sorted(item.pair_id for item in items), ['A+B', 'A+C', 'A+D', 'B+C', 'B+D', 'C+D'])
            for item in items:
                self.assertEqual(len(item.animals), 2)
                self.assertTrue(set(item.animals) <= set(group))
                self.assertIsNone(item.domain)             # synergy is domain-independent
                self.assertIsNone(item.animal_id)
                self.assertEqual(item.true_value, truth[item.pair_id])

    def test_levels_follow_the_synergy_colour_order(self):
        levels = {item.true_value: item.true_level for item in synergy_items(STIM.animal_groups[0], STIM, ATTRS)}
        self.assertEqual(levels, {0.8: 'low', 1.0: 'mid', 1.4: 'high'})


class TestCompetenceItems(unittest.TestCase):
    def test_one_animal_per_question_in_every_domain(self):
        truth = _table_competence()
        group = STIM.animal_groups[COMPETENCE_BLOCK]
        items = competence_items(group, STIM, ATTRS)
        self.assertEqual(len(items), 12)                   # 4 animals × 3 domains
        self.assertEqual({(item.animal_id, item.domain) for item in items},
                         {(role, d) for role in 'ABCD' for d in S.DOMAINS})
        for item in items:
            self.assertEqual(len(item.animals), 1)        # never a pair
            self.assertIsNone(item.pair_id)
            self.assertIn(item.animals[0], group)
            self.assertEqual(item.true_value, truth[(item.animal_id, item.domain)])   # decimals kept
        a_cooking = [item for item in items if item.animal_id == 'A' and item.domain == 'cooking'][0]
        self.assertEqual(a_cooking.true_value, 8.5)        # not the integer 8 of StimulusSet.competence

    def test_competence_is_domain_specific(self):
        items = competence_items(STIM.animal_groups[1], STIM, ATTRS)
        a_values = {item.domain: (item.true_value, item.true_level) for item in items if item.animal_id == 'A'}
        self.assertEqual(a_values, {'cooking': (8.5, 'high'), 'repairing': (4.6, 'mid'), 'tennis': (1.9, 'low')})

    def test_domains_are_configurable(self):
        items = competence_items(STIM.animal_groups[1], STIM, ATTRS, domains=('tennis',))
        self.assertEqual(len(items), 4)
        self.assertEqual({item.domain for item in items}, {'tennis'})
        with self.assertRaises(ValueError):
            competence_items(STIM.animal_groups[1], STIM, ATTRS, domains=('swimming',))

    def test_level_cut_offs_match_the_border_colours(self):
        # Design table: Low 1.0–3.0, Middle 3.5–6.0, High 6.5–9.0
        self.assertEqual([STIM.competence_level(v) for v in (1.0, 3.0, 3.5, 6.0, 6.5, 9.0)],
                         ['low', 'low', 'mid', 'mid', 'high', 'high'])
        # values between the ranges never raise; they go to the level above
        self.assertEqual([STIM.competence_level(v) for v in (3.2, 6.3)], ['mid', 'high'])
        # border colours for the integer levels the trials use
        expected = {1: '#F44336', 3: '#F44336', 4: '#FFEB3B', 6: '#FFEB3B', 7: '#4CAF50', 9: '#4CAF50'}
        for score, colour in expected.items():
            self.assertEqual(STIM.comp_color(score), colour)


class TestOrder(unittest.TestCase):
    def test_reproducible_and_complete(self):
        group = STIM.animal_groups[0]
        first = build_appraisal_items('synergy', group, STIM, ATTRS, seed='T01|b0_middle')
        again = build_appraisal_items('synergy', group, STIM, ATTRS, seed='T01|b0_middle')
        self.assertEqual(first, again)
        self.assertEqual(len({item.pair_id for item in first}), 6)        # each pair exactly once
        for item in first:
            self.assertEqual(sorted(item.display_animals), sorted(item.animals))

    def test_middle_and_end_ask_the_same_questions(self):
        group = STIM.animal_groups[1]
        middle = build_appraisal_items('competence', group, STIM, ATTRS, seed='T01|b1_middle')
        end = build_appraisal_items('competence', group, STIM, ATTRS, seed='T01|b1_end')
        self.assertEqual(sorted((i.animal_id, i.domain) for i in middle), sorted((i.animal_id, i.domain) for i in end))

    def test_competence_stays_grouped_by_domain(self):
        for seed in ('a', 'b', 'c', 'd'):
            items = build_appraisal_items('competence', STIM.animal_groups[1], STIM, ATTRS, seed=seed)
            domain_runs = [items[0].domain]
            for item in items[1:]:
                if item.domain != domain_runs[-1]:
                    domain_runs.append(item.domain)
            self.assertEqual(sorted(domain_runs), sorted(S.DOMAINS))      # each domain is one run of 4
            self.assertEqual([item_counter(items, p)['n'] for p in range(12)], [1, 2, 3, 4] * 3)

    def test_mixed_types_rejected(self):
        mixed = synergy_items(STIM.animal_groups[0], STIM, ATTRS)[:1] + \
                competence_items(STIM.animal_groups[0], STIM, ATTRS)[:1]
        with self.assertRaises(ValueError):
            ordered_items(mixed, seed='x')

    def test_is_correct(self):
        self.assertTrue(is_correct('mid', 'mid'))
        self.assertFalse(is_correct('low', 'high'))
        self.assertIsNone(is_correct(None, 'high'))


class TestBlockFlowOrder(unittest.TestCase):
    """run_block_trials with fake trials: where do the appraisals run?"""

    def _run_block(self, tmp, block_index):
        log = []
        schedules = generate_block_schedules(STIM.animal_groups)
        attach_forced_first(schedules, STIM.animal_groups, STIM.char_code)
        schedule = schedules[block_index]

        def fake_trial(win, clock, frame_log, factory, stim, domain, char_order, handle,
                       neon_client=None, forced_first=None):
            log.append(('trial', frame_log['trial_id'] + 1, forced_first))
            return None                                      # no response → no feedback screen

        def fake_appraisal(env, block_i, phase, checkpoint, trial_after):
            saved = _read_csv(Path(tmp) / 'sub-flow' / 'trials.csv')
            log.append(('appraisal', checkpoint, trial_after, len(saved)))

        env = BlockEnv(win=SimpleNamespace(size=(1000, 700)), global_clock=core.Clock(),
                       factory=SimpleNamespace(get_slot_info=lambda: {'slot_coords': {}, 'animal_size_px': 100}),
                       stim=STIM, subject_id='flow', handle=None, neon_client=SimpleNamespace())
        cumulative = {'total': 0, 'phase': 0, **{d: 0 for d in S.DOMAINS}}
        phase = S.BLOCK_PHASES[block_index]
        with mock.patch.object(writers, 'DATA_DIR', Path(tmp)), \
             mock.patch.dict(block_mod.TRIAL_RUNNERS, {phase: fake_trial}), \
             mock.patch.object(block_mod, 'run_block_appraisal', fake_appraisal), \
             mock.patch.object(block_mod, 'run_gaussian_iti', lambda *a, **k: None), \
             mock.patch.object(block_mod, 'on_block_start', lambda *a, **k: None), \
             mock.patch.object(block_mod, 'save_experiment_summary', lambda *a: log.append(('block_end',))):
            run_block_trials(env, block_index, phase, schedule, cumulative)
        return log, schedule

    def test_middle_after_7_end_after_15_then_block_ends(self):
        with tempfile.TemporaryDirectory() as tmp:
            log, schedule = self._run_block(tmp, 0)

        expected = []
        for n in range(1, 8):
            expected.append(('trial', n, schedule[n - 1]['forced_first']))
        expected.append(('appraisal', 'middle', 7, 7))           # trial 7 already saved
        for n in range(8, 16):
            expected.append(('trial', n, schedule[n - 1]['forced_first']))
        expected.append(('appraisal', 'end', 15, 15))
        expected.append(('block_end',))                           # nothing else runs before main() continues
        self.assertEqual(log, expected)

    def test_esc_in_the_appraisal_ends_the_session(self):
        env = SimpleNamespace(win=mock.Mock(), global_clock=None, stim=STIM, subject_id='x', session_id=None)
        with mock.patch.object(block_mod, 'make_appraisal_env', lambda *a: None), \
             mock.patch.object(block_mod, 'run_appraisal', lambda *a: SimpleNamespace(aborted=True)), \
             mock.patch.object(block_mod.core, 'quit') as quit_mock:
            block_mod.run_block_appraisal(env, 0, 'phase_1', 'middle', 7)
        env.win.close.assert_called_once()
        quit_mock.assert_called_once()


# ── with a window ─────────────────────────────────────────────────────────────

class ScreenBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.win = visual.Window(size=(1000, 700), fullscr=False, units='pix', color=S.BACKGROUND_COLOR,
                                colorSpace='hex', screen=0, winType='pyglet', allowGUI=True)

    @classmethod
    def tearDownClass(cls):
        cls.win.close()

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        patcher = mock.patch.object(A, 'CONFIRM_FEEDBACK_S', 0.0)
        patcher.start()
        self.addCleanup(patcher.stop)

    def run_appraisal(self, block_index, scripts, checkpoint='middle', trial_after=7, subject_id='T01'):
        env = AppraisalEnv(win=self.win, global_clock=core.Clock(),
                           source=ScriptedSource(scripts, key_map=A.APPRAISAL_KEYS), stim=STIM, attrs=ATTRS,
                           subject_id=subject_id, subject_dir=self.tmp, session_id='S')
        result = run_appraisal(env, block_index, S.BLOCK_PHASES[block_index], checkpoint, trial_after,
                               show_intro=False)
        return result, self.rows()

    def rows(self):
        path = self.tmp / 'appraisals.csv'
        if not path.exists():
            return []
        return _read_csv(path)


class TestSynergyScreen(ScreenBase):
    def test_six_pairs_saved_with_responses_and_rts(self):
        scripts = [
            _script('right', 'left', 'space'),          # changes its mind: high → low
            _script('space', 'down', 'space'),          # confirm before choosing is ignored
            _script('right', 'space'),
            _script('right', 'space'),
            _script('left', 'x', 'space'),              # unmapped key ignored
            _script('down', 'space', t0=0.3),
        ]
        result, rows = self.run_appraisal(SYNERGY_BLOCK, scripts)
        self.assertFalse(result.aborted)
        self.assertEqual(len(rows), 6)
        self.assertEqual(list(rows[0]), APPRAISAL_FIELDS)
        self.assertEqual(sorted(row['pair_id'] for row in rows), ['A+B', 'A+C', 'A+D', 'B+C', 'B+D', 'C+D'])

        truth = _table_synergy()
        expected_responses = ['low', 'mid', 'high', 'high', 'low', 'mid']
        for position, (row, script) in enumerate(zip(rows, scripts)):
            self.assertEqual(row['appraisal_type'], 'synergy')
            self.assertEqual((row['checkpoint'], row['trial_after'], row['block_idx']), ('middle', '7', str(SYNERGY_BLOCK)))
            self.assertEqual(row['presentation_order'], str(position + 1))
            self.assertEqual((row['domain'], row['animal_id'], row['animal_name']), ('', '', ''))
            self.assertEqual(len(row['display_animals'].split('|')), 2)
            self.assertEqual(row['status'], 'complete')
            self.assertEqual(row['response'], expected_responses[position])
            self.assertAlmostEqual(float(row['response_rt']), script[-1][0], places=4)
            self.assertAlmostEqual(float(row['confirm_global']),
                                   float(row['onset_global']) + float(row['response_rt']), places=4)
            self.assertEqual(float(row['true_attribute_value']), truth[row['pair_id']])
            self.assertEqual(row['correct'], str(row['response'] == row['true_attribute_level']))
        self.assertEqual((rows[0]['n_presses'], rows[0]['first_press_rt']), ('2', '0.1'))
        self.assertEqual(rows[0]['selection_history'], 'high@0.1000;low@0.1500')

    def test_abort_keeps_earlier_answers(self):
        scripts = [_script('left', 'space'), _script('down', 'space'), _script('right', 'escape')]
        result, rows = self.run_appraisal(SYNERGY_BLOCK, scripts)
        self.assertTrue(result.aborted)
        self.assertEqual([row['status'] for row in rows], ['complete', 'complete', 'aborted'])
        self.assertEqual((rows[2]['response'], rows[2]['response_rt'], rows[2]['correct']), ('', '', ''))
        self.assertEqual(rows[2]['selection_history'], 'high@0.1000')    # highlighted, never confirmed

    def test_timeout_is_saved_and_skipped(self):
        scripts = [[]] + [_script('down', 'space')] * 5
        with mock.patch.object(A, 'APPRAISAL_MAX_TIME', 0.2):
            result, rows = self.run_appraisal(SYNERGY_BLOCK, scripts)
        self.assertEqual([row['status'] for row in rows], ['timeout'] + ['complete'] * 5)
        self.assertEqual(rows[0]['response'], '')


class TestCompetenceScreen(ScreenBase):
    def test_twelve_single_animal_questions_grouped_by_domain(self):
        result, rows = self.run_appraisal(COMPETENCE_BLOCK, [_script('left', 'space')] * 12,
                                          checkpoint='end', trial_after=15)
        truth = _table_competence()
        self.assertEqual(len(rows), 12)
        domains_in_order = [row['domain'] for row in rows]
        for start in (0, 4, 8):
            self.assertEqual(len(set(domains_in_order[start:start + 4])), 1)
        self.assertEqual(sorted(set(domains_in_order)), sorted(S.DOMAINS))
        for row in rows:
            self.assertEqual(row['appraisal_type'], 'competence')
            self.assertEqual((row['checkpoint'], row['trial_after']), ('end', '15'))
            self.assertEqual((row['pair_id'], row['pair_animals']), ('', ''))
            self.assertEqual(row['display_animals'], row['animal_name'])     # exactly one animal on screen
            self.assertEqual(float(row['true_attribute_value']), truth[(row['animal_id'], row['domain'])])
            self.assertEqual(row['response'], 'low')
            self.assertEqual(row['correct'], str(row['true_attribute_level'] == 'low'))

    def test_screen_is_the_same_for_right_and_wrong_answers(self):
        """No feedback: what is drawn never depends on the true answer."""
        drawn = {}
        real_draw = visual.TextStim.draw
        for answer in ('low', 'high'):
            texts = set()

            def recording_draw(stim, *args, **kwargs):
                texts.add(stim.text)
                return real_draw(stim, *args, **kwargs)

            key = A.APPRAISAL_KEYS[answer][0]
            with mock.patch.object(A, 'COMPETENCE_APPRAISAL_DOMAINS', ('cooking',)), \
                 mock.patch.object(visual.TextStim, 'draw', recording_draw):
                self.run_appraisal(COMPETENCE_BLOCK, [_script(key, 'space')] * 4, subject_id=f'same_{answer}')
            drawn[answer] = texts

        rows = self.rows()
        self.assertEqual(len(rows), 8)
        # Each run has right and wrong answers (cooking levels are high, mid, low, high) ...
        self.assertEqual({row['correct'] for row in rows}, {'True', 'False'})
        # ... yet both runs draw exactly the same text, and no true value appears anywhere.
        self.assertEqual(drawn['low'], drawn['high'])
        all_text = ' '.join(drawn['low'])
        for row in rows:
            self.assertNotIn(row['true_attribute_value'], all_text)


if __name__ == '__main__':
    unittest.main()
