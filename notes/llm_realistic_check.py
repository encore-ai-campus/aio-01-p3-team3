"""현실적인 가짜 상황 20개로 실제 LLM 문장을 어르신·보호자 입장에서 점검하는 스크립트 — 해든

[변경 기록]
2026-10-08 해든: 새 파일. 팀 코드가 아니라 확인용이라 notes/에 둠. llm_live_check.py의 확장판.
2026-10-08 해든 (워치 버튼): 상황 설명의 스피커 응답을 워치 버튼 응답으로 바꿈.
2026-10-08 해든 (시연 시나리오 확정안): 기기 상태를 구조 형식으로, README 시나리오(S10·S11·S13)를 확정안 값으로 바꾸고 S21(확정안 fall) 추가.

실행 (저장소 맨 위 폴더에서):
    python notes/llm_realistic_check.py              # 실제 LLM + 평가 LLM
    python notes/llm_realistic_check.py --no-judge   # 평가 LLM 없이 규칙 점검만

하는 일:
  1. 상황 20개(낙상·심뇌·호흡·환경·겹침·센서 오류)를 rules/risk.py로 판정
  2. 상황마다 흐름(승인 / 거절 / 보호자 무응답 / 기기 실패 / 119 바로 연결)을 따라
     보호자 휴대폰 알림 → Emergency 조치안(LLM) → Summary 결과 안내(LLM)를 만든다
  3. 규칙 점검: 어르신 문장(존댓말, 무서운 말·수치·의료 용어 없음, 할 일 안내), 보호자 문장(다음 할 일, 길이)
  4. 평가 LLM(기본 gpt-4.1)이 "회사에서 알림 받은 보호자"와 "혼자 사는 80세 어르신" 입장에서 1~5점과 한 줄 의견
  5. notes/llm_realistic_check_result.md, .json에 저장 (키 값은 어디에도 찍지 않음)

키: backend/config/.env → mcp_server/config/.env 순서로 읽음.
"""

import json
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT_MD = ROOT / "notes" / "llm_realistic_check_result.md"
OUT_JSON = ROOT / "notes" / "llm_realistic_check_result.json"


def load_env():
    for path in (ROOT / "backend/config/.env", ROOT / "mcp_server/config/.env"):
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                if v.strip() and not os.getenv(k.strip()):
                    os.environ[k.strip()] = v.strip().strip('"').strip("'")


load_env()
sys.path.insert(0, str(ROOT / "backend"))

from src.agents.emergency import run_emergency      # noqa: E402
from src.agents.summary import run_summary          # noqa: E402
from src.llm.client import make_llm, provider       # noqa: E402
from src.llm.fallback import (                      # noqa: E402
    emergency_alert_message, pending_guardian_message, reminder_guardian_message)
from src.rules.risk import GUARDIAN_REMIND_SEC, GUARDIAN_WAIT_119_SEC, evaluate   # noqa: E402

HOSPITAL = "○○병원 응급실 (1.2km)"
NORMAL = {"hr": 72, "sbp": 125, "temp": 36.5, "spo2": 98, "measured_at": "10:42", "source": "live"}


def vitals(**kw):
    return {**NORMAL, **kw}


def cam(posture, fall=False, visible=True, confidence="high", desc=""):
    return {"available": True, "person_visible": visible, "posture": posture, "fall_suspected": fall,
            "confidence": confidence, "description": desc}


def care(cctv, v=None, env_temp=24, devices=None, event=None, signs=None, vul="중"):
    c = {"vitals": v or dict(NORMAL), "env": {"temp": env_temp, "humidity": 50},
         "devices": devices or {"aircon": {"state": "off"}, "induction": {"state": "off", "minutes": 0, "temperature": 0}},
         "cctv": cctv,
         "vulnerability": vul, "area": "서울 마포구"}
    if event:
        c["fall_event"] = event
    if signs:
        c["signs"] = signs
    return c


SOFA = cam("sitting", desc="거실 소파에 앉아 있는 것으로 보입니다.")
UNAVAILABLE = {"available": False, "description": "영상 판단 불가"}

