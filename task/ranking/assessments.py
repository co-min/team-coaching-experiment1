"""
assessments.py
--------------
평가(assessment) 하나를 처음부터 끝까지 실행하고, 각 순위의 결과를 저장합니다.

    run_counterfactual_probe  블록 끝: 기준(baseline) 팀 점수 순위
                              → 가상 변화 안내 → 수정(revised) 순위
    run_attribute_ranking     사용하지 않음 — High / Medium / Low 평가 페이지
                              (짝 시너지, 또는 짝의 능력 합 C_i(d) + C_j(d))로
                              대체될 예정이며, 그 페이지는 별도 모듈로 추가됩니다.

정답은 Performance(i, j, d) = S(i, j) × (C_i(d) + C_j(d)) 이며, 원래 자극 표
(items.load_attributes)에서 계산합니다. 학습 시행에 쓰인 "순위로 변환된 점수"가 아닙니다.

선택지 표시 순서는 (참가자 id, ranking_id) 로 만든 seed 로 섞습니다.
그래서 같은 참가자·같은 순위는 언제 다시 실행해도 같은 순서가 나오고(재현 가능),
그 순서는 결과에 기록됩니다.
가상 변화는 매번 원래 속성값의 복사본에 적용되므로(Attributes.with_change)
probe 를 여러 번 해도 변화가 누적되지 않습니다.
"""

import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any, List, Optional, Sequence

from config.ranking_strings import rt
from config.settings import COMPETENCE_COLOR
from recording.ranking_writers import save_ranking
from recording.stimuli_loader import StimulusSet
from task.ranking.flow import RankingResult, run_revised_ranking, run_sequential_ranking, show_change_screen
from task.ranking.items import Attributes, Change, RankItem, RankingSpec, items_for, role_map
from task.ranking.record import build_ranking_record
from task.ranking.view import ChangeDisplay, domain_label

# 단계 이름. 인덱스 0, 1, 2 가 각각 낮음·중간·높음입니다.
LEVELS = ('low', 'mid', 'high')

# 블록 종류(phase)별로 순위를 매길 속성
#   phase_1 (능력이 보이는 블록)   → 숨은 속성인 시너지를 묻기
#   phase_2 (시너지가 보이는 블록) → 숨은 속성인 능력을 묻기
ATTRIBUTE_BY_PHASE = {'phase_1': 'synergy', 'phase_2': 'competence'}


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


@dataclass(frozen=True)
class Probe:
    """가상 변화 probe 하나: 어느 도메인의 팀 점수를, 어떤 변화를 가정하고 다시 묻는지."""
    probe_id: int
    domain:   str
    change:   Change


# ── 도우미 ────────────────────────────────────────────────────────────────────

