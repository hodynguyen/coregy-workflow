# Runbook

## Development Setup

```bash
# Clone the repo
git clone git@github.com:hodynguyen/coregy-workflow.git
cd coregy-workflow

# No install step — no dependencies needed for development
# PyYAML is only needed at runtime in target projects
```

## Running Tests

```bash
# Run all 110 unit tests across 17 test files
python3 -m unittest discover -s test -v

# Run a specific test file
python3 -m unittest test.test_detect_stack -v
python3 -m unittest test.test_node_detector -v

# Tests use temp directories simulating various project types
# (React, Go, Python, Rust, Java, C#, Ruby, PHP, monorepo)
# Also covers: quality gate, KB sync, auto-refresh, conventions, serializer
```

## Local Plugin Testing

```bash
# Install plugin locally for testing
claude
/plugin marketplace add hodynguyen/coregy-workflow
/plugin install coregy-workflow@coregy
# Restart Claude Code after install

# Test in any project
cd ~/projects/some-project
claude
/coregy-workflow:init
```

## Release Process

1. Code and test locally
2. Bump version in `plugins/coregy-workflow/.claude-plugin/plugin.json`
3. Commit with conventional format: `<type>: <description>`
4. Push to `main` branch
5. Users update via `/plugin marketplace update` + `/plugin update coregy-workflow@coregy`

## Pre-push Checklist

- [ ] Version bumped in `plugin.json` (for non-README changes)
- [ ] Tests pass: `python3 -m unittest discover -s test -v`
- [ ] Commit message follows format: `<type>: <description>`
- [ ] No sensitive files committed (`.env`, credentials, `settings.local.json`)

## Common Issues

| Issue | Fix |
|-------|-----|
| Plugin not loading after install | Restart Claude Code |
| Plugin showing old version | Run `/plugin marketplace update` then `/plugin update coregy-workflow@coregy` |
| `/coregy-workflow:init` not found | Check plugin installed: `/plugin list` |
| Cache corrupted | Delete cache: `rm -rf ~/.claude/plugins/cache/coregy/coregy-workflow/` then reinstall |
| `detect_stack.py` fails | Ensure Python 3.8+ available, check PyYAML installed in target project |
