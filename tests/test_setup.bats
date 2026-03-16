#!/usr/bin/env bats
# Tests for setup.sh — LibreChat install/update logic

load helpers/setup

setup() {
    setup_sandbox
    prepend_bin_to_path
    create_deploy_conf

    # Stub external commands
    stub_command "systemctl" 'echo "stubbed systemctl $*"'
    stub_command "uberspace" 'echo "stubbed uberspace $*"'
    stub_command "node" 'echo "v22.0.0"'
    stub_command "npm" 'echo "stubbed npm $*"'
    stub_command "hostname" 'echo "test.uber.space"'
    # Stub all python versions setup.sh scans (prevent real python from being used)
    stub_command "python3.13" 'exit 1'
    stub_command "python3.12" 'exit 1'
    stub_command "python3.11" 'exit 1'
    stub_command "python3.10" 'exit 1'
    stub_command "python3" 'exit 1'
    stub_command "curl" 'echo "stubbed curl $*"'
    # Stub uvx so setup.sh skips the uv install step
    stub_command "uvx" 'echo "stubbed uvx $*"'

    # Create mcps repo structure that setup.sh expects
    mkdir -p "$STACK_DIR/augur-uberspace/config"
    mkdir -p "$STACK_DIR/augur-uberspace/scripts"
    # Provide a minimal Augur.sh for the ops shortcut install
    echo '#!/bin/bash' > "$STACK_DIR/Augur.sh"
}

# Helper: create a minimal source directory that passes setup.sh validation
create_src_app() {
    local src="${1:?}"
    mkdir -p "$src/config" "$src/scripts" "$src/node_modules/@modelcontextprotocol" "$src/api/server"
    echo "// stub" > "$src/api/server/index.js"
}

teardown() {
    teardown_sandbox
}

@test "setup.sh passes syntax check" {
    run bash -n "$REPO_ROOT/augur-uberspace/scripts/setup.sh"
    [[ "$status" -eq 0 ]]
}

@test "setup.sh fails without arguments" {
    run bash "$REPO_ROOT/augur-uberspace/scripts/setup.sh"
    [[ "$status" -ne 0 ]]
}

@test "setup.sh install mode creates version file" {
    # Prepare a source directory with required files
    local src="$TEST_SANDBOX/src_app"
    create_src_app "$src"

    # Create .env.example where setup.sh looks for it (mcps repo config)
    cat > "$STACK_DIR/augur-uberspace/config/.env.example" <<'EOF'
CREDS_KEY=placeholder
CREDS_IV=placeholder
JWT_SECRET=placeholder
JWT_REFRESH_SECRET=placeholder
MONGO_URI=
EOF

    # Remove APP_DIR so install mode is triggered
    rm -rf "$APP_DIR"

    # Stub openssl for key generation
    stub_command "openssl" 'echo "deadbeef1234567890abcdef12345678"'

    run bash "$REPO_ROOT/augur-uberspace/scripts/setup.sh" "$src" "v1.0.0"
    [[ "$status" -eq 0 ]]
    [[ -f "$APP_DIR/.version" ]]
    [[ "$(cat "$APP_DIR/.version")" == "v1.0.0" ]]
}

@test "setup.sh install mode generates .env with crypto keys" {
    local src="$TEST_SANDBOX/src_app"
    create_src_app "$src"
    cat > "$STACK_DIR/augur-uberspace/config/.env.example" <<'EOF'
CREDS_KEY=placeholder
CREDS_IV=placeholder
JWT_SECRET=placeholder
JWT_REFRESH_SECRET=placeholder
SEARCH=true
EOF
    rm -rf "$APP_DIR"
    stub_command "openssl" 'echo "abcdef0123456789abcdef0123456789"'

    run bash "$REPO_ROOT/augur-uberspace/scripts/setup.sh" "$src" "v1.0.0"
    [[ "$status" -eq 0 ]]
    [[ -f "$APP_DIR/.env" ]]

    # Keys should be replaced (not "placeholder")
    run grep "^CREDS_KEY=" "$APP_DIR/.env"
    [[ "$output" != *"placeholder"* ]]

    # SEARCH should be false
    run grep "^SEARCH=" "$APP_DIR/.env"
    [[ "$output" == "SEARCH=false" ]]
}

