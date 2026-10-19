"""Detect Ruby project from Gemfile."""
import os

from detectors.utils import read_lines


def detect_ruby(cwd):
    """Detect Ruby project from Gemfile."""
    content = read_lines(os.path.join(cwd, "Gemfile"))
    if not content:
        return None, None

    be = {"language": "ruby"}
    testing = None

    if "rails" in content or "railties" in content:
        be["framework"] = "rails"
    elif "sinatra" in content:
        be["framework"] = "sinatra"
    elif "hanami" in content:
        be["framework"] = "hanami"

    if "activerecord" in content or "rails" in content:
        be["orm"] = "activerecord"
    elif "sequel" in content:
        be["orm"] = "sequel"

    if "rspec" in content:
        testing = "rspec"
    elif "minitest" in content:
        testing = "minitest"

    return be if be.get("framework") else None, testing
