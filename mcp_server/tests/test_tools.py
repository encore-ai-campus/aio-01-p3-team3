"""MCP 도구 반환 형식 테스트 — 두나."""

import pytest

from src.mock_data import HOSPITALS_BY_AREA, MOCK_PROFILES, SCENARIOS
from src.tools.cctv import analyze_cctv, capture_cctv
from src.tools.hospital import find_hospital
from src.tools.home import control_device, get_device_status, get_indoor_env
from src.tools.notify import call_119, notify_guardian
from src.tools.vitals import get_vitals
from src.vision import analyzer


def test_mock_data_matches_latest_team_contract() -> None:
    assert set(MOCK_PROFILES) == {"profile-01", "profile-02", "profile-03"}
    assert set(SCENARIOS) == {"normal", "heat", "induction", "fall", "critical"}
    assert SCENARIOS["fall"]["vital"] == {
        "heart_rate": 118,
        "systolic_bp": 120,
        "temperature_c": 36.4,
        "spo2": 96,
    }
    assert SCENARIOS["critical"]["vital"] == {
        "heart_rate": 140,
        "systolic_bp": 85,
        "temperature_c": 36.0,
        "spo2": 88,
    }
    assert all(
        "diastolic_bp" not in scenario["vital"]  # type: ignore[operator]
        for scenario in SCENARIOS.values()
    )


@pytest.mark.parametrize("profile_id", MOCK_PROFILES)
def test_get_vitals_supports_every_mock_profile(profile_id: str) -> None:
    result = get_vitals(profile_id, "normal")

    assert result == SCENARIOS["normal"]["vital"]


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_get_vitals_returns_each_scenario(scenario: str) -> None:
    result = get_vitals("profile-01", scenario)  # type: ignore[arg-type]

    assert result == SCENARIOS[scenario]["vital"]


def test_get_vitals_rejects_unknown_profile() -> None:
    with pytest.raises(ValueError, match="지원하지 않는 profile_id"):
        get_vitals("profile-99", "normal")


def test_get_vitals_rejects_unknown_scenario() -> None:
    with pytest.raises(ValueError, match="지원하지 않는 scenario"):
        get_vitals("profile-01", "storm")  # type: ignore[arg-type]


def test_get_vitals_returns_copy() -> None:
    result = get_vitals("profile-01", "normal")
    result["heart_rate"] = 999

    assert SCENARIOS["normal"]["vital"]["heart_rate"] == 72  # type: ignore[index]


@pytest.mark.parametrize("profile_id", MOCK_PROFILES)
def test_get_indoor_env_supports_every_mock_profile(profile_id: str) -> None:
    result = get_indoor_env(profile_id, "normal")

    assert result == SCENARIOS["normal"]["indoor_environment"]


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_get_indoor_env_returns_each_scenario(scenario: str) -> None:
    result = get_indoor_env("profile-01", scenario)  # type: ignore[arg-type]

    assert result == SCENARIOS[scenario]["indoor_environment"]


def test_get_indoor_env_rejects_unknown_profile() -> None:
    with pytest.raises(ValueError, match="지원하지 않는 profile_id"):
        get_indoor_env("profile-99", "normal")


def test_get_indoor_env_rejects_unknown_scenario() -> None:
    with pytest.raises(ValueError, match="지원하지 않는 scenario"):
        get_indoor_env("profile-01", "storm")  # type: ignore[arg-type]


def test_get_indoor_env_returns_copy() -> None:
    result = get_indoor_env("profile-01", "normal")
    result["temperature_c"] = 99.0

    original = SCENARIOS["normal"]["indoor_environment"]
    assert original["temperature_c"] == 24.0  # type: ignore[index]


@pytest.mark.parametrize("profile_id", MOCK_PROFILES)
def test_get_device_status_supports_every_mock_profile(profile_id: str) -> None:
    result = get_device_status(profile_id, "normal")

    assert result == SCENARIOS["normal"]["devices"]


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_get_device_status_returns_each_scenario(scenario: str) -> None:
    result = get_device_status("profile-01", scenario)  # type: ignore[arg-type]

    assert result == SCENARIOS[scenario]["devices"]


