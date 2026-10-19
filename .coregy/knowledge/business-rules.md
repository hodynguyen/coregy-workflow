# Business Rules

> To be filled by the team as business rules are defined.

## Plugin Behavior Rules

### Rule: Knowledge base never overwrites
- **Description**: When running `/coregy-workflow:init`, existing knowledge base files are never overwritten
- **Conditions**: `.coregy/knowledge/*.md` files already exist
- **Actions**: Skip file creation, only create missing files
- **Exceptions**: None — this is a hard rule to prevent data loss

### Rule: Profile detection scans config files only
- **Description**: `detect_stack.py` only reads config/manifest files, never scans full codebase
- **Conditions**: Always
- **Actions**: Read package.json, go.mod, requirements.txt, Cargo.toml, pom.xml, .csproj, Gemfile, composer.json, etc.
- **Exceptions**: None — scanning the full codebase would be too slow for the 60s hook timeout

### Rule: Agents are static, behavior is dynamic
- **Description**: Agent prompts are static Markdown — they adapt by reading profile.yaml at runtime
- **Conditions**: Always (Claude Code plugin constraint)
- **Actions**: Each agent bootstraps by reading `.coregy/profile.yaml` and relevant knowledge files
- **Exceptions**: None
