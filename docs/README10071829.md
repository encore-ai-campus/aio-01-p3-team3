# 어르신 날씨 안전 안내 멀티에이전트 계획서 (수정본 v2)

> 원본: `multi_agent_safety_service_plan.md`. 바뀐 곳은 **[v2]** 로 표시했습니다.

## 1. 목표

날씨, 사용자 취약도, 쉼터 정보를 바탕으로 어르신과 보호자에게 폭염·한파 안전 안내를 제공한다.

> 위험도 판정은 일관성과 검증 가능성을 위해 코드가 담당하고, LLM은 판정 결과를 사람이 읽기 쉬운 문장으로 바꾼다.

이 서비스는 질병을 진단하거나 약 복용을 조언하지 않는다. 입력에 없는 장소, 거리, 운영시간, 기상 수치를 생성하지 않는다.

## 2. 전체 구조

**[v2]** 입력은 오케스트레이터(지혜 님)가 Weather·Shelter·Profile 병렬 조사와 Join Guard를 거쳐 넘기는 `SafetyResearchResult`이다. 이 문서는 그 뒤 단계(LLM 파트)를 다룬다.

```text
SafetyResearchResult (오케스트레이터)
            |
            v
 ProfileAgent (code) ----> vulnerability: 상 | 중 | 하
            |
            v
   RiskAgent (code) ----> weather_stage, hazard, risk_level: 관심 | 주의 | 경고 | 위험
            |
            v
 HandoffGuard (code) ---> 관심이면 여기서 종료 (status: no_alert, LLM 호출 없음)   [v2: 위치 이동]
            |
            v
 WriterAgent (LLM) -----> actions[3], reason
            |
            v
 SummaryAgent (LLM) ----> elder_message, guardian_message
            |
            v
 ValidationAgent (code) -> 통과 / 실패 (실패 시 AutoHealing이 재요청 → 그래도 실패하면 Fallback)   [v2]
```

에이전트는 자유롭게 판단하거나 토론하지 않는다. 앞 단계의 구조화된 결과만 받아 자기 역할의 결과만 반환하는 파이프라인형 멀티에이전트다.

## 3. 역할 분담

| 컴포넌트 | 구현 | 책임 | 금지 사항 |
| --- | --- | --- | --- |
| ProfileAgent | 코드 | 사용자 정보로 취약도 계산 | 지병명 해석, LLM 판정 |
| RiskAgent | 코드 | **[v2]** 기온·체감·특보로 날씨 단계 계산, 날씨 단계와 취약도로 위험도 판정 | LLM 응답으로 위험도 변경 |
| HandoffGuard | 코드 | 알림 진행 여부 결정 (**[v2]** Writer 앞) | 위험도 자체 변경 |
| WriterAgent | LLM | 행동요령 3개와 판정 근거 문장 생성 | 위험도 재판정, 의료 조언, 정보 창작 |
| SummaryAgent | LLM | 어르신용/보호자용 안내문 재작성 | 입력에 없는 사실 추가 |
| ValidationAgent | 코드 | JSON 구조와 안전 제약 검사 | **[v2]** 재시도 직접 구현 (AutoHealing 담당) |
| FallbackAgent | 코드 | 재요청까지 실패 시 **[v2] 계절별** 템플릿 출력 | 새 수치나 장소 생성 |

**[v2] AutoHealing(상옥 님)에 넘기는 것**: 검증 함수 `validate_writer()`, `validate_summary()`, 필수 키 목록, 계절별 FALLBACK. 재요청 1회와 로그 기록은 AutoHealing의 `with_healing` 계층에서 감싼다.

## 4. 데이터 계약

**[v2] 값 표기**: 팀 전체가 쓰는 응답 값은 한글로 통일한다. 취약도 `상/중/하`, 위험도 `관심/주의/경고/위험`. (프런트 `COLORS`, 오케스트레이터 `vulnerability` 필드와 맞춤)

### 4.1 공통 입력 (SafetyResearchResult 중 LLM 파트가 쓰는 부분)

```json
{
  "task_id": "task-102",
  "season": "winter",
  "profile": {
    "age": 78,
    "lives_alone": true,
    "has_condition": true,
    "has_cooling": true,
    "has_heating": false
  },
  "weather": {
    "max_temp": -4.0,
    "min_temp": -13.0,
    "min_temp_yesterday": -2.0,
    "min_temp_tomorrow": -12.5,
    "wind_ms": 4.0,
    "feels_like": -20.3,
    "warning": null,
    "base": "20261007 0500"
  },
  "shelters": [
    {"name": "OO 경로당", "address": "...", "distance_m": 320, "open": "09:00-18:00"}
  ]
}
```

