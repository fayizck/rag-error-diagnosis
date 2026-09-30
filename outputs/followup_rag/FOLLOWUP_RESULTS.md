# RAG follow-up: paired intervention results

**Status:** complete and reconciled on 30 September 2026. This is a separate, prospectively frozen follow-up. Study 1 and Study 2 were not changed. The protocol and prompt manifests were frozen before any follow-up model generation; the eight-request technical pilot passed before the 394-request main run.

## Question and design

This follow-up asks whether answer errors in the frozen HotpotQA bridge-question sample are more responsive to **supplying missing annotated evidence** or to **marking annotated evidence already present**. It uses the same Gemini 3.5 Flash-Lite reader and generation settings as Study 2, over the same shared development-derived corpus. Every question has a fresh control and a fresh intervention response. The three questions with neither support page in the original top ten are outside these two comparisons.

| Comparison | Questions | Control | Intervention |
|---|---:|---|---|
| Missing page | 91 with one annotated support page in BM25 top ten | Original ten pages | Replace the lowest-ranked non-support page with the missing annotated support page, preserving ten pages and its position |
| Present-page cue | 106 with both annotated support pages in BM25 top ten | Identical ten pages, all page focus flags `0` | Change only the two annotated support-page flags to `1` |

The support labels are used deliberately for these diagnostic interventions. They make the inserted page and cue *oracle* information; the intervention is not a new retriever. The primary outcome is each question's intervention-minus-control official HotpotQA exact-match (EM) score. Pre-specified secondary outcomes are answer F1 and response integrity. Intervals are paired bootstrap percentile 95% intervals (10,000 resamples); the p-values are exact two-sided discordant-pair tests, adjusted across the two primary contrasts using Holm's method.

## Results

| Comparison | Control EM | Intervention EM | Paired EM change (95% interval) | Repairs / harms | Mean F1 change | Holm-adjusted p |
|---|---:|---:|---:|---:|---:|---:|
| Missing page, 91 questions | 28/91 (30.8%) | 48/91 (52.7%) | **+22.0 percentage points** (+12.1 to +31.9) | 23 / 3 | +0.341 | 0.000176 |
| Present-page cue, 106 questions | 59/106 (55.7%) | 56/106 (52.8%) | −2.8 percentage points (−7.5 to +1.9) | 2 / 5 | −0.017 | 0.453 |

All **394/394** main responses were committed, had valid response-integrity status, matched their recorded prompt hashes, and reported model version `gemini-3.5-flash-lite`. There were no missing or duplicate scientific observations. The estimated usage cost from returned token counts and the [published Gemini 3.5 Flash-Lite rates](https://ai.google.dev/gemini-api/docs/pricing) was **USD 0.17868** for the main run plus **USD 0.00371** for the technical pilot; this is not a verified invoice.

The fresh missing-page control exactly reproduced the original Study 2 EM count (28/91). The fresh present-page control scored 59/106, compared with 58/106 in Study 2. Exact answer strings still varied between runs, so the fresh paired controls are the basis for causal comparisons.

## What the result supports

Adding the missing annotated page materially improved official answer scores in this setup. This gives direct evidence that incomplete retrieved context was an important bottleneck for the 91 partial-retrieval questions. The simple page-level cue did not improve official scores when both annotated support pages were already present. The observed cue effect is small and uncertain, and it does not rule out better cues or other reader interventions. The two effect sizes come from different question subsets and should not be treated as a head-to-head randomized comparison of retrieval and highlighting.

The follow-up does **not** establish that every EM failure with both pages present is a generation error. A page may lack enough answer-bearing text despite its annotated title, and EM may reject a semantically acceptable answer. For example, the cue condition changed one answer from “The show's 500th episode” to “The 500th episode of the series”; the latter fails EM against “show's 500th episode” despite expressing the same milestone. The colleague's pending Study 2 human audit is therefore needed for the paper's claim about *genuine* failures despite sufficient retrieved evidence. Study 1's support-sentence highlighting and this follow-up's page-level cue are distinct interventions.

## Reproducibility and limits

The frozen protocol is `frozen_protocol.json`; exact prompts and schedule are in `main_manifest.jsonl`. The append-only request/response log is `main/collection.sqlite3`; `main_reconciliation.json` records its fingerprint and completeness. `analysis/summary.json` holds the numerical results and `analysis/paired_items.jsonl` holds each paired answer transition. All 197 main questions came from the frozen Study 2 main set. The pilot used four separate Study 2 pilot questions.

The shared page corpus pools contexts from the entire HotpotQA development distractor split, not the official FullWiki corpus. Gold-title matching and deterministic merging of page text can overstate practical retrieval. There is one dataset sample, one retriever, one reader model, one top-ten context size, and one version of each intervention. The paper should present this as a controlled case study, with the human audit resolving the most important semantic ambiguity.
