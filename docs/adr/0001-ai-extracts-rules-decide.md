# ADR-0001: AI extracts, rules decide

**Status:** Accepted · 2026-10-28

## Context
Invoices lead to payments. A model that approves, matches or posts can be wrong in ways that are hard to predict and easy to exploit (prompt injection inside a PDF). Finance teams and auditors need decisions they can explain and replay.

## Decision
- The LLM's only output is a schema-constrained extraction with evidence.
- Matching, validation, duplicate and fraud checks, approval routing and posting are deterministic Python rules, versioned and configurable per org.
- The one place AI suggests something beyond extraction (expense account for a new non-PO vendor) always requires human approval.

## Consequences
- ✅ Prompt injection can at most corrupt extracted values, which grounding and the math checks catch. It can't cause an approval.
- ✅ Every decision is explainable ("rule X with tolerance Y") and replayable with `rules_version`.
- ✅ Cheap: one AI call per invoice.
- ❌ Some judgment calls (unusual line descriptions) go to people instead of being automated. This is acceptable: the goal is straight-through processing for clean invoices, not for all of them.
