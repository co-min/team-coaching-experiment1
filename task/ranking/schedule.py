"""
schedule.py
-----------
블록별 performance 순위 도메인과 probe 순서 스케줄을 검사합니다.

    ranking_domain           이 블록의 순위 도메인
    probe_order              이 블록의 probe 순서 (예: ('competence', 'synergy'))
    ranking_domain_problems  도메인 스케줄 자체의 균형 검사 (실행 전)
    probe_order_problems     probe 순서 스케줄 자체의 균형 검사 (실행 전)
    saved_ranking_problems   저장된 rankings.csv 행이 스케줄을 따랐는지 검사 (실행 후)

두 스케줄 모두 "원래 블록 번호"로 찾습니다. 제시 순서(그룹 A/B)와 상관없습니다.

도메인 스케줄 규칙 (블록 6개, 도메인 3개 기준)
    1. 블록 수 = 과제의 블록 수
    2. 모르는 도메인이 없음
    3. 각 도메인은 phase 마다 같은 횟수(phase_1 에 1번, phase_2 에 1번) 나옴
       → phase 마다 맞으면 전체 횟수(2번)도 저절로 맞습니다.
    4. 같은 도메인이 연속한 두 블록에 나오지 않음 (원래 블록 번호 순서 기준)

probe 순서 규칙
    1. 블록 수 = 과제의 블록 수
    2. 각 블록의 순서는 competence, synergy 를 한 번씩 담음
    3. 각 속성이 먼저 나오는 블록 수가 같음 (3 / 3)
    4. 각 phase 에서 두 순서가 모두 나옴 (순서가 phase 와 겹치지 않음)
    5. 각 순위 도메인에서 두 순서가 모두 나옴

저장 데이터 규칙 (행 하나씩)
    - 행의 도메인·phase 가 그 블록의 스케줄과 같음
    - 블록마다 기준(baseline) 순위는 하나, baseline_id 는 자기 자신, probe 순서가 스케줄과 같음
    - 수정(revised) 순위는
        같은 블록의 완료된 기준 순위를 가리킴, 같은 도메인
        출발 순위(initial_ranking) = 기준 순위의 최종 순위 (두 probe 모두)
        probe_pos 의 속성(change_kind)이 그 블록의 probe 순서와 같음, (블록, probe_pos) 마다 하나
        competence 변화는 순위 도메인의 실력을 바꿈, synergy 변화는 도메인이 없음

검사 함수는 모두 "문제 문장의 목록"을 돌려줍니다. 빈 목록이면 통과입니다.
psychopy를 쓰지 않으므로 테스트에서 창 없이 import할 수 있습니다.
"""

from typing import Dict, List, Mapping, Optional, Sequence, Tuple

from config.ranking import PERFORMANCE_RANKING_DOMAINS, PROBE_KINDS, PROBE_ORDERS


def ranking_domain(block_index: int) -> str:
    """이 블록의 performance 순위 도메인."""
    return PERFORMANCE_RANKING_DOMAINS[block_index]


def probe_order(block_index: int) -> Tuple[str, ...]:
    """이 블록의 probe 순서: (probe 1 의 속성, probe 2 의 속성)."""
    return tuple(PROBE_ORDERS[block_index])


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


def probe_order_problems(orders: Sequence[Sequence[str]], phases: Sequence[str],
                         domain_schedule: Sequence[str], kinds: Sequence[str] = PROBE_KINDS) -> List[str]:
    """probe 순서 스케줄이 규칙을 어기는 곳을 문장 목록으로 돌려줍니다. 빈 목록이면 통과.

    orders          : 블록별 probe 순서 (예: PROBE_ORDERS)
    phases          : 블록별 phase (settings.BLOCK_PHASES)
    domain_schedule : 블록별 순위 도메인 (PERFORMANCE_RANKING_DOMAINS)
    """
    # 규칙 1
    if len(orders) != len(phases) or len(orders) != len(domain_schedule):
        return [f"probe orders have {len(orders)} blocks, task has {len(phases)}, "
                f"domain schedule has {len(domain_schedule)}"]

    # 규칙 2: 나머지 규칙은 순서가 올바른 블록만 셉니다.
    problems = []
    first_kind_by_block = {}
    for block_index, order in enumerate(orders):
        if sorted(order) != sorted(kinds):
            problems.append(f"block {block_index}: probe order {list(order)} is not one of each {list(kinds)}")
        else:
            first_kind_by_block[block_index] = order[0]

    # 규칙 3
    first_kinds = list(first_kind_by_block.values())
    counts = {kind: first_kinds.count(kind) for kind in kinds}
    if len(set(counts.values())) > 1:
        problems.append(f"unbalanced first probe: {counts}")

    # 규칙 4, 5: phase 별, 도메인 별로 먼저 나오는 속성이 모두 다른 값을 갖는지
    for label, block_labels in (('phase', phases), ('domain', domain_schedule)):
        firsts_by_label: Dict[str, set] = {}
        for block_index, first_kind in first_kind_by_block.items():
            firsts_by_label.setdefault(block_labels[block_index], set()).add(first_kind)
        for value, firsts in sorted(firsts_by_label.items()):
            if firsts != set(kinds):
                problems.append(f"{label} {value}: every block is {sorted(firsts)[0]}-first "
                                f"(order confounded with {label})")
    return problems


