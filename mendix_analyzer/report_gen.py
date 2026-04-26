"""
HTML Report Generator
Produces a self-contained, professional HTML report from agent outputs.
"""
import re
import html
import zlib
import base64
import datetime
from pathlib import Path
from typing import Dict, Optional
from .scanner import ProjectScan


def _plantuml_to_kroki_url(source: str) -> str:
    """Encode PlantUML source for kroki.io rendering (deflate + url-safe base64)."""
    compressed = zlib.compress(source.encode("utf-8"), 9)
    encoded = base64.urlsafe_b64encode(compressed).decode("ascii").rstrip("=")
    return f"https://kroki.io/plantuml/svg/{encoded}"


def _md_to_html(text: str) -> str:
    """Markdown → HTML (tables, headers, bold, lists, code, PlantUML diagrams)."""
    lines = text.split("\n")
    out, in_table, in_ul, in_ol = [], False, False, False
    in_code = False
    code_lang = ""
    code_buf: list = []

    def flush_list():
        nonlocal in_ul, in_ol
        if in_ul:
            out.append("</ul>"); in_ul = False
        if in_ol:
            out.append("</ol>"); in_ol = False

    def flush_table():
        nonlocal in_table
        if in_table:
            out.append("</tbody></table>"); in_table = False

    def flush_code():
        nonlocal in_code, code_lang, code_buf
        if not in_code:
            return
        src = "\n".join(code_buf).strip()
        if code_lang.lower() in ("plantuml", "puml", "uml") and src:
            url = _plantuml_to_kroki_url(src)
            out.append(
                f'<div class="puml"><img src="{url}" alt="PlantUML diagram" '
                f'loading="lazy"/><details><summary>Show source</summary>'
                f'<pre class="code">{html.escape(src)}</pre></details></div>')
        else:
            cls = f' class="code lang-{html.escape(code_lang)}"' if code_lang else ' class="code"'
            out.append(f"<pre{cls}>{html.escape(src)}</pre>")
        in_code = False
        code_lang = ""
        code_buf = []

    for line in lines:
        # Fenced code block start/end
        m_code = re.match(r"^\s*```\s*([A-Za-z0-9_+\-]*)\s*$", line)
        if m_code:
            if not in_code:
                flush_list(); flush_table()
                in_code = True
                code_lang = m_code.group(1) or ""
            else:
                flush_code()
            continue
        if in_code:
            code_buf.append(line)
            continue

        # Tables
        if line.strip().startswith("|"):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if re.match(r"^[\s\-|:]+$", line):          # separator row
                continue
            if not in_table:
                flush_list()
                out.append('<table class="md-table"><tbody>')
                in_table = True
            tag = "th" if not in_table or len(out) <= 2 else "td"
            out.append("<tr>" + "".join(f"<{tag}>{c}</{tag}>" for c in cells) + "</tr>")
            continue
        else:
            flush_table()

        # Headers
        m = re.match(r"^(#{1,4})\s+(.+)", line)
        if m:
            flush_list()
            level = min(len(m.group(1)) + 1, 5)
            text_h = _inline(m.group(2))
            anchor = re.sub(r"[^a-z0-9]+", "-", text_h.lower()).strip("-")
            out.append(f'<h{level} id="{anchor}">{text_h}</h{level}>')
            continue

        # Ordered list
        m = re.match(r"^\d+\.\s+(.*)", line)
        if m:
            flush_table()
            if not in_ol:
                flush_list(); out.append("<ol>"); in_ol = True
            out.append(f"<li>{_inline(m.group(1))}</li>")
            continue

        # Unordered list
        m = re.match(r"^[\-\*]\s+(.*)", line)
        if m:
            flush_table()
            if not in_ul:
                flush_list(); out.append("<ul>"); in_ul = True
            out.append(f"<li>{_inline(m.group(1))}</li>")
            continue

        flush_list()
        if line.strip() == "":
            out.append("<br>")
        else:
            out.append(f"<p>{_inline(line)}</p>")

    flush_list(); flush_table(); flush_code()
    return "\n".join(out)


def _inline(text: str) -> str:
    """Convert inline markdown (bold, italic, code, badges) to HTML."""
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"\*([^*]+)\*", r"<em>\1</em>", text)
    # Emoji risk badges → colored spans
    text = text.replace("🔴", '<span class="badge red">🔴</span>')
    text = text.replace("🟠", '<span class="badge orange">🟠</span>')
    text = text.replace("🟡", '<span class="badge yellow">🟡</span>')
    text = text.replace("🟢", '<span class="badge green">🟢</span>')
    text = text.replace("✅", '<span class="badge green">✅</span>')
    text = text.replace("⚠️", '<span class="badge yellow">⚠️</span>')
    text = text.replace("❌", '<span class="badge red">❌</span>')
    return text


