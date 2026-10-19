"""Detect frontend and backend root directories."""
import os


def detect_directories(cwd, has_frontend, has_backend):
    """Detect frontend.dir and backend.dir based on project structure.

    Returns (frontend_dir, backend_dir) — either may be None.
    """
    fe_dir = _detect_frontend_dir(cwd) if has_frontend else None
    be_dir = _detect_backend_dir(cwd, has_frontend) if has_backend else None
    return fe_dir, be_dir


def _detect_frontend_dir(cwd):
    """Detect the primary frontend directory."""
    # Next.js app router
    app_dir = os.path.join(cwd, "app")
    if os.path.isdir(app_dir) and (
        os.path.isfile(os.path.join(app_dir, "page.tsx"))
        or os.path.isfile(os.path.join(app_dir, "layout.tsx"))
    ):
        return "app"

    dir_checks = ["pages", "client", "frontend", "web", "src"]
    for d in dir_checks:
        if os.path.isdir(os.path.join(cwd, d)):
            return d

    return None


def _detect_backend_dir(cwd, has_frontend):
    """Detect the primary backend directory."""
    dir_checks = ["server", "api", "backend"]
    for d in dir_checks:
        if os.path.isdir(os.path.join(cwd, d)):
            return d

    # src/ only if no frontend (otherwise src is ambiguous)
    if not has_frontend and os.path.isdir(os.path.join(cwd, "src")):
        return "src"

    # Go convention
    if os.path.isdir(os.path.join(cwd, "cmd")):
        return "cmd"

    # Django/Rails app dir
    if os.path.isdir(os.path.join(cwd, "app")):
        return "app"

    return None
