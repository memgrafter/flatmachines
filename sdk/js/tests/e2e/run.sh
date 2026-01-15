#!/bin/bash
# E2E Test Runner
# Runs end-to-end tests that simulate real-world workflows

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# Load shared environment
if [ -f "../test-env.sh" ]; then
    source ../test-env.sh
else
    echo "Error: test-env.sh not found"
    exit 1
fi

echo "=============================================="
echo -e "${BLUE}FlatAgents E2E Tests${NC}"
echo "=============================================="
echo ""

# Parse arguments
VERBOSE=false
COVERAGE=false
KEEP_ENV=false
TEST_PATTERN="e2e/**/*.test.ts"

while [[ $# -gt 0 ]]; do
  case $1 in
    --verbose|-v)
      VERBOSE=true
      shift
      ;;
    --coverage|-c)
      COVERAGE=true
      shift
      ;;
    --keep-env|-k)
      KEEP_ENV=true
      shift
      ;;
    --pattern|-p)
      TEST_PATTERN="$2"
      shift 2
      ;;
    --help|-h)
      echo "Usage: $0 [--verbose] [--coverage] [--keep-env] [--pattern PATTERN]"
      echo ""
      echo "Options:"
      echo "  --verbose, -v    Enable verbose output"
      echo "  --coverage, -c   Generate coverage report"
      echo "  --keep-env, -k   Keep test environment after run"
      echo "  --pattern, -p    Test file pattern"
      echo "  --help, -h       Show this help message"
      exit 0
      ;;
    *)
      shift
      ;;
  esac
done

# Track results
PASSED=0
FAILED=0
FAILED_TESTS=""

# Function to setup test environment
setup_test_env() {
    echo -e "${YELLOW}🔧 Setting up E2E test environment...${NC}"
    
    # Install dependencies
    if [ -f "package.json" ]; then
        npm install --silent
    else
        echo -e "${RED}❌ No package.json found${NC}"
        return 1
    fi
    
    # Build the main package if needed
    if [ -d "../../src" ] && [ -f "../../package.json" ]; then
        echo -e "${YELLOW}🏗️  Building flatagents package...${NC}"
        cd ../..
        npm run build 2>/dev/null || echo "Build failed, continuing anyway"
        ln -sf "$(pwd)" node_modules/flatagents 2>/dev/null || echo "Symlink creation failed"
        cd tests
    
    fi
    
    # Ensure test data directory exists
    mkdir -p test-data/fixtures
    mkdir -p test-data/results
    
    return 0
}

# Function to cleanup test environment
cleanup_test_env() {
    if [ "$KEEP_ENV" = false ]; then
        echo -e "${YELLOW}🧹 Cleaning up test environment...${NC}"
        rm -rf test-data/temp 2>/dev/null || true
    fi
}

# Function to run E2E test
run_e2e_test() {
    local test_file="$1"
    local test_name=$(basename "$test_file" .e2e.test.ts)
    
    echo -e "${YELLOW}🧪 Running E2E test: $test_name${NC}"
    echo "----------------------------------------------"
    
    # Run the test
    local test_args=""
    if [ "$VERBOSE" = true ]; then
        test_args="$test_args --verbose"
    fi
    if [ "$COVERAGE" = true ]; then
        test_args="$test_args --coverage"
    fi
    
    if npx vitest run "$test_file" --reporter=verbose $test_args; then
        echo -e "${GREEN}✓ $test_name PASSED${NC}"
        ((PASSED++))
        return 0
    else
        echo -e "${RED}✗ $test_name FAILED${NC}"
        ((FAILED++))
        FAILED_TESTS="$FAILED_TESTS $test_name"
        return 1
    fi
}

# Setup environment
if ! setup_test_env; then
    echo -e "${RED}❌ Failed to setup test environment${NC}"
    exit 1
fi

# Find and run all E2E tests
cd "$SCRIPT_DIR"

# Find E2E test files
E2E_FILES=(e2e/*.e2e.test.ts)
if [ ${#E2E_FILES[@]} -eq 0 ] || [ ! -f "${E2E_FILES[0]}" ]; then
    echo -e "${RED}❌ No E2E test files found matching pattern: $TEST_PATTERN${NC}"
    cleanup_test_env
    exit 1
fi

echo "Found ${#E2E_FILES[@]} E2E test files"
echo ""

# Run each E2E test
for test_file in "${E2E_FILES[@]}"; do
    if [ -f "$test_file" ]; then
        run_e2e_test "$test_file" || true
        echo ""
    fi
done

# Cleanup
cleanup_test_env

# Summary
echo "=============================================="
echo -e "E2E Results: ${GREEN}$PASSED passed${NC}${FAILED -gt 0 && echo -e ", ${RED}$FAILED failed${NC}" || echo ""}"
echo "=============================================="

if [ $FAILED -gt 0 ]; then
    echo -e "${RED}Failed E2E tests:$FAILED_TESTS${NC}"
    exit 1
fi

echo -e "${GREEN}All E2E tests passed!${NC}"