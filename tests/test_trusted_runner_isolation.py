"""The trusted AICG wrapper must not import candidate modules from its working directory."""

from pathlib import Path
import os
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
WRAPPER = ROOT / "scripts" / "run_trusted_aicg.py"
POLICY_CHECK = ROOT / "scripts" / "check_verifier_policy.py"
RUNNER = ROOT / "scripts" / "run-semantic-verifier.sh"
PIPELINE = ROOT / "pipeline.yml"


class TrustedRunnerIsolationTest(unittest.TestCase):
    def test_candidate_module_cannot_shadow_pinned_aicg_package(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            trusted_scripts = root / "trusted" / "scripts"
            trusted_package = root / "trusted" / "aicg" / "src" / "aicg"
            candidate = root / "candidate"
            trusted_scripts.mkdir(parents=True)
            trusted_package.mkdir(parents=True)
            candidate.mkdir()
            for wrapper in (WRAPPER, POLICY_CHECK):
                shutil.copyfile(wrapper, trusted_scripts / wrapper.name)

            trusted_marker = root / "trusted-imported"
            candidate_marker = root / "candidate-imported"
            (trusted_package / "__init__.py").write_text("")
            (trusted_package / "cli.py").write_text(
                "import os\nfrom pathlib import Path\n"
                "Path(os.environ['TRUSTED_MARKER']).write_text('trusted')\n"
                "def main(): pass\n"
            )
            (trusted_package / "policy.py").write_text(
                "import os\nfrom pathlib import Path\nfrom types import SimpleNamespace\n"
                "Path(os.environ['TRUSTED_MARKER']).write_text('trusted')\n"
                "def load_policy(root): return SimpleNamespace("
                "verifier=SimpleNamespace(configured=True, provider='cloudflare-workers-ai', "
                "model='@cf/google/gemma-4-26b-a4b-it'), "
                "completion=SimpleNamespace(independent_verification_required=True))\n"
            )
            (candidate / "aicg.py").write_text(
                "import os\nfrom pathlib import Path\n"
                "Path(os.environ['CANDIDATE_MARKER']).write_text('candidate')\n"
            )

            environment = os.environ.copy()
            environment["TRUSTED_MARKER"] = str(trusted_marker)
            environment["CANDIDATE_MARKER"] = str(candidate_marker)
            for wrapper in (WRAPPER, POLICY_CHECK):
                subprocess.run(
                    [sys.executable, "-I", str(trusted_scripts / wrapper.name)],
                    cwd=candidate,
                    env=environment,
                    check=True,
                )

            self.assertEqual(trusted_marker.read_text(), "trusted")
            self.assertFalse(candidate_marker.exists())

    def test_secret_access_follows_pinned_runtime_and_artifact_validation(self):
        runner = RUNNER.read_text()
        self.assertLess(runner.index("docker build --tag"), runner.index("buildkite-agent secret get"))
        self.assertLess(runner.index("run_trusted check_verifier_policy.py"), runner.index("buildkite-agent secret get"))
        self.assertLess(
            runner.index('find "$artifacts/.ai/evidence" "$artifacts/.ai/runs" -type l'),
            runner.index('cp -R "$artifacts/.ai/evidence/."'),
        )
        self.assertIn('repo="${BUILDKITE_REPO:-}"', runner)
        self.assertIn('readonly TRUSTED_AICG_COMMIT=', runner)
        self.assertNotIn("pip install .", runner)

        pipeline = PIPELINE.read_text()
        self.assertIn('AICG_VERIFIER_ENABLED: "false"', pipeline)
        self.assertIn('queue: aicg-verifier', pipeline)
        self.assertIn('depends_on: aicg-sandboxed-checks', pipeline)
        self.assertIn('context: buildkite/aicg-semantic-verifier/pr', pipeline)
        self.assertIn('build.pull_request.id != null && build.env("AICG_VERIFIER_ENABLED") == "true"', pipeline)


if __name__ == "__main__":
    unittest.main()
