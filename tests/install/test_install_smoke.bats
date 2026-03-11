#!/usr/bin/env bats
# Smoke test for the install path.
# Uses real git/python3/node/curl — only stubs Uberspace-specific commands
# (supervisorctl, uberspace, hostname).
# Basic tests pre-create APP_DIR/.version to skip LC download.
# Full lifecycle test exercises the complete flow including LC bundle download.
#
# A shared venv is built once in setup_file and copied per test to avoid
# repeated slow venv creation.

load ../helpers/setup

# ── File-level setup: build a reusable venv once ──
setup_file() {
    export SHARED_VENV_DIR="$(mktemp -d)"
    python3 -m venv "$SHARED_VENV_DIR/venv"
    "$SHARED_VENV_DIR/venv/bin/pip" install -q -r "$REPO_ROOT/requirements.txt"
}

teardown_file() {
    [[ -n "${SHARED_VENV_DIR:-}" ]] && rm -rf "$SHARED_VENV_DIR"
}

setup() {
    setup_sandbox
    prepend_bin_to_path

    # Only stub what CI genuinely lacks (Uberspace-specific)
    stub_command "supervisorctl" 'echo "stubbed supervisorctl $*"'
    stub_command "uberspace" 'echo "stubbed uberspace $*"'
    stub_command "hostname" 'echo "test.uber.space"'
    stub_command "crontab" 'echo ""'
    stub_command "nano" 'echo "stubbed nano $*"'

    # Pre-create LibreChat dir with .version matching the prerelease tag
    # so install skips the LC download (version check: already up-to-date)
    mkdir -p "$APP_DIR/api/server"
    echo "module.exports = {};" > "$APP_DIR/api/server/index.js"
    echo "librechat-build" > "$APP_DIR/.version"

    # Stub curl to return release metadata for the sandbox TestUser/TestRepo.
    # The installed version "librechat-build" matches the tag, so download is skipped.
    stub_command "curl" '
        for arg in "$@"; do
            if [[ "$arg" == *"api.github.com/repos"*"releases"* ]]; then
                echo "{\"tag_name\":\"librechat-build\",\"assets\":[{\"browser_download_url\":\"https://example.com/librechat-build.tar.gz\",\"name\":\"librechat-build.tar.gz\"}]}"
                exit 0
            fi
        done
        # Pass through for non-GitHub-API calls (wget fallback, etc.)
        exit 1
    '

    # Use real git, but intercept clone to use local repo (no network).
    # Also inject the shared venv into STACK_DIR after clone to skip venv creation.
    local real_git="$REAL_GIT"
    local real_repo="$REPO_ROOT"
    local shared_venv="$SHARED_VENV_DIR/venv"
    cat > "$HOME/bin/git" <<STUBEOF
#!/bin/bash
REAL_GIT="$real_git"
REAL_REPO="$real_repo"
# Only intercept clone of Augur repo
if [[ "\${1:-}" == "clone" ]] && echo "\$*" | grep -q "Augur\|TestRepo"; then
    TARGET="\${@: -1}"
    mkdir -p "\$TARGET"
    cp -r "\$REAL_REPO"/. "\$TARGET/"
    # Copy shared venv so install skips slow venv creation
    cp -r "$shared_venv" "\$TARGET/venv"
    "\$REAL_GIT" -C "\$TARGET" init -q 2>/dev/null || true
    "\$REAL_GIT" -C "\$TARGET" add -A 2>/dev/null || true
    "\$REAL_GIT" -C "\$TARGET" commit -q -m "init" --allow-empty 2>/dev/null || true
    exit 0
fi
# Everything else: use real git
exec "\$REAL_GIT" "\$@"
STUBEOF
    chmod +x "$HOME/bin/git"

    # Remove STACK_DIR so install auto-detect triggers (simulates fresh host)
    rm -rf "$STACK_DIR"
}

teardown() {
    teardown_sandbox
}

# ── Tests ──────────────────────────────────────

