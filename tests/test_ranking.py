"""
Ranking assessment tests.

    python -m unittest tests.test_ranking -v

Logic tests need no window. The *Screen tests open a small window on
screen 0 (~20 s) and drive the real screens with scripted key presses,
then check what was written to disk.
"""

import copy
import csv
import json
import random
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from psychopy import core, visual

from config import ranking as R
from config import settings as S
from recording.ranking_writers import EVENT_FIELDS, RANKING_FIELDS
from recording.stimuli_loader import load_stimuli
from task.forced_first import attach_forced_first
from task.ranking import flow
from task.ranking.assessments import (
    Probe, ProbeCondition, RankingEnv, _shuffled, block_probes, change_level, run_block_rankings,
)
from task.ranking.inputs import ScriptedSource, action_map
from task.ranking.items import (
    Change, RankItem, RankingSpec, _average_ranks, kendall_distance, load_attributes, pair_items, spearman,
    true_values,
)
from task.ranking.record import build_ranking_record
from task.ranking.schedule import (
    probe_order, probe_order_problems, ranking_domain, ranking_domain_problems, saved_ranking_problems,
)
from task.ranking.state import RevisedRanking, SequentialRanking
from task.schedule import block_order, block_order_problems, counterbalance_group, generate_block_schedules

STIM = load_stimuli()
ATTRS = load_attributes(STIM.synergy)
GROUP0 = STIM.animal_groups[0]


def _items(n=4):
    return [RankItem((c,), (c.lower(),)) for c in 'ABCDEF'[:n]]


class TestItems(unittest.TestCase):
    def test_items_use_block_animals(self):
        for g in STIM.animal_groups:
            pairs = pair_items(g, STIM.char_code)
            self.assertEqual(len(pairs), 6)
            self.assertEqual(sorted({a for it in pairs for a in it.animals}), sorted(g))
            for it in pairs:
                self.assertEqual([STIM.char_code[a] for a in it.animals], list(it.roles))

    def test_raw_competence_not_truncated(self):
        self.assertEqual(ATTRS.competence['A']['cooking'], 8.5)

    def test_performance_matches_task_scores(self):
        """Ordering by Performance agrees with the task's rank-coded pair scores."""
        for d in S.DOMAINS:
            perf = {p: ATTRS.performance(p, d) for p in STIM.scores}
            for p in perf:
                for q in perf:
                    if perf[p] > perf[q]:
                        self.assertGreater(STIM.scores[p][d], STIM.scores[q][d], (d, p, q))

    def test_changes_do_not_accumulate(self):
        c1 = Change('competence', ('C',), 8.5, domain='cooking')
        c2 = Change('synergy', ('B', 'C'), 1.4)
        a1 = ATTRS.with_change(c1)
        a2 = ATTRS.with_change(c2)
        self.assertEqual(a1.competence['C']['cooking'], 8.5)
        self.assertEqual(ATTRS.competence['C']['cooking'], 2.2)       # original untouched
        self.assertEqual(a2.competence['C']['cooking'], 2.2)          # probe 2 does not see probe 1
        self.assertEqual(a2.synergy[('B', 'C')], 1.4)
        self.assertEqual(ATTRS.synergy[('B', 'C')], 0.8)

    def test_change_level_uses_task_colours(self):
        self.assertEqual(change_level(STIM, Change('competence', ('C',), 8.5, domain='cooking'))[0], 'high')
        self.assertEqual(change_level(STIM, Change('synergy', ('B', 'C'), 0.8))[0], 'low')
        with self.assertRaises(ValueError):
            change_level(STIM, Change('synergy', ('B', 'C'), 1.2))

    def test_agreement_metrics(self):
        truth = {'A': 3.0, 'B': 2.0, 'C': 1.0}
        self.assertEqual(spearman(['A', 'B', 'C'], truth), 1.0)
        self.assertEqual(spearman(['C', 'B', 'A'], truth), -1.0)
        self.assertIsNone(spearman(['A', 'B'], truth))
        self.assertEqual(kendall_distance(['A', 'B', 'C'], ['C', 'B', 'A']), 3)
        self.assertEqual(kendall_distance(['A', 'B', 'C'], ['A', 'B', 'C']), 0)

    def test_agreement_metrics_with_ties(self):
        self.assertEqual(_average_ranks([5.0, 3.0, 3.0, 1.0]), [1.0, 2.5, 2.5, 4.0])
        self.assertIsNone(spearman(['A', 'B'], {'A': 1.0, 'B': 1.0}))          # no variance
        self.assertEqual(spearman(['A', 'B', 'C'], {'A': 2.0, 'B': 2.0, 'C': 1.0}), 0.866)
        self.assertIsNone(kendall_distance(['A', 'B'], ['A', 'C']))


