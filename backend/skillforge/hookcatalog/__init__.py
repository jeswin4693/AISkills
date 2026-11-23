"""The hook catalogue: the fixed hooks a plugin may carry (see `catalogue.py`)."""

from .catalogue import CATALOGUE, CatalogueError, HookEntry, Option, get_entry

__all__ = ["CATALOGUE", "CatalogueError", "HookEntry", "Option", "get_entry"]
