"""LLM 실패 시 템플릿 문구 (FALLBACK) — 해든"""

# [변경 기록]
# 2026-10-08 해든: 빈 파일에 템플릿 문구를 넣음.
#   - 출처: notes/llm_contract.py의 fallback_writer/fallback_summary 틀. 폭염·한파·쉼터 문구는 모두 뺌.
#   - 기준: 계획서 4장 "템플릿" 표(승인 대기, 승인·실행 성공, 119 실행, 기기 제어 실패, 거절)와 README 7장 FALLBACK.
#   - 모든 템플릿은 llm/prompts.py의 validate_emergency / validate_summary를 통과해야 함 (tests/test_llm_contract.py).
# 2026-10-08 해든 (4단계): 조치 이름에 speaker_check("스피커로 상태 확인") 추가.
# 2026-10-08 해든 (축 정리): 보일러 이름 추가 (HEATING_DEVICE를 boiler로 바꿀 때 "보일러 난방 20℃로 켜기").
# 2026-10-08 해든 (승인·119 흐름): 119 자동 연결 이름("119 바로 연결"), 보호자 알림 3종(승인 요청·재알림·긴급),
#   Summary 상황 3개(info: 승인할 조치 없이 알림만, auto_119: 어르신 무응답·바이탈 매우 위험으로 바로 연결, timeout_119: 보호자 무응답으로 자동 연결) 추가.
#   알림 문구는 LLM을 기다리지 않고 바로 보내야 해서 모두 코드 템플릿. 흐름: notes/승인-119-흐름.md
# 2026-10-08 해든 (말투): 어르신 문장은 다정한 간호사처럼 "어르신,"으로 시작해 챙기는 한 마디를 넣고,
#   위급 알림·안내는 "지금 바로 ~하세요"처럼 단호하게 바꿈. 어르신 문장 길이 40 → 60자.
# 2026-10-08 해든 (CCTV 캡처): 승인 알림에 CCTV 캡처를 붙인 경우 "CCTV 캡처를 보고 판단하세요" /
#   판단 불가면 "원본 캡처를 직접 확인하세요" 한 문장을 넣음 (CCTV_CHECK_TEXT).
# 2026-10-08 해든 (워치 버튼): 스피커 대신 워치 버튼 확인(watch_check). 거절 템플릿에 판정 근거를 붙이고(120자 안일 때),
#   체온 원인이면 어르신 안내에 하실 일(ctx["elder_care"])을 씀.
# 2026-10-08 해든 (현실 상황 점검): 보호자 문장 끝은 prompts.next_step() 그대로, 거절이어도 어르신께 짧게 안내,
#   기기 실패면 어르신께 솔직하게 말하고 직접 하실 일 안내(ELDER_TIP), 119 안내에 "구급대가 오고 있어요" 안심 한 마디.
#
# [팀 합의] 상옥 님: LLM 재요청까지 실패하면 AutoHealing이 이 함수 결과를 쓰고 fallback_used = true로 기록.
# 2026-10-08 해든 (main 문서 개정판): 119 자동 연결 알림(emergency_alert_message)에도 CCTV 캡처 안내를 붙임 (DR-VISION-01 원본 캡처 확인).

# 승인 화면·안내문에 쓰는 조치 이름. 각 30자 이내 (Emergency action_texts 길이 제한과 같음).
# [팀 합의] 기화 님: README 5장 "거절 → 보호자용 기록만"과 다름. 거절돼도 어르신이 아무 말도 못 듣고 혼자 남지 않게
#   "보호자분께 알려 드렸어요, 곧 연락드릴 거예요"만 짧게 보냄. README대로 하려면 False.
ELDER_MESSAGE_ON_REJECT = True

DEVICE_LABEL = {"aircon": "에어컨", "induction": "인덕션", "boiler": "보일러"}


def action_label(action: dict) -> str:
    """조치 dict → 사람이 읽는 이름. 예: {"type": "call_119"} → "119 호출"."""
    kind, value = action["type"], action.get("value") or {}
    if kind == "call_119":
        return "119 바로 연결" if action.get("auto") else "119 호출"
    if kind == "notify_guardian":
        return "보호자에게 상황 알림"
    if kind == "hospital_info":
        return "가까운 병원 정보 안내"
    if kind == "watch_check":
        return "워치로 상태 확인"
    if kind == "control_device":
        device = DEVICE_LABEL.get(value.get("device"), value.get("device", "기기"))
        if value.get("action") == "off":
            return f"{device} 끄기"
        mode = {"cool": "냉방", "heat": "난방"}.get(value.get("mode"), "")
        target = f" {value['target']}℃로" if value.get("target") is not None else ""
        return f"{device} {mode}{target} 켜기".replace("  ", " ")
    return kind


