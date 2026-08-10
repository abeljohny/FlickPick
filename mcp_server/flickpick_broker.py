"""
Movie recommendation broker using TMDB API and Lakebase storage.

This module provides functions for movie search, recommendations, watchlist
management, and rating tracking. Data is stored in Lakebase PostgreSQL.

Functions:
    - search_movies_with_recommendations(query, group_id, limit): Search and get filtered recommendations
    - compare_movies(movie_ids): Compare multiple movies side-by-side
    - add_to_watchlist(movie_id, group_id, added_by): Add movie to group watchlist
    - record_rating(movie_id, group_id, member_id, rating, watched_date): Record group rating
    - get_watchlist(group_id): Get group's watchlist
    - get_watched_movies(group_id): Get movies already watched by group
"""

import os
import sys
import time
from datetime import datetime
from typing import List, Dict, Optional, Any
import requests
from databricks.sdk import WorkspaceClient

# Add parent directory to path to import lakebase
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from lakebase import get_connection

# Initialize Databricks client
w = WorkspaceClient()

# TMDB API Configuration
TMDB_API_KEY = w.secrets.get_secret(scope="api-keys", key="tmdb-api-key")
TMDB_BASE_URL = "https://api.themoviedb.org/3"
TMDB_IMAGE_BASE = "https://image.tmdb.org/t/p/w500"


def _fetch_movie_details(movie_id: int) -> Dict[str, Any]:
    """Fetch detailed movie information from TMDB API."""
    url = f"{TMDB_BASE_URL}/movie/{movie_id}"
    params = {
        "api_key": TMDB_API_KEY,
        "append_to_response": "credits,keywords,videos"
    }
    response = requests.get(url, params=params, timeout=10)
    response.raise_for_status()
    
    data = response.json()
    
    # Extract director and top cast
    director = None
    cast_list = []
    if "credits" in data:
        for crew in data["credits"].get("crew", []):
            if crew.get("job") == "Director":
                director = crew.get("name")
                break
        cast_list = [actor["name"] for actor in data["credits"].get("cast", [])[:5]]
    
    # Format the movie data
    return {
        "id": data["id"],
        "title": data["title"],
        "overview": data.get("overview", ""),
        "release_date": data.get("release_date", ""),
        "runtime": data.get("runtime"),
        "genres": [g["name"] for g in data.get("genres", [])],
        "vote_average": data.get("vote_average", 0),
        "vote_count": data.get("vote_count", 0),
        "poster_path": f"{TMDB_IMAGE_BASE}{data['poster_path']}" if data.get("poster_path") else None,
        "director": director,
        "cast": cast_list,
        "keywords": [kw["name"] for kw in data.get("keywords", {}).get("keywords", [])[:10]]
    }


