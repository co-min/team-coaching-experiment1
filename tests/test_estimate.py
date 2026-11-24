"""
Attribute estimate tests (task/estimate).

    python -m unittest tests.test_estimate -v

The first classes need no window: checkpoints, estimate type, questions,
ground truth, order, the position of the estimates in the block loop, and the
LabJack codes / Neon labels.
The Screen classes open a small PsychoPy window and answer with scripted keys;
TestEstimateEvents also checks which events go out on which screen flip.
"""

import csv
import tempfile
from collections import Counter
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from psychopy import core, visual

import recording.writers as writers
import hardware.events as hw_events
import hardware.labjack as labjack
import task.estimate.run as run_mod
import task.block as block_mod
from config import estimate as E
from config import settings as S
from config.paths import COMPETENCE_CSV, SYNERGY_CSV
from recording.estimate_writers import ESTIMATE_FIELDS
from recording.stimuli_loader import load_stimuli
from task.estimate.items import (
    estimate_type_for_phase, build_estimate_items, checkpoint_after_trial, competence_domains, competence_items,
    is_correct, item_counter, ordered_items, synergy_items,
)
from task.estimate.run import EstimateEnv, run_estimate
from task.block import BlockEnv, run_block_trials
from task.forced_first import attach_forced_first
from task.ranking.inputs import ScriptedSource
from task.ranking.items import load_attributes
from task.schedule import generate_block_schedules

STIM = load_stimuli()
ATTRS = load_attributes(STIM.synergy)
SYNERGY_BLOCK = S.BLOCK_PHASES.index('phase_1')       # competence visible → synergy estimate
COMPETENCE_BLOCK = S.BLOCK_PHASES.index('phase_2')    # synergy visible → competence estimate
COMPETENCE_BLOCKS = [b for b, phase in enumerate(S.BLOCK_PHASES) if phase == 'phase_2']


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
        self.assertEqual(estimate_type_for_phase('phase_1'), 'synergy')
        self.assertEqual(estimate_type_for_phase('phase_2'), 'competence')
        for phase in S.BLOCK_PHASES:
            estimate_type_for_phase(phase)                 # every configured block has a type
        with self.assertRaises(ValueError):
            estimate_type_for_phase('phase_3')


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
    def test_one_animal_in_one_domain_per_question(self):
        truth = _table_competence()
        for block in COMPETENCE_BLOCKS:
            group = STIM.animal_groups[block]
            items = competence_items(group, STIM, ATTRS, competence_domains(block))
            self.assertEqual(len(items), 4)                    # 4 animals × 1 domain
            self.assertEqual({item.animal_id: item.domain for item in items}, E.COMPETENCE_ESTIMATE_MAP[block])
            for item in items:
                self.assertEqual(len(item.animals), 1)        # never a pair
                self.assertIsNone(item.pair_id)
                self.assertIn(item.animals[0], group)
                self.assertEqual(item.true_value, truth[(item.animal_id, item.domain)])   # decimals kept
        a_cooking = competence_items(STIM.animal_groups[1], STIM, ATTRS, competence_domains(1))[0]
        self.assertEqual((a_cooking.animal_id, a_cooking.domain, a_cooking.true_value), ('A', 'cooking', 8.5))

    def test_competence_is_domain_specific(self):
        a_values = {}
        for block in COMPETENCE_BLOCKS:
            items = build_estimate_items('competence', block, STIM, ATTRS, seed='x')
            a_item = [item for item in items if item.animal_id == 'A'][0]
            a_values[a_item.domain] = (a_item.true_value, a_item.true_level)
        self.assertEqual(a_values, {'cooking': (8.5, 'high'), 'repairing': (4.6, 'mid'), 'tennis': (1.9, 'low')})

    def test_bad_domains_rejected(self):
        group = STIM.animal_groups[1]
        with self.assertRaises(ValueError):
            competence_items(group, STIM, ATTRS, {'A': 'swimming', 'B': 'tennis', 'C': 'tennis', 'D': 'tennis'})
        with self.assertRaises(ValueError):
            competence_items(group, STIM, ATTRS, {'A': 'tennis', 'B': 'tennis', 'C': 'tennis'})   # D missing
        with self.assertRaises(ValueError):
            competence_domains(SYNERGY_BLOCK)                 # no competence estimate there

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


