"""Profile Agent: 취약도(상/중/하) 계산 — 해든"""

# [변경 기록]
# 2026-10-08 해든: 빈 파일에 README 4장 vulnerability() 함수와 run_profile()을 넣음.
#   - notes/risk_rules.py의 vulnerability()는 냉난방기 유무를 셌는데, README 기준(거동 불편)으로 바꿈.
#   - 지병명 원문은 받지 않고 has_condition(유무)만 씀. 결과에도 취약도만 내보냄.


def vulnerability(p: dict | None) -> str:
    """75세 이상, 독거, 지병 있음, 거동 불편 중 3개 이상이면 상, 2개면 중, 그 밖에는 하.
    값이 없으면 위험한 쪽으로 센다. 프로필 자체가 없으면 상."""
    p = p or {}
    score = 0
    if p.get("age", 80) >= 75:
        score += 1
    if p.get("lives_alone", True):
        score += 1
    if p.get("has_condition", True):        # 지병 유무만 사용
        score += 1
    if p.get("mobility_limited", True):     # 거동 불편 여부
        score += 1
    return "상" if score >= 3 else "중" if score >= 2 else "하"


# [팀 합의] 지혜 님: 오케스트레이터가 SQLite에서 읽은 프로필 dict를 넘겨 주는 방식을 제안.
#   프로필 조회(db/)를 이 에이전트 안에서 할지, 오케스트레이터가 할지 정해야 함.
def run_profile(profile: dict | None) -> dict:
    """CareStatusResult의 vulnerability 필드에 들어갈 값. 프로필이 없으면 "상" (README Join Guard)."""
    return {"vulnerability": vulnerability(profile)}