class TestRegression(unittest.TestCase):
    """Behaviour pinned during the readability refactor."""

    def _result(self, status='complete', initial=()):
        items = pair_items(GROUP0, STIM.char_code)
        spec = RankingSpec('b0_probe1_competence', 'counterfactual', 0, 'phase_1', tuple(GROUP0),
                           {STIM.char_code[a]: a for a in GROUP0}, domain='cooking', probe_pos=1,
                           change=Change('competence', ('C',), 8.5, domain='cooking'), baseline_id='b0_baseline',
                           presentation_pos=1, counterbalance_group='B', probe_order='competence>synergy')
        events = [{'event_idx': 0, 'event': 'onset', 'key': None, 'rt': 0.0},
                  {'event_idx': 1, 'event': 'move', 'key': 'down', 'rt': 0.25}]
        return flow.RankingResult(spec=spec, display_order=items, initial=list(initial), final=items[::-1],
                                  status=status, onset_global=1.0, end_rt=0.5, events=events)

    def test_record_schema_matches_writer_columns(self):
        record, events = build_ranking_record(self._result(), ATTRS, 'T01', 'S', 'high')
        self.assertEqual(list(record), RANKING_FIELDS)
        self.assertEqual(list(events[0])[:9], EVENT_FIELDS[:9])          # identity columns
        self.assertEqual((record['confirm_global'], record['first_key_rt'], record['n_moves']), (1.5, 0.25, 1))
        self.assertEqual((record['counterbalance_group'], record['presentation_pos'], record['probe_pos'],
                          record['baseline_id'], record['probe_order']),
                         ('B', 1, 1, 'b0_baseline', 'competence>synergy'))
        self.assertIsNone(record['changed'])                    # no initial ranking
        timed_out, _ = build_ranking_record(self._result('timeout', initial=self._result().final), ATTRS, 'T01')
        self.assertEqual((timed_out['confirm_rt'], timed_out['spearman_true'], timed_out['changed']),
                         (None, None, False))

    def test_display_order_is_reproducible(self):
        env = RankingEnv(None, None, None, STIM, ATTRS, 'T01', Path('.'))
        spec = RankingSpec('b0_baseline', 'performance', 0, 'phase_1', tuple(GROUP0), {}, domain='cooking')
        self.assertEqual(_shuffled(env, spec), _shuffled(env, spec))
        other = RankingEnv(None, None, None, STIM, ATTRS, 'T02', Path('.'))
        self.assertEqual(sorted(_shuffled(other, spec), key=lambda i: i.roles),
                         pair_items(GROUP0, STIM.char_code))

    def test_outcome_extras_go_to_detail(self):
        items = _items(2)
        fields = flow._fields({'event': 'move', 'item': items[0], 'from_pos': 2, 'to_pos': 1,
                               'displaced': items[1], 'relocated': True})
        self.assertEqual(fields, {'item': items[0], 'from_pos': 2, 'to_pos': 1,
                                  'detail': 'displaced=B;relocated=True'})
        self.assertIsNone(flow._fields({'event': 'select', 'item': items[0], 'rank_pos': 1})['detail'])


class TestSequentialState(unittest.TestCase):
    def test_place_skips_removed_and_wraps(self):
        s = SequentialRanking(_items(4))
        s.move(+1)                      # cursor 1
        s.place()                       # B → rank 1, cursor → 2
        self.assertEqual(s.cursor, 2)
        s.move(-1)                      # skips the empty slot 1
        self.assertEqual(s.cursor, 0)
        s.move(-1)                      # wraps to the bottom
        self.assertEqual(s.cursor, 3)

    def test_undo_restores_slot_and_cursor(self):
        items = _items(4)
        s = SequentialRanking(items)
        s.place(); s.place()
        out = s.undo()
        self.assertEqual(out['item'], items[1])
        self.assertEqual(s.options[1], items[1])
        self.assertEqual(s.cursor, 1)
        self.assertEqual(s.ranking, [items[0]])

    def test_complete_and_nothing_left(self):
        s = SequentialRanking(_items(3))
        for _ in range(3):
            s.place()
        self.assertTrue(s.complete)
        self.assertIsNone(s.cursor)
        self.assertIsNone(s.place())
        self.assertIsNone(s.move(1))
        self.assertIsNone(SequentialRanking(_items(2)).undo())


