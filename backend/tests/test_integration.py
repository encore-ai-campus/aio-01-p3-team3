"""5단계 연결 확인: README 도구 형식(가짜 MCP)으로 /care/run → /care/approve가 끝까지 도는지 — 해든"""

# [변경 기록]
# 2026-10-08 해든: 새 파일. 계획서 7장 5단계. 지혜·두나 님 코드가 아직 없어서, README 6장 응답 형식과
#   README MCP 도구 이름·인자(get_vitals, get_indoor_env, get_device_status, capture_cctv, analyze_cctv,
#   control_device, find_hospital, notify_guardian, call_119)를 그대로 흉내 낸 가짜로 해든 함수를 연결해 봄.
#   care_run / care_approve는 지혜 님 오케스트레이터가 할 일을 보여 주는 "연결 예시"일 뿐, 실제 코드가 아님.
# 2026-10-08 해든 (워치 버튼): 스피커 확인 이름을 워치 버튼 확인(watch_check, watch_response)으로 바꿈.
# 2026-10-08 해든 (CCTV 캡처): fall 승인 알림에 캡처 경로·"CCTV 캡처를 보고 판단하세요", CCTV 판단 불가면 원본 확인 요청 테스트.
# 2026-10-08 해든 (시연 시나리오 확정안): MOCK을 확정안 4장 값(기기 구조 형식, fall 바이탈)으로, 프로필을 확정안 3장
#   profile-01~03과 5장 조합으로 바꿈. critical은 119 바로 연결이 아니라 승인 요청 (확정안 7장 5번 장면).
# 2026-10-12 해든: README대로 critical(VITAL_SEVERE) 119 자동 연결, 에어컨 조치 값에 action 추가에 맞춰 기대값을 바꿈.
#
# [팀 합의] 지혜 님: 아래 care_run / care_approve 순서대로 해든 함수를 부르면 됩니다. 응답 키는 README 6장 응답 1·2와 같음.
# [팀 합의] 두나 님: FakeTools의 함수 이름·인자·반환 형식이 실제 MCP 도구와 같아야 합니다. 다르면 알려 주세요.
# 2026-10-08 해든 (main 문서 개정판): 기대값을 docs/scenarios.md로. critical 119는 해든 결정으로 승인 요청 유지, 자동 연결 알림에도 캡처 안내.
# 2026-10-12 해든 (README 9장 최종 맞춤): CCTV 약한 의심 = 경고(CCTV_SUSPECT_IS_CRITICAL False), 119 시간 초과 자동 연결 끔(ENABLE_TIMEOUT_119 False). 예전 동작은 monkeypatch로 확인.

import pytest

from src.agents.emergency import run_emergency
from src.agents.profile import run_profile
from src.agents.summary import run_summary
from src.llm.fallback import emergency_alert_message, pending_guardian_message
import src.rules.risk as risk
from src.rules.risk import after_guardian_timeout, device_call_args

