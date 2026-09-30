# Complete Evidence, Incomplete Highlights

## Research question and framing

When complete supporting evidence is available, how does incomplete versus complete evidence highlighting affect multi-hop question answering?

This is a controlled behavioral extension and paired HotpotQA case study. The distinction is independent manipulation of emphasis coverage across two annotated support groups while all factual context remains present. HiLight, CUE-R, COFT, Say Less, Mean More, Evidence Interfaces and Pair-ID constrain the novelty claim. No further gap search is planned.

## Prospective sample and eligibility

HotpotQA distractor development data: ten context paragraphs per item. Seed **20260929** is fixed before any generation. Each eligible ID receives a SHA256 rank over canonical JSON `[seed, "sample", item_id]`. The first ten are pilot items; the next 200 are main items. Hash-ranked sampling avoids dependence on dataset order or Python's random implementation. No output-dependent replacement is allowed.

Eligibility requires bridge type, a nonempty question/answer/ID, exactly ten structurally valid paragraphs, unique nonempty titles, two distinct supporting titles, and valid integer sentence indices. Additional structural exclusions are duplicate support annotations and collisions with the reserved sentence-wrapper syntax. No malformed record is silently repaired. Duplicate global IDs stop preparation. Exclusions are logged before sampling; rule counts are nonexclusive.

The maximum rendered prompt is capped prospectively at 100,000 UTF-8 bytes, without truncation. This conservative preparation bound is far below the documented model context size. Account-specific model limits and actual token counts for **all 840 pilot/main prompts** must then pass before pilot generation and final freeze. Token checks generate no answers and are reported separately from 40 pilot / 800 main generations. All four conditions must have equal provider token counts per item; otherwise a technical protocol review is required before observing pilot answers.

The authors' original CMU HTTP/HTTPS hosts timed out during implementation. Preparation therefore used a documented Hugging Face `hotpotqa/hotpot_qa` distractor-validation snapshot pinned at revision `1908d6afbbead072334abe2965f91bd2709910ab`. The Parquet file is cached and hashed. Conversion only renames `id` to `_id` and zips parallel title/sentence and supporting-title/index arrays. It never changes strings or order. Both downloaded-file and converted-cache hashes and access dates are recorded. Dataset license: CC BY-SA 4.0. Official scorer source: Apache 2.0.

## Conditions, prompt and randomization

A/B are randomized group labels, assigned by sorting the two support titles on SHA256 `[seed, item_id + ":AB", title]`. They do not encode order, hop, answer location or difficulty. Every sentence has `<s focus="0">…</s>` or `<s focus="1">…</s>`. Only supporting sentences may receive 1.

| Condition | Group A support | Group B support | Every other sentence |
|---|---|---|---|
| 00 | 0 | 0 | 0 |
| 10 | 1 | 0 | 0 |
| 01 | 0 | 1 | 0 |
| 11 | 1 | 1 | 0 |

00 is an unhighlighted tagged control. All titles, all ten paragraphs, their order, sentence order, question, and raw text are identical. No evidence deletion, rewriting, retrieval, or conversation history. An automated invariant checker validates each rendered string against the original ordered sentences and the exact flag mask. It checks all 16 requested invariants, including duplicate/lost sentences and support-index validity.

The exact instruction and template are appended by the freeze command from `experiment.prompts.TEMPLATE`. Each paragraph renders as `Title: <original title>`, newline, its wrapped sentences separated by newlines. Paragraphs are separated by two newlines. Source strings are not escaped, stripped or rewritten. User prompt contains no experimental condition ID, A/B label, gold answer, support count or annotation metadata.

Each scientific ID is `<item_id>::<condition>`. Requests are ordered by SHA256 `[seed, split + ":schedule", scientific_id]`; schedules are saved before generation. Concurrent dispatch follows this schedule, while completion order can vary. Retries never change scientific identity.

## Reader and output settings

Exactly one requested model: `gemini-3.5-flash-lite`. No substitution. Account-specific `GET models/{id}` must identify that model and support `generateContent`. Model metadata, requested ID, returned response version, generation settings and official documentation sources are recorded. Model metadata alone does not verify account-specific generation-parameter acceptance; the 40-call pilot does.

