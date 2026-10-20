"""Factorial Codex pilot: model x frozen Remind interface, with one grader."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import shlex
import sys
import time

from remind.evals import agent_suite, dataset
from remind.serialization import canonical_json


def source_digest(source: Path) -> str:
    files = {str(p.relative_to(source)): hashlib.sha256(p.read_bytes()).hexdigest()
             for p in sorted(source.rglob('*')) if p.is_file() and '__pycache__' not in p.parts}
    return hashlib.sha256(canonical_json(files).encode()).hexdigest()


async def compare(args: argparse.Namespace) -> None:
    root = args.output.resolve()
    root.mkdir(parents=True, exist_ok=True)
    if (root / 'design.json').exists():
        raise ValueError('Choose a new output directory; an existing experiment must not be overwritten')
    data = dataset()
    selected = [case for case in data['agent'] if case['family'] in args.families]
    data = {**data, 'agent': selected}
    runner = Path(__file__).with_name('codex_runner.py').resolve()
    sources = {'original': args.original.resolve(), 'revised': args.revised.resolve()}
    design = {'version': 1, 'grading_version': 3, 'models': args.models,
              'reasoning_effort': args.reasoning_effort, 'repetitions': args.repetitions,
              'families': args.families, 'case_ids': [c['id'] for c in selected],
              'tool_profile': args.tool_profile, 'concurrency': args.concurrency,
              'sources': {k: {'path': str(p), 'digest': source_digest(p)} for k, p in sources.items()},
              'runner_sha256': hashlib.sha256(runner.read_bytes()).hexdigest(),
              'grader_sha256': hashlib.sha256((Path(__file__).parents[1] / 'src/remind/evals.py').read_bytes()).hexdigest(),
              'sampling_seed_supported': False}
    (root / 'design.json').write_text(canonical_json(design))
    semaphore = asyncio.Semaphore(args.concurrency)
    async def condition(model, variant, source):
        name = model + '-' + variant
        output = root / name
        output.mkdir(exist_ok=True)
        command = shlex.join([sys.executable, str(runner), '--model', model,
                              '--reasoning-effort', args.reasoning_effort, '--tool-profile', args.tool_profile])
        configuration = argparse.Namespace(agent_command=command, scenario=None, seed=0,
            repetitions=args.repetitions, agent_server_source=str(source),
            agent_skills_root=str(source / 'remind/skills'))
        async with semaphore:
            started = time.perf_counter()
            print(f'START {name}', file=sys.stderr, flush=True)
            result = await agent_suite(data, configuration, output / 'runs')
            report = {'condition': name, 'model': model, 'interface': variant,
                      'source_digest': design['sources'][variant]['digest'],
                      'elapsed_seconds': time.perf_counter()-started, **result}
            (output / 'report.json').write_text(canonical_json(report))
            print(f"DONE {name}: {sum(c['passed'] for c in report['cases'])}/{len(report['cases'])}",
                  file=sys.stderr, flush=True)
            return report
    # Run all conditions with independent stores and frozen sources. No agent sees
    # any other condition's prompts, transcripts, expected data, or final states.
    reports = await asyncio.gather(*(condition(model, variant, source)
                                    for variant, source in sources.items() for model in args.models))
    (root / 'comparison.json').write_text(canonical_json({'design': design, 'conditions': reports}))
    lines = ['# Codex model and Remind interface pilot', '',
             '| Model | Interface | Passed | Answer | History | Evidence | Provenance | Capture facts | Calls/case |',
             '|---|---|---:|---:|---:|---:|---:|---:|---:|']
    for report in reports:
        cases = report['cases']
        n = len(cases)
        count = lambda key: sum(c.get('checks', {}).get(key, False) for c in cases)
        lines.append(f"| {report['model']} | {report['interface']} | {sum(c['passed'] for c in cases)}/{n} | "
                     f"{count('answer_rubric')}/{n} | {count('history')}/{n} | {count('supported_pattern')}/{n} | "
                     f"{count('source_provenance')}/{n} | {sum(c.get('stage_checks',{}).get('capture_fact',False) for c in cases)}/{n} | "
                     f"{sum(c.get('tool_calls',0) for c in cases)/max(n,1):.1f} |")
    lines += ['', 'History is automatically satisfied for capture-only tasks; inspect correction cases separately.',
              'This is a small stochastic pilot. Seeds do not fix model sampling. No API-dollar estimate is implied by Codex token usage.',
              'All conditions use the same six tools and grader. The interface treatment changes descriptions/skills only.']
    (root / 'comparison.md').write_text('\n'.join(lines)+'\n')
    print(root / 'comparison.md')


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--original', type=Path, required=True, help='Frozen original src directory')
    parser.add_argument('--revised', type=Path, required=True, help='Frozen revised src directory')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--models', nargs='+', default=['gpt-6-luna', 'gpt-6.1-sol'])
    parser.add_argument('--families', nargs='+', default=['architecture', 'configuration'])
    parser.add_argument('--repetitions', type=int, default=3)
    parser.add_argument('--concurrency', type=int, default=4)
    parser.add_argument('--reasoning-effort', default='medium')
    parser.add_argument('--tool-profile', choices=['core', 'extended'], default='extended')
    args = parser.parse_args()
    if args.repetitions < 1 or args.concurrency < 1:
        parser.error('Repetitions and concurrency must be positive')
    if len(args.models) != 2 or len(set(args.models)) != 2:
        parser.error('Select exactly two distinct model IDs')
    known = {f['id'] for f in dataset()['families']}
    if set(args.families) - known:
        parser.error('Unknown fixture family')
    for source in (args.original, args.revised):
        if not (source / 'remind/mcp_server.py').is_file():
            parser.error('Each source must contain remind/mcp_server.py')
    asyncio.run(compare(args))


if __name__ == '__main__':
    main()
