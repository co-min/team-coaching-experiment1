"""
ranking.py
----------
Constants for the ranking assessments (performance baseline, counterfactual
revision). Kept apart from settings.py until the ranking flow is integrated
into the block loop.
"""

# ─── Performance ranking domain schedule ─────────────────────────────────────
# Domain of each block's performance ranking (baseline and revised), block 0 first.
# Fixed for every participant. Each domain appears once in a competence-visible
# (phase_1) block and once in a synergy-visible (phase_2) block, three blocks
# apart. Checked by task.ranking.schedule.ranking_domain_problems.
# Counterfactual probe conditions are defined separately and bound to these
# domains at run time (task.ranking.assessments.ProbeCondition).
PERFORMANCE_RANKING_DOMAINS = ('cooking', 'repairing', 'tennis', 'cooking', 'repairing', 'tennis')

# ─── Input ───────────────────────────────────────────────────────────────────
# Logical action → keys. Ranking screens only ever see actions, so an MRI
# response box can be swapped in by editing this map (or replacing KeySource).
#   up / down : move the cursor (revised ranking, while holding: move the item)
#   select    : sequential — place the item at the next rank
#               revised    — pick up / put down the item under the cursor
#   undo      : sequential — take back the last placed item
#               revised    — revert the last one-step move
#   confirm   : submit; only accepted once the ranking is complete (and, in
#               the revised ranking, while nothing is held)
#   quit      : abort the session (ranking is saved with status 'aborted')
# confirm must not share a key with select / undo / up / down.
RANKING_KEYS = {
    'up':      ['up'],
    'down':    ['down'],
    'select':  ['space'],
    'undo':    ['backspace'],
    'confirm': ['return'],
    'quit':    ['escape'],
}

# Participant-facing names for keys in on-screen hints.
KEY_DISPLAY = {
    'up': '↑', 'down': '↓', 'left': '←', 'right': '→',
    'space': 'Space', 'backspace': 'Backspace', 'return': 'Enter', 'escape': 'Esc',
}

# ─── Timing ──────────────────────────────────────────────────────────────────
RANKING_MAX_TIME   = None   # seconds per ranking screen; None = no deadline (to be decided)
CONFIRM_FEEDBACK_S = 0.5    # confirmed ranking stays on screen this long (no input)

# ─── Colours ─────────────────────────────────────────────────────────────────
CURSOR_COLOR    = '#FFD54F'
HELD_COLOR      = '#FF9800'
CONFIRMED_COLOR = '#4CAF50'
CARD_COLOR      = '#3a3a3a'
SLOT_COLOR      = '#555555'
DIM_TEXT_COLOR  = '#9e9e9e'
