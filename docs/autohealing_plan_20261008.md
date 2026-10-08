# 상옥 AutoHealing 수정 개발 계획 — 2026-10-08

## 16:04 두나 요청 반영 — 다음 보완 계획

출처: 1008_1604_상옥님 바이탈 DB 저장 및 장애 복구 요청_두나.md.
첨부 파일명은 MMDD_HHMM_내용_작성자 형식으로 읽는다.
1008은 10월 8일, 1604는 16:04, 두나는 작성자다. 명시한 날짜/시각/작성자를
자료 구분에 쓰되, 최신 문서라는 이유만으로 제안 사항을 팀 확정 계약으로 취급하지 않는다.

### 현재 구현과 요청의 차이

- vital_readings, 측정·수신 시각 분리, 최신 조회, 중복 방지, SQLite 잠금 복구는 구현 완료.
- 현재 save는 inserted/duplicate·reading_id·attempts 반환. 두나 제안은 DB 행 id(int) 반환.
  id를 신규/중복 모두 반환하도록 repository를 보완하고 API용 저장 어댑터를 준비한다.
- reading_id와 scenario는 현재 내부 repository 계약이다. 두나 제안 요청에는 없다.
  public reading_id를 추가할지, 서버에서 중복 키를 만드는지 지혜/두나와 합의한다.
  scenario=None으로 수집한 일반 스트림을 heat 시연 스트림으로 묵시 혼합하지 않는다.
- 최신성 30초는 제안값이다. 설정형 정책/명시 인자로 준비하고 확정 전 하드코딩하지 않는다.
- 시뮬레이터도 가상 데이터이므로 public source=mock, 캐시 대체=cache로 계획한다.
  내부 origin=simulator는 유지하되 live로 임의 확장하지 않는다.
  해든 코드 live/cache 입력 변환과 자동119의 데이터 신뢰 조건은 별도 확인한다.
- 현재 DB 정렬은 measured_at_epoch 기준이다. ISO 문자열의 timezone별 정렬 문제를 피하므로 유지한다.
  received_at은 서버 UTC ISO로 명시 저장하고 SQLite CURRENT_TIMESTAMP에 의존하지 않는다.

### 개발 묶음 A: 저장·조회 연결 계약 보완

1. 저장 반환에 행 id 추가: 신규 삽입과 동일 재전송은 같은 id를 반환.
   다른 payload를 같은 reading_id로 보내면 ReadingConflict 유지.
2. save_vital_reading(reading) / get_latest_vital_reading(profile_id, max_age_seconds)
   어댑터를 준비하되 실제 public DTO 필드는 지혜 VitalReadingCreate 확정 후 매핑.
3. latest의 None은 데이터 없음/만료라는 정상 조회 결과로 유지한다.
   DB 잠금·파일·스키마 오류는 예외로 유지하여 None이나 가짜 정상값으로 바꾸지 않는다.
4. async API는 동기 DB 호출을 별도 스레드에서 실행. 프로필 유효성/외래키/허용값은
   지혜 수집 API 계약에 맞춘다. 기존 이력을 삭제하거나 임의로 외래키를 추가하지 않는다.

### 개발 묶음 B: Vital 조회 복구 연결

정상 최신 측정 조회 → source=mock으로 반환 → 마지막 정상 결과를 cache에도 저장.
계약된 Vital 조회 경계의 일시 실패 → 제한된 재시도 → 유효한 cache 사용.
캐시도 없을 때 Mock으로 대체할지 fail로 종료할지는 지혜 정책을 전달받는다.
데이터 없음/만료는 DB 오류와 다르게 처리한다. 15초마다 데이터가 안 왔다는 이유만으로
같은 DB를 반복 조회하는 루프를 복구 성공으로 간주하지 않는다.

- 기존 cache_key(kind, profile_id, scenario) 규칙을 유지한다. vitals:profile-01로
  일괄 변경하지 않는다. 일반 수집과 시나리오별 mock의 캐시 경계는 팀과 맞춘다.
