"""가상 어르신의 바이탈 데이터를 백엔드로 주기적으로 전송한다."""

from __future__ import annotations

import argparse
import logging
import os
import random
import time
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from threading import Event
from typing import Mapping
from urllib.parse import urlparse

import httpx
from dotenv import load_dotenv

from .mock_data import MOCK_PROFILES, SCENARIOS, Scenario


LOGGER = logging.getLogger("vital_sender")
PROJECT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_INGEST_URL = "http://localhost:8000/vitals/readings"

# 보호자 로그인 시연에서 어르신마다 보여 줄 시나리오 (docs/scenarios.md 3장, frontend PROFILE_SCENARIO와 같다).
# 백엔드는 (프로필, 시나리오)로 최신 측정값을 찾으므로 전송도 같은 짝으로 해야 한다.
PROFILE_SCENARIOS: dict[str, Scenario] = {
    "profile-01": "fall",
    "profile-02": "heat",
    "profile-03": "induction",
    "profile-04": "critical",
}

# 실시간처럼 보이게 값을 흔들 때의 최대 변동폭.
JITTER_STEP = {"heart_rate": 3, "systolic_bp": 3, "temperature_c": 0.1, "spo2": 1}
# 직전 값에서 한 번에 움직이는 최대 폭. 자주 보낼 때 값이 튀지 않고 사람의 맥박처럼 서서히 오르내린다.
JITTER_WALK_STEP = {"heart_rate": 2, "systolic_bp": 1, "temperature_c": 0.1, "spo2": 1}
# 변동해도 위험도 판정(backend/src/rules/risk.py 점수표)이 시나리오 기대 결과에서 벗어나지 않는 범위.
# 값이 점수 경계에 걸리는 곳(critical 체온 36.0, 산소포화도 96 등)은 한쪽으로만 흔든다.
JITTER_BOUNDS: dict[str, dict[str, tuple[float, float]]] = {
    "normal": {"heart_rate": (62, 82), "systolic_bp": (118, 132), "temperature_c": (36.3, 36.8), "spo2": (97, 99)},
    "heat": {"heart_rate": (100, 108), "systolic_bp": (133, 147), "temperature_c": (37.6, 37.9), "spo2": (96, 97)},
    "induction": {"heart_rate": (74, 86), "systolic_bp": (123, 137), "temperature_c": (36.4, 36.8), "spo2": (96, 98)},
    "fall": {"heart_rate": (114, 122), "systolic_bp": (114, 126), "temperature_c": (36.3, 36.6), "spo2": (96, 97)},
    "critical": {"heart_rate": (135, 145), "systolic_bp": (80, 88), "temperature_c": (35.8, 36.0), "spo2": (86, 89)},
}


def _positive_float(value: str, name: str) -> float:
    try:
        parsed = float(value)
    except ValueError as exc:
        raise ValueError(f"{name}은 숫자여야 합니다: {value}") from exc

    if parsed <= 0:
        raise ValueError(f"{name}은 0보다 커야 합니다: {value}")
    return parsed


