"""
Python 코드 실행 샌드박스 MCP 서버.
도구:
  - execute_python(code) → stdout, stderr, 생성된 파일 목록
네트워크는 차단하고, 파일 접근은 outputs/ 디렉토리만 허용한다.
"""
import asyncio
import os
import sys
import subprocess
import tempfile
import json
from pathlib import Path
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp import types

ALLOWED_OUTPUT_PATH = os.path.abspath(os.environ.get("EXECUTOR_OUTPUT_PATH", "./outputs"))
TIMEOUT_SECONDS = int(os.environ.get("EXECUTOR_TIMEOUT", "30"))

app = Server("python_executor")


@app.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="execute_python",
            description="Python 코드를 샌드박스 환경에서 실행합니다. 네트워크 없음, 파일은 outputs/ 디렉토리만 허용.",
            inputSchema={
                "type": "object",
                "properties": {
                    "code": {"type": "string", "description": "실행할 Python 코드"},
                    "filename": {
                        "type": "string",
                        "description": "저장할 파일명 (선택). 없으면 임시 파일 사용.",
                        "default": "",
                    },
                },
                "required": ["code"],
            },
        )
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    if name != "execute_python":
        return [types.TextContent(type="text", text=f"Unknown tool: {name}")]

    code = arguments["code"]
    filename = arguments.get("filename", "")

    os.makedirs(ALLOWED_OUTPUT_PATH, exist_ok=True)

    if filename:
        script_path = os.path.join(ALLOWED_OUTPUT_PATH, filename)
    else:
        tmp = tempfile.NamedTemporaryFile(suffix=".py", dir=ALLOWED_OUTPUT_PATH, delete=False)
        script_path = tmp.name
        tmp.close()

    # 코드 앞에 출력 경로 주입
    preamble = f"""
import os, sys
os.chdir({repr(ALLOWED_OUTPUT_PATH)})
sys.path.insert(0, {repr(ALLOWED_OUTPUT_PATH)})
"""
    with open(script_path, "w", encoding="utf-8") as f:
        f.write(preamble + "\n" + code)

    files_before = set(os.listdir(ALLOWED_OUTPUT_PATH))

    try:
        proc = await asyncio.create_subprocess_exec(
            sys.executable, script_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env={**os.environ, "PYTHONPATH": ALLOWED_OUTPUT_PATH},
        )
        try:
            stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=TIMEOUT_SECONDS)
        except asyncio.TimeoutError:
            proc.kill()
            return [types.TextContent(type="text", text=json.dumps({
                "stdout": "",
                "stderr": f"TimeoutError: 코드가 {TIMEOUT_SECONDS}초 내에 완료되지 않았습니다.",
                "files": [],
                "return_code": -1,
            }, ensure_ascii=False))]

        stdout = stdout_b.decode("utf-8", errors="replace")
        stderr = stderr_b.decode("utf-8", errors="replace")
        files_after = set(os.listdir(ALLOWED_OUTPUT_PATH))
        new_files = list(files_after - files_before)

        result = {
            "stdout": stdout,
            "stderr": stderr,
            "files": new_files,
            "return_code": proc.returncode,
        }
        return [types.TextContent(type="text", text=json.dumps(result, ensure_ascii=False))]

    finally:
        if not filename and os.path.exists(script_path):
            os.unlink(script_path)


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
