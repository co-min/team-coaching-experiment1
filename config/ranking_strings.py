"""
Participant-facing text for the ranking assessments (Korean / English).

Same lookup as config/strings.py; merged into it at integration time.
"""

from config.strings import _lang

_STRINGS: dict[str, dict[str, str]] = {
    # ── intro screens ────────────────────────────────────────────────────────
    "rank_intro_performance": {
        "ko": "이번 블록의 게임이 끝났어요.\n이제 팀 점수를 예상해서 순위를 매겨 주세요.\n\n[{key}] 키를 눌러 시작",
        "en": "The games in this block are over.\nNow rank the teams by the score you expect.\n\nPress [{key}] to start",
    },

    # ── prompts (top of the ranking screen) ──────────────────────────────────
    "rank_prompt_performance": {
        "ko": "{domain} 점수 순위를 매겨 주세요.\n점수가 가장 높을 팀부터 고르세요.",
        "en": "Rank the teams by their {domain} score.\nStart with the highest-scoring team.",
    },
    "rank_prompt_revised": {
        "ko": "오른쪽의 변화가 일어난다면 {domain} 점수 순위는 어떻게 될까요?\n그대로 두거나 순서를 바꿀 수 있어요.",
        "en": "If the change on the right happened, how would the {domain} ranking look?\nKeep it or change the order.",
    },

    # ── column headers / rank labels ─────────────────────────────────────────
    "rank_header_ranking": {"ko": "나의 순위", "en": "Your ranking"},
    "rank_header_options": {"ko": "선택지", "en": "Options"},
    "rank_label":          {"ko": "{n}위", "en": "#{n}"},
    "rank_top_caption":    {"ko": "가장 높음", "en": "highest"},
    "rank_bottom_caption": {"ko": "가장 낮음", "en": "lowest"},

    # ── key hints (bottom of the screen) ─────────────────────────────────────
    "hint_sequential": {
        "ko": "{up} {down} 이동    ·    {select} 선택    ·    {undo} 취소",
        "en": "{up} {down} move    ·    {select} choose    ·    {undo} undo",
    },
    "hint_sequential_done": {
        "ko": "{confirm} 순위 확정    ·    {undo} 다시 고르기",
        "en": "{confirm} confirm ranking    ·    {undo} undo",
    },
    "hint_revised": {
        "ko": "{up} {down} 이동    ·    {select} 집기    ·    {undo} 되돌리기    ·    {confirm} 제출",
        "en": "{up} {down} move    ·    {select} pick up    ·    {undo} undo    ·    {confirm} submit",
    },
    "hint_revised_held": {
        "ko": "{up} {down} 위치 옮기기    ·    {select} 내려놓기",
        "en": "{up} {down} move this team    ·    {select} put down",
    },
    "rank_confirmed": {"ko": "확정되었습니다", "en": "Confirmed"},

    # ── hypothetical change ──────────────────────────────────────────────────
    "change_title": {"ko": "가상의 변화", "en": "Hypothetical change"},
    "change_competence": {
        "ko": "이 동물의 {domain} 실력이 '{level}'이 된다면?",
        "en": "What if this animal's {domain} skill became {level}?",
    },
    "change_synergy": {
        "ko": "이 두 동물의 팀워크가 '{level}'이 된다면?",
        "en": "What if these two animals' teamwork became {level}?",
    },
    "change_rest_same": {
        "ko": "그 밖의 모든 것은 그대로예요.\n(이 변화는 이번 질문에만 해당돼요.)",
        "en": "Everything else stays the same.\n(This change applies to this question only.)",
    },
    "change_continue": {"ko": "[{key}] 키를 눌러 계속", "en": "Press [{key}] to continue"},

    # ── between the two probes ───────────────────────────────────────────────
    "reset_title": {"ko": "원래 상황으로", "en": "Back to the original"},
    "reset_body": {
        "ko": "방금 상상한 변화는 이제 잊어 주세요.\n모든 것이 처음 그대로예요.\n\n"
              "다음 질문은 처음에 매긴 순위에서 시작해요.",
        "en": "Forget the change you just imagined.\nEverything is as it was at the start.\n\n"
              "The next question begins from your original ranking.",
    },

    "level_low":  {"ko": "낮음", "en": "low"},
    "level_mid":  {"ko": "보통", "en": "medium"},
    "level_high": {"ko": "높음", "en": "high"},
}


def rt(name: str, /, **kwargs) -> str:
    """Look up a localized ranking string by name, formatting with kwargs if given."""
    template = _STRINGS[name][_lang()]
    return template.format(**kwargs) if kwargs else template
