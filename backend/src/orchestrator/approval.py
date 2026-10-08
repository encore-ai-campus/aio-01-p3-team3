"""승인 대기(pending_approval) 저장·조회, run_id 기준 — 기화(④ 저장) / 두나(⑤ 처리)

/care/run이 승인 대기 상태를 저장하고, /care/approve(⑤)가 run_id로 꺼내 쓴다.
저장하는 값:
- care_status: CareStatusResult (dict)
- emergency:   스키마 EmergencyResult (dict). 승인 화면에 보여주는 값
- raw:         해든 님 run_emergency() 결과 전체. Summary Agent가 raw["context"]를 다시 받는다
- created_at:  저장 시각 (epoch 초). 60초 무응답 처리 등에 쓸 수 있음

TODO(상옥·지혜): 지금은 메모리 저장이라 backend를 재시작하면 사라진다. 필요하면 SQLite 테이블로 옮긴다.
"""

import threading
import time


class PendingApprovals:
    def __init__(self, clock=time.time):
        self._items: dict[str, dict] = {}
        self._lock = threading.Lock()
        self._clock = clock

    def save(
        self,
        run_id: str,
        *,
        care_status: dict,
        emergency: dict,
        raw: dict,
        fault: list[str] | None = None,
    ) -> None:
        with self._lock:
            self._items[run_id] = {
                "care_status": care_status,
                "emergency": emergency,
                "raw": raw,
                "fault": list(fault or []),
                "created_at": self._clock(),
            }

    def get(self, run_id: str) -> dict | None:
        with self._lock:
            return self._items.get(run_id)

    def pop(self, run_id: str) -> dict | None:
        """승인·거절을 처리할 때 꺼내면서 지운다. 같은 run_id를 두 번 처리하지 않게 한다."""
        with self._lock:
            return self._items.pop(run_id, None)


pending = PendingApprovals()
