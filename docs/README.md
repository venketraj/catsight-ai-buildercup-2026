# CatSight - documentation

Google Cloud AI Builder Cup 2026 · BFSI theme · Team Techno Crackers

Start with the [project README](../README.md): what CatSight does, how to run it, what is measured and what is not.

| Doc | What it is |
|---|---|
| [`ARCHITECTURE.md`](ARCHITECTURE.md) | The agent graph, data flows, service topology and the trust architecture (verified-or-withheld citations, engine-only figures) |
| [`DOMAIN_PRIMER.md`](DOMAIN_PRIMER.md) | Reinsurance terms in plain language, and the hand-checked worked example the loss engine's tests reproduce (QA-1) |
| [`MONEY_MOMENT.md`](MONEY_MOMENT.md) | Where each party stands - insurer, all reinsurers, Lion Re - derived number by number, including the reinstatement-premium convention |
| [`BUSINESS_IMPACT.md`](BUSINESS_IMPACT.md) | The impact model and benchmarks B1-B8: what is measured, how, and against what baseline |
| [`RESULTS.md`](RESULTS.md) | Every measured number, with the caveat each one carries |
| [`../backend/data/ASSUMPTIONS.md`](../backend/data/ASSUMPTIONS.md) | Every modelling assumption and decision, with its status (DERIVED, JUDGEMENT, UNVERIFIED) and evidence |

Requirement IDs in code and commit messages (`FR-LOSS-2`, `UI-11`, `QA-1`, ...) refer to the team's internal specification.

*Indicative first view on synthetic data. Not a catastrophe-model output. Not underwriting or claims advice.*
