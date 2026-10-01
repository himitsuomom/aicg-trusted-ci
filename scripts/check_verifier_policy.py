#!/usr/bin/env python3
"""Fail before secret retrieval unless the PR opts into a complete verifier gate."""

from pathlib import Path
import sys

TRUSTED_SOURCE = Path(__file__).resolve().parents[1] / "aicg" / "src"
sys.path.insert(0, str(TRUSTED_SOURCE))

from aicg.policy import load_policy  # noqa: E402


def main() -> int:
    policy = load_policy(Path.cwd())
    trust = policy.verifier
    if not policy.completion.independent_verification_required or not trust.configured:
        print("Semantic Verifier policy is not enabled with a complete trust identity", file=sys.stderr)
        return 2
    if trust.provider != "cloudflare-workers-ai" or trust.model != "@cf/google/gemma-4-26b-a4b-it":
        print("Semantic Verifier policy does not match the pinned provider and model", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
