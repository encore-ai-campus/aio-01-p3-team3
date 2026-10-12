import asyncio
from datetime import datetime, timezone
import subprocess

import pytest
from fastapi.testclient import TestClient

from src import main, mcp_client
from src.agents.iot import _read_environment
from src.db.database import Database, cache_key
from src.healing.retry import RetryPolicy
from src.healing.vital import get_vitals_with_healing, VitalUnavailable
from src.schemas import VitalData


def vital(**changes):
    return dict(heart_rate=75,systolic_bp=120,temperature_c=36.5,spo2=98,
                measured_at=datetime.now(timezone.utc).isoformat(),**changes)


@pytest.mark.parametrize('field,low,high', [('heart_rate',20,250),('systolic_bp',50,260),
                                        ('temperature_c',30,43),('spo2',50,100)])
def test_agreed_boundaries(field,low,high):
    data=vital()
    for value in (low,high):
        VitalData.model_validate({**data,field:value})
    for value in (low-1,high+1):
        with pytest.raises(ValueError):
            VitalData.model_validate({**data,field:value})


def test_invalid_latest_preserves_good_cache_and_invalid_fallback_fails(tmp_path):
    db=Database(tmp_path/'db')
    key=cache_key('vital','p','heat')
    good=vital()
    db.save_cache(key,good)
    calls=[]
    def fetch():
        calls.append(1)
        return {**good,'heart_rate':999}
    async def run(run_id):
        return await get_vitals_with_healing(db=db,run_id=run_id,profile_id='p',scenario='heat',
            fetch_latest=fetch,validate=VitalData.model_validate,freshness_seconds=45,
            policy=RetryPolicy(delay_s=0),mock_fetch=lambda: {**good,'spo2':101})
    result=asyncio.run(run('cache'))
    assert result['source']=='cache' and result['data']==good and len(calls)==3
    assert db.load_cache(key,300)['data']==good
    db.save_cache(key,{**good,'temperature_c':25})
    with pytest.raises(VitalUnavailable):
        asyncio.run(run('failed'))
    assert not any(l['status']=='success' for l in db.logs('failed'))


def test_humidity_only_error_and_logs_api(tmp_path,monkeypatch):
    db=Database(tmp_path/'db')
    async def tool(*args,**kwargs):
        return {'temperature_c':33,'humidity_percent':200}
    monkeypatch.setattr(mcp_client,'call_tool',tool)
    data,bad=asyncio.run(_read_environment(db,'humidity','p','heat'))
    assert bad and data=={'temperature_c':33,'humidity_percent':None}
    db.log('other','vital',1,'fail')
    main.app.dependency_overrides[main.get_db]=lambda:db
    try:
        client=TestClient(main.app)
        response=client.get('/logs',params={'run_id':'humidity','limit':1})
        assert response.status_code==200
        body=response.json()
        assert body['count']==1 and body['logs'][0]['run_id']=='humidity'
        all_logs=client.get('/logs',params={'limit':2}).json()['logs']
        assert [l['id'] for l in all_logs]==sorted([l['id'] for l in all_logs],reverse=True)
        for params in ({'limit':0},{'limit':501},{'run_id':''}):
            assert client.get('/logs',params=params).status_code==422
    finally:
        main.app.dependency_overrides.pop(main.get_db,None)
