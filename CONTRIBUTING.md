# Contributing to jupiter-swap-python

## Setup

```bash
git clone https://github.com/JinUltimate1995/jupiter-swap-python.git
cd jupiter-swap-python
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

## Development

```bash
# Run tests
pytest -v

# Lint
ruff check jupiter_swap/ tests/

# Type check
mypy jupiter_swap/
```

## Pull Requests

1. Fork the repo
2. Create a feature branch
3. Add tests for new functionality
4. Ensure all checks pass
5. Submit a PR
