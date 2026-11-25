"""
build_proposals_workbook.py
---------------------------
OFFLINE: builds the review workbook for the counterfactual probe proposals (not imported by the task).

    python -m tools.export_proposals            # first: writes the two CSVs
    python -m tools.build_proposals_workbook    # → docs/counterfactual/Counterfactual_Probe_Proposed_Combinations.xlsx
    python -m tools.build_proposals_workbook --out some.xlsx

Reads docs/counterfactual/proposed_combinations.csv, selected_configuration_p1.csv (for the
before/after sheet) and the stimulus tables (for the baseline section). Needs openpyxl. Summary
cells, baseline scores and chart data are Excel formulas over the copied rows, so they recalculate
if a row is edited.

Sheets: Overview · Proposed Combinations · Selected P1 · Before vs After Rankings — P1 ·
Ranking Analysis · Selection Rationale
"""

import argparse
import csv
from pathlib import Path
from typing import Dict, List

from openpyxl import Workbook
from openpyxl.chart import BarChart, LineChart, Reference, Series
from openpyxl.chart.axis import ChartLines
from openpyxl.chart.data_source import StrRef
from openpyxl.chart.label import DataLabel, DataLabelList
from openpyxl.chart.series import SeriesLabel
from openpyxl.chart.shapes import GraphicalProperties
from openpyxl.chart.text import RichText
from openpyxl.drawing.line import LineProperties
from openpyxl.drawing.text import CharacterProperties, Paragraph, ParagraphProperties
from openpyxl.comments import Comment
from openpyxl.formatting.rule import FormulaRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from config import settings as S
from tools.analyze_counterfactuals import exact_attributes
from tools.export_proposals import DOCS_DIR, NEAR, TEAMS

CSV_PATH = DOCS_DIR / "proposed_combinations.csv"
P1_CSV_PATH = DOCS_DIR / "selected_configuration_p1.csv"
DEFAULT_OUT = DOCS_DIR / "Counterfactual_Probe_Proposed_Combinations.xlsx"
CONFIGS = ["P1", "P2", "P3", "P4", "E-a", "E-b"]
DOMAINS = ["cooking", "repairing", "tennis"]
ALT_ORDER_B = (1, 0, 3, 2, 5, 4)   # earlier Group B order (commit fbd3463), see limitation

# ── styles ────────────────────────────────────────────────────────────────────
FONT = "Arial"
F_BASE = Font(name=FONT, size=10)
F_BOLD = Font(name=FONT, size=10, bold=True)
F_TITLE = Font(name=FONT, size=14, bold=True, color="1F3A5F")
F_SECTION = Font(name=FONT, size=11, bold=True, color="1F3A5F")
F_HEAD = Font(name=FONT, size=10, bold=True, color="FFFFFF")
F_NOTE = Font(name=FONT, size=9, italic=True, color="52514E")
F_INPUT = Font(name=FONT, size=10, color="0000FF")
F_MISSING = Font(name=FONT, size=10, bold=True, color="C00000")
F_P1 = Font(name=FONT, size=10, bold=True, color="7F6000")
FILL_HEAD = PatternFill("solid", fgColor="1F3A5F")
FILL_P1 = PatternFill("solid", fgColor="FFF2CC")
FILL_MISSING = PatternFill("solid", fgColor="FDE2E1")
FILL_KEY = PatternFill("solid", fgColor="EAF1FB")
THIN = Side(style="thin", color="BFBFBF")
MED = Side(style="medium", color="1F3A5F")
BOX = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
WRAP = Alignment(wrap_text=True, vertical="top")
CENTER = Alignment(horizontal="center", vertical="center", wrap_text=True)
COMP_COLOR, SYN_COLOR = "2A78D6", "EB6834"   # categorical slots 1, 2 (Competence, Synergy)

TEXT_COLS = {"config_id", "slot_id", "candidate_id", "artifact_probe_id", "direction",
             "revised_gaps_g1_g5", "near_tie_gaps"}


def _typed(name: str, v: str):
    if name in TEXT_COLS or v == "":
        return v if v != "" else None
    for cast in (int, float):
        try:
            return cast(v)
        except ValueError:
            pass
    return v


def load_rows() -> List[Dict[str, object]]:
    with open(CSV_PATH, newline="", encoding="utf-8") as f:
        rows = [{k: _typed(k, v) for k, v in r.items()} for r in csv.DictReader(f)]
    for r in rows:
        for i, g in enumerate(str(r["revised_gaps_g1_g5"]).split(), start=1):
            r[f"gap_g{i}"] = float(g)
    return rows


def _cell(ws, row, col, value=None, font=F_BASE, fill=None, fmt=None, align=None, border=None):
    c = ws.cell(row=row, column=col, value=value)
    c.font = font
    if fill:
        c.fill = fill
    if fmt:
        c.number_format = fmt
    if align:
        c.alignment = align
    if border:
        c.border = border
    return c


def _header(ws, row, col, labels, widths=None):
    for i, label in enumerate(labels):
        _cell(ws, row, col + i, label, F_HEAD, FILL_HEAD, align=CENTER, border=BOX)
        if widths:
            ws.column_dimensions[get_column_letter(col + i)].width = widths[i]


def _para(ws, row, text, font=F_BASE, col=2, height=None):
    c = _cell(ws, row, col, text, font, align=WRAP)
    if height:
        ws.row_dimensions[row].height = height
    return row + 1


def _style_chart(chart, title, y_title, x_title):
    chart.title = title
    chart.y_axis.title = y_title
    chart.x_axis.title = x_title
    chart.roundedCorners = False
    chart.legend.position = "b"
    chart.legend.overlay = False
    chart.x_axis.delete = False
    chart.y_axis.delete = False
    chart.y_axis.majorGridlines = ChartLines(spPr=GraphicalProperties(ln=LineProperties(solidFill="D9D9D9")))
    chart.gapWidth = 60
    chart.overlap = -5
    for s, color, label in zip(chart.series, (COMP_COLOR, SYN_COLOR), ("Competence probe", "Synergy probe")):
        s.tx = SeriesLabel(v=label)
        s.graphicalProperties.solidFill = color
        s.graphicalProperties.line.solidFill = "FFFFFF"
        s.dLbls = DataLabelList()
        s.dLbls.showVal = True
        for attr in ("showSerName", "showCatName", "showLegendKey", "showPercent"):
            setattr(s.dLbls, attr, False)
    chart.height, chart.width = 7.5, 15.5
    for t in (chart.title, chart.x_axis.title, chart.y_axis.title):
        if t is not None:
            t.overlay = False


# ── sheet 2: Proposed Combinations ────────────────────────────────────────────

