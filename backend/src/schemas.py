"""어르신 케어 API와 에이전트 사이에서 사용하는 공통 Pydantic 스키마."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


Scenario = Literal["normal", "heat", "induction", "fall", "critical"]
FaultName = Literal["vital", "iot", "vision", "llm"]
DataSource = Literal["live", "mock", "cache", "mixed"]
RiskLevel = Literal["정상", "주의", "경고", "위급"]
CareStatus = Literal[
    "no_issue",
    "pending_approval",
    "done",
    "rejected",
    "fail",
]
DecidedBy = Literal["guardian", "auto", "timeout"]
ActionTool = Literal[
    "control_device",
    "notify_guardian",
    "call_119",
    "find_hospital",
]
RiskAxis = Literal["fall", "cardio", "respiratory", "environment"]
Auto119Reason = Literal["VITAL_SEVERE"]


# ---------- POST /care/run 요청 ----------

class CareRunRequest(BaseModel):
    # 필수: 대시보드에서 선택한 가상 어르신 ID
    profile_id: str = Field(min_length=1)

    # 필수: 실행할 Mock 시나리오
    scenario: Scenario

    # 선택: 장애 주입 목록. 생략하면 장애 없이 실행
    fault: list[FaultName] = Field(default_factory=list)


# ---------- 두나 담당 MCP 조회 결과 ----------

class VitalData(BaseModel):
    # 팀 합의 센서 오류 범위. 위험도 경계(rules/risk.py)와는 별개다.
    heart_rate: int = Field(ge=20, le=250, description="심박수(회/분)")
    systolic_bp: int = Field(ge=50, le=260, title="최고 혈압")
    temperature_c: float = Field(ge=30, le=43, description="체온(°C)")
    spo2: int = Field(ge=50, le=100, description="산소포화도(%)")

    # 측정 시각이 없는 Mock 상황도 허용
    measured_at: str | None = None


# ---------- POST /vitals/readings 요청 ----------

class VitalReadingCreate(BaseModel):
    """15초 주기로 수신하는 어르신 바이탈 측정 데이터."""

    # 필수: 바이탈 데이터가 속한 어르신 ID. 공백 문자열은 허용하지 않음
    profile_id: str = Field(min_length=1, description="바이탈 데이터가 속한 어르신 ID")

    # 저장 API에도 조회와 동일한 합의 범위를 적용한다.
    heart_rate: int = Field(ge=20, le=250, description="실제 측정한 심박수(회/분)")

    # 선택: 측정 장비나 전송 상황에 따라 값이 없을 수 있음
    systolic_bp: int | None = Field(default=None, ge=50, le=260, title="최고 혈압")
    # 프로젝트 합의 범위 대상은 수축기 혈압이다. 최저혈압 범위는 별도 합의 전이라 유지한다.
    diastolic_bp: int | None = Field(default=None, title="최저 혈압")
    temperature_c: float | None = Field(default=None, ge=30, le=43, description="체온(°C)")
    spo2: int | None = Field(
        default=None,
        ge=50,
        le=100,
        description="산소포화도(%). 값이 있는 경우 합의한 50~100 범위",
    )

    # 필수: HTTP 전송 시각이 아니라 심박수를 실제로 측정한 시각
    measured_at: datetime = Field(
        description="심박수를 실제로 측정한 시각(전송 시각과 다를 수 있음)",
    )

    # 선택: 시나리오별 시뮬레이션 데이터 구분용. 생략하면 일반 수집 데이터로 저장
    scenario: Scenario | None = Field(
        default=None,
        description="시나리오별 측정 데이터인 경우 시나리오 이름",
    )


class VitalReadingResponse(BaseModel):
    """바이탈 데이터 저장 완료 응답."""

    status: Literal["stored"] = Field(
        default="stored",
        description="요청한 바이탈 데이터를 저장했음을 나타내는 상태",
    )
    profile_id: str = Field(description="저장한 바이탈 데이터가 속한 어르신 ID")
    measured_at: datetime = Field(description="저장한 바이탈 데이터의 실제 측정 시각")


class IndoorEnvironment(BaseModel):
    # 팀 합의 센서 오류 범위. 25°C 전후의 실내값도 유효하다.
    temperature_c: float = Field(ge=-10, le=60)
    # 습도만 잘못된 경우 온도를 살리기 위해 선택값으로 표현한다.
    # 범위 판정과 None 정리는 Agent 복구 경로에서 수행한다.
    humidity_percent: float | None = None


class DeviceStatus(BaseModel):
    # 기기 상태 조회 결과에 필요한 값
    air_conditioner: Literal["on", "off", "unknown"]
    induction: Literal["on", "off", "unknown"]

    # 인덕션 작동 시간(분). 꺼져 있거나 시간을 알 수 없으면 None
    induction_minutes: int | None = None

    # 인덕션 온도(℃). 꺼져 있거나 알 수 없으면 None
    induction_temperature: int | None = None


# ---------- 해든 담당 CCTV 분석 결과 ----------

class CctvAnalysis(BaseModel):
    # 캡처된 Mock 이미지 경로. 이미지 파일 자체는 스키마에 담지 않음
    image_path: str | None = None

    # 두나 MCP 계약에서 사용하는 분석 요약
    summary: str | None = None

    # 해든 비전 분석에서 제공하는 관찰 정보
    person_visible: bool | None = None
    posture: Literal["standing", "sitting", "lying", "fallen", "none"] | None = None
    fall_suspected: bool | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)

    # 해든 분석 계약의 설명 필드. summary와 중복되지 않도록 연결 시 매핑 확인
    description: str | None = None

    # 분석 완료·판단 불가·처리 실패
    status: Literal["analyzed", "unavailable", "failed"] = "unavailable"


# ---------- Orchestration 1 집계 결과 ----------

class CareStatusResult(BaseModel):
    # 필수: 한 번의 실행을 식별하며 승인 단계까지 같은 값을 사용
    run_id: str

    # 필수: 가상 어르신과 시나리오 식별자
    profile_id: str
    scenario: Scenario

    # 선택: 전체 흐름 시도 번호. 도구별 재시도 횟수와 구분
    attempt: int = Field(default=1, ge=1)

    # 선택: 조회 실패나 부분 데이터 상황을 허용
    vital: VitalData | None = None
    indoor_environment: IndoorEnvironment | None = None
    devices: DeviceStatus | None = None
    cctv: CctvAnalysis | None = None

    # 선택: 해든 Profile Agent 값. 지병명 원문은 전달하지 않음
    vulnerability: Literal["상", "중", "하"] | None = None

    # 선택: 병원 검색 지역. 프로필 주소에서 채우며 없으면 기본 Mock 목록 사용
    area: str | None = None

    # 선택: 실시간·Mock·캐시 또는 일부 캐시가 섞인 데이터일 수 있음
    source: DataSource = "mock"

    # 선택: 오류·복구 요약. 민감한 원문 정보는 기록하지 않음
    errors: list[str] = Field(default_factory=list)


# ---------- Emergency Agent 및 승인 대상 ----------

class ProposedAction(BaseModel):
    # 필수: 두나가 등록하는 MCP 도구 이름
    tool: ActionTool

    # 필수: 승인 화면에 표시할 조치 설명
    description: str

    # 선택: 해당 MCP 함수의 매개변수 이름과 일치하는 값
    # control_device(device, action), notify_guardian(message),
    # call_119(message), find_hospital(area)
    arguments: dict[str, str] = Field(default_factory=dict)

    # 필수: 이 조치 하나를 실행하기 전에 승인이 필요한지
    # 구체적인 도구별 정책은 팀 합의에 따라 해든의 조치 결과에서 채움
    needs_approval: bool


class EmergencyResult(BaseModel):
    # 필수: 긴급 판단이 속한 실행 ID
    run_id: str

    # 필수: 해든 규칙표에서 결정한 최종 위험도
    risk_level: RiskLevel

    # 선택: 보호자에게 보여줄 판정 근거
    reasons: list[str] = Field(default_factory=list)

    # 선택: 네 축별 단계. 해든 evaluate()의 axes 반환값(축 → 위험도 문자열)과 같음
    axes: dict[RiskAxis, RiskLevel] = Field(default_factory=dict)

    # 선택: 해든이 정의한 낙상 상태 5종 중 하나
    # 정확한 허용 문자열을 전달받으면 Literal로 좁힐 것
    fall_state: str | None = None

    # 선택: 즉시 자동 119 조건과 그 사유
    auto_119: Auto119Reason | None = None

    # 선택: 보호자에게 제안할 Mock 조치 목록
    proposed_actions: list[ProposedAction] = Field(default_factory=list)

    # 긴급 응답 전체를 승인 Gate에 보낼지 표시
    # 아래 needs_approval은 개별 조치의 승인 여부라 서로 다른 의미
    requires_approval: bool = True

    # 선택: 보호자 화면에 표시할 CCTV 요약
    cctv_summary: str | None = None


# ---------- POST /care/run 응답 ----------

class CareRunResponse(BaseModel):
    # 필수: 화면과 이후 승인 흐름에서 공유하는 실행 ID
    run_id: str

    # 필수: README의 공통 상태값
    status: CareStatus

    # 필수: 대시보드에 보여줄 한 줄 진행 상황
    current_step: str

    # 선택: 정상 종료·승인 대기·실패 시 수집 결과
    care_status: CareStatusResult | None = None
    emergency: EmergencyResult | None = None

    # 선택: 정상·실패·복구 안내
    message: str | None = None

    # 선택: 자동 119 등 보호자가 버튼을 누르지 않은 흐름에서는 None
    approved: bool | None = None

    # 선택: 최종 결정이 아직 없거나 승인 대기 중이면 None
    decided_by: DecidedBy | None = None


# ---------- POST /care/approve 요청 ----------

class CareApprovalRequest(BaseModel):
    # 필수: 승인 대기 중인 실행 ID
    run_id: str

    # 필수: 두나 승인 화면에서 보낸 보호자의 명시적 선택
    decision: Literal["approve", "reject"]


# ---------- Mock Action 결과와 최종 응답 ----------

class ActionResult(BaseModel):
    # 필수: 실행한 Mock MCP 도구
    tool: ActionTool

    # 필수: 도구 실행 결과 상태
    status: Literal["success", "failed", "skipped"]
    message: str

    # 선택: 재시도나 대체 경로가 있었을 때 설명
    recovery: str | None = None


class ExecutedAction(BaseModel):
    # Summary Agent에 전달할 실행 기록 형식
    # ActionResult의 tool/status에서 이 형식으로 변환해 전달
    action: ActionTool
    device: str | None = None
    result: Literal["success", "failed", "skipped"]


class SummaryContext(BaseModel):
    # 해든 run_summary()에 필요한 승인·실행 정보
    approved: bool | None
    executed: list[ExecutedAction] = Field(default_factory=list)
    decided_by: DecidedBy


class SummaryResult(BaseModel):
    # Summary Agent가 만든 안내. 거절이면 어르신 안내가 없을 수 있음
    guardian_message: str | None = None
    elder_message: str | None = None


class CareApprovalResponse(BaseModel):
    # 필수: 처리한 실행 ID
    run_id: str

    # 필수: 승인·거절·타임아웃 처리를 포함한 최종 상태
    status: CareStatus
    current_step: str

    # 선택: 실행된 Mock Action 결과. 거절이면 빈 목록
    actions: list[ActionResult] = Field(default_factory=list)

    # 선택: Summary Agent가 만든 대상별 안내
    guardian_message: str | None = None
    elder_message: str | None = None

    # 선택: 자동·타임아웃 처리는 보호자가 버튼을 누른 것이 아니므로 None
    approved: bool | None = None

    # 선택: guardian=보호자 결정, auto=즉시 자동 119, timeout=60초 무응답
    decided_by: DecidedBy | None = None