- DB 자체 장애면 같은 SQLite의 cache와 run_logs도 실패할 수 있다.
  읽기/로그 실패를 원래 실패와 구분하고 복구가 되었다고 기록하지 않는다.
  DB 장애 시에도 화면에 전달할 최소 오류 객체를 반환/전파할 경계를 준비하고,
  Mock 대체 또는 최종 fail 결정은 지혜에게 맡긴다.
- 저장/조회 sqlite3 busy/locked는 일시 장애로 제한된 재시도.
  권한/디스크/스키마 오류는 무조건 반복하지 않는다.
- vital fault는 DB 전체 장애가 아니라 조회 호출 장애로 주입하는 안을 우선 제안.
  실제 DB 장애는 별도 시험 fixture로 검증하고 기존 fault enum을 임의 확장하지 않는다.
- 로그의 상태는 success/retry/fallback/fail, recovery는 cache/mock.
  오류는 원문 메시지 대신 민감정보 없는 오류 코드/종류를 기록한다.

### 추가 시험 및 합의 목록

시험: 같은 행 id 재반환, 최근 30초 후보의 경계값, 미수신/만료와 DB 오류 구분,
최신 정상 조회 후 캐시 저장, 조회 fault 후 cache, cache 없음 정책별 결과,
DB 전체 장애에서 cache/log도 불가, 프로필·시나리오·중복 재전송 분리.

합의: VitalReadingCreate 입력/저장 반환 id, reading_id 생성 주체, scenario 유무,
최신성 30초 확정, 캐시 유효시간(최신성 한계와 별도), 최신값/캐시/Mock 대체 우선순위,
DB 장애 시 fail/Mock, 보관기간·정리·외래키.
보관기간 확정 전 자동 삭제 작업을 추가하지 않는다.

개발 묶음 A·B 구현 완료. 저장·중복 재전송의 같은 행 id 반환, VitalService 어댑터,
get_vitals_with_healing을 추가했다. HTTP API와 팀원 함수 연결은 다음 단계다.

### 보완 구현 검증 결과

- 백엔드 테스트 80개 통과(기존 placeholder 1개 포함).
- 최신값 없음/만료는 즉시 대체 경로로 이동하며 반복 조회하지 않는다.
- 일시 조회 실패는 제한 재시도 후 캐시 복구, 실제 DB 장애는 같은 DB 캐시를 건너뛴다.
- 캐시·Mock·최종 실패를 구분하고 Mock 콜백 및 DB 장애 시 Mock 허용을 명시 인자로 받는다.
- 로그 저장 실패는 events의 persisted=False로 전달한다. 예외 원문은 기록하지 않는다.
- 최신성은 freshness_seconds 필수 인자, 캐시 유효시간은 별도 RetryPolicy로 설정한다.
- 다음 순서: 지혜 수집 DTO 매핑 → 두나 Vital 조회 함수 연결 → 기기 제어 → Vision/LLM → 통합 지표.

## 최신 진행 현황 — GitHub 공유용

개발 기준 main: 2a419c4 (지혜 스키마 및 첫 AutoHealing 묶음 병합 포함).
계획서와 연결 안내는 이후에도 같은 docs 파일을 갱신해 브랜치/PR로 공유한다.
아래 과거 확인 기록보다 이 현황과 실제 코드가 우선한다.

완료:
- DB 초기화·캐시·복구 로그, 요청별 장애 주입, 공통 async 재시도.
- docs/scenarios.md의 프로필 3개 반영, 명시적 --overwrite 시드 갱신.
- vital_readings 이력 테이블, 중복 방지 저장, 프로필/시나리오별 최신 측정 조회.
- 측정·수신 시각 분리, 순서 뒤집힌 도착·시간대·만료·동시 접근 검증.
- SQLite busy/locked만 제한적 저장 재시도, 오류/중복 충돌 전달.
- 백엔드 시험 62개 통과 (기능 61개 + 기존 placeholder 1개).
- Docker backend 이미지 빌드, 컨테이너 내 SQLite 초기화·프로필·repository smoke 통과.
- 루트 Compose 설정 검사 통과. API 서비스 실행·운영 배포 검증과는 구분한다.