class TestCompetenceCounterbalance(unittest.TestCase):
    """config.estimate.COMPETENCE_ESTIMATE_MAP: which domain each animal is asked about."""

    MAP = E.COMPETENCE_ESTIMATE_MAP

    def test_matches_the_design_table(self):
        self.assertEqual(self.MAP, {
            1: {'A': 'cooking',   'B': 'tennis',    'C': 'repairing', 'D': 'cooking'},
            3: {'A': 'repairing', 'B': 'cooking',   'C': 'tennis',    'D': 'repairing'},
            5: {'A': 'tennis',    'B': 'repairing', 'C': 'cooking',   'D': 'tennis'},
        })

    def test_keyed_by_the_competence_hidden_blocks(self):
        self.assertEqual(sorted(self.MAP), COMPETENCE_BLOCKS)
        for block in self.MAP:
            self.assertEqual(estimate_type_for_phase(S.BLOCK_PHASES[block]), 'competence')

    def test_one_domain_per_animal_and_all_domains_in_every_block(self):
        for block, domain_by_role in self.MAP.items():
            self.assertEqual(sorted(domain_by_role), ['A', 'B', 'C', 'D'])        # each animal exactly once
            self.assertEqual(sorted(set(domain_by_role.values())), sorted(S.DOMAINS))

    def test_each_animal_gets_each_domain_once_across_blocks(self):
        for role in 'ABCD':
            self.assertEqual(sorted(self.MAP[block][role] for block in self.MAP), sorted(S.DOMAINS))

    def test_each_domain_four_times_in_total(self):
        counts = Counter(domain for domain_by_role in self.MAP.values() for domain in domain_by_role.values())
        self.assertEqual(counts, {domain: 4 for domain in S.DOMAINS})

    def _true_levels(self, block):
        """{role: 'low' / 'mid' / 'high'} of the asked domain, read straight from competence_d3.csv."""
        table = _table_competence()
        return {role: STIM.competence_level(table[(role, domain)]) for role, domain in self.MAP[block].items()}

    def test_true_level_distribution_per_block(self):
        self.assertEqual({block: Counter(self._true_levels(block).values()) for block in self.MAP}, {
            1: {'high': 2, 'mid': 1, 'low': 1},
            3: {'high': 1, 'mid': 2, 'low': 1},
            5: {'high': 1, 'mid': 1, 'low': 2},
        })

    def test_all_three_levels_in_every_block(self):
        for block in self.MAP:
            self.assertEqual(set(self._true_levels(block).values()), {'low', 'mid', 'high'}, block)

    def test_each_level_four_times_in_total(self):
        counts = Counter(level for block in self.MAP for level in self._true_levels(block).values())
        self.assertEqual(counts, {'low': 4, 'mid': 4, 'high': 4})

    def test_items_carry_the_table_levels(self):
        """The levels the estimate scores against are the ones the design counts on, at both checkpoints."""
        for block in self.MAP:
            for checkpoint in ('middle', 'end'):
                items = build_estimate_items('competence', block, STIM, ATTRS, seed=f'T01|b{block}_{checkpoint}')
                self.assertEqual({item.animal_id: item.true_level for item in items}, self._true_levels(block))

    def test_same_animal_domain_pairs_under_both_block_orders(self):
        """The mapping follows the original block ID, whatever position the block is shown at."""
        for group, order in S.BLOCK_ORDERS.items():
            shown = []
            for position, block in enumerate(order):
                if S.BLOCK_PHASES[block] != 'phase_2':
                    continue
                shown.append(block)
                for checkpoint in ('middle', 'end'):
                    items = build_estimate_items('competence', block, STIM, ATTRS,
                                                 seed=f"T0{position}|b{block}_{checkpoint}")
                    self.assertEqual({item.animal_id: item.domain for item in items}, self.MAP[block], (group, block))
                    self.assertEqual({item.animals[0] for item in items}, set(STIM.animal_groups[block]))
            self.assertEqual(sorted(shown), COMPETENCE_BLOCKS, group)


