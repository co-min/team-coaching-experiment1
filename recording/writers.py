"""
writers.py
----------
All per-subject output files.

Directory schema
----------------
data/
  sub-{subject_id}/
    session_metadata.json
    trials.csv            ← one row per trial (analysis convenience)
    frames.csv            ← one row per frame
    summary.json          ← recording/summary.py
    neon_event_log.xlsx   ← hardware/neon.py
    block_{block_i}/{phase}/{domain}/{stim_pair_id}/
        metadata.json     ← per-trial record (crash recovery)
        frame_log.csv
"""

import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from config.paths import DATA_DIR
from hardware.events import PHASE_INT, choice_trigger_code

_SLOT_NAMES: List[str] = ['up', 'down', 'right', 'left']


# ── paths ─────────────────────────────────────────────────────────────────────

def get_subject_dir(subject_id: str) -> Path:
    """Return  data/sub-{subject_id}/"""
    return DATA_DIR / f"sub-{subject_id}"


def build_trial_save_dir(subject_id: str, block_i: int, phase: str, domain: str,
                         stim_pair_id: str) -> Path:
    """e.g. data/sub-001/block_0/phase_1/cooking/block0_phase_1_t00/ (not created)"""
    return get_subject_dir(subject_id) / f"block_{block_i}" / phase / domain / stim_pair_id


def _ensure_subject_dir(subject_id: str) -> Path:
    d = get_subject_dir(subject_id)
    d.mkdir(parents=True, exist_ok=True)
    return d


