# Reproducibility guide

## Archived collections

The repository contains three immutable scientific collections:

| Collection | Database | Reconciliation | Sealed output record |
|---|---|---|---|
| Study 1 | `outputs/main/collection.sqlite3` | `outputs/main_reconciliation.json` | `outputs/main/sealed_outputs.json` |
| Study 2 | `outputs/study2_rag/main/collection.sqlite3` | `outputs/study2_rag/main_reconciliation.json` | `outputs/study2_rag/main/sealed_outputs.json` |
| Follow-up | `outputs/followup_rag/main/collection.sqlite3` | `outputs/followup_rag/main_reconciliation.json` | `outputs/followup_rag/sealed_outputs.json` |

Each SQLite database is append-only at the application level. The reconciliation files report planned requests, committed observations, retry accounting, response-integrity categories, and duplicate checks.

## Offline verification

Run:

```bash
python scripts/verify_release.py
```

This verifies every file listed in `release_manifest.json`, runs SQLite `PRAGMA integrity_check`, confirms unique scientific IDs, and compares database counts with the collection reports.

## Analysis artifacts

Study 1 results are in `outputs/analysis/`. Study 2 results are in `outputs/study2_rag/analysis/`. Paired follow-up results are in `outputs/followup_rag/analysis/`. Human-review reconciliation is in `outputs/human_audit_20260930/`.

The two review workbooks are:

- `outputs/human_audit_20260930/evidence/study1_review.xlsx`
- `outputs/human_audit_20260930/evidence/study2_review.xlsx`

## Replication

The stored outputs, manifests, and analysis files document the reported results. Because hosted models and serving systems can change, results from a later collection are a replication.
