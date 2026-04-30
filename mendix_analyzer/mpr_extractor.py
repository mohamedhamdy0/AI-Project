"""
Mendix MPR Extractor
Wraps `mx dump-mpr` to extract a Mendix project's full model as JSON,
then transforms it into the 19-section structure required by the AI pipeline.
"""
from __future__ import annotations

import json
import os
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional


# Unit types we request from `mx dump-mpr` on first attempt.
# Nanoflows$Nanoflow is intentionally omitted: not supported on every Mx version.
# WebServices$ConsumedWebService and MicroflowExpressions$ScheduledEventActionInfo
# are rejected by Mx 10.24 ("Invalid unit type(s)") so we don't ask for them up
# front; the retry path below removes the remaining integration types entirely
# if even the trimmed set fails.
DEFAULT_UNIT_TYPES = [
    "DomainModels$DomainModel",
    "Microflows$Microflow",
    "Pages$Page",
    "Workflows$Workflow",
    "Enumerations$Enumeration",
    "Constants$Constant",
    "Security$ProjectSecurity",
    "Security$ModuleSecurity",
    # Integration-related (best-effort; ignored if unsupported on this Mx version)
    "Rest$PublishedRestService",
    "Rest$ConsumedRestService",
    "WebServices$PublishedWebService",
]

# Well-known Mendix Marketplace / App-Store module names. `mx dump-mpr
# --exclude-protected-modules` skips modules that are imported as locked
# (the modern default), but older imports often store these as unprotected.
# We post-filter by name as a safety net so business analysis isn't polluted
# by Atlas widgets, CommunityCommons utility flows, etc.
MARKETPLACE_MODULES: set = {
    # Atlas UI / styling
    "Atlas_Core", "Atlas_UI_Resources", "Atlas_NativeMobile_Resources",
    "Atlas_Web_Content", "AtlasUI_Resources", "BootstrapStyle",
    "LayoutGrid",
    # Common utility modules
    "CommunityCommons", "NanoflowCommons", "Nanoflow_Commons",
    "Encryption", "MxModelReflection", "WorkflowCommons",
    "DataWidgets", "DocumentTemplates",
    # Native mobile
    "NativeMobileResources", "Nanoflow_Commons_Native",
    # Charts / visualisation
    "Charts", "ChartsConfiguration", "ChartsAddOn",
    # Import / export utilities
    "ExcelImporter", "ExcelExporter", "FileDocumentDownloader",
    # Other common marketplace add-ons
    "DeepLink", "EmailTemplate", "PerformanceMonitor",
    "AppCloudServices", "MxAssistAvailable", "MxAssistContentSuggester",
    "ConflictsResolver", "ObjectHandling",
    # Authentication add-ons
    "SAML20", "OIDC", "OpenIDConnect", "LDAPLogin",
}

ProgressCB = Optional[Callable[[str], None]]


# ── mx.exe discovery ─────────────────────────────────────────────────── #

_MX_SEARCH_DIRS = [
    r"C:\Program Files\Mendix",
    r"C:\Program Files (x86)\Mendix",
    os.path.expandvars(r"%LOCALAPPDATA%\Mendix"),
]


def _parse_version_tuple(name: str) -> tuple:
    """Convert a version-like directory name (e.g. '10.24.13.86719') to a
    tuple of ints suitable for numeric ordering. Non-numeric parts sort low."""
    parts: List[int] = []
    for chunk in name.split("."):
        try:
            parts.append(int(chunk))
        except ValueError:
            parts.append(-1)
    return tuple(parts) if parts else (-1,)


# `mx dump-mpr` was introduced in Mendix Studio Pro 10.x — older builds
# (e.g. 9.x) accept only a small set of verbs and will reject "dump-mpr"
# with: "Verb 'dump-mpr' is not recognized." Skip them entirely.
_MIN_MX_MAJOR = 10


def find_mx_exe() -> Optional[Path]:
    """Return the newest mx.exe (>= Mendix 10) found on the system, or None.

    Versions are compared numerically, NOT lexicographically — otherwise
    "9.6.13" sorts above "10.24.13" because '9' > '1' as a character.
    """
    # (version_tuple, path) so we can sort numerically
    candidates: List[tuple] = []
    # PATH (no version info available — assume current/recent)
    for p in os.environ.get("PATH", "").split(os.pathsep):
        cand = Path(p) / "mx.exe"
        if cand.is_file():
            candidates.append(((9999,), cand))
    # Standard install dirs (each version has modeler\mx.exe)
    for root in _MX_SEARCH_DIRS:
        rp = Path(root)
        if not rp.exists():
            continue
        for ver_dir in rp.iterdir():
            cand = ver_dir / "modeler" / "mx.exe"
            if cand.is_file():
                ver = _parse_version_tuple(ver_dir.name)
                candidates.append((ver, cand))
    if not candidates:
        return None
    # Filter to Mendix 10+ where dump-mpr exists; if none qualify, fall back
    # to the highest available (so error reporting still works).
    eligible = [c for c in candidates if c[0][0] >= _MIN_MX_MAJOR]
    pool = eligible or candidates
    pool.sort(key=lambda c: c[0], reverse=True)
    return pool[0][1]


