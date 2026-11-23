# Runtime contract

Bohrium Playground Period 4 submission — challenge `challenge-b810ef56` (track: `academic-writing`).

This repository holds the complete skill package for the challenge: the skill
definition, its executable entry point and all supporting scripts. No precomputed
answers, private data or credentials are included.

## Skill

- Name: `evidence-driven-claim-writer`
- Summary: Split a draft into checkable claims, bind each claim to its cited sources, grade evidence strength from study design and sample size, and flag overclaims, causal language and topical mismatches. Use when a writing task must show claim-evidence mapping, evidence levels and honest uncertainty.

## Contents

| File |
|------|
| `SKILL.md` |
| `scripts/run_skill.py` |
| `README.md` |

## How to run

```bash
python scripts/run_skill.py --case /input/case.json --output /app/output/result.json
```

The entry point is `SKILL.md`; input/output contracts, error handling and a minimal
usage example are documented there.

## Notes

- Pure Python standard library; no network access required.
- The result JSON keeps the input case id, the main results, per-item evidence,
  a run status and an uncertainty section.
