# deezer-python-gql

Async typed Python client for Deezer's Pipe GraphQL API.

Built with [ariadne-codegen](https://github.com/mirumee/ariadne-codegen) — all
client methods and response models are generated from the GraphQL schema and
`.graphql` query files.

## Installation

```bash
uv add deezer-python-gql
```

## Quick Start

```python
import asyncio

from deezer_python_gql import DeezerGQLClient

async def main():
    client = DeezerGQLClient(arl="YOUR_ARL_COOKIE")

    # Current user
    me = await client.get_me()
    print(me)

    # Track with media URLs, lyrics, and contributors
    track = await client.get_track(track_id="3135556")
    print(track.title, track.duration)

    # Album with paginated track list
    album = await client.get_album(album_id="302127")
    print(album.display_title, album.tracks_count)

    # Artist with top tracks and discography
    artist = await client.get_artist(artist_id="27")
    print(artist.name, artist.fans_count)

    # Playlist with tracks
    playlist = await client.get_playlist(playlist_id="53362031")
    print(playlist.title, playlist.estimated_tracks_count)

    # Unified search across all entity types
    results = await client.search(query="Daft Punk")
    print(len(results.tracks.edges), "tracks found")

asyncio.run(main())
```

## Available Queries

### Content Retrieval

| Method                                               | Description                                                          |
| ---------------------------------------------------- | -------------------------------------------------------------------- |
| `get_me()`                                           | Current authenticated user                                           |
| `get_track(track_id)`                                | Full track details — ISRC, media tokens, lyrics, contributors        |
| `get_album(album_id)`                                | Album with cover, label, paginated tracks, fallback                  |
| `get_artist(artist_id)`                              | Artist with bio, top tracks, albums (ordered by release date)        |
| `get_playlist(playlist_id)`                          | Playlist with owner, picture, paginated tracks                       |
| `get_livestream(livestream_id)`                       | Livestream (radio station) with streaming URLs and codec info        |
| `get_podcast(podcast_id)`                            | Podcast with paginated episodes and rights info                      |
| `get_podcast_episode(podcast_episode_id)`            | Single episode with media URL, codec, and parent podcast ref         |
| `get_audiobook(audiobook_id)`                        | Audiobook with paginated chapters, contributors, and fallback        |
| `get_audiobook_chapter(audiobook_chapter_id)`        | Chapter with media token, estimated sizes, and streaming rights      |

### Search & Discovery

| Method                                               | Description                                                          |
| ---------------------------------------------------- | -------------------------------------------------------------------- |
| `search(query, ...)`                                 | Unified search across tracks, albums, artists, playlists, podcasts, livestreams |
| `search_flows(query)`                                | Discover all available Deezer flows via search                       |
| `get_similar_tracks(track_id, nb)`                   | Recommended tracks based on a given track                            |
| `get_artist_mix(artist_ids, limit)`                  | Track mix blended from given artists                                 |
| `get_track_mix(track_ids, limit)`                    | Track mix blended around given tracks                                |
| `get_flow()`                                         | User's default Flow with tracks                                      |
| `get_flow_batch()`                                   | 4 batches of Flow tracks in one request (via GraphQL aliases)        |
| `get_flow_configs(moods_first, genres_first)`        | Mood & genre flow config lists for discovery                         |
| `get_flow_config_tracks(flow_config_id)`             | Tracks for a specific mood/genre flow config                         |
| `get_made_for_me(first)`                             | "Made For You" SmartTracklist & Flow items                           |
| `get_smart_tracklist(smart_tracklist_id, first)`     | Smart tracklist with paginated tracks                                |
| `get_charts(country_code, ...)`                      | Country charts — tracks, albums, artists, playlists                  |
| `get_recommendations(playlists_first, ...)`          | Personalized recommendations across categories                       |
| `get_recently_played(first)`                         | Recently played mixed content (albums, playlists, artists...)        |
| `get_user_charts()`                                  | Personal top tracks, artists, and albums                             |

### Library & Favorites

| Method                                               | Description                                                          |
| ---------------------------------------------------- | -------------------------------------------------------------------- |
| `get_favorite_artists(first, after)`                 | Paginated favorite artists                                           |
| `get_favorite_albums(first, after)`                  | Paginated favorite albums                                            |
| `get_favorite_tracks(first, after)`                  | Paginated favorite tracks                                            |
| `get_favorite_playlists(first, after)`               | Paginated favorite playlists                                         |
| `get_favorite_podcasts(first, after)`                | Paginated favorite podcasts                                          |
| `get_favorite_audiobooks()`                          | Favorite audiobook IDs with dates (via deprecated endpoint)          |
| `get_podcast_episode_bookmarks(first, after)`        | Bookmarked podcast episodes with playback position                   |
| `get_user_playlists(first, after)`                   | User's own playlists (not just favorites)                            |

### Music Together (Collaborative Playlists)

| Method                                               | Description                                                          |
| ---------------------------------------------------- | -------------------------------------------------------------------- |
| `get_music_together_groups(first)`                   | User's Music Together groups                                         |
| `get_music_together_group(group_id, mood)`           | Single group with members, suggested & curated tracklists            |
| `get_music_together_affinity(group_id)`              | Group member affinity scores and discovery content                   |

## Available Mutations

### Favorites Management

| Method                                               | Description                                                          |
| ---------------------------------------------------- | -------------------------------------------------------------------- |
| `add_artist_to_favorite(artist_id)`                  | Add artist to favorites                                              |
| `remove_artist_from_favorite(artist_id)`             | Remove artist from favorites                                         |
| `add_album_to_favorite(album_id)`                    | Add album to favorites                                               |
| `remove_album_from_favorite(album_id)`               | Remove album from favorites                                          |
| `add_track_to_favorite(track_id)`                    | Add track to favorites                                               |
| `remove_track_from_favorite(track_id)`               | Remove track from favorites                                          |
| `add_playlist_to_favorite(playlist_id)`              | Add playlist to favorites                                            |
| `remove_playlist_from_favorite(playlist_id)`         | Remove playlist from favorites                                       |
| `add_podcast_to_favorite(podcast_id)`                | Add podcast to favorites                                             |
| `remove_podcast_from_favorite(podcast_id)`           | Remove podcast from favorites                                        |
| `add_audiobook_to_favorite(audiobook_id)`            | Add audiobook to favorites (deprecated but functional)               |
| `remove_audiobook_from_favorite(audiobook_id)`       | Remove audiobook from favorites (deprecated but functional)          |

### Playlist Management

| Method                                               | Description                                                          |
| ---------------------------------------------------- | -------------------------------------------------------------------- |
| `create_playlist(title, ...)`                        | Create a new playlist                                                |
| `update_playlist(playlist_id, ...)`                  | Update playlist title, description, or visibility                    |
| `delete_playlist(playlist_id)`                       | Delete a playlist                                                    |
| `add_tracks_to_playlist(playlist_id, track_ids)`     | Add tracks to a playlist                                             |
| `remove_tracks_from_playlist(playlist_id, ...)`      | Remove tracks from a playlist                                        |

### Podcast Episode Management

| Method                                               | Description                                                          |
| ---------------------------------------------------- | -------------------------------------------------------------------- |
| `bookmark_podcast_episode(episode_id, offset)`       | Bookmark episode with playback position (seconds)                    |
| `unbookmark_podcast_episode(episode_id)`             | Remove bookmark from episode                                         |
| `mark_as_played_podcast_episode(episode_id)`         | Mark episode as played                                               |
| `mark_as_not_played_podcast_episode(episode_id)`     | Mark episode as not played                                           |

### Music Together

| Method                                               | Description                                                          |
| ---------------------------------------------------- | -------------------------------------------------------------------- |
| `music_together_create_group(name, ...)`             | Create a new Music Together group                                    |
| `music_together_join_group(group_id)`                | Join an existing group                                               |
| `music_together_leave_group(group_id)`               | Leave a group                                                        |
| `music_together_refresh_suggested_tracklist(...)`     | Refresh the suggested tracklist for a group                          |
| `music_together_update_group_settings(...)`          | Update group settings (name, family mode)                            |
| `music_together_generate_group_name()`               | Generate a random group name                                         |

All methods return fully-typed Pydantic models generated from the GraphQL schema.

## Development

Requires **Python 3.12+** and [uv](https://docs.astral.sh/uv/).

```bash
# Install all dependencies (including codegen tooling)
make setup

# Re-generate the typed client from schema + queries
make generate

# Run linters and type checks
make lint

# Run tests
make test
```

### Adding a new query

1. Create a `.graphql` file in `queries/`.
2. Run `make generate` to produce the typed client method and response models.
3. Add tests in `tests/`.

## Exploring the API

To run ad-hoc GraphQL queries against the live Pipe API during development:

1. Create a `.env` file (already gitignored) with your ARL cookie:

   ```bash
   echo 'DEEZER_ARL=your_arl_cookie_value' > .env
   ```

2. Run queries:

   ```bash
   # Run a .graphql file
   uv run python scripts/explore.py queries/get_me.graphql

   # Run an inline query
   uv run python scripts/explore.py -q '{ me { id } }'

   # With variables
   uv run python scripts/explore.py -q 'query($id: String!) { track(trackId: $id) { title } }' \
       -v '{"id": "3135556"}'

   # Via make
   make explore Q=queries/get_me.graphql
   ```

The script handles JWT auth automatically — no manual token management needed.

## Authentication

The Pipe API uses short-lived JWTs obtained from an ARL cookie. The base client
handles token acquisition and refresh automatically — you only need to supply a
valid ARL value.

## License

Apache-2.0