class TestRevisedState(unittest.TestCase):
    def test_move_held_item(self):
        items = _items(4)
        s = RevisedRanking(items)
        s.move(+1); s.toggle_hold(); s.move(+1); s.move(+1)
        self.assertIsNone(s.move(+1))   # bottom
        s.toggle_hold()
        self.assertEqual(s.order, [items[0], items[2], items[3], items[1]])
        self.assertEqual(s.n_relocations, 1)
        self.assertTrue(s.changed)

    def test_undo_reverts_and_unchanged_submission(self):
        items = _items(4)
        s = RevisedRanking(items)
        s.toggle_hold(); s.move(+1); s.toggle_hold()
        s.undo()
        self.assertEqual(s.order, items)
        self.assertFalse(s.changed)

    def test_undo_while_holding_only_current_pickup(self):
        items = _items(4)
        s = RevisedRanking(items)
        s.toggle_hold(); s.move(+1); s.toggle_hold()     # episode 1: A down
        s.move(+1); s.toggle_hold()                      # episode 2: hold C, no moves yet
        self.assertIsNone(s.undo())
        s.toggle_hold()
        self.assertIsNotNone(s.undo())

    def test_pick_up_put_down_in_place_is_not_a_relocation(self):
        s = RevisedRanking(_items(3))
        s.toggle_hold(); s.toggle_hold()
        self.assertEqual(s.n_relocations, 0)

    def test_revision_does_not_mutate_its_starting_list(self):
        items = _items(4)
        start = list(items)
        s = RevisedRanking(start)
        s.toggle_hold(); s.move(+1); s.toggle_hold()
        self.assertEqual(start, items)


class TestKeyMap(unittest.TestCase):
    def test_confirm_must_be_distinct(self):
        with self.assertRaises(ValueError):
            action_map({**R.RANKING_KEYS, 'confirm': ['space']})
        with self.assertRaises(ValueError):
            action_map({'up': ['1'], 'down': ['1']})
        self.assertEqual(action_map()['return'], 'confirm')


# ── schedules ─────────────────────────────────────────────────────────────────

SCHEDULE = R.PERFORMANCE_RANKING_DOMAINS
PROBE_ORDERS = R.PROBE_ORDERS
CONDITIONS = {'competence': ProbeCondition('competence', ('C',), 8.5),
              'synergy':    ProbeCondition('synergy', ('B', 'C'), 1.4)}


def _problems(schedule):
    return ranking_domain_problems(schedule, S.BLOCK_PHASES, S.DOMAINS)


def _order_problems(orders):
    return probe_order_problems(orders, S.BLOCK_PHASES, SCHEDULE)


class TestRankingSchedule(unittest.TestCase):
    def test_agreed_schedule(self):
        self.assertEqual(SCHEDULE, ('cooking', 'repairing', 'tennis', 'cooking', 'repairing', 'tennis'))
        self.assertEqual(_problems(SCHEDULE), [])
        self.assertEqual([ranking_domain(b) for b in range(6)], list(SCHEDULE))
        for domain in S.DOMAINS:
            phases_of_domain = []
            for block_index in range(len(SCHEDULE)):
                if SCHEDULE[block_index] == domain:
                    phases_of_domain.append(S.BLOCK_PHASES[block_index])
            self.assertEqual(sorted(phases_of_domain), ['phase_1', 'phase_2'], domain)

    def test_broken_schedules_fail(self):
        cases = {
            'old placeholder: one domain everywhere': ['cooking'] * 6,
            'cooking twice in phase_1':  ['cooking', 'repairing', 'cooking', 'tennis', 'tennis', 'repairing'],
            'back-to-back repeat':       ['cooking', 'cooking', 'repairing', 'repairing', 'tennis', 'tennis'],
            'wrong length':              ['cooking', 'repairing', 'tennis'],
            'unknown domain':            ['cooking', 'repairing', 'tennis', 'cooking', 'repairing', 'golf'],
        }
        for name, schedule in cases.items():
            self.assertNotEqual(_problems(schedule), [], name)
        self.assertTrue(any('phase_1' in p for p in _problems(cases['cooking twice in phase_1'])))
        self.assertEqual(_problems(cases['back-to-back repeat']),
                         ['blocks 0 and 1 both use cooking', 'blocks 2 and 3 both use repairing',
                          'blocks 4 and 5 both use tennis'])


