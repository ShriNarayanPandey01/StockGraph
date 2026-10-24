"""The free browser gateway preserves Graph pagination and authenticated ownership."""

import hashlib
from uuid import UUID

from fastapi.testclient import TestClient
from marketgraph_platform.api import create_app
from marketgraph_platform.settings import Settings


class Repository:
    pool = None

    async def authenticate(self, digest):
        if digest == hashlib.sha256(b'fixture-token').hexdigest():
            return {'id':UUID(int=1),'name':'Researcher','professional_verified':False}

    async def allow_request(self, user):
        return True

    async def measure(self,*args):
        pass


def test_explorer_requires_token_for_data_but_page_and_assets_load():
    client = TestClient(create_app(Settings(_env_file=None),Repository(),object()))
    page = client.get('/connections')
    assert page.status_code == 200
    assert "frame-ancestors 'none'" in page.headers['content-security-policy']
    assert 'ProfessionalEvidence' in page.text
    assert client.get('/connections/assets/explorer.js').status_code == 200
    assert client.get('/connections/assets/mark.svg').status_code == 200
    assert client.get('/api/v1/stocks/RELIANCE/connections').status_code == 401
    assert client.get('/ready').status_code == 503


def test_gateway_retains_fixed_snapshot_and_never_hides_professional_evidence(monkeypatch):
    calls = []

    async def graph(request,path,params):
        calls.append((path,params))
        return {'nodes':[{'kind':'ProfessionalEvidence','id':'version'}],
                'pagination':{'as_of_ts':123456789,'next_offset':100},'processing_status':'graph_processing'}

    monkeypatch.setattr('marketgraph_platform.connections_api.graph_get',graph)
    client = TestClient(create_app(Settings(_env_file=None),Repository(),object()))
    headers = {'Authorization':'Bearer fixture-token'}
    result = client.get('/api/v1/stocks/RELIANCE/connections?window=LAST_1Y&limit=50&offset=50&as_of_ts=123456789',headers=headers)
    assert result.status_code == 200
    assert result.json()['nodes'][0]['kind'] == 'ProfessionalEvidence'
    assert calls == [('/api/v1/stocks/RELIANCE/context',{'window':'LAST_1Y','limit':50,'offset':50,'as_of_ts':123456789})]
    assert client.get('/api/v1/stocks/RELIANCE/connections?from_date=2020-01-01',headers=headers).status_code == 422
    assert client.get('/api/v1/stocks/RELIANCE/connections?window=ALL_TIME',headers=headers).status_code == 422
