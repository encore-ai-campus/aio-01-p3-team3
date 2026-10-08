# 상옥 첫 개발 묶음 — 연결 안내

DB/가상 프로필/장애 주입/공통 조회 복구 및 바이탈 이력 repository를 구현했습니다.
승인, 자동 119, 실제 MCP/LLM, 상세 도메인 검증, 지표는 이번 범위에 없습니다.
이전 초안은 docs/archive/autohealing_v1에 보존했으며 런타임·현재 테스트에서 사용하지 않습니다.

## 지혜님 연결 예제

```python
from src.db.database import Database, cache_key
from src.db.seed import seed_profiles
from src.healing.retry import RetryPolicy, with_healing, RecoveryError

db = Database()  # DB_PATH, 없으면 backend/data/app.db
seed_profiles(db)  # 초기화 때 한 번; 재실행 시 기존 프로필 유지

result = await with_healing(
    db=db, run_id=run_id, step="vital",
    fetch=lambda: call_get_vitals(profile_id, scenario),
    validate=validate_vital,  # 동기 검사, ValueError 또는 False로 거부
    policy=RetryPolicy(max_attempts=3, timeout_s=15, delay_s=0.5, max_cache_age_s=300),
    fault=fault, use_cache=True,
    cache_key=cache_key("vital", profile_id, scenario),
    require_measured_at=True,
)
vital_data = result["data"]
logs = db.logs(run_id)
```

실제 MCP 함수와 validate_vital은 연결 담당자가 제공합니다. Pydantic ValidationError는
ValueError 계열이므로 검증 실패로 처리됩니다. None 반환은 검사 통과, False는 거부입니다.
콜백이 새 데이터나 정규화 결과를 반환해도 wrapper는 원본을 사용하므로 검증 함수는 검사 전용입니다.

## 임시 정책 및 반환 계약

- 기본값은 **최초 포함 총 3회**, 15초/시도, 대기 0.5·1초, 캐시 최대 300초.
  Vital 횟수·유효시간은 팀 미확정으로 언제든 RetryPolicy로 변경 가능합니다.
- 정상 source=mock, 대체 source=cache. attempts는 수행 시도 수.
- measured_age_s는 실제 측정 시각 기준 나이. 캐시 반환은 saved_at도 포함.
  require_measured_at=True이면 시간대가 있는 measured_at이 필수이며 미래/오래된 값 거부.
  measured_at은 재저장 시에도 변경하지 않습니다. 저장 시각과 측정 시각 모두 유효해야 합니다.
- 시연 캐시는 profile_id/scenario별로 분리합니다. normal 캐시를 fall에 쓰지 않습니다.
- use_cache=False이면 캐시 읽기·저장을 모두 하지 않습니다. 기기 제어에 캐시 금지.
- TimeoutError/ConnectionError/InvalidResult만 기본 재시도.
  실제 SDK 예외 클래스는 retryable 인자로 추가하세요. 인증/설정 오류까지 넣지 마세요.
  응답 dict의 status=failed 또는 success=False도 실패로 처리합니다.
- 소진 후 RecoveryError(step, attempts). 안전 종료·정보 없이 진행은 지혜님 Guard 결정.
  TypeError 등 프로그래밍 오류와 DB 저장 오류는 숨기거나 재시도하지 않습니다.
- 취소는 전파하며 sync HTTP 콜백은 별도 스레드에서 실행합니다.
  timeout이 동기 스레드를 종료하지 못하므로 클라이언트 자체 timeout도 필요합니다.
- fault는 vital/iot/vision/llm 목록. 요청마다 고정 사본으로 사용, 전역 상태 없음.
  fault_target으로 단계별 주입 대상을 지정할 수 있습니다. 승인 후 iot를 어디에 적용할지는 합의 필요.
- 로그: success/retry/fail/fallback/error. fail 후 fallback이면 해당 호출은 캐시 복구.
  error는 재시도하지 않는 오류. 오류 클래스만 저장하고 예외 메시지는 저장하지 않습니다.
  API 로그 필드와 metrics는 추후 연결합니다.

## 시험

```powershell
cd backend
python -m pytest tests/test_healing.py -q
python -m src.db.seed
```

seed 명령은 설정된 DB에 가상 프로필 3개를 넣습니다. 테스트는 tmp_path와 고정 시각을
사용하며 실제 API·키·실사용 DB 없이 동작합니다. 프로필 값/ID는 docs/scenarios.md와 같습니다.
기존 임시 프로필을 갱신하려면 개발 DB에서 `python -m src.db.seed --overwrite`를
명시적으로 실행하세요. 기본 시드는 기존 데이터를 덮어쓰지 않습니다.

## 15초 수집용 저장·조회 준비 (수집 API는 지혜 담당)

