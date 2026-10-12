# 시연 시나리오 확정안

> 이 문서는 데이터 시나리오, 테스트 프로필, 시나리오별 기대 결과를 정리한 **팀 공용 기준**입니다.
> 데이터 형식은 `backend/src/schemas.py`(지혜), 판정 규칙은 `backend/src/rules/risk.py`(해든)를 기준으로 합니다.
> `mock_data.py`(두나), Guard·응답 조립(지혜), 장애 주입(상옥), 화면(수언)이 이 문서를 기준으로 개발합니다.
>
> ⚠️ 모든 수치는 **시연용 가상값**이며, 판정 기준은 **의학적 기준이 아닌 시연용 예시 규칙**입니다.

---

## 1. 결정 사항

| # | 항목 | 결정 |
|---|---|---|
| 1 | 데이터 시나리오 | `normal`, `heat`, `induction`, `fall`, `critical` **5개** |
| 2 | 장애 주입 | 데이터 시나리오와 별도로 요청의 `fault` 필드로 **시나리오에 얹어서** 실행한다. 4종(`vital`, `iot`, `vision`, `llm`) 모두 **시연 필수** |
| 3 | 데이터 형식 | 필드 이름과 구조는 **지혜님 `schemas.py`** 를 따른다 (`run_id`, `profile_id`, `vital`, `indoor_environment`, `devices` …) |
| 4 | 스키마 추가 | `Scenario`에 `critical` 추가, `DeviceStatus`에 `induction_temperature` 추가, `DataSource`에 `live` 추가 |
| 5 | 혈압 | 확장기 혈압(`diastolic_bp`)은 쓰지 않는다. 수축기(`systolic_bp`)만 사용 |
| 6 | 판정 규칙 | **해든님 `risk.py`** 를 따른다: NEWS2 바이탈 점수, 실내 이상·극한, 판정 축 4개, 낙상 상태 5종 |
| 7 | 취약도 보정 | 취약도 "상"이면 한 단계 올리되, **정상은 올리지 않는다** (최대 "위급") |
| 8 | 119 자동 연결 | **바이탈이 매우 위험하면(`VITAL_SEVERE`) 보호자 승인 없이 119 호출.** 그 밖의 119는 승인 필요 |
| 9 | 제외 | `fall_event`(워치·음성 응답·움직임 없는 시간·머리 충격), `signs`(이상 행동·호흡 곤란)는 쓰지 않는다 |
| 10 | 프로필 | 시나리오별로 사용할 테스트 프로필을 정해 둔다 (3장) |
| 13 | 보호자 로그인 (10/12) | 보호자 한 명이 부모 한 분을 본다. 회원가입 없이 **데모 계정 4개**(자녀 A·B·C·D → 어르신 A·B·C·D)로만 로그인한다. CCTV 사진 속 인물 한 명이 부모 한 분이다. 시연 영상은 장면마다 해당 보호자로 로그인해서 찍는다 (3장·7장) |
| 11 | `fall` | 위급 판정의 근거가 **CCTV** 가 되도록, 바이탈은 위험 범위(3점) 없이 심박 변화만 둔다 |
| 12 | 인덕션 | `induction: "on"`, `induction_minutes: 120`, `induction_temperature: 300`이 들어오면 **인덕션 끄기** 조치안 (보호자 승인 후 실행) |

---

## 2. 판정 기준 (해든님 `risk.py`)

### 2-1. 바이탈 점수 (NEWS2 기반)

항목마다 0~3점. **3점 = 위험 범위**, 1~2점 = 바이탈 변화.

| 항목 | 0점 | 1점 | 2점 | 3점 (위험 범위) |
|---|---|---|---|---|
| `heart_rate` (회/분) | 51~90 | 41~50, 91~110 | 111~130 | ≤40, ≥131 |
| `systolic_bp` (mmHg) | 111~219 | 101~110 | 91~100 | ≤90, ≥220 |
| `temperature_c` (℃) | 36.1~38.0 | 35.1~36.0, 38.1~39.0 | 39.1~39.9 | ≤35.0, ≥40.0 |
| `spo2` (%) | ≥96 | 94~95 | 92~93 | ≤91 |

### 2-2. 실내·기기

| 항목 | 기준 |
|---|---|
| 실내 이상 | 28℃ 초과 또는 20℃ 미만 |
| 실내 극한 | 31℃ 초과 또는 18℃ 미만 |
| 에어컨 목표 온도 | 4~10월 24~26℃, 11~3월 20~22℃ (고온 → 상한으로 냉방, 저온 → 하한으로 난방) |
| 인덕션 방치 | CCTV에 사람 없음 + `induction == "on"` + (`induction_minutes ≥ 60` 또는 `induction_temperature ≥ 250`) |