@test "setup.sh update mode preserves .env" {
    # Set up existing APP_DIR (update mode)
    mkdir -p "$APP_DIR" "$APP_DIR/uploads"
    echo "EXISTING_KEY=keep_me" > "$APP_DIR/.env"
    echo "v0.9.0" > "$APP_DIR/.version"

    # Source directory
    local src="$TEST_SANDBOX/src_app"
    create_src_app "$src"

    run bash "$REPO_ROOT/augur-uberspace/scripts/setup.sh" "$src" "v1.1.0"
    [[ "$status" -eq 0 ]]

    # .env should be preserved
    [[ -f "$APP_DIR/.env" ]]
    run grep "EXISTING_KEY=keep_me" "$APP_DIR/.env"
    [[ "$status" -eq 0 ]]

    # Version should be updated
    [[ "$(cat "$APP_DIR/.version")" == "v1.1.0" ]]
}

@test "setup.sh creates systemd service file on install" {
    local src="$TEST_SANDBOX/src_app"
    create_src_app "$src"
    cat > "$STACK_DIR/augur-uberspace/config/.env.example" <<'EOF'
CREDS_KEY=placeholder
CREDS_IV=placeholder
JWT_SECRET=placeholder
JWT_REFRESH_SECRET=placeholder
EOF
    rm -rf "$APP_DIR"
    stub_command "openssl" 'echo "deadbeef1234567890abcdef12345678"'

    run bash "$REPO_ROOT/augur-uberspace/scripts/setup.sh" "$src" "v1.0.0"
    [[ "$status" -eq 0 ]]
    [[ -f "$HOME/.config/systemd/user/librechat.service" ]]

    run grep "ExecStart=node" "$HOME/.config/systemd/user/librechat.service"
    [[ "$status" -eq 0 ]]
}

@test "setup.sh merges system+user yaml and replaces __HOME__" {
    local src="$TEST_SANDBOX/src_app"
    create_src_app "$src"
    # Place system + user yaml where setup.sh looks for them
    cat > "$STACK_DIR/augur-uberspace/config/librechat-system.yaml" <<'SYSEOF'
version: 1.3.6
mcpServers:
  finance:
    command: __HOME__/augur/venv/bin/python
SYSEOF
    cat > "$STACK_DIR/augur-uberspace/config/librechat-user.yaml" <<'USREOF'
cache: true
USREOF
    # Copy merge script
    cp "$REPO_ROOT/augur-uberspace/scripts/merge-librechat-yaml.py" \
       "$STACK_DIR/augur-uberspace/scripts/merge-librechat-yaml.py"
    cat > "$STACK_DIR/augur-uberspace/config/.env.example" <<'EOF'
CREDS_KEY=placeholder
CREDS_IV=placeholder
JWT_SECRET=placeholder
JWT_REFRESH_SECRET=placeholder
EOF
    rm -rf "$APP_DIR"
    stub_command "openssl" 'echo "deadbeef1234567890abcdef12345678"'

    run bash "$REPO_ROOT/augur-uberspace/scripts/setup.sh" "$src" "v1.0.0"
    [[ "$status" -eq 0 ]]
    [[ -f "$APP_DIR/librechat.yaml" ]]

    run grep "__HOME__" "$APP_DIR/librechat.yaml"
    [[ "$status" -ne 0 ]]  # __HOME__ should be replaced

    run grep "$HOME" "$APP_DIR/librechat.yaml"
    [[ "$status" -eq 0 ]]
}

@test "setup.sh rejects Node.js < 20" {
    # Override node stub to return old version
    stub_command "node" 'if [[ "$1" == "-v" ]]; then echo "v18.0.0"; else echo "v18.0.0"; fi'

    local src="$TEST_SANDBOX/src_app"
    mkdir -p "$src"
    rm -rf "$APP_DIR"

    run bash "$REPO_ROOT/augur-uberspace/scripts/setup.sh" "$src" "v1.0.0"
    [[ "$status" -ne 0 ]]
    [[ "$output" == *"Node.js"* ]]
}

@test "setup.sh preserves uploads directory on update" {
    # Create existing APP_DIR with uploads
    mkdir -p "$APP_DIR/api/server" "$APP_DIR/uploads"
    echo "// old" > "$APP_DIR/api/server/index.js"
    echo "important-file" > "$APP_DIR/uploads/test.txt"
    echo "v0.0.9" > "$APP_DIR/.version"
    echo "MONGO_URI=test" > "$APP_DIR/.env"

    # Create new source
    local src="$TEST_SANDBOX/src_preserve"
    create_src_app "$src"

    bash "$REPO_ROOT/augur-uberspace/scripts/setup.sh" "$src" "v0.3.0" 2>&1

    # Uploads should be preserved in new install
    [ -d "$APP_DIR/uploads" ]
    [ -f "$APP_DIR/uploads/test.txt" ]
    grep -q "important-file" "$APP_DIR/uploads/test.txt"
}

