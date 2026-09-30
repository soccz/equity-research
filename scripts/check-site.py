"""Verify the static artifact without a server or scientific Python dependencies."""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from equitylab.publication import verify_site

manifest = verify_site(ROOT / "site")
print(
    f"PASS static Pages artifact: {len(manifest['files'])} verified files; {manifest['analysisHash'][:12]}"
)
