"""Run a generated Node MCP server over the real protocol, and only inside the sandbox.

The same design as the Python half (build/mcp_protocol.py, whose grading and verdict hardening this uses unchanged): a fixed harness written by us, never
by a model, is copied next to the server and both run in the locked container, from an image that has the pinned SDK. The harness starts the server the way
Claude Code would (over stdio, as `node --permission --allow-fs-read=<folder> server.ts`, so the run is under Node's permission model too), lists its
tools, calls every test case and prints one line of JSON. Code, not a model, compares that with what the design said.
"""

from __future__ import annotations

from collections.abc import Mapping

from ..mcpnode import SERVER_FILE
from ..sandbox.images import MCP_NODE_IMAGE, NODE_SDK_DIR
from ..validate.mcp_node import analyze_node_server
from .mcp_node import NodeDefinition
from .mcp_protocol import CASES_FILE, Flavour, McpRunner, ProtocolReport, SandboxMcpRunner, run_protocol_tests

NODE_HARNESS_FILE = "_skillforge_harness.mjs"
NODE_BUILD_COMMAND = "python -m skillforge sandbox-build-mcp-node"

# The one program that talks to a server. It uses only names that were checked against a real install of the SDK (docs/mcp-builder-node.md).
# The server gets only the environment variable NAMES the design declared, with a dummy value. It is started under Node's permission model: it may
# read its own folder and the installed packages, and nothing else (no writes, no programs, no workers). The image keeps the packages outside the folder,
# so the two folders that hold them are allowed too; on a person's machine they are inside the folder.
NODE_HARNESS = '''\
import { Client } from "@modelcontextprotocol/client";
import { StdioClientTransport } from "@modelcontextprotocol/client/stdio";
import { readFileSync } from "node:fs";
import { join } from "node:path";

const ROOT = import.meta.dirname;
const plan = JSON.parse(readFileSync(join(ROOT, "%(cases)s"), "utf8"));
const out = { started: false, tools: [], results: [], problem: "" };
const env = {};
for (const name of plan.env) env[name] = "skillforge-test-value";

function textOf(result) {
  return (result.content || []).map((part) => (typeof part.text === "string" ? part.text : "")).join("\\n");
}

function within(promise, ms) {
  let timer;
  const clock = new Promise((_, reject) => { timer = setTimeout(() => reject(new Error("timed out after " + ms + " ms")), ms); });
  return Promise.race([promise, clock]).finally(() => clearTimeout(timer));
}

let client;
try {
  const transport = new StdioClientTransport({
    command: process.execPath,
    args: ["--permission", "--allow-fs-read=" + ROOT, "--allow-fs-read=%(sdk)s", "--allow-fs-read=/node_modules", join(ROOT, "%(server)s")],
    env,
  });
  client = new Client({ name: "skillforge-harness", version: "0.0.0" }, { capabilities: {} });
  await within(client.connect(transport), 30000);
  out.started = true;
  const listed = await within(client.listTools(), 30000);
  out.tools = listed.tools.map((tool) => tool.name).sort();
  for (const item of plan.cases) {
    const row = { name: item.name, is_error: null, text: "", problem: "" };
    try {
      const reply = await within(client.callTool({ name: item.tool, arguments: item.arguments }), 20000);
      row.is_error = Boolean(reply.isError);
      row.text = textOf(reply).slice(0, 2000);
    } catch (error) {
      row.problem = (String(error && error.constructor && error.constructor.name) + ": " + String(error && error.message)).slice(0, 300);
    }
    out.results.push(row);
  }
} catch (error) {
  out.problem = (String(error && error.constructor && error.constructor.name) + ": " + String(error && error.message)).slice(0, 500);
}
try { if (client) await client.close(); } catch (error) { /* the verdict is already known */ }
process.stdout.write(JSON.stringify(out) + "\\n", () => process.exit(0));
''' % {"cases": CASES_FILE, "sdk": NODE_SDK_DIR, "server": SERVER_FILE}


def node_tools_needing_network(source: str) -> set[str]:
    """The tools whose own code can reach the network, by syntax. Their cases cannot run in a box with no network."""
    try:
        facts = analyze_node_server(source)
    except (SyntaxError, ValueError, RecursionError):
        return set()
    return {tool.name for tool in facts.tools if "network" in tool.capabilities}


NODE = Flavour(NODE_HARNESS_FILE, NODE_HARNESS, ("node",), MCP_NODE_IMAGE, NODE_BUILD_COMMAND, SERVER_FILE, node_tools_needing_network)


def node_runner(**kwargs) -> SandboxMcpRunner:
    return SandboxMcpRunner(flavour=NODE, **kwargs)


def run_node_protocol_tests(defn: NodeDefinition, files: Mapping[str, str], runner: McpRunner | None = None) -> ProtocolReport:
    """Start the server in the sandbox and call its cases. Nothing runs without a sandbox and the image."""
    return run_protocol_tests(defn, files, runner, flavour=NODE)  # type: ignore[arg-type]  # a NodeDefinition has the cases and env_vars the run reads


__all__ = ["NODE", "NODE_HARNESS", "NODE_HARNESS_FILE", "node_runner", "node_tools_needing_network", "run_node_protocol_tests"]