class Table:
    """The 72-row copy of proposed_combinations.csv; gives absolute column ranges for formulas."""
    SHEET = "'Proposed Combinations'"

    def __init__(self, ws, rows):
        cols = list(rows[0])
        gap_cols = [c for c in cols if c.startswith("gap_g")]
        cols = [c for c in cols if c not in gap_cols]
        at = cols.index("revised_gaps_g1_g5") + 1
        self.cols = cols[:at] + gap_cols + cols[at:]
        self.first, self.last = 2, len(rows) + 1
        widths = {"config_source": 30, "baseline_ranking": 26, "revised_ranking": 26, "candidate_id_status": 22,
                  "config_name": 16, "revised_gaps_g1_g5": 22, "near_tie_gaps": 18, "affected_baseline_scores": 16,
                  "affected_revised_scores": 16, "affected_teams": 14}
        _header(ws, 1, 1, self.cols, [widths.get(c, 11) for c in self.cols])
        ws.row_dimensions[1].height = 42
        for i, r in enumerate(rows, start=2):
            p1 = r["config_id"] == "P1"
            for j, name in enumerate(self.cols, start=1):
                v = r[name]
                font, fill = F_BASE, FILL_P1 if p1 else None
                if name == "config_id" and p1:
                    font = F_P1
                if name == "candidate_id" and v == "MISSING":
                    font, fill = F_MISSING, FILL_MISSING
                fmt = "0.00" if name.startswith("gap_g") or name == "min_adjacent_gap_revised" else None
                if name == "modal_ranking_share_grid":
                    fmt = "0%"
                _cell(ws, i, j, v, font, fill, fmt, border=BOX)
            if r["candidate_id"] == "MISSING":
                ws.cell(row=i, column=self.idx("candidate_id")).comment = Comment(
                    f"No cf ID: {r['target']} {r['original_value']} → {r['cf_value']} is outside the values "
                    "enumerated in cf001–cf148. Original values kept; metrics computed from the stimulus tables.",
                    "export_proposals")
        ws.freeze_panes = "F2"
        ws.auto_filter.ref = f"A1:{get_column_letter(len(self.cols))}{self.last}"

    def idx(self, name):
        return self.cols.index(name) + 1

    def rng(self, name):
        L = get_column_letter(self.idx(name))
        return f"{self.SHEET}!${L}${self.first}:${L}${self.last}"


# ── sheet 1: Overview ─────────────────────────────────────────────────────────

def overview(ws, rows):
    ws.column_dimensions["A"].width = 3
    ws.column_dimensions["B"].width = 26
    for L in "CDEFGHI":
        ws.column_dimensions[L].width = 15
    ws.sheet_view.showGridLines = False
    _cell(ws, 1, 2, "Counterfactual Probe: Proposed Combinations", F_TITLE)
    _cell(ws, 2, 2, "Status 2026-11-25: configuration P1 selected. Stimulus tables, experimental code, "
                    "block order and ProbeCondition are unchanged; P1's IDs are not yet written into the task.", F_NOTE)

    def section(row, title):
        _cell(ws, row, 2, title, F_SECTION)
        ws.cell(row=row, column=2).border = Border(bottom=MED)
        return row + 1

    def long(row, text, height):
        ws.merge_cells(start_row=row, start_column=2, end_row=row, end_column=9)
        _cell(ws, row, 2, text, align=WRAP)
        ws.row_dimensions[row].height = height
        return row + 1

    r = section(4, "Research objective")
    r = long(r, "The primary objective is to investigate how participants use the learned representations of "
                "individual attributes (competence) and relational attributes (synergy) to update their team "
                "rankings under uncertainty. The probes are not designed mainly to measure exact ranking accuracy. "
                "Each block therefore pairs one competence update and one synergy update of comparable size "
                "against the same baseline, so that differences in updating can be attributed to the attribute "
                "type rather than to how much the correct ranking changes.", 72)
    ws.cell(row=r - 1, column=2).fill = FILL_KEY

    r = section(r + 1, "Selection criteria (in order of priority)")
    for text in [
        "1. Comparable change size within a block: equal Kendall distance (K) for the competence and synergy probe "
        "(Σ|ΔK| over the 6 blocks as small as possible).",
        "2. Direction balance: equal numbers of High→Low and Low→High changes, for each attribute and in each phase.",
        "3. Use only values already in the stimulus tables, so trials, estimate items and the forced-first schedule stay valid.",
        "4. Secondary: few near-ties in the revised ranking (adjacent gap < 0.5), similar gap profiles within a block, "
        "correct ranking robust to the hidden value within the level, and few extreme moves of the top team.",
    ]:
        r = long(r, text, 28)

    r = section(r + 1, "Data sources")
    for label, text in [
        ("Stimulus tables", "stimuli/tables/competence_d3.csv, synergy.csv (exact values; Performance = S(i,j) × (C_i + C_j))."),
        ("P1–P4", "Rank-1 set of each proposal in the Counterfactual Probe Candidates artifact "
                  "(claude.ai/artifact/6GWy6wtFVfkGyaVvoU8v7a); saved as docs/counterfactual/source/candidates_artifact_data.json."),
        ("E-a, E-b", "Alternatives in section 3 of the Counterfactual Probe Reassessment artifact "
                     "(claude.ai/artifact/L48PaNghMKbVu6HpuxSPm7); transcribed in tools/export_proposals.py."),
        ("Candidate table", "cf001–cf148 from tools/analyze_counterfactuals.py (rebuilt from the stimulus tables)."),
        ("This workbook", "docs/counterfactual/proposed_combinations.csv (python -m tools.export_proposals), "
                          "built by python -m tools.build_proposals_workbook. All P1–P4 metrics were checked against "
                          "the artifact numbers during export."),
    ]:
        _cell(ws, r, 2, label, F_BOLD, align=WRAP)
        ws.merge_cells(start_row=r, start_column=3, end_row=r, end_column=9)
        _cell(ws, r, 3, text, align=WRAP)
        ws.row_dimensions[r].height = 28
        r += 1

    r = section(r + 1, "Identifiers and naming")
    for label, text, font, fill in [
        ("P1 (configuration)", "Proposed probe set 1, 'distance-matched': the SELECTED configuration. Highlighted in "
                               "this colour on every sheet. Not related to the experimental phase.", F_P1, FILL_P1),
        ("phase_1 / phase_2", "Experimental phase of a block. phase_1 = blocks 0, 2, 4 (competence visible); "
                              "phase_2 = blocks 1, 3, 5 (synergy visible). Every configuration covers both phases.", F_BOLD, None),
        ("P2, P3, P4", "Other rank-1 proposals: fewest extremes, distinct targets, mixed direction.", F_BOLD, None),
        ("E-a, E-b", "Reassessment alternatives: no repeated role / repeats allowed.", F_BOLD, None),
        ("candidate_id (cfNNN)", "Row in the repo candidate table cf001–cf148, matched on domain, kind, target role, "
                                 "original value and new value.", F_BOLD, None),
        ("MISSING", "The probe's value is not one of the values enumerated in cf001–cf148 (8 E-a/E-b competence probes). "
                    "Original values are kept and metrics are computed from the stimulus tables; no new ID is generated. "
                    "P1 has no MISSING IDs.", F_MISSING, FILL_MISSING),
        ("artifact_probe_id", "ID used inside the Candidates artifact (C01–C44 competence, S13–S48 synergy); n/a for E-a/E-b.", F_BOLD, None),
        ("slot_id", "b<block>_probe<order>: block 0–5 and probe order 1–2 within the block.", F_BOLD, None),
    ]:
        _cell(ws, r, 2, label, font, fill, align=WRAP, border=BOX)
        ws.merge_cells(start_row=r, start_column=3, end_row=r, end_column=9)
        _cell(ws, r, 3, text, align=WRAP)
        ws.row_dimensions[r].height = 28
        r += 1

    r = section(r + 1, "Block design (shared by all configurations)")
    _header(ws, r, 2, ["Block", "Experimental phase", "Visible attribute", "Domain", "Probe 1", "Probe 2",
                       "Position, Group A", "Position, Group B"])
    r += 1
    p1 = [x for x in rows if x["config_id"] == "P1"]
    for b in range(6):
        pr = [x for x in p1 if x["block_id"] == b]
        vals = [f"b{b}", pr[0]["phase"], pr[0]["visible_attribute"], pr[0]["domain"],
                pr[0]["probe_type"], pr[1]["probe_type"],
                S.BLOCK_ORDERS["A"].index(b) + 1, S.BLOCK_ORDERS["B"].index(b) + 1]
        for j, v in enumerate(vals):
            _cell(ws, r, 2 + j, v, align=CENTER, border=BOX)
        r += 1
    _cell(ws, r, 2, f"Positions (1–6) from config/settings.py BLOCK_ORDERS: A = {S.BLOCK_ORDERS['A']}, "
                    f"B = {S.BLOCK_ORDERS['B']} (commit 194ffb0). The earlier Group B order {ALT_ORDER_B} placed "
                    "both tennis blocks back to back; see Selection Rationale, limitation 5.", F_NOTE)

    r = section(r + 2, "Sheets")
    for name, text in [("Proposed Combinations", "All 72 probes (6 configurations × 12), every exported column. Filterable."),
                       ("Selected P1", "The 12 P1 probes by block and probe order, with presentation positions."),
                       (BA_SHEET, "For each P1 probe: the change applied, baseline (before) vs revised (after) ranking, "
                                  "Kendall distance, and a rank change chart per probe with the affected teams highlighted."),
                       ("Ranking Analysis", "Baseline scores and rankings, configuration summary, P1 baseline vs revised "
                                            "rankings, Kendall distances, score gaps, near-ties, top-team changes, charts."),
                       ("Selection Rationale", "Why P1 was selected and its remaining limitations.")]:
        _cell(ws, r, 2, name, F_BOLD)
        ws.merge_cells(start_row=r, start_column=3, end_row=r, end_column=9)
        _cell(ws, r, 3, text, align=WRAP)
        r += 1
    _cell(ws, r + 1, 2, "Colour key: blue text = input values copied from the stimulus tables; black = formulas or "
                        "exported values; yellow fill = configuration P1; red = MISSING candidate ID.", F_NOTE)


