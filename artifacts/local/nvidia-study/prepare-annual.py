from pathlib import Path
import sys

root = Path(__file__).resolve().parents[3]
stage = Path(__file__).resolve().parent
script = root / "scripts/archive-sec-filing.py"
source = script.read_text().replace(
    "ROOT = Path(__file__).resolve().parents[1]", "ROOT = Path(" + repr(str(stage)) + ")"
)
sys.argv = [str(script), "--cik", "1045810", "--accession", "0001045810-26-000021", "--document", "nvda-20260125.htm"]
exec(compile(source, str(script), "exec"), {"__file__": str(script), "__name__": "__main__"})