class TestProbeOrderSchedule(unittest.TestCase):
    def test_agreed_probe_orders(self):
        c, s = 'competence', 'synergy'
        self.assertEqual(PROBE_ORDERS, ((c, s), (c, s), (s, c), (s, c), (s, c), (c, s)))
        self.assertEqual(_order_problems(PROBE_ORDERS), [])
        self.assertEqual([probe_order(b)[0] for b in range(6)].count(c), 3)
        for domain in S.DOMAINS:
            firsts = {probe_order(b)[0] for b in range(6) if SCHEDULE[b] == domain}
            self.assertEqual(firsts, {c, s}, domain)
        for phase in set(S.BLOCK_PHASES):
            firsts = {probe_order(b)[0] for b in range(6) if S.BLOCK_PHASES[b] == phase}
            self.assertEqual(firsts, {c, s}, phase)

    def test_broken_probe_orders_fail(self):
        c, s = 'competence', 'synergy'
        confounded_with_phase = ((c, s), (s, c)) * 3          # phase_1 always competence-first
        self.assertTrue(any('phase phase_1' in p for p in _order_problems(confounded_with_phase)))
        # 3/3 and both orders per phase, but cooking (blocks 0, 3) always competence-first
        confounded_with_domain = ((c, s), (s, c), (s, c), (c, s), (c, s), (s, c))
        self.assertTrue(any('domain cooking' in p for p in _order_problems(confounded_with_domain)))
        self.assertTrue(any('unbalanced' in p for p in _order_problems(((c, s),) * 4 + ((s, c),) * 2)))
        self.assertNotEqual(_order_problems(((c, c),) + PROBE_ORDERS[1:]), [])
        self.assertNotEqual(_order_problems(PROBE_ORDERS[:5]), [])

    def test_block_probes_follow_original_block(self):
        for block_index in range(6):
            probes = block_probes(block_index, CONDITIONS)
            self.assertEqual([p.position for p in probes], [1, 2])
            self.assertEqual(tuple(p.change.kind for p in probes), PROBE_ORDERS[block_index])
            self.assertEqual({p.domain for p in probes}, {SCHEDULE[block_index]})

    def test_mislabelled_condition_rejected(self):
        with self.assertRaises(ValueError):
            block_probes(0, {'competence': CONDITIONS['synergy'], 'synergy': CONDITIONS['synergy']})


class TestBlockOrder(unittest.TestCase):
    def test_group_from_subject_id(self):
        for subject_id, group in (('001', 'A'), ('002', 'B'), ('P17', 'A'), ('sub-10', 'B'), (' 9 ', 'A')):
            self.assertEqual(counterbalance_group(subject_id), group, subject_id)
        for subject_id in ('preview', '12a', ''):
            with self.assertRaises(ValueError):
                counterbalance_group(subject_id)

    def test_agreed_orders(self):
        self.assertEqual(block_order('A'), (0, 1, 2, 3, 4, 5))
        self.assertEqual(block_order('B'), (1, 0, 5, 4, 3, 2))
        self.assertEqual(block_order_problems(S.BLOCK_ORDERS, len(S.BLOCK_PHASES)), [])
        with self.assertRaises(ValueError):
            block_order('C')

    def test_broken_orders_fail(self):
        self.assertNotEqual(block_order_problems({'A': (0, 1, 2, 3, 4, 4)}, 6), [])
        self.assertNotEqual(block_order_problems({'A': (0, 1, 2, 3, 4)}, 6), [])

    def test_order_changes_only_presentation(self):
        """Every original block keeps its phase, animals, learning trials, forced first choices,
        ranking domain and probe order, whichever group presents it and in what global RNG state."""
        def per_block(rng_seed):
            random.seed(rng_seed)
            schedules = generate_block_schedules(STIM.animal_groups)
            attach_forced_first(schedules, STIM.animal_groups, STIM.char_code)
            return schedules

        reference = per_block(0)
        for rng_seed, group in enumerate(sorted(S.BLOCK_ORDERS), start=1):
            schedules = per_block(rng_seed)
            for block_index in block_order(group):
                self.assertEqual(schedules[block_index], reference[block_index], (group, block_index))
                self.assertLessEqual({t['forced_first'] for t in schedules[block_index]},
                                     set(STIM.animal_groups[block_index]))
                self.assertEqual(probe_order(block_index), PROBE_ORDERS[block_index])
                self.assertEqual(ranking_domain(block_index), SCHEDULE[block_index])


# ── saved-data check ──────────────────────────────────────────────────────────

