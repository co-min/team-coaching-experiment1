# Team-managing task (v4)

PsychoPy task: participants pick the best 2-animal team out of 4 for a domain
(cooking / repairing / tennis). Blocks alternate between

- **phase_1**: individual competence is visible (coloured border on hover)
- **phase_2**: pairwise synergy is visible (coloured block under each animal)

## Run

```bash
python main.py                    # from anywhere — all paths are resolved from the project root
python tools/check_neon.py        # (optional) Neon pre-flight, when USE_NEON=True
python -m tools.preview_ending    # preview the leaderboard screen
```

## What to edit

| I want to change…                                   | File                     |
|-----------------------------------------------------|--------------------------|
| domains, trial count, block order, language, timing, window, LabJack/Neon on/off | `config/settings.py` |
| participant-facing text (ko/en)                     | `config/strings.py`      |
| trigger codes                                       | `hardware/labjack.py`    |
| stimulus tables / images                            | `stimuli/`               |

## Layout

```
main.py                 session → blocks → ending
config/                 settings (constants), paths, strings
task/                   everything the participant sees
  session.py            subject dialog, window, LabJack + Neon connection
  schedule.py           seeded per-block trial schedules
  block.py              trial loop: ITI → trial → feedback → save (background thread)
  trials/               phase1.py (competence), phase2.py (synergy), common.py
  screens/              instructions, ITI, feedback, ending
  visuals.py            preloaded animal/domain stimuli, 4-slot layout
  keyboard.py           arrow-key display
hardware/               LabJack TTL, Neon client, LJ+Neon event dispatch, photodiode marker
recording/              stimulus loading, frame logger, file writers, summary.json
stimuli/                tables/ (CSV), images/
tools/                  stimulus generation + data checks (not imported by the task)
data/                   output (git-ignored)
```

Dependency direction: `task → hardware, recording, config`; `hardware` and
`recording` never import `task`.

## First-choice mode

`FIRST_CHOICE_MODE` in `config/settings.py`:

- `'free'`: participant picks both animals (original task).
- `'forced'`: the first animal is assigned from
  `stimuli/tables/forced_first_schedule.csv` and shown locked for
  `FORCED_FIRST_DURATION` s. The participant then picks only the second animal.

The CSV is fixed and identical for every subject. `main.py` validates it before
opening the window: balance, domain order, animal groups. Any mismatch aborts
the run. It was built for the domain order given by `DOMAIN_ORDER` /
`SCHEDULE_SEED`. If you change those, regenerate it:

```bash
python -m tools.make_forced_first_schedule                    # balance report + validation of the committed CSV
python -m tools.make_forced_first_schedule --write --force    # regenerate (deterministic)
python -m unittest tests.test_forced_first_schedule -v        # schedule tests (no window)
python -m unittest tests.test_trial_flow -v                   # trial-flow tests (opens a window, ~1 min)
```

Forced-mode logging: `choice1_*` holds the assigned animal, and
`trig_choice1` / `rt_choice1` are empty. No choice TTL is sent for the
assignment. The forced display carries the usual choice-onset code (201/202).
New `trials.csv` columns are appended after the original ones:
`first_choice_mode, forced_first_animal, forced_first_code, forced_first_onset,
second_choice_onset, selected_team, schedule_version`.

## Output (`data/sub-{id}/`)

`session_metadata.json`, `trials.csv`, `frames.csv`, `summary.json`,
`neon_event_log.xlsx`, and per trial
`block_{i}/{phase}/{domain}/{stim_pair_id}/{metadata.json, frame_log.csv}`.
Column layouts are identical to v3; forced-first columns are appended at the end of `trials.csv`.

## Stimulus tables

Only two input tables define the task (plus `synergy_color.csv` for display):

- `competence_d3.csv`: animal → char code (A–D) and competence per domain
- `synergy.csv`: synergy score per char-code pair

Char codes A–D repeat across the 6 animal groups (each group of 4 shares the same
competence profile), so scores are keyed by code pair. Pair scores are computed at
startup in `recording/stimuli_loader.py`:

1. raw score = synergy × (competence₁ + competence₂), per domain
2. each domain is replaced by its rank among the 6 pairs × 10 (10 = worst, 60 = perfect)