def test_get_device_status_reports_induction_duration() -> None:
    result = get_device_status("profile-01", "induction")

    assert result == {
        "air_conditioner": "off",
        "induction": "on",
        "induction_minutes": 120,
        "induction_temperature": 300,
    }


def test_get_device_status_rejects_unknown_profile() -> None:
    with pytest.raises(ValueError, match="지원하지 않는 profile_id"):
        get_device_status("profile-99", "normal")


def test_get_device_status_rejects_unknown_scenario() -> None:
    with pytest.raises(ValueError, match="지원하지 않는 scenario"):
        get_device_status("profile-01", "storm")  # type: ignore[arg-type]


def test_get_device_status_returns_copy() -> None:
    result = get_device_status("profile-01", "induction")
    result["induction_minutes"] = 999

    original = SCENARIOS["induction"]["devices"]
    assert original["induction_minutes"] == 120  # type: ignore[index]


@pytest.mark.parametrize("profile_id", MOCK_PROFILES)
def test_capture_cctv_supports_every_mock_profile(profile_id: str) -> None:
    result = capture_cctv(profile_id, "normal")

    assert result == {"image_path": "assets/cctv/normal.jpg"}


@pytest.mark.parametrize(
    ("scenario", "expected_path"),
    [
        ("normal", "assets/cctv/normal.jpg"),
        ("heat", "assets/cctv/normal.jpg"),
        ("induction", "assets/cctv/kitchen_empty.jpg"),
        ("fall", "assets/cctv/fall.jpg"),
    ],
)
def test_capture_cctv_returns_scenario_image(
    scenario: str,
    expected_path: str,
) -> None:
    result = capture_cctv("profile-01", scenario)  # type: ignore[arg-type]

    assert result == {"image_path": expected_path}


def test_capture_cctv_rejects_unknown_profile() -> None:
    with pytest.raises(ValueError, match="지원하지 않는 profile_id"):
        capture_cctv("profile-99", "normal")


def test_capture_cctv_rejects_unknown_scenario() -> None:
    with pytest.raises(ValueError, match="지원하지 않는 scenario"):
        capture_cctv("profile-01", "storm")  # type: ignore[arg-type]


def test_capture_cctv_returns_new_mapping() -> None:
    first = capture_cctv("profile-01", "fall")
    second = capture_cctv("profile-01", "fall")
    first["image_path"] = "changed.jpg"

    assert second == {"image_path": "assets/cctv/fall.jpg"}


@pytest.mark.parametrize("area", HOSPITALS_BY_AREA)
def test_find_hospital_supports_every_mock_area(area: str) -> None:
    result = find_hospital(area)

    expected_distance = min(
        float(hospital["distance_km"])
        for hospital in HOSPITALS_BY_AREA[area]
    )
    assert result["distance_km"] == expected_distance
    assert set(result) == {"name", "distance_km", "type"}


def test_find_hospital_returns_nearest_hospital() -> None:
    result = find_hospital("서울시 강남구")

    assert result == {
        "name": "강남안심병원",
        "distance_km": 1.2,
        "type": "응급실",
    }


def test_find_hospital_rejects_blank_area() -> None:
    with pytest.raises(ValueError, match="area는 비어 있을 수 없습니다"):
        find_hospital("   ")


def test_find_hospital_rejects_unknown_area() -> None:
    with pytest.raises(ValueError, match="지원하지 않는 area"):
        find_hospital("서울시 없는구")


def test_find_hospital_returns_copy() -> None:
    result = find_hospital("서울시 강남구")
    result["name"] = "변경된 병원"

    assert HOSPITALS_BY_AREA["서울시 강남구"][0]["name"] == "강남안심병원"


def test_control_device_runs_aircon_mock() -> None:
    result = control_device("aircon", action="cool")

    assert result == {
        "tool": "control_device",
        "status": "success",
        "message": "에어컨 냉방을 Mock으로 실행했습니다.",
        "recovery": None,
    }


