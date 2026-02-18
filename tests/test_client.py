"""Tests for the deezer-python-gql client.

Organized into three layers:
1. Client setup — import, instantiation, codegen method presence
2. Auth flow — JWT acquisition, refresh, token parsing (mocked HTTP)
3. Error handling — HTTP errors, invalid responses, GraphQL errors (mocked HTTP)
4. Model smoke tests — one per query, verifying fixtures parse correctly
"""

from __future__ import annotations

import base64
import json
import time
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from deezer_python_gql import DeezerGQLClient
from deezer_python_gql.base_client import (
    DeezerBaseClient,
    GraphQLClientGraphQLMultiError,
    GraphQLClientHttpError,
    GraphQLClientInvalidResponseError,
)
from deezer_python_gql.generated.get_album import GetAlbum
from deezer_python_gql.generated.get_artist import GetArtist
from deezer_python_gql.generated.get_me import GetMe
from deezer_python_gql.generated.get_playlist import GetPlaylist
from deezer_python_gql.generated.get_track import GetTrack
from deezer_python_gql.generated.search import Search

FIXTURES = Path(__file__).parent / "fixtures"


def _load_fixture(name: str) -> dict[str, Any]:
    """Load a JSON fixture file and return its data dict."""
    with (FIXTURES / name).open() as f:
        result: dict[str, Any] = json.load(f)["data"]
    return result


def _make_jwt(exp: float | None = None) -> str:
    """Build a fake JWT with a configurable expiration timestamp.

    :param exp: Unix timestamp for JWT expiry. Defaults to 6 min from now.
    """
    if exp is None:
        exp = time.time() + 360  # 6 min, matching Deezer's real TTL
    header = base64.urlsafe_b64encode(b'{"alg":"ES256"}').rstrip(b"=").decode()
    payload = (
        base64.urlsafe_b64encode(
            json.dumps({"exp": exp}).encode(),
        )
        .rstrip(b"=")
        .decode()
    )
    return f"{header}.{payload}.fake_signature"


def _mock_auth_response(jwt: str | None = None) -> httpx.Response:
    """Create a mock auth.deezer.com response returning a JWT.

    Mimics the real API's text/plain Content-Type containing JSON.
    """
    if jwt is None:
        jwt = _make_jwt()
    return httpx.Response(
        status_code=200,
        text=json.dumps({"jwt": jwt}),
        headers={"Content-Type": "text/plain"},
        request=httpx.Request("POST", "https://auth.deezer.com/login/arl"),
    )


# ---------------------------------------------------------------------------
# 1. Client setup
# ---------------------------------------------------------------------------


def test_client_import() -> None:
    """Verify the client class is importable from the top-level package."""
    assert DeezerGQLClient is not None


def test_client_instantiation() -> None:
    """Verify the client can be instantiated with an ARL."""
    client = DeezerGQLClient(arl="test_arl_value")
    assert client._arl == "test_arl_value"  # noqa: SLF001
    assert client.url == "https://pipe.deezer.com/api"


def test_client_has_generated_methods() -> None:
    """Verify that codegen produced all expected query methods."""
    client = DeezerGQLClient(arl="test")
    expected_methods = ["get_me", "get_track", "get_album", "get_artist", "get_playlist", "search"]
    for method in expected_methods:
        assert hasattr(client, method), f"Missing method: {method}"
        assert callable(getattr(client, method))


# ---------------------------------------------------------------------------
# 2. Auth flow (mocked HTTP)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_auth_acquires_jwt_on_first_request() -> None:
    """Verify the client fetches a JWT via ARL on the first execute() call."""
    jwt = _make_jwt()
    client = DeezerBaseClient(arl="test_arl")

    mock_auth = AsyncMock(return_value=_mock_auth_response(jwt))
    mock_gql = AsyncMock(
        return_value=httpx.Response(
            200,
            json={"data": {"me": {"id": "1"}}},
            request=httpx.Request("POST", DeezerBaseClient.PIPE_URL),
        ),
    )

    with patch("deezer_python_gql.base_client.httpx.AsyncClient") as mock_client_cls:
        mock_instance = AsyncMock()
        mock_instance.post = mock_auth
        mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
        mock_instance.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_instance

        # First call: should trigger auth, then make GQL request
        # Override post to return auth first, then GQL response
        mock_instance.post = AsyncMock(
            side_effect=[_mock_auth_response(jwt), mock_gql.return_value],
        )
        resp = await client.execute(query="{ me { id } }")

    assert resp.status_code == 200
    assert client._jwt == jwt  # noqa: SLF001


