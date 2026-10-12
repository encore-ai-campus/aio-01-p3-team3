import json
from src.healing.experiment import run_experiments


def test_experiment_evidence_and_metrics_match(tmp_path):
    result = run_experiments(tmp_path, repeats=1)
    saved = json.loads((tmp_path/'results.json').read_text(encoding='utf-8'))
    assert saved['metrics'] == result['metrics']
    assert len(saved['records']) == 4
    assert all(r['expected_behavior_passed'] and r['logs'] for r in saved['records'])
    assert saved['metrics']['recovery_rate_percent'] == 50
    assert saved['source_sha256']
    assert (tmp_path/'1012_장애복구_시험결과_상옥.md').exists()
