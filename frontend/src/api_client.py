"""백엔드 API 호출 함수 모음 — 수언·두나 공용."""

from __future__ import annotations

from pathlib import PurePath
from typing import Literal, Protocol
from urllib.parse import quote

import requests


DEFAULT_TIMEOUT_SECONDS = 10.0
SCENARIOS = frozenset({"normal", "heat", "induction", "fall", "critical"})
FAULT_NAMES = frozenset({"vital", "iot", "vision", "llm"})


class BackendAPIError(RuntimeError):
    """백엔드 연결 또는 응답 계약이 올바르지 않을 때 발생한다."""


class HTTPSession(Protocol):
    def post(self, url: str, **kwargs: object) -> requests.Response: ...

    def get(self, url: str, **kwargs: object) -> requests.Response: ...


def _base_url(backend_url: str) -> str:
    normalized = backend_url.strip().rstrip("/")
    if not normalized.startswith(("http://", "https://")):
        raise ValueError("backend_url은 http 또는 https 주소여야 합니다.")
    return normalized


def _error_detail(response: requests.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return response.text.strip() or f"HTTP {response.status_code}"

    if isinstance(body, dict):
        detail = body.get("detail") or body.get("message")
        if detail:
            return str(detail)
    return f"HTTP {response.status_code}"


def _response_json(response: requests.Response, action: str) -> dict[str, object]:
    if not response.ok:
        raise BackendAPIError(f"{action} 실패: {_error_detail(response)}")

    try:
        payload = response.json()
    except ValueError as exc:
        raise BackendAPIError(f"{action} 응답이 JSON이 아닙니다.") from exc

    if not isinstance(payload, dict):
        raise BackendAPIError(f"{action} 응답은 JSON 객체여야 합니다.")
    return payload


def request_care_run(
    backend_url: str,
    profile_id: str,
    scenario: str,
    fault: list[str],
    *,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    session: HTTPSession | None = None,
) -> dict[str, object]:
    """돌봄 시나리오를 실행하고 ``CareRunResponse``를 반환한다."""

    if not profile_id.strip():
        raise ValueError("profile_id는 비어 있을 수 없습니다.")
    if scenario not in SCENARIOS:
        raise ValueError(f"지원하지 않는 scenario입니다: {scenario}")
    unknown_faults = set(fault) - FAULT_NAMES
    if unknown_faults:
        unknown = ", ".join(sorted(unknown_faults))
        raise ValueError(f"지원하지 않는 fault입니다: {unknown}")

    requester = session or requests
    url = f"{_base_url(backend_url)}/care/run"
    try:
        response = requester.post(
            url,
            json={
                "profile_id": profile_id,
                "scenario": scenario,
                "fault": list(fault),
            },
            timeout=timeout,
        )
    except requests.RequestException as exc:
        raise BackendAPIError(f"돌봄 실행 API에 연결할 수 없습니다: {exc}") from exc

    return _response_json(response, "돌봄 실행")


def submit_care_decision(
    backend_url: str,
    run_id: str,
    decision: Literal["approve", "reject"],
    *,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    session: HTTPSession | None = None,
) -> dict[str, object]:
    """보호자의 승인 또는 거절을 전송한다."""

    if not run_id.strip():
        raise ValueError("run_id는 비어 있을 수 없습니다.")
    if decision not in {"approve", "reject"}:
        raise ValueError(f"지원하지 않는 decision입니다: {decision}")

    requester = session or requests
    url = f"{_base_url(backend_url)}/care/approve"
    try:
        response = requester.post(
            url,
            json={"run_id": run_id, "decision": decision},
            timeout=timeout,
        )
    except requests.RequestException as exc:
        raise BackendAPIError(f"승인 처리 API에 연결할 수 없습니다: {exc}") from exc

    return _response_json(response, "승인 처리")


def fetch_cctv_image(
    backend_url: str,
    image_path: str,
    *,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    session: HTTPSession | None = None,
) -> bytes:
    """응답의 이미지 경로에서 파일명만 추출해 CCTV 이미지를 가져온다."""

    image_name = PurePath(image_path.replace("\\", "/")).name
    if not image_name:
        raise ValueError("image_path에서 파일명을 찾을 수 없습니다.")

    requester = session or requests
    url = f"{_base_url(backend_url)}/cctv/{quote(image_name, safe='')}"
    try:
        response = requester.get(url, timeout=timeout)
    except requests.RequestException as exc:
        raise BackendAPIError(f"CCTV 이미지를 가져올 수 없습니다: {exc}") from exc

    if not response.ok:
        raise BackendAPIError(f"CCTV 이미지 조회 실패: {_error_detail(response)}")
    return response.content


def fetch_cctv_video(
    backend_url: str,
    video_name: str,
    *,
    timeout: float | tuple[float, float] = (5.0, 60.0),   # (연결 5초, 영상 받기 60초): 서버가 안 열려 있어도 화면이 오래 멈추지 않게
    session: HTTPSession | None = None,
) -> bytes:
    """백엔드를 거쳐 MCP 서버의 CCTV 영상(예: ``lying.mp4``)을 가져온다."""

    name = PurePath(video_name.replace("\\", "/")).name
    if not name:
        raise ValueError("video_name에서 파일명을 찾을 수 없습니다.")

    requester = session or requests
    url = f"{_base_url(backend_url)}/video/{quote(name, safe='')}"
    try:
        response = requester.get(url, timeout=timeout)
    except requests.RequestException as exc:
        raise BackendAPIError(f"CCTV 영상을 가져올 수 없습니다: {exc}") from exc

    if not response.ok:
        raise BackendAPIError(f"CCTV 영상 조회 실패: {_error_detail(response)}")
    return response.content


def request_latest_vital(
    backend_url: str,
    profile_id: str,
    scenario: str,
    *,
    limit: int = 20,
    timeout: float = 5.0,
    session: HTTPSession | None = None,
) -> dict[str, object]:
    """실시간 심박수 화면용 최근 바이탈(``VitalLatestResponse``)을 가져온다. 값이 없으면 status가 no_data."""

    if not profile_id.strip():
        raise ValueError("profile_id는 비어 있을 수 없습니다.")
    if scenario not in SCENARIOS:
        raise ValueError(f"지원하지 않는 scenario입니다: {scenario}")

    requester = session or requests
    url = f"{_base_url(backend_url)}/vitals/latest"
    try:
        response = requester.get(
            url,
            params={"profile_id": profile_id, "scenario": scenario, "limit": limit},
            timeout=timeout,
        )
    except requests.RequestException as exc:
        raise BackendAPIError(f"실시간 바이탈 API에 연결할 수 없습니다: {exc}") from exc

    return _response_json(response, "실시간 바이탈 조회")


DEVICE_NAMES = frozenset({"aircon", "induction"})


def fetch_device_states(
    backend_url: str,
    profile_id: str,
    *,
    timeout: float = 5.0,
    session: HTTPSession | None = None,
) -> dict[str, str]:
    """토글로 바꾼 기기 상태({"aircon": "on", ...}). 바꾼 적 없는 기기는 없다."""

    if not profile_id.strip():
        raise ValueError("profile_id는 비어 있을 수 없습니다.")
    requester = session or requests
    url = f"{_base_url(backend_url)}/devices/{quote(profile_id.strip(), safe='')}"
    try:
        response = requester.get(url, timeout=timeout)
    except requests.RequestException as exc:
        raise BackendAPIError(f"기기 상태를 가져올 수 없습니다: {exc}") from exc

    devices = _response_json(response, "기기 상태 조회").get("devices")
    return {str(name): str(state) for name, state in devices.items()} if isinstance(devices, dict) else {}


def control_device(
    backend_url: str,
    profile_id: str,
    device: str,
    state: str,
    *,
    timeout: float = 15.0,
    session: HTTPSession | None = None,
) -> dict[str, object]:
    """에어컨·인덕션을 켜거나(``on``) 끈다(``off``). 백엔드가 MCP Mock 제어를 실행하고 상태를 저장한다."""

    if not profile_id.strip():
        raise ValueError("profile_id는 비어 있을 수 없습니다.")
    if device not in DEVICE_NAMES:
        raise ValueError(f"지원하지 않는 device입니다: {device}")
    if state not in {"on", "off"}:
        raise ValueError(f"지원하지 않는 state입니다: {state}")

    requester = session or requests
    url = f"{_base_url(backend_url)}/devices/control"
    try:
        response = requester.post(url, json={"profile_id": profile_id, "device": device, "state": state}, timeout=timeout)
    except requests.RequestException as exc:
        raise BackendAPIError(f"기기를 제어할 수 없습니다: {exc}") from exc

    return _response_json(response, "기기 제어")

