"""Measure the exact context-string length and estimated tokens that the
analysis pipeline would send for a given Mendix project, by reusing the
existing per-section dump on disk (no re-extraction)."""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, r"D:\Ai Project")
os.chdir(r"D:\Ai Project")

from mendix_analyzer.mpr_extractor import ExtractResult, _empty_sections
from mendix_analyzer.scanner import Scanner
from mendix_analyzer import pipeline as P


def load_dump(dump_dir: Path, project_name: str, mpr_path: str) -> ExtractResult:
    manifest = json.loads((dump_dir / "_manifest.json").read_text(encoding="utf-8"))
    sections = _empty_sections()
    for k, fp in manifest["files"].items():
        if not Path(fp).exists():
            continue
        sections[k] = json.loads(Path(fp).read_text(encoding="utf-8"))
    res = ExtractResult(
        project_name=project_name,
        mpr_path=mpr_path,
        sections=sections,
        counts=manifest.get("counts", {}),
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

    extract = load_dump(dump, project_name, mpr_path)
    digest = extract.to_context_string(max_modules=40, max_per_module=8)
    print(f"  mpr_data.to_context_string():")
    print(f"    chars      : {len(digest):>8,}")
    print(f"    est tokens : {len(digest)//4:>8,}  (~chars/4 heuristic)")

    sc = Scanner()
    scan = sc.scan_with_mpr(mpr_path, extract)
    full = sc.to_context_string(scan)
    print(f"  Full pipeline context (mpr_data + filesystem scan):")
    print(f"    chars      : {len(full):>8,}")
    print(f"    est tokens : {len(full)//4:>8,}")

    sysprompt = P.ARCHITECT_PROMPT
    user_content = "## PROJECT METADATA\n" + full + "\n\n"
    total = len(sysprompt) + len(user_content)
    print(f"  Architect agent total prompt (system+user):")
    print(f"    chars      : {total:>8,}")
    print(f"    est tokens : {total//4:>8,}")
    print(f"    + 8192 reply budget => need n_ctx >= {total//4 + 8192:>6,}")
    return full


print("State Owned Enterprises Platform:")
ctx_soep = measure(
    r"D:\LCGPA_Branches\StateOwnedEnterprice",
    "State Owned Enterprises Platform",
    "State Owned Enterprises Platform",
    "State Owned Enterprises Platform.mpr",
)

print("\nLCGPA Service Application (for reference):")
ctx_lcgpa = measure(
    r"D:\LCGPA_Branches\EV_Production_v10",
    "LCGPA Service Application",
    "LCGPA Service Application",
    "LCGPA Service Application.mpr",
)
