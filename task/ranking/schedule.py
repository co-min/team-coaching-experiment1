"""
schedule.py
-----------
블록별 performance 순위 도메인 스케줄을 검사합니다.

    ranking_domain           이 블록의 순위 도메인
    ranking_domain_problems  스케줄 자체의 균형 검사 (실행 전)
    saved_ranking_problems   저장된 rankings.csv 행이 스케줄을 따랐는지 검사 (실행 후)

스케줄 규칙 (블록 6개, 도메인 3개 기준)
    1. 블록 수 = 과제의 블록 수
    2. 모르는 도메인이 없음
    3. 각 도메인은 phase 마다 같은 횟수(phase_1 에 1번, phase_2 에 1번) 나옴
       → phase 마다 맞으면 전체 횟수(2번)도 저절로 맞습니다.
    4. 같은 도메인이 연속한 두 블록에 나오지 않음

저장 데이터 규칙 (행 하나씩)
    - 행의 도메인·phase 가 그 블록의 스케줄과 같음
    - 수정(revised) 순위가 자기 기준(baseline) 순위와 같은 도메인
    - competence 변화는 순위 도메인의 실력을 바꿈, synergy 변화는 도메인이 없음

검사 함수는 모두 "문제 문장의 목록"을 돌려줍니다. 빈 목록이면 통과입니다.
psychopy를 쓰지 않으므로 테스트에서 창 없이 import할 수 있습니다.
"""

from typing import List, Mapping, Optional, Sequence

from config.ranking import PERFORMANCE_RANKING_DOMAINS


def ranking_domain(block_index: int) -> str:
    """이 블록의 performance 순위 도메인."""
    return PERFORMANCE_RANKING_DOMAINS[block_index]


# ── 스케줄 검사 (실행 전) ─────────────────────────────────────────────────────

def ranking_domain_problems(schedule: Sequence[str], phases: Sequence[str],
                            domains: Sequence[str]) -> List[str]:
    """스케줄이 규칙을 어기는 곳을 문장 목록으로 돌려줍니다. 빈 목록이면 통과.

    schedule : 블록별 순위 도메인 (예: PERFORMANCE_RANKING_DOMAINS)
    phases   : 블록별 phase (settings.BLOCK_PHASES)
    domains  : 과제의 도메인 목록 (settings.DOMAINS)
    """
    # 규칙 1: 블록 수가 다르면 나머지 검사는 의미가 없으므로 바로 돌려줍니다.
    if len(schedule) != len(phases):
        return [f"schedule has {len(schedule)} blocks, task has {len(phases)}"]

    problems = []
    problems += _unknown_domain_problems(schedule, domains)        # 규칙 2
    problems += _phase_count_problems(schedule, phases, domains)   # 규칙 3
    problems += _back_to_back_problems(schedule)                   # 규칙 4
    return problems


def _unknown_domain_problems(schedule: Sequence[str], domains: Sequence[str]) -> List[str]:
    """규칙 2: 과제에 없는 도메인 이름이 있는지."""
    unknown = []
    for domain in schedule:
        if domain not in domains and domain not in unknown:
            unknown.append(domain)

    if unknown:
        return [f"unknown domains {sorted(unknown)}"]
    return []


def _phase_count_problems(schedule: Sequence[str], phases: Sequence[str],
                          domains: Sequence[str]) -> List[str]:
    """규칙 3: phase 마다 각 도메인이 같은 횟수 나오는지 (phase 당 3블록 ÷ 3도메인 = 1번)."""
    problems = []
    n_domains = len(domains)

    for phase in sorted(set(phases)):
        # 이 phase 에 속한 블록들의 도메인만 모읍니다.
        domains_in_phase = []
        for block_index in range(len(schedule)):
            if phases[block_index] == phase:
                domains_in_phase.append(schedule[block_index])

        n_blocks = len(domains_in_phase)
        if n_blocks % n_domains != 0:
            problems.append(f"{phase}: {n_blocks} blocks cannot be split evenly over {n_domains} domains")

        expected = n_blocks // n_domains
        for domain in domains:
            actual = domains_in_phase.count(domain)
            if actual != expected:
                problems.append(f"domain {domain}: {actual} {phase} blocks, expected {expected}")
    return problems


