# Contributing to SlateDesk

Thanks for your interest in contributing! Here's how to get started.

## Development Setup

1. Clone the repo:
   ```bash
   git clone https://github.com/BryanBaluyut/SlateDesk.git
   cd SlateDesk
   ```

2. Copy the environment file:
   ```bash
   cp .env.example .env
   ```

3. Run with Docker:
   ```bash
   docker compose up -d
   ```

4. Or run locally (Python 3.12+):
   ```bash
   python -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   uvicorn app.main:app --reload
   ```

## Workflow

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/my-feature`
3. Make your changes
4. Run linting: `ruff check app/`
5. Run tests: `pytest tests/ -v`
6. Commit with a clear message (see below)
7. Push and open a Pull Request

## Commit Messages

Use [Conventional Commits](https://www.conventionalcommits.org/):

```
feat: add ticket export to PDF
fix: resolve SLA escalation timing bug
docs: update Azure AD setup instructions
refactor: extract email parsing logic
test: add automation trigger tests
chore: upgrade FastAPI to 0.110
```

## Code Style

- Follow PEP 8 conventions
- Use type hints where practical
- Keep functions focused and concise
- Use `ruff` for linting

## Reporting Bugs

Use the [bug report template](https://github.com/BryanBaluyut/SlateDesk/issues/new?template=bug_report.yml) when filing issues.

## License

By contributing, you agree that your contributions will be licensed under the MIT License.
