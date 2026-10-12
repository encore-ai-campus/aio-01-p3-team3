"""최신 팀 시나리오 계약에 따른 어르신 케어 Mock 데이터."""

from typing import Final, Literal, TypeAlias


Scenario: TypeAlias = Literal[
    "normal",
    "heat",
    "induction",
    "fall",
    "critical",
]


MOCK_PROFILES: Final[dict[str, dict[str, object]]] = {
    "profile-01": {
        "display_name": "어르신 A",
        "age": 84,
        "lives_alone": True,
        "has_condition": True,
        "mobility_limited": True,
        "home_id": "home-01",
        "area": "서울시 강남구",
    },
    "profile-02": {
        "display_name": "어르신 B",
        "age": 78,
        "lives_alone": True,
        "has_condition": False,
        "mobility_limited": False,
        "home_id": "home-02",
        "area": "서울시 송파구",
    },
    "profile-03": {
        "display_name": "어르신 C",
        "age": 70,
        "lives_alone": True,
        "has_condition": False,
        "mobility_limited": False,
        "home_id": "home-03",
        "area": "서울시 서초구",
    },
}


SCENARIOS: Final[dict[Scenario, dict[str, object]]] = {
    "normal": {
        "vital": {
            "heart_rate": 72,
            "systolic_bp": 125,
            "temperature_c": 36.5,
            "spo2": 98,
        },
        "indoor_environment": {
            "temperature_c": 24.0,
            "humidity_percent": 50.0,
        },
        "devices": {
            "air_conditioner": "off",
            "induction": "off",
            "induction_minutes": None,
            "induction_temperature": None,
        },
        "cctv_image_path": "assets/cctv/normal.png",
    },
    "heat": {
        "vital": {
            "heart_rate": 105,
            "systolic_bp": 140,
            "temperature_c": 37.8,
            "spo2": 96,
        },
        "indoor_environment": {
            "temperature_c": 33.0,
            "humidity_percent": 75.0,
        },
        "devices": {
            "air_conditioner": "off",
            "induction": "off",
            "induction_minutes": None,
            "induction_temperature": None,
        },
        "cctv_image_path": "assets/cctv/normal.png",
    },
    "induction": {
        "vital": {
            "heart_rate": 80,
            "systolic_bp": 130,
            "temperature_c": 36.6,
            "spo2": 97,
        },
        "indoor_environment": {
            "temperature_c": 26.0,
            "humidity_percent": 55.0,
        },
        "devices": {
            "air_conditioner": "off",
            "induction": "on",
            "induction_minutes": 120,
            "induction_temperature": 300,
        },
        "cctv_image_path": "assets/cctv/kitchen_empty.png",
    },
    "fall": {
        "vital": {
            "heart_rate": 118,
            "systolic_bp": 120,
            "temperature_c": 36.4,
            "spo2": 96,
        },
        "indoor_environment": {
            "temperature_c": 25.0,
            "humidity_percent": 50.0,
        },
        "devices": {
            "air_conditioner": "off",
            "induction": "off",
            "induction_minutes": None,
            "induction_temperature": None,
        },
        "cctv_image_path": "assets/cctv/fall.png",
    },
    "critical": {
        "vital": {
            "heart_rate": 140,
            "systolic_bp": 85,
            "temperature_c": 36.0,
            "spo2": 88,
        },
        "indoor_environment": {
            "temperature_c": 25.0,
            "humidity_percent": 50.0,
        },
        "devices": {
            "air_conditioner": "off",
            "induction": "off",
            "induction_minutes": None,
            "induction_temperature": None,
        },
        "cctv_image_path": "assets/cctv/lying.png",
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
}
