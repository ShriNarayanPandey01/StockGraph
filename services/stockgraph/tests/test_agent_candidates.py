"""The discovery feed remains bounded, canonical, and scoped to requested stocks."""

from stockgraph.adapters.repositories.falkor.repository import GraphRepository


def test_candidate_feed_deduplicates_and_keeps_material_versions(monkeypatch):
    repo = GraphRepository.__new__(GraphRepository)
    event = {'id': 'news-1', 'headline': 'Demand grew', 'summary': 'Reported demand',
             'event_ts': 1000, 'source': 'BSE', 'category': 'REG30'}
    queries = []
    def run(query, params):
        queries.append((query, params))
        if query.startswith('MATCH (n:NewsEvent)'):
            return [['AAA', event, 'DIRECTLY_IMPACTS', {'confidence': 0.9}]]
        return [['AAA', event, 'SHOCKS', {'confidence': 0.9}, 'EXPOSED_TO',
                 {'confidence': 0.9}, 'Commodity', {'id': 'CRUDE'}]]
    monkeypatch.setattr(repo, '_run', run)
    data = repo.agent_candidates(['AAA'], 1100)
    assert len(data['items']) == 1
    assert data['items'][0]['path_kind'] == 'direct'
    assert len(data['items'][0]['material_version']) == 64
    assert all(query[1]['tickers'] == ['AAA'] for query in queries)
    assert all('DUPLICATE_OF' in query[0] for query in queries)
