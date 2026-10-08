"""지역별 가까운 Mock 병원 조회 도구."""

from copy import deepcopy

from ..mock_data import HOSPITALS_BY_AREA


def _distance_km(hospital: dict[str, object]) -> float:
    """병원 데이터의 거리 값을 비교 가능한 실수로 변환한다."""

    distance = hospital.get("distance_km")
    if isinstance(distance, bool) or not isinstance(distance, (int, float)):
        raise TypeError("병원의 distance_km는 숫자여야 합니다.")
    return float(distance)


def find_hospital(area: str) -> dict[str, object]:
    """선택한 지역에서 거리가 가장 가까운 Mock 병원을 반환한다."""

    if not area.strip():
        raise ValueError("area는 비어 있을 수 없습니다.")

    hospitals = HOSPITALS_BY_AREA.get(area)
    if hospitals is None:
        raise ValueError(f"지원하지 않는 area입니다: {area}")
    if not hospitals:
        raise LookupError(f"등록된 병원이 없습니다: {area}")

    nearest = min(hospitals, key=_distance_km)
    return deepcopy(nearest)
