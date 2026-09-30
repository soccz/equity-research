import json
from pathlib import Path
import tempfile
import unittest
from equitylab import data, publication


class PublicationTests(unittest.TestCase):
    def test_public_projection_removes_workstation_paths_without_changing_analysis(
        self,
    ):
        payload = dict(
            snapshot=dict(
                contentHash="a" * 64,
                engineFiles={"private": "hash"},
                inputFiles={},
                renderFiles={},
                companies=[
                    dict(
                        prices=list(range(300)),
                        sources=[
                            dict(
                                file="/private/source",
                                url="https://example.com",
                                sha256="hash",
                            )
                        ],
                        financials=dict(
                            sourceFile="/private/input", originalPath="/private/archive"
                        ),
                    )
                ],
            ),
            ledger=[],
        )
        result = publication.public_payload(payload)
        self.assertNotIn("/private", json.dumps(result))
        self.assertEqual(len(result["snapshot"]["companies"][0]["prices"]), 253)
        self.assertEqual(len(payload["snapshot"]["companies"][0]["prices"]), 300)
        self.assertEqual(
            result["publication"]["analysisHash"], payload["snapshot"]["contentHash"]
        )
        self.assertIn("engineFiles", payload["snapshot"])

    def site(self, root, body):
        (root / "index.html").write_text(body)
        manifest = dict(files={"index.html": data.digest(body.encode())})
        (root / "site-manifest.json").write_text(json.dumps(manifest))

    def test_static_artifact_detects_changed_and_unlisted_files(self):
        with tempfile.TemporaryDirectory(dir=data.work_temp()) as tmp:
            root = Path(tmp)
            self.site(root, "<p>Reviewed analysis</p>")
            publication.verify_site(root)
            (root / "index.html").write_text("changed")
            with self.assertRaisesRegex(ValueError, "hash mismatch"):
                publication.verify_site(root)
            self.site(root, "<p>Reviewed analysis</p>")
            (root / "private.env").write_text("not part of the publication")
            with self.assertRaisesRegex(ValueError, "Unlisted"):
                publication.verify_site(root)

    def test_static_artifact_rejects_backend_dependency_and_missing_asset(self):
        with tempfile.TemporaryDirectory(dir=data.work_temp()) as tmp:
            root = Path(tmp)
            self.site(root, '<script>fetch("/api/refresh")</script>')
            with self.assertRaisesRegex(ValueError, "Backend"):
                publication.verify_site(root)
            self.site(root, '<img src="missing.svg">')
            with self.assertRaisesRegex(ValueError, "Broken publication link"):
                publication.verify_site(root)

    def test_static_artifact_rejects_symlink_to_workspace(self):
        with tempfile.TemporaryDirectory(dir=data.work_temp()) as tmp:
            root = Path(tmp)
            self.site(root, "<p>Reviewed</p>")
            (root / "external.html").symlink_to(data.ROOT / "app/index.html")
            manifest = json.loads((root / "site-manifest.json").read_text())
            manifest["files"]["external.html"] = data.digest(
                (root / "external.html").read_bytes()
            )
            (root / "site-manifest.json").write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, "external workspace"):
                publication.verify_site(root)

    def test_clean_runner_storage_does_not_reset_existing_history(self):
        with tempfile.TemporaryDirectory(dir=data.work_temp()) as tmp:
            root = Path(tmp)
            data.ensure_storage(root)
            manifest = root / "data/dart-imports.json"
            manifest.write_text('[{"preserved": true}]')
            data.ensure_storage(root)
            self.assertEqual(json.loads(manifest.read_text()), [{"preserved": True}])
