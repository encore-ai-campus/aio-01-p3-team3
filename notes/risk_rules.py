"""
판정 코드 (LLM 파트, 초안)

계획서 v2 4.2~4.5를 코드로 옮긴 것입니다. LLM은 쓰지 않습니다.
- vulnerability: 취약도 상/중/하
- wind_chill: 겨울 체감온도 (기상청 적용 조건 포함)
- weather_stage: 날씨 단계 normal/advisory/severe + hazard(heat/cold)
- risk_level: 위험도 관심/주의/경고/위험
- needs_alert: HandoffGuard. 관심이면 False (어디서 부를지는 오케스트레이터가 정함)
- select_shelter: Writer에 넘길 쉼터 1곳
- decide: SafetyResearchResult 하나를 받아 위 과정을 모두 거친 판정과 LLM 입력(ctx)을 돌려줌

아직 합의되지 않은 값은 아래 상수에 모아 두었습니다. 합의되면 상수만 바꾸면 됩니다.

팀원과 겹치는 부분에는 "# [팀 합의] 이름: 설명" 주석을 달았습니다.
검색: grep -n "팀 합의" risk_rules.py
"""

from datetime import time

# ---------- 합의 전 기본값 (여기만 바꾸면 됨) ----------

# [팀 합의] 지혜 님: HandoffGuard 기준. 원래 설계는 "특보 없음 + 체감 정상 + 취약도 하"면 종료였고,
#   여기서는 "위험도가 관심이면 종료"로 바꿨다. 주의도 알림(alert)으로 보낼지도 확인 필요.
ALERT_LEVELS = {"주의", "경고", "위험"}

# 기상청 특보 기준을 바탕으로 한 초안. 연동 전에 기상청 최신 기준 확인. (해든 담당)
HEAT_SEVERE_FEELS = 35.0
HEAT_ADVISORY_FEELS = 33.0
COLD_SEVERE_MIN = -15.0
COLD_ADVISORY_MIN = -12.0
COLD_SEVERE_DROP = 15.0
COLD_ADVISORY_DROP = 10.0
COLD_DROP_CEILING = 3.0  # 급강하 규칙은 오늘 최저가 3℃ 이하일 때만

# [팀 합의] 수언 님: 화면 계절 선택이 지금은 여름/겨울뿐. 봄·가을을 추가하면 이 기준으로 폭염/한파를 고른다.
# 봄·가을처럼 계절이 여름/겨울이 아닐 때 hazard를 정하는 기준
SHOULDER_HEAT_FROM = 20.0  # 최고기온이 이 이상이면 heat, 아니면 cold

# [팀 합의] 수언 님: 위험도 값은 한글(관심/주의/경고/위험). 프런트 COLORS 키와 같아야 카드 색이 나온다.
# [팀 합의] 지혜 님: 취약도 값(상/중/하)은 SafetyResearchResult의 vulnerability와 같은 표기.
# [해든 결정 10/7] 평범한 날씨(normal)는 취약도와 상관없이 관심 (원래 계획서는 취약도 상이면 주의).
#   이유: 봄·가을 18℃에도 "더위에 주의하세요" 알림이 나가는 것을 막기 위해.
RISK_TABLE = {
    "normal":   {"하": "관심", "중": "관심", "상": "관심"},
    "advisory": {"하": "주의", "중": "경고", "상": "경고"},
    "severe":   {"하": "경고", "중": "위험", "상": "위험"},
}
STAGE_LABEL = {
    ("heat", "normal"): "평소 수준 날씨",
    ("heat", "advisory"): "폭염주의보 수준",
    ("heat", "severe"): "폭염경보 수준",
    ("cold", "normal"): "평소 수준 날씨",
    ("cold", "advisory"): "한파주의보 수준",
    ("cold", "severe"): "한파경보 수준",
}
# [팀 합의] 두나 님: 기상청 특보 API가 weather["warning"]에 넣어 줄 문자열. 이 네 가지 이름과 같아야 한다.
WARNINGS = {
    "폭염주의보": ("heat", "advisory"),
    "폭염경보": ("heat", "severe"),
    "한파주의보": ("cold", "advisory"),
    "한파경보": ("cold", "severe"),
}


