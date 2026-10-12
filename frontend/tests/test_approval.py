"""보호자 승인 화면 상태와 렌더링 테스트 — 두나."""

import pytest
from streamlit.testing.v1 import AppTest

import src.approval as approval
from src.approval import get_approval_actions, store_pending_approval


def test_store_pending_approval_keeps_agreed_fields() -> None:
    state: dict[str, object] = {"approval_result": {"status": "done"}}
    response = {
        "run_id": "run-001",
        "status": "pending_approval",
        "care_status": {"profile_id": "profile-01"},
        "emergency": {"risk_level": "위급"},
    }

    store_pending_approval(response, state)

    assert state == {
        "run_id": "run-001",
        "care_status": {"profile_id": "profile-01"},
        "emergency": {"risk_level": "위급"},
    }


def test_store_pending_approval_preserves_result_for_same_run() -> None:
    result = {"status": "done"}
    state: dict[str, object] = {
        "run_id": "run-001",
        "approval_result": result,
    }

    store_pending_approval(
        {"run_id": "run-001", "status": "pending_approval"},
        state,
    )

    assert state["approval_result"] is result


def test_only_actions_marked_as_needing_approval_are_selected() -> None:
    emergency = {
        "proposed_actions": [
            {"tool": "notify_guardian", "description": "알림", "needs_approval": False},
            {"tool": "find_hospital", "description": "병원", "needs_approval": False},
            {"tool": "control_device", "description": "에어컨", "needs_approval": True},
            {"tool": "call_119", "description": "119", "needs_approval": True},
        ],
        "requires_approval": True,
    }

    actions = get_approval_actions(emergency)

    assert [action["tool"] for action in actions] == [
        "control_device",
        "call_119",
    ]


def test_pending_approval_renders_explicit_decision_buttons() -> None:
    app = AppTest.from_string(
        """
from src.approval import render_approval_panel

render_approval_panel(
    {
        "run_id": "run-001",
        "status": "pending_approval",
        "current_step": "보호자 승인 대기",
        "care_status": {"cctv": None},
        "emergency": {
            "risk_level": "위급",
            "requires_approval": True,
            "reasons": ["쓰러짐이 의심됩니다."],
            "proposed_actions": [
                {
                    "tool": "notify_guardian",
                    "description": "보호자에게 상황을 알립니다.",
                    "arguments": {},
                    "needs_approval": False,
                },
                {
                    "tool": "call_119",
                    "description": "119 호출을 실행합니다.",
                    "arguments": {"message": "쓰러짐 의심"},
                    "needs_approval": True,
                },
            ],
        },
    },
    "http://backend.test",
)
"""
    ).run()

    assert not app.exception
    assert [button.label for button in app.button] == [
        "조치 승인 및 실행",
        "조치 거절",
    ]
    # 기화 10/12: 위험도는 st.error 대신 첫 화면 맨 위의 큰 배너(components/risk_banner.py)로 표시
    assert any("care-risk" in item.value and "위급" in item.value for item in app.markdown)


def test_notification_only_does_not_render_approval_buttons() -> None:
    app = AppTest.from_string(
        """
from src.approval import render_approval_panel

render_approval_panel(
    {
        "run_id": "run-002",
        "status": "pending_approval",
        "care_status": None,
        "emergency": {
            "risk_level": "주의",
            "requires_approval": False,
            "reasons": ["확인이 필요합니다."],
            "proposed_actions": [
                {
                    "tool": "notify_guardian",
                    "description": "보호자에게 알립니다.",
                    "arguments": {},
                    "needs_approval": False,
                }
            ],
        },
    },
    "http://backend.test",
)
"""
    ).run()

    assert not app.exception
    assert len(app.button) == 0
    assert any("추가 승인이 필요한 조치는 없습니다" in info.value for info in app.info)


def test_critical_auto_119_renders_result_without_approval_buttons() -> None:
    app = AppTest.from_string(
        """
from src.approval import render_approval_panel

render_approval_panel(
    {
        "run_id": "run-005",
        "status": "done",
        "current_step": "119 자동 연결 완료",
        "care_status": None,
        "emergency": {
            "risk_level": "위급",
            "auto_119": "VITAL_SEVERE",
            "requires_approval": False,
            "reasons": ["바이탈 위험 범위 항목이 3개입니다."],
            "proposed_actions": [
                {
                    "tool": "call_119",
                    "description": "119 자동 연결",
                    "arguments": {"message": "바이탈 매우 위험"},
                    "needs_approval": False,
                }
            ],
        },
        "message": "보호자 승인 없이 119에 연락했습니다.",
        "approved": None,
        "decided_by": "auto",
    },
    "http://backend.test",
)
"""
    ).run()

    assert not app.exception
    assert len(app.button) == 0
    assert any("자동 긴급 조치" in success.value for success in app.success)
    assert any("보호자 승인 없이" in error.value for error in app.error)


def test_timeout_result_is_not_shown_as_guardian_approval() -> None:
    app = AppTest.from_string(
        """
from src.approval import render_approval_result

render_approval_result(
    {
        "run_id": "run-006",
        "status": "done",
        "current_step": "승인 대기 시간 초과 → 119 호출(mock) 완료",
        "actions": [],
        "decided_by": "timeout",
    }
)
"""
    ).run()

    assert not app.exception
    assert any("승인 응답이 없어" in warning.value for warning in app.warning)
    assert not any("승인된 조치" in success.value for success in app.success)


