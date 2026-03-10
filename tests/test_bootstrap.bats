#!/usr/bin/env bats
# Tests for shell script syntax validation

load helpers/setup

setup() {
    setup_sandbox
}

teardown() {
    teardown_sandbox
}

@test "all shell scripts pass syntax check" {
    local scripts=(
        "$REPO_ROOT/librechat-uberspace/scripts/TradeAssistant.sh"
        "$REPO_ROOT/librechat-uberspace/scripts/setup.sh"
        "$REPO_ROOT/librechat-uberspace/scripts/claude-auth-daemon.sh"
    )
    for script in "${scripts[@]}"; do
        run bash -n "$script"
        [[ "$status" -eq 0 ]] || {
            echo "Syntax error in: $script"
            echo "$output"
            return 1
        }
    done
}
