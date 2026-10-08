"""가짜 CCTV 이미지로 비전 LLM을 실제 호출해 정답과 비교하는 스크립트 — 해든

[변경 기록]
2026-10-08 해든: 새 파일. 4단계(CCTV 분석 실제 호출)를 기화 님 이미지 없이 먼저 확인하려고 만듦.
2026-10-08 해든 (시연 대비): --repeat N으로 이미지마다 N번 불러 답이 흔들리는지 봄 (시연 전 3~5번 권장).
  위험도 판정은 시연 시나리오 확정안 조합(바이탈은 그 이미지를 쓰는 시나리오 값, 프로필 profile-03 하)으로 바꿈.

실행 (저장소 맨 위 폴더에서):
    pip install "openai>=1.66" pillow
    python notes/make_fake_cctv.py     # 이미지가 없을 때 한 번
    python notes/cctv_check.py
    python notes/cctv_check.py --repeat 3     # 같은 이미지를 3번씩 (답이 흔들리는지)

하는 일:
  1. mcp_server/assets/cctv/의 이미지마다 analyze_cctv_or_unavailable() 실제 호출 (재시도 2회, 실패면 "영상 판단 불가")
  2. 결과를 make_fake_cctv.EXPECTED(정답)와 비교 → 자세·사람 보임·낙상 의심이 맞는지
  3. 그 CCTV 결과를 바이탈 정상 + 취약도 중으로 backend rules/risk.py에 넣어 낙상 상태와 위험도까지 보여 줌
  4. notes/cctv_check_result.md에 저장 (VS Code에서 Ctrl+Shift+V)
키: backend/config/.env → mcp_server/config/.env 순서로 읽음. 키 값은 찍지 않음.
"""

import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "notes" / "cctv_check_result.md"
IMAGES = ROOT / "mcp_server" / "assets" / "cctv"
sys.path.insert(0, str(ROOT / "notes"))

from make_fake_cctv import EXPECTED    # noqa: E402


def load_env():
    for path in (ROOT / "backend/config/.env", ROOT / "mcp_server/config/.env"):
        if path.is_file():
            for line in path.read_text(encoding="utf-8").splitlines():
                if "=" in line and not line.lstrip().startswith("#"):
                    k, v = line.split("=", 1)
                    if v.strip() and not os.getenv(k.strip()):
                        os.environ[k.strip()] = v.strip().strip('"').strip("'")


def use_package(name):
    """backend와 mcp_server 둘 다 패키지 이름이 src라서, 쓸 쪽으로 바꿔 끼운다."""
    for mod in [m for m in sys.modules if m == "src" or m.startswith("src.")]:
        del sys.modules[mod]
    for other in ("backend", "mcp_server"):
        p = str(ROOT / other)
        if p in sys.path:
            sys.path.remove(p)
    sys.path.insert(0, str(ROOT / name))


def main():
    load_env()
    images = [p for p in sorted(IMAGES.glob("*.jpg")) if p.name in EXPECTED]
    if not images:
        print("이미지가 없습니다. 먼저 python notes/make_fake_cctv.py 를 실행하세요.")
        return 1

    repeat = int(sys.argv[sys.argv.index("--repeat") + 1]) if "--repeat" in sys.argv else 1
    use_package("mcp_server")
    from src.vision.analyzer import analyze_cctv_or_unavailable
    results, runs = [], {}
    for img in images:
        for i in range(repeat):
            start = time.time()
            out = analyze_cctv_or_unavailable(str(img))
            runs.setdefault(img.name, []).append(out)
            print(f"{img.name} #{i + 1}: {out.get('posture')} / {out.get('description')} ({time.time() - start:.1f}초)")
        results.append((img.name, runs[img.name][0], time.time() - start))

    use_package("backend")
    from src.rules.risk import evaluate
    normal_vitals = {"hr": 72, "sbp": 125, "temp": 36.5, "spo2": 98, "source": "live"}
    # 시연 시나리오 확정안에서 이 이미지를 쓰는 시나리오의 바이탈 (그 밖의 이미지는 정상 바이탈)
    scene_vitals = {"fall.jpg": {"hr": 118, "sbp": 120, "temp": 36.4, "spo2": 95},
                    "lying.jpg": {"hr": 140, "sbp": 85, "temp": 36.0, "spo2": 88}}
    off = {"aircon": {"state": "off"}, "induction": {"state": "off", "minutes": 0, "temperature": 0}}
    kitchen = {"aircon": {"state": "off"}, "induction": {"state": "on", "minutes": 120, "temperature": 300}}

    def matches(out, posture, visible, fall):
        return bool(out.get("available")) and out["posture"] == posture and out["person_visible"] == visible and \
            (fall is None or out["fall_suspected"] == fall)

    rows, ok_count = [], 0
    for name, out, sec in results:
        desc, posture, visible, fall, note = EXPECTED[name]
        stable = sum(matches(o, posture, visible, fall) for o in runs[name])
        ok = stable == len(runs[name])
        ok_count += ok
        r = evaluate({"vitals": {**scene_vitals.get(name, normal_vitals), "source": "live"}, "env": {"temp": 24},
                      "devices": kitchen if name == "kitchen_empty.jpg" else off,
                      "cctv": out, "vulnerability": "하"}, month=8)
        rows.append((name, desc, posture, out, ok, sec, note + (f" (반복 {stable}/{len(runs[name])} 일치)" if repeat > 1 else ""), r))

    lines = [f"# CCTV 비전 LLM 점검 ({time.strftime('%Y-%m-%d %H:%M')})", "",
             f"- 모델: {os.getenv('OPENAI_MODEL', 'gpt-4.1-mini')} · 이미지: 가짜(notes/make_fake_cctv.py)",
             f"- 정답과 일치: **{ok_count}/{len(rows)}**" + (f" (이미지마다 {repeat}번 모두 맞아야 일치)" if repeat > 1 else ""),
             "- 위험도 열: 확정안에서 그 이미지를 쓰는 시나리오의 바이탈 + 프로필 하(보정 없음)", "",
             "| 이미지 | 장면 | 기대 자세 | LLM 자세 | 사람 | 낙상 의심 | 확신 | LLM 설명 | 일치 | 낙상 상태 → 위험도 |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    for name, desc, posture, out, ok, sec, note, r in rows:
        if not out.get("available"):
            lines.append(f"| {name} | {desc} | {posture} | 판단 불가 | | | | {out.get('error', '')} | ❌ | {r['fall_state']} → {r['risk_level']} |")
            continue
        lines.append(f"| {name} | {desc} | {posture} | {out['posture']} | {'보임' if out['person_visible'] else '없음'} | "
                     f"{'예' if out['fall_suspected'] else '아니오'} | {out['confidence']} | {out['description']} | "
                     f"{'✅' if ok else '❌'} | {r['fall_state']} → **{r['risk_level']}** |")
    notes = [f"- {n}: {note.strip()}" for n, _, _, _, _, _, note, _ in rows if note.strip()]
    if notes:
        lines += ["", "참고:"] + notes
    lines += ["", "<details><summary>원본 JSON</summary>", "", "```json",
              json.dumps({n: o for n, o, _ in results}, ensure_ascii=False, indent=1), "```", "</details>"]
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n정답 일치 {ok_count}/{len(rows)}. 결과 저장: {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
