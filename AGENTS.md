# Equity Research

- This project runs on GitHub-hosted Actions and publishes the static `site/` folder to Pages. Do not add a required local server or self-hosted runner.
- `README.md` describes the current eight-company exploratory scope. Preserve filing dates, accounting periods, units, source hashes, missing intervals, baselines and failed hypotheses.
- Do not equate research candidates with validated investment recommendations. Keep variance loss, excess return and condition fulfillment separate.
- Do not place credentials, raw workspace dumps or private paths in `site/`. Run `python scripts/check-site.py` before publishing.
- For analysis changes run the engine tests, isolated replay, Chrome file-based checks and PDF audit before `python -m equitylab build-site`.
- Preserve `data/ledger/conditions.jsonl` as an append-only record. A local hash chain is not external timestamp certification.
- Do not use subagents unless the user explicitly requests them.