```python
from src.db.vital_readings import VitalReadings, ReadingConflict

repo = VitalReadings(db)
saved = repo.save(
    reading_id=reading_id,  # 재전송 시 같은 ID; 공개 요청에서 받는지는 팀 합의
    profile_id=profile_id,
    scenario=scenario,     # 시연 데이터 격리. None은 별도 일반 수집 스트림
    data=vital_data,       # VitalData 필드 + timezone-aware measured_at
)
latest = repo.latest(profile_id, scenario=scenario, max_age_s=freshness_seconds)
```

- save는 id(int), inserted/duplicate와 attempts 반환. 같은 ID의 다른 payload는 ReadingConflict.
  reading_id는 전체 테이블에서 고유하므로 시뮬레이터는 UUID 등의 고유 ID를 사용하세요.
- 데이터 필드는 heart_rate/systolic_bp/temperature_c/spo2/measured_at.
  타입·유한 숫자·시간대·미래시각만 검사합니다. 위험도/생리적 범위 검증은 수집 API/규칙 담당.
- latest는 측정시각 순으로 조회합니다. 재전송이 freshness를 갱신하지 않습니다.
  max_age_s 필수이며 팀 최신성 기준을 임의로 정하지 않습니다.
- 반환의 data는 VitalData와 호환되고 origin=simulator는 repository 내부 메타데이터입니다.
  public source=mock/cache/mixed 및 해든 live/cache 변환은 아직 연결하지 않았습니다.
- 최신값 없음/만료면 None, 조회 DB 장애는 예외. Mock fallback을 자동 수행하지 않습니다.
- 스키마 오류·디스크/권한 오류는 재시도하지 않습니다. SQLite busy/locked만 WritePolicy의
  총 횟수만큼 재시도합니다. DB connection busy_timeout_s × 횟수와 대기를 합산한 시간에 유의하세요.
- repository는 동기 함수입니다. async 수집 API에서는 asyncio.to_thread 등으로 감싸세요.
  SQLite 파일은 backend만 접근하고 MCP 컨테이너와 DB 파일을 공유하지 않습니다.
- 저장 함수는 DB transaction commit 이후 inserted를 반환합니다. API는 오류를 잡아
  성공 응답으로 바꾸지 않아야 합니다. ReadingConflict의 HTTP 상태도 지혜님이 정합니다.
- schema.sql의 CREATE IF NOT EXISTS는 새 vital_readings 테이블을 추가하고 기존 캐시를 유지합니다.
  임의 외부 DB의 다른 구형 schema를 자동 migration하는 기능은 없습니다.

추가 시험: `python -m pytest tests/test_vital_readings.py -q`.

Docker DB_PATH/볼륨은 팀 main 설정을 사용합니다. 이번 검증은 SQLite 재열기까지이며
컨테이너 재생성·배포 유지 시험은 통합 때 수행합니다.

## 두나 저장·조회 어댑터 및 Vital 복구

```python
from src.db.vital_service import VitalService
from src.healing.vital import get_vitals_with_healing, VitalDatabaseError, VitalUnavailable

service = VitalService(db)
row_id = service.save_vital_reading(reading)  # reading_id/profile_id 및 VitalData 필드
result = await get_vitals_with_healing(
    db=db, run_id=run_id, profile_id=profile_id, scenario=scenario,
    fetch_latest=lambda: service.get_latest_vital_reading(
        profile_id, scenario=scenario, max_age_seconds=freshness_seconds),
    validate=validate_vital, freshness_seconds=freshness_seconds,
    policy=RetryPolicy(max_attempts=3, max_cache_age_s=cache_age_seconds), fault=fault,
)
```

수집 API에서는 동기 save를 asyncio.to_thread로 호출하세요. 공개 DTO에서 내부 reading_id를
어떻게 만드는지는 수집 담당자와 합의해야 합니다. 동일 재전송은 같은 row_id를 반환합니다.

None/만료는 반복 조회하지 않고 캐시로 이동합니다. 조회 실패는 제한 재시도하며 SQLite
자체 장애는 같은 DB의 캐시를 읽지 않습니다. 캐시도 없으면 VitalUnavailable,
DB 장애면 VitalDatabaseError를 전달합니다. 두 예외의 events로 저장 불가 로그를 확인하세요.
Mock 대체는 mock_fetch를 제공해야 켜지며 DB 장애 대체는 mock_on_db_error=True도 필요합니다.
대체 Mock은 측정 캐시에 덮어쓰지 않습니다. 일반 스트림 scenario=None은 시연 캐시와 분리합니다.

반환은 data/source/attempts/recovery/events/log_persisted/database_failed입니다.
source는 mock/cache, recovery는 None/retry/cache/mock이며 로그 저장 불가 시 persisted=False입니다.
최신성 한계와 캐시 한계는 각각 명시해야 하며 30초는 확정 기본값으로 넣지 않았습니다.
시험: `python -m pytest tests -q` — 80개 통과(기존 placeholder 1개 포함).
