"""
appraisal_writers.py
--------------------
Output file for the attribute appraisal, next to the trial and ranking outputs.

    {subject_dir}/
        appraisals.csv   ← one row per appraisal question

Each row is appended the moment its question ends (confirmed, timed out, or
aborted with Esc), so everything answered so far is on disk even if the
session stops in the middle of a block.

Rows are plain dicts built by task/appraisal/run.py (build_appraisal_row).
Empty cells mean "not applicable": a synergy row has no domain / animal_id,
a competence row has no pair_id.
"""

from pathlib import Path
from typing import Any, Dict

from recording.ranking_writers import append_csv

APPRAISAL_FIELDS = [
    # who / which appraisal
    "subject_id", "session_id", "appraisal_id", "block_idx", "phase", "block_type",
    "checkpoint", "trial_after", "appraisal_type", "n_items",
    # which question
    "presentation_order", "domain", "animal_id", "animal_name", "pair_id", "pair_animals", "display_animals",
    # participant's answer
    "status", "response", "response_rt", "first_press_rt", "n_presses", "selection_history",
    "onset_global", "confirm_global", "key_backend",
    # ground truth (kept apart from the answer columns above)
    "true_attribute_value", "true_attribute_level", "correct",
    "timestamp",
]


def append_appraisal_row(subject_dir: Path, row: Dict[str, Any]) -> None:
    """Append one question's row to {subject_dir}/appraisals.csv (header written on first use)."""
    subject_dir.mkdir(parents=True, exist_ok=True)
    append_csv(subject_dir / "appraisals.csv", APPRAISAL_FIELDS, [row])