def _saved_row(block_index, ranking_id, ranking_type, baseline_id, probe_pos='', change=None,
               status='complete', initial='', final='A+B|C+D'):
    """One rankings.csv row as csv.DictReader returns it: every value a string, None as ''."""
    change_kind = ''
    change_domain = ''
    if change is not None:
        change_kind = change.kind
        if change.domain is not None:
            change_domain = change.domain
    return {
        'block_index':     str(block_index),
        'phase':           S.BLOCK_PHASES[block_index],
        'domain':          SCHEDULE[block_index],
        'ranking_id':      ranking_id,
        'ranking_type':    ranking_type,
        'baseline_id':     baseline_id,
        'probe_order':     '>'.join(PROBE_ORDERS[block_index]),
        'probe_pos':       str(probe_pos),
        'change_kind':     change_kind,
        'change_domain':   change_domain,
        'status':          status,
        'initial_ranking': initial,
        'final_ranking':   final,
    }


def _saved_rows():
    """Every block: one shared baseline then its two revisions, as the preview saves them."""
    rows = []
    for block_index in range(len(SCHEDULE)):
        baseline_id = f"b{block_index}_baseline"
        rows.append(_saved_row(block_index, baseline_id, 'performance', baseline_id, final='A+B|C+D'))
        for probe in block_probes(block_index, CONDITIONS):
            rows.append(_saved_row(block_index, f"b{block_index}_probe{probe.position}_{probe.change.kind}",
                                   'counterfactual', baseline_id, probe.position, probe.change,
                                   initial='A+B|C+D', final='C+D|A+B'))
    return rows


def _check(rows):
    return saved_ranking_problems(rows, SCHEDULE, S.BLOCK_PHASES, PROBE_ORDERS)


class TestSavedRankingCheck(unittest.TestCase):
    def test_complete_schedule_passes(self):
        self.assertEqual(_check(_saved_rows()), [])

    def test_partial_run_checks_rows_only(self):
        rows = [r for r in _saved_rows() if r['block_index'] in ('0', '1')]
        self.assertEqual(_check(rows), [])

    def test_violations_reported(self):
        # rows[0] = b0 baseline, rows[1] = b0 probe 1 (competence), rows[2] = b0 probe 2 (synergy)
        def problems(mutate):
            rows = _saved_rows()
            mutate(rows)
            return _check(rows)

        def wrong_block_domain(rows):
            for r in rows:
                if r['block_index'] == '3':
                    r['domain'] = 'tennis'

        def revised_other_domain(rows):
            rows[1]['domain'] = 'tennis'

        def competence_other_domain(rows):
            rows[1]['change_domain'] = 'tennis'

        def synergy_with_domain(rows):
            rows[2]['change_domain'] = 'cooking'

        def wrong_phase(rows):
            rows[0]['phase'] = 'phase_2'

        def second_baseline(rows):
            rows.insert(1, _saved_row(0, 'b0_baseline_again', 'performance', 'b0_baseline_again'))

        def revision_not_from_shared_baseline(rows):
            rows[2]['initial_ranking'] = rows[1]['final_ranking']     # probe 2 started from probe 1's result

        def probe_kinds_swapped(rows):
            rows[1]['probe_pos'], rows[2]['probe_pos'] = '2', '1'

        def wrong_probe_order(rows):
            rows[0]['probe_order'] = 'synergy>competence'

        def revised_after_timeout(rows):
            rows[0]['status'] = 'timeout'

        def baseline_from_other_block(rows):
            rows[4]['baseline_id'] = 'b0_baseline'                     # b1 probe 1 → b0 baseline

        def duplicate_probe(rows):
            rows.insert(2, dict(rows[1]))

        for mutate in (wrong_block_domain, revised_other_domain, competence_other_domain, synergy_with_domain,
                       wrong_phase, second_baseline, revision_not_from_shared_baseline, probe_kinds_swapped,
                       wrong_probe_order, revised_after_timeout, baseline_from_other_block, duplicate_probe):
            self.assertNotEqual(problems(mutate), [], mutate.__name__)


