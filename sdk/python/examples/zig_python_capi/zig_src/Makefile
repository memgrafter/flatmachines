# Makefile for building Zig Python C-API extension

# Detect Python configuration
PYTHON ?= python3
PYTHON_CONFIG ?= $(PYTHON)-config
PYTHON_INCLUDE := $(shell $(PYTHON_CONFIG) --includes)
PYTHON_LDFLAGS := $(shell $(PYTHON_CONFIG) --ldflags)

# Zig compiler
ZIG ?= zig

# Get Python extension suffix
EXT_SUFFIX := $(shell $(PYTHON) -c "import sysconfig; print(sysconfig.get_config_var('EXT_SUFFIX'))")

# Output library name
LIB_NAME = zigprimes$(EXT_SUFFIX)

# Build target
.PHONY: all clean

all: $(LIB_NAME)

$(LIB_NAME): prime_compute.zig
	@echo "Building Zig Python extension..."
	@echo "Python includes: $(PYTHON_INCLUDE)"
	@echo "Extension suffix: $(EXT_SUFFIX)"
	$(ZIG) build-lib prime_compute.zig \
		-dynamic \
		-lc \
		$(PYTHON_INCLUDE) \
		-O ReleaseFast \
		-femit-bin=$(LIB_NAME)
	@echo "Built: $(LIB_NAME)"

clean:
	rm -f *.so *.dylib *.dll *.pyd
	rm -f *.o *.a
	rm -rf zig-cache zig-out

install: $(LIB_NAME)
	cp $(LIB_NAME) ../src/zig_python_capi/
	@echo "Installed to ../src/zig_python_capi/"

test: $(LIB_NAME)
	@echo "Testing Zig extension..."
	$(PYTHON) -c "import sys; sys.path.insert(0, '.'); import zigprimes; print('is_prime(17):', zigprimes.is_prime(17)); print('count_primes(1, 100):', zigprimes.count_primes(1, 100)); print('nth_prime(10):', zigprimes.nth_prime(10))"
