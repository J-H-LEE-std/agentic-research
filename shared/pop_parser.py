"""Publish or Perish CSV/JSON/RIS 내보내기 파서 → paper dict 리스트."""
import csv
import io
import json
import os
from typing import List, Dict

# 컬럼명 후보 (Google Scholar / Web of Science / Scopus / PubMed 혼용 대응)
_TITLE_COLS   = ["Title", "title", "TI", "Article Title"]
_AUTHORS_COLS = ["Authors", "authors", "AU", "Author", "AF"]
_YEAR_COLS    = ["Year", "year", "PY", "Publication Year", "PD"]
_SOURCE_COLS  = ["Source", "source", "SO", "Journal", "Publication Name"]
_DOI_COLS     = ["DOI", "doi", "DI"]
_URL_COLS     = ["ArticleURL", "URL", "url", "UR", "Link"]
_ABSTRACT_COLS= ["Abstract", "abstract", "AB"]
_CITES_COLS   = ["Cites", "Times Cited", "TC", "Cited by"]


def _first(row: dict, candidates: list, default: str = "") -> str:
    for c in candidates:
        if c in row and row[c]:
            return row[c].strip()
    return default


def parse_pop_file(path: str) -> List[Dict]:
    """확장자에 따라 CSV / JSON / JSONL을 자동 감지하여 파싱."""
    ext = os.path.splitext(path)[1].lower()
    if ext in (".json",):
        return _parse_json(path)
    if ext in (".jsonl",):
        return _parse_jsonl(path)
    return parse_pop_csv(path)


def _parse_json(path: str) -> List[Dict]:
    with open(path, "r", encoding="utf-8-sig", errors="replace") as f:
        data = json.load(f)
    items = data if isinstance(data, list) else data.get("results", [])
    return [_normalize_json_item(item) for item in items if item.get("title") or item.get("Title")]


def _parse_jsonl(path: str) -> List[Dict]:
    papers = []
    with open(path, "r", encoding="utf-8-sig", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
                if item.get("title") or item.get("Title"):
                    papers.append(_normalize_json_item(item))
            except json.JSONDecodeError:
                continue
    return papers


def _normalize_json_item(item: dict) -> dict:
    """PoP JSON 출력 필드를 paper dict로 변환."""
    title = item.get("title") or item.get("Title", "")
    doi = item.get("doi") or item.get("DOI", "")
    url = item.get("url") or item.get("ArticleURL", "") or (f"https://doi.org/{doi}" if doi else "")
    authors_raw = item.get("authors") or item.get("Authors", "")
    if isinstance(authors_raw, list):
        authors = authors_raw
    elif "; " in str(authors_raw):
        authors = [a.strip() for a in str(authors_raw).split(";") if a.strip()]
    else:
        authors = [a.strip() for a in str(authors_raw).split(",") if a.strip()]
    return {
        "source": "pop",
        "title": title,
        "abstract": item.get("abstract") or item.get("Abstract", ""),
        "authors": authors,
        "published": str(item.get("year") or item.get("Year", "")),
        "url": url,
        "doi": doi,
        "journal": item.get("source") or item.get("Source", ""),
        "citations": str(item.get("cites") or item.get("Cites", "")),
    }


def parse_pop_csv(path: str) -> List[Dict]:
    """PoP CSV 내보내기 파일 파싱. paper dict 리스트 반환."""
    with open(path, "r", encoding="utf-8-sig", errors="replace") as f:
        content = f.read()

    # PoP는 헤더 앞에 메타데이터 행을 넣는 경우가 있음
    # "Title" 또는 "Authors" 컬럼이 있는 행을 헤더로 간주
    lines = content.splitlines()
    header_idx = 0
    for i, line in enumerate(lines):
        if any(col in line for col in ("Title", "Authors", "TI,", "AU,")):
            header_idx = i
            break

    reader = csv.DictReader(io.StringIO("\n".join(lines[header_idx:])))

    papers = []
    for row in reader:
        title = _first(row, _TITLE_COLS)
        if not title:
            continue

        authors_raw = _first(row, _AUTHORS_COLS)
        # PoP는 저자를 "; " 또는 ", "로 구분
        if "; " in authors_raw:
            authors = [a.strip() for a in authors_raw.split(";") if a.strip()]
        else:
            authors = [a.strip() for a in authors_raw.split(",") if a.strip()]

        doi = _first(row, _DOI_COLS)
        url = _first(row, _URL_COLS) or (f"https://doi.org/{doi}" if doi else "")

        papers.append({
            "source": "pop",
            "title": title,
            "abstract": _first(row, _ABSTRACT_COLS),  # PoP는 기본적으로 abstract 미포함
            "authors": authors,
            "published": _first(row, _YEAR_COLS),
            "url": url,
            "doi": doi,
            "journal": _first(row, _SOURCE_COLS),
            "citations": _first(row, _CITES_COLS),
        })
    return papers
