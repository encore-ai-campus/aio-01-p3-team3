# 🏠 바이탈·IoT·긴급대응 멀티 에이전트 기반 노인 케어 시스템

> 떨어져 사는 보호자가 어르신의 상태를 한눈에 확인하고, 긴급 상황에는 승인 한 번으로 대응하는 서비스
> — 보호자 승인과 자가 복구(AutoHealing)를 갖춘 멀티 에이전트 케어 시스템

바이탈 사인, 집 안 IoT 기기, CCTV 캡처 이미지를 여러 에이전트가 나눠 살펴보고, 이상이 있으면 조치안을 만들어 **보호자에게 승인을 요청**합니다.
보호자가 승인하면 에어컨 켜기·인덕션 끄기·119 호출 같은 조치를 실행합니다. 센서·기기·LLM에 장애가 나도 재시도·캐시·대체 경로로 스스로 복구하고, 끝까지 복구되지 않으면 보호자에게 직접 조치를 요청합니다.

> ⚠️ 이 프로젝트의 바이탈·기기·CCTV 데이터는 모두 **시연용 mock 데이터**이며, 위험 판정 기준은 **의학적 기준이 아닌 시연용 예시 규칙**입니다.

---

## 목차

1. [프로젝트 개요](#1-프로젝트-개요)
2. [시스템 아키텍처](#2-시스템-아키텍처)
3. [에이전트 흐름](#3-에이전트-흐름)
4. [에이전트별 역할](#4-에이전트별-역할)
5. [Guard·Validation·승인 단계](#5-guardvalidation승인-단계)
6. [Handoff 데이터 형식](#6-handoff-데이터-형식)
7. [AutoHealing (장애 감지·복구)](#7-autohealing-장애-감지복구)
8. [Mock 데이터와 MCP 도구](#8-mock-데이터와-mcp-도구)
9. [위험도 판정 규칙](#9-위험도-판정-규칙)
10. [화면 구성 (보호자 대시보드)](#10-화면-구성-보호자-대시보드)
11. [API 명세](#11-api-명세)
12. [팀 구성과 역할](#12-팀-구성과-역할)
13. [실행 방법](#13-실행-방법)
14. [시연 시나리오와 장애 시험 결과](#14-시연-시나리오와-장애-시험-결과)
15. [보안·개인정보 원칙](#15-보안개인정보-원칙)

---

## 1. 프로젝트 개요

| 구분            | 내용                                                                                                                                                                                                   |
| --------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| 과목 주제       | 에러 자가 치유(AutoHealing) 워크플로우                                                                                                                                                                 |
| 서비스          | 노인 실시간 케어: 바이탈·실내 환경·CCTV 모니터링, 긴급 조치안 생성, 보호자 승인 후 조치 실행                                                                                                           |
| **주요 사용자** | **떨어져 사는 노인 보호자** (자녀, 가족, 돌봄 담당자)                                                                                                                                                  |
| 돌봄 대상       | 혼자 사는 어르신                                                                                                                                                                                       |
| 핵심 원칙       | ① 기기 제어·119 호출 같은 조치는 **보호자 승인 후에만** 실행한다. 단, **바이탈이 매우 위험하면(`VITAL_SEVERE`) 승인 없이 119에 바로 연결**하고 보호자에게 즉시 알린다. ② 장애가 나도 조용히 멈추지 않고, 복구가 안 되면 **보호자에게 직접 알린다**. ③ 정보가 빠지면 더 보수적인 쪽(알리는 쪽)으로 판단한다. |

### 해결하려는 문제

- 보호자는 떨어져 살아서 어르신의 상태를 실시간으로 알기 어렵습니다.
- 바이탈, 집 안 온습도, 가전 상태, CCTV를 각각 따로 확인해야 해서 놓치기 쉽습니다.
- 위급 상황에서 무엇을 해야 할지 판단하고 실행하는 데 시간이 걸립니다.

### 전체 흐름 한 문장

> 보호자가 어르신을 선택하면, 바이탈·IoT(실내 온습도·기기·CCTV)·취약도를 병렬로 확인하고, 이상이 있을 때만 긴급상황 에이전트가 조치안을 만들어 보호자에게 승인을 요청하며, 승인되면 조치를 실행하고 결과를 보호자와 어르신에게 안내한다.

### 역할을 나눈 이유

- 바이탈, 집 안 기기, 프로필은 서로 독립적인 정보라 **병렬로 확인**하면 빠르고, 한쪽 센서가 고장 나도 나머지는 살릴 수 있습니다.
- **판정(코드 규칙)**과 **조치안·문장 작성(LLM)**을 나눠서, 판단은 일관되고 검증 가능하게, 안내는 읽기 쉽게 만듭니다.
- 사람의 판단이 필요한 조치는 **승인 단계**로 분리해서, 에이전트가 마음대로 기기를 끄거나 119에 전화하지 않게 합니다. 예외는 바이탈이 매우 위험해 승인을 기다릴 시간이 없는 경우(119 자동 연결) 하나뿐입니다.

---

## 2. 시스템 아키텍처

```
 frontend 컨테이너          backend 컨테이너                     mcp 컨테이너
┌──────────────┐        ┌───────────────────────┐          ┌────────────────────┐
│  Streamlit   │──HTTP─▶│  FastAPI              │──MCP────▶│  MCP 서버            │
│  보호자 대시보드 │        │  오케스트레이터            │          │  바이탈·IoT·CCTV·     │
│  승인 버튼,    │◀───────│  + 승인 대기 관리          │          │  병원·알림 도구        │
│  장애 주입     │        │  + AutoHealing        │          └────────┬───────────┘
└──────────────┘        │        │              │                   │
                        │        ▼              │                   ▼
                        │  [SQLite] (볼륨)        │      mock_data.py, CCTV 이미지
                        │  캐시, 실행 로그, 프로필    │      (비전 분석은 LLM API 호출)
                        └────────┬──────────────┘
                                 ▼
                             [LLM API]
```

- 재시도·캐시 폴백은 backend의 AutoHealing에서 처리합니다. MCP 서버는 mock 데이터를 돌려주거나 기기 제어를 흉내 내고, 실패하면 예외를 그대로 던집니다.
- 실제 센서·가전·119 연동은 하지 않습니다. 모든 조치는 **로그에 기록하는 mock 동작**입니다.
- SQLite는 backend만 사용하며, 재배포해도 캐시가 남도록 Docker 볼륨에 저장합니다.

| 구성요소   | 기술                                          | 역할                                                                          |
| ---------- | --------------------------------------------- | ----------------------------------------------------------------------------- |
| 프런트엔드 | Streamlit                                     | 보호자 대시보드, 진행 상황 한 줄 표시, 승인/거절, 장애 주입, 로그 표시        |
| 백엔드     | FastAPI                                       | 오케스트레이터, 승인 대기 관리, `/care/run` `/care/approve` `/health` `/logs` |
| 도구 계층  | MCP (FastMCP)                                 | 바이탈·실내 환경·기기·CCTV·병원·알림 도구 (mock)                              |
| DB         | SQLite                                        | 캐시(복구 수단), 실행 로그(복구 증거), 테스트 프로필                          |
| LLM        | (팀에서 사용하는 모델, 이미지 입력 지원 필요) | CCTV 이미지 분석, 조치안 문장, 보호자용·어르신용 안내                         |
| 배포       | Docker Compose + GitHub Actions               | 컨테이너 3개, 테스트 실패 시 배포 차단                                        |

---

## 3. 에이전트 흐름

```
                         START
       (보호자가 어르신 선택 + 시연 시나리오 선택)
                           │
                  [Orchestration 1]
                    Care Monitoring
                           │
                ┌──────────┼──────────┐
                ▼          ▼          ▼
             Vital        IoT       Profile
             Agent       Agent       Agent
          (바이탈 사인) (실내 온습도·  (취약 요인)
                       기기 상태·
                      CCTV 이미지 분석)
                │          │          │
                └──────────┼──────────┘
                           ▼
                Validation (PASS / RETRY / FAIL)
                       Join Guard
                       Aggregator
                           │
                    CareStatusResult
                           │
                     Handoff Guard
                    (정상이면 종료)
                           │
                  [Orchestration 2]
                    Emergency Response
                           │
                    Emergency Agent
   (위험 판정 + 조치안: 기기 제어 / 보호자 알림 / 119 / 병원)
          ※ 바이탈 + 온습도 + 기기 + CCTV 분석 결과를 함께 사용
                           │
                  ★ Approval Gate ★
                    (보호자 승인)
       ※ VITAL_SEVERE면 승인 없이 119 자동 연결 → 보호자 긴급 알림
                  승인 ↙        ↘ 거절
           Action 실행          조치 없이 기록
   (IoT 제어, 알림·119 호출 — mock)
                           │
                     Summary Agent
     (보호자용 결과 보고 + CCTV 캡처 / 어르신용 짧은 안내)
                           │
                     Write Result
                           │
                          END
```

**IoT Agent는 두 번 일합니다.** Orchestration 1에서는 실내 온습도·기기 상태·CCTV를 **읽고**, 승인 후에는 기기를 **제어**합니다. 실내 온습도와 CCTV는 별도 에이전트가 아니라 IoT Agent가 쓰는 도구입니다.

| 에이전트 흐름       | 시스템에서 하는 일                                                                   |
| ------------------- | ------------------------------------------------------------------------------------ |
| START               | Streamlit → FastAPI `POST /care/run`                                                 |
| Vital / IoT Agent   | MCP 도구 호출 → mock 데이터, CCTV 이미지 비전 분석                                   |
| Profile Agent       | SQLite 테스트 프로필 읽기                                                            |
| Validation, Guard   | 판정 결과를 SQLite 실행 로그에 기록                                                  |
| Emergency Agent     | 규칙으로 위험도 판정, LLM으로 조치안 문장 생성                                       |
| Approval Gate       | `status: pending_approval` 반환 → 보호자가 화면에서 승인/거절 → `POST /care/approve`. `auto_119`가 있으면 승인 없이 바로 Action 실행 (`decided_by: "auto"`) |
| Action 실행         | MCP `control_device`, `notify_guardian`, `call_119` (mock)                           |
| Summary Agent → END | LLM으로 안내문 생성 → Streamlit 결과 카드 표시                                       |

---

## 4. 에이전트별 역할

| 에이전트            | 주요 역할                                                                                    | 제한사항                                                             | 주요 출력                                       |
| ------------------- | -------------------------------------------------------------------------------------------- | -------------------------------------------------------------------- | ----------------------------------------------- |
| **Orchestrator**    | 호출 순서·병렬 실행, Guard 판단, 승인 대기 관리, run_id·시도 횟수 관리, 최종 성공·실패 판단 | 도구 직접 호출 금지, 위험도 직접 판정 금지, 승인 없이 조치 실행 금지 (`auto_119` 예외) | 다음 경로, 실행 상태, `current_step`            |
| **Vital Agent**     | 심박, 혈압, 체온, 산소포화도 조회                                                            | 진단 금지, 실패 시 예외를 그대로 던짐                                | 바이탈 수치, 측정 시각                          |
| **IoT Agent**       | 실내 온습도·기기 상태 조회, CCTV 캡처 이미지 분석, 승인된 기기 제어                          | 승인 없는 기기 제어 금지, 이미지에 보이지 않는 내용 추측 금지        | 실내 환경, 기기 상태, CCTV 분석 결과, 제어 결과 |
| **Profile Agent**   | 취약도(상/중/하) 계산                                                                        | 질병 진단 금지, 지병명 전달 금지                                     | 취약도                                          |
| **Emergency Agent** | 규칙표로 위험도·축별 단계·낙상 상태·자동 119 여부 판정(코드), 조치안 작성(LLM), 필요 시 가까운 병원 정보 첨부 | 위험도와 조치 종류를 LLM이 정하지 않음, 입력에 없는 수치·장소 생성 금지 | 위험도, 판정 근거, 조치안 목록, `axes`, `fall_state`, `auto_119` |
| **Summary Agent**   | 보호자용 결과 보고, 어르신용 짧은 안내 작성(LLM)                                             | 질병·약 조언 금지, 어르신용에 CCTV 이미지 포함 금지                  | guardian_message, elder_message                 |

> **원칙: LLM은 판단하지 않고 전달만 한다.** 위험도 판정은 일관되고 검증 가능한 코드 규칙으로 처리하고, LLM은 이미지 설명·조치안 문장·안내문만 만듭니다.

### Profile Agent

```python
def vulnerability(p):
    score = 0
    if p.get("age", 80) >= 75: score += 1
    if p.get("lives_alone", True): score += 1
    if p.get("has_condition", True): score += 1        # 지병 유무만 사용
    if p.get("mobility_limited", True): score += 1     # 거동 불편 여부
    return "상" if score >= 3 else "중" if score >= 2 else "하"
```
값이 없으면 위험한 쪽을 기본값으로 잡아 보수적으로 판단합니다.

---

## 5. Guard·Validation·승인 단계

모든 Guard는 **LLM이 아닌 코드 규칙**으로 구현합니다.

### Validation (에이전트 결과 개별 검사 → PASS / RETRY / FAIL)

| 대상          | 검사 내용                                                                             | 실패 시                 |
| ------------- | ------------------------------------------------------------------------------------- | ----------------------- |
| Vital         | 값이 존재하고 측정 가능한 범위인가 (센서 오류값 걸러내기)                             | RETRY                   |
| IoT 실내 환경 | 온도·습도가 측정 가능한 범위인가                                                      | RETRY                   |
| CCTV 분석     | JSON 파싱, 필수 키(`person_visible`, `posture`, `fall_suspected`, `description`) 존재 | RETRY                   |
| LLM 출력      | JSON 파싱, 필수 키 존재 여부                                                          | RETRY 1회 → 템플릿 대체 |

- RETRY는 **최대 3회**(CCTV 분석은 2회), 넘으면 FAIL
- FAIL이면 해당 정보 없이 진행하거나 안전 종료하고, 보호자에게 알린 뒤 로그에 기록

### Join Guard (결과가 모두 모였는가)

| 상황                          | 정책                                                                            |
| ----------------------------- | ------------------------------------------------------------------------------- |
| Vital 최종 실패 (캐시도 없음) | 안전 종료, 보호자에게 "센서 확인 필요" 알림                                     |
| Vital 캐시 사용               | "n분 전 측정값"으로 표시하고 진행                                               |
| IoT 상태 조회 실패            | 기기 정보 없이 진행, 보호자 화면에 "기기 상태 확인 불가" 표시                   |
| CCTV 분석 실패                | "영상 판단 불가"로 표시하고 바이탈 기준으로만 판정, 캡처 원본은 보호자에게 표시 |
| Profile 누락                  | 취약도 "상"으로 간주하고 진행                                                   |

### Handoff Guard (Orchestration 2로 넘길 가치가 있는가)

- 바이탈 정상 + 실내 환경 정상 + 기기 이상 없음 + 쓰러짐 의심 없음 → **"이상 없음"으로 종료**
- 불필요한 알림을 막아 보호자의 "알림 피로"를 줄입니다.

### Approval Gate (보호자 승인)

| 항목                  | 내용                                                                       |
| --------------------- | -------------------------------------------------------------------------- |
| 승인이 필요한 조치    | 기기 제어(에어컨 켜기, 인덕션 끄기 등), 119 호출                           |
| 승인 없이 하는 일     | 상태 확인, 위험도 판정, 보호자 알림(승인 요청·긴급 알림·정보), 병원 정보 조회 |
| **119 자동 연결**     | `auto_119: "VITAL_SEVERE"`일 때만. 바이탈 위험 범위(3점) 항목 2개 이상 **그리고** 점수 합 7점 이상 **그리고** 최신 측정값(캐시 아님). 승인 화면 없이 119 → 보호자에게 "연락했습니다" 긴급 알림 |
| 승인 화면에 보여줄 것 | 위험도, 판정 근거, 조치안 목록, CCTV 캡처 + 한 문장 설명, 가까운 병원 정보 |
| 승인                  | Action 실행 → Summary → 결과 보고 (`decided_by: "guardian"`)               |
| 거절                  | 조치 없이 "보호자 거절"로 기록 → Summary(보호자용 기록만)                  |

> 캐시(이전 측정값)일 때는 센서 오류일 수 있어 자동 연결하지 않고 승인 요청으로 돌립니다.

---

## 6. Handoff 데이터 형식

### CareStatusResult (Orchestration 1 → 2)

> 형식의 기준은 `backend/src/schemas.py`(지혜)입니다. 아래는 `fall` 시나리오 예시입니다.

```json
{
  "run_id": "run-102",
  "profile_id": "profile-01",
  "scenario": "fall",
  "attempt": 1,
  "vital": {
    "heart_rate": 118,
    "systolic_bp": 120,
    "temperature_c": 36.4,
    "spo2": 96,
    "measured_at": "10:42"
  },
  "indoor_environment": { "temperature_c": 25, "humidity_percent": 50 },
  "devices": {
    "air_conditioner": "off",
    "induction": "off",
    "induction_minutes": null,
    "induction_temperature": null
  },
  "cctv": {
    "image_path": "assets/cctv/fall.jpg",
    "person_visible": true,
    "posture": "fallen",
    "fall_suspected": true,
    "confidence": 0.9,
    "description": "거실 바닥에 사람이 쓰러져 있는 것으로 보입니다.",
    "status": "analyzed"
  },
  "vulnerability": "상",
  "area": "서울 ○○구",
  "source": "live",
  "errors": []
}
```
> 지병명 원문은 넘기지 않고 `vulnerability`만, CCTV는 이미지 자체가 아니라 **파일 경로와 분석 결과만** 전달합니다.
> `source`: `live`(실시간) / `cache`(이전 측정값) / `mock` / `mixed`. CCTV `status`: `analyzed` / `unavailable` / `failed`.

### EmergencyResult (Emergency Agent → Approval Gate)

```json
{
  "run_id": "run-102",
  "risk_level": "위급",
  "reasons": ["CCTV 쓰러짐 의심", "심박·혈압 변화"],
  "axes": { "fall": "위급", "cardio": "주의", "respiratory": "정상", "environment": "정상" },
  "fall_state": "confirmed",
  "auto_119": null,
  "proposed_actions": [
    { "tool": "call_119", "description": "119에 연락합니다", "arguments": { "message": "거실 쓰러짐 의심" }, "needs_approval": true },
    { "tool": "find_hospital", "description": "가까운 응급실: ○○병원 (1.2km)", "arguments": { "area": "서울 ○○구" }, "needs_approval": false },
    { "tool": "notify_guardian", "description": "보호자에게 승인 요청", "arguments": { "message": "승인이 필요합니다" }, "needs_approval": false }
  ],
  "requires_approval": true,
  "cctv_summary": "거실 바닥에 사람이 쓰러져 있는 것으로 보입니다."
}
```
- `axes`: 판정 축 4개(`fall` 낙상 / `cardio` 심뇌 / `respiratory` 호흡 / `environment` 환경)별 단계. 최종 위험도는 가장 높은 축 + 취약도 보정 (9장)
- `fall_state`: `none` / `false_alarm`(오탐 가능) / `suspected`(의심) / `confirmed`(확인) / `critical`(위급)
- `auto_119`: `"VITAL_SEVERE"`면 승인 없이 119 자동 연결, 아니면 `null`

### 응답 1: 승인 대기 (`POST /care/run`)

```json
{
  "run_id": "run-102",
  "status": "pending_approval",
  "current_step": "바이탈 확인 → IoT·CCTV 확인 → 위험 판정 완료 → 보호자 승인 대기",
  "care_status": { "...": "위 CareStatusResult" },
  "emergency": { "...": "위 EmergencyResult" },
  "message": null,
  "approved": null,
  "decided_by": null
}
```

### 응답 2: 최종 결과 (`POST /care/approve`)

요청: `{ "run_id": "run-102", "decision": "approve" }` (거절은 `"reject"`)

```json
{
  "run_id": "run-102",
  "status": "done",
  "current_step": "보호자 승인 → 119 호출(mock) 완료 → 안내 전송",
  "actions": [
    { "tool": "call_119", "status": "success", "message": "119 호출(mock) 완료", "recovery": null },
    { "tool": "notify_guardian", "status": "success", "message": "보호자 알림 전송", "recovery": null }
  ],
  "guardian_message": "어르신 댁 거실에서 쓰러짐이 의심되어 승인하신 대로 119에 연락했습니다. 가까운 응급실: ○○병원(1.2km).",
  "elder_message": "곧 도움이 도착해요. 움직이지 말고 기다려 주세요.",
  "approved": true,
  "decided_by": "guardian"
}
```

### 응답 3: 119 자동 연결 (`POST /care/run`, `critical` 시나리오)

`auto_119`가 있으면 승인 대기 없이 `/care/run` 한 번에 최종 결과까지 돌려줍니다.

```json
{
  "run_id": "run-105",
  "status": "done",
  "current_step": "바이탈 확인 → 위험 판정(바이탈 매우 위험) → 119 자동 연결(mock) → 보호자 긴급 알림",
  "care_status": { "...": "CareStatusResult" },
  "emergency": { "risk_level": "위급", "auto_119": "VITAL_SEVERE", "requires_approval": false, "...": "" },
  "message": "바이탈 여러 항목이 매우 위험해 보호자 승인 없이 119에 연락했습니다.",
  "approved": null,
  "decided_by": "auto"
}
```
- `status`: `no_issue` / `pending_approval` / `done` / `rejected` / `fail`
- `decided_by`: `guardian`(보호자 결정) / `auto`(119 자동 연결)
- `ActionResult.status`: `success` / `failed` / `skipped`

---

## 7. AutoHealing (장애 감지·복구)

### 장애 유형별 대응 (fault → retry → 마지막엔 fail)

| ID           | 장애 상황                         | 감지 조건                    | 복구 전략                                                | 최종 실패 시                                                                         |
| ------------ | --------------------------------- | ---------------------------- | -------------------------------------------------------- | ------------------------------------------------------------------------------------ |
| DR-VITAL-01  | 바이탈 센서 응답 없음             | 타임아웃, 값 누락            | 3회 재시도 → 마지막 측정값(캐시) 사용 + "n분 전 값" 표시 | 보호자에게 "센서 확인 필요" 알림                                                     |
| DR-IOT-01    | 기기 제어 실패 (에어컨이 안 켜짐) | 제어 결과 실패, 상태 미변경  | 3회 재시도                                               | **FAIL** → 보호자에게 "직접 조치 필요" 알림                                          |
| DR-VISION-01 | CCTV 이미지 분석 실패             | 응답 없음, JSON 형식 오류    | 2회 재시도                                               | "영상 판단 불가" 표시, 바이탈 기준으로만 판정, 보호자에게 원본 캡처로 직접 확인 요청 |
| DR-LLM-01    | 조치안·안내문 출력 형식 오류      | JSON 파싱 실패, 필수 키 누락 | "JSON으로만 답하라" 1회 재요청 → 고정 템플릿 문구        | —                                                                                    |

DR-IOT-01은 **"끝까지 복구가 안 되면 사람에게 넘긴다"**를 보여주는 시나리오입니다.

### 재시도 + 캐시 폴백

```python
def with_healing(cache_key, fetch, run_id, step, fault=None, retries=3, use_cache=True):
    start = time.time()
    for attempt in range(1, retries + 1):
        try:
            if fault == step:
                raise TimeoutError("주입된 장애")
            result = fetch()
            if use_cache:
                save_cache(cache_key, result)
            log(run_id, step, attempt, "success", elapsed_ms=elapsed(start))
            return {"data": result, "source": "live"}
        except Exception as e:
            log(run_id, step, attempt, "retry", error=str(e))
            time.sleep(0.5 * attempt)

    cached = load_cache(cache_key) if use_cache else None
    if cached:
        log(run_id, step, retries, "fallback", recovery="cache", elapsed_ms=elapsed(start))
        return {"data": cached, "source": "cache"}

    log(run_id, step, retries, "fail")
    raise RuntimeError(f"{step} 복구 실패")
```
- 바이탈 조회: `use_cache=True` (마지막 측정값으로 대체)
- 기기 제어: `use_cache=False` (제어는 캐시로 대신할 수 없으므로 실패 시 보호자에게 넘김)

### LLM 실패 시 템플릿

```python
FALLBACK = {
  "guardian_message": "어르신 상태 확인이 필요합니다. 위험도 {risk_level}. 판정 근거: {reason}. 화면에서 상세 내용을 확인해 주세요.",
  "elder_message": "보호자에게 연락했어요. 편하게 계시고 무리하지 마세요."
}
```

### SQLite 테이블

```sql
CREATE TABLE cache (
  key TEXT PRIMARY KEY,      -- 예: vitals_person01
  value TEXT,                -- JSON
  saved_at TEXT
);

CREATE TABLE run_logs (
  run_id TEXT, step TEXT, attempt INT,
  status TEXT,               -- success / retry / fallback / fail / approved / rejected
  error TEXT, recovery TEXT, elapsed_ms INT, created_at TEXT
);
```

- `cache`: 장애 시 꺼내 쓰는 **복구 수단**
- `run_logs`: 자동 복구율·평균 복구시간 계산과 승인 이력 기록에 쓰는 **복구 증거**

### 장애 주입

실제로 무언가를 끊지 않고 **코드에서 일부러 예외를 던지는 방식**으로 시연합니다.

| 옵션     | 동작                                     |
| -------- | ---------------------------------------- |
| `vital`  | 바이탈 조회 시 TimeoutError 발생         |
| `iot`    | 기기 제어 시 실패 반환                   |
| `vision` | CCTV 분석 시 깨진 응답 반환              |
| `llm`    | 조치안·안내문 응답 대신 깨진 문자열 반환 |

### 복구 지표

- **자동 복구율** = 수동 개입 없이 정상 결과까지 전달된 장애 시나리오 수 ÷ 전체 장애 시나리오 수 × 100
- **평균 복구시간** = 자동 복구 성공 시나리오의 복구시간 합계 ÷ 자동 복구 성공 건수

```sql
SELECT AVG(elapsed_ms) FROM run_logs WHERE status = 'fallback';
```

---

## 8. Mock 데이터와 MCP 도구

### mock_data.py

시나리오별 데이터를 파이썬 파일 하나에 넣고, MCP 도구는 이 값을 읽기만 합니다.
데이터 시나리오는 `normal`, `heat`, `induction`, `fall`, `critical` **5개**입니다. 시나리오별 프로필·기대 결과는 [docs/scenarios.md](docs/scenarios.md)에 정리되어 있습니다.

필드 이름은 `schemas.py`의 `VitalData`, `IndoorEnvironment`, `DeviceStatus`를 그대로 씁니다.

```python
OFF = {"air_conditioner": "off", "induction": "off",
       "induction_minutes": None, "induction_temperature": None}

def vital(hr, sbp, temp, spo2):
    return {"heart_rate": hr, "systolic_bp": sbp, "temperature_c": temp, "spo2": spo2}

def room(temp, humidity):
    return {"temperature_c": temp, "humidity_percent": humidity}

SCENARIOS = {
  "normal":    {"vital": vital(72, 125, 36.5, 98),  "indoor_environment": room(24, 50),
                "devices": OFF, "cctv": "assets/cctv/normal.jpg"},
  "heat":      {"vital": vital(105, 140, 37.8, 96), "indoor_environment": room(33, 75),
                "devices": OFF, "cctv": "assets/cctv/normal.jpg"},
  "induction": {"vital": vital(80, 130, 36.6, 97),  "indoor_environment": room(26, 55),
                "devices": {"air_conditioner": "off", "induction": "on",
                            "induction_minutes": 120, "induction_temperature": 300},
                "cctv": "assets/cctv/kitchen_empty.jpg"},
  "fall":      {"vital": vital(118, 120, 36.4, 96), "indoor_environment": room(25, 50),   # 심박만 변화
                "devices": OFF, "cctv": "assets/cctv/fall.jpg"},
  "critical":  {"vital": vital(140, 85, 36.0, 88),  "indoor_environment": room(25, 50),   # 위험 범위 3개
                "devices": OFF, "cctv": "assets/cctv/lying.jpg"},
}
```
> 수치는 시연용 가상값입니다. 혈압은 수축기(`systolic_bp`)만 씁니다.

### 테스트 프로필 (가상 인물)

| ID           | 이름 (가상) | 나이 | 혼자 거주 | 지병 | 거동 불편 | 취약도 |
| ------------ | ----------- | ---- | --------- | ---- | --------- | ------ |
| `profile-01` | 어르신 A    | 84   | ✅         | ✅    | ✅         | 상     |
| `profile-02` | 어르신 B    | 78   | ✅         | ❌    | ❌         | 중     |
| `profile-03` | 어르신 C    | 70   | ✅         | ❌    | ❌         | 하     |

### MCP 도구

| MCP 도구                                 | 사용 에이전트 | 역할                                                         |
| ---------------------------------------- | ------------- | ------------------------------------------------------------ |
| `get_vitals(person_id)`                  | Vital         | 바이탈 조회                                                  |
| `get_indoor_env(home_id)`                | IoT           | 실내 온습도                                                  |
| `get_device_status(home_id)`             | IoT           | 기기 상태                                                    |
| `capture_cctv(home_id)`                  | IoT           | CCTV 캡처 이미지 경로 반환 (시나리오별로 미리 준비한 이미지) |
| `analyze_cctv(image_path)`               | IoT           | 이미지를 LLM(비전)에 넣어 상황 판단                          |
| `control_device(device, action)`         | IoT (승인 후) | 에어컨 켜기, 인덕션 끄기 등 (mock)                           |
| `find_hospital(area)`                    | Emergency     | 가까운 병원 정보 (mock 목록)                                 |
| `notify_guardian(msg)` / `call_119(msg)` | Action 실행   | 알림·호출 (실제 전송 없이 로그만)                            |

### CCTV 이미지 분석

CCTV 캡처처럼 보이는 이미지를 시나리오별로 미리 준비해 두고, `analyze_cctv`가 이미지 입력을 지원하는 LLM에 넣어 상황을 판단합니다.

**준비할 이미지** (`assets/cctv/`)

| 파일                | 장면                                      |
| ------------------- | ----------------------------------------- |
| `normal.jpg`        | 거실에 어르신이 앉아 있음                 |
| `kitchen_empty.jpg` | 주방에 사람 없음 (인덕션 켜짐 시나리오용) |
| `fall.jpg`          | 바닥에 쓰러져 있음                        |
| `lying.jpg`         | 침대나 소파에 누워 움직임 없음            |

실제 CCTV 영상이나 모르는 사람의 사진은 쓰지 않고, 팀원이 연출해 찍은 사진이나 일러스트를 사용합니다. 화면 위쪽에 날짜·시각과 `CAM 01` 같은 글씨를 넣고 흑백·저화질로 바꿔 CCTV 캡처처럼 만듭니다.

**프롬프트**
```
너는 어르신 돌봄용 CCTV 화면을 확인하는 도우미다.
이미지에 보이는 것만 근거로 판단한다. 보이지 않는 것은 추측하지 않는다.
아래 JSON 형식으로만 답한다.

{"person_visible": true/false,
 "posture": "standing" | "sitting" | "lying" | "fallen" | "none",
 "fall_suspected": true/false,
 "description": "보호자에게 보여줄 한 문장 설명"}
```

**결과 사용**
- `posture: "fallen"`이고 신뢰도가 낮지 않으면 낙상 축이 **위급**이 됩니다(바이탈과 상관없음). 흐린 사진이나 자세와 플래그가 어긋나면 "낙상 의심(확인 필요)"으로 **경고**입니다. (9장)
- 승인 화면과 보호자용 결과에 **캡처 이미지 + 한 문장 설명**을 함께 보여줘서, 보호자가 눈으로 확인하고 승인할 수 있게 합니다.
- 판단은 "의심" 수준으로만 표현하고 확진처럼 쓰지 않습니다.

---

## 9. 위험도 판정 규칙

위험도는 **정상 / 주의 / 경고 / 위급** 4단계이며, Emergency Agent가 코드 규칙으로 판정합니다.

> 아래 기준은 **시연용 예시 규칙**이며 의학적 기준이 아닙니다. 구현은 `backend/src/rules/risk.py`(해든)입니다. 출처(NEWS2 RCP 2017, 질병관리청, WHO)는 발표 전 원문을 확인합니다.

### 바이탈 점수 (NEWS2 기반)

항목마다 0~3점. **3점 = 위험 범위**, 1~2점 = 바이탈 변화.

| 항목                           | 0점        | 1점                  | 2점       | 3점 (위험 범위)  |
| ------------------------------ | ---------- | -------------------- | --------- | ---------------- |
| 심박 `heart_rate` (회/분)      | 51~90      | 41~50, 91~110        | 111~130   | ≤40, ≥131        |
| 수축기 혈압 `systolic_bp`      | 111~219    | 101~110              | 91~100    | ≤90, ≥220        |
| 체온 `temperature_c` (℃)       | 36.1~38.0  | 35.1~36.0, 38.1~39.0 | 39.1~39.9 | ≤35.0, ≥40.0     |
| 산소포화도 `spo2` (%)          | ≥96        | 94~95                | 92~93     | ≤91              |

체온 40.0℃ 이상을 3점으로 둔 것만 NEWS2 원표와 다릅니다 (질병관리청 열사병 기준).

### 실내 온도·기기 기준

| 항목                           | 기준                                                                     |
| ------------------------------ | ------------------------------------------------------------------------ |
| 실내 이상                      | 28℃ 초과 또는 20℃ 미만                                                   |
| 실내 극한                      | 31℃ 초과 또는 18℃ 미만                                                   |
| 에어컨 목표 온도               | 4~10월 24~26℃, 11~3월 20~22℃ (고온이면 상한으로 냉방, 저온이면 하한으로 난방) |
| 인덕션 방치                    | CCTV에 사람 없음 + `induction == "on"` + (`induction_minutes ≥ 60` 또는 `induction_temperature ≥ 250`) |

### 판정 축 4개

원인마다 축과 단계를 매기고, **최종 위험도 = 가장 높은 축** (+ 축을 넘는 규칙) **+ 취약도 보정**입니다. 바이탈이 정상이어도 낙상 축만으로 위급이 될 수 있습니다.

| 축                      | 원인                                                         | 단계 |
| ----------------------- | ------------------------------------------------------------ | ---- |
| `fall` 낙상             | CCTV가 쓰러진 자세를 분명히 봄 (`FALL_DETECTED`)             | 위급 |
|                         | 흐린 사진·자세와 플래그 불일치 등 약한 신호 (`FALL_SUSPECTED`) | 경고 |
|                         | 낙상 의심 + 바이탈 위험 범위 (`FALL_WITH_VITAL_DANGER`)      | 위급 |
| `cardio` 심뇌           | 심박·혈압 3점 / 1~2점                                        | 경고 / 주의 |
| `respiratory` 호흡      | 산소포화도 3점 / 1~2점                                       | 경고 / 주의 |
| `environment` 환경      | 체온 3점 / 1~2점                                             | 경고 / 주의 |
|                         | 실내 극한                                                    | 경고 |
|                         | 실내 이상 + 바이탈 변화 / 실내 이상만                        | 경고 / 주의 |
|                         | 인덕션 방치                                                  | 주의 |
| **축을 넘는 규칙**      | 위험 범위(3점) 항목 2개 이상 (`VITAL_DANGER_MULTI`)          | 위급 |

- **낙상 상태** (`fall_state`): `none` / `false_alarm`(오탐 가능, 기록만) / `suspected`(의심) / `confirmed`(확인) / `critical`(낙상 + 바이탈 위험)
- **취약도 보정**: 취약도 "상"(또는 프로필 없음)이면 한 단계 올립니다 (최대 "위급"). 단, **정상은 올리지 않습니다.**
- **정보 누락**: 바이탈 FAIL → 안전 종료(Join Guard), CCTV 판단 불가 → 바이탈만으로 판정, 프로필 없음 → 취약도 "상"

### 119 자동 연결 (`auto_119`)

다음을 **모두** 만족하면 보호자 승인 없이 119에 바로 연결합니다 (`VITAL_SEVERE`).

1. 최종 위험도가 위급
2. 바이탈 위험 범위(3점) 항목 2개 이상
3. 바이탈 4항목 점수 합 7점 이상
4. 최신 측정값 (`source`가 `cache`가 아님. 이전 측정값은 센서 오류일 수 있음)

그 밖의 119는 모두 보호자 승인을 받습니다.

### 원인별 조치안 (코드가 정하고, LLM은 설명만 씀)

| 원인                                                   | 조치안                                  | 승인 필요 |
| ------------------------------------------------------ | --------------------------------------- | --------- |
| `VITAL_SEVERE`                                         | 119 자동 연결                           | ❌ (자동) |
| 낙상 축 위급, 위험 범위 2개 이상                       | 119 호출                                | ✅         |
| 실내 이상·극한 (고온)                                  | 에어컨 냉방 (목표 온도 상한)            | ✅         |
| 실내 이상·극한 (저온)                                  | 에어컨 난방 (목표 온도 하한)            | ✅         |
| 인덕션 방치                                            | 인덕션 끄기                             | ✅         |
| 119를 부르거나, 바이탈 위험 범위(3점) + 경고 이상      | 가까운 병원 정보 (`find_hospital`)      | ❌         |
| 정상이 아닌 모든 경우                                  | 보호자 알림 (승인 요청 / 긴급 알림 / 정보) | ❌      |

### 시나리오별 기대 결과

자세한 계산은 [docs/scenarios.md](docs/scenarios.md)에 있습니다.

| 시나리오    | 프로필 (취약도)   | 판정 근거                                   | 최종 위험도       | 조치안                                           |
| ----------- | ----------------- | ------------------------------------------- | ----------------- | ------------------------------------------------ |
| `normal`    | `profile-01` (상) | 이상 없음                                   | 정상 (보정 안 함) | 없음                                             |
| `heat`      | `profile-02` (중) | 실내 온도 극한(33℃) + 심박·혈압 변화         | 경고              | 에어컨 냉방 ✅ / 보호자 알림                       |
| `induction` | `profile-03` (하) | 사람 없는 곳에서 인덕션 오래 켜짐            | 주의              | 인덕션 끄기 ✅ / 보호자 알림                       |
| `fall`      | `profile-01` (상) | **CCTV 쓰러짐 의심** + 심박·혈압 변화        | 위급              | 119 호출 ✅ / 병원 정보 / 보호자 알림              |
| `critical`  | `profile-01` (상) | 심박·혈압·산소포화도 위험 범위 (점수 합 10)  | 위급              | **119 자동 연결** / 병원 정보 / 보호자 긴급 알림   |

`fall`은 바이탈만 보면 "주의"지만 CCTV 분석 결과로 "위급"이 됩니다.

---

## 10. 화면 구성 (보호자 대시보드)

```
┌──────────────────────────────────────────────────┐
│ 진행: 바이탈 확인 → IoT·CCTV 확인 → 위험 판정 → 승인 대기   │  ← 한 줄 진행 표시
├──────────────────────────────────────────────────┤
│ 사이드바                                              │
│  - 어르신 선택 (테스트 인물)                             │
│  - 시나리오 선택 (normal / heat / induction / fall …)   │
│  - 장애 주입: □ 바이탈 □ IoT □ CCTV 분석 □ LLM           │
│  - [상태 확인하기] 버튼                                  │
├────────────────┬────────────────┬────────────────┤
│ ❤️ 바이탈 카드     │ 🏠 실내·기기 카드    │ 📷 CCTV 캡처       │
│ 심박·혈압·체온·SpO2│ 온습도, 에어컨·인덕션 │ 이미지 + 분석 한 문장 │
├────────────────┴────────────────┴────────────────┤
│ 🚨 위험도: 위급 (빨강)  판정 근거: …                       │
│ 조치안: 119 호출 / ○○병원 응급실 정보                      │
│            [ 승인 ]   [ 거절 ]                          │
├──────────────────────────────────────────────────┤
│ ✅ 실행 결과 / 보호자용 보고 / 어르신 안내 미리보기            │
├──────────────────────────────────────────────────┤
│ 🔧 실행 과정 (AutoHealing 로그)                          │
│ vital 1회차 실패 → 2회차 실패 → 캐시 사용 ✅                │
└──────────────────────────────────────────────────┘
```

| 위험도 | 정상 | 주의 | 경고 | 위급 |
| ------ | ---- | ---- | ---- | ---- |
| 색상   | 초록 | 노랑 | 주황 | 빨강 |

**안내 문구 기준**
- 보호자용(주 사용자): 위험도, 판정 근거, 실행한 조치와 결과, CCTV 설명, 병원 정보, 필요한 다음 행동

---

## 11. API 명세

| Method | Endpoint        | 설명                                                                        |
| ------ | --------------- | --------------------------------------------------------------------------- |
| POST   | `/care/run`     | 모니터링 → 위험 판정 → 조치안 생성. 조치가 필요하면 `pending_approval` 반환 (`auto_119`면 바로 실행 후 `done`) |
| POST   | `/care/approve` | 보호자 승인/거절 처리 → 조치 실행 → 결과 반환                               |
| GET    | `/health`       | 서버 상태 확인                                                              |
| GET    | `/logs`         | 최근 실행 기록 조회                                                         |

**`POST /care/run` 요청 예시**

```json
{
  "profile_id": "profile-01",
  "scenario": "fall",
  "fault": ["vision"]
}
```
- `scenario`: `normal` / `heat` / `induction` / `fall` / `critical`
- `fault` (선택): `vital` / `iot` / `vision` / `llm`. 생략하면 장애 없이 실행

**`POST /care/approve` 요청 예시**

```json
{
  "run_id": "run-102",
  "decision": "approve"
}
```
- `decision`: `approve` / `reject`

---

## 12. 팀 구성과 역할

| 담당           | 이름 | 맡은 부분                                                                                                                | 산출물                               |
| -------------- | ---- | ------------------------------------------------------------------------------------------------------------------------ | ------------------------------------ |
| 팀장 · PM      | 기화 | 기획, 일정 관리, 문서 총괄, 발표, 시나리오 5개 확정, CCTV 시연 이미지 준비 / 개발 전반 지원                              | 산출물 3종 취합·검토, 발표자료, 발표 |
| 오케스트레이터 | 지혜 | FastAPI, 에이전트 흐름 연결, Validation·Join·Handoff Guard, Approval Gate 백엔드(승인 대기 저장, `/care/approve` API), CareStatusResult 스키마 | 멀티 에이전트 아키텍처 설계서        |
| AutoHealing    | 상옥 | 재시도·캐시 폴백·템플릿 대체, 장애 주입(`vital`, `iot`, `vision`, `llm`), SQLite(캐시·로그), 복구 지표 계산              | 배포 및 장애 복구 보고서             |
| 데이터·MCP     | 두나 | `mock_data.py`, MCP 도구 9개 (해든이 만든 CCTV 분석 함수를 `analyze_cctv` 도구로 등록), **승인 화면** (`approval.py`: 위험도·조치안·CCTV 캡처 표시, 승인/거절 버튼, `/care/run` → `/care/approve` 2단계 호출, 승인 대기 상태 관리) | 설계서 중 도구 부분                  |
| LLM 에이전트   | 해든 | 취약도 계산, 위험도 규칙표, Emergency 조치안 프롬프트, Summary 프롬프트, 템플릿 문구, **CCTV 분석 전체** (분석 함수, 비전 모델 호출, CCTV 분석 프롬프트, 분석 결과 JSON 형식 정의) | 설계서 중 에이전트 역할·CCTV 분석 부분 |
| 프런트엔드     | 수언 | 보호자 대시보드 레이아웃(메인 화면, 두나의 `approval.py`를 불러와 배치), 진행 한 줄 표시, 바이탈·기기·CCTV 카드, 로그 화면, 시연 영상 (UI 먼저 → 기능 연결) | 파이프라인 보고서, 시연 영상         |

### 팀원 간 합의 사항

| 누구와 누구                  | 합의할 것                                                                                          |
| ---------------------------- | -------------------------------------------------------------------------------------------------- |
| PM ↔ 전체                    | 일정, 산출물 담당·마감, 시나리오 목록, 문서와 실제 구현이 일치하는지 확인                          |
| 오케스트레이터 ↔ 전체        | CareStatusResult, EmergencyResult, `/care/run`·`/care/approve` 요청·응답 형식, `current_step` 문구 |
| 데이터·MCP ↔ AutoHealing     | 도구 함수 이름과 반환 형식, 실패 시 예외 그대로 던지기                                             |
| AutoHealing ↔ 오케스트레이터 | `source`(live/cache/mock/mixed) 표시, 최종 실패 시 예외로 알리기                                   |
| LLM ↔ 데이터·MCP             | CCTV 분석 함수 이름·입출력 형식, MCP 서버 안 파일 위치 (해든은 분석 함수, 두나는 도구 등록만), 사용할 LLM 모델과 키 설정 |
| LLM ↔ 오케스트레이터         | CCTV 분석 결과 JSON 형식 (CareStatusResult의 `cctv` 필드)                                          |
| LLM ↔ AutoHealing            | 필수 키 목록, 템플릿 문구                                                                          |
| 승인 화면(두나) ↔ 오케스트레이터 | 승인 대기 응답 형식(`pending_approval`), 승인/거절 요청 형식                                   |
| 프런트 ↔ 승인 화면(두나)     | `approval.py` 함수 이름과 넘겨줄 값, 화면 배치·스타일 통일 (같은 Streamlit 파일을 함께 고치지 않기) |
| 프런트 ↔ 오케스트레이터      | `current_step` 표시 방식, CCTV 이미지 경로를 화면에 표시하는 방법                                  |
| 프런트 ↔ AutoHealing         | 장애 주입 옵션 이름(`vital`, `iot`, `vision`, `llm`), 로그 표시 형식                               |

---

## 13. 실행 방법

```bash
# 1. 저장소 받기
git clone <저장소 URL>
cd <저장소 폴더>

# 2. 환경변수 설정 (서비스별 config/.env, 깃에 올리지 않습니다)
cp frontend/config/.env.example frontend/config/.env
cp backend/config/.env.example backend/config/.env
cp mcp_server/config/.env.example mcp_server/config/.env
# backend/config/.env와 mcp_server/config/.env에 OPENAI_API_KEY 또는 GEMINI_API_KEY 입력
# (mcp_server는 CCTV 이미지 분석에 LLM을 사용합니다)

# 3. 실행 (루트 compose.yml로 컨테이너 3개를 한 번에 띄웁니다)
docker compose up --build
```

| 서비스    | 주소                                         |
| --------- | -------------------------------------------- |
| Streamlit | http://localhost:8501                        |
| FastAPI   | http://localhost:8000 (`/docs`에서 API 확인) |
| MCP 서버  | http://localhost:8010/mcp                    |

**Compose 파일 구분**

| 파일                                           | 용도                                                             |
| ---------------------------------------------- | ---------------------------------------------------------------- |
| `compose.yml` (루트)                           | 로컬 통합 실행용. 서비스 3개, 공용 네트워크, backend SQLite 볼륨 |
| `frontend/deploy/compose.yml` 등 서비스별 파일 | 배포용. GitHub Actions가 서비스별로 빌드·배포                    |

**주요 환경변수**

| 파일                     | 변수                                | 비고                                                                                                       |
| ------------------------ | ----------------------------------- | ---------------------------------------------------------------------------------------------------------- |
| `frontend/config/.env`   | `BACKEND_URL`                       | 루트 compose에서는 `http://backend:8000`으로 자동 설정                                                     |
| `backend/config/.env`    | `MCP_URL`                           | MCP 서버 주소. 루트 compose에서는 `http://mcp:8010/mcp`로 자동 설정                                        |
| `backend/config/.env`    | `OPENAI_API_KEY` / `GEMINI_API_KEY` | 사용하는 LLM의 키 하나                                                                                     |
| `backend/config/.env`    | `DB_PATH`                           | compose에서 `/app/data/app.db`로 자동 설정                                                                 |
| `mcp_server/config/.env` | `OPENAI_API_KEY` / `GEMINI_API_KEY` | CCTV 이미지 분석용 (이미지 입력 지원 모델)                                                                 |

배포 서버에서는 같은 변수를 각 서비스 폴더의 `.env.docker`에 넣습니다.

> 장애 시험 전에는 정상 실행을 한 번 해서 바이탈 캐시를 채워 두세요. 캐시가 비어 있으면 폴백이 동작하지 않습니다.

---

## 14. 시연 시나리오와 장애 시험 결과

> 장애 시험 결과는 실제로 수행한 결과만 기록합니다.

### 시연 시나리오

데이터 시나리오 5개를 보여준 뒤, 같은 시나리오에 장애를 얹어(`fault` 필드) AutoHealing 4종을 **모두** 시연합니다. 장애 주입은 데이터 시나리오가 아니라 요청 옵션이지만, 시연에서는 필수입니다.

| 순서 | 실행                       | 보여줄 장면                                                                                            |
| ---- | -------------------------- | ------------------------------------------------------------------------------------------------------ |
| 1    | `normal`                   | 모두 정상 → Handoff Guard에서 종료, "이상 없음"                                                        |
| 2    | `heat`                     | 실내 극한 고온(33℃) + 심박 변화 → 경고 → 에어컨 냉방 조치안 → 보호자 승인 → 에어컨 켜짐               |
| 3    | `induction`                | CCTV에 주방이 비어 있음 + 인덕션 120분·300℃ → 주의 → 인덕션 끄기 승인                                  |
| 4    | `fall`                     | **CCTV 이미지를 LLM이 분석해 쓰러짐 의심 판단** → 위급 → 캡처와 함께 보호자 승인 요청 → 119 호출(mock) |
| 5    | `critical`                 | 바이탈 위험 범위 3개(점수 합 10) → 위급 → **승인 없이 119 자동 연결** → 보호자에게 긴급 알림           |
| 6    | `heat` + `vital` 장애      | 바이탈 재시도 3회 → 캐시 사용 → "n분 전 측정값"으로 정상 진행 (2번에서 캐시가 채워짐)                  |
| 7    | `heat` + `iot` 장애        | 에어컨 제어 재시도 3회 → FAIL → 보호자에게 "직접 조치 필요"                                            |
| 8    | `critical` + `vision` 장애 | 영상 판단 불가 → 바이탈만으로 위급 판정 → 119 자동 연결 + 원본 이미지로 확인 요청                      |
| 9    | `fall` + `llm` 장애        | 안내문 생성 실패 → 재요청 1회 → 템플릿 문구로 안내                                                     |

4번에서는 화면에 **캡처 이미지 → LLM 분석 결과(한 문장) → 위험도 상승 → 승인 요청**이 한 흐름으로 보이게 합니다.
4번(승인 후 119)과 5번(자동 119)을 이어서 보여주면 "승인이 원칙, 바이탈이 매우 위험할 때만 예외"라는 차이가 드러납니다.
6~9번에서는 화면 아래 AutoHealing 로그에 재시도·폴백·FAIL 과정이 보이게 합니다.

### 시험 기록표

| Scenario ID  | 주입 장애             | 기대 동작                                                         | 실제 동작 | 복구 시간 | 수동 개입 | 판정 | 증빙 |
| ------------ | --------------------- | ----------------------------------------------------------------- | --------- | --------- | --------- | ---- | ---- |
| DR-VITAL-01  | 바이탈 센서 응답 없음 | 3회 재시도 → 캐시 사용 → "n분 전 값"으로 정상 진행                |           |           |           |      |      |
| DR-IOT-01    | 기기 제어 실패        | 3회 재시도 → FAIL → 보호자에게 "직접 조치 필요"                   |           |           |           |      |      |
| DR-VISION-01 | CCTV 분석 실패        | 2회 재시도 → "영상 판단 불가" → 바이탈 기준 판정 + 원본 확인 요청 |           |           |           |      |      |
| DR-LLM-01    | LLM 출력 형식 오류    | 1회 재요청 → 템플릿 → 정상 안내                                   |           |           |           |      |      |

### 지표

| 지표          | 값  |
| ------------- | --- |
| 자동 복구율   |     |
| 평균 복구시간 |     |

---

## 15. 보안·개인정보 원칙

- API 키는 `.env`에만 저장하고 저장소에 올리지 않습니다. (`.gitignore`에 `.env`, `.env.docker` 포함)
- 시연용 프로필은 **가상 인물**만 사용합니다.
- CCTV 시연 이미지는 **팀원이 연출해 찍은 사진이나 일러스트**만 사용합니다.
- 로그에는 CCTV 이미지 자체가 아니라 **파일 경로와 분석 결과만** 기록합니다.
- CCTV 이미지는 보호자 화면에서만 보여주고, 어르신용 안내에는 넣지 않습니다.
- 지병명 원문은 다음 단계로 넘기거나 로그에 남기지 않고, **취약도(상/중/하)만** 전달합니다.
- LLM은 질병 진단이나 약 복용 조언을 하지 않으며, CCTV 판단은 "의심" 수준으로만 표현합니다.
- 기기 제어와 119 호출은 **보호자 승인 없이 실행하지 않습니다.** 예외는 바이탈이 매우 위험할 때(`VITAL_SEVERE`)의 119 자동 연결뿐이며, 이때도 보호자에게 즉시 알립니다.
- 모든 실행에는 `run_id`를 붙여 로그로 추적합니다.

---

## 실행 정보

| 항목                | 링크 |
| ------------------- | ---- |
| 배포 URL            |      |
| 저장소 URL          |      |
| 파이프라인 실행 URL |      |
| 시연 영상           |      |
