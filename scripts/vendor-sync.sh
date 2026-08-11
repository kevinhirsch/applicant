#!/usr/bin/env bash
# vendor-sync.sh — Pull latest upstream agent-zero into the vendored subtree
# Usage: ./scripts/vendor-sync.sh [upstream-tag]
#   upstream-tag: optional, defaults to fetching main branch
#
# This script:
#   1. Fetches the latest upstream tag/commit
#   2. Runs git subtree pull (only real conflicts surface)
#   3. Runs the full gate set to validate the pull
#   4. Reports any conflicts or gate failures

set -euo pipefail

UPSTREAM_REPO="https://github.com/agent0ai/agent-zero.git"
UPSTREAM_REF="${1:-main}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$REPO_ROOT"

# --- Step 1: Check for uncommitted work -----------------------------------
if ! git diff --quiet HEAD; then
    echo "ERROR: uncommitted changes — commit or stash before syncing"
    exit 1
fi

# --- Step 2: Fetch upstream -----------------------------------------------
echo "=== Fetching upstream $UPSTREAM_REF ==="
git fetch "$UPSTREAM_REPO" "$UPSTREAM_REF" 2>&1
FETCH_HEAD_HASH=$(git rev-parse FETCH_HEAD)
echo "Upstream $UPSTREAM_REF at $FETCH_HEAD_HASH"

# --- Step 3: Subtree pull -------------------------------------------------
echo "=== Running git subtree pull ==="
if git subtree pull --prefix=agent-zero "$UPSTREAM_REPO" "$FETCH_HEAD_HASH" --squash 2>&1; then
    echo "subtree pull: clean"
else
    PULL_EXIT=$?
    echo "FAILED: subtree pull has conflicts — resolve manually then run gates"
    exit $PULL_EXIT
fi

# --- Step 4: Verify byte-identity of upstream files -----------------------
echo "=== Verifying upstream files are pristine ==="
# The subtree is squashed, so we can't directly diff; instead confirm
# the Squashed 'agent-zero/' commit message references the upstream commit
LATEST_SQUASH_MSG=$(git log --oneline --grep="Squashed 'agent-zero/" -1 2>&1 || echo "")
if echo "$LATEST_SQUASH_MSG" | grep -q "$FETCH_HEAD_HASH"; then
    echo "byte-identity check: SQUASHED (normal for subtree)"
else
    echo "WARNING: Could not verify squashed commit matches $FETCH_HEAD_HASH"
    echo "  Latest squash message: $LATEST_SQUASH_MSG"
fi

# --- Step 5: Run gate set -------------------------------------------------
echo "=== Running full gate set ==="
GATES_PASSED=true

# 5a. White-label greps (with agent-zero/ excluded from upstream content)
echo "--- White-label denylist (carving out agent-zero/) ---"
if git grep -I -i -E 'firehouse|orwell|odysseus|smokey' \
    -- ':!.github' ':!*.lock' ':!uv.lock' \
    ':!HARVEST-INVENTORY.md' ':!docs/HARVEST-*' ':!docs/APPLICANT-SURVIVAL-PLAN.md' \
    ':!docs/design/hig/color-wells.md' \
    ':!workspace/tests/test_landing_page_content.py' \
    ':!workspace/tests/test_applicant_activation_funnel_09.py' \
    ':!workspace/tests/test_applicant_mind_help_lens12.py' \
    ':!workspace/tests/test_applicant_remote_help_lens12.py' \
    ':!workspace/tests/test_applicant_debug_help_lens12.py' \
    ':!workspace/tests/test_applicant_gallery_intro_lens12.py' \
    ':!workspace/tests/test_applicant_copy_digest_lens02.py' \
    ':!workspace/tests/test_applicant_chat_polish_lens0102.py' \
    ':!agent-zero/**' 2>&1; then
    echo "FAILED: white-label codename found outside agent-zero/"
    GATES_PASSED=false
else
    echo "white-label grep 1: clean"
fi

if git grep -I -i -F 'hermes-agent' \
    -- ':!.github' ':!*.lock' ':!uv.lock' \
    ':!HARVEST-INVENTORY.md' ':!docs/HARVEST-*' ':!docs/APPLICANT-SURVIVAL-PLAN.md' \
    ':!workspace/services/memory/skill_format.py' \
    ':!docs/spec/master-spec.md' \
    ':!docs/traceability.md' \
    ':!NOTICE' \
    ':!docs/spec/computer-use.md' \
    ':!docs/spec/agent-intelligence.md' \
    ':!docs/adr/0005-computer-use-cua-driver.md' \
    ':!docs/adr/0006-agent-intelligence-port.md' \
    ':!workspace/tests/test_applicant_mind_help_lens12.py' \
    ':!workspace/tests/test_applicant_remote_help_lens12.py' \
    ':!workspace/tests/test_applicant_gallery_intro_lens12.py' \
    ':!workspace/tests/test_applicant_copy_digest_lens02.py' \
    ':!workspace/tests/test_applicant_chat_polish_lens0102.py' \
    ':!agent-zero/**' 2>&1; then
    echo "FAILED: white-label 'hermes-agent' found outside agent-zero/"
    GATES_PASSED=false
else
    echo "white-label grep 2: clean"
fi

# 5b. Ruff lint (excluding agent-zero/)
echo "--- Ruff lint ---"
if uv run ruff check . --exclude agent-zero 2>&1; then
    echo "ruff: clean"
else
    echo "FAILED: ruff has findings"
    GATES_PASSED=false
fi

# 5c. Import contract
echo "--- Lint imports ---"
if uv run lint-imports 2>&1; then
    echo "lint-imports: clean"
else
    echo "FAILED: import contract broken"
    GATES_PASSED=false
fi

# 5d. Engine tests (hermetic)
echo "--- Engine pytest (hermetic) ---"
if DATABASE_URL='postgresql+psycopg://x:x@127.0.0.1:1/none' uv run pytest -q -m "not integration" --tb=short 2>&1 | tail -5; then
    echo "engine tests: clean"
else
    echo "FAILED: engine tests"
    GATES_PASSED=false
fi

# --- Step 6: Report -------------------------------------------------------
echo ""
echo "=== VENDOR SYNC REPORT ==="
echo "Upstream ref: $UPSTREAM_REF ($FETCH_HEAD_HASH)"
if [ "$GATES_PASSED" = true ]; then
    echo "RESULT: ALL GATES PASSED — vendor sync ready to commit"
    echo "Run: git commit (amending the merge) and push"
    exit 0
else
    echo "RESULT: ONE OR MORE GATES FAILED — fix before committing"
    exit 1
fi
