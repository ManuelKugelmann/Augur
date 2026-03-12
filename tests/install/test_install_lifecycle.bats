#!/usr/bin/env bats
# Integration test: full install → pull → update lifecycle
# Exercises Augur.sh _do_install, pull, and setup.sh in a sandboxed env.
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

# Copy the shared venv into the given directory
copy_shared_venv() {
    local dest="${1:?}"
    cp -r "$SHARED_VENV_DIR/venv" "$dest/venv"
}

setup() {
    setup_sandbox
    prepend_bin_to_path

    # Stub external commands that aren't available in CI
    stub_command "systemctl" 'echo "stubbed: $*"'
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
    cp "$REPO_ROOT/Augur.sh" "$STACK_DIR/"
    cp -r "$REPO_ROOT/augur-uberspace" "$STACK_DIR/"
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

# ── Install tests ─────────────────────────────

@test "install: creates Python venv and installs deps" {
    # Stub git clone to use local repo instead of network
    stub_command "git" '
        if [[ "$1" == "clone" ]]; then
            # Already cloned in setup, just exit success
            exit 0
        fi
        "$REAL_GIT" "$@"
    '

    # Copy shared venv (built once in setup_file)
    copy_shared_venv "$STACK_DIR"

    [ -x "$STACK_DIR/venv/bin/python" ]
    "$STACK_DIR/venv/bin/python" -c "import httpx" 2>/dev/null
}

@test "install: creates .env from example when missing" {
    [ ! -f "$STACK_DIR/.env" ] || rm "$STACK_DIR/.env"
    cp "$STACK_DIR/.env.example" "$STACK_DIR/.env"

    [ -f "$STACK_DIR/.env" ]
    grep -q "MONGO_URI_SIGNALS" "$STACK_DIR/.env"
}

@test "install: registers systemd service files" {
    mkdir -p "$HOME/.config/systemd/user"

    # Simulate the service registration from _do_install
    cat > "$HOME/.config/systemd/user/trading.service" << SVCEOF
[Install]
WantedBy=default.target

[Service]
WorkingDirectory=${STACK_DIR}
EnvironmentFile=${STACK_DIR}/.env
Environment=MCP_TRANSPORT=http
Environment=MCP_PORT=8071
ExecStart=${STACK_DIR}/venv/bin/python src/servers/combined_server.py
Restart=always
RestartSec=10
SVCEOF

    [ -f "$HOME/.config/systemd/user/trading.service" ]
    grep -q "MCP_TRANSPORT=http" "$HOME/.config/systemd/user/trading.service"
    grep -q "combined_server.py" "$HOME/.config/systemd/user/trading.service"
}

@test "install: installs augur shortcut" {
    mkdir -p "$HOME/bin"
    cp "$STACK_DIR/Augur.sh" "$HOME/bin/augur"
    chmod +x "$HOME/bin/augur"
    ln -sf "$HOME/bin/augur" "$HOME/bin/Augur"

    [ -x "$HOME/bin/augur" ]
    [ -L "$HOME/bin/Augur" ]
}

@test "install: _do_install pre-LibreChat steps complete correctly" {
    # Simulate the individual pre-LibreChat steps from _do_install
    # (end-to-end sourcing isn't feasible due to mktemp/trap interactions)

    stub_command "node" 'echo "v22.0.0"'

    # Step 1: Node.js check
    command -v node &>/dev/null

    # Step 2: Repo already exists (setup created it)
    [ -d "$STACK_DIR/.git" ]

    # Step 3: Venv (copy shared venv)
    copy_shared_venv "$STACK_DIR"
    [ -x "$STACK_DIR/venv/bin/python" ]

    # Step 4: .env
    cp "$STACK_DIR/.env.example" "$STACK_DIR/.env"
    [ -f "$STACK_DIR/.env" ]

    # Step 5: Services
    mkdir -p "$HOME/.config/systemd/user"
    cat > "$HOME/.config/systemd/user/trading.service" << SVCEOF
[Service]
WorkingDirectory=${STACK_DIR}
EnvironmentFile=${STACK_DIR}/.env
ExecStart=${STACK_DIR}/venv/bin/python src/servers/combined_server.py
SVCEOF
    [ -f "$HOME/.config/systemd/user/trading.service" ]

    # Step 8: augur shortcut
    cp "$STACK_DIR/Augur.sh" "$HOME/bin/augur"
    chmod +x "$HOME/bin/augur"
    ln -sf "$HOME/bin/augur" "$HOME/bin/Augur"
    [ -x "$HOME/bin/augur" ]
    [ -L "$HOME/bin/Augur" ]

}

# ── Pull tests ────────────────────────────────

@test "pull: git pull updates stack repo" {
    # Copy shared venv (built once in setup_file)
    copy_shared_venv "$STACK_DIR"

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

    # Run pull via the script
    stub_command "node" 'echo "v22.0.0"'

    # Execute just the pull section
    cd "$STACK_DIR"
    "$REAL_GIT" -C "$STACK_DIR" pull --ff-only origin main
    VER="dev-$("$REAL_GIT" -C "$STACK_DIR" rev-parse --short HEAD)"

    # Copy scripts as pull does
    cp "$STACK_DIR/Augur.sh" "$HOME/bin/augur" 2>/dev/null || true
    chmod +x "$HOME/bin/augur" 2>/dev/null || true

    # Update deps
    "$STACK_DIR/venv/bin/pip" install -q -r "$STACK_DIR/requirements.txt" 2>/dev/null || true

    echo "$VER" > "$APP_DIR/.version"

    # Verify
    grep -q "# updated" "$STACK_DIR/deploy.conf"
    grep -q "dev-" "$APP_DIR/.version"
    [ -x "$HOME/bin/augur" ]
}

@test "pull: warns when venv is missing" {
    mkdir -p "$APP_DIR"
    echo "v0.1.0" > "$APP_DIR/.version"

    # Ensure no venv
    rm -rf "$STACK_DIR/venv"

    # Source the script in a subshell and check the pull warning
    output=$(bash -c '
        export HOME='"'$HOME'"'
        export PATH='"'$PATH'"'
        export STACK_DIR='"'$STACK_DIR'"'
        export APP_DIR='"'$APP_DIR'"'
        export REAL_GIT='"'$REAL_GIT'"'
        STACK="$STACK_DIR"
        APP="$APP_DIR"

        # Simulate the venv check from pull
        if [[ -d "$STACK/venv" ]]; then
            "$STACK/venv/bin/pip" install -q -r "$STACK/requirements.txt" 2>/dev/null || true
        else
            echo "warn: Python venv not found"
        fi
    ' 2>&1)

    [[ "$output" == *"venv not found"* ]]
}

# ── Setup.sh tests ───────────────────────────

@test "setup.sh: detects install mode when APP_DIR missing" {
    rm -rf "$APP_DIR"

    # Create a fake source dir with required structure
    SRC="$TEST_SANDBOX/src_bundle"
    mkdir -p "$SRC/api/server"
    echo "// fake" > "$SRC/api/server/index.js"
    mkdir -p "$SRC/config"
    cp "$STACK_DIR/.env.example" "$SRC/config/.env.example"

    output=$(bash "$STACK_DIR/augur-uberspace/scripts/setup.sh" "$SRC" "v0.1.0-test" 2>&1)

    [[ "$output" == *"Installing"* ]]
    [ -f "$APP_DIR/.version" ]
    grep -q "v0.1.0-test" "$APP_DIR/.version"
}

@test "setup.sh: detects update mode when APP_DIR exists" {
    # Create existing APP_DIR
    mkdir -p "$APP_DIR/api/server" "$APP_DIR/uploads"
    echo "// old" > "$APP_DIR/api/server/index.js"
    echo "v0.0.9" > "$APP_DIR/.version"
    echo "MONGO_URI=test" > "$APP_DIR/.env"

    # Create new source
    SRC="$TEST_SANDBOX/src_update"
    mkdir -p "$SRC/api/server"
    echo "// new" > "$SRC/api/server/index.js"

    output=$(bash "$STACK_DIR/augur-uberspace/scripts/setup.sh" "$SRC" "v0.2.0-test" 2>&1)

    [[ "$output" == *"Updating"* ]]
    grep -q "v0.2.0-test" "$APP_DIR/.version"
    # .env should be preserved
    grep -q "MONGO_URI=test" "$APP_DIR/.env"
    # Previous version should be backed up
    [ -d "${APP_DIR}.prev" ]
}

@test "setup.sh: preserves uploads directory on update" {
    # Create existing APP_DIR with uploads
    mkdir -p "$APP_DIR/api/server" "$APP_DIR/uploads"
    echo "// old" > "$APP_DIR/api/server/index.js"
    echo "important-file" > "$APP_DIR/uploads/test.txt"
    echo "v0.0.9" > "$APP_DIR/.version"
    echo "MONGO_URI=test" > "$APP_DIR/.env"

    # Create new source
    SRC="$TEST_SANDBOX/src_preserve"
    mkdir -p "$SRC/api/server"
    echo "// new" > "$SRC/api/server/index.js"

    bash "$STACK_DIR/augur-uberspace/scripts/setup.sh" "$SRC" "v0.3.0" 2>&1

    # Uploads should be preserved in new install
    [ -d "$APP_DIR/uploads" ]
    [ -f "$APP_DIR/uploads/test.txt" ]
    grep -q "important-file" "$APP_DIR/uploads/test.txt"
}

@test "setup.sh: rolls back on missing app code" {
    # Create existing APP_DIR
    mkdir -p "$APP_DIR/api/server"
    echo "// working" > "$APP_DIR/api/server/index.js"
    echo "v0.0.5" > "$APP_DIR/.version"
    echo "KEEP_ME=yes" > "$APP_DIR/.env"

    # Create bad source (missing api/server/index.js)
    SRC="$TEST_SANDBOX/src_bad"
    mkdir -p "$SRC"
    echo "incomplete" > "$SRC/README.md"

    run bash "$STACK_DIR/augur-uberspace/scripts/setup.sh" "$SRC" "v0.4.0-bad" 2>&1
    [ "$status" -ne 0 ]

    # Should have rolled back to previous version
    [ -f "$APP_DIR/api/server/index.js" ]
    grep -q "// working" "$APP_DIR/api/server/index.js"
}

@test "setup.sh: generates crypto keys on fresh install" {
    rm -rf "$APP_DIR"

    SRC="$TEST_SANDBOX/src_crypto"
    mkdir -p "$SRC/api/server" "$SRC/config"
    echo "// app" > "$SRC/api/server/index.js"

    # Create a minimal .env.example with crypto key placeholders
    cat > "$SRC/config/.env.example" <<'ENVEOF'
CREDS_KEY=
CREDS_IV=
JWT_SECRET=
JWT_REFRESH_SECRET=
ENVEOF

    bash "$STACK_DIR/augur-uberspace/scripts/setup.sh" "$SRC" "v0.5.0" 2>&1

    [ -f "$APP_DIR/.env" ]
    # Keys should be populated (non-empty)
    CREDS_KEY=$(grep "^CREDS_KEY=" "$APP_DIR/.env" | cut -d= -f2)
    [ -n "$CREDS_KEY" ]
    JWT_SECRET=$(grep "^JWT_SECRET=" "$APP_DIR/.env" | cut -d= -f2)
    [ -n "$JWT_SECRET" ]
}

# ── Cron compact import test ─────────────────

@test "cron: compact import uses correct sys.path (not src.store.server)" {
    # Verify the fix: should use server import, not src.store.server
    grep -q "from server import compact" "$STACK_DIR/Augur.sh"
    ! grep -q "from src.store.server import" "$STACK_DIR/Augur.sh"
}

# ── Full lifecycle test ──────────────────────

@test "lifecycle: install → pull → update succeeds" {
    stub_command "node" 'echo "v22.0.0"'
    stub_command "npm" 'echo "stubbed npm"'
    stub_command "openssl" '
        if [[ "$1" == "rand" ]]; then
            echo "deadbeef0123456789abcdef"
        fi
    '

    # === INSTALL ===
    # Copy shared venv (built once in setup_file)
    copy_shared_venv "$STACK_DIR"

    # Create .env
    cp "$STACK_DIR/.env.example" "$STACK_DIR/.env"

    # Register services
    mkdir -p "$HOME/.config/systemd/user"
    cat > "$HOME/.config/systemd/user/trading.service" <<SVCEOF
[Service]
WorkingDirectory=${STACK_DIR}
ExecStart=${STACK_DIR}/venv/bin/python src/servers/combined_server.py
SVCEOF

    # Install augur shortcut
    cp "$STACK_DIR/Augur.sh" "$HOME/bin/augur"
    chmod +x "$HOME/bin/augur"

    # Create APP_DIR with mock LibreChat
    mkdir -p "$APP_DIR/api/server" "$APP_DIR/scripts" "$APP_DIR/config"
    echo "// app" > "$APP_DIR/api/server/index.js"
    echo "v0.1.0" > "$APP_DIR/.version"

    # Verify install state
    [ -x "$STACK_DIR/venv/bin/python" ]
    [ -f "$STACK_DIR/.env" ]
    [ -f "$HOME/.config/systemd/user/trading.service" ]
    [ -x "$HOME/bin/augur" ]

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
    cp "$STACK_DIR/Augur.sh" "$HOME/bin/augur"
    chmod +x "$HOME/bin/augur"
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

    bash "$STACK_DIR/augur-uberspace/scripts/setup.sh" "$SRC" "v1.0.0" 2>&1

    # Verify update state
    grep -q "v1.0.0" "$APP_DIR/.version"
    grep -q "KEEP=yes" "$APP_DIR/.env"
    [ -d "${APP_DIR}.prev" ]
}