def _spec(env: RankingEnv, block_index: int, phase: str, ranking_id: str, **spec_fields) -> RankingSpec:
    """이 블록의 동물·역할 정보를 채운 RankingSpec 을 만듭니다.

    spec_fields : ranking_type, attribute, domain 등 RankingSpec 의 나머지 필드
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
    items = items_for(spec.attribute, spec.group, env.stim.char_code)
    seed = f"{env.subject_id}|{spec.ranking_id}"
    random.Random(seed).shuffle(items)
    return items


def _save(env: RankingEnv, result: RankingResult, change_level: Optional[str] = None) -> RankingResult:
    """결과를 기록으로 바꿔 파일에 씁니다 (JSON + rankings.csv + ranking_events.csv)."""
    record, events = build_ranking_record(result, env.attrs, env.subject_id, env.session_id, change_level)
    save_ranking(env.subject_dir, record, events)
    return result


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

def run_attribute_ranking(env: RankingEnv, block_index: int, phase: str, after_trial: int,
                          domain: Optional[str] = None) -> RankingResult:
    """(사용하지 않음) 숨은 속성 순위 하나를 실행하고 저장합니다.

    after_trial : 몇 번째 학습 시행 뒤인지 (1부터)
    domain      : competence 순위일 때 필수
    """
    attribute = ATTRIBUTE_BY_PHASE[phase]
    if attribute == 'competence' and domain is None:
        raise ValueError("competence ranking (synergy-visible block) needs a domain")

    if attribute == 'competence':
        spec_domain = domain
        prompt = rt("rank_prompt_competence", domain=domain_label(domain))
    else:
        spec_domain = None
        prompt = rt("rank_prompt_synergy")

    spec = _spec(env, block_index, phase, f"b{block_index}_attr_t{after_trial:02d}",
                 ranking_type='attribute', attribute=attribute, after_trial=after_trial,
                 domain=spec_domain)
    result = run_sequential_ranking(env.win, env.global_clock, env.source, spec, _shuffled(env, spec), prompt)
    return _save(env, result)


def run_counterfactual_probe(env: RankingEnv, block_index: int, phase: str,
                             probe: Probe) -> Sequence[RankingResult]:
    """가상 변화 probe 하나: 기준 순위 → 가상 변화 안내 → 수정 순위.

    반환: 실행한 순위 결과 목록
        [baseline, revised]  끝까지 진행한 경우
        [baseline]           기준 순위나 가상 변화 화면에서 Esc 로 중단한 경우
    부작용: 순위마다 즉시 파일에 저장합니다 (중간에 중단돼도 앞의 결과는 남음).
    """
    # 1단계: 기준 순위 (현재 속성으로 팀 점수 예측)
    baseline_spec = _baseline_spec(env, block_index, phase, probe)
    baseline = _run_baseline_ranking(env, baseline_spec, probe)
    _save(env, baseline)
    if baseline.aborted:
        return [baseline]

    # 2단계: 가상 변화 안내 화면
    revised_spec = _revised_spec(env, block_index, phase, probe, baseline_spec)
    display, level = change_display(env, revised_spec, probe.change)
    change_screen = show_change_screen(env.win, env.global_clock, env.source, display, probe.domain)
    if change_screen['aborted']:
        return [baseline]

    # 3단계: 수정 순위 (기준 순위에서 출발)
    initial = _starting_order_for_revision(baseline)
    revised = run_revised_ranking(env.win, env.global_clock, env.source, revised_spec, initial,
                                  rt("rank_prompt_revised", domain=domain_label(probe.domain)), display)

    # 4단계: 가상 변화 화면의 시간 정보를 수정 순위 결과에 붙여 저장
    if change_screen['onset'] is None:
        revised.change_onset_global = None
    else:
        revised.change_onset_global = round(change_screen['onset'], 5)
    revised.change_rt = change_screen['rt']
    _save(env, revised, change_level=level)
    return [baseline, revised]


# ── run_counterfactual_probe 의 단계별 도우미 ─────────────────────────────────

def _baseline_spec(env: RankingEnv, block_index: int, phase: str, probe: Probe) -> RankingSpec:
    """기준 순위의 RankingSpec. ranking_id 예: 'b0_p1_baseline'"""
    return _spec(env, block_index, phase, f"b{block_index}_p{probe.probe_id}_baseline",
                 ranking_type='performance', attribute='performance', domain=probe.domain,
                 probe_id=probe.probe_id)


def _revised_spec(env: RankingEnv, block_index: int, phase: str, probe: Probe,
                  baseline_spec: RankingSpec) -> RankingSpec:
    """수정 순위의 RankingSpec. 가상 변화와 기준 순위의 id 를 함께 담습니다."""
    return _spec(env, block_index, phase, f"b{block_index}_p{probe.probe_id}_revised",
                 ranking_type='counterfactual', attribute='performance', domain=probe.domain,
                 probe_id=probe.probe_id, change=probe.change, baseline_id=baseline_spec.ranking_id)


def _run_baseline_ranking(env: RankingEnv, baseline_spec: RankingSpec, probe: Probe) -> RankingResult:
    """기준 순위 화면을 실행합니다 (선택지는 재현 가능한 무작위 순서)."""
    prompt = rt("rank_prompt_performance", domain=domain_label(probe.domain))
    options = _shuffled(env, baseline_spec)
    return run_sequential_ranking(env.win, env.global_clock, env.source, baseline_spec, options, prompt)


def _starting_order_for_revision(baseline: RankingResult) -> List[RankItem]:
    """수정 순위의 출발 순위 = 기준 순위의 최종 순위.

    기준 순위가 시간 초과로 덜 끝났다면(일부만 고름), 고르지 않은 대상을
    "화면에 표시됐던 순서(위→아래)" 그대로 뒤에 붙여 완전한 목록으로 만듭니다.
    수정 화면은 항상 모든 대상이 있어야 하기 때문입니다.
    이렇게 채운 뒤쪽 순서는 참가자가 고른 것이 아니므로, 분석 시
    기준 순위의 status 가 'timeout' 인지 꼭 확인해야 합니다.
    """
    starting_order = list(baseline.final)
    for item in baseline.display_order:
        if item not in baseline.final:
            starting_order.append(item)
    return starting_order