**[v2] 바뀐 점**
- `base`는 데이터·MCP와 같은 뜻(예보 발표 시각)으로만 쓴다. 판정 근거 문구는 RiskAgent가 만드는 `stage_label`로 분리.
- `weather_stage`는 입력으로 받지 않고 RiskAgent가 계산한다.
- `feels_like`, `wind_ms`, `min_temp_yesterday`, `min_temp_tomorrow`를 받는다 (한파 판정용).
- 쉼터는 데이터·MCP 형식대로 리스트(최대 3곳)를 받는다.
- `has_cooling_heating` 한 칸을 `has_cooling`, `has_heating` 두 칸으로 나눈다.

`has_condition`은 지병 유무만 사용하며, 질병명은 저장하거나 프롬프트에 전달하지 않는다.

### 4.2 ProfileAgent 출력

```json
{ "vulnerability": "상" }
```

```python
def vulnerability(profile: dict, season: str) -> str:
    score = 0
    if profile.get("age", 80) >= 75:
        score += 1
    if profile.get("lives_alone", True):
        score += 1
    if profile.get("has_condition", True):
        score += 1
    # [v2] 계절에 맞는 설비만 본다
    device = "has_heating" if season == "winter" else "has_cooling"
    if not profile.get(device, False):
        score += 1
    return "상" if score >= 3 else "중" if score >= 2 else "하"
```

누락 정보는 보수적으로 처리한다.

### 4.3 RiskAgent

**[v2] ① 체감온도 (데이터·MCP와 공유할 함수)**

```python
def wind_chill(t: float, wind_ms: float) -> float:
    # 기상청 겨울 체감온도식은 기온 10℃ 이하, 풍속 1.3m/s 이상에서만 쓴다.
    if t > 10 or wind_ms < 1.3:
        return t
    v = wind_ms * 3.6
    return 13.12 + 0.6215 * t - 11.37 * v**0.16 + 0.3965 * v**0.16 * t
```

원본 공식은 조건이 없어 -12℃·무풍이 +5.7℃로 계산됐다.

**[v2] ② 날씨 단계 계산**

기준값은 기상청 특보 기준을 바탕으로 한 초안이며, 코드 상수 한 곳(`STAGE_RULES`)에 둔다. 연동 전 기상청 최신 기준을 확인해 확정한다.

| 단계 | 폭염 (hazard=heat) | 한파 (hazard=cold) |
| --- | --- | --- |
| severe | 폭염경보, 또는 체감 최고 35℃ 이상 | 한파경보, 또는 최저 -15℃ 이하 2일 지속, 또는 전날보다 15℃ 이상 하강하고 3℃ 이하 |
| advisory | 폭염주의보, 또는 체감 최고 33℃ 이상 | 한파주의보, 또는 최저 -12℃ 이하 2일 지속, 또는 전날보다 10℃ 이상 하강하고 3℃ 이하 |
| normal | 그 외 | 그 외 |

- 특보(`warning`)가 있으면 특보가 우선, 없거나 특보 API 장애면 기온으로 자체 판정한다.
- 기상청의 "평년보다 3℃ 낮음" 조건은 평년값 데이터가 없어 생략한다 (보수적으로 알림이 더 나가는 쪽).
- `hazard`는 `season`으로 정한다 (`summer` → heat, `winter` → cold, 그 외 → 기온으로 판단).

**③ 위험도 규칙표** (원본과 같음, 값만 한글)

| 날씨 단계 | 취약도 하 | 취약도 중 | 취약도 상 |
| --- | --- | --- | --- |
| normal | 관심 | 관심 | 주의 |
| advisory | 주의 | 경고 | 경고 |
| severe | 경고 | 위험 | 위험 |

출력:

```json
{
  "hazard": "cold",
  "weather_stage": "advisory",
  "stage_label": "한파주의보 수준",
  "risk_level": "경고",
  "risk_reason": "한파주의보 수준 + 취약도 중"
}
```

WriterAgent와 SummaryAgent는 `risk_level`을 읽기만 하며 변경할 권한이 없다.

### 4.4 HandoffGuard **[v2: Writer 앞으로 이동]**

| 위험도 | 응답 status | 다음 단계 |
| --- | --- | --- |
| 관심 | `no_alert` | 종료. LLM 호출 없음, 화면에 "알림 보내지 않음" |
| 주의 | `alert` | Writer·Summary 진행 |
| 경고 | `alert` | Writer·Summary 진행, 보호자 안부 전화 권고 |
| 위험 | `alert` | Writer·Summary 진행, 보호자 안부 전화 권고, 화면 긴급 표시 |