@pytest.mark.asyncio
async def test_auth_reuses_valid_jwt() -> None:
    """Verify the client does NOT re-auth when the JWT is still valid."""
    client = DeezerBaseClient(arl="test_arl")
    # Pre-seed a valid JWT (expires far in the future)
    client._jwt = _make_jwt(exp=time.time() + 600)  # noqa: SLF001
    client._jwt_expires_at = time.time() + 600  # noqa: SLF001

    gql_response = httpx.Response(
        200,
        json={"data": {"me": {"id": "1"}}},
        request=httpx.Request("POST", DeezerBaseClient.PIPE_URL),
    )

    with patch("deezer_python_gql.base_client.httpx.AsyncClient") as mock_client_cls:
        mock_instance = AsyncMock()
        mock_instance.post = AsyncMock(return_value=gql_response)
        mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
        mock_instance.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_instance

        await client.execute(query="{ me { id } }")

        # Only 1 call (the GQL query), no auth call
        assert mock_instance.post.call_count == 1


@pytest.mark.asyncio
async def test_auth_refreshes_expiring_jwt() -> None:
    """Verify the client refreshes when JWT is within the 30s margin."""
    client = DeezerBaseClient(arl="test_arl")
    # Pre-seed a JWT that expires in 10 seconds (within 30s margin)
    client._jwt = _make_jwt(exp=time.time() + 10)  # noqa: SLF001
    client._jwt_expires_at = time.time() + 10  # noqa: SLF001

    new_jwt = _make_jwt(exp=time.time() + 600)

    with patch("deezer_python_gql.base_client.httpx.AsyncClient") as mock_client_cls:
        mock_instance = AsyncMock()
        mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
        mock_instance.__aexit__ = AsyncMock(return_value=False)
        # Auth response, then GQL response
        mock_instance.post = AsyncMock(
            side_effect=[
                _mock_auth_response(new_jwt),
                httpx.Response(
                    200,
                    json={"data": {"me": {"id": "1"}}},
                    request=httpx.Request("POST", DeezerBaseClient.PIPE_URL),
                ),
            ],
        )
        mock_client_cls.return_value = mock_instance

        await client.execute(query="{ me { id } }")

    assert client._jwt == new_jwt  # noqa: SLF001


@pytest.mark.asyncio
async def test_auth_sends_arl_cookie_to_correct_domain() -> None:
    """Verify the ARL cookie is sent to auth.deezer.com, not www.deezer.com."""
    client = DeezerBaseClient(arl="my_secret_arl")

    with patch("deezer_python_gql.base_client.httpx.AsyncClient") as mock_client_cls:
        mock_instance = AsyncMock()
        mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
        mock_instance.__aexit__ = AsyncMock(return_value=False)
        mock_instance.post = AsyncMock(
            side_effect=[
                _mock_auth_response(),
                httpx.Response(
                    200,
                    json={"data": {"me": {"id": "1"}}},
                    request=httpx.Request("POST", DeezerBaseClient.PIPE_URL),
                ),
            ],
        )
        mock_client_cls.return_value = mock_instance

        await client.execute(query="{ me { id } }")

    # First call was the auth request
    auth_call = mock_instance.post.call_args_list[0]
    assert auth_call.args[0] == "https://auth.deezer.com/login/arl"
    assert auth_call.kwargs["cookies"] == {"arl": "my_secret_arl"}


@pytest.mark.asyncio
async def test_auth_parses_text_plain_response() -> None:
    """Verify the client handles auth.deezer.com's text/plain JSON response."""
    jwt = _make_jwt()
    client = DeezerBaseClient(arl="test")

    # Verify _ensure_jwt correctly parses the text/plain body
    with patch("deezer_python_gql.base_client.httpx.AsyncClient") as mock_client_cls:
        mock_instance = AsyncMock()
        mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
        mock_instance.__aexit__ = AsyncMock(return_value=False)
        mock_instance.post = AsyncMock(return_value=_mock_auth_response(jwt))
        mock_client_cls.return_value = mock_instance

        result = await client._ensure_jwt()  # noqa: SLF001

    assert result == jwt
    assert client._jwt_expires_at > 0  # noqa: SLF001


# ---------------------------------------------------------------------------
# 3. Error handling (mocked HTTP)
# ---------------------------------------------------------------------------


def test_get_data_raises_on_http_error() -> None:
    """Verify get_data raises GraphQLClientHttpError for non-2xx responses."""
    client = DeezerBaseClient(arl="test")
    response = httpx.Response(
        status_code=500,
        text="Internal Server Error",
        request=httpx.Request("POST", DeezerBaseClient.PIPE_URL),
    )

    with pytest.raises(GraphQLClientHttpError) as exc_info:
        client.get_data(response)
    assert exc_info.value.status_code == 500


