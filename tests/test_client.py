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
from deezer_python_gql.generated.add_album_to_favorite import AddAlbumToFavorite
from deezer_python_gql.generated.add_artist_to_favorite import AddArtistToFavorite
from deezer_python_gql.generated.add_audiobook_to_favorite import AddAudiobookToFavorite
from deezer_python_gql.generated.add_playlist_to_favorite import AddPlaylistToFavorite
from deezer_python_gql.generated.add_podcast_to_favorite import AddPodcastToFavorite
from deezer_python_gql.generated.add_track_to_favorite import AddTrackToFavorite
from deezer_python_gql.generated.add_tracks_to_playlist import AddTracksToPlaylist
from deezer_python_gql.generated.bookmark_podcast_episode import BookmarkPodcastEpisode
from deezer_python_gql.generated.create_playlist import CreatePlaylist
from deezer_python_gql.generated.delete_playlist import DeletePlaylist
from deezer_python_gql.generated.enums import PodcastType
from deezer_python_gql.generated.get_album import GetAlbum
from deezer_python_gql.generated.get_artist import GetArtist
from deezer_python_gql.generated.get_artist_mix import GetArtistMix
from deezer_python_gql.generated.get_audiobook import GetAudiobook
from deezer_python_gql.generated.get_audiobook_chapter import GetAudiobookChapter
from deezer_python_gql.generated.get_charts import GetCharts
from deezer_python_gql.generated.get_favorite_albums import GetFavoriteAlbums
from deezer_python_gql.generated.get_favorite_artists import GetFavoriteArtists
from deezer_python_gql.generated.get_favorite_audiobooks import GetFavoriteAudiobooks
from deezer_python_gql.generated.get_favorite_playlists import GetFavoritePlaylists
from deezer_python_gql.generated.get_favorite_podcasts import GetFavoritePodcasts
from deezer_python_gql.generated.get_favorite_tracks import GetFavoriteTracks
from deezer_python_gql.generated.get_flow import GetFlow
from deezer_python_gql.generated.get_flow_batch import GetFlowBatch
from deezer_python_gql.generated.get_flow_config_tracks import GetFlowConfigTracks
from deezer_python_gql.generated.get_flow_configs import GetFlowConfigs
from deezer_python_gql.generated.get_livestream import GetLivestream
from deezer_python_gql.generated.get_made_for_me import GetMadeForMe
from deezer_python_gql.generated.get_me import GetMe
from deezer_python_gql.generated.get_music_together_affinity import (
    GetMusicTogetherAffinity,
)
from deezer_python_gql.generated.get_music_together_group import GetMusicTogetherGroup
from deezer_python_gql.generated.get_music_together_groups import GetMusicTogetherGroups
from deezer_python_gql.generated.get_playlist import GetPlaylist
from deezer_python_gql.generated.get_podcast import GetPodcast
from deezer_python_gql.generated.get_podcast_episode import GetPodcastEpisode
from deezer_python_gql.generated.get_podcast_episode_bookmarks import (
    GetPodcastEpisodeBookmarks,
)
from deezer_python_gql.generated.get_podcast_episodes_by_ids import (
    GetPodcastEpisodesByIds,
)
from deezer_python_gql.generated.get_recently_played import GetRecentlyPlayed
from deezer_python_gql.generated.get_recommendations import GetRecommendations
from deezer_python_gql.generated.get_similar_tracks import GetSimilarTracks
from deezer_python_gql.generated.get_smart_tracklist import GetSmartTracklist
from deezer_python_gql.generated.get_track import GetTrack
from deezer_python_gql.generated.get_track_mix import GetTrackMix
from deezer_python_gql.generated.get_user_charts import GetUserCharts
from deezer_python_gql.generated.get_user_playlists import GetUserPlaylists
from deezer_python_gql.generated.mark_as_not_played_podcast_episode import (
    MarkAsNotPlayedPodcastEpisode,
)
from deezer_python_gql.generated.mark_as_played_podcast_episode import (
    MarkAsPlayedPodcastEpisode,
)
from deezer_python_gql.generated.music_together_create_group import (
    MusicTogetherCreateGroup,
)
from deezer_python_gql.generated.music_together_generate_group_name import (
    MusicTogetherGenerateGroupName,
)
from deezer_python_gql.generated.music_together_join_group import MusicTogetherJoinGroup
from deezer_python_gql.generated.music_together_leave_group import MusicTogetherLeaveGroup
from deezer_python_gql.generated.remove_album_from_favorite import RemoveAlbumFromFavorite
from deezer_python_gql.generated.remove_artist_from_favorite import RemoveArtistFromFavorite
from deezer_python_gql.generated.remove_audiobook_from_favorite import (
    RemoveAudiobookFromFavorite,
)
from deezer_python_gql.generated.remove_playlist_from_favorite import (
    RemovePlaylistFromFavorite,
)
from deezer_python_gql.generated.remove_podcast_from_favorite import (
    RemovePodcastFromFavorite,
)
from deezer_python_gql.generated.remove_track_from_favorite import RemoveTrackFromFavorite
from deezer_python_gql.generated.remove_tracks_from_playlist import RemoveTracksFromPlaylist
from deezer_python_gql.generated.search import Search
from deezer_python_gql.generated.search_flows import SearchFlows
from deezer_python_gql.generated.unbookmark_podcast_episode import UnbookmarkPodcastEpisode
from deezer_python_gql.generated.update_playlist import UpdatePlaylist

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
    expected_methods = [
        "get_me",
        "get_track",
        "get_album",
        "get_artist",
        "get_playlist",
        "search",
        "get_flow",
        "get_flow_batch",
        "get_flow_configs",
        "get_flow_config_tracks",
        "get_made_for_me",
        "get_smart_tracklist",
        "get_charts",
        "get_recommendations",
        "get_recently_played",
        "get_favorite_artists",
        "get_favorite_albums",
        "get_favorite_tracks",
        "get_favorite_playlists",
        "get_livestream",
        "search_flows",
        "get_user_charts",
        "get_user_playlists",
        "add_artist_to_favorite",
        "remove_artist_from_favorite",
        "add_album_to_favorite",
        "remove_album_from_favorite",
        "add_track_to_favorite",
        "remove_track_from_favorite",
        "add_playlist_to_favorite",
        "remove_playlist_from_favorite",
        "create_playlist",
        "update_playlist",
        "delete_playlist",
        "add_tracks_to_playlist",
        "remove_tracks_from_playlist",
        "get_podcast",
        "get_podcast_episode",
        "get_podcast_episodes_by_ids",
        "get_favorite_podcasts",
        "get_podcast_episode_bookmarks",
        "add_podcast_to_favorite",
        "remove_podcast_from_favorite",
        "bookmark_podcast_episode",
        "unbookmark_podcast_episode",
        "mark_as_played_podcast_episode",
        "mark_as_not_played_podcast_episode",
        "get_artist_mix",
        "get_track_mix",
        "get_similar_tracks",
        "get_audiobook",
        "get_audiobook_chapter",
        "get_favorite_audiobooks",
        "add_audiobook_to_favorite",
        "remove_audiobook_from_favorite",
        "get_music_together_groups",
        "get_music_together_group",
        "get_music_together_affinity",
        "music_together_create_group",
        "music_together_join_group",
        "music_together_leave_group",
        "music_together_refresh_suggested_tracklist",
        "music_together_update_group_settings",
        "music_together_generate_group_name",
    ]
    for method in expected_methods:
        assert hasattr(client, method), f"Missing method: {method}"
        assert callable(getattr(client, method))


