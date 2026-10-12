"""Scenario-level recovery metrics from explicit, verified experiment records."""
import math


OUTCOMES = {'recovered', 'degraded', 'failed', 'safe_stop', 'pending', 'rejected'}


def calculate_metrics(records):
    """Each unique case_id represents one injected-fault experiment, not a log row.

    recovered means the affected capability was restored (retry/cache/template).
    degraded means flow continued with missing capability. It is not recovery.
    pending/rejected are excluded; durations exclude human approval waiting.
    Empty denominators/absence of recoveries produce None rather than misleading 0.
    """
    cases = list(records)
    seen = set()
    for case in cases:
        case_id = case['case_id']
        if not isinstance(case_id, str) or not case_id or case_id in seen:
            raise ValueError('case_id must be nonempty and unique')
        seen.add(case_id)
        if case['outcome'] not in OUTCOMES:
            raise ValueError('Unknown experiment outcome')
        duration = case['technical_flow_ms']
        if isinstance(duration, bool) or not isinstance(duration, (int, float)) or not math.isfinite(duration) or duration < 0:
            raise ValueError('Invalid technical duration')
        if type(case['fault_injected']) is not bool:
            raise ValueError('fault_injected must be bool')
    eligible = [c for c in cases if c['fault_injected'] and c['outcome'] not in {'pending', 'rejected'}]
    recovered = [c for c in eligible if c['outcome'] == 'recovered']
    return dict(total_records=len(cases), completed_fault_cases=len(eligible),
                recovered_cases=len(recovered),
                recovery_rate_percent=100*len(recovered)/len(eligible) if eligible else None,
                mean_recovered_technical_flow_ms=sum(c['technical_flow_ms'] for c in recovered)/len(recovered) if recovered else None,
                outcomes={o: sum(c['outcome'] == o for c in eligible) for o in sorted(OUTCOMES - {'pending', 'rejected'})})
