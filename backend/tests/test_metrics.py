import pytest
from src.healing.metrics import calculate_metrics


def case(name, outcome, ms, fault=True):
    return dict(case_id=name, outcome=outcome, technical_flow_ms=ms, fault_injected=fault)


def test_recovery_counts_cases_not_logs_and_excludes_waiting():
    result = calculate_metrics([case('cache','recovered',100), case('template','recovered',300),
        case('vision','degraded',1000),case('action','failed',1500),case('wait','pending',0),
        case('reject','rejected',0),case('normal','recovered',10,False)])
    assert result['completed_fault_cases'] == 4
    assert result['recovery_rate_percent'] == 50
    assert result['mean_recovered_technical_flow_ms'] == 200


def test_empty_and_no_recovery_are_not_fabricated():
    assert calculate_metrics([])['recovery_rate_percent'] is None
    result = calculate_metrics([case('fail','failed',500)])
    assert result['recovery_rate_percent'] == 0
    assert result['mean_recovered_technical_flow_ms'] is None


@pytest.mark.parametrize('rows', [[case('x','recovered',1),case('x','failed',2)],
    [case('x','failed',float('nan'))],[case('x','unknown',1)],[case('x','failed',-1)]])
def test_invalid_experiments_rejected(rows):
    with pytest.raises(ValueError):
        calculate_metrics(rows)
