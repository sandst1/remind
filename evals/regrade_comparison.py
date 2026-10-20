"""Rescore saved states uniformly without rerunning agents or altering raw reports."""

from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from remind.evals import covers, dataset, grade_agent_state
from remind.serialization import canonical_json
from remind.store import SQLAlchemyMemoryStore


def score_case(case: dict, families: dict) -> dict | None:
    transcripts = Path(case['transcripts'])
    final_path = transcripts / 'final-state.json'
    if not final_path.exists():
        return None
    family_name, task = case['id'].split('.', 1)
    family = families[family_name]
    initial = json.loads((transcripts / 'initial-state.json').read_text())
    sessions = [json.loads(path.read_text()) for path in sorted(transcripts.glob('session-*.json'))]
    store = SQLAlchemyMemoryStore('sqlite://')
    try:
        store.import_data({'version': 4, 'mode': 'portable', 'records': json.loads(final_path.read_text())})
        graded = grade_agent_state(store, family, task, sessions,
            json.loads((transcripts / 'before-final.json').read_text()), initial['facts'])
    finally:
        store.engine.dispose()
    expected = family['old'] if task == 'correction_recall' else family['current']
    graded['stage_checks'] = {
        'capture_fact': any(covers(fact['statement'], expected) for fact in initial['facts']),
        'capture_granularity': all(any(row['data'].get('episode_type') == kind
            and covers(row['data']['content'], family[key]) for row in initial['episodes'])
            for kind, key in (('decision', 'decision'), ('outcome', 'outcome'))),
        'capture_provenance': any(fact.get('source_ref') == 'fixture:' + family_name for fact in initial['facts']),
    }
    return graded


def regrade(path: Path) -> dict:
    raw_path = path / 'comparison.json' if path.is_dir() else path
    result = deepcopy(json.loads(raw_path.read_text()))
    conditions = result.get('conditions')
    if conditions is None:
        conditions = [result['suites']['agent']]
    families = {family['id']: family for family in dataset()['families']}
    changes = []
    for condition in conditions:
        for case in condition['cases']:
            graded = score_case(case, families)
            if graded is None:
                continue
            old_checks = case.get('checks', {})
            if case['passed'] != graded['passed'] or old_checks != graded['checks']:
                changes.append({'condition': condition.get('condition', 'agent'), 'id': case['id'],
                    'repetition': case['repetition'], 'before': {'passed': case['passed'], 'checks': old_checks},
                    'after': {'passed': graded['passed'], 'checks': graded['checks']}})
            case.update(graded)
        complete = (condition['cases'] and
            sum(case['passed'] for case in condition['cases']) / len(condition['cases']) >= .9 and
            not any(case.get('hard_violations') for case in condition['cases']))
        condition['status'] = 'passed' if complete else 'failed'
    result['rescoring'] = {
        'grading_version': 3, 'original_report_sha256': hashlib.sha256(raw_path.read_bytes()).hexdigest(),
        'grader_sha256': hashlib.sha256((Path(__file__).parents[1] / 'src/remind/evals.py').read_bytes()).hexdigest(),
        'reason': 'Normalize use/uses and keep/kept/remain consistently. All cases rescored from persisted states.',
        'changed_cases': changes,
    }
    destination = raw_path.with_name(raw_path.stem + '.regraded.json')
    destination.write_text(canonical_json(result))
    print(destination)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('path', type=Path, help='Comparison directory or individual agent report.json')
    regrade(parser.parse_args().path.resolve())
