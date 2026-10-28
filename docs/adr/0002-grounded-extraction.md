# ADR-0002: Grounded extraction with evidence

**Status:** Accepted · 2026-10-28

## Context
LLMs read invoice layouts well but can produce plausible values that aren't on the page (for example a "typical" invoice number format, or a total that makes the math work). Reviewers need to verify values fast.

## Decision
- Every extracted value comes with the page and an exact quote.
- For PDFs with a text layer, the quote must be found in the page's words (exact, then fuzzy ≥ 90); its bounding box is stored for highlighting. Values that can't be found are cleared and flagged.
- For scans and photos, values are marked `model_only` (lower trust) and must pass math checks before they can go straight through.
- Trust levels come from grounding + checks, never from the model's self-reported confidence.

## Consequences
- ✅ Hallucinated values are caught mechanically; E2 measures how many.
- ✅ The review screen can highlight every value on the document, making review fast.
- ❌ More code (word search, normalising quotes) and slightly stricter: occasionally a correct value is flagged when the quote formatting differs. This is tuned with the fuzzy threshold and evals.
