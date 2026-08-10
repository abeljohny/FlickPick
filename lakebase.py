from __future__ import annotations

import base64
import logging
import os
from contextlib import contextmanager
from typing import Any, Dict, List

import psycopg2
from databricks.sdk import WorkspaceClient
from psycopg2.extras import RealDictCursor

logger = logging.getLogger(__name__)

_w = WorkspaceClient()

_SCOPE = os.environ.get("LAKEBASE_SECRET_SCOPE", "database")
_KEY = os.environ.get("LAKEBASE_SECRET_KEY", "lakebase-url")


def _lakebase_url() -> str:
    """Fetch and decode the Lakebase connection URL from the Databricks secret scope."""
    secret = _w.secrets.get_secret(scope=_SCOPE, key=_KEY)
    return base64.b64decode(secret.value).decode("utf-8")


@contextmanager
def get_connection():
    """Yield a raw psycopg2 connection with a RealDictCursor factory."""
    conn = psycopg2.connect(_lakebase_url(), cursor_factory=RealDictCursor)
    try:
        yield conn
    finally:
        conn.close()


# FlickPick schema DDL
# Based on the schema described in templates/index.html

DDL_FLICKPICK = """
-- Users table
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    email TEXT UNIQUE NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now()
);

-- Groups table
CREATE TABLE IF NOT EXISTS groups (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now()
);

-- Group members junction table
CREATE TABLE IF NOT EXISTS group_members (
    id SERIAL PRIMARY KEY,
    group_id INTEGER NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    joined_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE (group_id, user_id)
);

-- Movies table
CREATE TABLE IF NOT EXISTS movies (
    id INTEGER PRIMARY KEY,  -- TMDB movie ID
    title TEXT NOT NULL,
    poster_path TEXT,
    release_date DATE,
    overview TEXT,
    created_at TIMESTAMPTZ DEFAULT now()
);

-- Watchlist table (as per templates/index.html schema)
CREATE TABLE IF NOT EXISTS watchlist (
    id SERIAL PRIMARY KEY,
    group_id INTEGER NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
    movie_id INTEGER NOT NULL REFERENCES movies(id) ON DELETE CASCADE,
    added_by_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ DEFAULT now(),
    watched_at TIMESTAMPTZ,  -- NULL = queued, set = watched by group
    CONSTRAINT uq_watchlist_group_movie UNIQUE (group_id, movie_id)
);

-- Ratings table (per-user ratings, 1-5)
CREATE TABLE IF NOT EXISTS ratings (
    id SERIAL PRIMARY KEY,
    movie_id INTEGER NOT NULL REFERENCES movies(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    rating INTEGER NOT NULL CHECK (rating >= 1 AND rating <= 5),
    created_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE (movie_id, user_id)
);

-- Recommendations table (per-user recommendations)
CREATE TABLE IF NOT EXISTS recommendations (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    movie_id INTEGER NOT NULL REFERENCES movies(id) ON DELETE CASCADE,
    score NUMERIC NOT NULL,
    reason TEXT,
    created_at TIMESTAMPTZ DEFAULT now()
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_group_members_group_id ON group_members(group_id);
CREATE INDEX IF NOT EXISTS idx_group_members_user_id ON group_members(user_id);
CREATE INDEX IF NOT EXISTS idx_watchlist_group_id ON watchlist(group_id);
CREATE INDEX IF NOT EXISTS idx_watchlist_movie_id ON watchlist(movie_id);
CREATE INDEX IF NOT EXISTS idx_ratings_movie_id ON ratings(movie_id);
CREATE INDEX IF NOT EXISTS idx_ratings_user_id ON ratings(user_id);
CREATE INDEX IF NOT EXISTS idx_recommendations_user_id ON recommendations(user_id);
"""


def ensure_flickpick_tables() -> None:
    """Idempotent migration — safe to call on every app startup."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            # Execute each statement separately to handle permission errors gracefully
            statements = [stmt.strip() + ';' for stmt in DDL_FLICKPICK.split(';') if stmt.strip()]
            
            for stmt in statements:
                if stmt and stmt != ';':
                    try:
                        cur.execute(stmt)
                        conn.commit()
                    except psycopg2.Error as e:
                        # Tables may already exist or we may lack permissions
                        # Log but don't fail - the app can still work if tables exist
                        logger.warning(f"DDL statement skipped: {e}")
                        conn.rollback()
                    
    logger.info("FlickPick schema ensured")


def upsert_movie(movie_data: Dict[str, Any]) -> None:
    """Upsert a movie from TMDB data.
    
    Handles both old and new schema - if new fields are present, they're stored.
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO movies (
                    id, title, poster_path, release_date, overview,
                    movie_genre_id, original_language, original_title,
                    country, popularity, duration_minutes
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    title = EXCLUDED.title,
                    poster_path = EXCLUDED.poster_path,
                    release_date = EXCLUDED.release_date,
                    overview = EXCLUDED.overview,
                    movie_genre_id = EXCLUDED.movie_genre_id,
                    original_language = EXCLUDED.original_language,
                    original_title = EXCLUDED.original_title,
                    country = EXCLUDED.country,
                    popularity = EXCLUDED.popularity,
                    duration_minutes = EXCLUDED.duration_minutes
                """,
                (
                    movie_data["id"],
                    movie_data.get("title", movie_data.get("original_title", "")),
                    movie_data.get("poster_path", ""),
                    movie_data.get("release_date"),
                    movie_data.get("overview", ""),
                    movie_data.get("movie_genre_id", movie_data.get("genre_ids", [0])[0] if movie_data.get("genre_ids") else 0),
                    movie_data.get("original_language", "en"),
                    movie_data.get("original_title", movie_data.get("title", "")),
                    movie_data.get("country", movie_data.get("origin_country", ["US"])[0] if movie_data.get("origin_country") else "US"),
                    movie_data.get("popularity", 0.0),
                    movie_data.get("duration_minutes", movie_data.get("runtime", 0)),
                ),
            )
            conn.commit()


def create_user(name: str, email: str) -> int:
    """Create a new user and return their ID."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO users (name, email)
                VALUES (%s, %s)
                ON CONFLICT (email) DO UPDATE SET name = EXCLUDED.name
                RETURNING id
                """,
                (name, email),
            )
            result = cur.fetchone()
            conn.commit()
            return result["id"]


def create_group(name: str) -> int:
    """Create a new group and return its ID."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO groups (name) VALUES (%s) RETURNING id",
                (name,),
            )
            result = cur.fetchone()
            conn.commit()
            return result["id"]


