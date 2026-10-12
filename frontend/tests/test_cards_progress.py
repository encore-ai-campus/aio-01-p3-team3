"""바이탈·실내기기 카드와 한 줄 진행 표시 테스트 — 기화"""

from streamlit.testing.v1 import AppTest

from src import approval
from src.components import logs as log_view
from src.components.cards import induction_text, measured_text, vital_values
from src.components.progress import DEFAULT_STEPS, latest_progress, split_steps

CARE_STATUS = {
    "run_id": "run-1", "profile_id": "profile-03", "scenario": "induction",
    "vital": {"heart_rate": 80, "systolic_bp": 130, "temperature_c": 36.6, "spo2": 97, "measured_at": None},
    "indoor_environment": {"temperature_c": 26.0, "humidity_percent": 55.0},
    "devices": {"air_conditioner": "off", "induction": "on", "induction_minutes": 120, "induction_temperature": 300},
    "cctv": {"image_path": "assets/cctv/kitchen_empty.png", "status": "analyzed"},
    "vulnerability": "하", "area": "서울시 서초구", "source": "mock", "errors": [],
}


# ---------- 진행 표시 ----------

def test_split_steps():
    assert split_steps("바이탈 확인 → IoT·CCTV 확인 → 위험 판정 완료(경고) → 보호자 승인 대기") == [
        "바이탈 확인", "IoT·CCTV 확인", "위험 판정 완료(경고)", "보호자 승인 대기"]
    assert split_steps(None) == [] and split_steps("") == []


def test_approval_result_progress_is_newer_than_run():
    run = {"status": "pending_approval", "current_step": "위험 판정 → 보호자 승인 대기"}
    approved = {"status": "done", "current_step": "보호자 승인 → 에어컨 냉방(mock) 완료 → 안내 전송"}
    assert latest_progress(run, None) == (["위험 판정", "보호자 승인 대기"], "pending_approval")
    assert latest_progress(run, approved)[1] == "done"
    assert latest_progress(None, None) == ([], None)


# ---------- 카드 ----------

def test_vital_values_and_missing():
    assert vital_values(CARE_STATUS["vital"]) == [
        ("심박", "80 bpm"), ("수축기 혈압", "130 mmHg"), ("체온", "36.6 ℃"), ("산소포화도", "97 %")]
    assert [value for _, value in vital_values({"heart_rate": 75})][1:] == ["—", "—", "—"]   # 일부만 들어옴


def test_measured_text_shows_source():
    assert measured_text({}, "cache") == "🟡 이전 측정값 (캐시)"
    assert measured_text({"measured_at": "2026-10-12T10:42:05+09:00"}, "live") == "🟢 실시간 측정값 · 측정 10:42:05"
    assert measured_text({}, None) == ""


def test_induction_text():
    assert induction_text(CARE_STATUS["devices"]) == "켜짐 · 120분 · 300℃"
    assert induction_text({"induction": "off", "induction_minutes": None}) == "꺼짐"


# ---------- 화면 ----------

def run_app(monkeypatch, response):
    monkeypatch.setenv("DEMO_ACCOUNTS", "childC:pw-c:profile-03")
    monkeypatch.setattr(approval, "request_care_run", lambda url, profile, scenario, fault: response)
    monkeypatch.setattr(log_view, "fetch_run_logs", lambda url, run_id, **kw: [])
    app = AppTest.from_file("../src/app.py", default_timeout=30).run()
    app.text_input[0].input("childC")
    app.text_input[1].input("pw-c")
    app = next(b for b in app.button if b.label == "로그인").click().run()
    metrics_before = [m.label for m in app.metric]   # AppTest는 같은 객체를 갱신하므로 값으로 남겨 둔다
    after = next(b for b in app.button if b.label == "상태 확인하기").click().run()
    return metrics_before, after


def test_cards_and_progress_show_this_run_immediately(monkeypatch):
    response = {"run_id": "run-1", "status": "no_issue", "current_step": "바이탈 확인 → IoT·CCTV 확인 → 위험 판정: 이상 없음 → 종료",
                "message": "이상 없음", "care_status": CARE_STATUS}
    metrics_before, after = run_app(monkeypatch, response)

    assert metrics_before == []                           # 실행 전에는 카드 없음
    assert not after.exception
    metrics = {m.label: m.value for m in after.metric}    # 버튼을 누른 바로 그 실행에서 값이 보여야 함
    assert metrics["심박"] == "80 bpm" and metrics["실내 온도"] == "26.0 ℃" and metrics["습도"] == "55 %"
    assert any("인덕션: **켜짐 · 120분 · 300℃**" in m.value for m in after.markdown)
    assert any("위험 판정: 이상 없음" in m.value for m in after.markdown)   # 진행 표시
    assert any(c.value == "이상 없음" for c in after.caption)


def test_missing_vital_shows_sensor_warning(monkeypatch):
    care = dict(CARE_STATUS, vital=None, source="mock", errors=["vital_unavailable"])
    response = {"run_id": "run-2", "status": "fail", "current_step": "바이탈 조회 실패 → 안전 종료",
                "message": "센서 확인", "care_status": care}
    _, after = run_app(monkeypatch, response)
    assert any("바이탈을 불러오지 못했습니다" in w.value for w in after.warning)


def test_default_steps_before_run():
    assert DEFAULT_STEPS[0] == "상태 확인" and DEFAULT_STEPS[-1] == "결과 안내"