# ── sheet 3: Selected P1 ──────────────────────────────────────────────────────

def selected_p1(ws, rows):
    ws.sheet_view.showGridLines = False
    _cell(ws, 1, 1, "Selected configuration P1 (distance-matched): 12 probes", F_TITLE)
    _cell(ws, 2, 1, "P1 = configuration ID, not the experimental phase. Rows ordered by block ID and probe order; "
                    "the presentation positions show when each block is seen in each counterbalance group.", F_NOTE)
    cols = [("Block", "block_id", 7), ("Slot", "slot_id", 11), ("Experimental phase", "phase", 11),
            ("Domain", "domain", 10), ("Visible attribute", "visible_attribute", 11), ("Probe order", "probe_pos", 7),
            ("Probe type", "probe_type", 12), ("Changes visible attribute", "changes_visible_attribute", 10),
            ("Candidate ID", "candidate_id", 10), ("Artifact ID", "artifact_probe_id", 9), ("Target", "target", 8),
            ("Direction", "direction", 9), ("Original value", "original_value", 9), ("CF value", "cf_value", 9),
            ("Kendall distance", "kendall_distance", 9), ("Footrule", "footrule", 8),
            ("|ΔK| in block", "block_kendall_abs_diff", 8), ("Baseline top", "baseline_top", 9),
            ("Revised top", "revised_top", 9), ("Smallest revised gap", "min_adjacent_gap_revised", 9),
            ("Near-tie (<0.5)", "near_tie_lt_0.5", 8), ("Value-dependent (grid)", "value_dependent_grid", 10),
            ("Group A position", None, 9), ("Group B position", None, 9),
            (f"Group B position if {ALT_ORDER_B}", None, 12)]
    _header(ws, 4, 1, [c[0] for c in cols], [c[2] for c in cols])
    ws.row_dimensions[4].height = 44
    p1 = sorted((x for x in rows if x["config_id"] == "P1"), key=lambda x: (x["block_id"], x["probe_pos"]))
    for i, x in enumerate(p1, start=5):
        b = x["block_id"]
        extra = [S.BLOCK_ORDERS["A"].index(b) + 1, S.BLOCK_ORDERS["B"].index(b) + 1, ALT_ORDER_B.index(b) + 1]
        vals = [x[k] for _, k, _ in cols[:-3]] + extra
        for j, v in enumerate(vals, start=1):
            border = Border(left=THIN, right=THIN, top=THIN, bottom=MED if x["probe_pos"] == 2 else THIN)
            fmt = "0.00" if cols[j - 1][1] == "min_adjacent_gap_revised" else None
            _cell(ws, i, j, v, F_P1 if j == 9 else F_BASE, FILL_P1, fmt, CENTER, border)
    last = 4 + len(p1)
    _cell(ws, last + 2, 1, "Totals", F_BOLD)
    for label, col, fn in [("High→Low changes", "L", f'=COUNTIF(L5:L{last},"H->L")'),
                           ("Low→High changes", "L", f'=COUNTIF(L5:L{last},"L->H")'),
                           ("Σ|ΔK| (blocks)", "Q", f"=SUMIFS(Q5:Q{last},F5:F{last},1)"),
                           ("Probes with near-tie", "U", f"=SUM(U5:U{last})"),
                           ("Top team changed", None, f"=SUMPRODUCT(--(R5:R{last}<>S5:S{last}))"),
                           ("Value-dependent competence probes", "V", f"=SUM(V5:V{last})")]:
        r = ws.max_row + 1
        _cell(ws, r, 1, label)
        ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=4)
        _cell(ws, r, 5, fn, F_BOLD, align=CENTER)
    ws.freeze_panes = "C5"


