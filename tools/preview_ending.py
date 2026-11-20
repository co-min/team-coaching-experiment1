"""
Standalone preview of the ending (leaderboard) screen.

Usage (from the project root)
-----------------------------
    python -m tools.preview_ending                   # subject 000, score 750, 20분 30초
    python -m tools.preview_ending 002               # subject 변경
    python -m tools.preview_ending 002 980 600       # subject / cumulative_score / elapsed_seconds

Press [Space] to close, [Esc] to quit immediately.
"""
import sys

from psychopy import monitors, visual

from config.modes import get_config
from config.settings import BACKGROUND_COLOR, MISSION_MODE, WINDOW_SIZE
from task.screens.ending import run_ending


def _make_window() -> visual.Window:
    mon = monitors.Monitor("testMonitor")
    mon.setSizePix(WINDOW_SIZE)
    return visual.Window(size=WINDOW_SIZE, fullscr=False, color=BACKGROUND_COLOR,
                         units="pix", monitor=mon, allowGUI=True)


if __name__ == "__main__":
    args = sys.argv[1:]
    subject_id       = args[0]         if len(args) > 0 else "000"
    cumulative_score = float(args[1])  if len(args) > 1 else 750.0
    elapsed_seconds  = float(args[2])  if len(args) > 2 else 1230.0

    win = _make_window()
    run_ending(win, subject_id, cumulative_score,
               score_csv=get_config(MISSION_MODE).phase('phase_1').score_csv,
               elapsed_seconds=elapsed_seconds)
    win.close()
