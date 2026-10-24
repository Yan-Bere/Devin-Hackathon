# Requirements-parser prompt evaluation

Runtime prompts: `prompts/requirements_parser/<version>/task.md` and `repair.md`.
Structured-output schema: `coldplate/extraction_schema.py` (shared by all versions; sent
to Devin as `structured_output_schema`). Fixtures: `tests/fixtures/A_canonical.md` …
`F_impossible_limits.md`. Expected values and scoring: `coldplate/eval/rubric.py` and
`coldplate/eval/harness.py`.

```
# live: one Devin session per fixture; records raw outputs for offline replay
.venv\Scripts\python.exe scripts\eval_prompts.py --provider devin --record --prompt-version v2
# offline: replay recorded Devin outputs, no quota
.venv\Scripts\python.exe scripts\eval_prompts.py --provider recorded --prompt-version v2
```

Each run writes a JSON report to `prompts/requirements_parser/eval/<version>-<UTC>.json`.

## Metrics

- **extraction errors**: wrong or missing values, failed unit conversions, heat-source
  mismatches, forbidden values (e.g. reporting 2.0 L/min in fixture E).
- **provenance errors**: right value, wrong `source`. For example, a row marked
  **ASSUMPTION** that is reported as plain `input`.
- **unsupported assumptions**: `source: "assumed"` on a field the document states, or on
  an essential input.
- **evidence misses**: the evidence quote is not a verbatim substring of the document.
- **value not in quote**: the quote exists but does not contain the reported number(s).
  Detected by the normalizer.
- **schema failures**: the first Devin output failed Pydantic validation or a blocking
  semantic check, which triggers the single repair request.
- **Devin calls**: sessions created plus repair messages sent.

## Results (2026-10-24, live Devin sessions, API v1 legacy key)

| Prompt | Fixture | Status | Rubric findings | Value not in quote | Schema failure | Devin calls | Latency (s) |
|---|---|---|---|---|---|---|---|
| v1 | A canonical | ok* | 0 | 4 | no | 1 | 47 |
| v1 | B flow 3 L/min | ok* | 0 | 4 | no | 1 | 111 |
| v1 | C GPU1 +20 % | ok | 0 | 5 | no | 1 | 166 |
| v1 | D plate 90×84 | ok | 0† | 5 | no | 1 | 95 |
| v1 | E flow removed | needs_input | 0 | 0 | no | 1 | 94 |
| v1 | F impossible limits | ok | 0† | 4 | no | 1 | 102 |
| **v2** | A canonical | ok | 0 | **0** | no | 1 | 85 |
| **v2** | B flow 3 L/min | ok | 0 | **0** | no | 1 | 102 |
| **v2** | C GPU1 +20 % | ok | 0 | **0** | no | 1 | 103 |
| **v2** | D plate 90×84 | ok | 0 | **0** | no | 1 | 119 |
| **v2** | E flow removed | needs_input | 0 | **0** | no | 1 | 102 |
| **v2** | F impossible limits | ok | 0 | **0** | no | 1 | 94 |

Pipeline-level checks passed for both versions: B → 3.0 L/min; C → 1603.68 W total;
D → plate 90 × 84 × 2.5 mm; E → `needs_input`, with `coolant.flow_rate` missing and never
substituted with 2.0 L/min. No run needed a repair request. Totals: v1 = 6 sessions,
v2 = 6 sessions.

\* At the time of the run, A and B returned `needs_input`. Devin had (correctly) flagged
`flow.flow_axis` as an essential missing field, because the text never says which pair of
edges are the inlets. The engine now decides essential inputs itself. Devin's flags are
kept in `reported_missing`, and the axis falls back to a labelled default (x, which matches
the competition flow-path figure). The `ok` shown is from replaying the same recorded
outputs through the corrected normalizer.

† The original grader counted one error each for D and F: Devin listed the uniform-heat
components as `H1…H8` instead of `HBM`. The schema explicitly allows source names *or*
types, so this was a rubric defect. The rubric now accepts either form (`covers_type`).
After this correction, v1 and v2 both have 0 rubric findings on all fixtures.

## Change log

- **v1:** baseline prompt.
- **v2:** one change to rule 5, made because v1 failed it in 5 of 6 fixtures (22 misses,
  all on `coolant.flow_rate_sweep`, where Devin quoted only one table row). v2 requires a
  list's quote to contain every listed value, allowing up to 300 characters. Result: 22 → 0
  misses with no regressions. **v2 is the default.**
