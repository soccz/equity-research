"""The ratings page builder (scripts/build_ratings_page.py): what it derives from the
ledger and registration files, and the checks of the assembled Pages artifact."""

import importlib.util
import json
import shutil
import unittest
from unittest import mock

from equitylab.data import ROOT, digest
from ratings import registry, sectors
from ratings.rating import PREFER, PROTOCOL_HASH

import test_ratings_registry as fixtures

spec = importlib.util.spec_from_file_location(
    "build_ratings_page", ROOT / "scripts/build_ratings_page.py"
)
build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build)

GLOSSARY = json.loads((build.PAGE / "glossary.ko.json").read_text())


class Built(fixtures.Ledgered):
    """A temp ledger (fixtures.Ledgered), no evaluations and a fixed build commit."""

    def setUp(self):
        super().setUp()
        evaluations = self.root / "evaluation"
        for name, value in (
            ("EVALUATIONS", evaluations),
            ("commit", lambda: "c" * 40),
        ):
            patcher = mock.patch.object(build, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.evaluations = evaluations

    def assemble(self, name="out", preview=()):
        out = self.root / name
        build.assemble(ROOT / "site", out, list(preview))
        return out

    def read(self, out, relative):
        return json.loads((out / "ratings" / relative).read_text())

    def files(self, out):
        return {
            p.relative_to(out).as_posix(): p.read_bytes()
            for p in sorted(out.rglob("*"))
            if p.is_file()
        }


class DeriveTests(Built):
    def test_without_a_ledger_only_the_schedule_is_shown(self):
        index, months = build.derive([])
        self.assertEqual(index["status"], "ok")
        self.assertEqual((index["months"], months), ([], {}))
        self.assertEqual(index["gates"], dict(US=None, KR=None))
        self.assertEqual(index["ledger"], dict(head=None, events=0, registrations=0))
        self.assertEqual(index["protocol"]["hash"], PROTOCOL_HASH)
        self.assertEqual(index["schedule"]["gateAsOf"], fixtures.GATE_AS_OF)
        self.assertEqual(index["schedule"]["thresholds"], dict(US=0.9, KR=0.8))
        self.assertIsNone(index["evaluation"])
        self.assertFalse(index["preview"])

    def test_recorded_gates_are_shown_with_their_verdicts(self):
        self.gates(US="pass", KR="fail")
        index, _ = build.derive([])
        self.assertEqual(index["gates"]["US"]["verdict"], "pass")
        self.assertEqual(index["gates"]["US"]["rate"], 0.95)
        self.assertEqual(index["gates"]["KR"]["verdict"], "fail")
        self.assertEqual(index["gates"]["KR"]["threshold"], 0.8)
        self.assertEqual(index["ledger"]["events"], 2)

    def test_a_registration_is_a_month_tied_to_its_ledger_event(self):
        self.gates()
        path = self.register()
        index, months = build.derive([])
        (entry,) = index["months"]
        event = self.events()[0]
        self.assertEqual(entry["month"], "2026-10")
        self.assertFalse(entry["preview"])
        self.assertEqual(entry["data"], "data/2026-10.json")
        self.assertEqual(entry["fileSha256"], digest(path.read_bytes()))
        self.assertEqual(entry["fileSha256"], event["fileSha256"])
        self.assertEqual(entry["eventHash"], event["hash"])
        view = months["2026-10"]
        self.assertEqual(view["columns"], list(build.COLUMNS))
        self.assertEqual(view["ledger"]["sequence"], 2)  # after the two gates
        self.assertEqual(len(view["rows"]), 14)
        self.assertTrue(all(len(r) == len(build.COLUMNS) for r in view["rows"]))
        stored = {r["id"]: r for r in json.loads(path.read_text())["rows"]}
        for values in view["rows"]:
            row = dict(zip(build.COLUMNS, values))
            self.assertEqual(row["label"], stored[row["id"]]["label"])
            self.assertEqual(row["labelReason"], stored[row["id"]]["labelReason"])

    def test_an_altered_registration_shows_only_that_the_ledger_failed(self):
        self.gates()
        path = self.register()
        path.write_bytes(path.read_bytes().replace(b'"label"', b'"label" '))
        index, months = build.derive([])
        self.assertEqual(index["status"], "ledger_invalid")
        self.assertIn("does not match its ledger event", index["error"])
        self.assertEqual((index["months"], months), ([], {}))
        self.assertEqual(index["gates"], dict(US=None, KR=None))

    def test_a_broken_hash_chain_shows_only_that_the_ledger_failed(self):
        self.gates()
        lines = registry.LEDGER.read_text().splitlines()
        lines[0] = lines[0].replace('"pass"', '"fail"')
        registry.LEDGER.write_text("\n".join(lines) + "\n")
        index, _ = build.derive([])
        self.assertEqual(index["status"], "ledger_invalid")

    def test_previews_take_dry_runs_only(self):
        self.gates()
        dry = self.register(dry_run=True)
        index, months = build.derive([dry])
        self.assertTrue(index["preview"])
        self.assertEqual([m["month"] for m in index["months"]], ["2026-10-preview"])
        self.assertTrue(months["2026-10-preview"]["preview"])
        self.assertIsNone(months["2026-10-preview"]["ledger"]["eventHash"])
        real = self.register()
        with self.assertRaisesRegex(build.BuildError, "dry-run files only"):
            build.derive([real])

    def test_the_latest_evaluation_is_summarized_per_market(self):
        self.evaluations.mkdir()
        older = dict(through="2026-11-30", periods=[], summary={})
        period = dict(
            market="US",
            month="2026-10",
            status="complete",
            entry="2026-11-03",
            exit="2026-12-02",
            frozen=dict(period="2026-10"),
            flags=["stored_series"],
            errors=[],
            portfolios={PREFER: dict(netSectorExcess=0.0123456789)},
            spread=0.02,
            ic=0.051234,
        )
        newer = dict(
            through="2026-12-31",
            valuedThrough=dict(US="2026-12-31", KR="2026-12-30"),
            official=True,
            periods=[period],
            summary=dict(
                US=dict(complete=1, primary=dict(mean=0.0123, periods=1), other=1),
                KR=dict(complete=0, inProgress=1),
            ),
        )
        (self.evaluations / "2026-11-30.json").write_text(json.dumps(older))
        (self.evaluations / "2026-12-31.json").write_text(json.dumps(newer))
        index, _ = build.derive([])
        evaluation = index["evaluation"]
        self.assertEqual(evaluation["through"], "2026-12-31")
        self.assertEqual(evaluation["file"], "data/ratings/evaluation/2026-12-31.json")
        self.assertEqual(evaluation["valuedThrough"]["KR"], "2026-12-30")
        self.assertEqual(set(evaluation["summary"]), {"US", "KR"})
        self.assertEqual(evaluation["summary"]["US"]["complete"], 1)
        self.assertEqual(evaluation["summary"]["US"]["primary"]["periods"], 1)
        self.assertNotIn("other", evaluation["summary"]["US"])
        self.assertEqual(evaluation["summary"]["KR"]["inProgress"], 1)
        (shown,) = evaluation["periods"]
        self.assertEqual(shown["preferNetSectorExcess"], 0.012346)
        self.assertEqual((shown["status"], shown["frozen"]), ("complete", True))
        self.assertEqual(shown["flags"], ["stored_series"])

    def test_rows_are_ordered_by_market_then_percentile_with_unrated_last(self):
        rows = [
            dict(id="a", market="US", ticker="A", percentile=0.0),
            dict(id="b", market="US", ticker="B", percentile=None),
            dict(id="c", market="US", ticker="C", percentile=0.5),
            dict(id="d", market="KR", ticker="D", percentile=1.0),
        ]
        view = build.month_view(dict(rows=rows), None, preview=False)
        ids = [r[build.COLUMNS.index("id")] for r in view["rows"]]
        self.assertEqual(ids, ["d", "c", "a", "b"])


class AssembleTests(Built):
    def test_the_site_is_unchanged_and_the_build_is_deterministic(self):
        self.gates()
        self.register()
        first, second = self.assemble("one"), self.assemble("two")
        self.assertEqual(self.files(first), self.files(second))
        site = {
            p.relative_to(ROOT / "site").as_posix(): p.read_bytes()
            for p in (ROOT / "site").rglob("*")
            if p.is_file()
        }
        outside = {
            k: v for k, v in self.files(first).items() if not k.startswith("ratings/")
        }
        self.assertEqual(outside, site)
        manifest = self.read(first, "manifest.json")
        index = self.read(first, "data/index.json")
        self.assertEqual(manifest["contentDigest"], index["contentDigest"])
        self.assertEqual(index["commit"], "c" * 40)
        listed = set(manifest["files"])
        self.assertEqual(
            listed,
            {
                "index.html",
                "ratings.css",
                "ratings.js",
                "glossary.ko.json",
                "data/index.json",
                "data/2026-10.json",
            },
        )

    def test_the_content_digest_ignores_the_build_commit_only(self):
        self.gates()
        first = self.read(self.assemble("one"), "manifest.json")["contentDigest"]
        with mock.patch.object(build, "commit", lambda: "d" * 40):
            second = self.read(self.assemble("two"), "manifest.json")["contentDigest"]
        self.assertEqual(first, second)
        self.register()
        third = self.read(self.assemble("three"), "manifest.json")["contentDigest"]
        self.assertNotEqual(first, third)

    def page_with(self, name, old, new):
        """A copy of pages/ratings/ with one replacement in one file."""
        page = self.root / "page"
        shutil.copytree(build.PAGE, page)
        text = (page / name).read_text()
        self.assertIn(old, text)
        (page / name).write_text(text.replace(old, new, 1))
        patcher = mock.patch.object(build, "PAGE", page)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_a_backend_or_local_reference_fails_the_build(self):
        self.page_with("ratings.js", '"data/index.json"', '"http://localhost:8000/x"')
        with self.assertRaisesRegex(build.BuildError, "verify_site"):
            self.assemble()

    def test_a_broken_relative_link_fails_the_build(self):
        self.page_with("index.html", '"../app/index.html"', '"../app/missing.html"')
        with self.assertRaisesRegex(build.BuildError, "Broken publication link"):
            self.assemble()

    def test_a_root_relative_link_fails_the_build(self):
        self.page_with("index.html", 'href="ratings.css"', 'href="/ratings.css"')
        with self.assertRaisesRegex(build.BuildError, "Root-relative"):
            self.assemble()

    def test_files_outside_ratings_must_equal_the_site(self):
        out = self.assemble()
        (out / "app/extra.txt").write_text("x")
        with self.assertRaisesRegex(build.BuildError, "differs from site/"):
            build.check(ROOT / "site", out)

    def test_the_manifest_must_match_the_ratings_files(self):
        out = self.assemble()
        (out / "ratings/glossary.ko.json").write_text("{}\n")
        with self.assertRaisesRegex(build.BuildError, "glossary.ko.json"):
            build.check(ROOT / "site", out)

    def test_the_cli_reports_a_failed_check_and_exits_nonzero(self):
        self.page_with("ratings.js", '"data/index.json"', '"/mnt/20t/x"')
        with mock.patch("sys.stderr"):
            code = build.main(["--out", str(self.root / "out")])
        self.assertEqual(code, 1)


class GlossaryTests(unittest.TestCase):
    def test_every_issue_has_a_short_label_and_every_sector_a_name(self):
        codes = set(GLOSSARY["issues"]) | set(GLOSSARY["periods"])
        codes -= {"pending", "in_progress", "complete", "frozen"}
        self.assertEqual(codes - set(GLOSSARY["issueShort"]), set())
        self.assertEqual(set(GLOSSARY["issueInfo"]) - codes, set())
        self.assertEqual(set(GLOSSARY["sectors"]), set(sectors.FF12))

    def test_issue_codes_in_the_dry_runs_are_explained(self):
        seen = set()
        for path in sorted((ROOT / "data/ratings/dry-run").glob("*.json")):
            for row in json.loads(path.read_text()).get("rows") or []:
                seen.update(row.get("issues") or [])
        self.assertEqual(seen - set(GLOSSARY["issues"]), set())

    def test_the_page_loads_its_own_files(self):
        html = (build.PAGE / "index.html").read_text()
        self.assertIn('href="ratings.css"', html)
        self.assertIn('src="ratings.js"', html)
        script = (build.PAGE / "ratings.js").read_text()
        self.assertIn('"data/index.json"', script)
        self.assertIn('"glossary.ko.json"', script)


if __name__ == "__main__":
    unittest.main()