@test "Augur.sh auto-detects fresh install when repo missing" {
    run bash "$REPO_ROOT/Augur.sh" 2>&1
    [[ "$output" == *"Augur"* ]] || [[ "$output" == *"Cloning"* ]] || [[ "$output" == *"Repo"* ]]
}

@test "install clones repo to STACK_DIR" {
    run bash "$REPO_ROOT/Augur.sh" install 2>&1
    [[ "$status" -eq 0 ]]
    [[ -d "$STACK_DIR" ]]
    [[ -f "$STACK_DIR/deploy.conf" ]]
}

@test "install creates python venv" {
    run bash "$REPO_ROOT/Augur.sh" install 2>&1
    [[ "$status" -eq 0 ]]
    [[ -d "$STACK_DIR/venv" ]]
    [[ -x "$STACK_DIR/venv/bin/python" ]]
}

@test "install creates signals .env from template" {
    run bash "$REPO_ROOT/Augur.sh" install 2>&1
    [[ "$status" -eq 0 ]]
    [[ -f "$STACK_DIR/.env" ]]
}

@test "install registers supervisord services" {
    run bash "$REPO_ROOT/Augur.sh" install 2>&1
    [[ "$status" -eq 0 ]]
    [[ -f "$HOME/etc/services.d/trading.ini" ]]
    run grep "program:trading" "$HOME/etc/services.d/trading.ini"
    [[ "$status" -eq 0 ]]
    run grep "combined_server.py" "$HOME/etc/services.d/trading.ini"
    [[ "$status" -eq 0 ]]
}

@test "install creates augur shortcut in ~/bin" {
    run bash "$REPO_ROOT/Augur.sh" install 2>&1
    [[ "$status" -eq 0 ]]
    [[ -x "$HOME/bin/augur" ]]
    [[ -L "$HOME/bin/Augur" ]]
}

@test "install is idempotent (re-run succeeds)" {
    run bash "$REPO_ROOT/Augur.sh" install 2>&1
    [[ "$status" -eq 0 ]]
    # Second run (repo already exists → pull path)
    run bash "$REPO_ROOT/Augur.sh" install 2>&1
    [[ "$status" -eq 0 ]]
}

@test "install prints completion banner" {
    run bash "$REPO_ROOT/Augur.sh" install 2>&1
    [[ "$status" -eq 0 ]]
    [[ "$output" == *"Installation complete"* ]]
}

# ── Cron entrypoint tests ─────────────────────

@test "cron: runs without error after install" {
    # First install to set up STACK_DIR with .git
    run bash "$REPO_ROOT/Augur.sh" install 2>&1
    [[ "$status" -eq 0 ]]

    # Now run cron — should succeed (no data changes, skips compact without venv python)
    run bash "$REPO_ROOT/Augur.sh" cron 2>&1
    [[ "$status" -eq 0 ]]
    [[ "$output" == *"done (hour="* ]]
}

# ── Full install with LibreChat bundle download ──

