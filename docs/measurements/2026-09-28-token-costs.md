# Jev input-token costs by question set (measured)

Date: 2026-09-28 (UTC). Model `jev-1.13.0`, price $0.042 per million input tokens.
Runs: `measure-20260928T205036`, `measure-20260928T205121` (ledgers local; budget `smoke`).
Inputs: three synthetic comments (1, 4, and 16 sentences) under an Ask HN parent. No HN text.

| Question set | Short | Medium | Long | Notes |
|---|---|---|---|---|
| baseline (1 tiny noul, comment + parent) | 313 | 375 | 591 | fixed per-call overhead is about 280 tokens |
| screen v0 (3 questions, 20-option domain, parent) | 1,136 | 1,198 | 1,414 | |
| screen v1, first draft (2 questions, parent) | 522 | 584 | 800 | |
| **screen v1 (2 questions, comment only)** | **498** | **560** | **776** | frozen for the pilot |
| deep v0 (16 questions) | 1,130 | 1,299 | 1,923 | |
| facets v1, first draft (17 questions, comment + sentences + parent) | 1,431 | 1,600 | 2,224 | comment sent twice |
| **facets v1 (17 questions, sentences + parent)** | **1,423** | **1,530** | **1,938** | frozen for the pilot |

Implications for the $25 budget:
- Screen cost is about 490 tokens of fixed overhead plus the comment: about 590 tokens for a
  typical HN comment, so 250k comments is about $6.20 and 300k about $7.40.
- Facets cost about 1,420 tokens plus the comment.
- The per-call overhead (about 280 tokens) makes call count matter. The pilot tests packing
  several comments per call against one per call, scored on Hansel's gold labels.

Total spent on measurement: $0.000977 (calculated from reported usage).