def _write_json(path: Path, record: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(record, f, indent=2, ensure_ascii=False)


# ── session metadata ──────────────────────────────────────────────────────────

def save_session_metadata(
    subject_id: str,
    session_id: str,
    win_size: tuple,
    mission_mode: int,
    win_fullscr: bool,
    monitor_name: str,
    frame_rate: int,
    slot_info: Optional[Dict[str, Any]] = None,
    neon_recording_id: Optional[str] = None,
) -> Path:
    """Save one-time session-level metadata (ground-truth win.size + slot AOIs)."""
    record: Dict[str, Any] = {
        "subject_id":        subject_id,
        "session_id":        session_id,
        "timestamp":         datetime.now().isoformat(timespec='seconds'),
        "win_width":         int(win_size[0]),
        "win_height":        int(win_size[1]),
        "win_fullscr":       win_fullscr,
        "monitor_name":      monitor_name,
        "frame_rate":        frame_rate,
        "mission_mode":      mission_mode,
        "neon_recording_id": neon_recording_id,
    }
    if slot_info:
        record["slot_coords"]    = {k: [int(x), int(y)] for k, (x, y) in slot_info['slot_coords'].items()}
        record["animal_size_px"] = slot_info['animal_size_px']

    out_path = get_subject_dir(subject_id) / "session_metadata.json"
    _write_json(out_path, record)
    return out_path


# ── per-trial metadata ────────────────────────────────────────────────────────

def _trig_code(phase: str, animal: Optional[str], slot: int) -> Optional[int]:
    """Return the trigger code that was sent for this choice, or None if not applicable."""
    if animal is None:
        return None
    return choice_trigger_code(PHASE_INT.get(phase, 0), slot, animal)


def build_trial_record(
    subject_id: str,
    block_i: int,
    phase: str,
    domain: str,
    trial_id: int,
    stim_pair_id: str,
    char_order: List[str],
    char_code: Dict[str, str],
    result: Optional[Dict[str, Any]],
    feedback_score: float = 0,
    elapsed_time: Optional[float] = None,
    session_id: Optional[str] = None,
    neon_recording_id: Optional[str] = None,
    win_size: Optional[tuple] = None,
    slot_coords: Optional[Dict[str, Any]] = None,
    animal_size_px: Optional[int] = None,
) -> Dict[str, Any]:
    """Build and return the trial metadata dict (does not write to disk)."""
    layout = {slot: animal for slot, animal in zip(_SLOT_NAMES, char_order)}
    code_to_animal = {char_code[animal]: animal for animal in char_order}
    responded = result is not None
    c1 = result['choice1'] if responded else None
    c2 = result['choice2'] if responded else None
    c1_animal = code_to_animal.get(c1) if c1 else None
    c2_animal = code_to_animal.get(c2) if c2 else None
    return {
        "subject_id":        subject_id,
        "session_id":        session_id,
        "neon_recording_id": neon_recording_id,
        "block":             f"block_{block_i}",
        "phase":             phase,
        "domain":            domain,
        "trial_id":          trial_id,
        "stim_pair_id":      stim_pair_id,
        "trial_layout":      layout,
        "response_made":     responded,
        "choice1_code":      c1,
        "choice2_code":      c2,
        "choice1_animal":    c1_animal,
        "choice2_animal":    c2_animal,
        "trig_choice1":      _trig_code(phase, c1_animal, 1) if responded else None,
        "trig_choice2":      _trig_code(phase, c2_animal, 2) if responded else None,
        "rt_choice1":        round(result['rt1'], 4) if responded and result.get('rt1') is not None else None,
        "rt_choice2":        round(result['rt2'], 4) if responded and result.get('rt2') is not None else None,
        "feedback_score":    feedback_score if responded else None,
        "elapsed_time":      round(elapsed_time, 4) if elapsed_time is not None else None,
        "timestamp":         datetime.now().isoformat(timespec='seconds'),
        "win_size":          [int(v) for v in win_size] if win_size is not None else None,
        "slot_coords":       {k: [int(x), int(y)] for k, (x, y) in slot_coords.items()} if slot_coords else None,
        "animal_size_px":    animal_size_px,
    }


def save_trial_metadata(save_dir: Path, record: Dict[str, Any]) -> Path:
    out_path = save_dir / "metadata.json"
    _write_json(out_path, record)
    return out_path


# ── per-trial frame log ───────────────────────────────────────────────────────

_FRAME_LOG_FIELDS = [
    "frame_idx",
    "phase",
    "segment",        # "DOMAIN_ONSET" | "CHOICE1" | "CHOICE2" | "FEEDBACK" | "" — screen phase within trial
    "trial_id",
    "stim_pair_id",
    "elapsed_time",
    "global_time",
    "flip_time",
    "event_marker",   # "{SEGMENT}_onset" | "{SEGMENT}_response" | "{SEGMENT}_timeout" | ""
    "ttl_code",
]


def save_frame_log(rows: List[Dict], save_dir: Path) -> Path:
    """Write *rows* to  save_dir / frame_log.csv."""
    save_dir.mkdir(parents=True, exist_ok=True)
    out_path = save_dir / "frame_log.csv"
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=_FRAME_LOG_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    return out_path


# ── subject-level consolidated CSVs ───────────────────────────────────────────

# trial_layout is a nested dict in the JSON record; flatten it here.
_TRIAL_FIELDS = [
    "subject_id", "global_trial_id", "block_trial_id",
    "block", "phase", "domain", "trial_id", "stim_pair_id",
    "layout_up", "layout_down", "layout_right", "layout_left",
    "pos_up_x",    "pos_up_y",
    "pos_down_x",  "pos_down_y",
    "pos_right_x", "pos_right_y",
    "pos_left_x",  "pos_left_y",
    "animal_size_px",
    "win_width", "win_height",
    "response_made",
    "choice1_code", "choice2_code", "choice1_animal", "choice2_animal",
    "trig_choice1", "trig_choice2",
    "rt_choice1", "rt_choice2", "feedback_score", "elapsed_time", "timestamp",
]

_FRAME_FIELDS = [
    "subject_id",
    "frame_idx", "phase", "trial_id", "stim_pair_id",
    "elapsed_time", "global_time", "flip_time", "event_marker",
]


def append_trial_row(subject_id: str, record: Dict[str, Any]) -> None:
    """Append one trial's metadata to data/sub-{id}/trials.csv."""
    csv_path = _ensure_subject_dir(subject_id) / "trials.csv"
    write_header = not csv_path.exists()

    global_trial_id = 0
    block_trial_id = 0
    current_block = record.get("block")
    if csv_path.exists():
        with open(csv_path, "r", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                global_trial_id += 1
                if row.get("block") == current_block:
                    block_trial_id += 1

    layout       = record.get("trial_layout", {})
    slot_coords  = record.get("slot_coords") or {}
    win_size_raw = record.get("win_size")

    flat = {k: v for k, v in record.items() if k not in ("trial_layout", "slot_coords", "win_size")}
    flat["global_trial_id"] = global_trial_id
    flat["block_trial_id"]  = block_trial_id
    for slot in _SLOT_NAMES:
        flat[f"layout_{slot}"] = layout.get(slot)
        pos = slot_coords.get(slot)
        flat[f"pos_{slot}_x"] = pos[0] if pos is not None else None
        flat[f"pos_{slot}_y"] = pos[1] if pos is not None else None
    if win_size_raw:
        flat["win_width"]  = win_size_raw[0]
        flat["win_height"] = win_size_raw[1]

    with open(csv_path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=_TRIAL_FIELDS, extrasaction="ignore")
        if write_header:
            writer.writeheader()
        writer.writerow(flat)


def append_frame_rows(subject_id: str, rows: List[Dict[str, Any]]) -> None:
    """Append frame-log rows to data/sub-{id}/frames.csv."""
    if not rows:
        return
    csv_path = _ensure_subject_dir(subject_id) / "frames.csv"
    write_header = not csv_path.exists()

    with open(csv_path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=_FRAME_FIELDS, extrasaction="ignore")
        if write_header:
            writer.writeheader()
        for row in rows:
            writer.writerow({"subject_id": subject_id, **row})