# ── sheet 4: Before vs After Rankings — P1 ────────────────────────────────────

BA_SHEET = "Before vs After Rankings — P1"
LEVEL = {"low": "Low", "high": "High"}
DIRECTION = {"L->H": "Low → High", "H->L": "High → Low"}
FILL_COMP_HI, FILL_SYN_HI = PatternFill("solid", fgColor="DCEAF9"), PatternFill("solid", fgColor="FCE4D6")
OTHER_LINE = "BFBFBF"


def load_p1_rows() -> List[Dict[str, object]]:
    """selected_configuration_p1.csv as is; checked against the P1 rows of proposed_combinations.csv."""
    with open(P1_CSV_PATH, newline="", encoding="utf-8") as f:
        rows = [{k: _typed(k, v) for k, v in r.items()} for r in csv.DictReader(f)]
    assert len(rows) == 12
    return sorted(rows, key=lambda x: (x["block_id"], x["probe_pos"]))


def _rank_chart(ws, x, first_row, before_col, title, line_color):
    """Slope chart: one line per team from its baseline rank to its revised rank (rank 1 at the top)."""
    ch = LineChart()
    for k in range(6):
        r = first_row + k
        s = Series(Reference(ws, min_col=before_col, max_col=before_col + 1, min_row=r, max_row=r),
                   title_from_data=False)
        s.tx = SeriesLabel(strRef=StrRef(f"'{BA_SHEET}'!${get_column_letter(before_col - 1)}${r}"))
        affected = x["team"][k] in x["affected"]
        s.smooth = False
        s.graphicalProperties.line.solidFill = line_color if affected else OTHER_LINE
        s.graphicalProperties.line.width = 38100 if affected else 15875          # 3 pt / 1.25 pt
        s.marker.symbol = "circle"
        s.marker.size = 8 if affected else 6
        s.marker.graphicalProperties = GraphicalProperties(solidFill=line_color if affected else OTHER_LINE)
        s.marker.graphicalProperties.line.solidFill = "FFFFFF"
        lbl = dict(showSerName=True, showVal=False, showCatName=False, showLegendKey=False, showPercent=False)
        s.dLbls = DataLabelList(dLbl=[DataLabel(idx=0, dLblPos="l", **lbl), DataLabel(idx=1, dLblPos="r", **lbl)],
                                **lbl)
        s.dLbls.txPr = RichText(p=[Paragraph(pPr=ParagraphProperties(defRPr=CharacterProperties(
            sz=1000, b=affected, solidFill="1F3A5F" if affected else "7F7F7F")), endParaRPr=CharacterProperties())])
        ch.series.append(s)
    ch.set_categories(Reference(ws, min_col=before_col, max_col=before_col + 1, min_row=first_row - 1))
    ch.title = title
    ch.title.overlay = False
    ch.legend = None
    ch.roundedCorners = False
    ch.x_axis.delete = False
    ch.y_axis.delete = False
    ch.y_axis.title = "Rank (1 = best)"
    ch.y_axis.title.overlay = False
    ch.y_axis.scaling.min, ch.y_axis.scaling.max = 1, 6
    ch.y_axis.scaling.orientation = "maxMin"
    ch.y_axis.majorUnit = 1
    ch.y_axis.number_format = "0"
    ch.y_axis.majorGridlines = ChartLines(spPr=GraphicalProperties(ln=LineProperties(solidFill="E7E6E6")))
    ch.x_axis.crosses = "max"            # with the reversed rank axis, keeps the category labels at the bottom
    for ax in (ch.x_axis, ch.y_axis):     # no axis lines: rank 6 would sit on the x axis
        ax.graphicalProperties = GraphicalProperties(ln=LineProperties(noFill=True))
    ch.height, ch.width = 9.0, 11.5
    return ch


