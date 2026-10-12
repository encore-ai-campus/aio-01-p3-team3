"""Reproducible local ASGI/SQLite experiments; substitutes MCP and LLM providers.

Run from backend: python -m src.healing.experiment --output ../docs/evidence/autohealing_20261012
No keys, network, real device commands or production database are used.
"""
import argparse
import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from unittest.mock import patch

from fastapi.testclient import TestClient
from src import main, mcp_client
from src.db.database import Database
from src.db.seed import seed_profiles
from src.healing.metrics import calculate_metrics
from src.orchestrator import emergency, approval_flow
from src.orchestrator.approval import pending


def run_experiments(output, repeats=3):
    if type(repeats) is not int or repeats < 1:
        raise ValueError('repeats must be positive')
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    repo = Path(__file__).resolve().parents[3]
    script = "import json; from src.mock_data import SCENARIOS; print(json.dumps(SCENARIOS))"
    scenarios = json.loads(subprocess.check_output([sys.executable, '-c', script], cwd=repo/'mcp_server', text=True, encoding='utf-8'))
    records = []
    definitions = [('DR-VITAL-01','heat','vital'),('DR-IOT-01','heat','iot'),
                   ('DR-VISION-01','critical','vision'),('DR-LLM-01','fall','llm')]
    for repetition in range(1, repeats+1):
        for scenario_id, scenario, fault in definitions:
            with tempfile.TemporaryDirectory() as tmp:
                db = Database(Path(tmp)/'experiment.db')
                seed_profiles(db)
                calls = []
                data = scenarios[scenario]
                async def tool(name, arguments=None, **kwargs):
                    arguments = arguments or {}
                    calls.append(name)
                    if name == 'get_vitals':
                        return data['vital']
                    if name == 'get_indoor_env':
                        return data['indoor_environment']
                    if name == 'get_device_status':
                        return data['devices']
                    if name == 'capture_cctv':
                        return {'image_path': data['cctv_image_path']}
                    if name == 'analyze_cctv':
                        # Stub observation only; real image/LLM accuracy is not tested.
                        fallen = scenario == 'fall'
                        return dict(image_path=arguments['image_path'],available=True,status='analyzed',
                            person_visible=True,posture='fallen' if fallen else 'sitting',
                            fall_suspected=fallen,confidence='high',description='시연 관찰 결과')
                    if name == 'find_hospital':
                        return {'name':'시연병원','distance_km':1.2,'type':'응급실'}
                    return {'status':'success','tool':name,'message':'Mock 실행 완료'}
                def llm(faults):
                    return (lambda _: '{잘못된 JSON') if 'llm' in faults.values else None
                main.app.dependency_overrides[main.get_db] = lambda: db
                run_id = None
                try:
                    with patch.object(mcp_client,'call_tool',tool), patch.object(emergency,'_llm',llm), \
                         patch.object(approval_flow,'_summary_llm',lambda faults: (lambda _: '{잘못된 JSON') if 'llm' in faults else None):
                        client = TestClient(main.app)
                        ingest = client.post('/vitals/readings',json=dict(data['vital'],profile_id='profile-02',scenario=scenario,
                            measured_at=(datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat()))
                        assert ingest.status_code == 200, ingest.text
                        if fault == 'vital':
                            warm = client.post('/care/run',json=dict(profile_id='profile-02',scenario=scenario,fault=[]))
                            assert warm.status_code == 200
                            pending.pop(warm.json()['run_id'])
                        calls.clear()
                        start = time.perf_counter()
                        response = client.post('/care/run',json=dict(profile_id='profile-02',scenario=scenario,fault=[fault]))
                        duration = (time.perf_counter()-start)*1000
                        assert response.status_code == 200, response.text
                        first = response.json()
                        run_id = first['run_id']
                        final = first
                        if first['status'] == 'pending_approval':
                            start = time.perf_counter()
                            approved = client.post('/care/approve',json=dict(run_id=run_id,decision='approve'))
                            duration += (time.perf_counter()-start)*1000
                            assert approved.status_code == 200, approved.text
                            final = approved.json()
                        logs = db.logs(run_id)
                        if fault == 'vital':
                            passed = first['care_status']['source']=='cache' and 'get_vitals' not in calls
                            primary = [l for l in logs if l['step']=='vital']
                            passed = passed and [l['status'] for l in primary] == ['retry','retry','fail','fallback']
                            outcome, recovery = 'recovered','cache'
                        elif fault == 'iot':
                            actions = [a for a in final['actions'] if a['tool']=='control_device']
                            passed = bool(actions) and all(a['status']=='failed' for a in actions) and '실패' in final['guardian_message']
                            primary = [l for l in logs if l['step']=='action:control_device']
                            passed = passed and [l['status'] for l in primary] == ['retry','retry','fail']
                            outcome, recovery = 'failed',None
                        elif fault == 'vision':
                            passed = first['care_status']['cctv']['status']=='failed' and 'analyze_cctv' not in calls
                            primary = [l for l in logs if l['step']=='vision']
                            passed = passed and [l['status'] for l in primary] == ['retry','fail']
                            outcome, recovery = 'degraded',None
                        else:
                            passed = any(l['recovery']=='template' for l in logs) and bool(final.get('guardian_message'))
                            passed = passed and sum(l['status']=='retry' for l in logs if l['step']=='llm') == 2
                            outcome, recovery = 'recovered','template'
                        assert passed, f'{scenario_id} unexpected result: {final}'
                        records.append(dict(case_id=f'{scenario_id}-{repetition}',scenario_id=scenario_id,
                            scenario=scenario,fault=fault,fault_injected=True,outcome=outcome,recovery=recovery,
                            expected_behavior_passed=passed,technical_flow_ms=round(duration,3),
                            run_id=run_id,care_response=first,final_response=final,logs=logs,provider_calls=calls.copy()))
                finally:
                    if run_id:
                        pending.pop(run_id)
                    main.app.dependency_overrides.pop(main.get_db,None)
    revision = subprocess.check_output(['git','rev-parse','HEAD'],cwd=repo,text=True).strip()
    sources = {str(p.relative_to(repo)): hashlib.sha256(p.read_bytes()).hexdigest()
               for p in sorted((repo/'backend/src').rglob('*.py'))}
    result = dict(executed_at=datetime.now(timezone(timedelta(hours=9))).isoformat(),
        base_revision=revision,scope='Local ASGI TestClient + real temporary SQLite; MCP/LLM stubs',
        source_sha256=sources,repeats=repeats,metrics=calculate_metrics(records),records=records)
    (output/'results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    metrics = result['metrics']
    rows = '\n'.join(f"| {r['case_id']} | {r['outcome']} | {r['recovery'] or '-'} | {r['technical_flow_ms']:.3f} | 통과 |" for r in records)
    report = f'''# 상옥 장애 복구 시험 보고서 — 2026-10-12

실행 시각: {result['executed_at']}
개발 기준 커밋: {revision}. 실행 당시 소스 SHA256은 results.json에 저장했다.

## 시험 환경과 범위

실제 FastAPI 앱의 /vitals/readings, /care/run, /care/approve와 임시 SQLite를 사용했다.
MCP·LLM은 시험용 응답으로 교체했다. 실제 네트워크, LLM 키, CCTV 인식 정확도,
AWS 배포와 화면 시연을 검증한 결과가 아니다. 기본 재시도 대기는 줄이지 않았다.
시나리오별로 새 DB를 사용하고 바이탈 캐시는 정상 조회로 먼저 준비했다.

## 지표 정의와 결과

장애 시나리오 한 번을 한 건으로 집계하며 로그 행 수를 건수로 사용하지 않는다.
재시도/캐시/템플릿으로 해당 기능을 대체·복구한 경우만 recovered로 계산한다.
영상 없이 진행은 degraded, 기기 실패 후 수동 안내는 failed로 계산한다.
pending/rejected와 정상 시험은 장애 분모에서 제외한다.

- 완료 장애 시험: {metrics['completed_fault_cases']}건
- 자동 복구: {metrics['recovered_cases']}건
- 자동 복구율: {metrics['recovery_rate_percent']:.2f}%
- 자동 복구 성공 건의 평균 기술 흐름 시간: {metrics['mean_recovered_technical_flow_ms']:.3f}ms

시간은 장애 /care/run 및 필요 시 /care/approve의 실제 처리시간 합이다.
캐시 준비·수집·사람의 승인 대기는 제외했다. 개별 호출 복구시간이나
실서비스 SLA로 해석하지 않는다. 결과는 이 로컬 시험 세트에 한정된다.

## 실제 시험 기록

| 시험 | 결과 분류 | 대체 방법 | 기술 흐름 ms | 기대 동작 |
|---|---|---|---:|---|
{rows}

DR-VITAL-01: 최신 조회 장애 → 3회 시도 소진 → 동일 스트림 캐시 → 안내.
DR-IOT-01: 승인 후 제어 장애 → 3회 시도 소진 → 제어 실패·직접 조치 안내.
DR-VISION-01: 분석 장애 → 2회 시도 소진 → 영상 판단 불가·바이탈 판정.
DR-LLM-01: 깨진 JSON → 교정 1회 → Emergency/Summary 템플릿 안내.
각 case의 API 응답·run_logs·Mock 도구 호출 목록은 results.json을 참고한다.
모든 기대 동작 통과는 기능이 모두 복구됐다는 뜻이 아니다.

## 구현 현황과 남은 확인

바이탈 이력/캐시/로그/프로필, 부분 바이탈 저장, DB 마이그레이션,
area 전달 및 heat 캐시 준비는 구현되어 있다. 지표는 명시적 시험 결과를
입력받아 계산하며 /logs·실시간 화면과는 아직 연결되지 않았다.
승인 대기 정보는 메모리에 있으므로 재시작하면 사라진다.
DB 전체 장애의 상세 메모리 진단 전달과 통합 알림, 센서 범위 변경 연결,
CCTV 숫자 confidence 보존·중복 재시도, 실제 LLM·화면 확인은 남은 통합 과제다.
본 작업에서 위험도·최신성·source·재시도 정책은 변경하지 않았다.

## 재실행

backend에서 `python -m src.healing.experiment --output ../docs/evidence/autohealing_20261012` 실행.
results.json과 1012_장애복구_시험결과_상옥.md를 새 실행 결과로 갱신한다. 임시 DB는 실행 후 제거된다.
'''
    (output/'1012_장애복구_시험결과_상옥.md').write_text(report,encoding='utf-8')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output',required=True)
    parser.add_argument('--repeats',type=int,default=3)
    args = parser.parse_args()
    print(json.dumps(run_experiments(args.output,args.repeats)['metrics'],ensure_ascii=False))
