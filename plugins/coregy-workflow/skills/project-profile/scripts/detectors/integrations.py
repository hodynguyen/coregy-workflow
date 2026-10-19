"""Load existing integrations from profile.yaml."""
import os


def load_existing_integrations(cwd):
    """Load the integrations section from an existing profile.yaml.

    This preserves user-configured integrations (github, linear, jira)
    across profile re-detection runs.
    """
    profile_path = os.path.join(cwd, ".coregy", "profile.yaml")
    try:
        with open(profile_path, "r") as f:
            content = f.read()
    except (FileNotFoundError, PermissionError):
        return None

    # Simple YAML parser for the integrations section
    integrations = {}
    in_integrations = False
    for line in content.splitlines():
        stripped = line.strip()
        if line.startswith("integrations:"):
            in_integrations = True
            continue
        if in_integrations:
            if stripped and not stripped.startswith("#"):
                if line[0] != " " and line[0] != "\t":
                    # New top-level key, stop
                    break
                parts = stripped.split(":", 1)
                if len(parts) == 2:
                    key = parts[0].strip()
                    val = parts[1].strip()
                    if val == "true":
                        integrations[key] = True
                    elif val == "false":
                        integrations[key] = False
                    else:
                        integrations[key] = val

    return integrations if integrations else None