# ---------------------------------------------------------------------------
# 2. Lifecycle (connection pool management)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_close_shuts_down_internal_client() -> None:
    """Verify close() calls aclose() on the internally-created httpx client."""
    client = DeezerBaseClient(arl="test")

    with patch("deezer_python_gql.base_client.httpx.AsyncClient") as mock_cls:
        mock_instance = AsyncMock()
        mock_cls.return_value = mock_instance

        # Trigger lazy creation
        client._get_http_client()  # noqa: SLF001
        assert client._http_client is mock_instance  # noqa: SLF001

        await client.close()

    mock_instance.aclose.assert_awaited_once()
    assert client._http_client is None  # noqa: SLF001


@pytest.mark.asyncio
async def test_close_skips_external_client() -> None:
    """Verify close() does NOT close an externally-provided httpx client."""
    external = AsyncMock(spec=httpx.AsyncClient)
    client = DeezerBaseClient(arl="test", http_client=external)

    await client.close()

    external.aclose.assert_not_awaited()


@pytest.mark.asyncio
async def test_context_manager_calls_close() -> None:
    """Verify the async context manager closes the client on exit."""
    with patch("deezer_python_gql.base_client.httpx.AsyncClient") as mock_cls:
        mock_instance = AsyncMock()
        mock_cls.return_value = mock_instance

        async with DeezerBaseClient(arl="test") as client:
            client._get_http_client()  # noqa: SLF001

    mock_instance.aclose.assert_awaited_once()


# ---------------------------------------------------------------------------
# 3. Auth flow (mocked HTTP)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_auth_acquires_jwt_on_first_request() -> None:
    """Verify the client fetches a JWT via ARL on the first execute() call."""
    jwt = _make_jwt()
    client = DeezerBaseClient(arl="test_arl")

    gql_response = httpx.Response(
        200,
        json={"data": {"me": {"id": "1"}}},
        request=httpx.Request("POST", DeezerBaseClient.PIPE_URL),
    )

    with patch("deezer_python_gql.base_client.httpx.AsyncClient") as mock_client_cls:
        mock_instance = AsyncMock()
        mock_instance.post = AsyncMock(
            side_effect=[_mock_auth_response(jwt), gql_response],
        )
        mock_client_cls.return_value = mock_instance

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
        mock_instance.post = AsyncMock(return_value=_mock_auth_response(jwt))
        mock_client_cls.return_value = mock_instance

        result = await client._ensure_jwt()  # noqa: SLF001

    assert result == jwt
    assert client._jwt_expires_at > 0  # noqa: SLF001


# ---------------------------------------------------------------------------
# 4. Error handling (mocked HTTP)
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
# 5. check_audiobook_ids tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_audiobook_ids_returns_matching() -> None:
    """Verify check_audiobook_ids returns IDs that are valid audiobooks."""
    client = DeezerBaseClient(arl="test_arl")
    client._jwt = _make_jwt(exp=time.time() + 600)  # noqa: SLF001
    client._jwt_expires_at = time.time() + 600  # noqa: SLF001

    # a0 is an audiobook (has displayTitle), a1 is not (displayTitle is null)
    gql_response = httpx.Response(
        200,
        json={
            "data": {
                "a0": {"id": "111", "displayTitle": "Test Book"},
                "a1": {"id": "222", "displayTitle": None},
            }
        },
        request=httpx.Request("POST", DeezerBaseClient.PIPE_URL),
    )

    with patch("deezer_python_gql.base_client.httpx.AsyncClient") as mock_client_cls:
        mock_instance = AsyncMock()
        mock_instance.post = AsyncMock(return_value=gql_response)
        mock_client_cls.return_value = mock_instance

        result = await client.check_audiobook_ids(["111", "222"])

    assert result == {"111"}


