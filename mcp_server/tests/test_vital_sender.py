"""15초 주기 바이탈 HTTP 전송 프로그램 테스트 — 두나."""

import json
from datetime import datetime, timezone

import httpx
import pytest

from src.mock_data import MOCK_PROFILES, SCENARIOS
from src.vital_sender import (
    SenderSettings,
    build_vital_payload,
    post_vital_reading,
    run_sender,
    send_vital_cycle,
)


FIXED_TIME = datetime(2026, 10, 8, 15, 30, tzinfo=timezone.utc)


def test_settings_use_agreed_defaults() -> None:
    settings = SenderSettings.from_env({})

    assert settings.ingest_url == "http://localhost:8000/vitals/readings"
    assert settings.interval_seconds == 15
    assert settings.timeout_seconds == 5
    assert settings.scenario == "normal"


def test_settings_read_environment_values() -> None:
    settings = SenderSettings.from_env(
        {
            "VITAL_INGEST_URL": "http://backend:8000/vitals/readings",
            "VITAL_SEND_INTERVAL_SECONDS": "20",
            "VITAL_HTTP_TIMEOUT_SECONDS": "3",
            "VITAL_SCENARIO": "fall",
        }
    )

    assert settings.ingest_url == "http://backend:8000/vitals/readings"
    assert settings.interval_seconds == 20
    assert settings.timeout_seconds == 3
    assert settings.scenario == "fall"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("VITAL_SEND_INTERVAL_SECONDS", "0"),
        ("VITAL_HTTP_TIMEOUT_SECONDS", "not-a-number"),
        ("VITAL_SCENARIO", "storm"),
    ],
)
def test_settings_reject_invalid_values(field: str, value: str) -> None:
    with pytest.raises(ValueError):
        SenderSettings.from_env({field: value})


def test_build_payload_uses_existing_vital_contract() -> None:
    payload = build_vital_payload(
        "profile-01",
        "fall",
        measured_at=FIXED_TIME,
    )

    assert payload == {
        "profile_id": "profile-01",
        "heart_rate": 118,
        "systolic_bp": 120,
        "temperature_c": 36.4,
        "spo2": 96,
        "measured_at": "2026-10-08T15:30:00+00:00",
    }


def test_build_payload_does_not_modify_shared_mock_data() -> None:
    original_vital = dict(SCENARIOS["normal"]["vital"])  # type: ignore[arg-type]

    build_vital_payload("profile-01", "normal", measured_at=FIXED_TIME)

    assert SCENARIOS["normal"]["vital"] == original_vital
    assert "profile_id" not in SCENARIOS["normal"]["vital"]  # type: ignore[operator]


def test_post_vital_reading_sends_json() -> None:
    captured: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content))
        return httpx.Response(
            201,
            json={"status": "stored", "profile_id": "profile-01"},
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = post_vital_reading(
            client,
            "http://backend.test/vitals/readings",
            {"profile_id": "profile-01", "heart_rate": 72},
        )

    assert captured == [{"profile_id": "profile-01", "heart_rate": 72}]
    assert result["status"] == "stored"


def test_send_cycle_sends_all_profiles() -> None:
    received_profiles: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        received_profiles.append(payload["profile_id"])
        return httpx.Response(201, json={"status": "stored"})

    settings = SenderSettings(ingest_url="http://backend.test/vitals/readings")
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        results = send_vital_cycle(client, settings, measured_at=FIXED_TIME)

    assert received_profiles == list(MOCK_PROFILES)
    assert results == {profile_id: "sent" for profile_id in MOCK_PROFILES}


def test_send_cycle_continues_after_one_profile_fails() -> None:
    requested_profiles: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        profile_id = json.loads(request.content)["profile_id"]
        requested_profiles.append(profile_id)
        if profile_id == "profile-03":
            return httpx.Response(500, json={"detail": "temporary failure"})
        return httpx.Response(201, json={"status": "stored"})

    settings = SenderSettings(ingest_url="http://backend.test/vitals/readings")
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        results = send_vital_cycle(client, settings, measured_at=FIXED_TIME)

    assert requested_profiles == list(MOCK_PROFILES)
    assert results["profile-03"].startswith("failed:")
    assert results["profile-01"] == "sent"
    assert results["profile-02"] == "sent"


def test_post_vital_reading_rejects_non_object_response() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(201, json=["stored"])
    )

    with httpx.Client(transport=transport) as client:
        with pytest.raises(ValueError, match="JSON 객체"):
            post_vital_reading(
                client,
                "http://backend.test/vitals/readings",
                {"profile_id": "profile-01"},
            )


def test_run_sender_once_does_not_wait() -> None:
    request_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal request_count
        request_count += 1
        return httpx.Response(201, json={"status": "stored"})

    settings = SenderSettings(ingest_url="http://backend.test/vitals/readings")
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        run_sender(settings, once=True, client=client)

    assert request_count == len(MOCK_PROFILES)
