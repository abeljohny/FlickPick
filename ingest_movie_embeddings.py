from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from typing import List, Tuple
from urllib.parse import urlparse, unquote

# Set up logging early so it can be used during initialization
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# Load environment variables from .env file
# In Databricks, __file__ is not defined, so use current working directory
try:
    script_dir = os.path.dirname(os.path.abspath(__file__))
except NameError:
    # Running in Databricks notebook context
    script_dir = "/Workspace/Users/abel.johny@proton.me/FlickPick"

env_path = os.path.join(script_dir, ".env")

try:
    from dotenv import load_dotenv
    load_dotenv(env_path)
except ImportError:
    # dotenv not available, try manual parsing
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    os.environ[key] = value

# Parse Lakebase connection URL and set individual environment variables
if "LAKEBASE_URL" in os.environ:
    parsed = urlparse(os.environ["LAKEBASE_URL"])
    os.environ["LAKEBASE_HOST"] = parsed.hostname or "localhost"
    os.environ["LAKEBASE_PORT"] = str(parsed.port or 5432)
    os.environ["LAKEBASE_DATABASE"] = parsed.path.lstrip("/") if parsed.path else "postgres"
    
    # For Databricks Lakebase, generate OAuth credentials using the SDK
    if not os.environ.get("LAKEBASE_PASSWORD"):
        try:
            from databricks.sdk import WorkspaceClient
            w = WorkspaceClient()
            
            # Get current user for authentication
            current_user = w.current_user.me().user_name
            os.environ["LAKEBASE_USER"] = current_user
            
            # Find the endpoint by matching hostname
            target_host = parsed.hostname or ""
            logger.info(f"Looking for Lakebase endpoint with host: {target_host}")
            
            endpoint_found = False
            for project in w.postgres.list_projects():
                if endpoint_found:
                    break
                for branch in w.postgres.list_branches(parent=project.name):
                    if endpoint_found:
                        break
                    for endpoint in w.postgres.list_endpoints(parent=branch.name):
                        if endpoint.status and endpoint.status.hosts:
                            ep_host = endpoint.status.hosts.host
                            if ep_host == target_host:
                                logger.info(f"Found endpoint: {endpoint.name}")
                                # Generate OAuth token for this endpoint
                                creds = w.postgres.generate_database_credential(endpoint=endpoint.name)
                                if creds and creds.token:
                                    os.environ["LAKEBASE_PASSWORD"] = creds.token
                                    logger.info("Successfully generated Lakebase OAuth token")
                                    endpoint_found = True
                                    break
            
            if not endpoint_found:
                logger.warning(f"Could not find endpoint with host: {target_host}")
        except Exception as e:
            logger.warning(f"Could not generate OAuth credentials: {e}")
            import traceback
            logger.warning(traceback.format_exc())

# Disable FIPS mode to avoid OpenSSL FIPS self-test failures
# Must be set before importing libraries that use OpenSSL (PyTorch, SentenceTransformer)
os.environ["OPENSSL_FIPS"] = "0"

from sentence_transformers import SentenceTransformer

from lakebase import (
    ensure_movie_tables,
    fetch_unembedded_movies,
    write_movie_embeddings,
)

DEFAULT_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"  # 384-dim, good for movie descriptions
DEFAULT_BATCH_SIZE = 100

# Movie overviews and plot summaries are typically 200-500 characters each.
# Chunking mainly kicks in when combining overview + tagline + plot + cast/crew info.
# We use slightly larger chunks than weather since movie descriptions are denser.
DEFAULT_CHUNK_SIZE = 1000
DEFAULT_CHUNK_OVERLAP = 150


def get_params() -> dict:
    try:
        dbutils.widgets.text("batch_size", str(DEFAULT_BATCH_SIZE))
        dbutils.widgets.text("chunk_size", str(DEFAULT_CHUNK_SIZE))
        dbutils.widgets.text("chunk_overlap", str(DEFAULT_CHUNK_OVERLAP))
        dbutils.widgets.text("embedding_model", DEFAULT_MODEL_NAME)

        return {
            "batch_size": int(dbutils.widgets.get("batch_size")),
            "chunk_size": int(dbutils.widgets.get("chunk_size")),
            "chunk_overlap": int(dbutils.widgets.get("chunk_overlap")),
            "embedding_model": dbutils.widgets.get("embedding_model"),
        }
    except NameError:
        # Not running on a Databricks cluster — dbutils isn't injected.
        # Fall back to argparse so the same file works as a local script.
        parser = argparse.ArgumentParser()
        parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
        parser.add_argument("--chunk-size", type=int, default=DEFAULT_CHUNK_SIZE)
        parser.add_argument("--chunk-overlap", type=int, default=DEFAULT_CHUNK_OVERLAP)
        parser.add_argument("--embedding-model", default=DEFAULT_MODEL_NAME)
        args, _ = parser.parse_known_args()
        return {
            "batch_size": args.batch_size,
            "chunk_size": args.chunk_size,
            "chunk_overlap": args.chunk_overlap,
            "embedding_model": args.embedding_model,
        }


