#!/usr/bin/env bats
# Smoke test for the one-liner install path (curl ... | bash).
# Runs TradeAssistant.sh in a fully sandboxed environment with stubbed externals,
# simulating a fresh Uberspace host where the repo hasn't been cloned yet.

load helpers/setup

_write_stub() {
    # Write a stub script to $HOME/bin/$1 with body from stdin
    local name="$1"
    { echo "#!/bin/bash"; cat; } > "$HOME/bin/$name"
    chmod +x "$HOME/bin/$name"
}

setup() {
    setup_sandbox
    prepend_bin_to_path

    # Simple stubs
    stub_command "supervisorctl" 'echo "stubbed supervisorctl $*"'
    stub_command "uberspace" 'echo "stubbed uberspace $*"'
    stub_command "hostname" 'echo "test.uber.space"'
    stub_command "crontab" 'echo ""'
    stub_command "nano" 'echo "stubbed nano $*"'
    stub_command "openssl" 'echo "deadbeef1234567890abcdef12345678"'

    # node stub: returns version when asked
    _write_stub "node" <<'STUBEOF'
if [[ "${1:-}" == "-v" ]]; then echo "v22.0.0"; else echo "stubbed node $*"; fi
STUBEOF

    # python3 stub: handles -m venv by creating fake venv dir
    _write_stub "python3" <<'STUBEOF'
if [[ "${1:-}" == "-m" && "${2:-}" == "venv" ]]; then
    mkdir -p "${3}/bin"
    printf '#!/bin/bash\necho "stubbed venv python $*"\n' > "${3}/bin/python"
    chmod +x "${3}/bin/python"
    printf '#!/bin/bash\necho "stubbed pip $*"\n' > "${3}/bin/pip"
    chmod +x "${3}/bin/pip"
else
    echo "stubbed python3 $*"
fi
STUBEOF

    # curl stub: simulate GitHub API responses
    _write_stub "curl" <<'STUBEOF'
# Release metadata request
if echo "$*" | grep -q "api.github.com/repos.*releases"; then
    echo '{"tag_name":"v0.1.0","assets":[]}'
    exit 0
fi
echo "stubbed curl $*"
STUBEOF

    # git stub: intercept clone, delegate the rest
    local real_git="$REAL_GIT"
    local real_repo="$REPO_ROOT"
    _write_stub "git" <<STUBEOF
REAL_GIT="$real_git"
REAL_REPO="$real_repo"
if [[ "\${1:-}" == "clone" ]]; then
    TARGET=""
    for arg in "\$@"; do
        case "\$arg" in clone|-b|--depth|1|main|https://*) ;; *) TARGET="\$arg" ;; esac
    done
    if [[ -n "\$TARGET" ]]; then
        mkdir -p "\$TARGET"
        cp -r "\$REAL_REPO"/. "\$TARGET/"
        "\$REAL_GIT" -C "\$TARGET" init -q 2>/dev/null || true
        "\$REAL_GIT" -C "\$TARGET" add -A 2>/dev/null || true
        "\$REAL_GIT" -C "\$TARGET" commit -q -m "init" --allow-empty 2>/dev/null || true
        exit 0
    fi
fi
exec "\$REAL_GIT" "\$@"
STUBEOF

    # Remove STACK_DIR so install auto-detect triggers (simulates fresh host)
    rm -rf "$STACK_DIR"
}

teardown() {
    teardown_sandbox
}

# ── Tests ──────────────────────────────────────

@test "TradeAssistant.sh auto-detects fresh install when repo missing" {
    run bash "$REPO_ROOT/librechat-uberspace/scripts/TradeAssistant.sh" 2>&1
    [[ "$output" == *"TradingAssistant"* ]] || [[ "$output" == *"Cloning"* ]] || [[ "$output" == *"Repo"* ]]
}

@test "install clones repo to STACK_DIR" {
    run bash "$REPO_ROOT/librechat-uberspace/scripts/TradeAssistant.sh" install 2>&1
    [[ "$status" -eq 0 ]]
    [[ -d "$STACK_DIR" ]]
    [[ -f "$STACK_DIR/deploy.conf" ]]
}

@test "install creates python venv" {
    run bash "$REPO_ROOT/librechat-uberspace/scripts/TradeAssistant.sh" install 2>&1
    [[ "$status" -eq 0 ]]
    [[ -d "$STACK_DIR/venv" ]]
    [[ -x "$STACK_DIR/venv/bin/python" ]]
}

@test "install creates signals .env from template" {
    run bash "$REPO_ROOT/librechat-uberspace/scripts/TradeAssistant.sh" install 2>&1
    [[ "$status" -eq 0 ]]
    [[ -f "$STACK_DIR/.env" ]]
}

@test "install registers supervisord services" {
    run bash "$REPO_ROOT/librechat-uberspace/scripts/TradeAssistant.sh" install 2>&1
    [[ "$status" -eq 0 ]]
    [[ -f "$HOME/etc/services.d/trading.ini" ]]
    run grep "program:trading" "$HOME/etc/services.d/trading.ini"
    [[ "$status" -eq 0 ]]
    run grep "combined_server.py" "$HOME/etc/services.d/trading.ini"
    [[ "$status" -eq 0 ]]
}

@test "install creates ta shortcut in ~/bin" {
    run bash "$REPO_ROOT/librechat-uberspace/scripts/TradeAssistant.sh" install 2>&1
    [[ "$status" -eq 0 ]]
    [[ -x "$HOME/bin/ta" ]]
    [[ -L "$HOME/bin/TradeAssistant" ]]
}

@test "install creates data directory" {
    run bash "$REPO_ROOT/librechat-uberspace/scripts/TradeAssistant.sh" install 2>&1
    [[ "$status" -eq 0 ]]
    [[ -d "$DATA_DIR/files" ]]
}

@test "install is idempotent (re-run succeeds)" {
    run bash "$REPO_ROOT/librechat-uberspace/scripts/TradeAssistant.sh" install 2>&1
    [[ "$status" -eq 0 ]]
    # Second run (repo already exists → pull path)
    run bash "$REPO_ROOT/librechat-uberspace/scripts/TradeAssistant.sh" install 2>&1
    [[ "$status" -eq 0 ]]
}

@test "install prints completion banner" {
    run bash "$REPO_ROOT/librechat-uberspace/scripts/TradeAssistant.sh" install 2>&1
    [[ "$status" -eq 0 ]]
    [[ "$output" == *"Installation complete"* ]]
}
