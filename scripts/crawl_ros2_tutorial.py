"""Crawl https://zsc.github.io/ros2_tutorial/ into RAG-ready artifacts.

The site is a GitHub Pages static site (Markdown → HTML).
All 24 chapters live under the same origin, no dynamic JS needed.
Re-uses the same output schema as crawl_ros2_kilted.py so the
clean_rag_database.py / build_vector_index.py pipeline works unchanged.
"""

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

START_URL = "https://zsc.github.io/ros2_tutorial/"
ALLOW_PREFIX = "https://zsc.github.io/ros2_tutorial/"

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
SKIP_PATH_PARTS = ("/_static/", "/_images/", "/_sources/", "/_downloads/", "/assets/")


def url_allowed(url: str) -> bool:
    if not url.startswith(ALLOW_PREFIX):
        return False
    lower = url.lower().split("?", 1)[0].split("#", 1)[0]
    if any(lower.endswith(ext) for ext in SKIP_EXT):
        return False
    if any(part in url for part in SKIP_PATH_PARTS):
        return False
    return True


def extract_links(html: str, base_url: str) -> Iterable[str]:
    for match in re.finditer(r'href=["\']([^"\']+)["\']', html, re.IGNORECASE):
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
    """Strip tags; for Markdown-generated HTML this gives back clean prose."""
    text = re.sub(r"<script[\s\S]*?</script>", "", html, flags=re.IGNORECASE)
    text = re.sub(r"<style[\s\S]*?</style>", "", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def extract_title(html: str) -> str:
    match = re.search(r"<title>(.*?)</title>", html, flags=re.IGNORECASE | re.DOTALL)
    if not match:
        return ""
    return re.sub(r"\s+", " ", match.group(1)).strip()


def sanitize_filename(url: str) -> str:
    path = urlparse(url).path.strip("/") or "index"
    safe = re.sub(r"[^a-zA-Z0-9._/-]", "_", path).replace("/", "__")
    return f"{safe}.txt"


def split_text_to_chunks(text: str, chunk_size: int, chunk_overlap: int) -> list[str]:
    if not text:
        return []
    chunks: list[str] = []
    step = chunk_size - chunk_overlap
    start = 0
    while start < len(text):
        piece = text[start : start + chunk_size].strip()
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
            if not url_allowed(url):
                continue

            try:
                response = client.get(url)
                response.raise_for_status()
            except Exception as exc:  # noqa: BLE001
                crawl_records.append({"url": url, "ok": False, "error": str(exc)})
                visited.add(url)
                continue

            content_type = response.headers.get("content-type", "")
            if "text/html" not in content_type and "text/plain" not in content_type:
                visited.add(url)
                continue

            html = response.text
            # If served as raw Markdown (some GH Pages configs), wrap in minimal html.
            is_markdown_raw = "text/plain" in content_type or (
                "text/html" not in content_type and url.endswith(".md")
            )
            text = html if is_markdown_raw else html_to_text(html)
            title = "" if is_markdown_raw else extract_title(html)
            if not title:
                # Derive title from first heading or filename.
                m = re.search(r"^#+ (.+)$", text, re.MULTILINE)
                title = m.group(1).strip() if m else url.split("/")[-1]

            filename = sanitize_filename(url)
            (raw_pages_dir / filename).write_text(text, encoding="utf-8")

            outgoing: list[str] = []
            for link in extract_links(html, url):
                if url_allowed(link):
                    outgoing.append(link)
                    if link not in visited:
                        queue.append(link)
                    graph_edges.append({"source": url, "target": link, "relation": "links_to"})

            visited.add(url)
            ok_count = sum(1 for r in crawl_records if r.get("ok")) + 1
            crawl_records.append(
                {
                    "url": url,
                    "ok": True,
                    "status_code": response.status_code,
                    "chars": len(text),
                    "saved_file": filename,
                    "outgoing_links": len(outgoing),
                }
            )
            print(
                f"[{ok_count}/{max_pages}] queue={len(queue)} chars={len(text)} {url}", flush=True
            )

            documents.append(
                {
                    "doc_id": url,
                    "url": url,
                    "title": title,
                    "source": "zsc.github.io/ros2_tutorial",
                    "version": "tutorial",
                    "lang": "zh",
                    "content_type": content_type,
                    "text_chars": len(text),
                    "outgoing_links": list(dict.fromkeys(outgoing)),
                    "saved_file": filename,
                }
            )

            for idx, chunk_text in enumerate(split_text_to_chunks(text, chunk_size, chunk_overlap)):
                chunks.append(
                    {
                        "chunk_id": f"{url}#chunk-{idx:04d}",
                        "doc_id": url,
                        "url": url,
                        "title": title,
                        "chunk_index": idx,
                        "text": chunk_text,
                        "text_chars": len(chunk_text),
                        "source": "zsc.github.io/ros2_tutorial",
                        "version": "tutorial",
                        "lang": "zh",
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
        "\n".join(json.dumps(r, ensure_ascii=False) for r in crawl_records), encoding="utf-8"
    )
    (output_dir / "documents.jsonl").write_text(
        "\n".join(json.dumps(d, ensure_ascii=False) for d in documents), encoding="utf-8"
    )
    (output_dir / "chunks.jsonl").write_text(
        "\n".join(json.dumps(c, ensure_ascii=False) for c in chunks), encoding="utf-8"
    )
    (output_dir / "graph_edges.jsonl").write_text(
        "\n".join(json.dumps(e, ensure_ascii=False) for e in graph_edges), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def main() -> None:
    p = argparse.ArgumentParser(description="Crawl zsc ros2_tutorial into RAG-ready artifacts.")
    p.add_argument("--max-pages", type=int, default=60)
    p.add_argument("--timeout", type=float, default=20.0)
    p.add_argument("--chunk-size", type=int, default=1400)
    p.add_argument("--chunk-overlap", type=int, default=200)
    p.add_argument("--output-dir", type=Path, default=Path("database/ros2-tutorial"))
    args = p.parse_args()
    crawl(
        max_pages=args.max_pages,
        timeout=args.timeout,
        output_dir=args.output_dir,
        chunk_size=args.chunk_size,
        chunk_overlap=args.chunk_overlap,
    )


if __name__ == "__main__":
    main()
