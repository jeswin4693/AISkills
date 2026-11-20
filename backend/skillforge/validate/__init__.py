"""Static validation of skill and agent folders. Reads files, never runs them."""

from .agent import check_agent_md
from .mcp import check_server_py
from .plugin import check_plugin_json
from .static import DEFINITION_CHECKS, DefinitionCheck, read_dir, validate_files, validate_skill_dir

DEFINITION_CHECKS["agent"] = check_agent_md
DEFINITION_CHECKS["plugin"] = check_plugin_json  # the one check that is an agent's own; every other check runs for every kind
DEFINITION_CHECKS["mcp"] = check_server_py

__all__ = ["DEFINITION_CHECKS", "DefinitionCheck", "read_dir", "validate_files", "validate_skill_dir"]
