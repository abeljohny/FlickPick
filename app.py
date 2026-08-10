"""
FlickPick app.py — movie recommendation API for groups
"""

from __future__ import annotations

import logging
import os

import requests
from flask import Flask, jsonify, request, render_template
from databricks.sdk import WorkspaceClient

from lakebase import get_connection, ensure_flickpick_tables, upsert_movie

try:
    from sentence_transformers import SentenceTransformer
    import numpy as np
    _embedding_model = None  # Lazy load
except ImportError:
    SentenceTransformer = None
    np = None

logger = logging.getLogger(__name__)

_w = WorkspaceClient()
_TMDB_SECRET_SCOPE = os.environ.get("TMDB_SECRET_SCOPE", "api-keys")
_TMDB_SECRET_KEY = os.environ.get("TMDB_SECRET_KEY", "tmdb-api-key")


def _get_tmdb_api_key() -> str:
    """Fetch TMDB API key from Databricks secret scope."""
    secret = _w.secrets.get_secret(scope=_TMDB_SECRET_SCOPE, key=_TMDB_SECRET_KEY)
    return secret.value


def register_flickpick_routes(app: Flask) -> None:
    """Register all FlickPick API routes."""

    @app.route("/")
    def index():
        """Serve the FlickPick UI."""
        return render_template("index.html")

    @app.route("/api/groups", methods=["GET"])
    def get_groups():
        """GET /api/groups — list all groups."""
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT id, name, created_at FROM groups ORDER BY name")
                groups = cur.fetchall()
        return jsonify(groups)

    @app.route("/api/groups/<int:group_id>/members", methods=["GET"])
    def get_group_members(group_id):
        """GET /api/groups/:id/members — list members of a group."""
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT u.id, u.name AS full_name, u.email, gm.joined_at
                    FROM users u
                    JOIN group_members gm ON u.id = gm.user_id
                    WHERE gm.group_id = %s
                    ORDER BY u.name
                    """,
                    (group_id,),
                )
                members = cur.fetchall()
        return jsonify(members)

    @app.route("/api/tmdb/search", methods=["GET"])
    def tmdb_search():
        """
        GET /api/tmdb/search?q=<query>&group_id=<id>
        Proxied TMDB search, annotated server-side with each result's
        watched/disliked status for the given group.
        
        Searches TMDB API, upserts results to local DB, and returns annotated movies.
        """
        query = request.args.get("q", "").strip()
        group_id = request.args.get("group_id", type=int)

        if not query:
            return jsonify({"error": "query parameter 'q' is required"}), 400
        if not group_id:
            return jsonify({"error": "query parameter 'group_id' is required"}), 400

        # Search local movies table (TMDB integration can be added later)
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT 
                        id, title, poster_path, release_date, overview,
                        movie_genre_id, original_language, original_title,
                        country, popularity, duration_minutes
                    FROM movies
                    WHERE LOWER(title) LIKE LOWER(%s) OR LOWER(original_title) LIKE LOWER(%s)
                    ORDER BY popularity DESC, title
                    LIMIT 20
                    """,
                    (f"%{query}%", f"%{query}%"),
                )
                results = cur.fetchall()
        
        movie_ids = [m["id"] for m in results]

        # Annotate results with watched/disliked status for the group
        watched_ids = set()
        disliked_ids = set()

        if movie_ids:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    # Check watchlist for watched movies
                    cur.execute(
                        """
                        SELECT DISTINCT movie_id
                        FROM movie_watchlist
                        WHERE group_id = %s AND movie_id = ANY(%s) AND watched_at IS NOT NULL
                        """,
                        (group_id, movie_ids),
                    )
                    watched_ids = {row["movie_id"] for row in cur.fetchall()}

                    # Check average ratings for disliked movies (avg rating <= 2)
                    cur.execute(
                        """
                        SELECT r.movie_id
                        FROM ratings r
                        JOIN group_members gm ON r.user_id = gm.user_id
                        WHERE gm.group_id = %s AND r.movie_id = ANY(%s)
                        GROUP BY r.movie_id
                        HAVING AVG(r.rating) <= 2
                        """,
                        (group_id, movie_ids),
                    )
                    disliked_ids = {row["movie_id"] for row in cur.fetchall()}

        # Annotate results
        for result in results:
            movie_id = result.get("id")
            result["watched"] = movie_id in watched_ids
            result["disliked"] = movie_id in disliked_ids

        return jsonify({"results": results})

    @app.route("/api/groups/<int:group_id>/recommendations", methods=["GET"])
    def get_group_recommendations(group_id):
        """
        GET /api/groups/:id/recommendations
        Merged per-member recommendations for the group.
        """
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                        r.movie_id,
                        m.title,
                        m.poster_path,
                        MAX(r.score) as score,
                        STRING_AGG(DISTINCT r.reason, ' · ' ORDER BY r.reason) as reasons
                    FROM recommendations r
                    JOIN group_members gm ON r.user_id = gm.user_id
                    JOIN movies m ON r.movie_id = m.id
                    WHERE gm.group_id = %s
                    GROUP BY r.movie_id, m.title, m.poster_path
                    ORDER BY MAX(r.score) DESC
                    LIMIT 20
                    """,
                    (group_id,),
                )
                recs = cur.fetchall()
        return jsonify(recs)

    @app.route("/api/groups/<int:group_id>/watchlist", methods=["GET"])
    def get_watchlist(group_id):
        """GET /api/groups/:id/watchlist — get group's watchlist."""
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                        w.movie_id,
                        m.title,
                        m.poster_path,
                        m.release_date,
                        m.overview,
                        m.original_title,
                        m.original_language,
                        m.duration_minutes,
                        m.popularity,
                        w.added_by_user_id,
                        u.name as added_by_name,
                        w.created_at,
                        w.watched_at
                    FROM movie_watchlist w
                    JOIN movies m ON w.movie_id = m.id
                    JOIN users u ON w.added_by_user_id = u.id
                    WHERE w.group_id = %s AND w.watched_at IS NULL
                    ORDER BY w.created_at DESC
                    """,
                    (group_id,),
                )
                items = cur.fetchall()
        return jsonify(items)

    @app.route("/api/groups/<int:group_id>/watchlist", methods=["POST"])
    def add_to_watchlist(group_id):
        """POST /api/groups/:id/watchlist — add movie to group watchlist."""
        body = request.get_json(silent=True) or {}
        movie_id = body.get("movie_id")
        added_by_user_id = body.get("added_by_user_id")

        if not movie_id or not added_by_user_id:
            return jsonify({"error": "movie_id and added_by_user_id are required"}), 400

        with get_connection() as conn:
            with conn.cursor() as cur:
                try:
                    cur.execute(
                        """
                        INSERT INTO movie_watchlist (group_id, movie_id, added_by_user_id)
                        VALUES (%s, %s, %s)
                        ON CONFLICT (group_id, movie_id) DO NOTHING
                        """,
                        (group_id, movie_id, added_by_user_id),
                    )
                    conn.commit()
                    return jsonify({"movie_id": movie_id, "message": "added to watchlist"}), 201
                except Exception as e:
                    conn.rollback()
                    logger.exception("Failed to add to watchlist")
                    return jsonify({"error": "failed to add to watchlist"}), 500

    @app.route("/api/groups/<int:group_id>/watchlist/<int:movie_id>", methods=["DELETE"])
    def remove_from_watchlist(group_id, movie_id):
        """DELETE /api/groups/:id/watchlist/:movie_id — remove movie from watchlist."""
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM movie_watchlist WHERE group_id = %s AND movie_id = %s",
                    (group_id, movie_id),
                )
                conn.commit()
        return jsonify({"message": "removed from watchlist"}), 200

    @app.route("/api/groups/<int:group_id>/watchlist/<int:movie_id>/watched", methods=["POST"])
    def mark_as_watched(group_id, movie_id):
        """POST /api/groups/:id/watchlist/:movie_id/watched — mark movie as watched."""
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE movie_watchlist
                    SET watched_at = now()
                    WHERE group_id = %s AND movie_id = %s
                    """,
                    (group_id, movie_id),
                )
                conn.commit()
        return jsonify({"message": "marked as watched"}), 200

    @app.route("/api/ratings", methods=["POST"])
    def create_rating():
        """POST /api/ratings — create or update a user's rating for a movie."""
        body = request.get_json(silent=True) or {}
        movie_id = body.get("movie_id")
        user_id = body.get("user_id")
        rating = body.get("rating")

        if not movie_id or not user_id or rating is None:
            return jsonify({"error": "movie_id, user_id, and rating are required"}), 400

        try:
            rating = int(rating)
            if not (1 <= rating <= 5):
                raise ValueError
        except (TypeError, ValueError):
            return jsonify({"error": "rating must be an integer between 1 and 5"}), 400

        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO ratings (movie_id, user_id, rating, created_at)
                    VALUES (%s, %s, %s, now())
                    ON CONFLICT (movie_id, user_id) DO UPDATE
                    SET rating = EXCLUDED.rating, created_at = now()
                    """,
                    (movie_id, user_id, rating),
                )
                conn.commit()
        return jsonify({"message": "rating saved"}), 200

    @app.route("/api/groups/<int:group_id>/history", methods=["GET"])
    def get_watch_history(group_id):
        """GET /api/groups/:id/history — get group's watch history."""
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                        w.movie_id,
                        m.title,
                        m.poster_path,
                        m.release_date,
                        w.watched_at,
                        COALESCE(AVG(r.rating), 0) as avg_rating,
                        COUNT(r.rating) as rating_count
                    FROM movie_watchlist w
                    JOIN movies m ON w.movie_id = m.id
                    JOIN group_members gm ON w.group_id = gm.group_id
                    LEFT JOIN ratings r ON w.movie_id = r.movie_id AND r.user_id = gm.user_id
                    WHERE w.group_id = %s AND w.watched_at IS NOT NULL
                    GROUP BY w.movie_id, m.title, m.poster_path, m.release_date, w.watched_at
                    ORDER BY w.watched_at DESC
                    """,
                    (group_id,),
                )
                history = cur.fetchall()
        return jsonify(history)

    @app.route("/api/search/semantic", methods=["GET"])
    def semantic_search():
        """
        GET /api/search/semantic?q=<query>&group_id=<id>&limit=<limit>
        Semantic search using movie embeddings. Returns top-k similar movies
        based on cosine similarity, excluding watched/disliked movies.
        """
        if SentenceTransformer is None or np is None:
            return jsonify({"error": "sentence-transformers not installed"}), 501
        
        query = request.args.get("q", "").strip()
        group_id = request.args.get("group_id", type=int)
        limit = request.args.get("limit", 20, type=int)
        
        if not query:
            return jsonify({"error": "query parameter 'q' is required"}), 400
        
        # Lazy load the embedding model
        global _embedding_model
        if _embedding_model is None:
            _embedding_model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
        
        # Embed the query
        query_embedding = _embedding_model.encode([query], normalize_embeddings=True)[0].tolist()
        
        with get_connection() as conn:
            with conn.cursor() as cur:
                # Get excluded movie IDs (watched or disliked) if group_id provided
                excluded_ids = []
                if group_id:
                    cur.execute(
                        """
                        SELECT DISTINCT w.movie_id
                        FROM movie_watchlist w
                        WHERE w.group_id = %s AND w.watched_at IS NOT NULL
                        UNION
                        SELECT DISTINCT r.movie_id
                        FROM ratings r
                        JOIN group_members gm ON r.user_id = gm.user_id
                        WHERE gm.group_id = %s
                        GROUP BY r.movie_id
                        HAVING AVG(r.rating) <= 2
                        """,
                        (group_id, group_id),
                    )
                    excluded_ids = [row["movie_id"] for row in cur.fetchall()]
                
                # Compute cosine similarity using PostgreSQL array operations
                # Cosine similarity = dot product (since vectors are normalized)
                excluded_clause = "AND me.movie_id != ALL(%s)" if excluded_ids else ""
                
                cur.execute(
                    f"""
                    WITH similarities AS (
                        SELECT 
                            me.movie_id,
                            (
                                SELECT SUM(e1 * e2)
                                FROM unnest(me.embedding_vector) WITH ORDINALITY AS t1(e1, i)
                                JOIN unnest(%s::float8[]) WITH ORDINALITY AS t2(e2, i) ON t1.i = t2.i
                            ) as similarity
                        FROM movie_embeddings me
                        WHERE me.embedding_model = 'sentence-transformers/all-MiniLM-L6-v2'
                        {excluded_clause}
                        GROUP BY me.movie_id
                    )
                    SELECT 
                        m.id,
                        m.title,
                        m.poster_path,
                        m.release_date,
                        m.overview,
                        m.popularity,
                        s.similarity
                    FROM similarities s
                    JOIN movies m ON s.movie_id = m.id
                    ORDER BY s.similarity DESC
                    LIMIT %s
                    """,
                    (query_embedding, excluded_ids, limit) if excluded_ids else (query_embedding, limit),
                )
                results = cur.fetchall()
        
        return jsonify({
            "query": query,
            "results": results,
            "count": len(results)
        })


if __name__ == "__main__":
    app = Flask(__name__)
    register_flickpick_routes(app)
    app.run(host="0.0.0.0", port=8000, debug=False)