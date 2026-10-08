# 바이탈 데이터 수집 API 수정 요청

지혜님, 기존 바이탈 조회 기능에 실시간 데이터 수집 방식을 추가하고 싶어서 수정 요청드립니다.

두나가 Python 프로그램에서 가상 어르신의 바이탈 데이터를 **15초마다 HTTP로 전송**할 예정입니다. 기존 `VitalData`와 `/care/run` 응답 구조는 유지하고, 백엔드에 바이탈 데이터를 수신하는 API를 추가하는 방향을 제안합니다.

## 1. 신규 API 추가 요청

```http
POST /vitals/readings
```

요청 예시:

```json
{
  "profile_id": "profile-01",
  "heart_rate": 82,
  "systolic_bp": 128,
  "diastolic_bp": 78,
  "temperature_c": 36.7,
  "spo2": 97,
  "measured_at": "2026-10-08T15:30:00+09:00"
}
```

## 2. 요청 스키마 추가

기존 `VitalData` 필드명을 그대로 사용하고, 저장 대상을 구분하기 위한 `profile_id`를 추가합니다.

```python
class VitalReadingCreate(BaseModel):
    profile_id: str
    heart_rate: int | None = None
    systolic_bp: int | None = None
    diastolic_bp: int | None = None
    temperature_c: float | None = None
    spo2: int | None = None
    measured_at: str
```

저장 성공 응답은 우선 다음과 같이 제안합니다.

```json
{
  "status": "stored",
  "profile_id": "profile-01",
  "measured_at": "2026-10-08T15:30:00+09:00"
}
```

## 3. 기존 Vital Agent 수정 요청

Vital Agent의 바이탈 조회 순서를 다음과 같이 변경하는 것을 제안합니다.

1. 해당 `profile_id`의 최신 DB 바이탈 데이터를 조회합니다.
2. 최근 데이터가 있으면 해당 데이터를 사용합니다.
3. 최근 데이터가 없거나 DB 조회에 실패하면 기존 시나리오 Mock 데이터를 사용합니다.
4. 최종 반환 형식은 기존 `VitalData`와 동일하게 유지합니다.

최근 데이터의 기준은 우선 **30초 이내**로 제안합니다.

## 4. 기존 API 계약 유지

다음 구조는 변경하지 않습니다.

- `CareRunRequest`
- `CareStatusResult.vital`
- `CareRunResponse`
- 기존 `VitalData` 필드
- `/care/run` 응답 형식

따라서 프런트엔드에서도 별도의 응답 구조 변경 없이 기존 방식으로 바이탈 정보를 표시할 수 있습니다.

## 5. `source` 값 확인 요청

두나가 보내는 데이터는 Python에서 생성하는 가상 데이터이므로 현재는 `source="mock"`으로 처리해도 됩니다.

나중에 실제 센서를 연결한다면 다음과 같이 `live` 값을 추가하는 스키마 확장을 검토할 수 있습니다.

```python
source: Literal["mock", "cache", "mixed", "live"]
```

실제 센서를 연결하기 전에는 기존 `source` 계약을 변경하지 않는 것을 권장합니다.

## 6. 역할 분담 제안

| 담당자 | 작업 |
|---|---|
| 두나 | 15초마다 바이탈 데이터를 HTTP로 전송하는 Python 프로그램 구현 |
| 지혜 | `POST /vitals/readings` API, 요청·응답 스키마, Vital Agent 연결 |
| 상옥 | 바이탈 DB 테이블, 저장·조회 함수, DB 장애 복구 |

DB 관련 작업은 상옥 담당과 겹칠 수 있으므로, 지혜님은 API와 스키마를 추가하고 실제 저장·조회 함수의 인터페이스는 상옥님과 맞추는 방식으로 진행하면 좋겠습니다.

## 7. 확인이 필요한 사항

- `POST /vitals/readings` 경로를 그대로 사용할지
- 최신 데이터 판정 기준을 30초로 사용할지
- DB 저장·조회 함수의 이름과 반환 형식
- DB 장애 시 기존 Mock 데이터를 사용하는 위치를 Vital Agent와 AutoHealing 중 어디로 둘지

위 구조로 진행해도 괜찮은지 확인 부탁드립니다.
