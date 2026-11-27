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
# Counterfactual probe conditions (PROBE_CONDITIONS below) are bound to these
# domains at run time (task.ranking.assessments.ProbeCondition).
PERFORMANCE_RANKING_DOMAINS = ('cooking', 'repairing', 'tennis', 'cooking', 'repairing', 'tennis')

# ─── Counterfactual probe order ──────────────────────────────────────────────
# Attribute changed by probe 1 and probe 2 of each block, block 0 first.
# Attached to the original block ID (not the presentation position), fixed for
# every participant. 3 competence-first / 3 synergy-first blocks; both orders
# occur in each phase and for each ranking domain.
# Checked by task.ranking.schedule.probe_order_problems.
PROBE_ORDERS = (
    ('competence', 'synergy'),      # block 0  phase_1  cooking
    ('competence', 'synergy'),      # block 1  phase_2  repairing
    ('synergy', 'competence'),      # block 2  phase_1  tennis
    ('synergy', 'competence'),      # block 3  phase_2  cooking
    ('synergy', 'competence'),      # block 4  phase_1  repairing
    ('competence', 'synergy'),      # block 5  phase_2  tennis
)
PROBE_KINDS = ('competence', 'synergy')

# ─── Counterfactual probe conditions (configuration P1, selected 2026-11-25) ─
# Hypothetical change of each probe, block 0 first: {kind: (role codes, new value)}.
# Values are on the original stimulus-table scale and all occur in the tables.
# A competence change applies to the block's ranking domain (above); a synergy
# change has no domain. Each change is applied on its own to the original
# attributes. Participants see only the new level (low / high), never the value.
# Roles A–D are mapped to the block's animals at run time.
# Looked up by original block ID (task.ranking.assessments.block_conditions).
# Source and metrics: analysis/counterfactual/results/selected_configuration_p1.csv
#   block  probe 1                          probe 2
PROBE_CONDITIONS = (
    {'competence': (('C',), 7.5),        # b0  cf024 C cooking 2.2→7.5 (L→H)  cf040 A+C 1.4→0.8 (H→L)
     'synergy':    (('A', 'C'), 0.8)},
    {'competence': (('B',), 2.2),        # b1  cf062 B repairing 8.2→2.2 (H→L)  cf094 B+C 0.8→1.4 (L→H)
     'synergy':    (('B', 'C'), 1.4)},
    {'competence': (('B',), 7.5),        # b2  cf144 B+C 0.8→1.4 (L→H)  cf114 B tennis 2.0→7.5 (L→H)
     'synergy':    (('B', 'C'), 1.4)},
    {'competence': (('D',), 2.2),        # b3  cf043 A+D 0.8→1.4 (L→H)  cf032 D cooking 7.5→2.2 (H→L)
     'synergy':    (('A', 'D'), 1.4)},
    {'competence': (('B',), 2.1),        # b4  cf095 B+D 1.4→0.8 (H→L)  cf061 B repairing 8.2→2.1 (H→L)
     'synergy':    (('B', 'D'), 0.8)},
    {'competence': (('B',), 7.7),        # b5  cf115 B tennis 2.0→7.7 (L→H)  cf139 A+C 1.4→0.8 (H→L)
     'synergy':    (('A', 'C'), 0.8)},
)

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
# RANKING_MAX_TIME: None for the behavioural experiment. If set, a baseline that
# times out is saved as partial with status 'timeout' (never filled in) and the
# block's revised rankings are skipped.
RANKING_MAX_TIME   = None   # seconds per ranking screen; None = no deadline
CONFIRM_FEEDBACK_S = 0.5    # confirmed ranking stays on screen this long (no input)

# ─── Colours ─────────────────────────────────────────────────────────────────
# Red / yellow / green are reserved for the competence & synergy hints
# (low / medium / high), so the ranking UI stays neutral.
CURSOR_COLOR    = '#00d9ff'   # same highlight as the trial arrow keys (task/keyboard.py)
HELD_COLOR      = 'white'
CONFIRMED_COLOR = '#bdbdbd'
TITLE_COLOR     = 'white'
CARD_COLOR      = '#3a3a3a'
SLOT_COLOR      = '#555555'
DIM_TEXT_COLOR  = '#9e9e9e'
