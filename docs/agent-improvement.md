# Making the agent better, on purpose

Most "improve the prompt" work is guessing. Someone reads a bad output, edits
some wording, the next few results look better, and nobody can say whether
anything actually changed. This document describes the loop this service is
built around instead, where every claim about the agent getting better has a
number behind it.

The loop is already wired. What follows is how to run it.

---

## 1. The loop in one picture

```
   Operator reviews an analysis
              │
              │  verdict + field corrections
              ▼
     analysis_feedback  ─────────────┐
                                     │
   build_golden_set.py               │  labelled examples
              │                      │
              ▼                      │
      evals/data/golden.jsonl  ◀─────┘
              │
              │  same cases, two configurations
              ▼
    evals/main.py compare --variant v3 --variant v4
              │
              │  five rates
              ▼
      Keep the winner. Ship it. Repeat.
```

Nothing here depends on anyone remembering to write test cases. The training
data is a by-product of the work operators already do.

---

## 2. What gets measured

Five numbers, reported by `evals/main.py`. Four of them can move independently,
which is the point — a single "accuracy" score hides the trade that matters.

| Metric | What it means | Why it is separate |
| --- | --- | --- |
| **Field accuracy** | matches ÷ judged fields | The headline. Meaningless alone. |
| **Miss rate** | expected a value, produced `no_encontrado` | Cheap failure. The reviewer sees a gap and fills it. |
| **Invention rate** | expected nothing, produced something | **Expensive failure.** A deducible that is not in the policy can authorise or deny a claim on a number nobody wrote. |
| **Grounding rate** | populated fields whose quote is actually in the document | Hallucination, measured directly and without a model in the loop. |
| **Latency / tokens** | cost per policy | The budget a quality gain is bought with. |

**The rule: a change that raises accuracy and raises invention is a
regression.** `evals/main.py compare` ranks configurations by
`accuracy − invention` for exactly this reason. It is the difference between an
agent that is more useful and one that is more confident.

---

## 3. Where the labels come from

```bash
uv run python evals/build_golden_set.py --output evals/data/golden.jsonl
```

Three kinds of label, from one form:

- **`correct`** → every populated field becomes an expected value. One click
  produces ~20 labels.
- **`partially_correct` / `incorrect` with a corrected field** → that field
  becomes an expected value. Fields the reviewer did not touch stay *unjudged*,
  because silence is not a label and treating it as one fills the set with
  confident nonsense.
- **A correction with an empty `should_be`** → an `expected_absent` entry. The
  reviewer is saying *the agent made this up*.

That last kind is the most valuable data the system collects and the easiest to
under-collect. A golden set with no negative examples cannot measure invention
at all — it can only reward a model for filling fields in. `build_golden_set.py`
prints a warning when the set has none, and the review UI has a dedicated
**Inventado** button next to every field so producing one is a single click.

**Tell reviewers this explicitly.** "Mark it invented" is a different action
from "leave it blank", and only one of them teaches the system anything.

### Volume needed before the numbers mean anything

| Reviewed analyses | What you can trust |
| --- | --- |
| < 30 | Nothing. Individual failures only. |
| 30–100 | Direction of a large change (a model swap). |
| 100–300 | A prompt edit worth ~5 points of accuracy. |
| 300+ | Field-level regressions, per-insurer breakdowns. |

At 10 policies a day with a 60% review rate, that is roughly six weeks to a set
worth gating deploys on. Until then the harness is a debugging tool, not a gate.

---

## 4. The weekly loop

**Monday — rebuild and baseline.**

```bash
uv run python evals/build_golden_set.py
uv run python evals/main.py run --output evals/reports/baseline.json
```

**Read the failures, not the score.** The report lists the fields that fail
most. That ranking is the week's agenda, and it is almost never uniform — in
practice one or two fields carry most of the error.

**Tuesday–Thursday — change exactly one thing.**

Copy the current `extraction_v3.md` to `extraction_v4.md` and edit. One
hypothesis per version. A version that changes the schema, the wording, and the
temperature at once cannot be attributed to anything.

**Friday — compare and decide.**

```bash
uv run python evals/main.py compare \
  --golden evals/data/golden.jsonl \
  --variant v3 --variant v4
```

Ship `v4` by setting `ANALYSIS_PROMPT_VERSION=v4`. Keep `extraction_v3.md` in
the repository: old runs recorded `prompt_version`, and deleting the file makes
those runs unexplainable.

The one exception is a version the schema has outgrown. The output contract is
generated from `AnalisisGMM` and appended at call time, so a prompt naming
sections the schema no longer has returns something plausible and wrong rather
than failing. Delete such a version in the same change that retires it — a
`prompt_version` with no file behind it is a smaller loss than one somebody can
still select. `v1` and `v2` went that way with the seven-section schema.

---

## 5. A playbook per failure mode

The failure tells you which lever to pull. Reaching for the prompt every time is
how teams spend a month on wording when the schema was the problem.

### High miss rate on one field

The value is in the document and the agent is not finding it.

