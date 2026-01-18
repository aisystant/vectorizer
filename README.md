# vectorizer
Generates semantic embeddings from markdown-based repositories for search and retrieval

## Overview

A Python script packaged as a Docker image that processes markdown documents and generates vector embeddings for semantic search and retrieval. Stores embeddings in SurrealDB with automatic MTREE index for vector similarity search.

## Inputs

- **docs/** - Directory containing markdown documents (mount to container or pass as parameter)
- **SurrealDB connection** - Host, credentials, namespace, and database
- **Embedding credentials** - OpenAI API credentials

## Processing

- Markdown files must be under 10,000 characters
- Files exceeding 10k chars: only first 10k is processed, script exits with non-zero status
- Uses OpenAI's `text-embedding-3-large` model (3072 dimensions)

## Stored Fields

| Field | Description |
|-------|-------------|
| id | SHA256 hash of filename |
| filename | Relative file path from docs root |
| content | Full markdown content |
| embedding | Vector embedding (3072 dimensions) |
| hash | Content hash for incremental updates |

## Usage

### Prerequisites

```bash
pip install -r requirements.txt
export OPENAI_API_KEY=your-api-key
export SURREAL_HOST=http://localhost:8000
export SURREAL_USER=root
export SURREAL_PASSWORD=root
export SURREAL_NS=test
export SURREAL_DB=test
```

### Python

```bash
python vectorizer.py --docs ./example_docs

# Or with explicit parameters
python vectorizer.py \
  --docs ./docs \
  --host http://localhost:8000 \
  --user root \
  --password root \
  --namespace myns \
  --database mydb
```

### Docker

```bash
# Build
docker build -t vectorizer .

# Run
docker run \
  -v $(pwd)/example_docs:/docs \
  -e OPENAI_API_KEY \
  -e SURREAL_HOST=http://surrealdb:8000 \
  -e SURREAL_USER=root \
  -e SURREAL_PASSWORD=root \
  -e SURREAL_NS=test \
  -e SURREAL_DB=test \
  vectorizer --docs /docs
```

### CLI Options

| Option | Env Variable | Description |
|--------|--------------|-------------|
| `--docs` | - | Path to directory containing markdown files |
| `--host` | `SURREAL_HOST` | SurrealDB host URL |
| `--user` | `SURREAL_USER` | SurrealDB username |
| `--password` | `SURREAL_PASSWORD` | SurrealDB password |
| `--namespace` | `SURREAL_NS` | SurrealDB namespace |
| `--database` | `SURREAL_DB` | SurrealDB database |
| `--openai-key` | `OPENAI_API_KEY` | OpenAI API key |

## Incremental Updates

The vectorizer only recomputes embeddings for files that have changed:

- New files: embedded and added
- Modified files: re-embedded (detected by content hash)
- Deleted files: removed from database
- Unchanged files: skipped (saves API costs)

## Vector Search

After vectorizing documents, you can perform similarity search in SurrealDB:

```sql
-- Find 5 most similar documents to a query vector
SELECT *, vector::similarity::cosine(embedding, $query_vector) AS score
FROM documents
WHERE embedding <|5|> $query_vector
ORDER BY score DESC;
```