def add_user_to_group(group_id: int, user_id: int) -> None:
    """Add a user to a group."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO group_members (group_id, user_id)
                VALUES (%s, %s)
                ON CONFLICT (group_id, user_id) DO NOTHING
                """,
                (group_id, user_id),
            )
            conn.commit()


def get_group_member_ids(group_id: int) -> List[int]:
    """Get all user IDs in a group."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT user_id FROM group_members WHERE group_id = %s",
                (group_id,),
            )
            return [row["user_id"] for row in cur.fetchall()]


# Movie embeddings support

DDL_MOVIE_EMBEDDINGS = """
-- Movie embeddings table for semantic search
CREATE TABLE IF NOT EXISTS movie_embeddings (
    id SERIAL PRIMARY KEY,
    movie_id INTEGER NOT NULL REFERENCES movies(id) ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL,
    chunk_text TEXT NOT NULL,
    embedding_vector FLOAT8[] NOT NULL,
    embedding_model TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE (movie_id, chunk_index, embedding_model)
);

CREATE INDEX IF NOT EXISTS idx_movie_embeddings_movie_id ON movie_embeddings(movie_id);
CREATE INDEX IF NOT EXISTS idx_movie_embeddings_model ON movie_embeddings(embedding_model);
"""


def ensure_movie_tables() -> None:
    """Ensure movie embeddings table exists."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            statements = [stmt.strip() + ';' for stmt in DDL_MOVIE_EMBEDDINGS.split(';') if stmt.strip()]
            
            for stmt in statements:
                if stmt and stmt != ';':
                    try:
                        cur.execute(stmt)
                        conn.commit()
                    except psycopg2.Error as e:
                        logger.warning(f"DDL statement skipped: {e}")
                        conn.rollback()
    
    logger.info("Movie embeddings schema ensured")


def fetch_unembedded_movies(batch_size: int = 100, embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2") -> List[Dict[str, Any]]:
    """Fetch movies that don't have embeddings yet.
    
    Returns a list of movie dictionaries with: movie_id, title, overview, tagline, genres, keywords, director, cast.
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            # Find movies that don't have embeddings for the specified model
            cur.execute(
                """
                SELECT m.id as movie_id, m.title, m.overview
                FROM movies m
                LEFT JOIN movie_embeddings me ON m.id = me.movie_id AND me.embedding_model = %s
                WHERE me.id IS NULL
                LIMIT %s
                """,
                (embedding_model, batch_size),
            )
            rows = cur.fetchall()
            
            # Convert to list of dicts with all fields (some may be empty)
            movies = []
            for row in rows:
                movies.append({
                    "movie_id": row["movie_id"],
                    "title": row["title"] or "",
                    "overview": row["overview"] or "",
                    "tagline": "",  # Will be populated if we store taglines
                    "genres": "",   # Will be populated if we store genres
                    "keywords": "", # Will be populated if we store keywords
                    "director": "", # Will be populated if we store director
                    "cast": "",     # Will be populated if we store cast
                })
            
            return movies


def write_movie_embeddings(
    movie_id: int,
    chunks: List[str],
    embeddings: List[List[float]],
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2",
) -> None:
    """Write movie embeddings to the database.
    
    Args:
        movie_id: TMDB movie ID
        chunks: List of text chunks
        embeddings: List of embedding vectors (one per chunk)
        embedding_model: Name of the embedding model used
    """
    if len(chunks) != len(embeddings):
        raise ValueError(f"Chunk count ({len(chunks)}) doesn't match embedding count ({len(embeddings)})")
    
    with get_connection() as conn:
        with conn.cursor() as cur:
            # Delete existing embeddings for this movie + model
            cur.execute(
                "DELETE FROM movie_embeddings WHERE movie_id = %s AND embedding_model = %s",
                (movie_id, embedding_model),
            )
            
            # Insert new embeddings
            for idx, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
                cur.execute(
                    """
                    INSERT INTO movie_embeddings (movie_id, chunk_index, chunk_text, embedding_vector, embedding_model)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (movie_id, idx, chunk, embedding, embedding_model),
                )
            
            conn.commit()
    
    logger.debug(f"Wrote {len(chunks)} embeddings for movie {movie_id}")