# (번호, 이야기, care_status, 월)
SCENARIOS = [
    ("S01", "오후 3시, 거실 바닥에 쓰러진 모습이 CCTV에 분명히 찍힘. 바이탈은 정상, 아직 워치로 묻지 않음",
     care(cam("fallen", True, desc="거실 바닥에 사람이 누워 있는 것으로 보입니다.")), 8),
    ("S02", "S01 뒤 워치로 '어르신, 괜찮으세요?'를 물었는데 30초 동안 버튼을 누르지 않음",
     care(cam("fallen", True, desc="거실 바닥에 사람이 누워 있는 것으로 보입니다."), event={"watch_response": "none"}), 8),
    ("S03", "화장실 앞 CCTV가 어둡고 흐림. 바닥에 있는 것 같지만 확실하지 않음",
     care(cam("fallen", True, confidence="low", desc="화장실 앞 바닥에 사람이 있는 것으로 보이나 화면이 어둡습니다.")), 8),
    ("S04", "밤 11시, 침대에 누워 있음. 워치 확인에 대답이 없음 (잠들었거나 귀가 어두울 수 있음)",
     care(cam("lying", desc="침대에 누워 있는 것으로 보입니다."), event={"watch_response": "none"}), 8),
    ("S05", "워치가 낙상을 감지했지만 CCTV에는 소파에 앉아 있음",
     care(SOFA, event={"watch_fall": True}), 8),
    ("S06", "워치가 낙상을 감지했는데 CCTV 분석이 3번 실패해 영상 판단 불가",
     care(UNAVAILABLE, event={"watch_fall": True}), 8),
    ("S07", "바닥에 쓰러진 채 워치에서 '도와주세요' 버튼을 누름",
     care(cam("fallen", True, desc="거실 바닥에 사람이 누워 있는 것으로 보입니다."), event={"watch_response": "help"}), 8),
    ("S08", "심박 135회/분, 평소와 다르게 같은 자리를 계속 맴돎 (이상 행동)",
     care(cam("standing", desc="거실에 서 있는 것으로 보입니다."), vitals(hr=135), signs={"abnormal_behavior": True}), 8),
    ("S09", "산소포화도 89%, 숨을 몰아쉬는 정황 (호흡 곤란 신호)",
     care(SOFA, vitals(spo2=89), signs={"breathing_distress": True}), 8),
    ("S10", "확정안 critical: 심박 140, 혈압 85, 산소포화도 88%. 소파에 누워 움직임 없음",
     care(cam("lying", desc="소파에 누워 있는 것으로 보입니다."), vitals(hr=140, sbp=85, temp=36.0, spo2=88)), 8),
    ("S11", "확정안 heat: 8월, 실내 33℃, 에어컨 꺼짐, 심박 105·체온 37.8",
     care(SOFA, vitals(hr=105, sbp=140, temp=37.8, spo2=96), env_temp=33), 8),
    ("S12", "1월 한파, 보일러 고장으로 실내 16℃, 체온 35.8℃",
     care(SOFA, vitals(temp=35.8), env_temp=16), 1),
    ("S13", "확정안 induction: 인덕션 120분째 켜짐·300℃, 주방에 사람 없음",
     care(cam("none", visible=False, desc="주방에 사람이 보이지 않습니다."), env_temp=26,
          devices={"aircon": {"state": "off"}, "induction": {"state": "on", "minutes": 120, "temperature": 300}}), 8),
    ("S14", "인덕션 켜짐(시간 모름), 집 안 CCTV에 사람이 안 보임 (외출했을 수 있음)",
     care(cam("none", visible=False, desc="거실에 사람이 보이지 않습니다."),
          devices={"aircon": {"state": "off"}, "induction": {"state": "on"}}), 8),
    ("S15", "폭염(실내 33℃) 중 거실 바닥에 쓰러진 모습",
     care(cam("fallen", True, desc="거실 바닥에 사람이 누워 있는 것으로 보입니다."),
          vitals(hr=112, temp=38.2), env_temp=33), 8),
    ("S16", "워치 연결이 끊겨 20분 전 측정값(심박 140, 산소포화도 88%)만 있음. 소파에 앉아 있음",
     care(SOFA, vitals(hr=140, spo2=88, sbp=85, source="cache", measured_at="10:22")), 8),
    ("S17", "취약도 상(혼자 사는 85세, 지병 있음) + 흐린 사진 낙상 의심",
     care(cam("fallen", True, confidence="low", desc="거실 바닥에 사람이 있는 것으로 보이나 화면이 흐립니다."), vul="상"), 8),
    ("S18", "산소포화도 92%로 조금 낮음, 다른 건 정상",
     care(SOFA, vitals(spo2=92)), 8),
    ("S19", "체온 39.3℃ 고열, 소파에 앉아 있음",
     care(SOFA, vitals(temp=39.3, hr=100)), 8),
    ("S20", "8월 실내 30℃(고온 기준선), 바이탈 정상, 에어컨 꺼짐",
     care(SOFA, env_temp=30), 8),
    ("S21", "확정안 fall: 거실 바닥에 쓰러진 모습, 심박 118만 위험 범위",
     care(cam("fallen", True, desc="거실 바닥에 사람이 누워 있는 것으로 보입니다."),
          vitals(hr=118, sbp=120, temp=36.4, spo2=95), env_temp=25), 8),
]

