"""Committed evidence processing and transparent professional weighting."""

from stockgraph.adapters.repositories.falkor.professional import EvidenceRepository
from stockgraph.domain.platform_events import ProfessionalEvidence


class EvidencePipeline:
    def __init__(self, repo, embedder=None):
        self._repo = repo
        self.embedder = embedder
        self.evidence = EvidenceRepository(repo)

    def process(self, event):
        if event.kind == "professional.author-status":
            return self.evidence.project_author_status(event)
        if event.kind == "document.extracted":
            self.evidence.project_document(event)
            if self.embedder is not None:
                for chunk in event.payload["chunks"]:
                    embedding = self.embedder.embed_one(chunk["text"])
                    self.evidence.embed_document_chunk(chunk["id"], embedding)
                self.evidence.document_semantic_status(event.payload["version_id"], "completed")
            else:
                self.evidence.document_semantic_status(event.payload["version_id"], "pending_disabled")
            return True
        payload = (ProfessionalEvidence.model_validate(event.payload)
                   if event.kind == "professional.published" else None)
        return self.evidence.project_professional(event, payload)


def professional_context(repo, ticker, start, end, offset=0, limit=50, weight=1.5):
    rows = (repo.professional_page(ticker, start, end, offset, limit)
            if hasattr(repo, "professional_page") else
            EvidenceRepository(repo).professional_page(ticker, start, end, offset, limit))
    return {
        "items": [{**row, "priority_weight": weight if row.get("author_verified", True) else 1.0}
                  for row in rows[:limit]],
        "pagination": {"offset": offset, "limit": limit, "has_more": len(rows) > limit,
                       "next_offset": offset + limit if len(rows) > limit else None,
                       "as_of_ts": end},
        "policy": {"version": "professional-priority-v1", "professional_weight": weight,
                   "ordinary_evidence_weight": 1.0,
                   "instruction": "Give eligible professional views greater weight. Preserve and cite "
                   "opposing evidence; compare the same stock and horizon. Professional status does "
                   "not guarantee correctness and sufficiently strong opposing evidence can prevail.",
                   "access": "FREE", "subscription_enforced": False},
    }
