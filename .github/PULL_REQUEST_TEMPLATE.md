## Description

<!-- Briefly describe what this PR does and why. Link to relevant issue(s). -->

Closes #

## Type of Change

- [ ] Bug fix (non-breaking change that fixes an issue)
- [ ] New feature (non-breaking change that adds functionality)
- [ ] Breaking change (fix or feature that would cause existing functionality to change)
- [ ] Refactor (no functional change)
- [ ] Infrastructure / config change
- [ ] Documentation

## Optimizer / Market Changes

<!-- If this PR touches the dispatch optimizer or market code, answer these: -->

- [ ] This PR does NOT touch the optimizer or market integration code
- [ ] Optimizer changes are tested with at least one full dispatch cycle scenario
- [ ] Settlement calculation changes have been validated against known results
- [ ] No changes to market bid/offer schemas that break existing parsing

## Testing

- [ ] Unit tests added / updated (`pytest tests/`)
- [ ] Integration tests pass locally
- [ ] Backtesting results are acceptable (attach or link if changed strategy logic)
- [ ] Manual testing performed (describe below)

**Manual testing steps:**

1.
2.

## Performance Impact

<!-- Note any known performance regressions or improvements. -->

- Solver time delta: N/A
- API latency delta: N/A

## Database Migrations

- [ ] No database migrations required
- [ ] Migration added in `alembic/versions/`
- [ ] Migration is reversible (has `downgrade()` function)
- [ ] Migration tested against a copy of production data

## Deployment Notes

<!-- Any special deployment steps, config changes, or environment variables needed? -->

- [ ] No special deployment steps required
- [ ] New environment variables added (documented in `config/base.yaml`)
- [ ] Infrastructure changes required (Terraform / Helm changes included)

## Checklist

- [ ] Code follows project style guide (`ruff check` passes)
- [ ] Type annotations added (`mypy` passes)
- [ ] Self-review completed
- [ ] Documentation updated (docstrings, config comments)
- [ ] No secrets or credentials committed
- [ ] CODEOWNERS notified if touching sensitive modules