# ---------- 규칙 점검 (어르신·보호자 입장) ----------

ELDER_SCARY = ["위급", "위험", "쓰러", "사고", "응급", "심박", "산소", "혈압", "체온", "바이탈", "CCTV", "영상", "카메라", "낙상"]
ELDER_DO = ["움직이지", "기다려", "계세요", "쉬세요", "앉아", "누워", "드세요", "마세요", "안심"]
GUARDIAN_NEXT = ["확인하세요", "전화하세요", "연락하세요", "승인하세요", "확인해 주", "전화", "연락해 주", "직접 조치", "살펴", "승인해 주", "바랍니다", "부탁", "확인 바", "주세요"]


def rule_check(guardian: str, elder: str, flow: str) -> list[str]:
    issues = []
    if not any(w in guardian for w in GUARDIAN_NEXT) and flow != "approve":
        issues.append("보호자: 다음에 할 일이 없음")
    if elder:
        if not re.search(r"(요|세요|니다|까요)[.!?]?$", elder.strip()):
            issues.append("어르신: 존댓말로 끝나지 않음")
        scary = [w for w in ELDER_SCARY if w in elder]
        if scary:
            issues.append(f"어르신: 어려운·무서운 말 {scary}")
        if flow in ("auto", "timeout") or "119" in guardian:
            if not any(w in elder for w in ELDER_DO):
                issues.append("어르신: 119 상황인데 어떻게 하라는 안내가 없음")
    return issues


# ---------- 평가 LLM ----------

JUDGE_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["guardian_score", "guardian_comment", "elder_score", "elder_comment", "risk"],
    "properties": {
        "guardian_score": {"type": "integer"}, "guardian_comment": {"type": "string"},
        "elder_score": {"type": "integer"}, "elder_comment": {"type": "string"},
        "risk": {"type": "string"},
    },
}


def make_judge():
    if provider() != "openai":
        return None
    from openai import OpenAI
    client = OpenAI(timeout=30, max_retries=1)
    model = os.getenv("JUDGE_MODEL", "gpt-4.1")

    def judge(story, flow_text, risk, alerts, guardian, elder):
        prompt = f"""너는 노인 돌봄 서비스 문장을 두 사람 입장에서 평가한다.
(1) 보호자: 멀리 떨어져 사는 50대 자녀. 회사에서 휴대폰 알림으로 읽는다. 무슨 일인지, 얼마나 급한지, 내가 지금 뭘 해야 하는지 바로 알아야 한다.
(2) 어르신: 혼자 사는 80세. 워치나 집 스피커로 안내를 받는다. 쉬운 말, 존댓말, 겁먹지 않게, 지금 어떻게 하면 되는지.

[상황] {story}
[시스템 판정] 위험도 {risk} / 흐름: {flow_text}
[보호자 휴대폰 알림] {" / ".join(alerts) or "없음"}
[보호자 결과 안내] {guardian}
[어르신 안내] {elder or "(보내지 않음)"}

점수는 1~5 (5가 가장 좋음). 의견은 각 40자 이내 한국어 한 문장으로, 고칠 점이 있으면 고칠 점을 쓴다.
risk: 이 문장 때문에 생길 수 있는 가장 큰 문제 한 문장 (없으면 "없음")."""
        r = client.responses.create(model=model, temperature=0.0, input=prompt, text={"format": {
            "type": "json_schema", "name": "judge", "strict": True, "schema": JUDGE_SCHEMA}})
        return json.loads(r.output_text)

    return judge


