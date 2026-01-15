#!/bin/bash
# Integration Test Runner
# Runs all integration tests in isolated environments

set -e

INTEGRATION_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$INTEGRATION_DIR"

# Load shared environment
if [ -f "$INTEGRATION_DIR/../test-env.sh" ]; then
    source "$INTEGRATION_DIR/../test-env.sh"
else
    echo "Error: test-env.sh not found"
    exit 1
fi

echo "=============================================="
echo -e "${BLUE}FlatAgents Integration Tests${NC}"
echo "=============================================="
echo ""

# Environment setup
echo -e "${CYAN}🔧 Setting up test environment...${NC}"
check_node_version
check_npm_version
setup_test_env

# Install dependencies and build SDK
install_dependencies "$SDK_ROOT"
build_project "$SDK_ROOT"

# Ensure test symlinks for integration imports
if [ ! -e "$TESTS_ROOT/src" ]; then
    ln -s "$SDK_ROOT/src" "$TESTS_ROOT/src"
fi
if [ ! -e "$TESTS_ROOT/dist" ] && [ -d "$SDK_ROOT/dist" ]; then
    ln -s "$SDK_ROOT/dist" "$TESTS_ROOT/dist"
fi

# Run integration tests from SDK root
echo -e "${YELLOW}Running integration tests...${NC}"
echo "----------------------------------------------"

cd "$SDK_ROOT"
if npx vitest run "$INTEGRATION_DIR"/*.integration.test.ts --reporter=verbose; then
    echo "=============================================="
    echo -e "${GREEN}All integration tests passed!${NC}"
    exit 0
fi

echo "=============================================="
echo -e "${RED}Integration tests failed.${NC}"
exit 1
