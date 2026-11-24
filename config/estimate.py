"""
estimate.py
-----------
Constants for the attribute estimate (High / Medium / Low judgments of the
hidden attribute, asked in the middle and at the end of each block's learning trials).

    competence-visible block (phase_1) → Synergy estimate:    S(i, j) of every pair
    synergy-visible block    (phase_2) → Competence estimate: C_i(d) of every animal, one at a time

Participant-facing text lives in config/strings.py ("estimate_*").
"""

from config.settings import N_TRIALS_PER_BLOCK

# ─── When ────────────────────────────────────────────────────────────────────
# Learning-trial number (1-based) after which an estimate runs → checkpoint name.
# The end estimate is tied to the block length so it is always after the last trial.
# An empty dict switches the estimate off.
ESTIMATE_CHECKPOINTS = {
    7:                  'middle',
    N_TRIALS_PER_BLOCK: 'end',
}

# ─── What ────────────────────────────────────────────────────────────────────
# Domains asked in the competence estimate, each with all four animals.
# All three = 12 questions per checkpoint. Remove a domain to shorten it.
# Middle and end use the same domains, so answers can be compared directly.
COMPETENCE_ESTIMATE_DOMAINS = ('cooking', 'repairing', 'tennis')

# ─── Input ───────────────────────────────────────────────────────────────────
# Same convention as the learning trials: an arrow key picks an option directly,
# Space confirms. Keys are read through task.ranking.inputs.KeySource (precise RTs).
#   low / mid / high : highlight that response (can be changed freely before confirming)
#   confirm          : accepted only once a response is highlighted
#   quit             : abort the session (the current question is saved with status 'aborted')
ESTIMATE_KEYS = {
    'low':     ['left'],
    'mid':     ['down'],
    'high':    ['right'],
    'confirm': ['space'],
    'quit':    ['escape'],
}

# ─── Timing ──────────────────────────────────────────────────────────────────
ESTIMATE_MAX_TIME  = None   # seconds per question; None = no deadline. A timeout is saved and skipped.
CONFIRM_FEEDBACK_S = 0.4    # the confirmed response stays on screen this long (no input)

# ─── Colours ─────────────────────────────────────────────────────────────────
# Deliberately not red / yellow / green: those are the task's low / mid / high
# colour cues, and the response buttons must not hint at a "correct" level.
BUTTON_COLOR    = '#3a3a3a'
BUTTON_LINE     = '#555555'
SELECTED_COLOR  = '#00d9ff'   # same highlight as the trial arrow keys (task/keyboard.py)
DIM_TEXT_COLOR  = '#9e9e9e'
