"""AutoHealing 로그 화면 테스트 — 기화"""

from types import SimpleNamespace

import pytest
import requests
from streamlit.testing.v1 import AppTest

from src import approval
from src.components import logs as log_view
from src.components.logs import LogsUnavailable, fetch_run_logs, summarize_logs


def log(id, step, attempt, status, error=None, recovery=None):
    return {"id": id, "run_id": "run-1", "step": step, "attempt": attempt, "status": status,
            "error": error, "recovery": recovery, "elapsed_ms": 10, "created_at": "2026-10-12T00:00:00Z"}


def by_step(summary):
    return {item["step"]: item for item in summary}


def test_vital_fault_recovered_by_cache():
    """시연 6번: 바이탈 장애 → 재시도 3회 → 캐시 사용."""
    s = by_step(summarize_logs([
        log(1, "vital", 1, "retry", "InjectedFault"), log(2, "vital", 2, "retry", "InjectedFault"),
        log(3, "vital", 3, "fail", "InjectedFault"), log(4, "vital", 3, "fallback", recovery="cache"),
    ]))["vital"]
    assert s["label"] == "바이탈 조회"
    assert s["text"] == ("1회차 실패(주입된 장애) → 2회차 실패(주입된 장애) → 3회차 실패(주입된 장애) "
                         "→ 캐시(이전 측정값) 사용")
    assert s["ok"] and s["recovered"]


def test_device_control_failure_shows_final_fail():
    """시연 7번: 기기 제어 3회 실패 → FAIL."""
    s = by_step(summarize_logs([
        log(1, "action:control_device", 1, "retry", "InjectedFault"),
        log(2, "action:control_device", 2, "retry", "InjectedFault"),
        log(3, "action:control_device", 3, "fail", "InjectedFault"),
    ]))["action:control_device"]
    assert s["label"] == "기기 제어" and not s["ok"] and not s["recovered"]
    assert s["text"].endswith("3회차 실패(주입된 장애) → 복구 실패")


def test_llm_template_and_plain_success():
    """시연 9번(LLM 템플릿)과, 아무 문제 없는 단계."""
    s = by_step(summarize_logs([
        log(1, "iot_env", 1, "success"),
        log(2, "llm", 1, "retry", "LLMOutputError"), log(3, "llm", 2, "fallback", recovery="template"),
    ]))
    assert s["iot_env"]["text"] == "성공" and s["iot_env"]["ok"] and not s["iot_env"]["recovered"]
    assert s["llm"]["text"] == "1회차 실패(형식 오류) → 고정 템플릿 문구 사용" and s["llm"]["recovered"]


def test_step_order_follows_first_appearance_and_unknown_step_kept():
    summary = summarize_logs([log(1, "vision", 1, "success"), log(2, "vital", 1, "success"),
                              log(3, "new_step", 1, "success")])
    assert [item["step"] for item in summary] == ["vision", "vital", "new_step"]
    assert summary[2]["label"] == "new_step"


class FakeSession:
    def __init__(self, response=None, error=None):
        self.response, self.error, self.calls = response, error, []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if self.error:
            raise self.error
        return self.response


def response(status, body):
    return SimpleNamespace(ok=200 <= status < 300, status_code=status, json=lambda: body)


def test_fetch_sorts_oldest_first_and_sends_run_id():
    session = FakeSession(response(200, {"logs": [log(2, "vital", 2, "success"), log(1, "vital", 1, "retry")],
                                         "count": 2}))
    logs = fetch_run_logs("http://backend.test/", "run-1", session=session)
    assert [item["id"] for item in logs] == [1, 2]
    url, kwargs = session.calls[0]
    assert url == "http://backend.test/logs" and kwargs["params"]["run_id"] == "run-1"


@pytest.mark.parametrize("session", [
    FakeSession(error=requests.ConnectionError("down")),
    FakeSession(response(500, {})),
    FakeSession(response(200, {"unexpected": True})),
])
def test_fetch_failures_raise_logs_unavailable(session):
    with pytest.raises(LogsUnavailable):
        fetch_run_logs("http://backend.test", "run-1", session=session)


def test_app_shows_log_lines_after_run(monkeypatch):
    monkeypatch.setenv("DEMO_ACCOUNTS", "childB:pw-b:profile-02")
    monkeypatch.setattr(approval, "request_care_run", lambda url, profile, scenario, fault: {
        "run_id": "run-77", "status": "no_issue", "current_step": "완료", "message": "이상 없음"})
    requested = []

    def fake_fetch(backend_url, run_id, **kwargs):
        requested.append(run_id)
        return [log(1, "vital", 1, "fail", "NoRecentReading"), log(2, "vital", 1, "fallback", recovery="mock")]

    monkeypatch.setattr(log_view, "fetch_run_logs", fake_fetch)
    # 표(st.dataframe)를 처음 그릴 때 라이브러리를 불러오느라 기본 3초를 넘길 수 있음
    app = AppTest.from_file("../src/app.py", default_timeout=30).run()
    app.text_input[0].input("childB")
    app.text_input[1].input("pw-b")
    app = next(b for b in app.button if b.label == "로그인").click().run()
    assert any("AutoHealing" in h.value for h in app.subheader)          # 실행 전에도 영역은 보임
    app = next(b for b in app.button if b.label == "상태 확인하기").click().run()

    assert not app.exception
    assert requested and requested[-1] == "run-77"
    assert any("바이탈 조회" in w.value and "mock 값 사용" in w.value for w in app.warning)
