"""Evaluate a developer-labelled opportunity benchmark without calling a model.

Input is JSON: {"reviewer": "name", "scenarios": [{"id": "...",
"expected_opportunity": true, "generated_opportunity": false, "reviewed": true}]}.
The results are a qualification measure, not a profitability or backtest metric.
"""

import argparse
import json
from pathlib import Path


def evaluate(data):
    if not isinstance(data, dict) or not isinstance(data.get('reviewer'), str) or not data['reviewer'].strip():
        raise ValueError('A named developer reviewer is required')
    scenarios = data.get('scenarios')
    if not isinstance(scenarios, list):
        raise ValueError('Scenarios must be a list')
    identities, positives, correct = set(), 0, 0
    for scenario in scenarios:
        if not isinstance(scenario, dict):
            raise ValueError('Invalid scenario')
        identity = scenario.get('id')
        if not isinstance(identity, str) or not identity.strip() or identity in identities:
            raise ValueError('Scenario IDs must be nonempty and unique')
        identities.add(identity)
        if scenario.get('reviewed') is not True or any(type(scenario.get(key)) is not bool
                for key in ('expected_opportunity', 'generated_opportunity')):
            raise ValueError('Each scenario needs a reviewed boolean label and result')
        if scenario['generated_opportunity']:
            positives += 1
            correct += int(scenario['expected_opportunity'])
    precision = correct / positives if positives else None
    return {'reviewer': data['reviewer'].strip(), 'scenarios': len(scenarios),
            'generated_opportunities': positives, 'correct_opportunities': correct,
            'precision': precision, 'passed': len(scenarios) >= 30 and precision is not None and precision >= 0.8}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('benchmark', type=Path)
    args = parser.parse_args()
    try:
        result = evaluate(json.loads(args.benchmark.read_text(encoding='utf-8')))
    except (OSError, ValueError) as exc:
        parser.exit(2, f'Benchmark invalid: {exc}\n')
    print(json.dumps(result, sort_keys=True))
    if not result['passed']:
        parser.exit(1, 'Pilot precision gate not met.\n')


if __name__ == '__main__':
    main()
