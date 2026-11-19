"""The local HTTP API over the same code the command line uses."""

from .app import create_app

__all__ = ["create_app"]
