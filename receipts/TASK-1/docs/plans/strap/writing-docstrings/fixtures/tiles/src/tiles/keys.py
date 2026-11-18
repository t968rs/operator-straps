from typing import Tuple


def tile_key(z: int, x: int, y: int) -> str:
    return f"{z}/{x}/{y}"


def parse_key(key: str) -> Tuple[int, int, int]:
    parts = key.split("/")
    if len(parts) != 3:
        raise ValueError(f"not a tile key: {key!r}")
    z, x, y = (int(part) for part in parts)
    return z, x, y


def parent_key(key: str) -> str:
    z, x, y = parse_key(key)
    if z == 0:
        return key
    return tile_key(z - 1, x // 2, y // 2)
