#!/usr/bin/env bats
# Tests for Augur.sh — command dispatch and help

load helpers/setup

setup() {
    setup_sandbox
    prepend_bin_to_path
    create_deploy_conf

    # Stub commands that Augur.sh calls
    stub_command "supervisorctl" 'echo "stubbed supervisorctl $*"'
    stub_command "uberspace" 'echo "stubbed uberspace $*"'
    stub_command "node" 'echo "v22.0.0"'
    stub_command "hostname" 'echo "test.uber.space"'

    # Create a .git dir so auto-install detection is skipped
    mkdir -p "$STACK_DIR/.git"
}

teardown() {
    teardown_sandbox
}

@test "help command shows usage info" {
    run bash "$REPO_ROOT/Augur.sh" help
    [[ "$status" -eq 0 ]]
    [[ "$output" == *"status"* ]]
    [[ "$output" == *"restart"* ]]
    [[ "$output" == *"update"* ]]
    [[ "$output" == *"install"* ]]
    [[ "$output" == *"rollback"* ]]
    [[ "$output" == *"cron"* ]]
}

@test "unknown command shows help" {
    run bash "$REPO_ROOT/Augur.sh" nonexistent
    [[ "$status" -eq 0 ]]
    [[ "$output" == *"status"* ]]
    [[ "$output" == *"Augur"* ]]
}

@test "version command reads .version file" {
    echo "v1.2.3" > "$APP_DIR/.version"
    run bash "$REPO_ROOT/Augur.sh" version
    [[ "$status" -eq 0 ]]
    [[ "$output" == *"v1.2.3"* ]]
}

@test "version command shows unknown when no .version" {
    rm -f "$APP_DIR/.version"
    run bash "$REPO_ROOT/Augur.sh" v
    [[ "$status" -eq 0 ]]
    [[ "$output" == *"unknown"* ]]
}

@test "status command shows version and host" {
    echo "v0.5.0" > "$APP_DIR/.version"
    run bash "$REPO_ROOT/Augur.sh" status
    [[ "$status" -eq 0 ]]
    [[ "$output" == *"v0.5.0"* ]]
}

@test "status short alias 's' works" {
    echo "v0.5.0" > "$APP_DIR/.version"
    run bash "$REPO_ROOT/Augur.sh" s
    [[ "$status" -eq 0 ]]
    [[ "$output" == *"v0.5.0"* ]]
}

@test "restart command calls supervisorctl" {
    run bash "$REPO_ROOT/Augur.sh" restart
    [[ "$status" -eq 0 ]]
    [[ "$output" == *"stubbed supervisorctl restart librechat"* ]]
}

@test "rollback fails when no .prev directory exists" {
    rm -rf "${APP_DIR}.prev"
    run bash "$REPO_ROOT/Augur.sh" rollback
    [[ "$status" -eq 1 ]]
    [[ "$output" == *"No previous version"* ]]
}

@test "rollback succeeds when .prev directory exists" {
    mkdir -p "${APP_DIR}.prev"
    echo "v0.4.0" > "${APP_DIR}.prev/.version"
    run bash "$REPO_ROOT/Augur.sh" rb
    [[ "$status" -eq 0 ]]
    [[ "$output" == *"Rolled back"* ]]
    [[ "$output" == *"v0.4.0"* ]]
    # Original APP_DIR should now contain the .prev content
    [[ -f "$APP_DIR/.version" ]]
    [[ "$(cat "$APP_DIR/.version")" == "v0.4.0" ]]
}

@test "Augur.sh passes syntax check" {
    run bash -n "$REPO_ROOT/Augur.sh"
    [[ "$status" -eq 0 ]]
}