미확정 정책은 구현하지 않음:
- POST /vitals/readings 입력/응답, 15초 시뮬레이터 HTTP 전송.
- 수집값 없음/만료 시 Mock 자동 대체 순서, 최신성 한계값, public source 변환.
- LLM/Vision 어댑터, metrics 완료 실행 정의, 승인 타이머·자동 119.
- 위험도/의학적 값 범위 정책, 시나리오 및 CCTV confidence 계약 변경.

다음 연결: 지혜/두나와 reading_id·measured_at·scenario 계약 확정 →
수집 API에서 VitalReadings 호출 → 조회 출처/Mock 대체 정책 확정 → LLM/Vision 복구.
Repository는 reading_id와 시간대 있는 measured_at을 내부 저장 요구사항으로 사용한다.
이를 공개 수집 API의 확정 필드로 강제한 것은 아니다.

## 첫 개발 묶음 진행 상태

### 15초 HTTP 바이탈 수집 및 지혜 스키마 확인 후 추가 계획

2026-10-08 fetch 결과 jihye-jjye라는 원격 브랜치는 없고,
지혜 스키마는 origin/jjye 9e575a7에서 확인했다. 이름 차이를 명시하며 아직 병합하지 않았다.

확인된 계약: profile_id/run_id, vital(VitalData), 긴 바이탈 필드명,
source=mock/cache/mixed, errors=list[str], /care/approve decision=approve/reject.
VitalData.measured_at은 선택 str이며 수집용 요청 모델은 아직 없다.
Scenario에는 critical이 빠져 있어 docs/scenarios.md 5개와 불일치한다.
confidence는 0~1 float, ProposedAction.arguments는 dict[str,str]라
해든 high/low confidence와 숫자 target은 변환 정책 합의가 필요하다.

**신규 수집 흐름은 Discord의 제안이며 구현 확정으로 간주하지 않는다.**

두나 Python simulator → 지혜 POST /vitals/readings 및 입력 검증 →
상옥 vital_readings 저장 → 최신 측정 조회 → 지혜 Vital Agent 연결.
SQLite는 backend만 접근하고 MCP 프로세스가 같은 DB 파일을 직접 열지 않는다.
Mock 조회를 실제로 어디에서 호출할지는 지혜/두나와 연결 경계를 정한다.

#### 먼저 준비할 부분

1. vital_readings 테이블/인덱스와 저장·최신 조회 repository.
   제안 컬럼: id, reading_id, profile_id, scenario(시연 격리용 여부 합의),
   heart_rate, systolic_bp, diastolic_bp, temperature_c, spo2,
   measured_at(원본 ISO), measured_at_epoch(정렬용), received_at.
   reading_id UNIQUE 또는 별도 중복 키를 두나/지혜와 합의한다.
   최신 조회 인덱스는 profile_id, 필요하면 scenario, measured_at_epoch 순.
2. 저장·조회 시험: out-of-order 도착, 중복 재전송, 시간대, 미래/만료 측정,
   서로 다른 프로필·시나리오 격리, 수집/조회 병렬 실행.
3. 데이터 선택 함수: 신선한 수집값 → 데이터 없음/만료면 Mock 대체 제안.
   예외로 인한 조회 장애와 단순 데이터 없음은 구분한다.
   서비스 조회 장애에 대한 기존 캐시 사용 우선순위는 팀과 별도 합의한다.
   measured_at 원본 보존, received_at으로 최신성을 꾸미지 않는다.
4. 내부 출처는 simulator/mock/cache와 대체 이유를 분리해 보존하고
   public mock/cache/mixed 및 해든 live/cache 변환은 연결 어댑터로 준비한다.
   Mock 대체를 최신 실제 측정으로 표기하거나 자동 119 근거로 쓰지 않도록
   source 확장 또는 데이터 신뢰도 메타데이터를 팀과 합의한다.
