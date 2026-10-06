"""Local-only filing interpretation. No hosted AI, tools, or automatic fallback."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import re
from pathlib import Path
import urllib.request
import urllib.error
from urllib.parse import urlsplit
from .data import ROOT, canonical, digest


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class LocalClient:
    def __init__(self, base="http://127.0.0.1:11435", timeout=180, thinking=False):
        u = urlsplit(base)
        if (
            u.scheme != "http"
            or u.hostname not in ("127.0.0.1", "::1")
            or u.username
            or u.password
            or u.query
            or u.fragment
            or u.path not in ("", "/")
        ):
            raise ValueError("Only a numeric loopback model endpoint is allowed")
        self.base = base.rstrip("/")
        self.timeout = timeout
        self.inference_config = dict(
            think=thinking,
            options=dict(
                num_ctx=8192 if thinking else 4096,
                num_predict=4096 if thinking else 1400,
                temperature=1.0 if thinking else 0.7,
                top_p=0.95 if thinking else 0.8,
                top_k=20,
                min_p=0.0,
                presence_penalty=1.5,
                repeat_penalty=1.0,
                seed=42,
                num_batch=128,
            ),
        )
        self.opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}), NoRedirect
        )

    def call(self, path, body=None):
        if path not in ("tags", "version", "ps", "chat", "generate"):
            raise ValueError("Unsupported local model operation")
        req = urllib.request.Request(
            self.base + "/api/" + path,
            data=canonical(body) if body is not None else None,
            headers={"Content-Type": "application/json"},
        )
        try:
            with self.opener.open(req, timeout=self.timeout) as response:
                raw = response.read(2_000_001)
        except urllib.error.HTTPError as exc:
            detail = exc.read(4096).decode("utf-8", errors="replace")
            raise RuntimeError(f"Local model HTTP {exc.code}: {detail}") from None
        if len(raw) > 2_000_000:
            raise ValueError("Local model response too large")
        result = json.loads(raw)
        if not isinstance(result, dict) or result.get("error"):
            raise ValueError("Local model response failed")
        return result

    def model(self, name):
        if (
            not re.fullmatch(r"[a-zA-Z0-9._-]+:[a-zA-Z0-9._-]+", name)
            or "cloud" in name.lower()
        ):
            raise ValueError("Only installed local model names are allowed")
        installed = next(
            (m for m in self.call("tags").get("models", []) if m["name"] == name), None
        )
        if not installed or not installed.get("digest"):
            raise ValueError(
                "Install the local model before inference; automatic downloads are disabled"
            )
        return installed

    def generate(self, model, messages, schema, archive=None):
        request = dict(
            model=model,
            messages=messages,
            format=schema,
            stream=False,
            keep_alive="120s",
            **{
                k: v
                for k, v in self.inference_config.items()
                if k in ("think", "options")
            },
        )
        if archive is not None:
            archive.with_name(
                archive.name.replace("-raw.json", "-request.json")
            ).write_bytes(canonical(request))
        response = self.call("chat", request)
        # Preserve the server response before completeness, JSON or schema checks.
        if archive is not None:
            archive.write_bytes(canonical(response))
        if not response.get("done") or response.get("done_reason") not in (
            "stop",
            None,
        ):
            raise ValueError(
                "Local response incomplete; preserve it as a failed attempt"
            )
        # Prompt truncation is not acceptable evidence coverage.
        if (
            response.get("prompt_eval_count", 0)
            >= self.inference_config["options"]["num_ctx"] - 1024
        ):
            raise ValueError("Local input too close to context limit")
        text = response.get("message", {}).get("content", "")
        return (
            json.loads(text),
            {
                k: response.get(k)
                for k in (
                    "model",
                    "created_at",
                    "done_reason",
                    "prompt_eval_count",
                    "eval_count",
                    "total_duration",
                    "load_duration",
                    "eval_duration",
                )
            },
            response,
        )


def text_ok(value):
    return (
        isinstance(value, str)
        and 1 <= len(value.strip()) <= 1200
        and not re.search(r"[0-9]", value)
    )


def validate_draft(draft, evidence):
    if (
        not isinstance(draft, dict)
        or set(draft) != {"summary", "claims"}
        or not text_ok(draft["summary"])
    ):
        raise ValueError("Invalid local draft summary")
    claims = draft["claims"]
    known = {e["id"] for e in evidence}
    if not isinstance(claims, list) or not 1 <= len(claims) <= 3:
        raise ValueError("Local draft needs one to three claims")
    for c in claims:
        if not isinstance(c, dict) or set(c) != {
            "text",
            "evidence",
            "alternative",
            "check",
        }:
            raise ValueError("Invalid claim fields")
        if not all(text_ok(c[k]) for k in ("text", "alternative", "check")):
            raise ValueError(
                "Claim text must be short and contain no unverified numerals"
            )
        if (
            not isinstance(c["evidence"], list)
            or not 1 <= len(c["evidence"]) <= 4
            or any(not isinstance(x, str) or x not in known for x in c["evidence"])
        ):
            raise ValueError("Unknown or absent evidence reference")
    return draft


def validate_critic(critic, count):
    if (
        not isinstance(critic, dict)
        or set(critic) != {"verdict", "issues", "unsupportedClaims"}
        or critic["verdict"] not in ("usable_with_caveats", "revise")
    ):
        raise ValueError("Invalid critique")
    if (
        not isinstance(critic["issues"], list)
        or not 1 <= len(critic["issues"]) <= 5
        or not all(
            text_ok(re.sub(r"^claim_[0-9]+:\s*", "", s)) for s in critic["issues"]
        )
    ):
        raise ValueError("Critique must explain limits")
    if not isinstance(critic["unsupportedClaims"], list) or any(
        type(x) is not int or not 0 <= x < count for x in critic["unsupportedClaims"]
    ):
        raise ValueError("Invalid challenged claim index")
    if critic["unsupportedClaims"] and critic["verdict"] != "revise":
        raise ValueError("Unsupported claims cannot pass review")
    return critic


def ask_recorded(client, model, out, stage, system, task, content, schema):
    messages = [
        {"role": "system", "content": system},
        {
            "role": "user",
            "content": task + "\n" + json.dumps(content, ensure_ascii=False),
        },
    ]
    (out / (stage + "-request.json")).write_bytes(
        canonical({"model": model, "messages": messages, "schema": schema})
    )
    try:
        result, timing, raw = client.generate(
            model, messages, schema, archive=out / (stage + "-raw.json")
        )
    except Exception as exc:
        (out / (stage + "-error.json")).write_bytes(
            canonical(
                {
                    "error": type(exc).__name__ + ": " + str(exc)[:500],
                    "createdAt": datetime.now(timezone.utc).isoformat(),
                }
            )
        )
        raise
    return result, timing


def review(
    company,
    snapshot_hash,
    client,
    model,
    *,
    protocol=None,
    archive_name="local-reviews",
):
    from . import reasoning as default_reasoning
    from .model_evaluation import gate_for

    reasoning = protocol or default_reasoning
    if archive_name not in ("local-reviews", "coverage-reviews"):
        raise ValueError("Unknown research-note archive")
    gate_options = (
        dict(
            protocol=protocol,
            suite_path=protocol.SUITE,
            archive_name="coverage-evaluations",
        )
        if protocol
        else {}
    )

    installed = client.model(model)
    p = reasoning.input_packet(company)
    compact = reasoning.compact_packet(p)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    out = ROOT / "data" / archive_name / company["id"] / stamp
    out.mkdir(parents=True, exist_ok=False)
    (out / "input.json").write_bytes(canonical(p))
    (out / "prompt-input.json").write_bytes(canonical(compact))
    record = dict(
        schemaVersion=2,
        company=company["id"],
        createdAt=datetime.now(timezone.utc).isoformat(),
        snapshotHash=snapshot_hash,
        evidenceHash=(
            protocol.evidence_hash(company)
            if protocol
            else company["dossier"]["evidenceHash"]
        ),
        inputHash=digest(canonical(p)),
        promptVersion=reasoning.VERSION,
        promptHash=reasoning.protocol_hash(),
        model=model,
        modelDigest=installed["digest"],
        serverVersion=client.call("version")["version"],
        mode="local_only",
        independentReview=False,
        status="failed",
        observations=p["computedObservations"],
        evaluation=gate_for(
            installed["digest"], client.inference_config, **gate_options
        ),
        inferenceConfig=client.inference_config,
        scope="관측은 코드가 계산하고 모델은 가능한 설명·대안·확인 질문·근거 공백을 작성한다. 문장별 자체 점검과 합성 개발 평가는 독립 금융 해석 승인이 아니다.",
    )
    try:
        schema = reasoning.DRAFT_SCHEMA
        notes, stats = ask_recorded(
            client,
            model,
            out,
            "draft",
            reasoning.SYSTEM,
            reasoning.DRAFT_TASK,
            compact,
            schema,
        )
        notes = reasoning.attach_evidence(notes, p["evidence"])
        reasoning.validate_notes(notes, p["evidence"])
        record["loadedModels"] = client.call("ps").get("models", [])
        rounds = []
        for attempt in range(2):
            items = reasoning.review_items(notes)
            scrutiny, cstats = {"assessments": []}, {}
            # Match evaluation granularity: each call reviews only one sentence.
            for item in items:
                result, timing = ask_recorded(
                    client,
                    model,
                    out,
                    "review-" + str(attempt) + "-" + item["id"],
                    reasoning.SYSTEM,
                    reasoning.REVIEW_TASK,
                    {"input": compact, "items": [item]},
                    reasoning.review_schema([item]),
                )
                reasoning.validate_assessments(result, [item])
                scrutiny["assessments"].extend(result["assessments"])
                cstats[item["id"]] = timing
            passed = reasoning.all_accepted(scrutiny, items)
            style_findings = reasoning.style_findings(items)
            rounds.append(
                {
                    "notes": notes,
                    "scrutiny": scrutiny,
                    "styleFindings": style_findings,
                    "draftRuntime": stats,
                    "reviewRuntime": cstats,
                }
            )
            if passed or attempt == 1:
                break
            notes, stats = ask_recorded(
                client,
                model,
                out,
                "revision",
                reasoning.SYSTEM,
                reasoning.DRAFT_TASK + " 문장별 지적을 검토하고 오류만 수정하라.",
                {
                    "input": compact,
                    "previousNotes": notes,
                    "scrutiny": scrutiny,
                    "styleFindings": style_findings,
                },
                schema,
            )
            notes = reasoning.attach_evidence(notes, p["evidence"])
            reasoning.validate_notes(notes, p["evidence"])
        record.update(
            notes=notes,
            scrutiny=scrutiny,
            reviewRounds=rounds,
            styleFindings=style_findings,
            draftRuntime=stats,
            reviewRuntime=cstats,
            status=(
                "revision_required"
                if not passed
                else (
                    "reviewed_draft"
                    if record["evaluation"]["passed"]
                    else "evaluation_required"
                )
            ),
        )
    except Exception as exc:
        record["error"] = type(exc).__name__ + ": " + str(exc)[:500]
    record["recordHash"] = digest(canonical(record))
    (out / "review.json").write_bytes(canonical(record))
    if archive_name == "coverage-reviews":
        attempt_pointer = out.parent / "last-attempt.json"
        pending = attempt_pointer.with_suffix(".tmp")
        pending.write_bytes(
            canonical(
                {
                    "file": str((out / "review.json").relative_to(ROOT)),
                    "hash": record["recordHash"],
                }
            )
        )
        pending.replace(attempt_pointer)
    if record["status"] != "failed":
        pointer = out.parent / "latest.json"
        temp = pointer.with_suffix(".tmp")
        temp.write_bytes(
            canonical(
                {
                    "file": str((out / "review.json").relative_to(ROOT)),
                    "hash": record["recordHash"],
                }
            )
        )
        temp.replace(pointer)
    return record


def read_reviews(snapshot, *, protocol=None, archive_name="local-reviews"):
    if archive_name not in ("local-reviews", "coverage-reviews"):
        raise ValueError("Unknown research-note archive")
    output = {}
    for c in snapshot["companies"]:
        if (protocol and c.get("status") != "ready") or (
            not protocol and not c.get("dossier")
        ):
            continue
        archive = ROOT / "data" / archive_name
        pointer = archive / c["id"] / "latest.json"
        if not pointer.exists() and archive_name == "coverage-reviews":
            pointer = archive / c["id"] / "last-attempt.json"
        if not pointer.exists():
            continue
        p = json.loads(pointer.read_text())
        path = (ROOT / p["file"]).resolve()
        if not path.is_relative_to(archive.resolve()):
            raise ValueError("Review pointer outside local archive")
        r = json.loads(path.read_text())
        body = {k: v for k, v in r.items() if k != "recordHash"}
        if digest(canonical(body)) != p["hash"] or r["recordHash"] != p["hash"]:
            raise ValueError("Local review integrity mismatch")
        if r["status"] == "failed":
            output[c["id"]] = {
                k: r[k] for k in ["status", "createdAt", "error", "recordHash"]
            }
            continue
        evidence_hash = (
            protocol.evidence_hash(c) if protocol else c["dossier"]["evidenceHash"]
        )
        if r["evidenceHash"] != evidence_hash:
            output[c["id"]] = {
                "status": "stale",
                "createdAt": r["createdAt"],
                "reason": "공시 근거가 바뀌어 이전 모델 해석을 보류합니다.",
            }
            continue
        if r.get("schemaVersion") == 2:
            from . import reasoning as default_reasoning
            from .model_evaluation import gate_for

            reasoning = protocol or default_reasoning
            evidence = (
                protocol.input_packet(c)["evidence"]
                if protocol
                else c["dossier"]["evidence"]
            )
            reasoning.validate_notes(r["notes"], evidence)
            reasoning.validate_assessments(
                r["scrutiny"], reasoning.review_items(r["notes"])
            )
            if (
                r["observations"] != reasoning.observations(c)
                or r["promptHash"] != reasoning.protocol_hash()
            ):
                output[c["id"]] = {
                    "status": "stale",
                    "createdAt": r["createdAt"],
                    "reason": "관측 또는 판독 프로토콜이 바뀌어 이전 해석을 보류합니다.",
                }
                continue
            # Display eligibility follows current evaluation without rewriting history.
            gate_options = (
                dict(
                    protocol=protocol,
                    suite_path=protocol.SUITE,
                    archive_name="coverage-evaluations",
                )
                if protocol
                else {}
            )
            r["currentEvaluation"] = gate_for(
                r["modelDigest"], r["inferenceConfig"], **gate_options
            )
            r["displayEligible"] = (
                r["status"] == "reviewed_draft" and r["currentEvaluation"]["passed"]
            )
        else:
            validate_draft(r["draft"], c["dossier"]["evidence"])
            validate_critic(r["critic"], len(r["draft"]["claims"]))
        output[c["id"]] = r
    return output