@test "setup.sh installs finance-mcp-server not yahoo-finance-mcp" {
    # Create update-mode APP_DIR (skips install-only logic)
    mkdir -p "$APP_DIR/api/server"
    echo "// stub" > "$APP_DIR/api/server/index.js"
    echo "v0.0.1" > "$APP_DIR/.version"
    echo "KEY=val" > "$APP_DIR/.env"

    # Create venv with pip stub that logs what gets installed
    mkdir -p "$STACK_DIR/venv/bin"
    echo '#!/bin/bash
echo "v22.0.0"' > "$STACK_DIR/venv/bin/python"
    chmod +x "$STACK_DIR/venv/bin/python"
    echo '#!/bin/bash
echo "PIP_INSTALL: $*" >> "$STACK_DIR/pip.log"' > "$STACK_DIR/venv/bin/pip"
    chmod +x "$STACK_DIR/venv/bin/pip"

    local src="$TEST_SANDBOX/src_mcp"
    create_src_app "$src"

    run bash "$REPO_ROOT/augur-uberspace/scripts/setup.sh" "$src" "v1.0.0"
    [[ "$status" -eq 0 ]]

    # Should install finance-mcp-server, NOT yahoo-finance-mcp
    if [[ -f "$STACK_DIR/pip.log" ]]; then
        run grep "yahoo-finance-mcp" "$STACK_DIR/pip.log"
        [[ "$status" -ne 0 ]]  # must NOT appear

        run grep "finance-mcp-server" "$STACK_DIR/pip.log"
        [[ "$status" -eq 0 ]]  # must appear
    fi
}

@test "setup.sh clones crypto-feargreed-mcp to vendor dir" {
    mkdir -p "$APP_DIR/api/server"
    echo "// stub" > "$APP_DIR/api/server/index.js"
    echo "v0.0.1" > "$APP_DIR/.version"
    echo "KEY=val" > "$APP_DIR/.env"

    # Stub git to log clone commands
    stub_command "git" '
if [[ "$1" == "clone" ]]; then
    echo "GIT_CLONE: $*" >> "$HOME/git.log"
    mkdir -p "$5" 2>/dev/null || true
else
    echo "stubbed git $*"
fi'

    local src="$TEST_SANDBOX/src_mcp2"
    create_src_app "$src"

    run bash "$REPO_ROOT/augur-uberspace/scripts/setup.sh" "$src" "v1.0.0"
    [[ "$status" -eq 0 ]]

    # Should attempt to clone crypto-feargreed-mcp into vendor/
    [[ -f "$HOME/git.log" ]]
    run grep "crypto-feargreed-mcp" "$HOME/git.log"
    [[ "$status" -eq 0 ]]
    run grep "vendor/crypto-feargreed-mcp" "$HOME/git.log"
    [[ "$status" -eq 0 ]]
}

@test "setup.sh skips crypto-feargreed-mcp clone when vendor dir exists" {
    mkdir -p "$APP_DIR/api/server"
    echo "// stub" > "$APP_DIR/api/server/index.js"
    echo "v0.0.1" > "$APP_DIR/.version"
    echo "KEY=val" > "$APP_DIR/.env"

    # Pre-create the vendor dir
    mkdir -p "$STACK_DIR/vendor/crypto-feargreed-mcp"

    local src="$TEST_SANDBOX/src_mcp3"
    create_src_app "$src"

    run bash "$REPO_ROOT/augur-uberspace/scripts/setup.sh" "$src" "v1.0.0"
    [[ "$status" -eq 0 ]]
    [[ "$output" == *"crypto-feargreed-mcp already installed"* ]]
}

@test "setup.sh fails on missing app code" {
    # Create existing APP_DIR
    mkdir -p "$APP_DIR/api/server"
    echo "// working" > "$APP_DIR/api/server/index.js"
    echo "v0.0.5" > "$APP_DIR/.version"
    echo "KEEP_ME=yes" > "$APP_DIR/.env"

    # Create bad source (missing api/server/index.js)
    local src="$TEST_SANDBOX/src_bad"
    mkdir -p "$src"
    echo "incomplete" > "$src/README.md"

    run bash "$REPO_ROOT/augur-uberspace/scripts/setup.sh" "$src" "v0.4.0-bad" 2>&1
    [ "$status" -ne 0 ]
    [[ "$output" == *"app code missing"* ]]
}
