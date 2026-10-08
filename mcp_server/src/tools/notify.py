"""보호자 알림과 119 호출을 모사하는 실행형 도구."""


def notify_guardian(message: str) -> dict[str, object]:
    """보호자 알림을 실제 전송 없이 Mock으로 실행한다."""

    if not isinstance(message, str):
        raise TypeError("message는 문자열이어야 합니다.")

    if not message.strip():
        raise ValueError("message는 비어 있을 수 없습니다.")

    return {
        "tool": "notify_guardian",
        "status": "success",
        "message": "보호자 알림을 Mock으로 실행했습니다.",
        "recovery": None,
    }


def call_119(message: str) -> dict[str, object]:
    """119 호출을 실제 신고 없이 Mock으로 실행한다.

    보호자 승인 여부는 오케스트레이터의 Approval Gate에서 확인한다.
    이 함수는 전화나 외부 네트워크 요청을 수행하지 않는다.
    """

    if not isinstance(message, str):
        raise TypeError("message는 문자열이어야 합니다.")

    if not message.strip():
        raise ValueError("message는 비어 있을 수 없습니다.")

    return {
        "tool": "call_119",
        "status": "success",
        "message": "119 호출을 Mock으로 실행했습니다.",
        "recovery": None,
    }
