"""
assessments.py
--------------
평가(assessment) 하나를 처음부터 끝까지 실행하고, 각 순위의 결과를 저장합니다.

    run_block_rankings  블록 끝: 공유 기준(baseline) 팀 점수 순위 1번
                        → probe 1: 가상 변화 안내 → 수정 순위 (기준 순위에서 출발)
                        → "변화 취소" 안내
                        → probe 2: 가상 변화 안내 → 수정 순위 (다시 기준 순위에서 출발)

두 수정 순위는 같은 기준 순위에서 출발하고(1번 수정 결과와 무관), 두 가상 변화는
각각 원래 속성값에 따로 적용됩니다(Attributes.with_change). 기준 순위가 완료되지
않으면(시간 초과 등) 수정 순위는 진행하지 않습니다 — 빈 자리를 채워 넣지 않습니다.

블록의 phase, 순위 도메인, probe 순서는 모두 "원래 블록 번호"로 스케줄에서 찾습니다
(config.ranking). 제시 위치(presentation_pos)는 기록에만 쓰입니다.

숨은 속성(시너지 / 능력)은 순위로 묻지 않습니다. 그 평가는 별도 모듈의
High / Medium / Low 평가 페이지가 맡습니다.

정답은 Performance(i, j, d) = S(i, j) × (C_i(d) + C_j(d)) 이며, 원래 자극 표
(items.load_attributes)에서 계산합니다. 학습 시행에 쓰인 "순위로 변환된 점수"가 아닙니다.

선택지 표시 순서는 (참가자 id, ranking_id) 로 만든 seed 로 섞습니다.
그래서 같은 참가자·같은 순위는 언제 다시 실행해도 같은 순서가 나오고(재현 가능),
그 순서는 결과에 기록됩니다.
"""

import random
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from config.ranking_strings import rt
from config.settings import BLOCK_PHASES, COMPETENCE_COLOR
from recording.ranking_writers import save_ranking
from recording.stimuli_loader import StimulusSet
from task.ranking.flow import (
    COMPLETE, RankingResult, run_revised_ranking, run_sequential_ranking, show_change_screen, show_reset_screen,
)
from task.ranking.items import Attributes, Change, RankItem, RankingSpec, pair_items, role_map
from task.ranking.record import build_ranking_record
from task.ranking.schedule import probe_order, ranking_domain
from task.ranking.view import ChangeDisplay, domain_label

# 단계 이름. 인덱스 0, 1, 2 가 각각 낮음·중간·높음입니다.
LEVELS = ('low', 'mid', 'high')


@dataclass
class RankingEnv:
    """모든 순위 화면이 함께 쓰는 실행 환경."""
    win:          Any                       # PsychoPy 창
    global_clock: Any                       # 세션 전체 시계
    source:       Any                       # 키 입력: task.ranking.inputs.KeySource (또는 ScriptedSource)
    stim:         StimulusSet               # 자극 정보 (블록별 동물, 역할 코드, 색 등)
    attrs:        Attributes                # 원래(가상 변화 전) 속성값 — 절대 수정하지 않음
    subject_id:   str
    subject_dir:  Path                      # 결과 파일을 쓸 폴더
    session_id:   Optional[str] = None
    counterbalance_group: Optional[str] = None   # 'A' | 'B' (task.schedule.counterbalance_group)


@dataclass(frozen=True)
class Probe:
    """가상 변화 probe 하나: 블록 안에서 몇 번째인지, 어느 도메인의 팀 점수를, 어떤 변화를 가정하고 묻는지.

    수정 순위는 domain 으로 묻습니다 (기준 순위와 같은 도메인).
    competence 변화는 반드시 같은 도메인의 실력을 바꿔야 합니다.
    """
    position: int           # 1 또는 2
    domain:   str
    change:   Change

    def __post_init__(self):
        if self.change.kind == 'competence' and self.change.domain != self.domain:
            raise ValueError(f"competence change on {self.change.domain!r} "
                             f"but the ranking domain is {self.domain!r}: {self}")


@dataclass(frozen=True)
class ProbeCondition:
    """도메인과 순서가 정해지지 않은 가상 변화 조건. 도메인·순서 스케줄과 따로 정의합니다.

    for_domain(domain, position) 으로 그 블록의 순위 도메인과 probe 위치에 묶어 Probe 를 만듭니다.
        competence : 그 도메인의 실력을 value 로 바꿈
        synergy    : 도메인과 상관없이 짝의 시너지를 value 로 바꿈 (효과는 그 도메인의 팀 점수로 평가)
    """
    kind:     str
    roles:    Tuple[str, ...]
    value:    float

    def for_domain(self, domain: str, position: int) -> Probe:
        """이 조건을 순위 도메인 domain, 블록 안의 위치 position 에 묶은 Probe."""
        if self.kind == 'competence':
            change_domain = domain          # 순위 도메인의 실력을 바꿈
        else:
            change_domain = None            # synergy 는 도메인과 상관없음
        change = Change(self.kind, self.roles, self.value, domain=change_domain)
        return Probe(position, domain, change)