### 2-3. 판정 축과 최종 위험도

| 축 | 원인 | 단계 |
|---|---|---|
| `fall` | CCTV가 쓰러진 자세를 분명히 봄 | 위급 |
| | 약한 낙상 신호 (흐린 사진, 자세·플래그 불일치) | 경고 |
| | 낙상 의심 + 바이탈 위험 범위 | 위급 |
| `cardio` | 심박·혈압 3점 / 1~2점 | 경고 / 주의 |
| `respiratory` | 산소포화도 3점 / 1~2점 | 경고 / 주의 |
| `environment` | 체온 3점 / 1~2점 | 경고 / 주의 |
| | 실내 극한 | 경고 |
| | 실내 이상 + 바이탈 변화 / 실내 이상만 | 경고 / 주의 |
| | 인덕션 방치 | 주의 |
| 축을 넘는 규칙 | 위험 범위(3점) 항목 2개 이상 | 위급 |

**최종 위험도 = 가장 높은 축 + 취약도 보정** (취약도 "상"이면 한 단계 올림, 정상은 그대로)

```python
LEVELS = ["정상", "주의", "경고", "위급"]

def adjust(level: str, vulnerability: str | None) -> str:
    if level == "정상" or (vulnerability or "상") != "상":
        return level
    return LEVELS[min(LEVELS.index(level) + 1, len(LEVELS) - 1)]
```

### 2-4. 119 자동 연결 (`auto_119: "VITAL_SEVERE"`)

아래를 **모두** 만족할 때만 보호자 승인 없이 119에 연결합니다.

1. 최종 위험도 위급
2. 바이탈 위험 범위(3점) 항목 2개 이상
3. 바이탈 4항목 점수 합 7점 이상
4. 최신 측정값 (`source != "cache"`)

---

## 3. 테스트 프로필 (가상 인물)

취약도 계산식은 README 4장 `vulnerability()`를 따릅니다. (나이 ≥ 75, 혼자 거주, 지병 있음, 거동 불편 각 1점 → 3점 이상 "상", 2점 "중", 그 외 "하")

| ID | 이름 (가상) | 나이 | 혼자 거주 | 지병 | 거동 불편 | 점수 | 취약도 | 보호자 데모 계정 | 시연 시나리오 |
|---|---|---|---|---|---|---|---|---|---|
| `profile-01` | 어르신 A | 84 | ✅ | ✅ | ✅ | 4 | **상** | 자녀 A | `fall` |
| `profile-02` | 어르신 B | 78 | ✅ | ❌ | ❌ | 2 | **중** | 자녀 B | `normal`, `heat` |
| `profile-03` | 어르신 C | 70 | ✅ | ❌ | ❌ | 1 | **하** | 자녀 C | `induction` |
| `profile-04` | 어르신 D | 86 | ✅ | ✅ | ✅ | 4 | **상** | 자녀 D | `critical` |

> 지병명은 저장하지 않고 `has_condition`(유무)만 둡니다.
> 보호자 데모 계정은 회원가입 없이 미리 정한 3개뿐입니다. 아이디·비밀번호는 `frontend/config/.env`의 `DEMO_ACCOUNTS`(`아이디:비밀번호:프로필ID`를 쉼표로 구분)에만 두고 저장소에 올리지 않습니다. 로그인하면 연결된 어르신 한 분만 보이고 어르신 선택 메뉴는 없습니다.

---

## 4. 데이터 시나리오

### 4-1. 시나리오별 데이터 (`mock_data.py` 기준, 스키마 필드 이름)

