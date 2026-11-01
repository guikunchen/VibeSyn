#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import hashlib
import json
import os
import re
import shutil
import time
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import fitz
import httpx

from llama_index.core import (
    Document,
    Settings,
    StorageContext,
    VectorStoreIndex,
    load_index_from_storage,
)
from llama_index.core.node_parser import SentenceSplitter
from llama_index.embeddings.openai import OpenAIEmbedding
from llama_index.llms.openai import OpenAI

from dataclasses import dataclass

# ============================================================
# Logging
# ============================================================

class RunLogger:
    def __init__(self, log_dir: str) -> None:
        self.log_dir = Path(log_dir).resolve()
        self.log_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.log_path = self.log_dir / f"rag_run_{ts}.jsonl"

    def write(self, event_type: str, **payload: Any) -> None:
        record = {
            "ts": datetime.now().isoformat(),
            "event": event_type,
            **payload,
        }
        with self.log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def llm(self, name: str, prompt: str, response: Any, meta: Optional[dict[str, Any]] = None) -> None:
        self.write(
            "llm_call",
            name=name,
            meta=meta or {},
            prompt=prompt,
            response=str(response),
        )


# ============================================================
# Text helpers
# ============================================================

DASH_TRANSLATION = str.maketrans(
    {
        "–": "-",
        "—": "-",
        "−": "-",
        "‒": "-",
        "﹣": "-",
        "－": "-",
    }
)


def normalize_text(text: str) -> str:
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", text)
    text = text.translate(DASH_TRANSLATION)
    text = text.replace("\u00ad", "")
    text = re.sub(r"\s+", " ", text)
    return text.casefold().strip()


