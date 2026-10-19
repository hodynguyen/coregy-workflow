"""Detect Python project from requirements.txt or pyproject.toml."""
import os

from detectors.utils import read_lines


def detect_python(cwd):
    """Detect Python project from requirements.txt or pyproject.toml."""
    content = ""
    for fname in ["requirements.txt", "Pipfile", "pyproject.toml", "setup.py"]:
        content += read_lines(os.path.join(cwd, fname))

    if not content:
        return None, None

    be = {"language": "python"}
    testing = None

    if "django" in content:
        be["framework"] = "django"
    elif "fastapi" in content:
        be["framework"] = "fastapi"
    elif "flask" in content:
        be["framework"] = "flask"

    if "sqlalchemy" in content:
        be["orm"] = "sqlalchemy"
    elif "django" in content:
        be["orm"] = "django-orm"

    if "pytest" in content:
        testing = "pytest"
    elif "unittest" in content:
        testing = "unittest"

    return be if be.get("framework") else None, testing