- Is it in a table or a footnote? OCR flattens tables into column-mixed lines,
  so `deducible` and `coaseguro` end up on the same row. Check
  `notas_calidad_documento` on the failing runs first — this is frequently an
  **OCR problem wearing a prompt problem's clothes**, and no amount of prompt
  editing fixes a page the model cannot read.
- Does the field have a name the prompt does not mention? Insurers differ:
  "tope de coaseguro", "límite de coaseguro", "coaseguro máximo". Add the
  variants to the "Qué buscar" section.
- Add one worked example to the prompt showing the field in the layout it is
  being missed in.

### High invention rate

The agent is filling a field it should have left empty.

- Strengthen the `no_encontrado` instruction — but check first that the schema
  is not fighting it. A field the model believes is required is a field it will
  invent a value for.
- Confirm the self-critique pass is on (`ANALYSIS_SELF_CRITIQUE_ENABLED`). Its
  first job is deleting values whose quote is not in the document.
- Lower `GEMINI_TEMPERATURE` if it has drifted from `0.0`.

### High grounding failure, low miss rate

The agent is producing plausible values with quotes that do not exist — the most
dangerous combination, because the output looks complete and cited.

- This is usually a model-capability ceiling rather than a prompt bug. Try a
  stronger model — a newer flash such as `gemini-3.7-flash`, or `gemini-pro-latest`
  — before rewriting anything.
- Verify the evidence field is being asked for *per value*, not per section. A
  section-level quote is unverifiable by construction.

### Errors clustered on one insurer

Sort failures by `identificacion.aseguradora`. GNP, AXA and Monterrey lay out a
carátula very differently. A per-insurer example block in the prompt is cheap
and targeted; a general rewrite is neither.

---

## 6. The next three upgrades, in order of value

Each of these is a real step up, listed in the order the return justifies the
work. The current system is deliberately the simplest thing that supports them.

### a. Few-shot examples mined from corrections — *highest value, lowest effort*

Once ~50 corrections exist, select the 3–5 that represent the most common
failures and paste the corrected field plus its real evidence quote into the
prompt as worked examples. Grounded few-shot examples reliably outperform more
instruction text, because they show the model the layout rather than describing
it.

Rebuild these each time the prompt version changes, and pick them from the
*training* half of the set (see §7).

### b. A retrieval step for insurer-specific layouts

When one insurer dominates the volume, store a short layout note per insurer
("GNP puts the tope de coaseguro in the third table, right column") and inject
only the matching one. This keeps the prompt short — a prompt carrying every
insurer's quirks gets worse at all of them.

### c. Fine-tuning — *last, not first*

Only worth considering at 500+ corrected examples, and only if prompt work has
plateaued. Everything needed is already stored: `redacted_text` is the input,
the corrected `result` is the target. The reason it is last is that a fine-tune
freezes today's schema and today's failure modes, and this schema is still
moving. Prompt changes ship in an afternoon; a fine-tune does not.

**Note on data:** fine-tuning would send the redacted corpus to a training
service. That is a materially different disclosure from a single inference call
and needs its own review under the LFPDPPP before anyone starts.

---

## 7. Two ways this loop lies to you

**Overfitting to the golden set.** Optimise against the same 100 cases for long
enough and you get a prompt that is excellent at those 100 cases. Hold back 20%
by case id, never look at it while iterating, and check it before shipping. If
held-out accuracy has not moved with training accuracy, the gain is not real.

**Reviewer drift.** Verdicts are labels, and labels are only as good as the
people producing them. A reviewer who clicks "correct" to clear their queue is
manufacturing false confidence — and it shows up as *rising* accuracy, which
looks like success. Two cheap controls:

- Watch `review_rate` and `accuracy_rate` together on the dashboard. Accuracy
  climbing while review rate falls is a warning, not a win.
- Have two reviewers judge the same 10 analyses once a month. If they disagree
  materially, the schema is ambiguous — fix the schema, not the reviewers.

---

## 8. What is already running without you

- **Per-value evidence verification.** The `verify` node checks in ordinary
  Python that every quote appears in the document, and downgrades the confidence
  of any field that fails. It costs no tokens and does not ask the model to
  grade itself.
- **A targeted repair pass.** `critique` runs *only* when verification found
  something, and runs once. Unconditional self-critique costs double and starts
  rewriting fields that were already right.
- **Live hallucination metrics.** `analysis_evidence_failures_total` rises the
  moment a deploy makes the agent less grounded, without waiting for a review.
  Alert on it.
- **Full provenance.** Every run stores `model_name`, `prompt_version`,
  `redacted_text` and its output, so any answer can be replayed against a new
  prompt months later.

---

## 9. Commands

```bash
# Rebuild the golden set from reviewer feedback
uv run python evals/build_golden_set.py --limit 500

# Score the current configuration
uv run python evals/main.py run --output evals/reports/$(date +%F).json

# Compare prompt versions over identical cases
uv run python evals/main.py compare --variant v3 --variant v4

# Gate a deploy in CI
uv run python evals/main.py run --min-accuracy 0.85 --max-invention 0.02
```

Set the CI thresholds from your own measured baseline, not from the numbers
above — they are placeholders, and a gate calibrated to someone else's data
fails honest changes while passing bad ones.