def _flag(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def jitter_vital(
    vital: dict[str, object],
    scenario: str,
    rng: random.Random,
    previous: dict[str, float] | None = None,
) -> None:
    """측정값을 시나리오 범위(JITTER_BOUNDS) 안에서 조금 흔든다. vital을 직접 바꾼다.

    previous(직전에 보낸 값)가 있으면 거기서 JITTER_WALK_STEP만큼만 움직이고, 없으면 시나리오 기본값에서 시작한다.
    """
    for field, step in JITTER_STEP.items():
        base = vital.get(field)
        if base is None:
            continue
        if previous and previous.get(field) is not None:
            base, step = previous[field], JITTER_WALK_STEP[field]
        low, high = JITTER_BOUNDS[scenario][field]
        value = min(max(float(base) + rng.uniform(-step, step), low), high)
        vital[field] = round(value, 1) if field == "temperature_c" else round(value)


@dataclass(frozen=True)
class SenderSettings:
    """바이탈 전송 프로그램 설정."""

    ingest_url: str = DEFAULT_INGEST_URL
    interval_seconds: float = 15.0
    timeout_seconds: float = 5.0
    scenario: Scenario = "normal"
    per_profile: bool = False  # True면 scenario 대신 어르신마다 PROFILE_SCENARIOS의 시나리오로 보낸다
    jitter: bool = False       # True면 측정값을 시나리오 범위 안에서 조금씩 흔든다

    def __post_init__(self) -> None:
        parsed_url = urlparse(self.ingest_url)
        if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
            raise ValueError(
                "VITAL_INGEST_URL은 http 또는 https 주소여야 합니다: "
                f"{self.ingest_url}"
            )
        if self.interval_seconds <= 0:
            raise ValueError("VITAL_SEND_INTERVAL_SECONDS는 0보다 커야 합니다.")
        if self.timeout_seconds <= 0:
            raise ValueError("VITAL_HTTP_TIMEOUT_SECONDS는 0보다 커야 합니다.")
        if self.scenario not in SCENARIOS:
            raise ValueError(f"지원하지 않는 VITAL_SCENARIO입니다: {self.scenario}")

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> SenderSettings:
        values = os.environ if environ is None else environ
        scenario = values.get("VITAL_SCENARIO", "normal")
        return cls(
            ingest_url=values.get("VITAL_INGEST_URL", DEFAULT_INGEST_URL),
            interval_seconds=_positive_float(
                values.get("VITAL_SEND_INTERVAL_SECONDS", "15"),
                "VITAL_SEND_INTERVAL_SECONDS",
            ),
            timeout_seconds=_positive_float(
                values.get("VITAL_HTTP_TIMEOUT_SECONDS", "5"),
                "VITAL_HTTP_TIMEOUT_SECONDS",
            ),
            scenario=scenario,  # type: ignore[arg-type]
            per_profile=_flag(values.get("VITAL_PER_PROFILE")),
            jitter=_flag(values.get("VITAL_JITTER")),
        )


def build_vital_payload(
    profile_id: str,
    scenario: Scenario,
    *,
    measured_at: datetime | None = None,
    rng: random.Random | None = None,
    previous: dict[str, float] | None = None,
) -> dict[str, object]:
    """기존 Mock 바이탈을 수집 API 요청 형식으로 변환한다. rng를 주면 값을 범위 안에서 흔들고, previous를 주면 직전 값에서 이어서 움직인다."""

    if profile_id not in MOCK_PROFILES:
        raise ValueError(f"지원하지 않는 profile_id입니다: {profile_id}")
    if scenario not in SCENARIOS:
        raise ValueError(f"지원하지 않는 scenario입니다: {scenario}")

    vital = deepcopy(SCENARIOS[scenario]["vital"])
    if not isinstance(vital, dict):
        raise TypeError(f"{scenario} 시나리오의 vital 데이터 형식이 올바르지 않습니다.")

    timestamp = measured_at or datetime.now().astimezone()
    if timestamp.tzinfo is None:
        timestamp = timestamp.astimezone()

    if rng is not None:
        jitter_vital(vital, scenario, rng, previous)

    vital["scenario"] = scenario
    vital["profile_id"] = profile_id
    vital["measured_at"] = timestamp.isoformat(timespec="seconds")
    return vital


def post_vital_reading(
    client: httpx.Client,
    ingest_url: str,
    payload: Mapping[str, object],
) -> dict[str, object]:
    """바이탈 한 건을 전송하고 백엔드의 JSON 응답을 반환한다."""

    response = client.post(ingest_url, json=dict(payload))
    response.raise_for_status()
    result = response.json()
    if not isinstance(result, dict):
        raise ValueError("바이탈 수집 API 응답은 JSON 객체여야 합니다.")
    return result


def send_vital_cycle(
    client: httpx.Client,
    settings: SenderSettings,
    *,
    measured_at: datetime | None = None,
    rng: random.Random | None = None,
    previous: dict[str, dict[str, float]] | None = None,
) -> dict[str, str]:
    """어르신 프로필을 한 번씩 전송하고 결과를 반환한다.

    previous는 어르신별로 직전에 보낸 값을 담는 상자다. 같은 상자를 계속 넘기면 값이 직전 값에서 이어서 움직인다.
    """

    results: dict[str, str] = {}
    cycle_time = measured_at or datetime.now().astimezone()

    if rng is None and settings.jitter:
        rng = random.Random()
    for profile_id in MOCK_PROFILES:
        scenario = PROFILE_SCENARIOS.get(profile_id, settings.scenario) if settings.per_profile else settings.scenario
        payload = build_vital_payload(
            profile_id,
            scenario,
            measured_at=cycle_time,
            rng=rng,
            previous=previous.get(profile_id) if previous is not None else None,
        )
        if previous is not None and rng is not None:
            previous[profile_id] = {field: payload[field] for field in JITTER_STEP if payload.get(field) is not None}
        try:
            response = post_vital_reading(client, settings.ingest_url, payload)
        except (httpx.HTTPError, ValueError) as exc:
            results[profile_id] = f"failed: {exc}"
            LOGGER.error("바이탈 전송 실패 profile_id=%s error=%s", profile_id, exc)
            continue

        results[profile_id] = "sent"
        LOGGER.info(
            "바이탈 전송 완료 profile_id=%s scenario=%s measured_at=%s response=%s",
            profile_id,
            payload["scenario"],
            payload["measured_at"],
            response,
        )

    return results


def run_sender(
    settings: SenderSettings,
    *,
    once: bool = False,
    stop_event: Event | None = None,
    client: httpx.Client | None = None,
) -> None:
    """즉시 한 주기를 전송한 뒤 설정된 간격으로 반복한다."""

    owns_client = client is None
    active_client = client or httpx.Client(timeout=settings.timeout_seconds)

    rng = random.Random() if settings.jitter else None
    previous: dict[str, dict[str, float]] = {}   # 어르신별 직전 값. 값이 서서히 이어서 움직이게 한다
    try:
        while True:
            send_vital_cycle(active_client, settings, rng=rng, previous=previous)
            if once:
                return

            if stop_event is not None:
                if stop_event.wait(settings.interval_seconds):
                    return
            else:
                time.sleep(settings.interval_seconds)
    finally:
        if owns_client:
            active_client.close()


def _parse_args(settings: SenderSettings) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="가상 어르신 3명의 바이탈 데이터를 주기적으로 전송합니다.",
    )
    parser.add_argument("--url", default=settings.ingest_url, help="바이탈 수집 API 주소")
    parser.add_argument(
        "--interval",
        type=float,
        default=settings.interval_seconds,
        help="전송 주기(초)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=settings.timeout_seconds,
        help="HTTP 요청 제한 시간(초)",
    )
    parser.add_argument(
        "--scenario",
        choices=tuple(SCENARIOS),
        default=settings.scenario,
        help="전송할 Mock 바이탈 시나리오",
    )
    parser.add_argument(
        "--per-profile",
        action="store_true",
        default=settings.per_profile,
        help="어르신마다 자기 시나리오(A 낙상·B 폭염·C 인덕션·D 위급)로 전송 (--scenario 무시)",
    )
    parser.add_argument(
        "--jitter",
        action="store_true",
        default=settings.jitter,
        help="측정값을 시나리오 범위 안에서 조금씩 흔들어 실시간처럼 보내기",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="세 프로필을 한 번만 전송하고 종료",
    )
    return parser.parse_args()


def main() -> int:
    load_dotenv(PROJECT_DIR / "config" / ".env")
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    try:
        defaults = SenderSettings.from_env()
        args = _parse_args(defaults)
        settings = SenderSettings(
            ingest_url=args.url,
            interval_seconds=args.interval,
            timeout_seconds=args.timeout,
            scenario=args.scenario,
            per_profile=args.per_profile,
            jitter=args.jitter,
        )
        run_sender(settings, once=args.once)
    except KeyboardInterrupt:
        LOGGER.info("사용자 요청으로 바이탈 전송을 종료합니다.")
    except ValueError as exc:
        LOGGER.error("바이탈 전송 설정 오류: %s", exc)
        return 2

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