class TestOrder(unittest.TestCase):
    def test_reproducible_and_complete(self):
        first = build_estimate_items('synergy', 0, STIM, ATTRS, seed='T01|b0_middle')
        again = build_estimate_items('synergy', 0, STIM, ATTRS, seed='T01|b0_middle')
        self.assertEqual(first, again)
        self.assertEqual(len({item.pair_id for item in first}), 6)        # each pair exactly once
        for item in first:
            self.assertEqual(sorted(item.display_animals), sorted(item.animals))

    def test_middle_and_end_ask_the_same_questions(self):
        for block in COMPETENCE_BLOCKS:
            middle = build_estimate_items('competence', block, STIM, ATTRS, seed=f'T01|b{block}_middle')
            end = build_estimate_items('competence', block, STIM, ATTRS, seed=f'T01|b{block}_end')
            self.assertEqual(len(middle), 4)
            self.assertEqual(len(end), 4)
            self.assertEqual(sorted((i.animal_id, i.domain, i.true_value) for i in middle),
                             sorted((i.animal_id, i.domain, i.true_value) for i in end))

    def test_competence_order_shuffled_and_reproducible(self):
        orders = set()
        for seed in ('a', 'b', 'c', 'd', 'e', 'f'):
            items = build_estimate_items('competence', COMPETENCE_BLOCK, STIM, ATTRS, seed=seed)
            self.assertEqual(items, build_estimate_items('competence', COMPETENCE_BLOCK, STIM, ATTRS, seed=seed))
            self.assertEqual(sorted(item.animal_id for item in items), ['A', 'B', 'C', 'D'])
            self.assertEqual([item_counter(items, p) for p in range(4)],
                             [{'n': n, 'total': 4} for n in (1, 2, 3, 4)])
            orders.add(tuple(item.animal_id for item in items))
        self.assertGreater(len(orders), 1)

    def test_mixed_types_rejected(self):
        mixed = synergy_items(STIM.animal_groups[0], STIM, ATTRS)[:1] + \
                competence_items(STIM.animal_groups[1], STIM, ATTRS, competence_domains(1))[:1]
        with self.assertRaises(ValueError):
            ordered_items(mixed, seed='x')

    def test_is_correct(self):
        self.assertTrue(is_correct('mid', 'mid'))
        self.assertFalse(is_correct('low', 'high'))
        self.assertIsNone(is_correct(None, 'high'))


