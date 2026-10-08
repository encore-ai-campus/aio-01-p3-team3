"""백엔드 API 클라이언트 계약 테스트 — 두나."""

from __future__ import annotations

from typing import Any

import pytest
import requests

from src.api_client import (
    BackendAPIError,
    fetch_cctv_image,
    request_care_run,
    submit_care_decision,
)


class FakeResponse:
    def __init__(
        self,
        status_code: int,
        payload: object,
        *,
        content: bytes = b"",
        text: str = "",
    ) -> None:
        self.status_code = status_code
        self.ok = 200 <= status_code < 400
        self._payload = payload
        self.content = content
        self.text = text

    def json(self) -> object:
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class FakeSession:
    def __init__(self, response: FakeResponse | Exception) -> None:
        self.response = response
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    def post(self, url: str, **kwargs: Any) -> FakeResponse:
        self.calls.append(("POST", url, kwargs))
        if isinstance(self.response, Exception):
            raise self.response
        return self.response

    def get(self, url: str, **kwargs: Any) -> FakeResponse:
        self.calls.append(("GET", url, kwargs))
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def test_request_care_run_uses_agreed_contract() -> None:
    session = FakeSession(
        FakeResponse(
            200,
            {"run_id": "run-001", "status": "pending_approval"},
        )
    )

    result = request_care_run(
        "http://backend.test/",
        "profile-01",
        "fall",
        ["vision"],
        timeout=3,
        session=session,  # type: ignore[arg-type]
    )

    assert result["run_id"] == "run-001"
    assert session.calls == [
        (
            "POST",
            "http://backend.test/care/run",
            {
                "json": {
                    "profile_id": "profile-01",
                    "scenario": "fall",
                    "fault": ["vision"],
                },
                "timeout": 3,
            },
        )
    ]


@pytest.mark.parametrize("decision", ["approve", "reject"])
def test_submit_care_decision_uses_same_run_id(decision: str) -> None:
    session = FakeSession(
        FakeResponse(200, {"run_id": "run-001", "status": "completed"})
    )

    result = submit_care_decision(
        "http://backend.test",
        "run-001",
        decision,  # type: ignore[arg-type]
        session=session,  # type: ignore[arg-type]
    )

    assert result["run_id"] == "run-001"
    assert session.calls[0][2]["json"] == {
        "run_id": "run-001",
        "decision": decision,
    }


def test_fetch_cctv_image_uses_only_safe_file_name() -> None:
    session = FakeSession(
        FakeResponse(200, {}, content=b"image-bytes")
    )

    result = fetch_cctv_image(
        "http://backend.test",
        "assets/cctv/fall.jpg",
        session=session,  # type: ignore[arg-type]
    )

    assert result == b"image-bytes"
    assert session.calls[0][1] == "http://backend.test/cctv/fall.jpg"


def test_api_error_exposes_backend_detail() -> None:
    session = FakeSession(FakeResponse(422, {"detail": "invalid profile"}))

    with pytest.raises(BackendAPIError, match="invalid profile"):
        request_care_run(
            "http://backend.test",
            "profile-99",
            "normal",
            [],
            session=session,  # type: ignore[arg-type]
        )


def test_connection_error_is_wrapped() -> None:
    session = FakeSession(requests.ConnectionError("connection refused"))

    with pytest.raises(BackendAPIError, match="연결할 수 없습니다"):
        submit_care_decision(
            "http://backend.test",
            "run-001",
            "approve",
            session=session,  # type: ignore[arg-type]
        )


def test_non_object_json_is_rejected() -> None:
    session = FakeSession(FakeResponse(200, ["unexpected"]))

    with pytest.raises(BackendAPIError, match="JSON 객체"):
        request_care_run(
            "http://backend.test",
            "profile-01",
            "normal",
            [],
            session=session,  # type: ignore[arg-type]
        )
