# 🎬 FlickPick — Group Movie Recommendation System

**Smart movie recommendations for friend groups, powered by TMDB and Lakebase PostgreSQL.**

FlickPick helps groups of friends pick movies together by:
- 🔍 **Smart search** — Search TMDB's massive movie database
- 🎯 **Group recommendations** — See what movies match your group's taste
- 📝 **Shared watchlists** — Queue movies to watch together
- ⭐ **Collaborative ratings** — Track what your group loved (or hated)
- 📊 **Watch history** — Remember your movie nights
- 🌍 **International support** — Native-script titles for foreign films (기생충, 千と千尋の神隠し, 올드보이)

## 🌟 Features

### Core Functionality
- **TMDB Integration** — Access to millions of movies with rich metadata
- **Group Management** — Create groups, add members, track together
- **Smart Search** — Search by title, original title, with watched/disliked filtering
- **Watchlists** — Queue movies for group movie nights
- **Ratings & Reviews** — Rate movies 1-5 stars after watching
- **Watch History** — Track what you've seen and loved
- **Compare Movies** — Side-by-side comparison of multiple films

### Enhanced Movie Data
FlickPick stores **8 core movie fields** plus **6 enhanced TMDB fields**:
- `original_title` — Native-script titles (기생충 for Parasite, 千と千尋の神隠し for Spirited Away)
- `original_language` — ISO language codes (EN, KO, JA)
- `country` — Country of origin
- `movie_genre_id` — TMDB genre IDs
- `popularity` — TMDB popularity scores
- `duration_minutes` — Runtime

### MCP Tools for Databricks AI/ML Playground
FlickPick includes a **Model Context Protocol (MCP) server** that exposes 6 movie tools:
- `search_and_recommend` — Smart search with group-aware recommendations
- `compare_multiple_movies` — Side-by-side movie comparison
- `add_movie_to_watchlist` — Add movies to group watchlists
- `record_movie_rating` — Rate movies after watching
- `get_group_watchlist` — View queued movies
- `get_group_watched_movies` — View watch history

## 💾 Database Schema

FlickPick uses **Lakebase PostgreSQL** for all data storage:

### Core Tables

**`movies`** — Movie metadata from TMDB:
```sql
id (PK), title, poster_path, release_date, overview,
movie_genre_id, original_language, original_title,
country, popularity, duration_minutes
```

**`groups`** — Friend groups:
```sql
id (PK), name, created_at
```

**`users`** — Group members:
```sql
id (PK), name, email, created_at
```

**`group_members`** — Many-to-many join:
```sql
group_id (FK), user_id (FK), joined_at
PRIMARY KEY (group_id, user_id)
```

**`movie_watchlist`** — Group watchlists:
```sql
group_id (FK), movie_id (FK), added_by_user_id (FK),
created_at, watched_at
PRIMARY KEY (group_id, movie_id)
```

**`ratings`** — Movie ratings (1-5 stars):
```sql
movie_id (FK), user_id (FK), rating (1-5), created_at
PRIMARY KEY (movie_id, user_id)
```

**`recommendations`** — Personalized recommendations:
```sql
id (PK), user_id (FK), movie_id (FK), score, reason, created_at
```

## 🚀 Quick Start

### Prerequisites

1. **Databricks Workspace** with Lakebase PostgreSQL enabled
2. **TMDB API Key** — Get free key at https://www.themoviedb.org/settings/api
3. **Python 3.9+** with dependencies:

```bash
pip install flask databricks-sdk psycopg2-binary requests python-dotenv
```

### Setup

#### 1. Configure Databricks Secrets

Store your credentials in Databricks secret scopes:

```bash
# Create secret scopes (if not exists)
databricks secrets create-scope database
databricks secrets create-scope api-keys

# Store Lakebase connection URL
databricks secrets put --scope database --key lakebase-url
# Paste: postgres://user:pass@host:5432/dbname

# Store TMDB API key
databricks secrets put --scope api-keys --key tmdb-api-key
# Paste your TMDB API key
```

#### 2. Initialize Database

Run the initialization script to create all tables and load sample data:

```bash
python init_db.py
```

This creates:
- 8 tables (movies, groups, users, group_members, movie_watchlist, ratings, recommendations)
- Sample data: 2 groups, 4 users, 8 movies, multiple ratings