5. 잠금 등 일시 DB 장애는 짧고 제한된 retry, 스키마/권한/디스크 오류는
   실패를 전달한다. 저장 실패 후 성공 응답 금지. HTTP 재전송은 같은 reading_id 사용.
   저장 재시도는 외부 MCP 재시도와 별도이며 중복 방지가 전제다.

#### 신규 확정이 필요한 계약

- 지혜: VitalReadingRequest/Response, profile_id/scenario/reading_id 포함 여부,
  필수 timezone-aware measured_at, 유효 범위, 미등록 프로필, 중복 수집 응답.
- 두나: 15초 전송, 동일 reading_id 재사용, HTTP timeout, 제한된 재전송 정책.
- 지혜/해든: 최신성 임계값(45/60초 등 후보일 뿐 미확정), source 및 Mock 대체 의미.
- 기화: 수집 시뮬레이터 운영 위치, 배포 DB 볼륨, 보존기간/정리 기준.

#### 수정된 다음 개발 묶음

팀 프로필 시드 보완 → vital_readings repository와 단독 시험 →
최신 조회/Mock 대체 어댑터(설정형 정책) → 지혜 수집 API 연결 예제 →
LLM 복구/Vision 단일 복구 주체 연결 → 지표/통합 시험.
수집 API/시뮬레이터/승인 타이머/자동119는 상옥이 미리 구현하지 않는다.
새 스키마 전체 병합과 원격 push도 이번 계획 보완에서 수행하지 않았다.

autohealing_jso에 origin/main 87db5be 구조를 fast-forward 반영했다.
기존 단일 모듈·테스트·안내는 docs/archive/autohealing_v1에 보존했다.
db/schema.sql·database.py·seed.py, healing/faults.py·retry.py와 독립 시험을 구현했다.
연결 계약과 임시 설정은 docs/autohealing_integration.md를 참고한다.
metrics·실제 에이전트 연결·LLM/Vision 복구·승인/119·Docker 검증은 남아 있다.
아래 '확인 기준과 현재 상태' 및 '현재 수행하지 않은 작업'은 계획 작성 시점의 기록이다.

## 확인 기준과 현재 상태

- Git fetch 후 origin/main `87db5be` 기준으로 소스·테스트·Compose·CI·README·LLM 계획서를 확인.
- origin/jjye는 main과 동일. origin/choiduna의 트리 차이는 VS Code 설정뿐.
  origin/c.h.d와 origin/ykw는 현재 main과 다른 이전 구조를 포함하므로 최신 통합 기준으로 사용하지 않는다.
- main의 schemas.py, main.py, MCP server.py, agents, healing, db,
  frontend app/approval 등 핵심 파일은 설명만 있는 자리표시자다.
  backend와 MCP의 임시 테스트는 assert True뿐이므로 CI 통과가 기능 검증을 의미하지 않는다.
- 로컬 autohealing_jso에는 어제 작성한 미커밋 autohealing.py와 테스트가 있다.
  이전 18개 통과 결과는 기존 예제와 로컬 모듈 시험이며 새 main 통합 검증이 아니다.
- SQLite 볼륨과 DB_PATH=/app/data/app.db는 루트 및 backend 배포 Compose에 이미 설정됨.
  볼륨 재연결보다 코드의 경로 사용, 권한, 재생성 후 데이터 유지 시험이 필요하다.

## 기존 계획에서 변경

1. 실제 에이전트 연결을 기다리기 전에 지정 폴더에 복구·DB 공통 기능을 구현한다.
2. 단일 src/autohealing.py를 팀 폴더로 분리하고 중복 DB/재시도 구현은 두지 않는다.
3. SQLite 가상 프로필 시드도 상옥 담당 파일에 포함한다.
4. 거절 Summary는 elder_message 빈 문자열이 유효하다. 기존 비어 있지 않음 검증을 재사용하지 않는다.
5. Emergency LLM 출력은 reason/action_texts 계약을 제안 기준으로 사용한다.
   코드가 만든 조치 목록을 LLM이 변경하지 못하도록 해든 검증을 연결한다.
