import copy
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest
from equitylab import forward_study as study, pipeline
from equitylab.data import ROOT


class ForwardStudyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.snapshot = pipeline.load_latest()

    def test_frozen_selection_is_idempotent_and_future_only(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "data/cache/tmp") as tmp:
            path = Path(tmp) / "protocol.json"
            p = study.freeze(
                self.snapshot, path, datetime(2026, 9, 30, 12, tzinfo=timezone.utc)
            )
            again = study.freeze({"bad": "later inputs"}, path)
            self.assertEqual(p, again)
            self.assertEqual(
                sum(len(c["members"]) for c in p["markets"].values()),
                len(self.snapshot["companies"]),
            )
            for r in study.evaluate(p, self.snapshot)["results"]:
                self.assertEqual(r["status"], "pending")
            path.write_text(path.read_text().replace("0.001", "0.002"))
            with self.assertRaises(ValueError):
                study.read(path)

    def test_expanded_coverage_never_reselects_the_original_forty(self):
        original = study.PATH.read_bytes()
        contract = study.read()
        self.assertEqual(
            contract["protocolHash"],
            "14e3d1c9bb52979ddb7e4cd048a9742c040df5a7727042a402e2e582ca981f30",
        )
        self.assertEqual(
            sum(len(c["members"]) for c in contract["markets"].values()), 40
        )
        with tempfile.TemporaryDirectory(dir=ROOT / "data/cache/tmp") as tmp:
            path = Path(tmp) / "frozen.json"
            path.write_bytes(original)
            self.assertEqual(study.freeze(self.snapshot, path), contract)
            self.assertEqual(path.read_bytes(), original)
        self.assertEqual(study.PATH.read_bytes(), original)

    def test_known_future_window_cost_ablation_and_missing_member(self):
        contract = dict(
            markets={
                "US": dict(
                    registrationDay="2026-09-30",
                    calendarCompany="A",
                    members=["A", "B"],
                    selection=dict(
                        equal_weight=["A", "B"],
                        cash_conditions=["A"],
                        without_growth=[],
                        momentum63_top5=["B"],
                    ),
                )
            },
            horizons=[2],
            oneWayCost=0.001,
        )
        dates = ["2026-09-30", "2026-10-01", "2026-10-02", "2026-10-05"]
        companies = [
            dict(
                id=id,
                prices=[dict(date=d, adjustedClose=v) for d, v in zip(dates, values)],
                sources=[],
            )
            for id, values in [("A", [1, 100, 105, 110]), ("B", [1, 200, 200, 190])]
        ]
        s = dict(asOf="2026-10-05", contentHash="test", companies=companies)
        r = study.evaluate(contract, s)["results"][0]
        self.assertEqual((r["entry"], r["end"]), ("2026-10-01", "2026-10-05"))
        self.assertAlmostEqual(r["policies"]["equal_weight"]["net"], 0.023)
        self.assertAlmostEqual(
            r["policies"]["cash_conditions"]["differenceFromBaseline"], 0.075
        )
        self.assertEqual(r["policies"]["without_growth"]["net"], 0)
        self.assertEqual(r["policies"]["oracle_upper_bound"]["selected"], ["A"])
        negative = copy.deepcopy(s)
        negative["companies"][0]["prices"][-1]["adjustedClose"] = 90
        upper = study.evaluate(contract, negative)["results"][0]["policies"][
            "oracle_upper_bound"
        ]
        self.assertEqual(upper["selected"], [])
        self.assertEqual(upper["net"], 0)
        s["companies"][1]["prices"].pop()
        self.assertEqual(
            study.evaluate(contract, s)["results"][0]["status"], "unresolved"
        )
        self.assertEqual(
            study.evaluate(contract, {**s, "asOf": "2026-10-02"})["results"][0][
                "status"
            ],
            "pending",
        )
        missing_calendar = study.evaluate(
            contract, {**s, "companies": s["companies"][1:]}
        )["results"][0]
        self.assertEqual(missing_calendar["status"], "unresolved")
        self.assertEqual(missing_calendar["missing"], ["A"])