@dataclass
class BlockRankings:
    """run_block_rankings 의 결과: 공유 기준 순위 하나와 그 뒤의 수정 순위들."""
    baseline: RankingResult
    revised:  List[RankingResult] = field(default_factory=list)
    aborted:  bool = False                  # 어느 화면에서든 Esc 로 중단했는지


def block_probes(block_index: int, conditions: Mapping[str, ProbeCondition]) -> List[Probe]:
    """이 블록의 probe 들을 스케줄의 순서대로 만듭니다.

    conditions : {'competence': ProbeCondition, 'synergy': ProbeCondition}
    순서는 PROBE_ORDERS[block_index], 도메인은 PERFORMANCE_RANKING_DOMAINS[block_index]
    — 둘 다 원래 블록 번호로 찾으므로 제시 순서와 상관없습니다.
    """
    domain = ranking_domain(block_index)
    probes = []
    for position, kind in enumerate(probe_order(block_index), start=1):
        condition = conditions[kind]
        if condition.kind != kind:
            raise ValueError(f"conditions[{kind!r}] is a {condition.kind!r} condition")
        probes.append(condition.for_domain(domain, position))
    return probes


# ── 도우미 ────────────────────────────────────────────────────────────────────

def _spec(env: RankingEnv, block_index: int, phase: str, ranking_id: str, **spec_fields) -> RankingSpec:
    """이 블록의 동물·역할 정보를 채운 RankingSpec 을 만듭니다.

    spec_fields : ranking_type, domain 등 RankingSpec 의 나머지 필드
    """
    group = tuple(env.stim.animal_groups[block_index])
    roles = role_map(group, env.stim.char_code)
    return RankingSpec(ranking_id=ranking_id, block_index=block_index, phase=phase, group=group,
                       roles=roles, **spec_fields)


def _shuffled(env: RankingEnv, spec: RankingSpec) -> List[RankItem]:
    """선택지를 재현 가능한 무작위 순서로 섞어 돌려줍니다.

    seed 는 "참가자 id|ranking_id" 문자열입니다. 따라서
        - 같은 참가자의 같은 순위 → 항상 같은 순서 (다시 실행해도 동일)
        - 참가자나 순위가 다르면 → 다른 순서
    random.Random(seed) 로 전용 난수 생성기를 만들어, 실험의 다른 난수에 영향을 주지 않습니다.
    """
    items = pair_items(spec.group, env.stim.char_code)
    seed = f"{env.subject_id}|{spec.ranking_id}"
    random.Random(seed).shuffle(items)
    return items


def _save(env: RankingEnv, result: RankingResult, change_level: Optional[str] = None) -> RankingResult:
    """결과를 기록으로 바꿔 파일에 씁니다 (JSON + rankings.csv + ranking_events.csv)."""
    record, events = build_ranking_record(result, env.attrs, env.subject_id, env.session_id, change_level)
    save_ranking(env.subject_dir, record, events)
    return result


def _rounded(value: Optional[float]) -> Optional[float]:
    if value is None:
        return None
    return round(value, 5)


def change_level(stim: StimulusSet, change: Change) -> tuple:
    """가상 변화의 새 값이 과제의 색 규칙에서 몇 단계인지: (단계 이름, 색).

    competence : 학습 과제의 테두리 색 규칙(stim.comp_color)으로 색을 정하고,
                 COMPETENCE_COLOR = {1: 빨강, 2: 노랑, 3: 초록} 에서 그 색의 단계를 찾습니다.
    synergy    : synergy 표의 값들을 크기순으로 정렬했을 때의 위치가 단계입니다.
                 표에 없는 값이면 ValueError (화면에 보여 줄 색이 없기 때문).
    """
    if change.kind == 'competence':
        color = stim.comp_color(change.value)
        level_number_by_color = {}
        for level_number, level_color in COMPETENCE_COLOR.items():
            level_number_by_color[level_color] = level_number
        level_index = level_number_by_color[color] - 1      # 단계 1~3 → 인덱스 0~2
        return LEVELS[level_index], color

    synergy_values = sorted(stim.synergy_color)
    if change.value not in stim.synergy_color:
        raise ValueError(f"synergy change value {change.value} not in synergy table {synergy_values}")
    level_index = synergy_values.index(change.value)
    return LEVELS[level_index], stim.synergy_color[change.value]


