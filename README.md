# vectorizer
Generates semantic embeddings from markdown-based repositories for search and retrieval

## Overview

A Python script packaged as a Docker image that processes markdown documents and generates vector embeddings for semantic search and retrieval.

## Inputs

- **docs/** - Directory containing markdown documents (mount to container or pass as parameter)
- **LanceDB path** - Local path or S3 URI for vector storage
- **Embedding credentials** - OpenAI API credentials

## Processing

- Markdown files must be under 10,000 characters
- Files exceeding 10k chars: only first 10k is processed, script exits with non-zero status
- Uses OpenAI's `text-embedding-3-large` model

## Stored Fields

| Field | Description |
|-------|-------------|
| filename | Original file path |
| content | Full markdown content |
| embedding | Vector embedding |
| hash | Content hash for incremental updates |
