"""Fetch and convert the Deezer Pipe GraphQL schema.

Can fetch live from pipe.deezer.com (no auth needed) or convert a local
introspection JSON file. Outputs schema.graphql (SDL) for ariadne-codegen.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, cast

import httpx
from graphql import IntrospectionQuery, build_client_schema, get_introspection_query, print_schema

PIPE_URL = "https://pipe.deezer.com/api"
SCHEMA_JSON = Path("schema.json")
SCHEMA_GRAPHQL = Path("schema.graphql")


def fetch_introspection() -> dict[str, Any]:
    """Fetch the full introspection result from the Pipe API (no auth required)."""
    query = get_introspection_query(descriptions=True)
    resp = httpx.post(PIPE_URL, json={"query": query}, timeout=30)
    resp.raise_for_status()
    data: dict[str, Any] = resp.json()
    if "errors" in data:
        msg = f"Introspection errors: {data['errors']}"
        raise RuntimeError(msg)
    result: dict[str, Any] = data["data"]
    return result


def fix_type_ref(type_ref: dict[str, Any] | None) -> dict[str, Any] | None:
    """Recursively fix truncated type wrappers (LIST/NON_NULL missing ofType)."""
    if type_ref is None:
        return None
    if type_ref.get("ofType"):
        type_ref["ofType"] = fix_type_ref(type_ref["ofType"])
    elif type_ref["kind"] in ("NON_NULL", "LIST"):
        type_ref["ofType"] = {"name": "String", "kind": "SCALAR", "ofType": None}
    return type_ref


def fix_introspection(introspection: dict[str, Any]) -> None:
    """Patch incomplete types from shallow or truncated introspection results."""
    # Fix union types missing possibleTypes and object types missing interfaces
    for t in introspection["__schema"]["types"]:
        if t["kind"] == "UNION" and not t.get("possibleTypes"):
            t["possibleTypes"] = []
        if t["kind"] in ("OBJECT", "INTERFACE") and "interfaces" not in t:
            t["interfaces"] = []

    # Fix truncated type wrappers in directives
    for d in introspection["__schema"].get("directives", []):
        for arg in d.get("args", []):
            fix_type_ref(arg["type"])

    # Fix truncated type wrappers in all types
    for t in introspection["__schema"]["types"]:
        for field in t.get("fields") or []:
            fix_type_ref(field["type"])
            for arg in field.get("args") or []:
                fix_type_ref(arg["type"])
        for inp in t.get("inputFields") or []:
            fix_type_ref(inp["type"])


def convert_to_sdl(introspection: dict[str, Any]) -> str:
    """Build a GraphQL schema from introspection and return as SDL string."""
    fix_introspection(introspection)
    schema = build_client_schema(cast("IntrospectionQuery", introspection))
    sdl: str = print_schema(schema)
    return sdl


def main() -> None:
    """Fetch or load introspection JSON and write schema.graphql."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--fetch",
        action="store_true",
        help="Fetch live introspection from pipe.deezer.com (default: read schema.json)",
    )
    args = parser.parse_args()

    if args.fetch:
        print(f"Fetching introspection from {PIPE_URL}...")  # noqa: T201
        introspection = fetch_introspection()
        with SCHEMA_JSON.open("w") as f:
            json.dump(introspection, f)
        print(f"Saved introspection to {SCHEMA_JSON}")  # noqa: T201
    else:
        with SCHEMA_JSON.open() as f:
            introspection = json.load(f)
        # Handle {"data": {"__schema": ...}} wrapper from older dumps
        if "data" in introspection and "__schema" in introspection["data"]:
            introspection = introspection["data"]

    sdl = convert_to_sdl(introspection)

    with SCHEMA_GRAPHQL.open("w") as f:
        f.write(sdl)

    print(  # noqa: T201
        f"Wrote {SCHEMA_GRAPHQL}: {len(sdl)} chars, {sdl.count(chr(10))} lines"
    )


if __name__ == "__main__":
    main()
