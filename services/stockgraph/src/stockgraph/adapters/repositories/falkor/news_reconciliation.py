"""Replace one article's accepted inference in a single guarded graph query."""

import hashlib
import math

from stockgraph.runtime.settings import settings


class NewsReconciliation:
    def reconcile_news_impacts(
        self, news_id, scope_tickers, stock_impacts, market_impacts, *, replace_market=True
    ):
        # Never delete old results until every model call and identity check succeeded.
        params = {"news_id": news_id, "scope": list(dict.fromkeys(scope_tickers))}
        clauses = [
            "MATCH (n:NewsEvent {id:$news_id})",
            "OPTIONAL MATCH (n)-[old:DIRECTLY_IMPACTS|INDIRECTLY_IMPACTS]->(s:Stock)",
            "WHERE s.ticker IN $scope",
            "DELETE old WITH DISTINCT n",
        ]
        if replace_market:
            clauses += [
                "OPTIONAL MATCH (n)-[old_market:SHOCKS|IMPACTS_SECTOR|ALTERS_MACRO]->()",
                "DELETE old_market WITH DISTINCT n",
            ]
        rows = []
        for row in stock_impacts:
            relation = row["impact_type"]
            if relation not in {"DIRECTLY_IMPACTS", "INDIRECTLY_IMPACTS"}:
                raise ValueError("Unsupported news impact")
            if row["ticker"] not in params["scope"]:
                raise ValueError("News impact outside replacement scope")
            rows.append(("Stock", "ticker", row["ticker"], relation, row))
        kinds = {
            "commodity": ("Commodity", "SHOCKS"),
            "macro": ("MacroFactor", "ALTERS_MACRO"),
            "sector": ("Sector", "IMPACTS_SECTOR"),
        }
        for row in market_impacts:
            label, relation = kinds[row["kind"]]
            rows.append((label, "id", row["entity_id"], relation, row))
        # Read old provider sentiment before replacement: replay without a new score
        # must not erase an existing provider observation.
        previous = self._run(
            "MATCH (n:NewsEvent {id:$news_id})-[r]->(t) "
            "RETURN type(r), coalesce(t.ticker,t.id), r.sentiment",
            {"news_id": news_id},
        )
        sentiments = {}
        for old in previous:
            values = list(old.values()) if isinstance(old, dict) else old
            sentiments[(values[0], values[1])] = values[2]
        for i, (label, key, identity, relation, row) in enumerate(rows):
            confidence = float(row["confidence"])
            if not math.isfinite(confidence) or not settings.ontology_min_confidence <= confidence <= 1:
                raise ValueError("Invalid impact confidence")
            if not self.get_entity(label, identity):
                raise ValueError("Impact target is not projected")
            sentiment = row.get("sentiment")
            if sentiment is None:
                sentiment = sentiments.get((relation, identity))
                if sentiment is None and label == "Stock":
                    sentiment = sentiments.get(("DIRECTLY_IMPACTS",identity))
                    if sentiment is None:
                        sentiment = sentiments.get(("INDIRECTLY_IMPACTS",identity))
            props = {
                "edge_id": hashlib.sha256(f"{news_id}:{relation}:{identity}".encode()).hexdigest(),
                "confidence": confidence,
                "causal_rationale": row["rationale"],
                "inferred_by": "llm",
            }
            if sentiment is not None:
                props["sentiment"] = sentiment
            params[f"target_{i}"] = identity
            params[f"props_{i}"] = props
            clauses += [
                f"MATCH (t{i}:{label} {{{key}:$target_{i}}})",
                f"MERGE (n)-[r{i}:{relation}]->(t{i}) SET r{i} += $props_{i}",
                "WITH DISTINCT n",
            ]
        result = self._run(" ".join([*clauses, "RETURN n.id"]), params)
        if not result:
            raise ValueError("News inference source is not projected")
