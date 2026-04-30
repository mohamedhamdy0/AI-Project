"""Verify that the split-dump extractor produces 19 files and excludes
all known Mendix Marketplace / system / protected modules."""
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, r"D:\Ai Project")
os.chdir(r"D:\Ai Project")

from mendix_analyzer.mpr_extractor import MPRExtractor, MARKETPLACE_MODULES

t0 = time.time()


def cb(msg: str) -> None:
    print(f"  [{time.time() - t0:6.1f}s] {msg}", flush=True)


mpr = r"D:\LCGPA_Branches\EV_Production_v10\LCGPA Service Application.mpr"
res = MPRExtractor().extract(mpr, on_progress=cb)

print()
print("=== RESULT ===")
print(f"  duration:  {res.duration_seconds}s    raw_units: {res.raw_unit_count:,}")
print(f"  dump_dir:  {res.dump_dir}")

print("\n=== Files in dump_dir ===")
for f in sorted(Path(res.dump_dir).iterdir()):
    sz = f.stat().st_size
    print(f"  {sz:>12,} B   {f.name}")

print("\n=== Counts (after filtering) ===")
for k, v in res.counts.items():
    print(f"  {k:<22} {v:>6,}")

mods = sorted(m["name"] for m in res.sections["modules"])
suspects = [m for m in mods if any(s in m.lower() for s in
            ("atlas", "communitycommons", "encryption", "appstore",
             "mxmodelreflection", "saml", "nanoflowcommons", "datawidgets",
             "bootstrapstyle", "documenttemplates", "layoutgrid", "charts"))]
print(f"\n  Total modules: {len(mods)}")
print(f"  Suspect names still present: {suspects or 'NONE - clean'}")
print(f"  Known marketplace list size: {len(MARKETPLACE_MODULES)}")

print("\n  All kept module names:")
for m in mods:
    print(f"    - {m}")
