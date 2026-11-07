"""Professional evidence workflows independent of HTTP and PostgreSQL details."""

from uuid import UUID

from marketgraph_platform.application.ports import ContributionRepositoryPort, DataClientPort
from marketgraph_platform.models import ContributionInput, Principal, VersionInput
from marketgraph_platform.policy import require_permission


class ContributionService:
    def __init__(self, repository: ContributionRepositoryPort, data_client: DataClientPort):
        self._repository = repository
        self._data_client = data_client

    async def create(self, user: Principal, content: ContributionInput, idempotency_key: str):
        require_permission(user, "author")
        await self._validate(content)
        result = await self._repository.create_contribution(user, content, idempotency_key)
        await self._repository.measure(user.id, "contribution_drafts")
        return result

    async def add_version(self, contribution_id: UUID, user: Principal, content: VersionInput):
        require_permission(user, "author")
        await self._validate(content)
        submission = ContributionInput.model_validate(
            content.model_dump(exclude={"expected_revision"})
        )
        return await self._repository.add_version(
            contribution_id, user, submission, content.expected_revision
        )

    async def submit(self, contribution_id: UUID, user: Principal, expected_revision: int):
        require_permission(user, "author")
        return await self._repository.submit(contribution_id, user, expected_revision)

    async def review(self, contribution_id: UUID, user: Principal, expected_revision: int,
                     decision: str, reason: str):
        require_permission(user, "review")
        return await self._repository.review(
            contribution_id, user, expected_revision, decision, reason
        )

    async def retract(self, contribution_id: UUID, user: Principal, expected_revision: int,
                      reason: str):
        require_permission(user, "author")
        return await self._repository.retract(
            contribution_id, user, expected_revision, reason
        )

    async def _validate(self, content: ContributionInput) -> None:
        await self._data_client.validate_ticker(content.ticker)
        await self._data_client.validate_citations(content)


class AccountAdministrationService:
    """Explicitly groups privileged account changes and session revocation."""

    def __init__(self, accounts):
        self._accounts = accounts

    async def bootstrap_developer(self):
        return await self._accounts.bootstrap_developer()

    async def update_user(self, actor: Principal, user_id: UUID, changes: dict):
        return await self._accounts.update_user(actor, user_id, changes)

    async def revoke_sessions(self, actor: Principal, user_id: UUID):
        return await self._accounts.revoke_sessions(actor, user_id)