def before_after_p1(ws, p1):
    ws.sheet_view.showGridLines = False
    widths = {"A": 10, "B": 9, "C": 10, "D": 15, "E": 9, "F": 11, "G": 10, "H": 9, "I": 9, "J": 9, "K": 9,
              "L": 29, "M": 29, "N": 9, "O": 16}
    for L, w in widths.items():
        ws.column_dimensions[L].width = w
    _cell(ws, 1, 1, "Before vs After Rankings: configuration P1 (12 selected probes)", F_TITLE)
    _cell(ws, 2, 1, "Source: docs/counterfactual/selected_configuration_p1.csv, copied without changes. "
                    "P1 = the selected configuration ID, not experimental phase_1.", F_NOTE)

    # how to read
    _cell(ws, 4, 1, "How to read this sheet", F_SECTION)
    r = 5
    for text in [
        "• Each block has four animals, coded A–D (each block uses its own animal set). Any two animals form a team, "
        "so there are 6 teams (A+B, A+C, A+D, B+C, B+D, C+D). Team score = synergy of the pair × (competence of "
        "animal 1 + competence of animal 2), in the block's domain. The ranking orders the 6 teams by score (1 = best).",
        "• Baseline ranking (before) = the correct ranking with the learned attribute values. Each probe then changes "
        "ONE value (one animal's competence, or one pair's synergy) from Low to High or High to Low. Revised ranking "
        "(after) = the correct ranking once that single change is applied. Both probes in a block start from the same baseline.",
        "• Kendall distance = how many of the 15 team pairs swap order between the two rankings (0 = identical, "
        "15 = fully reversed). In the tables below, 'Overtaken by' counts, for each team, the teams that were below it "
        "and are now above it; the column total equals the Kendall distance.",
        "• Directly affected teams = teams whose score changes: the 3 teams containing the changed animal (competence "
        "probe) or the one changed pair (synergy probe). They are shaded in the tables and drawn as thick coloured "
        "lines in the charts (blue = competence probe, orange = synergy probe); all other teams are grey.",
    ]:
        ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=15)
        _cell(ws, r, 1, text, align=WRAP)
        ws.row_dimensions[r].height = 30
        r += 1

    # A. summary of the 12 probes
    a0 = r + 1
    _cell(ws, a0, 1, "A. All 12 probes", F_SECTION)
    heads = ["Probe", "Block ID", "Domain", "Phase", "Probe position", "Probe type", "Target (animal / pair)",
             "Original level", "Original value", "Counterfactual level", "Counterfactual value",
             "Baseline ranking (before)", "Revised ranking (after)", "Kendall distance", "Directly affected teams"]
    _header(ws, a0 + 1, 1, heads)
    ws.row_dimensions[a0 + 1].height = 44
    first = a0 + 2
    for i, x in enumerate(p1, start=first):
        x["row"] = i
        x["team"] = x["baseline_ranking"].split(">")
        x["affected"] = x["affected_teams"].split("|")
        phase = f"{x['phase']} ({x['visible_attribute']} visible)"
        vals = [x["slot_id"], x["block_id"], x["domain"], phase, x["probe_pos"], x["probe_type"], x["target"],
                LEVEL[x["original_level"]], x["original_value"], LEVEL[x["cf_level"]], x["cf_value"],
                x["baseline_ranking"].replace(">", " > "), x["revised_ranking"].replace(">", " > "), x["kendall_distance"],
                x["affected_teams"].replace("|", ", ")]
        for j, v in enumerate(vals, start=1):
            border = Border(left=THIN, right=THIN, top=THIN, bottom=MED if x["probe_pos"] == 2 else THIN)
            font = F_P1 if j == 1 else F_BOLD if j == 14 else F_BASE
            _cell(ws, i, j, v, font, FILL_P1 if j == 1 else None, "0.0" if j in (9, 11) else None,
                  Alignment(horizontal="left", vertical="center") if j in (12, 13) else CENTER, border)
        ws.row_dimensions[i].height = 26 if len(phase) > 15 else None
    last = first + len(p1) - 1
    _cell(ws, last + 1, 1, "Rankings read left to right from 1st to 6th place. Original/counterfactual values are the hidden "
                           "attribute values (competence 0–10 scale, synergy multiplier); participants see only the level. "
                           "Probe = b<block>_probe<position>.", F_NOTE)

    # B. per-block rank tables and rank change plots
    b0 = last + 4
    _cell(ws, b0, 1, "B. Rank changes by block: each table and chart shows how the six teams move from the baseline "
                     "ranking to the revised ranking", F_SECTION)
    _cell(ws, b0 + 1, 1, "Change: ▲ = moved up (better rank), ▼ = moved down. Tables are formulas over section A, "
                         "so they update if a ranking in section A is edited (chart line colours are set when the "
                         "workbook is built).", F_NOTE)
    tcols = ["Team", "Before rank (baseline)", "After rank (revised)", "Change", "Directly affected", "Overtaken by"]
    r = b0 + 3
    for b in range(6):
        pair = [x for x in p1 if x["block_id"] == b]
        hdr = (f"Block {b} · {pair[0]['domain']} · {pair[0]['phase']} ({pair[0]['visible_attribute']} visible) · "
               f"shared baseline: {pair[0]['baseline_ranking'].replace('>', ' > ')}")
        ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=15)
        _cell(ws, r, 1, hdr, F_HEAD, FILL_HEAD, align=Alignment(vertical="center"))
        ws.row_dimensions[r].height = 20
        for x, c0 in zip(pair, (1, 8)):       # probe 1 in columns A–F, probe 2 in H–M
            src = x["row"]
            comp = x["probe_type"] == "Competence"
            what = (f"animal {x['target']}'s competence" if comp else f"synergy of pair {x['target']}")
            cap = (f"Probe {x['probe_pos']} ({x['slot_id']}, {x['probe_type'].lower()}): {what} "
                   f"{LEVEL[x['original_level']]} {x['original_value']:g} → {LEVEL[x['cf_level']]} {x['cf_value']:g}")
            _cell(ws, r + 1, c0, cap, F_BOLD)
            _header(ws, r + 2, c0, tcols)
            ws.row_dimensions[r + 2].height = 30
            t0 = r + 3
            Ltm, Lb, La = (get_column_letter(c0 + k) for k in range(3))
            for k in range(6):
                rr = t0 + k
                fs = [f"=MID($L${src},{6 * k + 1},3)",
                      f"=(FIND({Ltm}{rr},$L${src})-1)/6+1",
                      f"=(FIND({Ltm}{rr},$M${src})-1)/6+1",
                      f"={Lb}{rr}-{La}{rr}",
                      f'=IF(ISNUMBER(FIND({Ltm}{rr},$O${src})),"Yes","")',
                      f'=COUNTIFS(${Lb}${t0}:${Lb}${t0 + 5},">"&{Lb}{rr},${La}${t0}:${La}${t0 + 5},"<"&{La}{rr})']
                for j, f in enumerate(fs):
                    fmt = '"▲ "0;"▼ "0;"–"' if j == 3 else "0" if j in (1, 2, 5) else None
                    _cell(ws, rr, c0 + j, f, F_BOLD if j == 0 else F_BASE, fmt=fmt, align=CENTER, border=BOX)
            ws.conditional_formatting.add(
                f"{Ltm}{t0}:{get_column_letter(c0 + 5)}{t0 + 5}",
                FormulaRule(formula=[f'${get_column_letter(c0 + 4)}{t0}="Yes"'],
                            fill=FILL_COMP_HI if comp else FILL_SYN_HI, font=Font(name=FONT, bold=True)))
            Lk = get_column_letter(c0 + 5)
            kr = t0 + 6
            _cell(ws, kr, c0, "Kendall distance", F_BOLD)
            _cell(ws, kr, c0 + 5, f"=SUM({Lk}{t0}:{Lk}{t0 + 5})", F_BOLD, fmt="0", align=CENTER, border=BOX)
            _cell(ws, kr + 1, c0, f'=IF({Lk}{kr}=$N${src},"✓ matches section A","✗ differs from section A ("&$N${src}&")")',
                  F_NOTE)
            title = f"{x['slot_id']} · {x['probe_type']}: {x['target']} {x['original_value']:g} → {x['cf_value']:g} · K = {x['kendall_distance']}"
            ws.add_chart(_rank_chart(ws, x, t0, c0 + 1, title, COMP_COLOR if comp else SYN_COLOR),
                         f"{get_column_letter(c0)}{kr + 3}")
        r += 33
    ws.freeze_panes = f"B{a0 + 2}"


# ── sheet 5: Ranking Analysis ─────────────────────────────────────────────────

