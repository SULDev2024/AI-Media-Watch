"""Local regression tests; fixture scores are synthetic test inputs, not research results."""
import csv
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import current_evaluation as evaluation


class EvaluationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        for folder in ("scam videos", "safe_videos", "REVISION/annotation"):
            (self.root / folder).mkdir(parents=True)
        (self.root / "scam videos/one.mp4").write_bytes(b"candidate fixture")
        (self.root / "safe_videos/two.mkv").write_bytes(b"other fixture")

    def labels(self, name, rows):
        with (self.root / "REVISION/annotation" / name).open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=["video", "file_name", "final_label", "sha256", "labelled_by"])
            writer.writeheader()
            writer.writerows(rows)

    def test_folders_are_not_ground_truth(self):
        rows = evaluation.inventory(self.root)
        self.assertEqual([r["label"] for r in rows], [None, None])
        predictions = {r["sha256"]: {"status": "ok", "score": 90} for r in rows}
        self.assertIsNone(evaluation.evaluate(rows, predictions)["metrics"])

    def test_explicit_labels_only_and_independence_is_separate(self):
        self.labels("author_labels.csv", [{"video": "one.mp4", "final_label": "scam"}])
        rows = evaluation.inventory(self.root)
        predictions = {r["sha256"]: {"status": "ok", "score": 70} for r in rows}
        self.assertEqual(evaluation.evaluate(rows, predictions)["n_evaluated"], 1)
        self.assertEqual(evaluation.evaluate(rows, predictions, independent_only=True)["n_evaluated"], 0)

    def test_uncertain_or_invalid_labels_never_become_safe(self):
        for label in ("unsure", "", "unknown", "provisional"):
            self.labels("author_labels.csv", [{"video": "one.mp4", "final_label": label}])
            self.assertIsNone(evaluation.inventory(self.root)[0]["label"])

    def test_uncertain_adjudication_overrides_author_label(self):
        self.labels("author_labels.csv", [{"video": "one.mp4", "final_label": "scam"}])
        self.labels("adjudicated_labels.csv", [{"video": "one.mp4", "final_label": "unsure"}])
        self.assertIsNone(evaluation.inventory(self.root)[0]["label"])

    def test_empty_adjudication_does_not_create_folder_labels(self):
        self.labels("adjudicated_labels.csv", [])
        self.assertTrue(all(r["label"] is None for r in evaluation.inventory(self.root)))

    def test_unicode_filename_alias_and_explicit_filename(self):
        (self.root / "scam videos/one.mp4").rename(self.root / "scam videos/Iran’s video.mp4")
        self.labels("author_labels.csv", [{"video": "Iran's video.mp4", "file_name": "Iran’s video.mp4", "final_label": "safe"}])
        self.assertEqual(evaluation.inventory(self.root)[0]["label"], 0)
        self.assertNotEqual(evaluation.name_key("Cutting $500.mp4"), evaluation.name_key("Cutting .mp4"))

    def test_conflicting_alias_is_rejected(self):
        self.labels("author_labels.csv", [{"video": "one.mp4", "final_label": "safe"}, {"video": "one.mp4", "final_label": "scam"}])
        with self.assertRaisesRegex(ValueError, "Ambiguous"):
            evaluation.inventory(self.root)

    def test_failed_and_invalid_predictions_are_not_scores(self):
        for record in (None, 50, {}, {"status": "error", "score": 50},
                       {"status": "ok", "score": 50, "flags": ["parse_error"]},
                       {"status": "ok", "score": True}, {"status": "ok", "score": float("nan")},
                       {"status": "ok", "score": 101}):
            self.assertIsNone(evaluation.valid_score(record))
        self.assertEqual(evaluation.valid_score({"status": "ok", "score": 0}), 0)
        self.assertEqual(evaluation.valid_score({"status": "ok", "score": 50}), 50)

    def test_missing_predictions_are_excluded(self):
        self.labels("author_labels.csv", [{"video": "one.mp4", "final_label": "scam"}])
        report = evaluation.evaluate(evaluation.inventory(self.root), {})
        self.assertEqual(report["n_evaluated"], 0)
        self.assertEqual(report["excluded"][0]["reason"], "missing_or_failed_prediction")

    def test_fixed_threshold_and_hash_binding(self):
        self.labels("author_labels.csv", [{"video": "one.mp4", "final_label": "scam"}])
        rows = evaluation.inventory(self.root)
        predictions = {rows[0]["sha256"]: {"status": "ok", "score": 40}}
        report = evaluation.evaluate(rows, predictions, 50)
        self.assertEqual(report["threshold"], 50)
        self.assertEqual(report["metrics"]["fn"], 1)
        (self.root / "scam videos/one.mp4").write_bytes(b"changed content")
        self.assertEqual(evaluation.evaluate(evaluation.inventory(self.root), predictions)["n_evaluated"], 0)

    def test_missing_or_empty_folder_is_an_error(self):
        (self.root / "scam videos/one.mp4").unlink()
        with self.assertRaisesRegex(ValueError, "no supported videos"):
            evaluation.inventory(self.root)
        (self.root / "scam videos").rmdir()
        with self.assertRaisesRegex(FileNotFoundError, "Required active dataset"):
            evaluation.inventory(self.root)

    def test_exact_duplicate_is_not_counted_twice(self):
        (self.root / "scam videos/copy.mp4").write_bytes(b"candidate fixture")
        self.labels("author_labels.csv", [{"video": "one.mp4", "final_label": "scam"}, {"video": "copy.mp4", "final_label": "scam"}])
        rows = evaluation.inventory(self.root)
        predictions = {r["sha256"]: {"status": "ok", "score": 70} for r in rows}
        self.assertEqual(evaluation.evaluate(rows, predictions)["n_evaluated"], 1)

    def test_cli_does_not_overwrite_existing_report(self):
        output = self.root / "report.json"
        output.write_text("preserve me", encoding="utf-8")
        with patch.object(evaluation, "inventory", return_value=[]):
            with self.assertRaises(SystemExit):
                evaluation.main(["--output", str(output)])
        self.assertEqual(output.read_text(encoding="utf-8"), "preserve me")

    def test_real_dataset(self):
        rows = evaluation.inventory()
        report = evaluation.summary(rows)
        self.assertEqual(report["folders"], {"scam videos": 34, "safe_videos": 13})
        self.assertEqual(report["human_labeled"], 47)
        self.assertEqual(report["independent_adjudicated"], 0)
        self.assertEqual(report["provisional_or_uncertain"], 0)
        self.assertEqual(len({r["sha256"] for r in rows}), 47)
        self.assertEqual(evaluation.evaluate(rows, {})["n_evaluated"], 0)

    def test_confirmed_current_labels_require_matching_content(self):
        path = self.root / "scam videos/one.mp4"
        current = self.root / "current_author_labels.csv"
        current.write_text("video,final_label,sha256,labelled_by\none.mp4,scam," + evaluation.sha256(path) + ",Project author\n", encoding="utf-8")
        self.assertEqual(evaluation.inventory(self.root)[0]["label"], 1)
        path.write_bytes(b"replacement video")
        with self.assertRaisesRegex(ValueError, "hash does not match"):
            evaluation.inventory(self.root)


if __name__ == "__main__":
    unittest.main()
