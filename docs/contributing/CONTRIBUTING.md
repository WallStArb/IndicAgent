# Contributing to IndicAgent

Thank you for your interest in contributing!

---

## Quick Start

1. Fork the repository
2. Create a feature branch: `git checkout -b feat/my-feature`
3. Follow [Code Standards](code-standards.md)
4. Write tests (see [Testing Standards](testing-standards.md))
5. Submit a pull request

---

## Development Workflow

### Setting Up

See [Installation Guide](../getting-started/installation.md)

### Adding Features

1. **Design first:** Use brainstorming → writing-plans workflow
2. **TDD:** Write tests before implementation
3. **Small commits:** Frequent, focused commits
4. **Documentation:** Update docs with code changes

### Plugin Development

See [Adding Plugins Guide](../guides/adding-plugins.md)

---

## Pull Request Process

1. Update STATUS.md if adding plugins or changing versions
2. Add tests for new functionality
3. Ensure all tests pass: `pytest tests/`
4. Update relevant documentation
5. Use conventional commits: `feat:`, `fix:`, `docs:`, etc.

---

## Code Review

All PRs require review. See [Code Standards](code-standards.md) for what we look for.

---

## Questions?

- **Current Status:** [STATUS.md](../STATUS.md)
- **Roadmap:** [MASTER_ROADMAP.md](../roadmap/MASTER_ROADMAP.md)
- **Architecture:** [Concepts](../concepts/)
