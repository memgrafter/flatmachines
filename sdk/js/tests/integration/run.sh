#!/bin/bash
# Integration Test Runner
# Runs all integration tests in isolated environments

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
echo -e "${BLUE}FlatAgents Integration Tests${NC}"
echo "=============================================="
echo ""

# Track results
PASSED=0
FAILED=0
FAILED_TESTS=""

# Function to run a specific integration test
run_integration_test() {
    local test_dir="$1"
    local test_name=$(basename "$test_dir")
    
    if [ ! -d "$test_dir" ]; then
        echo -e "${RED}❌ Integration test directory '$test_name' not found.${NC}"
        ((FAILED++))
        FAILED_TESTS="$FAILED_TESTS $test_name"
        return 1
    fi
    
    echo -e "${YELLOW}Running: $test_name${NC}"
    echo "----------------------------------------------"
    
    cd "$test_dir"
    
    # Create package.json if it doesn't exist
    if [ ! -f "package.json" ]; then
        cat > package.json << EOF
{
  "name": "flatagents-integration-$test_name",
  "version": "1.0.0",
  "private": true,
  "scripts": {
    "test": "vitest run",
    "test:verbose": "vitest run --verbose"
  },
  "devDependencies": {
    "vitest": "^1.0.0",
    "@vitest/coverage-v8": "^1.0.0",
    "typescript": "^5.0.0"
  }
}
EOF
    fi
    
    # Install dependencies
    echo "📦 Installing dependencies..."
    npm install --silent 2>/dev/null || {
        echo -e "${RED}❌ Failed to install dependencies for $test_name${NC}"
        cd ..
        ((FAILED++))
        FAILED_TESTS="$FAILED_TESTS $test_name"
        return 1
    }
    
    # Run the integration test
    echo "🧪 Running integration test..."
    if npx vitest run --reporter=verbose; then
        echo -e "${GREEN}✓ $test_name PASSED${NC}"
        ((PASSED++))
        RESULT=0
    else
        echo -e "${RED}✗ $test_name FAILED${NC}"
        ((FAILED++))
        FAILED_TESTS="$FAILED_TESTS $test_name"
        RESULT=1
    fi
    
    cd ..
    echo ""
    return $RESULT
}

# Find and run all test suites
for test_dir in "$SCRIPT_DIR"/*/; do
    if [ -f "$test_dir"/*.test.ts ] || [ -f "$test_dir"/*.spec.ts ]; then
        run_integration_test "$test_dir" || true
    fi
done

# Also run root-level integration tests
for test_file in "$SCRIPT_DIR"/*.integration.test.ts; do
    if [ -f "$test_file" ]; then
        test_name=$(basename "$test_file" .integration.test.ts)
        echo -e "${YELLOW}Running: $test_name${NC}"
        echo "----------------------------------------------"
        
        cd "$SCRIPT_DIR"
        
        # Run the integration test
        if npx vitest run "$test_file" --reporter=verbose; then
            echo -e "${GREEN}✓ $test_name PASSED${NC}"
            ((PASSED++))
        else
            echo -e "${RED}✗ $test_name FAILED${NC}"
            ((FAILED++))
            FAILED_TESTS="$FAILED_TESTS $test_name"
        fi
        
        echo ""
    fi
done

# Summary
echo "=============================================="
echo -e "Results: ${GREEN}$PASSED passed${NC}${FAILED -gt 0 && echo -e ", ${RED}$FAILED failed${NC}" || echo ""}"
echo "=============================================="

if [ $FAILED -gt 0 ]; then
    echo -e "${RED}Failed tests:$FAILED_TESTS${NC}"
    exit 1
fi

echo -e "${GREEN}All integration tests passed!${NC}"