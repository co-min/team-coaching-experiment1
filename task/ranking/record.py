"""
record.py
---------
RankingResult → recording/ranking_writers.py 가 쓰는 평평한(flat) 사전.

정답(true_values, spearman)은 여기서 계산합니다.
    - baseline(기준) 순위       : 원래 속성값 기준
    - counterfactual(수정) 순위 : 원래 속성값에 가상 변화를 적용한 값 기준

주의: 출력 열의 순서는 사전에 넣는 순서 그대로입니다 (JSON 파일).
CSV 열 순서는 ranking_writers.RANKING_FIELDS 가 정합니다.
아래 _..._fields 함수들을 부르는 순서를 바꾸면 JSON 열 순서가 바뀝니다.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from config import ranking as R
from recording.ranking_writers import MAX_ITEMS
from task.forced_first import BLOCK_TYPE
from task.ranking.flow import COMPLETE, RankingResult
from task.ranking.items import Attributes, RankingSpec, kendall_distance, spearman, true_values


# ── 작은 도우미 ───────────────────────────────────────────────────────────────

def _keys(items) -> str:
    """대상 목록 → 'A+B|C+D|...' (역할 코드)"""
    return '|'.join(item.key for item in items)


def _labels(items) -> str:
    """대상 목록 → 'duck+panda|...' (동물 이름)"""
    return '|'.join(item.label for item in items)


def _count(events, *names) -> int:
    """이벤트 중 이름이 names 에 속하는 것의 개수."""
    count = 0
    for row in events:
        if row['event'] in names:
            count += 1
    return count


# ── 기록의 각 부분 ────────────────────────────────────────────────────────────

def _identity_fields(result: RankingResult, subject_id: str, session_id: Optional[str]) -> Dict[str, Any]:
    """참가자·세션과, 이 순위가 무엇인지 (블록, 대상, 도메인 등)."""
    spec = result.spec
    role_map_parts = []
    for role, animal in sorted(spec.roles.items()):
        role_map_parts.append(f"{role}={animal}")

    return {
        "subject_id":   subject_id,
        "session_id":   session_id,
        "counterbalance_group": spec.counterbalance_group,
        "ranking_id":   spec.ranking_id,
        "ranking_type": spec.ranking_type,
        "n_items":      len(result.display_order),
        "block_index":  spec.block_index,
        "presentation_pos": spec.presentation_pos,
        "phase":        spec.phase,
        "block_type":   BLOCK_TYPE.get(spec.phase, spec.phase),
        "animal_set":   ','.join(spec.group),
        "role_map":     ';'.join(role_map_parts),
        "domain":       spec.domain,
        "baseline_id":  spec.baseline_id,
        "probe_order":  spec.probe_order,
        "probe_pos":    spec.probe_pos,
    }


def _change_fields(result: RankingResult, change_level: Optional[str]) -> Dict[str, Any]:
    """가상 변화 정보. 가상 변화가 없는 순위(baseline 등)는 모두 None."""
    spec = result.spec
    change = spec.change
    if change:
        changed_animals = []
        for role in change.roles:
            changed_animals.append(spec.roles[role])
        return {
            "change_kind":    change.kind,
            "change_roles":   '+'.join(change.roles),
            "change_animals": '+'.join(changed_animals),
            "change_domain":  change.domain,
            "change_value":   change.value,
            "change_level":   change_level,
            "change_onset":   result.change_onset_global,
            "change_rt":      result.change_rt,
            "reset_onset":    result.reset_onset_global,
            "reset_rt":       result.reset_rt,
        }
    return {
        "change_kind":    None,
        "change_roles":   None,
        "change_animals": None,
        "change_domain":  None,
        "change_value":   None,
        "change_level":   change_level,
        "change_onset":   result.change_onset_global,
        "change_rt":      result.change_rt,
        "reset_onset":    result.reset_onset_global,
        "reset_rt":       result.reset_rt,
    }


def _timing_fields(result: RankingResult, presses: List[Dict]) -> Dict[str, Any]:
    """종료 상태와 시간 정보.

    first_key_rt   : 첫 키 입력의 rt (아무 키도 안 눌렀으면 None)
    confirm_rt     : 제출 rt. 제출로 끝난 경우(complete)에만 값이 있음
    confirm_global : 제출 시각 (global_clock 기준)
    total_rt       : 화면을 끝낸 시점의 rt (제출·시간 초과·중단 모두)
    """
    complete = result.status == COMPLETE

    if result.onset_global is None:
        onset_global = None
    else:
        onset_global = round(result.onset_global, 5)

    if presses:
        first_key_rt = presses[0]['rt']
    else:
        first_key_rt = None

    if complete:
        confirm_rt = result.end_rt
    else:
        confirm_rt = None

    if complete and result.onset_global is not None:
        confirm_global = round(result.onset_global + result.end_rt, 5)
    else:
        confirm_global = None

    return {
        "status":         result.status,
        "key_backend":    result.key_backend,
        "time_limit":     R.RANKING_MAX_TIME,
        "onset_global":   onset_global,
        "first_key_rt":   first_key_rt,
        "confirm_rt":     confirm_rt,
        "confirm_global": confirm_global,
        "total_rt":       result.end_rt,
    }


def _behavior_fields(result: RankingResult, presses: List[Dict]) -> Dict[str, Any]:
    """키 입력 행동의 횟수."""
    events = result.events
    return {
        "n_keypresses":  len(presses),
        "n_unmapped":    _count(events, 'unmapped'),
        "n_invalid":     _count(events, 'invalid'),
        "n_selections":  _count(events, 'select'),
        "n_undos":       _count(events, 'undo'),
        "n_moves":       _count(events, 'move'),
        "n_relocations": result.n_relocations,
    }


def _revision_fields(result: RankingResult, initial_keys: List[str], final_keys: List[str]) -> Dict[str, Any]:
    """수정 순위가 출발 순위에서 얼마나 바뀌었는지. 출발 순위가 없으면(sequential) 모두 None.

    changed              : 하나라도 바뀌었는지
    n_changed_positions  : 같은 자리에 다른 대상이 온 자리 수
    kendall_from_initial : 순서가 뒤바뀐 대상 쌍의 수
    """
    if not result.initial:
        return {"changed": None, "n_changed_positions": None, "kendall_from_initial": None}

    n_changed_positions = 0
    for final_key, initial_key in zip(final_keys, initial_keys):
        if final_key != initial_key:
            n_changed_positions += 1

    return {
        "changed":              final_keys != initial_keys,
        "n_changed_positions":  n_changed_positions,
        "kendall_from_initial": kendall_distance(initial_keys, final_keys),
    }


def _order_fields(result: RankingResult, final_keys: List[str]) -> Dict[str, Any]:
    """표시 순서, 출발 순위, 최종 순위, 그리고 rank1 ~ rank{MAX_ITEMS} 열."""
    fields = {
        "display_order":           _keys(result.display_order),
        "display_order_animals":   _labels(result.display_order),
        "initial_ranking":         _keys(result.initial) or None,     # 빈 문자열이면 None
        "initial_ranking_animals": _labels(result.initial) or None,
        "final_ranking":           _keys(result.final),
        "final_ranking_animals":   _labels(result.final),
    }
    # 대상 수와 상관없이 열 수를 고정하려고 MAX_ITEMS 개를 모두 만들고, 없는 순위는 None
    for index in range(MAX_ITEMS):
        if index < len(final_keys):
            fields[f"rank{index + 1}"] = final_keys[index]
        else:
            fields[f"rank{index + 1}"] = None
    return fields


def _accuracy_fields(truth: Dict[str, float], final_keys: List[str], complete: bool) -> Dict[str, Any]:
    """정답 값, 정답 순서, 참가자 순위와 정답의 Spearman 상관 (완료된 순위만)."""
    true_value_parts = []
    for key, value in truth.items():
        true_value_parts.append(f"{key}:{value}")

    # 값이 큰 것부터. 값이 같으면 truth 의 순서(역할 코드 순)를 유지합니다.
    keys_by_value = sorted(truth, key=lambda key: -truth[key])

    if complete:
        spearman_true = spearman(final_keys, truth)
    else:
        spearman_true = None

    return {
        "true_values":   ';'.join(true_value_parts),
        "true_order":    '|'.join(keys_by_value),
        "spearman_true": spearman_true,
    }


def _ground_truth(result: RankingResult, attrs: Attributes) -> Dict[str, float]:
    """이 순위의 정답 값. 가상 변화가 있으면 원래 속성값의 "복사본"에 적용해서 계산합니다."""
    spec: RankingSpec = result.spec
    if spec.change:
        truth_attrs = attrs.with_change(spec.change)
    else:
        truth_attrs = attrs
    return true_values(truth_attrs, result.display_order, spec.domain)


# ── 진입점 ────────────────────────────────────────────────────────────────────

def build_ranking_record(result: RankingResult, attrs: Attributes, subject_id: str,
                         session_id: Optional[str] = None, change_level: Optional[str] = None
                         ) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """순위 화면 하나의 (기록 한 줄, 이벤트 행 목록)을 만듭니다.

    result       : flow.py 가 돌려준 결과
    attrs        : 원래(가상 변화 전) 속성값
    change_level : 가상 변화의 새 단계 이름 ('low' / 'mid' / 'high'), 없으면 None
    반환          : (record, events)
                   record : rankings.csv 한 줄
                   events : ranking_events.csv 의 행들. 각 행 앞에 식별 열을 붙임
    부작용 없음 (파일은 쓰지 않음).
    """
    spec = result.spec
    truth = _ground_truth(result, attrs)
    final_keys = [item.key for item in result.final]
    initial_keys = [item.key for item in result.initial]
    complete = result.status == COMPLETE

    # 실제 키 입력 이벤트만 (onset, timeout 은 key 가 None)
    presses = []
    for row in result.events:
        if row['key'] is not None:
            presses.append(row)

    # 섹션 순서 = 출력 열 순서
    record: Dict[str, Any] = {}
    record.update(_identity_fields(result, subject_id, session_id))
    record.update(_change_fields(result, change_level))
    record.update(_timing_fields(result, presses))
    record.update(_behavior_fields(result, presses))
    record.update(_revision_fields(result, initial_keys, final_keys))
    record.update(_order_fields(result, final_keys))
    record.update(_accuracy_fields(truth, final_keys, complete))
    record["timestamp"] = datetime.now().isoformat(timespec='seconds')

    # 이벤트 행마다 어느 참가자·순위의 것인지 알 수 있도록 식별 열을 앞에 붙입니다.
    common = {"subject_id": subject_id, "session_id": session_id,
              "counterbalance_group": spec.counterbalance_group, "ranking_id": spec.ranking_id,
              "ranking_type": spec.ranking_type, "block_index": spec.block_index,
              "presentation_pos": spec.presentation_pos, "baseline_id": spec.baseline_id,
              "probe_pos": spec.probe_pos}
    event_rows = []
    for row in result.events:
        event_rows.append({**common, **row})
    return record, event_rows