@pytest.mark.asyncio
async def test_check_audiobook_ids_empty_input() -> None:
    """Verify check_audiobook_ids returns empty set for empty input."""
    client = DeezerBaseClient(arl="test_arl")
    result = await client.check_audiobook_ids([])
    assert result == set()


# ---------------------------------------------------------------------------
# 6. Model smoke tests (one per query — fixture-based)
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
    assert len(results.livestreams.edges) > 0
    assert results.livestreams.edges[0].node is not None
    assert results.livestreams.edges[0].node.name == "Deezer Pop"
    assert isinstance(results.tracks.page_info.has_next_page, bool)


# ---------------------------------------------------------------------------
# 6. Browse-related model smoke tests (new queries)
# ---------------------------------------------------------------------------


def test_smoke_get_flow() -> None:
    """Verify GetFlow fixture parses with flow tracks."""
    data = _load_fixture("get_flow.json")
    me = GetFlow.model_validate(data).me
    assert me is not None
    assert me.flow is not None
    assert me.flow.id == "flow:default"
    assert me.flow.title == "Flow"
    assert len(me.flow.tracks) == 2
    assert me.flow.tracks[0].track is not None
    assert me.flow.tracks[0].track.title == "Harder, Better, Faster, Stronger"


def test_smoke_get_flow_batch() -> None:
    """Verify GetFlowBatch fixture parses 4 aliased track batches."""
    data = _load_fixture("get_flow_batch.json")
    me = GetFlowBatch.model_validate(data).me
    assert me is not None
    flow = me.flow
    assert flow is not None
    assert flow.id == "flow:default"
    assert len(flow.batch_1) == 1
    assert len(flow.batch_2) == 1
    assert len(flow.batch_3) == 1
    assert len(flow.batch_4) == 1
    assert flow.batch_1[0].track is not None
    assert flow.batch_1[0].track.title == "Batch One Track"
    assert flow.batch_2[0].track is not None
    assert flow.batch_2[0].track.title == "Batch Two Track"
    assert flow.batch_3[0].track is not None
    assert flow.batch_3[0].track.is_explicit is True
    assert flow.batch_4[0].track is not None
    assert flow.batch_4[0].track.id == "401"


def test_smoke_get_flow_configs() -> None:
    """Verify GetFlowConfigs fixture parses mood and genre flow configs."""
    data = _load_fixture("get_flow_configs.json")
    me = GetFlowConfigs.model_validate(data).me
    assert me is not None
    configs = me.flow_configs
    assert len(configs.moods.edges) == 3
    assert len(configs.genres.edges) == 3
    mood_node = configs.moods.edges[0].node
    assert mood_node is not None
    assert mood_node.title == "Chill"
    genre_node = configs.genres.edges[0].node
    assert genre_node is not None
    assert genre_node.title == "Rock"
    assert configs.moods.page_info.has_next_page is True


def test_smoke_get_flow_config_tracks() -> None:
    """Verify GetFlowConfigTracks fixture parses tracks for a flow config."""
    data = _load_fixture("get_flow_config_tracks.json")
    flow_config = GetFlowConfigTracks.model_validate(data).flow_config
    assert flow_config is not None
    assert flow_config.id == "flow_config:chill"
    assert flow_config.title == "Chill"
    assert len(flow_config.tracks) == 1
    assert flow_config.tracks[0].track is not None
    assert flow_config.tracks[0].track.title == "Around the World"


def test_smoke_get_made_for_me() -> None:
    """Verify GetMadeForMe fixture parses SmartTracklist and Flow items."""
    data = _load_fixture("get_made_for_me.json")
    me = GetMadeForMe.model_validate(data).me
    assert me is not None
    edges = me.made_for_me.edges
    assert len(edges) == 3
    # First two are SmartTracklists, third is a Flow
    node_0 = edges[0].node
    assert node_0 is not None
    assert node_0.typename__ == "SmartTracklist"
    node_2 = edges[2].node
    assert node_2 is not None
    assert node_2.typename__ == "Flow"


def test_smoke_get_smart_tracklist() -> None:
    """Verify GetSmartTracklist fixture parses with paginated tracks."""
    data = _load_fixture("get_smart_tracklist.json")
    st = GetSmartTracklist.model_validate(data).smart_tracklist
    assert st is not None
    assert st.id == "smart:daily_mix_1"
    assert st.title == "Your Daily Mix 1"
    assert len(st.tracks.edges) == 2
    track_node = st.tracks.edges[0].node
    assert track_node is not None
    assert track_node.title == "Harder, Better, Faster, Stronger"
    assert st.tracks.page_info.has_next_page is True


def test_smoke_get_charts() -> None:
    """Verify GetCharts fixture parses all chart categories."""
    data = _load_fixture("get_charts.json")
    charts = GetCharts.model_validate(data).charts
    assert charts is not None
    country = charts.country
    assert country is not None
    assert country.tracks is not None
    assert country.albums is not None
    assert country.artists is not None
    assert country.playlists is not None
    assert len(country.tracks.edges) > 0
    assert len(country.albums.edges) > 0
    assert len(country.artists.edges) > 0
    assert len(country.playlists.edges) > 0
    first_track = country.tracks.edges[0].node
    assert first_track is not None
    assert first_track.title == "Greedy"


