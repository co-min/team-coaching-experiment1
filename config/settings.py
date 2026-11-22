"""
settings.py
-----------
Experiment-wide constants only. No file I/O happens at import time.

Stimulus table locations live in config/paths.py.
"""

import platform

# ─── Task design ──────────────────────────────────────────────────────────────
DOMAINS            = ['cooking', 'repairing', 'tennis']
N_TRIALS_PER_BLOCK = 15
BLOCK_PHASES       = ['phase_1', 'phase_2'] * 3     # one animal group per block

# Competence level → border colour (low ≤3 / middle ≤6 / high)
COMPETENCE_COLOR = {1: '#F44336', 2: '#FFEB3B', 3: '#4CAF50'}

# ─── Language ─────────────────────────────────────────────────────────────────
# True  : all participant-facing text is shown in English (see config/strings.py)
# False : all participant-facing text is shown in Korean
MODE_ENG = False

# DOMAIN_ORDER: trial 내 domain 제시 순서
#   'random'     — seed 고정 랜덤 셔플
#   'sequential' — DOMAINS 순서대로 묶음
DOMAIN_ORDER  = 'random'
SCHEDULE_SEED = 42

# FIRST_CHOICE_MODE: 첫 번째 동물 선택 방식
#   'free'   — 참가자가 두 마리를 순서대로 직접 선택 (기존 방식)
#   'forced' — 첫 번째 동물은 stimuli/tables/forced_first_schedule.csv 에 따라
#              자동 배정 (모든 참가자 동일), 참가자는 두 번째 동물만 선택
# The forced CSV is built for the domain order produced by DOMAIN_ORDER /
# SCHEDULE_SEED below; changing either requires regenerating it
# (python -m tools.make_forced_first_schedule). main.py refuses to start otherwise.
FIRST_CHOICE_MODE = 'forced'

# Blocks (1-indexed) that show a break screen before the phase instruction
BREAK_BEFORE_BLOCKS = {3, 5}

# ─── Window ───────────────────────────────────────────────────────────────────
WINDOW_SIZE      = (1470, 956)   # TODO: adjust to your display
WINDOW_UNITS     = "pix"
WINDOW_FULLSCR   = True          # Set True for actual experiment
BACKGROUND_COLOR = "#2b2b2b"
MONITOR_NAME     = "testMonitor" # TODO: calibrate your monitor
SCREEN_NUMBER    = 1

# ─── Timing ──────────────────────────────────────────────────────────────────
MAX_RESPONSE_TIME     = 300.0    # seconds; None = unlimited
FRAME_RATE            = 60       # Hz – recorded in session metadata
DOMAIN_ONSET_DURATION = 0.7      # seconds domain image is shown before choices appear
FB_TIME               = 3.5      # feedback screen duration (seconds)

# Gaussian ITI (seconds)
ITI_MEAN = 1.2
ITI_SD   = 0.3
ITI_MIN  = 0.6
ITI_MAX  = 1.8

# ─── Text ────────────────────────────────────────────────────────────────────
FONT = "AppleGothic" if platform.system() == "Darwin" else "Malgun Gothic"

# ─── Arrow keys ──────────────────────────────────────────────────────────────
ARROW_OFFSET = 70
ARROW_RADIUS = 40

# ─── LabJack ─────────────────────────────────────────────────────────────────
LABJACK_DEVICE = "T4"

# ─── Neon eyetracker ─────────────────────────────────────────────────────────
# Set USE_NEON=False to run without the eyetracker (NullNeonClient is used).
USE_NEON = False

NEON_DISCOVERY_TIMEOUT_S      = 10.0  # seconds to search for Companion device
NEON_RETRY_INTERVAL_S         = 1.0   # seconds between failed send retries
NEON_SHUTDOWN_FLUSH_TIMEOUT_S = 5.0   # seconds to wait for queue drain on exit

# AprilTag positions and size in PsychoPy 'height' units.
# height=1.0 spans the full screen height; for 1470×956 the X range is ≈ ±0.77.
NEON_APRILTAG_SIZE = 0.08
NEON_APRILTAG_POSITIONS = (
    (-0.70,  0.43),   # top-left
    ( 0.70,  0.43),   # top-right
    (-0.74,  0.00),   # mid-left
    ( 0.74,  0.00),   # mid-right
    (-0.70, -0.43),   # bottom-left
    ( 0.70, -0.43),   # bottom-right
)
