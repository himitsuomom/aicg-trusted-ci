#!/usr/bin/env bash
set -euo pipefail
set +x
export GIT_CONFIG_NOSYSTEM=1 GIT_CONFIG_GLOBAL=/dev/null GIT_TERMINAL_PROMPT=0

readonly TARGET_REPO="himitsuomom/ai-coding-governance-platform"
readonly TRUSTED_AICG_COMMIT="8d4adcb271764814950af7be0027a6b1bbc438cc"
readonly PYTHON_IMAGE="python:3.12-slim@sha256:2f17fc044b579bab302c2e8054d3a686e2cb9a83de48e70534b94cd8ebbe06a9"
readonly POLICY_SHA256="463cd464924945f6aee922c434c131d3f92d6eb5a147be8f425c35048b479fa9"
readonly REQUIREMENTS_SHA256="4036f3896dc8b37f9ef1cb7023c393cf01cc243e3b6bce675641e850b3d3e8d1"

die() {
  printf '%s\n' "$1" >&2
  exit 1
}

[[ "${BUILDKITE_PIPELINE_SLUG:-}" == "aicg-semantic-verifier" ]] \
  || die "Semantic Verifier must run in its dedicated pipeline"
[[ "${BUILDKITE_TRIGGERED_FROM_BUILD_PIPELINE_SLUG:-}" == "aicg-trusted-gate" ]] \
  || die "Semantic Verifier must be triggered by the trusted mechanical pipeline"
[[ "${BUILDKITE_TRIGGERED_FROM_BUILD_ID:-}" =~ ^[a-f0-9-]{36}$ ]] \
  || die "Semantic Verifier requires a parent Buildkite build"
[[ "${AICG_VERIFIER_ENABLED:-false}" == "true" ]] || die "AICG_VERIFIER_ENABLED must be true"
[[ "${AICG_PARENT_PULL_REQUEST:-}" =~ ^[1-9][0-9]*$ ]] \
  || die "Semantic Verifier only runs for pull requests"
[[ "${AICG_PARENT_PR_BASE_BRANCH:-}" == "main" ]] \
  || die "Semantic Verifier only accepts pull requests targeting main"

repo="${BUILDKITE_REPO:-}"
repo="${repo#git://github.com/}"
repo="${repo#https://github.com/}"
repo="${repo#http://github.com/}"
repo="${repo#ssh://git@github.com/}"
repo="${repo#git@github.com:}"
repo="${repo%.git}"
[[ "$repo" == "$TARGET_REPO" ]] || die "Semantic Verifier rejected an unexpected Buildkite pipeline repository"

source_commit="${BUILDKITE_COMMIT:?missing BUILDKITE_COMMIT}"
[[ "$source_commit" =~ ^[a-f0-9]{40}$ ]] || die "invalid Buildkite source commit"

tmp="$(mktemp -d "${TMPDIR:-/tmp}/aicg-verifier.XXXXXX")"
image="aicg-semantic:${BUILDKITE_BUILD_ID:-local}"
trap 'docker image rm -f "$image" >/dev/null 2>&1 || true; rm -rf "$tmp"' EXIT

source_git="$tmp/source-git"
mkdir -p "$source_git"
GIT_CONFIG_NOSYSTEM=1 GIT_CONFIG_GLOBAL=/dev/null git -C "$source_git" init -q
git -C "$source_git" remote add origin "https://github.com/${TARGET_REPO}.git"
GIT_CONFIG_NOSYSTEM=1 GIT_CONFIG_GLOBAL=/dev/null GIT_TERMINAL_PROMPT=0 \
  git -C "$source_git" -c credential.helper= -c core.askPass=/bin/false \
  fetch --no-tags --depth=1 origin \
  "refs/pull/${AICG_PARENT_PULL_REQUEST}/head:refs/remotes/origin/aicg-pr"
[[ "$(git -C "$source_git" rev-parse refs/remotes/origin/aicg-pr)" == "$source_commit" ]] \
  || die "pull request head changed after the parent mechanical build"

