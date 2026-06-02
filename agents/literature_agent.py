import sys
import os
import json
import asyncio
import httpx

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agents.base_agent import BaseAgent
from shared.prompts import LITERATURE
from shared.pdf_extractor import extract_text


class LiteratureAgent(BaseAgent):
    def run(self, context: dict) -> dict:
        topic = context.get("topic", "")
        note = context.get("note", {})

        # 연구 노트 키워드로 검색어 보강
        search_query = topic
        if note.get("keywords"):
            kw = note["keywords"].replace("\n", " ").strip()
            search_query = f"{topic} {kw}"

        pop_papers = note.get("pop_papers", [])
        if pop_papers:
            print(f"  → PoP 제공 논문 {len(pop_papers)}편 사용 (자동 검색 건너뜀)")
            papers = pop_papers
            # abstract가 없는 논문만 Semantic Scholar에서 보완 시도
            papers = asyncio.run(self._supplement_abstracts(papers))
        else:
            papers = asyncio.run(self._fetch_papers_with_fulltext(search_query))

        # 원문을 구하지 못한 논문 — 사용자에게 업로드 요청 (로컬 모드 전용)
        missing = [p for p in papers if not p.get("full_text") and not p.get("error")]
        channel = context.get("_channel")
        if missing and channel is not None:
            print(f"  → 원문 자동 수집 실패 {len(missing)}편 — 사용자에게 업로드 요청")
            uploaded = channel.request_papers(missing)
            for paper in papers:
                title = paper.get("title", "")
                if title in uploaded and uploaded[title]:
                    paper["full_text"] = uploaded[title]

        # 논문이 너무 적으면 방향 질문
        valid_papers = [p for p in papers if p.get("title") and not p.get("error")]
        if len(valid_papers) < 3:
            decision, note_msg = self.ask_direction(
                context,
                question="수집된 논문이 너무 적습니다 — 계속 진행할까요?",
                summary=(
                    f"검색 주제: {topic}\n"
                    f"수집된 논문: {len(valid_papers)}편 (기준: 3편 이상)\n\n"
                    "계속 진행하면 적은 문헌으로 분석합니다.\n"
                    "수정 시 검색 주제를 더 넓게 조정하는 등의 지시를 입력하세요."
                ),
            )
            if decision == "stop":
                raise RuntimeError("사용자가 문헌 수집 단계에서 파이프라인을 중단했습니다.")
            if decision == "modify" and note_msg:
                print(f"  → 수정 지시: {note_msg} — 재검색 실행")
                papers = asyncio.run(self._fetch_papers_with_fulltext(f"{search_query} {note_msg}"))
                valid_papers = [p for p in papers if p.get("title") and not p.get("error")]
                print(f"  → 재검색 결과: {len(valid_papers)}편")

        papers_text = json.dumps(papers, ensure_ascii=False, indent=2)

        note_context = ""
        if note.get("hypothesis"):
            note_context += f"\n연구 가설: {note['hypothesis']}"
        if note.get("background"):
            note_context += f"\n연구 배경: {note['background'][:300]}"

        messages = [
            {"role": "system", "content": LITERATURE},
            {
                "role": "user",
                "content": (
                    f"연구 주제: {topic}{note_context}\n\n"
                    f"수집된 논문 데이터:\n{papers_text}\n\n"
                    "다음 JSON 형식으로 분석 결과를 출력하세요:\n"
                    "{\n"
                    '  "papers": [{"title": "", "contribution": "", "method": "", "limitation": ""}],\n'
                    '  "relationships": "논문 간 관계 설명",\n'
                    '  "research_gap": "발견된 연구 공백",\n'
                    '  "recommended_direction": "추천 연구 방향"\n'
                    "}"
                ),
            },
        ]

        response = self.client.chat(
            model=self.model,
            messages=messages,
            temperature=0.3,
            max_tokens=4096,
            caller="literature_agent",
        )

        try:
            start = response.find("{")
            end = response.rfind("}") + 1
            analysis = json.loads(response[start:end])
        except (json.JSONDecodeError, ValueError):
            analysis = {"raw_analysis": response}

        analysis["raw_papers"] = papers
        return analysis

    # ── Paper fetching ─────────────────────────────────────────────────

    async def _fetch_papers_with_fulltext(self, topic: str, max_results: int = 10) -> list:
        output_base = os.path.dirname(os.path.abspath(
            os.environ.get("EXECUTOR_OUTPUT_PATH", "./data/outputs")
        ))
        papers_dir = os.path.join(output_base, "papers")
        os.makedirs(papers_dir, exist_ok=True)

        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            arxiv_papers = await self._arxiv_search(client, topic, max_results)
            ss_papers = await self._semantic_scholar_search(client, topic, max_results)

        papers = arxiv_papers + ss_papers

        # 중복 제거
        seen: set = set()
        unique = []
        for p in papers:
            key = p.get("title", "").lower().strip()
            if key and key not in seen:
                seen.add(key)
                unique.append(p)
        papers = unique[:max_results]

        # 병렬 PDF 취득 및 디스크 저장
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            results = await asyncio.gather(
                *[self._try_fetch_fulltext(client, p, papers_dir) for p in papers],
                return_exceptions=True,
            )
        for paper, result in zip(papers, results):
            if isinstance(result, tuple) and result[0]:
                paper["full_text"] = result[0]
                paper["saved_path"] = result[1]

        fetched = sum(1 for p in papers if p.get("full_text"))
        print(f"  → 논문 {len(papers)}편 수집 (원문 텍스트 추출 {fetched}편, 저장 위치: {papers_dir})")
        return papers

    async def _try_fetch_fulltext(self, client: httpx.AsyncClient, paper: dict, papers_dir: str) -> tuple:
        """arXiv / 오픈 액세스 PDF 다운로드 후 텍스트 추출 및 저장. 실패 시 ('', '')."""
        url = None
        filename = None
        if paper.get("source") == "arxiv" and paper.get("url"):
            arxiv_id = paper["url"].rstrip("/").split("/")[-1]
            url = f"https://arxiv.org/pdf/{arxiv_id}"
            filename = f"arxiv_{arxiv_id}.txt"
        elif paper.get("open_access_pdf"):
            url = paper["open_access_pdf"]
            safe_title = paper.get("title", "unknown")[:60].replace("/", "_").replace("\\", "_").replace(":", "_")
            filename = f"ss_{safe_title}.txt"

        if not url or not filename:
            return "", ""
        try:
            resp = await client.get(url, timeout=20)
            if resp.status_code == 200 and "pdf" in resp.headers.get("content-type", ""):
                text = extract_text(resp.content)
                if text:
                    save_path = os.path.join(papers_dir, filename)
                    with open(save_path, "w", encoding="utf-8") as f:
                        f.write(text)
                    return text, save_path
        except Exception:
            pass
        return "", ""

    async def _supplement_abstracts(self, papers: list) -> list:
        """PoP 논문 중 abstract가 없는 것을 Semantic Scholar DOI/제목 검색으로 보완."""
        missing = [p for p in papers if not p.get("abstract")]
        if not missing:
            return papers

        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            for paper in missing:
                doi = paper.get("doi", "")
                title = paper.get("title", "")
                abstract = ""
                try:
                    if doi:
                        url = f"https://api.semanticscholar.org/graph/v1/paper/DOI:{doi}"
                        resp = await client.get(url, params={"fields": "abstract"})
                        if resp.status_code == 200:
                            abstract = resp.json().get("abstract", "")
                    if not abstract and title:
                        resp = await client.get(
                            "https://api.semanticscholar.org/graph/v1/paper/search",
                            params={"query": title, "limit": 1, "fields": "abstract"},
                        )
                        if resp.status_code == 200:
                            data = resp.json().get("data", [])
                            if data:
                                abstract = data[0].get("abstract", "")
                except Exception:
                    pass
                if abstract:
                    paper["abstract"] = abstract

        filled = sum(1 for p in missing if p.get("abstract"))
        print(f"  → abstract 보완: {filled}/{len(missing)}편")
        return papers

    async def _request_with_retry(
        self, client: httpx.AsyncClient, url: str, params: dict,
        headers: dict = None, max_retries: int = 4
    ) -> httpx.Response:
        delay = 2.0
        for attempt in range(max_retries):
            resp = await client.get(url, params=params, headers=headers or {})
            if resp.status_code not in (429, 503):
                return resp
            wait = delay * (2 ** attempt)
            print(f"  → {resp.status_code} 응답, {wait:.0f}초 후 재시도 ({attempt + 1}/{max_retries})")
            await asyncio.sleep(wait)
        return resp

    async def _arxiv_search(self, client: httpx.AsyncClient, query: str, max_results: int) -> list:
        import xml.etree.ElementTree as ET
        url = "https://export.arxiv.org/api/query"
        params = {"search_query": f"all:{query}", "max_results": max_results, "sortBy": "relevance"}
        try:
            resp = await self._request_with_retry(client, url, params)
            resp.raise_for_status()
            root = ET.fromstring(resp.text)
            ns = {"atom": "http://www.w3.org/2005/Atom"}
            papers = []
            for entry in root.findall("atom:entry", ns):
                title_el = entry.find("atom:title", ns)
                summary_el = entry.find("atom:summary", ns)
                published_el = entry.find("atom:published", ns)
                link_el = entry.find("atom:id", ns)
                authors = [
                    a.find("atom:name", ns).text
                    for a in entry.findall("atom:author", ns)
                    if a.find("atom:name", ns) is not None
                ]
                papers.append({
                    "source": "arxiv",
                    "title": title_el.text.strip().replace("\n", " ") if title_el is not None else "",
                    "abstract": summary_el.text.strip().replace("\n", " ") if summary_el is not None else "",
                    "authors": authors,
                    "published": published_el.text[:10] if published_el is not None else "",
                    "url": link_el.text.strip() if link_el is not None else "",
                })
            return papers
        except Exception as e:
            return [{"source": "arxiv", "error": str(e), "title": ""}]

    async def _semantic_scholar_search(self, client: httpx.AsyncClient, query: str, max_results: int) -> list:
        url = "https://api.semanticscholar.org/graph/v1/paper/search"
        params = {
            "query": query,
            "limit": max_results,
            "fields": "title,abstract,authors,year,url,openAccessPdf",
        }
        ss_api_key = os.environ.get("SEMANTIC_SCHOLAR_API_KEY", "")
        headers = {"x-api-key": ss_api_key} if ss_api_key else {}
        try:
            resp = await self._request_with_retry(client, url, params, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            papers = []
            for item in data.get("data", []):
                authors = [a.get("name", "") for a in item.get("authors", [])]
                oa = item.get("openAccessPdf") or {}
                papers.append({
                    "source": "semantic_scholar",
                    "title": item.get("title", ""),
                    "abstract": item.get("abstract", ""),
                    "authors": authors,
                    "published": str(item.get("year", "")),
                    "url": item.get("url", ""),
                    "open_access_pdf": oa.get("url", ""),
                })
            return papers
        except Exception as e:
            return [{"source": "semantic_scholar", "error": str(e), "title": ""}]
