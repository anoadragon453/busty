.PHONY: run lint format type-check help

help: ## Show this help message
	@echo "Available commands:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-15s\033[0m %s\n", $$1, $$2}'

run: ## Run the bot
	uv run python -m busty.main

lint: ## Lint the code with ruff
	uv run ruff check --fix .

format: ## Format the code with ruff
	uv run ruff format .

type-check: ## Type check the code with mypy
	uv run mypy src/