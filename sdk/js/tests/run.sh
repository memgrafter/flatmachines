#!/bin/bash
# FlatAgents JavaScript SDK - Test Runner
# Unified interface for all test types

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# Load shared environment
if [ -f "test-env.sh" ]; then
    source test-env.sh
else
    echo "Error: test-env.sh not found"
    exit 1
fi

# Colors for output
echo -e "${BLUE}"
echo "=============================================="
echo " FlatAgents JavaScript SDK - Test Suite"
echo "=============================================="
echo -e "${NC}"

# Default values
TEST_TYPE="unit"
VERBOSE=false
COVERAGE=false
HELP=false
PARALLEL=false
WATCH=false
TEST_PATTERN=""

# Parse arguments
while [[ $# -gt 0 ]]; do
  case $1 in
    unit|integration|e2e|all|parity|parity-lock|parity-all)
      TEST_TYPE="$1"
      shift
      ;;
    --verbose|-v)
      VERBOSE=true
      shift
      ;;
    --coverage|-c)
      COVERAGE=true
      shift
      ;;
    --parallel|-p)
      PARALLEL=true
      shift
      ;;
    --watch|-w)
      WATCH=true
      shift
      ;;
    --pattern)
      TEST_PATTERN="$2"
      shift 2
      ;;
    --help|-h)
      HELP=true
      shift
      ;;
    *)
      echo -e "${RED}Unknown option: $1${NC}"
      HELP=true
      shift
      ;;
  esac
done

# Show help
if [ "$HELP" = true ]; then
    echo "FlatAgents JavaScript SDK Test Runner"
    echo ""
    echo "Usage: $0 [test-type] [options]"
    echo ""
    echo "Test Types:"
    echo "  unit         Run unit tests (default)"
    echo "  integration  Run integration tests"
    echo "  e2e          Run end-to-end tests"
    echo "  all          Run all test suites"
    echo "  parity       Run holdback + topical parity suites"
    echo "  parity-lock  Run holdback inventory/assignment lock only"
    echo "  parity-all   Alias for parity"
    echo ""
    echo "Options:"
    echo "  --verbose, -v    Enable verbose output"
    echo "  --coverage, -c   Generate coverage report"
    echo "  --parallel, -p   Run test suites in parallel (with 'all')"
    echo "  --watch, -w      Watch mode for continuous testing"
    echo "  --pattern <pat>  Run specific test pattern"
    echo "  --help, -h       Show this help message"
    echo ""
    echo "Examples:"
    echo "  $0                    # Run unit tests"
    echo "  $0 integration        # Run integration tests"
    echo "  $0 all --coverage     # Run all tests with coverage"
    echo "  $0 unit --watch       # Watch mode for unit tests"
    exit 0
fi

# Environment setup
echo -e "${CYAN}🔧 Setting up test environment...${NC}"
check_node_version
check_npm_version
setup_test_env

# Install dependencies
install_dependencies "$SDK_ROOT"
install_dependencies .

# Build project if needed
build_project "$SDK_ROOT"

# Build vitest args
build_vitest_args() {
    local args=""
    if [ "$COVERAGE" = true ]; then
        args="$args --coverage"
    fi
    if [ "$VERBOSE" = true ]; then
        args="$args --verbose"
    fi
    if [ "$WATCH" = true ]; then
        args="$args --watch"
    else
        args="$args run"
    fi
    echo "$args"
}

# Track results
TOTAL_PASSED=0
TOTAL_FAILED=0

# Function to run a single test suite
run_suite() {
    local suite_name="$1"
    local test_dir="$2"
    local pattern="$3"

    echo ""
    echo -e "${YELLOW}🧪 Running $suite_name tests...${NC}"
    echo "----------------------------------------------"

    local vitest_args=$(build_vitest_args)
    local test_filter="${pattern:-$test_dir}"

    if [ "$VERBOSE" = true ]; then
        echo "Filter: $test_filter"
        echo "Args: $vitest_args"
    fi

    # Run from SDK root
    cd "$SDK_ROOT"

    if npx vitest $vitest_args "$test_filter"; then
        TOTAL_PASSED=$((TOTAL_PASSED + 1))
        echo -e "${GREEN}✓ $suite_name tests PASSED${NC}"
        return 0
    else
        TOTAL_FAILED=$((TOTAL_FAILED + 1))
        echo -e "${RED}✗ $suite_name tests FAILED${NC}"
        return 1
    fi
}

