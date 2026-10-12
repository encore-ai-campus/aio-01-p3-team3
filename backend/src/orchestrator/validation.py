"""README 계약을 코드로 확인하는 검사기.

재시도는 각 Agent의 AutoHealing이 소유합니다. 이 모듈은 Agent가 복구를
끝낸 뒤 Orchestrator가 Join Guard에 넘기기 직전 최종 결과를 확인합니다.
따라서 여기서 Agent를 다시 호출하지 않습니다.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Any

from pydantic import ValidationError

from src.rules.risk import cctv_contract_errors
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


def validate_cctv_candidate(value: Any) -> bool:
    """AutoHealing에 전달할 CCTV 검증 콜백. False면 기존 정책으로 재시도.

    최종 판정에서도 쓰는 risk.py의 공용 계약 검사기를 재사용해 두 경로의
    필수 키·자료형·빈 description 정책이 달라지지 않게 한다.
    """
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
