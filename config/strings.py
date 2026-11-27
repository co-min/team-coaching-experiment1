"""
Centralized participant-facing text (Korean / English).

Language is picked from settings.MODE_ENG at call time.
"""

from config import settings


def _lang() -> str:
    return "en" if settings.MODE_ENG else "ko"


# ── generic key -> {lang: template} ───────────────────────────────────────────

_STRINGS: dict[str, dict[str, str]] = {
    "inst_phase1": {
        "ko": "[{block_num} / {total_blocks}]\n\n"
              "이번 단계에서, 각자 수행하는 능력이 보여요.\n"
              "숨겨진 팀워크를 생각하면서 만점인 동물 두 마리를 찾아볼까요?{forced_note}\n\n"
              "[Space] 키를 눌러 시작",
        "en": "[{block_num} / {total_blocks}]\n\n"
              "In this phase, you can see each animal's individual performance.\n"
              "Think about their hidden teamwork and find the two animals with a perfect score.{forced_note}\n\n"
              "Press [Space] to start",
    },
    "inst_phase2": {
        "ko": "[{block_num} / {total_blocks} 블록]\n\n"
              "이번 단계에서, 협력하는 팀워크가 보여요.\n"
              "숨겨진 수행하는 능력을 예상하면서 만점인 동물 두 마리를 찾아볼까요?{forced_note}\n\n"
              "[Space] 키를 눌러 시작",
        "en": "[Block {block_num} / {total_blocks}]\n\n"
              "In this phase, you can see how well the animals cooperate.\n"
              "Guess their hidden individual performance and find the two animals with a perfect score.{forced_note}\n\n"
              "Press [Space] to start",
    },
    # Inserted into inst_phase1/2 as {forced_note} only when FIRST_CHOICE_MODE == 'forced'
    "inst_forced_note": {
        "ko": "\n첫 번째 동물은 미리 정해져 있어요. 나머지 세 마리 중에서 짝꿍을 골라 주세요.",
        "en": "\nThe first animal is assigned for you. Choose its partner from the other three.",
    },
    "inst_break": {
        "ko": "잠시 휴식 시간입니다.\n\n준비가 되면 실험자가 실험을 재개합니다.",
        "en": "Take a short break.\n\nThe experimenter will resume the task when you are ready.",
    },

    # ── ending screen ────────────────────────────────────────────────────────
    "ending_title":              {"ko": "게임이 끝났습니다!", "en": "The game is over!"},
    "ending_subtitle":           {"ko": "수고하셨습니다.", "en": "Well done!"},
    "ending_leaderboard_header": {"ko": "순위표  (정답률 기준)", "en": "Leaderboard  (by accuracy)"},
    "ending_me_tag":             {"ko": "  ← 나", "en": "  ← Me"},
    "ending_rank_label":         {"ko": "{rank}위", "en": "#{rank}"},
    "ending_stats": {
        "ko": "정답률  {accuracy}   ·   총 점수  {score}점   ·   소요시간  {elapsed}",
        "en": "Accuracy  {accuracy}   ·   Total Score  {score}   ·   Elapsed  {elapsed}",
    },
    "ending_rank_summary": {"ko": "전체 {total}명 중  {rank}위", "en": "Rank {rank} of {total}"},
    "ending_exit_prompt":  {"ko": "[ Space ] 키를 눌러 종료", "en": "Press [ Space ] to exit"},
    "ending_elapsed_fmt":  {"ko": "{m}분 {s:02d}초", "en": "{m}m {s:02d}s"},

    # ── feedback screen ──────────────────────────────────────────────────────
    "feedback_bubble": {
        "ko": "{score}점이야.",
        "en": "{score} points.",
    },
    "feedback_domain_score": {"ko": "{domain}: {score}점", "en": "{domain}: {score} pts"},
    "feedback_block_score":  {"ko": "블록 점수: {score}점", "en": "Block score: {score}"},
    "feedback_total_score":  {"ko": "총 점수: {score}점", "en": "Total score: {score}"},

    # ── attribute estimate (task/estimate) ───────────────────────────────────
    "estimate_intro_synergy": {
        "ko": "{checkpoint}\n\n지금까지의 게임을 떠올리며\n두 동물이 함께할 때의 팀워크가 어느 정도인지 평가해 주세요.\n\n"
              "{low} 낮음    {mid} 보통    {high} 높음\n고른 뒤 [{confirm}] 키로 확정해요.\n\n[{confirm}] 키를 눌러 시작",
        "en": "{checkpoint}\n\nThinking back on the games so far,\nrate the synergy of each pair of animals.\n\n"
              "{low} Low    {mid} Medium    {high} High\nThen press [{confirm}] to confirm.\n\nPress [{confirm}] to start",
    },
    "estimate_intro_competence": {
        "ko": "{checkpoint}\n\n지금까지의 게임을 떠올리며\n각 동물 한 마리의 실력이 어느 정도인지 평가해 주세요.\n\n"
              "{low} 낮음    {mid} 보통    {high} 높음\n고른 뒤 [{confirm}] 키로 확정해요.\n\n[{confirm}] 키를 눌러 시작",
        "en": "{checkpoint}\n\nThinking back on the games so far,\nrate the competence of each animal on its own.\n\n"
              "{low} Low    {mid} Medium    {high} High\nThen press [{confirm}] to confirm.\n\nPress [{confirm}] to start",
    },
    "estimate_checkpoint_middle": {"ko": "중간 평가", "en": "Middle estimate"},
    "estimate_checkpoint_end":    {"ko": "마지막 평가", "en": "End estimate"},
    "estimate_title_synergy":     {"ko": "팀워크 평가", "en": "SYNERGY ESTIMATE"},
    "estimate_title_competence":  {"ko": "실력 평가", "en": "COMPETENCE ESTIMATE"},
    "estimate_counter_pair":      {"ko": "팀 {n} / {total}", "en": "Pair {n} / {total}"},
    "estimate_counter_animal":    {"ko": "동물 {n} / {total}", "en": "Animal {n} / {total}"},
    "estimate_question_synergy": {
        "ko": "이 두 동물의 팀워크는 어느 정도일까요?",
        "en": "How would you rate the synergy\nbetween these animals?",
    },
    "estimate_question_competence": {
        "ko": "이 동물의 {domain} 실력은 어느 정도일까요?",
        "en": "How would you rate this animal's\ncompetence in {domain}?",
    },
    "estimate_level_low":  {"ko": "낮음", "en": "LOW"},
    "estimate_level_mid":  {"ko": "보통", "en": "MEDIUM"},
    "estimate_level_high": {"ko": "높음", "en": "HIGH"},
    "estimate_hint_choose":  {"ko": "{low} {mid} {high} 키로 고르세요", "en": "Choose with {low} {mid} {high}"},
    "estimate_hint_confirm": {"ko": "[{confirm}] 확정", "en": "[{confirm}] Confirm"},
}


def t(key: str, **kwargs) -> str:
    """Look up a localized string by key, formatting with kwargs if given."""
    template = _STRINGS[key][_lang()]
    return template.format(**kwargs) if kwargs else template


# ── domain display names ──────────────────────────────────────────────────────

_DOMAIN_NAMES = {
    "cooking":   {"ko": "요리", "en": "Cooking"},
    "repairing": {"ko": "수리", "en": "Repairing"},
    "tennis":    {"ko": "테니스", "en": "Tennis"},
}


def domain_name(domain: str) -> str:
    return _DOMAIN_NAMES.get(domain, {}).get(_lang(), domain)
