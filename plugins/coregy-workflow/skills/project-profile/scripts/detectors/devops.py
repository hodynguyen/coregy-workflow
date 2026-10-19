"""Detect CI/CD, containerization, infrastructure, deploy, and monitoring."""
import os

from detectors.utils import read_json, read_lines


def detect_devops(cwd):
    """Detect CI/CD, containerization, infrastructure, deploy, and monitoring."""
    devops = {}

    # Container
    if os.path.isfile(os.path.join(cwd, "Dockerfile")):
        devops["containerize"] = "docker"
    elif os.path.isfile(os.path.join(cwd, "docker-compose.yml")) or os.path.isfile(
        os.path.join(cwd, "docker-compose.yaml")
    ):
        devops["containerize"] = "docker"

    # CI
    if os.path.isdir(os.path.join(cwd, ".github", "workflows")):
        devops["ci"] = "github-actions"
    elif os.path.isfile(os.path.join(cwd, ".gitlab-ci.yml")):
        devops["ci"] = "gitlab-ci"
    elif os.path.isfile(os.path.join(cwd, "Jenkinsfile")):
        devops["ci"] = "jenkins"

    # Infrastructure
    tf_files = [f for f in os.listdir(cwd) if f.endswith(".tf")] if os.path.isdir(cwd) else []
    if tf_files:
        devops["infra"] = "terraform"
    elif os.path.isdir(os.path.join(cwd, "pulumi")):
        devops["infra"] = "pulumi"

    # Deploy platform
    deploy = _detect_deploy(cwd)
    if deploy:
        devops["deploy"] = deploy

    # Monitoring
    monitoring = _detect_monitoring(cwd)
    if monitoring:
        devops["monitoring"] = monitoring

    return devops if devops else None


def _detect_deploy(cwd):
    """Detect deployment platform from config files."""
    deploy_checks = [
        ("vercel.json", "vercel"),
        ("netlify.toml", "netlify"),
        ("fly.toml", "fly-io"),
        ("Procfile", "heroku"),
        ("app.yaml", "gcp-app-engine"),
        ("app.yml", "gcp-app-engine"),
    ]
    for filename, platform in deploy_checks:
        if os.path.isfile(os.path.join(cwd, filename)):
            return platform

    # Directory-based checks
    if os.path.isdir(os.path.join(cwd, "k8s")) or os.path.isdir(os.path.join(cwd, "kubernetes")):
        return "kubernetes"

    return None


def _detect_monitoring(cwd):
    """Detect monitoring/observability tools from dependencies."""
    # Gather all dependency text
    dep_sources = []

    pkg = read_json(os.path.join(cwd, "package.json"))
    if pkg:
        for key in ("dependencies", "devDependencies"):
            deps = pkg.get(key, {})
            if isinstance(deps, dict):
                dep_sources.extend(deps.keys())

    for dep_file in ("requirements.txt", "go.mod", "Gemfile"):
        content = read_lines(os.path.join(cwd, dep_file))
        if content:
            dep_sources.append(content)

    all_deps = " ".join(dep_sources).lower()

    monitoring_checks = [
        (["dd-trace", "datadog"], "datadog"),
        (["newrelic", "@newrelic"], "newrelic"),
        (["@sentry", "sentry-sdk", "sentry_sdk"], "sentry"),
        (["prom-client", "prometheus"], "prometheus"),
        (["@elastic/apm", "elastic-apm"], "elastic-apm"),
    ]
    for keywords, tool in monitoring_checks:
        for kw in keywords:
            if kw in all_deps:
                return tool

    return None
