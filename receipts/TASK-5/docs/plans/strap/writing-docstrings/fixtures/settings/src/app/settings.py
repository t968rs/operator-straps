"""Application settings read from the environment."""
import os
from typing import Dict, Optional

_CACHE: Optional[Dict[str, str]] = None


def settings() -> Dict[str, str]:
    """settings"""
    global _CACHE
    if _CACHE is None:
        _CACHE = {key[4:].lower(): value for key, value in os.environ.items() if key.startswith("APP_")}
    return _CACHE


def parse_port(text: str) -> int:
    """Port parsing. Takes the text and gives back the port number as an int. Bad text is an error and
    so is a number that is not a valid TCP port."""
    if not text.isdigit():
        raise ValueError(f"not a port: {text!r}")
    port = int(text)
    if not 0 < port < 65536:
        raise ValueError(f"port out of range: {port}")
    return port
