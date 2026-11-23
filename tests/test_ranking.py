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
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from psychopy import core, visual

from config import ranking as R
from config import settings as S
from recording.ranking_writers import EVENT_FIELDS, RANKING_FIELDS
from recording.stimuli_loader import load_stimuli
from task.ranking import flow
from task.ranking.assessments import (
    Probe, ProbeCondition, RankingEnv, _shuffled, _starting_order_for_revision, change_level,
    run_counterfactual_probe,
)
from task.ranking.inputs import ScriptedSource, action_map
from task.ranking.items import (
    Change, RankItem, RankingSpec, _average_ranks, kendall_distance, load_attributes, pair_items, spearman,
    true_values,
)
from task.ranking.record import build_ranking_record
from task.ranking.schedule import ranking_domain, ranking_domain_problems, saved_ranking_problems
from task.ranking.state import RevisedRanking, SequentialRanking

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
        spec = RankingSpec('b0_p1_revised', 'counterfactual', 0, 'phase_1', tuple(GROUP0),
                           {STIM.char_code[a]: a for a in GROUP0}, domain='cooking', probe_id=1,
                           change=Change('competence', ('C',), 8.5, domain='cooking'))
        events = [{'event_idx': 0, 'event': 'onset', 'key': None, 'rt': 0.0},
                  {'event_idx': 1, 'event': 'move', 'key': 'down', 'rt': 0.25}]
        return flow.RankingResult(spec=spec, display_order=items, initial=list(initial), final=items[::-1],
                                  status=status, onset_global=1.0, end_rt=0.5, events=events)

    def test_record_schema_matches_writer_columns(self):
        record, events = build_ranking_record(self._result(), ATTRS, 'T01', 'S', 'high')
        self.assertEqual(list(record), RANKING_FIELDS)
        self.assertEqual(list(events[0])[:6], EVENT_FIELDS[:6])
        self.assertEqual((record['confirm_global'], record['first_key_rt'], record['n_moves']), (1.5, 0.25, 1))
        self.assertIsNone(record['changed'])                    # no initial ranking
        timed_out, _ = build_ranking_record(self._result('timeout', initial=self._result().final), ATTRS, 'T01')
        self.assertEqual((timed_out['confirm_rt'], timed_out['spearman_true'], timed_out['changed']),
                         (None, None, False))

    def test_timed_out_baseline_is_completed_in_display_order(self):
        items = _items(4)
        baseline = flow.RankingResult(spec=None, display_order=items, initial=[], final=[items[2]],
                                      status='timeout')
        self.assertEqual(_starting_order_for_revision(baseline), [items[2], items[0], items[1], items[3]])

    def test_display_order_is_reproducible(self):
        env = RankingEnv(None, None, None, STIM, ATTRS, 'T01', Path('.'))
        spec = RankingSpec('b0_p1_baseline', 'performance', 0, 'phase_1', tuple(GROUP0), {}, domain='cooking')
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


class TestKeyMap(unittest.TestCase):
    def test_confirm_must_be_distinct(self):
        with self.assertRaises(ValueError):
            action_map({**R.RANKING_KEYS, 'confirm': ['space']})
        with self.assertRaises(ValueError):
            action_map({'up': ['1'], 'down': ['1']})
        self.assertEqual(action_map()['return'], 'confirm')


# ── screen tests ──────────────────────────────────────────────────────────────

def _script(*keys, t0=0.1, dt=0.05):
    """[(rt, key), ...] at t0, t0+dt, ..."""
    return [(round(t0 + i * dt, 3), k) for i, k in enumerate(keys)]


SCHEDULE = R.PERFORMANCE_RANKING_DOMAINS
CONDITIONS = (ProbeCondition(1, 'competence', ('C',), 8.5), ProbeCondition(2, 'synergy', ('B', 'C'), 1.4))


def _problems(schedule):
    return ranking_domain_problems(schedule, S.BLOCK_PHASES, S.DOMAINS)