# ---------- 흐름 ----------

FLOW_TEXT = {"approve": "보호자 승인 → 실행 성공", "reject": "보호자 거절",
             "timeout": f"보호자 {GUARDIAN_WAIT_119_SEC}초 무응답 → 119 자동 연결",
             "device_fail": "보호자 승인 → 기기 제어 실패", "auto": "119 바로 연결 (승인 없이)",
             "info": "승인할 조치 없음 → 알림·워치 확인만"}


def flows_for(em: dict) -> list[str]:
    acts = em["actions"]
    c119 = next((a for a in acts if a["type"] == "call_119"), None)
    if c119 and c119.get("auto"):
        return ["auto"]
    if c119:
        return ["approve", "reject", "timeout"]
    if any(a["type"] == "control_device" for a in acts):
        return ["approve", "reject", "device_fail"]
    return ["info"]


def executed_for(em: dict, flow: str) -> list[dict]:
    out = []
    for a in em["actions"]:
        if a["type"] == "hospital_info":
            continue
        if flow == "reject" and a.get("needs_approval"):
            continue
        if flow == "timeout" and a.get("needs_approval") and a.get("on_timeout") != "execute":
            continue
        result = "fail" if flow == "device_fail" and a["type"] == "control_device" else "success"
        out.append({"action": a["type"], "device": (a.get("value") or {}).get("device"), "result": result})
    return out


def alerts_for(em: dict, flow: str) -> list[str]:
    """보호자 휴대폰에 차례로 오는 알림 (코드 템플릿, LLM 안 기다림)."""
    acts, reason = em["actions"], em["reason"]
    c119 = next((a for a in acts if a["type"] == "call_119"), None)
    if flow == "auto":
        return [emergency_alert_message(reason, c119["auto_reason"], em.get("hospital"))]
    if flow == "info":
        return [f"어르신 상태 확인이 필요합니다. 위험도 {em['risk_level']}. 판정 근거: {reason}."]
    alerts = [pending_guardian_message(em["risk_level"], reason, acts)]
    if flow == "timeout":
        alerts.append(reminder_guardian_message(em["risk_level"], GUARDIAN_WAIT_119_SEC - GUARDIAN_REMIND_SEC))
    return alerts


# ---------- 실행 ----------

