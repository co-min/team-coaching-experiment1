"""
estimate_writers.py
-------------------
Output file for the attribute estimate, next to the trial and ranking outputs.

    {subject_dir}/
        estimates.csv    ← one row per estimate question

Each row is appended the moment its question ends (confirmed, timed out, or
aborted with Esc), so everything answered so far is on disk even if the
session stops in the middle of a block.

Rows are plain dicts built by task/estimate/run.py (build_estimate_row).
Empty cells mean "not applicable": a synergy row has no domain / animal_id,
a competence row has no pair_id.

Block identity (same convention as rankings.csv)
    block_idx            original block ID (0–5): phase, animals, estimate type
    presentation_pos     where this participant saw the block (0-based; block number shown = pos + 1)
    counterbalance_group 'A' (odd subject ID) or 'B' (even)

response is 'low' / 'mid' / 'high' (Low / Medium / High on screen) and is only
filled when status is 'complete'; 'timeout' and 'aborted' rows leave it empty.
"""

from pathlib import Path
from typing import Any, Dict

from recording.ranking_writers import append_csv

ESTIMATE_FIELDS = [
    # who / which estimate
    "subject_id", "session_id", "counterbalance_group", "estimate_id", "block_idx", "presentation_pos",
    "phase", "block_type",
    "checkpoint", "trial_after", "estimate_type", "n_items",
    # which question
    "presentation_order", "domain", "animal_id", "animal_name", "pair_id", "pair_animals", "display_animals",
    # participant's answer
    "status", "response", "response_rt", "first_press_rt", "n_presses", "selection_history",
    "onset_global", "confirm_global", "key_backend",
    # ground truth (kept apart from the answer columns above)
    "true_attribute_value", "true_attribute_level", "correct",
    "timestamp",
]


def append_estimate_row(subject_dir: Path, row: Dict[str, Any]) -> None:
    """Append one question's row to {subject_dir}/estimates.csv (header written on first use)."""
    subject_dir.mkdir(parents=True, exist_ok=True)
    append_csv(subject_dir / "estimates.csv", ESTIMATE_FIELDS, [row])