# ── Public data container ────────────────────────────────────────────── #

@dataclass
class ExtractedData:
    """Result of an MPR extraction."""
    project_name: str = ""
    mpr_path: str = ""
    dump_dir: str = ""           # directory containing per-section JSON files
    dump_path: str = ""           # kept for backwards-compat: points at dump_dir
    section_files: Dict[str, str] = field(default_factory=dict)  # section -> file
    sections: Dict[str, object] = field(default_factory=dict)  # 19-section structure
    duration_seconds: float = 0.0
    raw_unit_count: int = 0

    # Convenience counts
    @property
    def counts(self) -> Dict[str, int]:
        s = self.sections
        return {
            "modules":            len(s.get("modules", []) or []),
            "domain_models":      len(s.get("domain_models", []) or []),
            "entities":           len(s.get("entities", []) or []),
            "attributes":         len(s.get("attributes", []) or []),
            "associations":       len(s.get("associations", []) or []),
            "microflows":         len(s.get("microflows", []) or []),
            "microflow_steps":    len(s.get("microflow_steps", []) or []),
            "nanoflows":          len(s.get("nanoflows", []) or []),
            "pages":              len(s.get("pages", []) or []),
            "page_elements":      len(s.get("page_elements", []) or []),
            "workflows":          len(s.get("workflows", []) or []),
            "workflow_states":    len(s.get("workflow_states", []) or []),
            "workflow_transitions": len(s.get("workflow_transitions", []) or []),
            "constants":          len(s.get("constants", []) or []),
            "enumerations":       len(s.get("enumerations", []) or []),
            "integrations":       len(s.get("integrations", []) or []),
            "published_services": len(s.get("published_services", []) or []),
            "consumed_services":  len(s.get("consumed_services", []) or []),
        }

    def to_dict(self) -> Dict[str, object]:
        return dict(self.sections)

    def save_json(self, path: str) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.sections, f, ensure_ascii=False, indent=2)

    def save_split_json(self, dump_dir: str) -> Dict[str, str]:
        """Write each of the 19 sections to its own JSON file under `dump_dir`.

        Returns a {section_name: file_path} map and also writes a `_manifest.json`
        summarising counts. Used by the GUI so users can inspect microflows.json,
        pages.json, etc. independently of the giant raw dump.
        """
        d = Path(dump_dir)
        d.mkdir(parents=True, exist_ok=True)
        files: Dict[str, str] = {}
        for key, value in self.sections.items():
            path = d / f"{key}.json"
            with open(path, "w", encoding="utf-8") as f:
                json.dump(value, f, ensure_ascii=False, indent=2)
            files[key] = str(path)
        manifest = {
            "project_name": self.project_name,
            "mpr_path": self.mpr_path,
            "duration_seconds": self.duration_seconds,
            "raw_unit_count": self.raw_unit_count,
            "counts": self.counts,
            "sections": list(self.sections.keys()),
            "files": files,
        }
        with open(d / "_manifest.json", "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)
        self.section_files = files
        self.dump_dir = str(d)
        self.dump_path = str(d)
        return files

    def to_context_string(self, max_modules: int = 20, max_per_module: int = 6,
                          compact: bool = False) -> str:
        """Compact, AI-friendly digest of the 19 sections.

        When `compact=True`, the digest is shrunk by ~50% so the full prompt
        (system + this digest + filesystem scan) can fit inside an 8K-token
        window. It tightens `max_modules`/`max_per_module`, drops the per-role
        security listing, and omits the integrations detail block.
        """
        if compact:
            max_modules = min(max_modules, 15)
            max_per_module = min(max_per_module, 3)
        s = self.sections
        c = self.counts
        lines: List[str] = [
            f"PROJECT NAME: {self.project_name}",
            f"MPR FILE: {self.mpr_path}",
            f"EXTRACTION TIME: {self.duration_seconds}s | RAW UNITS: {self.raw_unit_count:,}",
            "",
            "=== 19-SECTION COUNTS ===",
        ]
        for k, v in c.items():
            lines.append(f"  {k:<22} {v:>6,}")

        # Security overview
        sec = s.get("security", {}) or {}
        lines += ["", "=== SECURITY ===",
                  f"  Security level: {sec.get('security_level', '')}",
                  f"  Check security: {sec.get('check_security', '')}",
                  f"  Guest access: {sec.get('enable_guest_access', '')} (role={sec.get('guest_user_role_name', '')})",
                  f"  User roles: {len(sec.get('user_roles', []))} | "
                  f"Module roles: {len(sec.get('module_roles', []))} | "
                  f"Access rules: {len(sec.get('access_rules', []))}"]
        if not compact:
            for r in (sec.get("user_roles") or [])[:8]:
                lines.append(f"    • {r.get('name','')} ({len(r.get('module_roles',[]))} module roles)")

        # Modules
        mods = s.get("modules", []) or []
        lines += ["", f"=== MODULES (top {min(max_modules, len(mods))} of {len(mods)}) ==="]
        for m in mods[:max_modules]:
            lines.append(
                f"  {m['name']:<32} ent={m.get('entity_count',0):<3} "
                f"mf={m.get('microflow_count',0):<3} pg={m.get('page_count',0):<3} "
                f"wf={m.get('workflow_count',0):<2} en={m.get('enum_count',0):<2} "
                f"co={m.get('constant_count',0):<2} roles={len(m.get('module_roles',[]))}")

        # Per-module entity / microflow detail
        ents_by_mod: Dict[str, List[dict]] = {}
        for e in s.get("entities", []) or []:
            ents_by_mod.setdefault(e["module"], []).append(e)
        mfs_by_mod: Dict[str, List[dict]] = {}
        for mf in s.get("microflows", []) or []:
            mfs_by_mod.setdefault(mf["module"], []).append(mf)
        wfs_by_mod: Dict[str, List[dict]] = {}
        for wf in s.get("workflows", []) or []:
            wfs_by_mod.setdefault(wf["module"], []).append(wf)

        lines += ["", "=== BUSINESS MODULES — DETAIL ==="]
        for m in mods[:max_modules]:
            mn = m["name"]
            lines.append(f"\n## {mn}")
            es = ents_by_mod.get(mn, [])
            if es:
                names = ", ".join(e["name"] for e in es[:max_per_module])
                more = f" ...(+{len(es)-max_per_module} more)" if len(es) > max_per_module else ""
                lines.append(f"  Entities: {names}{more}")
            mfs = mfs_by_mod.get(mn, [])
            if mfs:
                names = ", ".join(mf["name"] for mf in mfs[:max_per_module])
                more = f" ...(+{len(mfs)-max_per_module} more)" if len(mfs) > max_per_module else ""
                lines.append(f"  Microflows: {names}{more}")
            wfs = wfs_by_mod.get(mn, [])
            if wfs:
                names = ", ".join(f"{wf['name']}({wf.get('state_count',0)} states)" for wf in wfs[:4])
                lines.append(f"  Workflows: {names}")

        # Integrations
        ints = s.get("integrations", []) or []
        if ints and not compact:
            lines += ["", f"=== INTEGRATIONS ({len(ints)}) ==="]
            for it in ints[:15]:
                lines.append(f"  • [{it.get('direction','')}/{it.get('kind','')}] "
                             f"{it.get('qualified_name','')} {it.get('path') or it.get('location','')}")

        return "\n".join(lines)


def _empty_sections() -> Dict[str, object]:
    return {
        "modules": [],
        "domain_models": [],
        "entities": [],
        "attributes": [],
        "associations": [],
        "microflows": [],
        "microflow_steps": [],
        "nanoflows": [],
        "pages": [],
        "page_elements": [],
        "workflows": [],
        "workflow_states": [],
        "workflow_transitions": [],
        "security": {"user_roles": [], "module_roles": [], "access_rules": []},
        "constants": [],
        "enumerations": [],
        "integrations": [],
        "published_services": [],
        "consumed_services": [],
    }



# ── Extractor ────────────────────────────────────────────────────────── #

class MPRExtractor:
    """Runs `mx dump-mpr` and transforms the JSON to the 19-section schema."""

    def __init__(self, mx_exe: Optional[Path] = None):
        self.mx_exe = mx_exe or find_mx_exe()

    def is_available(self) -> bool:
        return self.mx_exe is not None and self.mx_exe.is_file()

    # ------- Main entry point ------- #

    def extract(self, mpr_path: str, on_progress: ProgressCB = None,
                dump_dir: Optional[str] = None,
                keep_raw_dump: bool = False) -> ExtractedData:
        """Run `mx dump-mpr` (excluding system + protected/marketplace modules),
        then split the result into per-section JSON files.

        Args:
            mpr_path:       absolute path to the .mpr file.
            on_progress:    optional progress callback.
            dump_dir:       directory to write the per-section JSON files into.
                            Defaults to <cwd>/dumps/<project_stem>/.
            keep_raw_dump:  if True, keeps the giant intermediate `_raw_dump.json`
                            for debugging. Otherwise it is deleted after splitting.
        """
        if not self.is_available():
            raise RuntimeError(
                "mx.exe not found. Install Mendix Studio Pro or set its install dir on PATH.")
        mpr = Path(mpr_path)
        if not mpr.is_file():
            raise FileNotFoundError(f"MPR file not found: {mpr_path}")

        t0 = time.time()
        result = ExtractedData(
            project_name=mpr.stem,
            mpr_path=str(mpr),
            sections=_empty_sections(),
        )

        # Per-project output folder for split files
        out_dir = Path(dump_dir) if dump_dir else (Path.cwd() / "dumps" / mpr.stem)
        out_dir.mkdir(parents=True, exist_ok=True)
        raw_dump = out_dir / "_raw_dump.json"

        self._notify(on_progress,
                     f"Running mx dump-mpr on {mpr.name} (excluding system & "
                     f"protected/marketplace modules) ...")
        ok = self._run_dump(mpr, raw_dump, DEFAULT_UNIT_TYPES, on_progress,
                            exclude_protected=True)
        if not ok:
            # First fallback: same flags but drop --exclude-protected-modules
            # (older mx may not have it).
            self._notify(on_progress,
                         "Retrying without --exclude-protected-modules ...")
            ok = self._run_dump(mpr, raw_dump, DEFAULT_UNIT_TYPES, on_progress,
                                exclude_protected=False)
        if not ok:
            self._notify(on_progress,
                         "Retrying with reduced unit types (integration types not supported)...")
            reduced = [t for t in DEFAULT_UNIT_TYPES
                       if not (t.startswith("Rest$") or t.startswith("WebServices$")
                               or t.startswith("MicroflowExpressions$"))]
            ok = self._run_dump(mpr, raw_dump, reduced, on_progress,
                                exclude_protected=False)
            if not ok:
                raise RuntimeError("mx dump-mpr failed; see logs for details.")

        size_mb = raw_dump.stat().st_size / (1024 * 1024)
        self._notify(on_progress, f"Loading JSON dump ({size_mb:.1f} MB)...")
        with open(raw_dump, "r", encoding="utf-8-sig") as f:
            payload = json.load(f)
        units: List[dict] = payload.get("units", []) if isinstance(payload, dict) else []
        result.raw_unit_count = len(units)

        self._notify(on_progress, f"Transforming {len(units):,} units into 19 sections...")
        self._transform(units, result.sections, on_progress)

        # Write per-section JSON files (microflows.json, pages.json, ...)
        self._notify(on_progress,
                     f"Writing per-section JSON files to {out_dir} ...")
        files = result.save_split_json(str(out_dir))
        self._notify(on_progress,
                     f"Wrote {len(files)} section files + _manifest.json.")

        if not keep_raw_dump:
            try:
                raw_dump.unlink()
            except OSError:
                pass

        result.duration_seconds = round(time.time() - t0, 2)
        self._notify(on_progress,
                     f"MPR extraction complete in {result.duration_seconds}s "
                     f"(units={result.raw_unit_count}, "
                     f"entities={result.counts['entities']}, "
                     f"microflows={result.counts['microflows']}, "
                     f"pages={result.counts['pages']}).")
        return result

    # ------- mx dump-mpr invocation ------- #

    def _run_dump(self, mpr: Path, output: Path, unit_types: List[str],
                  on_progress: ProgressCB,
                  exclude_protected: bool = True) -> bool:
        cmd = [
            str(self.mx_exe), "dump-mpr", str(mpr),
            "--output-file", str(output),
            "--exclude-system-module",
            "--unit-type", ",".join(unit_types),
        ]
        if exclude_protected:
            # Marketplace / App Store modules are imported as "protected".
            cmd.append("--exclude-protected-modules")
        if output.exists():
            output.unlink()
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        except subprocess.TimeoutExpired:
            self._notify(on_progress, "ERROR: mx dump-mpr timed out (>10 min).")
            return False

        if proc.returncode != 0:
            err = (proc.stderr or proc.stdout or "").strip().splitlines()
            tail = " | ".join(err[-3:]) if err else f"rc={proc.returncode}"
            self._notify(on_progress, f"ERROR: mx dump-mpr rc={proc.returncode}: {tail}")
            return False
        if not output.exists() or output.stat().st_size == 0:
            self._notify(on_progress, "ERROR: mx dump-mpr produced no output file.")
            return False
        return True

    @staticmethod
    def _notify(cb: ProgressCB, msg: str) -> None:
        if cb:
            try:
                cb(msg)
            except Exception:
                pass

    # ------- Transformation: units → 19-section schema ------- #

    @staticmethod
    def _unit_module_name(u: dict) -> str:
        """Best-effort module name for a unit. Returns '' for project-scoped
        units like Security$ProjectSecurity that aren't tied to a module."""
        qn = u.get("$QualifiedName") or ""
        if qn and "." in qn:
            return qn.split(".", 1)[0]
        t = u.get("$Type") or ""
        # DomainModel and ModuleSecurity store the bare module name (no dot)
        # in $QualifiedName, or none at all — derive from a child element.
        if t == "DomainModels$DomainModel":
            if qn:
                return qn
            for e in (u.get("entities") or []):
                eq = e.get("$QualifiedName") or ""
                if "." in eq:
                    return eq.split(".", 1)[0]
        elif t == "Security$ModuleSecurity":
            if qn:
                return qn
            for r in (u.get("moduleRoles") or []):
                rq = r.get("$QualifiedName") or ""
                if "." in rq:
                    return rq.split(".", 1)[0]
        return ""

    def _transform(self, units: List[dict], sections: Dict[str, object],
                   on_progress: ProgressCB) -> None:
        modules: Dict[str, dict] = {}    # name -> module record
        entity_uuid_to_qn: Dict[str, str] = {}

        # Drop units belonging to known marketplace modules (--exclude-protected-modules
        # only catches *protected* imports; older unprotected imports slip through).
        before = len(units)
        units = [u for u in units
                 if self._unit_module_name(u) not in MARKETPLACE_MODULES]
        skipped = before - len(units)
        if skipped:
            self._notify(on_progress,
                         f"Filtered out {skipped} unit(s) from known marketplace modules.")

        # Pass 1: collect entities + uuid map (also seeds modules)
        for u in units:
            t = u.get("$Type")
            if t == "DomainModels$DomainModel":
                self._handle_domain_model(u, sections, modules, entity_uuid_to_qn)

        # Pass 2: handle other unit types using the uuid map
        for u in units:
            t = u.get("$Type")
            if t == "Microflows$Microflow":
                self._handle_microflow(u, sections, modules)
            elif t == "Pages$Page":
                self._handle_page(u, sections, modules)
            elif t == "Workflows$Workflow":
                self._handle_workflow(u, sections, modules)
            elif t == "Enumerations$Enumeration":
                self._handle_enumeration(u, sections, modules)
            elif t == "Constants$Constant":
                self._handle_constant(u, sections, modules)
            elif t == "Security$ProjectSecurity":
                self._handle_project_security(u, sections)
            elif t == "Security$ModuleSecurity":
                self._handle_module_security(u, sections, modules)
            elif t in ("Rest$PublishedRestService", "WebServices$PublishedWebService"):
                self._handle_published_service(u, sections, modules)
            elif t in ("Rest$ConsumedRestService", "WebServices$ConsumedWebService"):
                self._handle_consumed_service(u, sections, modules)

        # Resolve association entity names from uuid map
        for assoc in sections["associations"]:  # type: ignore[index]
            assoc["parent_entity"] = entity_uuid_to_qn.get(assoc.get("_parent_uuid", ""), assoc.get("parent_entity", ""))
            assoc["child_entity"] = entity_uuid_to_qn.get(assoc.get("_child_uuid", ""), assoc.get("child_entity", ""))
            assoc.pop("_parent_uuid", None)
            assoc.pop("_child_uuid", None)

        # Finalize modules list
        sections["modules"] = sorted(modules.values(), key=lambda m: m["name"])

    # --- helpers --- #

    @staticmethod
    def _module_of(qn: Optional[str]) -> str:
        if not qn or "." not in qn:
            return qn or ""
        return qn.split(".", 1)[0]

    @staticmethod
    def _ensure_module(modules: Dict[str, dict], name: str) -> dict:
        if not name:
            return {}
        m = modules.get(name)
        if m is None:
            m = {
                "name": name, "entity_count": 0, "microflow_count": 0,
                "page_count": 0, "workflow_count": 0, "enum_count": 0,
                "constant_count": 0, "module_roles": [],
            }
            modules[name] = m
        return m

    def _handle_domain_model(self, u: dict, sections: Dict[str, object],
                             modules: Dict[str, dict],
                             entity_uuid_to_qn: Dict[str, str]) -> None:
        entities = u.get("entities") or []
        # Module name: derive from any entity's $QualifiedName
        mod_name = ""
        for e in entities:
            mod_name = self._module_of(e.get("$QualifiedName"))
            if mod_name:
                break
        m = self._ensure_module(modules, mod_name) if mod_name else {}

        dm_record = {
            "module": mod_name,
            "entity_count": len(entities),
            "association_count": len(u.get("associations") or []),
            "cross_association_count": len(u.get("crossAssociations") or []),
            "documentation": (u.get("documentation") or "").strip()[:500],
        }
        sections["domain_models"].append(dm_record)  # type: ignore[index]

        for e in entities:
            qn = e.get("$QualifiedName") or ""
            entity_uuid_to_qn[e.get("$ID", "")] = qn
            gen = e.get("generalization") or {}
            ent_record = {
                "qualified_name": qn,
                "module": mod_name,
                "name": e.get("name", ""),
                "documentation": (e.get("documentation") or "").strip()[:300],
                "generalization": gen.get("generalization") if gen.get("$Type") == "DomainModels$Generalization" else None,
                "is_persistent": gen.get("$Type") != "DomainModels$NoGeneralization" or any(
                    [gen.get("hasChangedDate"), gen.get("hasCreatedDate"), gen.get("hasOwner")]),
                "attribute_count": len(e.get("attributes") or []),
                "validation_rule_count": len(e.get("validationRules") or []),
                "event_handler_count": len(e.get("eventHandlers") or []),
                "index_count": len(e.get("indexes") or []),
                "access_rule_count": len(e.get("accessRules") or []),
            }
            sections["entities"].append(ent_record)  # type: ignore[index]
            if m:
                m["entity_count"] = m.get("entity_count", 0) + 1

            # Attributes
            for a in (e.get("attributes") or []):
                a_type = (a.get("type") or {}).get("$Type", "").replace("DomainModels$", "").replace("AttributeType", "")
                a_value = a.get("value") or {}
                sections["attributes"].append({  # type: ignore[index]
                    "qualified_name": a.get("$QualifiedName", ""),
                    "entity": qn,
                    "module": mod_name,
                    "name": a.get("name", ""),
                    "type": a_type or "Unknown",
                    "value_kind": (a_value.get("$Type") or "").replace("DomainModels$", ""),
                    "default_value": a_value.get("defaultValue", ""),
                })

            # Per-entity access rules (security.access_rules)
            for ar in (e.get("accessRules") or []):
                allowed_roles = ar.get("moduleRoles") or []
                if isinstance(allowed_roles, list) and allowed_roles and isinstance(allowed_roles[0], dict):
                    allowed_roles = [r.get("$QualifiedName") or r.get("name") for r in allowed_roles]
                sections["security"]["access_rules"].append({  # type: ignore[index]
                    "entity": qn,
                    "module": mod_name,
                    "allow_create": bool(ar.get("allowCreate")),
                    "allow_delete": bool(ar.get("allowDelete")),
                    "default_member_access": ar.get("defaultMemberAccessRights") or "",
                    "x_path_constraint": (ar.get("xPathConstraint") or "")[:200],
                    "module_roles": allowed_roles,
                })

        # Associations (in-module)
        for assoc in (u.get("associations") or []):
            sections["associations"].append({  # type: ignore[index]
                "qualified_name": assoc.get("$QualifiedName", ""),
                "module": mod_name,
                "name": assoc.get("name", ""),
                "type": assoc.get("type", ""),
                "owner": assoc.get("owner", ""),
                "_parent_uuid": assoc.get("parent", ""),
                "_child_uuid": assoc.get("child", ""),
                "parent_entity": "",
                "child_entity": "",
                "delete_behavior_parent": (assoc.get("deleteBehavior") or {}).get("parentDeleteBehavior", ""),
                "delete_behavior_child": (assoc.get("deleteBehavior") or {}).get("childDeleteBehavior", ""),
            })
        # Cross-module associations
        for assoc in (u.get("crossAssociations") or []):
            sections["associations"].append({  # type: ignore[index]
                "qualified_name": assoc.get("$QualifiedName", ""),
                "module": mod_name,
                "name": assoc.get("name", ""),
                "type": assoc.get("type", ""),
                "owner": assoc.get("owner", ""),
                "_parent_uuid": assoc.get("parent", ""),
                "_child_uuid": assoc.get("child", ""),
                "parent_entity": "",
                "child_entity": "",
                "delete_behavior_parent": (assoc.get("deleteBehavior") or {}).get("parentDeleteBehavior", ""),
                "delete_behavior_child": (assoc.get("deleteBehavior") or {}).get("childDeleteBehavior", ""),
                "cross_module": True,
            })


    def _handle_microflow(self, u: dict, sections: Dict[str, object],
                          modules: Dict[str, dict]) -> None:
        qn = u.get("$QualifiedName") or ""
        mod = self._module_of(qn)
        m = self._ensure_module(modules, mod)
        if m:
            m["microflow_count"] = m.get("microflow_count", 0) + 1
        objects = (u.get("objectCollection") or {}).get("objects", []) or []
        flows = u.get("flows") or []
        # Activity-type counts and step extraction
        activity_counts: Dict[str, int] = {}
        action_counts: Dict[str, int] = {}
        microflow_calls: List[str] = []
        steps_for_this: List[dict] = []
        for o in objects:
            ot = (o.get("$Type") or "").replace("Microflows$", "")
            activity_counts[ot] = activity_counts.get(ot, 0) + 1
            step = {"microflow": qn, "module": mod, "step_type": ot, "caption": o.get("caption", "")}
            if ot == "ActionActivity":
                act = o.get("action") or {}
                at = (act.get("$Type") or "").replace("Microflows$", "")
                action_counts[at] = action_counts.get(at, 0) + 1
                step["action"] = at
                if at == "MicroflowCallAction":
                    call = (act.get("microflowCall") or {}).get("microflow") or act.get("microflow") or ""
                    if call:
                        microflow_calls.append(call)
                        step["calls_microflow"] = call
                elif at in ("CreateObjectAction", "ChangeObjectAction", "DeleteAction",
                            "RetrieveAction", "CommitAction"):
                    step["entity"] = act.get("entity") or act.get("retrieveSource", {}).get("entity", "") or ""
                elif at == "ShowPageAction":
                    step["page"] = (act.get("pageSettings") or {}).get("page", "") or act.get("page", "")
                elif at == "JavaActionCallAction":
                    step["java_action"] = act.get("javaAction", "")
                elif at == "ChangeVariableAction":
                    step["variable"] = act.get("variableName", "")
            elif ot == "ExclusiveSplit":
                cond = (o.get("splitCondition") or {})
                step["condition"] = (cond.get("expression") or cond.get("attribute") or "")[:200]
            steps_for_this.append(step)
        sections["microflow_steps"].extend(steps_for_this)  # type: ignore[index]

        sections["microflows"].append({  # type: ignore[index]
            "qualified_name": qn,
            "module": mod,
            "name": u.get("name", ""),
            "documentation": (u.get("documentation") or "").strip()[:300],
            "apply_entity_access": bool(u.get("applyEntityAccess")),
            "allowed_module_roles": [r for r in (u.get("allowedModuleRoles") or [])
                                     if isinstance(r, str)],
            "object_count": len(objects),
            "sequence_flow_count": len(flows),
            "activity_counts": activity_counts,
            "action_counts": action_counts,
            "called_microflows": list(dict.fromkeys(microflow_calls)),
            "return_type": (u.get("microflowReturnType") or {}).get("$Type", "").replace("DataTypes$", ""),
        })

    def _handle_page(self, u: dict, sections: Dict[str, object],
                     modules: Dict[str, dict]) -> None:
        qn = u.get("$QualifiedName") or ""
        mod = self._module_of(qn)
        m = self._ensure_module(modules, mod)
        if m:
            m["page_count"] = m.get("page_count", 0) + 1
        layout = (u.get("layoutCall") or {}).get("layout", "") or ""
        # Walk widget tree counting types and extracting microflow/page links
        widget_counts: Dict[str, int] = {}
        elements: List[dict] = []
        called_microflows: List[str] = []
        called_pages: List[str] = []

        def walk(o):
            if isinstance(o, dict):
                t = o.get("$Type", "")
                if t.startswith("Pages$"):
                    short = t.replace("Pages$", "")
                    widget_counts[short] = widget_counts.get(short, 0) + 1
                    if short in ("ActionButton", "MicroflowClientAction",
                                 "OpenPageClientAction", "DataView", "ListView",
                                 "DataGrid", "DataGrid2", "TextBox", "DropDown"):
                        elem = {"page": qn, "module": mod, "type": short,
                                "caption": (o.get("caption") or {}).get("text", "")
                                          if isinstance(o.get("caption"), dict) else ""}
                        # Action button -> click action -> microflow / page
                        action = o.get("action") or o.get("clientAction") or {}
                        at = action.get("$Type", "")
                        if at == "Pages$MicroflowClientAction":
                            mf = (action.get("microflowSettings") or {}).get("microflow", "")
                            if mf:
                                called_microflows.append(mf)
                                elem["calls_microflow"] = mf
                        elif at in ("Pages$OpenPageClientAction", "Pages$ShowPageClientAction"):
                            pg = (action.get("pageSettings") or {}).get("page", "") or action.get("page", "")
                            if pg:
                                called_pages.append(pg)
                                elem["opens_page"] = pg
                        if "dataSource" in o:
                            ds = o["dataSource"] or {}
                            elem["data_source"] = (ds.get("$Type") or "").replace("Pages$", "")
                            if "entityPath" in ds:
                                elem["entity_path"] = ds["entityPath"]
                        elements.append(elem)
                for v in o.values():
                    walk(v)
            elif isinstance(o, list):
                for v in o:
                    walk(v)

        walk(u.get("layoutCall"))
        sections["page_elements"].extend(elements)  # type: ignore[index]
        sections["pages"].append({  # type: ignore[index]
            "qualified_name": qn,
            "module": mod,
            "name": u.get("name", ""),
            "layout": layout,
            "title": self._extract_text(u.get("title")),
            "allowed_roles": [r for r in (u.get("allowedRoles") or []) if isinstance(r, str)],
            "widget_counts": widget_counts,
            "called_microflows": list(dict.fromkeys(called_microflows)),
            "called_pages": list(dict.fromkeys(called_pages)),
        })

    @staticmethod
    def _extract_text(node) -> str:
        if not isinstance(node, dict):
            return ""
        for tr in (node.get("translations") or []):
            if tr.get("languageCode", "").startswith("en"):
                return (tr.get("text") or "")[:200]
        trs = node.get("translations") or []
        if trs:
            return (trs[0].get("text") or "")[:200]
        return ""


    def _handle_workflow(self, u: dict, sections: Dict[str, object],
                         modules: Dict[str, dict]) -> None:
        qn = u.get("$QualifiedName") or ""
        mod = self._module_of(qn)
        m = self._ensure_module(modules, mod)
        if m:
            m["workflow_count"] = m.get("workflow_count", 0) + 1

        # Walk flow.activities — each activity becomes a "state"; outcomes become transitions
        states: List[dict] = []
        transitions: List[dict] = []

        def walk_flow(flow_node, parent_state: Optional[str]):
            if not isinstance(flow_node, dict):
                return
            for act in (flow_node.get("activities") or []):
                at = (act.get("$Type") or "").replace("Workflows$", "")
                state_id = act.get("$ID", "")
                state_caption = ""
                if isinstance(act.get("title"), dict):
                    state_caption = self._extract_text(act["title"])
                state_rec = {
                    "workflow": qn, "module": mod,
                    "type": at, "id": state_id, "caption": state_caption,
                }
                # Pull useful refs
                if at == "CallMicroflowTask":
                    state_rec["microflow"] = act.get("microflow", "")
                elif at == "UserTask":
                    state_rec["page"] = act.get("page", "")
                    state_rec["allowed_module_roles"] = [
                        r for r in (act.get("allowedModuleRoles") or []) if isinstance(r, str)
                    ]
                elif at == "JumpActivity":
                    state_rec["target"] = act.get("targetActivity", "")
                states.append(state_rec)
                # outcomes -> transitions
                for oc in (act.get("outcomes") or []):
                    oc_type = (oc.get("$Type") or "").replace("Workflows$", "")
                    transitions.append({
                        "workflow": qn, "module": mod,
                        "from_state": state_id,
                        "from_type": at,
                        "outcome_type": oc_type,
                        "condition": (oc.get("condition") or oc.get("expression") or "")[:200]
                                     if isinstance(oc.get("condition"), str) else "",
                    })
                    # Recurse into nested flows
                    walk_flow(oc.get("flow"), state_id)

        walk_flow(u.get("flow"), None)
        sections["workflow_states"].extend(states)  # type: ignore[index]
        sections["workflow_transitions"].extend(transitions)  # type: ignore[index]
        param = u.get("parameter") or {}
        sections["workflows"].append({  # type: ignore[index]
            "qualified_name": qn,
            "module": mod,
            "name": u.get("name", ""),
            "title": self._extract_text(u.get("title")) or u.get("title", "") if isinstance(u.get("title"), str) else self._extract_text(u.get("title")),
            "context_entity": param.get("entity", ""),
            "documentation": (u.get("documentation") or "").strip()[:300],
            "state_count": len(states),
            "transition_count": len(transitions),
        })

    def _handle_enumeration(self, u: dict, sections: Dict[str, object],
                            modules: Dict[str, dict]) -> None:
        qn = u.get("$QualifiedName") or ""
        mod = self._module_of(qn)
        m = self._ensure_module(modules, mod)
        if m:
            m["enum_count"] = m.get("enum_count", 0) + 1
        values = []
        for v in (u.get("values") or []):
            values.append({
                "name": v.get("name", ""),
                "caption": self._extract_text(v.get("caption")),
            })
        sections["enumerations"].append({  # type: ignore[index]
            "qualified_name": qn,
            "module": mod,
            "name": u.get("name", ""),
            "values": values,
        })

    def _handle_constant(self, u: dict, sections: Dict[str, object],
                         modules: Dict[str, dict]) -> None:
        qn = u.get("$QualifiedName") or ""
        mod = self._module_of(qn)
        m = self._ensure_module(modules, mod)
        if m:
            m["constant_count"] = m.get("constant_count", 0) + 1
        sections["constants"].append({  # type: ignore[index]
            "qualified_name": qn,
            "module": mod,
            "name": u.get("name", ""),
            "type": (u.get("type") or {}).get("$Type", "").replace("DataTypes$", ""),
            "default_value": u.get("defaultValue", ""),
            "exposed_to_client": bool(u.get("exposedToClient")),
        })

    def _handle_project_security(self, u: dict, sections: Dict[str, object]) -> None:
        for r in (u.get("userRoles") or []):
            sections["security"]["user_roles"].append({  # type: ignore[index]
                "name": r.get("name", ""),
                "description": (r.get("description") or "").strip()[:200],
                "module_roles": list(r.get("moduleRoles") or []),
            })
        sections["security"]["security_level"] = u.get("securityLevel", "")  # type: ignore[index]
        sections["security"]["check_security"] = bool(u.get("checkSecurity"))  # type: ignore[index]
        sections["security"]["enable_guest_access"] = bool(u.get("enableGuestAccess"))  # type: ignore[index]
        sections["security"]["guest_user_role_name"] = u.get("guestUserRoleName", "")  # type: ignore[index]

    def _handle_module_security(self, u: dict, sections: Dict[str, object],
                                modules: Dict[str, dict]) -> None:
        for r in (u.get("moduleRoles") or []):
            qn = r.get("$QualifiedName") or ""
            mod = self._module_of(qn)
            m = self._ensure_module(modules, mod)
            entry = {
                "qualified_name": qn,
                "module": mod,
                "name": r.get("name", ""),
                "description": (r.get("description") or "").strip()[:200],
            }
            sections["security"]["module_roles"].append(entry)  # type: ignore[index]
            if m:
                m.setdefault("module_roles", []).append(r.get("name", ""))

    def _handle_published_service(self, u: dict, sections: Dict[str, object],
                                  modules: Dict[str, dict]) -> None:
        qn = u.get("$QualifiedName") or ""
        mod = self._module_of(qn)
        kind = "REST" if u.get("$Type", "").startswith("Rest$") else "SOAP"
        rec = {
            "qualified_name": qn, "module": mod, "kind": kind,
            "name": u.get("name", ""),
            "version": u.get("version", ""),
            "path": u.get("path") or u.get("location", ""),
        }
        sections["published_services"].append(rec)  # type: ignore[index]
        sections["integrations"].append({**rec, "direction": "published"})  # type: ignore[index]

    def _handle_consumed_service(self, u: dict, sections: Dict[str, object],
                                 modules: Dict[str, dict]) -> None:
        qn = u.get("$QualifiedName") or ""
        mod = self._module_of(qn)
        kind = "REST" if u.get("$Type", "").startswith("Rest$") else "SOAP"
        rec = {
            "qualified_name": qn, "module": mod, "kind": kind,
            "name": u.get("name", ""),
            "location": u.get("location", "") or u.get("baseUrl", ""),
        }
        sections["consumed_services"].append(rec)  # type: ignore[index]
        sections["integrations"].append({**rec, "direction": "consumed"})  # type: ignore[index]
