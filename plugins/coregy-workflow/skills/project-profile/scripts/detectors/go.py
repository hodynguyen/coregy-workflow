"""Detect Go project from go.mod."""
import os

from detectors.utils import read_lines


def detect_go(cwd):
    """Detect Go project from go.mod."""
    gomod_path = os.path.join(cwd, "go.mod")
    content = read_lines(gomod_path)
    if not content:
        return None

    be = {"language": "go"}

    if "github.com/gin-gonic/gin" in content:
        be["framework"] = "gin"
    elif "github.com/labstack/echo" in content:
        be["framework"] = "echo"
    elif "github.com/gofiber/fiber" in content:
        be["framework"] = "fiber"

    if "gorm.io/gorm" in content:
        be["orm"] = "gorm"
    elif "github.com/jmoiron/sqlx" in content:
        be["orm"] = "sqlx"

    return be