CSS = """
:root{--bg:#0f1117;--panel:#1a1d2e;--card:#22263a;--accent:#6c8ebf;
      --accent2:#4ecca3;--text:#e2e8f0;--muted:#8892a4;--border:#2d3552;
      --red:#f87171;--orange:#fb923c;--yellow:#fbbf24;--green:#4ade80;}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Segoe UI',system-ui,sans-serif;background:var(--bg);
     color:var(--text);line-height:1.7;font-size:15px;}
.wrapper{display:flex;min-height:100vh}
/* Sidebar */
.sidebar{width:260px;background:var(--panel);border-right:1px solid var(--border);
         position:sticky;top:0;height:100vh;overflow-y:auto;padding:24px 0;flex-shrink:0}
.sidebar-logo{padding:0 24px 24px;border-bottom:1px solid var(--border);margin-bottom:16px}
.sidebar-logo h2{color:var(--accent2);font-size:1.1rem;font-weight:700}
.sidebar-logo p{color:var(--muted);font-size:.78rem;margin-top:4px}
.nav-item{display:block;padding:10px 24px;color:var(--muted);text-decoration:none;
          font-size:.88rem;border-left:3px solid transparent;transition:.2s}
.nav-item:hover,.nav-item.active{color:var(--text);background:var(--card);
  border-left-color:var(--accent2)}
.nav-section{padding:12px 24px 4px;font-size:.72rem;text-transform:uppercase;
             letter-spacing:.08em;color:var(--muted);margin-top:8px}
/* Main */
.main{flex:1;overflow-x:hidden}
.hero{background:linear-gradient(135deg,#1a1d2e 0%,#0f1117 60%,#12172b 100%);
      padding:48px 48px 40px;border-bottom:1px solid var(--border)}
.hero h1{font-size:2rem;font-weight:800;
         background:linear-gradient(90deg,var(--accent2),var(--accent));
         -webkit-background-clip:text;-webkit-text-fill-color:transparent}
.hero p{color:var(--muted);margin-top:8px;font-size:.95rem}
.hero-meta{display:flex;gap:24px;margin-top:20px;flex-wrap:wrap}
.hero-badge{background:var(--card);border:1px solid var(--border);
            padding:6px 14px;border-radius:20px;font-size:.82rem;color:var(--accent2)}
/* Stats row */
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));
       gap:16px;padding:32px 48px}
.stat-card{background:var(--card);border:1px solid var(--border);border-radius:12px;
           padding:20px;text-align:center}
.stat-card .num{font-size:2rem;font-weight:800;color:var(--accent2)}
.stat-card .lbl{font-size:.78rem;color:var(--muted);margin-top:4px;text-transform:uppercase;letter-spacing:.05em}
/* Content sections */
.section{padding:32px 48px;border-bottom:1px solid var(--border)}
.section h2{font-size:1.3rem;font-weight:700;color:var(--accent);margin-bottom:20px;
            display:flex;align-items:center;gap:10px}
.agent-block{background:var(--card);border:1px solid var(--border);border-radius:12px;
             padding:28px;margin-bottom:24px}
.agent-header{display:flex;align-items:center;gap:12px;margin-bottom:20px;
              padding-bottom:16px;border-bottom:1px solid var(--border)}
.agent-icon{font-size:1.6rem}
.agent-title{font-size:1.05rem;font-weight:700;color:var(--accent2)}
.agent-sub{font-size:.8rem;color:var(--muted)}
/* Markdown output */
.md-body h2{color:var(--accent);font-size:1.1rem;margin:24px 0 12px;
            border-bottom:1px solid var(--border);padding-bottom:6px}
.md-body h3{color:var(--accent2);font-size:1rem;margin:18px 0 8px}
.md-body h4{color:var(--text);font-size:.95rem;margin:14px 0 6px}
.md-body p{color:var(--text);margin:6px 0}
.md-body ul,.md-body ol{margin:8px 0 8px 22px;color:var(--text)}
.md-body li{margin:3px 0}
.md-body code{background:#0d1117;color:#4ecca3;padding:2px 7px;border-radius:4px;font-size:.88em}
.md-body strong{color:#fff}
/* Tables */
.md-table{width:100%;border-collapse:collapse;margin:16px 0;font-size:.88rem}
.md-table th{background:rgba(108,142,191,.15);color:var(--accent);
             padding:10px 14px;text-align:left;border:1px solid var(--border)}
.md-table td{padding:9px 14px;border:1px solid var(--border);color:var(--text)}
.md-table tr:nth-child(even) td{background:rgba(255,255,255,.02)}
/* Badges */
.badge{padding:1px 5px;border-radius:4px}
.badge.red{color:var(--red)}.badge.orange{color:var(--orange)}
.badge.yellow{color:var(--yellow)}.badge.green{color:var(--green)}
/* Code & PlantUML */
pre.code{background:#0d1117;color:#c0caf5;padding:14px 16px;border-radius:8px;
         border:1px solid var(--border);overflow-x:auto;font-family:Consolas,Menlo,monospace;
         font-size:.85rem;line-height:1.5;margin:12px 0}
.puml{margin:18px 0;padding:14px;background:#fff;border-radius:10px;
      border:1px solid var(--border);text-align:center}
.puml img{max-width:100%;height:auto}
.puml details{margin-top:8px;text-align:left;background:#0d1117;
              border-radius:6px;padding:6px 12px}
.puml summary{cursor:pointer;color:var(--accent2);font-size:.82rem;font-weight:600}
.puml details pre.code{margin:8px 0 0 0;border:0}
/* Footer */
.footer{padding:24px 48px;text-align:center;color:var(--muted);font-size:.8rem;
        border-top:1px solid var(--border)}
@media print{.sidebar{display:none}.hero{padding:24px}.stats{grid-template-columns:repeat(4,1fr)}}
"""