# ---------- ProfileAgent ----------

def vulnerability(profile: dict | None, season: str) -> str:
    """값이 없으면 위험한 쪽으로 본다. 프로필 자체가 없으면 상."""
    p = profile or {}
    score = 0
    if p.get("age", 80) >= 75:
        score += 1
    if p.get("lives_alone", True):
        score += 1
    if p.get("has_condition", True):
        score += 1
    device = "has_heating" if season == "winter" else "has_cooling"
    if not p.get(device, False):
        score += 1
    return "상" if score >= 3 else "중" if score >= 2 else "하"


# ---------- RiskAgent ----------

# [팀 합의] 두나 님: 데이터·MCP 문서의 wind_chill()에도 같은 적용 조건(기온 10℃ 이하, 풍속 1.3m/s 이상)을 넣어야 한다.
#   조건이 없으면 -12℃ 무풍이 +5.7℃로 계산된다. 한쪽 함수만 쓰도록 합치는 것도 방법.
def wind_chill(t: float, wind_ms: float) -> float:
    """기상청 겨울 체감온도식. 기온 10℃ 이하, 풍속 1.3m/s 이상에서만 쓰고, 그 밖에는 기온 그대로."""
    if t > 10 or wind_ms < 1.3:
        return t
    v = wind_ms * 3.6
    return round(13.12 + 0.6215 * t - 11.37 * v**0.16 + 0.3965 * v**0.16 * t, 1)


def _hazard(season: str, weather: dict) -> str:
    if season == "summer":
        return "heat"
    if season == "winter":
        return "cold"
    return "heat" if weather["max_temp"] >= SHOULDER_HEAT_FROM else "cold"


# [팀 합의] 두나 님: weather["feels_like"]가 여름엔 TMX(최고기온)라고 했는데 겨울엔 무엇인지 정해지지 않음.
#   그래서 겨울은 cold_feels()에서 최저기온과 풍속으로 다시 계산한다.
def heat_feels(weather: dict) -> float:
    """여름 체감온도: 데이터 쪽 feels_like가 있으면 그대로, 없으면 최고기온."""
    return weather.get("feels_like", weather["max_temp"])


def cold_feels(weather: dict) -> float:
    """겨울 체감온도: 아침 최저기온과 풍속으로 다시 계산한다."""
    return wind_chill(weather["min_temp"], weather.get("wind_ms", 0.0))


# [팀 합의] 두나 님: get_weather 출력에 min_temp_yesterday(전날 최저), min_temp_tomorrow(내일 최저) 추가 요청.
#   없으면 급강하 규칙은 건너뛰고, 이틀 지속은 오늘 값만으로 본다 (알림이 더 나가는 쪽).
def _cold_stage(weather: dict) -> str:
    today = weather["min_temp"]
    # 내일 값이 없으면 오늘만으로 본다 (알림이 더 나가는 쪽)
    tomorrow = weather.get("min_temp_tomorrow", today)
    two_days = max(today, tomorrow)  # 이틀 모두 기준 이하인지
    yesterday = weather.get("min_temp_yesterday")  # 없으면 급강하 규칙은 건너뜀
    drop = (yesterday - today) if yesterday is not None and today <= COLD_DROP_CEILING else 0.0

    if two_days <= COLD_SEVERE_MIN or drop >= COLD_SEVERE_DROP:
        return "severe"
    if two_days <= COLD_ADVISORY_MIN or drop >= COLD_ADVISORY_DROP:
        return "advisory"
    return "normal"


def _heat_stage(weather: dict) -> str:
    feels = heat_feels(weather)
    if feels >= HEAT_SEVERE_FEELS:
        return "severe"
    if feels >= HEAT_ADVISORY_FEELS:
        return "advisory"
    return "normal"


def weather_stage(season: str, weather: dict) -> tuple[str, str]:
    """(hazard, stage). 특보가 있으면 특보가 우선, 없거나 특보 API 장애면 기온으로 판정."""
    warning = weather.get("warning")
    if warning in WARNINGS:
        return WARNINGS[warning]
    hazard = _hazard(season, weather)
    return hazard, (_heat_stage(weather) if hazard == "heat" else _cold_stage(weather))