class TestBlockFlowOrder(unittest.TestCase):
    """run_block_trials with fake trials: where do the estimates run?"""

    def _run_block(self, tmp, block_index):
        log = []
        schedules = generate_block_schedules(STIM.animal_groups)
        attach_forced_first(schedules, STIM.animal_groups, STIM.char_code)
        schedule = schedules[block_index]

        def fake_trial(win, clock, frame_log, factory, stim, domain, char_order, handle,
                       neon_client=None, forced_first=None):
            log.append(('trial', frame_log['trial_id'] + 1, forced_first))
            return None                                      # no response → no feedback screen

        def fake_estimate(env, block_i, phase, checkpoint, trial_after, presentation_pos=None):
            saved = _read_csv(Path(tmp) / 'sub-flow' / 'trials.csv')
            log.append(('estimate', checkpoint, trial_after, len(saved)))

        env = BlockEnv(win=SimpleNamespace(size=(1000, 700)), global_clock=core.Clock(),
                       factory=SimpleNamespace(get_slot_info=lambda: {'slot_coords': {}, 'animal_size_px': 100}),
                       stim=STIM, subject_id='flow', handle=None, neon_client=SimpleNamespace())
        cumulative = {'total': 0, 'phase': 0, **{d: 0 for d in S.DOMAINS}}
        phase = S.BLOCK_PHASES[block_index]
        with mock.patch.object(writers, 'DATA_DIR', Path(tmp)), \
             mock.patch.dict(block_mod.TRIAL_RUNNERS, {phase: fake_trial}), \
             mock.patch.object(block_mod, 'run_block_estimate', fake_estimate), \
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
        expected.append(('estimate', 'middle', 7, 7))            # trial 7 already saved
        for n in range(8, 16):
            expected.append(('trial', n, schedule[n - 1]['forced_first']))
        expected.append(('estimate', 'end', 15, 15))
        expected.append(('block_end',))                           # nothing else runs before main() continues
        self.assertEqual(log, expected)

    def test_esc_in_the_estimate_ends_the_session(self):
        env = SimpleNamespace(win=mock.Mock(), global_clock=None, stim=STIM, subject_id='x', session_id=None,
                              handle=None, neon_client=None, counterbalance_group=None)
        with mock.patch.object(block_mod, 'make_estimate_env', lambda *a, **k: None), \
             mock.patch.object(block_mod, 'run_estimate', lambda *a, **k: SimpleNamespace(aborted=True)), \
             mock.patch.object(block_mod.core, 'quit') as quit_mock:
            block_mod.run_block_estimate(env, 0, 'phase_1', 'middle', 7)
        env.win.close.assert_called_once()
        quit_mock.assert_called_once()


class TestEstimateEventCodes(unittest.TestCase):
    """TTL codes and Neon labels, without a window (fake win runs callOnFlip callbacks on flip())."""

    def test_codes_follow_the_phase(self):
        self.assertEqual(hw_events._ESTIMATE_START_TRIG,    {1: 151, 2: 152})
        self.assertEqual(hw_events._ESTIMATE_QUESTION_TRIG, {1: 161, 2: 162})
        self.assertEqual(hw_events._ESTIMATE_RESPONSE_TRIG, {1: 171, 2: 172})
        self.assertEqual(hw_events._ESTIMATE_END_TRIG,      {1: 181, 2: 182})

    def test_no_collision_with_existing_codes(self):
        estimate_codes = set()
        other_codes = set()
        for name in dir(labjack):
            if not name.startswith('TRIG_') or name == 'TRIG_RESET':
                continue
            if 'ESTIMATE' in name:
                estimate_codes.add(getattr(labjack, name))
            else:
                other_codes.add(getattr(labjack, name))
        # animal-encoded choice codes are base + 0..23
        for base in (labjack.TRIG_P1_CHOICE1, labjack.TRIG_P1_CHOICE2, labjack.TRIG_P2_CHOICE1, labjack.TRIG_P2_CHOICE2):
            for animal_index in labjack.ANIMAL_IDX.values():
                other_codes.add(base + animal_index)

        self.assertEqual(estimate_codes, {151, 152, 161, 162, 171, 172, 181, 182})
        self.assertEqual(estimate_codes & other_codes, set())
        for code in estimate_codes | other_codes:
            self.assertTrue(1 <= code <= 255, code)          # 8 EIO data lines

    def test_labels_name_block_checkpoint_question_and_response(self):
        ttl, neon = [], FakeNeon(lambda: (0, False))
        win = FakeWin()
        with mock.patch.object(hw_events, 'send_trigger', lambda handle, code, *a, **k: ttl.append(code)):
            hw_events.callonflip_estimate_start(win, neon, None, 2, 3, 'end')
            hw_events.callonflip_estimate_question(win, neon, None, 2, 3, 'end', 4)
            self.assertEqual((ttl, neon.names()), ([], []))  # nothing before the flip
            win.flip()
            hw_events.on_estimate_confirm(neon, None, 2, 3, 'end', 4, 'mid')
            hw_events.on_estimate_no_response(neon, 2, 3, 'end', 5, 'timeout')
            hw_events.on_estimate_no_response(neon, 2, 3, 'end', 6, 'aborted')
            hw_events.on_estimate_end(neon, None, 2, 3, 'end', 'aborted')
        self.assertEqual(ttl, [152, 162, 172, 182])
        self.assertEqual(neon.names(), [
            'P2_BLOCK_03_ESTIMATE_END_START',
            'P2_BLOCK_03_ESTIMATE_END_Q04_ONSET',
            'P2_BLOCK_03_ESTIMATE_END_Q04_MID_CONFIRM',
            'P2_BLOCK_03_ESTIMATE_END_Q05_TIMEOUT',
            'P2_BLOCK_03_ESTIMATE_END_Q06_ABORTED',
            'P2_BLOCK_03_ESTIMATE_END_END_ABORTED',
        ])
        self.assertEqual([e['meta'].get('task_type') for e in neon.events], ['estimate'] * 6)
        self.assertEqual([e['meta'].get('trial_index') for e in neon.events], [None, 4, 4, 5, 6, None])

    def test_block_estimate_passes_hardware_group_and_position(self):
        seen = {}

        def fake_make_env(*args, **kwargs):
            seen['env_kwargs'] = kwargs
            return 'estimate_env'

        def fake_run(estimate_env, block_index, phase, checkpoint, trial_after, presentation_pos=None):
            seen['run'] = (estimate_env, block_index, phase, checkpoint, trial_after, presentation_pos)
            return SimpleNamespace(aborted=False)

        env = SimpleNamespace(win=None, global_clock=None, stim=STIM, subject_id='x', session_id='S',
                              handle='LJ', neon_client='NEON', counterbalance_group='B')
        with mock.patch.object(block_mod, 'make_estimate_env', fake_make_env), \
             mock.patch.object(block_mod, 'run_estimate', fake_run):
            block_mod.run_block_estimate(env, 5, 'phase_2', 'end', 15, presentation_pos=2)
        self.assertEqual(seen['env_kwargs'], {'lj_handle': 'LJ', 'neon': 'NEON', 'counterbalance_group': 'B'})
        self.assertEqual(seen['run'], ('estimate_env', 5, 'phase_2', 'end', 15, 2))


