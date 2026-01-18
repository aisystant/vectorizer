#!/usr/bin/env python3
"""Vectorizer: Generate embeddings from markdown files and store in SurrealDB."""

import argparse
import asyncio
import hashlib
import os
import sys
from pathlib import Path

from openai import OpenAI
from surrealdb import AsyncSurreal

MAX_CONTENT_LENGTH = 10000
EMBEDDING_MODEL = "text-embedding-3-large"
EMBEDDING_DIMENSIONS = 3072
TABLE_NAME = "documents"


def compute_hash(content: str) -> str:
    """Compute SHA256 hash of content."""
    return hashlib.sha256(content.encode()).hexdigest()


def filename_to_id(filename: str) -> str:
    """Convert filename to SurrealDB record ID using SHA256 hash."""
    return hashlib.sha256(filename.encode()).hexdigest()


def get_embedding(client: OpenAI, text: str) -> list[float]:
    """Generate embedding using OpenAI API."""
    response = client.embeddings.create(input=text, model=EMBEDDING_MODEL)
    return response.data[0].embedding


def scan_markdown_files(docs_path: Path) -> list[Path]:
    """Recursively find all markdown files in directory."""
    return list(docs_path.rglob("*.md"))


async def setup_database(db: AsyncSurreal) -> None:
    """Create table and vector index if they don't exist."""
    await db.query(f"""
        DEFINE TABLE IF NOT EXISTS {TABLE_NAME} SCHEMAFULL;
        DEFINE FIELD IF NOT EXISTS filename ON {TABLE_NAME} TYPE string;
        DEFINE FIELD IF NOT EXISTS content ON {TABLE_NAME} TYPE string;
        DEFINE FIELD IF NOT EXISTS embedding ON {TABLE_NAME} TYPE array<float>;
        DEFINE FIELD IF NOT EXISTS hash ON {TABLE_NAME} TYPE string;
        DEFINE INDEX IF NOT EXISTS idx_embedding ON {TABLE_NAME} FIELDS embedding MTREE DIMENSION {EMBEDDING_DIMENSIONS};
    """)


async def load_existing_records(db: AsyncSurreal) -> dict[str, dict]:
    """Load existing records from SurrealDB, return dict keyed by filename."""
    result = await db.query(f"SELECT * FROM {TABLE_NAME}")
    if not result or not result[0].get("result"):
        return {}
    records = result[0]["result"]
    return {r["filename"]: r for r in records}


async def delete_record(db: AsyncSurreal, filename: str) -> None:
    """Delete a record by filename."""
    record_id = filename_to_id(filename)
    await db.query(f"DELETE {TABLE_NAME}:{record_id}")


async def upsert_record(db: AsyncSurreal, filename: str, content: str, embedding: list[float], content_hash: str) -> None:
    """Insert or update a record."""
    record_id = filename_to_id(filename)
    await db.query(f"""
        UPSERT {TABLE_NAME}:{record_id} SET
            filename = $filename,
            content = $content,
            embedding = $embedding,
            hash = $hash
    """, {
        "filename": filename,
        "content": content,
        "embedding": embedding,
        "hash": content_hash,
    })


async def run(args):
    # Resolve configuration from args or environment
    host = args.host or os.environ.get("SURREAL_HOST")
    user = args.user or os.environ.get("SURREAL_USER")
    password = args.password or os.environ.get("SURREAL_PASSWORD")
    namespace = args.namespace or os.environ.get("SURREAL_NS")
    database = args.database or os.environ.get("SURREAL_DB")
    api_key = args.openai_key or os.environ.get("OPENAI_API_KEY")

    # Validate required parameters
    missing = []
    if not host:
        missing.append("--host or SURREAL_HOST")
    if not user:
        missing.append("--user or SURREAL_USER")
    if not password:
        missing.append("--password or SURREAL_PASSWORD")
    if not namespace:
        missing.append("--namespace or SURREAL_NS")
    if not database:
        missing.append("--database or SURREAL_DB")
    if not api_key:
        missing.append("--openai-key or OPENAI_API_KEY")

    if missing:
        print(f"Error: Missing required parameters: {', '.join(missing)}", file=sys.stderr)
        sys.exit(1)

    docs_path = Path(args.docs)
    if not docs_path.is_dir():
        print(f"Error: {args.docs} is not a directory", file=sys.stderr)
        sys.exit(1)

    # Connect to SurrealDB
    db = AsyncSurreal(host)
    await db.__aenter__()
    await db.signin({
        "username": user,
        "password": password,
        "namespace": namespace,
        "database": database,
    })
    await db.use(namespace, database)

    await setup_database(db)

    openai_client = OpenAI(api_key=api_key)
    existing_records = await load_existing_records(db)
    md_files = scan_markdown_files(docs_path)

    docs_before = len(existing_records)

    if not md_files:
        print("No markdown files found")
        sys.exit(0)

    exceeded_limit = False
    current_filenames = set()
    stats = {"new": 0, "updated": 0, "unchanged": 0}

    for md_file in md_files:
        relative_path = str(md_file.relative_to(docs_path))
        current_filenames.add(relative_path)

        content = md_file.read_text(encoding="utf-8")

        if len(content) > MAX_CONTENT_LENGTH:
            print(f"Warning: {relative_path} exceeds {MAX_CONTENT_LENGTH} chars, truncating")
            content = content[:MAX_CONTENT_LENGTH]
            exceeded_limit = True

        content_hash = compute_hash(content)

        if relative_path in existing_records:
            existing = existing_records[relative_path]
            if existing["hash"] == content_hash:
                print(f"Unchanged: {relative_path}")
                stats["unchanged"] += 1
                continue
            else:
                print(f"Updated: {relative_path}")
                stats["updated"] += 1
        else:
            print(f"New: {relative_path}")
            stats["new"] += 1

        embedding = get_embedding(openai_client, content)
        await upsert_record(db, relative_path, content, embedding, content_hash)

    # Delete records for files that no longer exist
    deleted_filenames = set(existing_records.keys()) - current_filenames
    for filename in deleted_filenames:
        await delete_record(db, filename)

    deleted_count = len(deleted_filenames)
    if deleted_count > 0:
        print(f"Removed {deleted_count} deleted file(s)")

    docs_after = docs_before + stats["new"] - deleted_count

    await db.__aexit__(None, None, None)

    print()
    print("Statistics:")
    print(f"  Documents before: {docs_before}")
    print(f"  Documents after:  {docs_after}")
    print(f"  New:       {stats['new']}")
    print(f"  Updated:   {stats['updated']}")
    print(f"  Unchanged: {stats['unchanged']}")
    print(f"  Deleted:   {deleted_count}")

    if exceeded_limit:
        print("Exiting with error: one or more files exceeded the character limit")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="Generate embeddings from markdown files")
    parser.add_argument("--docs", required=True, help="Path to docs directory")
    parser.add_argument("--host", help="SurrealDB host URL (or SURREAL_HOST env var)")
    parser.add_argument("--user", help="SurrealDB username (or SURREAL_USER env var)")
    parser.add_argument("--password", help="SurrealDB password (or SURREAL_PASSWORD env var)")
    parser.add_argument("--namespace", help="SurrealDB namespace (or SURREAL_NS env var)")
    parser.add_argument("--database", help="SurrealDB database (or SURREAL_DB env var)")
    parser.add_argument("--openai-key", help="OpenAI API key (or OPENAI_API_KEY env var)")
    args = parser.parse_args()

    asyncio.run(run(args))


if __name__ == "__main__":
    main()
