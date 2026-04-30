"""Probe LM Studio: list loaded models, then run the Architect prompt
against the State Owned Enterprises context using the existing AIClient.
Surfaces any upstream provider error (e.g. n_keep >= n_ctx)."""
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, r"D:\Ai Project")
os.chdir(r"D:\Ai Project")

import requests
from mendix_analyzer.mpr_extractor import ExtractedData, _empty_sections
from mendix_analyzer.scanner import MendixScanner
from mendix_analyzer.ai_client import AIClient
from mendix_analyzer import pipeline as P


BASE = "http://localhost:1234"
DUMP_DIR = Path(r"D:\Ai Project\dumps\State Owned Enterprises Platform")
PROJECT_DIR = r"D:\LCGPA_Branches\StateOwnedEnterprice"
PROJECT_NAME = "State Owned Enterprises Platform"
MPR = str(Path(PROJECT_DIR) / f"{PROJECT_NAME}.mpr")


def list_models():
    r = requests.get(f"{BASE}/v1/models", timeout=5)
    print(f"  HTTP {r.status_code}  {r.text[:200]}")
    if r.ok:
        data = r.json().get("data", [])
        print(f"  {len(data)} model(s):")
        for m in data:
            print(f"    - {m.get('id')}")
        return [m.get("id") for m in data]
    return []


def load_dump():
    manifest = json.loads((DUMP_DIR / "_manifest.json").read_text(encoding="utf-8"))
    sections = _empty_sections()
    for k, fp in manifest["files"].items():
        if Path(fp).exists():
            sections[k] = json.loads(Path(fp).read_text(encoding="utf-8"))
    res = ExtractedData(
        project_name=PROJECT_NAME, mpr_path=MPR, sections=sections,
        duration_seconds=manifest.get("duration_seconds", 0.0),
        raw_unit_count=manifest.get("raw_unit_count", 0))
    res.dump_dir = str(DUMP_DIR)
    res.section_files = manifest.get("files", {})
    return res


def build_context(compact: bool = False):
    extract = load_dump()
    sc = MendixScanner()
    scan = sc.scan(PROJECT_DIR, run_mpr_extract=False)
    scan.mpr_data = extract
    scan.mpr_path = MPR
    return sc.to_context_string(scan, compact=compact)


def run_agent(model: str, context: str):
    print(f"\n--- Running Architect against model: {model} ---")
    client = AIClient("LM Studio")
    chunks = []

    def on_token(t):
        chunks.append(t)
        # Print first 200 tokens then a dot per chunk to keep output sane
        if len(chunks) <= 50:
            print(t, end="", flush=True)
        elif len(chunks) == 51:
            print("\n[...truncating live output, will summarise at end...]", flush=True)

    user_content = "## PROJECT METADATA\n" + context + "\n\n"
    messages = [
        {"role": "system", "content": P.ARCHITECT_PROMPT},
        {"role": "user",   "content": user_content},
    ]
    t0 = time.time()
    try:
        out = client.chat(model=model, messages=messages, on_token=on_token,
                          temperature=0.3, max_tokens=8192)
        dt = time.time() - t0
        print(f"\n\n=== Result ===")
        print(f"  duration       : {dt:.1f}s")
        print(f"  chunks streamed: {len(chunks)}")
        print(f"  content length : {len(out):,} chars")
        print(f"  preview        : {out[:400]!r}")
    except Exception as e:
        dt = time.time() - t0
        print(f"\n\n=== ERROR after {dt:.1f}s ===")
        print(f"  {type(e).__name__}: {e}")


print("=== /v1/models ===")
ids = list_models()

if not ids:
    print("\nNo models loaded in LM Studio. Aborting agent probe.")
    sys.exit(0)

COMPACT = os.environ.get("COMPACT", "1") not in ("0", "false", "False", "")
print(f"\n=== Building context (compact={COMPACT}) ===")
ctx = build_context(compact=COMPACT)
print(f"  context chars: {len(ctx):,}  ~tokens: {len(ctx)//4:,}")
total = len(P.ARCHITECT_PROMPT) + len("## PROJECT METADATA\n") + len(ctx) + 4
print(f"  full prompt  : {total:,} chars  ~{total//4:,} tokens")

# Try the first non-embedding model
target = next((m for m in ids if "embed" not in m.lower()), ids[0])
run_agent(target, ctx)
