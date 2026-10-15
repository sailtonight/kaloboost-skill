"""Local stdio MCP adapter over the CLI's command registry.

SDK dependencies are optional; importing or running the CLI never loads them.
"""

from __future__ import annotations

import json
import sys
from typing import Literal

from . import __version__, config, render
from .commands import COMMANDS
from .errors import BoostError, UsageError

# Configuration is controlled by the operator, never by model-supplied arguments.
TOOLS = {
    c.path.replace(" ", "_").replace("-", "_"): c for c in COMMANDS if not c.path.startswith("config ")
}
# `--json` is presentation only (MCP always returns raw JSON); `--file` would let the
# model read arbitrary local files, and positional `ids` already covers its use.
HIDDEN_FLAGS = {"json", "file"}
# Commands that change state upstream. Those with --yes return a dry run until yes=true.
WRITES = {c.path for c in COMMANDS if c.flag("--yes") or c.flag("--idempotency-key")}
DESTRUCTIVE = {"outreach cancel", "webhook update", "webhook rotate-secret"}


def _confirm_param(cmd) -> str:
    # outreach create keys its retries on --external-id; other writes on --idempotency-key.
    return "idempotency_key" if cmd.flag("--idempotency-key") else "external_id"


def create_server():
    import anyio
    from mcp import types
    from mcp.server import Server
    from pydantic import ConfigDict, Field, ValidationError, create_model

    models = {}
    tools = []
    for name, cmd in TOOLS.items():
        fields = {}
        if cmd.positional:
            if cmd.pos_max == 1:
                fields[cmd.positional] = (str, Field(min_length=1, description=cmd.positional))
            else:
                fields["ids"] = (
                    list[str],
                    Field(min_length=max(cmd.pos_min, 1),
                          description=f"One or more {cmd.positional} values; keep IDs as strings"),
                )
        for flag in cmd.flags:
            if flag.dest in HIDDEN_FLAGS:
                continue
            annotation = {"str": str, "int": int, "flag": bool, "multi": list[str]}[flag.kind]
            if flag.choices:
                annotation = Literal[flag.choices]
            if flag.default is None:
                annotation = annotation | None
            fields[flag.dest] = (annotation, Field(default=flag.default, description=flag.help,
                                                   ge=flag.min, le=flag.max))
        model = create_model(
            f"{name}Arguments", __config__=ConfigDict(extra="forbid", strict=True), **fields
        )
        models[name] = model
        description = cmd.summary
        if cmd.flag("--yes"):
            description += (
                ". Without yes=true nothing is sent and a dry_run preview is returned: show it to the "
                f"user, and once they confirm call again with the same arguments, yes=true and the "
                f"returned {_confirm_param(cmd)}"
            )
        write = cmd.path in WRITES
        tools.append(types.Tool(
            name=name, description=description, input_schema=model.model_json_schema(),
            annotations=types.ToolAnnotations(
                read_only_hint=not write, destructive_hint=cmd.path in DESTRUCTIVE,
                idempotent_hint=False, open_world_hint=True,
            ),
        ))

    async def list_tools(ctx, params):
        return types.ListToolsResult(tools=tools)

    def execute(name, arguments):
        cmd = TOOLS[name]
        opts = {flag.dest: list(flag.default) if isinstance(flag.default, list) else flag.default
                for flag in cmd.flags}
        arguments = dict(arguments)
        args = []
        if cmd.positional:
            args = ([arguments.pop(cmd.positional)] if cmd.pos_max == 1
                    else arguments.pop("ids"))
            if any(not value.strip() for value in args):
                raise UsageError("IDs must not be empty")
        opts.update(arguments)
        opts["json"] = True
        with render.collect_results() as results:
            status = cmd.handler(config.load(), opts, args)
        if len(results) != 1:
            raise RuntimeError(f"{name} did not produce one structured result")
        payload = {"data": results[0]}
        preview = results[0].get("dry_run") if isinstance(results[0], dict) else None
        if preview:
            param = _confirm_param(cmd)
            payload["next"] = (
                "Nothing was sent. Show this to the user; once they confirm, call "
                f"{name} again with the same arguments plus yes=true and "
                f"{param}={preview['idempotency_key']!r}"
            )
        return payload, status != 0

    async def call_tool(ctx, params):
        try:
            if params.name not in models:
                raise UsageError(f"unknown tool '{params.name}'")
            arguments = models[params.name].model_validate(params.arguments or {}).model_dump()
            # urllib requests and retries block; run them outside the protocol event loop.
            payload, is_error = await anyio.to_thread.run_sync(execute, params.name, arguments)
        except ValidationError as exc:
            payload = {"error": "Invalid tool arguments", "kind": "parameter",
                       "details": exc.errors(include_input=False, include_url=False)}
            is_error = True
        except (BoostError, UsageError) as exc:
            payload = {"error": str(exc), "kind": getattr(exc, "kind", "parameter"),
                       "help": exc.help_lines}
            is_error = True
        return types.CallToolResult(
            content=[types.TextContent(type="text", text=json.dumps(payload, ensure_ascii=False))],
            structured_content=payload, is_error=is_error,
        )

    return Server(
        "kaloboost", version=__version__,
        instructions="Kaloboost TikTok Shop creator outreach. Call shops first for shop_id values "
                     "(the operator may have configured a default shop). IDs are strings. Lists are "
                     "cursor-paged: pass next_cursor back as cursor, or set all=true. Write tools "
                     "(outreach_create/cancel, webhook_*) reach real creators or change settings: "
                     "they return a dry_run preview until called with yes=true after the user "
                     "confirms. Credentials come from the local environment/configuration. "
                     "Results contain raw upstream JSON data.",
        on_list_tools=list_tools, on_call_tool=call_tool,
        get_tool_input_schema=lambda name: models[name].model_json_schema() if name in models else None,
    )


async def serve():
    from mcp.server.stdio import stdio_server

    server = create_server()
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


def entry() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Kaloboost local stdio MCP server")
    parser.add_argument("--version", action="version", version=f"kaloboost-mcp {__version__}")
    parser.parse_args()
    try:
        import anyio
        import mcp  # noqa: F401
    except ImportError:
        print('MCP dependencies missing. Install with: uv pip install "kaloboost-mcp[mcp]"',
              file=sys.stderr)
        raise SystemExit(1)
    try:
        anyio.run(serve)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    entry()
