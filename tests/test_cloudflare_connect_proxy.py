"""The verifier's only network path is a fixed Cloudflare HTTPS destination."""

import unittest
from pathlib import Path

from scripts.cloudflare_connect_proxy import is_allowed_authority

ROOT = Path(__file__).resolve().parents[1]


class CloudflareConnectProxyTest(unittest.TestCase):
    def test_allows_only_the_exact_workers_ai_authority(self):
        self.assertTrue(is_allowed_authority("api.cloudflare.com:443"))

    def test_rejects_other_hosts_ports_and_authority_forms(self):
        for authority in (
            "example.com:443",
            "api.cloudflare.com:80",
            "api.cloudflare.com.evil.example:443",
            "api.cloudflare.com.:443",
            "API.CLOUDFLARE.COM:443",
            "user@api.cloudflare.com:443",
            "api.cloudflare.com:443/path",
            "1.1.1.1:443",
            "[2606:4700::1111]:443",
            "api.cloudflare.com",
        ):
            with self.subTest(authority=authority):
                self.assertFalse(is_allowed_authority(authority))

    def test_credential_bearing_runner_uses_only_the_internal_proxy_network(self):
        runner = (ROOT / "scripts" / "run-semantic-verifier.sh").read_text()
        credential_start = runner.index("verifier_status=0")
        credential_runner = runner[credential_start:]

        self.assertIn("docker network create --internal", runner)
        self.assertIn("docker network connect --alias aicg-cloudflare-proxy", runner)
        self.assertIn('--network "$verifier_network"', credential_runner)
        self.assertIn("--env HTTPS_PROXY=http://aicg-cloudflare-proxy:3128", credential_runner)
        self.assertNotIn('--network bridge', credential_runner)


if __name__ == "__main__":
    unittest.main()
