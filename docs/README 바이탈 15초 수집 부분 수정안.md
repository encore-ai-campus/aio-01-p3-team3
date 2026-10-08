# README 바이탈 15초 수집 부분 수정안

이 문서는 README 전체를 다시 작성하지 않고, **Python 바이탈 전송기 → HTTP 수집 API → SQLite 저장 → Vital Agent 조회 → AutoHealing** 흐름만 부분적으로 반영하기 위한 수정안이다.

아직 구현과 팀 합의가 완료되지 않았으므로 README에는 우선 **제안 또는 예정 구조**로 반영하고, 통합 테스트가 끝난 뒤 완료 표현으로 변경한다.

## 1. 이번 수정의 범위

다음 내용만 README에 추가하거나 수정한다.

- 두나의 Python 프로그램이 가상 바이탈 데이터를 15초마다 전송
- 지혜의 `POST /vitals/readings` 수집 API
- 상옥의 `vital_readings` SQLite 테이블 및 저장·조회 함수
- 최근 30초 이내 측정값 우선 사용
- 조회 실패 시 AutoHealing 재시도와 기존 캐시 폴백
- 기존 `/care/run`, `/care/approve`, `VitalData` 응답 계약 유지

실제 의료 센서를 연결하는 것은 아니다. 전송 과정은 실제 HTTP를 사용하지만, 전송되는 값은 시연용 가상 데이터이므로 `source="mock"`으로 처리한다.

## 2. README 수정 위치 요약

| README 위치 | 수정 방식 | 반영 내용 |
|---|---|---|
| `2. 시스템 아키텍처` | 다이어그램·설명 수정 | Python 바이탈 전송기와 `/vitals/readings` 추가 |
| `3. 에이전트 흐름` | 표 일부 수정 | Vital Agent의 최신 DB 측정값 조회 흐름 추가 |
| `4. 에이전트별 역할` | Vital Agent 행 수정 | 최근 데이터 우선 사용 및 오래된 데이터 처리 |
| `6. Handoff 데이터 형식` | 바이탈 예시 교체 | 지혜의 `VitalData` 필드명과 `source="mock"` 사용 |
| `7. AutoHealing` | 설명·SQLite DDL 추가 | `vital_readings`와 `cache` 역할 구분 |
| `9. 데이터와 MCP 도구` | 도구 설명 수정 | DB 우선 조회와 MCP Mock fallback 관계 명시 |
| `12. 팀 구성과 역할` | 담당 내용 추가 | 두나·지혜·상옥의 신규 작업 분담 |
| 실행·환경변수 절 | 선택 추가 | 전송 간격, 최신 데이터 기준, 수집 API 주소 |

## 3. `2. 시스템 아키텍처` 수정안

기존 아키텍처 그림의 앞부분에 Python 바이탈 전송기를 추가한다.

```text
Python 바이탈 전송기
  가상 어르신 5명
  15초마다 전송
         │ HTTP POST /vitals/readings
         ▼
frontend 컨테이너          backend 컨테이너                     mcp 컨테이너
┌──────────────┐        ┌───────────────────────┐          ┌────────────────────┐
│  Streamlit   │──HTTP─▶│  FastAPI              │──MCP────▶│  MCP 서버            │
│  보호자 대시보드 │        │  오케스트레이터            │          │  바이탈·IoT·CCTV·     │
│  승인 버튼     │◀───────│  + 바이탈 수집 API         │          │  병원·알림 도구        │
└──────────────┘        │  + AutoHealing        │          └────────────────────┘
                        │        │
                        │        ▼
                        │  [SQLite] (볼륨)
                        │  바이탈 이력·캐시·로그·프로필
                        └────────────────────────
```

기존 설명 아래에 다음 문장을 추가한다.

```markdown
- 실제 의료 센서를 연결하지 않고, Python 전송기가 가상 바이탈 데이터를 15초마다 `POST /vitals/readings`로 전송합니다.
- HTTP 전송과 DB 저장 흐름은 실제로 동작하지만 데이터 자체는 시연용이므로 `source="mock"`으로 표시합니다.
- SQLite의 `vital_readings`는 수집 이력을 저장하고, 기존 `cache`는 조회 실패 시 마지막 정상 결과를 제공하는 복구 수단으로 사용합니다.
```

구성요소 표의 백엔드와 DB 행은 다음처럼 수정한다.

```markdown
| 백엔드 | FastAPI | 오케스트레이터, 승인 대기 관리, `/care/run`, `/care/approve`, `/vitals/readings`, `/health`, `/logs` |
| DB | SQLite | 바이탈 측정 이력, 캐시, 실행 로그, 테스트 프로필 |
```

## 4. `3. 에이전트 흐름` 수정안