# 시연 시나리오 확정안 4장 mock_data.py 그대로 (cctv는 이미지 경로)
OFF = {"aircon": {"state": "off"}, "induction": {"state": "off", "minutes": 0, "temperature": 0}}
MOCK = {
    "normal":   {"vitals": {"hr": 72, "sbp": 125, "temp": 36.5, "spo2": 98},
                 "env": {"temp": 24, "humidity": 50}, "devices": OFF,
                 "cctv": "assets/cctv/normal.jpg"},
    "heat":     {"vitals": {"hr": 105, "sbp": 140, "temp": 37.8, "spo2": 96},
                 "env": {"temp": 33, "humidity": 75}, "devices": OFF,
                 "cctv": "assets/cctv/normal.jpg"},
    "induction": {"vitals": {"hr": 80, "sbp": 130, "temp": 36.6, "spo2": 97},
                  "env": {"temp": 26, "humidity": 55}, "devices": {"aircon": {"state": "off"},
                                                                "induction": {"state": "on", "minutes": 120, "temperature": 300}},
                  "cctv": "assets/cctv/kitchen_empty.jpg"},
    "fall":     {"vitals": {"hr": 118, "sbp": 120, "temp": 36.4, "spo2": 95},
                 "env": {"temp": 25, "humidity": 50}, "devices": OFF,
                 "cctv": "assets/cctv/fall.jpg"},
    "critical": {"vitals": {"hr": 140, "sbp": 85, "temp": 36.0, "spo2": 88},
                 "env": {"temp": 25, "humidity": 50}, "devices": OFF,
                 "cctv": "assets/cctv/lying.jpg"},
}
# 이미지가 아직 없어서 analyze_cctv 결과(비전 LLM 출력 형식)를 미리 정해 둠
CCTV_RESULT = {
    "assets/cctv/normal.jpg": ("sitting", False, True, "거실 소파에 앉아 있는 것으로 보입니다."),
    "assets/cctv/kitchen_empty.jpg": ("none", False, False, "주방에 사람이 보이지 않습니다."),
    "assets/cctv/fall.jpg": ("fallen", True, True, "거실 바닥에 사람이 누워 있는 것으로 보입니다."),
    "assets/cctv/lying.jpg": ("lying", False, True, "소파에 누워 있는 것으로 보입니다."),
}
# 확정안 3장 프로필과 5장 시나리오별 조합
PROFILES = {
    "profile-01": {"age": 84, "lives_alone": True, "has_condition": True, "mobility_limited": True},     # 상
    "profile-02": {"age": 78, "lives_alone": True, "has_condition": False, "mobility_limited": False},   # 중
    "profile-03": {"age": 70, "lives_alone": True, "has_condition": False, "mobility_limited": False},   # 하
}
DEMO_PERSON = {"normal": "profile-01", "heat": "profile-02", "induction": "profile-03",
               "fall": "profile-01", "critical": "profile-01"}


class FakeTools:
    """README MCP 도구 9개의 가짜. 호출 기록을 남긴다."""

    def __init__(self, scenario, fail=(), person=None):
        self.data, self.fail, self.log = MOCK[scenario], set(fail), []
        self.profile = PROFILES[person or DEMO_PERSON[scenario]]

    def get_vitals(self, person_id):
        return {**self.data["vitals"], "measured_at": "10:42", "source": "live"}

    def get_indoor_env(self, home_id):
        return self.data["env"]

    def get_device_status(self, home_id):
        return self.data["devices"]

    def capture_cctv(self, home_id):
        return self.data["cctv"]

    def analyze_cctv(self, image_path):     # 실제로는 mcp_server vision.analyzer.analyze_cctv_or_unavailable
        posture, fall, visible, desc = CCTV_RESULT[image_path]
        return {"image_path": image_path, "available": True, "person_visible": visible, "posture": posture,
                "fall_suspected": fall, "confidence": "high", "description": desc}

    def control_device(self, device, action, **options):
        self.log.append(("control_device", device, action, options))
        return {"result": "fail" if "control_device" in self.fail else "success"}

    def find_hospital(self, area):
        return [{"name": "○○병원 응급실", "distance_km": 1.2}]

    def notify_guardian(self, msg):
        self.log.append(("notify_guardian", msg))
        return {"result": "success"}

    def call_119(self, msg):
        self.log.append(("call_119", msg))
        return {"result": "fail" if "call_119" in self.fail else "success"}


# ---------- 지혜 님 오케스트레이터가 할 일 (연결 예시) ----------

PENDING = {}     # 실제로는 orchestrator/approval.py (task_id로 저장)


def execute(tools, action, emergency):
    kind = action["type"]
    if kind == "call_119":
        r = tools.call_119(emergency["reason"])
    elif kind == "control_device":
        device, act, options = device_call_args(action)
        r = tools.control_device(device, act, **options)
    elif kind == "watch_check":
        r = {"result": "success"}          # 워치 확인 mock 도구가 생기면 교체
    else:
        return None                        # hospital_info, notify_guardian은 실행 결과에 넣지 않음
    return {"action": kind, "device": (action.get("value") or {}).get("device"), "result": r["result"]}