def _saved_row(block_index, ranking_id, ranking_type, baseline_id='', change=None):
    """One rankings.csv row as csv.DictReader returns it: every value a string, None as ''."""
    change_kind = ''
    change_domain = ''
    if change is not None:
        change_kind = change.kind
        if change.domain is not None:
            change_domain = change.domain
    return {
        'block_index':   str(block_index),
        'phase':         S.BLOCK_PHASES[block_index],
        'domain':        SCHEDULE[block_index],
        'ranking_id':    ranking_id,
        'ranking_type':  ranking_type,
        'baseline_id':   baseline_id,
        'change_kind':   change_kind,
        'change_domain': change_domain,
    }


def _saved_rows():
    """Rows for every block × CONDITIONS (baseline then revised), as the preview would save them."""
    rows = []
    for block_index in range(len(SCHEDULE)):
        for condition in CONDITIONS:
            probe = condition.for_domain(SCHEDULE[block_index])
            baseline_id = f"b{block_index}_p{probe.probe_id}_baseline"
            revised_id = f"b{block_index}_p{probe.probe_id}_revised"
            rows.append(_saved_row(block_index, baseline_id, 'performance'))
            rows.append(_saved_row(block_index, revised_id, 'counterfactual', baseline_id, probe.change))
    return rows


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


class TestProbeBinding(unittest.TestCase):
    def test_competence_change_uses_ranking_domain(self):
        for d in S.DOMAINS:
            probe = CONDITIONS[0].for_domain(d)
            self.assertEqual((probe.domain, probe.change.domain), (d, d))
            changed = ATTRS.with_change(probe.change)
            self.assertEqual(changed.competence['C'][d], 8.5)
            for other in set(S.DOMAINS) - {d}:
                self.assertEqual(changed.competence['C'][other], ATTRS.competence['C'][other])

    def test_synergy_change_has_no_domain(self):
        probe = CONDITIONS[1].for_domain('tennis')
        self.assertEqual((probe.domain, probe.change.domain), ('tennis', None))
        self.assertEqual(ATTRS.with_change(probe.change).competence, ATTRS.competence)

    def test_mismatched_competence_domain_rejected(self):
        with self.assertRaises(ValueError):
            Probe(1, 'tennis', Change('competence', ('C',), 8.5, domain='cooking'))

    def test_no_carryover_across_blocks(self):
        # every block's probes start from the original attributes
        original_competence = copy.deepcopy(ATTRS.competence)
        original_synergy = copy.deepcopy(ATTRS.synergy)
        for domain in SCHEDULE:
            for condition in CONDITIONS:
                ATTRS.with_change(condition.for_domain(domain).change)
        self.assertEqual(ATTRS.competence, original_competence)
        self.assertEqual(ATTRS.synergy, original_synergy)
        a = ATTRS.with_change(CONDITIONS[1].for_domain('cooking').change)
        self.assertEqual(a.competence['C']['cooking'], 2.2)       # synergy probe does not see the competence one


class TestSavedRankingCheck(unittest.TestCase):
    def test_complete_schedule_passes(self):
        self.assertEqual(saved_ranking_problems(_saved_rows(), SCHEDULE, S.BLOCK_PHASES), [])

    def test_partial_run_checks_rows_only(self):
        rows = [r for r in _saved_rows() if r['block_index'] in ('0', '1')]
        self.assertEqual(saved_ranking_problems(rows, SCHEDULE, S.BLOCK_PHASES), [])

    def test_violations_reported(self):
        def problems(mutate):
            rows = _saved_rows()
            mutate(rows)
            return saved_ranking_problems(rows, SCHEDULE, S.BLOCK_PHASES)

        def wrong_block_domain(rows):
            for r in rows:
                if r['block_index'] == '3':
                    r['domain'] = 'tennis'

        def revised_other_domain(rows):
            rows[1]['domain'] = 'tennis'

        def competence_other_domain(rows):
            rows[1]['change_domain'] = 'tennis'

        def synergy_with_domain(rows):
            rows[3]['change_domain'] = 'cooking'

        def wrong_phase(rows):
            rows[0]['phase'] = 'phase_2'

        for mutate in (wrong_block_domain, revised_other_domain, competence_other_domain,
                       synergy_with_domain, wrong_phase):
            self.assertNotEqual(problems(mutate), [], mutate.__name__)


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

    def env(self, *scripts):
        return RankingEnv(win=self.win, global_clock=core.Clock(), source=ScriptedSource(scripts),
                          stim=STIM, attrs=ATTRS, subject_id='T01', subject_dir=self.tmp, session_id='S')

    def rows(self, name):
        with open(self.tmp / name, encoding='utf-8') as f:
            return list(csv.DictReader(f))


