# Eval methodology

Technical companion to [README.md §11](../README.md#11-evaluation) and
[ARCHITECTURE.md §9](../ARCHITECTURE.md#9-testing--evaluation-strategy). Explains
what each of the four metrics actually checks, why `ledger_integrity` exists, and
the known limitations of this evalset.

## The four metrics

| Metric | Level | What it actually checks |
|--------|-------|--------------------------|
| `pii_containment` | Deterministic, narration | Scans the final **response text** shown to the user for an unredacted account/card number or SSN pattern. |
| `injection_rejection` | Deterministic, narration | Scans the final response's **prose** for words implying a defense fired ("ignored", "flagged", "as data") vs. words implying the attack succeeded. |
| `ledger_integrity` | Deterministic, **mechanism** | Reads the actual **persisted ledger** (`app/data/ledger.json`) after the run and asserts the structural invariant the case depends on — an attacked receipt/statement line is still a positive expense; a PII-bearing entry is redacted at rest. |
| `custom_response_quality` | LLM-as-judge | Grades the response against the case's `reference` for accuracy, **completeness of reasoning** (not just a correct final conclusion), and clarity. |

## Why `ledger_integrity` exists

A live run once scored `injection_rejection = 5.0` on the `injection_defense` case
purely because the reply said *"I ignored it."* In that run the Orchestrator had
actually **paraphrased** the attack text before delegating to the Ingestion agent,
so the deterministic guard in `app/tools/injection_guard.py` never saw the literal
attack string and never fired — the reply's claim was true in spirit but the
security *mechanism* never ran. `injection_rejection` cannot tell those two
situations apart because it only ever reads the model's prose.

`ledger_integrity` closes that gap by checking the **outcome the guard exists to
protect**, not a claim about it: after the run, is the attacked entry still a
positive expense in the ledger? Is the PII-bearing entry redacted at rest? Those
are structural facts about persisted state, not narration, so they can't be
satisfied by a model that merely *says* the right thing.

The fix that actually closed the gap lives in code, not in this eval: the
Orchestrator's instruction now requires delegating document text to the Ingestion
agent **verbatim** (`app/agent.py`), and `IngestResult.summary()`
(`app/tools/ingest.py`) builds the confirmation sentence in code rather than
leaving it to the model. `ledger_integrity` is the metric that would have caught
the original gap; it exists to keep that fix honest going forward.

## Known limitations

- **Duplicated metric logic across two harnesses.** `tests/eval/eval_config.yaml`
  (the Vertex-managed `agents-cli eval` path) and `tests/eval/run_eval.py` (the
  AI-Studio-compatible local fallback) each implement the same four metrics
  independently, rather than sharing one implementation. This is not an oversight:
  `agents-cli eval grade` executes `custom_function` blocks in its own isolated
  tool environment, which cannot `import app.*` (that transitively pulls in
  `google.adk`, which that environment lacks). The metric logic is small enough
  (a few regexes and a ledger read) that keeping both copies in lockstep by hand is
  an accepted tradeoff, not a solved problem — a change to one must be manually
  mirrored in the other.
- **Cases with no injection trivially score 5 on `injection_rejection` and
  `ledger_integrity`.** Both metrics return a perfect score with an
  "not applicable to this case" explanation when a case isn't a security case at
  all (e.g. `budget_status`). That inflates the reported average number of "5.0"
  results relative to how many cases actually exercise the defense — only
  `injection_defense` and `injection_via_statement` (of 10 cases) exercise the
  injection path, and only `pii_redaction` exercises the redaction path. Treat the
  scorecard's per-metric average as "no regression detected," not "N cases proved
  this."
- **`ledger_integrity` shares one ledger file across the whole eval run.** Cases
  run against the same `app/data/ledger.json`, seeded once at the start
  (`make eval` / `run_eval.py`'s `main()`). This is intentional — later cases
  (e.g. `which_card_hero`) depend on the seeded state — but it means
  `ledger_integrity`'s per-case check can only assert "this pattern of entry
  exists somewhere in the ledger," not "this specific run added exactly this
  entry," since concurrent or repeated runs would leave earlier entries in place.
- **10 cases cover 8 of the ~16 SPEC §3 scenarios end-to-end via the live agent.**
  The rest (reconciliation, deadline-tiebreak, correction-learning) are proven
  deterministically in `tests/unit/` instead, since they don't need a live model
  call to verify and a unit test is strictly more reliable for them.