def test_smoke_get_recommendations() -> None:
    """Verify GetRecommendations fixture parses all recommendation categories."""
    data = _load_fixture("get_recommendations.json")
    me = GetRecommendations.model_validate(data).me
    assert me is not None
    reco = me.recommendations
    assert len(reco.playlists.edges) > 0
    assert len(reco.artist_playlists.edges) == 2
    assert reco.artist_playlists.edges[0].node is not None
    assert reco.artist_playlists.edges[0].node.title == "This Is Daft Punk"
    assert len(reco.new_releases.edges) > 0
    assert len(reco.artists.edges) > 0
    assert reco.hot_tracks is not None
    assert len(reco.hot_tracks) > 0
    assert reco.hot_tracks[0].title == "Harder, Better, Faster, Stronger"


def test_smoke_get_recently_played() -> None:
    """Verify GetRecentlyPlayed fixture parses mixed content types."""
    data = _load_fixture("get_recently_played.json")
    me = GetRecentlyPlayed.model_validate(data).me
    assert me is not None
    edges = me.recently_played.edges
    assert len(edges) == 4
    # Check discriminated union types
    node_0 = edges[0].node
    assert node_0 is not None
    assert node_0.typename__ == "Album"
    node_1 = edges[1].node
    assert node_1 is not None
    assert node_1.typename__ == "Playlist"
    node_2 = edges[2].node
    assert node_2 is not None
    assert node_2.typename__ == "Artist"
    node_3 = edges[3].node
    assert node_3 is not None
    assert node_3.typename__ == "Flow"


def test_smoke_get_favorite_artists() -> None:
    """Verify GetFavoriteArtists fixture parses with pagination."""
    data = _load_fixture("get_favorite_artists.json")
    me = GetFavoriteArtists.model_validate(data).me
    assert me is not None
    artists = me.user_favorites.artists
    assert artists is not None
    assert len(artists.edges) == 2
    artist_node = artists.edges[0].node
    assert artist_node is not None
    assert artist_node.name == "Daft Punk"
    assert artists.edges[0].favorited_at == "2025-06-15"
    assert artists.page_info.has_next_page is True


def test_smoke_get_favorite_albums() -> None:
    """Verify GetFavoriteAlbums fixture parses with pagination."""
    data = _load_fixture("get_favorite_albums.json")
    me = GetFavoriteAlbums.model_validate(data).me
    assert me is not None
    albums = me.user_favorites.albums
    assert albums is not None
    assert len(albums.edges) == 1
    album_node = albums.edges[0].node
    assert album_node is not None
    assert album_node.display_title == "Discovery"
    assert albums.edges[0].favorited_at == "2025-06-15"
    assert albums.page_info.has_next_page is True


def test_smoke_get_favorite_tracks() -> None:
    """Verify GetFavoriteTracks fixture parses with pagination."""
    data = _load_fixture("get_favorite_tracks.json")
    me = GetFavoriteTracks.model_validate(data).me
    assert me is not None
    tracks = me.user_favorites.tracks
    assert tracks is not None
    assert len(tracks.edges) == 1
    track_node = tracks.edges[0].node
    assert track_node is not None
    assert track_node.title == "Harder, Better, Faster, Stronger"
    assert tracks.edges[0].favorited_at == "2025-06-15"
    assert tracks.page_info.has_next_page is True


def test_smoke_get_favorite_playlists() -> None:
    """Verify GetFavoritePlaylists fixture parses with pagination."""
    data = _load_fixture("get_favorite_playlists.json")
    me = GetFavoritePlaylists.model_validate(data).me
    assert me is not None
    playlists = me.user_favorites.playlists
    assert playlists is not None
    assert len(playlists.edges) == 1
    playlist_node = playlists.edges[0].node
    assert playlist_node is not None
    assert playlist_node.title == "Electronic Hits"
    assert playlists.edges[0].favorited_at == "2025-06-15"
    assert playlists.page_info.has_next_page is True


def test_smoke_search_flows() -> None:
    """Verify SearchFlows fixture parses with flow config nodes."""
    data = _load_fixture("search_flows.json")
    search = SearchFlows.model_validate(data).search
    assert search is not None
    flow_configs = search.results.flow_configs
    assert len(flow_configs.edges) == 5
    first_node = flow_configs.edges[0].node
    assert first_node is not None
    assert first_node.id == "flow_config:chill"
    assert first_node.title == "Chill"
    assert first_node.visuals.hardware_square_icon is not None
    assert len(first_node.visuals.hardware_square_icon.urls) == 1
    assert flow_configs.page_info.has_next_page is True


def test_smoke_get_user_charts() -> None:
    """Verify GetUserCharts fixture parses personal top tracks, artists, and albums."""
    data = _load_fixture("get_user_charts.json")
    me = GetUserCharts.model_validate(data).me
    assert me is not None
    charts = me.charts
    assert charts is not None
    assert charts.tracks is not None
    assert len(charts.tracks.edges) > 0
    assert charts.artists is not None
    assert len(charts.artists.edges) > 0
    assert charts.albums is not None
    assert len(charts.albums.edges) > 0


# ---------------------------------------------------------------------------
# 6. User playlists query smoke test
# ---------------------------------------------------------------------------


def test_smoke_get_user_playlists() -> None:
    """Verify GetUserPlaylists fixture parses with paginated playlist nodes."""
    data = _load_fixture("get_user_playlists.json")
    me = GetUserPlaylists.model_validate(data).me
    assert me is not None
    playlists = me.playlists
    assert len(playlists.edges) == 1
    node = playlists.edges[0].node
    assert node is not None
    assert node.id == "1000000001"
    assert node.title == "My Playlist"
    assert node.estimated_tracks_count == 42
    assert node.owner is not None
    assert node.owner.name == "TestUser"
    assert playlists.page_info.has_next_page is False