class TestProbeBinding(unittest.TestCase):
    def test_competence_change_uses_ranking_domain(self):
        for d in S.DOMAINS:
            probe = CONDITIONS['competence'].for_domain(d, 1)
            self.assertEqual((probe.domain, probe.change.domain, probe.position), (d, d, 1))
            changed = ATTRS.with_change(probe.change)
            self.assertEqual(changed.competence['C'][d], 8.5)
            for other in set(S.DOMAINS) - {d}:
                self.assertEqual(changed.competence['C'][other], ATTRS.competence['C'][other])

    def test_synergy_change_has_no_domain(self):
        probe = CONDITIONS['synergy'].for_domain('tennis', 2)
        self.assertEqual((probe.domain, probe.change.domain), ('tennis', None))
        self.assertEqual(ATTRS.with_change(probe.change).competence, ATTRS.competence)

    def test_mismatched_competence_domain_rejected(self):
        with self.assertRaises(ValueError):
            Probe(1, 'tennis', Change('competence', ('C',), 8.5, domain='cooking'))

    def test_no_carryover_across_blocks(self):
        # every block's probes start from the original attributes
        original_competence = copy.deepcopy(ATTRS.competence)
        original_synergy = copy.deepcopy(ATTRS.synergy)
        for block_index in range(len(SCHEDULE)):
            for probe in block_probes(block_index, CONDITIONS):
                ATTRS.with_change(probe.change)
        self.assertEqual(ATTRS.competence, original_competence)
        self.assertEqual(ATTRS.synergy, original_synergy)
        a = ATTRS.with_change(CONDITIONS['synergy'].for_domain('cooking', 2).change)
        self.assertEqual(a.competence['C']['cooking'], 2.2)       # synergy probe does not see the competence one


# ── screen tests ──────────────────────────────────────────────────────────────

def _script(*keys, t0=0.1, dt=0.05):
    """[(rt, key), ...] at t0, t0+dt, ..."""
    return [(round(t0 + i * dt, 3), k) for i, k in enumerate(keys)]


BASELINE_KEYS = _script(*(['space'] * 6), 'return')
CONTINUE = _script('space')


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
        p = mock.patch.object(R, 'CONFIRM_FEEDBACK_S', 0.0)
        p.start()
        self.addCleanup(p.stop)

    def env(self, *scripts, group='A'):
        self.source = ScriptedSource(scripts)
        return RankingEnv(win=self.win, global_clock=core.Clock(), source=self.source, stim=STIM, attrs=ATTRS,
                          subject_id='T01', subject_dir=self.tmp, session_id='S', counterbalance_group=group)

    def rows(self, name):
        with open(self.tmp / name, encoding='utf-8') as f:
            return list(csv.DictReader(f))


class TestBaselineScreen(ScreenBase):
    """The sequential baseline ranking; the first change screen is escaped so only the baseline runs."""

    def run_baseline(self, *baseline_keys, extra=(_script('escape'),)):
        env = self.env(_script(*baseline_keys), *extra)
        out = run_block_rankings(env, 0, 0, CONDITIONS)
        self.assertEqual(out.revised, [])
        self.assertTrue(out.aborted)
        return out.baseline

    def test_baseline_ranking_saved(self):
        # 6 pairs: place slot 0, then the next available each time; one undo + re-place; confirm.
        keys = ['space', 'space', 'backspace', 'space', 'x', 'return', 'space', 'space', 'space', 'space',
                'return']
        res = self.run_baseline(*keys)
        self.assertEqual(res.status, 'complete')

        rec = self.rows('rankings.csv')[0]
        self.assertEqual((rec['ranking_id'], rec['ranking_type'], rec['domain'], rec['baseline_id']),
                         ('b0_baseline', 'performance', 'cooking', 'b0_baseline'))
        self.assertEqual((rec['counterbalance_group'], rec['presentation_pos'], rec['probe_order'], rec['probe_pos']),
                         ('A', '0', 'competence>synergy', ''))
        self.assertEqual(rec['animal_set'], ','.join(GROUP0))
        self.assertEqual(rec['n_items'], '6')
        # placing top-to-bottom reproduces the display order
        self.assertEqual(rec['final_ranking'], rec['display_order'])
        self.assertEqual(rec['n_keypresses'], str(len(keys)))
        self.assertEqual(rec['n_undos'], '1')
        self.assertEqual(rec['n_unmapped'], '1')
        self.assertEqual(rec['n_invalid'], '1')          # first 'return' before complete
        self.assertEqual(rec['n_selections'], '7')
        self.assertAlmostEqual(float(rec['confirm_rt']), _script(*keys)[-1][0], places=4)
        self.assertNotEqual(rec['spearman_true'], '')

        ev = self.rows('ranking_events.csv')
        self.assertEqual(ev[0]['event'], 'onset')
        self.assertEqual({(e['baseline_id'], e['counterbalance_group']) for e in ev}, {('b0_baseline', 'A')})
        presses = [e for e in ev if e['key']]
        self.assertEqual([e['key'] for e in presses], keys)
        onset = float(rec['onset_global'])
        for e, (t, _) in zip(presses, _script(*keys)):
            self.assertAlmostEqual(float(e['rt']), t, places=4)
            self.assertAlmostEqual(float(e['t_global']), onset + t, places=4)
        selects = [e for e in ev if e['event'] == 'select']
        self.assertEqual([e['rank_pos'] for e in selects], ['1', '2', '2', '3', '4', '5', '6'])
        self.assertTrue((self.tmp / 'rankings' / 'b0_baseline.json').exists())

    def test_abort_saves_partial_and_skips_revisions(self):
        res = self.run_baseline('space', 'escape', extra=(CONTINUE,))
        self.assertTrue(res.aborted)
        rec = self.rows('rankings.csv')[0]
        self.assertEqual(rec['status'], 'aborted')
        self.assertEqual(len(rec['final_ranking'].split('|')), 1)
        self.assertEqual(rec['confirm_rt'], '')
        self.assertEqual(len(self.source._scripts), 1)       # change screen never shown

    def test_timeout_saves_partial_and_skips_revisions(self):
        env = self.env(_script('space'), CONTINUE, _script('return'))
        with mock.patch.object(R, 'RANKING_MAX_TIME', 0.3):
            out = run_block_rankings(env, 0, 0, CONDITIONS)
        self.assertEqual((out.baseline.status, out.revised, out.aborted), ('timeout', [], False))
        self.assertEqual(len(out.baseline.final), 1)           # not filled in from the display order
        rows = self.rows('rankings.csv')
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]['status'], rows[0]['rank2']), ('timeout', ''))
        self.assertEqual(self.rows('ranking_events.csv')[-1]['event'], 'timeout')
        self.assertEqual(len(self.source._scripts), 2)       # no change screen, no revised ranking


