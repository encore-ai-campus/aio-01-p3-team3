"""실제 키로 LLM이 도는지 눈으로 확인하는 스크립트 — 해든

[변경 기록]
2026-10-08 해든: 새 파일. 팀 코드가 아니라 확인용이라 notes/에 둠.

실행 (저장소 맨 위 폴더에서):
    pip install openai          # 처음 한 번
    python notes/llm_live_check.py

하는 일:
  - README 시나리오 5개(normal, heat, induction, fall, critical)를 Emergency → Summary(승인·거절)로 실제 호출
  - 프롬프트, LLM 원문 답, 검증 결과, 재요청 여부, 최종 문장을 화면에 찍고
    notes/llm_live_check_result.md에 같은 내용을 저장 (VS Code에서 미리보기로 보기 좋음)
  - mcp_server/assets/cctv/에 이미지가 있으면 CCTV 분석도 실제 호출

키: backend/config/.env를 먼저 읽고, 없으면 mcp_server/config/.env를 읽음. 키 값은 화면·파일에 찍지 않음.
"""

import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "notes" / "llm_live_check_result.md"


def load_env():
    for path in (ROOT / "backend/config/.env", ROOT / "mcp_server/config/.env"):
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                if v.strip() and not os.getenv(k.strip()):
                    os.environ[k.strip()] = v.strip().strip('"').strip("'")
        print(f"키 파일 읽음: {path.relative_to(ROOT)}")


load_env()
sys.path.insert(0, str(ROOT / "backend"))

from src.agents.emergency import run_emergency      # noqa: E402
from src.agents.summary import run_summary          # noqa: E402
from src.llm.client import make_llm, provider       # noqa: E402

SCENARIOS = {   # README 6장 mock_data.py와 같은 값 + CCTV 분석 결과 예시
    "normal": {"vitals": {"hr": 72, "sbp": 125, "temp": 36.5, "spo2": 98}, "env": {"temp": 24},
               "devices": {"aircon": "off", "induction": "off"},
               "cctv": {"person_visible": True, "posture": "sitting", "fall_suspected": False,
                        "description": "거실 소파에 앉아 있는 것으로 보입니다."}},
    "heat": {"vitals": {"hr": 105, "sbp": 140, "temp": 37.8, "spo2": 96}, "env": {"temp": 33},
             "devices": {"aircon": "off", "induction": "off"},
             "cctv": {"person_visible": True, "posture": "sitting", "fall_suspected": False,
                      "description": "거실 소파에 앉아 있는 것으로 보입니다."}},
    "induction": {"vitals": {"hr": 80, "sbp": 130, "temp": 36.6, "spo2": 97}, "env": {"temp": 26},
                  "devices": {"aircon": "off", "induction": "on(2h)"},
                  "cctv": {"person_visible": False, "posture": "none", "fall_suspected": False,
                           "description": "주방에 사람이 보이지 않습니다."}},
    "fall": {"vitals": {"hr": 118, "sbp": 100, "temp": 36.3, "spo2": 93}, "env": {"temp": 25},
             "devices": {"aircon": "off", "induction": "off"},
             "cctv": {"person_visible": True, "posture": "fallen", "fall_suspected": True,
                      "description": "거실 바닥에 사람이 쓰러져 있는 것으로 보입니다."}},
    "critical": {"vitals": {"hr": 140, "sbp": 85, "temp": 36.0, "spo2": 88}, "env": {"temp": 25},
                 "devices": {"aircon": "off", "induction": "off"},
                 "cctv": {"person_visible": True, "posture": "lying", "fall_suspected": False,
                          "description": "침대에 누워 있는 것으로 보입니다."}},
}
HOSPITAL = "○○병원 응급실 (1.2km)"


class Recorder:
    """실제 LLM 호출을 감싸서 프롬프트·원문·걸린 시간을 기록한다."""

    def __init__(self, llm):
        self.llm, self.calls = llm, []

    def __call__(self, prompt):
        start = time.time()
        try:
            raw = self.llm(prompt)
        except Exception as e:
            self.calls.append({"prompt": prompt, "raw": f"(예외) {type(e).__name__}: {e}", "sec": time.time() - start})
            raise
        self.calls.append({"prompt": prompt, "raw": raw, "sec": time.time() - start})
        return raw


lines = []


def say(text=""):
    print(text)
    lines.append(text)


def note(text=""):
    """파일에만 남김 (프롬프트·원문처럼 긴 것)."""
    lines.append(text)


