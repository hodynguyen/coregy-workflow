"""Detect Rust project from Cargo.toml."""
import os

from detectors.utils import read_lines


def detect_rust(cwd):
    """Detect Rust project from Cargo.toml."""
    content = read_lines(os.path.join(cwd, "Cargo.toml"))
    if not content:
        return None, None

    be = {"language": "rust"}
    testing = "cargo-test"

    if "actix-web" in content:
        be["framework"] = "actix-web"
    elif "rocket" in content:
        be["framework"] = "rocket"
    elif "axum" in content:
        be["framework"] = "axum"

    if "diesel" in content:
        be["orm"] = "diesel"
    elif "sqlx" in content:
        be["orm"] = "sqlx"
    elif "sea-orm" in content:
        be["orm"] = "sea-orm"

    return be if be.get("framework") else None, testing