- 판단 기준은 `risk_level` 하나뿐이다. 원본의 "주의: 선택적 발송"은 동작이 정해져 있지 않아 `alert`로 확정했다.
- 오케스트레이터 설계의 Guard 조건("특보 없음 + 체감 정상 + 취약도 하")을 이 기준으로 바꾸도록 지혜 님과 합의한다.

### 4.5 쉼터 선택 **[v2 신규]**

Writer에는 쉼터 1곳만 넘긴다. 코드에서 고른다.

1. 지금 운영 중인 곳 중 가장 가까운 곳
2. 운영 중인 곳이 없으면 가장 가까운 곳 + `shelter_open_now: false`
3. 쉼터 리스트가 비었으면 `shelter: null`

`shelter_open_now`가 false면 Writer는 "실내에 머무르기"를 우선 안내하고 쉼터는 운영 시작 시각과 함께 쓴다. 한파 위험은 새벽·아침에 크고 이때 경로당은 대부분 닫혀 있기 때문이다.

### 4.6 WriterAgent 계약

입력:

```json
{
  "hazard": "cold",
  "risk_level": "경고",
  "stage_label": "한파주의보 수준",
  "max_temp": -4.0,
  "min_temp": -13.0,
  "feels_like": -20.3,
  "wind_ms": 4.0,
  "shelter_name": "OO 경로당",
  "distance_m": 320,
  "open": "09:00-18:00",
  "shelter_open_now": false
}
```

필수 출력:

```json
{
  "actions": ["새벽 외출을 줄이세요", "모자와 장갑을 하세요", "난방을 꼭 켜 두세요"],
  "reason": "한파주의보 수준 추위와 중간 취약도가 확인되었습니다."
}
```

Writer 프롬프트 규칙:

- 행동요령은 정확히 3개, 각 항목은 20자 이내로 작성한다.
- 어르신이 바로 할 수 있는 행동만 작성한다.
- **[v2]** `hazard`에 맞는 행동만 쓴다. heat이면 수분·그늘·한낮 외출, cold이면 보온·난방·새벽 외출·빙판길.
- **[v2]** 프롬프트에 hazard별 좋은 예시 1개씩을 넣는다.
- 제공된 쉼터, 수치, 운영시간 외의 사실은 언급하지 않는다.
- 질병 진단, 약 복용, 치료 조언을 하지 않는다.
- JSON 객체만 반환한다.

### 4.7 SummaryAgent 계약

입력:

```json
{
  "hazard": "cold",
  "risk_level": "경고",
  "actions": ["새벽 외출을 줄이세요", "모자와 장갑을 하세요", "난방을 꼭 켜 두세요"],
  "shelter_name": "OO 경로당",
  "distance_m": 320,
  "stage_label": "한파주의보 수준"
}
```

필수 출력:

```json
{
  "elder_message": "오늘은 많이 춥습니다. 새벽에는 나가지 마시고 난방을 꼭 켜 두세요.",
  "guardian_message": "위험도: 경고. 한파주의보 수준이며 OO 경로당이 약 320m 거리에 있습니다. 어르신께 안부 전화를 드려 주세요."
}
```

Summary 프롬프트 규칙:

- `elder_message`: 90자 이내, 존댓말과 쉬운 말 사용, 가장 중요한 행동 하나 강조.
- `guardian_message`: 위험도, 이유, 추천 쉼터를 포함. 위험도가 경고 또는 위험이면 안부 전화를 권한다.
- JSON 객체만 반환하고 입력에 없는 사실을 추가하지 않는다.

### 4.8 최종 응답 (프런트로 가는 형식) **[v2 신규]**

프런트 문서의 형식에 `hazard`, `fallback_used`를 더한다.

```json
{
  "task_id": "task-102",
  "status": "alert",
  "hazard": "cold",
  "risk_level": "경고",
  "elder_message": "...",
  "guardian_message": "...",
  "fallback_used": false,
  "data_source": "live",
  "base": "20261007 0500",
  "logs": []
}
```

## 5. 검증과 Fallback

### 5.1 ValidationAgent 검사 항목

Writer 결과:

