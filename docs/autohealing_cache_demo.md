# heat + vital 캐시 복구 시연 준비

## 준비

backend와 MCP를 실행합니다. 저장·조회는 같은 프로필과 scenario를 사용해야 합니다.
호스트 터미널에서 저장소의 mcp_server 폴더로 이동한 뒤 다음을 실행합니다.

```powershell
python -m src.vital_sender --scenario heat --interval 15
```

기본 전송 주소는 http://localhost:8000/vitals/readings입니다. 컨테이너 내부 전송은
VITAL_INGEST_URL=http://backend:8000/vitals/readings로 지정합니다.
전송기는 세 가상 프로필의 heat 측정값을 전송하며 payload에 scenario=heat를 포함합니다.
터미널에서 전송 성공을 확인한 뒤 진행합니다.

## 시연 순서

1. profile-02, heat, fault=[]로 /care/run 또는 화면의 상태 확인을 실행합니다.
2. Vital Agent가 최신 DB 측정값을 읽고 동일 프로필·heat 캐시에 저장합니다.
3. 동일 profile-02, heat, fault=["vital"]로 다시 실행합니다.
4. Vital 재시도 소진 후 care_status.source=cache와 캐시 측정값을 확인합니다.
5. run_logs의 vital 단계에서 retry → retry → fail → fallback(recovery=cache)을 확인합니다.

계속 실행되는 전송기는 새 이력을 저장하지만 vital 장애 주입은 최신 조회를 차단하므로
마지막 정상 Agent 조회에서 준비한 캐시를 사용합니다. 시연 후 전송기는 Ctrl+C로 종료합니다.
현재 Agent 최신성은 45초, 기본 캐시 한계는 300초입니다. 본 작업은 이 정책을 변경하지 않습니다.
캐시가 만료됐다면 장애 없이 정상 조회를 다시 실행해 준비하세요.

## 주의할 조건

시뮬레이터 없이 실행하면 MCP 대체 Mock으로 진행할 수 있으며, 이 값은 캐시에 저장하지 않습니다.
다른 프로필·scenario의 캐시는 공유하지 않습니다. 새 데이터가 DB에 들어오는 것만으로 캐시는
생기지 않고 정상 Vital 조회가 필요합니다. Mock 자동 캐시 저장·출처 변환은 변경하지 않았습니다.
화면의 캐시 측정 나이 표시와 전체 Docker 실환경 시연은 별도 통합 확인 사항입니다.

## 검증 기록

backend/tests/test_simulator_cache.py에서 실제 전송기 payload 생성 → FastAPI TestClient
수집 → 임시 SQLite 저장 → 정상 Vital 조회 → vital 장애 캐시 복구를 검증합니다.
MCP Mock 호출이 발생하면 실패하도록 시험하며 scenario 격리·측정 시각 보존·복구 로그를 확인합니다.
실제 네트워크·Docker·LLM 실행 시험을 의미하지 않습니다.