def main():
    no_judge = "--no-judge" in sys.argv
    use = provider()
    em_llm = make_llm("emergency") if use else None
    sm_llm = make_llm("summary") if use else None
    judge = None if (no_judge or not use) else make_judge()
    started = time.time()
    rows = []

    for no, story, cs, month in SCENARIOS:
        decision = evaluate(cs, month)
        row = {"no": no, "story": story, "risk_level": decision["risk_level"], "axes": decision["axes"],
               "fall_state": decision["fall_state"], "auto_119": decision["auto_119"], "flows": []}
        print(f"{no} {decision['risk_level']} {story[:30]}")
        if decision["risk_level"] == "정상":
            row["note"] = "이상 없음 → 알림·LLM 없이 종료" + (" (낙상 오탐 기록)" if decision["fall_state"] == "false_alarm" else "")
            rows.append(row)
            continue
        t = time.time()
        em = run_emergency(cs, llm=em_llm, find_hospital=lambda area: HOSPITAL, month=month)
        row.update(reason=em["reason"], code_reason=em["context"]["code_reason"], em_fallback=em["fallback_used"],
                   em_sec=round(time.time() - t, 1), em_errors=(em["llm_log"] or {}).get("errors", []),
                   actions=[{"label": a["label"], "text": a["text"], "approval": "자동" if a.get("auto") else
                             ("필요" if a.get("needs_approval") else "없음")} for a in em["actions"]])
        for flow in flows_for(em):
            t = time.time()
            decided_by = {"auto": "auto", "timeout": "timeout"}.get(flow, "guardian")
            approved = flow in ("approve", "device_fail", "info")
            sm = run_summary(em, approved=approved, executed=executed_for(em, flow), llm=sm_llm, decided_by=decided_by)
            f = {"flow": flow, "flow_text": FLOW_TEXT[flow], "alerts": alerts_for(em, flow),
                 "guardian": sm["guardian_message"], "elder": sm["elder_message"],
                 "fallback": sm["fallback_used"], "sec": round(time.time() - t, 1),
                 "llm_errors": (sm["llm_log"] or {}).get("errors", [])}
            f["rule_issues"] = rule_check(f["guardian"], f["elder"], flow)
            if judge:
                try:
                    f["judge"] = judge(story, f["flow_text"], em["risk_level"], f["alerts"], f["guardian"], f["elder"])
                except Exception as e:
                    f["judge"] = {"error": f"{type(e).__name__}: {e}"}
            row["flows"].append(f)
            print(f"   {flow}: {f['guardian'][:50]} / {f['elder']}")
        rows.append(row)

    meta = {"time": time.strftime("%Y-%m-%d %H:%M"), "provider": use or "(키 없음, 템플릿)",
            "model": os.getenv("OPENAI_MODEL", "gpt-4.1-mini") if use == "openai" else os.getenv("GEMINI_MODEL", "-"),
            "judge_model": os.getenv("JUDGE_MODEL", "gpt-4.1") if judge else None,
            "seconds": round(time.time() - started)}
    OUT_JSON.write_text(json.dumps({"meta": meta, "rows": rows}, ensure_ascii=False, indent=1), encoding="utf-8")
    OUT_MD.write_text(to_md(meta, rows), encoding="utf-8")
    print(f"\n결과 저장: {OUT_MD.relative_to(ROOT)}, {OUT_JSON.relative_to(ROOT)}")
    return 0


def to_md(meta, rows):
    L = [f"# 현실 상황 LLM 점검 ({meta['time']})", "",
         f"- 문장: {meta['provider']} {meta['model']} / 평가: {meta['judge_model'] or '없음'} / {meta['seconds']}초", ""]
    for r in rows:
        L += ["---", f"## {r['no']} {r['story']}", "",
              f"**위험도 {r['risk_level']}** · 낙상 {r['fall_state']} · 119 바로 연결: {r['auto_119'] or '아니오'}", ""]
        if "note" in r:
            L += [r["note"], ""]
            continue
        L += [f"- 판정 근거: {r['reason']}" + (" (템플릿)" if r["em_fallback"] else ""), ""]
        L += ["| 조치 | 승인 | 설명 |", "|---|---|---|"] + [f"| {a['label']} | {a['approval']} | {a['text']} |" for a in r["actions"]]
        for f in r["flows"]:
            L += ["", f"### {f['flow_text']}", ""]
            L += [f"- 📱 알림 {i}: {a}" for i, a in enumerate(f["alerts"], 1)]
            L += [f"- 👤 보호자: **{f['guardian']}**", f"- 👵 어르신: **{f['elder'] or '(보내지 않음)'}**"]
            if f["fallback"]:
                L.append(f"- ⚠️ 템플릿 사용 (LLM 검증 실패: {'; '.join(f['llm_errors'])})")
            for i in f["rule_issues"]:
                L.append(f"- ⚠️ 규칙 점검: {i}")
            j = f.get("judge")
            if j and "error" not in j:
                L.append(f"- 평가 보호자 {j['guardian_score']}/5: {j['guardian_comment']}")
                L.append(f"- 평가 어르신 {j['elder_score']}/5: {j['elder_comment']}")
                L.append(f"- 위험: {j['risk']}")
        L.append("")
    return "\n".join(L)


if __name__ == "__main__":
    sys.exit(main())
