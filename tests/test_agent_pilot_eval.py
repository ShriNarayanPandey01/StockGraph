import pytest

from scripts.evaluate_agent_pilot import evaluate


def benchmark(count=30):
    return {'reviewer': 'Developer', 'scenarios': [
        {'id': str(i), 'expected_opportunity': i < 8, 'generated_opportunity': i < 10, 'reviewed': True}
        for i in range(count)]}


def test_precision_gate_requires_thirty_reviewed_scenarios_and_80_percent_precision():
    assert evaluate(benchmark())['passed'] is True
    assert evaluate(benchmark(29))['passed'] is False
    data = benchmark()
    data['scenarios'][7]['expected_opportunity'] = False
    assert evaluate(data)['passed'] is False


def test_empty_predictions_and_unreviewed_labels_do_not_pass():
    data = benchmark()
    for item in data['scenarios']:
        item['generated_opportunity'] = False
    assert evaluate(data)['passed'] is False
    data['scenarios'][0]['reviewed'] = False
    with pytest.raises(ValueError, match='reviewed'):
        evaluate(data)