def _get_excluded_movie_ids(group_id: int) -> set:
    """
    Get movie IDs that should be excluded for a group (watched or disliked).
    
    Args:
        group_id: Unique identifier for the group (integer)
        
    Returns:
        Set of movie IDs to exclude from recommendations
    """
    with get_connection() as conn:
        with conn.cursor() as cursor:
            # Get movies watched by the group or with low average ratings (< 3)
            cursor.execute(
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
                HAVING AVG(r.rating) < 3
                """,
                (group_id, group_id)
            )
            
            excluded_ids = {row['movie_id'] for row in cursor.fetchall()}
            return excluded_ids


def search_movies_with_recommendations(query: str, group_id: int, limit: int = 10) -> Dict[str, Any]:
    """
    Search for movies and provide recommendations, excluding watched/disliked movies.
    
    Args:
        query: Search query (movie title, genre, keywords)
        group_id: Unique identifier for the group
        limit: Maximum number of results to return
        
    Returns:
        Dict with search results and explanations for each recommendation
    """
    # Search TMDB
    search_url = f"{TMDB_BASE_URL}/search/movie"
    params = {
        "api_key": TMDB_API_KEY,
        "query": query,
        "include_adult": False,
        "page": 1
    }
    response = requests.get(search_url, params=params, timeout=10)
    response.raise_for_status()
    search_results = response.json().get("results", [])
    
    # Get excluded movies for this group
    excluded_ids = _get_excluded_movie_ids(group_id)
    
    # Filter and enrich results
    recommendations = []
    for movie in search_results[:limit * 2]:  # Get extra to account for filtering
        if movie["id"] in excluded_ids:
            continue
            
        # Fetch detailed info
        try:
            details = _fetch_movie_details(movie["id"])
            
            # Generate recommendation explanation
            explanation = _generate_recommendation_explanation(details)
            
            details["recommendation_reason"] = explanation
            recommendations.append(details)
            
            if len(recommendations) >= limit:
                break
        except Exception as e:
            # Skip movies that fail to fetch
            continue
    
    return {
        "query": query,
        "group_id": group_id,
        "total_results": len(recommendations),
        "excluded_count": len(excluded_ids),
        "movies": recommendations
    }


def _generate_recommendation_explanation(movie: Dict[str, Any]) -> str:
    """Generate a natural language explanation for why a movie is recommended."""
    reasons = []
    
    if movie.get("vote_average", 0) >= 7.5:
        reasons.append(f"highly rated ({movie['vote_average']}/10 from {movie.get('vote_count', 0):,} votes)")
    
    if movie.get("genres"):
        reasons.append(f"genres: {', '.join(movie['genres'][:3])}")
    
    if movie.get("director"):
        reasons.append(f"directed by {movie['director']}")
    
    if movie.get("runtime"):
        hours = movie["runtime"] // 60
        mins = movie["runtime"] % 60
        reasons.append(f"runtime: {hours}h {mins}m")
    
    return "; ".join(reasons) if reasons else "Popular choice"


def compare_movies(movie_ids: List[int]) -> Dict[str, Any]:
    """
    Compare multiple movies side-by-side.
    
    Args:
        movie_ids: List of TMDB movie IDs to compare
        
    Returns:
        Dict with detailed comparison of movies
    """
    movies = []
    for movie_id in movie_ids:
        try:
            details = _fetch_movie_details(movie_id)
            movies.append(details)
        except Exception as e:
            # Include error info for failed movies
            movies.append({
                "id": movie_id,
                "error": f"Failed to fetch: {str(e)}"
            })
    
    # Generate comparison summary
    comparison = {
        "movies": movies,
        "count": len(movies),
        "comparison_summary": _generate_comparison_summary(movies)
    }
    
    return comparison


def _generate_comparison_summary(movies: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Generate a summary comparing multiple movies."""
    valid_movies = [m for m in movies if "error" not in m]
    
    if not valid_movies:
        return {"error": "No valid movies to compare"}
    
    return {
        "avg_rating": round(sum(m.get("vote_average", 0) for m in valid_movies) / len(valid_movies), 2),
        "avg_runtime": round(sum(m.get("runtime", 0) or 0 for m in valid_movies) / len(valid_movies)),
        "all_genres": list(set(g for m in valid_movies for g in m.get("genres", []))),
        "newest": max(valid_movies, key=lambda m: m.get("release_date", ""))["title"],
        "oldest": min(valid_movies, key=lambda m: m.get("release_date", ""))["title"],
        "highest_rated": max(valid_movies, key=lambda m: m.get("vote_average", 0))["title"]
    }


def add_to_watchlist(movie_id: int, group_id: int, added_by_user_id: int) -> Dict[str, Any]:
    """
    Add a movie to the group's watchlist.
    
    Args:
        movie_id: TMDB movie ID
        group_id: Unique identifier for the group (integer)
        added_by_user_id: User ID who added the movie
        
    Returns:
        Dict confirming the addition
    """
    # Fetch movie details first to validate and get title
    movie = _fetch_movie_details(movie_id)
    
    with get_connection() as conn:
        with conn.cursor() as cursor:
            # First ensure the movie exists in our database
            cursor.execute(
                """
                INSERT INTO movies (id, title, poster_path, release_date, overview)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (id) DO NOTHING
                """,
                (movie_id, movie["title"], movie.get("poster_path"), 
                 movie.get("release_date"), movie.get("overview"))
            )
            
            # Insert into movie_watchlist (correct table name)
            cursor.execute(
                """
                INSERT INTO movie_watchlist (group_id, movie_id, added_by_user_id, created_at)
                VALUES (%s, %s, %s, now())
                ON CONFLICT (group_id, movie_id) DO NOTHING
                RETURNING id
                """,
                (group_id, movie_id, added_by_user_id)
            )
            
            result = cursor.fetchone()
            conn.commit()
            
            return {
                "success": True,
                "movie_id": movie_id,
                "movie_title": movie["title"],
                "group_id": group_id,
                "added_by_user_id": added_by_user_id,
                "already_existed": result is None
            }


def record_rating(movie_id: int, user_id: int, rating: int, group_id: Optional[int] = None) -> Dict[str, Any]:
    """
    Record a rating for a movie after a user watches it.
    
    Args:
        movie_id: TMDB movie ID
        user_id: User ID of the member rating
        rating: Rating value (1-5 stars)
        group_id: Optional group ID to calculate group average
        
    Returns:
        Dict confirming the rating with group statistics if group_id provided
    """
    if not (1 <= rating <= 5):
        raise ValueError("Rating must be between 1 and 5")
    
    with get_connection() as conn:
        with conn.cursor() as cursor:
            # Insert or update rating (per-user, not per-group)
            cursor.execute(
                """
                INSERT INTO ratings (movie_id, user_id, rating, created_at)
                VALUES (%s, %s, %s, now())
                ON CONFLICT (movie_id, user_id) 
                DO UPDATE SET rating = EXCLUDED.rating, created_at = now()
                RETURNING id
                """,
                (movie_id, user_id, rating)
            )
            
            conn.commit()
            
            result = {
                "success": True,
                "movie_id": movie_id,
                "user_id": user_id,
                "rating": rating
            }
            
            # If group_id provided, calculate group average from all group members
            if group_id is not None:
                cursor.execute(
                    """
                    SELECT AVG(r.rating) as avg_rating, COUNT(*) as rating_count
                    FROM ratings r
                    JOIN group_members gm ON r.user_id = gm.user_id
                    WHERE r.movie_id = %s AND gm.group_id = %s
                    """,
                    (movie_id, group_id)
                )
                
                stats = cursor.fetchone()
                if stats and stats["rating_count"] > 0:
                    result["group_id"] = group_id
                    result["group_average"] = round(float(stats["avg_rating"]), 2)
                    result["total_group_ratings"] = stats["rating_count"]
            
            return result


def get_watchlist(group_id: int) -> Dict[str, Any]:
    """
    Get the group's watchlist with movie details.
    
    Args:
        group_id: Unique identifier for the group (integer)
        
    Returns:
        Dict with watchlist movies including title and metadata
    """
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT 
                    w.movie_id,
                    m.title as movie_title,
                    w.added_by_user_id,
                    u.name as added_by_name,
                    w.created_at as added_date,
                    w.watched_at
                FROM movie_watchlist w
                JOIN movies m ON w.movie_id = m.id
                JOIN users u ON w.added_by_user_id = u.id
                WHERE w.group_id = %s AND w.watched_at IS NULL
                ORDER BY w.created_at DESC
                """,
                (group_id,)
            )
            
            watchlist = cursor.fetchall()
            
            return {
                "group_id": group_id,
                "count": len(watchlist),
                "movies": [dict(row) for row in watchlist]
            }


def get_watched_movies(group_id: int) -> Dict[str, Any]:
    """
    Get movies already watched by the group with their ratings.
    
    Args:
        group_id: Unique identifier for the group (integer)
        
    Returns:
        Dict with watched movies and their group ratings
    """
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT 
                    w.movie_id,
                    m.title as movie_title,
                    w.watched_at,
                    COALESCE(AVG(r.rating), 0) as avg_rating,
                    COUNT(r.rating) as rating_count
                FROM movie_watchlist w
                JOIN movies m ON w.movie_id = m.id
                JOIN group_members gm ON w.group_id = gm.group_id
                LEFT JOIN ratings r ON w.movie_id = r.movie_id AND r.user_id = gm.user_id
                WHERE w.group_id = %s AND w.watched_at IS NOT NULL
                GROUP BY w.movie_id, m.title, w.watched_at
                ORDER BY w.watched_at DESC
                """,
                (group_id,)
            )
            
            watched = cursor.fetchall()
            
            return {
                "group_id": group_id,
                "count": len(watched),
                "movies": [{
                    "movie_id": row["movie_id"],
                    "movie_title": row["movie_title"],
                    "avg_rating": round(float(row["avg_rating"]), 2),
                    "rating_count": row["rating_count"],
                    "watched_at": str(row["watched_at"])
                } for row in watched]
            }