@test "install: full lifecycle including LibreChat bundle download" {
    # Remove pre-created APP_DIR so install must download LibreChat
    rm -rf "$APP_DIR"

    # Build a fake release bundle (mimics CI output from release.yml)
    local BUNDLE_DIR="$TEST_SANDBOX/fake_bundle"
    mkdir -p "$BUNDLE_DIR/api/server"
    echo "module.exports = {};" > "$BUNDLE_DIR/api/server/index.js"
    echo "1.0.0+abc1234" > "$BUNDLE_DIR/.version"
    tar czf "$TEST_SANDBOX/librechat-bundle.tar.gz" -C "$BUNDLE_DIR" .

    # Override the curl stub from setup() to serve our fake bundle.
    # Handles both GitHub API metadata calls and the actual file download.
    local bundle_path="$TEST_SANDBOX/librechat-bundle.tar.gz"
    local real_curl
    real_curl="$(command -v curl)"
    cat > "$HOME/bin/curl" <<CURLEOF
#!/bin/bash
for arg in "\$@"; do
    if [[ "\$arg" == *"api.github.com/repos"*"releases"* ]]; then
        echo '{"tag_name":"v1.0.0","assets":[{"browser_download_url":"file://$bundle_path","name":"librechat-build.tar.gz"}]}'
        exit 0
    fi
    if [[ "\$arg" == "file://"* ]]; then
        local_path="\${arg#file://}"
        out=""
        prev=""
        for a in "\$@"; do
            [[ "\$prev" == "-o" ]] && { out="\$a"; break; }
            prev="\$a"
        done
        [[ -n "\$out" ]] && cp "\$local_path" "\$out" || cat "\$local_path"
        exit 0
    fi
done
exec "$real_curl" "\$@"
CURLEOF
    chmod +x "$HOME/bin/curl"

    # Stub openssl for crypto key generation in setup.sh
    stub_command "openssl" '
        if [[ "$1" == "rand" ]]; then
            echo "deadbeef0123456789abcdef01234567"
        fi
    '

    # Run full install (no APP_DIR/.version → will download bundle)
    # Timeout prevents stall if an external dep hangs (npm, pip, git clone, curl)
    run timeout 120 bash "$REPO_ROOT/Augur.sh" install 2>&1
    echo "$output"
    if [[ "$status" -eq 124 ]]; then
        echo "FAIL: install timed out after 120s" >&2
        false
    fi
    [[ "$status" -eq 0 ]]

    # Verify LibreChat was installed from bundle with LC version
    [[ -f "$APP_DIR/.version" ]]
    grep -q "1.0.0+abc1234" "$APP_DIR/.version"
    [[ -f "$APP_DIR/api/server/index.js" ]]

    # Verify .env was generated with crypto keys
    [[ -f "$APP_DIR/.env" ]]
    grep -q "CREDS_KEY=" "$APP_DIR/.env"

    # Verify librechat.yaml was copied and __HOME__ replaced
    [[ -f "$APP_DIR/librechat.yaml" ]]
    ! grep -q "__HOME__" "$APP_DIR/librechat.yaml"

    # Verify supervisord service was created
    [[ -f "$HOME/etc/services.d/librechat.ini" ]]
    grep -q "program:librechat" "$HOME/etc/services.d/librechat.ini"

    # Verify completion banner
    [[ "$output" == *"Installation complete"* ]] || [[ "$output" == *"Installed"* ]]
}

@test "install: skips download when LC version already matches" {
    # Pre-create APP_DIR with version matching the prerelease tag
    mkdir -p "$APP_DIR/api/server"
    echo "module.exports = {};" > "$APP_DIR/api/server/index.js"
    echo "librechat-build" > "$APP_DIR/.version"

    # Stub curl to return release metadata (avoids GitHub API rate limits in CI).
    # The real release uses tag "librechat-build" with asset "librechat-build.tar.gz".
    stub_command "curl" '
        for arg in "$@"; do
            if [[ "$arg" == *"api.github.com/repos"*"releases"* ]]; then
                echo "{\"tag_name\":\"librechat-build\",\"assets\":[{\"browser_download_url\":\"https://github.com/ManuelKugelmann/Augur/releases/download/librechat-build/librechat-build.tar.gz\",\"name\":\"librechat-build.tar.gz\"}]}"
                exit 0
            fi
        done
        exit 1
    '

    run bash "$REPO_ROOT/Augur.sh" install 2>&1
    echo "$output"
    [[ "$status" -eq 0 ]]
    [[ "$output" == *"already up-to-date"* ]]
}

@test "install: fails with clear message when no release bundle available" {
    # Remove pre-created APP_DIR so install must download LibreChat
    rm -rf "$APP_DIR"

    # Stub curl to return empty JSON (no release assets)
    stub_command "curl" 'echo "{}"'

    run bash -c 'bash "$1" install 2>&1' _ "$REPO_ROOT/Augur.sh"
    echo "$output"
    [[ "$status" -ne 0 ]]
    [[ "$output" == *"No prebuilt LibreChat release found"* ]]
}
