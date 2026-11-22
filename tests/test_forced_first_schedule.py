"""
Schedule-level tests for the fixed forced-first-choice CSV (no window needed).

    python -m unittest tests.test_forced_first_schedule -v
"""

import copy
import json
import os
import random
import subprocess
import sys
import unittest
from collections import Counter

from config import settings as S
from config.paths import FORCED_FIRST_CSV, ROOT_DIR
from recording.stimuli_loader import load_stimuli
from task.forced_first import (
    ScheduleError, attach_forced_first, balance_problems, read_schedule_csv,
    schedule_version, sync_problems, write_schedule_csv,
)
from task.schedule import generate_block_schedules

POSITIONS = ['A', 'B', 'C', 'D']


def _problems(rows, schedules, stim):
    return (balance_problems(rows, POSITIONS, len(schedules), S.N_TRIALS_PER_BLOCK, S.DOMAINS)
            + sync_problems(rows, schedules, stim.animal_groups, stim.char_code, S.BLOCK_PHASES))


class TestCommittedSchedule(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.stim = load_stimuli()
        cls.schedules = generate_block_schedules(cls.stim.animal_groups)
        cls.rows = read_schedule_csv()

    def test_design_assumptions(self):
        self.assertEqual(len(self.schedules), 6)
        self.assertTrue(all(len(b) == 15 for b in self.schedules))
        self.assertEqual(sorted(set(self.stim.char_code.values())), POSITIONS)
        for block in self.schedules:
            self.assertEqual(Counter(t['domain'] for t in block), {d: 5 for d in S.DOMAINS})

    def test_all_hard_constraints(self):
        self.assertEqual(_problems(self.rows, self.schedules, self.stim), [])

    def test_explicit_counts(self):
        rows = self.rows
        self.assertEqual(len(rows), 90)
        for b in range(6):
            c = Counter(r['forced_first_code'] for r in rows if r['block'] == b)
            self.assertEqual(sorted(c.values()), [3, 4, 4, 4], f"block {b}")
            for d in S.DOMAINS:
                dc = Counter(r['forced_first_code'] for r in rows if r['block'] == b and r['domain'] == d)
                self.assertEqual(set(dc), set(POSITIONS), f"block {b} {d}")
        g = Counter(r['forced_first_code'] for r in rows)
        self.assertTrue(all(v in (22, 23) for v in g.values()), g)
        for d in S.DOMAINS:
            dc = Counter(r['forced_first_code'] for r in rows if r['domain'] == d)
            self.assertTrue(all(dc[p] in (7, 8) for p in POSITIONS), (d, dc))
        for bt in ('competence_visible', 'synergy_visible'):
            bc = Counter(r['forced_first_code'] for r in rows if r['block_type'] == bt)
            self.assertEqual(sum(bc.values()), 45)
            self.assertTrue(all(bc[p] in (11, 12) for p in POSITIONS), (bt, bc))

    def test_no_immediate_repeats(self):
        for b in range(6):
            seq = [r['forced_first_code'] for r in sorted(
                (r for r in self.rows if r['block'] == b), key=lambda r: r['trial'])]
            self.assertTrue(all(x != y for x, y in zip(seq, seq[1:])), f"block {b}: {seq}")

    def test_generator_reproduces_committed_csv(self):
        from tools.make_forced_first_schedule import build_rows
        import contextlib, io
        with contextlib.redirect_stdout(io.StringIO()):
            rebuilt = build_rows()
        committed = [{k: v for k, v in r.items()} for r in self.rows]
        self.assertEqual(rebuilt, committed)


class TestValidatorCatchesErrors(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.stim = load_stimuli()
        cls.schedules = generate_block_schedules(cls.stim.animal_groups)
        cls.rows = read_schedule_csv()

    def _mutated(self, fn):
        rows = copy.deepcopy(self.rows)
        fn(rows)
        return _problems(rows, self.schedules, self.stim)

    def test_unbalanced_position(self):
        def fn(rows):
            # move one assignment of block 0 to another position (keeps code/animal consistent)
            r = rows[0]
            group = self.stim.animal_groups[0]
            other = next(a for a in group if self.stim.char_code[a] != r['forced_first_code'])
            r['forced_first'], r['forced_first_code'] = other, self.stim.char_code[other]
        self.assertTrue(self._mutated(fn))

    def test_domain_out_of_sync(self):
        def fn(rows):
            rows[3]['domain'] = next(d for d in S.DOMAINS if d != rows[3]['domain'])
        self.assertTrue(any('task domain' in p for p in self._mutated(fn)))

    def test_missing_and_duplicate_ids(self):
        self.assertTrue(self._mutated(lambda rows: rows.pop()))
        self.assertTrue(any('duplicate' in p for p in self._mutated(lambda rows: rows.append(dict(rows[0])))))

    def test_animal_from_wrong_block(self):
        def fn(rows):
            rows[0]['forced_first'] = self.stim.animal_groups[1][0]
        self.assertTrue(any('not in block animals' in p for p in self._mutated(fn)))

    def test_attach_raises_on_invalid_csv(self):
        import tempfile, pathlib
        rows = copy.deepcopy(self.rows)
        rows[0]['domain'] = next(d for d in S.DOMAINS if d != rows[0]['domain'])
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / 'bad.csv'
            write_schedule_csv(rows, path)
            with self.assertRaises(ScheduleError):
                attach_forced_first(generate_block_schedules(self.stim.animal_groups),
                                    self.stim.animal_groups, self.stim.char_code, path)


_DUMP_SNIPPET = r"""
import json, random, sys, time
random.seed(sys.argv[1])                       # per-subject global RNG state
from recording.stimuli_loader import load_stimuli
from task.schedule import generate_block_schedules
from task.forced_first import attach_forced_first
stim = load_stimuli()
sch = generate_block_schedules(stim.animal_groups)
ver = attach_forced_first(sch, stim.animal_groups, stim.char_code)
print(json.dumps({'version': ver,
                  'trials': [[t['domain'], t['forced_first'], t['char_order']] for b in sch for t in b]}))
"""


class TestCrossSubjectConsistency(unittest.TestCase):
    def test_identical_for_all_subjects(self):
        """Fresh interpreter per 'subject' with different global RNG and hash seeds."""
        outputs = []
        for i, subject in enumerate(['001', '002', 'P17', 'pilot-x', '999']):
            env = dict(os.environ, PYTHONHASHSEED=str(i * 7919))
            out = subprocess.run([sys.executable, '-c', _DUMP_SNIPPET, subject], cwd=ROOT_DIR,
                                 env=env, capture_output=True, text=True, check=True).stdout
            outputs.append(json.loads(out.strip().splitlines()[-1]))
        first = outputs[0]
        self.assertEqual(len(first['trials']), 90)
        for o in outputs[1:]:
            self.assertEqual(o, first)

    def test_repeat_loads_in_process_identical(self):
        stim = load_stimuli()
        seqs = []
        for seed in range(5):
            random.seed(seed)
            sch = generate_block_schedules(stim.animal_groups)
            attach_forced_first(sch, stim.animal_groups, stim.char_code)
            seqs.append([t['forced_first'] for b in sch for t in b])
        self.assertTrue(all(s == seqs[0] for s in seqs))
        self.assertEqual(schedule_version(), schedule_version(FORCED_FIRST_CSV))


if __name__ == '__main__':
    unittest.main()
