"""README 계약을 코드로 확인하는 검사기.

재시도는 각 Agent의 AutoHealing이 소유합니다. 이 모듈은 Agent가 복구를
끝낸 뒤 Orchestrator가 Join Guard에 넘기기 직전 최종 결과를 확인합니다.
따라서 여기서 Agent를 다시 호출하지 않습니다.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Any

from pydantic import ValidationError

from src.schemas import CareStatusResult


class ValidationStatus(str, Enum):
    """검사 결과. RETRY 결정은 Agent 복구 경로에서만 내립니다."""

    VALID = "valid"
    INVALID = "invalid"


@dataclass(frozen=True)
class ValidationResult:
    """검사 상태와 사람이 읽을 수 있는 오류 목록."""

    status: ValidationStatus
    errors: tuple[str, ...] = ()


def _plain(value: Any) -> Any:
    """Pydantic 객체와 일반 dict를 같은 방식으로 검사할 수 있게 변환."""
    if hasattr(value, "model_dump"):
        return value.model_dump()
    return value


def cctv_contract_errors(value: Any) -> list[str]:
    """README CCTV 계약을 검사한다.

    analyzed만 관찰 필수 필드를 요구합니다. unavailable/failed는 정상적인
    판단 불가 결과이므로 관찰 필드가 비어 있어도 오류가 아닙니다. 특히
    False는 유효한 관찰값이며, None/누락과 구분합니다. 빈 description도
    팀 합의에 따라 허용합니다.

    참고: 현재 체크아웃에는 해든 님이 공유한 rules.risk.cctv_contract_errors
    함수가 아직 없으므로, 같은 계약을 이 파일에 둡니다. 해당 구현이 합쳐지면
    중복 구현을 제거하고 공용 함수로 연결하면 됩니다.
    """
    raw = _plain(value)
    if not isinstance(raw, dict):
        return ["cctv_not_object"]

    status = raw.get("status", "unavailable")
    if status in ("failed", "unavailable"):
        return []
    if status != "analyzed":
        return ["cctv_status_invalid"]

    errors: list[str] = []
    # 값의 truthiness가 아니라 존재와 자료형을 확인해 False를 허용한다.
    for key in ("person_visible", "fall_suspected"):
        if key not in raw or type(raw[key]) is not bool:
            errors.append(f"cctv_{key}_missing_or_invalid")

    posture_values = {"standing", "sitting", "lying", "fallen", "none"}
    posture = raw.get("posture")
    if not isinstance(posture, str) or posture not in posture_values:
        errors.append("cctv_posture_missing_or_invalid")

    # README는 문자열 필수만 규정한다. 빈 문자열은 현재 팀 결정상 허용한다.
    if "description" not in raw or not isinstance(raw["description"], str):
        errors.append("cctv_description_missing_or_invalid")
    return errors


def validate_cctv_candidate(value: Any) -> bool:
    """AutoHealing에 전달할 CCTV 검증 콜백. False면 기존 정책으로 재시도."""
    return not cctv_contract_errors(value)


def validate_care_status(value: Any) -> ValidationResult:
    """Join Guard 직전 CareStatusResult의 최종 계약을 확인한다.

    스키마의 타입·필수값 검사는 Pydantic에 맡기고, 여기서는 README에 적힌
    CCTV 업무 계약처럼 Pydantic 타입만으로는 표현되지 않는 규칙을 검사한다.
    """
    try:
        care_status = value if isinstance(value, CareStatusResult) else CareStatusResult.model_validate(value)
    except (ValidationError, TypeError, ValueError):
        # Do not copy raw validation details into logs or guardian-facing errors.
        return ValidationResult(ValidationStatus.INVALID, ("care_status_schema_invalid",))

    errors = cctv_contract_errors(care_status.cctv) if care_status.cctv is not None else []
    if errors:
        return ValidationResult(ValidationStatus.INVALID, tuple(errors))
    return ValidationResult(ValidationStatus.VALID)
