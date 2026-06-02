"""PDF full-text extraction utility."""
import io


def extract_text(pdf_bytes: bytes, max_chars: int = 4000) -> str:
    """Extract plain text from PDF bytes. Returns '' on failure."""
    try:
        import pypdf
        reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
        pages = []
        total = 0
        for page in reader.pages:
            text = page.extract_text() or ""
            pages.append(text)
            total += len(text)
            if total >= max_chars:
                break
        return "\n\n".join(pages)[:max_chars]
    except Exception:
        return ""
