# Counterfactual probe configuration: P1 selected

Status: P1 selected as the final configuration (2026-11-25). The experimental code and
stimulus tables (`competence_d3.csv`, synergy table) are unchanged. `counterfactual_schedule.csv`
still has empty candidate columns. P1's IDs are in `selected_configuration_p1.csv` and have not
been written into the schedule or the task.

Naming: **P1** is a *configuration* ID (proposed probe set 1, "distance-matched"). It is not the
experimental phase **phase_1** (blocks 0, 2, 4, competence visible). Every configuration
covers both phases.

## Files

| File | Contents |
|---|---|
| `proposed_combinations.csv` | 72 rows: 6 configurations × 12 probe slots (P1–P4, E-a, E-b) |
| `selected_configuration_p1.csv` | The 12 P1 rows, same columns |
| `source/candidates_artifact_data.json` | Data embedded in the Candidates artifact page, saved verbatim (2026-11-25) |
| `Counterfactual_Probe_Proposed_Combinations.xlsx` | Review workbook built from `proposed_combinations.csv` (generated; for Google Drive). The *Before vs After Rankings — P1* sheet is built from `selected_configuration_p1.csv` |

Reproduce (from the repo root):

    python -m tools.export_proposals                     # → the two CSVs above
    python -m tools.build_proposals_workbook             # → the .xlsx (needs openpyxl)

The exporter reads only `source/candidates_artifact_data.json`, the E-a/E-b table written in the
script, and the stimulus tables. It rebuilds the cf candidates and the schedule in process with
`tools.analyze_counterfactuals`, so it does not need the gitignored `data/analysis/` CSVs. It checks
that the artifact's attribute values equal the stimulus tables, and that each P1–P4 probe gives the
artifact's Kendall distance, footrule and gaps.

Sources:
- P1–P4: the rank-1 set shown in the "Proposed combinations" tabs of the *Counterfactual Probe
  Candidates* artifact (claude.ai/artifact/6GWy6wtFVfkGyaVvoU8v7a). The artifact data also holds
  9 near-equal-cost variants for each P (cost within 0.015). These reorder the same probes across
  same-domain blocks or change a hidden value. They were never presented, so they are not exported.
- E-a, E-b: the alternatives in section 3 of the *Counterfactual Probe Reassessment* artifact
  (claude.ai/artifact/L48PaNghMKbVu6HpuxSPm7). They are included for completeness.

### Candidate ID mapping
The artifacts used their own IDs (C01–C44, S13–S48). These are kept in `artifact_probe_id`.
Each probe was matched to `counterfactual_candidates.csv` on domain, kind, target, original value
and new value. All 48 P1–P4 probes match exactly one `cf` ID. Their Kendall distance, footrule and
revised gaps match the artifact numbers (the export asserts this).

**Missing IDs:** 8 E-a/E-b probes use competence values that cf001–cf148 doesn't enumerate:
E-a C→7.0, D→6.3, B→2.3; E-b D→2.9, D→6.1, B→6.7, D→6.3, C→1.3. These rows have
`candidate_id = MISSING`. Their target, original and counterfactual values and all metrics were
computed from the stimulus tables. **P1 has no missing IDs.**

## P1

| Slot | Probe | Candidate | Change | K | Revised top | Min gap |
|---|---|---|---|---|---|---|
| b0_probe1 | Competence | cf024 | cooking C 2.2 → 7.5 (L→H) | 3 | A+C (was B+D) | 0.50 |
| b0_probe2 | Synergy | cf040 | cooking A+C 1.4 → 0.8 (H→L) | 3 | B+D (unchanged) | 0.50 |
| b1_probe1 | Competence | cf062 | repairing B 8.2 → 2.2 (H→L) | **5** | A+C (was B+D) | **0.18** |
| b1_probe2 | Synergy | cf094 | repairing B+C 0.8 → 1.4 (L→H) | **3** | B+C (was B+D) | 0.78 |
| b2_probe1 | Synergy | cf144 | tennis B+C 0.8 → 1.4 (L→H) | 3 | B+C (was A+C) | **0.14** |
| b2_probe2 | Competence | cf114 | tennis B 2.0 → 7.5 (L→H) | 3 | B+D (was A+C) | **0.34** |
| b3_probe1 | Synergy | cf043 | cooking A+D 0.8 → 1.4 (L→H) | 3 | A+D (was B+D) | 1.68 |
| b3_probe2 | Competence | cf032 | cooking D 7.5 → 2.2 (H→L) | 3 | A+C (was B+D) | 1.20 |
| b4_probe1 | Synergy | cf095 | repairing B+D 1.4 → 0.8 (H→L) | **3** | A+C (was B+D) | 0.78 |
| b4_probe2 | Competence | cf061 | repairing B 8.2 → 2.1 (H→L) | **5** | A+C (was B+D) | **0.12** |
| b5_probe1 | Competence | cf115 | tennis B 2.0 → 7.7 (L→H) | 3 | B+D (was A+C) | **0.34** |
| b5_probe2 | Synergy | cf139 | tennis A+C 1.4 → 0.8 (H→L) | 3 | C+D (was A+C) | **0.08** |

## Why P1 was selected

The primary objective is to study how participants use the learned representations of
individual (competence) and relational (synergy) attributes to update their rankings under
uncertainty. It is not simply to measure how accurate the rankings are. So the key requirement is that the two probes in a block are comparable: a
competence update and a synergy update of similar size, against the same baseline.

