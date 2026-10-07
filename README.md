# 🌡️ 어르신과 보호자를 함께 지키는 폭염·한파 안전 알리미

> 장애가 나도 멈추지 않는 AutoHealing 멀티 에이전트 서비스

폭염·한파 날씨와 어르신의 취약 요인을 함께 살펴 위험도를 판정하고, **어르신에게는 쉬운 안내**를, **보호자에게는 빠른 알림**을 전달합니다.
외부 API나 LLM에 장애가 나도 재시도·캐시·템플릿으로 스스로 복구해서, 안전 안내가 끊기지 않도록 설계했습니다.

---

## 목차

1. [프로젝트 개요](#1-프로젝트-개요)
2. [시스템 아키텍처](#2-시스템-아키텍처)
3. [에이전트 흐름](#3-에이전트-흐름)
4. [에이전트별 역할](#4-에이전트별-역할)
5. [Guard와 Validation](#5-guard와-validation)
6. [Handoff 데이터 형식](#6-handoff-데이터-형식)
7. [AutoHealing (장애 감지·복구)](#7-autohealing-장애-감지복구)
8. [데이터와 외부 API](#8-데이터와-외부-api)
9. [위험도 판정 규칙](#9-위험도-판정-규칙)
10. [화면 구성](#10-화면-구성)
11. [API 명세](#11-api-명세)
12. [팀 구성과 역할](#12-팀-구성과-역할)
13. [실행 방법](#13-실행-방법)
14. [장애 시험 결과](#14-장애-시험-결과)
15. [보안·개인정보 원칙](#15-보안개인정보-원칙)

---

## 1. 프로젝트 개요

| 구분 | 내용 |
|---|---|
| 주제 | 에러 자가 치유(AutoHealing) 워크플로우 |
| 서비스 | 폭염·한파 시 어르신 위험도 판정 및 어르신·보호자 맞춤 안내 |
| 주요 사용자 | 홀몸 어르신, 어르신을 돌보는 보호자 |
| 핵심 원칙 | **안전 서비스는 장애가 나도 조용히 멈추면 안 된다.** 장애·정보 누락 시에는 항상 더 보수적인 쪽(알림을 보내는 쪽)으로 판단한다. |

**전체 흐름 한 문장**
> 어르신 프로필을 입력하면, 날씨·특보·쉼터·취약도를 병렬로 조사하고, 위험할 때만 위험도와 행동요령을 만들어 어르신용·보호자용 안내로 나눠 전달한다.

**역할을 나눈 이유**
- 날씨, 쉼터, 프로필은 서로 독립적인 정보라 **병렬로 조사**하면 빠르고, 한쪽이 실패해도 나머지는 살릴 수 있습니다.
- 위험도 **판정(코드)**과 **문장 작성(LLM)**을 분리해서, 판단은 일관되고 검증 가능하게, 안내문은 읽기 쉽게 만듭니다.
- 같은 정보라도 어르신과 보호자에게 필요한 내용이 달라 **요약 에이전트**를 따로 둡니다.

---

## 2. 시스템 아키텍처

```
[Streamlit]  ──HTTP──▶  [FastAPI]
 화면, 장애 주입 체크박스       │
                         오케스트레이터 ───────▶ [LLM API]
                         (에이전트 흐름)
                              │
                     ┌────────┴────────┐
                     ▼                 ▼
                [MCP 서버] ───────▶ [SQLite]
              날씨·특보·쉼터 도구    캐시, 실행 로그, 프로필
                     │
                     ▼
          기상청 단기예보 / 기상특보 / 쉼터 CSV
```

| 구성요소 | 기술 | 역할 |
|---|---|---|
| 프런트엔드 | Streamlit | 프로필 선택, 장애 주입, 결과·로그 표시 |
| 백엔드 | FastAPI | 오케스트레이터, `/alert` `/health` `/logs` 엔드포인트 |
| 도구 계층 | MCP (FastMCP) | 날씨·특보·쉼터 조회 도구 |
| DB | SQLite | 캐시(복구 수단), 실행 로그(복구 증거), 테스트 프로필 |
| LLM | (팀에서 사용하는 모델) | 행동요령, 어르신용·보호자용 문장 생성 |
| 배포 | Docker Compose + GitHub Actions | 컨테이너 2개(Streamlit, FastAPI), 테스트 실패 시 배포 차단 |

---

## 3. 에이전트 흐름

```
                         START
                  (어르신 프로필 입력)
                           │
                           ▼
                  [Orchestration 1]
                   Safety Research
                           │
                ┌──────────┼──────────┐
                ▼          ▼          ▼
            Weather     Shelter     Profile
             Agent       Agent       Agent
          (기온·특보)  (쉼터 위치)  (취약 요인)
                │          │          │
                └──────────┼──────────┘
                           ▼
                       Validation
                   (PASS / RETRY / FAIL)
                           │
                       Join Guard
                           │
                       Aggregator
                           │
                           ▼
                  SafetyResearchResult
                           │
                     Handoff Guard
                    (위험 없으면 종료)
                           │
                        HANDOFF
                           │
                           ▼
                  [Orchestration 2]
                  Write + Summary
                           │
                           ▼
                     Writer Agent
           (위험도 판정 + 행동요령 + 쉼터 선정)
                           │
                           ▼
                      AlertResult
                           │
                           ▼
                     Summary Agent
              (어르신용 / 보호자용 안내)
                           │
                           ▼
                     Write Result
                           │
                           ▼
                          END
```

시스템 아키텍처의 **오케스트레이터 박스 안에서** 위 에이전트 흐름이 실행됩니다.

| 에이전트 흐름 | 시스템에서 하는 일 |
|---|---|
| START | Streamlit → FastAPI `POST /alert` |
| Weather / Shelter Agent | MCP 도구 호출 → 기상청 API, 쉼터 CSV |
| Profile Agent | SQLite 테스트 프로필 읽기 |
| Validation, Guard | 판정 결과를 SQLite 실행 로그에 기록 |
| Writer / Summary Agent | LLM API 호출 |
| Write Result → END | FastAPI 응답 → Streamlit 카드 표시 |

---

## 4. 에이전트별 역할

| 에이전트 | 주요 역할 | 제한사항 | 주요 출력 |
|---|---|---|---|
| **Orchestrator** | 호출 순서·병렬 실행, Guard 판단, task_id·시도 횟수 관리, 최종 성공·실패 판단 | API 직접 호출 금지, 위험도 직접 판정 금지, 민감정보 전달 금지 | 다음 경로, 실행 상태 |
| **Weather Agent** | 기상청 단기예보·기상특보 조회, 체감온도 계산 | 위험도 판단 금지, 실패 시 예외를 그대로 던짐 | 최고·최저기온, 습도, 풍속, 체감온도, 특보 |
| **Shelter Agent** | 계절에 맞는 쉼터(무더위/한파) 중 가까운 3곳 선정 | 위험도 판단 금지 | 쉼터 이름·주소·거리·운영시간 |
| **Profile Agent** | 취약도(상/중/하) 계산 | 질병 진단 금지, 지병명 전달 금지 | 취약도 |
| **Writer Agent** | 규칙표로 위험도 판정(코드), 행동요령 생성(LLM) | 위험도를 LLM이 정하지 않음, 입력에 없는 장소·수치 생성 금지 | 위험도, 행동요령 3개, 판정 근거 |
| **Summary Agent** | 어르신용·보호자용 안내문 작성(LLM) | 질병·약 조언 금지 | elder_message, guardian_message |

> **원칙: LLM은 판단하지 않고 전달만 한다.** 안전 서비스라 위험도 판정은 일관되고 검증 가능한 코드 규칙으로 처리합니다.

### Profile Agent 입력

| 항목 | 입력 방식 | 비고 |
|---|---|---|
| 나이, 혼자 거주 여부, 지병 유무, 냉난방기 유무 | 테스트 프로필(SQLite) | 가상 인물만 사용 |

```python
def vulnerability(p):
    score = 0
    if p.get("age", 80) >= 75: score += 1
    if p.get("lives_alone", True): score += 1
    if p.get("has_condition", True): score += 1        # 지병 유무만 사용
    if not p.get("has_cooling_heating", False): score += 1
    return "상" if score >= 3 else "중" if score >= 2 else "하"
```
값이 없으면 위험한 쪽을 기본값으로 잡아 보수적으로 판단합니다.

---

## 5. Guard와 Validation

모든 Guard는 **LLM이 아닌 코드 규칙**으로 구현합니다.

### Validation (에이전트 결과 개별 검사 → PASS / RETRY / FAIL)

| 대상 | 검사 내용 | 실패 시 |
|---|---|---|
| Weather | 기온이 -40~50℃ 범위인가 | RETRY |
| Shelter | 쉼터가 1곳 이상인가 | 검색 반경 확대 후 RETRY |
| LLM 출력 | JSON 파싱, 필수 키 존재 여부 | RETRY 1회 → 템플릿 대체 |

- RETRY는 **최대 3회**, 넘으면 FAIL
- FAIL이면 안전 종료 + 기본 안내 문구 + 로그 기록

### Join Guard (결과가 모두 모였는가)

| 상황 | 정책 |
|---|---|
| Weather 최종 실패 (캐시도 없음) | 안전 종료, 기본 안내 |
| Shelter 실패 | "쉼터 정보 없음"으로 진행 |
| Profile 누락 | 취약도 "상"으로 간주하고 진행 |

### Handoff Guard (Orchestration 2로 넘길 가치가 있는가)

- 특보 없음 + 체감온도 정상 + 취약도 하 → **알림 없이 종료**
- 불필요한 알림을 막아 "알림 피로"를 줄입니다.

---

## 6. Handoff 데이터 형식

### SafetyResearchResult (Orchestration 1 → 2)

```json
{
  "task_id": "task-102",
  "attempt": 1,
  "season": "여름",
  "weather": {
    "max_temp": 35.2, "min_temp": 26.1,
    "humidity": 70, "wind_ms": 1.5, "feels_like": 35.2,
    "warning": "폭염경보",
    "base": "20261007 1400",
    "source": "live"
  },
  "shelters": [
    { "name": "○○경로당", "address": "...", "distance_m": 320, "open": "09:00-18:00" }
  ],
  "vulnerability": "상",
  "errors": ["weather: timeout → cache 사용"]
}
```
> 지병명 원문은 넘기지 않고 `vulnerability`만 전달합니다.

### AlertResult (Writer → Summary)

```json
{
  "risk_level": "위험",
  "actions": ["오후 외출 줄이기", "물 자주 마시기", "○○경로당에서 쉬기"],
  "reason": "폭염경보 + 취약도 상",
  "recommended_shelter": "○○경로당",
  "notify_guardian": true
}
```

### 최종 응답 (FastAPI → Streamlit)

```json
{
  "task_id": "task-102",
  "status": "alert",
  "risk_level": "위험",
  "elder_message": "오늘 많이 더워요. 오후에는 ○○경로당에서 쉬세요.",
  "guardian_message": "위험도: 위험 (폭염경보, 혼자 거주). 추천 쉼터: ○○경로당(320m). 안부 전화를 권합니다.",
  "data_source": "cache",
  "base": "20261007 1400",
  "logs": [{ "step": "weather", "attempt": 1, "status": "retry", "error": "timeout" }]
}
```
`status`: `alert` / `no_alert` / `fail`, `data_source`: `live` / `cache`

---

## 7. AutoHealing (장애 감지·복구)

### 장애 유형별 대응

| 장애 상황 | 감지 조건 | 복구 전략 | 최종 실패 시 |
|---|---|---|---|
| 기상청 단기예보 API 장애 | 타임아웃, 5xx, 응답 형식 오류 | 3회 재시도 → SQLite 캐시(마지막 성공 예보) 사용 | 안전 종료 + 기본 안내 |
| 기상특보 API 장애 | 응답 실패 | 기온 기준으로 자체 판정 | — |
| 쉼터 조회 실패 | 결과 0건, 파일 오류 | 검색 반경 확대 → "쉼터 정보 없음" | — |
| LLM 출력 형식 오류 | JSON 파싱 실패, 필수 키 누락 | "JSON으로만 답하라" 1회 재요청 → 고정 템플릿 문구 | — |
| 프로필 정보 누락 | 필수 항목 없음 | 보수적 기본값(취약도 상)으로 진행 | — |

### 재시도 + 캐시 폴백

```python
def with_healing(cache_key, fetch, task_id, step, fault=None, retries=3):
    start = time.time()
    for attempt in range(1, retries + 1):
        try:
            if fault == step:
                raise TimeoutError("주입된 장애")
            result = fetch()
            save_cache(cache_key, result)
            log(task_id, step, attempt, "success", elapsed_ms=elapsed(start))
            return {"data": result, "source": "live"}
        except Exception as e:
            log(task_id, step, attempt, "retry", error=str(e))
            time.sleep(0.5 * attempt)

    cached = load_cache(cache_key)
    if cached:
        log(task_id, step, retries, "fallback", recovery="cache", elapsed_ms=elapsed(start))
        return {"data": cached, "source": "cache"}

    log(task_id, step, retries, "fail")
    raise RuntimeError(f"{step} 복구 실패")
```

### LLM 실패 시 템플릿

```python
FALLBACK = {
  "actions": ["물 자주 마시기", "한낮·새벽 외출 줄이기", "가까운 쉼터 이용하기"],
  "elder_message": "오늘 날씨가 위험해요. 무리하지 마시고 가까운 쉼터에서 쉬세요.",
  "guardian_message": "위험도 {risk_level}. 어르신께 안부 전화를 드려 주세요. 추천 쉼터: {shelter_name}"
}
```

### SQLite 테이블

```sql
CREATE TABLE cache (
  key TEXT PRIMARY KEY,      -- 예: weather_60_127
  value TEXT,                -- JSON
  saved_at TEXT
);

CREATE TABLE run_logs (
  task_id TEXT, step TEXT, attempt INT,
  status TEXT,               -- success / retry / fallback / fail
  error TEXT, recovery TEXT, elapsed_ms INT, created_at TEXT
);
```

- `cache`: 장애 시 꺼내 쓰는 **복구 수단**
- `run_logs`: 자동 복구율·평균 복구시간을 계산하는 **복구 증거**

### 장애 주입

실제 API를 끊지 않고 **코드에서 일부러 예외를 던지는 방식**으로 시연합니다.

| 옵션 | 동작 |
|---|---|
| `weather` | 기상청 API 호출 시 TimeoutError 발생 |
| `llm` | LLM 응답 대신 깨진 문자열 반환 |

### 복구 지표

- **자동 복구율** = 수동 개입 없이 정상 안내까지 전달된 장애 시나리오 수 ÷ 전체 장애 시나리오 수 × 100
- **평균 복구시간** = 자동 복구 성공 시나리오의 복구시간 합계 ÷ 자동 복구 성공 건수

```sql
SELECT AVG(elapsed_ms) FROM run_logs WHERE status = 'fallback';
```

---

## 8. 데이터와 외부 API

| 용도 | 데이터 | 형태 | 장애 시 대체 |
|---|---|---|---|
| 날씨 (기온·습도·풍속) | 기상청 단기예보 조회서비스 | API (공공데이터포털) | SQLite 캐시 |
| 특보 | 기상청 기상특보 조회서비스 | API (공공데이터포털) | 기온 기준 자체 판정 |
| 쉼터 | 행정안전부 무더위쉼터·한파쉼터 | CSV (시연 지역만 추림) | 반경 확대 → "정보 없음" |
| 문장 생성 | LLM | API | 재요청 → 템플릿 |

### 기상청 단기예보 메모

- 인증키는 **Decoding 키**를 `requests`의 `params`에 넣습니다. (Encoding 키는 이중 인코딩 오류 발생)
- `dataType=JSON` 사용
- 위경도 → 격자(nx, ny) 변환 필요. 서울시청(37.5665, 126.9780) → `(60, 127)`이면 정상
- 발표 시각(base_time): 02, 05, 08, 11, 14, 17, 20, 23시, 발표 후 약 10분 뒤 조회 가능. 자정 직후는 전날 23시 처리
- 사용 항목: `TMX`/`TMN`(최고/최저), `TMP`(시간별 기온), `REH`(습도), `WSD`(풍속). TMX·TMN이 없으면 TMP의 최댓값·최솟값 사용
- 체감온도: 여름은 최고기온, 겨울은 풍속 반영

```python
def wind_chill(t, wsd_ms):
    v = wsd_ms * 3.6  # km/h
    return 13.12 + 0.6215*t - 11.37*v**0.16 + 0.3965*v**0.16*t
```

### 쉼터 거리 계산

쉼터 CSV의 위도·경도로 직선거리(하버사인)를 계산해 가까운 3곳을 반환합니다. 외부 지도 API는 사용하지 않습니다.

### 좌표 입력

카카오맵 등 외부 지도 API 없이, 테스트 프로필에 **위도·경도를 직접 저장**해서 사용합니다.

### MCP 도구

```python
from mcp.server.fastmcp import FastMCP
mcp = FastMCP("safety-tools")

@mcp.tool()
def weather(lat: float, lon: float) -> dict:
    return get_weather(lat, lon)

@mcp.tool()
def weather_warning(lat: float, lon: float) -> dict:
    return get_warning(lat, lon)

@mcp.tool()
def shelters(lat: float, lon: float, season: str) -> list:
    return get_shelters(lat, lon, season)
```
함수와 MCP를 분리해 두어, MCP 연결에 문제가 생기면 오케스트레이터가 함수를 직접 호출하도록 되돌릴 수 있습니다.

---

## 9. 위험도 판정 규칙

위험도는 **관심 / 주의 / 경고 / 위험** 4단계입니다.

### 실외 날씨 × 취약도

| 실외 날씨 | 취약도 하 | 중 | 상 |
|---|---|---|---|
| 정상 | 관심 | 관심 | 주의 |
| 주의보 수준 | 주의 | 경고 | 경고 |
| 경보 수준 | 경고 | 위험 | 위험 |

특보가 있으면 특보 등급을 쓰고, 특보 API 장애 시에는 기온 기준으로 주의보/경보 수준을 자체 판정합니다.

> 특보 발령 기준 온도는 기상청 공식 자료에서 최신 기준을 확인해 확정합니다. 확정한 값은 이 표에 기록합니다.

---

## 10. 화면 구성

```
┌─────────────────────────────────────────────┐
│ 사이드바                                        │
│  - 어르신 선택 (테스트 인물 3명)                   │
│  - 계절 선택 (여름 / 겨울)                        │
│  - 장애 주입: □ 기상청 API  □ LLM 형식 오류        │
│  - [알림 확인하기] 버튼                           │
├──────────────────────┬──────────────────────┤
│ 👵 어르신용 카드         │ 👨‍👩‍👧 보호자용 카드        │
│ (큰 글씨, 위험도 색)      │ (위험도, 이유, 쉼터)      │
├──────────────────────┴──────────────────────┤
│ 🔧 실행 과정 (AutoHealing 로그)                  │
│ weather 1회차 실패 → 2회차 실패 → 캐시 사용 ✅       │
│ 데이터 기준: 14시 예보 (캐시)                      │
└─────────────────────────────────────────────┘
```

| 위험도 | 관심 | 주의 | 경고 | 위험 |
|---|---|---|---|---|
| 색상 | 초록 | 노랑 | 주황 | 빨강 |

**안내 문구 기준**
- 어르신용: 90자 이내, 존댓말, 쉬운 말, 숫자 최소화, 가장 중요한 행동 하나 강조
- 보호자용: 위험도, 이유, 추천 쉼터 포함. 경고 이상이면 안부 전화 권장

---

## 11. API 명세

| Method | Endpoint | 설명 |
|---|---|---|
| POST | `/alert` | 프로필·장애 주입 옵션을 받아 전체 흐름 실행 |
| GET | `/health` | 서버 상태 확인 |
| GET | `/logs` | 최근 실행 기록 조회 |

**`POST /alert` 요청 예시**

```json
{
  "person": "profile-01",
  "season": "여름",
  "fault": ["weather"]
}
```

---

## 12. 팀 구성과 역할

| 담당 | 이름 | 맡은 부분 | 산출물 |
|---|---|---|---|
| 팀장 · PM | 기화 | 기획, 일정 관리, 문서 총괄, 발표 / 개발 전반 지원 (통합·장애 시험·막히는 부분 보조) | 산출물 3종 취합·검토, 발표자료, 발표 |
| 오케스트레이터 | 지혜 | FastAPI, 에이전트 흐름 연결, Validation·Join·Handoff Guard, Handoff 스키마 | 멀티 에이전트 아키텍처 설계서 |
| AutoHealing | 상옥 | 재시도·캐시 폴백·템플릿 대체, 장애 주입, SQLite(캐시·로그), 복구 지표 계산 | 배포 및 장애 복구 보고서 |
| 데이터·MCP | 두나 | 기상청 단기예보·특보 API, 격자 변환, 쉼터 CSV, MCP 도구 | 설계서 중 도구 부분 |
| LLM 에이전트 | 해든 | 취약도 계산, 위험도 규칙표, Writer·Summary 프롬프트, 템플릿 문구 | 설계서 중 에이전트 역할 부분 |
| 프런트엔드 | 수언 | Streamlit 화면, 장애 주입·로그 화면, 시연 영상 | 파이프라인 보고서, 시연 영상 |

### 팀원 간 합의 사항

| 누구와 누구 | 합의할 것 |
|---|---|
| PM ↔ 전체 | 일정, 산출물 담당·마감, 문서와 실제 구현이 일치하는지 확인 |
| 오케스트레이터 ↔ 전체 | SafetyResearchResult, AlertResult, `/alert` 요청·응답 형식 |
| 데이터·MCP ↔ AutoHealing | `fetch` 함수 이름과 반환 형식, 실패 시 예외 그대로 던지기 |
| AutoHealing ↔ 오케스트레이터 | `source`(live/cache) 표시, 최종 실패 시 예외로 알리기 |
| LLM ↔ AutoHealing | 필수 키 목록, 템플릿 문구 |
| 프런트 ↔ AutoHealing | 장애 주입 옵션 이름(`weather`, `llm`), 로그 표시 형식 |

---

## 13. 실행 방법

```bash
# 1. 저장소 받기
git clone <저장소 URL>
cd <저장소 폴더>

# 2. 환경변수 설정 (.env는 깃에 올리지 않습니다)
cp .env.example .env
# .env에 KMA_API_KEY, LLM_API_KEY 입력

# 3. 실행
docker-compose up --build
```

| 서비스 | 주소 |
|---|---|
| Streamlit | http://localhost:8501 |
| FastAPI | http://localhost:8000 (`/docs`에서 API 확인) |

**`.env.example`**
```
KMA_API_KEY=
LLM_API_KEY=
API_URL=http://backend:8000
```

> 장애 시험 전에는 정상 실행을 한 번 해서 캐시를 채워 두세요. 캐시가 비어 있으면 폴백이 동작하지 않습니다.

---

## 14. 장애 시험 결과

> 실제로 수행한 시험 결과만 기록합니다.

### 시연 시나리오

1. **정상**: 장애 주입 없이 실행 → 어르신용·보호자용 카드 표시
2. **위험 없음**: 날씨 정상 + 취약도 하 → "알림 보내지 않음" (Handoff Guard)
3. **API 장애**: 기상청 장애 주입 → 재시도 → 캐시 사용 → 정상 안내
4. **LLM 장애**: LLM 장애 주입 → 재요청 → 템플릿 문구로 정상 안내

### 시험 기록표

| Scenario ID | 주입 장애 | 기대 동작 | 실제 동작 | 복구 시간 | 수동 개입 | 판정 | 증빙 |
|---|---|---|---|---|---|---|---|
| DR-API-01 | 기상청 API 타임아웃 | 3회 재시도 → 캐시 사용 → 정상 안내 | | | | | |
| DR-LLM-01 | LLM 출력 형식 깨짐 | 1회 재요청 → 템플릿 → 정상 안내 | | | | | |

### 지표

| 지표 | 값 |
|---|---|
| 자동 복구율 | |
| 평균 복구시간 | |

---

## 15. 보안·개인정보 원칙

- API 키는 `.env`에만 저장하고 저장소에 올리지 않습니다. (`.gitignore`에 `.env` 포함)
- 시연용 프로필은 **가상 인물**만 사용합니다.
- 지병명 원문은 다음 단계로 넘기거나 로그에 남기지 않고, **취약도(상/중/하)만** 전달합니다.
- LLM은 질병 진단이나 약 복용 조언을 하지 않습니다.
- 모든 실행에는 `task_id`를 붙여 로그로 추적합니다.

---

## 실행 정보

| 항목 | 링크 |
|---|---|
| 배포 URL | |
| 저장소 URL | |
| 파이프라인 실행 URL | |
| 시연 영상 | |