# ---------------------------------------------------------------------------
# 7. Favorite mutation smoke tests
# ---------------------------------------------------------------------------


def test_smoke_add_artist_to_favorite() -> None:
    """Verify AddArtistToFavorite fixture parses with returned artist."""
    data = _load_fixture("add_artist_to_favorite.json")
    result = AddArtistToFavorite.model_validate(data)
    assert result.add_artist_to_favorite.artist.id == "100000001"
    assert result.add_artist_to_favorite.artist.name == "Test Artist"


def test_smoke_remove_artist_from_favorite() -> None:
    """Verify RemoveArtistFromFavorite fixture parses with returned artist."""
    data = _load_fixture("remove_artist_from_favorite.json")
    result = RemoveArtistFromFavorite.model_validate(data)
    assert result.remove_artist_from_favorite.artist.id == "100000001"
    assert result.remove_artist_from_favorite.artist.name == "Test Artist"


def test_smoke_add_album_to_favorite() -> None:
    """Verify AddAlbumToFavorite fixture parses with returned album."""
    data = _load_fixture("add_album_to_favorite.json")
    result = AddAlbumToFavorite.model_validate(data)
    assert result.add_album_to_favorite.album.id == "100000001"
    assert result.add_album_to_favorite.album.display_title == "Test Album"


def test_smoke_remove_album_from_favorite() -> None:
    """Verify RemoveAlbumFromFavorite fixture parses with returned album."""
    data = _load_fixture("remove_album_from_favorite.json")
    result = RemoveAlbumFromFavorite.model_validate(data)
    assert result.remove_album_from_favorite.album.id == "100000001"
    assert result.remove_album_from_favorite.album.display_title == "Test Album"


def test_smoke_add_track_to_favorite() -> None:
    """Verify AddTrackToFavorite fixture parses with returned track."""
    data = _load_fixture("add_track_to_favorite.json")
    result = AddTrackToFavorite.model_validate(data)
    assert result.add_track_to_favorite.track.id == "100000001"
    assert result.add_track_to_favorite.track.title == "Test Track"


def test_smoke_remove_track_from_favorite() -> None:
    """Verify RemoveTrackFromFavorite fixture parses with returned track."""
    data = _load_fixture("remove_track_from_favorite.json")
    result = RemoveTrackFromFavorite.model_validate(data)
    assert result.remove_track_from_favorite.track.id == "100000001"
    assert result.remove_track_from_favorite.track.title == "Test Track"


def test_smoke_add_playlist_to_favorite() -> None:
    """Verify AddPlaylistToFavorite fixture parses with returned playlist."""
    data = _load_fixture("add_playlist_to_favorite.json")
    result = AddPlaylistToFavorite.model_validate(data)
    assert result.add_playlist_to_favorite.playlist.id == "1000000001"
    assert result.add_playlist_to_favorite.playlist.title == "Test Playlist"


def test_smoke_remove_playlist_from_favorite() -> None:
    """Verify RemovePlaylistFromFavorite fixture parses with returned playlist."""
    data = _load_fixture("remove_playlist_from_favorite.json")
    result = RemovePlaylistFromFavorite.model_validate(data)
    assert result.remove_playlist_from_favorite.playlist.id == "1000000001"
    assert result.remove_playlist_from_favorite.playlist.title == "Test Playlist"


# ---------------------------------------------------------------------------
# 8. Playlist mutation smoke tests
# ---------------------------------------------------------------------------


def test_smoke_create_playlist() -> None:
    """Verify CreatePlaylist fixture parses with returned playlist."""
    data = _load_fixture("create_playlist.json")
    result = CreatePlaylist.model_validate(data)
    playlist = result.create_playlist.playlist
    assert playlist is not None
    assert playlist.id == "1000000001"
    assert playlist.title == "New Playlist"


def test_smoke_update_playlist() -> None:
    """Verify UpdatePlaylist fixture parses with returned playlist."""
    data = _load_fixture("update_playlist.json")
    result = UpdatePlaylist.model_validate(data)
    playlist = result.update_playlist.playlist
    assert playlist is not None
    assert playlist.id == "1000000001"
    assert playlist.title == "Updated Playlist"


def test_smoke_delete_playlist() -> None:
    """Verify DeletePlaylist fixture parses with delete status."""
    data = _load_fixture("delete_playlist.json")
    result = DeletePlaylist.model_validate(data)
    assert result.delete_playlist.delete_status is True


def test_smoke_add_tracks_to_playlist() -> None:
    """Verify AddTracksToPlaylist fixture parses the union success variant."""
    data = _load_fixture("add_tracks_to_playlist.json")
    result = AddTracksToPlaylist.model_validate(data)
    output = result.add_tracks_to_playlist
    assert output.typename__ == "PlaylistAddTracksOutput"
    assert output.added_track_ids == ["100000001", "100000002"]


def test_smoke_remove_tracks_from_playlist() -> None:
    """Verify RemoveTracksFromPlaylist fixture parses with removed track IDs."""
    data = _load_fixture("remove_tracks_from_playlist.json")
    result = RemoveTracksFromPlaylist.model_validate(data)
    assert result.remove_tracks_from_playlist.removed_track_ids == ["100000001", "100000002"]