**Included movies:**
- The Shawshank Redemption
- The Godfather
- The Dark Knight
- Pulp Fiction
- Fight Club
- Parasite (기생충)
- Oldboy (올드보이)
- Spirited Away (千と千尋の神隠し)

#### 3. Run the FlickPick App

```bash
python app.py
# App runs on http://localhost:8000
```

Or deploy as a Databricks App:

```bash
databricks apps create flickpick --source-code-path .
```

#### 4. Deploy the MCP Server (Optional)

To enable FlickPick tools in Databricks AI/ML Playground:

```bash
cd mcp_server/
databricks apps create flickpick-mcp --source-code-path .
```

Then register the MCP server URL in **Workspace Settings → AI/ML → MCP Servers**.

See [MCP_DEPLOYMENT_GUIDE.md](MCP_DEPLOYMENT_GUIDE.md) for full instructions.

## 🔧 API Endpoints

### Web UI
- `GET /` — Main FlickPick web interface

### Groups & Members
- `GET /api/groups` — List all groups
- `GET /api/groups/:id/members` — List group members

### Movie Search
- `GET /api/tmdb/search?q=<query>&group_id=<id>` — Search movies (annotated with watched/disliked status)

### Recommendations
- `GET /api/groups/:id/recommendations` — Get group recommendations

### Watchlist
- `GET /api/groups/:id/watchlist` — Get group watchlist
- `POST /api/groups/:id/watchlist` — Add movie to watchlist
- `DELETE /api/groups/:id/watchlist/:movie_id` — Remove from watchlist
- `POST /api/groups/:id/watchlist/:movie_id/watched` — Mark as watched

### Ratings
- `POST /api/ratings` — Create or update rating (1-5 stars)

### Watch History
- `GET /api/groups/:id/history` — Get group watch history with ratings

## 📁 Project Structure

```
.
├── app.py                          # Main Flask app with all API routes
├── lakebase.py                     # Lakebase PostgreSQL connection + data access
├── init_db.py                      # Database initialization script
├── initial_data.sql                # Sample data (groups, users, movies, ratings)
├── migrate_movies_schema.py        # Schema migration script (adds new fields)
├── test_backend.py                 # API endpoint tests
├── requirements.txt                # Python dependencies
├── QUICKSTART.md                   # Quick setup guide
├── MCP_DEPLOYMENT_GUIDE.md         # MCP server deployment guide
├── templates/
│   └── index.html                  # FlickPick web UI (search, watchlist, ratings, compare)
├── mcp_server/                     # MCP server for Databricks AI/ML Playground
│   ├── flickpick_mcp_server.py     # FastMCP server with 6 movie tools
│   ├── flickpick_broker.py         # Backend functions (TMDB + Lakebase)
│   ├── app.yaml                    # MCP server Databricks App config
│   └── requirements.txt            # MCP server dependencies
├── screenshots/                    # 📸 Application screenshots
│   ├── home-page.png
│   ├── search-tmdb.png
│   ├── group-watchlist.png
│   ├── watch-history.png
│   ├── watchlist-ratings.png
│   └── compare-tab.png
└── conversation_history.pdf       # 🤖 MCP server AI conversation examples
```

## 📸 Screenshots & Demo

Application screenshots are available in the `screenshots/` folder:

- **home-page.png** — Main dashboard with group selection
- **search-tmdb.png** — Movie search with TMDB integration
- **group-watchlist.png** — Shared group watchlist
- **watch-history.png** — Watch history with ratings
- **watchlist-ratings.png** — Rating interface after watching
- **compare-tab.png** — Side-by-side movie comparison with enhanced fields

MCP server conversation examples are documented in **conversation_history.pdf**, showing:
- Natural language movie search
- AI-powered recommendations
- Watchlist management via chat
- Rating submission through AI assistant

## 🔧 Tech Stack

- **Backend**: Python, Flask
- **Database**: Lakebase PostgreSQL (Databricks)
- **Movie Data**: TMDB API
- **Frontend**: HTML, CSS, JavaScript (Vanilla)
- **MCP Server**: FastMCP (Model Context Protocol)
- **Deployment**: Databricks Apps

