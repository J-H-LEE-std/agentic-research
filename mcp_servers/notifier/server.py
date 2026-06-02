"""
ntfy 푸시 알림 MCP 서버.
도구:
  - notify(title, message, priority) → ntfy로 푸시
  - wait_for_approval(prompt, timeout_seconds) → SSE polling으로 응답 대기
"""
import asyncio
import os
import sys
import time
import json
import httpx
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp import types

from shared.models import get_ntfy_config

app = Server("notifier")


def _ntfy_cfg():
    return get_ntfy_config()


@app.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="notify",
            description="ntfy 서버로 푸시 알림을 전송합니다.",
            inputSchema={
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "알림 제목"},
                    "message": {"type": "string", "description": "알림 내용"},
                    "priority": {
                        "type": "string",
                        "enum": ["min", "low", "default", "high", "urgent"],
                        "default": "default",
                    },
                },
                "required": ["title", "message"],
            },
        ),
        types.Tool(
            name="wait_for_approval",
            description="사용자의 승인을 ntfy SSE로 대기합니다. 'approve'/'reject'/'modify' 중 하나를 반환합니다.",
            inputSchema={
                "type": "object",
                "properties": {
                    "prompt": {"type": "string", "description": "사용자에게 보여줄 승인 요청 내용"},
                    "timeout_seconds": {
                        "type": "integer",
                        "description": "대기 시간 (초). 초과 시 기본값 반환.",
                        "default": 300,
                    },
                },
                "required": ["prompt"],
            },
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    cfg = _ntfy_cfg()
    if name == "notify":
        result = await _send_notify(
            cfg,
            title=arguments["title"],
            message=arguments["message"],
            priority=arguments.get("priority", "default"),
        )
        return [types.TextContent(type="text", text=result)]

    elif name == "wait_for_approval":
        timeout = arguments.get("timeout_seconds", cfg["timeout_seconds"])
        await _send_notify(
            cfg,
            title="[승인 요청] " + arguments["prompt"][:60],
            message=arguments["prompt"] + "\n\n응답: ntfy 메시지로 'approve', 'reject', 'modify' 중 하나를 보내세요.",
            priority="high",
        )
        decision = await _poll_for_response(cfg, timeout)
        return [types.TextContent(type="text", text=decision)]

    return [types.TextContent(type="text", text=f"Unknown tool: {name}")]


def _make_auth(cfg: dict) -> httpx.BasicAuth | None:
    if cfg.get("username") and cfg.get("password"):
        return httpx.BasicAuth(cfg["username"], cfg["password"])
    return None


async def _send_notify(cfg: dict, title: str, message: str, priority: str = "default") -> str:
    url = f"{cfg['server_url']}/{cfg['topic']}"
    headers = {
        "Title": title,
        "Priority": priority,
        "Content-Type": "text/plain; charset=utf-8",
    }
    async with httpx.AsyncClient(timeout=10, auth=_make_auth(cfg)) as client:
        resp = await client.post(url, content=message.encode("utf-8"), headers=headers)
        resp.raise_for_status()
    return f"알림 전송 완료: {title}"


async def _poll_for_response(cfg: dict, timeout_seconds: int) -> str:
    """
    ntfy SSE 스트림을 polling하여 사용자 응답을 기다린다.
    사용자는 ntfy 앱에서 'approve', 'reject', 'modify' 중 하나를 메시지로 보낸다.
    """
    url = f"{cfg['server_url']}/{cfg['topic']}/sse"
    deadline = time.time() + timeout_seconds
    keywords = {"approve": "approve", "reject": "reject", "modify": "modify",
                 "승인": "approve", "거부": "reject", "수정": "modify"}

    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(connect=10, read=timeout_seconds + 5, write=10, pool=10),
            auth=_make_auth(cfg),
        ) as client:
            async with client.stream("GET", url) as stream:
                async for line in stream.aiter_lines():
                    if time.time() > deadline:
                        break
                    if not line.startswith("data:"):
                        continue
                    try:
                        data = json.loads(line[5:].strip())
                        msg_text = data.get("message", "").strip().lower()
                        for kw, decision in keywords.items():
                            if kw in msg_text:
                                return decision
                    except (json.JSONDecodeError, KeyError):
                        continue
    except (httpx.TimeoutException, httpx.ReadError):
        pass

    default = cfg.get("default_on_timeout", "approve")
    return default


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