def chunk_text(text: str, chunk_size: int, overlap: int) -> List[str]:
    """Character-based sliding-window chunking. Simple and deterministic —
    good for movie descriptions, overviews, and plot summaries."""
    text = (text or "").strip()
    if not text:
        return []
    if len(text) <= chunk_size:
        return [text]

    chunks = []
    start = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        chunks.append(text[start:end])
        if end == len(text):
            break
        start = end - overlap
    return chunks


def embed_movies(
    model: SentenceTransformer,
    movies: List[dict],
    chunk_size: int,
    chunk_overlap: int,
) -> List[Tuple[int, List[str], List[List[float]]]]:
    """Returns (movie_id, chunks, embeddings) triples. Batches the
    actual model.encode() call across all chunks from all movies in this
    batch for throughput, then regroups per movie for the write step.
    
    Each movie document combines: title, overview, tagline, genres, and keywords
    into a searchable narrative text field."""
    movie_chunks: List[Tuple[int, List[str]]] = []
    for movie in movies:
        # Combine movie metadata into searchable text
        parts = []
        if movie.get("title"):
            parts.append(f"Title: {movie['title']}")
        if movie.get("overview"):
            parts.append(f"Overview: {movie['overview']}")
        if movie.get("tagline"):
            parts.append(f"Tagline: {movie['tagline']}")
        if movie.get("genres"):
            parts.append(f"Genres: {movie['genres']}")
        if movie.get("keywords"):
            parts.append(f"Keywords: {movie['keywords']}")
        if movie.get("director"):
            parts.append(f"Director: {movie['director']}")
        if movie.get("cast"):
            parts.append(f"Cast: {movie['cast']}")
        
        narrative_text = " | ".join(parts)
        chunks = chunk_text(narrative_text, chunk_size, chunk_overlap)
        movie_chunks.append((movie["movie_id"], chunks))

    flat_chunks = [c for _, chunks in movie_chunks for c in chunks]
    if not flat_chunks:
        return []

    flat_embeddings = model.encode(
        flat_chunks, batch_size=64, show_progress_bar=False, normalize_embeddings=True
    ).tolist()

    results = []
    cursor = 0
    for movie_id, chunks in movie_chunks:
        n = len(chunks)
        embeddings = flat_embeddings[cursor : cursor + n]
        cursor += n
        if chunks:
            results.append((movie_id, chunks, embeddings))
    return results


def run(
    batch_size: int = DEFAULT_BATCH_SIZE,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
    embedding_model: str = DEFAULT_MODEL_NAME,
) -> int:
    ensure_movie_tables()

    logger.info("loading embedding model %s", embedding_model)
    model = SentenceTransformer(embedding_model)

    total_embedded = 0
    while True:
        movies = fetch_unembedded_movies(batch_size=batch_size)
        if not movies:
            break

        logger.info("embedding %d movies", len(movies))
        for movie_id, chunks, embeddings in embed_movies(
            model, movies, chunk_size, chunk_overlap
        ):
            write_movie_embeddings(movie_id, chunks, embeddings, embedding_model)
            total_embedded += 1

        if len(movies) < batch_size:
            break  # last page was partial — nothing more to pull

    logger.info("done — embedded %d movies this run", total_embedded)
    return total_embedded


if __name__ == "__main__":
    params = get_params()
    logger.info("params: %s", params)

    start = time.time()
    count = run(
        batch_size=params["batch_size"],
        chunk_size=params["chunk_size"],
        chunk_overlap=params["chunk_overlap"],
        embedding_model=params["embedding_model"],
    )
    elapsed = time.time() - start
    logger.info("finished in %.1fs", elapsed)
    logger.info("✓ Movie embedding pipeline completed successfully. Embedded %d movies.", count)
