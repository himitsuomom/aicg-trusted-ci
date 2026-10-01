# AICG trusted CI

This public repository stores the trusted Buildkite dashboard YAML and isolated Semantic Verifier runner for `himitsuomom/ai-coding-governance-platform`. The mechanical `aicg-trusted-gate` check is active and required by protected `main` alongside GitHub Actions. The verifier runner is implemented, but remains disabled until the trusted queue, pinned verifier policy, and Buildkite secrets are provisioned.

## What the check means

The dashboard YAML validates the Buildkite checkout SHA, pins the target policy and dependency lockfiles by SHA-256, downloads only hash-locked binary dependencies, audits the runtime lock in a networked container that never receives PR source, and runs the target's configured checks in an isolated container with network disabled. The PR container receives no host environment, Buildkite credentials, GitHub credentials, Docker socket, or authenticated `.git` directory. It runs on an ephemeral Buildkite-hosted Linux agent, with CPU, memory, process, and time limits. Host-side artifact upload skips symlinks and refuses individual evidence files larger than 10 MB.

The mechanical step protects CI credentials from ordinary malicious PR code. The target's application, CLI, test suite, and evidence are still PR-controlled; a green mechanical run cannot prove code benign.

The separate Semantic Verifier step is conditional on the protected dashboard YAML value `AICG_VERIFIER_ENABLED=true` and uses the dedicated `aicg-verifier` queue. It exports PR files and prior-step evidence as data, fetches AICG code at a fixed commit, verifies the policy and lockfile hashes, builds the runtime before reading secrets, and never installs or imports code from the PR. Only then does it read `CLOUDFLARE_ACCOUNT_ID`, `CLOUDFLARE_API_TOKEN`, and `AICG_VERIFIER_PRIVATE_KEY` through `buildkite-agent secret get`. Configure each Buildkite secret's access policy with the verifier pipeline's first-party `pipeline_id` and the dedicated queue's first-party `cluster_queue_id`; the existing candidate-code queue must not be allowed to read them. Keep that queue restricted to the trusted verifier pipeline and free of untrusted hooks or plugins. Do not put secret values in YAML, environment settings, plugins, or uploaded artifacts.

The signed report binds the exact source, policy, run, verifier input, provider, and model. The trusted package imports the report and runs the final gate; any non-PASS decision, invalid signature, missing secret, provider error, or free-quota exhaustion fails the step. Candidate evidence remains untrusted input even after its hashes are checked. The reviewer can miss defects and does not prove code benign.

The status context reserved for this step is `buildkite/aicg-semantic-verifier/pr`. Keep it optional until the policy requires authenticated verification, the verifier queue and secret access policies are in place, and a live signed PASS has been observed. Then require this exact Buildkite-App status in addition to the existing checks on protected `main`.

## Buildkite setup

1. Connect the Buildkite organization to GitHub using the **Buildkite GitHub App with full access**, installed for only `himitsuomom/ai-coding-governance-platform`. Buildkite requires this app for hosted-agent checkout. Its repository permissions are metadata read; code read; checks, commit statuses, deployments, pull requests, and repository hooks read/write. It does not request repository-content write access. Review the GitHub installation page before accepting.
2. Create a pipeline named `aicg-trusted-gate` for the target repository and use a Buildkite-hosted Linux queue.
3. Paste the contents of [`pipeline.yml`](pipeline.yml) into Buildkite's dashboard **YAML Steps** editor. Do not select Pipeline Upload and do not read `.buildkite` from the target repository.
4. Enable pull request builds, including **Allow builds from third-party forked repositories**. The ordinary candidate-code step receives no Buildkite secrets, contexts, plugins, workflow-scoped tokens, or writable credentials.
5. Wait for a successful Buildkite check on a test PR. In the target repository's `main` branch protection, require the exact status from the Buildkite App as well as the existing GitHub Actions `gate`. Require the expected app source, not just a check name.

For Semantic Verifier activation, create the `aicg-verifier` queue in the same cluster, set its agent-access policy so only the trusted verifier pipeline runs there, and add the three secrets above with an access policy limited to that pipeline ID and queue ID. Add the public Ed25519 key, issuer, provider, and model to the target `policy.yaml`, set `independent_verification_required: true`, update the externally pinned policy SHA-256, and change the protected dashboard YAML's `AICG_VERIFIER_ENABLED` value from `false` to `true`. The first successful PR run must publish the verifier status before it is added as a required GitHub check. Keep the secret values out of chat and source control.

The current GitHub Actions `gate` remains PR-controlled. Until the Buildkite App check is required on protected `main`, this repository is not protected against an adversarial PR replacing its own Actions workflow.

## Cost and maintenance

As of 2026-10-01, the connected Buildkite organization is on a 26-day evaluation trial; this does not establish permanent Free-plan availability. Confirm the current terms at [Buildkite pricing](https://buildkite.com/pricing/). Cloudflare Workers AI Free has a recurring 10,000 Neurons/day allocation; Free requests fail after quota and the runner has no paid fallback. Confirm current terms at [Cloudflare pricing](https://developers.cloudflare.com/workers-ai/platform/pricing/).

When `policy.yaml` or either lockfile changes, independently review the change and update the matching pinned SHA-256 in `pipeline.yml`, then update the Buildkite dashboard YAML from this repository. Keep this public trust repository's `main` branch protected from force pushes and deletion.

Official setup references: [Buildkite GitHub integration, permissions, and fork PRs](https://buildkite.com/docs/pipelines/source-control/github), [dashboard YAML Steps and Pipeline Upload](https://buildkite.com/docs/pipelines/configure/defining-steps), [Buildkite Secrets and per-step use](https://buildkite.com/docs/pipelines/security/secrets/buildkite-secrets), [Buildkite Secrets access policies](https://buildkite.com/docs/pipelines/security/secrets/buildkite-secrets/access-policies), [secret risk considerations](https://buildkite.com/docs/pipelines/security/secrets/risk-considerations), [hosted Linux agents and isolation](https://buildkite.com/docs/agent/buildkite-hosted/linux), [artifact symlink behavior](https://buildkite.com/docs/agent/cli/reference/artifact).
