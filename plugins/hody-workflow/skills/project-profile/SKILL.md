---
name: project-profile
description: Use this skill when user asks to "detect project stack", "init hody", "setup hody workflow", or when you need to understand the current project's technology stack.
---

# Project Profile

Auto-detect project tech stack and generate `.hody/profile.yaml`.

## When to Use

- User runs `/hody-workflow:init`
- User asks about the project's tech stack
- An agent needs to know the current stack before performing work

## Usage

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/project-profile/scripts/detect_stack.py --cwd <project-root>
```

### Options

| Flag | Description |
|------|-------------|
| `--cwd <path>` | Project root directory (default: `.`) |
| `--output <path>` | Custom output path (default: `<cwd>/.hody/profile.yaml`) |
| `--json` | Output as JSON instead of YAML |
| `--dry-run` | Print to stdout without writing file |

## What It Detects

| Category | Sources Scanned |
|----------|----------------|
| Node.js (React, Vue, Angular, Svelte, SvelteKit, Next, Nuxt, Express, Fastify, Nest) | `package.json` |
| Go (Gin, Echo, Fiber) | `go.mod` |
| Python (Django, FastAPI, Flask) | `requirements.txt`, `pyproject.toml`, `Pipfile`, `setup.py` |
| Rust (Actix-web, Rocket, Axum) | `Cargo.toml` |
| Java/Kotlin (Spring Boot, Quarkus, Micronaut) | `pom.xml`, `build.gradle`, `build.gradle.kts` |
| C#/.NET (ASP.NET Core, Blazor, Entity Framework) | `.csproj`, `.sln`, `global.json` |
| Ruby (Rails, Sinatra, Hanami) | `Gemfile` |
| PHP (Laravel, Symfony, Magento) | `composer.json` |
| Monorepo (Nx, Turborepo, Lerna, pnpm) | `nx.json`, `turbo.json`, `lerna.json`, `pnpm-workspace.yaml` |
| Database | `docker-compose.yml`, `.env`, `.env.example` |
| CI/CD | `.github/workflows/`, `.gitlab-ci.yml`, `Jenkinsfile` |
| Infrastructure | `*.tf` (Terraform), `pulumi/` |
| Conventions | Linter, formatter, PR template |

## Output

Creates `.hody/profile.yaml`:

```yaml
project:
  name: my-app
  type: fullstack
frontend:
  framework: react
  language: typescript
  testing: vitest
backend:
  framework: express
  language: typescript
  database: postgresql
  orm: prisma
devops:
  containerize: docker
  ci: github-actions
conventions:
  linter: eslint
  formatter: prettier
```

## After Detection

All agents read `.hody/profile.yaml` at runtime to adapt their behavior to the project's specific stack. The `SessionStart` hook also injects a summary into the system message.
