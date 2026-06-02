"""
논문 검색 MCP 서버.
arXiv API + Semantic Scholar API를 통해 논문을 검색한다.
도구:
  - search_papers(query, max_results, source) → list[Paper]
"""
import asyncio
import os
import json
import httpx
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp import types

app = Server("web_search")
DEFAULT_MAX = int(os.environ.get("WEB_SEARCH_MAX_RESULTS", "10"))

# Semantic Scholar API 키 유무에 따라 1 RPS 제한 적용
_SS_API_KEY = os.environ.get("SEMANTIC_SCHOLAR_API_KEY", "")
# API 키 있으면 1 RPS 제한이므로 요청 간 최소 간격 확보
_SS_MIN_INTERVAL = 1.1 if _SS_API_KEY else 0.0
_ss_last_request = 0.0


@app.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="search_papers",
            description="arXiv 및 Semantic Scholar에서 학술 논문을 검색합니다.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "검색 쿼리"},
                    "max_results": {
                        "type": "integer",
                        "description": "최대 결과 수",
                        "default": 10,
                    },
                    "source": {
                        "type": "string",
                        "enum": ["arxiv", "semantic_scholar", "both"],
                        "default": "both",
                    },
                },
                "required": ["query"],
            },
        )
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    if name != "search_papers":
        return [types.TextContent(type="text", text=f"Unknown tool: {name}")]

    query = arguments["query"]
    max_results = arguments.get("max_results", DEFAULT_MAX)
    source = arguments.get("source", "both")

    papers = []
    async with httpx.AsyncClient(timeout=30) as client:
        if source in ("arxiv", "both"):
            arxiv_papers = await _search_arxiv(client, query, max_results)
            papers.extend(arxiv_papers)
        if source in ("semantic_scholar", "both"):
            ss_papers = await _search_semantic_scholar(client, query, max_results)
            papers.extend(ss_papers)

    # 중복 제거 (제목 기준)
    seen = set()
    unique_papers = []
    for p in papers:
        key = p.get("title", "").lower().strip()
        if key not in seen:
            seen.add(key)
            unique_papers.append(p)

    return [types.TextContent(type="text", text=json.dumps(unique_papers[:max_results], ensure_ascii=False))]


async def _request_with_retry(
    client: httpx.AsyncClient,
    url: str,
    params: dict,
    headers: dict | None = None,
    max_retries: int = 4,
) -> httpx.Response:
    """429/503 응답 시 지수 백오프로 재시도."""
    delay = 2.0
    for attempt in range(max_retries):
        resp = await client.get(url, params=params, headers=headers or {})
        if resp.status_code not in (429, 503):
            return resp
        wait = delay * (2 ** attempt)
        await asyncio.sleep(wait)
    return resp  # 마지막 응답 반환 (호출자가 raise_for_status 처리)


async def _search_arxiv(client: httpx.AsyncClient, query: str, max_results: int) -> list[dict]:
    url = "https://export.arxiv.org/api/query"
    params = {
        "search_query": f"all:{query}",
        "max_results": max_results,
        "sortBy": "relevance",
        "sortOrder": "descending",
    }
    try:
        resp = await _request_with_retry(client, url, params)
        resp.raise_for_status()
        import xml.etree.ElementTree as ET
        root = ET.fromstring(resp.text)
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        papers = []
        for entry in root.findall("atom:entry", ns):
            title = entry.find("atom:title", ns)
            summary = entry.find("atom:summary", ns)
            published = entry.find("atom:published", ns)
            link = entry.find("atom:id", ns)
            authors = [a.find("atom:name", ns).text for a in entry.findall("atom:author", ns) if a.find("atom:name", ns) is not None]
            papers.append({
                "source": "arxiv",
                "title": title.text.strip().replace("\n", " ") if title is not None else "",
                "abstract": summary.text.strip().replace("\n", " ") if summary is not None else "",
                "authors": authors,
                "published": published.text[:10] if published is not None else "",
                "url": link.text.strip() if link is not None else "",
            })
        return papers
    except Exception as e:
        return [{"source": "arxiv", "error": str(e)}]


async def _search_semantic_scholar(client: httpx.AsyncClient, query: str, max_results: int) -> list[dict]:
    global _ss_last_request

    # API 키 있을 때 1 RPS 제한 준수
    if _SS_MIN_INTERVAL > 0:
        elapsed = asyncio.get_event_loop().time() - _ss_last_request
        if elapsed < _SS_MIN_INTERVAL:
            await asyncio.sleep(_SS_MIN_INTERVAL - elapsed)

    url = "https://api.semanticscholar.org/graph/v1/paper/search"
    params = {
        "query": query,
        "limit": max_results,
        "fields": "title,abstract,authors,year,externalIds,url",
    }
    headers = {}
    if _SS_API_KEY:
        headers["x-api-key"] = _SS_API_KEY

    try:
        resp = await _request_with_retry(client, url, params, headers)
        _ss_last_request = asyncio.get_event_loop().time()
        resp.raise_for_status()
        data = resp.json()
        papers = []
        for item in data.get("data", []):
            authors = [a.get("name", "") for a in item.get("authors", [])]
            papers.append({
                "source": "semantic_scholar",
                "title": item.get("title", ""),
                "abstract": item.get("abstract", ""),
                "authors": authors,
                "published": str(item.get("year", "")),
                "url": item.get("url", ""),
            })
        return papers
    except Exception as e:
        return [{"source": "semantic_scholar", "error": str(e)}]


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
