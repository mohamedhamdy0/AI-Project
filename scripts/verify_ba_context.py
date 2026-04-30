"""Verification: compact + full context for State Owned Enterprises Platform.

Asserts the BA-relevant blocks (PUBLISHED REST/SOAP SERVICES, INTEGRATIONS,
all 24 modules) are present in BOTH compact and full mode, and that the
compact prompt still fits inside an 8K-token window.
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, r"D:\Ai Project")
os.chdir(r"D:\Ai Project")

from mendix_analyzer.mpr_extractor import ExtractedData, _empty_sections  # noqa: E402
from mendix_analyzer.scanner import MendixScanner                          # noqa: E402
from mendix_analyzer import pipeline as P                                   # noqa: E402

PROJECT_DIR = r"D:\LCGPA_Branches\StateOwnedEnterprice"
MPR = str(Path(PROJECT_DIR) / "State Owned Enterprises Platform.mpr")
DUMP_DIR = Path(r"D:\Ai Project\dumps") / "State Owned Enterprises Platform"
PROJECT_NAME = "State Owned Enterprises Platform"

EXPECTED_MODULES = {
    "Administration", "AppCore", "Communication", "DocumentGeneration",
    "Email_Connector", "FeedbackModule", "FileUploader", "IntegrationLogs",
    "LcgpaDesign", "Letters", "MoCIntegration", "Notifications",
    "RecordManagement", "RequestCore", "SOEManagement", "SOERepresentatives",
    "SSOConnector", "UserClassification", "UserCommons", "UserManagement",
    "Utility", "Validations", "WebActions", "XLSReport",
}


def load_dump() -> ExtractedData:
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


def check_block(label: str, ctx: str, needle: str) -> bool:
    found = needle in ctx
    print(f"    {'OK ' if found else 'MISS'}  {label:<48}  ('{needle}')")
    return found


def check_modules(label: str, ctx: str) -> int:
    missing = sorted(m for m in EXPECTED_MODULES if m not in ctx)
    found = len(EXPECTED_MODULES) - len(missing)
    status = "OK " if not missing else "MISS"
    print(f"    {status}  {label:<48}  {found}/{len(EXPECTED_MODULES)} modules present")
    if missing:
        print(f"          missing: {missing}")
    return found


def main() -> int:
    extract = load_dump()
    print(f"counts: {extract.counts}")
    print(f"published_services entries: {len(extract.sections['published_services'])}")
    print(f"consumed_services  entries: {len(extract.sections['consumed_services'])}")
    print(f"integrations       entries: {len(extract.sections['integrations'])}")

    sc = MendixScanner()
    scan = sc.scan(PROJECT_DIR, run_mpr_extract=False)
    scan.mpr_data = extract
    scan.mpr_path = MPR

    rc = 0
    for label, compact in (("FULL", False), ("COMPACT", True)):
        ctx = sc.to_context_string(scan, compact=compact)
        sysprompt = P.BA_PROMPT
        prompt_chars = len(sysprompt) + len("## PROJECT METADATA\n") + len(ctx)
        est_tokens = prompt_chars // 4
        need_ctx = est_tokens + 8192

        print(f"\n=== {label} ===")
        print(f"  ctx_chars={len(ctx):,}  prompt_chars={prompt_chars:,}  "
              f"~tokens={est_tokens:,}  need_n_ctx>={need_ctx:,}")
        print(f"  fits 4K={'YES' if need_ctx<=4096 else 'NO'}  "
              f"8K={'YES' if need_ctx<=8192 else 'NO'}  "
              f"32K={'YES' if need_ctx<=32768 else 'NO'}")

        ok = True
        ok &= check_block(label, ctx, "=== PUBLISHED REST/SOAP SERVICES")
        ok &= check_block(label, ctx, "=== INTEGRATIONS")
        ok &= check_block(label, ctx, "=== MODULES")
        ok &= check_block(label, ctx, "=== BUSINESS MODULES \u2014 DETAIL")
        modules_found = check_modules(label, ctx)
        if modules_found != len(EXPECTED_MODULES):
            ok = False
        # Compact mode constraint: the PROMPT itself (system + user) must fit
        # comfortably in an 8K window, leaving room for a reply. The GUI's
        # pre-flight already recommends a 32K context when prompt + 8K reply
        # exceeds 8K, so we only fail here if the prompt alone exceeds 8K.
        if label == "COMPACT" and est_tokens > 8192:
            print(f"    FAIL  COMPACT prompt itself ({est_tokens:,} tok) exceeds 8K window")
            ok = False
        if not ok:
            rc = 1

        # Show the new service block
        if "PUBLISHED REST/SOAP SERVICES" in ctx:
            i = ctx.index("=== PUBLISHED REST/SOAP SERVICES")
            j = ctx.find("===", i + 5)
            j = ctx.find("===", j + 5) if j != -1 else len(ctx)
            print("  --- emitted service block ---")
            for line in ctx[i:j].splitlines()[:8]:
                print(f"    {line}")

    print(f"\nVERIFY rc={rc}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
