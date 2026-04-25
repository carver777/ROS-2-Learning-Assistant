from __future__ import annotations

import argparse
import json
import re
import time
from collections import deque
from collections.abc import Iterable
from pathlib import Path
from urllib.parse import urldefrag, urljoin, urlparse

import httpx

START_URL = "https://docs.ros.org/en/kilted/"
ALLOW_PREFIX = "https://docs.ros.org/en/kilted/"
PACKAGE_DOCS_PREFIX = "https://docs.ros.org/en/kilted/p/"
SKIP_EXT = (
    ".css",
    ".js",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".svg",
    ".ico",
    ".woff",
    ".woff2",
    ".ttf",
    ".eot",
    ".map",
    ".pdf",
    ".zip",
    ".tar",
    ".gz",
    ".mp4",
    ".webm",
)
SKIP_PATH_PARTS = ("/_static/", "/_images/", "/_sources/", "/_downloads/")


def url_allowed(url: str, limit_package_docs: bool) -> bool:
    """Gate URLs. Filters static assets, Apache mod_autoindex sort variants,
    and when limit_package_docs is True, allows only each package's landing
    page under /p/ (not auto-generated Doxygen class/file subpages)."""
    if not url.startswith(ALLOW_PREFIX):
        return False
    # Drop Apache directory-listing sort params (they duplicate indexes).
    if "?C=" in url or "&C=" in url:
        return False
    lower = url.lower().split("?", 1)[0].split("#", 1)[0]
    if any(lower.endswith(ext) for ext in SKIP_EXT):
        return False
    if any(part in url for part in SKIP_PATH_PARTS):
        return False
    if not limit_package_docs:
        return True
    if not url.startswith(PACKAGE_DOCS_PREFIX):
        return True
    tail = url[len(PACKAGE_DOCS_PREFIX) :]
    tail = tail.split("?", 1)[0].split("#", 1)[0]
    parts = [p for p in tail.split("/") if p]
    if len(parts) == 0:
        return True  # /p/ index
    if len(parts) == 1:
        return True  # /p/<pkg>  or /p/<pkg>/
    if len(parts) == 2 and parts[1] in ("index.html", "README.html"):
        return True
    return False


def extract_links(html: str, base_url: str) -> Iterable[str]:
    href_pattern = re.compile(r'href=["\']([^"\']+)["\']', re.IGNORECASE)
    for match in href_pattern.finditer(html):
        href = match.group(1).strip()
        if (
            not href
            or href.startswith("#")
            or href.startswith("mailto:")
            or href.startswith("javascript:")
        ):
            continue
        absolute = urljoin(base_url, href)
        absolute, _ = urldefrag(absolute)
        yield absolute


def html_to_text(html: str) -> str:
    no_script = re.sub(r"<script[\s\S]*?</script>", "", html, flags=re.IGNORECASE)
    no_style = re.sub(r"<style[\s\S]*?</style>", "", no_script, flags=re.IGNORECASE)
    no_tags = re.sub(r"<[^>]+>", "\n", no_style)
    text = re.sub(r"\n{3,}", "\n\n", no_tags)
    return text.strip()


def extract_title(html: str) -> str:
    match = re.search(r"<title>(.*?)</title>", html, flags=re.IGNORECASE | re.DOTALL)
    if not match:
        return ""
    return re.sub(r"\s+", " ", match.group(1)).strip()


def sanitize_filename(url: str) -> str:
    parsed = urlparse(url)
    path = parsed.path.strip("/")
    if not path:
        path = "index"
    safe = re.sub(r"[^a-zA-Z0-9._/-]", "_", path)
    safe = safe.replace("/", "__")
    return f"{safe}.txt"


def split_text_to_chunks(text: str, chunk_size: int, chunk_overlap: int) -> list[str]:
    if not text:
        return []
    if chunk_overlap >= chunk_size:
        raise ValueError("chunk_overlap must be smaller than chunk_size")
    chunks: list[str] = []
    start = 0
    step = chunk_size - chunk_overlap
    while start < len(text):
        end = start + chunk_size
        piece = text[start:end].strip()
        if piece:
            chunks.append(piece)
        start += step
    return chunks


