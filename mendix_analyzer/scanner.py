"""
Mendix Project Scanner
Extracts metadata from a Mendix 10 project directory and (when an .mpr file
is supplied) also runs `mx dump-mpr` via MPRExtractor to obtain the full
19-section model digest.
"""
import os
import re
from pathlib import Path
from dataclasses import dataclass, field
from typing import Callable, List, Optional, Dict, Tuple

from .mpr_extractor import MPRExtractor, ExtractedData

ProgressCB = Optional[Callable[[str], None]]


@dataclass
class EntityInfo:
    name: str
    attributes: List[str] = field(default_factory=list)
    associations: List[str] = field(default_factory=list)  # association names

    @property
    def attribute_count(self) -> int:
        return len(self.attributes)


@dataclass
class ModuleInfo:
    name: str
    entities: List[str] = field(default_factory=list)
    entity_details: List[EntityInfo] = field(default_factory=list)
    enums: List[str] = field(default_factory=list)
    enum_values: Dict[str, List[str]] = field(default_factory=dict)
    java_actions: List[str] = field(default_factory=list)
    microflow_names: List[str] = field(default_factory=list)
    constants: List[str] = field(default_factory=list)
    has_workflows: bool = False
    has_microflows: bool = False

    @property
    def is_business_module(self) -> bool:
        PLATFORM = {
            "system", "administration", "communitycommons", "nanoflowcommons",
            "atlas_core", "atlas_web_content", "datawidgets", "mxmodelreflection",
            "oql", "workflowadministration", "workflowcommons", "deeplink", "jwt",
            "encryption", "ldap", "emailtemplate", "emailtemplateexportimport",
            "documentgeneration", "fillablepdf", "advanced_excel", "excelimporter",
            "exceltemplatereader", "excelexportertemplatemanager", "simpleexcelexporter",
            "xlsreport", "csv", "barcode", "datamigration", "dataplatform",
            "integrationhub", "logs", "mimetypechecker", "getipaddress", "enumtolist",
            "customsettingmanager", "feedbackmodule", "webactions", "mobileapis",
        }
        return self.name.lower() not in PLATFORM


@dataclass
class ProjectScan:
    project_name: str
    project_path: str
    modules: List[ModuleInfo] = field(default_factory=list)
    libraries: List[str] = field(default_factory=list)
    widgets: List[str] = field(default_factory=list)
    resources: List[str] = field(default_factory=list)
    has_git: bool = False
    has_native: bool = False
    has_rtl: bool = False
    mendix_version: str = "Unknown"
    mpr_path: str = ""
    mpr_data: Optional[ExtractedData] = None
    mpr_error: str = ""

    @property
    def module_count(self) -> int:
        return len(self.modules)

    @property
    def business_modules(self) -> List[ModuleInfo]:
        return [m for m in self.modules if m.is_business_module]

    @property
    def entity_count(self) -> int:
        return sum(len(m.entities) for m in self.modules)

    @property
    def enum_count(self) -> int:
        return sum(len(m.enums) for m in self.modules)

    @property
    def integration_libraries(self) -> List[str]:
        keywords = ["ldap", "jwt", "oauth", "spring", "nimbus", "jakarta.mail",
                    "commons-email", "connector", "nafath", "ncnp"]
        return [l for l in self.libraries if any(k in l.lower() for k in keywords)]