check_pinned_file() {
  local path="$1" expected="$2" mode actual
  mode="$(git -C "$source_git" ls-tree "$source_commit" -- "$path" | awk 'NF {print $1}')"
  [[ "$mode" == "100644" ]] || die "unexpected file mode for $path"
  actual="$(git -C "$source_git" show "$source_commit:$path" | sha256sum | cut -d' ' -f1)"
  [[ "$actual" == "$expected" ]] || die "protected SHA-256 mismatch for $path"
}

check_pinned_file policy.yaml "$POLICY_SHA256"
check_pinned_file requirements.lock "$REQUIREMENTS_SHA256"

candidate="$tmp/candidate"
artifacts="$tmp/artifacts"
trusted_git="$tmp/trusted-git"
trusted_app="$tmp/trusted-app"
image_context="$tmp/image-context"
mkdir -p "$candidate" "$artifacts" "$trusted_git" "$trusted_app" \
  "$image_context/trusted/aicg/src" "$image_context/trusted/scripts"

# Copy the pinned PR commit as inert data; the child pipeline skipped checkout so repository hooks never ran.
GIT_CONFIG_NOSYSTEM=1 GIT_CONFIG_GLOBAL=/dev/null \
  git -C "$source_git" -c filter.lfs.process= -c filter.lfs.smudge= -c filter.lfs.clean= \
  archive --format=tar "$source_commit" | tar -xf - -C "$candidate"
[[ ! -L "$candidate/.ai" && ( ! -e "$candidate/.ai" || -d "$candidate/.ai" ) ]] \
  || die "source snapshot has an unsafe .ai path"
mkdir -p "$candidate/.ai"
for path in "$candidate/.ai/evidence" "$candidate/.ai/runs"; do
  [[ ! -e "$path" && ! -L "$path" ]] || die "source snapshot contains a generated evidence path"
done
mkdir -p "$candidate/.ai/evidence" "$candidate/.ai/runs"
GIT_CONFIG_NOSYSTEM=1 GIT_CONFIG_GLOBAL=/dev/null \
  git -C "$candidate" -c core.hooksPath=/dev/null init -q
git -C "$candidate" config user.name "AICG trusted verifier"
git -C "$candidate" config user.email "aicg-verifier@invalid"
git -C "$candidate" -c core.hooksPath=/dev/null add --all --force
git -C "$candidate" -c core.hooksPath=/dev/null commit -q -m "isolated PR data snapshot"

# Download artifacts into a separate directory so PR-controlled symlinks cannot redirect writes.
(
  cd "$artifacts"
  buildkite-agent artifact download ".ai/evidence/**/*" . \
    --build "$BUILDKITE_TRIGGERED_FROM_BUILD_ID" --step aicg-sandboxed-checks
  buildkite-agent artifact download ".ai/runs/**/*" . \
    --build "$BUILDKITE_TRIGGERED_FROM_BUILD_ID" --step aicg-sandboxed-checks
)
[[ -d "$artifacts/.ai/evidence" && ! -L "$artifacts/.ai/evidence" ]] || die "missing or symlinked evidence directory"
[[ -d "$artifacts/.ai/runs" && ! -L "$artifacts/.ai/runs" ]] || die "missing or symlinked run directory"
[[ -f "$artifacts/.ai/evidence/current.json" && ! -L "$artifacts/.ai/evidence/current.json" ]] \
  || die "missing or symlinked current evidence binding"
find "$artifacts/.ai/evidence" "$artifacts/.ai/runs" -type l -print -quit | grep -q . \
  && die "symlinked evidence artifacts are not allowed"
find "$artifacts/.ai/runs" -type f -name summary.json -print -quit | grep -q . \
  || die "missing run summary artifact"
artifact_kb="$(du --apparent-size --count-links -sk "$artifacts/.ai/evidence" "$artifacts/.ai/runs" | awk '{total += $1} END {print total + 0}')"
[[ "$artifact_kb" -le 51200 ]] || die "evidence artifacts exceed the 50 MiB limit"
find "$artifacts/.ai/evidence" "$artifacts/.ai/runs" -type f -size +10M -print -quit | grep -q . \
  && die "evidence artifact exceeds the 10 MiB per-file limit"
