# 시연 시나리오 확정안

> 이 문서는 데이터 시나리오, 테스트 프로필, 시나리오별 기대 결과를 정리한 **팀 공용 기준**입니다.
> `mock_data.py`(두나), 위험도 규칙과 테스트(해든), Guard(지혜), 장애 주입(상옥), 화면(수언)이 이 문서를 기준으로 개발합니다.
> 확정되면 README 8장·9장·14장에 반영합니다.
>
> ⚠️ 모든 수치는 **시연용 가상값**이며, 위험 범위는 **의학적 기준이 아닌 시연용 예시 규칙**입니다.

---

## 1. 결정 사항

| # | 항목 | 결정 |
|---|---|---|
| 1 | 데이터 시나리오 | `normal`, `heat`, `induction`, `fall`, `critical` **5개** |
| 2 | 장애 주입 | 데이터 시나리오와 별도로 요청의 `fault` 필드로 **시나리오에 얹어서** 실행한다. 4종(`vital`, `iot`, `vision`, `llm`) 모두 **시연 필수** |
| 3 | 취약도 보정 | 취약도 "상"이면 한 단계 올리되, **정상은 올리지 않는다** (최대 "위급") |
| 4 | 프로필 | 시나리오별로 사용할 테스트 프로필을 정해 둔다 (3장) |
| 5 | `fall` 바이탈 | 위험 범위인 바이탈을 **1개만** 둔다. 위급 판정의 근거가 CCTV가 되도록 |
| 6 | 기기 상태 형식 | 문자열(`"on(2h)"`) 대신 구조로 받는다. 예: `{"state": "on", "minutes": 120, "temperature": 300}` |
| 7 | 인덕션 | 위 형식으로 장시간 켜짐·과열이 들어오면 **인덕션 끄기** 조치안을 만들고, 보호자 승인 후 끈다 |

---

## 2. 위험 범위 기준 (시연용)

| 항목 | 위험 범위 |
|---|---|
| 심박 (`hr`) | < 50 또는 > 110 |
| 수축기 혈압 (`sbp`) | < 90 또는 > 160 |
| 체온 (`temp`) | < 35.5 또는 > 37.5 |
| 산소포화도 (`spo2`) | < 94 |
| 실내 온도 | ≥ 30 (고온) 또는 ≤ 16 (저온) |
| 인덕션 장시간 켜짐 | `state == "on"` 이고 `minutes ≥ 60` |
| 인덕션 과열 | `state == "on"` 이고 `temperature ≥ 250` |

### 판정 순서

| 우선순위 | 조건 | 위험도 |
|---|---|---|
| 1 | CCTV 쓰러짐 의심, 또는 바이탈 2개 이상 위험 범위 | 위급 |
| 2 | 바이탈 1개 위험 범위, 또는 실내 고온·저온 + 바이탈 변화 | 경고 |
| 3 | 실내 환경 이상만 있음, 또는 사람 없음 + 인덕션 장시간 켜짐·과열 | 주의 |
| 4 | 이상 없음 | 정상 (Handoff Guard에서 종료) |

**취약도 보정:** 위 결과가 **주의·경고**이고 취약도가 "상"이면 한 단계 올린다. **정상은 그대로 둔다.**

```python
LEVELS = ["정상", "주의", "경고", "위급"]

def adjust(level: str, vulnerability: str) -> str:
    if level == "정상" or vulnerability != "상":
        return level
    return LEVELS[min(LEVELS.index(level) + 1, len(LEVELS) - 1)]
```

---

## 3. 테스트 프로필 (가상 인물)

취약도 계산식은 README 4장 `vulnerability()`를 따릅니다. (나이 ≥ 75, 혼자 거주, 지병 있음, 거동 불편 각 1점 → 3점 이상 "상", 2점 "중", 그 외 "하")

| ID | 이름 (가상) | 나이 | 혼자 거주 | 지병 | 거동 불편 | 점수 | 취약도 |
|---|---|---|---|---|---|---|---|
| `profile-01` | 어르신 A | 84 | ✅ | ✅ | ✅ | 4 | **상** |
| `profile-02` | 어르신 B | 78 | ✅ | ❌ | ❌ | 2 | **중** |
| `profile-03` | 어르신 C | 70 | ✅ | ❌ | ❌ | 1 | **하** |

> 지병명은 저장하지 않고 `has_condition`(유무)만 둡니다.

---

## 4. 데이터 시나리오

### 4-1. 시나리오별 데이터 (`mock_data.py` 기준)

