"""
record.py
---------
RankingResult → the flat dicts written by recording/ranking_writers.py.
Ground truth (true values, Spearman) is computed here from the original
attributes, or from the counterfactual attributes for revised rankings.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from config import ranking as R
from recording.ranking_writers import MAX_ITEMS
from task.forced_first import BLOCK_TYPE
from task.ranking.flow import COMPLETE, RankingResult
from task.ranking.items import (
    ATTRIBUTE_ITEM_KIND, Attributes, kendall_distance, spearman, true_values,
)


def _keys(items) -> str:
    return '|'.join(it.key for it in items)


def _labels(items) -> str:
    return '|'.join(it.label for it in items)


def _count(events, *names) -> int:
    return sum(1 for e in events if e['event'] in names)


def build_ranking_record(result: RankingResult, attrs: Attributes, subject_id: str,
                         session_id: Optional[str] = None, change_level: Optional[str] = None
                         ) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """Return (ranking record, event rows) for one ranking screen."""
    spec, ev = result.spec, result.events
    truth_attrs = attrs.with_change(spec.change) if spec.change else attrs
    truth = true_values(truth_attrs, spec.attribute, result.display_order, spec.domain)
    final_keys = [it.key for it in result.final]
    complete = result.status == COMPLETE
    presses = [e for e in ev if e['key'] is not None]
    change = spec.change
    initial_keys = [it.key for it in result.initial]

    record: Dict[str, Any] = {
        "subject_id":   subject_id,
        "session_id":   session_id,
        "ranking_id":   spec.ranking_id,
        "ranking_type": spec.ranking_type,
        "attribute":    spec.attribute,
        "item_kind":    ATTRIBUTE_ITEM_KIND[spec.attribute],
        "n_items":      len(result.display_order),
        "block_index":  spec.block_index,
        "phase":        spec.phase,
        "block_type":   BLOCK_TYPE.get(spec.phase, spec.phase),
        "animal_set":   ','.join(spec.group),
        "role_map":     ';'.join(f"{r}={a}" for r, a in sorted(spec.roles.items())),
        "domain":       spec.domain,
        "after_trial":  spec.after_trial,
        "probe_id":     spec.probe_id,
        "baseline_id":  spec.baseline_id,
        "change_kind":    change.kind if change else None,
        "change_roles":   '+'.join(change.roles) if change else None,
        "change_animals": '+'.join(spec.roles[r] for r in change.roles) if change else None,
        "change_domain":  change.domain if change else None,
        "change_value":   change.value if change else None,
        "change_level":   change_level,
        "change_onset":   result.change_onset_global,
        "change_rt":      result.change_rt,
        "status":       result.status,
        "key_backend":  result.key_backend,
        "time_limit":   R.RANKING_MAX_TIME,
        "onset_global": None if result.onset_global is None else round(result.onset_global, 5),
        "first_key_rt": presses[0]['rt'] if presses else None,
        "confirm_rt":     result.end_rt if complete else None,
        "confirm_global": (round(result.onset_global + result.end_rt, 5)
                           if complete and result.onset_global is not None else None),
        "total_rt":     result.end_rt,
        "n_keypresses": len(presses),
        "n_unmapped":   _count(ev, 'unmapped'),
        "n_invalid":    _count(ev, 'invalid'),
        "n_selections": _count(ev, 'select'),
        "n_undos":      _count(ev, 'undo'),
        "n_moves":      _count(ev, 'move'),
        "n_relocations": result.n_relocations,
        "changed":             (final_keys != initial_keys) if result.initial else None,
        "n_changed_positions": (sum(a != b for a, b in zip(final_keys, initial_keys))
                                if result.initial else None),
        "kendall_from_initial": kendall_distance(initial_keys, final_keys) if result.initial else None,
        "display_order":           _keys(result.display_order),
        "display_order_animals":   _labels(result.display_order),
        "initial_ranking":         _keys(result.initial) or None,
        "initial_ranking_animals": _labels(result.initial) or None,
        "final_ranking":           _keys(result.final),
        "final_ranking_animals":   _labels(result.final),
        **{f"rank{i + 1}": (final_keys[i] if i < len(final_keys) else None) for i in range(MAX_ITEMS)},
        "true_values":   ';'.join(f"{k}:{v}" for k, v in truth.items()),
        "true_order":    '|'.join(sorted(truth, key=lambda k: -truth[k])),
        "spearman_true": spearman(final_keys, truth) if complete else None,
        "timestamp":     datetime.now().isoformat(timespec='seconds'),
    }
    common = {"subject_id": subject_id, "session_id": session_id, "ranking_id": spec.ranking_id,
              "ranking_type": spec.ranking_type, "block_index": spec.block_index, "probe_id": spec.probe_id}
    return record, [{**common, **e} for e in ev]