# ---------- Emergency (승인 대기) ----------

def fallback_emergency(ctx: dict) -> dict:
    """LLM 조치안 문장 대신 쓰는 출력. reason은 rules/risk.py가 만든 원인 문장을 그대로 씀."""
    return {
        "reason": ctx["code_reason"],
        "action_texts": [action_label(a) for a in ctx["actions"]],
    }


# [팀 합의] 지혜 님·두나 님: 승인 대기 응답(pending_approval) 때 보호자 휴대폰에 보내는 첫 알림 문구.
#   README 7장 FALLBACK 문장에서 말투를 바꿈 (위급은 "[긴급] … 지금 바로 화면에서 조치를 승인하세요"). README 문장도 같이 고쳐 주세요.
CCTV_CHECK_TEXT = {"fall": "CCTV 캡처를 보고 판단하세요.",
                   "unavailable": "CCTV 판단이 안 돼 원본 캡처를 직접 확인하세요."}


def pending_guardian_message(risk_level: str, reason: str, actions: list[dict] | None = None) -> str:
    wait = [a["timeout_seconds"] for a in actions or [] if a["type"] == "call_119" and a.get("on_timeout") == "execute"]
    note = next((a["value"].get("cctv_check") for a in actions or [] if a["type"] == "notify_guardian"), None)
    cctv = f" {CCTV_CHECK_TEXT[note]}" if note in CCTV_CHECK_TEXT else ""
    if risk_level == "위급":      # 위급은 단호하게: 무슨 일인지 → 사진 → 지금 할 일 → 자동 연결 안내
        text = f"[긴급] 어르신이 위급합니다. 판정 근거: {reason}.{cctv} 지금 바로 화면에서 조치를 승인하세요."
        if wait:
            text += f" {wait[0]}초 안에 응답이 없으면 119에 자동으로 연락합니다."
        return text
    return f"[확인 요청] 어르신 상태를 살펴봐 주세요. 위험도 {risk_level}. 판정 근거: {reason}.{cctv} 화면에서 조치를 승인해 주세요."


# [팀 합의] 지혜 님·두나 님: 승인 요청 뒤 GUARDIAN_REMIND_SEC 동안 응답이 없을 때 한 번 더 보내는 알림.
def reminder_guardian_message(risk_level: str, seconds_left: int | None = None) -> str:
    if risk_level == "위급":
        text = "[긴급·다시 알림] 아직 응답이 없습니다. 지금 바로 화면을 확인하세요."
        if seconds_left:
            text += f" {seconds_left}초 뒤 119에 자동으로 연락합니다."
        return text
    return f"[다시 알림] 어르신 위험도 {risk_level}, 아직 승인 응답이 없습니다. 화면을 확인해 주세요."


AUTO_119_WHY = {"ELDER_NO_RESPONSE": "어르신이 워치 확인에 응답하지 않아",
                "VITAL_SEVERE": "바이탈 여러 항목이 매우 위험해",
                "GUARDIAN_TIMEOUT": "보호자 응답이 없어"}


# [팀 합의] 지혜 님·두나 님: 119를 승인 없이 연결한 직후 보호자에게 바로 보내는 알림 (LLM 기다리지 않음).
def emergency_alert_message(reason: str, auto_reason: str, hospital: str | None = None,
                            actions: list[dict] | None = None) -> str:
    note = next((a["value"].get("cctv_check") for a in actions or [] if a["type"] == "notify_guardian"), None)
    cctv = f" {CCTV_CHECK_TEXT[note]}" if note in CCTV_CHECK_TEXT else ""
    text = f"[긴급] {AUTO_119_WHY.get(auto_reason, '위급 상황이라')} 119에 바로 연락했습니다. 판정 근거: {reason}.{cctv}"
    if hospital:
        text += f" 가까운 응급실: {hospital}."
    return text + " 지금 바로 어르신께 전화하세요."


# ---------- Summary (승인·거절 뒤) ----------