```python
OFF = {"air_conditioner": "off", "induction": "off",
       "induction_minutes": None, "induction_temperature": None}

def vital(hr, sbp, temp, spo2):
    return {"heart_rate": hr, "systolic_bp": sbp, "temperature_c": temp, "spo2": spo2}

def room(temp, humidity):
    return {"temperature_c": temp, "humidity_percent": humidity}

SCENARIOS = {
  "normal":    {"vital": vital(72, 125, 36.5, 98),  "indoor_environment": room(24, 50),
                "devices": OFF, "cctv": "assets/cctv/normal.png"},
  "heat":      {"vital": vital(105, 140, 37.8, 96), "indoor_environment": room(33, 75),
                "devices": OFF, "cctv": "assets/cctv/normal.png"},
  "induction": {"vital": vital(80, 130, 36.6, 97),  "indoor_environment": room(26, 55),
                "devices": {"air_conditioner": "off", "induction": "on",
                            "induction_minutes": 120, "induction_temperature": 300},
                "cctv": "assets/cctv/kitchen_empty.png"},
  "fall":      {"vital": vital(118, 120, 36.4, 96), "indoor_environment": room(25, 50),
                "devices": OFF, "cctv": "assets/cctv/fall.png"},
  "critical":  {"vital": vital(140, 85, 36.0, 88),  "indoor_environment": room(25, 50),
                "devices": OFF, "cctv": "assets/cctv/lying.png"},
}
```

### 4-2. 바이탈 점수 계산

| 시나리오 | 심박 | 혈압 | 체온 | SpO2 | 3점 개수 | 합계 |
|---|---|---|---|---|---|---|
| `normal` | 72 → 0 | 125 → 0 | 36.5 → 0 | 98 → 0 | 0 | 0 |
| `heat` | 105 → **1** | 140 → 0 | 37.8 → 0 | 96 → 0 | 0 | 1 |
| `induction` | 80 → 0 | 130 → 0 | 36.6 → 0 | 97 → 0 | 0 | 0 |
| `fall` | 118 → **2** | 120 → 0 | 36.4 → 0 | 96 → 0 | 0 | 2 |
| `critical` | 140 → **3** | 85 → **3** | 36.0 → **1** | 88 → **3** | **3** | **10** |

### 4-3. CCTV 이미지와 기대 분석 결과

| 이미지 | 장면 | `person_visible` | `posture` | `fall_suspected` |
|---|---|---|---|---|
| `normal.png` | 거실에 어르신이 앉아 있음 | true | sitting | false |
| `kitchen_empty.png` | 주방에 사람 없음, 인덕션 켜져 있음 | false | none | false |
| `fall.png` | 거실 바닥에 쓰러져 있음 | true | fallen | **true** |
| `lying.png` | 침대에서 자는 모습 (아픈 것이 아니라 잠든 상태) | true | lying | false |

> `lying`은 그것만으로는 낙상으로 보지 않습니다 (해든 규칙 D3). `fall`과 `lying` 사진은 비전 모델이 확실히 구분할 수 있게 차이를 크게 둡니다.

---

## 5. 시나리오별 기대 결과

| 시나리오 | 프로필 (취약도) | 축별 단계 (fall / cardio / resp / env) | 판정 근거 (`reasons`) | 최종 위험도 | `fall_state` | `auto_119` | 조치안 |
|---|---|---|---|---|---|---|---|
| `normal` | `profile-02` (중) | 정상 / 정상 / 정상 / 정상 | 이상 없음 | **정상** → 종료 | none | — | 없음 |
| `heat` | `profile-02` (중) | 정상 / 주의 / 정상 / **경고** | 실내 온도 극한 + 심박·혈압 변화 | **경고** | none | — | 에어컨 냉방 ✅ / 보호자 알림(승인 요청) |
| `induction` | `profile-03` (하) | 정상 / 정상 / 정상 / 주의 | 사람 없는 곳에서 인덕션 오래 켜짐 | **주의** | none | — | 인덕션 끄기 ✅ / 보호자 알림(승인 요청) |
| `fall` | `profile-01` (상) | **위급** / 주의 / 정상 / 정상 | CCTV 쓰러짐 의심 + 심박·혈압 변화 | **위급** | confirmed | — | 119 호출 ✅ / 병원 정보 / 보호자 알림(승인 요청) |
| `critical` | `profile-04` (상) | 정상 / 경고 / 경고 / 주의 + **위험 범위 3개** | 심박·혈압 위험 범위 + 산소포화도 위험 범위 + 체온 변화 | **위급** (위험 범위 2개 이상) | none | **VITAL_SEVERE** | **119 자동 연결** / 병원 정보 / 보호자 알림(긴급 알림) |