def test_smoke_get_livestream() -> None:
    """Verify GetLivestream fixture parses with fields and media URLs."""
    data = _load_fixture("get_livestream.json")
    result = GetLivestream.model_validate(data)
    ls = result.livestream
    assert ls is not None
    assert ls.id == "12345"
    assert ls.name == "Deezer Pop"
    assert ls.is_on_stream is True
    assert ls.country == "FR"
    assert len(ls.media) == 2
    assert ls.media[0].url.startswith("https://")
    assert ls.media[0].codec is not None
    assert ls.media[0].codec.type_ == "hls"
    assert ls.cover is not None
    assert len(ls.cover.urls) == 1


# ---------------------------------------------------------------------------
# 9. Podcast query smoke tests
# ---------------------------------------------------------------------------


def test_smoke_get_podcast() -> None:
    """Verify GetPodcast fixture parses with episodes and rights."""
    data = _load_fixture("get_podcast.json")
    podcast = GetPodcast.model_validate(data).podcast
    assert podcast is not None
    assert podcast.id == "1234"
    assert podcast.display_title == "Tech Weekly"
    assert podcast.is_favorite is True
    assert podcast.type_ == PodcastType.EPISODIC
    assert podcast.is_advertising_allowed is True
    assert podcast.is_download_allowed is True
    assert podcast.rights.ads.available is True
    assert podcast.rights.sub.available is True
    assert len(podcast.episodes.edges) == 2
    ep = podcast.episodes.edges[0].node
    assert ep is not None
    assert ep.id == "ep_100"
    assert ep.title == "Episode 100: AI Revolution"
    assert ep.duration == 2400
    assert ep.media.url.startswith("https://")
    assert podcast.episodes.page_info.has_next_page is True


def test_smoke_get_podcast_episode() -> None:
    """Verify GetPodcastEpisode fixture parses with podcast and URL."""
    data = _load_fixture("get_podcast_episode.json")
    ep = GetPodcastEpisode.model_validate(data).podcast_episode
    assert ep is not None
    assert ep.id == "ep_100"
    assert ep.title == "Episode 100: AI Revolution"
    assert ep.duration == 2400
    assert ep.publication_date == "2025-07-10"
    assert ep.media.url.startswith("https://")
    assert ep.podcast.id == "1234"
    assert ep.podcast.display_title == "Tech Weekly"


def test_smoke_get_podcast_episodes_by_ids() -> None:
    """Verify GetPodcastEpisodesByIds fixture parses with nullable entries."""
    data = _load_fixture("get_podcast_episodes_by_ids.json")
    episodes = GetPodcastEpisodesByIds.model_validate(data).podcast_episodes_by_ids
    assert len(episodes) == 3
    assert episodes[0] is not None
    assert episodes[0].id == "ep_100"
    assert episodes[0].title == "Episode 100: AI Revolution"
    assert episodes[0].duration == 2400
    assert episodes[1] is not None
    assert episodes[1].id == "ep_099"
    assert episodes[2] is None


def test_smoke_get_favorite_podcasts() -> None:
    """Verify GetFavoritePodcasts fixture parses with pagination."""
    data = _load_fixture("get_favorite_podcasts.json")
    me = GetFavoritePodcasts.model_validate(data).me
    assert me is not None
    podcasts = me.user_favorites.podcasts
    assert podcasts is not None
    assert len(podcasts.edges) == 1
    node = podcasts.edges[0].node
    assert node is not None
    assert node.display_title == "Tech Weekly"
    assert podcasts.edges[0].favorited_at == "2025-07-01"
    assert podcasts.page_info.has_next_page is True


def test_smoke_get_podcast_episode_bookmarks() -> None:
    """Verify GetPodcastEpisodeBookmarks fixture parses with bookmark state."""
    data = _load_fixture("get_podcast_episode_bookmarks.json")
    me = GetPodcastEpisodeBookmarks.model_validate(data).me
    assert me is not None
    bookmarks = me.podcast_episode_bookmarks
    assert len(bookmarks.edges) == 1
    bm = bookmarks.edges[0].node
    assert bm is not None
    assert bm.position == 1200
    assert bm.is_played is False
    assert bm.episode.id == "ep_100"
    assert bm.episode.podcast.display_title == "Tech Weekly"


# ---------------------------------------------------------------------------
# 10. Podcast mutation smoke tests
# ---------------------------------------------------------------------------


def test_smoke_add_podcast_to_favorite() -> None:
    """Verify AddPodcastToFavorite fixture parses with returned podcast."""
    data = _load_fixture("add_podcast_to_favorite.json")
    result = AddPodcastToFavorite.model_validate(data)
    assert result.add_podcast_to_favorite.podcast.id == "1234"
    assert result.add_podcast_to_favorite.podcast.display_title == "Tech Weekly"
    assert result.add_podcast_to_favorite.favorited_at == "2025-07-10"


def test_smoke_remove_podcast_from_favorite() -> None:
    """Verify RemovePodcastFromFavorite fixture parses with returned podcast."""
    data = _load_fixture("remove_podcast_from_favorite.json")
    result = RemovePodcastFromFavorite.model_validate(data)
    assert result.remove_podcast_from_favorite.podcast is not None
    assert result.remove_podcast_from_favorite.podcast.id == "1234"


def test_smoke_bookmark_podcast_episode() -> None:
    """Verify BookmarkPodcastEpisode fixture parses with bookmark state."""
    data = _load_fixture("bookmark_podcast_episode.json")
    result = BookmarkPodcastEpisode.model_validate(data)
    assert result.bookmark_podcast_episode.status is True
    assert result.bookmark_podcast_episode.bookmark is not None
    assert result.bookmark_podcast_episode.bookmark.position == 600