run_integration_runner() {
    echo ""
    echo -e "${YELLOW}🧪 Running Integration tests...${NC}"
    echo "----------------------------------------------"
    cd "$SCRIPT_DIR"
    if ./integration/run.sh; then
        TOTAL_PASSED=$((TOTAL_PASSED + 1))
        echo -e "${GREEN}✓ Integration tests PASSED${NC}"
        return 0
    else
        TOTAL_FAILED=$((TOTAL_FAILED + 1))
        echo -e "${RED}✗ Integration tests FAILED${NC}"
        return 1
    fi
}

run_vitest() {
    # Prefer pnpm if present, otherwise fall back to npm's npx (fnm-managed Node/npm).
    if command -v pnpm >/dev/null 2>&1; then
        pnpm vitest "$@"
    else
        npx vitest "$@"
    fi
}

run_parity_lock() {
    echo ""
    echo -e "${YELLOW}🧪 Running parity inventory lock suite...${NC}"
    echo "----------------------------------------------"
    cd "$SDK_ROOT"

    if run_vitest run tests/holdback/python-sdk-parity.test.ts; then
        TOTAL_PASSED=$((TOTAL_PASSED + 1))
        echo -e "${GREEN}✓ Parity inventory lock PASSED${NC}"
        return 0
    else
        TOTAL_FAILED=$((TOTAL_FAILED + 1))
        echo -e "${RED}✗ Parity inventory lock FAILED${NC}"
        return 1
    fi
}

run_parity_aggregate() {
    echo ""
    echo -e "${YELLOW}🧪 Running aggregate parity suites...${NC}"
    echo "----------------------------------------------"
    cd "$SDK_ROOT"

    if run_vitest run tests/parity tests/holdback/python-sdk-parity.test.ts; then
        TOTAL_PASSED=$((TOTAL_PASSED + 1))
        echo -e "${GREEN}✓ Aggregate parity suites PASSED${NC}"
        return 0
    else
        TOTAL_FAILED=$((TOTAL_FAILED + 1))
        echo -e "${RED}✗ Aggregate parity suites FAILED${NC}"
        return 1
    fi
}

# Run the requested test suite(s)
case "$TEST_TYPE" in
    unit)
        run_suite "Unit" "unit" "$TEST_PATTERN"
        ;;
    integration)
        run_integration_runner
        ;;
    e2e)
        run_suite "E2E" "e2e" "$TEST_PATTERN"
        ;;
    all)
        echo -e "${BLUE}Running all test suites...${NC}"

        if [ "$PARALLEL" = true ]; then
            echo -e "${YELLOW}Running tests in parallel...${NC}"

            # Run in background
            (run_suite "Unit" "unit") &
            UNIT_PID=$!
            (run_suite "Integration" "integration") &
            INTEGRATION_PID=$!
            (run_suite "E2E" "e2e") &
            E2E_PID=$!

            # Wait for completion
            wait $UNIT_PID || TOTAL_FAILED=$((TOTAL_FAILED + 1))
            wait $INTEGRATION_PID || TOTAL_FAILED=$((TOTAL_FAILED + 1))
            wait $E2E_PID || TOTAL_FAILED=$((TOTAL_FAILED + 1))
        else
            run_suite "Unit" "unit" || true
            run_suite "Integration" "integration" || true
            run_suite "E2E" "e2e" || true
        fi
        ;;
    parity)
        run_parity_lock || true
        run_parity_aggregate || true
        ;;
    parity-lock)
        run_parity_lock
        ;;
    parity-all)
        run_parity_aggregate
        ;;
esac

# Cleanup
cleanup_test_env 2>/dev/null || true

# Final summary
echo ""
echo "=============================================="
if [ $TOTAL_FAILED -gt 0 ]; then
    echo -e "Results: ${GREEN}$TOTAL_PASSED passed${NC}, ${RED}$TOTAL_FAILED failed${NC}"
    echo "=============================================="
    echo -e "${RED}Some tests failed!${NC}"
    exit 1
else
    echo -e "Results: ${GREEN}$TOTAL_PASSED passed${NC}"
    echo "=============================================="
    echo -e "${GREEN}🎉 All tests passed!${NC}"
    exit 0
fi
