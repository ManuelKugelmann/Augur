#!/usr/bin/env bats
# Integration test: pull workflow + setup.sh edge cases + full lifecycle
# Tests that can't be covered by install smoke tests alone.
#
# A shared venv is built once in setup_file to avoid repeated slow creation.

load helpers/setup

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

    # Stub external commands that aren't available in CI
    stub_command "supervisorctl" 'echo "stubbed: $*"'
    stub_command "uberspace" 'echo "stubbed: $*"'
    stub_command "hostname" 'echo "test.uber.space"'

    # Stub curl to avoid network calls — return empty for GitHub API
    stub_command "curl" 'echo "{}"'

    # Make the sandbox stack look like a real clone
    init_mock_git_repo "$STACK_DIR"
    # Copy actual repo content into sandbox stack
    cp "$REPO_ROOT/deploy.conf" "$STACK_DIR/"
    cp "$REPO_ROOT/requirements.txt" "$STACK_DIR/"
    cp "$REPO_ROOT/.env.example" "$STACK_DIR/"
    cp -r "$REPO_ROOT/librechat-uberspace" "$STACK_DIR/"
    cp -r "$REPO_ROOT/src" "$STACK_DIR/"
    mkdir -p "$STACK_DIR/profiles"

    # Stage and commit the copied files
    git -C "$STACK_DIR" add -A
    git -C "$STACK_DIR" commit -q -m "add project files"

    # Create a bare remote for push/pull simulation
    REMOTE_DIR="$TEST_SANDBOX/remote.git"
    git clone --bare -q "$STACK_DIR" "$REMOTE_DIR"
    git -C "$STACK_DIR" remote remove origin 2>/dev/null || true
    git -C "$STACK_DIR" remote add origin "$REMOTE_DIR"
    git -C "$STACK_DIR" fetch origin
    git -C "$STACK_DIR" branch --set-upstream-to=origin/main main
}

teardown() {
    teardown_sandbox
}

# ── Pull tests ────────────────────────────────

@test "pull: git pull updates stack repo and refreshes deps" {
    # Copy shared venv instead of creating from scratch
    cp -r "$SHARED_VENV_DIR/venv" "$STACK_DIR/venv"

    # Create APP_DIR with .version file
    mkdir -p "$APP_DIR/scripts" "$APP_DIR/config"
    echo "v0.1.0" > "$APP_DIR/.version"

    # Make a change on the remote
    TMP_CLONE="$TEST_SANDBOX/tmp_clone"
    git clone -q "$REMOTE_DIR" "$TMP_CLONE"
    echo "# updated" >> "$TMP_CLONE/deploy.conf"
    git -C "$TMP_CLONE" add -A
    git -C "$TMP_CLONE" commit -q -m "remote update"
    git -C "$TMP_CLONE" push -q origin main

    # Execute just the pull section
    stub_command "node" 'echo "v22.0.0"'
    cd "$STACK_DIR"
    "$REAL_GIT" -C "$STACK_DIR" pull --ff-only origin main
    VER="dev-$("$REAL_GIT" -C "$STACK_DIR" rev-parse --short HEAD)"

    # Copy scripts as pull does
    cp "$STACK_DIR/librechat-uberspace/scripts/TradeAssistant.sh" "$HOME/bin/ta" 2>/dev/null || true
    chmod +x "$HOME/bin/ta" 2>/dev/null || true

    # Update deps
    "$STACK_DIR/venv/bin/pip" install -q -r "$STACK_DIR/requirements.txt" 2>/dev/null || true

    echo "$VER" > "$APP_DIR/.version"

    # Verify
    grep -q "# updated" "$STACK_DIR/deploy.conf"
    grep -q "dev-" "$APP_DIR/.version"
    [ -x "$HOME/bin/ta" ]
}

