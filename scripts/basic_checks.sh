#!/usr/bin/env bash
# CLI smoke tests: exercise every subcommand and a variety of switches.
# Light on assertions — mostly "argv parses and exits with the expected code".
# No network (--no-network throughout); anything that writes uses --dry-run
# or an isolated throwaway --cache-dir under build/.
# Run via `make smoke` or `uv run bash scripts/basic_checks.sh`.

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP_DIR="${ROOT_DIR}/build/basic-checks"
CLI_PYTHON="${PYTHON:-python}"

cli() {
    "${CLI_PYTHON}" -m do_i_need_to_upgrade "$@"
}

run() {
    printf '==> %s\n' "$*"
    "$@" >/dev/null
}

expect_rc() {
    local want="$1"
    shift
    printf '==> [rc=%s] %s\n' "${want}" "$*"
    local rc=0
    "$@" >/dev/null 2>&1 || rc=$?
    if [[ "${rc}" != "${want}" ]]; then
        printf 'FAIL: expected exit %s, got %s: %s\n' "${want}" "${rc}" "$*" >&2
        return 1
    fi
}

# For commands whose success code depends on the dev environment
# (integrity-check: 0 clean / 1 problems; audit: 0 clean / 11 vulns).
expect_rc_one_of() {
    local wanted="$1"
    shift
    printf '==> [rc in %s] %s\n' "${wanted}" "$*"
    local rc=0
    "$@" >/dev/null 2>&1 || rc=$?
    local code
    for code in ${wanted}; do
        [[ "${rc}" == "${code}" ]] && return 0
    done
    printf 'FAIL: expected exit in {%s}, got %s: %s\n' "${wanted}" "${rc}" "$*" >&2
    return 1
}

assert_text_contains() {
    if [[ "$1" != *"$2"* ]]; then
        printf 'FAIL: expected text to contain %s\n' "$2" >&2
        return 1
    fi
}

assert_text_lacks() {
    if [[ "$1" == *"$2"* ]]; then
        printf 'FAIL: expected text NOT to contain %s\n' "$2" >&2
        return 1
    fi
}

assert_missing() {
    if [[ -e "$1" ]]; then
        printf 'FAIL: expected %s to be missing\n' "$1" >&2
        return 1
    fi
}

cd "${ROOT_DIR}"
rm -rf "${TMP_DIR}"
trap 'rm -rf "${TMP_DIR}"' EXIT
mkdir -p "${TMP_DIR}"
CACHE="${TMP_DIR}/cache"
CACHE_FILE="${CACHE}/do_i_need_to_upgrade.json"

echo "=== do_i_need_to_upgrade basic_checks ==="

echo "--- help / version for every command ---"
run cli --help
run cli --version
for cmd in status check audit upgrade watch integrity-check clear-cache snooze; do
    run cli "${cmd}" --help
done
run cli watch add --help
run cli watch remove --help
run cli watch list --help

echo "--- check: self, flag positions, output modes ---"
expect_rc 0 cli --cache-dir "${CACHE}" --no-network check
expect_rc 0 cli check --cache-dir "${CACHE}" --no-network         # shared flags after subcommand
expect_rc 0 cli --cache-dir "${CACHE}" --no-network --quiet check
expect_rc 0 cli --cache-dir "${CACHE}" --no-network check --include-prereleases
check_json="$(cli --cache-dir "${CACHE}" --no-network check --json)"
assert_text_contains "${check_json}" '"host_dist"'

echo "--- check: explicit targets ---"
expect_rc 0 cli --cache-dir "${CACHE}" --no-network check packaging
expect_rc 1 cli --cache-dir "${CACHE}" --no-network check this-pkg-does-not-exist-xyz123
printf 'packaging>=23.0\n# a comment\n-e ./local\n' > "${TMP_DIR}/reqs.txt"
expect_rc 0 cli --cache-dir "${CACHE}" --no-network check -r "${TMP_DIR}/reqs.txt"
expect_rc 1 cli --cache-dir "${CACHE}" --no-network check -r "${TMP_DIR}/missing-reqs.txt"

echo "--- watch: add / list / remove, dry-run does not save ---"
run cli --cache-dir "${CACHE}" watch add packaging pytest
watch_out="$(cli --cache-dir "${CACHE}" watch list)"
assert_text_contains "${watch_out}" "packaging"
assert_text_contains "${watch_out}" "pytest"
run cli --cache-dir "${CACHE}" watch remove pytest
run cli --cache-dir "${CACHE}" watch add --dry-run never-saved
run cli --cache-dir "${CACHE}" watch remove --dry-run packaging
watch_out="$(cli --cache-dir "${CACHE}" watch list)"
assert_text_lacks "${watch_out}" "never-saved"
assert_text_contains "${watch_out}" "packaging"
watch_json="$(cli --cache-dir "${CACHE}" --json watch list)"
assert_text_contains "${watch_json}" '"watch"'
expect_rc 0 cli --cache-dir "${CACHE}" --no-network check --watched

echo "--- snooze: dry-run writes nothing ---"
SNOOZE_CACHE="${TMP_DIR}/snooze-cache"
run cli --cache-dir "${SNOOZE_CACHE}" snooze demo-pkg==1.0.0 --days 3 --dry-run
assert_missing "${SNOOZE_CACHE}/do_i_need_to_upgrade.json"
run cli --cache-dir "${SNOOZE_CACHE}" snooze demo-pkg==1.0.0 --days 3
status_out="$(cli --cache-dir "${SNOOZE_CACHE}" status)"
assert_text_contains "${status_out}" "demo-pkg==1.0.0"

echo "--- status ---"
expect_rc 0 cli --cache-dir "${CACHE}" status
status_json="$(cli --cache-dir "${CACHE}" status --json)"
assert_text_contains "${status_json}" '"schema"'

echo "--- clear-cache: dry-run leaves data, real clear removes it ---"
run cli --cache-dir "${SNOOZE_CACHE}" clear-cache --dry-run
status_out="$(cli --cache-dir "${SNOOZE_CACHE}" status)"
assert_text_contains "${status_out}" "demo-pkg==1.0.0"
run cli --cache-dir "${SNOOZE_CACHE}" clear-cache
status_out="$(cli --cache-dir "${SNOOZE_CACHE}" status)"
assert_text_lacks "${status_out}" "demo-pkg==1.0.0"

echo "--- upgrade: dry-run only, never mutates the environment ---"
# Self-upgrade is rc 1 in dev (editable install has no upgrade path), rc 0 when installed normally.
expect_rc_one_of "0 1" cli upgrade --dry-run
run cli --dist packaging upgrade --dry-run
run cli upgrade packaging --dry-run
upgrade_json="$(cli --json upgrade --dry-run)"
assert_text_contains "${upgrade_json}" '"argv"'
expect_rc 1 cli upgrade this-pkg-does-not-exist-xyz123 --dry-run

echo "--- audit (isolated cache: nothing actionable, so no tool runs) ---"
expect_rc_one_of "0 11" cli --cache-dir "${CACHE}" audit
expect_rc_one_of "0 11" cli --cache-dir "${CACHE}" --quiet audit
expect_rc_one_of "0 11" cli --cache-dir "${CACHE}" --json audit

echo "--- integrity-check (0 clean / 1 problems, both acceptable here) ---"
expect_rc_one_of "0 1" cli integrity-check
expect_rc_one_of "0 1" cli integrity-check --json

echo ""
echo "Done"
