# Cardano Forge Manager - Makefile
# 
# This Makefile provides automation for development, testing, and deployment
# tasks. It sets up isolated virtual environments and runs comprehensive
# test suites without affecting the user's working machine.

# Configuration
PYTHON := python3
VENV_DIR := venv
VENV_PYTHON := $(VENV_DIR)/bin/python
VENV_PIP := $(VENV_DIR)/bin/pip
VENV_PYTEST := $(VENV_DIR)/bin/pytest
REQUIREMENTS := requirements.txt

# Project directories
SRC_DIR := src
TESTS_DIR := tests
DOCS_DIR := docs
EXAMPLES_DIR := examples

# Test configuration
TEST_TIMEOUT := 30
COVERAGE_MIN := 25
PYTEST_ARGS := -v --tb=short --timeout=$(TEST_TIMEOUT)

# Colors for output
RED := \033[0;31m
GREEN := \033[0;32m
YELLOW := \033[0;33m
BLUE := \033[0;34m
NC := \033[0m

# Default target
.DEFAULT_GOAL := help

.PHONY: help
help: ## Show this help message
	@echo "$(BLUE)Cardano Forge Manager - Development Automation$(NC)"
	@echo ""
	@echo "$(GREEN)Setup Commands:$(NC)"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | grep -E '^(venv|install|clean)' | awk 'BEGIN {FS = ":.*?## "}; {printf "  $(YELLOW)%-15s$(NC) %s\n", $$1, $$2}'
	@echo ""
	@echo "$(GREEN)Testing Commands:$(NC)"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | grep -E '^test' | awk 'BEGIN {FS = ":.*?## "}; {printf "  $(YELLOW)%-15s$(NC) %s\n", $$1, $$2}'
	@echo ""
	@echo "$(GREEN)Development Commands:$(NC)"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | grep -vE '^(venv|install|clean|test)' | awk 'BEGIN {FS = ":.*?## "}; {printf "  $(YELLOW)%-15s$(NC) %s\n", $$1, $$2}'
	@echo ""
	@echo "$(BLUE)Examples:$(NC)"
	@echo "  make install          # Set up development environment"
	@echo "  make test             # Run all tests"
	@echo "  make test-multi-tenant# Run multi-tenant tests only"
	@echo "  make test-coverage    # Run tests with coverage report"

# Setup targets
.PHONY: venv
venv: ## Create Python virtual environment
	@echo "$(GREEN)Creating virtual environment...$(NC)"
	@$(PYTHON) -m venv $(VENV_DIR)
	@echo "$(GREEN)Virtual environment created at $(VENV_DIR)$(NC)"
	@echo "$(YELLOW)To activate: source $(VENV_DIR)/bin/activate$(NC)"


.PHONY: install
install: $(VENV_DIR) ## Install dependencies in virtual environment
	@echo "$(GREEN)Installing dependencies...$(NC)"
	@$(VENV_PIP) install --upgrade pip setuptools wheel
	@if [ -f $(REQUIREMENTS) ]; then \
		echo "$(BLUE)Installing requirements.txt...$(NC)"; \
		$(VENV_PIP) install -r $(REQUIREMENTS); \
	else \
		echo "$(BLUE)Installing development dependencies...$(NC)"; \
		$(VENV_PIP) install pytest pytest-cov pytest-timeout black flake8 mypy requests kubernetes; \
	fi
	@echo "$(GREEN)Dependencies installed successfully$(NC)"

# Testing targets
.PHONY: test
test: install ## Run all tests
	@echo "$(GREEN)Running all tests...$(NC)"
	@PYTHONPATH=$(SRC_DIR) $(VENV_PYTEST) $(PYTEST_ARGS) $(TESTS_DIR)

.PHONY: test-multi-tenant
test-multi-tenant: install ## Run multi-tenant tests only
	@echo "$(GREEN)Running multi-tenant tests...$(NC)"
	@PYTHONPATH=$(SRC_DIR) $(VENV_PYTEST) $(PYTEST_ARGS) $(TESTS_DIR)/test_cluster_management.py::TestMultiTenantSupport

.PHONY: test-cluster
test-cluster: install ## Run cluster management tests
	@echo "$(GREEN)Running cluster management tests...$(NC)"
	@PYTHONPATH=$(SRC_DIR) $(VENV_PYTEST) $(PYTEST_ARGS) $(TESTS_DIR)/test_cluster_management.py

.PHONY: test-forgemanager
test-forgemanager: install ## Run forge manager tests
	@echo "$(GREEN)Running forge manager tests...$(NC)"
	@PYTHONPATH=$(SRC_DIR) $(VENV_PYTEST) $(PYTEST_ARGS) $(TESTS_DIR)/test_forgemanager.py

.PHONY: test-coverage
test-coverage: install ## Run tests with coverage report
	@echo "$(GREEN)Running tests with coverage...$(NC)"
	@PYTHONPATH=$(SRC_DIR) $(VENV_PYTEST) $(PYTEST_ARGS) \
		--cov=$(SRC_DIR) \
		--cov-report=term-missing \
		--cov-report=html:htmlcov \
		--cov-fail-under=$(COVERAGE_MIN) \
		$(TESTS_DIR)
	@echo "$(GREEN)Coverage report generated in htmlcov/index.html$(NC)"

.PHONY: test-specific
test-specific: install ## Run specific test (use TEST=test_name)
	@if [ -z "$(TEST)" ]; then \
		echo "$(RED)Please specify TEST variable, e.g., make test-specific TEST=test_pool_isolation$(NC)"; \
		exit 1; \
	fi
	@echo "$(GREEN)Running specific test: $(TEST)$(NC)"
	@PYTHONPATH=$(SRC_DIR) $(VENV_PYTEST) $(PYTEST_ARGS) -k "$(TEST)" $(TESTS_DIR)

# Development targets
.PHONY: lint
lint: $(VENV_DIR) ## Run code linting
	@echo "$(GREEN)Running code linting...$(NC)"
	@$(VENV_DIR)/bin/flake8 $(SRC_DIR) $(TESTS_DIR) --max-line-length=88 --extend-ignore=E203,W503 || true
	@echo "$(GREEN)Linting completed$(NC)"

.PHONY: format
format: $(VENV_DIR) ## Format code with black
	@echo "$(GREEN)Formatting code with black...$(NC)"
	@$(VENV_DIR)/bin/black $(SRC_DIR) $(TESTS_DIR) --line-length=88 || true
	@echo "$(GREEN)Code formatted$(NC)"

.PHONY: check
check: $(VENV_DIR) lint format ## Run all code quality checks
	@echo "$(GREEN)All code quality checks completed$(NC)"

# Documentation targets
.PHONY: docs
docs: ## Show available documentation
	@echo "$(GREEN)Documentation is in $(DOCS_DIR)/$(NC)"
	@echo "$(BLUE)Available documentation:$(NC)"
	@ls -1 $(DOCS_DIR)/*.md 2>/dev/null | sed 's/^/  /' || echo "  No documentation found"

# Utility targets
.PHONY: env
env: $(VENV_DIR) ## Show environment information
	@echo "$(GREEN)Environment Information:$(NC)"
	@echo "Python version: $$($(VENV_PYTHON) --version 2>/dev/null || echo 'Not found')"
	@echo "Virtual environment: $(VENV_DIR)"
	@echo "Project directory: $$(pwd)"
	@echo "Source directory: $(SRC_DIR)"
	@echo "Tests directory: $(TESTS_DIR)"

.PHONY: clean
clean: ## Clean up generated files and virtual environment
	@echo "$(GREEN)Cleaning up...$(NC)"
	@rm -rf $(VENV_DIR)
	@rm -rf .pytest_cache
	@rm -rf htmlcov
	@rm -rf .coverage
	@rm -rf dist
	@rm -rf *.egg-info
	@find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	@find . -type f -name "*.pyc" -delete 2>/dev/null || true
	@echo "$(GREEN)Cleanup completed$(NC)"

.PHONY: reset
reset: clean install ## Reset environment (clean + install)
	@echo "$(GREEN)Environment reset completed$(NC)"

# CI/CD targets
.PHONY: ci
ci: install check test-coverage ## Run full CI pipeline locally
	@echo "$(GREEN)Full CI pipeline completed successfully!$(NC)"

.PHONY: quick-test
quick-test: install ## Run quick test suite
	@echo "$(GREEN)Running quick tests...$(NC)"
	@PYTHONPATH=$(SRC_DIR) $(VENV_PYTEST) -q --tb=no $(TESTS_DIR)

.PHONY: status
status: ## Show project status
	@echo "$(GREEN)Project Status:$(NC)"
	@echo "Virtual environment: $$([ -d $(VENV_DIR) ] && echo '✓ Created' || echo '✗ Not found')"
	@echo "Dependencies: $$([ -f $(VENV_DIR)/bin/pytest ] && echo '✓ Installed' || echo '✗ Not installed')"
	@echo "Tests: $$([ -d $(TESTS_DIR) ] && echo "✓ $$(find $(TESTS_DIR) -name "*.py" | wc -l) test files" || echo '✗ No tests found')"
	@echo "Documentation: $$([ -d $(DOCS_DIR) ] && echo "✓ $$(find $(DOCS_DIR) -name "*.md" | wc -l) documents" || echo '✗ No docs found')"

# Examples
.PHONY: examples
examples: ## List available deployment examples
	@echo "$(GREEN)Available deployment examples:$(NC)"
	@find $(EXAMPLES_DIR) -name "*.yaml" -o -name "*.yml" 2>/dev/null | sort | sed 's/^/  /' || echo "  No examples found"

# Make sure intermediate files are not deleted
.PRECIOUS: $(VENV_DIR)

# Ensure make doesn't get confused by files with same names as targets
.PHONY: all