def ranking_analysis(ws, rows, T: Table):
    ws.sheet_view.showGridLines = False
    ws.column_dimensions["A"].width = 13
    for L in "BCDEFGHIJKLMNOPQRSTU":
        ws.column_dimensions[L].width = 11
    _cell(ws, 1, 1, "Ranking Analysis", F_TITLE)
    _cell(ws, 2, 1, "Performance(i, j, d) = S(i, j) × (C_i(d) + C_j(d)). Each probe applies one change to the "
                    "baseline (shared-baseline design). Kendall distance = number of the 15 team pairs whose order flips.", F_NOTE)
    attrs = exact_attributes()

    # A. inputs
    _cell(ws, 4, 1, "A. Inputs: attribute values by role code (from stimulus tables)", F_SECTION)
    _header(ws, 5, 1, ["Role"] + DOMAINS)
    for i, role in enumerate("ABCD", start=6):
        _cell(ws, i, 1, role, F_BOLD, align=CENTER, border=BOX)
        for j, d in enumerate(DOMAINS, start=2):
            _cell(ws, i, j, float(attrs.competence[role][d]), F_INPUT, fmt="0.0", align=CENTER, border=BOX)
    _header(ws, 5, 6, ["Pair", "Synergy"])
    for i, t in enumerate(TEAMS, start=6):
        _cell(ws, i, 6, t, F_BOLD, align=CENTER, border=BOX)
        _cell(ws, i, 7, float(attrs.synergy[(t[0], t[2])]), F_INPUT, fmt="0.0", align=CENTER, border=BOX)
    _cell(ws, 5, 9, "Near-tie threshold", F_BOLD)
    thr = _cell(ws, 6, 9, NEAR, F_INPUT, FILL_KEY, "0.00", CENTER, BOX)
    thr.comment = Comment("Provisional cut-off: an adjacent revised gap below this counts as a near-tie.", "notes")
    THR = "$I$6"

    # B. baseline
    r0 = 14
    _cell(ws, r0, 1, "B. Baseline team performance and ranking (formulas)", F_SECTION)
    _header(ws, r0 + 1, 1, ["Team"] + [f"{d} {k}" for d in DOMAINS for k in ("score", "rank")])
    for i, t in enumerate(TEAMS, start=r0 + 2):
        _cell(ws, i, 1, t, F_BOLD, align=CENTER, border=BOX)
        for k, d in enumerate(DOMAINS):
            cc = get_column_letter(2 + k)   # competence column for domain in section A
            sc = 2 + 2 * k
            f = (f"=INDEX($G$6:$G$11,MATCH($A{i},$F$6:$F$11,0))*(INDEX(${cc}$6:${cc}$9,MATCH(LEFT($A{i},1),$A$6:$A$9,0))"
                 f"+INDEX(${cc}$6:${cc}$9,MATCH(RIGHT($A{i},1),$A$6:$A$9,0)))")
            _cell(ws, i, sc, f, fmt="0.00", align=CENTER, border=BOX)
            L = get_column_letter(sc)
            _cell(ws, i, sc + 1, f"=RANK({L}{i},{L}${r0 + 2}:{L}${r0 + 7},0)", align=CENTER, border=BOX)
    gr = r0 + 9
    _header(ws, gr, 1, ["Baseline gap"] + [f"{d} gap" for d in DOMAINS])
    places = ["1st", "2nd", "3rd", "4th", "5th", "6th"]
    for g in range(1, 6):
        _cell(ws, gr + g, 1, f"g{g} ({places[g - 1]}–{places[g]})", align=CENTER, border=BOX)
        for k in range(3):
            L = get_column_letter(2 + 2 * k)
            rng = f"${L}${r0 + 2}:${L}${r0 + 7}"
            _cell(ws, gr + g, 2 + k, f"=LARGE({rng},{g})-LARGE({rng},{g + 1})", fmt="0.00", align=CENTER, border=BOX)
    _cell(ws, gr + 6, 1, "Smallest", F_BOLD, align=CENTER, border=BOX)
    for k in range(3):
        L = get_column_letter(2 + k)
        _cell(ws, gr + 6, 2 + k, f"=MIN({L}{gr + 1}:{L}{gr + 5})", F_BOLD, fmt="0.00", align=CENTER, border=BOX)
    _cell(ws, gr + 7, 1, "Baseline orders: " + "; ".join(
        f"{d}: {next(x['baseline_ranking'] for x in rows if x['domain'] == d)}" for d in DOMAINS), F_NOTE)

    # C. configuration summary
    c0 = gr + 10
    _cell(ws, c0, 1, "C. Configuration summary (formulas over 'Proposed Combinations')", F_SECTION)
    heads = ["Configuration", "Probes", "Σ|ΔK| over blocks", "Blocks with ΔK = 0", "Mean K competence",
             "Mean K synergy", "Mean smallest gap competence", "Mean smallest gap synergy", "Probes with near-tie",
             "Top team changed", "Value-dependent (grid)", "High→Low", "Low→High", "MISSING IDs", "Set cost"]
    _header(ws, c0 + 1, 1, heads)
    ws.row_dimensions[c0 + 1].height = 44
    cfg, typ, pos = T.rng("config_id"), T.rng("probe_type"), T.rng("probe_pos")
    for i, cid in enumerate(CONFIGS, start=c0 + 2):
        a = f"$A{i}"
        fs = [f"=COUNTIF({cfg},{a})",
              f"=SUMIFS({T.rng('block_kendall_abs_diff')},{cfg},{a},{pos},1)",
              f"=COUNTIFS({cfg},{a},{pos},1,{T.rng('block_kendall_abs_diff')},0)",
              f'=AVERAGEIFS({T.rng("kendall_distance")},{cfg},{a},{typ},"Competence")',
              f'=AVERAGEIFS({T.rng("kendall_distance")},{cfg},{a},{typ},"Synergy")',
              f'=AVERAGEIFS({T.rng("min_adjacent_gap_revised")},{cfg},{a},{typ},"Competence")',
              f'=AVERAGEIFS({T.rng("min_adjacent_gap_revised")},{cfg},{a},{typ},"Synergy")',
              f'=COUNTIFS({cfg},{a},{T.rng("min_adjacent_gap_revised")},"<"&{THR})',
              f"=SUMIFS({T.rng('top_changed')},{cfg},{a})",
              f"=SUMIFS({T.rng('value_dependent_grid')},{cfg},{a})",
              f'=COUNTIFS({cfg},{a},{T.rng("direction")},"H->L")',
              f'=COUNTIFS({cfg},{a},{T.rng("direction")},"L->H")',
              f'=COUNTIFS({cfg},{a},{T.rng("candidate_id")},"MISSING")',
              f'=IF(INDEX({T.rng("config_set_cost")},MATCH({a},{cfg},0))="","n/a",'
              f'INDEX({T.rng("config_set_cost")},MATCH({a},{cfg},0)))']
        p1 = cid == "P1"
        _cell(ws, i, 1, cid, F_P1 if p1 else F_BOLD, FILL_P1 if p1 else None, align=CENTER, border=BOX)
        for j, f in enumerate(fs, start=2):
            fmt = "0.00" if j in (5, 6, 7, 8) else "0.000" if j == 15 else "0"
            _cell(ws, i, j, f, F_BOLD if p1 else F_BASE, FILL_P1 if p1 else None, fmt, CENTER, BOX)
    _cell(ws, c0 + 8, 1, "Near-tie counts use the threshold in I6. Set cost is the artifact's optimisation cost "
                         "(lower = better; not defined for E-a/E-b).", F_NOTE)
    summary_first = c0 + 2

    # D. P1 probes
    d0 = c0 + 11
    _cell(ws, d0, 1, "D. P1: baseline vs counterfactual ranking for each probe", F_SECTION)
    heads = ["Slot", "Block", "Domain", "Probe type", "Change", "Baseline ranking", "Revised ranking",
             "Kendall distance", "Footrule", "g1", "g2", "g3", "g4", "g5", "Smallest gap", "Near-ties",
             "Baseline top", "Revised top", "Top changed", "Moved to 1st"]
    _header(ws, d0 + 1, 1, heads)
    ws.row_dimensions[d0 + 1].height = 30
    ws.column_dimensions["F"].width = 26
    ws.column_dimensions["G"].width = 26
    p1 = sorted((x for x in rows if x["config_id"] == "P1"), key=lambda x: (x["block_id"], x["probe_pos"]))
    first = d0 + 2
    for i, x in enumerate(p1, start=first):
        change = f"{x['target']} {x['original_value']:g} → {x['cf_value']:g} ({x['direction']})"
        vals = [x["slot_id"], x["block_id"], x["domain"], x["probe_type"], change,
                x["baseline_ranking"].replace(">", " > "), x["revised_ranking"].replace(">", " > "),
                x["kendall_distance"], x["footrule"]] + [x[f"gap_g{g}"] for g in range(1, 6)] + [
                f"=MIN(J{i}:N{i})", f'=COUNTIF(J{i}:N{i},"<"&{THR})',
                x["baseline_top"], x["revised_top"], f"=IF(Q{i}<>R{i},1,0)", x["affected_moved_to_first"] or "—"]
        for j, v in enumerate(vals, start=1):
            fmt = "0.00" if 10 <= j <= 15 else None
            al = Alignment(vertical="center", wrap_text=True) if j in (5, 6, 7) else CENTER
            _cell(ws, i, j, v, F_BOLD if j == 15 else F_BASE, FILL_P1, fmt, al, BOX)
    last = first + len(p1) - 1
    _cell(ws, last + 1, 1, "g1…g5 = adjacent score gaps in the revised ranking (1st–2nd … 5th–6th). "
                           "Near-ties counts gaps below the threshold in I6.", F_NOTE)

    # E. chart data
    e0 = last + 4
    _cell(ws, e0, 1, "E. Chart data: competence vs synergy probes", F_SECTION)
    _header(ws, e0 + 1, 1, ["P1 block", "K competence", "K synergy", "Smallest gap competence", "Smallest gap synergy"])
    ws.row_dimensions[e0 + 1].height = 30
    for k, b in enumerate(range(6), start=e0 + 2):
        dom = DOMAINS[b % 3]
        _cell(ws, k, 1, f"b{b} {dom}", F_BOLD, align=CENTER, border=BOX)
        for j, (col, t) in enumerate([("H", "Competence"), ("H", "Synergy"), ("O", "Competence"), ("O", "Synergy")], start=2):
            f = f'=SUMIFS(${col}${first}:${col}${last},$B${first}:$B${last},{b},$D${first}:$D${last},"{t}")'
            _cell(ws, k, j, f, fmt="0.00" if col == "O" else "0", align=CENTER, border=BOX)
    _header(ws, e0 + 1, 7, ["Configuration", "Mean K competence", "Mean K synergy",
                            "Mean smallest gap competence", "Mean smallest gap synergy"])
    for k, cid in enumerate(CONFIGS):
        rr, sr = e0 + 2 + k, summary_first + k
        p1 = cid == "P1"
        _cell(ws, rr, 7, f"=A{sr}", F_P1 if p1 else F_BOLD, FILL_P1 if p1 else None, align=CENTER, border=BOX)
        for j, src in enumerate("EFGH", start=8):
            _cell(ws, rr, j, f"={src}{sr}", fill=FILL_P1 if p1 else None, fmt="0.00", align=CENTER, border=BOX)

    # charts
    ch0 = e0 + 10
    _cell(ws, ch0 - 1, 1, "F. Charts (blue = competence probe, orange = synergy probe)", F_SECTION)
    cats = Reference(ws, min_col=1, min_row=e0 + 2, max_row=e0 + 7)
    cfg_cats = Reference(ws, min_col=7, min_row=e0 + 2, max_row=e0 + 7)
    specs = [
        ("P1: Kendall distance by block", "Kendall distance (pairs flipped)", "Block", 2, cats, "0"),
        ("P1: smallest adjacent score gap by block", "Smallest revised gap", "Block", 4, cats, "0.00"),
        ("All configurations: mean Kendall distance", "Mean Kendall distance", "Configuration", 8, cfg_cats, "0.0"),
        ("All configurations: mean smallest score gap", "Mean smallest revised gap", "Configuration", 10, cfg_cats, "0.00"),
    ]
    for n, (title, yt, xt, col, cat_ref, fmt) in enumerate(specs):
        ch = BarChart()
        ch.type = "col"
        data = Reference(ws, min_col=col, max_col=col + 1, min_row=e0 + 1, max_row=e0 + 7)
        ch.add_data(data, titles_from_data=True)
        ch.set_categories(cat_ref)
        _style_chart(ch, title, yt, xt)
        for s in ch.series:
            s.dLbls.numFmt = fmt
        ch.y_axis.number_format = fmt
        ch.y_axis.scaling.min = 0
        anchor = f"{'A' if n % 2 == 0 else 'J'}{ch0 + (n // 2) * 17}"
        ws.add_chart(ch, anchor)
    _cell(ws, ch0 + 34, 1, "Gap charts: the smallest adjacent gap in the revised ranking; lower = closer to a tie "
                           f"(near-tie threshold {NEAR}). In P1 the competence and synergy probes have equal K in "
                           "cooking and tennis blocks; repairing blocks differ by 2 (K 5 vs 3).", F_NOTE)
    ws.freeze_panes = "B4"
    return summary_first