def risk_level(stage: str, vul: str) -> str:
    return RISK_TABLE[stage][vul]


# ---------- HandoffGuard ----------

# [팀 합의] 지혜 님: 이 함수를 오케스트레이터에서 Writer 호출 전에 부르는 것을 제안 (원래 설계도 Writer 앞).
def needs_alert(level: str) -> bool:
    return level in ALERT_LEVELS


# ---------- 쉼터 선택 ----------

# [팀 합의] 두나 님: 쉼터 CSV의 운영시간 형식. 지금은 "09:00-18:00"과 "24시간"만 읽는다.
#   무더위쉼터와 한파쉼터 CSV의 실제 형식을 확인해 맞춰야 한다.
def _is_open(hours: str, now: time) -> bool:
    """'09:00-18:00' 형식만 판단한다. '24시간'은 운영 중, 알 수 없는 형식은 운영 전으로 본다."""
    if not hours:
        return False
    if "24" in hours and "시간" in hours:
        return True
    try:
        start, end = (time.fromisoformat(x.strip()) for x in hours.split("-"))
    except ValueError:
        return False
    return start <= now < end


# [팀 합의] 두나 님: get_shelters 출력의 키 이름(name, distance_m, open)을 그대로 쓴다.
def select_shelter(shelters: list[dict] | None, now: time) -> dict | None:
    if not shelters:
        return None
    by_distance = sorted(shelters, key=lambda s: s["distance_m"])
    open_now = [s for s in by_distance if _is_open(s.get("open", ""), now)]
    chosen = open_now[0] if open_now else by_distance[0]
    return {
        "name": chosen["name"],
        "distance_m": chosen["distance_m"],
        "open": chosen.get("open", ""),
        "open_now": bool(open_now),
    }


# ---------- 전체 판정 + LLM 입력 ----------

# [팀 합의] 지혜 님: research는 오케스트레이터가 넘기는 SafetyResearchResult.
#   쓰는 키: task_id, season("summer"/"winter"/그 외), weather, profile, shelters.
# [팀 합의] 수언 님, 지혜 님: status 값은 프런트 응답 형식과 같은 alert / no_alert.
def decide(research: dict, now: time) -> dict:
    """SafetyResearchResult → 판정 결과. status가 alert면 ctx를 llm_contract에 넘긴다."""
    season, weather = research["season"], research["weather"]
    vul = vulnerability(research.get("profile"), season)
    hazard, stage = weather_stage(season, weather)
    level = risk_level(stage, vul)
    label = STAGE_LABEL[(hazard, stage)]
    feels = heat_feels(weather) if hazard == "heat" else cold_feels(weather)

    result = {
        "task_id": research.get("task_id"),
        "vulnerability": vul,
        "hazard": hazard,
        "weather_stage": stage,
        "stage_label": label,
        "risk_level": level,
        "risk_reason": f"{label} + 취약도 {vul}",
        "status": "alert" if needs_alert(level) else "no_alert",
        "ctx": None,
    }
    if result["status"] == "alert":
        result["ctx"] = build_ctx(result, weather, research.get("shelters"), now, feels)
    return result


# [팀 합의] 상옥 님: 이 ctx를 AutoHealing.llm()이 llm_contract.py의 call_* / validate_* / fallback_*에 넘긴다.
def build_ctx(decision: dict, weather: dict, shelters: list[dict] | None, now: time, feels: float) -> dict:
    """llm_contract.py가 받는 입력 형식. 지병 등 프로필 원문은 넣지 않는다."""
    return {
        "hazard": decision["hazard"],
        "risk_level": decision["risk_level"],
        "stage_label": decision["stage_label"],
        "vulnerability": decision["vulnerability"],
        "max_temp": weather["max_temp"],
        "min_temp": weather["min_temp"],
        "feels_like": feels,
        "wind_ms": weather.get("wind_ms", 0.0),
        "shelter": select_shelter(shelters, now),
    }