# 어르신 안내: 다정한 간호사 말투. "어르신,"으로 시작, 한 일 + 지금 하실 일 하나. 119는 짧고 분명하게.
ELDER_DONE = "어르신, 보호자분께 잘 전해 드렸어요. 편히 쉬고 계세요."
ELDER_COOL = "어르신, 시원하게 에어컨을 켜 두었어요. 물 한 잔 천천히 드세요."
ELDER_HEAT = "어르신, 따뜻하게 난방을 켜 두었어요. 담요도 꼭 덮고 계세요."
ELDER_INDUCTION = "어르신, 켜져 있던 인덕션은 제가 꺼 두었어요. 안심하세요."
ELDER_INFO = "어르신, 괜찮으신지 보호자분께 알려 드렸어요. 천천히 움직이세요."
ELDER_119 = "어르신, 구급대가 오고 있어요. 보호자분께도 알렸어요. 움직이지 말고 그대로 계세요."
ELDER_REJECTED = "어르신, 보호자분께 상황을 알려 드렸어요. 곧 연락드릴 거예요."
ELDER_DEVICE_FAIL = "어르신, 보호자분이 곧 연락드릴 거예요. 편히 계세요."


def _elder_done(labels: list[str]) -> str:
    text = " ".join(labels)
    if "냉방" in text:
        return ELDER_COOL
    if "난방" in text:
        return ELDER_HEAT
    if "인덕션" in text:
        return ELDER_INDUCTION
    return ELDER_DONE


def _elder_care(ctx: dict) -> str | None:
    care = ctx.get("elder_care")
    return f"어르신, {care[0]}" if care and len(care[0]) + 5 <= 60 else None


def fallback_summary(ctx: dict) -> dict:
    """상황별 고정 문구. ctx는 prompts.build_summary_ctx() 결과. 보호자 문장 끝에는 ctx["next_step"]을 그대로 붙인다."""
    level, nxt = ctx["risk_level"], " " + ctx["next_step"]
    if ctx["situation"] == "rejected":
        text = f"{ctx['reason'].rstrip('.')}. 보호자 거절로 조치 없이 기록했습니다. 위험도 {level}.{nxt}"
        return {"guardian_message": text if len(text) <= 120 else f"보호자 거절로 조치 없이 기록했습니다. 위험도 {level}.{nxt}",
                "elder_message": ELDER_REJECTED if ELDER_MESSAGE_ON_REJECT else ""}

    if ctx["situation"] in ("auto_119", "timeout_119"):
        why = AUTO_119_WHY.get(ctx.get("auto_reason"), "위급 상황이라")
        guardian = f"{why} 119에 바로 연락했습니다."
        if ctx.get("hospital"):
            guardian += f" 가까운 응급실: {ctx['hospital']}."
        return {"guardian_message": guardian + nxt, "elder_message": ELDER_119}

    if ctx["situation"] == "device_fail":
        failed = ", ".join(ctx["failed_labels"])
        tip = ctx.get("elder_tip")
        elder = f"어르신, {tip[0]}" if tip and len(tip[0]) + 5 <= 60 else ELDER_DEVICE_FAIL
        return {"guardian_message": f"{failed}에 실패했습니다. 직접 조치가 필요합니다. 위험도 {level}.{nxt}",
                "elder_message": elder}

    if "call_119" in ctx["succeeded_types"]:
        guardian = "승인하신 대로 119에 연락했습니다."
        if ctx.get("hospital"):
            guardian += f" 가까운 응급실: {ctx['hospital']}."
        return {"guardian_message": guardian + nxt, "elder_message": ELDER_119}

    if ctx["situation"] == "info":
        spoke = "워치로 어르신께 괜찮은지 물었습니다. " if "watch_check" in ctx["succeeded_types"] else ""
        text = f"{spoke}{ctx['reason'].rstrip('.')}. 위험도 {level}.{nxt}"
        return {"guardian_message": text if len(text) <= 120 else f"{spoke}위험도 {level}.{nxt}",
                "elder_message": _elder_care(ctx) or ELDER_INFO}

    done = ", ".join(ctx["succeeded_labels"]) or "조치"
    return {"guardian_message": f"승인하신 조치({done})를 실행했습니다. 위험도 {level}.{nxt}",
            "elder_message": _elder_done(ctx["succeeded_labels"]) if _elder_done(ctx["succeeded_labels"]) != ELDER_DONE
            else _elder_care(ctx) or ELDER_DONE}
