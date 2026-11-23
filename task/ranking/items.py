"""
items.py
--------
순위를 매기는 "대상(item)"과, 참가자의 순위를 채점할 "정답(ground truth)"을 정의합니다.

    RankItem    순위를 매길 대상 하나: 동물 두 마리로 된 팀(pair)
    Change      가상 변화(counterfactual probe) 하나: "만약 ~가 바뀐다면?"
    Attributes  한 블록의 숨은 속성값 (개인 능력 competence + 팀 시너지 synergy)
    RankingSpec 순위 화면 하나를 로그에서 식별하는 정보

순위의 기준은 항상 팀 점수(performance) 입니다.
    competence  개인 능력.   C_i(d) = 동물 i 의 도메인 d 실력
    synergy     짝 시너지.   S(i,j) = 동물 i, j 가 함께할 때의 협력도
    performance 팀 점수.     S(i,j) × (C_i(d) + C_j(d))
competence / synergy 는 가상 변화(Change)로만 바뀌고, 그 자체를 순위로 묻지는 않습니다.

내부에서는 동물을 역할 코드(A–D)로 다룹니다. 역할 코드는 화면에 절대
나오지 않고, 화면(view)은 RankItem.animals(동물 이름)만 사용합니다.
psychopy를 쓰지 않으므로(표준 라이브러리만 사용) 테스트에서 창 없이 import할 수 있습니다.
"""

import csv
import itertools
from dataclasses import dataclass, field
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

from config.paths import COMPETENCE_CSV

# 역할 코드 두 개로 된 팀, 예: ('A', 'C')
Pair = Tuple[str, str]


# ── 순위를 매길 대상 ────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class RankItem:
    """순위를 매길 대상 하나 (팀 1개).

    roles   : 역할 코드, 알파벳 순으로 정렬됨. 예: ('A', 'C')
    animals : roles 와 같은 순서의 동물 이름. 예: ('duck', 'panda')
    """
    roles:   Tuple[str, ...]
    animals: Tuple[str, ...]

    @property
    def key(self) -> str:
        """로그에 쓰는 역할 코드 이름. 예: 'A+C'"""
        return '+'.join(self.roles)

    @property
    def label(self) -> str:
        """로그에 쓰는 동물 이름. 예: 'duck+panda'"""
        return '+'.join(self.animals)


def role_map(group: Sequence[str], char_code: Mapping[str, str]) -> Dict[str, str]:
    """한 블록의 동물들에 대해 {역할 코드: 동물 이름} 사전을 만듭니다.

    group     : 이 블록에 나오는 동물 이름들
    char_code : {동물 이름: 역할 코드} (자극 파일에서 읽은 값)
    반환       : 예) {'A': 'duck', 'B': 'panda', ...}
    """
    roles = {}
    for animal in group:
        role = char_code[animal]
        roles[role] = animal
    return roles


def pair_items(group: Sequence[str], char_code: Mapping[str, str]) -> List[RankItem]:
    """가능한 모든 두 마리 팀을 대상으로 하는 RankItem 목록.

    4마리면 4C2 = 6팀. 순서는 (A,B), (A,C), (A,D), (B,C), ... 입니다.
    """
    roles = role_map(group, char_code)
    items = []
    for first_role, second_role in itertools.combinations(sorted(roles), 2):
        items.append(RankItem((first_role, second_role), (roles[first_role], roles[second_role])))
    return items


# ── 속성값과 가상 변화 ──────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Change:
    """한 번의 가상 변화(counterfactual probe). 항상 "원래" 속성값에 적용됩니다.

    kind   : 'competence' (roles = (r,) 한 명, domain 필수)
             또는 'synergy' (roles = (r1, r2) 두 명)
    roles  : 바뀌는 동물의 역할 코드. 생성 시 자동으로 정렬됩니다.
    value  : 바뀐 뒤의 속성값 (자극 표와 같은 척도)
    domain : competence 변화일 때 어느 도메인의 실력이 바뀌는지
    """
    kind:   str
    roles:  Tuple[str, ...]
    value:  float
    domain: Optional[str] = None

    def __post_init__(self):
        # synergy 표의 키가 정렬된 쌍이므로 roles 도 정렬해 둡니다.
        # frozen dataclass 라서 일반 대입 대신 object.__setattr__ 를 씁니다.
        object.__setattr__(self, 'roles', tuple(sorted(self.roles)))

        if self.kind == 'competence':
            if len(self.roles) != 1 or self.domain is None:
                raise ValueError(f"competence change needs one role and a domain: {self}")
        if self.kind == 'synergy':
            if len(self.roles) != 2:
                raise ValueError(f"synergy change needs two roles: {self}")
        if self.kind not in ('competence', 'synergy'):
            raise ValueError(f"unknown change kind {self.kind!r}")


