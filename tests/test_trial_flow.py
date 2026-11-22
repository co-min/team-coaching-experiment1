"""
Trial-flow tests: run real Phase 1 / Phase 2 trials in a small PsychoPy window
with emulated key presses, capturing LabJack codes and Neon events.

    python -m unittest tests.test_trial_flow -v

Opens a window on screen 0 for ~1 min. Nothing is sent to hardware
(send_trigger is replaced by a recorder; Neon is a fake client).
"""

import csv
import tempfile
import unittest
from collections import Counter
from pathlib import Path
from unittest import mock

from psychopy import core, event, visual

import hardware.events as hw_events
import recording.writers as writers
import task.block as block_mod
from config import settings as S
from hardware.frame_marker import init_marker
from hardware.labjack import (
    ANIMAL_IDX, TRIG_P1_CHOICE1, TRIG_P1_CHOICE2, TRIG_P2_CHOICE1, TRIG_P2_CHOICE2,
    TRIG_P1_CHOICE_ONSET, TRIG_P2_CHOICE_ONSET,
)
from recording.frame_logger import make_frame_log
from recording.stimuli_loader import load_stimuli, pair_key
from task.block import BlockEnv, run_block_trials
from task.forced_first import attach_forced_first
from task.schedule import generate_block_schedules
from task.trials.phase1 import run_phase1_trial
from task.trials.phase2 import run_phase2_trial
from task.visuals import VisualObjectFactory

ARROWS = ['up', 'down', 'right', 'left']   # slot index → key
FRAME = 1 / 60


class FakeNeon:
    session_id = recording_id = None

    def __init__(self):
        self.events = []

    def call_on_flip(self, win, names, **meta):
        win.callOnFlip(self.enqueue_events, names, metadata=meta)

    def enqueue_events(self, names, metadata=None):
        self.events += [names] if isinstance(names, str) else list(names)


class KeyScript:
    """Wraps win.flip; after the n-th flip of a segment, injects emulated keys."""

    def __init__(self, win):
        self.win, self._flip = win, win.flip
        self.plan, self.frame_log, self.count = [], None, Counter()
        win.flip = self.flip

    def arm(self, frame_log, plan):
        self.frame_log, self.plan, self.count = frame_log, list(plan), Counter()

    def flip(self, *a, **k):
        t = self._flip(*a, **k)
        if self.frame_log is not None:
            seg = self.frame_log['segment']
            self.count[seg] += 1
            for p_seg, n, keys in self.plan:
                if p_seg == seg and n == self.count[seg]:
                    for key in keys:
                        event._onPygletKey(key, 0, emulated=True)
        return t

    def restore(self):
        self.win.flip = self._flip


class TrialFlowBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.win = visual.Window(size=(1000, 700), fullscr=False, units='pix', color=S.BACKGROUND_COLOR,
                                colorSpace='hex', screen=0, winType='pyglet', allowGUI=True)
        init_marker(cls.win)
        cls.stim = load_stimuli()
        cls.factory = VisualObjectFactory(cls.win, cls.stim.animal_groups, S.DOMAINS)
        cls.schedules = generate_block_schedules(cls.stim.animal_groups)
        attach_forced_first(cls.schedules, cls.stim.animal_groups, cls.stim.char_code)
        cls.keys = KeyScript(cls.win)

    @classmethod
    def tearDownClass(cls):
        cls.keys.restore()
        cls.win.close()

    def setUp(self):
        self.ttl = []
        patcher = mock.patch.object(hw_events, 'send_trigger', lambda h, code, *a, **k: self.ttl.append(code))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.neon = FakeNeon()
        event.clearEvents()

    def run_trial(self, runner, block, trial, plan, forced):
        info = self.schedules[block][trial]
        frame_log = make_frame_log(phase=f'phase_{1 if runner is run_phase1_trial else 2}',
                                   trial_id=trial, stim_pair_id='test')
        self.keys.arm(frame_log, plan)
        clock = core.Clock()
        result = runner(self.win, clock, frame_log, self.factory, self.stim, info['domain'],
                        info['char_order'], handle=None, neon_client=self.neon,
                        forced_first=info['forced_first'] if forced else None)
        self.keys.arm(None, [])
        segments = Counter(r['segment'] for r in frame_log['rows'])
        return info, result, segments


