# AI usage statement

As allowed by Section 10 of the assignment, this group used a generative AI assistant.
Every member has read, run and can explain the code in their own lead area (see `docs/guides/`).

| Tool | Used for | Who checked it |
|---|---|---|
| Claude (Anthropic), chat assistant with code execution | First version of the code skeleton: generator, Spark pipeline, analytics modules, D3 dashboard, Makefile, tests; explanation of the assignment and planning | All members (each reviewed, ran and modified their own area) |
| | Explanations of methods (EARS, historical limits, WIS, LP formulation, small-cell suppression) used in the report | Analytics / Visualisation leads |

## Representative prompts
- "Explain this CEP assignment step by step and what each requirement means."
- "Build a working version of the EpiScope project that meets all M requirements: seeded synthetic generator,
  bronze/silver/gold Spark pipeline with quality rules and idempotent incremental loads, outbreak detection,
  forecasting with backtests, PuLP allocation, preparedness calendar and a linked D3 dashboard."
- "Explain how the small-cell suppression avoids recovery by subtraction."

## What we changed / verified ourselves
<!-- EDIT THIS: list your own changes honestly, e.g. -->
- Ran `make all` on our own machine at SF = 0.25, 0.5 and 1 and recorded the timings (docs/experiments/).
- Tuned …, fixed …, added …
- Tested the dashboard with two non-CS users and changed … based on their feedback.

## Limits
AI output was treated as a draft. Numbers in the report come from our own runs, not from the assistant.