@dataclass(frozen=True)
class Attributes:
    """한 블록의 숨은 속성값.

    competence : {역할 코드: {도메인: 실력값}}   예) competence['A']['cooking'] = 8.5
    synergy    : {정렬된 역할 쌍: 시너지값}       예) synergy[('B', 'C')] = 0.8
    """
    competence: Mapping[str, Mapping[str, float]]
    synergy:    Mapping[Pair, float]

    def performance(self, roles: Sequence[str], domain: str) -> float:
        """팀 점수 Performance(i, j, d) = Synergy(i, j) × (Competence(i, d) + Competence(j, d))."""
        first_role, second_role = sorted(roles)
        pair_synergy = self.synergy[(first_role, second_role)]
        summed_competence = self.competence[first_role][domain] + self.competence[second_role][domain]
        return pair_synergy * summed_competence

    def with_change(self, change: Change) -> 'Attributes':
        """change 를 적용한 "새" Attributes 를 돌려줍니다.

        self 는 절대 바뀌지 않습니다 (사전을 복사한 뒤 복사본만 수정).
        그래서 probe 가 여러 번 있어도 변화가 누적되지 않고,
        각 probe 는 항상 원래 속성값에서 출발합니다.
        """
        competence_copy = {}
        for role, values_by_domain in self.competence.items():
            competence_copy[role] = dict(values_by_domain)
        synergy_copy = dict(self.synergy)

        if change.kind == 'competence':
            changed_role = change.roles[0]
            competence_copy[changed_role][change.domain] = change.value
        else:
            synergy_copy[change.roles] = change.value

        return Attributes(competence_copy, synergy_copy)


def load_attributes(synergy: Mapping[Pair, float], path=COMPETENCE_CSV) -> Attributes:
    """CSV 의 원래(반올림하지 않은) competence 값과 synergy 표로 Attributes 를 만듭니다.

    StimulusSet.competence 에는 테두리 색에 쓰려고 정수 단계로 바꾼 값이 들어 있습니다.
    정답 계산에는 원래 값(예: 8.5)이 필요하므로 CSV 를 여기서 다시 읽습니다.

    synergy : {정렬된 역할 쌍: 시너지값} (StimulusSet.synergy)
    path    : competence CSV 경로
    """
    competence: Dict[str, Dict[str, float]] = {}
    with open(path, newline='', encoding='utf-8') as f:
        for row in csv.DictReader(f, skipinitialspace=True):
            # 열 이름 앞뒤 공백 제거
            values = {}
            for column, cell in row.items():
                values[column.strip()] = cell
            role = values.pop('char_ani').strip()

            # 나머지 열 중 id / animal / img_file 을 뺀 것이 도메인별 실력입니다.
            values_by_domain = {}
            for domain, cell in values.items():
                if domain not in ('id', 'animal', 'img_file'):
                    values_by_domain[domain] = float(cell)

            # 같은 역할의 동물들은 프로필이 같으므로 처음 나온 행만 사용합니다.
            if role not in competence:
                competence[role] = values_by_domain
    return Attributes(competence, dict(synergy))


# ── 정답 값과 일치도 지표 ───────────────────────────────────────────────────────

def true_values(attrs: Attributes, items: Sequence[RankItem], domain: str) -> Dict[str, float]:
    """{item.key: 정답 팀 점수(소수 4자리 반올림)}.

    화면에 보인 순서와 상관없이 항상 역할 코드 순서로 정렬해서 만듭니다.
    """
    items_in_role_order = sorted(items, key=lambda item: item.roles)
    values = {}
    for item in items_in_role_order:
        values[item.key] = round(attrs.performance(item.roles, domain), 4)
    return values