def _back_to_back_problems(schedule: Sequence[str]) -> List[str]:
    """규칙 4: 같은 도메인이 연속한 두 블록에 나오지 않는지."""
    problems = []
    for block_index in range(1, len(schedule)):
        previous_domain = schedule[block_index - 1]
        current_domain = schedule[block_index]
        if current_domain == previous_domain:
            problems.append(f"blocks {block_index - 1} and {block_index} both use {current_domain}")
    return problems


# ── 저장 데이터 검사 (실행 후) ────────────────────────────────────────────────

def saved_ranking_problems(rows: Sequence[Mapping[str, str]], schedule: Sequence[str],
                           phases: Sequence[str]) -> List[str]:
    """rankings.csv 의 행들이 스케줄을 따랐는지 검사합니다. 빈 목록이면 통과.

    rows : csv.DictReader 로 읽은 rankings.csv 행 (모든 값은 문자열, None 은 빈 칸 '')
    일부 블록만 실행했어도 저장된 행만 검사하므로 그대로 쓸 수 있습니다.
    """
    problems = []

    # 수정 순위에서 자기 기준 순위를 찾을 수 있도록 ranking_id 로 찾아보는 사전을 만듭니다.
    rows_by_id = {}
    for row in rows:
        rows_by_id[row['ranking_id']] = row

    for row in rows:
        block_index = _block_index_or_none(row, len(schedule))
        if block_index is None:
            problems.append(f"{row['ranking_id']}: block_index {row['block_index']!r} "
                            f"is not a block of the schedule (0–{len(schedule) - 1})")
            continue

        problems += _block_match_problems(row, block_index, schedule, phases)
        if row['ranking_type'] == 'counterfactual':
            problems += _revised_row_problems(row, rows_by_id)
    return problems


def _block_index_or_none(row: Mapping[str, str], n_blocks: int) -> Optional[int]:
    """행의 block_index 를 정수로 돌려줍니다. 숫자가 아니거나 스케줄 범위 밖이면 None."""
    text = row['block_index']
    if not text.isdigit():          # '' 나 '-1' 처럼 0 이상의 정수가 아닌 값
        return None
    block_index = int(text)
    if block_index >= n_blocks:
        return None
    return block_index


def _block_match_problems(row: Mapping[str, str], block_index: int,
                          schedule: Sequence[str], phases: Sequence[str]) -> List[str]:
    """행의 phase·도메인이 그 블록의 스케줄과 같은지."""
    problems = []
    ranking_id = row['ranking_id']
    expected_phase = phases[block_index]
    expected_domain = schedule[block_index]

    if row['phase'] != expected_phase:
        problems.append(f"{ranking_id}: phase {row['phase']!r}, block {block_index} is {expected_phase!r}")
    if row['domain'] != expected_domain:
        problems.append(f"{ranking_id}: domain {row['domain']!r}, "
                        f"block {block_index} is scheduled for {expected_domain!r}")
    return problems


def _revised_row_problems(row: Mapping[str, str], rows_by_id: Mapping[str, Mapping[str, str]]) -> List[str]:
    """수정(counterfactual) 순위 행 하나: 기준 순위와 같은 도메인인지, 가상 변화의 도메인이 맞는지."""
    problems = []
    ranking_id = row['ranking_id']

    # 기준 순위와 같은 도메인인지
    baseline = rows_by_id.get(row['baseline_id'])
    if baseline is None:
        problems.append(f"{ranking_id}: baseline {row['baseline_id']!r} not saved")
    elif baseline['domain'] != row['domain']:
        problems.append(f"{ranking_id}: domain {row['domain']!r}, its baseline uses {baseline['domain']!r}")

    # competence 변화 → 순위 도메인의 실력을 바꿔야 함
    if row['change_kind'] == 'competence' and row['change_domain'] != row['domain']:
        problems.append(f"{ranking_id}: competence change on {row['change_domain']!r}, "
                        f"ranking domain is {row['domain']!r}")

    # synergy 변화 → 도메인이 없어야 함 (CSV 에서는 빈 칸)
    if row['change_kind'] == 'synergy' and row['change_domain'] != '':
        problems.append(f"{ranking_id}: synergy change has a domain {row['change_domain']!r}")
    return problems
