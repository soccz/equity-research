"""Download a named public model into this project; never start inference or a service."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
import urllib.request

ROOT = Path(__file__).resolve().parents[1]


def sha(path):
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("model", choices=["qwen3:8b", "qwen3:14b", "qwen3.5:9b"])
    args = p.parse_args()
    family, tag = args.model.split(":")
    base = f"https://registry.ollama.ai/v2/library/{family}"
    opener = urllib.request.build_opener()
    with opener.open(base + "/manifests/" + tag, timeout=60) as response:
        blob = response.read(100_000)
    manifest = json.loads(blob)
    layers = [manifest["config"], *manifest["layers"]]
    root = ROOT / ".local/models"
    files = []
    for layer in layers:
        name = layer["digest"]
        if not re.fullmatch(r"sha256:[a-f0-9]{64}", name):
            raise ValueError("Invalid registry digest")
        dest = root / "blobs" / name.replace(":", "-")
        dest.parent.mkdir(parents=True, exist_ok=True)
        expected = name.removeprefix("sha256:")
        if not (
            dest.is_file()
            and dest.stat().st_size == layer["size"]
            and sha(dest) == expected
        ):
            part = dest.with_suffix(".partial")
            print(f"Downloading {name[:24]}… {layer['size']/1e9:.3f} GB", flush=True)
            subprocess.run(
                [
                    "curl",
                    "--fail",
                    "--location",
                    "--silent",
                    "--show-error",
                    "--retry",
                    "3",
                    "--connect-timeout",
                    "30",
                    "--max-time",
                    "3600",
                    "--continue-at",
                    "-",
                    base + "/blobs/" + name,
                    "--output",
                    str(part),
                ],
                check=True,
            )
            if part.stat().st_size != layer["size"] or sha(part) != expected:
                raise ValueError("Downloaded model size or SHA256 mismatch: " + name)
            part.replace(dest)
        print("Verified " + name[:24], flush=True)
        files.append(
            dict(file=str(dest.relative_to(ROOT)), sha256=expected, size=layer["size"])
        )
    dest = root / "manifests/registry.ollama.ai/library" / family / tag
    dest.parent.mkdir(parents=True, exist_ok=True)
    pending = dest.with_suffix(".tmp")
    pending.write_bytes(blob)
    pending.replace(dest)
    provenance = dict(
        model=args.model,
        registry=base,
        downloadedAt=datetime.now(timezone.utc).isoformat(),
        manifestHash=hashlib.sha256(blob).hexdigest(),
        files=files,
        scope="Public weights downloaded; no inference or remote AI request performed",
    )
    out = ROOT / "artifacts/local" / ("model-install-" + family + "-" + tag + ".json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(provenance, ensure_ascii=False, indent=2) + "\n")
    print("Project model installed: " + args.model, flush=True)


if __name__ == "__main__":
    main()
