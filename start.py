"""Local entry point: inspect, open, recalculate, collect, or run local inference."""

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import webbrowser

ROOT = Path(__file__).resolve().parent


def read(path):
    return json.loads(path.read_text()) if path.is_file() else None


def status():
    from equitylab.pipeline import load_latest
    from equitylab.local_ai import read_reviews
    from equitylab import coverage_reasoning, questions, filing_reading

    snapshot = load_latest()
    pointer = read(ROOT / "artifacts/local/last-verified-run.json")
    verified = None
    if pointer:
        path = ROOT / pointer["file"]
        if (
            path.is_file()
            and hashlib.sha256(path.read_bytes()).hexdigest() == pointer["sha256"]
        ):
            verified = read(path)
    current_code = all(
        (ROOT / p).is_file()
        and hashlib.sha256((ROOT / p).read_bytes()).hexdigest() == h
        for group in ["engineFiles", "renderFiles"]
        for p, h in snapshot[group].items()
    )
    reviews = read_reviews(
        snapshot, protocol=coverage_reasoning, archive_name="coverage-reviews"
    )
    ready = [c for c in snapshot["companies"] if c["status"] == "ready"]
    print(
        f"자료 기준 {snapshot['asOf']} · 연결 {len(ready)}/{len(snapshot['companies'])}개"
    )
    print(
        f"현재 분석 {snapshot['contentHash'][:12]} · 계산 이후 코드 {'일치' if current_code else '변경됨: 재계산 필요'}"
    )
    print(
        "현재 버전 전체 검증: "
        + (
            "통과"
            if current_code
            and verified
            and verified.get("snapshotHash") == snapshot["contentHash"]
            else "최신 버전의 검증 필요"
        )
    )
    states = {}
    for r in reviews.values():
        states[r["status"]] = states.get(r["status"], 0) + 1
    print("로컬 기업 판독: " + json.dumps(states, ensure_ascii=False))
    readings = filing_reading.read(snapshot)
    print("공시 본문 모델 판독:", len(readings), "개 (해석 의미 별도 검토)")
    selections = questions.read(snapshot)
    print(
        f"현재 근거의 로컬 조사 질문 선택: {sum(r['status'] == 'selected' for r in selections.values())}/{len(ready)}개 · 우선순위 효과 미검증"
    )
    print(
        "현재 검토용으로 펼쳐지는 초안 "
        + str(sum(bool(r.get("displayEligible")) for r in reviews.values()))
        + "개 · 추가 오류 지적 "
        + str(sum(len(r.get("editorialFindings", [])) for r in reviews.values()))
        + "문장 · 독립 금융 승인 없음"
    )
    runtime_present = (ROOT / ".local/ollama/bin/ollama").is_file()
    manifest_path = ROOT / ".local/models/manifests/registry.ollama.ai/library/qwen3/8b"
    manifest = read(manifest_path)
    model_present = bool(manifest) and all(
        (ROOT / ".local/models/blobs" / layer["digest"].replace(":", "-")).is_file()
        and (ROOT / ".local/models/blobs" / layer["digest"].replace(":", "-"))
        .stat()
        .st_size
        == layer["size"]
        for layer in [manifest["config"], *manifest["layers"]]
    )
    print(
        "새 모델 판독의 설치 파일: 런타임 "
        + ("있음" if runtime_present else "미반입")
        + " · 기본 Qwen3:8B "
        + ("있음" if model_present else "미반입")
        + " (저장된 보고서 열기는 모델 없이 가능)"
    )
    runs = sorted((ROOT / "artifacts/local/runs").glob("*/run.json"))
    if runs:
        last = read(runs[-1])
        print(f"최근 통합 실행: {last['status']} · {runs[-1].relative_to(ROOT)}")
        for stage in last.get("stages", []):
            if stage["status"] not in ["passed", "running"]:
                print(f"  {stage['name']}: {stage['status']} · {stage['log']}")
    print("열기: local.html · 보고서: app/index.html · PDF: artifacts/live/")
    print(
        "화면·저장 자료 계산은 인터넷 없이 사용합니다. 수집 명령만 공개자료 서버에 접속합니다."
    )
    return snapshot


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "action",
        nargs="?",
        choices=["status", "open", "offline", "collect", "research"],
        default="status",
    )
    p.add_argument("--as-of")
    p.add_argument(
        "--dart-env", help="Read DART_API_KEY only from an authorized local file"
    )
    args = p.parse_args()
    snapshot = status()
    if args.dart_env and args.action != "collect":
        p.error("--dart-env belongs only to collect")
    if args.action == "open":
        if not webbrowser.open((ROOT / "local.html").as_uri()):
            print("브라우저를 자동으로 열지 못했습니다. local.html을 직접 여세요.")
    elif args.action in ("offline", "research"):
        if not shutil.which("node"):
            raise SystemExit(
                "PDF·화면 검증에 Node.js가 필요합니다. 기존 화면은 local.html에서 열 수 있습니다."
            )
        command = [
            sys.executable,
            "scripts/run-local.py",
            "--as-of",
            args.as_of or snapshot["asOf"],
        ]
        command += ["--skip-model"] if args.action == "offline" else ["--evaluate"]
        raise SystemExit(subprocess.call(command, cwd=ROOT))
    elif args.action == "collect":
        as_of = (
            args.as_of
            or (datetime.now(timezone.utc).date() - timedelta(days=1)).isoformat()
        )
        command = [
            sys.executable,
            "-m",
            "equitylab",
            "refresh",
            "--as-of",
            as_of,
            "--online",
        ]
        if args.dart_env:
            command += ["--dart-env", args.dart_env]
        result = subprocess.call(command, cwd=ROOT)
        if result:
            raise SystemExit(result)
        result = subprocess.call(
            [sys.executable, "scripts/archive-xbrl.py", "--universe", "--as-of", as_of],
            cwd=ROOT,
        )
        if result:
            raise SystemExit(result)
        share_command = [sys.executable, "scripts/collect-shares.py"]
        if args.dart_env:
            share_command += ["--dart-env", args.dart_env]
        result = subprocess.call(share_command, cwd=ROOT)
        if result:
            raise SystemExit(result)
        narrative_command = [sys.executable, "scripts/collect-narratives.py"]
        if args.dart_env:
            narrative_command += ["--dart-env", args.dart_env]
        result = subprocess.call(narrative_command, cwd=ROOT)
        if result:
            raise SystemExit(result)
        result = subprocess.call(
            [sys.executable, "-m", "equitylab", "refresh", "--as-of", as_of], cwd=ROOT
        )
        if result:
            raise SystemExit(result)
        print(
            "공개자료·상세 원문 갱신·계산 완료. 로컬 판독·PDF 갱신을 이어서 실행하세요."
        )
        print("python3 start.py research")


if __name__ == "__main__":
    main()