기존 `Vital / IoT Agent` 행을 둘로 나누는 것을 권장한다.

```markdown
| Vital Agent | SQLite에서 최근 30초 이내 바이탈 데이터를 우선 조회하고, 사용할 수 없으면 합의된 Mock/fallback 흐름을 실행 |
| IoT Agent | MCP 도구를 통해 실내 환경·기기 상태·CCTV 데이터를 조회하고 CCTV 이미지를 분석 |
```

### 반드시 팀에서 확정할 구조

SQLite는 backend만 사용하므로, `POST /vitals/readings`로 저장한 값을 Vital Agent가 사용하려면 다음 구조가 가장 자연스럽다.

```text
Vital Agent
  1. backend SQLite의 최신 vital_readings 조회
  2. 최근 데이터가 없으면 MCP get_vitals(profile_id, scenario) 사용
  3. 조회 오류는 AutoHealing으로 전달
```

이 구조를 채택하면 기존의 “Vital Agent는 항상 MCP `get_vitals`만 호출한다”는 설명을 **DB 우선, MCP fallback**으로 수정해야 한다.

## 5. `4. 에이전트별 역할` 수정안

Vital Agent 행을 다음 내용으로 교체한다.

```markdown
| **Vital Agent** | 최근 바이탈 조회, 최신성 확인, Mock fallback 요청 | 의료 진단 금지, 실패 예외 숨김 금지 | 심박·혈압·체온·산소포화도, 측정 시각, 데이터 출처 |
```

추가 설명:

```markdown
Vital Agent는 해당 프로필의 가장 최근 측정값이 30초 이내이면 이를 사용합니다. 데이터가 없거나 오래됐으면 MCP의 시나리오 Mock 데이터를 사용하며, 조회 과정의 오류는 AutoHealing이 재시도와 캐시 폴백을 수행할 수 있도록 그대로 전달합니다.
```

## 6. 바이탈 수집 API 설명 추가안

`에이전트별 역할` 뒤 또는 `Handoff 데이터 형식` 앞에 다음 절을 추가한다.

### 바이탈 데이터 수집

두나의 Python 전송기는 가상 어르신의 바이탈 데이터를 15초마다 백엔드로 전송합니다.

`POST /vitals/readings`

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

성공 응답 예시:

```json
{
  "status": "stored",
  "profile_id": "profile-01",
  "measured_at": "2026-10-08T15:30:00+09:00"
}
```

기존 `VitalData`, `CareStatusResult.vital`, `CareRunResponse` 구조는 변경하지 않습니다.

## 7. `6. Handoff 데이터 형식` 수정안

기존 README의 `vitals.hr`, `vitals.sbp`, `vitals.temp` 축약형은 지혜의 최신 스키마와 다르므로 다음 형식으로 교체한다.

```json
{
  "run_id": "run-102",
  "profile_id": "profile-01",
  "scenario": "fall",
  "vital": {
    "heart_rate": 118,
    "systolic_bp": 120,
    "diastolic_bp": 78,
    "temperature_c": 36.4,
    "spo2": 95,
    "measured_at": "2026-10-08T15:30:00+09:00"
  },
  "source": "mock"
}
```

- Python 생성 데이터를 DB에서 읽어도 실제 센서 값이 아니므로 `source="mock"`을 사용한다.
- AutoHealing이 마지막 정상 캐시를 사용한 경우 `source="cache"`를 사용한다.
- 실제 센서 연동 전에는 `live`를 추가하지 않는다.

## 8. `7. AutoHealing` 수정안

DR-VITAL-01 행은 다음처럼 보완한다.

```markdown
| DR-VITAL-01 | 최신 바이탈 조회 응답 없음 | 타임아웃, 값 누락, 오래된 측정값 | 3회 재시도 → 마지막 정상 캐시 사용 + "n분 전 값" 표시 | 보호자에게 "센서 확인 필요" 알림 |
```

기존 `SQLite 테이블` 코드 블록에 다음 테이블과 인덱스를 추가한다.

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

테이블 설명 아래에 다음 내용을 추가한다.

```markdown
- `vital_readings`: 15초마다 수신한 바이탈 측정 이력을 저장합니다.
- `cache`: MCP 또는 최신값 조회 실패 시 사용하는 마지막 정상 결과입니다.
- `run_logs`: 재시도·폴백·실패와 복구 시간을 기록합니다.
```

### DB 장애 설명 보완

다음 주의사항도 함께 기록한다.

```markdown
`vital` 장애 주입이 MCP 또는 최신 바이탈 조회 실패를 의미하면 SQLite 캐시를 사용할 수 있습니다. 그러나 SQLite 자체가 열리지 않으면 같은 DB의 캐시도 사용할 수 없으므로, 이 경우 시나리오 Mock 데이터로 대체할지 최종 실패로 처리할지 별도 정책을 적용합니다.
```