class TestForcedTrialFlow(TrialFlowBase):

    def _forced_case(self, runner, block, trial, ch1_base, ch2_base, onset_code):
        info = self.schedules[block][trial]
        order = info['char_order']
        forced = info['forced_first']
        f_slot = order.index(forced)
        others = [i for i in range(4) if i != f_slot]
        target = others[1]
        plan = [
            # try to change / re-confirm the first animal during the forced display
            ('FORCED_FIRST', 5, [ARROWS[others[0]], 'space']),
            ('FORCED_FIRST', 8, [ARROWS[f_slot], 'space']),
            # try to pick the forced animal again as Choice 2
            ('CHOICE2', 5, [ARROWS[f_slot], 'space']),
            ('CHOICE2', 15, [ARROWS[target]]),
            ('CHOICE2', 20, ['space']),
        ]
        info, result, segments = self.run_trial(runner, block, trial, plan, forced=True)
        code = self.stim.char_code

        # first animal = schedule, cannot be changed, not a response
        self.assertEqual(result['choice1'], code[forced])
        self.assertIsNone(result['rt1'])
        # second choice: free, not the forced animal, the one we picked
        self.assertNotEqual(result['choice2'], result['choice1'])
        self.assertEqual(result['choice2'], code[order[target]])
        # RT measured from Choice 2 screen (space on its 20th frame), not from forced onset
        self.assertGreater(result['rt2'], 15 * FRAME)
        self.assertLess(result['rt2'], S.FORCED_FIRST_DURATION)
        # onsets
        gap = result['choice2_onset'] - result['forced_first_onset']
        self.assertAlmostEqual(gap, S.FORCED_FIRST_DURATION, delta=3 * FRAME)
        # segments: no participant Choice 1 phase
        self.assertNotIn('CHOICE1', segments)
        self.assertGreater(segments['FORCED_FIRST'], 0)
        self.assertGreater(segments['CHOICE2'], 0)
        # TTL: onset code at forced display, Choice 2 response code, never a Choice 1 code
        self.assertIn(onset_code, self.ttl)
        self.assertFalse(any(ch1_base <= c < ch1_base + 24 for c in self.ttl), self.ttl)
        self.assertEqual([c for c in self.ttl if ch2_base <= c < ch2_base + 24],
                         [ch2_base + ANIMAL_IDX[order[target]]])
        # Neon
        ph = 1 if runner is run_phase1_trial else 2
        self.assertIn(f"TRIAL_{trial:03d}_P{ph}_FORCED_FIRST", self.neon.events)
        self.assertIn(f"TRIAL_{trial:03d}_P{ph}_FORCED_FIRST_{forced.upper()}_ASSIGNED", self.neon.events)
        self.assertFalse(any(f"P{ph}_CHOICE1" in e for e in self.neon.events), self.neon.events)
        return result

    def test_phase1_forced(self):
        self._forced_case(run_phase1_trial, 0, 0, TRIG_P1_CHOICE1, TRIG_P1_CHOICE2, TRIG_P1_CHOICE_ONSET)

    def test_phase2_forced(self):
        self._forced_case(run_phase2_trial, 1, 0, TRIG_P2_CHOICE1, TRIG_P2_CHOICE2, TRIG_P2_CHOICE_ONSET)


class TestFreeTrialFlow(TrialFlowBase):

    def _free_case(self, runner, block, ch1_base, ch2_base):
        order = self.schedules[block][0]['char_order']
        plan = [
            ('CHOICE1', 5, ['right']),
            ('CHOICE1', 8, ['space']),
            ('CHOICE2', 5, ['right', 'space']),     # same animal again → ignored
            ('CHOICE2', 10, ['left']),
            ('CHOICE2', 12, ['space']),
        ]
        info, result, segments = self.run_trial(runner, block, 0, plan, forced=False)
        code = self.stim.char_code
        self.assertEqual(result['choice1'], code[order[2]])
        self.assertEqual(result['choice2'], code[order[3]])
        self.assertIsNotNone(result['rt1'])
        self.assertIsNone(result['forced_first_onset'])
        self.assertIsNotNone(result['choice2_onset'])
        self.assertNotIn('FORCED_FIRST', segments)
        self.assertGreater(segments['CHOICE1'], 0)
        self.assertIn(ch1_base + ANIMAL_IDX[order[2]], self.ttl)
        self.assertIn(ch2_base + ANIMAL_IDX[order[3]], self.ttl)

    def test_phase1_free(self):
        self._free_case(run_phase1_trial, 0, TRIG_P1_CHOICE1, TRIG_P1_CHOICE2)

    def test_phase2_free(self):
        self._free_case(run_phase2_trial, 1, TRIG_P2_CHOICE1, TRIG_P2_CHOICE2)