def crawl(
    max_pages: int,
    timeout: float,
    output_dir: Path,
    chunk_size: int,
    chunk_overlap: int,
    limit_package_docs: bool = False,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    raw_pages_dir = output_dir / "raw_pages"
    raw_pages_dir.mkdir(parents=True, exist_ok=True)

    queue: deque[str] = deque([START_URL])
    visited: set[str] = set()
    crawl_records: list[dict] = []
    documents: list[dict] = []
    chunks: list[dict] = []
    graph_edges: list[dict] = []

    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        while queue and len(visited) < max_pages:
            url = queue.popleft()
            if url in visited:
                continue
            if not url_allowed(url, limit_package_docs):
                continue

            try:
                response = client.get(url)
                response.raise_for_status()
            except Exception as exc:  # noqa: BLE001
                crawl_records.append({"url": url, "ok": False, "error": str(exc)})
                visited.add(url)
                continue

            content_type = response.headers.get("content-type", "")
            if "text/html" not in content_type:
                visited.add(url)
                continue

            html = response.text
            text = html_to_text(html)
            title = extract_title(html)
            filename = sanitize_filename(url)
            (raw_pages_dir / filename).write_text(text, encoding="utf-8")

            outgoing: list[str] = []
            for link in extract_links(html, url):
                if url_allowed(link, limit_package_docs):
                    outgoing.append(link)
                    if link not in visited:
                        queue.append(link)
                    graph_edges.append(
                        {
                            "source": url,
                            "target": link,
                            "relation": "links_to",
                        }
                    )

            visited.add(url)
            crawl_records.append(
                {
                    "url": url,
                    "ok": True,
                    "status_code": response.status_code,
                    "chars": len(text),
                    "saved_file": str((raw_pages_dir / filename).name),
                    "outgoing_links": len(outgoing),
                }
            )
            ok_count = sum(1 for r in crawl_records if r.get("ok"))
            print(
                f"[{ok_count}/{max_pages}] queue={len(queue)} chars={len(text)} {url}", flush=True
            )

            documents.append(
                {
                    "doc_id": url,
                    "url": url,
                    "title": title,
                    "source": "docs.ros.org",
                    "version": "kilted",
                    "lang": "en",
                    "content_type": "text/html",
                    "text_chars": len(text),
                    "outgoing_links": list(dict.fromkeys(outgoing)),
                    "saved_file": filename,
                }
            )

            page_chunks = split_text_to_chunks(
                text, chunk_size=chunk_size, chunk_overlap=chunk_overlap
            )
            for idx, chunk_text in enumerate(page_chunks):
                chunks.append(
                    {
                        "chunk_id": f"{url}#chunk-{idx:04d}",
                        "doc_id": url,
                        "url": url,
                        "title": title,
                        "chunk_index": idx,
                        "text": chunk_text,
                        "text_chars": len(chunk_text),
                        "source": "docs.ros.org",
                        "version": "kilted",
                        "lang": "en",
                    }
                )

    summary = {
        "start_url": START_URL,
        "allow_prefix": ALLOW_PREFIX,
        "max_pages": max_pages,
        "visited_count": len(visited),
        "success_count": sum(1 for r in crawl_records if r.get("ok")),
        "failed_count": sum(1 for r in crawl_records if not r.get("ok")),
        "document_count": len(documents),
        "chunk_count": len(chunks),
        "edge_count": len(graph_edges),
        "chunk_size": chunk_size,
        "chunk_overlap": chunk_overlap,
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }

    (output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (output_dir / "crawl_records.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in crawl_records),
        encoding="utf-8",
    )
    (output_dir / "documents.jsonl").write_text(
        "\n".join(json.dumps(d, ensure_ascii=False) for d in documents), encoding="utf-8"
    )
    (output_dir / "chunks.jsonl").write_text(
        "\n".join(json.dumps(c, ensure_ascii=False) for c in chunks), encoding="utf-8"
    )
    (output_dir / "graph_edges.jsonl").write_text(
        "\n".join(json.dumps(e, ensure_ascii=False) for e in graph_edges),
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Crawl ROS2 Kilted docs into RAG-ready artifacts.")
    parser.add_argument("--max-pages", type=int, default=120, help="Maximum pages to crawl.")
    parser.add_argument("--timeout", type=float, default=20.0, help="Request timeout in seconds.")
    parser.add_argument(
        "--chunk-size", type=int, default=1400, help="Chunk size for vector indexing."
    )
    parser.add_argument(
        "--chunk-overlap", type=int, default=200, help="Overlap between adjacent chunks."
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("database/ros2-kilted"),
        help="Output directory for crawl artifacts.",
    )
    parser.add_argument(
        "--limit-package-docs",
        action="store_true",
        help="Under /p/, only crawl each package's landing page (skip auto-generated Doxygen subpages).",
    )
    args = parser.parse_args()
    crawl(
        max_pages=args.max_pages,
        timeout=args.timeout,
        output_dir=args.output_dir,
        chunk_size=args.chunk_size,
        chunk_overlap=args.chunk_overlap,
        limit_package_docs=args.limit_package_docs,
    )


if __name__ == "__main__":
    main()
