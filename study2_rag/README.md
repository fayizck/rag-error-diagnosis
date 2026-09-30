# Study 2 retrieval pipeline

This package implements the shared-corpus BM25 retrieval and reader pipeline for Study 2. Retrieval uses 66,576 page units pooled from the pinned HotpotQA development distractor data. The corpus is development-derived and is not the official FullWiki corpus.

The collection policy separates scientific outputs from technical retries. Empty, refused, malformed, or truncated responses are committed once and reported by response-integrity category. Only the predefined transient transport failures qualify for a retry.

Run the following commands from the repository root.

```bash
python -m study2_rag.cli analyze
python -m pytest -q tests/test_study2_rag.py
```

The stored database, reconciliation report, sealed outputs, and analysis tables are available under `outputs/study2_rag/`. Hosted models may change over time, so a later collection is a replication rather than a reconstruction of the stored responses.