class FakeWin:
    """Just enough of a window for callOnFlip: callbacks run (in order) on the next flip()."""

    def __init__(self):
        self._callbacks = []

    def callOnFlip(self, function, *args, **kwargs):
        self._callbacks.append((function, args, kwargs))

    def flip(self):
        callbacks, self._callbacks = self._callbacks, []
        for function, args, kwargs in callbacks:
            function(*args, **kwargs)


class FakeNeon:
    """Records Neon events with where_now() = (flip number, inside a flip?) at the moment they are queued."""

    def __init__(self, where_now):
        self.where_now = where_now
        self.events = []

    def call_on_flip(self, win, names, **meta):
        win.callOnFlip(self.enqueue_events, names, metadata=meta)

    def enqueue_events(self, names, metadata=None):
        if isinstance(names, str):
            names = [names]
        flip_number, in_flip = self.where_now()
        for name in names:
            self.events.append({'name': name, 'flip': flip_number, 'in_flip': in_flip, 'meta': metadata or {}})

    def names(self):
        return [e['name'] for e in self.events]


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
        patcher = mock.patch.object(E, 'CONFIRM_FEEDBACK_S', 0.0)
        patcher.start()
        self.addCleanup(patcher.stop)

    def run_estimate(self, block_index, scripts, checkpoint='middle', trial_after=7, subject_id='T01'):
        env = EstimateEnv(win=self.win, global_clock=core.Clock(),
                           source=ScriptedSource(scripts, key_map=E.ESTIMATE_KEYS), stim=STIM, attrs=ATTRS,
                           subject_id=subject_id, subject_dir=self.tmp, session_id='S')
        result = run_estimate(env, block_index, S.BLOCK_PHASES[block_index], checkpoint, trial_after,
                               show_intro=False)
        return result, self.rows()

    def rows(self):
        path = self.tmp / 'estimates.csv'
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
        result, rows = self.run_estimate(SYNERGY_BLOCK, scripts)
        self.assertFalse(result.aborted)
        self.assertEqual(len(rows), 6)
        self.assertEqual(list(rows[0]), ESTIMATE_FIELDS)
        self.assertEqual(sorted(row['pair_id'] for row in rows), ['A+B', 'A+C', 'A+D', 'B+C', 'B+D', 'C+D'])

        truth = _table_synergy()
        expected_responses = ['low', 'mid', 'high', 'high', 'low', 'mid']
        for position, (row, script) in enumerate(zip(rows, scripts)):
            self.assertEqual(row['estimate_type'], 'synergy')
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
        result, rows = self.run_estimate(SYNERGY_BLOCK, scripts)
        self.assertTrue(result.aborted)
        self.assertEqual([row['status'] for row in rows], ['complete', 'complete', 'aborted'])
        self.assertEqual((rows[2]['response'], rows[2]['response_rt'], rows[2]['correct']), ('', '', ''))
        self.assertEqual(rows[2]['selection_history'], 'high@0.1000')    # highlighted, never confirmed

    def test_timeout_is_saved_and_skipped(self):
        scripts = [[]] + [_script('down', 'space')] * 5
        with mock.patch.object(E, 'ESTIMATE_MAX_TIME', 0.2):
            result, rows = self.run_estimate(SYNERGY_BLOCK, scripts)
        self.assertEqual([row['status'] for row in rows], ['timeout'] + ['complete'] * 5)
        self.assertEqual(rows[0]['response'], '')


