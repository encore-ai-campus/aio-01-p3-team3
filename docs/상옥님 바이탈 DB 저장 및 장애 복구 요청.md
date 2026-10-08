# 바이탈 데이터 DB 저장 및 장애 복구 요청

상옥님, 기존 AutoHealing과 SQLite 구조에 바이탈 데이터 수집·저장 기능을 추가하고 싶어서 협업 요청드립니다.

두나가 Python 프로그램에서 가상 어르신의 바이탈 데이터를 **15초마다 HTTP로 전송**하고, 지혜님이 백엔드의 `POST /vitals/readings` 수집 API와 스키마를 담당하는 구조를 제안했습니다. 상옥님께는 수신된 데이터를 저장·조회하는 SQLite 기능과 장애 복구 연결을 부탁드리고 싶습니다.

## 1. 전체 흐름

```text
두나의 Python 바이탈 전송기
    ↓ 15초마다 HTTP POST
지혜님의 POST /vitals/readings API
    ↓ 검증된 VitalReadingCreate 전달
상옥님의 SQLite 저장 함수
    ↓
Vital Agent가 최신 측정값 조회
    ↓ 실패 시 AutoHealing 재시도 및 캐시 폴백
/care/run 응답
```

## 2. 바이탈 저장 테이블 추가 요청

15초마다 수신되는 측정값을 누적하기 위해 기존 `cache`, `run_logs`, `profiles` 테이블과 별도로 `vital_readings` 테이블을 추가하는 방식을 제안합니다.

```sql
CREATE TABLE IF NOT EXISTS vital_readings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_id TEXT NOT NULL,
    heart_rate INTEGER,
    systolic_bp INTEGER,
    diastolic_bp INTEGER,
    temperature_c REAL,
    spo2 INTEGER,
    measured_at TEXT NOT NULL,
    received_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_vital_readings_profile_measured
ON vital_readings(profile_id, measured_at DESC);
```

- `measured_at`: 전송 프로그램이 측정한 시각
- `received_at`: 백엔드가 DB에 저장한 시각
- 시각 값은 ISO 8601 형식 사용
- `profile_id`는 기존 테스트 프로필과 동일한 값을 사용

프로필 외래 키 적용 여부는 기존 `profiles` 테이블의 생성 순서와 테스트 방식에 맞춰 결정하면 좋겠습니다.

## 3. 저장·조회 함수 인터페이스 제안

지혜님의 수집 API와 Vital Agent가 사용할 수 있도록 다음과 같은 인터페이스를 제안합니다.

```python
def save_vital_reading(reading: dict) -> int:
    """검증된 바이탈 데이터를 저장하고 생성된 ID를 반환한다."""


def get_latest_vital_reading(
    profile_id: str,
    max_age_seconds: int = 30,
) -> dict | None:
    """지정 시간 이내의 최신 바이탈 데이터를 반환한다."""
```

구체적인 함수명과 동기·비동기 방식은 현재 DB 모듈 구조에 맞춰 조정해도 됩니다. 다만 지혜님과 다음 계약은 통일이 필요합니다.

- 저장 함수의 입력 형식
- 저장 성공 시 반환값
- 최근 데이터가 없을 때 `None`을 반환할지 예외를 발생시킬지
- DB 오류가 발생했을 때 사용할 예외 형식

## 4. 최신 데이터 조회 기준

Vital Agent는 다음 순서로 데이터를 사용하도록 제안합니다.

1. `profile_id`로 가장 최근 측정값을 조회합니다.
2. 현재 시각을 기준으로 **30초 이내**이면 최신 데이터로 사용합니다.
3. 데이터가 없거나 30초보다 오래됐으면 최신 데이터 없음으로 처리합니다.
4. 조회 실패는 숨기지 않고 AutoHealing이 처리할 수 있도록 예외로 전달합니다.

30초는 15초 전송 주기에서 한 번의 전송 누락까지 허용하기 위한 제안값이며, 팀 합의에 따라 변경할 수 있습니다.

## 5. 기존 캐시와의 관계

`vital_readings`와 기존 `cache` 테이블은 용도를 구분하는 것이 좋습니다.

| 저장소 | 용도 |
|---|---|
| `vital_readings` | 15초마다 수신한 바이탈 측정 이력 저장 |
| `cache` | MCP 바이탈 조회가 실패했을 때 사용할 마지막 정상 결과 저장 |

정상적으로 바이탈 데이터를 조회한 경우 기존 캐시 키 규칙에 맞춰 마지막 정상 결과를 `cache`에도 저장하면, `vital` 장애 주입 시 기존 AutoHealing 흐름을 그대로 사용할 수 있습니다.

캐시 키 예시:

```text
vitals:profile-01
```

기존 프로젝트에 이미 다른 키 규칙이 있다면 그 규칙을 우선합니다.

## 6. AutoHealing 연결 요청

기존 `with_healing()` 흐름을 유지하면서 바이탈 조회를 다음처럼 처리하는 방식을 제안합니다.

```text
최신 바이탈 조회
    ↓ 실패
최대 3회 재시도
    ↓ 계속 실패
SQLite cache의 마지막 정상 바이탈 사용
    ↓ 캐시도 없음
기존 시나리오 Mock 데이터 사용 또는 최종 실패
```

다음 사항을 로그로 남기면 프런트엔드에서 복구 과정을 보여주기 좋습니다.

- 실행 ID
- 단계명 `vital`
- 시도 횟수
- `success`, `retry`, `fallback`, `fail` 상태
- 오류 메시지
- `cache` 또는 `mock` 복구 방식
- 복구 소요 시간

### 장애 범위 구분

- `vital` 장애 주입이 MCP 조회 실패를 의미한다면 SQLite 캐시 폴백이 가능합니다.
- SQLite 자체가 열리지 않는 장애라면 같은 SQLite의 `cache`도 사용할 수 없습니다.
- 실제 DB 장애까지 처리하려면 기존 시나리오 Mock 데이터로 대체할지 최종 실패로 처리할지 지혜님과 합의가 필요합니다.

## 7. `source` 값 처리

두나가 전송하는 값은 Python에서 생성한 가상 데이터이므로 현재는 `source="mock"`으로 처리하는 것이 적절합니다.

AutoHealing이 마지막 정상 캐시를 사용하면 `source="cache"`로 표시합니다. 실제 센서를 연결하기 전에는 지혜님의 기존 `source` 스키마를 임의로 변경하지 않는 것을 권장합니다.

실제 센서를 연결할 때는 지혜님과 협의하여 다음과 같은 확장을 검토할 수 있습니다.

```python
source: Literal["mock", "cache", "mixed", "live"]
```

## 8. 역할 분담 제안

| 담당자 | 작업 |
|---|---|
| 두나 | 15초마다 바이탈 데이터를 HTTP로 전송하는 Python 프로그램 구현 |
| 지혜 | `POST /vitals/readings` API, 요청·응답 스키마, Vital Agent 연결 |
| 상옥 | `vital_readings` 테이블, 저장·최신값 조회, 캐시·재시도·장애 로그 연결 |

## 9. 확인이 필요한 사항

- `vital_readings` 테이블을 새로 추가하는 방식이 적절한지
- 저장·조회 함수명과 입력·반환 형식
- 최신 데이터 판정 기준을 30초로 사용할지
- 정상 조회 결과를 기존 `cache` 테이블에 저장하는 위치
- DB 자체 장애 시 Mock fallback과 최종 실패 중 어떤 정책을 사용할지
- 오래된 바이탈 이력의 보관 기간과 정리 방식이 필요한지

위 구조로 진행해도 괜찮은지 확인 부탁드립니다.