cp -R "$artifacts/.ai/evidence/." "$candidate/.ai/evidence/"
cp -R "$artifacts/.ai/runs/." "$candidate/.ai/runs/"

# Fetch application code at a protected immutable commit; never install or import the PR package.
GIT_CONFIG_NOSYSTEM=1 GIT_CONFIG_GLOBAL=/dev/null git -C "$trusted_git" init -q
git -C "$trusted_git" remote add origin "https://github.com/${TARGET_REPO}.git"
GIT_CONFIG_NOSYSTEM=1 GIT_CONFIG_GLOBAL=/dev/null GIT_TERMINAL_PROMPT=0 \
  git -C "$trusted_git" -c credential.helper= -c core.askPass=/bin/false \
  fetch --depth=1 origin "$TRUSTED_AICG_COMMIT"
[[ "$(git -C "$trusted_git" rev-parse FETCH_HEAD)" == "$TRUSTED_AICG_COMMIT" ]] \
  || die "trusted application commit mismatch"
GIT_CONFIG_NOSYSTEM=1 GIT_CONFIG_GLOBAL=/dev/null \
  git -C "$trusted_git" archive --format=tar FETCH_HEAD | tar -xf - -C "$trusted_app"
find "$trusted_app/src/aicg" -type l -print -quit | grep -q . \
  && die "trusted application package contains a symlink"

cp -R "$trusted_app/src/aicg" "$image_context/trusted/aicg/src/"
cp "$(dirname -- "${BASH_SOURCE[0]}")/run_trusted_aicg.py" "$image_context/trusted/scripts/"
cp "$(dirname -- "${BASH_SOURCE[0]}")/check_verifier_policy.py" "$image_context/trusted/scripts/"
cp "$candidate/requirements.lock" "$image_context/requirements.lock"
cat > "$image_context/Dockerfile" <<EOF
FROM ${PYTHON_IMAGE}
COPY requirements.lock /opt/requirements.lock
RUN python -m pip install --disable-pip-version-check --no-cache-dir --require-hashes -r /opt/requirements.lock
COPY trusted/aicg/src/aicg /opt/trusted/aicg/src/aicg
COPY trusted/scripts/run_trusted_aicg.py /opt/trusted/scripts/run_trusted_aicg.py
COPY trusted/scripts/check_verifier_policy.py /opt/trusted/scripts/check_verifier_policy.py
EOF
docker build --tag "$image" "$image_context"

run_trusted() {
  docker run --rm --network none \
    --user "$(id -u):$(id -g)" --cpus 2 --memory 3g --pids-limit 256 \
    --cap-drop ALL --security-opt no-new-privileges --read-only \
    --tmpfs /tmp:rw,noexec,nosuid,size=64m \
    --mount "type=bind,src=$candidate,dst=/workspace" --workdir /workspace \
    "$image" python -I "/opt/trusted/scripts/$1" "${@:2}"
}

# Reject unconfigured policy before asking Buildkite for any credential.
run_trusted check_verifier_policy.py

for key in CLOUDFLARE_ACCOUNT_ID CLOUDFLARE_API_TOKEN AICG_VERIFIER_PRIVATE_KEY; do
  value="$(buildkite-agent secret get "$key")"
  [[ -n "$value" ]] || die "required Buildkite secret is empty: $key"
  export "$key=$value"
  unset value
done

docker run --rm --network bridge \
  --user "$(id -u):$(id -g)" --cpus 2 --memory 3g --pids-limit 256 \
  --cap-drop ALL --security-opt no-new-privileges --read-only \
  --tmpfs /tmp:rw,noexec,nosuid,size=64m \
  --env CLOUDFLARE_ACCOUNT_ID --env CLOUDFLARE_API_TOKEN --env AICG_VERIFIER_PRIVATE_KEY \
  --mount "type=bind,src=$candidate,dst=/workspace" --workdir /workspace \
  "$image" python -I /opt/trusted/scripts/run_trusted_aicg.py verifier run

(
  cd "$candidate"
  buildkite-agent artifact upload --upload-skip-symlinks ".ai/evidence/verifier.json"
)
run_trusted run_trusted_aicg.py gate final
