"""Detect PHP project from composer.json."""
import os

from detectors.utils import read_json


def detect_php(cwd):
    """Detect PHP project from composer.json."""
    composer = read_json(os.path.join(cwd, "composer.json"))
    if not composer:
        return None, None

    require = {}
    require.update(composer.get("require", {}))
    require_dev = composer.get("require-dev", {})

    be = {"language": "php"}
    testing = None

    if "laravel/framework" in require:
        be["framework"] = "laravel"
    elif "symfony/framework-bundle" in require or "symfony/symfony" in require:
        be["framework"] = "symfony"
    elif "magento/product-community-edition" in require or "magento/magento2-base" in require:
        be["framework"] = "magento"
    elif "slim/slim" in require:
        be["framework"] = "slim"

    if "doctrine/orm" in require:
        be["orm"] = "doctrine"
    elif "illuminate/database" in require or "laravel/framework" in require:
        be["orm"] = "eloquent"

    if "phpunit/phpunit" in require_dev or "phpunit/phpunit" in require:
        testing = "phpunit"
    elif "pestphp/pest" in require_dev:
        testing = "pest"

    return be if be.get("framework") else None, testing