def _average_ranks(values: Sequence[float]) -> List[float]:
    """값이 클수록 높은 순위(1위)를 줍니다. 같은 값끼리는 순위의 평균을 나눠 갖습니다.

    예) [5, 3, 3, 1] → [1.0, 2.5, 2.5, 4.0]   (3 두 개가 2위·3위를 나눠 2.5위)
    """
    # 값이 큰 것부터의 인덱스 순서
    order = sorted(range(len(values)), key=lambda index: -values[index])
    ranks = [0.0] * len(values)

    group_start = 0
    while group_start < len(order):
        # 같은 값이 이어지는 구간 [group_start, group_end] 을 찾습니다.
        group_end = group_start
        while (group_end + 1 < len(order)
               and values[order[group_end + 1]] == values[order[group_start]]):
            group_end += 1

        # 구간 안의 모든 대상이 같은 평균 순위를 받습니다. (순위는 1부터 시작)
        shared_rank = (group_start + group_end) / 2 + 1
        for position in range(group_start, group_end + 1):
            ranks[order[position]] = shared_rank

        group_start = group_end + 1
    return ranks


def spearman(ranking: Sequence[str], truth: Mapping[str, float]) -> Optional[float]:
    """참가자 순위와 정답 값 사이의 Spearman 순위 상관(rho).

    ranking : 참가자가 매긴 순위, item key 목록 (1위가 맨 앞)
    truth   : {item key: 정답 값}
    반환     : -1 ~ 1 사이 값(소수 4자리). 아래 경우에는 None
               - 순위가 미완성이거나 대상이 다를 때
               - 정답 값이 모두 같아서(분산 0) 상관을 계산할 수 없을 때

    계산 방법: 참가자 순위(1, 2, 3, ...)와 정답의 평균 순위 사이의 Pearson 상관.
    """
    if sorted(ranking) != sorted(truth):
        return None

    # truth 의 키 순서대로 두 순위 목록을 맞춰 놓습니다.
    given_ranks = []
    for key in truth:
        given_ranks.append(float(ranking.index(key) + 1))
    true_ranks = _average_ranks(list(truth.values()))

    mean_given = sum(given_ranks) / len(given_ranks)
    mean_true = sum(true_ranks) / len(true_ranks)

    covariance = 0
    variance_given = 0
    variance_true = 0
    for given, true in zip(given_ranks, true_ranks):
        covariance += (given - mean_given) * (true - mean_true)
        variance_given += (given - mean_given) ** 2
        variance_true += (true - mean_true) ** 2

    if not variance_given or not variance_true:
        return None
    return round(covariance / (variance_given * variance_true) ** 0.5, 4)


def kendall_distance(a: Sequence[str], b: Sequence[str]) -> Optional[int]:
    """두 순위 사이의 Kendall 거리: 순서가 서로 뒤바뀐 대상 쌍의 개수.

    0 이면 두 순위가 같고, 값이 클수록 많이 바뀐 것입니다.
    예) ['A','B','C'] vs ['C','B','A'] → 3 (세 쌍 모두 뒤바뀜)
    두 순위의 대상이 다르면(미완성 등) None.
    """
    if sorted(a) != sorted(b):
        return None

    position_in_b = {}
    for index, key in enumerate(b):
        position_in_b[key] = index

    discordant_pairs = 0
    for i, j in itertools.combinations(range(len(a)), 2):
        # a 에서는 a[i] 가 a[j] 보다 앞인데, b 에서는 뒤에 있으면 "뒤바뀐 쌍"
        if position_in_b[a[i]] > position_in_b[a[j]]:
            discordant_pairs += 1
    return discordant_pairs


# ── 순위 화면 하나의 정의 ───────────────────────────────────────────────────────

@dataclass
class RankingSpec:
    """로그에서 순위 화면 하나를 식별하는 모든 정보."""
    ranking_id:   str                   # 예: 'b0_p1_baseline'
    ranking_type: str                   # 'performance'(기준) | 'counterfactual'(수정)
    block_index:  int
    phase:        str
    group:        Tuple[str, ...]       # 이 블록의 동물들
    roles:        Dict[str, str]        # 역할 코드 → 동물 이름
    domain:       Optional[str] = None
    probe_id:     Optional[int] = None
    change:       Optional[Change] = None
    baseline_id:  Optional[str] = None  # counterfactual 순위 → 그 기준(baseline) 순위의 id
    extra:        Dict[str, object] = field(default_factory=dict)
