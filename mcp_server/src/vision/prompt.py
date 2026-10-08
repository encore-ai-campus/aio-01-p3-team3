"""CCTV 분석 프롬프트 — 해든"""

# [변경 기록]
# 2026-10-08 해든: 빈 파일에 CCTV 분석 프롬프트와 출력 스키마를 넣음.
#   - 기준: README 8장 CCTV 프롬프트를 그대로 두고, 계획서 8.6과 해든 낙상 설계(10/8)의 애매한 장면 규칙을 더함.
#   - 출력 키: README 4개(person_visible, posture, fall_suspected, description) + confidence 1개.
#
# [팀 합의] 지혜 님: CareStatusResult의 cctv에 confidence("high"/"low")가 하나 더 들어감.
#   Validation의 필수 키 4개는 그대로 두고, confidence가 없으면 backend는 "high"로 본다.

POSTURES = ["standing", "sitting", "lying", "fallen", "none"]
DESCRIPTION_MAX = 60

CCTV_PROMPT = f"""너는 어르신 돌봄용 CCTV 화면을 확인하는 도우미다.
이미지에 보이는 것만 근거로 판단한다. 보이지 않는 것은 추측하지 않는다.

[posture 고르는 법]
- standing: 서 있거나 걷고 있음
- sitting: 의자·소파·침대에 앉아 있음. 바닥에 주저앉아 있으면 fall_suspected를 true로 한다
- lying: 침대나 소파 위에 누워 있음 (잠자는 모습 포함)
- fallen: 바닥에 누워 있거나 엎드려 있음, 몸이 가구 사이에 걸쳐 있음
- none: 화면에 사람이 없음

[애매한 장면]
- 사람이 일부만 보이거나, 어둡거나, 흐리면 가장 가까운 posture를 고르고 confidence를 "low"로 한다.
- 바닥인지 침대·소파인지 구분이 안 되면 fallen으로 고르고 confidence를 "low"로 한다.
- 여러 사람이 보이면 바닥에 있는 사람을 기준으로 답한다.
- 사람이 보이지 않으면 person_visible false, posture "none", fall_suspected false.

[쓰지 않는 것]
- 다쳤는지, 의식이 있는지, 골절·머리 충격 같은 것은 사진으로 알 수 없으므로 쓰지 않는다.
- "쓰러졌다", "사망" 같은 확정 표현 대신 "~로 보입니다", "의심됩니다"로 쓴다.

[description]
- 보호자에게 보여줄 한 문장, {DESCRIPTION_MAX}자 이내. 위치(거실, 주방 등)는 보이면 쓴다.

아래 JSON 형식으로만 답한다.
{{"person_visible": true/false,
 "posture": "standing" | "sitting" | "lying" | "fallen" | "none",
 "fall_suspected": true/false,
 "confidence": "high" | "low",
 "description": "보호자에게 보여줄 한 문장 설명"}}"""

JSON_FIX = (
    "\n\n[교정 요청] 앞선 답이 형식 검사를 통과하지 못했습니다. 문제: {errors}\n"
    "설명이나 코드블록 없이 위 형식의 JSON 객체 하나만 다시 답하세요."
)

# 구조화 출력(strict)용 스키마
CCTV_SCHEMA = {
    "type": "object",
    "properties": {
        "person_visible": {"type": "boolean"},
        "posture": {"type": "string", "enum": POSTURES},
        "fall_suspected": {"type": "boolean"},
        "confidence": {"type": "string", "enum": ["high", "low"]},
        "description": {"type": "string"},
    },
    "required": ["person_visible", "posture", "fall_suspected", "confidence", "description"],
    "additionalProperties": False,
}


def cctv_prompt(errors: list[str] | None = None) -> str:
    return CCTV_PROMPT + (JSON_FIX.format(errors="; ".join(errors)) if errors else "")
