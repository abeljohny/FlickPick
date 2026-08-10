"""
Test suite for FlickPick API endpoints.

Run with: pytest tests/test_api.py -v
"""
import pytest
import os
from unittest.mock import Mock, patch, MagicMock

# Import app factory
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app


@pytest.fixture
def app():
    """Create test app instance."""
    app = create_app()
    app.config['TESTING'] = True
    return app


@pytest.fixture
def client(app):
    """Create test client."""
    return app.test_client()


@pytest.fixture
def mock_db_connection():
    """Mock database connection."""
    with patch('lakebase.get_connection') as mock:
        conn = MagicMock()
        cursor = MagicMock()
        conn.__enter__ = Mock(return_value=conn)
        conn.__exit__ = Mock(return_value=False)
        conn.cursor.return_value.__enter__ = Mock(return_value=cursor)
        conn.cursor.return_value.__exit__ = Mock(return_value=False)
        mock.return_value = conn
        yield cursor


class TestWatchlistEndpoints:
    """Test watchlist CRUD operations."""
    
    def test_get_watchlist_success(self, client, mock_db_connection):
        """Test GET /api/groups/:id/watchlist."""
        # Mock database response
        mock_db_connection.fetchall.return_value = [
            {"movie_id": 101, "title": "Parasite", "poster_path": "/path.jpg"},
            {"movie_id": 102, "title": "Dune", "poster_path": "/path2.jpg"}
        ]
        
        response = client.get('/api/groups/1/watchlist')
        
        assert response.status_code == 200
        data = response.get_json()
        assert len(data) == 2
        assert data[0]["title"] == "Parasite"
    
    def test_add_to_watchlist_success(self, client, mock_db_connection):
        """Test POST /api/groups/:id/watchlist."""
        mock_db_connection.rowcount = 1
        
        response = client.post(
            '/api/groups/1/watchlist',
            json={"movie_id": 101}
        )
        
        assert response.status_code == 201
        data = response.get_json()
        assert data["movie_id"] == 101
        assert "added to watchlist" in data["message"]
    
    def test_add_to_watchlist_missing_movie_id(self, client):
        """Test POST without movie_id returns 400."""
        response = client.post(
            '/api/groups/1/watchlist',
            json={}
        )
        
        assert response.status_code == 400
        data = response.get_json()
        assert "error" in data
    
    def test_remove_from_watchlist_success(self, client, mock_db_connection):
        """Test DELETE /api/groups/:id/watchlist/:movie_id."""
        mock_db_connection.rowcount = 1
        
        response = client.delete('/api/groups/1/watchlist/101')
        
        assert response.status_code == 200
        data = response.get_json()
        assert "removed from watchlist" in data["message"]
    
    def test_mark_watched_success(self, client, mock_db_connection):
        """Test POST /api/groups/:id/watchlist/:movie_id/watched."""
        mock_db_connection.rowcount = 1
        
        response = client.post('/api/groups/1/watchlist/101/watched')
        
        assert response.status_code == 200
        data = response.get_json()
        assert "marked as watched" in data["message"]


class TestRatingsEndpoints:
    """Test movie rating operations."""
    
    def test_add_rating_success(self, client, mock_db_connection):
        """Test POST /api/ratings."""
        mock_db_connection.fetchone.return_value = {"avg_rating": 4.5}
        
        response = client.post(
            '/api/ratings',
            json={
                "movie_id": 101,
                "user_id": 1,
                "rating": 5
            }
        )
        
        assert response.status_code == 201
        data = response.get_json()
        assert "avg_rating" in data or "message" in data
    
    def test_add_rating_invalid_range(self, client):
        """Test rating outside 1-5 range returns 400."""
        response = client.post(
            '/api/ratings',
            json={
                "movie_id": 101,
                "user_id": 1,
                "rating": 10  # Invalid: should be 1-5
            }
        )
        
        assert response.status_code == 400
    
    def test_get_watch_history_success(self, client, mock_db_connection):
        """Test GET /api/groups/:id/history."""
        mock_db_connection.fetchall.return_value = [
            {
                "movie_id": 101,
                "title": "Parasite",
                "avg_rating": 4.5,
                "watched_at": "2024-01-15"
            }
        ]
        
        response = client.get('/api/groups/1/history')
        
        assert response.status_code == 200
        data = response.get_json()
        assert len(data) > 0 or isinstance(data, dict)


class TestSearchEndpoints:
    """Test search functionality."""
    
    def test_tmdb_search_missing_query(self, client):
        """Test TMDB search without query parameter."""
        response = client.get('/api/tmdb/search?group_id=1')
        
        assert response.status_code == 400
        data = response.get_json()
        assert "error" in data
    
    def test_tmdb_search_missing_group_id(self, client):
        """Test TMDB search without group_id parameter."""
        response = client.get('/api/tmdb/search?q=inception')
        
        assert response.status_code == 400
        data = response.get_json()
        assert "error" in data
    
    @pytest.mark.skipif(
        not os.getenv('TMDB_SECRET_KEY'),
        reason="TMDB API key not configured"
    )
    def test_tmdb_search_integration(self, client):
        """Integration test for TMDB search (requires API key)."""
        response = client.get('/api/tmdb/search?q=inception&group_id=1')
        
        # Should either succeed or gracefully fall back to local search
        assert response.status_code in [200, 502]
    
    def test_semantic_search_missing_query(self, client):
        """Test semantic search without query parameter."""
        response = client.get('/api/search/semantic?group_id=1')
        
        assert response.status_code == 400
        data = response.get_json()
        assert "error" in data
    
    def test_semantic_search_missing_group_id(self, client):
        """Test semantic search without group_id parameter."""
        response = client.get('/api/search/semantic?q=action movies')
        
        assert response.status_code == 400
        data = response.get_json()
        assert "error" in data


class TestRecommendationsEndpoints:
    """Test recommendation endpoints."""
    
    def test_get_group_recommendations(self, client, mock_db_connection):
        """Test GET /api/groups/:id/recommendations."""
        mock_db_connection.fetchall.return_value = [
            {
                "movie_id": 101,
                "title": "Parasite",
                "score": 0.95,
                "reasons": "Highly rated · Matches your taste"
            }
        ]
        
        response = client.get('/api/groups/1/recommendations')
        
        assert response.status_code == 200
        data = response.get_json()
        assert isinstance(data, list) or isinstance(data, dict)


class TestCompareEndpoints:
    """Test movie comparison functionality."""
    
    def test_compare_movies_success(self, client, mock_db_connection):
        """Test GET /api/compare with movie IDs."""
        mock_db_connection.fetchall.return_value = [
            {"id": 101, "title": "Parasite", "overview": "..." },
            {"id": 102, "title": "Dune", "overview": "..."}
        ]
        
        response = client.get('/api/compare?ids=101,102')
        
        assert response.status_code == 200
        data = response.get_json()
        assert "movies" in data or isinstance(data, list)
    
    def test_compare_movies_missing_ids(self, client):
        """Test compare without movie IDs returns 400."""
        response = client.get('/api/compare')
        
        assert response.status_code == 400


class TestHealthEndpoints:
    """Test application health and status."""
    
    def test_home_page(self, client):
        """Test GET / returns HTML."""
        response = client.get('/')
        
        assert response.status_code == 200
        assert b'html' in response.data.lower() or len(response.data) > 0


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