def show_calls(rec, log):
    for i, c in enumerate(rec.calls, 1):
        note(f"<details><summary>호출 {i} 프롬프트 ({c['sec']:.1f}초)</summary>\n\n```text\n{c['prompt']}\n```\n</details>\n")
        note(f"호출 {i} LLM 원문 답:\n\n```json\n{c['raw']}\n```\n")
        print(f"  호출 {i} ({c['sec']:.1f}초) 원문: {c['raw'][:200]}")
    if log:
        say(f"- 시도 {log['attempts']}번, 템플릿 사용: **{'예' if log['fallback_used'] else '아니오'}**")
        for e in log["errors"]:
            say(f"- 검증에서 걸린 것: {e}")


def main():
    use = provider()
    if not use:
        print("키가 없습니다. backend/config/.env 또는 mcp_server/config/.env에 OPENAI_API_KEY를 넣으세요.")
        return 1
    model = os.getenv("OPENAI_MODEL" if use == "openai" else "GEMINI_MODEL", "(기본값)")
    say(f"# 실제 LLM 호출 확인 ({time.strftime('%Y-%m-%d %H:%M')})\n")
    say(f"- 사용: **{use}**, 모델: **{model}**\n")
    summary_rows = []

    for name, data in SCENARIOS.items():
        care = {**data, "vulnerability": "중", "task_id": f"check-{name}"}
        say(f"\n---\n\n## {name}\n")
        em_rec = Recorder(make_llm("emergency"))
        em = run_emergency(care, llm=em_rec, find_hospital=lambda area: HOSPITAL)
        say(f"**위험도: {em['risk_level']}**  (코드 판정)\n")
        if em["risk_level"] == "정상":
            say("이상 없음 → LLM을 부르지 않고 종료 (Handoff Guard)")
            summary_rows.append((name, "정상", "-", "-", "-"))
            continue
        say("### Emergency 조치안")
        show_calls(em_rec, em["llm_log"])
        say(f"\n- 판정 근거(reason): **{em['reason']}**")
        for a in em["actions"]:
            approve = "승인 필요" if a.get("needs_approval") else "승인 없음"
            say(f"- [{approve}] {a['label']} → \"{a['text']}\"")

        executed = [{"action": a["type"], "device": (a.get("value") or {}).get("device"), "result": "success"}
                    for a in em["actions"] if a["type"] != "hospital_info"]
        for approved in (True, False):
            sm_rec = Recorder(make_llm("summary"))
            sm = run_summary(em, approved=approved, executed=executed if approved else [], llm=sm_rec)
            say(f"\n### Summary ({'승인 → 실행 성공' if approved else '거절'})")
            show_calls(sm_rec, sm["llm_log"])
            say(f"\n- 보호자용: **{sm['guardian_message']}**")
            say(f"- 어르신용: **{sm['elder_message'] or '(보내지 않음)'}**")
            if approved:
                done_sm = sm
        summary_rows.append((name, em["risk_level"], "예" if em["fallback_used"] else "아니오",
                             "예" if done_sm["fallback_used"] else "아니오", em["reason"]))

    say("\n---\n\n## 요약\n")
    say("| 시나리오 | 위험도 | Emergency 템플릿 사용 | Summary 템플릿 사용 | 판정 근거 |")
    say("|---|---|---|---|---|")
    for row in summary_rows:
        say("| " + " | ".join(row) + " |")

    cctv_dir = ROOT / "mcp_server/assets/cctv"
    images = sorted(p for p in cctv_dir.glob("*") if p.suffix.lower() in (".jpg", ".jpeg", ".png"))
    say("\n## CCTV 분석\n")
    if not images:
        say(f"`{cctv_dir.relative_to(ROOT)}`에 이미지가 아직 없어 건너뜀.")
    else:
        sys.path.insert(0, str(ROOT / "mcp_server"))
        for mod in [m for m in sys.modules if m == "src" or m.startswith("src.")]:
            del sys.modules[mod]           # backend의 src와 mcp_server의 src 이름이 같아서 다시 불러옴
        sys.path.remove(str(ROOT / "backend"))
        from src.vision.analyzer import analyze_cctv_or_unavailable
        for img in images:
            start = time.time()
            out = analyze_cctv_or_unavailable(str(img))
            say(f"- `{img.name}` ({time.time() - start:.1f}초): "
                f"```{json.dumps({k: v for k, v in out.items() if k != 'image_path'}, ensure_ascii=False)}```")

    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n결과 저장: {OUT.relative_to(ROOT)} (VS Code에서 Ctrl+Shift+V로 미리보기)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