- 시나리오마다 CCTV 사진 속 인물의 보호자 계정으로 시연합니다 (3장). `normal`은 어르신 B(중)라 "정상은 올리지 않는다" 규칙은 시연이 아니라 8장 테스트(`normal` + `profile-01`)로 확인합니다.
- 다섯 시나리오로 위험도 4단계(정상·주의·경고·위급)가 모두 화면에 나옵니다.
- `fall`은 바이탈만 보면 "주의"지만, **CCTV 분석 결과 때문에 위급**이 됩니다.
- `critical`은 보호자 승인 없이 119가 연결되는 **유일한 시나리오**입니다. `/care/run` 응답이 바로 `status: "done"`, `decided_by: "auto"`로 옵니다.
- 보호자 알림과 병원 정보는 승인 없이 처리합니다. 기기 제어와 (자동이 아닌) 119만 승인이 필요합니다.
- 에어컨 목표 온도는 시연하는 달 기준입니다 (10월이면 냉방 26℃).

---

## 6. 장애 주입 (시연 필수)

장애 주입은 데이터 시나리오가 아니라, `POST /care/run` 요청의 `fault` 필드로 시나리오에 얹어 실행합니다. 4종 모두 시연에서 보여주고 README 14장 시험 기록표에 결과를 남깁니다.

```json
{ "profile_id": "profile-02", "scenario": "heat", "fault": ["iot"] }
```

| ID | 장애 | 조합 | 기대 동작 |
|---|---|---|---|
| DR-VITAL-01 | `vital` | `heat` + `profile-02` | 3회 재시도 실패 → 캐시 사용(`source: "cache"`) → "n분 전 측정값"으로 정상 진행 |
| DR-IOT-01 | `iot` | `heat` + `profile-02` | 에어컨 냉방 승인 → 3회 재시도 실패 → **FAIL** (`ActionResult.status: "failed"`) → 보호자에게 "직접 조치 필요" |
| DR-VISION-01 | `vision` | `critical` + `profile-01` | CCTV 2회 재시도 실패 → "영상 판단 불가"(`cctv.status: "failed"`) → 바이탈만으로 **위급** + 119 자동 연결 + 원본 캡처 확인 요청 |
| DR-LLM-01 | `llm` | `fall` + `profile-01` | 1회 재요청 실패 → 고정 템플릿 문구로 안내 (위험도·조치는 코드라 정상 진행) |

> `vital` 장애 전에는 같은 프로필로 `heat`를 장애 없이 한 번 실행해 캐시를 채워 둡니다. (7장 시연 순서대로 하면 2번에서 자동으로 채워집니다.)

---

## 7. 시연 순서

| 순서 | 로그인 | 실행 | 보여줄 장면 |
|---|---|---|---|
| 1 | 자녀 B | `normal` | 모두 정상 → Handoff Guard에서 "이상 없음"으로 종료 |
| 2 | 자녀 B | `heat` | 실내 극한 고온(33℃) + 심박 변화 → 경고 → 에어컨 냉방 승인 → 에어컨 켜짐 |
| 3 | 자녀 C | `induction` | CCTV 주방 비어 있음 + 인덕션 120분·300℃ → 주의 → 인덕션 끄기 승인 |
| 4 | 자녀 A | `fall` | **CCTV 캡처 → LLM 분석(쓰러짐 의심) → 위급 → 캡처와 함께 승인 요청 → 119 호출(mock)** |
| 5 | 자녀 D | `critical` | 바이탈 위험 범위 3개(점수 합 10) → 위급 → **승인 없이 119 자동 연결** → 보호자 긴급 알림 |
| 6 | 자녀 B | `heat` + `vital` 장애 | 바이탈 재시도 3회 → 캐시 사용 → "n분 전 측정값"으로 정상 진행 (2번에서 캐시가 채워짐) |
| 7 | 자녀 B | `heat` + `iot` 장애 | 에어컨 제어 재시도 3회 → FAIL → 보호자에게 "직접 조치 필요" |
| 8 | 자녀 D | `critical` + `vision` 장애 | 영상 판단 불가 → 바이탈만으로 위급 → 119 자동 연결 + 원본 확인 요청 |
| 9 | 자녀 A | `fall` + `llm` 장애 | 안내문 생성 실패 → 재요청 1회 → 템플릿 문구로 안내 |

> 영상은 계정별로 묶어 찍고 편집에서 순서를 맞춰도 됩니다: 자녀 A(4·9) → 자녀 B(1·2·6·7) → 자녀 C(3) → 자녀 D(5·8). 6번은 같은 계정으로 2번을 먼저 실행해야 캐시가 채워집니다.
> 5번(자녀 D)은 CCTV에는 평범하게 자는 모습만 보이지만 바이탈이 매우 위험한 장면입니다. "카메라로는 모르는 위급을 바이탈이 잡아낸다"를 보여 줍니다.