# ── 저장 데이터 검사 (실행 후) ────────────────────────────────────────────────

def saved_ranking_problems(rows: Sequence[Mapping[str, str]], schedule: Sequence[str],
                           phases: Sequence[str], probe_orders: Sequence[Sequence[str]]) -> List[str]:
    """rankings.csv 의 행들이 스케줄을 따랐는지 검사합니다. 빈 목록이면 통과.

    rows : csv.DictReader 로 읽은 rankings.csv 행 (모든 값은 문자열, None 은 빈 칸 '')
    일부 블록만 실행했어도 저장된 행만 검사하므로 그대로 쓸 수 있습니다.
    """
    problems = []

    # 수정 순위에서 자기 기준 순위를 찾을 수 있도록 ranking_id 로 찾아보는 사전을 만듭니다.
    rows_by_id = {}
    for row in rows:
        rows_by_id[row['ranking_id']] = row

    baselines_per_block: Dict[int, int] = {}
    revised_per_probe: Dict[Tuple[int, str], int] = {}

    for row in rows:
        block_index = _block_index_or_none(row, len(schedule))
        if block_index is None:
            problems.append(f"{row['ranking_id']}: block_index {row['block_index']!r} "
                            f"is not a block of the schedule (0–{len(schedule) - 1})")
            continue

        problems += _block_match_problems(row, block_index, schedule, phases)
        if row['ranking_type'] == 'performance':
            baselines_per_block[block_index] = baselines_per_block.get(block_index, 0) + 1
            problems += _baseline_row_problems(row, block_index, probe_orders)
        if row['ranking_type'] == 'counterfactual':
            key = (block_index, row['probe_pos'])
            revised_per_probe[key] = revised_per_probe.get(key, 0) + 1
            problems += _revised_row_problems(row, block_index, rows_by_id, probe_orders)

    for block_index, count in sorted(baselines_per_block.items()):
        if count > 1:
            problems.append(f"block {block_index}: {count} baseline rankings, expected one shared baseline")
    for (block_index, probe_pos), count in sorted(revised_per_probe.items()):
        if count > 1:
            problems.append(f"block {block_index}: {count} revised rankings for probe {probe_pos}")
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


def _baseline_row_problems(row: Mapping[str, str], block_index: int,
                           probe_orders: Sequence[Sequence[str]]) -> List[str]:
    """기준 순위 행 하나: 자기 자신이 공유 기준이고, probe 순서가 스케줄과 같은지."""
    problems = []
    ranking_id = row['ranking_id']
    if row['baseline_id'] != ranking_id:
        problems.append(f"{ranking_id}: baseline_id {row['baseline_id']!r} should be its own id")
    expected_order = '>'.join(probe_orders[block_index])
    if row['probe_order'] != expected_order:
        problems.append(f"{ranking_id}: probe order {row['probe_order']!r}, "
                        f"block {block_index} is scheduled for {expected_order!r}")
    return problems


def _revised_row_problems(row: Mapping[str, str], block_index: int, rows_by_id: Mapping[str, Mapping[str, str]],
                          probe_orders: Sequence[Sequence[str]]) -> List[str]:
    """수정(counterfactual) 순위 행 하나."""
    problems = []
    ranking_id = row['ranking_id']

    # 같은 블록의 완료된 공유 기준 순위에서 출발했는지
    baseline = rows_by_id.get(row['baseline_id'])
    if baseline is None:
        problems.append(f"{ranking_id}: baseline {row['baseline_id']!r} not saved")
    else:
        if baseline['ranking_type'] != 'performance' or baseline['block_index'] != row['block_index']:
            problems.append(f"{ranking_id}: baseline {row['baseline_id']!r} is not this block's baseline")
        if baseline['domain'] != row['domain']:
            problems.append(f"{ranking_id}: domain {row['domain']!r}, its baseline uses {baseline['domain']!r}")
        if baseline['status'] != 'complete':
            problems.append(f"{ranking_id}: revised after a {baseline['status']!r} baseline")
        if row['initial_ranking'] != baseline['final_ranking']:
            problems.append(f"{ranking_id}: started from {row['initial_ranking']!r}, "
                            f"shared baseline is {baseline['final_ranking']!r}")

    # probe 위치의 속성이 스케줄과 같은지
    order = probe_orders[block_index]
    probe_pos = row['probe_pos']
    if not probe_pos.isdigit() or not 1 <= int(probe_pos) <= len(order):
        problems.append(f"{ranking_id}: probe_pos {probe_pos!r} outside 1–{len(order)}")
    elif row['change_kind'] != order[int(probe_pos) - 1]:
        problems.append(f"{ranking_id}: probe {probe_pos} is {row['change_kind']!r}, "
                        f"block {block_index} is scheduled for {order[int(probe_pos) - 1]!r}")

    # competence 변화 → 순위 도메인의 실력을 바꿔야 함
    if row['change_kind'] == 'competence' and row['change_domain'] != row['domain']:
        problems.append(f"{ranking_id}: competence change on {row['change_domain']!r}, "
                        f"ranking domain is {row['domain']!r}")

    # synergy 변화 → 도메인이 없어야 함 (CSV 에서는 빈 칸)
    if row['change_kind'] == 'synergy' and row['change_domain'] != '':
        problems.append(f"{ranking_id}: synergy change has a domain {row['change_domain']!r}")
    return problems
