"""
Mendix Project Scanner
Extracts metadata from a Mendix 10 project directory without reading the binary .mpr file.
"""
import os
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class ModuleInfo:
    name: str
    entities: List[str] = field(default_factory=list)
    enums: List[str] = field(default_factory=list)
    java_actions: List[str] = field(default_factory=list)
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
    """Scans a Mendix 10 project directory and extracts structured metadata."""

    def scan(self, project_dir: str) -> Optional[ProjectScan]:
        path = Path(project_dir)
        if not path.exists() or not path.is_dir():
            return None

        scan = ProjectScan(
            project_name=self._get_project_name(path),
            project_path=str(path),
            has_git=(path / ".git").exists(),
            has_native=(path / "deployment" / "native").exists(),
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

        return scan

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
                if lower.startswith("enum_") or lower.startswith("enm_") or lower.startswith("enum"):
                    module.enums.append(n)
                elif n not in ("Microflows", "Workflows", "Constants"):
                    module.entities.append(n)
            module.has_workflows = (proxies / "workflows").exists()
            module.has_microflows = (proxies / "microflows").exists()

        actions = module_dir / "actions"
        if actions.exists():
            module.java_actions = [f.stem for f in actions.glob("*.java")]

        return module

    def to_context_string(self, scan: ProjectScan) -> str:
        biz = scan.business_modules
        lines = [
            f"PROJECT NAME: {scan.project_name}",
            f"MENDIX VERSION: {scan.mendix_version}",
            f"TOTAL MODULES: {scan.module_count} ({len(biz)} business, {scan.module_count - len(biz)} platform)",
            f"TOTAL ENTITIES: {scan.entity_count}",
            f"TOTAL ENUMS: {scan.enum_count}",
            f"JAVA LIBRARIES: {len(scan.libraries)}",
            f"CUSTOM WIDGETS: {len(scan.widgets)}",
            f"HAS GIT: {scan.has_git}",
            f"HAS RTL (Arabic): {scan.has_rtl}",
            f"HAS NATIVE MOBILE: {scan.has_native}",
            "",
            "=== BUSINESS MODULES ===",
        ]
        for m in biz:
            lines.append(f"\nMODULE: {m.name}")
            if m.entities:
                lines.append(f"  Entities ({len(m.entities)}): {', '.join(m.entities[:8])}{'...' if len(m.entities) > 8 else ''}")
            if m.enums:
                lines.append(f"  Enums ({len(m.enums)}): {', '.join(m.enums[:5])}{'...' if len(m.enums) > 5 else ''}")
            if m.java_actions:
                lines.append(f"  Java Actions: {', '.join(m.java_actions[:5])}")
            if m.has_workflows:
                lines.append(f"  [Has Mendix Workflows]")

        lines += ["", "=== KEY INTEGRATION LIBRARIES ==="]
        lines.append(", ".join(scan.integration_libraries[:20]) or "None detected")
        return "\n".join(lines)
