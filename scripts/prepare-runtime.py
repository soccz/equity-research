"""Bundle the installed Linux runtime and Qwen3:8B for private offline transfer."""

from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import platform
import tarfile

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def main():
    if platform.system() != "Linux" or platform.machine() != "x86_64":
        raise SystemExit("This installed runtime bundle is for Linux x86_64 only")
    runtime = ROOT / ".local/ollama"
    model = ROOT / ".local/models"
    manifest_path = model / "manifests/registry.ollama.ai/library/qwen3/8b"
    manifest = json.loads(manifest_path.read_text())
    selected = [manifest_path]
    for layer in [manifest["config"], *manifest["layers"]]:
        algorithm, expected = layer["digest"].split(":", 1)
        if algorithm != "sha256" or len(expected) != 64:
            raise ValueError("Unexpected model digest")
        path = model / "blobs" / ("sha256-" + expected)
        if path.is_symlink() or path.stat().st_size != layer["size"]:
            raise ValueError("Unexpected model file: " + str(path.relative_to(ROOT)))
        if digest(path) != expected:
            raise ValueError("Model digest mismatch: " + str(path.relative_to(ROOT)))
        selected.append(path)
    if not (runtime / "bin/ollama").is_file():
        raise ValueError("Project runtime is missing")
    selected.extend(p for p in runtime.rglob("*") if p.is_file() or p.is_symlink())
    selected = sorted(set(selected))
    record = dict(
        createdAt=datetime.now(timezone.utc).isoformat(),
        platform="Linux x86_64",
        model="qwen3:8b",
        private=True,
        files={},
        scope="Project Ollama runtime and exact Qwen3:8B layers, including its license. No other models, keys, logs or external services.",
        prerequisites="Compatible Linux x86_64, NVIDIA driver, Python 3.12 and the separate research bundle. Chrome/Node/fonts are needed for full PDF/browser verification.",
    )
    for path in selected:
        relative = str(path.relative_to(ROOT))
        if path.is_symlink():
            target = path.readlink()
            if target.is_absolute() or not path.resolve().is_relative_to(runtime):
                raise ValueError("Runtime link leaves its directory: " + relative)
            record["files"][relative] = dict(link=str(target))
        else:
            record["files"][relative] = dict(
                size=path.stat().st_size, sha256=digest(path)
            )
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    out = ROOT / "artifacts/packages" / f"equity-gpu-linux-x86_64-{stamp}.tar"
    out.parent.mkdir(parents=True, exist_ok=True)
    blob = (json.dumps(record, ensure_ascii=False, indent=2) + "\n").encode()
    with tarfile.open(out, "x") as archive:
        for path in selected:
            archive.add(path, arcname=str(path.relative_to(ROOT)), recursive=False)
        info = tarfile.TarInfo("GPU-BUNDLE-MANIFEST.json")
        info.size = len(blob)
        archive.addfile(info, io.BytesIO(blob))
    with tarfile.open(out, "r") as archive:
        for name, expected in record["files"].items():
            member = archive.getmember(name)
            if "link" in expected:
                if not member.issym() or member.linkname != expected["link"]:
                    raise ValueError("Archived runtime link mismatch: " + name)
            else:
                with archive.extractfile(member) as handle:
                    if (
                        hashlib.file_digest(handle, "sha256").hexdigest()
                        != expected["sha256"]
                    ):
                        raise ValueError("Archived file digest mismatch: " + name)
        if json.load(archive.extractfile("GPU-BUNDLE-MANIFEST.json")) != record:
            raise ValueError("Archived manifest mismatch")
    result = dict(
        status="verified_private_runtime_archive",
        file=str(out.relative_to(ROOT)),
        size=out.stat().st_size,
        sha256=digest(out),
        files=len(record["files"]),
        model=record["model"],
        platform=record["platform"],
        verification="Model layer digests and every archived file/link verified by reading the archive; platform prerequisites remain required.",
    )
    out.with_suffix(".json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