```python
SCENARIOS = {
  "normal": {
    "vitals":  {"hr": 72, "sbp": 125, "temp": 36.5, "spo2": 98},
    "env":     {"temp": 24, "humidity": 50},
    "devices": {"aircon": {"state": "off"},
                "induction": {"state": "off", "minutes": 0, "temperature": 0}},
    "cctv":    "assets/cctv/normal.jpg",
  },
  "heat": {
    "vitals":  {"hr": 105, "sbp": 140, "temp": 37.8, "spo2": 96},
    "env":     {"temp": 33, "humidity": 75},
    "devices": {"aircon": {"state": "off"},
                "induction": {"state": "off", "minutes": 0, "temperature": 0}},
    "cctv":    "assets/cctv/normal.jpg",
  },
  "induction": {
    "vitals":  {"hr": 80, "sbp": 130, "temp": 36.6, "spo2": 97},
    "env":     {"temp": 26, "humidity": 55},
    "devices": {"aircon": {"state": "off"},
                "induction": {"state": "on", "minutes": 120, "temperature": 300}},
    "cctv":    "assets/cctv/kitchen_empty.jpg",
  },
  "fall": {
    "vitals":  {"hr": 118, "sbp": 120, "temp": 36.4, "spo2": 95},   # 심박만 위험 범위
    "env":     {"temp": 25, "humidity": 50},
    "devices": {"aircon": {"state": "off"},
                "induction": {"state": "off", "minutes": 0, "temperature": 0}},
    "cctv":    "assets/cctv/fall.jpg",
  },
  "critical": {
    "vitals":  {"hr": 140, "sbp": 85, "temp": 36.0, "spo2": 88},
    "env":     {"temp": 25, "humidity": 50},
    "devices": {"aircon": {"state": "off"},
                "induction": {"state": "off", "minutes": 0, "temperature": 0}},
    "cctv":    "assets/cctv/lying.jpg",
  },
}
```

### 4-2. CCTV 이미지와 기대 분석 결과

| 이미지 | 장면 | `person_visible` | `posture` | `fall_suspected` |
|---|---|---|---|---|
| `normal.jpg` | 거실에 어르신이 앉아 있음 | true | sitting | false |
| `kitchen_empty.jpg` | 주방에 사람 없음, 인덕션 켜져 있음 | false | none | false |
| `fall.jpg` | 거실 바닥에 쓰러져 있음 | true | fallen | **true** |
| `lying.jpg` | 소파에 누워 움직임 없음 | true | lying | false |

---

## 5. 시나리오별 기대 결과

| 시나리오 | 프로필 (취약도) | 위험 범위인 바이탈 | 실내·기기 | CCTV | 판정 근거 | 기본 위험도 | 최종 위험도 | 조치안 | 승인 |
|---|---|---|---|---|---|---|---|---|---|
| `normal` | `profile-01` (상) | 없음 | 정상 | 앉아 있음 | 이상 없음 | 정상 | **정상** (보정 안 함) | 없음 | — |
| `heat` | `profile-02` (중) | 체온 | **고온 33℃** | 앉아 있음 | 바이탈 1개 + 고온 | 경고 | **경고** | 에어컨 켜기 / 보호자 알림 / 병원 정보 | 에어컨 ✅ |
| `induction` | `profile-03` (하) | 없음 | **인덕션 120분·300℃** | 사람 없음 | 사람 없음 + 인덕션 장시간·과열 | 주의 | **주의** | 인덕션 끄기 | ✅ |
| `fall` | `profile-01` (상) | 심박 | 정상 | **쓰러짐** | CCTV 쓰러짐 의심 + 심박 상승 | 위급 | **위급** | 119 호출 / 응급실 정보 / 보호자 알림 | 119 ✅ |
| `critical` | `profile-01` (상) | 심박·혈압·SpO2 | 정상 | 누워 있음 | 바이탈 3개 위험 | 위급 | **위급** | 119 호출 / 응급실 정보 / 보호자 알림 | 119 ✅ |

- `normal`은 일부러 취약도 "상" 프로필을 써서 **정상은 올리지 않는다**는 규칙을 확인합니다.
- 다섯 시나리오로 위험도 4단계(정상·주의·경고·위급)가 모두 화면에 나옵니다.
- `fall`은 바이탈만 보면 "경고"지만, **CCTV 분석 결과 때문에 위급**이 됩니다. (시연 4번의 핵심 장면)
- 보호자 알림(`notify_guardian`)은 승인 없이 보냅니다. 기기 제어와 119 호출만 승인이 필요합니다.

