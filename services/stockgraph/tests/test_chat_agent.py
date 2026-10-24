"""Offline tests for graph action validation and source allowlisting."""

from types import SimpleNamespace

from stockgraph.application.graph_queries.chat import GraphChatService
from stockgraph.domain.chat import AgentDraft, ChatRequest
from stockgraph.domain.context import GraphContextResponse, GraphEdge, GraphNode
from stockgraph.domain.enums import Window


class FakeContext:
    def get_context(self, ticker, window, offset, limit):
        return GraphContextResponse(
            ticker=ticker, window=window, start_ts=1, end_ts=2,
            processing_status="completed",
            nodes=[
                GraphNode(id="Stock:RELIANCE", kind="Stock"),
                GraphNode(id="Commodity:BRENT_CRUDE", kind="Commodity"),
            ],
            edges=[GraphEdge(id="e1", source="Stock:RELIANCE",
                             target="Commodity:BRENT_CRUDE", relation="EXPOSED_TO")],
            direct_news=[], indirect_news=[], pagination={"has_more": {}},
        )


class FakeLLM:
    def complete_json(self, prompt, schema):
        return AgentDraft(
            answer="Graph exposure exists.",
            actions=[
                {"type": "HIGHLIGHT_PATH",
                 "node_ids": ["Stock:RELIANCE", "Commodity:BRENT_CRUDE"]},
                {"type": "FOCUS_NODE", "node_ids": ["Stock:MADE_UP"]},
                {"type": "SHOW_NEWS", "node_ids": []},
            ],
            citation_urls=["https://invented.example"],
        )


def test_chat_validates_actions_and_citations():
    response = GraphChatService(FakeContext(), FakeLLM()).respond(
        ChatRequest(message="Highlight crude exposure", ticker="reliance", window=Window.LAST_6M)
    )
    assert response.ticker == "RELIANCE"
    assert [action.type for action in response.actions] == ["HIGHLIGHT_PATH", "SHOW_NEWS"]
    assert response.citations == []