def change_display(env: RankingEnv, spec: RankingSpec, change: Change) -> tuple:
    """가상 변화를 화면에 보여 줄 정보: (ChangeDisplay, 단계 이름).

    역할 코드를 동물 이름으로 바꾸고, 참가자용 문장을 만듭니다.
    """
    level, color = change_level(env.stim, change)

    animals = []
    for role in change.roles:
        animals.append(spec.roles[role])

    if change.kind == 'competence':
        text = rt("change_competence", domain=domain_label(change.domain), level=rt(f"level_{level}"))
    else:
        text = rt("change_synergy", level=rt(f"level_{level}"))
    return ChangeDisplay(change.kind, animals, color, text), level


# ── 진입점 ────────────────────────────────────────────────────────────────────

def run_block_rankings(env: RankingEnv, block_index: int, presentation_pos: int,
                       conditions: Mapping[str, ProbeCondition]) -> BlockRankings:
    """블록 끝의 순위 평가 전체: 공유 기준 순위 → probe 1 → 변화 취소 안내 → probe 2.

    block_index      : 원래 블록 번호. phase·도메인·probe 순서는 이것으로 스케줄에서 찾습니다.
    presentation_pos : 이 참가자에게 이 블록이 몇 번째로 제시되는지 (0부터, 기록용)
    conditions       : {'competence': ..., 'synergy': ...} 가상 변화 조건
    반환              : BlockRankings
    부작용            : 순위마다 즉시 파일에 저장합니다 (중간에 중단돼도 앞의 결과는 남음).

    기준 순위가 완료(complete)되지 않으면 — 중단이든 시간 초과든 — 일부만 고른
    순위를 그대로 저장하고 수정 순위는 진행하지 않습니다.
    """
    phase = BLOCK_PHASES[block_index]
    domain = ranking_domain(block_index)
    probes = block_probes(block_index, conditions)

    # 1단계: 공유 기준 순위 (현재 속성으로 팀 점수 예측)
    baseline_id = f"b{block_index}_baseline"
    baseline_spec = _spec(env, block_index, phase, baseline_id, ranking_type='performance', domain=domain,
                          baseline_id=baseline_id, presentation_pos=presentation_pos,
                          counterbalance_group=env.counterbalance_group,
                          probe_order='>'.join(probe_order(block_index)))
    prompt = rt("rank_prompt_performance", domain=domain_label(domain))
    baseline = run_sequential_ranking(env.win, env.global_clock, env.source, baseline_spec,
                                      _shuffled(env, baseline_spec), prompt)
    _save(env, baseline)
    out = BlockRankings(baseline, aborted=baseline.aborted)
    if baseline.status != COMPLETE:
        return out

    # 두 수정 순위가 함께 쓰는 출발 순위. 튜플이라 1번 수정이 바꿀 수 없습니다.
    original = tuple(baseline.final)

    # 2단계: probe 들 (두 번째부터는 앞의 변화가 취소됐음을 먼저 알림)
    for probe in probes:
        reset = None
        if probe.position > 1:
            reset = show_reset_screen(env.win, env.global_clock, env.source, domain)
            if reset['aborted']:
                out.aborted = True
                return out

        revised = _run_probe(env, baseline_spec, probe, original, reset)
        if revised is None:                 # 가상 변화 화면에서 중단
            out.aborted = True
            return out
        out.revised.append(revised)
        if revised.aborted:
            out.aborted = True
            return out
    return out


def _run_probe(env: RankingEnv, baseline_spec: RankingSpec, probe: Probe, original: Sequence[RankItem],
               reset: Optional[Dict]) -> Optional[RankingResult]:
    """probe 하나: 가상 변화 안내 → 수정 순위(original 에서 출발) → 저장.

    reset : 이 probe 앞에 보여 준 "변화 취소" 화면의 결과 (1번째 probe 는 None)
    반환   : 수정 순위 결과. 가상 변화 화면에서 Esc 로 중단하면 None
    """
    spec = replace(baseline_spec, ranking_id=f"b{baseline_spec.block_index}_probe{probe.position}_{probe.change.kind}",
                   ranking_type='counterfactual', probe_pos=probe.position, change=probe.change)

    display, level = change_display(env, spec, probe.change)
    change_screen = show_change_screen(env.win, env.global_clock, env.source, display, probe.domain)
    if change_screen['aborted']:
        return None

    revised = run_revised_ranking(env.win, env.global_clock, env.source, spec, list(original),
                                  rt("rank_prompt_revised", domain=domain_label(probe.domain)), display)

    # 안내 화면들의 시간 정보를 수정 순위 결과에 붙여 저장
    revised.change_onset_global = _rounded(change_screen['onset'])
    revised.change_rt = change_screen['rt']
    if reset is not None:
        revised.reset_onset_global = _rounded(reset['onset'])
        revised.reset_rt = reset['rt']
    _save(env, revised, change_level=level)
    return revised