class MendixScanner:
    """Scans a Mendix 10 project directory and extracts structured metadata.

    Accepts either a project directory or an .mpr file path. When an .mpr is
    supplied (or located inside the chosen directory and `run_mpr_extract=True`),
    `mx dump-mpr` is executed to populate `ProjectScan.mpr_data` with the
    full 19-section structure.
    """

    def scan(self, target: str,
             on_progress: ProgressCB = None,
             run_mpr_extract: bool = True) -> Optional[ProjectScan]:
        path = Path(target)
        mpr_file: Optional[Path] = None
        if path.is_file() and path.suffix.lower() == ".mpr":
            mpr_file = path
            path = path.parent
        if not path.exists() or not path.is_dir():
            return None

        scan = ProjectScan(
            project_name=self._get_project_name(path),
            project_path=str(path),
            has_git=(path / ".git").exists(),
            has_native=(path / "deployment" / "native").exists(),
            mpr_path=str(mpr_file) if mpr_file else "",
        )

        # Detect Mendix version from launch file
        for lf in path.glob("*.launch"):
            content = lf.read_text(errors="ignore")
            if "10." in content:
                scan.mendix_version = "10.x"
            elif "9." in content:
                scan.mendix_version = "9.x"

        # Scan javasource → modules
        javasource = path / "javasource"
        if javasource.exists():
            for mod_dir in sorted(javasource.iterdir()):
                if mod_dir.is_dir():
                    scan.modules.append(self._scan_module(mod_dir))

        # Libraries (JARs only, skip marker files)
        userlib = path / "userlib"
        if userlib.exists():
            scan.libraries = [
                f.name for f in userlib.iterdir()
                if f.suffix == ".jar" and f.is_file()
            ]

        # Widgets
        widgets = path / "widgets"
        if widgets.exists():
            scan.widgets = [f.name for f in widgets.iterdir()]

        # Resources - detect RTL
        resources = path / "resources"
        if resources.exists():
            for f in resources.rglob("*"):
                if f.is_file():
                    scan.resources.append(f.name)
                    if "rtl" in f.name.lower():
                        scan.has_rtl = True

        # If no .mpr was supplied explicitly, look for one in the project root
        if not scan.mpr_path:
            for cand in path.glob("*.mpr"):
                scan.mpr_path = str(cand)
                break

        # Run mx dump-mpr when requested and an .mpr is available
        if run_mpr_extract and scan.mpr_path:
            self._run_mpr_extraction(scan, on_progress)

        return scan

    def _run_mpr_extraction(self, scan: ProjectScan, on_progress: ProgressCB) -> None:
        extractor = MPRExtractor()
        if not extractor.is_available():
            msg = ("mx.exe not found (Mendix Studio Pro 10+ required for "
                   "`mx dump-mpr`).")
            scan.mpr_error = msg
            if on_progress:
                on_progress(msg)
            return
        if on_progress:
            on_progress(f"Using mx.exe: {extractor.mx_exe}")
        try:
            scan.mpr_data = extractor.extract(scan.mpr_path, on_progress=on_progress)
            scan.mpr_error = ""
        except Exception as exc:
            scan.mpr_data = None
            scan.mpr_error = f"{exc}"
            if on_progress:
                on_progress(f"MPR extraction failed: {exc}")

    def _get_project_name(self, path: Path) -> str:
        mprname = path / "mprcontents" / "mprname"
        if mprname.exists():
            return mprname.read_text(errors="ignore").strip().replace(".mpr", "")
        for mpr in path.glob("*.mpr"):
            return mpr.stem
        return path.name

    def _scan_module(self, module_dir: Path) -> ModuleInfo:
        module = ModuleInfo(name=module_dir.name)
        proxies = module_dir / "proxies"
        if proxies.exists():
            for jf in proxies.glob("*.java"):
                n = jf.stem
                lower = n.lower()
                if n in ("Microflows",):
                    module.microflow_names = self._parse_microflow_names(jf)
                    continue
                if n in ("Constants",):
                    module.constants = self._parse_constants(jf)
                    continue
                if n in ("Workflows",):
                    continue
                if lower.startswith("enum_") or lower.startswith("enm_") or lower.startswith("enum"):
                    module.enums.append(n)
                    vals = self._parse_enum_values(jf)
                    if vals:
                        module.enum_values[n] = vals
                else:
                    module.entities.append(n)
                    attrs, assocs = self._parse_member_names(jf)
                    if attrs or assocs:
                        module.entity_details.append(
                            EntityInfo(name=n, attributes=attrs, associations=assocs))
            module.has_workflows = (proxies / "workflows").exists()
            module.has_microflows = (proxies / "microflows").exists()

        actions = module_dir / "actions"
        if actions.exists():
            module.java_actions = [f.stem for f in actions.glob("*.java")]

        return module

    # ── Java proxy parsers ─────────────────────────────────────────────── #

    _MEMBER_BLOCK_RE = re.compile(
        r"public\s+enum\s+MemberNames\s*\{([^}]+)\}", re.DOTALL)
    _MEMBER_ITEM_RE = re.compile(
        r'([A-Za-z_][A-Za-z0-9_]*)\s*\(\s*"([^"]+)"\s*\)')
    _MICROFLOW_METHOD_RE = re.compile(
        r"public\s+static\s+(?:[A-Za-z0-9_<>\[\],\s\.]+)\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*\(",
        re.MULTILINE)
    _CONSTANT_METHOD_RE = re.compile(
        r"public\s+static\s+[A-Za-z0-9_<>\[\]\.]+\s+get([A-Z][a-zA-Z0-9_]*)\s*\(\s*\)")
    _ENUM_VALUE_RE = re.compile(
        r"^\s*([A-Z][A-Za-z0-9_]*)\s*\(", re.MULTILINE)

    def _read(self, path: Path, limit: int = 200_000) -> str:
        try:
            return path.read_text(errors="ignore")[:limit]
        except Exception:
            return ""

    def _parse_member_names(self, java_file: Path) -> Tuple[List[str], List[str]]:
        """Extract attributes and associations from the MemberNames enum."""
        text = self._read(java_file)
        m = self._MEMBER_BLOCK_RE.search(text)
        if not m:
            return [], []
        attrs, assocs = [], []
        for ident, raw in self._MEMBER_ITEM_RE.findall(m.group(1)):
            if "." in raw or "_" in ident and ident[0].isupper() and any(
                    c.isupper() for c in ident[1:]):
                # Associations are typically named like "ModuleName.AssocName"
                # or contain an underscore separating two entity-like CamelCase names.
                if "." in raw or re.match(r"^[A-Z][A-Za-z0-9]*_[A-Z][A-Za-z0-9]*", ident):
                    assocs.append(ident)
                    continue
            attrs.append(ident)
        return attrs, assocs

    def _parse_microflow_names(self, java_file: Path) -> List[str]:
        text = self._read(java_file)
        names = self._MICROFLOW_METHOD_RE.findall(text)
        # filter out helper methods commonly auto-generated
        skip = {"getInstance", "valueOf", "values", "toString"}
        return [n for n in dict.fromkeys(names) if n not in skip]

    def _parse_constants(self, java_file: Path) -> List[str]:
        text = self._read(java_file)
        return list(dict.fromkeys(self._CONSTANT_METHOD_RE.findall(text)))

    def _parse_enum_values(self, java_file: Path) -> List[str]:
        text = self._read(java_file)
        # Find first enum block
        m = re.search(r"public\s+enum\s+\w+\s*\{([^}]+)\}", text, re.DOTALL)
        if not m:
            return []
        return list(dict.fromkeys(self._ENUM_VALUE_RE.findall(m.group(1))))

    def to_context_string(self, scan: ProjectScan, compact: bool = False) -> str:
        """Build the full project context string sent to the AI agents.

        When `compact=True`, the digest is shrunk so the full prompt fits
        inside an 8K-token window: the mpr_data digest is rebuilt with
        `compact=True`, the per-module filesystem appendix is replaced by a
        short summary, and the libraries listing is trimmed.
        """
        biz = scan.business_modules
        total_microflows = sum(len(m.microflow_names) for m in scan.modules)
        total_attrs = sum(
            sum(e.attribute_count for e in m.entity_details) for m in scan.modules)
        lines: List[str] = []

        # Prepend the full MPR dump digest when available — this is the
        # authoritative model data the AI agents should reason about.
        if scan.mpr_data is not None:
            lines += [
                "================================================================",
                " FULL MPR DUMP — extracted via `mx dump-mpr` (19-section schema)",
                "================================================================",
                scan.mpr_data.to_context_string(
                    max_modules=40, max_per_module=8, compact=compact),
            ]
            if not compact:
                lines += [
                    "",
                    "================================================================",
                    " FILESYSTEM SCAN — javasource / userlib / resources",
                    "================================================================",
                ]

        # In compact mode we only emit a one-block headline + integration
        # libraries; the per-module Java-proxy detail is redundant with the
        # mpr_data digest above and adds ~2K chars for no extra signal.
        if compact and scan.mpr_data is not None:
            lines += [
                "",
                f"FILESYSTEM HEADLINES: mendix={scan.mendix_version} · "
                f"git={scan.has_git} · native={scan.has_native} · rtl={scan.has_rtl} · "
                f"libs={len(scan.libraries)} · widgets={len(scan.widgets)}",
                "",
                "=== KEY INTEGRATION LIBRARIES ===",
                ", ".join(scan.integration_libraries[:15]) or "None detected",
            ]
            return "\n".join(lines)

        lines += [
            f"PROJECT NAME: {scan.project_name}",
            f"MENDIX VERSION: {scan.mendix_version}",
            f"MPR FILE: {scan.mpr_path or '(none — directory scan only)'}",
            f"TOTAL MODULES: {scan.module_count} ({len(biz)} business, {scan.module_count - len(biz)} platform)",
            f"TOTAL ENTITIES: {scan.entity_count}",
            f"TOTAL ATTRIBUTES (parsed): {total_attrs}",
            f"TOTAL ENUMS: {scan.enum_count}",
            f"TOTAL MICROFLOWS (proxy-exposed): {total_microflows}",
            f"JAVA LIBRARIES: {len(scan.libraries)}",
            f"CUSTOM WIDGETS: {len(scan.widgets)}",
            f"HAS GIT: {scan.has_git}",
            f"HAS RTL (Arabic): {scan.has_rtl}",
            f"HAS NATIVE MOBILE: {scan.has_native}",
            "",
            "=== BUSINESS MODULES (DETAILED) ===",
        ]
        for m in biz:
            lines.append(f"\n## MODULE: {m.name}")
            if m.entities:
                lines.append(f"  Entities ({len(m.entities)}): "
                             f"{', '.join(m.entities[:12])}"
                             f"{' ...' if len(m.entities) > 12 else ''}")
            # Detailed entity info (top 6 per module to keep context manageable)
            for ent in m.entity_details[:6]:
                attrs_preview = ', '.join(ent.attributes[:8])
                more = f" ...(+{len(ent.attributes)-8} more)" if len(ent.attributes) > 8 else ""
                lines.append(f"    • {ent.name}: [{attrs_preview}{more}]")
                if ent.associations:
                    assocs_preview = ', '.join(ent.associations[:5])
                    lines.append(f"        ↳ assocs: {assocs_preview}"
                                 f"{' ...' if len(ent.associations) > 5 else ''}")
            if m.enums:
                lines.append(f"  Enums ({len(m.enums)}): "
                             f"{', '.join(m.enums[:6])}"
                             f"{' ...' if len(m.enums) > 6 else ''}")
                # Show values for first 2 enums
                for en in m.enums[:2]:
                    vals = m.enum_values.get(en, [])
                    if vals:
                        lines.append(f"    • {en} = [{', '.join(vals[:8])}"
                                     f"{' ...' if len(vals) > 8 else ''}]")
            if m.microflow_names:
                lines.append(f"  Microflows ({len(m.microflow_names)} exposed): "
                             f"{', '.join(m.microflow_names[:8])}"
                             f"{' ...' if len(m.microflow_names) > 8 else ''}")
            if m.java_actions:
                lines.append(f"  Java Actions: {', '.join(m.java_actions[:5])}"
                             f"{' ...' if len(m.java_actions) > 5 else ''}")
            if m.constants:
                lines.append(f"  Constants: {', '.join(m.constants[:5])}"
                             f"{' ...' if len(m.constants) > 5 else ''}")
            if m.has_workflows:
                lines.append(f"  [Has Mendix Workflows]")

        lines += ["", "=== KEY INTEGRATION LIBRARIES ==="]
        lines.append(", ".join(scan.integration_libraries[:20]) or "None detected")
        lines += ["", "=== ALL JAVA LIBRARIES (sample) ==="]
        lines.append(", ".join(scan.libraries[:25]) +
                     (f" ...(+{len(scan.libraries)-25} more)" if len(scan.libraries) > 25 else ""))
        return "\n".join(lines)
