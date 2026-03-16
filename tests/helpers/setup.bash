#!/bin/bash
# Shared test helpers for bats tests
# Sources by each test file via: load helpers/setup

# Save original HOME before any sandbox overrides
ORIG_HOME="$HOME"
export ORIG_HOME

# Create a temporary sandbox for each test
setup_sandbox() {
    export TEST_SANDBOX="$(mktemp -d)"
    export HOME="$TEST_SANDBOX"
    export STACK_DIR="$TEST_SANDBOX/mcps"
    export APP_DIR="$TEST_SANDBOX/LibreChat"
    export LC_PORT="3080"
    export NODE_VERSION="24"
    export GH_USER="TestUser"
    export GH_REPO="TestRepo"
    export UBER_USER="testuser"
    export UBER_HOST="testuser.uber.space"
    export BRANCH="main"

    mkdir -p "$STACK_DIR" "$APP_DIR" "$HOME/bin" "$HOME/etc/services.d" "$HOME/logs" \
             "$HOME/.config/systemd/user"

    # Create dummy service files so _svc_exists returns true for core services
    for _svc in librechat augur charts; do
        touch "$HOME/.config/systemd/user/${_svc}.service"
    done

    # Git config for sandbox (needed for commits)
    git config --global user.email "test@test.com"
    git config --global user.name "Test"
    git config --global init.defaultBranch main
}

teardown_sandbox() {
    # Restore original HOME so global gitconfig changes don't leak
    export HOME="$ORIG_HOME"
    [[ -n "${TEST_SANDBOX:-}" ]] && rm -rf "$TEST_SANDBOX"
}

# Create a minimal deploy.conf in the sandbox
create_deploy_conf() {
    cat > "$STACK_DIR/deploy.conf" <<'EOF'
UBER_USER="${UBER_USER:-testuser}"
UBER_HOST="${UBER_HOST:-testuser.uber.space}"
GH_USER="${GH_USER:-TestUser}"
GH_REPO="${GH_REPO:-TestRepo}"
STACK_DIR="${STACK_DIR:-$HOME/augur}"
APP_DIR="${APP_DIR:-$HOME/LibreChat}"
LC_PORT="${LC_PORT:-3080}"
NODE_VERSION="${NODE_VERSION:-24}"
EOF
}

# Create a mock git repo in the given directory
init_mock_git_repo() {
    local dir="${1:?}"
    mkdir -p "$dir"
    git -C "$dir" init -q
    git -C "$dir" config user.email "test@test.com"
    git -C "$dir" config user.name "Test"
    touch "$dir/.gitkeep"
    git -C "$dir" add .
    git -C "$dir" commit -q -m "init"
}

# Stub an external command by creating a script in $HOME/bin
# Usage: stub_command "supervisorctl" "echo stubbed"
stub_command() {
    local cmd="$1"
    local body="${2:-echo stubbed}"
    cat > "$HOME/bin/$cmd" <<STUB
#!/bin/bash
$body
STUB
    chmod +x "$HOME/bin/$cmd"
}

# Ensure $HOME/bin is first in PATH for stubs
prepend_bin_to_path() {
    export PATH="$HOME/bin:$PATH"
}

# Save real paths to system commands before any stubbing
REAL_GIT="$(command -v git)"
export REAL_GIT

# The actual repo root (for reading source scripts)
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
export REPO_ROOT