class ReportGenerator:
    def build(self, scan: ProjectScan, results: Dict[str, str]) -> str:
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        biz = scan.business_modules

        def section(icon, title, key, desc):
            output = results.get(key, "_Agent did not run._")
            return f"""
<div class="section" id="{key}">
  <h2>{icon} {title}</h2>
  <div class="agent-block">
    <div class="agent-header">
      <span class="agent-icon">{icon}</span>
      <div><div class="agent-title">{title} Analysis</div>
           <div class="agent-sub">{desc}</div></div>
    </div>
    <div class="md-body">{_md_to_html(output)}</div>
  </div>
</div>"""

        nav = "\n".join([
            '<span class="nav-section">9-Section Report</span>',
            '<a class="nav-item" href="#architect">🏗️ §1-2,7 Architecture &amp; Domain Model</a>',
            '<a class="nav-item" href="#ba">💼 §4-5 Business &amp; UI Analysis</a>',
            '<a class="nav-item" href="#qa">🧪 §3,6,8 Microflows · Security · Risks</a>',
            '<a class="nav-item" href="#consolidation">📄 §9 Final Summary</a>',
        ])

        stats_html = "".join([
            f'<div class="stat-card"><div class="num">{scan.module_count}</div><div class="lbl">Modules</div></div>',
            f'<div class="stat-card"><div class="num">{len(biz)}</div><div class="lbl">Business Modules</div></div>',
            f'<div class="stat-card"><div class="num">{scan.entity_count}</div><div class="lbl">Entities</div></div>',
            f'<div class="stat-card"><div class="num">{scan.enum_count}</div><div class="lbl">Enums</div></div>',
            f'<div class="stat-card"><div class="num">{len(scan.libraries)}</div><div class="lbl">Libraries</div></div>',
            f'<div class="stat-card"><div class="num">{len(scan.widgets)}</div><div class="lbl">Widgets</div></div>',
        ])

        return f"""<!DOCTYPE html><html lang="en"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Mendix Analyzer — {html.escape(scan.project_name)}</title>
<style>{CSS}</style></head><body>
<div class="wrapper">
<nav class="sidebar">
  <div class="sidebar-logo"><h2>⚡ Mendix Analyzer</h2>
    <p>Multi-Agent Report</p></div>
  <a class="nav-item" href="#overview">📊 Overview</a>
  {nav}
  <span class="nav-section">Meta</span>
  <a class="nav-item" href="#footer">ℹ️ About</a>
</nav>
<div class="main">
  <div class="hero" id="overview">
    <h1>📦 {html.escape(scan.project_name)}</h1>
    <p>Multi-Agent Architecture, Business & QA Analysis</p>
    <div class="hero-meta">
      <span class="hero-badge">📁 {html.escape(scan.project_path)}</span>
      <span class="hero-badge">🕐 {now}</span>
      <span class="hero-badge">🏗️ Mendix {scan.mendix_version}</span>
      {'<span class="hero-badge">🌐 RTL / Arabic</span>' if scan.has_rtl else ''}
      {'<span class="hero-badge">📱 Native Mobile</span>' if scan.has_native else ''}
    </div>
  </div>
  <div class="stats">{stats_html}</div>
  {section("🏗️","Architecture &amp; Domain Model","architect","§1 System Overview · §2 Domain Model · §7 PlantUML Diagrams (ERD, Architecture, Sequence)")}
  {section("💼","Business &amp; UI Analysis","ba","§4 Actors, Processes, User Stories, Business Rules · §5 UI / Page Analysis")}
  {section("🧪","Microflows · Security · Risks","qa","§3 Microflow Analysis · §6 Security Analysis · §8 Risks &amp; Improvements")}
  {section("📄","Final Summary","consolidation","§9 Executive summary, system maturity verdict, critical risks &amp; top recommendations")}
  <div class="footer" id="footer">Generated by Mendix Multi-Agent Analyzer v1.1 · {now}</div>
</div></div></body></html>"""

    def save(self, scan: ProjectScan, results: Dict[str, str], output_path: str) -> str:
        html_content = self.build(scan, results)
        Path(output_path).write_text(html_content, encoding="utf-8")
        return output_path