def test_smoke_unbookmark_podcast_episode() -> None:
    """Verify UnbookmarkPodcastEpisode fixture parses with episode."""
    data = _load_fixture("unbookmark_podcast_episode.json")
    result = UnbookmarkPodcastEpisode.model_validate(data)
    assert result.unbookmark_podcast_episode.status is True
    assert result.unbookmark_podcast_episode.episode.id == "ep_100"


def test_smoke_mark_as_played_podcast_episode() -> None:
    """Verify MarkAsPlayedPodcastEpisode fixture parses with bookmark state."""
    data = _load_fixture("mark_as_played_podcast_episode.json")
    result = MarkAsPlayedPodcastEpisode.model_validate(data)
    assert result.mark_as_played_podcast_episode.status is True
    assert result.mark_as_played_podcast_episode.bookmark is not None
    assert result.mark_as_played_podcast_episode.bookmark.is_played is True


def test_smoke_mark_as_not_played_podcast_episode() -> None:
    """Verify MarkAsNotPlayedPodcastEpisode fixture parses with episode."""
    data = _load_fixture("mark_as_not_played_podcast_episode.json")
    result = MarkAsNotPlayedPodcastEpisode.model_validate(data)
    assert result.mark_as_not_played_podcast_episode.status is True
    assert result.mark_as_not_played_podcast_episode.episode.id == "ep_100"


# ---------------------------------------------------------------------------
# 11. Mix (Shaker) smoke tests
# ---------------------------------------------------------------------------


def test_smoke_get_artist_mix() -> None:
    """Verify GetArtistMix fixture parses with track results."""
    data = _load_fixture("get_artist_mix.json")
    mix = GetArtistMix.model_validate(data).artist_mix
    assert mix is not None
    assert len(mix.tracks) == 2
    track = mix.tracks[0].track
    assert track is not None
    assert track.id == "3135556"
    assert track.title == "Harder, Better, Faster, Stronger"
    assert track.duration == 226
    assert len(track.contributors.edges) == 1


def test_smoke_get_track_mix() -> None:
    """Verify GetTrackMix fixture parses with track results."""
    data = _load_fixture("get_track_mix.json")
    mix = GetTrackMix.model_validate(data).track_mix
    assert mix is not None
    assert len(mix.tracks) == 2
    track = mix.tracks[1].track
    assert track is not None
    assert track.id == "999001"
    assert track.title == "Get Lucky"
    assert len(track.contributors.edges) == 2


# ---------------------------------------------------------------------------
# 12. Audiobook smoke tests
# ---------------------------------------------------------------------------


def test_smoke_get_audiobook() -> None:
    """Verify GetAudiobook fixture parses with chapters and contributors."""
    data = _load_fixture("get_audiobook.json")
    audiobook = GetAudiobook.model_validate(data).audiobook
    assert audiobook is not None
    assert audiobook.id == "ab_1001"
    assert audiobook.display_title == "The Art of War"
    assert audiobook.is_favorite is True
    assert audiobook.chapters_count == 13
    assert audiobook.discs_count == 1
    assert audiobook.publisher == "Penguin Audio"
    assert audiobook.is_taken_down is False
    assert len(audiobook.contributors.edges) == 2
    assert audiobook.contributors.edges[0].roles == ["AUTHOR"]
    assert audiobook.contributors.edges[0].node.name == "Sun Tzu"
    assert len(audiobook.chapters.edges) == 2
    ch = audiobook.chapters.edges[0].node
    assert ch is not None
    assert ch.id == "ch_001"
    assert ch.display_title == "Chapter 1: Laying Plans"
    assert ch.disk_info is not None
    assert ch.disk_info.chapter_position == 1
    assert audiobook.chapters.page_info.has_next_page is True


def test_smoke_get_audiobook_chapter() -> None:
    """Verify GetAudiobookChapter fixture parses with media and audiobook."""
    data = _load_fixture("get_audiobook_chapter.json")
    chapter = GetAudiobookChapter.model_validate(data).audiobook_chapter
    assert chapter is not None
    assert chapter.id == "ch_001"
    assert chapter.display_title == "Chapter 1: Laying Plans"
    assert chapter.duration == 420
    assert chapter.gain == -6.5
    assert chapter.audiobook.id == "ab_1001"
    assert chapter.audiobook.display_title == "The Art of War"
    assert chapter.media is not None
    assert chapter.media.token.payload
    assert chapter.media.rights.ads is not None
    assert chapter.media.rights.ads.available is True


def test_smoke_get_similar_tracks() -> None:
    """Verify GetSimilarTracks fixture parses with TrackFields."""
    data = _load_fixture("get_similar_tracks.json")
    track = GetSimilarTracks.model_validate(data).track
    assert track is not None
    recs = [t for t in track.recommended_tracks if t is not None]
    assert len(recs) == 3
    assert recs[0].id == "901"
    assert recs[0].title == "Similar Song One"
    assert recs[0].duration == 245
    assert recs[1].is_explicit is True
    assert recs[2].contributors.edges[0].node.name == "Third Artist"


def test_smoke_get_favorite_audiobooks() -> None:
    """Verify GetFavoriteAudiobooks fixture parses with raw audiobook IDs."""
    data = _load_fixture("get_favorite_audiobooks.json")
    me = GetFavoriteAudiobooks.model_validate(data).me
    assert me is not None
    raw = me.favorites.raw_audiobooks
    assert raw is not None
    assert len(raw) == 3
    assert raw[0].id == "ab_1001"
    assert raw[0].favorited_at == "2025-11-15T10:30:00Z"
    assert raw[2].id == "ab_1003"


