"""The free stock-connections API preserves Graph pagination and ownership."""

import hashlib
from uuid import UUID

from fastapi.testclient import TestClient
from marketgraph_platform.api import create_app
from marketgraph_platform.domain.access import AccessSnapshot
from marketgraph_platform.models import Principal
from marketgraph_platform.settings import Settings


class Repository:
    def __init__(self):
        self.user = Principal(id=UUID(int=1), name='Researcher', plan='PRO')
        self.pool = EntitlementPool(self.user)

    async def authenticate(self, digest):
        if digest == hashlib.sha256(b'fixture-token').hexdigest():
            return self.user.model_dump()

    async def allow_request(self, user):
        return True

    async def measure(self,*args):
        pass

    async def load_access_snapshot(self, user_id):
        return AccessSnapshot(self.user, {
            'plan': 'PRO', 'active_stock_limit': None, 'monthly_alert_limit': None,
            'features': {'professional_evidence': True, 'research_chat': True,
                         'discovery': True, 'opportunity_alerts': True,
                         'stock_connections': True, 'monitoring': True,
                         'market_monitoring': True}, 'revision': 1,
        }, ())

    async def health_check(self):
        return False

    async def read_broker_credential(self, user_id):
        return None


class EntitlementPool:
    def __init__(self, user):
        self.user = user

    async def fetchrow(self, query, *args):
        if 'FROM platform_users' in query:
            return self.user.model_dump()
        if 'FROM platform_plan_policies' in query:
            return {'plan':'PRO','active_stock_limit':None,'monthly_alert_limit':None,
                    'features':{'professional_evidence':True,'research_chat':True,
                                'discovery':True,'opportunity_alerts':True,
                                'stock_connections':True,'monitoring':True,
                                'market_monitoring':True},'revision':1}
        if 'platform_broker_connections' in query:
            return None
        return None

    async def fetch(self, query, *args):
        return []

    async def execute(self, *args):
        return None


class GraphClient:
    def __init__(self, get_result=None, request_result=None):
        self.get_result = get_result or {}
        self.request_result = request_result or {}
        self.calls = []

    async def get(self, path, params=None, *, professional=False, developer=False):
        self.calls.append((path, params, professional, developer))
        return self.get_result

    async def request(self, method, path, *, body=None, params=None,
                      professional=False, developer=False):
        self.calls.append((method, path, body, params, professional, developer))
        return self.request_result


def test_connections_data_requires_token_and_browser_routes_are_absent():
    client = TestClient(create_app(Settings(_env_file=None),Repository(),object()))
    assert client.get('/connections').status_code == 404
    assert client.get('/connections/assets/explorer.js').status_code == 404
    assert client.get('/api/v1/stocks/RELIANCE/connections').status_code == 401
    assert client.get('/ready').status_code == 503


def test_pro_gateway_retains_fixed_snapshot_and_professional_evidence():
    result_body = {'nodes':[{'kind':'ProfessionalEvidence','id':'version'}],
                   'pagination':{'as_of_ts':123456789,'next_offset':100},'processing_status':'graph_processing'}
    graph = GraphClient(get_result=result_body)
    client = TestClient(create_app(Settings(_env_file=None),Repository(),object(),graph_client=graph))
    headers = {'Authorization':'Bearer fixture-token'}
    result = client.get('/api/v1/stocks/RELIANCE/connections?window=LAST_1Y&limit=50&offset=50&as_of_ts=123456789',headers=headers)
    assert result.status_code == 200
    assert result.json()['nodes'][0]['kind'] == 'ProfessionalEvidence'
    assert graph.calls == [('/api/v1/stocks/RELIANCE/context',
                            {'window':'LAST_1Y','limit':50,'offset':50,'as_of_ts':123456789},True,False)]
    assert client.get('/api/v1/stocks/RELIANCE/connections?from_date=2020-01-01',headers=headers).status_code == 422
    assert client.get('/api/v1/stocks/RELIANCE/connections?window=ALL_TIME',headers=headers).status_code == 422


def test_connection_hops_are_validated_and_forwarded_without_changing_pagination():
    graph = GraphClient(get_result={"exploration": {"hops": 3}, "pagination": {"offset": 50}})
    client = TestClient(create_app(Settings(_env_file=None), Repository(), object(), graph_client=graph))
    headers = {'Authorization': 'Bearer fixture-token'}
    response = client.get('/api/v1/stocks/RELIANCE/connections?hops=3&offset=50', headers=headers)
    assert response.status_code == 200
    assert graph.calls == [('/api/v1/stocks/RELIANCE/context', {
        'window': 'LAST_6M', 'offset': 50, 'limit': 50, 'hops': 3,
    }, True, False)]
    for invalid in ('0', '4', 'all'):
        assert client.get(f'/api/v1/stocks/RELIANCE/connections?hops={invalid}', headers=headers).status_code == 422


def test_market_gateway_proxies_authenticated_search_profile_and_candles():
    calls = []

    class CanonicalClient:
        async def get(self, path, params=None, *, headers=None):
            calls.append((path, params))
            return {'items': []} if path.endswith('/stocks') else {'candles': []}

    client = TestClient(create_app(Settings(_env_file=None),Repository(),CanonicalClient(),graph_client=GraphClient()))
    headers = {'Authorization':'Bearer fixture-token'}
    assert client.get('/api/v1/market/stocks?query=INFY&exchange=NSE&limit=20',headers=headers).json() == {'items':[]}
    assert client.get('/api/v1/market/stocks/INFY?exchange=NSE',headers=headers).status_code == 200
    assert client.get('/api/v1/market/stocks/INFY/candles?exchange=NSE&from=2025-01-01&to=2025-06-30',headers=headers).json() == {'candles':[]}
    assert calls == [
        ('/api/v1/stocks', {'query':'INFY','limit':20,'exchange':'NSE'}),
        ('/api/v1/stocks/INFY', {'exchange':'NSE'}),
        ('/api/v1/stocks/INFY/candles', {'exchange':'NSE','from':'2025-01-01','to':'2025-06-30'}),
    ]
    assert client.get('/api/v1/market/stocks').status_code == 401


def test_graph_stock_registration_is_authenticated_and_async():
    graph = GraphClient(request_result={'job_id':'job-123','status':'pending'})
    client = TestClient(create_app(Settings(_env_file=None),Repository(),object(),graph_client=graph))
    body = {'query':'INFY','exchange':'NSE','strengths':[],'business_exclusions':[]}
    assert client.post('/api/v1/market/stock-registrations',json=body).status_code == 401
    response = client.post('/api/v1/market/stock-registrations',json=body,
                           headers={'Authorization':'Bearer fixture-token'})
    assert response.status_code == 202
    assert response.json()['job_id'] == 'job-123'
    assert graph.calls == [('POST', '/api/v1/stocks', body, None, False, False)]