class TestCompetenceScreen(ScreenBase):
    def test_four_single_animal_questions_one_domain_each(self):
        truth = _table_competence()
        for block in COMPETENCE_BLOCKS:
            for checkpoint, trial_after in (('middle', 7), ('end', 15)):
                self.run_estimate(block, [_script('left', 'space')] * 4, checkpoint=checkpoint,
                                  trial_after=trial_after)
        rows = self.rows()
        self.assertEqual(len(rows), 4 * 2 * len(COMPETENCE_BLOCKS))
        for row in rows:
            self.assertEqual(row['estimate_type'], 'competence')
            self.assertEqual(row['n_items'], '4')
            self.assertEqual(row['domain'], E.COMPETENCE_ESTIMATE_MAP[int(row['block_idx'])][row['animal_id']])
            self.assertEqual((row['pair_id'], row['pair_animals']), ('', ''))
            self.assertEqual(row['display_animals'], row['animal_name'])     # exactly one animal on screen
            self.assertEqual(float(row['true_attribute_value']), truth[(row['animal_id'], row['domain'])])
            self.assertEqual(row['response'], 'low')
            self.assertEqual(row['correct'], str(row['true_attribute_level'] == 'low'))
        # Middle and end of a block: same animal–domain pairs
        for block in COMPETENCE_BLOCKS:
            pairs = {checkpoint: sorted((row['animal_id'], row['domain']) for row in rows
                                        if row['block_idx'] == str(block) and row['checkpoint'] == checkpoint)
                     for checkpoint in ('middle', 'end')}
            self.assertEqual(len(pairs['middle']), 4)
            self.assertEqual(pairs['middle'], pairs['end'])

    def test_screen_is_the_same_for_right_and_wrong_answers(self):
        """No feedback: what is drawn never depends on the true answer."""
        drawn = {}
        real_draw = visual.TextStim.draw
        for answer in ('low', 'high'):
            texts = set()

            def recording_draw(stim, *args, **kwargs):
                texts.add(stim.text)
                return real_draw(stim, *args, **kwargs)

            key = E.ESTIMATE_KEYS[answer][0]
            with mock.patch.object(visual.TextStim, 'draw', recording_draw):
                self.run_estimate(3, [_script(key, 'space')] * 4, subject_id=f'same_{answer}')
            drawn[answer] = texts

        rows = self.rows()
        self.assertEqual(len(rows), 8)
        # Right and wrong answers (block 3 levels are A mid, B low, C low, D low) ...
        self.assertEqual({row['correct'] for row in rows}, {'True', 'False'})
        # ... yet both runs draw exactly the same text, and no true value appears anywhere.
        self.assertEqual(drawn['low'], drawn['high'])
        all_text = ' '.join(drawn['low'])
        for row in rows:
            self.assertNotIn(row['true_attribute_value'], all_text)


