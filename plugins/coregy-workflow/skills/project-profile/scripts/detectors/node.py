"""Detect Node.js project from package.json."""
import os

from detectors.utils import read_json


def detect_node(cwd):
    """Detect Node.js project from package.json."""
    pkg = read_json(os.path.join(cwd, "package.json"))
    if not pkg:
        return None, None

    deps = {}
    deps.update(pkg.get("dependencies", {}))
    dev_deps = pkg.get("devDependencies", {})

    result = {"language": "javascript"}

    # TypeScript
    if "typescript" in dev_deps or "typescript" in deps:
        result["language"] = "typescript"

    # Frontend framework
    fe = {}
    if "react" in deps or "react-dom" in deps:
        fe["framework"] = "react"
    elif "vue" in deps:
        fe["framework"] = "vue"
    elif "svelte" in deps:
        fe["framework"] = "svelte"
    elif "@angular/core" in deps:
        fe["framework"] = "angular"

    # SSR/meta frameworks (override)
    if "next" in deps:
        fe["framework"] = "next"
    elif "nuxt" in deps:
        fe["framework"] = "nuxt"
    elif "@sveltejs/kit" in deps or "@sveltejs/kit" in dev_deps:
        fe["framework"] = "sveltekit"

    # State management
    if "zustand" in deps:
        fe["state"] = "zustand"
    elif "redux" in deps or "@reduxjs/toolkit" in deps:
        fe["state"] = "redux"
    elif "pinia" in deps:
        fe["state"] = "pinia"
    elif "mobx" in deps:
        fe["state"] = "mobx"

    # Styling
    if "tailwindcss" in deps or "tailwindcss" in dev_deps:
        fe["styling"] = "tailwind"
    elif "styled-components" in deps:
        fe["styling"] = "styled-components"
    elif "sass" in dev_deps or "node-sass" in dev_deps:
        fe["styling"] = "scss"

    # Build tool
    if "vite" in dev_deps:
        fe["build"] = "vite"
    elif "webpack" in dev_deps:
        fe["build"] = "webpack"
    elif "esbuild" in dev_deps:
        fe["build"] = "esbuild"

    if fe.get("framework"):
        fe["language"] = result["language"]

    # Backend framework
    be = {}
    if "express" in deps:
        be["framework"] = "express"
    elif "fastify" in deps:
        be["framework"] = "fastify"
    elif "@nestjs/core" in deps:
        be["framework"] = "nest"

    # ORM
    if "prisma" in dev_deps or "@prisma/client" in deps:
        be["orm"] = "prisma"
    elif "drizzle-orm" in deps:
        be["orm"] = "drizzle"
    elif "typeorm" in deps:
        be["orm"] = "typeorm"
    elif "sequelize" in deps:
        be["orm"] = "sequelize"

    if be.get("framework"):
        be["language"] = result["language"]

    # Testing
    testing = None
    if "vitest" in dev_deps:
        testing = "vitest"
    elif "jest" in dev_deps:
        testing = "jest"

    # E2E testing
    e2e = None
    if "playwright" in dev_deps or "@playwright/test" in dev_deps:
        e2e = "playwright"
    elif "cypress" in dev_deps:
        e2e = "cypress"

    # Linter / Formatter
    linter = None
    formatter = None
    if "eslint" in dev_deps:
        linter = "eslint"
    elif "@biomejs/biome" in dev_deps:
        linter = "biome"
    if "prettier" in dev_deps:
        formatter = "prettier"
    elif "@biomejs/biome" in dev_deps:
        formatter = "biome"

    return (
        fe if fe.get("framework") else None,
        be if be.get("framework") else None,
        testing,
        e2e,
        linter,
        formatter,
    )
