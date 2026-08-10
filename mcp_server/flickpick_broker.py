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
from datetime import datetime
from typing import List, Dict, Optional, Any
import requests
import psycopg2
from psycopg2.extras import RealDictCursor
from databricks.sdk import WorkspaceClient

# Initialize Databricks client
w = WorkspaceClient()

# TMDB API Configuration
TMDB_API_KEY = w.secrets.get_secret(scope="massive", key="tmdb_api_key")
TMDB_BASE_URL = "https://api.themoviedb.org/3"
TMDB_IMAGE_BASE = "https://image.tmdb.org/t/p/w500"

# Lakebase connection details from secrets
LAKEBASE_HOST = w.secrets.get_secret(scope="database", key="lakebase_url")
LAKEBASE_USER = "admin"
LAKEBASE_PASSWORD = w.secrets.get_secret(scope="database", key="lakebase_password")
LAKEBASE_DATABASE = "flickpick"


def _get_db_connection():
    """Get a connection to the Lakebase PostgreSQL database."""
    return psycopg2.connect(
        host=LAKEBASE_HOST,
        database=LAKEBASE_DATABASE,
        user=LAKEBASE_USER,
        password=LAKEBASE_PASSWORD,
        cursor_factory=RealDictCursor
    )


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


def _get_excluded_movie_ids(group_id: str) -> set:
    """
    Get movie IDs that should be excluded for a group (watched or disliked).
    
    Args:
        group_id: Unique identifier for the group
        
    Returns:
        Set of movie IDs to exclude from recommendations
    """
    conn = _get_db_connection()
    try:
        cursor = conn.cursor()
        
        # Get movies with low ratings (< 3) or marked as watched
        cursor.execute(
            """
            SELECT DISTINCT movie_id 
            FROM ratings 
            WHERE group_id = %s AND (rating < 3 OR watched = TRUE)
            """,
            (group_id,)
        )
        
        excluded_ids = {row['movie_id'] for row in cursor.fetchall()}
        return excluded_ids
    finally:
        conn.close()


def search_movies_with_recommendations(query: str, group_id: str, limit: int = 10) -> Dict[str, Any]:
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


def add_to_watchlist(movie_id: int, group_id: str, added_by: str) -> Dict[str, Any]:
    """
    Add a movie to the group's watchlist.
    
    Args:
        movie_id: TMDB movie ID
        group_id: Unique identifier for the group
        added_by: User ID/name who added the movie
        
    Returns:
        Dict confirming the addition
    """
    # Fetch movie details first
    movie = _fetch_movie_details(movie_id)
    
    conn = _get_db_connection()
    try:
        cursor = conn.cursor()
        
        # Insert into watchlist
        cursor.execute(
            """
            INSERT INTO watchlist (movie_id, group_id, added_by, added_date, movie_title)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (movie_id, group_id) DO NOTHING
            RETURNING id
            """,
            (movie_id, group_id, added_by, datetime.now(), movie["title"])
        )
        
        result = cursor.fetchone()
        conn.commit()
        
        return {
            "success": True,
            "movie_id": movie_id,
            "movie_title": movie["title"],
            "group_id": group_id,
            "added_by": added_by,
            "already_existed": result is None
        }
    finally:
        conn.close()


def record_rating(movie_id: int, group_id: str, member_id: str, rating: float, 
                  watched_date: Optional[str] = None) -> Dict[str, Any]:
    """
    Record a rating for a movie after the group watches it.
    
    Args:
        movie_id: TMDB movie ID
        group_id: Unique identifier for the group
        member_id: User ID/name of the member rating
        rating: Rating value (0-10)
        watched_date: Date when watched (YYYY-MM-DD), defaults to today
        
    Returns:
        Dict confirming the rating
    """
    if not (0 <= rating <= 10):
        raise ValueError("Rating must be between 0 and 10")
    
    if watched_date is None:
        watched_date = datetime.now().strftime("%Y-%m-%d")
    
    conn = _get_db_connection()
    try:
        cursor = conn.cursor()
        
        # Insert or update rating
        cursor.execute(
            """
            INSERT INTO ratings (movie_id, group_id, member_id, rating, watched_date, watched)
            VALUES (%s, %s, %s, %s, %s, TRUE)
            ON CONFLICT (movie_id, group_id, member_id) 
            DO UPDATE SET rating = EXCLUDED.rating, watched_date = EXCLUDED.watched_date, watched = TRUE
            RETURNING id
            """,
            (movie_id, group_id, member_id, rating, watched_date)
        )
        
        conn.commit()
        
        # Calculate group average
        cursor.execute(
            """
            SELECT AVG(rating) as avg_rating, COUNT(*) as rating_count
            FROM ratings
            WHERE movie_id = %s AND group_id = %s
            """,
            (movie_id, group_id)
        )
        
        stats = cursor.fetchone()
        
        return {
            "success": True,
            "movie_id": movie_id,
            "group_id": group_id,
            "member_id": member_id,
            "rating": rating,
            "watched_date": watched_date,
            "group_average": round(float(stats["avg_rating"]), 2),
            "total_ratings": stats["rating_count"]
        }
    finally:
        conn.close()


def get_watchlist(group_id: str) -> Dict[str, Any]:
    """
    Get the group's watchlist.
    
    Args:
        group_id: Unique identifier for the group
        
    Returns:
        Dict with watchlist movies
    """
    conn = _get_db_connection()
    try:
        cursor = conn.cursor()
        
        cursor.execute(
            """
            SELECT movie_id, movie_title, added_by, added_date
            FROM watchlist
            WHERE group_id = %s
            ORDER BY added_date DESC
            """,
            (group_id,)
        )
        
        watchlist = cursor.fetchall()
        
        return {
            "group_id": group_id,
            "count": len(watchlist),
            "movies": [dict(row) for row in watchlist]
        }
    finally:
        conn.close()


def get_watched_movies(group_id: str) -> Dict[str, Any]:
    """
    Get movies already watched by the group with their ratings.
    
    Args:
        group_id: Unique identifier for the group
        
    Returns:
        Dict with watched movies and their group ratings
    """
    conn = _get_db_connection()
    try:
        cursor = conn.cursor()
        
        cursor.execute(
            """
            SELECT movie_id, AVG(rating) as avg_rating, COUNT(*) as rating_count, 
                   MAX(watched_date) as last_watched
            FROM ratings
            WHERE group_id = %s AND watched = TRUE
            GROUP BY movie_id
            ORDER BY last_watched DESC
            """,
            (group_id,)
        )
        
        watched = cursor.fetchall()
        
        return {
            "group_id": group_id,
            "count": len(watched),
            "movies": [{
                "movie_id": row["movie_id"],
                "avg_rating": round(float(row["avg_rating"]), 2),
                "rating_count": row["rating_count"],
                "last_watched": str(row["last_watched"])
            } for row in watched]
        }
    finally:
        conn.close()