class TestBaselineScreen(ScreenBase):
    """The sequential baseline ranking; the change screen is escaped so only the baseline runs."""
    PROBE = Probe(1, 'cooking', Change('competence', ('C',), 8.5, domain='cooking'))

    def run_baseline(self, *baseline_keys):
        env = self.env(_script(*baseline_keys), _script('escape'))
        results = run_counterfactual_probe(env, 0, 'phase_1', self.PROBE)
        self.assertEqual(len(results), 1)
        return results[0]

    def test_baseline_ranking_saved(self):
        # 6 pairs: place slot 0, then the next available each time; one undo + re-place; confirm.
        keys = ['space', 'space', 'backspace', 'space', 'x', 'return', 'space', 'space', 'space', 'space',
                'return']
        res = self.run_baseline(*keys)
        self.assertEqual(res.status, 'complete')

        rec = self.rows('rankings.csv')[0]
        self.assertEqual((rec['ranking_type'], rec['domain'], rec['probe_id']), ('performance', 'cooking', '1'))
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
        presses = [e for e in ev if e['key']]
        self.assertEqual([e['key'] for e in presses], keys)
        onset = float(rec['onset_global'])
        for e, (t, _) in zip(presses, _script(*keys)):
            self.assertAlmostEqual(float(e['rt']), t, places=4)
            self.assertAlmostEqual(float(e['t_global']), onset + t, places=4)
        selects = [e for e in ev if e['event'] == 'select']
        self.assertEqual([e['rank_pos'] for e in selects], ['1', '2', '2', '3', '4', '5', '6'])
        self.assertTrue((self.tmp / 'rankings' / 'b0_p1_baseline.json').exists())

    def test_abort_saves_partial(self):
        res = self.run_baseline('space', 'escape')
        self.assertTrue(res.aborted)
        rec = self.rows('rankings.csv')[0]
        self.assertEqual(rec['status'], 'aborted')
        self.assertEqual(len(rec['final_ranking'].split('|')), 1)
        self.assertEqual(rec['confirm_rt'], '')

    def test_timeout(self):
        with mock.patch.object(R, 'RANKING_MAX_TIME', 0.3):
            res = self.run_baseline('space')
        self.assertEqual(res.status, 'timeout')
        self.assertEqual(self.rows('rankings.csv')[0]['status'], 'timeout')
        self.assertEqual(self.rows('ranking_events.csv')[-1]['event'], 'timeout')


