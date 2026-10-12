"""가정 내 환경·기기 상태 조회 및 Mock 제어 도구."""

from copy import deepcopy
from typing import Literal, TypeAlias, cast

from ..mock_data import MOCK_PROFILES, SCENARIOS, Scenario


ControllableDevice: TypeAlias = Literal["aircon", "induction"]
DeviceAction: TypeAlias = Literal["cool", "heat", "on", "off"]

DEVICE_LABELS: dict[ControllableDevice, str] = {
    "aircon": "에어컨",
    "induction": "인덕션",
}


def get_indoor_env(profile_id: str, scenario: Scenario) -> dict[str, object]:
    """선택한 가상 어르신 주거지의 시나리오별 온·습도를 반환한다.

    호출자가 반환값을 변경해도 공용 Mock 데이터가 오염되지 않도록
    깊은 복사본을 반환한다. 지원하지 않는 입력은 AutoHealing이 감지할
    수 있도록 예외로 전달한다.
    """

    if profile_id not in MOCK_PROFILES:
        raise ValueError(f"지원하지 않는 profile_id입니다: {profile_id}")

    if scenario not in SCENARIOS:
        raise ValueError(f"지원하지 않는 scenario입니다: {scenario}")

    indoor_environment = cast(
        dict[str, object],
        SCENARIOS[scenario]["indoor_environment"],
    )
    return deepcopy(indoor_environment)


def get_device_status(profile_id: str, scenario: Scenario) -> dict[str, object]:
    """선택한 가상 어르신 주거지의 시나리오별 기기 상태를 반환한다.

    인덕션이 켜진 경우 ``induction_minutes``와 ``induction_temperature``를
    숫자로 제공한다. 이 함수는 조회만 수행하며 기기 상태를 변경하지 않는다.
    """

    if profile_id not in MOCK_PROFILES:
        raise ValueError(f"지원하지 않는 profile_id입니다: {profile_id}")

    if scenario not in SCENARIOS:
        raise ValueError(f"지원하지 않는 scenario입니다: {scenario}")

    devices = cast(dict[str, object], SCENARIOS[scenario]["devices"])
    return deepcopy(devices)


def control_device(
    device: ControllableDevice,
    action: DeviceAction,
) -> dict[str, object]:
    """승인된 기기 제어를 실제 동작 없이 Mock으로 실행한다.

    보호자 승인 여부는 오케스트레이터의 Approval Gate에서 확인한다.
    최신 공통 계약에 따라 ``device``와 ``action``만 받는다.
    """

    if device not in DEVICE_LABELS:
        raise ValueError(f"지원하지 않는 device입니다: {device}")

    if device == "aircon":
        if action not in {"cool", "heat", "off"}:
            raise ValueError("에어컨 action은 cool, heat, off 중 하나여야 합니다.")
        action_label = {"cool": "냉방을", "heat": "난방을", "off": "끄기를"}[action]
        message = f"에어컨 {action_label} Mock으로 실행했습니다."
    else:
        if action not in {"on", "off"}:
            raise ValueError("인덕션 action은 on, off 중 하나여야 합니다.")
        message = f"인덕션 {'켜기' if action == 'on' else '끄기'}를 Mock으로 실행했습니다."

    return {
        "tool": "control_device",
        "status": "success",
        "message": message,
        "recovery": None,
    }
