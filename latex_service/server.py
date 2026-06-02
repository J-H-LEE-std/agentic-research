"""
LaTeX 컴파일 서비스.
POST /compile  → .tex 파일을 xelatex으로 컴파일해 PDF 생성
GET  /health   → 헬스체크
"""
import os
import subprocess
import tempfile
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

app = FastAPI(title="LaTeX Compile Service")

LATEX_TIMEOUT = int(os.environ.get("LATEX_TIMEOUT", "120"))
DATA_ROOT = Path(os.environ.get("EXECUTOR_OUTPUT_PATH", "/data/outputs"))


class CompileRequest(BaseModel):
    # 공유 볼륨 상의 .tex 파일 절대 경로
    tex_path: str
    # xelatex (기본, 한국어 지원) 또는 pdflatex
    engine: str = "xelatex"
    # 두 번 컴파일 (목차/참조 해결)
    twice: bool = True


class CompileResponse(BaseModel):
    ok: bool
    pdf_path: str | None = None
    log: str = ""


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/compile", response_model=CompileResponse)
def compile_latex(req: CompileRequest):
    tex_path = Path(req.tex_path)
    if not tex_path.exists():
        raise HTTPException(400, f"파일 없음: {req.tex_path}")
    if tex_path.suffix != ".tex":
        raise HTTPException(400, "확장자가 .tex인 파일만 허용됩니다")

    work_dir = tex_path.parent

    def run_once() -> tuple[bool, str]:
        result = subprocess.run(
            [req.engine, "-interaction=nonstopmode", "-halt-on-error", tex_path.name],
            cwd=work_dir,
            capture_output=True,
            text=True,
            timeout=LATEX_TIMEOUT,
        )
        return result.returncode == 0, result.stdout + result.stderr

    try:
        ok, log = run_once()
        if ok and req.twice:
            ok, log2 = run_once()
            log = log2 if ok else log + "\n--- 2차 컴파일 ---\n" + log2
    except subprocess.TimeoutExpired:
        return CompileResponse(ok=False, log=f"타임아웃 ({LATEX_TIMEOUT}s 초과)")
    except Exception as exc:
        return CompileResponse(ok=False, log=str(exc))

    pdf_path = work_dir / tex_path.with_suffix(".pdf").name
    if pdf_path.exists():
        return CompileResponse(ok=True, pdf_path=str(pdf_path))

    # ok=True인데 PDF 없으면 실제 실패 (pdflatex 경고 후 종료 등)
    return CompileResponse(ok=False, log=log[-4000:])


@app.get("/pdf")
def download_pdf(path: str):
    """컴파일된 PDF를 직접 다운로드."""
    p = Path(path)
    if not p.exists() or p.suffix != ".pdf":
        raise HTTPException(404)
    return FileResponse(str(p), media_type="application/pdf", filename=p.name)
