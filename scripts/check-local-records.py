"""Bind company notes and question choices to archived inputs, responses and GPU."""

from datetime import datetime, timezone
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from equitylab import (
    coverage_reasoning as protocol,
    local_ai,
    model_evaluation,
    pipeline,
    questions,
    filing_reading,
)
from equitylab.data import canonical, digest


def main():
    snapshot = pipeline.load_latest()
    reviews = local_ai.read_reviews(
        snapshot, protocol=protocol, archive_name="coverage-reviews"
    )
    ready = {c["id"]: c for c in snapshot["companies"] if c["status"] == "ready"}
    if set(reviews) != set(ready):
        raise ValueError("Every ready company needs its own local review attempt")
    records = []
    for id, c in ready.items():
        r = reviews[id]
        if r["status"] in ("stale", "failed"):
            raise ValueError("Unfinished current company review: " + id)
        pointer = json.loads(
            (ROOT / "data/coverage-reviews" / id / "latest.json").read_text()
        )
        folder = (ROOT / pointer["file"]).parent
        full = (folder / "input.json").read_bytes()
        if digest(full) != r["inputHash"] or json.loads(full) != protocol.input_packet(
            c
        ):
            raise ValueError("Review input archive mismatch: " + id)
        if json.loads(
            (folder / "prompt-input.json").read_text()
        ) != protocol.compact_packet(json.loads(full)):
            raise ValueError("Prompt data archive mismatch: " + id)
        last = len(r["reviewRounds"]) - 1
        stage = "revision" if last else "draft"
        raw = json.loads((folder / (stage + "-raw.json")).read_text())
        notes = json.loads(raw["message"]["content"])
        if protocol.attach_evidence(notes, protocol.evidence(c)) != r["notes"]:
            raise ValueError(
                "Displayed notes differ from the last model response: " + id
            )
        for item in r["scrutiny"]["assessments"]:
            p = folder / f'review-{last}-{item["id"]}-raw.json'
            actual = json.loads(json.loads(p.read_text())["message"]["content"])[
                "assessments"
            ]
            if actual != [item]:
                raise ValueError(
                    "Displayed criticism differs from the model response: " + id
                )
        for path in folder.glob("*-request.json"):
            req = json.loads(path.read_text())
            if (
                req["think"] != r["inferenceConfig"]["think"]
                or req["options"] != r["inferenceConfig"]["options"]
            ):
                raise ValueError("Inference settings differ from archive: " + id)
        gpu = any(
            m.get("size_vram", 0) > 0 and m.get("digest") == r["modelDigest"]
            for m in r.get("loadedModels", [])
        )
        if not gpu:
            raise ValueError("GPU model evidence missing: " + id)
        records.append(
            dict(
                company=id,
                recordHash=r["recordHash"],
                status=r["status"],
                displayEligible=r["displayEligible"],
                gpu=gpu,
                editorialHoldHashes=[f["hash"] for f in r.get("editorialFindings", [])],
                files={
                    str(p.relative_to(ROOT)): digest(p.read_bytes())
                    for p in sorted(folder.iterdir())
                    if p.is_file()
                },
            )
        )
    evaluation = model_evaluation.read_evaluation("coverage-evaluations")
    transfer = model_evaluation.read_evaluation("coverage-transfer-evaluations")
    selections = questions.read(snapshot)
    if set(selections) != set(ready) or any(
        r["status"] != "selected" for r in selections.values()
    ):
        raise ValueError(
            "Every company needs a current completed local question selection"
        )
    for r in selections.values():
        if not any(
            m.get("size_vram", 0) > 0 and m.get("digest") == r["modelDigest"]
            for m in r["loadedModels"]
        ):
            raise ValueError("Question selection GPU evidence missing")
    readings = filing_reading.read(snapshot)
    if set(readings) != set(ready) or any(
        r["status"] == "stale" for r in readings.values()
    ):
        raise ValueError("Every ready company needs a current filing reading attempt")
    for r in readings.values():
        if r.get("semanticApproval"):
            raise ValueError("Filing reading cannot imply semantic approval")
        if r["status"] == "unreviewed_draft" and not any(
            m.get("size_vram", 0) > 0 and m.get("digest") == r["modelDigest"]
            for m in r["loadedModels"]
        ):
            raise ValueError("Filing reading GPU evidence missing")
    report = dict(
        checkedAt=datetime.now(timezone.utc).isoformat(),
        status="passed",
        snapshotHash=snapshot["contentHash"],
        companies=len(records),
        qualityHeld=sum(not r["displayEligible"] for r in records),
        independentFinancialApproval=False,
        evaluation=dict(
            recordHash=evaluation["recordHash"],
            gatePassed=evaluation["gatePassed"],
            counts=evaluation["counts"],
        ),
        transferEvaluation=(
            {k: transfer[k] for k in ("recordHash", "gatePassed", "counts", "scope")}
            if transfer
            else None
        ),
        records=records,
        filingReadings={
            k: dict(
                recordHash=r["recordHash"], status=r["status"], semanticApproval=False
            )
            for k, r in readings.items()
        },
        questionSelections={
            k: dict(recordHash=r["recordHash"], choice=r["choice"])
            for k, r in selections.items()
        },
    )
    report["verificationHash"] = digest(canonical(report))
    (ROOT / "artifacts/local/model-evidence-verification.json").write_bytes(
        canonical(report)
    )
    print(
        f"PASS {len(records)} company records and {len(selections)} question selections: original inputs, exact responses and GPU evidence; {report['qualityHeld']} freeform quality holds; no financial approval"
    )


if __name__ == "__main__":
    main()
