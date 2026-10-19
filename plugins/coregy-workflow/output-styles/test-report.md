# Test Report

> Used by: **unit-tester**, **integration-tester**
> Copy this template structure when producing test output.

---

## Coverage Summary

- **Files Tested**: [count]
- **Test Cases Written**: [count]
- **Coverage Areas**: Happy path, edge cases, error handling, boundaries

## Test Files Created

| File | Description | Tests |
|------|-------------|-------|
| `tests/auth.test.ts` | Authentication flows | 12 |
| `tests/user.test.ts` | User operations | 8 |

## Test Categories

### Happy Path
- `should create user with valid data`
- `should return user by ID`

### Edge Cases
- `should handle empty input gracefully`
- `should reject values at boundary limits`

### Error Handling
- `should return 404 for non-existent resource`
- `should handle database connection failure`

### Boundary Conditions
- `should handle maximum allowed input length`
- `should handle concurrent requests`

## Gaps Identified

> Business rules or specs that are unclear, missing, or untestable.

- [Gap 1: description and which spec is ambiguous]
- [Gap 2: description]

## Run Command

```bash
[command to run the tests, e.g., npm test, pytest, go test ./...]
```
