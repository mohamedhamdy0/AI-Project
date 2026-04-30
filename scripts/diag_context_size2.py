"""Measure the exact context-string length and estimated token count
that the analysis pipeline sends, by reusing the existing per-section
dump on disk (no re-extraction)."""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, r"D:\Ai Project")
os.chdir(r"D:\Ai Project")

from mendix_analyzer.mpr_extractor import ExtractedData, _empty_sections
from mendix_analyzer.scanner import MendixScanner
from mendix_analyzer import pipeline as P


def load_dump(dump_dir: Path, project_name: str, mpr_path: str) -> ExtractedData:
    manifest = json.loads((dump_dir / "_manifest.json").read_text(encoding="utf-8"))
    sections = _empty_sections()
    for k, fp in manifest["files"].items():
        if Path(fp).exists():
            sections[k] = json.loads(Path(fp).read_text(encoding="utf-8"))
    res = ExtractedData(
        project_name=project_name,
        mpr_path=mpr_path,
        sections=sections,
        duration_seconds=manifest.get("duration_seconds", 0.0),
        raw_unit_count=manifest.get("raw_unit_count", 0),
    )
    res.dump_dir = str(dump_dir)
    res.dump_path = str(dump_dir)
    res.section_files = manifest.get("files", {})
    return res


def measure(project_dir: str, dump_subdir: str, project_name: str, mpr_filename: str):
    print(f"\n{'='*70}\n {project_name}\n{'='*70}")
    dump = Path(r"D:\Ai Project\dumps") / dump_subdir
    mpr_path = str(Path(project_dir) / mpr_filename)
    if not Path(mpr_path).exists():
        print(f"  SKIP: mpr not found at {mpr_path}")
        return None

    extract = load_dump(dump, project_name, mpr_path)

    sc = MendixScanner()
    scan = sc.scan(project_dir, run_mpr_extract=False)
    if scan is None:
        print("  scan returned None")
        return None
    scan.mpr_data = extract
    scan.mpr_path = mpr_path

    for label, compact in (("FULL", False), ("COMPACT", True)):
        full = sc.to_context_string(scan, compact=compact)
        sysprompt = P.ARCHITECT_PROMPT
        user_content = "## PROJECT METADATA\n" + full + "\n\n"
        total = len(sysprompt) + len(user_content)
        est_tok = total // 4
        need = est_tok + 8192
        print(f"  [{label:<7}]  ctx_chars={len(full):>7,}  prompt_chars={total:>7,}  "
              f"~tokens={est_tok:>6,}  need_n_ctx>={need:>6,}  "
              f"4K={'OK' if need<=4096 else 'FAIL'}  "
              f"8K={'OK' if need<=8192 else 'FAIL'}  "
              f"32K={'OK' if need<=32768 else 'FAIL'}")
    return None


measure(
    r"D:\LCGPA_Branches\StateOwnedEnterprice",
    "State Owned Enterprises Platform",
    "State Owned Enterprises Platform",
    "State Owned Enterprises Platform.mpr",
)

measure(
    r"D:\LCGPA_Branches\EV_Production_v10",
    "LCGPA Service Application",
    "LCGPA Service Application",
    "LCGPA Service Application.mpr",
)