def test_control_device_runs_induction_off_mock() -> None:
    result = control_device("induction", action="off")

    assert result == {
        "tool": "control_device",
        "status": "success",
        "message": "인덕션 끄기를 Mock으로 실행했습니다.",
        "recovery": None,
    }


def test_control_device_rejects_unknown_device() -> None:
    with pytest.raises(ValueError, match="지원하지 않는 device"):
        control_device("heater", action="off")  # type: ignore[arg-type]


def test_control_device_rejects_unknown_aircon_action() -> None:
    with pytest.raises(ValueError, match="action은 cool, heat, off"):
        control_device("aircon", action="on")  # type: ignore[arg-type]


def test_control_device_rejects_turning_on_induction() -> None:
    with pytest.raises(ValueError, match="action은 off만 지원"):
        control_device("induction", action="on")  # type: ignore[arg-type]


def test_control_device_does_not_change_scenario_data() -> None:
    before = get_device_status("profile-01", "heat")

    control_device("aircon", action="cool")

    assert get_device_status("profile-01", "heat") == before


def test_notify_guardian_returns_mock_success() -> None:
    result = notify_guardian("어르신 상태 확인이 필요합니다.")

    assert result == {
        "tool": "notify_guardian",
        "status": "success",
        "message": "보호자 알림을 Mock으로 실행했습니다.",
        "recovery": None,
    }


def test_notify_guardian_rejects_blank_message() -> None:
    with pytest.raises(ValueError, match="message는 비어 있을 수 없습니다"):
        notify_guardian("   ")


def test_notify_guardian_rejects_non_string_message() -> None:
    with pytest.raises(TypeError, match="message는 문자열이어야 합니다"):
        notify_guardian(None)  # type: ignore[arg-type]


def test_call_119_returns_mock_success() -> None:
    result = call_119("CCTV에서 쓰러짐이 의심됩니다.")

    assert result == {
        "tool": "call_119",
        "status": "success",
        "message": "119 호출을 Mock으로 실행했습니다.",
        "recovery": None,
    }


def test_call_119_rejects_blank_message() -> None:
    with pytest.raises(ValueError, match="message는 비어 있을 수 없습니다"):
        call_119("   ")


def test_call_119_rejects_non_string_message() -> None:
    with pytest.raises(TypeError, match="message는 문자열이어야 합니다"):
        call_119(None)  # type: ignore[arg-type]


def test_analyze_cctv_delegates_to_haedeun_function(monkeypatch) -> None:
    received_paths: list[str] = []

    def fake_analyze_cctv_or_unavailable(image_path: str) -> dict[str, object]:
        received_paths.append(image_path)
        return {
            "person_visible": True,
            "posture": "fallen",
            "fall_suspected": True,
            "description": "거실 바닥에 사람이 쓰러져 있는 것으로 의심됩니다.",
            "confidence": 0.96,
        }

    monkeypatch.setattr(
        analyzer,
        "analyze_cctv_or_unavailable",
        fake_analyze_cctv_or_unavailable,
        raising=False,
    )

    result = analyze_cctv("assets/cctv/fall.jpg")

    assert received_paths == ["assets/cctv/fall.jpg"]
    assert result == {
        "image_path": "assets/cctv/fall.jpg",
        "person_visible": True,
        "posture": "fallen",
        "fall_suspected": True,
        "description": "거실 바닥에 사람이 쓰러져 있는 것으로 의심됩니다.",
        "confidence": 0.96,
        "summary": "거실 바닥에 사람이 쓰러져 있는 것으로 의심됩니다.",
        "status": "analyzed",
    }


def test_analyze_cctv_rejects_blank_path() -> None:
    with pytest.raises(ValueError, match="image_path는 비어 있을 수 없습니다"):
        analyze_cctv("   ")


def test_analyze_cctv_rejects_non_string_path() -> None:
    with pytest.raises(TypeError, match="image_path는 문자열이어야 합니다"):
        analyze_cctv(None)  # type: ignore[arg-type]


