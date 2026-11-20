"""
settings.py
-----------
Experiment-wide constants only. No file I/O happens at import time.

Mode-dependent values (CSV paths, domains, trial counts, block order) live in
config/modes.py; select the active preset with MISSION_MODE below.
"""

import platform

# ─── Mode / language ──────────────────────────────────────────────────────────
# See config/modes.py for what each mode means.
MISSION_MODE = 4

# True  : all participant-facing text is shown in English (see config/strings.py)
# False : all participant-facing text is shown in Korean
MODE_ENG = False

# DOMAIN_ORDER: trial 내 domain 제시 순서
#   'random'     — seed 고정 랜덤 셔플
#   'sequential' — DOMAINS 순서대로 묶음
DOMAIN_ORDER  = 'random'
SCHEDULE_SEED = 42

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

# ─── Practice ────────────────────────────────────────────────────────────────
PRACTICE_MODE         = False   # True: 본 실험 전 연습 세션 실행 / False: 건너뜀
PRACTICE_DOMAINS      = ['cooking', 'repairing']
PRACTICE_P1_TRIALS    = 4       # Phase 1 연습 총 trial 수
PRACTICE_P2_TRIALS    = 4       # Phase 2 연습 총 trial 수
PRACTICE_END_DURATION = 3.0

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