1. **Identical Kendall distances in 4 of 6 blocks.** In the cooking and tennis blocks
   (b0, b2, b3, b5), both probes have K = 3. A within-block competence-vs-synergy difference
   therefore isn't confounded with how much the correct ranking changes. P1 has the lowest total
   mismatch of the proposals (Σ|ΔK| = 4; P2 13, P3 5, P4 8, E-a 5, E-b 4).
2. **Balanced direction.** There are 6 High→Low and 6 Low→High changes: 3/3 for each attribute
   and 3/3 within each phase. Direction is therefore not confounded with attribute type or with
   which attribute is visible.
3. **Original stimulus tables preserved.** Every P1 value already occurs in the tables
   (`value_rules` = `table` / `domain|table` / `synergy_table`). No table edits are needed, so
   trials, estimate items and the forced-first schedule stay valid. Of the alternatives, E-a and
   E-b need values outside the enumerated set. Making the problem probes robust needs table edits
   (M1/M3/R/L in the Reassessment).
4. **No alternative clearly beats it with the current tables.** E-a and E-b reduce near-ties
   (4 and 3 vs 6), but E-a has a worse Kendall/footrule match and E-b repeats target D across
   domains. Neither makes the repairing or tennis competence probes value-robust.

## Remaining limitations

- **Kendall mismatch in the two repairing blocks (b1, b4).** The competence probe is
  B High→Low with K = 5. No repairing synergy probe goes above K = 3, so ΔK = 2 in both blocks.
  Repairing has only two High/Low animals (B High, D Low). D Low→High is value-dependent (K 1–3),
  so B is the only usable competence target and is reused in both repairing blocks (2.2 in b1,
  2.1 in b4). Tennis also reuses B (7.5 in b2, 7.7 in b5).
- **Value-dependent correct rankings.** Participants see only the level, not the hidden value.
  Over the widened grid (Low 1.0–3.0, High 6.1–9.0, 0.1 steps), 4 of P1's 6 competence probes
  give more than one correct ranking:
  repairing B→Low (b1, b4) gives 5 rankings, with the modal ranking at about 33–35% of the grid.
  Tennis B→High (b2, b5) gives 2 rankings, with the modal ranking at about 87–89%
  (`n_rankings_in_level_grid`, `modal_ranking_share_grid`). Within the values the CSV actually
  uses (1.9–2.2 / 7.5–8.5), all six are robust. Only the cooking probes (b0, b3) are robust
  over the full range. For these probes, a "correct" answer depends on what range participants
  infer, so scoring against a single ranking should be treated with caution.
- **Near-ties (adjacent revised gap < 0.5) in 6 of 12 probes:** b1 competence (0.18),
  b2 synergy (0.14), b2 competence (0.34), b4 competence (0.12), b5 competence (0.34) and
  b5 synergy (0.08). Both b0 probes sit exactly at 0.50. The tennis ties come from the baseline
  (A+C vs C+D differ by 0.34), not from the choice of probe. The 0.5 cut-off is provisional.
- **Repeated counterfactual change in Group B (potential limitation).** Both tennis
  competence probes change the role-B animal from Low to High (b2: 2.0 → 7.5, b5: 2.0 → 7.7).
  They give the same revised ranking (B+D > A+C > C+D > B+C > A+B > A+D) against the same tennis
  baseline. The two repairing competence probes (B High → Low, b1 and b4) also share a revised
  ranking.
  With Group B order (1, 0, 3, 2, 5, 4) (commit fbd3463), participants see the two tennis blocks
  one after the other (b2 at position 4, b5 at position 5). b2's competence probe is its second
  probe and b5's is its first, so the same update comes in two consecutive probes. This could cause
  carryover, repetition or strategy-transfer effects: participants might reuse the ranking they just
  gave, or recognise the change, instead of reasoning from the learned attributes again. Different
  animal sets are used in the two blocks, which may reduce this, but the role-B profile and the
  revised ranking are the same. This is a **potential** limitation, not an observed effect. It can
  be checked after data collection, for example by comparing b5 responses between groups.
  *Current code:* commit 194ffb0 (2026-11-25) sets `BLOCK_ORDERS['B'] = (1, 0, 5, 4, 3, 2)`.
  In that order the tennis blocks are 3 positions apart (positions 3 and 6), as in Group A
  (b2 at 3, b5 at 6). The identical update is then repeated within the session but not back to
  back, so the risk is smaller but still present in both groups. The final Group B order needs to be
  confirmed before data collection.
- **Most changes move the top team.** 11 of 12 probes change the top-ranked team, and 6 move the
  changed team to 1st place. This makes the top position a salient cue. Participants may update
  mainly the top position rather than the full order.

## Column notes
- `direction`: change of level (H->L / L->H). `original_*` and `cf_*` give the level and value.
- `kendall_distance`: number of the 15 team pairs whose order flips. `footrule`: sum of absolute
  rank shifts. `block_kendall_abs_diff`: |K of probe 1 − K of probe 2| within the block.
- `affected_*_scores`: performance S(i,j)·(C_i + C_j) of the teams containing the target,
  before and after the change.
- `revised_gaps_g1_g5`: adjacent gaps in the revised ranking (1st–2nd … 5th–6th).
  `block_gap_mismatch`: mean |gap difference| between the block's two probes.
  `min_reversal_margin`: from `counterfactual_candidates.csv`.
- `n_rankings_in_level_observed_csv_range`: from the repo analysis (values 1.9–2.2 / 7.5–8.5).
  `*_grid`: recomputed on the Reassessment grid. Modal shares differ from the Reassessment page by
  up to 2 percentage points, most likely because the two count grid points at the breakpoints
  differently (exact ties are excluded here).
  The number of distinct rankings matches.