6. CCTV 비전 호출이 MCP 안에 있으므로 backend에서 analyze_cctv 도구 호출을 감싼다.
   MCP 내부 SDK/해든 구현에서 중복 재시도하지 않도록 합의한다.
7. 기기 제어와 알림/119는 캐시 대체하지 않는다. 승인·실행 경로는 지혜 담당이다.

## 해든 전달서 추가 반영 — 2026-10-08

출처: Downloads/해든-LLM파트-전달_해든.md, 승인-119-흐름_해든.md.
전달서의 구현 완료·테스트 수는 해든 보고이며, 이 추가 검토에서는 원격 코드를
다시 가져오거나 해당 테스트를 실행하지 않았다. 위 main 상태는 이전 확인 시점의 기록이다.

### 호출 계약과 복구 정책

- LLM: 해든의 generate(step, ctx, llm)를 감싼다. 예외 또는 검증 실패 시
  교정 지시로 1회 재요청, 다시 실패하면 template(step, ctx)를 검증해 반환한다.
  fallback_used=true는 템플릿 사용 시 기록하고 재요청 성공과 구분한다.
- 단계마다 LLM 시간 제한 10초, 비전 15초를 적용할 계획이다.
  각 시도 제한과 전체 복구 시간 예산은 구분하며 로그에 실제 소요 시간을 남긴다.
  SDK 재시도는 꺼진 상태인지 코드 연결 때 확인한다.
- generate_or_template()은 해든의 임시 재시도 경로다. AutoHealing 연결 시
  generate()를 사용하고 중복 재요청·템플릿 적용을 제거한다.
- Vision: analyze_cctv_image()는 실패 시 예외를 내보내는 호출로 감싼다.
  최초 1회 + 재시도 2회 = 총 3회 실패 후 판단 불가로 처리한다.
  두나가 쓰는 analyze_cctv_or_unavailable()이 내부에서 복구한다면 backend 재시도를
  다시 적용하지 않는다. 실제 함수 구현을 보고 복구 주체 한 곳을 확정한다.
- CareStatusResult의 confidence, fall_event, signs와 개별 Vital 출처·측정시각을
  잃지 않고 전달한다. 스키마 확정·위험도 규칙은 지혜/해든 담당이다.
- Summary는 approved뿐 아니라 decided_by=guardian/auto/timeout 및 실제 executed를
  전달받는다. 거절 시 어르신 문장은 빈 값, 자동·시간초과 시 보호자 승인 표현 금지.
  글자 수는 새 전달서 기준 어르신 60자/보호자 120자/근거 60자이며 해든 검증과 맞춘다.

### 승인·119 예외는 팀 결정 후 적용

전달서에는 즉시 자동 119 및 60초 무응답 자동 119가 제안되어 있다.
두 문서 모두 기존 승인 원칙의 변경을 PM과 합의할 항목으로 명시하므로
확정된 팀 정책으로 간주하지 않는다. 승인 없는 자동 실행은 기본 비활성으로 준비한다.
ENABLE_AUTO_119 설정이 즉시 경로와 시간초과 경로 둘 다 차단하는지 확인한다.
기기 제어는 시간이 지나도 승인 없이 실행하지 않는다.

- 승인 대기·30초 재알림·60초 타이머·자동 실행 결정: 지혜 담당.
- 상옥: 결정된 Mock Action의 실행 복구, 실패 기록, 실패 안내 경로 보장.
- 119 실행 실패: 캐시로 대체하거나 성공으로 바꾸지 않고
  보호자에게 '직접 119에 연락해 주세요'를 전달하도록 결과를 제공한다.
  device_fail을 임시로 재사용하더라도 tool=call_119 실패를 보존한다.
- 보호자 알림 문구는 해든의 코드 템플릿을 사용해 LLM 복구를 기다리지 않는다.
  긴급 Action의 실패 안내 역시 LLM 재요청 완료를 기다리지 않게 연결한다.