def care_run(tools, task_id, month=8):
    """POST /care/run: 모니터링 → 판정 → (119 바로 연결) → 승인 대기 또는 결과."""
    care_status = {
        "task_id": task_id, "attempt": 1, "area": "서울 마포구",
        "vitals": tools.get_vitals("p1"),
        "env": tools.get_indoor_env("h1"),
        "devices": tools.get_device_status("h1"),
        "cctv": tools.analyze_cctv(tools.capture_cctv("h1")),
        **run_profile(tools.profile),
    }
    em = run_emergency(care_status, llm=None, find_hospital=tools.find_hospital, month=month)
    if em["risk_level"] == "정상":
        return {"task_id": task_id, "status": "no_issue", "risk_level": "정상"}

    auto = next((a for a in em["actions"] if a.get("auto")), None)
    if auto:                                # 정말 위급: 승인 없이 바로 119 → 긴급 알림 → 결과
        executed = [x for x in (execute(tools, a, em) for a in em["actions"] if not a.get("needs_approval")) if x]
        tools.notify_guardian(emergency_alert_message(em["reason"], auto["auto_reason"], em["hospital"], em["actions"]))
        sm = run_summary(em, approved=False, executed=executed, decided_by="auto")
        return {"task_id": task_id, "status": "done", "approved": None, "risk_level": em["risk_level"],
                "executed": executed, **{k: sm[k] for k in ("guardian_message", "elder_message")}}

    pre = [x for x in (execute(tools, a, em) for a in em["actions"] if not a.get("needs_approval")) if x]
    tools.notify_guardian(pending_guardian_message(em["risk_level"], em["reason"], em["actions"]))
    PENDING[task_id] = {"emergency": em, "executed": pre, "tools": tools}
    return {"task_id": task_id, "status": "pending_approval", "risk_level": em["risk_level"], "reason": em["reason"],
            "actions": [a["label"] for a in em["actions"]], "cctv": care_status["cctv"]}


def care_approve(task_id, approved: bool | None):
    """POST /care/approve. approved=None은 승인 대기 시간이 지난 경우 (지혜 님 타이머)."""
    p = PENDING.pop(task_id)
    em, tools, executed = p["emergency"], p["tools"], list(p["executed"])
    if approved is None:
        todo, decided_by = after_guardian_timeout(em["actions"])["execute"], "timeout"
    else:
        todo, decided_by = ([a for a in em["actions"] if a.get("needs_approval")] if approved else []), "guardian"
    executed += [x for x in (execute(tools, a, em) for a in todo) if x]
    sm = run_summary(em, approved=bool(approved), executed=executed, decided_by=decided_by)
    if approved is None and not todo:
        status = "pending_approval"        # 기기만 기다리는 중이면 다시 알림만 하고 계속 대기
    else:
        status = "done" if approved or todo else "rejected"
    tools.notify_guardian(sm["guardian_message"])
    return {"task_id": task_id, "status": status, "approved": approved, "risk_level": em["risk_level"],
            "executed": executed, **{k: sm[k] for k in ("guardian_message", "elder_message")}}


# ---------- 테스트 ----------

@pytest.mark.parametrize("scenario, status, level", [
    ("normal", "no_issue", "정상"),
    ("heat", "pending_approval", "경고"),        # profile-02 (중)
    ("induction", "pending_approval", "주의"),   # profile-03 (하)
    ("fall", "pending_approval", "위급"),
    ("critical", "done", "위급"),               # README: 바이탈 매우 위험 → 119 자동 연결
])
def test_care_run_readme_scenarios(scenario, status, level):
    r = care_run(FakeTools(scenario), f"t-{scenario}")
    assert (r["status"], r["risk_level"]) == (status, level)


def test_heat_approve_runs_aircon_with_readme_args():
    tools = FakeTools("heat")
    care_run(tools, "t1")
    r = care_approve("t1", True)
    assert r["status"] == "done" and r["elder_message"].startswith("어르신")
    assert ("control_device", "aircon", "cool", {"mode": "cool", "target": 26}) in tools.log


def test_induction_reject_tells_elder_and_guardian():
    tools = FakeTools("induction")
    care_run(tools, "t2")
    r = care_approve("t2", False)
    assert r["status"] == "rejected" and "거절" in r["guardian_message"] and r["elder_message"]
    assert not any(x[0] == "control_device" for x in tools.log)


