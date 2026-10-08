"""노인 실시간 케어 시연에서 사용하는 Mock 데이터.

실제 개인정보나 실제 기기 상태는 포함하지 않는다. MCP 조회 도구는
``profile_id``와 ``scenario``를 받아 이 모듈의 값을 조회한다.
"""

from typing import Final, Literal, TypeAlias


Scenario: TypeAlias = Literal["normal", "heat", "induction", "fall"]
Condition: TypeAlias = Literal[
    "diabetes",
    "hypertension",
    "hypotension",
    "heart_disease",
    "fall_risk",
]


CONDITION_LABELS: Final[dict[Condition, str]] = {
    "diabetes": "당뇨",
    "hypertension": "고혈압",
    "hypotension": "저혈압",
    "heart_disease": "심질환",
    "fall_risk": "낙상위험",
}


MOCK_PROFILES: Final[dict[str, dict[str, object]]] = {
    "profile-01": {
        "display_name": "김안심",
        "home_id": "home-01",
        "area": "서울시 강남구",
        "conditions": ["diabetes", "hypertension"],
        "has_forgetfulness": True,
    },
    "profile-02": {
        "display_name": "이평안",
        "home_id": "home-02",
        "area": "서울시 송파구",
        "conditions": ["hypotension", "fall_risk"],
        "has_forgetfulness": True,
    },
    "profile-03": {
        "display_name": "박건강",
        "home_id": "home-03",
        "area": "서울시 서초구",
        "conditions": ["heart_disease", "hypertension"],
        "has_forgetfulness": False,
    },
    "profile-04": {
        "display_name": "최다정",
        "home_id": "home-04",
        "area": "서울시 마포구",
        "conditions": ["diabetes", "fall_risk"],
        "has_forgetfulness": True,
    },
    "profile-05": {
        "display_name": "정행복",
        "home_id": "home-05",
        "area": "서울시 노원구",
        "conditions": ["hypertension", "heart_disease"],
        "has_forgetfulness": False,
    },
}


SCENARIOS: Final[dict[Scenario, dict[str, object]]] = {
    "normal": {
        "vital": {
            "heart_rate": 72,
            "systolic_bp": 125,
            "diastolic_bp": 80,
            "temperature_c": 36.5,
            "spo2": 98,
            "measured_at": "2026-10-08T10:00:00+09:00",
        },
        "indoor_environment": {
            "temperature_c": 24.0,
            "humidity_percent": 50.0,
        },
        "devices": {
            "air_conditioner": "off",
            "induction": "off",
            "induction_minutes": None,
        },
        "cctv_image_path": "assets/cctv/normal.jpg",
    },
    "heat": {
        "vital": {
            "heart_rate": 105,
            "systolic_bp": 140,
            "diastolic_bp": 90,
            "temperature_c": 37.8,
            "spo2": 96,
            "measured_at": "2026-10-08T10:10:00+09:00",
        },
        "indoor_environment": {
            "temperature_c": 33.0,
            "humidity_percent": 75.0,
        },
        "devices": {
            "air_conditioner": "off",
            "induction": "off",
            "induction_minutes": None,
        },
        "cctv_image_path": "assets/cctv/normal.jpg",
    },
    "induction": {
        "vital": {
            "heart_rate": 80,
            "systolic_bp": 130,
            "diastolic_bp": 82,
            "temperature_c": 36.6,
            "spo2": 97,
            "measured_at": "2026-10-08T10:20:00+09:00",
        },
        "indoor_environment": {
            "temperature_c": 26.0,
            "humidity_percent": 55.0,
        },
        "devices": {
            "air_conditioner": "off",
            "induction": "on",
            "induction_minutes": 120,
        },
        "cctv_image_path": "assets/cctv/kitchen_empty.jpg",
    },
    "fall": {
        "vital": {
            "heart_rate": 118,
            "systolic_bp": 100,
            "diastolic_bp": 65,
            "temperature_c": 36.3,
            "spo2": 93,
            "measured_at": "2026-10-08T10:30:00+09:00",
        },
        "indoor_environment": {
            "temperature_c": 25.0,
            "humidity_percent": 50.0,
        },
        "devices": {
            "air_conditioner": "off",
            "induction": "off",
            "induction_minutes": None,
        },
        "cctv_image_path": "assets/cctv/fall.jpg",
    },
}


HOSPITALS_BY_AREA: Final[dict[str, list[dict[str, object]]]] = {
    "서울시 강남구": [
        {
            "name": "강남안심병원",
            "distance_km": 1.2,
            "type": "응급실",
        },
        {
            "name": "서울케어병원",
            "distance_km": 2.8,
            "type": "종합병원",
        },
    ],
    "서울시 송파구": [
        {
            "name": "송파안심병원",
            "distance_km": 1.5,
            "type": "응급실",
        },
        {
            "name": "잠실케어병원",
            "distance_km": 3.1,
            "type": "종합병원",
        },
    ],
    "서울시 서초구": [
        {
            "name": "서초안심병원",
            "distance_km": 1.8,
            "type": "응급실",
        },
        {
            "name": "반포케어병원",
            "distance_km": 3.4,
            "type": "종합병원",
        },
    ],
    "서울시 마포구": [
        {
            "name": "마포안심병원",
            "distance_km": 1.1,
            "type": "응급실",
        },
        {
            "name": "공덕케어병원",
            "distance_km": 2.6,
            "type": "종합병원",
        },
    ],
    "서울시 노원구": [
        {
            "name": "노원안심병원",
            "distance_km": 1.4,
            "type": "응급실",
        },
        {
            "name": "상계케어병원",
            "distance_km": 2.9,
            "type": "종합병원",
        },
    ],
}