- 자동 실행/timeout/늦은 승인 경합은 중복 실행 방지가 필요하다.
  Action 실행 식별자·완료 상태·중복 요청 처리는 지혜와 합의하고
  실패 여부가 불분명한 119/알림 호출을 무조건 반복하지 않는다.
- 최신 Vital의 정의는 measured_at 기준으로 합의한다. cache/mixed라는 전체 출처만으로
  판단하지 않는다. 캐시에서 읽은 Vital을 최신 정상 조회로 표시하지 않는다.
  캐시일 때 자동 119 제외가 Vital 조건만인지 무응답 조건에도 적용되는지 해든/지혜 확인.

### 추가 시험과 연결 순서

Vital 우선 전달 순서는 유지한다. 다음으로 LLM 직접 호출 어댑터 → Vision 단일 복구
주체 확인 → 승인된 Action 복구를 연결한다. 자동 119 시험은 팀 정책 확정 후 추가한다.

1. 교정 1회 + template 사용, SDK/임시 래퍼 중복 재시도 없음.
2. Vision 총 3회 실패, 원본 캡처와 판단 불가 상태 유지.
3. 승인/거절/auto/timeout별 Summary 말투와 실행 사실 일치.
4. 자동 경로 비활성 시 즉시/60초 119 실행 0회, 기기 무승인 실행 0회.
5. 자동 경로 승인된 경우에만 Mock 119 실패 → 즉시 직접 연락 안내.
6. timeout과 늦은 approve가 겹쳐도 동일 Action은 중복 실행되지 않음.
7. 캐시 Vital의 출처·나이 보존, 자동 실행 조건에 대한 합의 정책 검증.

해든에게 받을 실제 코드 위치/커밋, generate 및 template의 정확한 signature,
비전 wrapper 내부 재시도, validation 예외 형식을 확인한 뒤 연결한다.

## 담당 파일과 산출물

| 파일 | 상옥 구현 범위 |
| --- | --- |
| backend/src/db/schema.sql | cache, run_logs, profiles; 지표용 완료 결과 기록 구조 합의 |
| backend/src/db/database.py | DB_PATH 사용, 초기화, 캐시·로그·프로필 접근 |
| backend/src/db/seed.py | age/lives_alone/has_condition/mobility_limited 가상 프로필, 중복 실행 안전 |
| backend/src/healing/retry.py | async with_healing, 검증 콜백, 단계별 횟수, timeout, use_cache 정책 |
| backend/src/healing/faults.py | vital/iot/vision/llm 주입, 요청별 fault 유지 |
| backend/src/healing/metrics.py | 장애 호출 복구 지표, 완료 실행 지표 분리 |
| backend/tests/test_healing.py | 정책별 실제 동작 검증 |

agents/vital.py, agents/iot.py와 MCP client는 main 파일 주석 기준 지혜 담당.
상옥은 감싸는 API와 연결 예제를 제공하고 해당 파일을 동시에 수정하지 않는다.
LLM prompts/fallback/validation은 해든 제공; 승인 상태 관리는 지혜 담당.

## 실행 순서와 완료 기준

### 1. 최신 구조 반영 준비

미커밋 파일을 보존한 뒤 main 구조를 autohealing_jso에 반영한다.
스키마의 profile_id/run_id/scenario/fault와 복구 결과 계약을 먼저 맞춘다.
문서의 task_id/person/approved 예시는 확정 코드 계약으로 대체한다.

### 2. DB와 공통 복구 구현 — 다른 팀 구현 없이 가능

DB 초기화, 로그·캐시, 프로필 시드, 장애 주입을 순수 목업 콜백으로 시험한다.
콜백 예외와 반환 status=failed 모두 감지하고, CancelledError는 재시도로 삼키지 않는다.
프로그램 입력 오류와 일시 서비스 장애를 구분하며 무조건 모든 예외를 재시도하지 않는다.
sync 콜백의 timeout은 스레드를 종료하지 못하므로 실제 클라이언트 timeout도 요구한다.

### 3. Vital 우선 전달

