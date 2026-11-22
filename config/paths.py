"""
paths.py
--------
Every file-system location the task touches, anchored at the project root so
the experiment runs identically regardless of the current working directory.
"""

from pathlib import Path

ROOT_DIR     = Path(__file__).resolve().parents[1]
DATA_DIR     = ROOT_DIR / "data"
STIMULI_DIR  = ROOT_DIR / "stimuli"
TABLES_DIR   = STIMULI_DIR / "tables"
IMAGE_DIR    = STIMULI_DIR / "images"

MONKEY_IMAGE      = IMAGE_DIR / "monkey.png"
COMPETENCE_CSV    = TABLES_DIR / "competence_d3.csv"
SYNERGY_CSV       = TABLES_DIR / "synergy.csv"
SYNERGY_COLOR_CSV = TABLES_DIR / "synergy_color.csv"
FORCED_FIRST_CSV  = TABLES_DIR / "forced_first_schedule.csv"   # tools/make_forced_first_schedule.py


def domain_image(domain: str) -> str:
    return str(IMAGE_DIR / "domains" / f"{domain}.png")


def animal_image(animal: str) -> str:
    return str(IMAGE_DIR / "objectives" / f"{animal}.png")