# ── sheet 5: Selection Rationale ──────────────────────────────────────────────

def rationale(ws, summary_first):
    ws.sheet_view.showGridLines = False
    ws.column_dimensions["A"].width = 3
    ws.column_dimensions["B"].width = 30
    for L in "CDEFGH":
        ws.column_dimensions[L].width = 14
    _cell(ws, 1, 2, "Selection Rationale: configuration P1", F_TITLE)
    _cell(ws, 2, 2, "P1 is a configuration ID (proposal 1, distance-matched), not experimental phase_1.", F_NOTE)

    def long(row, text, height, font=F_BASE, fill=None):
        ws.merge_cells(start_row=row, start_column=2, end_row=row, end_column=8)
        _cell(ws, row, 2, text, font, fill, align=WRAP)
        ws.row_dimensions[row].height = height
        return row + 1

    r = long(4, "Objective: to investigate how participants use learned representations of individual (competence) and "
                "relational (synergy) attributes to update their rankings under uncertainty, not simply to measure exact "
                "ranking accuracy. The key requirement is therefore that the two probes in each block are comparable.",
             44, F_BOLD, FILL_KEY)

    _cell(ws, r + 1, 2, "Key metrics (linked to Ranking Analysis, section C)", F_SECTION)
    r += 2
    heads = ["Configuration", "Σ|ΔK|", "Blocks ΔK = 0", "Near-tie probes", "Top changed", "Value-dependent", "MISSING IDs"]
    src_cols = ["A", "C", "D", "I", "J", "K", "N"]
    _header(ws, r, 2, heads)
    ws.row_dimensions[r].height = 30
    for k, cid in enumerate(CONFIGS):
        rr, sr = r + 1 + k, summary_first + k
        p1 = cid == "P1"
        for j, L in enumerate(src_cols):
            _cell(ws, rr, 2 + j, f"='Ranking Analysis'!{L}{sr}", F_P1 if p1 else (F_BOLD if j == 0 else F_BASE),
                  FILL_P1 if p1 else None, align=CENTER, border=BOX)
    r += 8

    _cell(ws, r, 2, "Why P1 was selected", F_SECTION)
    r += 1
    for text in [
        "1. Identical Kendall distances in 4 of 6 blocks. In the cooking and tennis blocks (b0, b2, b3, b5) both probes have "
        "K = 3, so a within-block competence-vs-synergy difference is not confounded with how much the correct ranking "
        "changes. P1 has the lowest total mismatch of the proposals (Σ|ΔK| = 4; P2 13, P3 5, P4 8, E-a 5, E-b 4).",
        "2. Balanced direction. 6 High→Low and 6 Low→High changes: 3/3 for each attribute and 3/3 within each experimental "
        "phase. Direction is not confounded with attribute type or with which attribute is visible.",
        "3. Original stimulus tables preserved. Every P1 value already occurs in the tables, so no table edits are needed "
        "and trials, estimate items and the forced-first schedule stay valid. All 12 P1 probes have a cf candidate ID. "
        "E-a and E-b need values outside the enumerated set (8 MISSING IDs).",
        "4. No alternative clearly beats it with the current tables. E-a and E-b reduce near-ties (4 and 3 vs 6), but E-a "
        "has a worse Kendall/footrule match and E-b repeats target D across domains. Neither makes the repairing or "
        "tennis competence probes value-robust.",
    ]:
        r = long(r, text, 44)

    _cell(ws, r + 1, 2, "Remaining limitations", F_SECTION)
    r += 2
    for text, fill in [
        ("1. Kendall mismatch in the two repairing blocks (b1, b4). The competence probe is B High→Low with K = 5; no "
         "repairing synergy probe exceeds K = 3, so ΔK = 2 in both blocks. Repairing has only two High/Low animals "
         "(B High, D Low), and D Low→High is value-dependent, so B is the only usable target and is reused (2.2 in b1, "
         "2.1 in b4). Tennis also reuses B (7.5 in b2, 7.7 in b5).", None),
        ("2. Value-dependent correct rankings. Participants see only the level, not the hidden value. Over the grid "
         "Low 1.0–3.0 / High 6.1–9.0, 4 of 6 competence probes give more than one correct ranking: repairing B→Low "
         "(b1, b4) 5 rankings, modal ≈ 33–35%; tennis B→High (b2, b5) 2 rankings, modal ≈ 87–89%. Within the values the "
         "tables actually use, all six are robust. Scoring against a single ranking should be treated with caution.", None),
        ("3. Near-ties (adjacent revised gap < 0.5) in 6 of 12 probes: b1 competence 0.18, b2 synergy 0.14, b2 competence "
         "0.34, b4 competence 0.12, b5 competence 0.34, b5 synergy 0.08; both b0 probes sit exactly at 0.50. The tennis "
         "near-ties come from the baseline (A+C vs C+D differ by 0.34). The 0.5 cut-off is provisional.", None),
        ("4. Most changes move the top team: 11 of 12 probes change the top-ranked team and 6 move the changed team to "
         "1st place. The top position is a salient cue; participants may update mainly the top rather than the full order.", None),
        ("5. Repeated counterfactual change in Group B (potential limitation). Both tennis competence probes change the "
         "role-B animal from Low to High (b2: 2.0 → 7.5, b5: 2.0 → 7.7) and produce the same revised ranking "
         "(B+D > A+C > C+D > B+C > A+B > A+D). With Group B order (1, 0, 3, 2, 5, 4), the two tennis blocks are presented "
         "consecutively (positions 4 and 5), and the two identical updates are adjacent probes (b2 probe 2, then b5 "
         "probe 1). This may introduce carryover, repetition or strategy-transfer effects (reusing the previous answer "
         "or recognising the change rather than reasoning from the learned attributes), although different animal sets "
         "are used across blocks. This is a potential limitation, not an established effect; it can be examined by "
         "comparing b5 responses between groups. Note: the current code (commit 194ffb0) sets Group B = "
         f"{S.BLOCK_ORDERS['B']}, which places the tennis blocks 3 positions apart (as in Group A); the final Group B "
         "order should be confirmed before data collection. The two repairing competence probes (B High→Low) also share "
         "a revised ranking.", FILL_KEY),
    ]:
        r = long(r, text, 100 if fill else 58, fill=fill)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--out', type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    rows = load_rows()
    assert len(rows) == 72 and sum(r["config_id"] == "P1" for r in rows) == 12
    wb = Workbook()
    ws_over = wb.active
    ws_over.title = "Overview"
    ws_pc = wb.create_sheet("Proposed Combinations")
    ws_p1 = wb.create_sheet("Selected P1")
    ws_ba = wb.create_sheet(BA_SHEET)
    ws_ra = wb.create_sheet("Ranking Analysis")
    ws_sr = wb.create_sheet("Selection Rationale")
    ws_p1.sheet_properties.tabColor = "FFC000"
    ws_ba.sheet_properties.tabColor = "FFC000"

    p1_rows = load_p1_rows()
    assert [(x["slot_id"], x["candidate_id"], x["revised_ranking"]) for x in p1_rows] == [
        (x["slot_id"], x["candidate_id"], x["revised_ranking"])
        for x in sorted((x for x in rows if x["config_id"] == "P1"), key=lambda x: (x["block_id"], x["probe_pos"]))]

    table = Table(ws_pc, rows)
    overview(ws_over, rows)
    selected_p1(ws_p1, rows)
    before_after_p1(ws_ba, p1_rows)
    summary_first = ranking_analysis(ws_ra, rows, table)
    rationale(ws_sr, summary_first)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    wb.save(args.out)
    print(f"Written: {args.out}")


if __name__ == '__main__':
    main()
