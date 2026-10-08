"""가상 어르신의 바이탈 데이터를 백엔드로 주기적으로 전송한다."""

from __future__ import annotations

import argparse
import logging
import os
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


def _positive_float(value: str, name: str) -> float:
    try:
        parsed = float(value)
    except ValueError as exc:
        raise ValueError(f"{name}은 숫자여야 합니다: {value}") from exc

    if parsed <= 0:
        raise ValueError(f"{name}은 0보다 커야 합니다: {value}")
    return parsed


@dataclass(frozen=True)
class SenderSettings:
    """바이탈 전송 프로그램 설정."""

    ingest_url: str = DEFAULT_INGEST_URL
    interval_seconds: float = 15.0
    timeout_seconds: float = 5.0
    scenario: Scenario = "normal"

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
        )


def build_vital_payload(
    profile_id: str,
    scenario: Scenario,
    *,
    measured_at: datetime | None = None,
) -> dict[str, object]:
    """기존 Mock 바이탈을 수집 API 요청 형식으로 변환한다."""

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
) -> dict[str, str]:
    """최신 계약의 세 프로필을 한 번씩 전송하고 결과를 반환한다."""

    results: dict[str, str] = {}
    cycle_time = measured_at or datetime.now().astimezone()

    for profile_id in MOCK_PROFILES:
        payload = build_vital_payload(
            profile_id,
            settings.scenario,
            measured_at=cycle_time,
        )
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
            settings.scenario,
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

    try:
        while True:
            send_vital_cycle(active_client, settings)
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
