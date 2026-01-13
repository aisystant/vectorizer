#!/usr/bin/env python3
"""Vectorizer: Generate embeddings from markdown files and store in LanceDB."""

import argparse
import hashlib
import os
import sys
from pathlib import Path

import lancedb
from openai import OpenAI

MAX_CONTENT_LENGTH = 10000
EMBEDDING_MODEL = "text-embedding-3-large"
TABLE_NAME = "documents"


def compute_hash(content: str) -> str:
    """Compute SHA256 hash of content."""
    return hashlib.sha256(content.encode()).hexdigest()


def get_embedding(client: OpenAI, text: str) -> list[float]:
    """Generate embedding using OpenAI API."""
    response = client.embeddings.create(input=text, model=EMBEDDING_MODEL)
    return response.data[0].embedding


def scan_markdown_files(docs_path: Path) -> list[Path]:
    """Recursively find all markdown files in directory."""
    return list(docs_path.rglob("*.md"))


def load_existing_records(db: lancedb.DBConnection) -> dict[str, dict]:
    """Load existing records from LanceDB, return dict keyed by filename."""
    if TABLE_NAME not in db.table_names():
        return {}

    table = db.open_table(TABLE_NAME)
    records = table.to_pandas().to_dict("records")
    return {r["filename"]: r for r in records}


def main():
    parser = argparse.ArgumentParser(description="Generate embeddings from markdown files")
    parser.add_argument("--docs", required=True, help="Path to docs directory")
    parser.add_argument("--db", required=True, help="LanceDB path (local or S3 URI)")
    parser.add_argument("--openai-key", help="OpenAI API key (or set OPENAI_API_KEY env var)")
    args = parser.parse_args()

    api_key = args.openai_key or os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("Error: OpenAI API key required (--openai-key or OPENAI_API_KEY)", file=sys.stderr)
        sys.exit(1)

    docs_path = Path(args.docs)
    if not docs_path.is_dir():
        print(f"Error: {args.docs} is not a directory", file=sys.stderr)
        sys.exit(1)

    client = OpenAI(api_key=api_key)
    db = lancedb.connect(args.db)

    existing_records = load_existing_records(db)
    md_files = scan_markdown_files(docs_path)

    if not md_files:
        print("No markdown files found")
        sys.exit(0)

    exceeded_limit = False
    new_records = []
    current_filenames = set()

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
                new_records.append(existing)
                continue
            else:
                print(f"Updated: {relative_path}")
        else:
            print(f"New: {relative_path}")

        embedding = get_embedding(client, content)
        new_records.append({
            "filename": relative_path,
            "content": content,
            "embedding": embedding,
            "hash": content_hash,
        })

    deleted_count = len(set(existing_records.keys()) - current_filenames)
    if deleted_count > 0:
        print(f"Removed {deleted_count} deleted file(s)")

    if TABLE_NAME in db.table_names():
        db.drop_table(TABLE_NAME)

    db.create_table(TABLE_NAME, new_records)
    print(f"Stored {len(new_records)} document(s) in {args.db}")

    if exceeded_limit:
        print("Exiting with error: one or more files exceeded the character limit")
        sys.exit(1)


if __name__ == "__main__":
    main()
