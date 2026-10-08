"""가상 어르신의 시나리오별 바이탈 조회 도구."""

from copy import deepcopy
from typing import cast

from ..mock_data import MOCK_PROFILES, SCENARIOS, Scenario


def get_vitals(profile_id: str, scenario: Scenario) -> dict[str, object]:
    """선택한 가상 어르신과 시나리오의 바이탈 측정값을 반환한다.

    호출자가 반환값을 변경해도 공용 Mock 데이터가 오염되지 않도록
    깊은 복사본을 반환한다. 지원하지 않는 입력은 AutoHealing이 감지할
    수 있도록 예외로 전달한다.
    """

    if profile_id not in MOCK_PROFILES:
        raise ValueError(f"지원하지 않는 profile_id입니다: {profile_id}")

    if scenario not in SCENARIOS:
        raise ValueError(f"지원하지 않는 scenario입니다: {scenario}")

    vital = cast(dict[str, object], SCENARIOS[scenario]["vital"])
    return deepcopy(vital)
