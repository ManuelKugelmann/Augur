#!/usr/bin/env bats
# Tests for Augur.sh cron command

load helpers/setup

setup() {
    setup_sandbox
    prepend_bin_to_path
    create_deploy_conf

    # Stub external commands
    stub_command "supervisorctl" 'echo "stubbed"'
    stub_command "uberspace" 'echo "stubbed"'
    stub_command "hostname" 'echo "test.uber.space"'

    mkdir -p "$STACK_DIR/.git"
}

teardown() {
    teardown_sandbox
}

@test "cron: outputs done message with hour and dow" {
    run bash "$REPO_ROOT/Augur.sh" cron
    [[ "$status" -eq 0 ]]
    [[ "$output" == *"done (hour="* ]]
}