class TestBlockIntegration(TrialFlowBase):
    """Two trials through run_block_trials (ITI → trial → feedback → save) per mode."""

    def _run_block(self, mode, tmp):
        holder = {}
        real_make = block_mod.make_frame_log

        def make(**kw):
            fl = real_make(**kw)
            first = 'FORCED_FIRST' if mode == 'forced' else 'CHOICE1'
            plan = [('CHOICE2', 10, ['down', 'left', 'up', 'right']), ('CHOICE2', 12, ['space'])]
            if mode == 'free':
                plan = [('CHOICE1', 5, ['up']), ('CHOICE1', 7, ['space'])] + plan
            else:
                plan = [('FORCED_FIRST', 5, ['up', 'space'])] + plan
            self.keys.arm(fl, plan)
            holder['fl'] = fl
            return fl

        env = BlockEnv(win=self.win, global_clock=core.Clock(), factory=self.factory, stim=self.stim,
                       subject_id=f'test_{mode}', handle=None, neon_client=self.neon,
                       schedule_version='test-version' if mode == 'forced' else None)
        cumulative = {'total': 0, 'phase': 0, **{d: 0 for d in S.DOMAINS}}
        with mock.patch.object(writers, 'DATA_DIR', Path(tmp)), \
             mock.patch.object(block_mod, 'make_frame_log', make), \
             mock.patch.object(S, 'FIRST_CHOICE_MODE', mode):
            run_block_trials(env, 0, 'phase_1', self.schedules[0][:2], cumulative)
        self.keys.arm(None, [])
        with open(Path(tmp) / f'sub-test_{mode}' / 'trials.csv', encoding='utf-8') as f:
            return list(csv.DictReader(f)), cumulative

    def test_forced_and_free_blocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            forced_rows, forced_cum = self._run_block('forced', tmp)
            free_rows, _ = self._run_block('free', tmp)

        for i, row in enumerate(forced_rows):
            sched = self.schedules[0][i]
            self.assertEqual(row['first_choice_mode'], 'forced')
            self.assertEqual(row['forced_first_animal'], sched['forced_first'])
            self.assertEqual(row['choice1_animal'], sched['forced_first'])
            self.assertEqual(row['forced_first_code'], self.stim.char_code[sched['forced_first']])
            self.assertNotEqual(row['choice2_animal'], row['choice1_animal'])
            self.assertEqual(row['trig_choice1'], '')
            self.assertEqual(row['rt_choice1'], '')
            self.assertNotEqual(row['rt_choice2'], '')
            self.assertLess(float(row['forced_first_onset']), float(row['second_choice_onset']))
            self.assertEqual(row['selected_team'],
                             '+'.join(sorted([row['choice1_animal'], row['choice2_animal']])))
            self.assertEqual(row['schedule_version'], 'test-version')
            # scoring unchanged: same pair-score lookup as free mode
            expected = self.stim.scores[pair_key(row['choice1_code'], row['choice2_code'])][row['domain']]
            self.assertEqual(float(row['feedback_score']), expected)
        self.assertEqual(forced_cum['total'], sum(float(r['feedback_score']) for r in forced_rows))

        for row in free_rows:
            self.assertEqual(row['first_choice_mode'], 'free')
            self.assertEqual(row['forced_first_animal'], '')
            self.assertNotEqual(row['trig_choice1'], '')
            self.assertNotEqual(row['rt_choice1'], '')
            expected = self.stim.scores[pair_key(row['choice1_code'], row['choice2_code'])][row['domain']]
            self.assertEqual(float(row['feedback_score']), expected)

        # original columns still first, in the original order
        self.assertEqual(list(forced_rows[0])[:len(writers._TRIAL_FIELDS) - 7], writers._TRIAL_FIELDS[:-7])


if __name__ == '__main__':
    unittest.main()
