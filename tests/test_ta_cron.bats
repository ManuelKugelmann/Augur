#!/usr/bin/env bats
# Tests for TradeAssistant.sh cron command

load helpers/setup

setup() {
    setup_sandbox
    prepend_bin_to_path
    create_deploy_conf

    # Stub external commands
    stub_command "supervisorctl" 'echo "stubbed"'
    stub_command "uberspace" 'echo "stubbed"'
    stub_command "hostname" 'echo "test.uber.space"'

    # STACK_DIR must be a real git repo (cron does git add profiles/)
    init_mock_git_repo "$STACK_DIR"
    mkdir -p "$STACK_DIR/profiles"
}

teardown() {
    teardown_sandbox
}

@test "cron: profile auto-commit when profiles changed" {
    echo '{"id":"TST"}' > "$STACK_DIR/profiles/TST.json"

    run bash "$REPO_ROOT/librechat-uberspace/scripts/TradeAssistant.sh" cron
    [[ "$status" -eq 0 ]]

    cd "$STACK_DIR"
    run git log --oneline -1
    [[ "$output" == *"profile updates"* ]]
}

@test "cron: no profile commit when nothing changed" {
    local before_hash
    before_hash=$(git -C "$STACK_DIR" rev-parse HEAD)

    run bash "$REPO_ROOT/librechat-uberspace/scripts/TradeAssistant.sh" cron
    [[ "$status" -eq 0 ]]

    local after_hash
    after_hash=$(git -C "$STACK_DIR" rev-parse HEAD)
    [[ "$before_hash" == "$after_hash" ]]
}

@test "cron: outputs done message with hour and dow" {
    run bash "$REPO_ROOT/librechat-uberspace/scripts/TradeAssistant.sh" cron
    [[ "$status" -eq 0 ]]
    [[ "$output" == *"done (hour="* ]]
}
