.PHONY: help
default: help

PYTHON ?= python3
export PYTHONPATH := src

help: ## Display this help screen
	@grep -hE '^[a-zA-Z0-9_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'
install: ## Install dependencies
	$(PYTHON) -m pip install -e ".[dev]"
build: ## Build the library version
	$(PYTHON) -m build
serve: ## Run the web app on http://127.0.0.1:8000 (never imports on its own)
	$(PYTHON) -m pamela.web --reload
seed: ## Fill an empty database with ~2 months of mock data, to look around
	$(PYTHON) -m pamela.seed
test: ## Run the test suite
	$(PYTHON) -m pytest --cov
lint: ## Apply the linter
	ruff check --fix