## 9. `9. 데이터와 MCP 도구` 수정안

`get_vitals` 행은 지혜·두나가 합의한 함수명으로 수정한다.

```markdown
| `get_vitals(profile_id, scenario)` | Vital | 최근 DB 데이터가 없을 때 사용할 시나리오별 Mock 바이탈 반환 |
```

이 설명은 **DB 우선, MCP Mock fallback 구조를 팀에서 확정한 경우에만** 반영한다. 기존처럼 MCP 조회를 주 데이터 경로로 유지한다면 `POST /vitals/readings` 저장값을 MCP 서버가 어떻게 읽을지 별도의 서버 간 API가 필요하므로 권장하지 않는다.

## 10. `12. 팀 구성과 역할` 수정안

기존 역할을 유지하면서 다음 내용을 각 담당자 행에 추가한다.

```markdown
| 오케스트레이터 | 지혜 | 기존 담당 + `POST /vitals/readings` 수집 API·스키마, Vital Agent 최신 데이터 연결 |
| AutoHealing | 상옥 | 기존 담당 + `vital_readings` 테이블, 저장·최신값 조회, 캐시·장애 로그 연결 |
| 데이터·MCP | 두나 | 기존 담당 + 가상 바이탈 데이터를 15초마다 전송하는 Python 프로그램 |
```

팀원 간 합의 사항 표에는 다음 행을 추가한다.

```markdown
| 바이탈 전송(두나) ↔ 오케스트레이터(지혜) | `POST /vitals/readings` 요청·응답 형식, 전송 실패 처리 |
| 오케스트레이터(지혜) ↔ AutoHealing(상옥) | 저장·조회 함수, 최신 데이터 기준, DB 예외 형식 |
| 데이터·MCP(두나) ↔ AutoHealing(상옥) | Mock 데이터 형식, 캐시 키, 장애 시 fallback 데이터 형식 |
```

## 11. 환경변수 추가안

구현 시 값을 코드에 고정하지 않으려면 다음 환경변수를 검토한다.

```text
VITAL_INGEST_URL=http://localhost:8000/vitals/readings
VITAL_SEND_INTERVAL_SECONDS=15
VITAL_MAX_AGE_SECONDS=30
```

- `VITAL_INGEST_URL`, `VITAL_SEND_INTERVAL_SECONDS`: 두나의 전송 프로그램에서 사용
- `VITAL_MAX_AGE_SECONDS`: backend의 최신 바이탈 판정에서 사용
- 실제 환경변수 파일 위치는 전송 프로그램의 실행 위치를 정한 뒤 확정

### 전송 프로그램 실행 방법

백엔드와 DB 구현이 실행 중인 상태에서 `mcp_server` 폴더에서 다음 명령을 사용한다.

```powershell
# 가상 어르신 5명을 한 번씩 전송하고 종료
python -m src.vital_sender --once

# 가상 어르신 5명을 15초마다 계속 전송
python -m src.vital_sender

# 낙상 시나리오 바이탈을 15초마다 전송
python -m src.vital_sender --scenario fall --interval 15
```

기본 주소는 `http://localhost:8000/vitals/readings`이며, Docker 내부에서 실행할 때는 `VITAL_INGEST_URL=http://backend:8000/vitals/readings`를 사용한다.

## 12. README 반영 전 최종 확인

다음 항목을 팀에서 확정한 뒤 README에 완료형 문장으로 반영한다.

- [ ] 지혜: `POST /vitals/readings` 경로와 요청·응답 스키마 확정
- [ ] 상옥: `vital_readings` 테이블과 저장·조회 함수 계약 확정
- [ ] 지혜·상옥: Vital Agent가 DB를 우선 조회하는 구조 확정
- [ ] 두나: 전송 프로그램의 위치와 환경변수 이름 확정
- [ ] 전체: 최신 데이터 기준 30초 확정
- [ ] 전체: SQLite 자체 장애 시 Mock fallback 또는 최종 실패 정책 확정
- [ ] 구현 후 15초 전송 → DB 저장 → `/care/run` 반영 통합 테스트

## 13. 구현 완료 후 README에 사용할 한 줄 요약

```markdown
Python 바이탈 전송기가 가상 어르신 5명의 측정값을 15초마다 HTTP로 전송하고, FastAPI가 이를 SQLite에 저장합니다. Vital Agent는 최근 30초 이내 데이터를 우선 사용하며, 조회 실패 시 AutoHealing이 재시도 후 마지막 정상 캐시로 복구합니다.
```
