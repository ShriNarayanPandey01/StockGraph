"""Operator-only provisioning; no HTTP endpoint can self-verify a professional."""

import argparse
import asyncio
from uuid import UUID

from marketgraph_platform.auth import issue_token
from marketgraph_platform.errors import PlatformError
from marketgraph_platform.repository import Repository
from marketgraph_platform.settings import Settings


async def execute(args):
    repository = Repository(Settings())
    try:
        await repository.connect()
        if args.command == "migrate":
            print("Platform migrations applied")
        elif args.command == "provision-user":
            token, digest = issue_token()
            user_id = await repository.provision_user(args.name, digest, args.professional_verified)
            print(f"User ID: {user_id}\nBearer token (shown once): {token}")
        elif args.command == "rotate-token":
            token, digest = issue_token()
            await repository.rotate_token(args.user_id, digest)
            print(f"Bearer token (shown once): {token}")
        elif args.command == "set-professional-verification":
            await repository.set_verified(args.user_id, args.verified)
            print("Professional verification updated")
    finally:
        await repository.close()


def main():
    parser = argparse.ArgumentParser(description="MarketGraph platform operator commands")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("migrate")
    provision = sub.add_parser("provision-user")
    provision.add_argument("--name", required=True)
    provision.add_argument("--professional-verified", action="store_true")
    rotate = sub.add_parser("rotate-token")
    rotate.add_argument("--user-id", type=UUID, required=True)
    verify = sub.add_parser("set-professional-verification")
    verify.add_argument("--user-id", type=UUID, required=True)
    verify.add_argument("--verified", action=argparse.BooleanOptionalAction, required=True)
    args = parser.parse_args()
    if getattr(args, "name", None) is not None and not 1 <= len(args.name.strip()) <= 200:
        parser.error("name must be between 1 and 200 characters")
    try:
        asyncio.run(execute(args))
    except PlatformError as exc:
        parser.exit(1, exc.detail + "\n")
    except Exception:
        parser.exit(1, "Platform operation failed; check database connectivity and migration state\n")


if __name__ == "__main__":
    main()