## 🚀 Deployment

### Deploy Main FlickPick App

```bash
# Deploy the FlickPick web app
databricks apps create flickpick --source-code-path .

# Check app status
databricks apps get flickpick

# View app logs
databricks apps logs flickpick
```

### Deploy MCP Server for AI/ML Playground

```bash
# Deploy the MCP server
cd mcp_server/
databricks apps create flickpick-mcp --source-code-path .

# Get the app URL
databricks apps get flickpick-mcp

# Register in Workspace Settings → AI/ML → MCP Servers
```

Full MCP deployment instructions: [MCP_DEPLOYMENT_GUIDE.md](MCP_DEPLOYMENT_GUIDE.md)

## ✨ Key Features Explained

### 1. Smart Group Filtering
When searching movies, results are automatically annotated with:
- ✅ **Watched** — Movies the group has already seen
- ❌ **Disliked** — Movies the group rated ≤ 2 stars average

This prevents suggesting movies you've already watched or didn't enjoy.

### 2. International Film Support
Native-script titles displayed alongside English titles:
- Parasite → 기생충 (Korean)
- Spirited Away → 千と千尋の神隠し (Japanese)
- Oldboy → 올드보이 (Korean)

### 3. Compare Movies
Side-by-side comparison shows:
- Original titles (when different)
- Runtime, popularity, ratings
- Release dates, languages, countries
- TMDB genre IDs

### 4. MCP Tools for AI Playground
Chat with Databricks Assistant to:
```
"Search for sci-fi movies for my friends group"
"Compare The Matrix, Inception, and Interstellar"
"Add Fight Club to my family watchlist"
"Show me what my group has watched"
```

## 🛠️ Development

### Running Tests

```bash
python test_backend.py
```

### Schema Migration

If you need to add new movie fields:

```bash
python migrate_movies_schema.py
```

### Local Development

```bash
# Set environment variables
export LAKEBASE_SECRET_SCOPE="database"
export LAKEBASE_SECRET_KEY="lakebase-url"
export TMDB_SECRET_SCOPE="api-keys"
export TMDB_SECRET_KEY="tmdb-api-key"

# Run locally
python app.py
# Visit http://localhost:8000
```

## 📝 Recent Updates

### Enhanced Movie Schema (v2.0)
- ✅ Added 6 TMDB fields: original_title, original_language, country, genre_id, popularity, duration
- ✅ Populated 8 movies with real data including native-script titles
- ✅ Updated compare tab to show all new fields
- ✅ Fixed watchlist POST endpoint (removed invalid RETURNING clause)
- ✅ Added ON CONFLICT handling for duplicate prevention

### MCP Server Integration
- ✅ Created FastMCP server with 6 movie tools
- ✅ Deployed as separate Databricks App
- ✅ Ready for AI/ML Playground integration

## 📚 Documentation

- [QUICKSTART.md](QUICKSTART.md) — Fast setup guide
- [MCP_DEPLOYMENT_GUIDE.md](MCP_DEPLOYMENT_GUIDE.md) — MCP server deployment
- [conversation_history.pdf](conversation_history.pdf) — AI assistant examples
- [screenshots/](screenshots/) — Application UI screenshots

## 👥 Sample Data

The `init_db.py` script creates:
- **2 groups**: "Movie Buffs" and "Friday Night Crew"
- **4 users**: Alice, Bob, Charlie, Diana
- **8 movies**: Mix of classics and international films
- **Multiple ratings**: Sample watch history with ratings

## 🤝 Contributing

FlickPick is built for group movie nights! Contributions welcome:
- TMDB API integration enhancements
- Additional recommendation algorithms
- UI/UX improvements
- More MCP tools

## 📝 License

MIT License - feel free to use for your movie nights! 🎬🍿er_embeddings_job.yml
# and change pause_status from PAUSED to UNPAUSED, then redeploy
```

## Environment Variables

Create a `.env` file in the project root:

```bash
LAKEBASE_URL=postgresql://user@host.database.cloud.databricks.com/databricks_postgres?sslmode=require
PAT=ghp_your_github_personal_access_token
```

**Note:** The Lakebase password is generated dynamically via OAuth using `WorkspaceClient.postgres.generate_database_credential()`. No static password is stored.