def test_get_data_raises_on_invalid_json() -> None:
    """Verify get_data raises GraphQLClientInvalidResponseError for malformed JSON."""
    client = DeezerBaseClient(arl="test")
    response = httpx.Response(
        status_code=200,
        text="this is not json",
        request=httpx.Request("POST", DeezerBaseClient.PIPE_URL),
    )

    with pytest.raises(GraphQLClientInvalidResponseError):
        client.get_data(response)


def test_get_data_raises_on_missing_data_key() -> None:
    """Verify get_data raises when response JSON has neither 'data' nor 'errors'."""
    client = DeezerBaseClient(arl="test")
    response = httpx.Response(
        status_code=200,
        json={"something": "unexpected"},
        request=httpx.Request("POST", DeezerBaseClient.PIPE_URL),
    )

    with pytest.raises(GraphQLClientInvalidResponseError):
        client.get_data(response)


def test_get_data_raises_on_graphql_errors() -> None:
    """Verify get_data raises GraphQLClientGraphQLMultiError for GraphQL-level errors."""
    client = DeezerBaseClient(arl="test")
    response = httpx.Response(
        status_code=200,
        json={
            "data": None,
            "errors": [
                {"message": "Track not found", "locations": [{"line": 1, "column": 1}]},
                {"message": "Unauthorized"},
            ],
        },
        request=httpx.Request("POST", DeezerBaseClient.PIPE_URL),
    )

    with pytest.raises(GraphQLClientGraphQLMultiError) as exc_info:
        client.get_data(response)
    assert len(exc_info.value.errors) == 2
    assert exc_info.value.errors[0].message == "Track not found"
    assert exc_info.value.errors[1].message == "Unauthorized"


def test_get_data_returns_data_on_success() -> None:
    """Verify get_data returns the 'data' dict on a normal response."""
    client = DeezerBaseClient(arl="test")
    response = httpx.Response(
        status_code=200,
        json={"data": {"track": {"id": "123", "title": "Test"}}},
        request=httpx.Request("POST", DeezerBaseClient.PIPE_URL),
    )

    data = client.get_data(response)
    assert data == {"track": {"id": "123", "title": "Test"}}


# ---------------------------------------------------------------------------
# 4. Model smoke tests (one per query — fixture-based)
# ---------------------------------------------------------------------------


def test_smoke_get_me() -> None:
    """Verify GetMe fixture parses and the user ID is accessible."""
    data = _load_fixture("get_me.json")
    result = GetMe.model_validate(data)
    assert result.me is not None
    assert result.me.id == "1234567890"


def test_smoke_get_track() -> None:
    """Verify GetTrack fixture parses with nested album, contributors, and media."""
    data = _load_fixture("get_track.json")
    track = GetTrack.model_validate(data).track
    assert track is not None
    assert track.id == "3135556"
    assert track.title == "Harder, Better, Faster, Stronger"
    assert track.duration == 226
    # Nested structures
    assert track.album is not None
    assert track.album.id == "302127"
    assert len(track.contributors.edges) > 0
    assert track.media is not None
    assert track.media.token.payload  # non-empty token


def test_smoke_get_album() -> None:
    """Verify GetAlbum fixture parses with cover, contributors, and paginated tracks."""
    data = _load_fixture("get_album.json")
    album = GetAlbum.model_validate(data).album
    assert album is not None
    assert album.id == "302127"
    assert album.display_title == "Discovery"
    assert album.tracks_count > 0
    assert len(album.tracks.edges) > 0
    assert len(album.contributors.edges) > 0


def test_smoke_get_artist() -> None:
    """Verify GetArtist fixture parses with picture, top tracks, and albums."""
    data = _load_fixture("get_artist.json")
    artist = GetArtist.model_validate(data).artist
    assert artist is not None
    assert artist.id == "27"
    assert artist.name == "Daft Punk"
    assert artist.fans_count > 0
    assert artist.top_tracks is not None
    assert len(artist.top_tracks.edges) > 0
    assert len(artist.albums.edges) > 0


def test_smoke_get_playlist() -> None:
    """Verify GetPlaylist fixture parses with owner and paginated tracks."""
    data = _load_fixture("get_playlist.json")
    playlist = GetPlaylist.model_validate(data).playlist
    assert playlist is not None
    assert playlist.id == "53362031"
    assert playlist.title
    assert playlist.owner is not None
    assert len(playlist.tracks.edges) > 0


def test_smoke_search() -> None:
    """Verify Search fixture parses all result types with pagination info."""
    data = _load_fixture("search.json")
    search = Search.model_validate(data).search
    assert search is not None
    results = search.results
    assert len(results.tracks.edges) > 0
    assert len(results.albums.edges) > 0
    assert len(results.artists.edges) > 0
    assert len(results.playlists.edges) > 0
    assert isinstance(results.tracks.page_info.has_next_page, bool)