@test "pull: warns when venv is missing" {
    mkdir -p "$APP_DIR"
    echo "v0.1.0" > "$APP_DIR/.version"

    # Ensure no venv
    rm -rf "$STACK_DIR/venv"

    # Simulate the venv check from pull
    output=$(bash -c '
        export HOME='"'$HOME'"'
        export PATH='"'$PATH'"'
        export STACK_DIR='"'$STACK_DIR'"'
        STACK="$STACK_DIR"
        if [[ -d "$STACK/venv" ]]; then
            "$STACK/venv/bin/pip" install -q -r "$STACK/requirements.txt" 2>/dev/null || true
        else
            echo "warn: Python venv not found"
        fi
    ' 2>&1)

    [[ "$output" == *"venv not found"* ]]
}

# ── Cron compact import test ─────────────────

@test "cron: compact import uses correct sys.path (not src.store.server)" {
    grep -q "from server import compact" "$STACK_DIR/librechat-uberspace/scripts/TradeAssistant.sh"
    ! grep -q "from src.store.server import" "$STACK_DIR/librechat-uberspace/scripts/TradeAssistant.sh"
}

# ── Full lifecycle test ──────────────────────

@test "lifecycle: install -> pull -> update succeeds" {
    stub_command "node" 'echo "v22.0.0"'
    stub_command "npm" 'echo "stubbed npm"'
    stub_command "openssl" '
        if [[ "$1" == "rand" ]]; then
            echo "deadbeef0123456789abcdef"
        fi
    '

    # === INSTALL ===
    # Copy shared venv
    cp -r "$SHARED_VENV_DIR/venv" "$STACK_DIR/venv"

    # Create .env
    cp "$STACK_DIR/.env.example" "$STACK_DIR/.env"

    # Register services
    cat > "$HOME/etc/services.d/trading.ini" <<SVCEOF
[program:trading]
directory=${STACK_DIR}
command=${STACK_DIR}/venv/bin/python src/servers/combined_server.py
SVCEOF

    # Install ta shortcut
    cp "$STACK_DIR/librechat-uberspace/scripts/TradeAssistant.sh" "$HOME/bin/ta"
    chmod +x "$HOME/bin/ta"

    # Create data dir
    mkdir -p "$DATA_DIR/files"

    # Create APP_DIR with mock LibreChat
    mkdir -p "$APP_DIR/api/server" "$APP_DIR/scripts" "$APP_DIR/config"
    echo "// app" > "$APP_DIR/api/server/index.js"
    echo "v0.1.0" > "$APP_DIR/.version"

    # Verify install state
    [ -x "$STACK_DIR/venv/bin/python" ]
    [ -f "$STACK_DIR/.env" ]
    [ -f "$HOME/etc/services.d/trading.ini" ]
    [ -x "$HOME/bin/ta" ]
    [ -d "$DATA_DIR/files" ]

    # === PULL ===
    # Make a change on remote
    TMP_CLONE="$TEST_SANDBOX/tmp_clone2"
    git clone -q "$REMOTE_DIR" "$TMP_CLONE"
    echo "# lifecycle test update" >> "$TMP_CLONE/deploy.conf"
    git -C "$TMP_CLONE" add -A
    git -C "$TMP_CLONE" commit -q -m "lifecycle update"
    git -C "$TMP_CLONE" push -q origin main

    # Pull
    "$REAL_GIT" -C "$STACK_DIR" pull --ff-only origin main
    VER="dev-$("$REAL_GIT" -C "$STACK_DIR" rev-parse --short HEAD)"
    cp "$STACK_DIR/librechat-uberspace/scripts/TradeAssistant.sh" "$HOME/bin/ta"
    chmod +x "$HOME/bin/ta"
    "$STACK_DIR/venv/bin/pip" install -q -r "$STACK_DIR/requirements.txt" 2>/dev/null || true
    echo "$VER" > "$APP_DIR/.version"

    # Verify pull state
    grep -q "# lifecycle test update" "$STACK_DIR/deploy.conf"
    grep -q "dev-" "$APP_DIR/.version"

    # === UPDATE (setup.sh) ===
    SRC="$TEST_SANDBOX/src_lifecycle"
    mkdir -p "$SRC/api/server"
    echo "// updated app" > "$SRC/api/server/index.js"
    echo "KEEP=yes" > "$APP_DIR/.env"

    bash "$STACK_DIR/librechat-uberspace/scripts/setup.sh" "$SRC" "v1.0.0" 2>&1

    # Verify update state
    grep -q "v1.0.0" "$APP_DIR/.version"
    grep -q "KEEP=yes" "$APP_DIR/.env"
    [ -d "${APP_DIR}.prev" ]
}
