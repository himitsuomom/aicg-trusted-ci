# AICG trusted CI

This public repository stores the trusted Buildkite dashboard YAML for `himitsuomom/ai-coding-governance-platform`. The mechanical `aicg-trusted-gate` check is active and required by protected `main` alongside GitHub Actions. It does not issue Semantic Verifier reports or receive model/signing secrets; the isolated authenticated verifier step is still pending.

## What the check means

The dashboard YAML validates the Buildkite checkout SHA, pins the target policy and dependency lockfiles by SHA-256, downloads only hash-locked binary dependencies, audits the runtime lock in a networked container that never receives PR source, and runs the target's configured checks in an isolated container with network disabled. The PR container receives no host environment, Buildkite credentials, GitHub credentials, Docker socket, or authenticated `.git` directory. It runs on an ephemeral Buildkite-hosted Linux agent, with CPU, memory, process, and time limits. Host-side artifact upload skips symlinks and refuses individual evidence files larger than 10 MB.

The check protects the pipeline definition and CI credentials from ordinary malicious PR code. The target's application, CLI, test suite, and evidence are still PR-controlled; a green run is not a trusted semantic review and cannot prove code benign. Do not describe this status as an independent Verifier report. This repository's policy opts out of a trusted reviewer identity.

## Buildkite setup

1. Connect the Buildkite organization to GitHub using the **Buildkite GitHub App with full access**, installed for only `himitsuomom/ai-coding-governance-platform`. Buildkite requires this app for hosted-agent checkout. Its repository permissions are metadata read; code read; checks, commit statuses, deployments, pull requests, and repository hooks read/write. It does not request repository-content write access. Review the GitHub installation page before accepting.
2. Create a pipeline named `aicg-trusted-gate` for the target repository and use a Buildkite-hosted Linux queue.
3. Paste the contents of [`pipeline.yml`](pipeline.yml) into Buildkite's dashboard **YAML Steps** editor. Do not select Pipeline Upload and do not read `.buildkite` from the target repository.
4. Enable pull request builds, including **Allow builds from third-party forked repositories**. Do not add Buildkite secrets, contexts, plugins, workflow-scoped tokens, or writable credentials to this pipeline.
5. Wait for a successful Buildkite check on a test PR. In the target repository's `main` branch protection, require the exact status from the Buildkite App as well as the existing GitHub Actions `gate`. Require the expected app source, not just a check name.

The current GitHub Actions `gate` remains PR-controlled. Until the Buildkite App check is required on protected `main`, this repository is not protected against an adversarial PR replacing its own Actions workflow.

## Cost and maintenance

As of 2026-09-28, Buildkite Free includes up to 2,000 Linux vCPU-minutes per month, up to 5 users and 10 concurrent jobs, with no card required to start; usage is quota-limited, not unlimited. Confirm current terms at [Buildkite pricing](https://buildkite.com/pricing/).

When `policy.yaml` or either lockfile changes, independently review the change and update the matching pinned SHA-256 in `pipeline.yml`, then update the Buildkite dashboard YAML from this repository. Keep this public trust repository's `main` branch protected from force pushes and deletion.

Official setup references: [Buildkite GitHub integration, permissions, and fork PRs](https://buildkite.com/docs/pipelines/source-control/github), [dashboard YAML Steps and Pipeline Upload](https://buildkite.com/docs/pipelines/configure/defining-steps), [hosted Linux agents and isolation](https://buildkite.com/docs/agent/buildkite-hosted/linux), [artifact symlink behavior](https://buildkite.com/docs/agent/cli/reference/artifact).
