# Human-review reconciliation and implications for the term paper

The two supplied workbooks were copied unchanged to `evidence/` and reconciled against the frozen response logs, retrieval manifest, and exact Study 2 prompts. The source workbook hashes and machine-readable counts are in `reconciliation.json`. This note reports the reviewers' entries separately from a narrow source-text quality check; it does not change any label.

## Study 1: 64 selected questions

The updated workbook has all four semantic-status columns filled. All 64 IDs, questions, gold answers, and all 256 model responses match the archived Study 1 records. No pair of identical answer strings has conflicting semantic labels. The 64 questions were selected after a lexical review of benchmark failures; they are **not a random sample of the 200-question study**.

| Condition | Correct | Partially correct | Incorrect | Ambiguous | Official EM correct within these 64 |
|---|---:|---:|---:|---:|---:|
| No support highlighting (00) | 36 | 4 | 20 | 4 | 2 |
| Group A highlighted (10) | 37 | 6 | 16 | 5 | 3 |
| Group B highlighted (01) | 39 | 4 | 16 | 5 | 4 |
| Both highlighted (11) | 40 | 4 | 15 | 5 | 5 |

Between 00 and 11, the reviewer changed four labels from incorrect to correct and one from incorrect to ambiguous; no label changed in the opposite direction. These five cases all have different response strings, and 19 of the 64 response strings change between 00 and 11. The selected sample is useful for checking answer forms and illustrating repairs, but it cannot supply a semantic accuracy estimate or confirm an average highlighting benefit on all 200 questions. The frozen official EM/F1 comparisons remain primary.

This updated workbook supersedes the earlier copy. The existing interim PDF says the 00/11 semantic labels agree on all 64 questions and reports older counts of 45/62 and 42/59 correct among official-EM failures. **Those statements are no longer true and must be replaced before the paper is shared.**

## Study 2: all 48 complete-retrieval EM failures

The workbook contains exactly the 48 official-EM failures among the 106 questions whose two annotated support titles were in BM25's top ten. All IDs, questions, gold answers, model responses, and full retrieved prompts match the frozen Study 2 records.

| Reviewer's semantic judgment | Cases |
|---|---:|
| Correct despite official EM failure | 38 |
| Partially correct | 1 |
| Incorrect | 9 |

Of the nine responses labeled incorrect, three had insufficient supplied context and six were labeled wrong despite sufficient supplied text. One of those six also has a reviewer-marked questionable question or gold answer. Thus **five** cases meet the reviewer's three labels `incorrect` + `sufficient` + `valid`. This is the narrow raw reviewer-supported count, not 48 alleged generation failures.

### Targeted quality check of the five `incorrect` + `sufficient` + `valid` cases

Three warrant caution when the exact retrieved text is read against the question:

- `5a84bc5b5542991dd0999dc3`: the question asks for a vizier *after* the one who served 17 years; the gold `Ibrium` is identified in the supplied page as that vizier's **predecessor**.
- `5a8c5be0554299653c1aa04b`: the question asks who first used the soccer move without specifying Europe. The supplied page says Pedro Calomino invented it, while Law Adam first used it **in Europe**. The model answers Pedro Calomino; the gold is Law Adam.
- `5a808f96554299485f598655`: the question asks for an *event*. The model answers `The First Balkan War`; the gold specifies the Slavic women accompanying their husbands in that war. The shorter answer may be defensible for the question's wording.

These are quality-control flags, not changes to the colleague's judgments. The reviewer marked one additional sufficient-text wrong answer as `questionable` already. If all four questionable cases are excluded in a strict sensitivity reading, **two clear cases** remain among the six reviewer-labeled wrong-with-sufficient-text responses: the Swiss referendum question and the Pollution Prevention Act question. This count is deliberately conservative and should not be presented as a population estimate.

No Study 2 row contains a human note, including the incorrect and questionable cases, although the worksheet requested brief explanations for them. One reviewer initial appears across all 48 rows. The paper can report the entered labels as an exploratory single-reviewer audit, but should avoid strong causal failure-type claims or inter-rater agreement claims.

## Paper-level conclusion

The new human evidence substantially changes the emphasis. The headline `48/106 complete-retrieval EM failures` is mostly an **answer-evaluation mismatch under the reviewer's judgments**: 38 were marked semantically correct. The controlled follow-up separately shows that supplying a missing annotated page improves official EM by 22.0 percentage points on the 91 partial-retrieval questions, while a simple page-level cue brings no measured improvement on 106 complete-retrieval questions. A defensible RAG paper can therefore lead with *retrieval access, answer realization, and evaluation* as separable sources of apparent failure. It should present the few genuine wrong answers with sufficient context as carefully checked examples, not as a broad 48-case failure rate.

Before the final LaTeX/PDF rewrite, replace every result that relies on the older Study 1 workbook, add the Study 2 audit with the above caveats, and integrate the frozen follow-up as its own controlled experiment. The workbooks themselves remain unchanged.
