"""Custom async base client with Deezer ARL → JWT authentication."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from base64 import urlsafe_b64decode
from dataclasses import dataclass
from typing import Any, ClassVar, Self, cast

from aiohttp import ClientSession, ClientTimeout

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class GQLResponse:
    """
    Lightweight response container for GraphQL HTTP responses.

    aiohttp responses cannot escape their context manager, so we capture
    the essential fields inside the ``async with`` block and return this.
    Carries the originating operation name and variables so error handling
    and logging stay correct under concurrent requests.
    """

    status: int
    data: bytes
    is_success: bool
    operation_name: str | None = None
    variables: dict[str, Any] | None = None


class GraphQLClientError(Exception):
    """Base exception for GraphQL client errors."""


class GraphQLClientAuthError(GraphQLClientError):
    """
    Raised when ARL → JWT authentication definitively fails.

    Indicates a bad or expired ARL cookie (or an unexpected auth response),
    not a transient network/server problem — consumers should treat this as
    "re-check your ARL token" rather than retry.
    """


class GraphQLClientHttpError(GraphQLClientError):
    """Raised when the HTTP response indicates an error."""

    def __init__(self, status_code: int, response: GQLResponse) -> None:
        self.status_code = status_code
        self.response = response
        super().__init__(f"HTTP status code: {status_code}")


class GraphQLClientInvalidResponseError(GraphQLClientError):
    """Raised when the response cannot be parsed as valid GraphQL."""

    def __init__(self, response: GQLResponse) -> None:
        self.response = response
        super().__init__("Invalid response format")


class GraphQLClientGraphQLError(GraphQLClientError):
    """A single GraphQL error from the response."""

    def __init__(self, message: str, locations: Any = None, path: Any = None) -> None:
        self.message = message
        self.locations = locations
        self.path = path
        super().__init__(message)


class GraphQLClientGraphQLMultiError(GraphQLClientError):
    """Raised when the GraphQL response contains errors."""

    def __init__(
        self,
        errors: list[GraphQLClientGraphQLError],
        data: Any = None,
        operation_name: str | None = None,
    ) -> None:
        self.errors = errors
        self.data = data
        self.operation_name = operation_name
        msg = f"{operation_name}: {errors}" if operation_name else str(errors)
        super().__init__(msg)

    @classmethod
    def from_errors_dicts(
        cls,
        errors_dicts: list[dict[str, Any]],
        data: Any = None,
        operation_name: str | None = None,
    ) -> GraphQLClientGraphQLMultiError:
        """Create from raw error dicts in a GraphQL response."""
        errors = [
            GraphQLClientGraphQLError(
                message=e.get("message", "Unknown error"),
                locations=e.get("locations"),
                path=e.get("path"),
            )
            for e in errors_dicts
        ]
        return cls(errors=errors, data=data, operation_name=operation_name)


class DeezerBaseClient:
    """
    Async HTTP client for Deezer's Pipe GraphQL API with ARL-based auth.

    Manages its own aiohttp session by default. Pass an external
    ``session`` to share a connection pool across multiple clients.

    :param arl: Deezer ARL cookie value for authentication.
    :param url: GraphQL endpoint URL (defaults to Pipe API).
    :param session: Optional pre-configured aiohttp.ClientSession.
        If provided, the caller is responsible for closing it.
    """

    PIPE_URL = "https://pipe.deezer.com/api"
    AUTH_URL = "https://auth.deezer.com/login/arl"
    JWT_REFRESH_MARGIN_SECONDS = 30
    REQUEST_TIMEOUT_SECONDS = 30
    AUDIOBOOK_CHECK_CHUNK_SIZE = 50

    def __init__(
        self,
        arl: str,
        url: str = PIPE_URL,
        session: ClientSession | None = None,
    ) -> None:
        self.url = url
        self._arl = arl
        self._session = session
        self._owns_session = session is None
        self._jwt: str | None = None
        self._jwt_expires_at: float = 0
        self._jwt_lock = asyncio.Lock()

    def _get_session(self) -> ClientSession:
        """Return the HTTP session, creating an internal one if needed."""
        if self._session is None:
            self._session = ClientSession()
            self._owns_session = True
        return self._session

    async def close(self) -> None:
        """
        Close the internal HTTP session if we own it.

        Safe to call multiple times. Does nothing if an external
        ``session`` was provided at construction time.
        """
        if self._owns_session and self._session is not None:
            await self._session.close()
            self._session = None

    async def __aenter__(self) -> Self:
        """Enter the async context manager."""
        return self

    async def __aexit__(self, *args: object) -> None:
        """Exit the async context manager, closing internal resources."""
        await self.close()

    async def execute(
        self,
        query: str,
        operation_name: str | None = None,
        variables: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> GQLResponse:
        """
        Execute a GraphQL query against the Pipe API.

        :param query: The GraphQL query string.
        :param operation_name: Optional operation name for multi-operation documents.
        :param variables: Optional query variables.
        :param kwargs: Additional keyword arguments passed to the session request.
        """
        logger.debug("GQL execute: %s (variables=%s)", operation_name or "<unnamed>", variables)
        jwt = await self._ensure_jwt()

        headers: dict[str, str] = kwargs.pop("headers", None) or {}
        headers["Authorization"] = f"Bearer {jwt}"
        headers["Content-Type"] = "application/json"
        kwargs.setdefault("timeout", ClientTimeout(total=self.REQUEST_TIMEOUT_SECONDS))

        payload: dict[str, Any] = {"query": query}
        if operation_name:
            payload["operationName"] = operation_name
        if variables:
            # Filter out UNSET sentinel values that are not JSON-serializable.
            # Inline import avoids depending on generated code at module level.
            from deezer_python_gql.generated.base_model import UnsetType  # noqa: PLC0415

            payload["variables"] = {
                k: v for k, v in variables.items() if not isinstance(v, UnsetType)
            }

        session = self._get_session()
        async with session.post(self.url, json=payload, headers=headers, **kwargs) as resp:
            body = await resp.read()
            gql_response = GQLResponse(
                status=resp.status,
                data=body,
                is_success=resp.ok,
                operation_name=operation_name,
                variables=variables,
            )

        logger.debug(
            "GQL response: %s status=%s length=%s",
            operation_name or "<unnamed>",
            gql_response.status,
            len(gql_response.data),
        )
        return gql_response

    def get_data(self, response: GQLResponse) -> dict[str, Any]:
        """
        Parse a GraphQL response and return the data dict.

        :param response: The GQLResponse from execute().
        """
        if not response.is_success:
            raise GraphQLClientHttpError(status_code=response.status, response=response)

        try:
            response_json = json.loads(response.data)
        except ValueError as exc:
            raise GraphQLClientInvalidResponseError(response=response) from exc

        if (not isinstance(response_json, dict)) or (
            "data" not in response_json and "errors" not in response_json
        ):
            raise GraphQLClientInvalidResponseError(response=response)

        data = response_json.get("data")
        errors = response_json.get("errors")

        if errors:
            op = response.operation_name or "<unknown>"
            variables = response.variables
            if data:
                # Partial success — some items failed (e.g. deleted albums in favorites).
                # Log the errors but return the valid data.
                error_details = [
                    f"{e.get('message', 'Unknown error')} (path={e.get('path')})" for e in errors
                ]
                logger.warning(
                    "GraphQL response for %s (variables=%s) contained %d error(s): %s",
                    op,
                    variables,
                    len(errors),
                    error_details,
                )
            else:
                raise GraphQLClientGraphQLMultiError.from_errors_dicts(
                    errors_dicts=errors, data=data, operation_name=op
                )

        # The Deezer API omits __typename for single-member union types
        # (e.g. Contributor = Artist). Pydantic discriminated unions require it,
        # so we inject the missing field before model validation.
        self._inject_missing_typenames(data)

        return cast("dict[str, Any]", data)

    # Map of parent key → child key → __typename value for single-member unions
    # where the Deezer API omits the discriminator.
    _TYPENAME_PATCHES: ClassVar[dict[str, dict[str, str]]] = {
        "contributors": {"node": "Artist"},
    }

    @classmethod
    def _inject_missing_typenames(cls, obj: Any) -> None:
        """Recursively inject __typename into nodes where the API omits it."""
        if isinstance(obj, dict):
            for parent_key, patches in cls._TYPENAME_PATCHES.items():
                if parent_key in obj:
                    container = obj[parent_key]
                    if isinstance(container, dict) and "edges" in container:
                        for edge in container["edges"]:
                            if isinstance(edge, dict):
                                for child_key, typename in patches.items():
                                    node = edge.get(child_key)
                                    if isinstance(node, dict) and "__typename" not in node:
                                        node["__typename"] = typename
            for value in obj.values():
                cls._inject_missing_typenames(value)
        elif isinstance(obj, list):
            for item in obj:
                cls._inject_missing_typenames(item)

    def _jwt_is_valid(self) -> bool:
        """Return True if the current JWT exists and is not about to expire."""
        return self._jwt is not None and time.time() < (
            self._jwt_expires_at - self.JWT_REFRESH_MARGIN_SECONDS
        )

    async def _ensure_jwt(self) -> str:
        """Acquire or refresh the JWT token from ARL cookie."""
        if self._jwt is not None and self._jwt_is_valid():
            return self._jwt

        # Serialize refreshes so concurrent expired-JWT requests trigger
        # exactly one auth call.
        async with self._jwt_lock:
            if self._jwt is not None and self._jwt_is_valid():
                return self._jwt

            logger.debug("JWT expired or missing, refreshing from ARL")
            params = {"jo": "p", "rto": "c", "i": "c"}

            session = self._get_session()
            async with session.post(
                self.AUTH_URL,
                params=params,
                cookies={"arl": self._arl},
                timeout=ClientTimeout(total=10),
            ) as resp:
                status = resp.status
                is_success = resp.ok
                # Response body is text/plain containing JSON
                text = await resp.text()

            if not is_success:
                if 400 <= status < 500:
                    msg = f"ARL authentication rejected by auth.deezer.com (HTTP {status})"
                    raise GraphQLClientAuthError(msg)
                raise GraphQLClientHttpError(
                    status_code=status,
                    response=GQLResponse(status=status, data=text.encode(), is_success=False),
                )

            try:
                data = json.loads(text)
                jwt: str = data["jwt"]
                # Decode expiration from JWT payload (second segment, base64url-encoded)
                payload_segment = jwt.split(".")[1]
                # Add padding for base64 decoding
                padded = payload_segment + "=" * (-len(payload_segment) % 4)
                payload = json.loads(urlsafe_b64decode(padded))
                expires_at = float(payload["exp"])
            except (ValueError, KeyError, IndexError, TypeError, AttributeError) as exc:
                msg = "Unexpected response from auth.deezer.com (invalid or missing JWT)"
                raise GraphQLClientAuthError(msg) from exc

            self._jwt = jwt
            self._jwt_expires_at = expires_at
            logger.debug("JWT acquired, expires at %s", self._jwt_expires_at)

            return jwt

    async def check_audiobook_ids(self, album_ids: list[str]) -> set[str]:
        """
        Check which album IDs are also valid audiobooks on Deezer.

        Queries are chunked to stay below the API's query complexity limit.

        :param album_ids: List of Deezer album/audiobook IDs to check.
        """
        audiobook_ids: set[str] = set()
        for start in range(0, len(album_ids), self.AUDIOBOOK_CHECK_CHUNK_SIZE):
            chunk = album_ids[start : start + self.AUDIOBOOK_CHECK_CHUNK_SIZE]
            audiobook_ids |= await self._check_audiobook_ids_chunk(chunk)
        return audiobook_ids

    async def _check_audiobook_ids_chunk(self, album_ids: list[str]) -> set[str]:
        """Check a single chunk of album IDs via one aliased query."""
        # Query displayTitle alongside id — querying only { id } echoes back the
        # input without validating that the ID is actually an audiobook.
        # json.dumps escapes the IDs so they cannot break out of the string
        # literal (this is a public library API — IDs may come from anywhere).
        parts = [
            f"a{i}: audiobook(audiobookId: {json.dumps(aid)}) {{ id displayTitle }}"
            for i, aid in enumerate(album_ids)
        ]
        query = "query CheckAudiobookIds { " + " ".join(parts) + " }"

        resp = await self.execute(query, operation_name="CheckAudiobookIds")
        try:
            data = self.get_data(resp)
        except GraphQLClientGraphQLMultiError as err:
            # Only swallow errors scoped to our aliased audiobook fields —
            # that is the legitimate "these IDs are not audiobooks" case.
            # Anything else (complexity limit, transient API failure) must
            # surface, otherwise audiobooks silently degrade to albums.
            aliases = {f"a{i}" for i in range(len(album_ids))}
            if all(e.path and e.path[0] in aliases for e in err.errors):
                logger.debug("CheckAudiobookIds: all %d IDs returned errors", len(album_ids))
                return set()
            raise

        audiobook_ids: set[str] = set()
        for i, aid in enumerate(album_ids):
            node = data.get(f"a{i}")
            # The API echoes back {id} for any valid album, so we must check
            # a real audiobook field like displayTitle to distinguish.
            if node is not None and node.get("displayTitle") is not None:
                audiobook_ids.add(aid)
        return audiobook_ids