class TestEstimateEvents(ScreenBase):
    """LabJack codes and Neon labels during a real estimate, and which flip each one goes out on."""

    def setUp(self):
        super().setUp()
        # Count flips and remember whether code runs inside one (callOnFlip callbacks do).
        self.n_flips = 0
        self.in_flip = False
        real_flip = self.win.flip

        def counting_flip(*args, **kwargs):
            self.n_flips += 1
            self.in_flip = True
            try:
                return real_flip(*args, **kwargs)
            finally:
                self.in_flip = False

        self.win.flip = counting_flip
        self.addCleanup(delattr, self.win, 'flip')

        self.ttl = []

        def record_ttl(handle, code, *args, **kwargs):
            self.ttl.append({'code': code, 'flip': self.n_flips, 'in_flip': self.in_flip})

        patcher = mock.patch.object(hw_events, 'send_trigger', record_ttl)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.neon = FakeNeon(lambda: (self.n_flips, self.in_flip))

    def run_with_events(self, block_index, scripts, checkpoint='middle', show_intro=True,
                        presentation_pos=None, group=None):
        env = EstimateEnv(win=self.win, global_clock=core.Clock(),
                           source=ScriptedSource(scripts, key_map=E.ESTIMATE_KEYS), stim=STIM, attrs=ATTRS,
                           subject_id='EV', subject_dir=self.tmp, session_id='S', lj_handle='LJ', neon=self.neon,
                           counterbalance_group=group)

        def one_frame_intro(win, text, advance_key='space'):
            win.flip()                                   # the intro screen appears; no key wait in tests

        with mock.patch.object(run_mod, 'show_instructions', one_frame_intro):
            result = run_estimate(env, block_index, S.BLOCK_PHASES[block_index], checkpoint, 7,
                                   show_intro=show_intro, presentation_pos=presentation_pos)
        return result, self.rows()

    def codes(self):
        return [e['code'] for e in self.ttl]

    def test_synergy_block_codes_labels_and_flip_alignment(self):
        block = 4                                         # a phase_1 block other than 0, so the ID is visible
        self.assertEqual(S.BLOCK_PHASES[block], 'phase_1')
        answers = ['left', 'down', 'right', 'left', 'down', 'right']
        result, rows = self.run_with_events(block, [_script(key, 'space') for key in answers],
                                            presentation_pos=3, group='B')
        self.assertFalse(result.aborted)

        self.assertEqual(self.codes(), [151] + [161, 171] * 6 + [181])
        prefix = 'P1_BLOCK_04_ESTIMATE_MIDDLE'
        expected_names = [f'{prefix}_START']
        for number, response in enumerate(['low', 'mid', 'high', 'low', 'mid', 'high'], start=1):
            expected_names += [f'{prefix}_Q{number:02d}_ONSET', f'{prefix}_Q{number:02d}_{response.upper()}_CONFIRM']
        expected_names.append(f'{prefix}_END_COMPLETE')
        self.assertEqual(self.neon.names(), expected_names)

        # Visual onsets go out inside a flip: the start on the intro's flip (the first),
        # each question onset on a later flip of its own, LabJack and Neon on the same flip.
        start = self.ttl[0]
        self.assertEqual((start['flip'], start['in_flip']), (1, True))
        onset_ttl = [e for e in self.ttl if e['code'] == 161]
        onset_neon = [e for e in self.neon.events if e['name'].endswith('_ONSET')]
        self.assertTrue(all(e['in_flip'] for e in onset_ttl + onset_neon))
        self.assertEqual([e['flip'] for e in onset_ttl], [e['flip'] for e in onset_neon])
        self.assertEqual(len({e['flip'] for e in onset_ttl}), 6)
        self.assertGreater(onset_ttl[0]['flip'], 1)
        # Responses and the end go out right away, between flips.
        for e in self.ttl:
            if e['code'] in (171, 181):
                self.assertFalse(e['in_flip'], e)
        for e in self.neon.events:
            if e['name'].endswith('_CONFIRM') or '_END_' in e['name']:
                self.assertFalse(e['in_flip'], e)

        # Behavioural CSV
        self.assertEqual([row['response'] for row in rows], ['low', 'mid', 'high', 'low', 'mid', 'high'])
        self.assertEqual({row['status'] for row in rows}, {'complete'})
        self.assertEqual({(row['block_idx'], row['presentation_pos'], row['counterbalance_group']) for row in rows},
                         {('4', '3', 'B')})

    def test_competence_block_uses_phase_2_codes(self):
        block = 3
        self.assertEqual(S.BLOCK_PHASES[block], 'phase_2')
        result, rows = self.run_with_events(block, [_script('right', 'space')] * 4, checkpoint='end',
                                            show_intro=False)
        self.assertEqual(self.codes(), [152] + [162, 172] * 4 + [182])
        # Without an intro, the start goes out on the first question's flip, before its onset.
        self.assertEqual(self.ttl[0]['flip'], self.ttl[1]['flip'])
        self.assertEqual(self.neon.names()[:2], ['P2_BLOCK_03_ESTIMATE_END_START',
                                                 'P2_BLOCK_03_ESTIMATE_END_Q01_ONSET'])
        self.assertEqual(self.neon.names()[-1], 'P2_BLOCK_03_ESTIMATE_END_END_COMPLETE')
        self.assertIn('P2_BLOCK_03_ESTIMATE_END_Q04_HIGH_CONFIRM', self.neon.names())
        self.assertEqual({row['presentation_pos'] for row in rows}, {''})     # not run from the block loop

    def test_timeout_has_no_confirm_and_still_completes(self):
        scripts = [[]] + [_script('down', 'space')] * 5
        with mock.patch.object(E, 'ESTIMATE_MAX_TIME', 0.2):
            result, rows = self.run_with_events(0, scripts)
        self.assertFalse(result.aborted)
        self.assertEqual(self.codes(), [151, 161] + [161, 171] * 5 + [181])
        names = self.neon.names()
        self.assertIn('P1_BLOCK_00_ESTIMATE_MIDDLE_Q01_TIMEOUT', names)
        self.assertFalse(any(n.startswith('P1_BLOCK_00_ESTIMATE_MIDDLE_Q01_') and n.endswith('_CONFIRM')
                             for n in names))
        self.assertEqual(names[-1], 'P1_BLOCK_00_ESTIMATE_MIDDLE_END_COMPLETE')
        self.assertEqual((rows[0]['status'], rows[0]['response']), ('timeout', ''))

    def test_esc_sends_aborted_and_end_then_stops(self):
        scripts = [_script('left', 'space'), _script('down', 'space'), _script('right', 'escape')]
        result, rows = self.run_with_events(0, scripts)
        self.assertTrue(result.aborted)
        self.assertEqual(self.codes(), [151, 161, 171, 161, 171, 161, 181])     # no confirm for Q03, no Q04
        self.assertEqual(self.neon.names()[-2:], ['P1_BLOCK_00_ESTIMATE_MIDDLE_Q03_ABORTED',
                                                  'P1_BLOCK_00_ESTIMATE_MIDDLE_END_ABORTED'])
        self.assertEqual([row['status'] for row in rows], ['complete', 'complete', 'aborted'])


if __name__ == '__main__':
    unittest.main()
