"""
ranking_writers.py
------------------
Output files for the ranking assessments, next to the trial outputs.

    {subject_dir}/
        rankings.csv          ← one row per ranking screen (final result)
        ranking_events.csv    ← one row per event (onset, every key press, timeout)
        rankings/{ranking_id}.json   ← full record + events (crash recovery)

Records are plain dicts built by task/ranking/record.py.
"""

import csv
import json
from pathlib import Path
from typing import Any, Dict, List

MAX_ITEMS = 6

RANKING_FIELDS = [
    "subject_id", "session_id", "counterbalance_group", "ranking_id", "ranking_type", "n_items",
    "block_index", "presentation_pos", "phase", "block_type", "animal_set", "role_map",
    "domain", "baseline_id", "probe_order", "probe_pos",
    "change_kind", "change_roles", "change_animals", "change_domain", "change_value", "change_level",
    "change_onset", "change_rt", "reset_onset", "reset_rt",
    "status", "key_backend", "time_limit",
    "onset_global", "first_key_rt", "confirm_rt", "confirm_global", "total_rt",
    "n_keypresses", "n_unmapped", "n_invalid", "n_selections", "n_undos", "n_moves", "n_relocations",
    "changed", "n_changed_positions", "kendall_from_initial",
    "display_order", "display_order_animals",
    "initial_ranking", "initial_ranking_animals",
    "final_ranking", "final_ranking_animals",
    *[f"rank{i}" for i in range(1, MAX_ITEMS + 1)],
    "true_values", "true_order", "spearman_true",
    "timestamp",
]

EVENT_FIELDS = [
    "subject_id", "session_id", "counterbalance_group", "ranking_id", "ranking_type",
    "block_index", "presentation_pos", "baseline_id", "probe_pos",
    "event_idx", "event", "key", "action", "rt", "t_global",
    "item", "item_animals", "rank_pos", "from_pos", "to_pos", "ranking_state", "detail",
]


def _append_csv(path: Path, fields: List[str], rows: List[Dict[str, Any]]) -> None:
    write_header = not path.exists()
    with open(path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        if write_header:
            writer.writeheader()
        writer.writerows(rows)


def save_ranking(subject_dir: Path, record: Dict[str, Any], events: List[Dict[str, Any]]) -> None:
    """Write one ranking: JSON first (complete), then the two consolidated CSVs."""
    subject_dir.mkdir(parents=True, exist_ok=True)
    json_path = subject_dir / "rankings" / f"{record['ranking_id']}.json"
    json_path.parent.mkdir(parents=True, exist_ok=True)
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump({"record": record, "events": events}, f, indent=2, ensure_ascii=False)
    _append_csv(subject_dir / "rankings.csv", RANKING_FIELDS, [record])
    _append_csv(subject_dir / "ranking_events.csv", EVENT_FIELDS, events)
