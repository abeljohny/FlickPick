"""
FlickPick Movie Recommendation MCP server.

Exposes movie-related tools over MCP (Model Context Protocol) so a
Databricks Agent Bricks agent can call them like any other tool:
    - search_and_recommend(query, group_id, limit)
    - compare_movies(movie_ids)
    - add_to_watchlist(movie_id, group_id, added_by)
    - record_rating(movie_id, group_id, member_id, rating, watched_date)

These tools are backed by the TMDB API and Lakebase PostgreSQL for
group watchlist and rating management.

Deploy this as its own Databricks App (same app.yaml + FastMCP entrypoint
pattern documented at
https://docs.databricks.com/aws/en/agents/mcp-tools/custom-mcp), separate
from the dashboard app, so an Agent Bricks agent (or any MCP client) can
register its URL as an external MCP server.

Run locally:
    python flickpick_mcp_server.py
"""

import os
import logging
from typing import List, Optional
from fastmcp import FastMCP

# Import the broker functions
from flickpick_broker import (
    search_movies_with_recommendations,
    compare_movies,
    add_to_watchlist,
    record_rating,
    get_watchlist,
    get_watched_movies
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("flickpick-mcp-server")

mcp = FastMCP("flickpick-service")


@mcp.tool
def search_and_recommend(query: str, group_id: str, limit: int = 10) -> dict:
    """
    Search for movies and get personalized recommendations for a group.
    
    Automatically excludes movies the group has already watched or disliked.
    Each recommendation includes an explanation of why it's suggested.

    Args:
        query: Search query (movie title, genre, keywords, e.g. "sci-fi thriller" or "Inception").
        group_id: Unique identifier for your group (e.g. "friends", "family").
        limit: Maximum number of recommendations to return (default: 10).

    Returns:
        A dict with filtered movie recommendations, each with title, overview, ratings,
        cast, genres, and a personalized recommendation explanation. Also includes
        the count of excluded movies (already watched or disliked).
    """
    try:
        result = search_movies_with_recommendations(query, group_id, limit)
        return {
            "status": "success",
            **result
        }
    except Exception as e:
        logger.exception(f"Failed to search movies for query '{query}' and group '{group_id}'")
        return {
            "status": "error",
            "message": f"Failed to search movies: {str(e)}"
        }


@mcp.tool
def compare_multiple_movies(movie_ids: List[int]) -> dict:
    """
    Compare several movies side-by-side.
    
    Provides detailed information for each movie and a comparison summary
    showing average ratings, runtimes, genres, and which is newest/oldest/highest-rated.

    Args:
        movie_ids: List of TMDB movie IDs to compare (2-10 movies recommended).
                   Example: [550, 155, 13] for Fight Club, The Dark Knight, Forrest Gump.

    Returns:
        A dict with detailed information for each movie plus a comparison summary
        with aggregated statistics.
    """
    try:
        if len(movie_ids) < 2:
            return {
                "status": "error",
                "message": "Please provide at least 2 movie IDs to compare"
            }
        
        if len(movie_ids) > 10:
            return {
                "status": "error",
                "message": "Maximum 10 movies can be compared at once"
            }
        
        result = compare_movies(movie_ids)
        return {
            "status": "success",
            **result
        }
    except Exception as e:
        logger.exception(f"Failed to compare movies {movie_ids}")
        return {
            "status": "error",
            "message": f"Failed to compare movies: {str(e)}"
        }


@mcp.tool
def add_movie_to_watchlist(movie_id: int, group_id: str, added_by: str) -> dict:
    """
    Add a movie to your group's watchlist.
    
    The movie will be queued for the group to watch together. If the movie
    is already on the watchlist, the operation is idempotent (no duplicate).

    Args:
        movie_id: TMDB movie ID to add. Example: 550 for Fight Club.
        group_id: Unique identifier for your group (e.g. "friends", "family").
        added_by: Name or user ID of the person adding the movie.

    Returns:
        A dict confirming the addition with movie title, group info, and whether
        the movie was already on the watchlist.
    """
    try:
        result = add_to_watchlist(movie_id, group_id, added_by)
        return {
            "status": "success",
            **result
        }
    except Exception as e:
        logger.exception(f"Failed to add movie {movie_id} to watchlist for group '{group_id}'")
        return {
            "status": "error",
            "message": f"Failed to add to watchlist: {str(e)}"
        }


@mcp.tool
def record_movie_rating(movie_id: int, group_id: str, member_id: str, 
                       rating: float, watched_date: Optional[str] = None) -> dict:
    """
    Record a rating after your group watches a movie.
    
    This marks the movie as watched and records the member's rating.
    The group average rating is calculated automatically.

    Args:
        movie_id: TMDB movie ID. Example: 550 for Fight Club.
        group_id: Unique identifier for your group (e.g. "friends", "family").
        member_id: Name or user ID of the member rating the movie.
        rating: Rating value from 0-10 (0 = hated it, 10 = loved it).
        watched_date: Date watched in YYYY-MM-DD format (optional, defaults to today).

    Returns:
        A dict confirming the rating with the member's score, group average,
        and total number of ratings from group members.
    """
    try:
        result = record_rating(movie_id, group_id, member_id, rating, watched_date)
        return {
            "status": "success",
            **result
        }
    except ValueError as e:
        return {
            "status": "error",
            "message": str(e)
        }
    except Exception as e:
        logger.exception(f"Failed to record rating for movie {movie_id}")
        return {
            "status": "error",
            "message": f"Failed to record rating: {str(e)}"
        }


@mcp.tool
def get_group_watchlist(group_id: str) -> dict:
    """
    Get your group's movie watchlist.
    
    Shows all movies queued to watch together, ordered by when they were added.

    Args:
        group_id: Unique identifier for your group (e.g. "friends", "family").

    Returns:
        A dict with the count and list of movies on the watchlist, including
        who added each movie and when.
    """
    try:
        result = get_watchlist(group_id)
        return {
            "status": "success",
            **result
        }
    except Exception as e:
        logger.exception(f"Failed to get watchlist for group '{group_id}'")
        return {
            "status": "error",
            "message": f"Failed to get watchlist: {str(e)}"
        }


@mcp.tool
def get_group_watched_movies(group_id: str) -> dict:
    """
    Get movies your group has already watched with their ratings.
    
    Shows viewing history with average group ratings and when each was last watched.

    Args:
        group_id: Unique identifier for your group (e.g. "friends", "family").

    Returns:
        A dict with the count and list of watched movies, including average rating,
        number of ratings, and last watched date for each.
    """
    try:
        result = get_watched_movies(group_id)
        return {
            "status": "success",
            **result
        }
    except Exception as e:
        logger.exception(f"Failed to get watched movies for group '{group_id}'")
        return {
            "status": "error",
            "message": f"Failed to get watched movies: {str(e)}"
        }


if __name__ == "__main__":
    # Databricks Apps route external HTTP traffic to this port via app.yaml.
    # Use SSE transport for MCP protocol over HTTP (standard for Databricks MCP clients).
    # The FastMCP SSE endpoint will be available at http://host:port/sse
    port = int(os.getenv("DATABRICKS_APP_PORT", os.getenv("PORT", 8000)))
    
    # Use SSE transport - Databricks MCP clients connect to the /sse endpoint
    mcp.run(transport="sse", host="0.0.0.0", port=port)
