"""Tile cache backed by a dict, with a byte budget."""
from typing import Dict, Optional

from tiles.keys import tile_key


class TileCache:
    """Cache."""

    def __init__(self, budget: int) -> None:
        self.budget = budget
        self.used = 0
        self._tiles: Dict[str, bytes] = {}

    def get(self, z: int, x: int, y: int) -> Optional[bytes]:
        """Get tile."""
        return self._tiles.get(tile_key(z, x, y))

    def put(self, z: int, x: int, y: int, data: bytes) -> bool:
        """This method stores the tile bytes under the key for z, x and y. If the tile would push the cache
        over its budget it is not stored and the method returns False, otherwise it returns True after
        adding the size to the used counter."""
        if self.used + len(data) > self.budget:
            return False
        self._tiles[tile_key(z, x, y)] = data
        self.used += len(data)
        return True