def normalize_alnum(text: str) -> str:
    text = normalize_text(text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def strip_outer_quotes(text: str) -> str:
    text = (text or "").strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {'"', "'", "“", "”", "‘", "’"}:
        text = text[1:-1].strip()
    return text


def is_bond_label(text: str) -> bool:
    t = strip_outer_quotes(text)
    return bool(re.fullmatch(r"[A-Za-z]{1,3}\s*[-−–—]\s*[A-Za-z]{1,3}", t))


def looks_like_field_token(text: str) -> bool:
    t = normalize_text(text)
    bad = [
        "c-h", "c h", "o-h", "o h", "n-h", "n h",
        "bde", "bond dissociation", "d°298", "d298",
        "kj mol", "mol-1", "a-b", "bond",
    ]
    return any(x in t for x in bad)


def is_good_exact_literal(text: str) -> bool:
    t = strip_outer_quotes(text)
    nt = normalize_text(t)

    if not nt:
        return False
    if len(t) > 60:
        return False
    if looks_like_field_token(t):
        return False

    if is_bond_label(t):
        return True
    if re.fullmatch(r"\d{2,7}-\d{2}-\d", t):
        return True
    if re.fullmatch(r"[A-Za-z0-9,()\-−–—]+", t):
        return True
    return False


def build_exact_variants(literal: str) -> list[str]:
    literal = strip_outer_quotes(literal)
    if not literal:
        return []

    variants: list[str] = []

    def add(x: str) -> None:
        x = (x or "").strip()
        if x and x not in variants:
            variants.append(x)

    def add_basic(x: str) -> None:
        add(x)
        add(x.replace("-", " "))
        add(x.replace(",", ", "))
        add(x.replace(", ", ","))
        add(x.replace("-", " - "))
        add(x.replace(",", "").replace("-", " "))
        add(re.sub(r"\s+", " ", x))

        loose = x.replace(",", " ").replace("-", " ")
        loose = re.sub(r"\s+", " ", loose).strip()
        add(loose)

    add_basic(literal)

    bond = re.fullmatch(r"\s*([^-\s]+)\s*-\s*([^-\s]+)\s*", literal)
    if bond:
        a, b = bond.group(1), bond.group(2)
        add_basic(f"{b}-{a}")

    m = re.match(r"^(\d+(?:,\d+)*)-(.+)$", literal)
    if m:
        add(f"{m.group(2).strip()}, {m.group(1)}-")

    return variants


def extract_json_obj(text: str) -> Optional[dict[str, Any]]:
    if not text:
        return None

    s = text.strip()
    s = re.sub(r"^```(?:json)?\s*", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\s*```$", "", s)

    try:
        obj = json.loads(s)
        if isinstance(obj, dict):
            return obj
    except Exception:
        pass

    start = s.find("{")
    end = s.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            obj = json.loads(s[start:end + 1])
            if isinstance(obj, dict):
                return obj
        except Exception:
            return None

    return None


# ============================================================
# File/cache helpers
# ============================================================

def file_signature(pdf_path: str) -> dict[str, Any]:
    p = Path(pdf_path).resolve()
    stat = p.stat()
    return {
        "path": str(p),
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
    }


def safe_doc_id(pdf_path: str) -> str:
    p = Path(pdf_path).resolve()
    stem = re.sub(r"[^a-zA-Z0-9_]+", "_", p.stem).strip("_") or "doc"
    suffix = hashlib.sha1(str(p).encode("utf-8")).hexdigest()[:10]
    return f"{stem}_{suffix}"


def read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def same_manifest(path: Path, current: dict[str, Any]) -> bool:
    if not path.exists():
        return False
    try:
        return read_json(path) == current
    except Exception:
        return False


def pages_to_target_string(pages: list[int]) -> str:
    pages = sorted(set(int(p) for p in pages if int(p) >= 1))
    if not pages:
        return ""

    ranges = []
    start = prev = pages[0]
    for p in pages[1:]:
        if p == prev + 1:
            prev = p
            continue
        ranges.append(str(start) if start == prev else f"{start}-{prev}")
        start = prev = p
    ranges.append(str(start) if start == prev else f"{start}-{prev}")
    return ",".join(ranges)


# ============================================================
# Markdown focusing
# ============================================================

def build_focus_snippet_from_markdown(markdown: str, exact_literals: list[str]) -> str:
    lines = markdown.splitlines()

    norm_variants = set()
    for lit in exact_literals:
        for v in build_exact_variants(lit):
            norm_variants.add(normalize_text(v))
            norm_variants.add(normalize_alnum(v))

    pipe_lines = [line for line in lines if "|" in line]
    matched_rows: list[str] = []

    for line in pipe_lines:
        n1 = normalize_text(line)
        n2 = normalize_alnum(line)
        for v in norm_variants:
            if not v:
                continue
            if v in n1 or v in n2:
                matched_rows.append(line)
                break

    if matched_rows:
        header = pipe_lines[:2]
        return "\n".join(header + matched_rows)

    matched_idx = []
    for i, line in enumerate(lines):
        n1 = normalize_text(line)
        n2 = normalize_alnum(line)
        for v in norm_variants:
            if not v:
                continue
            if v in n1 or v in n2:
                matched_idx.append(i)
                break

    if matched_idx:
        keep = set()
        for i in matched_idx:
            for j in range(max(0, i - 2), min(len(lines), i + 3)):
                keep.add(j)
        return "\n".join(lines[i] for i in sorted(keep))

    return markdown[:4000]


# ============================================================
# PDF catalog
# ============================================================

def load_pdf_catalog(pdf_dir: str, catalog_json: Optional[str]) -> dict[str, dict[str, Any]]:
    pdf_dir_path = Path(pdf_dir).resolve()
    catalog_path = Path(catalog_json).resolve() if catalog_json else (pdf_dir_path / "pdf_catalog.json")

    if catalog_path.exists():
        raw = read_json(catalog_path)
        out = {}
        if isinstance(raw, list):
            for item in raw:
                if not isinstance(item, dict):
                    continue
                file_name = item.get("file_name")
                if not isinstance(file_name, str):
                    continue
                out[file_name] = item
        elif isinstance(raw, dict):
            for file_name, item in raw.items():
                if isinstance(item, dict):
                    out[file_name] = {"file_name": file_name, **item}
        return out

    # fallback inference
    out: dict[str, dict[str, Any]] = {}
    for p in sorted(pdf_dir_path.glob("*.pdf")):
        fname = p.name
        role = "default"
        if fname == "bond_energies.pdf":
            role = "compact_d298_bond_table"
        elif fname == "Handbook_of_Bond_Dissociation_Energies.pdf":
            role = "comprehensive_handbook"
        out[fname] = {
            "file_name": fname,
            "role": role,
            "description": "",
            "aliases": [],
        }
    return out


# ============================================================
# LlamaParse page-targeted parser with local cache
# ============================================================

class LlamaParsePageParser:
    def __init__(
        self,
        api_key: str,
        cache_dir: str,
        logger: RunLogger,
        tier: str = "agentic",
        version: str = "latest",
        timeout: float = 300.0,
        poll_interval: float = 2.0,
        max_poll_seconds: float = 240.0,
        output_tables_as_markdown: bool = True,
        merge_continued_tables: bool = True,
    ) -> None:
        self.api_key = api_key
        self.cache_dir = Path(cache_dir).resolve()
        self.logger = logger
        self.tier = tier
        self.version = version
        self.timeout = timeout
        self.poll_interval = poll_interval
        self.max_poll_seconds = max_poll_seconds
        self.output_tables_as_markdown = output_tables_as_markdown
        self.merge_continued_tables = merge_continued_tables
        self.base_url = "https://api.cloud.llamaindex.ai/api/v2"

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"}

    def _cache_key(self, pdf_path: str, pages: list[int]) -> str:
        payload = {
            "file": file_signature(pdf_path),
            "pages": sorted(set(pages)),
            "tier": self.tier,
            "version": self.version,
            "output_tables_as_markdown": self.output_tables_as_markdown,
            "merge_continued_tables": self.merge_continued_tables,
        }
        raw = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]

    def _cache_file(self, pdf_path: str, pages: list[int]) -> Path:
        doc_id = safe_doc_id(pdf_path)
        key = self._cache_key(pdf_path, pages)
        return self.cache_dir / doc_id / "llamaparse_pages" / f"{key}.json"

    def _extract_job_id(self, obj: dict[str, Any]) -> Optional[str]:
        for path in [
            ("job", "id"),
            ("result", "job", "id"),
            ("id",),
            ("job_id",),
        ]:
            cur: Any = obj
            ok = True
            for k in path:
                if isinstance(cur, dict) and k in cur:
                    cur = cur[k]
                else:
                    ok = False
                    break
            if ok and isinstance(cur, str) and cur:
                return cur
        return None

    def _extract_status(self, obj: dict[str, Any]) -> Optional[str]:
        for path in [
            ("job", "status"),
            ("result", "job", "status"),
            ("status",),
        ]:
            cur: Any = obj
            ok = True
            for k in path:
                if isinstance(cur, dict) and k in cur:
                    cur = cur[k]
                else:
                    ok = False
                    break
            if ok and isinstance(cur, str):
                return cur
        return None

    def _extract_error(self, obj: dict[str, Any]) -> Optional[str]:
        for path in [
            ("job", "error_message"),
            ("error_message",),
            ("error", "message"),
        ]:
            cur: Any = obj
            ok = True
            for k in path:
                if isinstance(cur, dict) and k in cur:
                    cur = cur[k]
                else:
                    ok = False
                    break
            if ok and isinstance(cur, str) and cur:
                return cur
        return None

    def _extract_markdown_pages(self, obj: dict[str, Any], requested_pages: list[int]) -> list[dict[str, Any]]:
        candidates = None

        if isinstance(obj.get("markdown"), dict) and isinstance(obj["markdown"].get("pages"), list):
            candidates = obj["markdown"]["pages"]
        elif (
            isinstance(obj.get("result"), dict)
            and isinstance(obj["result"].get("markdown"), dict)
            and isinstance(obj["result"]["markdown"].get("pages"), list)
        ):
            candidates = obj["result"]["markdown"]["pages"]

        if not isinstance(candidates, list):
            return []

        out = []
        for i, item in enumerate(candidates):
            if not isinstance(item, dict):
                continue
            page_num = item.get("page") or item.get("page_num") or item.get("pageNumber") or item.get("index")
            markdown = item.get("markdown") or item.get("text") or item.get("content") or ""
            if page_num is None and i < len(requested_pages):
                page_num = requested_pages[i]
            if isinstance(page_num, int) and isinstance(markdown, str):
                out.append({"page_num": page_num, "markdown": markdown})

        out.sort(key=lambda x: x["page_num"])
        return out

    def parse_pages(self, pdf_path: str, pages: list[int]) -> dict[str, Any]:
        pages = sorted(set(int(p) for p in pages if int(p) >= 1))
        if not pages:
            return {"pages": [], "source": "none"}

        cache_file = self._cache_file(pdf_path, pages)
        if cache_file.exists():
            cached = read_json(cache_file)
            cached["source"] = "local_cache"
            self.logger.write(
                "llamaparse_cache_hit",
                pdf_path=str(Path(pdf_path).resolve()),
                pages=pages,
                cache_file=str(cache_file),
            )
            return cached

        target_pages = pages_to_target_string(pages)
        configuration = {
            "tier": self.tier,
            "version": self.version,
            "page_ranges": {
                "target_pages": target_pages,
            },
            "output_options": {
                "markdown": {
                    "tables": {
                        "output_tables_as_markdown": self.output_tables_as_markdown,
                        "compact_markdown_tables": False,
                        "merge_continued_tables": self.merge_continued_tables,
                    }
                }
            },
        }

        self.logger.write(
            "llamaparse_request",
            pdf_path=str(Path(pdf_path).resolve()),
            pages=pages,
            configuration=configuration,
        )

        with httpx.Client(timeout=self.timeout) as client:
            with open(pdf_path, "rb") as f:
                files = {"file": (Path(pdf_path).name, f, "application/pdf")}
                data = {"configuration": json.dumps(configuration)}
                resp = client.post(
                    f"{self.base_url}/parse/upload",
                    headers=self._headers(),
                    files=files,
                    data=data,
                )
                resp.raise_for_status()
                obj = resp.json()

            pages_md = self._extract_markdown_pages(obj, pages)
            if pages_md:
                payload = {
                    "pdf_path": str(Path(pdf_path).resolve()),
                    "requested_pages": pages,
                    "parsed_pages": pages_md,
                    "tier": self.tier,
                    "version": self.version,
                }
                write_json(cache_file, payload)
                payload["source"] = "fresh_parse_inline"
                self.logger.write("llamaparse_response", mode="inline", pages=pages, parsed_pages=pages_md)
                return payload

            job_id = self._extract_job_id(obj)
            if not job_id:
                raise RuntimeError(f"Could not find parse job id in response: {obj}")

            deadline = time.time() + self.max_poll_seconds
            while time.time() < deadline:
                poll = client.get(
                    f"{self.base_url}/parse/{job_id}",
                    headers=self._headers(),
                    params={"expand": "markdown"},
                )
                poll.raise_for_status()
                status_obj = poll.json()

                status = (self._extract_status(status_obj) or "").upper()
                if status == "COMPLETED":
                    pages_md = self._extract_markdown_pages(status_obj, pages)
                    if not pages_md:
                        raise RuntimeError(f"Parse job {job_id} completed but no markdown pages were returned.")
                    payload = {
                        "pdf_path": str(Path(pdf_path).resolve()),
                        "requested_pages": pages,
                        "parsed_pages": pages_md,
                        "tier": self.tier,
                        "version": self.version,
                        "job_id": job_id,
                    }
                    write_json(cache_file, payload)
                    payload["source"] = "fresh_parse_poll"
                    self.logger.write("llamaparse_response", mode="poll", job_id=job_id, pages=pages, parsed_pages=pages_md)
                    return payload

                if status in {"FAILED", "CANCELLED"}:
                    err = self._extract_error(status_obj) or f"Parse job {job_id} ended with status {status}."
                    self.logger.write("llamaparse_error", job_id=job_id, error=err)
                    raise RuntimeError(err)

                time.sleep(self.poll_interval)

            err = f"LlamaParse job {job_id} did not complete within {self.max_poll_seconds} seconds."
            self.logger.write("llamaparse_error", job_id=job_id, error=err)
            raise TimeoutError(err)


# ============================================================
# Main RAG
# ============================================================

class AgenticChemRAG:
    def __init__(
        self,
        pdf_dir: str,
        cache_dir: str,
        pdf_catalog: dict[str, dict[str, Any]],
        llm: OpenAI,
        embed_model: OpenAIEmbedding,
        parse_client: LlamaParsePageParser,
        logger: RunLogger,
        rebuild: bool = False,
        chunk_size: int = 900,
        chunk_overlap: int = 120,
        similarity_top_k: int = 4,
        show_trajectory: bool = True,
    ) -> None:
        self.pdf_dir = Path(pdf_dir).resolve()
        self.cache_dir = Path(cache_dir).resolve()
        self.pdf_catalog = pdf_catalog
        self.llm = llm
        self.embed_model = embed_model
        self.parse_client = parse_client
        self.logger = logger
        self.rebuild = rebuild
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.similarity_top_k = similarity_top_k
        self.show_trajectory = show_trajectory

        self.pdf_paths = self._discover_pdfs(self.pdf_dir)
        self.doc_info: dict[str, dict[str, Any]] = {}
        self.page_store: dict[str, list[dict[str, Any]]] = {}
        self.indexes: dict[str, Optional[VectorStoreIndex]] = {}
        self.index_errors: dict[str, Optional[str]] = {}

        self.splitter = SentenceSplitter(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
        )

        for pdf_path in self.pdf_paths:
            self._prepare_one_pdf(pdf_path)

    # --------------------------------------------------------
    # Console
    # --------------------------------------------------------

    def _print(self, text: str) -> None:
        if self.show_trajectory:
            print(text, flush=True)

    def _short(self, x: Any, max_len: int = 260) -> str:
        if isinstance(x, (dict, list)):
            s = json.dumps(x, ensure_ascii=False)
        else:
            s = str(x)
        s = re.sub(r"\s+", " ", s).strip()
        return s if len(s) <= max_len else s[:max_len] + " ..."

    def _print_step(self, step: Any, action: str, result: Optional[dict[str, Any]] = None, **kwargs: Any) -> None:
        self._print(f"\n[STEP {step}] action={action}")
        for k, v in kwargs.items():
            if v is None:
                continue
            if k == "doc_id":
                v = self.doc_info.get(v, {}).get("file_name", v)
                self._print(f"  doc={v}")
            else:
                self._print(f"  {k}={self._short(v, 220)}")

        if not result:
            return
        if "num_hits" in result:
            self._print(f"  num_hits={result['num_hits']}")
        if "variants" in result:
            self._print(f"  variants={result['variants']}")
        if "pages" in result:
            self._print(f"  pages={result['pages']}")
        if "source" in result:
            self._print(f"  source={result['source']}")
        if result.get("hits"):
            self._print(f"  first_hit={self._short(result['hits'][0], 220)}")
        if result.get("text"):
            self._print(f"  evidence_preview={self._short(result['text'], 220)}")
        if result.get("parsed_pages"):
            self._print(f"  first_parsed_page={self._short(result['parsed_pages'][0], 220)}")
        if result.get("error"):
            self._print(f"  error={result['error']}")

    # --------------------------------------------------------
    # Discovery and cache paths
    # --------------------------------------------------------

    def _discover_pdfs(self, pdf_dir: Path) -> list[str]:
        if not pdf_dir.exists():
            raise FileNotFoundError(f"pdf_dir not found: {pdf_dir}")
        if not pdf_dir.is_dir():
            raise NotADirectoryError(f"pdf_dir is not a directory: {pdf_dir}")

        pdfs = sorted(
            str(p.resolve())
            for p in pdf_dir.iterdir()
            if p.is_file() and p.suffix.lower() == ".pdf"
        )
        if not pdfs:
            raise FileNotFoundError(f"No PDF files found in directory: {pdf_dir}")
        return pdfs

    def _doc_cache_dir(self, doc_id: str) -> Path:
        return self.cache_dir / doc_id

    def _page_manifest_path(self, doc_id: str) -> Path:
        return self._doc_cache_dir(doc_id) / "pages_manifest.json"

    def _page_cache_path(self, doc_id: str) -> Path:
        return self._doc_cache_dir(doc_id) / "pages.json"

    def _index_manifest_path(self, doc_id: str) -> Path:
        return self._doc_cache_dir(doc_id) / "index_manifest.json"

    def _index_dir(self, doc_id: str) -> Path:
        return self._doc_cache_dir(doc_id) / "index"

    # --------------------------------------------------------
    # Local extraction and semantic index
    # --------------------------------------------------------

    def _prepare_one_pdf(self, pdf_path: str) -> None:
        doc_id = safe_doc_id(pdf_path)
        file_name = Path(pdf_path).name
        catalog_meta = self.pdf_catalog.get(file_name, {})

        self.doc_info[doc_id] = {
            "doc_id": doc_id,
            "file_name": file_name,
            "path": str(Path(pdf_path).resolve()),
            "role": catalog_meta.get("role", "default"),
            "description": catalog_meta.get("description", ""),
            "aliases": catalog_meta.get("aliases", []),
        }

        self.page_store[doc_id] = self._load_or_build_page_cache(pdf_path, doc_id)
        index, err = self._load_or_build_index(doc_id, pdf_path)
        self.indexes[doc_id] = index
        self.index_errors[doc_id] = err

    def _extract_page_record(self, page: fitz.Page, doc_id: str, file_name: str, page_num: int) -> dict[str, Any]:
        raw_text = page.get_text("text", sort=True) or ""
        words = page.get_text("words", sort=True) or []
        word_text = " ".join(w[4] for w in words if len(w) >= 5)

        semantic_text = raw_text if len(raw_text.strip()) >= len(word_text.strip()) else word_text

        return {
            "doc_id": doc_id,
            "file_name": file_name,
            "page_num": page_num,
            "raw_text": raw_text,
            "word_text": word_text,
            "semantic_text": semantic_text,
            "norm_raw": normalize_text(raw_text),
            "norm_word": normalize_text(word_text),
            "alnum_raw": normalize_alnum(raw_text),
            "alnum_word": normalize_alnum(word_text),
        }

    def _load_or_build_page_cache(self, pdf_path: str, doc_id: str) -> list[dict[str, Any]]:
        current = {
            "type": "page_cache_v1_pymupdf",
            "file": file_signature(pdf_path),
        }
        manifest_path = self._page_manifest_path(doc_id)
        cache_path = self._page_cache_path(doc_id)

        if (not self.rebuild) and same_manifest(manifest_path, current) and cache_path.exists():
            return read_json(cache_path)

        file_name = Path(pdf_path).name
        doc = fitz.open(pdf_path)
        pages: list[dict[str, Any]] = []
        try:
            for page_num, page in enumerate(doc, start=1):
                pages.append(self._extract_page_record(page, doc_id, file_name, page_num))
        finally:
            doc.close()

        write_json(cache_path, pages)
        write_json(manifest_path, current)
        return pages

    def _load_or_build_index(
        self,
        doc_id: str,
        pdf_path: str,
    ) -> tuple[Optional[VectorStoreIndex], Optional[str]]:
        current = {
            "type": "vector_index_v1_pymupdf",
            "file": file_signature(pdf_path),
            "embed_model": getattr(
                self.embed_model,
                "model_name",
                getattr(self.embed_model, "model", "unknown"),
            ),
            "chunk_size": self.chunk_size,
            "chunk_overlap": self.chunk_overlap,
        }

        manifest_path = self._index_manifest_path(doc_id)
        index_dir = self._index_dir(doc_id)

        if (not self.rebuild) and same_manifest(manifest_path, current) and index_dir.exists():
            try:
                storage_context = StorageContext.from_defaults(persist_dir=str(index_dir))
                return load_index_from_storage(storage_context), None
            except Exception as e:
                shutil.rmtree(index_dir, ignore_errors=True)
                self._print(f"[WARN] Failed to load cached index for {Path(pdf_path).name}: {e}")
                self.logger.write("semantic_index_load_error", pdf_path=pdf_path, error=str(e))

        try:
            docs: list[Document] = []
            for page in self.page_store[doc_id]:
                text = page["semantic_text"]
                if not text.strip():
                    continue
                docs.append(
                    Document(
                        text=text,
                        metadata={
                            "doc_id": doc_id,
                            "file_name": page["file_name"],
                            "page_num": page["page_num"],
                        },
                    )
                )

            if not docs:
                raise RuntimeError("No text extracted from PDF.")

            nodes = self.splitter.get_nodes_from_documents(docs)
            if not nodes:
                raise RuntimeError("SentenceSplitter returned no nodes.")

            index = VectorStoreIndex(nodes)

            tmp_dir = index_dir.with_name(index_dir.name + "_tmp")
            shutil.rmtree(tmp_dir, ignore_errors=True)
            tmp_dir.mkdir(parents=True, exist_ok=True)
            index.storage_context.persist(persist_dir=str(tmp_dir))

            if index_dir.exists():
                shutil.rmtree(index_dir, ignore_errors=True)
            tmp_dir.rename(index_dir)

            write_json(manifest_path, current)
            return index, None

        except Exception as e:
            self.logger.write("semantic_index_build_error", pdf_path=pdf_path, error=str(e))
            return None, str(e)

    # --------------------------------------------------------
    # Tools
    # --------------------------------------------------------

    def tool_list_pdfs(self) -> dict[str, Any]:
        docs = []
        for doc_id, meta in self.doc_info.items():
            docs.append(
                {
                    "doc_id": doc_id,
                    "file_name": meta["file_name"],
                    "role": meta["role"],
                    "description": meta["description"],
                    "num_pages": len(self.page_store[doc_id]),
                    "semantic_ready": self.indexes.get(doc_id) is not None,
                }
            )
        return {"documents": docs}

    def tool_exact_search(self, doc_id: str, literal: str, max_hits: int = 6) -> dict[str, Any]:
        pages = self.page_store.get(doc_id, [])
        variants = build_exact_variants(literal)
        hits: list[dict[str, Any]] = []

        for page in pages:
            matched_variant = None
            matched_mode = None

            for v in variants:
                q = normalize_text(v)
                qa = normalize_alnum(v)
                if not q:
                    continue

                if q in page["norm_raw"]:
                    matched_variant = v
                    matched_mode = "norm_raw"
                    break
                if q in page["norm_word"]:
                    matched_variant = v
                    matched_mode = "norm_word"
                    break
                if qa and qa in page["alnum_raw"]:
                    matched_variant = v
                    matched_mode = "alnum_raw"
                    break
                if qa and qa in page["alnum_word"]:
                    matched_variant = v
                    matched_mode = "alnum_word"
                    break

            if matched_variant is not None:
                p = page["page_num"]
                max_page = len(pages)
                hits.append(
                    {
                        "doc_id": doc_id,
                        "file_name": page["file_name"],
                        "matched_variant": matched_variant,
                        "match_mode": matched_mode,
                        "hit_page": p,
                        "hit_page_only": [p],
                        "recommended_pages": [x for x in (p - 1, p, p + 1) if 1 <= x <= max_page],
                    }
                )

        return {
            "doc_id": doc_id,
            "literal": strip_outer_quotes(literal),
            "variants": variants,
            "num_hits": len(hits[:max_hits]),
            "hits": hits[:max_hits],
        }

    def tool_semantic_search(self, doc_id: str, query: str, top_k: Optional[int] = None) -> dict[str, Any]:
        top_k = top_k or self.similarity_top_k
        index = self.indexes.get(doc_id)
        if index is None:
            return {
                "doc_id": doc_id,
                "query": query,
                "num_hits": 0,
                "hits": [],
                "error": self.index_errors.get(doc_id) or "Semantic index unavailable.",
            }

        try:
            retriever = index.as_retriever(similarity_top_k=top_k)
            results = retriever.retrieve(query)
        except Exception as e:
            self.logger.write("semantic_retrieval_error", doc_id=doc_id, query=query, error=str(e))
            return {
                "doc_id": doc_id,
                "query": query,
                "num_hits": 0,
                "hits": [],
                "error": f"Semantic retrieval failed: {e}",
            }

        hits = []
        for rank, item in enumerate(results, start=1):
            node = item.node
            meta = dict(getattr(node, "metadata", {}) or {})
            hits.append(
                {
                    "rank": rank,
                    "score": float(item.score) if item.score is not None else None,
                    "doc_id": meta.get("doc_id", doc_id),
                    "file_name": meta.get("file_name", self.doc_info[doc_id]["file_name"]),
                    "page": meta.get("page_num") or meta.get("page_label") or meta.get("page"),
                    "text": node.get_content()[:1800],
                }
            )

        return {
            "doc_id": doc_id,
            "query": query,
            "num_hits": len(hits),
            "hits": hits,
        }

    def tool_parse_pages(self, doc_id: str, pages: list[int]) -> dict[str, Any]:
        pdf_path = self.doc_info[doc_id]["path"]
        try:
            return self.parse_client.parse_pages(pdf_path, pages)
        except Exception as e:
            self.logger.write("llamaparse_error", doc_id=doc_id, pages=pages, error=str(e))
            return {
                "error": str(e),
                "requested_pages": pages,
                "parsed_pages": [],
            }

    # --------------------------------------------------------
    # Planning and ranking
    # --------------------------------------------------------

    def _llm_json(self, name: str, prompt: str, meta: Optional[dict[str, Any]] = None) -> Optional[dict[str, Any]]:
        try:
            resp = self.llm.complete(prompt)
            self.logger.llm(name, prompt, resp, meta=meta)
            return extract_json_obj(str(resp))
        except Exception as e:
            self.logger.write("llm_error", name=name, meta=meta or {}, error=str(e), prompt=prompt)
            return None

    def _heuristic_plan(self, question: str) -> dict[str, Any]:
        question_norm = normalize_text(question)

        # bond-label lookup
        bond_match = re.findall(r'["“]?([A-Za-z]{1,3}\s*[-−–—]\s*[A-Za-z]{1,3})["”]?', question)
        if bond_match:
            target = strip_outer_quotes(bond_match[0])
            return {
                "query_type": "bond_label_lookup",
                "target_entity": target,
                "target_field": "D°298/kJ mol-1" if ("d°298" in question_norm or "kj mol" in question_norm) else "",
                "exact_literals": [target],
                "semantic_queries": [question],
            }

        # compound property lookup: try quoted or "for X"
        candidates = []
        candidates.extend(re.findall(r'"([^"]+)"', question))
        candidates.extend(re.findall(r"'([^']+)'", question))
        for pat in [r"\bfor\s+([^.?;]+)", r"\bof\s+([^.?;]+)"]:
            for m in re.finditer(pat, question, flags=re.IGNORECASE):
                cand = m.group(1).strip().strip('"\' ')
                cand = cand.strip(" \t\n\r.,;:()[]{}")
                if cand:
                    candidates.append(cand)

        # prefer compound-like candidates over field-like ones
        cleaned = []
        seen = set()
        for c in candidates:
            c = strip_outer_quotes(c)
            if not c or looks_like_field_token(c):
                continue
            key = normalize_text(c)
            if key not in seen:
                seen.add(key)
                cleaned.append(c)

        target_entity = cleaned[-1] if cleaned else ""
        query_type = "compound_property_lookup" if target_entity else "other"

        return {
            "query_type": query_type,
            "target_entity": target_entity,
            "target_field": "C-H BDE" if "c-h" in question_norm and "dioxane" in question_norm else "",
            "exact_literals": [target_entity] if target_entity else [],
            "semantic_queries": [question],
        }

    def make_plan(self, question: str) -> dict[str, Any]:
        prompt = f"""
You are planning a chemistry PDF RAG query.

Question:
{question}

Return ONLY JSON:
{{
  "query_type": "bond_label_lookup | compound_property_lookup | other",
  "target_entity": "...",
  "target_field": "...",
  "exact_literals": ["..."],
  "semantic_queries": ["...", "..."]
}}

Rules:
- bond_label_lookup: direct bond label such as Cl−H, Br−H, C−O.
- compound_property_lookup: named compound or species such as 1,4-dioxane.
- For compound_property_lookup, exact_literals must contain ONLY compound names, aliases, or CAS-like identifiers.
- Do NOT include generic bond types like C-H, O-H, BDE, D°298, units.
- For bond_label_lookup, exact_literals should contain only the bond label.
- target_field should be concise, e.g. "D°298/kJ mol-1" or "C-H BDE".
"""
        obj = self._llm_json("make_plan", prompt, meta={"question": question})

        if not obj:
            obj = self._heuristic_plan(question)

        query_type = str(obj.get("query_type", "")).strip() or self._heuristic_plan(question)["query_type"]
        target_entity = strip_outer_quotes(str(obj.get("target_entity", "")).strip())
        target_field = str(obj.get("target_field", "")).strip()

        exact_literals = []
        seen = set()
        items = obj.get("exact_literals", [])
        if isinstance(items, list):
            for lit in items:
                lit = strip_outer_quotes(str(lit).strip())
                if query_type == "compound_property_lookup" and looks_like_field_token(lit):
                    continue
                if not is_good_exact_literal(lit):
                    continue
                key = normalize_text(lit)
                if key and key not in seen:
                    seen.add(key)
                    exact_literals.append(lit)

        if query_type == "bond_label_lookup":
            if target_entity and is_bond_label(target_entity):
                exact_literals = [target_entity]
        elif query_type == "compound_property_lookup":
            exact_literals = [x for x in exact_literals if not is_bond_label(x)]
            if target_entity:
                tkey = normalize_text(target_entity)
                if all(normalize_text(x) != tkey for x in exact_literals):
                    exact_literals = [target_entity] + exact_literals

        if not exact_literals:
            exact_literals = self._heuristic_plan(question)["exact_literals"]

        semantic_queries = []
        items = obj.get("semantic_queries", [])
        if isinstance(items, list):
            for q in items:
                q = str(q).strip()
                if q:
                    semantic_queries.append(q)
        if not semantic_queries:
            semantic_queries = [question]

        return {
            "query_type": query_type,
            "target_entity": target_entity,
            "target_field": target_field,
            "exact_literals": exact_literals[:4],
            "semantic_queries": semantic_queries[:3],
        }

    def rank_documents(self, question: str, plan: dict[str, Any]) -> list[str]:
        query_type = plan["query_type"]
        target_field = normalize_text(plan.get("target_field", ""))

        scored = []
        for doc_id, meta in self.doc_info.items():
            role = meta.get("role", "default")
            score = 0

            if query_type == "bond_label_lookup" and ("d°298" in target_field or "kj mol" in target_field or target_field == ""):
                if role == "compact_d298_bond_table":
                    score += 10
                elif role == "comprehensive_handbook":
                    score += 5
            else:
                if role == "comprehensive_handbook":
                    score += 10
                elif role == "compact_d298_bond_table":
                    score += 5

            scored.append((score, meta["file_name"], doc_id))

        scored.sort(key=lambda x: (-x[0], x[1]))
        return [doc_id for _, _, doc_id in scored]

    # --------------------------------------------------------
    # Extraction
    # --------------------------------------------------------

    def try_extract_exact_answer(
        self,
        question: str,
        plan: dict[str, Any],
        parsed_payload: dict[str, Any],
        file_name: str,
    ) -> Optional[str]:
        page_blocks = []
        focus_blocks = []

        for item in parsed_payload.get("parsed_pages", []):
            markdown = item["markdown"]
            page_blocks.append(
                f"===== {file_name} | PAGE {item['page_num']} START =====\n"
                f"{markdown}\n"
                f"===== {file_name} | PAGE {item['page_num']} END ====="
            )
            focus = build_focus_snippet_from_markdown(markdown, plan["exact_literals"])
            focus_blocks.append(
                f"===== {file_name} | PAGE {item['page_num']} FOCUS START =====\n"
                f"{focus}\n"
                f"===== {file_name} | PAGE {item['page_num']} FOCUS END ====="
            )

        if not page_blocks:
            return None

        full_text = "\n\n".join(page_blocks)
        focus_text = "\n\n".join(focus_blocks)

        prompt = f"""
You are extracting a chemistry value from parsed evidence.

Question:
{question}

Query type:
{plan["query_type"]}

Target entity:
{plan["target_entity"]}

Target field:
{plan["target_field"]}

Focused evidence:
{focus_text[:8000]}

Full evidence:
{full_text[:14000]}

Return ONLY JSON:
{{
  "found": true or false,
  "answer": "1-3 sentence final answer if found, else empty string"
}}

Rules:
- Use only the evidence.
- For bond_label_lookup, the answer must match the exact bond label or a normalized equivalent.
- For compound_property_lookup, do NOT return a generic value unless the target entity itself appears in the evidence.
- If the evidence only gives a general C-H or generic bond value without the target compound, found=false.
- Keep the answer short.
"""
        obj = self._llm_json(
            "extract_exact_answer",
            prompt,
            meta={
                "file_name": file_name,
                "query_type": plan["query_type"],
                "target_entity": plan["target_entity"],
                "target_field": plan["target_field"],
            },
        )
        if not obj:
            return None
        if bool(obj.get("found")) and str(obj.get("answer", "")).strip():
            return str(obj["answer"]).strip()
        return None

    def try_extract_generic_answer(
        self,
        question: str,
        plan: dict[str, Any],
        parsed_payload: dict[str, Any],
        file_name: str,
    ) -> Optional[str]:
        blocks = []
        for item in parsed_payload.get("parsed_pages", []):
            blocks.append(
                f"===== {file_name} | PAGE {item['page_num']} START =====\n"
                f"{item['markdown']}\n"
                f"===== {file_name} | PAGE {item['page_num']} END ====="
            )

        if not blocks:
            return None

        blocks_text = "\n\n".join(blocks)

        prompt = f"""
You are checking whether the parsed evidence is enough to answer the question.

Question:
{question}

Query type:
{plan["query_type"]}

Target entity:
{plan["target_entity"]}

Target field:
{plan["target_field"]}

Parsed markdown evidence:
{blocks_text[:16000]}

Return ONLY JSON:
{{
  "found": true or false,
  "answer": "1-3 sentence final answer if found, else empty string"
}}

Rules:
- Use only the evidence.
- For compound_property_lookup, the target entity must appear in the evidence. Do NOT return a generic C-H value.
- If the evidence is incomplete or ambiguous, found=false.
- Keep the answer short.
"""
        obj = self._llm_json(
            "extract_generic_answer",
            prompt,
            meta={
                "file_name": file_name,
                "query_type": plan["query_type"],
                "target_entity": plan["target_entity"],
                "target_field": plan["target_field"],
            },
        )
        if not obj:
            return None
        if bool(obj.get("found")) and str(obj.get("answer", "")).strip():
            return str(obj["answer"]).strip()
        return None

    def parsed_payload_to_evidence(self, mode: str, file_name: str, parsed_payload: dict[str, Any]) -> dict[str, Any]:
        pages = []
        blocks = []
        for item in parsed_payload.get("parsed_pages", []):
            pages.append(item["page_num"])
            blocks.append(
                f"===== {file_name} | PAGE {item['page_num']} START =====\n"
                f"{item['markdown']}\n"
                f"===== {file_name} | PAGE {item['page_num']} END ====="
            )
        text = "\n\n".join(blocks)
        return {
            "mode": mode,
            "file_name": file_name,
            "pages": pages,
            "text": text,
        }

    def pick_best_evidence(self, evidence_pool: list[dict[str, Any]]) -> Optional[dict[str, Any]]:
        if not evidence_pool:
            return None
        exact_blocks = [e for e in evidence_pool if e["mode"] == "exact_search"]
        if exact_blocks:
            return exact_blocks[-1]
        return evidence_pool[-1]

    def extract_final_answer(self, question: str, plan: dict[str, Any], evidence: Optional[dict[str, Any]]) -> str:
        if evidence is None:
            return "I could not find a clearly supported answer in the available PDF evidence."

        prompt = f"""
You are answering from one parsed evidence block only.

Question:
{question}

Query type:
{plan["query_type"]}

Target entity:
{plan["target_entity"]}

Target field:
{plan["target_field"]}

Evidence source:
{evidence["file_name"]}

Pages:
{evidence["pages"]}

Evidence:
{evidence["text"][:16000]}

Write 1-3 sentences only.
Use only the evidence.
For compound_property_lookup, do not return a generic bond value unless the target entity appears in evidence.
If the value is not clearly present, say it was not found clearly in the retrieved evidence.
"""
        try:
            resp = self.llm.complete(prompt)
            self.logger.llm("final_answer", prompt, resp, meta={"file_name": evidence["file_name"]})
            return str(resp).strip()
        except Exception as e:
            self.logger.write("llm_error", name="final_answer", error=str(e), prompt=prompt)
            return "I found relevant evidence, but the final extraction step failed."

    # --------------------------------------------------------
    # Main flow
    # --------------------------------------------------------

    def answer(self, question: str) -> str:
        plan = self.make_plan(question)
        doc_order = self.rank_documents(question, plan)

        self.logger.write(
            "plan",
            question=question,
            plan=plan,
            ranked_pdfs=[self.doc_info[d]["file_name"] for d in doc_order],
        )

        self._print("[PLAN]")
        self._print(f"  query_type={plan['query_type']}")
        self._print(f"  target_entity={plan['target_entity']}")
        self._print(f"  target_field={plan['target_field']}")
        self._print(f"  exact_literals={plan['exact_literals']}")
        self._print(f"  semantic_queries={plan['semantic_queries']}")
        self._print(f"  ranked_pdfs={[self.doc_info[d]['file_name'] for d in doc_order]}")

        evidence_pool: list[dict[str, Any]] = []
        searched_documents_in_order: list[str] = []

        docs_result = self.tool_list_pdfs()
        self._print_step(1, "list_pdfs", docs_result, reason="Inspect available PDFs first.")
        self.logger.write("step", step=1, action="list_pdfs", result=docs_result)

        step = 2

        for doc_id in doc_order:
            file_name = self.doc_info[doc_id]["file_name"]
            if file_name not in searched_documents_in_order:
                searched_documents_in_order.append(file_name)

            # exact search first
            for literal in plan["exact_literals"]:
                exact_result = self.tool_exact_search(doc_id, literal)
                self._print_step(step, "exact_search", exact_result, doc_id=doc_id, literal=literal, reason="Try exact lookup first on this PDF.")
                self.logger.write("step", step=step, action="exact_search", doc=file_name, literal=literal, result=exact_result)
                step += 1

                if exact_result.get("num_hits", 0) == 0:
                    continue

                hit = exact_result["hits"][0]

                page_only = hit["hit_page_only"]
                parsed_narrow = self.tool_parse_pages(doc_id, page_only)
                self._print_step(step, "llamaparse_pages", parsed_narrow, doc_id=doc_id, pages=page_only, reason="Parse the hit page only first.")
                self.logger.write("step", step=step, action="llamaparse_pages", doc=file_name, pages=page_only, result=parsed_narrow)
                step += 1

                if not parsed_narrow.get("error"):
                    evidence_pool.append(self.parsed_payload_to_evidence("exact_search", file_name, parsed_narrow))
                    direct = self.try_extract_exact_answer(question, plan, parsed_narrow, file_name)
                    if direct is not None:
                        self._print("\n[FINAL EXTRACTION]")
                        self._print(f"  source_file={file_name}")
                        self._print(f"  pages={page_only}")
                        self._print("  mode=exact_search")

                        self.logger.write(
                            "final_answer",
                            answer=direct,
                            searched_pdfs=searched_documents_in_order,
                            mode="exact_search",
                            file_name=file_name,
                            pages=page_only,
                        )

                        print("\n[FINAL ANSWER]")
                        print(direct)
                        print(f"(searched PDFs: {searched_documents_in_order})")
                        print(f"(used exact_search from {file_name} pages {page_only})")
                        print(f"(log file: {self.logger.log_path})")
                        return direct

                wide_pages = hit["recommended_pages"]
                if sorted(set(wide_pages)) != sorted(set(page_only)):
                    parsed_wide = self.tool_parse_pages(doc_id, wide_pages)
                    self._print_step(step, "llamaparse_pages_expand", parsed_wide, doc_id=doc_id, pages=wide_pages, reason="Single-page parse was insufficient; expand to neighboring pages.")
                    self.logger.write("step", step=step, action="llamaparse_pages_expand", doc=file_name, pages=wide_pages, result=parsed_wide)
                    step += 1

                    if not parsed_wide.get("error"):
                        evidence_pool.append(self.parsed_payload_to_evidence("exact_search", file_name, parsed_wide))
                        direct = self.try_extract_exact_answer(question, plan, parsed_wide, file_name)
                        if direct is not None:
                            self._print("\n[FINAL EXTRACTION]")
                            self._print(f"  source_file={file_name}")
                            self._print(f"  pages={wide_pages}")
                            self._print("  mode=exact_search")

                            self.logger.write(
                                "final_answer",
                                answer=direct,
                                searched_pdfs=searched_documents_in_order,
                                mode="exact_search",
                                file_name=file_name,
                                pages=wide_pages,
                            )

                            print("\n[FINAL ANSWER]")
                            print(direct)
                            print(f"(searched PDFs: {searched_documents_in_order})")
                            print(f"(used exact_search from {file_name} pages {wide_pages})")
                            print(f"(log file: {self.logger.log_path})")
                            return direct

                break

            # semantic fallback
            for query in plan["semantic_queries"]:
                semantic_result = self.tool_semantic_search(doc_id, query, self.similarity_top_k)
                self._print_step(step, "semantic_search", semantic_result, doc_id=doc_id, query=query, reason="Use semantic retrieval only if exact evidence was not enough.")
                self.logger.write("step", step=step, action="semantic_search", doc=file_name, query=query, result=semantic_result)
                step += 1

                if semantic_result.get("num_hits", 0) == 0:
                    continue

                top_hit = semantic_result["hits"][0]
                top_page = top_hit.get("page")
                if not isinstance(top_page, int):
                    continue

                narrow_pages = [top_page]
                parsed_narrow = self.tool_parse_pages(doc_id, narrow_pages)
                self._print_step(step, "llamaparse_pages", parsed_narrow, doc_id=doc_id, pages=narrow_pages, reason="Parse the top semantic hit page only first.")
                self.logger.write("step", step=step, action="llamaparse_pages", doc=file_name, pages=narrow_pages, result=parsed_narrow)
                step += 1

                if not parsed_narrow.get("error"):
                    evidence_pool.append(self.parsed_payload_to_evidence("semantic_search", file_name, parsed_narrow))
                    direct = self.try_extract_generic_answer(question, plan, parsed_narrow, file_name)
                    if direct is not None:
                        self._print("\n[FINAL EXTRACTION]")
                        self._print(f"  source_file={file_name}")
                        self._print(f"  pages={narrow_pages}")
                        self._print("  mode=semantic_search")

                        self.logger.write(
                            "final_answer",
                            answer=direct,
                            searched_pdfs=searched_documents_in_order,
                            mode="semantic_search",
                            file_name=file_name,
                            pages=narrow_pages,
                        )

                        print("\n[FINAL ANSWER]")
                        print(direct)
                        print(f"(searched PDFs: {searched_documents_in_order})")
                        print(f"(used semantic_search from {file_name} pages {narrow_pages})")
                        print(f"(log file: {self.logger.log_path})")
                        return direct

                wide_pages = sorted(set([max(1, top_page - 1), top_page, top_page + 1]))
                if wide_pages != narrow_pages:
                    parsed_wide = self.tool_parse_pages(doc_id, wide_pages)
                    self._print_step(step, "llamaparse_pages_expand", parsed_wide, doc_id=doc_id, pages=wide_pages, reason="Single-page semantic parse was insufficient; expand to neighboring pages.")
                    self.logger.write("step", step=step, action="llamaparse_pages_expand", doc=file_name, pages=wide_pages, result=parsed_wide)
                    step += 1

                    if not parsed_wide.get("error"):
                        evidence_pool.append(self.parsed_payload_to_evidence("semantic_search", file_name, parsed_wide))
                        direct = self.try_extract_generic_answer(question, plan, parsed_wide, file_name)
                        if direct is not None:
                            self._print("\n[FINAL EXTRACTION]")
                            self._print(f"  source_file={file_name}")
                            self._print(f"  pages={wide_pages}")
                            self._print("  mode=semantic_search")

                            self.logger.write(
                                "final_answer",
                                answer=direct,
                                searched_pdfs=searched_documents_in_order,
                                mode="semantic_search",
                                file_name=file_name,
                                pages=wide_pages,
                            )

                            print("\n[FINAL ANSWER]")
                            print(direct)
                            print(f"(searched PDFs: {searched_documents_in_order})")
                            print(f"(used semantic_search from {file_name} pages {wide_pages})")
                            print(f"(log file: {self.logger.log_path})")
                            return direct

                break

        best = self.pick_best_evidence(evidence_pool)

        self._print("\n[FINAL EXTRACTION]")
        if best is None:
            self._print("  no evidence block available")
        else:
            self._print(f"  source_file={best['file_name']}")
            self._print(f"  pages={best['pages']}")
            self._print(f"  mode={best['mode']}")

        final_answer = self.extract_final_answer(question, plan, best)
        self.logger.write(
            "final_answer",
            answer=final_answer,
            searched_pdfs=searched_documents_in_order,
            mode=best["mode"] if best else None,
            file_name=best["file_name"] if best else None,
            pages=best["pages"] if best else None,
        )

        print("\n[FINAL ANSWER]")
        print(final_answer)
        print(f"(searched PDFs: {searched_documents_in_order})")
        if best is not None:
            print(f"(used {best['mode']} from {best['file_name']} pages {best['pages']})")
        print(f"(log file: {self.logger.log_path})")
        return final_answer


# ============================================================
# Model builder
# ============================================================

def build_models(
    model: str,
    embedding_model: str,
    api_key: str,
    api_base: Optional[str] = None,
) -> tuple[OpenAI, OpenAIEmbedding]:
    llm = OpenAI(
        model=model,
        api_key=api_key,
        api_base=api_base,
        temperature=0,
        timeout=120.0,
        max_retries=3,
    )
    embed_model = OpenAIEmbedding(
        model=embedding_model,
        api_key=api_key,
        api_base=api_base,
        embed_batch_size=32,
        timeout=120.0,
        max_retries=3,
    )
    return llm, embed_model


@dataclass(frozen=True)
class HandbookRAGConfig:
    pdf_dir: str
    catalog_json: Optional[str] = None
    cache_dir: str = "src/chem_main/tools/config/HandbookSearchHelper/cache"
    model: str = os.environ.get("OPENAI_MODEL", "gpt-5")
    embedding_model: str = os.environ.get("OPENAI_EMBED_MODEL", "text-embedding-3-small")
    api_key: Optional[str] = os.environ.get("OPENAI_API_KEY")
    api_base: Optional[str] = os.environ.get("OPENAI_API_BASE")
    llama_cloud_api_key: Optional[str] = os.environ.get("LLAMA_CLOUD_API_KEY")
    parse_tier: str = "agentic"
    parse_version: str = "latest"
    rebuild: bool = False
    chunk_size: int = 900
    chunk_overlap: int = 120
    similarity_top_k: int = 4
    show_trajectory: bool = False


class HandbookRAGService:
    def __init__(self, config: HandbookRAGConfig):
        self.config = config

        if not config.api_key:
            raise RuntimeError("Missing OPENAI_API_KEY.")
        if not config.llama_cloud_api_key:
            raise RuntimeError("Missing LLAMA_CLOUD_API_KEY.")

        cache_dir = Path(config.cache_dir)
        logger = RunLogger(cache_dir / "logs")

        pdf_catalog = load_pdf_catalog(config.pdf_dir, config.catalog_json)
        logger.write("pdf_catalog", catalog=pdf_catalog)

        llm, embed_model = build_models(
            model=config.model,
            embedding_model=config.embedding_model,
            api_key=config.api_key,
            api_base=config.api_base,
        )

        Settings.llm = llm
        Settings.embed_model = embed_model

        parse_client = LlamaParsePageParser(
            api_key=config.llama_cloud_api_key,
            cache_dir=config.cache_dir,
            logger=logger,
            tier=config.parse_tier,
            version=config.parse_version,
        )

        self.rag = AgenticChemRAG(
            pdf_dir=config.pdf_dir,
            cache_dir=config.cache_dir,
            pdf_catalog=pdf_catalog,
            llm=llm,
            embed_model=embed_model,
            parse_client=parse_client,
            logger=logger,
            rebuild=config.rebuild,
            chunk_size=config.chunk_size,
            chunk_overlap=config.chunk_overlap,
            similarity_top_k=config.similarity_top_k,
            show_trajectory=config.show_trajectory,
        )

    def query(self, prompt: str) -> str:
        result = self.rag.answer(prompt)
        if result is None:
            raise RuntimeError("rag.answer(prompt) returned None. Please modify AgenticChemRAG.answer to return the final answer text.")

        if isinstance(result, str):
            return result

        if hasattr(result, "response"):
            return result.response

        return str(result)


def get_handbook_rag_service(config: HandbookRAGConfig) -> HandbookRAGService:
    return HandbookRAGService(config)
