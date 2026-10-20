"""Summarize model/interface pilot reports and observed tool friction."""

from __future__ import annotations

import argparse
from collections import Counter
import json
import math
from pathlib import Path

from remind.serialization import canonical_json


def interval(passed: int, count: int) -> list[float]:
    if not count:
        return [0., 1.]
    z = 1.96
    center = (passed/count + z*z/(2*count))/(1+z*z/count)
    half = z*math.sqrt(passed/count*(1-passed/count)/count + z*z/(4*count*count))/(1+z*z/count)
    return [max(0., center-half), min(1., center+half)]


def summarize(report: dict) -> dict:
    cases = report['cases']
    failures, calls, usage, tools = Counter(), 0, Counter(), Counter()
    for case in cases:
        for path in Path(case['transcripts']).glob('session-*.json'):
            session = json.loads(path.read_text())
            usage.update({k: v for k, v in session.get('usage', {}).items() if isinstance(v, (int, float))})
            for event in session['transcript']:
                if event['type'] == 'tool_call':
                    calls += 1
                    tools[event['name']] += 1
                elif event['type'] == 'tool_result':
                    if event.get('error') or event.get('result', {}).get('isError'):
                        failures['transport_or_schema'] += 1
                    try:
                        content = ''.join(c.get('text', '') for c in event.get('result', {}).get('content', []))
                        value = json.loads(content)
                    except (ValueError, TypeError):
                        continue
                    if not isinstance(value, dict):
                        continue
                    for error in value.get('errors', []):
                        failures[error.get('code') or 'operation_failed'] += 1
                    for key in value:
                        if key.startswith('error:'):
                            failures['unknown_snapshot_scope'] += 1
    count = len(cases)
    corrections = [case for case in cases if case['id'].endswith('.correction_recall')]
    passed = sum(case['passed'] for case in cases)
    core_passed = sum(bool(case.get('checks')) and all(value for key, value in case['checks'].items()
                       if key != 'source_provenance') and not case.get('hard_violations') for case in cases)
    checks = {key: sum(case.get('checks', {}).get(key, False) for case in cases)
              for key in ('current_fact', 'supported_pattern', 'source_provenance', 'answer_rubric',
                          'read_performed', 'read_only', 'pending_clear')}
    stages = {key: sum(case.get('stage_checks', {}).get(key, False) for case in cases)
              for key in ('capture_fact', 'capture_granularity', 'capture_provenance')}
    return {'model': report['model'], 'interface': report['interface'], 'cases': count,
            'passed': passed, 'core_passed': core_passed,
            'provenance_only_failures': core_passed-passed,
            'success_rate': passed/max(1,count), 'wilson_95': interval(passed,count),
            'checks': checks, 'stages': stages,
            'correction_history': {'passed': sum(c.get('checks',{}).get('history',False) for c in corrections),
                                   'cases': len(corrections)},
            'hard_violations': sum(bool(c.get('hard_violations')) for c in cases),
            'infrastructure_errors': sum('error' in c for c in cases),
            'calls': calls, 'calls_per_case': calls/max(1,count), 'tool_failures': dict(failures),
            'tools': dict(tools), 'usage': dict(usage),
            'mean_elapsed_seconds': sum(c.get('elapsed_seconds',0) for c in cases)/max(1,count)}


def analyze(root: Path) -> None:
    report_path = root / 'comparison.regraded.json'
    if not report_path.exists():
        report_path = root / 'comparison.json'
    comparison = json.loads(report_path.read_text())
    arms = [summarize(report) for report in comparison['conditions']]
    lookup = {(arm['model'], arm['interface']): arm for arm in arms}
    luna, stronger = comparison['design']['models'][:2]
    rate = lambda model, interface: lookup[(model,interface)]['success_rate']
    effects = {
        'luna_interface_gain_pp': 100*(rate(luna,'revised')-rate(luna,'original')),
        'stronger_interface_gain_pp': 100*(rate(stronger,'revised')-rate(stronger,'original')),
        'model_gain_original_pp': 100*(rate(stronger,'original')-rate(luna,'original')),
        'model_gain_revised_pp': 100*(rate(stronger,'revised')-rate(luna,'revised')),
    }
    result = {'arms': arms, 'descriptive_effects': effects,
              'source_report': str(report_path), 'rescoring': comparison.get('rescoring'),
              'limitations': ['Small fixture pilot, not a production success-rate estimate.',
                'Model sampling seeds are unsupported; repeated runs are not deterministic.',
                'API-dollar costs cannot be inferred from Codex subscription token counts.',
                'Descriptions and skills change together; the study does not isolate each sentence.',
                'Six tools and MCP initialization instructions are held constant across conditions.',
                'Repetitions share fixtures; binomial intervals do not account for that clustering.',
                'Lexical rubrics require manual review of paraphrase, quotation, and negation.']}
    (root / 'analysis.json').write_text(canonical_json(result))
    lines = ['# Model capability versus Remind interface', '',
             '| Model | Interface | Overall | Correct answer | Structural history | Evidence | Provenance | Fact capture | Calls/case |',
             '|---|---|---:|---:|---:|---:|---:|---:|---:|']
    for arm in arms:
        n=arm['cases']; checks=arm['checks']; history=arm['correction_history']
        lines.append(f"| {arm['model']} | {arm['interface']} | {arm['passed']}/{n} | {checks['answer_rubric']}/{n} | "
                     f"{history['passed']}/{history['cases']} | {checks['supported_pattern']}/{n} | "
                     f"{checks['source_provenance']}/{n} | {arm['stages']['capture_fact']}/{n} | {arm['calls_per_case']:.1f} |")
    lines += ['', 'Descriptive changes in overall completion (percentage points):', '']
    lines += [f'- {key}: {value:+.1f}' for key,value in effects.items()]
    lines += ['', 'Observed tool friction:', '']
    lines += [f"- {arm['model']} / {arm['interface']}: {arm['tool_failures']}; mean {arm['mean_elapsed_seconds']:.1f} seconds/case."
              for arm in arms]
    lines += ['', 'Limits:', ''] + ['- '+note for note in result['limitations']]
    (root / 'analysis.md').write_text('\n'.join(lines)+'\n')
    print(root / 'analysis.md')


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    analyze(parser.parse_args().directory.resolve())
