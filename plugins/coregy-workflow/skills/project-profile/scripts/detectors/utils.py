"""Shared utility functions for reading config files."""
import json


def read_json(path):
    try:
        with open(path, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, FileNotFoundError, PermissionError):
        return None


def read_lines(path):
    try:
        with open(path, "r") as f:
            return f.read().lower()
    except (FileNotFoundError, PermissionError):
        return ""
