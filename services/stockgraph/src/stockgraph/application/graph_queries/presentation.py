"""Shared filtering of graph properties returned to clients."""


def public_props(props: dict) -> dict:
    return {key: value for key, value in props.items()
            if key not in {"embedding", "profile_embedding", "profile_json"}}