---

## 6. 장애 주입 (시연 필수)

장애 주입은 데이터 시나리오가 아니라, `POST /care/run` 요청의 `fault` 필드로 시나리오에 얹어 실행합니다. 4종 모두 시연에서 보여주고 README 14장 시험 기록표에 결과를 남깁니다.

```json
{ "person": "profile-02", "scenario": "heat", "fault": ["iot"] }
```

| ID | 장애 | 조합 | 기대 동작 |
|---|---|---|---|
| DR-VITAL-01 | `vital` | `heat` + `profile-02` | 3회 재시도 실패 → 캐시 사용 → "n분 전 측정값"으로 정상 진행 |
| DR-IOT-01 | `iot` | `heat` + `profile-02` | 에어컨 켜기 승인 → 3회 재시도 실패 → **FAIL** → 보호자에게 "직접 조치 필요" |
| DR-VISION-01 | `vision` | `critical` + `profile-01` | CCTV 2회 재시도 실패 → "영상 판단 불가" → 바이탈만으로 **위급** 유지 + 원본 캡처 확인 요청 |
| DR-LLM-01 | `llm` | `fall` + `profile-01` | 1회 재요청 실패 → 고정 템플릿 문구로 안내 (위험도·조치는 정상 진행) |

> `vital` 장애 전에는 같은 프로필로 `heat`를 장애 없이 한 번 실행해 캐시를 채워 둡니다. (7장 시연 순서대로 하면 2번에서 자동으로 채워집니다.)

---

## 7. 시연 순서

| 순서 | 실행 | 보여줄 장면 |
|---|---|---|
| 1 | `normal` | 모두 정상 → Handoff Guard에서 "이상 없음"으로 종료 |
| 2 | `heat` | 고온 + 체온 상승 → 경고 → 에어컨 켜기 승인 → 에어컨 켜짐 |
| 3 | `induction` | CCTV 주방 비어 있음 + 인덕션 120분·300℃ → 주의 → 인덕션 끄기 승인 |
| 4 | `fall` | **CCTV 캡처 → LLM 분석(쓰러짐 의심) → 위급 → 캡처와 함께 승인 요청 → 119 호출(mock)** |
| 5 | `critical` | 바이탈 3개 위험 → 위급 → 119 호출 승인 |
| 6 | `heat` + `vital` 장애 | 바이탈 재시도 3회 → 캐시 사용 → "n분 전 측정값"으로 정상 진행 (2번에서 캐시가 채워짐) |
| 7 | `heat` + `iot` 장애 | 에어컨 제어 재시도 3회 → FAIL → 보호자에게 "직접 조치 필요" |
| 8 | `critical` + `vision` 장애 | 영상 판단 불가 → 바이탈 기준으로 위급 판정 + 원본 확인 요청 |
| 9 | `fall` + `llm` 장애 | 안내문 생성 실패 → 재요청 1회 → 템플릿 문구로 안내 |

> 1~5번은 데이터 시나리오, 6~9번은 같은 시나리오에 장애를 얹은 AutoHealing 시연입니다. 화면 아래 AutoHealing 로그에서 재시도·폴백·FAIL 과정이 보이게 합니다.

---

## 8. 테스트 케이스 (위험도 규칙)

해든님 `test_risk_rules.py`에서 그대로 쓸 수 있는 기대값입니다.

| 입력 | 기대 위험도 |
|---|---|
| `normal` + `profile-01` | 정상 |
| `heat` + `profile-02` | 경고 |
| `heat` + `profile-01` | 위급 (경고 → 보정) |
| `induction` + `profile-03` | 주의 |
| `induction` + `profile-01` | 경고 (주의 → 보정) |
| `fall` + `profile-03` | 위급 (CCTV) |
| `fall` + CCTV 분석 실패 + `profile-03` | 경고 (바이탈 1개) |
| `critical` + CCTV 분석 실패 + `profile-01` | 위급 (바이탈 3개) |

---

## 9. README 반영 시 바꿀 곳

| README | 바꿀 내용 |
|---|---|
| 8장 `mock_data.py` | `devices`를 구조 형식으로, `fall` 바이탈 수정 |
| 9장 위험도 판정 규칙 | 2장의 위험 범위 기준표 추가, 취약도 보정에 "정상은 제외" 명시 |
| 14장 시연 시나리오 | 7장 시연 순서로 교체 (데이터 시나리오 5개 + 장애 주입 4종, 모두 시연) |
| 6장 CareStatusResult 예시 | `devices` 형식 변경 |
