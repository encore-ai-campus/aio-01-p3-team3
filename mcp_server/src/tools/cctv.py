"""CCTV Mock 이미지 조회 및 분석 연결 도구."""

from ..mock_data import MOCK_PROFILES, SCENARIOS, Scenario
from ..vision import analyzer


CCTV_POSTURES = {"standing", "sitting", "lying", "fallen", "none"}


def capture_cctv(profile_id: str, scenario: Scenario) -> dict[str, str]:
    """선택한 가상 어르신과 시나리오의 CCTV 이미지 경로를 반환한다.

    이 함수는 이미지 파일을 읽거나 분석하지 않는다. 해든이 구현하는
    ``analyze_cctv_or_unavailable`` 연결은 별도의 ``analyze_cctv`` 도구에서 한다.
    """

    if profile_id not in MOCK_PROFILES:
        raise ValueError(f"지원하지 않는 profile_id입니다: {profile_id}")

    if scenario not in SCENARIOS:
        raise ValueError(f"지원하지 않는 scenario입니다: {scenario}")

    image_path = SCENARIOS[scenario]["cctv_image_path"]
    if not isinstance(image_path, str):
        raise TypeError("cctv_image_path는 문자열이어야 합니다.")

    return {"image_path": image_path}


def analyze_cctv(image_path: str) -> dict[str, object]:
    """해든의 안전 래퍼를 호출하고 CCTV 분석 반환 계약을 검증한다."""

    if not isinstance(image_path, str):
        raise TypeError("image_path는 문자열이어야 합니다.")
    if not image_path.strip():
        raise ValueError("image_path는 비어 있을 수 없습니다.")

    analyze_cctv_or_unavailable = getattr(
        analyzer,
        "analyze_cctv_or_unavailable",
        None,
    )
    if not callable(analyze_cctv_or_unavailable):
        raise RuntimeError(
            "vision.analyzer.analyze_cctv_or_unavailable(image_path)가 "
            "아직 구현되지 않았습니다."
        )

    result = analyze_cctv_or_unavailable(image_path)
    if not isinstance(result, dict):
        raise TypeError("CCTV 분석 결과는 dict여야 합니다.")

    required_fields = {
        "person_visible",
        "posture",
        "fall_suspected",
        "description",
    }
    missing_fields = required_fields - result.keys()
    if missing_fields:
        missing = ", ".join(sorted(missing_fields))
        raise ValueError(f"CCTV 분석 결과에 필수 필드가 없습니다: {missing}")

    result_path = result.get("image_path", image_path)
    if result_path != image_path:
        raise ValueError("CCTV 분석 결과의 image_path가 요청값과 다릅니다.")

    if not isinstance(result["person_visible"], bool):
        raise TypeError("CCTV 분석 결과의 person_visible은 bool이어야 합니다.")

    posture = result["posture"]
    if posture not in CCTV_POSTURES:
        raise ValueError(f"지원하지 않는 CCTV posture입니다: {posture}")

    if not isinstance(result["fall_suspected"], bool):
        raise TypeError("CCTV 분석 결과의 fall_suspected는 bool이어야 합니다.")

    if not isinstance(result["description"], str):
        raise TypeError("CCTV 분석 결과의 description은 문자열이어야 합니다.")

    confidence = result.get("confidence")
    if confidence is not None:
        if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
            raise TypeError("CCTV 분석 결과의 confidence는 숫자여야 합니다.")
        if not 0 <= float(confidence) <= 1:
            raise ValueError("CCTV 분석 결과의 confidence는 0부터 1 사이여야 합니다.")

    status = result.get("status", "analyzed")
    if status not in {"analyzed", "unavailable", "failed"}:
        raise ValueError(f"지원하지 않는 CCTV status입니다: {status}")

    normalized_result = dict(result)
    normalized_result["image_path"] = image_path
    normalized_result["summary"] = result.get("summary") or result["description"]
    normalized_result["status"] = status

    return normalized_result
