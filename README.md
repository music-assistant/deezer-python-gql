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

| Method                      | Description                                                   |
| --------------------------- | ------------------------------------------------------------- |
| `get_me()`                  | Current authenticated user                                    |
| `get_track(track_id)`       | Full track details — ISRC, media tokens, lyrics, contributors |
| `get_album(album_id)`       | Album with cover, label, paginated tracks, fallback           |
| `get_artist(artist_id)`     | Artist with bio, top tracks, albums (ordered by release date) |
| `get_playlist(playlist_id)` | Playlist with owner, picture, paginated tracks                |
| `search(query, ...)`        | Unified search across tracks, albums, artists, playlists      |

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
