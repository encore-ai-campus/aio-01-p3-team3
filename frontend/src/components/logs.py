"""AutoHealing 실행 과정 로그 화면 — 기화 (README 10장)

GET /logs?run_id=...(지혜 님 API)로 이번 실행의 로그를 받아 단계마다 한 줄로 보여 준다.
  예) 바이탈 조회: 1회차 실패(주입된 장애) → 2회차 실패 → 3회차 실패 → 캐시 사용 ✅
시연 6~9번(장애 주입)에서 재시도·대체·실패 과정이 보이게 하는 화면이다.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from urllib.parse import urljoin

import requests
import streamlit as st

DEFAULT_TIMEOUT_SECONDS = 10.0

STEP_LABELS = {
    "vital": "바이탈 조회",
    "iot_env": "실내 온습도 조회",
    "iot_devices": "기기 상태 조회",
    "vision": "CCTV 분석",
    "llm": "조치안 문장(LLM)",
    "approval": "승인",
    "summary": "안내문 작성(LLM)",
    "action:control_device": "기기 제어",
    "action:call_119": "119 호출",
    "action:notify_guardian": "보호자 알림",
    "action:find_hospital": "병원 조회",
}
RECOVERY_LABELS = {
    "cache": "캐시(이전 측정값) 사용",
    "mock": "mock 값 사용",
    "template": "고정 템플릿 문구 사용",
    "retry": "재시도로 성공",
    "auto_119": "바이탈 매우 위험 → 119 자동 연결",
}
ERROR_LABELS = {
    "InjectedFault": "주입된 장애",
    "NoRecentReading": "최근 측정값 없음",
    "LLMOutputError": "형식 오류",
    "TimeoutError": "시간 초과",
    "McpConnectionError": "MCP 연결 실패",
    "InvalidResult": "잘못된 응답",
}
OK_STATUSES = {"success", "fallback"}


class LogsUnavailable(RuntimeError):
    """로그를 가져오지 못함. 로그 화면만 비우고 나머지 화면은 그대로 둔다."""


def fetch_run_logs(backend_url: str, run_id: str, *, timeout: float = DEFAULT_TIMEOUT_SECONDS,
                   session=None) -> list[dict]:
    """GET /logs?run_id= → 오래된 순서의 로그 목록 (API는 최신 순으로 준다)."""
    requester = session or requests
    url = urljoin(backend_url.rstrip("/") + "/", "logs")
    try:
        response = requester.get(url, params={"run_id": run_id, "limit": 500}, timeout=timeout)
    except requests.RequestException as error:
        raise LogsUnavailable(f"로그 API에 연결할 수 없습니다: {error}") from error
    if not response.ok:
        raise LogsUnavailable(f"로그 조회 실패: HTTP {response.status_code}")
    try:
        logs = response.json()["logs"]
    except (ValueError, KeyError, TypeError) as error:
        raise LogsUnavailable("로그 응답 형식이 올바르지 않습니다.") from error
    return sorted(logs, key=lambda log: log.get("id", 0))


def _event_text(log: Mapping[str, object]) -> str:
    status, attempt = log.get("status"), log.get("attempt")
    error = ERROR_LABELS.get(str(log.get("error")), log.get("error"))
    if status == "success":
        return f"{attempt}회차 성공" if attempt and attempt != 1 else "성공"
    if status == "fallback":
        return RECOVERY_LABELS.get(str(log.get("recovery")), f"대체 경로({log.get('recovery')})")
    if status in ("retry", "fail"):
        return f"{attempt}회차 실패" + (f"({error})" if error else "")
    return "오류" + (f"({error})" if error else "")


def summarize_logs(logs: Sequence[Mapping[str, object]]) -> list[dict]:
    """단계별 한 줄 요약. 단계는 처음 나온 순서를 지킨다.
    → [{"step", "label", "text", "ok", "recovered"}] (ok: 마지막 기록이 성공·대체인지)"""
    grouped: dict[str, list[Mapping[str, object]]] = {}
    for log in logs:
        grouped.setdefault(str(log.get("step")), []).append(log)

    summary = []
    for step, events in grouped.items():
        last = events[-1]
        ok = last.get("status") in OK_STATUSES
        recovered = ok and (len(events) > 1 or last.get("status") == "fallback")
        text = " → ".join(_event_text(event) for event in events)
        if not ok:
            text += " → 복구 실패"
        summary.append({"step": step, "label": STEP_LABELS.get(step, step), "text": text,
                        "ok": ok, "recovered": recovered})
    return summary


def render_autohealing_logs(backend_url: str, run_id: str | None) -> None:
    st.subheader("🔧 실행 과정 (AutoHealing 로그)")
    if not run_id:
        st.caption("상태 확인을 실행하면 이번 실행의 재시도·복구 과정이 여기에 표시됩니다.")
        return
    try:
        logs = fetch_run_logs(backend_url, run_id)
    except LogsUnavailable as error:
        st.caption(f"로그를 불러오지 못했습니다: {error}")
        return
    if not logs:
        st.caption("기록된 로그가 없습니다.")
        return

    summary = summarize_logs(logs)
    recovered = sum(item["recovered"] for item in summary)
    failed = sum(not item["ok"] for item in summary)
    st.caption(f"실행 ID {run_id} · 단계 {len(summary)}개 · 자동 복구 {recovered}건 · 복구 실패 {failed}건")
    for item in summary:
        icon = "✅" if item["ok"] else "❌"
        line = f"{icon} **{item['label']}**: {item['text']}"
        if not item["ok"]:
            st.error(line)
        elif item["recovered"]:
            st.warning(line)
        else:
            st.markdown(line)

    with st.expander("로그 원본 보기"):
        st.dataframe(
            [{"단계": STEP_LABELS.get(str(log.get("step")), log.get("step")), "시도": log.get("attempt"),
              "상태": log.get("status"), "오류": log.get("error"), "복구": log.get("recovery"),
              "소요(ms)": log.get("elapsed_ms")} for log in logs],
            use_container_width=True, hide_index=True,
        )
