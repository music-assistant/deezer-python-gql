"""Run ad-hoc GraphQL queries against the Deezer Pipe API.

Reads DEEZER_ARL from a .env file in the project root and handles
JWT auth automatically via DeezerBaseClient.

Usage::

    # Run a .graphql file
    uv run python scripts/explore.py queries/get_me.graphql

    # Run an inline query
    uv run python scripts/explore.py -q '{ me { id } }'

    # Pass variables as JSON
    uv run python scripts/explore.py -q 'query($id: String!) { track(trackId: $id) { title } }' \
        -v '{"id": "3135556"}'

    # Make target
    make explore Q=queries/get_me.graphql
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

import httpx

from deezer_python_gql.base_client import DeezerBaseClient


def load_arl() -> str:
    """Load DEEZER_ARL from .env file in project root."""
    env_file = Path(__file__).resolve().parent.parent / ".env"
    if not env_file.exists():
        print("Error: .env file not found. Create it with:", file=sys.stderr)  # noqa: T201
        print("  echo 'DEEZER_ARL=your_arl_here' > .env", file=sys.stderr)  # noqa: T201
        sys.exit(1)

    for raw_line in env_file.read_text().splitlines():
        stripped = raw_line.strip()
        if stripped.startswith("#") or not stripped:
            continue
        if stripped.startswith("DEEZER_ARL="):
            value = stripped.split("=", 1)[1].strip().strip("'\"")
            if value and value != "your_arl_here":
                return value

    print("Error: DEEZER_ARL not set in .env file.", file=sys.stderr)  # noqa: T201
    sys.exit(1)


async def run_query(arl: str, query: str, variables: dict[str, Any] | None = None) -> None:
    """Execute a GraphQL query and print the JSON response."""
    client = DeezerBaseClient(arl=arl)
    async with httpx.AsyncClient() as http:
        client._http_client = http  # noqa: SLF001
        response = await client.execute(query=query, variables=variables)

    # Print raw JSON response (not just data — includes errors if any)
    try:
        result = response.json()
    except ValueError:
        result = {"raw": response.text}

    print(json.dumps(result, indent=2, ensure_ascii=False))  # noqa: T201


def main() -> None:
    """Parse args and run the query."""
    parser = argparse.ArgumentParser(
        description="Run GraphQL queries against Deezer's Pipe API.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Examples:\n"
        "  uv run python scripts/explore.py queries/get_me.graphql\n"
        "  uv run python scripts/explore.py -q '{ me { id } }'\n"
        "  uv run python scripts/explore.py -q "
        "'query($id: String!) { track(trackId: $id) { title } }' "
        '-v \'{"id": "3135556"}\'',
    )
    parser.add_argument(
        "file",
        nargs="?",
        help="Path to a .graphql file to execute",
    )
    parser.add_argument(
        "-q",
        "--query",
        help="Inline GraphQL query string",
    )
    parser.add_argument(
        "-v",
        "--variables",
        help="JSON string of query variables",
    )
    args = parser.parse_args()

    if args.file:
        path = Path(args.file)
        if not path.exists():
            print(f"Error: file not found: {path}", file=sys.stderr)  # noqa: T201
            sys.exit(1)
        query = path.read_text()
    elif args.query:
        query = args.query
    else:
        parser.print_help()
        sys.exit(1)

    variables = None
    if args.variables:
        variables = json.loads(args.variables)

    arl = load_arl()
    asyncio.run(run_query(arl, query, variables))


if __name__ == "__main__":
    main()
