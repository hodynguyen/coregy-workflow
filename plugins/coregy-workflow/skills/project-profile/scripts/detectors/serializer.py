"""YAML serialization and CLI entry point."""
import argparse
import json
import os
import sys

from detectors.profile import build_profile


def to_yaml(data, indent=0):
    """Convert dict to YAML string without external dependencies."""
    lines = []
    prefix = "  " * indent
    for key, value in data.items():
        if isinstance(value, dict):
            lines.append(f"{prefix}{key}:")
            lines.append(to_yaml(value, indent + 1))
        elif isinstance(value, list):
            lines.append(f"{prefix}{key}:")
            for item in value:
                if isinstance(item, dict):
                    first = True
                    for k, v in item.items():
                        if first:
                            lines.append(f"{prefix}  - {k}: {v}")
                            first = False
                        else:
                            lines.append(f"{prefix}    {k}: {v}")
                else:
                    lines.append(f"{prefix}  - {item}")
        elif isinstance(value, bool):
            lines.append(f"{prefix}{key}: {'true' if value else 'false'}")
        elif value is None:
            lines.append(f"{prefix}{key}: null")
        else:
            lines.append(f"{prefix}{key}: {value}")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Detect project tech stack")
    parser.add_argument("--cwd", default=".", help="Project root directory")
    parser.add_argument("--output", default=None, help="Output path (default: <cwd>/.coregy/profile.yaml)")
    parser.add_argument("--json", action="store_true", help="Output as JSON instead of YAML")
    parser.add_argument("--deep", action="store_true", help="Run deep dependency analysis (slower, runs package manager commands)")
    parser.add_argument("--dry-run", action="store_true", help="Print to stdout, don't write file")
    args = parser.parse_args()

    cwd = os.path.abspath(args.cwd)
    if not os.path.isdir(cwd):
        print(f"Error: {cwd} is not a directory", file=sys.stderr)
        sys.exit(1)

    profile = build_profile(cwd, deep=args.deep)

    if args.json:
        output = json.dumps(profile, indent=2)
    else:
        output = to_yaml(profile)

    if args.dry_run:
        print(output)
        sys.exit(0)

    # Write to file
    output_path = args.output or os.path.join(cwd, ".coregy", "profile.yaml")
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    with open(output_path, "w") as f:
        f.write(output + "\n")

    print(f"Profile written to {output_path}")
    print(f"Detected: {profile['project'].get('type', 'unknown')} project")

    # Print summary
    if "frontend" in profile:
        fe = profile["frontend"]
        print(f"  Frontend: {fe.get('framework', '?')} ({fe.get('language', '?')})")
    if "backend" in profile:
        be = profile["backend"]
        print(f"  Backend: {be.get('framework', '?')} ({be.get('language', '?')})")
    if "devops" in profile:
        devops = profile["devops"]
        parts = [f"{k}: {v}" for k, v in devops.items()]
        print(f"  DevOps: {', '.join(parts)}")
