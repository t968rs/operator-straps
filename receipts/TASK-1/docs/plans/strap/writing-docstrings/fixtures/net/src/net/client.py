"""Thin HTTP client over urllib."""
import json
import urllib.request
from typing import Any, Dict

from net.retry import with_retries


def get_json(url: str, timeout: float = 10.0) -> Dict[str, Any]:
    """Get JSON."""
    def call() -> Dict[str, Any]:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    return with_retries(call)


def healthy(url: str) -> bool:
    """Health."""
    try:
        return get_json(url).get("status") == "ok"
    except (ConnectionError, ValueError):
        return False