class TestSharedBaselineScreen(ScreenBase):
    MOVE_SECOND_TO_TOP = _script('down', 'space', 'up', 'space', 'return')

    def test_both_revisions_start_from_the_shared_baseline(self):
        # block 0: competence first. Probe 1 moves the 2nd team up; probe 2 submits unchanged.
        env = self.env(BASELINE_KEYS, _script('space', t0=0.2), self.MOVE_SECOND_TO_TOP,
                       _script('space', t0=0.3), CONTINUE, _script('return'))
        out = run_block_rankings(env, 0, 0, CONDITIONS)
        self.assertFalse(out.aborted)
        rev1, rev2 = out.revised

        # the in-memory results
        self.assertEqual(rev1.initial, out.baseline.final)
        self.assertEqual(rev2.initial, out.baseline.final)
        self.assertNotEqual(rev2.initial, rev1.final)
        self.assertEqual(rev2.final, out.baseline.final)

        # the saved rows
        b, r1, r2 = self.rows('rankings.csv')
        self.assertEqual([row['ranking_id'] for row in (b, r1, r2)],
                         ['b0_baseline', 'b0_probe1_competence', 'b0_probe2_synergy'])
        self.assertEqual({row['baseline_id'] for row in (b, r1, r2)}, {'b0_baseline'})
        self.assertEqual((r1['probe_pos'], r1['change_kind'], r2['probe_pos'], r2['change_kind']),
                         ('1', 'competence', '2', 'synergy'))
        self.assertEqual((r1['initial_ranking'], r2['initial_ranking']), (b['final_ranking'], b['final_ranking']))
        bf = b['final_ranking'].split('|')
        self.assertEqual(r1['final_ranking'].split('|'), [bf[1], bf[0]] + bf[2:])
        self.assertEqual((r1['changed'], r1['n_moves'], r1['n_relocations'], r1['kendall_from_initial']),
                         ('True', '1', '1', '1'))
        self.assertEqual((r2['changed'], r2['n_changed_positions']), ('False', '0'))
        self.assertEqual((r1['change_roles'], r1['change_level'], r1['change_value']), ('C', 'high', '8.5'))
        self.assertEqual(r1['change_animals'], STIM.animal_groups[0][2])
        self.assertAlmostEqual(float(r1['change_rt']), 0.2, places=4)

        # reset screen only before probe 2, and between the two rankings in time
        self.assertEqual((r1['reset_onset'], r1['reset_rt']), ('', ''))
        self.assertAlmostEqual(float(r2['reset_rt']), 0.3, places=4)
        self.assertLess(float(r1['confirm_global']), float(r2['reset_onset']))
        self.assertLess(float(r2['reset_onset']), float(r2['change_onset']))
        self.assertLess(float(r2['change_onset']), float(r2['onset_global']))
        for row in (b, r1, r2):
            self.assertNotEqual(row['onset_global'], '')
            self.assertNotEqual(row['confirm_global'], '')

        # each change applied independently to the original attributes
        items = pair_items(GROUP0, STIM.char_code)
        base_truth = true_values(ATTRS, items, 'cooking')
        comp_truth = true_values(ATTRS.with_change(Change('competence', ('C',), 8.5, domain='cooking')),
                                 items, 'cooking')
        syn_truth = true_values(ATTRS.with_change(Change('synergy', ('B', 'C'), 1.4)), items, 'cooking')
        for row, truth in ((b, base_truth), (r1, comp_truth), (r2, syn_truth)):
            self.assertEqual(row['true_values'], ';'.join(f"{k}:{v}" for k, v in truth.items()), row['ranking_id'])
        self.assertEqual(r1['true_order'].split('|')[0], 'A+C')
        self.assertIn(f"A+C:{base_truth['A+C']}", r2['true_values'])     # C's boost not carried into probe 2

        ev = [e for e in self.rows('ranking_events.csv') if e['ranking_id'] == r1['ranking_id']]
        self.assertEqual([e['event'] for e in ev], ['onset', 'cursor', 'pick_up', 'move', 'put_down', 'confirm'])
        self.assertEqual({e['probe_pos'] for e in ev}, {'1'})
        self.assertEqual(_check(self.rows('rankings.csv')), [])

    def test_synergy_first_block_and_presentation_position(self):
        env = self.env(BASELINE_KEYS, CONTINUE, _script('return'), CONTINUE, CONTINUE, _script('return'),
                       group='B')
        out = run_block_rankings(env, 2, 5, CONDITIONS)       # group B presents block 2 last
        self.assertEqual([r.spec.change.kind for r in out.revised], ['synergy', 'competence'])
        rows = self.rows('rankings.csv')
        self.assertEqual([r['ranking_id'] for r in rows],
                         ['b2_baseline', 'b2_probe1_synergy', 'b2_probe2_competence'])
        self.assertEqual({(r['block_index'], r['presentation_pos'], r['counterbalance_group'], r['phase'],
                           r['domain'], r['probe_order']) for r in rows},
                         {('2', '5', 'B', 'phase_1', 'tennis', 'synergy>competence')})
        self.assertEqual(rows[2]['change_domain'], 'tennis')
        self.assertEqual(_check(rows), [])

    def test_confirm_while_holding_refused(self):
        revised = _script('space', 'return', 'space', 'return')   # hold → confirm refused → drop → submit
        env = self.env(BASELINE_KEYS, CONTINUE, revised, CONTINUE, CONTINUE, _script('return'))
        out = run_block_rankings(env, 0, 0, CONDITIONS)
        r1 = self.rows('rankings.csv')[1]
        self.assertEqual(out.revised[0].status, 'complete')
        self.assertEqual((r1['changed'], r1['n_changed_positions'], r1['n_invalid']), ('False', '0', '1'))

    def test_abort_on_reset_screen(self):
        env = self.env(BASELINE_KEYS, CONTINUE, _script('return'), _script('escape'))
        out = run_block_rankings(env, 0, 0, CONDITIONS)
        self.assertTrue(out.aborted)
        self.assertEqual(len(out.revised), 1)
        self.assertEqual([r['ranking_id'] for r in self.rows('rankings.csv')],
                         ['b0_baseline', 'b0_probe1_competence'])

    def test_group_b_order_saved_data(self):
        """First two blocks of group B (original 1 then 0), as the preview runs them."""
        one_block = [BASELINE_KEYS, CONTINUE, _script('return'), CONTINUE, CONTINUE, _script('return')]
        env = self.env(*(one_block * 2), group='B')
        for position, block_index in enumerate(block_order('B')[:2]):
            run_block_rankings(env, block_index, position, CONDITIONS)

        rows = self.rows('rankings.csv')
        self.assertEqual(len(rows), 6)
        self.assertEqual(_check(rows), [])
        recs = {r['ranking_id']: r for r in rows}
        self.assertEqual((recs['b1_baseline']['presentation_pos'], recs['b0_baseline']['presentation_pos']),
                         ('0', '1'))
        self.assertEqual({recs['b1_baseline']['domain'], recs['b1_probe1_competence']['domain']}, {'repairing'})
        self.assertEqual(recs['b1_probe1_competence']['change_domain'], 'repairing')
        self.assertEqual(recs['b1_baseline']['phase'], 'phase_2')
        with open(self.tmp / 'rankings' / 'b0_probe2_synergy.json', encoding='utf-8') as f:
            self.assertEqual(json.load(f)['record']['change_kind'], 'synergy')


if __name__ == '__main__':
    unittest.main()
