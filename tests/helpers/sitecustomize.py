from __future__ import annotations

import importlib.abc
import os
import sys


class BlockImportFinder(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname: str, path, target=None):
        blocked = os.environ.get("BLOCK_IMPORT")
        if blocked and fullname.split(".", 1)[0] == blocked:
            raise ImportError(f"blocked import: {blocked}")
        return None


sys.meta_path.insert(0, BlockImportFinder())
