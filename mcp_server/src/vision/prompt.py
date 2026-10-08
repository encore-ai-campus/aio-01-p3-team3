"""CCTV 분석 프롬프트 — 해든"""

# [변경 기록]
# 2026-10-08 해든: 빈 파일에 CCTV 분석 프롬프트와 출력 스키마를 넣음.
#   - 기준: README 8장 CCTV 프롬프트를 그대로 두고, 계획서 8.6과 해든 낙상 설계(10/8)의 애매한 장면 규칙을 더함.
#   - 출력 키: README 4개(person_visible, posture, fall_suspected, description) + confidence 1개.
# 2026-10-08 해든 (가짜 이미지 실제 점검 8/8 뒤): 바닥에 주저앉은 모습을 "소파에 앉아 계십니다"로 설명해 정상으로 판정됨.
#   바닥에 앉으면 sitting + fall_suspected true, 설명에 "바닥에 앉아"를 쓰도록 규칙을 분명히 함.
# 2026-10-08 해든 (CCTV 판단 방식 변경): LLM에게 "낙상인가"를 묻지 않고 보이는 사실 4개만 묻는다
#   (사람 보임, 몸이 닿은 곳 floor/furniture, 몸 모양 upright/seated/horizontal, 사진이 선명한지).
#   자세·낙상 의심·확신은 analyzer.facts_to_result()가 코드 규칙으로 정함. 출력 키(posture 등)는 그대로라 backend는 안 바뀜.
#
# [팀 합의] 지혜 님: CareStatusResult의 cctv에 confidence("high"/"low")와 facts(LLM이 본 사실 4개)가 더 들어감.
#   Validation의 필수 키 4개는 그대로 두고, confidence가 없으면 backend는 "high"로 본다.

POSTURES = ["standing", "sitting", "lying", "fallen", "none"]
DESCRIPTION_MAX = 60
# LLM이 답하는 "보이는 사실". 자세(posture)와 낙상 의심(fall_suspected)은 analyzer.facts_to_result()가 코드로 정한다.
SUPPORTS = ["floor", "furniture", "unclear", "none"]          # 몸이 닿아 있는 곳: 바닥 / 의자·소파·침대 / 모르겠음 / 사람 없음
SHAPES = ["upright", "seated", "horizontal", "unclear", "none"]   # 몸 모양: 서 있음·걷기 / 앉음 / 누움·엎드림 / 모르겠음 / 사람 없음

CCTV_PROMPT = f"""너는 어르신 돌봄용 CCTV 화면에서 보이는 사실만 적는 도우미다.
낙상인지, 위험한지는 판단하지 않는다. 아래 질문에 이미지에 보이는 것만으로 답한다.

[질문]
1. person_visible: 화면에 사람이 보이는가 (true/false)
2. body_support: 사람 몸(엉덩이·등·옆구리)이 어디에 닿아 있는가
   - floor: 바닥 (가구 바로 앞이라도 엉덩이나 몸이 바닥에 닿아 있으면 floor)
   - furniture: 의자·소파·침대 위
   - unclear: 어둡거나 흐리거나 가려져서 모르겠음
   - none: 사람이 없음
3. body_shape: 몸 모양
   - upright: 서 있거나 걷고 있음
   - seated: 앉아 있음 (바닥에 주저앉은 것도 seated)
   - horizontal: 누워 있거나 엎드려 있음
   - unclear: 모르겠음
   - none: 사람이 없음
4. image_clear: 밝기·초점이 괜찮아 위 답을 자신 있게 할 수 있는가 (true/false)

[모를 때]
- 모르면 추측하지 말고 unclear로 답한다. 여러 사람이 보이면 바닥에 가까운 사람을 기준으로 답한다.

[쓰지 않는 것]
- 다쳤는지, 의식이 있는지, 골절·머리 충격처럼 사진으로 알 수 없는 것.
- "쓰러졌다", "사망" 같은 확정 표현. "~로 보입니다"로 쓴다.

[description]
- 보호자에게 보여줄 한 문장, {DESCRIPTION_MAX}자 이내. 장소(거실, 주방 등)와 몸이 어디에 있는지(바닥, 소파 등)를 쓴다.

아래 JSON 형식으로만 답한다.
{{"person_visible": true/false,
 "body_support": "floor" | "furniture" | "unclear" | "none",
 "body_shape": "upright" | "seated" | "horizontal" | "unclear" | "none",
 "image_clear": true/false,
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
        "body_support": {"type": "string", "enum": SUPPORTS},
        "body_shape": {"type": "string", "enum": SHAPES},
        "image_clear": {"type": "boolean"},
        "description": {"type": "string"},
    },
    "required": ["person_visible", "body_support", "body_shape", "image_clear", "description"],
    "additionalProperties": False,
}


def cctv_prompt(errors: list[str] | None = None) -> str:
    return CCTV_PROMPT + (JSON_FIX.format(errors="; ".join(errors)) if errors else "")
