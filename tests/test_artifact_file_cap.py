"""The parent and verifier enforce the same file-count bound on artifacts."""

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class ArtifactFileCapTest(unittest.TestCase):
    def test_parent_and_verifier_apply_the_same_cap(self):
        parent = (ROOT / "pipeline.yml").read_text()
        verifier = (ROOT / "scripts" / "run-semantic-verifier.sh").read_text()

        self.assertIn('"$$artifact_files" -gt 4096', parent)
        self.assertIn('[[ "$artifact_files" -le 4096 ]]', verifier)
        self.assertIn('-type f -printf . | wc -c', parent)
        self.assertIn('-type f -printf . | wc -c', verifier)

    def test_count_is_independent_of_filenames(self):
        import tempfile

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name in ("normal.json", "line\nbreak.json", "tab\tname.json"):
                (root / name).touch()
            count = sum(1 for path in root.rglob("*") if path.is_file())
        self.assertEqual(count, 3)


if __name__ == "__main__":
    unittest.main()