- `actions`가 문자열 3개로 구성됐는가
- 각 행동요령이 20자 이하인가
- `reason`이 비어 있지 않은가
- 쉼터명이 언급되었다면 입력 쉼터명과 일치하는가
- 금지 의료 표현이 없는가
- **[v2]** 숫자 검사는 기온(℃)과 거리(m)에만 적용한다. 입력에 없는 기온·거리 숫자가 있으면 실패. "오후 2~5시" 같은 시간대 표현은 허용한다.

Summary 결과:

- `elder_message`, `guardian_message`가 모두 존재하는가
- `elder_message`가 90자 이하인가
- `guardian_message`에 위험도가 포함됐는가
- **[v2]** 쉼터가 있을 때만 `guardian_message`에 쉼터명이 포함됐는지 검사한다 (쉼터 없음이 항상 실패로 가지 않게)
- 경고, 위험에서 안부 전화 권고가 포함됐는가

LLM의 JSON 파싱 실패, 필수 키 누락, 위 조건 위반은 모두 검증 실패로 처리한다.

### 5.2 재요청과 Fallback **[v2: 원본의 "재시도 없음, 즉시 템플릿" 변경]**

1. 검증 실패 → AutoHealing이 "JSON 형식으로만 답하라"를 덧붙여 **1회 재요청** (장애 시험 DR-LLM-01)
2. 재요청도 실패 → 계절별 템플릿 사용, `fallback_used: true`

```python
FALLBACK = {
    "heat": {
        "actions": ["물을 자주 드세요", "한낮 외출을 줄이세요", "가까운 쉼터를 이용하세요"],
        "elder_message": "오늘은 더위가 위험합니다. 무리하지 마시고 시원한 곳에서 쉬세요.",
    },
    "cold": {
        "actions": ["새벽 외출을 줄이세요", "모자와 장갑을 하세요", "난방을 꼭 켜 두세요"],
        "elder_message": "오늘은 추위가 위험합니다. 따뜻하게 입으시고 실내에 계세요.",
    },
    "guardian_message": "위험도 {risk_level}. 어르신께 안부 전화를 드려 주세요. 추천 쉼터: {shelter_name}",
}
```

`risk_level`, `shelter_name`은 코드에서 검증된 입력값으로 치환한다. 쉼터 데이터가 없을 때는 "추천 쉼터" 문장을 제거하고, 존재하지 않는 쉼터를 만들지 않는다.

## 6. 구현 순서

### 오늘 저녁: 결정 로직 완성

1. `vulnerability()`, `wind_chill()`, 날씨 단계 계산, 위험도 규칙표를 순수 함수로 구현한다.
2. ProfileAgent, RiskAgent, HandoffGuard 단위 테스트를 작성한다.
3. Writer/Summary는 모의 JSON 응답으로 파이프라인을 연결한다.

### 내일 오전: LLM 연결과 안전장치

1. WriterAgent와 SummaryAgent에 낮은 temperature(0.0-0.3)와 JSON 출력 모드를 적용한다.
2. 검증 함수, 필수 키, 계절별 FALLBACK을 AutoHealing에 넘겨 재요청 계층에 연결한다.
3. 프런트·오케스트레이터와 한글 값, `hazard`, `status` 형식을 맞춘다.

### 내일 오후: 품질과 시연

1. 안내 문장을 다듬고 글자 수를 확인한다.
2. 입력값, 취약도, 위험도, 행동요령, 대상별 요약문을 한 화면에 표시한다.
3. LLM 장애 주입 시 재요청 → fallback 화면이 정상적으로 보이는지 여름·겨울 모두 확인한다.

## 7. 테스트 시나리오 **[v2: 기대값을 하나로 고정, 한파 케이스 추가]**

LLM이 들어가는 시나리오는 5회 반복해 JSON 구조와 문장 제약을 검사한다.

| 시나리오 | 고정 입력 | 기대 코드 판정 | 추가 확인 |
| --- | --- | --- | --- |
| 폭염 고위험 | 여름, 체감 35℃, 취약도 상 | severe → 위험 | 쉼터 허위 생성 없음 |
| 한파 중위험 | 겨울, 최저 -13/-12.5℃ (2일), 취약도 중 | advisory → 경고 | 의료 조언 없음, 여름 문구 없음 |
| 한파 급강하 | 겨울, 전날 최저 8℃ → 오늘 -3℃, 취약도 하 | advisory → 주의 | |
| 바람 없는 한파 | 기온 -12℃, 풍속 0 | 체감 -12℃ (+5.7℃ 아님) | `wind_chill` 회귀 테스트 |
| 새벽, 쉼터 닫힘 | 겨울 05시, 한파경보, 쉼터 운영 전 | severe → 위험 이상, `alert` | "실내에 머무르기" 안내 |
| 쉼터 없음 | 쉼터 리스트 비어 있음 | 판정 그대로 | 검증 통과, 쉼터 문장 없음 |
| 가을 저위험 | 가을, 18℃, 취약도 하 | normal → 관심 | `no_alert`, LLM 호출 0회 |
| LLM 장애 (겨울) | fault=llm, 한파 | 판정 그대로 | 재요청 1회 후 겨울용 fallback |

