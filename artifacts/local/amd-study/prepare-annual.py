from pathlib import Path
import sys

root = Path(__file__).resolve().parents[3]
stage = Path(__file__).resolve().parent
script = root / "scripts/archive-sec-filing.py"
source = script.read_text().replace(
    "ROOT = Path(__file__).resolve().parents[1]", "ROOT = Path(" + repr(str(stage)) + ")"
)
sys.argv = [str(script), "--cik", "2488", "--accession", "0000002488-26-000018", "--document", "amd-20251227.htm"]
exec(compile(source, str(script), "exec"), {"__file__": str(script), "__name__": "__main__"})