get_vitals(profile_id, scenario) 정상 결과 검증 → 캐시 저장 → 장애 후 캐시 복구.
캐시 키는 데이터 종류/profile_id/scenario를 포함한다.
측정 시각 measured_at과 저장 시각 saved_at을 구분하고, 만료 기준은 팀 합의 후 설정한다.
누락된 measured_at을 현재 시각으로 꾸미지 않는다.
빈/만료/검증 불가 캐시는 복구 실패로 전달한다.
지혜에게 호출 예제·반환 형태·예외·로그 조회 방법을 전달하면 이 단계 완료.

### 4. 승인 후 기기 제어

use_cache=False, 실패 반환도 재시도 대상, 소진 후 ActionResult 실패로 변환할 정보를 반환.
승인 전과 reject 시 제어 호출 0회. 중복 승인 방지는 지혜 승인 Gate에서 검증.
control_device의 on/off처럼 같은 목표 상태를 다시 요청하는 Mock 동작만 우선 감싼다.
notify_guardian/call_119의 자동 재시도는 중복 실행 정책을 별도 합의한다.
iot fault가 조회/제어 중 어느 경로를 대상으로 하는지 확정한다.
기기 실패에서 보호자 알림까지 같은 iot fault로 막히지 않게 한다.

### 5. Vision 및 문장 LLM 연결

Vision: MCP analyze_cctv 호출 재시도 → 판단 불가. 캡처 원본 유지.
Summary: 1회 교정 → fallback. 승인 성공/일부 실패/전체 실패/거절 입력을 구분.
실패한 Mock 조치가 성공했다고 쓰이지 않도록 템플릿도 같은 검증을 통과시킨다.
현재 고정 문구의 실제 119 연락/도움 도착 표현은 Mock 실행 사실과 구분하도록 해든과 수정한다.

### 6. 통합·배포 증빙

DR-VITAL-01/DR-IOT-01/DR-VISION-01/DR-LLM-01과 승인·거절·재승인 시험.
DB 초기화·가상 프로필 조회·컨테이너 재생성 후 캐시/로그 유지 확인.
호출별 결과: 정상/재시도 복구/대체 복구/소진 실패 구분.
pending_approval은 완료 분모에서 제외, rejected는 기술 장애로 집계하지 않는다.
제어 실패의 수동 조치 안내는 제어 복구 성공으로 집계하지 않는다.
복구 시간에는 사람의 승인 대기 시간을 넣지 않는다.
검증된 실제 결과만 보고서에 기록하고 placeholder 테스트와 구분한다.

## 연결 전 합의가 필요한 불일치

- ID: README task_id vs 두나 계약 run_id. 확정 schemas.py가 단일 기준.
- source: README live vs 스키마 초안 mock/cache/mixed. 개별 조회 출처를 보존해야
  mixed일 때 Vital이 캐시인지 판정·표시할 수 있음.
- 재시도: 문서 '3회 재시도' vs 예시 총 3회 vs 로컬 총 4회. 최초/재시도를 명시.
- CCTV: 두나 summary/status vs 해든 구조화 관찰값 4개. 관찰값 손실 없는 모델 합의.
- 기기: 두나 air_conditioner/action vs 해든 aircon/mode/target. Mock MVP 계약 통일.
- 상태: README done/fail vs 두나 completed/failed, 스키마 approved 포함. 최신 API 계약으로 통일.
- Logs: API 스키마에 로그/캐시 시각 전달 경로와 GET /logs 필터·반환 형식 확정.
- faults: run 시 받은 목록을 approve 때 서버에 보존해야 승인 후 iot 실패 재현 가능.
- 경로: 해든 추천 *_agent.py/vision.py보다 main의 agents/*.py,
  rules/risk.py, llm/*, vision/analyzer.py를 우선해 구현 위치 통일.

## 현재 수행하지 않은 작업

실제 MCP/LLM 호출·컨테이너 재생성 유지 시험은 통합 단계에 남아 있다.
위 최신 진행 현황이 과거 검토 기록보다 우선한다.
