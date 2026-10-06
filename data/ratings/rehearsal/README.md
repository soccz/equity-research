# Rehearsal universes (never read by the code)

The computability-check rehearsal of 2026-10-06 built these universes (US part for T = 2026-10-05, KR part for T = 2026-10-06) under an earlier RULES text. On 2026-10-07 they were moved here from `data/ratings/universe/`.

They had to move because a part of the same month in `data/ratings/universe/` would have been picked up when the parts of the real gate (asOf 2026-10-19) were merged. That merge would have failed on 2026-10-19/20. The independent review found this on 2026-10-07.

The files are kept as a record only. The `part` paths inside the merged file name their original location, and git history holds them there (commit cf9ef51). Rehearsals build fresh universes (`scripts/ratings_ops.py rehearse`).