> 1~5번은 데이터 시나리오, 6~9번은 같은 시나리오에 장애를 얹은 AutoHealing 시연입니다. 화면 아래 AutoHealing 로그에서 재시도·폴백·FAIL 과정이 보이게 합니다.
> 4번(승인 후 119)과 5번(자동 119)을 이어서 보여주면 "승인이 원칙, 바이탈이 매우 위험할 때만 예외"라는 차이가 드러납니다.

---

## 8. 테스트 케이스 (위험도 규칙)

해든님 `test_risk_rules.py`에서 그대로 쓸 수 있는 기대값입니다.

| 입력 | 기대 위험도 | `auto_119` |
|---|---|---|
| `normal` + `profile-01` | 정상 | — |
| `heat` + `profile-02` | 경고 | — |
| `heat` + `profile-01` | 위급 (경고 → 보정) | — (3점 항목 없음) |
| `induction` + `profile-03` | 주의 | — |
| `induction` + `profile-01` | 경고 (주의 → 보정) | — |
| `induction`에서 `induction_minutes: 30`, `induction_temperature: 300` + `profile-03` | 주의 (과열만으로도 방치) | — |
| `fall` + `profile-03` | 위급 (CCTV) | — |
| `fall` + CCTV 분석 실패 + `profile-03` | 주의 (심박 변화만) | — |
| `critical` + `profile-01` | 위급 | VITAL_SEVERE |
| `critical` + CCTV 분석 실패 + `profile-01` | 위급 | VITAL_SEVERE |
| `critical` + 바이탈 캐시(`source: "cache"`) + `profile-01` | 위급 | — (승인 요청으로 전환) |

---

## 9. 스키마·코드에 반영할 것 (담당자 확인 필요)

### 반영 완료 (10/8)

| 담당 | 파일 | 바꾼 내용 |
|---|---|---|
| 지혜 | `schemas.py` | `Scenario`에 `"critical"` 추가 |
| 지혜 | `schemas.py` | `DeviceStatus`에 `induction_temperature: int \| None = None` 추가 |
| 지혜 | `schemas.py` | `DataSource`에 `"live"` 추가 |
| 지혜 | `schemas.py` | `VitalData.diastolic_bp` 삭제 |
| 지혜 | `schemas.py` | `FallEvent`, `Signs` 클래스와 `CareStatusResult.fall_event`, `signs` 삭제 |
| 지혜 | `schemas.py` | `Auto119Reason`을 `"VITAL_SEVERE"`만 남김 |
| 지혜 | `schemas.py` | `EmergencyResult.axes` 타입을 `dict[RiskAxis, RiskLevel]`로 |
| 상옥 | `db/schema.sql`, `db/vital_readings.py` | `vital_readings` 테이블과 저장 필드에서 `diastolic_bp` 삭제 |
| 상옥 | `tests/test_vital_readings.py`, `tests/test_healing.py` | 테스트 데이터에서 `diastolic_bp` 삭제 |

### 남은 일

| 담당 | 파일 | 바꿀 내용 |
|---|---|---|
| 지혜 | `schemas.py` | 119 자동 연결 시 `/care/run` 응답(`CareRunResponse`)에 실행 결과(`actions`)와 `guardian_message`를 담을 자리 필요 |
| 해든 | `rules/risk.py` | 입력 키를 스키마 이름으로 (`vitals`→`vital`, `hr`→`heart_rate`, `env`→`indoor_environment` …) |
| 해든 | `rules/risk.py` | 인덕션을 `induction_minutes`, `induction_temperature` 숫자로 읽고, 과열(≥250℃) 조건 추가 |
| 해든 | `rules/risk.py` | `fall_event`·`signs` 입력과 `ELDER_NO_RESPONSE`, 스피커 확인(`speaker_check`) 제거 |
| ~~해든·지혜~~ | ~~`rules/risk.py`~~ | ~~119 승인 대기 60초 초과 시 자동 연결 유지 여부~~ → **쓰지 않기로 결정 (10/12)**. `ENABLE_TIMEOUT_119 = False` |
| 두나 | `mock_data.py` | 4-1의 데이터로 교체 |

> **결정 (10/12):** 승인 없이 119에 연결하는 경우는 **바이탈 매우 위험(`VITAL_SEVERE`)일 때 하나뿐**입니다. "119 승인 요청에 60초 동안 보호자 응답이 없으면 자동 연결"은 쓰지 않습니다 (`risk.py`의 `ENABLE_TIMEOUT_119 = False`). 시간이 지나도 119를 걸지 않고 보호자에게 다시 알림만 보냅니다.