REST `generateContent`, a single user content, no tools/grounding, temperature 0.0, candidateCount 1, maxOutputTokens 2048, text/plain, thinkingLevel MINIMAL, includeThoughts false. Thinking configuration is held fixed; no reasoning text is requested or retained. A 2048 total output cap allows room for internal thinking and a short final answer. Low temperature is not a determinism guarantee. Unsupported fields cause a stop, never automatic removal or model replacement.

Official behavior checked 29 September 2026: [model](https://ai.google.dev/gemini-api/docs/models/gemini-3.5-flash-lite), [thinking levels](https://ai.google.dev/gemini-api/docs/thinking), [REST configuration](https://ai.google.dev/api/generate-content), [models metadata](https://ai.google.dev/api/models). The pilot verifies actual acceptance.

## Collection, retries and crash policy

Asyncio collector, bounded semaphore, rolling 60-second request/token limiter, fixed input token counts plus output-cap reservation, refunded using returned total usage. Defaults: concurrency 8, 30 RPM, 60,000 TPM; operational rates may be lowered or raised to match the account without changing scientific settings. Values are not claims about the account's actual limits.

At most three attempts per scientific ID across all resumes. Retry only HTTP 408/429/500/502/503/504 and listed transient transport errors. Exponential delays start at 2 seconds and cap at 60 seconds, with 0–1 second jitter and Retry-After respected. Retry jitter is operational randomness, independent of the scientific sample. Permanent auth/model/schema errors stop new dispatches. Never retry based on gold answer, EM/F1 or whether a result is interesting.

SQLite WAL with synchronous=FULL is the authoritative append-only attempt log. Starts and finishes are separate immutable events; storing a returned observation and its terminal finish is one transaction. The scientific-ID primary key prevents duplicate commits. Every response, including invalid ones, is durably committed immediately. A process lock prevents competing collectors/reconcilers. No completed observation can be updated, deleted or regenerated through the collector.

An interrupted request with a persisted start and no finish is ambiguous: the remote server may have generated an answer. On resume it becomes a terminal `uncertain_interruption`, with no automatic resend. This avoids claiming impossible provider-side exactly-once guarantees. Explicit transport errors can still be retried under the frozen policy; unreceived server computation cannot be ruled out. A valid received/committed response is never regenerated.

## Response integrity, scoring and missingness

Classification precedes and does not use gold correctness. `MAX_TOKENS` is truncated. Provider safety/recitation/prohibited-content blocks are refused. Missing/unsupported finish reason, unexpected tool calls or response shape, multiline answers, code fences or more than 100 whitespace tokens are malformed. Empty STOP text is empty. A narrow frozen lexical rule detects overt refusals; raw final text remains available and the rule cannot identify every implicit refusal. All other STOP final text is valid and scored exactly as returned, with surrounding whitespace removed only. No answer extraction, manual correction, semantic judge or reasoning parsing.

Official HotpotQA normalization lowercases, removes ASCII punctuation, removes English articles and normalizes whitespace. EM is normalized string equality. Token F1 uses multiset overlap and the official yes/no/noanswer mismatch rule. Empty normalized strings retain official behavior (EM may be 1 while F1 is 0). Differential tests compare the local scorer against the downloaded official functions.

Empty/refused/truncated/malformed outputs receive null EM/F1 and explicit integrity labels, not ordinary wrong-answer labels. They are terminal and not retried. Technical exhaustion/interruption has no committed answer. All 800 IDs must be accounted for as commits or terminal failures before sealing. Main analysis defaults to refusing incomplete/invalid blocks. The explicit `--allow-missing` option enables the prespecified complete-valid-block analysis after reconciliation; all attrition and condition-specific integrity counts remain visible. Such estimates concern a validity-conditioned subset and may be biased. They do not estimate the full 200-item target without assumptions. No item replacement or favorable-output selection.

## Estimands and statistics

Primary: mean[(Y10 + Y01)/2 - Y00], with Y equal to binary official answer EM. Two-sided estimation; no manufactured directional hypothesis.

Secondary: mean[Y11 - (Y10+Y01)/2], mean[Y11-Y00], and exploratory mean[Y11-Y10-Y01+Y00]. Report repairs (00 wrong, intervention correct), harms (00 correct, intervention wrong), both-correct and both-wrong counts separately for 10, 01 and 11. Keep the partial conditions separate in the transition figure rather than pooling them as independent questions. Official F1 parallels EM as a supporting outcome. Integrity outcomes are reported separately.

Use 10,000 nonparametric bootstrap resamples with NumPy PCG64 seed 20260929 and questions as the unit. All four responses travel together. Percentile 2.5%/97.5% intervals, NumPy linear quantile convention. Primary reporting emphasizes estimates and uncertainty. Secondary contrasts are exploratory, without post-hoc subgroup tests or p-value searches. If fewer than 200 complete blocks remain, resample the retained complete blocks and state the changed population and n.

Main outputs must be reconciled and sealed into a logical SHA256 fingerprint before analysis. Analysis verifies the protocol and snapshot before and after processing. It accepts no pilot-data input parameter.

## Small validation and example plan

Before main collection: review all ten pilot inputs across all conditions, then ten additional main inputs selected prospectively by SHA256 `[seed, "manual-main-input", item_id]`. Review source alignment, indices, preserved text and flags; no main answers exist at this stage. Record reviewer identity, exact plan/preparation hashes, pass/fail and factual notes. Automated checks complement this review, never claim a human review happened.

After collection: four disjoint strata in order: any harm from 00; repair with no harm; unchanged EM but normalized answer switch; no normalized answer switch. Select up to five hash-ranked cases from each (namespace `post-validation:<stratum>`), with no backfill: maximum 20 cases. Select the first chosen case in each of the first three nonempty strata for up to three illustrations. These are illustrative, not representative prevalence samples or new ground truth. Counts are computed on all complete blocks, never on the qualitative sample. No manual answer corrections.

## Exhibits and limits

Table 1: four conditions and fixed controls. Table 2: per-condition n, EM/F1, valid outputs and technical failures. Table 3: paired contrasts with 95% intervals. Figure 1: four-condition EM and paired contrast intervals. Figure 2: repair/harm counts. Save machine-readable CSV/JSON and PDF/300-dpi PNG plots after main outputs are frozen.

Use “complete annotated support.” Annotations do not prove both paragraphs logically necessary; shortcuts and contamination may exist. Oracle highlighting is not a deployable selector. Focus flags need not act like human attention; more highlighted text in 11 is part of the intervention. One model and 200 questions limit generalization. Interaction does not prove semantic conjunction. Repairs reveal no internal mechanism; harms do not prove that unhighlighted evidence was ignored. Small or null effects must be interpreted with interval width.

Input review found sentence segmentation and annotation-coverage limitations. Pilot item `5a7effeb5542994959419aa0` marks a fragmented Maize sentence; the following unhighlighted sentence contains domestication information. Main item `5abaeda95542992ccd8e7e5d` leaves the bank's headquarters relation in an unhighlighted sentence. Main item `5ae2c8b05542992decbdcd9d` also permits a question-level shortcut. These records remain unchanged. “Accurate” means faithfully aligned with benchmark annotations; it does not guarantee that every marked sentence is independently useful or that condition 11 highlights every fact needed. All source sentences remain available in every condition. This limits the semantic interpretation of emphasis coverage without invalidating the manipulation of annotated support groups.

## Recorded protocol and reproducibility

The selected sample, prompt renderings, model settings, scoring rules, condition definitions and analysis plan were fixed before the main collection. Their hashes are recorded in the machine-readable configuration and manifests. The stored schedules, append-only collection databases and reconciliation reports preserve the relationship between every scientific ID, prompt and returned observation.

The pilot confirmed that the prompts, model configuration, storage logic and response parser operated as specified. The main collection then used the same scientific configuration. Technical retries followed the predefined transport-error policy and never depended on answer content or correctness.