def test_analyze_cctv_reports_missing_haedeun_function(monkeypatch) -> None:
    monkeypatch.delattr(analyzer, "analyze_cctv_or_unavailable", raising=False)

    with pytest.raises(RuntimeError, match="아직 구현되지 않았습니다"):
        analyze_cctv("assets/cctv/fall.jpg")


def test_analyze_cctv_rejects_non_mapping_result(monkeypatch) -> None:
    monkeypatch.setattr(
        analyzer,
        "analyze_cctv_or_unavailable",
        lambda _image_path: "invalid result",
        raising=False,
    )

    with pytest.raises(TypeError, match="분석 결과는 dict"):
        analyze_cctv("assets/cctv/fall.jpg")


def test_analyze_cctv_rejects_missing_result_fields(monkeypatch) -> None:
    monkeypatch.setattr(
        analyzer,
        "analyze_cctv_or_unavailable",
        lambda _image_path: {
            "person_visible": True,
            "posture": "fallen",
            "fall_suspected": True,
            "confidence": 0.96,
        },
        raising=False,
    )

    with pytest.raises(ValueError, match="필수 필드가 없습니다: description"):
        analyze_cctv("assets/cctv/fall.jpg")


def test_analyze_cctv_rejects_different_result_path(monkeypatch) -> None:
    monkeypatch.setattr(
        analyzer,
        "analyze_cctv_or_unavailable",
        lambda _image_path: {
            "image_path": "assets/cctv/other.jpg",
            "person_visible": False,
            "posture": "none",
            "fall_suspected": False,
            "description": "영상에서 사람을 확인할 수 없습니다.",
            "confidence": 0.0,
        },
        raising=False,
    )

    with pytest.raises(ValueError, match="image_path가 요청값과 다릅니다"):
        analyze_cctv("assets/cctv/fall.jpg")


def test_analyze_cctv_rejects_invalid_posture(monkeypatch) -> None:
    monkeypatch.setattr(
        analyzer,
        "analyze_cctv_or_unavailable",
        lambda _image_path: {
            "person_visible": True,
            "posture": "crawling",
            "fall_suspected": False,
            "description": "사람의 자세를 확인했습니다.",
            "confidence": 0.5,
        },
        raising=False,
    )

    with pytest.raises(ValueError, match="지원하지 않는 CCTV posture"):
        analyze_cctv("assets/cctv/fall.jpg")


def test_analyze_cctv_rejects_non_numeric_confidence(monkeypatch) -> None:
    monkeypatch.setattr(
        analyzer,
        "analyze_cctv_or_unavailable",
        lambda _image_path: {
            "person_visible": True,
            "posture": "standing",
            "fall_suspected": False,
            "description": "사람이 서 있는 것으로 보입니다.",
            "confidence": "high",
        },
        raising=False,
    )

    with pytest.raises(TypeError, match="confidence는 숫자"):
        analyze_cctv("assets/cctv/fall.jpg")


def test_analyze_cctv_allows_missing_optional_confidence(monkeypatch) -> None:
    monkeypatch.setattr(
        analyzer,
        "analyze_cctv_or_unavailable",
        lambda _image_path: {
            "person_visible": False,
            "posture": "none",
            "fall_suspected": False,
            "description": "영상에서 사람을 확인할 수 없습니다.",
        },
        raising=False,
    )

    result = analyze_cctv("assets/cctv/normal.jpg")

    assert "confidence" not in result
    assert result["summary"] == "영상에서 사람을 확인할 수 없습니다."
    assert result["status"] == "analyzed"


def test_analyze_cctv_rejects_out_of_range_confidence(monkeypatch) -> None:
    monkeypatch.setattr(
        analyzer,
        "analyze_cctv_or_unavailable",
        lambda _image_path: {
            "person_visible": True,
            "posture": "standing",
            "fall_suspected": False,
            "description": "사람이 서 있습니다.",
            "confidence": 1.5,
        },
        raising=False,
    )

    with pytest.raises(ValueError, match="0부터 1 사이"):
        analyze_cctv("assets/cctv/normal.jpg")
