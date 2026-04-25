"""Second-pass cleaning for ROS2 Kilted RAG database.

Reads:  database/ros2-kilted/{documents.jsonl, raw_pages/*.txt, graph_edges.jsonl}
Writes: database/ros2-kilted-clean/{documents.jsonl, chunks.jsonl, graph_edges.jsonl,
                                   boilerplate.txt, summary.json}

Key operations:
  1. HTML entity unescape + terminal-escape/artifact strip.
  2. Cross-document boilerplate detection (Sphinx sidebar/nav/footer).
  3. Fragment-line reconstruction into real paragraphs.
  4. Paragraph-aware re-chunking with title + breadcrumb prefix for embedding.
  5. Graph-edge filtering: drop static assets, self-loops, duplicates, non-doc targets.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import time
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse

ALLOW_PREFIX = "https://docs.ros.org/en/kilted/"
STATIC_EXT = (
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
)
SKIP_URL_PARTS = (
    "_static/",
    "_images/",
    "_sources/",
    "genindex.html",
    "search.html",
    "py-modindex.html",
)

TERMINAL_ARTIFACTS = re.compile(r"\\?\^J|\\\\")
MULTI_WS = re.compile(r"[ \t]+")
MULTI_NEWLINE = re.compile(r"\n{3,}")
BLANK_SPLIT = re.compile(r"\n\s*\n+")
SENT_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\-#])")
TITLE_SUFFIX = re.compile(
    r"\s*&mdash;\s*ROS 2 Documentation.*$|\s*—\s*ROS 2 Documentation.*$", re.IGNORECASE
)
PUNCT_ONLY = re.compile(r"^[\W_\s]+$", re.UNICODE)  # nothing but punctuation / whitespace
ALPHA_RATIO = re.compile(r"[A-Za-z\u00c0-\u024f]")


# ---------- helpers ---------------------------------------------------------


def normalize_line(s: str) -> str:
    s = html.unescape(s)
    s = TERMINAL_ARTIFACTS.sub(" ", s)
    s = MULTI_WS.sub(" ", s)
    return s.strip()


def clean_title(raw: str) -> str:
    t = html.unescape(raw or "")
    t = TITLE_SUFFIX.sub("", t)
    return MULTI_WS.sub(" ", t).strip()


def breadcrumb_from_url(url: str) -> str:
    """Derive a human-readable section path from the URL."""
    parsed = urlparse(url)
    path = parsed.path.split("/en/kilted/", 1)[-1]
    path = path.rstrip("/")
    if path.endswith(".html"):
        path = path[:-5]
    if not path or path == "index":
        return "ROS 2 Kilted"
    parts = [p.replace("-", " ").replace("_", " ").strip() for p in path.split("/")]
    parts = [p for p in parts if p]
    return " / ".join(parts)


# ---------- boilerplate detection ------------------------------------------


def build_boilerplate(
    raw_dir: Path, min_doc_ratio: float = 0.30, min_line_chars: int = 1
) -> set[str]:
    """A line appearing (normalized) in >= min_doc_ratio of pages is boilerplate."""
    line_doc_count: Counter[str] = Counter()
    total_docs = 0
    for fp in raw_dir.iterdir():
        if not fp.is_file():
            continue
        total_docs += 1
        seen: set[str] = set()
        for raw in fp.read_text(encoding="utf-8", errors="ignore").splitlines():
            n = normalize_line(raw)
            if len(n) < min_line_chars:
                continue
            seen.add(n)
        for line in seen:
            line_doc_count[line] += 1
    threshold = max(2, int(total_docs * min_doc_ratio))
    return {line for line, c in line_doc_count.items() if c >= threshold}


# ---------- paragraph reconstruction ---------------------------------------


def is_meaningful_paragraph(p: str, min_chars: int = 15, min_alpha_ratio: float = 0.35) -> bool:
    if not p or len(p) < min_chars:
        return False
    if PUNCT_ONLY.match(p):
        return False
    alpha_count = len(ALPHA_RATIO.findall(p))
    return alpha_count / max(1, len(p)) >= min_alpha_ratio


def reconstruct_paragraphs(
    raw_text: str,
    boilerplate: set[str],
    page_title_variants: set[str],
    merge_short_threshold: int = 80,
) -> list[str]:
    """Turn the fragment-lined crawl dump into real paragraphs."""
    lines = [normalize_line(l) for l in raw_text.splitlines()]
    # Drop boilerplate + title-header residue + single-char debris.
    lines = [
        l
        for l in lines
        if l
        and l not in boilerplate
        and l not in page_title_variants
        and not (len(l) == 1 and not l.isalnum())
    ]

    # Rebuild paragraph blocks by collapsing single newlines within dense regions.
    # After boilerplate removal, consecutive short lines are the word-level
    # fragmentation artifact — merge them.
    paragraphs: list[str] = []
    buffer: list[str] = []

    def flush():
        if buffer:
            merged = " ".join(buffer)
            merged = MULTI_WS.sub(" ", merged).strip()
            if merged:
                paragraphs.append(merged)
            buffer.clear()

    for line in lines:
        if len(line) < merge_short_threshold:
            buffer.append(line)
        else:
            if buffer:
                # Prepend buffer content to this paragraph for smoother reading.
                combined = " ".join(buffer) + " " + line
                paragraphs.append(MULTI_WS.sub(" ", combined).strip())
                buffer.clear()
            else:
                paragraphs.append(line)
    flush()

    # Drop low-signal paragraphs (pure punctuation residue, too short).
    paragraphs = [p for p in paragraphs if is_meaningful_paragraph(p)]

    # Dedup adjacent duplicates (the crawler often repeats headings).
    deduped: list[str] = []
    for p in paragraphs:
        if deduped and deduped[-1] == p:
            continue
        deduped.append(p)
    return deduped


# ---------- chunking --------------------------------------------------------


def split_long_paragraph(p: str, target: int) -> list[str]:
    if len(p) <= target:
        return [p]
    sentences = SENT_SPLIT.split(p)
    out: list[str] = []
    buf = ""
    for s in sentences:
        if not s:
            continue
        if not buf:
            buf = s
        elif len(buf) + 1 + len(s) <= target:
            buf = f"{buf} {s}"
        else:
            out.append(buf)
            buf = s
    if buf:
        out.append(buf)
    # Hard-split any remaining giants (e.g. code blocks with no sentence breaks).
    final: list[str] = []
    for piece in out:
        while len(piece) > target * 1.3:
            final.append(piece[:target])
            piece = piece[target - 100 :]  # small overlap
        final.append(piece)
    return final


def chunk_paragraphs(paragraphs: list[str], target_size: int, overlap_paragraphs: int) -> list[str]:
    """Pack paragraphs into chunks near `target_size` chars; carry overlap paragraphs between chunks."""
    expanded: list[str] = []
    for p in paragraphs:
        expanded.extend(split_long_paragraph(p, target_size))

    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    for p in expanded:
        add_len = len(p) + (2 if current else 0)
        if current and current_len + add_len > target_size:
            chunks.append("\n\n".join(current))
            # carry tail paragraphs as overlap context
            if overlap_paragraphs > 0:
                current = current[-overlap_paragraphs:]
                current_len = sum(len(x) for x in current) + 2 * max(0, len(current) - 1)
            else:
                current, current_len = [], 0
        current.append(p)
        current_len += add_len
    if current:
        chunks.append("\n\n".join(current))
    return chunks


# ---------- graph edges -----------------------------------------------------


def keep_edge(source: str, target: str, doc_ids: set[str]) -> bool:
    if source == target:
        return False
    if not (source.startswith(ALLOW_PREFIX) and target.startswith(ALLOW_PREFIX)):
        return False
    if any(target.lower().endswith(ext) for ext in STATIC_EXT):
        return False
    if any(part in target for part in SKIP_URL_PARTS):
        return False
    # keep only links into crawled documents (drop dead / un-crawled targets)
    return target in doc_ids


# ---------- main pipeline ---------------------------------------------------


def run(in_dir: Path, out_dir: Path, target_size: int, overlap_paragraphs: int) -> None:
    docs_in = in_dir / "documents.jsonl"
    edges_in = in_dir / "graph_edges.jsonl"
    raw_dir = in_dir / "raw_pages"

    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"[1/5] building boilerplate set from {raw_dir} ...")
    boilerplate = build_boilerplate(raw_dir)
    (out_dir / "boilerplate.txt").write_text("\n".join(sorted(boilerplate)), encoding="utf-8")
    print(f"      -> {len(boilerplate)} shared lines marked as boilerplate")

    # Load documents index (for title + saved_file mapping).
    doc_records: dict[str, dict] = {}
    with docs_in.open(encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            d = json.loads(line)
            doc_records[d["doc_id"]] = d
    doc_ids = set(doc_records.keys())
    print(f"[2/5] loaded {len(doc_records)} documents")

    print("[3/5] cleaning + re-chunking ...")
    cleaned_docs: list[dict] = []
    cleaned_chunks: list[dict] = []
    stats = {"pages_with_content": 0, "pages_empty_after_clean": 0}

    for doc_id, d in doc_records.items():
        saved = d.get("saved_file")
        if not saved:
            continue
        raw_path = raw_dir / saved
        if not raw_path.exists():
            continue
        raw_text = raw_path.read_text(encoding="utf-8", errors="ignore")
        title = clean_title(d.get("title", ""))
        crumb = breadcrumb_from_url(doc_id)
        raw_title = html.unescape(d.get("title", ""))
        title_variants = {
            v for v in {raw_title, title, f"{title} documentation", raw_title.strip()} if v
        }
        paragraphs = reconstruct_paragraphs(raw_text, boilerplate, title_variants)
        if not paragraphs:
            stats["pages_empty_after_clean"] += 1
            continue
        stats["pages_with_content"] += 1
        full_text = "\n\n".join(paragraphs)

        cleaned_docs.append(
            {
                "doc_id": doc_id,
                "url": d.get("url", doc_id),
                "title": title,
                "breadcrumb": crumb,
                "source": d.get("source", "docs.ros.org"),
                "version": d.get("version", "kilted"),
                "lang": d.get("lang", "en"),
                "text_chars": len(full_text),
                "paragraph_count": len(paragraphs),
                "text": full_text,
            }
        )

        page_chunks = chunk_paragraphs(paragraphs, target_size, overlap_paragraphs)
        prefix = f"[{title}] {crumb}"
        for idx, chunk_text in enumerate(page_chunks):
            embed_text = f"{prefix}\n\n{chunk_text}"
            cleaned_chunks.append(
                {
                    "chunk_id": f"{doc_id}#chunk-{idx:04d}",
                    "doc_id": doc_id,
                    "url": d.get("url", doc_id),
                    "title": title,
                    "breadcrumb": crumb,
                    "chunk_index": idx,
                    "text": chunk_text,
                    "embed_text": embed_text,
                    "text_chars": len(chunk_text),
                    "embed_chars": len(embed_text),
                    "source": d.get("source", "docs.ros.org"),
                    "version": d.get("version", "kilted"),
                    "lang": d.get("lang", "en"),
                }
            )

    print(f"      -> docs kept: {len(cleaned_docs)}, chunks: {len(cleaned_chunks)}")

    print("[4/5] filtering graph edges ...")
    kept_edges: list[dict] = []
    seen_edges: set[tuple[str, str, str]] = set()
    total_raw = 0
    with edges_in.open(encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            total_raw += 1
            e = json.loads(line)
            src, tgt, rel = e.get("source", ""), e.get("target", ""), e.get("relation", "links_to")
            if not keep_edge(src, tgt, doc_ids):
                continue
            key = (src, tgt, rel)
            if key in seen_edges:
                continue
            seen_edges.add(key)
            kept_edges.append({"source": src, "target": tgt, "relation": rel})
    print(f"      -> edges: {total_raw} raw -> {len(kept_edges)} kept")

    print(f"[5/5] writing outputs to {out_dir} ...")
    with (out_dir / "documents.jsonl").open("w", encoding="utf-8") as f:
        for d in cleaned_docs:
            f.write(json.dumps(d, ensure_ascii=False) + "\n")
    with (out_dir / "chunks.jsonl").open("w", encoding="utf-8") as f:
        for c in cleaned_chunks:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
    with (out_dir / "graph_edges.jsonl").open("w", encoding="utf-8") as f:
        for e in kept_edges:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")

    chunk_sizes = [c["text_chars"] for c in cleaned_chunks] or [0]
    summary = {
        "source_dir": str(in_dir),
        "output_dir": str(out_dir),
        "document_count": len(cleaned_docs),
        "chunk_count": len(cleaned_chunks),
        "edge_count": len(kept_edges),
        "boilerplate_lines": len(boilerplate),
        "pages_empty_after_clean": stats["pages_empty_after_clean"],
        "chunk_size_target": target_size,
        "chunk_overlap_paragraphs": overlap_paragraphs,
        "chunk_size_stats": {
            "min": min(chunk_sizes),
            "max": max(chunk_sizes),
            "avg": round(sum(chunk_sizes) / len(chunk_sizes), 1),
        },
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    (out_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("Done.")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def main() -> None:
    p = argparse.ArgumentParser(description="Second-pass RAG cleaning for ROS2 Kilted crawl.")
    p.add_argument("--input-dir", type=Path, default=Path("database/ros2-kilted"))
    p.add_argument("--output-dir", type=Path, default=Path("database/ros2-kilted-clean"))
    p.add_argument("--target-chunk-size", type=int, default=1000, help="Target chars per chunk.")
    p.add_argument(
        "--overlap-paragraphs",
        type=int,
        default=1,
        help="Number of tail paragraphs carried as overlap.",
    )
    args = p.parse_args()
    run(args.input_dir, args.output_dir, args.target_chunk_size, args.overlap_paragraphs)


if __name__ == "__main__":
    main()