공통 검사: Writer의 `actions`는 3개이며, Summary의 필수 키가 존재하고 어르신용 문장은 90자 이하다.

## 8. 발표용 설명

"안전 서비스에서는 위험도 판정이 매번 같고 검증 가능해야 하므로, 취약도·날씨 단계·위험도는 코드 규칙으로 계산했습니다. 위험이 없는 날은 LLM을 부르지 않고 끝납니다. LLM은 판정 권한 없이 확정된 결과를 어르신과 보호자가 이해하기 쉬운 문장으로 전달하고, 형식이 깨지면 한 번 다시 요청한 뒤에도 실패하면 계절에 맞는 고정 문구로 대신해 모델 오류가 나도 최소 안전 안내가 전달됩니다."

## 9. 팀 합의 필요 사항 **[v2 신규]**

수정본 중 다른 파트와 맞물리는 항목이다. 합의되면 `상태`를 바꾸고 본문에 반영한다.

### 9.1 바뀐 점과 이유

| # | 바뀐 점 | 이유 |
| --- | --- | --- |
| 1 | 체감온도 공식에 적용 조건 추가 (기온 10℃ 이하, 풍속 1.3m/s 이상) | 조건이 없으면 바람 없는 -12℃가 체감 +5.7℃로 계산돼 한파 알림이 안 나감 |
| 2 | 날씨 단계를 RiskAgent에서 직접 계산 | 계산 담당이 없었고, 한파 판정에 전날 최저기온과 2일 지속 여부가 필요함 |
| 3 | 냉방·난방을 `has_cooling` / `has_heating`으로 분리 | 한 칸이면 난방이 부족한 분이 겨울에 덜 취약하게 나옴 |
| 4 | LLM 대체 문구를 여름용/겨울용으로 분리 | 기존 문구의 "물을 자주 드세요"가 한파 날에도 나감 |
| 5 | 응답에 `hazard`(heat/cold) 추가 | 화면과 보호자 문구에 위험 원인을 표시하기 위해 |
| 6 | 한파 테스트 기대값을 하나로 고정 | "위험 또는 경고"로는 테스트 통과·실패를 판단할 수 없음 |

### 9.2 파트별 확인 질문

| 담당 | 질문 | 관련 절 | 상태 |
| --- | --- | --- | --- |
| 지혜 (오케스트레이터) | Handoff Guard를 위험도 계산 직후로 옮기고, 기준을 "위험도 관심이면 종료" 하나로 바꿔도 되는가? | 2, 4.4 | 미정 |
| 지혜 (오케스트레이터) | 위험도 '주의'도 `alert`로 처리해도 되는가? | 4.4 | 미정 |
| 상옥 (AutoHealing) | LLM 재요청 1회는 `with_healing`에서 감싸고, LLM 파트는 검증 함수·필수 키·계절별 대체 문구만 넘기는 것이 맞는가? | 3, 5.2 | 미정 |
| 상옥 (AutoHealing) | 응답에 `fallback_used`를 추가해도 되는가? | 4.8 | 미정 |
| 두나 (데이터·MCP) | `get_weather` 출력에 `min_temp_yesterday`, `min_temp_tomorrow`를 추가할 수 있는가? | 4.1 | 미정 |
| 두나 (데이터·MCP) | 체감온도 함수에 적용 조건을 넣어 줄 수 있는가? | 4.3 ① | 미정 |
| 두나 (데이터·MCP) | `base`는 예보 발표 시각 뜻으로만 쓰고, 판정 문구는 `stage_label`로 분리해도 되는가? | 4.1 | 미정 |
| 수언 (프런트) | 위험도·취약도 값을 한글(관심/주의/경고/위험, 상/중/하)로 유지하는 것이 맞는가? | 4 | 미정 |
| 수언 (프런트) | `hazard` 값으로 폭염/한파 표시를 넣을 수 있는가? | 4.8 | 미정 |
| 수언 (프런트) | 계절 선택에 "봄·가을"을 추가할 수 있는가? (시연 장면 2번용) | 7 | 미정 |