def test_smoke_add_audiobook_to_favorite() -> None:
    """Verify AddAudiobookToFavorite fixture parses."""
    data = _load_fixture("add_audiobook_to_favorite.json")
    result = AddAudiobookToFavorite.model_validate(data)
    assert result.add_audiobook_to_favorite.id == "ab_1001"
    assert result.add_audiobook_to_favorite.favorited_at


def test_smoke_remove_audiobook_from_favorite() -> None:
    """Verify RemoveAudiobookFromFavorite fixture parses."""
    data = _load_fixture("remove_audiobook_from_favorite.json")
    result = RemoveAudiobookFromFavorite.model_validate(data)
    assert result.remove_audiobook_from_favorite.id == "ab_1001"


# ---------------------------------------------------------------------------
# 13. Music Together (Shaker) smoke tests
# ---------------------------------------------------------------------------


def test_smoke_get_music_together_groups() -> None:
    """Verify GetMusicTogetherGroups fixture parses with group list."""
    data = _load_fixture("get_music_together_groups.json")
    me = GetMusicTogetherGroups.model_validate(data).me
    assert me is not None
    assert me.music_together_group_count == 2
    groups = me.music_together_groups
    assert len(groups.edges) == 1
    group = groups.edges[0].node
    assert group is not None
    assert group.id == "mt_group_001"
    assert group.name == "Road Trip Vibes"
    assert group.is_ready is True
    assert group.is_family is False
    assert group.estimated_members_count == 3
    assert len(group.members.edges) == 2
    assert group.members.edges[0].node is not None
    assert group.members.edges[0].node.name == "Alice"
    assert groups.page_info.has_next_page is True


def test_smoke_get_music_together_group() -> None:
    """Verify GetMusicTogetherGroup fixture parses with members and tracklists."""
    data = _load_fixture("get_music_together_group.json")
    group = GetMusicTogetherGroup.model_validate(data).music_together_group
    assert group is not None
    assert group.id == "mt_group_001"
    assert group.name == "Road Trip Vibes"
    # Members with affinity
    assert len(group.members.edges) == 1
    assert group.members.edges[0].affinity is not None
    assert group.members.edges[0].affinity.compatibility_score == 85
    # Suggested tracklist
    st = group.suggested_tracklist
    assert st is not None
    assert st.is_refreshing is False
    assert st.tracklist is not None
    tracks = st.tracklist.tracks
    assert len(tracks.edges) == 1
    assert tracks.edges[0].node is not None
    assert tracks.edges[0].node.title == "Harder, Better, Faster, Stronger"
    assert tracks.edges[0].metadata is not None
    assert tracks.edges[0].metadata.music_together is not None
    origin = tracks.edges[0].metadata.music_together.track_origin
    assert origin is not None
    assert len(origin) > 0
    assert origin[0] is not None
    assert origin[0].member.name == "Alice"
    # Curated tracklist (Playlist)
    curated = group.curated_tracklist
    assert curated is not None
    assert curated.title == "Road Trip Vibes - Curated"


def test_smoke_get_music_together_affinity() -> None:
    """Verify GetMusicTogetherAffinity fixture parses with discovery content."""
    data = _load_fixture("get_music_together_affinity.json")
    affinity = GetMusicTogetherAffinity.model_validate(data).music_together_affinity
    assert affinity is not None
    assert affinity.compatibility_score == 85
    assert affinity.member.name == "Bob"
    assert len(affinity.discovery_tracks.edges) == 1
    assert affinity.discovery_tracks.edges[0].node is not None
    assert affinity.discovery_tracks.edges[0].node.title == "Harder, Better, Faster, Stronger"
    assert len(affinity.discovery_artists.edges) == 1
    assert affinity.discovery_artists.edges[0].node is not None
    assert affinity.discovery_artists.edges[0].node.name == "Daft Punk"


def test_smoke_music_together_create_group() -> None:
    """Verify MusicTogetherCreateGroup fixture parses the success variant."""
    data = _load_fixture("music_together_create_group.json")
    result = MusicTogetherCreateGroup.model_validate(data)
    output = result.music_together_create_group
    assert output.typename__ == "MusicTogetherCreateGroupOutput"
    assert output.group.id == "mt_group_new"
    assert output.group.name == "Weekend Jams"


def test_smoke_music_together_join_group() -> None:
    """Verify MusicTogetherJoinGroup fixture parses the success variant."""
    data = _load_fixture("music_together_join_group.json")
    result = MusicTogetherJoinGroup.model_validate(data)
    output = result.music_together_join_group
    assert output.typename__ == "MusicTogetherJoinGroupOutput"
    assert output.group.estimated_members_count == 4


def test_smoke_music_together_leave_group() -> None:
    """Verify MusicTogetherLeaveGroup fixture parses the success variant."""
    data = _load_fixture("music_together_leave_group.json")
    result = MusicTogetherLeaveGroup.model_validate(data)
    output = result.music_together_leave_group
    assert output.typename__ == "MusicTogetherLeaveGroupOutput"
    assert output.group is not None
    assert output.group.id == "mt_group_001"


def test_smoke_music_together_generate_group_name() -> None:
    """Verify MusicTogetherGenerateGroupName fixture parses."""
    data = _load_fixture("music_together_generate_group_name.json")
    result = MusicTogetherGenerateGroupName.model_validate(data)
    assert result.music_together_generate_group_name.name == "Sunset Harmonies"