def test_fall_timeout_only_reminds_by_default():
    """README 9장: 낙상 119는 보호자 승인. 시간이 지나도 119를 걸지 않고 계속 대기 (해든 10/12)."""
    tools = FakeTools("fall")
    care_run(tools, "t3b")
    r = care_approve("t3b", None)
    assert r["status"] == "pending_approval" and not any(x[0] == "call_119" for x in tools.log)


def test_fall_timeout_calls_119(monkeypatch):
    monkeypatch.setattr(risk, "ENABLE_TIMEOUT_119", True)        # 꺼 둔 확장 설계
    tools = FakeTools("fall")
    care_run(tools, "t3")
    r = care_approve("t3", None)
    assert r["status"] == "done" and any(x[0] == "call_119" for x in tools.log)
    assert r["guardian_message"].startswith("보호자 응답이 없어 119")


def test_critical_auto_119_alerts_before_summary(monkeypatch):
    monkeypatch.setattr(risk, "ENABLE_AUTO_119", True)        # 시연에서는 꺼 둔 확장 설계 (문서 2-4장)
    monkeypatch.setattr(risk, "ENABLE_AUTO_119_VITAL", True)
    tools = FakeTools("critical")
    r = care_run(tools, "t4")
    kinds = [x[0] for x in tools.log]
    assert kinds[:2] == ["call_119", "notify_guardian"] and tools.log[1][1].startswith("[긴급]")
    assert "119" in r["guardian_message"]


def test_119_failure_asks_guardian_to_act():
    tools = FakeTools("fall", fail={"call_119"})        # 승인 뒤 119 (critical은 자동 연결)
    care_run(tools, "t5")
    r = care_approve("t5", True)
    assert "실패" in r["guardian_message"] and "직접 조치" in r["guardian_message"]


def test_device_failure_tells_elder_what_to_do():
    tools = FakeTools("induction", fail={"control_device"})
    care_run(tools, "t6")
    r = care_approve("t6", True)
    assert "꺼 주세요" in r["elder_message"]


def test_fall_approval_alert_has_cctv_capture():
    """확정안 7장 4번: CCTV 캡처 → 위급 → 캡처와 함께 승인 요청."""
    tools = FakeTools("fall")
    r = care_run(tools, "t7")
    em = PENDING["t7"]["emergency"]
    note = next(a for a in em["actions"] if a["type"] == "notify_guardian")["value"]
    assert note["cctv_image"] == "assets/cctv/fall.jpg" and note["cctv_check"] == "fall"
    assert "CCTV 캡처를 보고 판단하세요" in tools.log[-1][1]
    assert r["cctv"]["image_path"] == "assets/cctv/fall.jpg"
    PENDING.pop("t7")


def test_vision_failure_asks_to_check_original_capture():
    """docs/scenarios.md 7장 8번: 영상 판단 불가 → 바이탈만으로 위급 + 원본 캡처 확인 요청 (fall은 119 승인 요청)."""
    tools = FakeTools("fall")
    tools.analyze_cctv = lambda path: {"image_path": path, "available": False, "description": "영상 판단 불가"}
    r = care_run(tools, "t8")
    assert r["status"] == "pending_approval"
    assert "원본 캡처를 직접 확인하세요" in tools.log[-1][1]
    PENDING.pop("t8")


def test_vision_failure_capture_note_in_auto_119_alert(monkeypatch):
    """119 자동 연결을 켜도 긴급 알림에 원본 캡처 확인 안내가 붙음."""
    monkeypatch.setattr(risk, "ENABLE_AUTO_119", True)
    monkeypatch.setattr(risk, "ENABLE_AUTO_119_VITAL", True)
    tools = FakeTools("critical")
    tools.analyze_cctv = lambda path: {"image_path": path, "available": False, "description": "영상 판단 불가"}
    r = care_run(tools, "t9")
    assert r["status"] == "done"
    alert = next(msg for kind, msg in tools.log if kind == "notify_guardian")
    assert alert.startswith("[긴급]") and "원본 캡처를 직접 확인하세요" in alert
