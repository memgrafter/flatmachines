# FlatAgents JavaScript SDK - Test Suite

This directory contains the complete test suite for the FlatAgents JavaScript SDK, following the same patterns and structure as the Python SDK tests.

## Directory Structure

```
tests/
├── run.sh                  # Main test runner (all test types)
├── test-env.sh             # Shared environment setup & utilities
├── vitest.config.ts        # Vitest configuration
├── unit/                   # Unit tests
│   ├── *.test.ts          # Individual unit test files
│   └── package.json       # Unit test dependencies
├── integration/            # Integration tests
│   ├── run.sh             # Integration test runner
│   └── *.integration.test.ts # Integration test files
├── e2e/                   # End-to-end tests
│   ├── run.sh             # E2E test runner
│   └── *.e2e.test.ts      # E2E test files
└── fixtures/              # Test utilities and fixtures
    ├── helpers.ts         # Test helper functions
    └── configs/           # YAML configuration examples
```

## Quick Start

### Prerequisites
- Node.js 18+
- npm 9+

### Running Tests

```bash
# Run unit tests (default)
./run.sh

# Run specific test type
./run.sh unit
./run.sh integration
./run.sh e2e
./run.sh all

# With coverage and parallel execution
./run.sh all --coverage --parallel

# Verbose output
./run.sh integration --verbose

# Watch mode
./run.sh unit --watch

# Run specific test pattern
./run.sh --pattern "unit/flatagent*.test.ts"
```

### Options
- `--verbose, -v`: Enable verbose output
- `--coverage, -c`: Generate coverage report
- `--parallel, -p`: Run tests in parallel (with 'all')
- `--watch, -w`: Watch mode for continuous testing
- `--pattern <pat>`: Run specific test pattern
- `--help, -h`: Show help message

## Test Types

### Unit Tests
- **Location**: `unit/`
- **Purpose**: Test individual components in isolation
- **Coverage**: All SDK classes and functions (FlatAgent, FlatMachine, etc.)
- **Execution**: `./run.sh` or `./run.sh unit`
- **Features**: Fast execution, comprehensive mocking, edge case coverage

### Integration Tests
- **Location**: `integration/`
- **Purpose**: Test component interactions and workflows
- **Coverage**: Real configuration loading, provider integration, persistence, MCP
- **Execution**: `./run.sh integration`
- **Features**: Real YAML configs, cross-component integration, error paths

### E2E Tests
- **Location**: `e2e/`
- **Purpose**: Test complete business scenarios
- **Coverage**: Full workflows like ETL pipelines, customer service automation
- **Execution**: `./run.sh e2e`
- **Features**: Real-world scenarios, performance testing, large datasets

## Test Infrastructure

### Shared Environment (`test-env.sh`)
Provides common setup and utilities for all test runners:
- **Environment Detection**: OS detection, Node.js/npm version checking
- **Dependency Management**: Automated npm install with error handling
- **Project Building**: Build phase with multiple fallback scripts
- **Test Environment**: Directory creation, permissions, environment variables
- **Utility Functions**: Common setup/teardown, test summary, cleanup
- **Exported Functions**: `check_node_version`, `install_dependencies`, `build_project`, etc.

### Configuration
- **Vitest Config**: Optimized for performance and coverage
- **Package JSON**: Isolated dependencies for each test type
- **Environment Variables**: Test-specific configuration

## Coverage

The test suite aims for comprehensive coverage:
- **Happy Paths**: All success scenarios
- **Error Paths**: Network failures, invalid configurations, timeouts
- **Edge Cases**: Unicode, large data, special characters
- **Performance**: Large datasets, concurrent operations

## Development

### Adding New Tests

1. **Unit Tests**: Add to `unit/` with `.test.ts` suffix
2. **Integration Tests**: Add to `integration/` with `.integration.test.ts` suffix
3. **E2E Tests**: Add to `e2e/` with `.e2e.test.ts` suffix

### Test Patterns

```typescript
// Standard test structure
import { describe, it, expect, beforeEach, afterEach } from 'vitest'
import { createMock, injectError } from './fixtures/helpers'

describe('ComponentName', () => {
  beforeEach(() => {
    // Setup
  })

  it('should handle success case', async () => {
    // Test implementation
  })

  it('should handle error case', async () => {
    // Error testing
  })
})
```

### Mock Data

Use fixtures in `fixtures/` directory:
- `helpers.ts`: Mock creation, error injection, performance helpers
- `configs/`: 14+ YAML configuration examples from `examples/`
- **Available Helpers**:
  - `createMockAgent()`, `createMockMachine()`
  - `injectError()`, `measurePerformance()`
  - `loadTestConfig()`, `createMockProvider()`

## Notes

### Current Status
- Complete test suite implementation (4000+ lines)
- Test infrastructure and runners
- Coverage of all SDK components
- Implementation phase needed to make tests pass

### Expected Failures
Tests will currently fail due to missing implementation files. This is intentional - the test suite serves as a specification for the SDK implementation.

### Integration with Python SDK
The JavaScript test suite mirrors the Python SDK structure:

| Python SDK | JavaScript SDK | Purpose |
|------------|----------------|---------|
| `tests/unit/run.sh` | `tests/run.sh unit` | Unit test execution |
| `tests/integration/run.sh` | `tests/run.sh integration` | Integration test execution |
| `uv` venv | npm package isolation | Environment isolation |
| `pytest` | `vitest` | Test framework |
| Shared setup functions | `test-env.sh` | Common utilities |

### File Permissions
All shell scripts should be executable:
```bash
chmod +x run.sh
chmod +x test-env.sh
chmod +x integration/run.sh
chmod +x e2e/run.sh
```
