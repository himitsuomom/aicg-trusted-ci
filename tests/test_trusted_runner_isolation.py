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
PARENT_PIPELINE = ROOT / "pipeline.yml"
VERIFIER_PIPELINE = ROOT / "verifier-pipeline.yml"


class TrustedRunnerIsolationTest(unittest.TestCase):
    def test_runner_rejects_direct_execution_before_buildkite_work(self):
        environment = os.environ.copy()
        for name in (
            "BUILDKITE_PIPELINE_SLUG",
            "BUILDKITE_TRIGGERED_FROM_BUILD_PIPELINE_SLUG",
            "BUILDKITE_TRIGGERED_FROM_BUILD_ID",
        ):
            environment.pop(name, None)

        result = subprocess.run(
            ["bash", str(RUNNER)],
            cwd=ROOT,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 1)
        self.assertIn("Semantic Verifier must run in its dedicated pipeline", result.stderr)

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
        self.assertIn("du --apparent-size --count-links -sk", runner)
        self.assertLess(runner.index("docker build --tag"), runner.index("buildkite-agent secret get"))
        self.assertLess(runner.index("run_trusted check_verifier_policy.py"), runner.index("buildkite-agent secret get"))
        self.assertLess(
            runner.index('find "$artifacts/.ai/evidence" "$artifacts/.ai/runs" -type l'),
            runner.index('cp -R "$artifacts/.ai/evidence/."'),
        )
        self.assertIn('repo="${BUILDKITE_REPO:-}"', runner)
        self.assertIn('readonly TRUSTED_AICG_COMMIT=', runner)
        self.assertNotIn("pip install .", runner)
        self.assertIn('BUILDKITE_PIPELINE_SLUG:-}', runner)
        self.assertIn('BUILDKITE_TRIGGERED_FROM_BUILD_PIPELINE_SLUG:-}', runner)
        self.assertIn('refs/pull/${AICG_PARENT_PULL_REQUEST}/head', runner)
        self.assertIn('--build "$BUILDKITE_TRIGGERED_FROM_BUILD_ID" --step aicg-sandboxed-checks', runner)

        parent = PARENT_PIPELINE.read_text()
        self.assertIn('AICG_VERIFIER_ENABLED: "false"', parent)
        self.assertIn('queue: linux-small', parent)
        self.assertIn('trigger: aicg-semantic-verifier', parent)
        self.assertIn('depends_on: aicg-sandboxed-checks', parent)
        self.assertIn('build.pull_request.id != null && build.env("AICG_VERIFIER_ENABLED") == "true"', parent)
        self.assertNotIn("buildkite-agent secret get", parent)

        verifier = VERIFIER_PIPELINE.read_text()
        self.assertIn('checkout:\n  skip: true', verifier)
        self.assertIn('queue: linux-small', verifier)
        self.assertIn('build.source == "trigger_job"', verifier)
        self.assertIn('BUILDKITE_TRIGGERED_FROM_BUILD_PIPELINE_SLUG', verifier)
        self.assertIn('context: buildkite/aicg-semantic-verifier/pr', verifier)
        self.assertRegex(verifier, r'trusted_commit="[0-9a-f]{40}"')

    def test_artifact_cap_counts_sparse_file_contents(self):
        parent = PARENT_PIPELINE.read_text()
        runner = RUNNER.read_text()
        self.assertIn("du --apparent-size --count-links -sk", parent)
        self.assertIn("du --apparent-size --count-links -sk", runner)
        self.assertIn('if [ "$$artifact_kb" -gt 51200 ]', parent)
        self.assertIn('[[ "$artifact_kb" -le 51200 ]]', runner)

        with tempfile.TemporaryDirectory() as temporary:
            roots = [Path(temporary) / "evidence", Path(temporary) / "runs"]
            for root in roots:
                root.mkdir()
            for index in range(6):
                sparse_file = roots[index % len(roots)] / f"evidence-{index}.json"
                sparse_file.touch()
                with sparse_file.open("r+b") as stream:
                    stream.truncate(9 * 1024 * 1024)

            files = [path for root in roots for path in root.iterdir()]
            self.assertGreater(sum(path.stat().st_size for path in files), 50 * 1024 * 1024)
            self.assertLessEqual(max(path.stat().st_size for path in files), 10 * 1024 * 1024)

            allocated = sum(getattr(path.stat(), "st_blocks", 0) * 512 for path in files)
            if allocated >= 50 * 1024 * 1024:
                self.skipTest("filesystem does not preserve sparse-file allocation")

            result = subprocess.run(
                ["du", "--apparent-size", "-sk", *(str(root) for root in roots)],
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode != 0:
                self.skipTest("du does not support GNU --apparent-size on this host")
            apparent_kib = sum(int(line.split()[0]) for line in result.stdout.splitlines())
            self.assertGreater(apparent_kib, 51200)

    def test_artifact_cap_counts_hardlink_paths(self):
        with tempfile.TemporaryDirectory() as temporary:
            roots = [Path(temporary) / "evidence", Path(temporary) / "runs"]
            for root in roots:
                root.mkdir()
            source = roots[0] / "source.json"
            with source.open("wb") as stream:
                stream.truncate(9 * 1024 * 1024)
            for index in range(6):
                os.link(source, roots[index % len(roots)] / f"copy-{index}.json")

            common = ["du", "--apparent-size", "-sk", *(str(root) for root in roots)]
            counted = subprocess.run(
                ["du", "--apparent-size", "--count-links", "-sk", *(str(root) for root in roots)],
                capture_output=True,
                text=True,
                check=False,
            )
            if counted.returncode != 0:
                self.skipTest("du does not support GNU --count-links on this host")
            deduplicated = subprocess.run(
                common,
                capture_output=True,
                text=True,
                check=True,
            )
            deduplicated_kib = sum(int(line.split()[0]) for line in deduplicated.stdout.splitlines())
            counted_kib = sum(int(line.split()[0]) for line in counted.stdout.splitlines())
            self.assertLessEqual(deduplicated_kib, 51200)
            self.assertGreater(counted_kib, 51200)


if __name__ == "__main__":
    unittest.main()
