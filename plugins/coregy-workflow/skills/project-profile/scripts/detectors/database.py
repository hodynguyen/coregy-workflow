"""Detect database from common config patterns."""
import os

from detectors.utils import read_lines


def detect_database(cwd):
    """Try to detect database from common config patterns."""
    db = None
    for fname in ["docker-compose.yml", "docker-compose.yaml", ".env", ".env.example"]:
        content = read_lines(os.path.join(cwd, fname))
        if "postgres" in content or "postgresql" in content:
            db = "postgresql"
            break
        elif "mysql" in content or "mariadb" in content:
            db = "mysql"
            break
        elif "mongodb" in content or "mongo:" in content:
            db = "mongodb"
            break
        elif "redis" in content:
            if not db:
                db = "redis"
    return db