class TestCounterfactualScreen(ScreenBase):
    PROBE = Probe(1, 'cooking', Change('competence', ('C',), 8.5, domain='cooking'))

    def test_probe_flow(self):
        baseline = _script(*(['space'] * 6), 'return')
        change = _script('space', t0=0.2)
        # move the 2nd team to the top, then submit
        revised = _script('down', 'space', 'up', 'space', 'return')
        env = self.env(baseline, change, revised)
        base, rev = run_counterfactual_probe(env, 0, 'phase_1', self.PROBE)

        self.assertEqual(rev.initial, base.final)
        b, r = self.rows('rankings.csv')
        self.assertEqual((b['ranking_type'], r['ranking_type']), ('performance', 'counterfactual'))
        self.assertEqual(r['baseline_id'], b['ranking_id'])
        self.assertEqual(r['initial_ranking'], b['final_ranking'])
        bf = b['final_ranking'].split('|')
        self.assertEqual(r['final_ranking'].split('|'), [bf[1], bf[0]] + bf[2:])
        self.assertEqual((r['changed'], r['n_moves'], r['n_relocations'], r['kendall_from_initial']),
                         ('True', '1', '1', '1'))
        self.assertEqual((r['change_kind'], r['change_roles'], r['change_level']), ('competence', 'C', 'high'))
        self.assertEqual(r['change_animals'], STIM.animal_groups[0][2])
        self.assertAlmostEqual(float(r['change_rt']), 0.2, places=4)

        # ground truth: baseline vs counterfactual attributes, both from the originals
        items = pair_items(GROUP0, STIM.char_code)
        base_truth = true_values(ATTRS, items, 'cooking')
        cf_truth = true_values(ATTRS.with_change(self.PROBE.change), items, 'cooking')
        self.assertIn(f"A+C:{cf_truth['A+C']}", r['true_values'])
        self.assertIn(f"A+C:{base_truth['A+C']}", b['true_values'])
        self.assertEqual(r['true_order'].split('|')[0], 'A+C')

        moves = [e for e in self.rows('ranking_events.csv') if e['ranking_id'] == r['ranking_id']]
        self.assertEqual([e['event'] for e in moves],
                         ['onset', 'cursor', 'pick_up', 'move', 'put_down', 'confirm'])

    def test_unchanged_submission_and_confirm_while_holding(self):
        baseline = _script(*(['space'] * 6), 'return')
        revised = _script('space', 'return', 'space', 'return')   # hold → confirm refused → drop → submit
        env = self.env(baseline, _script('space'), revised)
        _, rev = run_counterfactual_probe(env, 0, 'phase_1', self.PROBE)
        r = self.rows('rankings.csv')[1]
        self.assertEqual(rev.status, 'complete')
        self.assertEqual((r['changed'], r['n_changed_positions'], r['n_invalid']), ('False', '0', '1'))

    def test_second_probe_starts_from_original_attributes(self):
        env = self.env(_script(*(['space'] * 6), 'return'), _script('space'), _script('return'),
                       _script(*(['space'] * 6), 'return'), _script('space'), _script('return'))
        run_counterfactual_probe(env, 0, 'phase_1', self.PROBE)
        run_counterfactual_probe(env, 0, 'phase_1', Probe(2, 'cooking', Change('synergy', ('B', 'C'), 1.4)))
        recs = {r['ranking_id']: r for r in self.rows('rankings.csv')}
        self.assertEqual(recs['b0_p1_baseline']['true_values'], recs['b0_p2_baseline']['true_values'])
        expected = ATTRS.with_change(Change('synergy', ('B', 'C'), 1.4)).performance(('A', 'C'), 'cooking')
        self.assertIn(f"A+C:{round(expected, 4)}", recs['b0_p2_revised']['true_values'])   # C not boosted
        with open(self.tmp / 'rankings' / 'b0_p2_revised.json', encoding='utf-8') as f:
            self.assertEqual(json.load(f)['record']['change_kind'], 'synergy')

    def test_scheduled_blocks_saved_data(self):
        """Blocks 1 and 2 with the scheduled domains, as the preview runs them; saved rows pass the check."""
        blocks = (1, 2)
        one_probe = [_script(*(['space'] * 6), 'return'), _script('space'), _script('return')]
        env = self.env(*(one_probe * len(CONDITIONS) * len(blocks)))
        for b in blocks:
            for cond in CONDITIONS:
                run_counterfactual_probe(env, b, S.BLOCK_PHASES[b], cond.for_domain(ranking_domain(b)))

        rows = self.rows('rankings.csv')
        self.assertEqual(len(rows), 2 * len(CONDITIONS) * len(blocks))
        self.assertEqual(saved_ranking_problems(rows, SCHEDULE, S.BLOCK_PHASES), [])
        recs = {r['ranking_id']: r for r in rows}
        self.assertEqual({recs['b1_p1_baseline']['domain'], recs['b1_p1_revised']['domain']}, {'repairing'})
        self.assertEqual(recs['b1_p1_revised']['change_domain'], 'repairing')
        self.assertEqual((recs['b2_p2_revised']['domain'], recs['b2_p2_revised']['change_domain']), ('tennis', ''))
        # truth for the tennis competence probe: only C's tennis skill changed
        items = pair_items(STIM.animal_groups[2], STIM.char_code)
        cf = true_values(ATTRS.with_change(CONDITIONS[0].for_domain('tennis').change), items, 'tennis')
        self.assertIn(f"A+C:{cf['A+C']}", recs['b2_p1_revised']['true_values'])


if __name__ == '__main__':
    unittest.main()