def test_normal_and_failed_results_have_clear_feedback() -> None:
    normal_app = AppTest.from_string(
        """
from src.approval import render_approval_panel
render_approval_panel(
    {"status": "no_issue", "message": "정상 상태입니다."},
    "http://backend.test",
)
"""
    ).run()
    failed_app = AppTest.from_string(
        """
from src.approval import render_approval_panel
render_approval_panel(
    {"status": "fail", "message": "실행에 실패했습니다."},
    "http://backend.test",
)
"""
    ).run()

    assert not normal_app.exception
    assert normal_app.success[0].value == "정상 상태입니다."
    assert not failed_app.exception
    assert failed_app.error[0].value == "실행에 실패했습니다."


@pytest.mark.parametrize(
    ("button_index", "decision", "response_status", "expected_message"),
    [
        (0, "approve", "done", "승인된 조치를 실행했습니다."),
        (1, "reject", "rejected", "보호자가 조치를 거절했습니다."),
    ],
)
def test_decision_button_submits_and_renders_result(
    monkeypatch: pytest.MonkeyPatch,
    button_index: int,
    decision: str,
    response_status: str,
    expected_message: str,
) -> None:
    submitted: list[tuple[str, str]] = []

    def fake_submit(
        backend_url: str,
        run_id: str,
        submitted_decision: str,
    ) -> dict[str, object]:
        assert backend_url == "http://backend.test"
        submitted.append((run_id, submitted_decision))
        return {
            "run_id": run_id,
            "status": response_status,
            "current_step": "처리 완료",
            "actions": [],
        }

    monkeypatch.setattr(approval, "submit_care_decision", fake_submit)
    app = AppTest.from_string(
        """
from src.approval import render_approval_panel

render_approval_panel(
    {
        "run_id": "run-003",
        "status": "pending_approval",
        "care_status": None,
        "emergency": {
            "risk_level": "경고",
            "requires_approval": True,
            "reasons": ["조치가 필요합니다."],
            "proposed_actions": [
                {
                    "tool": "control_device",
                    "description": "에어컨을 작동합니다.",
                    "arguments": {"device": "aircon", "action": "cool"},
                    "needs_approval": True,
                }
            ],
        },
    },
    "http://backend.test",
)
"""
    ).run()

    app.button[button_index].click().run()

    assert not app.exception
    assert submitted == [("run-003", decision)]
    rendered_messages = [item.value for item in (*app.success, *app.info)]
    assert any(expected_message in message for message in rendered_messages)


def test_care_workflow_calls_run_api_and_renders_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    submitted: list[tuple[str, str, list[str]]] = []

    def fake_run(
        backend_url: str,
        profile_id: str,
        scenario: str,
        fault: list[str],
    ) -> dict[str, object]:
        assert backend_url == "http://backend.test"
        submitted.append((profile_id, scenario, fault))
        return {
            "run_id": "run-live-001",
            "status": "no_issue",
            "current_step": "위험 판정 완료",
            "message": "이상 없음",
        }

    monkeypatch.setattr(approval, "request_care_run", fake_run)
    app = AppTest.from_string(
        """
from src.approval import render_care_workflow
render_care_workflow("http://backend.test")
"""
    ).run()

    next(button for button in app.button if button.label == "상태 확인하기").click().run()

    assert not app.exception
    assert submitted == [("profile-01", "normal", [])]
    assert any(item.value == "이상 없음" for item in app.success)


def test_streamlit_app_mounts_actual_care_workflow(monkeypatch: pytest.MonkeyPatch) -> None:
    # 기화 10/12: 데모 계정으로 로그인한 뒤에 돌봄 워크플로가 보인다 (src/auth.py)
    monkeypatch.setenv("DEMO_ACCOUNTS", "childA:pw-a:profile-01")
    app = AppTest.from_file("../src/app.py").run()
    app.text_input[0].input("childA")
    app.text_input[1].input("pw-a")
    app = next(button for button in app.button if button.label == "로그인").click().run()

    assert not app.exception
    assert any(button.label == "상태 확인하기" for button in app.button)


@pytest.mark.parametrize(
    ("profile_id", "expected_scenario"),
    [
        ("profile-01", "fall"),
        ("profile-02", "heat"),
        ("profile-03", "induction"),
        ("profile-04", "critical"),
    ],
)
def test_logged_in_elder_is_fixed_to_own_scenario_with_all_faults(
    monkeypatch: pytest.MonkeyPatch, profile_id: str, expected_scenario: str
) -> None:
    submitted: list[tuple[str, str, list[str]]] = []

    def fake_run(backend_url, profile_id, scenario, fault):
        submitted.append((profile_id, scenario, fault))
        return {"run_id": "run-1", "status": "no_issue", "message": "이상 없음"}

    monkeypatch.setattr(approval, "request_care_run", fake_run)
    app = AppTest.from_string(
        f"""
from src.approval import render_care_workflow
render_care_workflow("http://backend.test", profile_id="{profile_id}")
"""
    ).run()

    assert [box.label for box in app.sidebar.selectbox] == []  # 시나리오 선택 없음
    assert app.sidebar.multiselect[0].options == ["vital", "iot", "vision", "llm"] or len(
        app.sidebar.multiselect[0].options
    ) == 4
    app.sidebar.multiselect[0].set_value(["vital", "iot", "vision", "llm"])
    next(b for b in app.button if b.label == "상태 확인하기").click().run()

    assert not app.exception
    assert submitted == [(profile_id, expected_scenario, ["vital", "iot", "vision", "llm"])]
