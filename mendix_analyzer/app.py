"""
Mendix Multi-Agent Analyzer — Main Desktop Application
Built with tkinter (stdlib only; no extra UI dependencies).
"""
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
import threading, queue, os, webbrowser, datetime, json
from pathlib import Path
from typing import Optional

from .scanner   import MendixScanner, ProjectScan
from .ai_client import AIClient, PROVIDERS
from .pipeline  import AnalysisPipeline
from .report_gen import ReportGenerator

# ── Colour palette (dark theme) ─────────────────────────────────────────── #
BG      = "#0f1117"
PANEL   = "#1a1d2e"
CARD    = "#22263a"
BORDER  = "#2d3552"
ACCENT  = "#6c8ebf"
ACCENT2 = "#4ecca3"
TEXT    = "#e2e8f0"
MUTED   = "#8892a4"
RED     = "#f87171"
GREEN   = "#4ade80"
YELLOW  = "#fbbf24"
BTN_BG  = "#2d3552"
BTN_ACT = "#4ecca3"

FONT       = ("Segoe UI", 10)
FONT_BOLD  = ("Segoe UI", 10, "bold")
FONT_H1    = ("Segoe UI", 16, "bold")
FONT_H2    = ("Segoe UI", 12, "bold")
FONT_SMALL = ("Segoe UI", 9)
FONT_MONO  = ("Consolas", 9)


def _style_button(btn: tk.Button, primary=False):
    bg = ACCENT2 if primary else BTN_BG
    fg = "#0f1117" if primary else TEXT
    btn.configure(bg=bg, fg=fg, relief="flat", font=FONT_BOLD,
                  padx=14, pady=7, cursor="hand2", bd=0,
                  activebackground=ACCENT, activeforeground="#fff")


class SidebarButton(tk.Button):
    def __init__(self, parent, text, command, **kw):
        super().__init__(parent, text=text, command=command,
                         bg=PANEL, fg=MUTED, relief="flat", font=FONT,
                         padx=20, pady=10, anchor="w", cursor="hand2", bd=0,
                         activebackground=CARD, activeforeground=TEXT, **kw)
        self.bind("<Enter>", lambda _: self.configure(fg=TEXT, bg=CARD))
        self.bind("<Leave>", self._restore)
        self._active = False

    def _restore(self, _=None):
        if not self._active:
            self.configure(fg=MUTED, bg=PANEL)

    def set_active(self, active: bool):
        self._active = active
        self.configure(fg=TEXT if active else MUTED,
                       bg=CARD if active else PANEL,
                       font=(*FONT[:2], "bold") if active else FONT)


class StatusBar(tk.Frame):
    def __init__(self, parent):
        super().__init__(parent, bg=PANEL, height=28)
        self.label = tk.Label(self, text="Ready", bg=PANEL, fg=MUTED, font=FONT_SMALL, anchor="w")
        self.label.pack(side="left", padx=12, fill="x", expand=True)
        self.dot = tk.Label(self, text="●", bg=PANEL, fg=MUTED, font=FONT_SMALL)
        self.dot.pack(side="right", padx=12)

    def set(self, msg: str, color=MUTED):
        self.label.configure(text=msg, fg=color)
        self.dot.configure(fg=color)


class MendixAnalyzerApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("⚡ Mendix Multi-Agent Analyzer v1.0")
        self.geometry("1280x820")
        self.minsize(1100, 700)
        self.configure(bg=BG)

        # State
        self.scan_result:    Optional[ProjectScan] = None
        self.ai_client:      Optional[AIClient]    = None
        self.last_results:   dict = {}
        self.stop_flag:      list = [False]
        self.log_queue:      queue.Queue = queue.Queue()
        self.available_models: list = []

        # Tkinter variables
        self.var_dir      = tk.StringVar()
        self.var_provider = tk.StringVar(value="Ollama")
        self.var_url      = tk.StringVar(value="http://localhost:11434")
        self.var_apikey   = tk.StringVar()
        self.var_conn     = tk.StringVar(value="Not tested")
        self.var_model_arch = tk.StringVar()
        self.var_model_ba   = tk.StringVar()
        self.var_model_qa   = tk.StringVar()
        self.var_model_cons = tk.StringVar()
        self.var_en_arch  = tk.BooleanVar(value=True)
        self.var_en_ba    = tk.BooleanVar(value=True)
        self.var_en_qa    = tk.BooleanVar(value=True)
        self.var_en_cons  = tk.BooleanVar(value=True)
        self.var_progress = tk.DoubleVar(value=0)
        self.var_status   = tk.StringVar(value="Ready")

        self._build_ui()
        self._poll_log_queue()

    # ── UI Construction ────────────────────────────────────────────────── #

    def _build_ui(self):
        # Header bar
        hdr = tk.Frame(self, bg=PANEL, height=52)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)
        tk.Label(hdr, text="⚡  Mendix Multi-Agent Analyzer",
                 bg=PANEL, fg=ACCENT2, font=("Segoe UI", 13, "bold")).pack(side="left", padx=20, pady=14)
        tk.Label(hdr, text="v1.0 • On-Premises AI",
                 bg=PANEL, fg=MUTED, font=FONT_SMALL).pack(side="right", padx=20)

        # Body
        body = tk.Frame(self, bg=BG)
        body.pack(fill="both", expand=True)

        # Sidebar
        self.sidebar = tk.Frame(body, bg=PANEL, width=220)
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)

        tk.Label(self.sidebar, text="NAVIGATION", bg=PANEL, fg=MUTED,
                 font=("Segoe UI", 8), pady=12).pack(fill="x", padx=20)

        self.pages = {}
        self.nav_btns = {}
        nav_items = [
            ("setup",    "📁  Project Setup"),
            ("agents",   "🤖  AI Agents"),
            ("analysis", "▶   Run Analysis"),
            ("report",   "📊  Report"),
        ]
        for key, label in nav_items:
            btn = SidebarButton(self.sidebar, label, lambda k=key: self._show_page(k))
            btn.pack(fill="x")
            self.nav_btns[key] = btn

        # Content area
        self.content = tk.Frame(body, bg=BG)
        self.content.pack(side="left", fill="both", expand=True)

        # Build all pages
        self.pages["setup"]    = self._build_setup_page()
        self.pages["agents"]   = self._build_agents_page()
        self.pages["analysis"] = self._build_analysis_page()
        self.pages["report"]   = self._build_report_page()

        # Status bar
        self.status_bar = StatusBar(self)
        self.status_bar.pack(fill="x", side="bottom")

        self._show_page("setup")

    def _show_page(self, key: str):
        for k, frame in self.pages.items():
            frame.pack_forget()
            self.nav_btns[k].set_active(False)
        self.pages[key].pack(fill="both", expand=True)
        self.nav_btns[key].set_active(True)

    # ── Helper widgets ────────────────────────────────────────────────── #

    def _scrollable(self, parent) -> tk.Frame:
        """Returns an inner frame inside a canvas+scrollbar for scrollable pages."""
        canvas = tk.Canvas(parent, bg=BG, bd=0, highlightthickness=0)
        vsb    = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
        inner  = tk.Frame(canvas, bg=BG)
        inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.configure(yscrollcommand=vsb.set)
        canvas.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        canvas.bind_all("<MouseWheel>", lambda e: canvas.yview_scroll(-1*(e.delta//120), "units"))
        return inner

    def _section_label(self, parent, text: str):
        f = tk.Frame(parent, bg=BG)
        f.pack(fill="x", padx=32, pady=(22, 6))
        tk.Label(f, text=text, bg=BG, fg=ACCENT, font=FONT_H2).pack(side="left")
        tk.Frame(f, bg=BORDER, height=1).pack(side="left", fill="x", expand=True, padx=(12, 0), pady=6)

    def _card(self, parent, **kw) -> tk.Frame:
        f = tk.Frame(parent, bg=CARD, bd=0, relief="flat", **kw)
        f.pack(fill="x", padx=32, pady=6)
        return f

    def _labeled_entry(self, parent, label, var, width=44, show="") -> tk.Entry:
        tk.Label(parent, text=label, bg=CARD, fg=MUTED, font=FONT_SMALL).pack(anchor="w", padx=16, pady=(10, 2))
        e = tk.Entry(parent, textvariable=var, bg=PANEL, fg=TEXT, insertbackground=TEXT,
                     font=FONT, relief="flat", width=width, show=show)
        e.pack(fill="x", padx=16, pady=(0, 10), ipady=6)
        return e

    # ── Page 1: Project Setup ─────────────────────────────────────────── #

    def _build_setup_page(self) -> tk.Frame:
        page  = tk.Frame(self.content, bg=BG)
        inner = self._scrollable(page)

        # Hero
        hero = tk.Frame(inner, bg=PANEL)
        hero.pack(fill="x")
        tk.Label(hero, text="📁  Project Setup", bg=PANEL, fg=TEXT, font=FONT_H1,
                 pady=18, padx=32, anchor="w").pack(fill="x")
        tk.Label(hero, text="Select a Mendix project directory to scan and analyse.",
                 bg=PANEL, fg=MUTED, font=FONT, padx=32, anchor="w").pack(fill="x")
        tk.Frame(hero, bg=BORDER, height=1).pack(fill="x", pady=(12, 0))

        # Directory picker card
        self._section_label(inner, "Mendix Project Directory")
        card = self._card(inner)
        card.pack(fill="x", padx=32, pady=6, ipadx=4, ipady=4)

        dir_row = tk.Frame(card, bg=CARD)
        dir_row.pack(fill="x", padx=16, pady=14)
        tk.Label(dir_row, text="Directory:", bg=CARD, fg=MUTED, font=FONT_SMALL).pack(anchor="w")
        row2 = tk.Frame(dir_row, bg=CARD)
        row2.pack(fill="x", pady=(4, 0))
        e = tk.Entry(row2, textvariable=self.var_dir, bg=PANEL, fg=TEXT, insertbackground=TEXT,
                     font=FONT, relief="flat", width=60)
        e.pack(side="left", fill="x", expand=True, ipady=8, padx=(0, 8))
        browse_btn = tk.Button(row2, text="📂 Browse", command=self._browse_dir)
        _style_button(browse_btn)
        browse_btn.pack(side="right")

        scan_btn = tk.Button(card, text="🔍  Scan Project", command=self._scan_project)
        _style_button(scan_btn, primary=True)
        scan_btn.pack(anchor="e", padx=16, pady=(0, 14))

        # Results area
        self._section_label(inner, "Scan Results")
        self.scan_results_frame = tk.Frame(inner, bg=BG)
        self.scan_results_frame.pack(fill="x")
        tk.Label(self.scan_results_frame,
                 text="No project scanned yet. Use Browse to select a Mendix project directory.",
                 bg=BG, fg=MUTED, font=FONT, padx=32, pady=16).pack(anchor="w")
        return page

    def _browse_dir(self):
        d = filedialog.askdirectory(title="Select Mendix Project Directory")
        if d:
            self.var_dir.set(d)

    def _scan_project(self):
        d = self.var_dir.get().strip()
        if not d or not Path(d).exists():
            messagebox.showerror("Error", "Please select a valid directory.")
            return
        self.status_bar.set("Scanning project...", YELLOW)
        threading.Thread(target=self._do_scan, args=(d,), daemon=True).start()

    def _do_scan(self, directory: str):
        scanner = MendixScanner()
        result  = scanner.scan(directory)
        self.after(0, lambda: self._on_scan_done(result))

    def _on_scan_done(self, result: Optional[ProjectScan]):
        if result is None:
            messagebox.showerror("Scan Failed", "Directory does not appear to be a Mendix project.")
            self.status_bar.set("Scan failed", RED)
            return
        self.scan_result = result
        self._render_scan_results(result)
        self.status_bar.set(f"✅ Scanned: {result.project_name} — {result.module_count} modules found", GREEN)

    def _render_scan_results(self, scan: ProjectScan):
        for w in self.scan_results_frame.winfo_children():
            w.destroy()

        biz = scan.business_modules

        # Stats grid
        stats = [
            ("📦", "Project", scan.project_name),
            ("🏗️", "Mendix Version", scan.mendix_version),
            ("📚", "Total Modules", str(scan.module_count)),
            ("🏢", "Business Modules", str(len(biz))),
            ("📄", "Entities", str(scan.entity_count)),
            ("🔢", "Enums", str(scan.enum_count)),
            ("📦", "Libraries", str(len(scan.libraries))),
            ("🌐", "RTL / Arabic", "Yes" if scan.has_rtl else "No"),
            ("📱", "Native Mobile", "Yes" if scan.has_native else "No"),
            ("🔀", "Git Tracked", "Yes" if scan.has_git else "No"),
        ]
        grid = tk.Frame(self.scan_results_frame, bg=BG)
        grid.pack(fill="x", padx=32, pady=8)
        for i, (icon, lbl, val) in enumerate(stats):
            c = tk.Frame(grid, bg=CARD, padx=16, pady=12)
            c.grid(row=i//5, column=i%5, padx=6, pady=6, sticky="nsew")
            grid.columnconfigure(i%5, weight=1)
            tk.Label(c, text=icon, bg=CARD, font=("Segoe UI", 18)).pack()
            tk.Label(c, text=val, bg=CARD, fg=ACCENT2, font=FONT_BOLD).pack()
            tk.Label(c, text=lbl, bg=CARD, fg=MUTED, font=FONT_SMALL).pack()

        # Module table (top 20 business modules)
        self._section_label(self.scan_results_frame, f"Business Modules ({len(biz)} found)")
        tbl_frame = tk.Frame(self.scan_results_frame, bg=CARD)
        tbl_frame.pack(fill="x", padx=32, pady=6)
        cols = ("Module", "Entities", "Enums", "Java Actions", "Workflows")
        tv   = ttk.Treeview(tbl_frame, columns=cols, show="headings", height=12)
        self._style_treeview(tv)
        for c in cols:
            tv.heading(c, text=c)
            tv.column(c, width=160 if c == "Module" else 90, anchor="center" if c != "Module" else "w")
        for m in biz[:30]:
            tv.insert("", "end", values=(
                m.name, len(m.entities), len(m.enums),
                len(m.java_actions), "✅" if m.has_workflows else "—"
            ))
        vsb2 = ttk.Scrollbar(tbl_frame, orient="vertical", command=tv.yview)
        tv.configure(yscrollcommand=vsb2.set)
        tv.pack(side="left", fill="both", expand=True, padx=2, pady=2)
        vsb2.pack(side="right", fill="y", pady=2)

        # Proceed hint
        tk.Label(self.scan_results_frame,
                 text="✅  Project scanned. Go to 🤖 AI Agents to configure your local model.",
                 bg=BG, fg=GREEN, font=FONT, padx=32, pady=12).pack(anchor="w")

    def _style_treeview(self, tv: ttk.Treeview):
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Treeview", background=CARD, foreground=TEXT,
                        fieldbackground=CARD, rowheight=28, font=FONT)
        style.configure("Treeview.Heading", background=PANEL, foreground=ACCENT,
                        font=FONT_BOLD, relief="flat")
        style.map("Treeview", background=[("selected", ACCENT)], foreground=[("selected", "#fff")])

    # ── Page 2: AI Agents ─────────────────────────────────────────────── #

    def _build_agents_page(self) -> tk.Frame:
        page  = tk.Frame(self.content, bg=BG)
        inner = self._scrollable(page)

        hero = tk.Frame(inner, bg=PANEL)
        hero.pack(fill="x")
        tk.Label(hero, text="🤖  AI Agents Configuration", bg=PANEL, fg=TEXT,
                 font=FONT_H1, pady=18, padx=32, anchor="w").pack(fill="x")
        tk.Label(hero, text="Connect to your local AI provider and assign models to each agent role.",
                 bg=PANEL, fg=MUTED, font=FONT, padx=32, anchor="w").pack(fill="x")
        tk.Frame(hero, bg=BORDER, height=1).pack(fill="x", pady=(12, 0))

        # Provider selection
        self._section_label(inner, "Provider Settings")
        card1 = tk.Frame(inner, bg=CARD)
        card1.pack(fill="x", padx=32, pady=6, ipadx=4)

        row = tk.Frame(card1, bg=CARD)
        row.pack(fill="x", padx=16, pady=14)
        tk.Label(row, text="Provider:", bg=CARD, fg=MUTED, font=FONT_SMALL).grid(row=0, column=0, sticky="w")
        provider_cb = ttk.Combobox(row, textvariable=self.var_provider,
                                   values=list(PROVIDERS.keys()), state="readonly", width=18)
        provider_cb.grid(row=0, column=1, padx=(8, 24), sticky="w")
        provider_cb.bind("<<ComboboxSelected>>", self._on_provider_change)

        tk.Label(row, text="Base URL:", bg=CARD, fg=MUTED, font=FONT_SMALL).grid(row=0, column=2, sticky="w")
        url_e = tk.Entry(row, textvariable=self.var_url, bg=PANEL, fg=TEXT,
                         insertbackground=TEXT, font=FONT, relief="flat", width=30)
        url_e.grid(row=0, column=3, padx=(8, 24), ipady=6, sticky="w")

        row2 = tk.Frame(card1, bg=CARD)
        row2.pack(fill="x", padx=16, pady=(0, 14))
        tk.Label(row2, text="API Key (optional):", bg=CARD, fg=MUTED, font=FONT_SMALL).pack(side="left")
        tk.Entry(row2, textvariable=self.var_apikey, bg=PANEL, fg=TEXT, insertbackground=TEXT,
                 font=FONT, relief="flat", width=30, show="*").pack(side="left", padx=(8, 24), ipady=6)

        conn_btn = tk.Button(row2, text="🔌 Test Connection", command=self._test_connection)
        _style_button(conn_btn)
        conn_btn.pack(side="left")
        self.conn_label = tk.Label(row2, textvariable=self.var_conn, bg=CARD, fg=MUTED, font=FONT_SMALL)
        self.conn_label.pack(side="left", padx=12)

        disc_btn = tk.Button(row2, text="🔎 Discover Models", command=self._discover_models)
        _style_button(disc_btn)
        disc_btn.pack(side="left", padx=(16, 0))

        # ── Quick-start helper banner ──────────────────────────────────
        self._section_label(inner, "Quick Start — No Service Running?")
        qs = tk.Frame(inner, bg=CARD)
        qs.pack(fill="x", padx=32, pady=6, ipadx=4, ipady=4)
        qs_top = tk.Frame(qs, bg=CARD)
        qs_top.pack(fill="x", padx=16, pady=(12, 6))

        # Ollama start button
        ol_frame = tk.Frame(qs_top, bg=PANEL, padx=14, pady=10)
        ol_frame.pack(side="left", padx=(0, 12))
        tk.Label(ol_frame, text="🦙  Ollama", bg=PANEL, fg=ACCENT2, font=FONT_BOLD).pack()
        tk.Label(ol_frame, text="Local AI service", bg=PANEL, fg=MUTED, font=FONT_SMALL).pack()
        start_ol = tk.Button(ol_frame, text="▶ Start Ollama", command=self._start_ollama)
        _style_button(start_ol, primary=True)
        start_ol.pack(pady=(8, 0))
        pull_ol = tk.Button(ol_frame, text="⬇ Pull qwen2.5:3b", command=self._pull_model)
        _style_button(pull_ol)
        pull_ol.pack(pady=(4, 0))

        # LM Studio hint
        lm_frame = tk.Frame(qs_top, bg=PANEL, padx=14, pady=10)
        lm_frame.pack(side="left", padx=(0, 12))
        tk.Label(lm_frame, text="🎨  LM Studio", bg=PANEL, fg=ACCENT2, font=FONT_BOLD).pack()
        tk.Label(lm_frame, text="Already installed", bg=PANEL, fg=MUTED, font=FONT_SMALL).pack()
        tk.Label(lm_frame, text="1. Open LM Studio\n2. Load any model\n3. Click Start Server\n4. Come back here",
                 bg=PANEL, fg=TEXT, font=FONT_SMALL, justify="left").pack(pady=(8, 0))

        # Built-in GGUF
        bi_frame = tk.Frame(qs_top, bg=PANEL, padx=14, pady=10)
        bi_frame.pack(side="left")
        tk.Label(bi_frame, text="📦  Built-in GGUF", bg=PANEL, fg=ACCENT2, font=FONT_BOLD).pack()
        tk.Label(bi_frame, text="No service needed", bg=PANEL, fg=MUTED, font=FONT_SMALL).pack()
        dl_btn = tk.Button(bi_frame, text="⬇ Download Model File", command=self._download_gguf)
        _style_button(dl_btn)
        dl_btn.pack(pady=(8, 0))
        tk.Label(bi_frame, text="Place .gguf files in\n/models/ folder",
                 bg=PANEL, fg=MUTED, font=FONT_SMALL, justify="center").pack(pady=(4, 0))

        self.qs_log = tk.Label(qs, text="", bg=CARD, fg=ACCENT2, font=FONT_SMALL, anchor="w")
        self.qs_log.pack(fill="x", padx=16, pady=(4, 12))

        # Model list
        self._section_label(inner, "Available Models")
        models_card = tk.Frame(inner, bg=CARD)
        models_card.pack(fill="x", padx=32, pady=6)
        self.models_list = tk.Listbox(models_card, bg=PANEL, fg=TEXT, font=FONT_MONO,
                                      relief="flat", height=6, selectmode="browse",
                                      selectbackground=ACCENT, selectforeground="#fff")
        self.models_list.pack(fill="x", padx=16, pady=14)
        self.models_list.insert("end", "Press 'Discover Models' to list available models →")

        # Agent role assignments
        self._section_label(inner, "Agent Role Assignments")
        roles_card = tk.Frame(inner, bg=CARD)
        roles_card.pack(fill="x", padx=32, pady=6, ipadx=4, ipady=4)

        self.model_vars = {
            "architect": self.var_model_arch,
            "ba":        self.var_model_ba,
            "qa":        self.var_model_qa,
            "cons":      self.var_model_cons,
        }
        roles = [
            ("🏗️  Architect Agent",     self.var_model_arch, "Analyzes system structure, modules, integrations"),
            ("💼  Business Analyst",    self.var_model_ba,   "Extracts requirements, epics, user stories"),
            ("🧪  QA Engineer",         self.var_model_qa,   "Validates requirements, writes test scenarios"),
            ("📄  Consolidation Agent", self.var_model_cons, "Merges all outputs into final executive report"),
        ]
        self.role_cbs: dict = {}
        for label, var, desc in roles:
            rrow = tk.Frame(roles_card, bg=CARD)
            rrow.pack(fill="x", padx=16, pady=8)
            tk.Label(rrow, text=label, bg=CARD, fg=TEXT, font=FONT_BOLD, width=24, anchor="w").pack(side="left")
            cb = ttk.Combobox(rrow, textvariable=var, values=[], state="readonly", width=28)
            cb.pack(side="left", padx=12)
            tk.Label(rrow, text=desc, bg=CARD, fg=MUTED, font=FONT_SMALL).pack(side="left", padx=8)
            key = label.split()[1].lower()[:4]
            self.role_cbs[key] = cb

        # Apply same model button
        same_btn = tk.Button(roles_card, text="⟳  Apply first model to all roles",
                             command=self._apply_same_model)
        _style_button(same_btn)
        same_btn.pack(anchor="e", padx=16, pady=(4, 14))

        go_btn = tk.Button(inner, text="✅  Save & Continue to Analysis  →",
                           command=lambda: self._show_page("analysis"))
        _style_button(go_btn, primary=True)
        go_btn.pack(anchor="e", padx=32, pady=16)
        return page

    def _on_provider_change(self, _=None):
        cfg = PROVIDERS.get(self.var_provider.get(), {})
        self.var_url.set(cfg.get("base_url", "http://localhost:11434"))
        self.var_conn.set("Not tested")
        self.conn_label.configure(fg=MUTED)

    def _test_connection(self):
        client = AIClient(self.var_provider.get(), self.var_url.get(), self.var_apikey.get())
        ok, msg = client.test_connection()
        self.var_conn.set(msg)
        self.conn_label.configure(fg=GREEN if ok else RED)
        if ok:
            self.ai_client = client
            self.status_bar.set(f"Connected to {self.var_provider.get()}", GREEN)

    def _discover_models(self):
        client = AIClient(self.var_provider.get(), self.var_url.get(), self.var_apikey.get())
        self.status_bar.set("Discovering models...", YELLOW)
        def _do():
            models = client.list_models()
            self.after(0, lambda: self._on_models_discovered(client, models))
        threading.Thread(target=_do, daemon=True).start()

    def _on_models_discovered(self, client: AIClient, models: list):
        self.ai_client = client
        self.available_models = models
        self.models_list.delete(0, "end")
        if not models:
            self.models_list.insert("end", "No models found. Is the provider running?")
            self.status_bar.set("No models found", RED)
            return
        for m in models:
            self.models_list.insert("end", f"  {m}")
        for cb in self.role_cbs.values():
            cb.configure(values=models)
        for var in self.model_vars.values():
            if not var.get() and models:
                var.set(models[0])
        self.status_bar.set(f"Found {len(models)} model(s)", GREEN)

    # ── Quick-start helpers ───────────────────────────────────────────── #

    def _qs_log(self, msg: str, color=ACCENT2):
        self.after(0, lambda: self.qs_log.configure(text=msg, fg=color))

    def _start_ollama(self):
        """Try to start Ollama service — works if Ollama is installed."""
        import subprocess, shutil
        self._qs_log("Starting Ollama service...", YELLOW)
        ollama_exe = shutil.which("ollama")
        if not ollama_exe:
            # Try known locations
            candidates = [
                os.path.expandvars(r"%LOCALAPPDATA%\Programs\Ollama\ollama.exe"),
                r"C:\Program Files\Ollama\ollama.exe",
                r"C:\Users\Administrator\AppData\Local\Programs\Ollama\ollama.exe",
            ]
            for c in candidates:
                if os.path.exists(c):
                    ollama_exe = c
                    break
        if not ollama_exe:
            self._qs_log("❌ Ollama not found. Install it from https://ollama.com", RED)
            return

        def _do():
            try:
                subprocess.Popen([ollama_exe, "serve"],
                                 creationflags=subprocess.CREATE_NO_WINDOW)
                import time; time.sleep(3)
                # Auto-discover
                self.var_provider.set("Ollama")
                self.var_url.set("http://localhost:11434")
                client = AIClient("Ollama", "http://localhost:11434")
                ok, msg = client.test_connection()
                if ok:
                    models = client.list_models()
                    self.after(0, lambda: self._on_models_discovered(client, models))
                    self._qs_log(f"✅ Ollama running — {len(models)} model(s) found", GREEN)
                else:
                    self._qs_log(f"⚠️ Ollama started but: {msg}", YELLOW)
            except Exception as e:
                self._qs_log(f"❌ Failed to start Ollama: {e}", RED)

        threading.Thread(target=_do, daemon=True).start()

    def _pull_model(self):
        """Pull qwen2.5:3b via Ollama — small and fast model."""
        import subprocess, shutil
        ollama_exe = shutil.which("ollama")
        if not ollama_exe:
            for c in [os.path.expandvars(r"%LOCALAPPDATA%\Programs\Ollama\ollama.exe"),
                      r"C:\Program Files\Ollama\ollama.exe"]:
                if os.path.exists(c):
                    ollama_exe = c
                    break
        if not ollama_exe:
            self._qs_log("❌ Ollama not installed yet", RED)
            return
        self._qs_log("⬇  Pulling qwen2.5:3b (~2 GB) — this may take several minutes...", YELLOW)
        def _do():
            try:
                result = subprocess.run([ollama_exe, "pull", "qwen2.5:3b"],
                                        capture_output=True, text=True, timeout=600)
                if result.returncode == 0:
                    self._qs_log("✅ qwen2.5:3b downloaded! Click 'Discover Models'.", GREEN)
                    self._discover_models()
                else:
                    self._qs_log(f"❌ Pull failed: {result.stderr[:100]}", RED)
            except Exception as e:
                self._qs_log(f"❌ Error: {e}", RED)
        threading.Thread(target=_do, daemon=True).start()

    def _download_gguf(self):
        """Open browser to Hugging Face for a recommended small GGUF model."""
        import webbrowser
        # Qwen2.5-3B-Instruct GGUF — good quality, ~2GB
        url = "https://huggingface.co/Qwen/Qwen2.5-3B-Instruct-GGUF/resolve/main/qwen2.5-3b-instruct-q4_k_m.gguf"
        models_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "models")
        os.makedirs(models_dir, exist_ok=True)
        webbrowser.open(url)
        self._qs_log(
            f"Browser opened — save the .gguf file to:\n{models_dir}  then select 'Built-in (GGUF)' provider.",
            ACCENT2)

    def _apply_same_model(self):
        if not self.available_models:
            return
        first = self.available_models[0]
        for var in self.model_vars.values():
            var.set(first)

    # ── Page 3: Analysis ─────────────────────────────────────────────── #

    def _build_analysis_page(self) -> tk.Frame:
        page = tk.Frame(self.content, bg=BG)

        # Top hero
        hero = tk.Frame(page, bg=PANEL)
        hero.pack(fill="x")
        tk.Label(hero, text="▶   Run Multi-Agent Analysis", bg=PANEL, fg=TEXT,
                 font=FONT_H1, pady=18, padx=32, anchor="w").pack(fill="x")
        tk.Label(hero, text="Enable agents below, then click Start Analysis.",
                 bg=PANEL, fg=MUTED, font=FONT, padx=32, anchor="w").pack(fill="x")
        tk.Frame(hero, bg=BORDER, height=1).pack(fill="x", pady=(12, 0))

        # Control row
        ctrl = tk.Frame(page, bg=BG)
        ctrl.pack(fill="x", padx=32, pady=16)

        # Agent toggles
        toggle_card = tk.Frame(ctrl, bg=CARD, padx=16, pady=12)
        toggle_card.pack(side="left")
        tk.Label(toggle_card, text="AGENTS TO RUN", bg=CARD, fg=MUTED,
                 font=("Segoe UI", 8), anchor="w").pack(fill="x")
        agent_checks = [
            ("🏗️  Architect",    self.var_en_arch),
            ("💼  BA",           self.var_en_ba),
            ("🧪  QA",           self.var_en_qa),
            ("📄  Consolidation",self.var_en_cons),
        ]
        for label, var in agent_checks:
            tk.Checkbutton(toggle_card, text=label, variable=var,
                           bg=CARD, fg=TEXT, font=FONT,
                           selectcolor=PANEL, activebackground=CARD,
                           activeforeground=TEXT).pack(anchor="w", pady=2)

        # Start / Stop buttons
        btn_frame = tk.Frame(ctrl, bg=BG)
        btn_frame.pack(side="left", padx=32)
        self.start_btn = tk.Button(btn_frame, text="▶  Start Analysis",
                                   command=self._start_analysis, width=18)
        _style_button(self.start_btn, primary=True)
        self.start_btn.pack(pady=6)
        self.stop_btn = tk.Button(btn_frame, text="⏹  Stop",
                                  command=self._stop_analysis, width=18, state="disabled")
        _style_button(self.stop_btn)
        self.stop_btn.pack()

        # Step indicators
        self.step_frame = tk.Frame(ctrl, bg=BG)
        self.step_frame.pack(side="left", padx=16)
        self.step_labels: dict = {}
        for key, icon in [("architect","🏗️"),("ba","💼"),("qa","🧪"),("consolidation","📄")]:
            f = tk.Frame(self.step_frame, bg=BG)
            f.pack(side="left", padx=10)
            lbl = tk.Label(f, text=f"{icon}\n—", bg=BG, fg=MUTED,
                           font=FONT_SMALL, justify="center")
            lbl.pack()
            self.step_labels[key] = lbl

        # Progress bar
        pb_frame = tk.Frame(page, bg=BG)
        pb_frame.pack(fill="x", padx=32, pady=(0, 8))
        self.progress_lbl = tk.Label(pb_frame, text="", bg=BG, fg=MUTED, font=FONT_SMALL)
        self.progress_lbl.pack(anchor="w")
        style = ttk.Style()
        style.configure("green.Horizontal.TProgressbar", troughcolor=CARD,
                        background=ACCENT2, borderwidth=0, thickness=8)
        self.progress_bar = ttk.Progressbar(pb_frame, variable=self.var_progress,
                                            maximum=100, length=400,
                                            style="green.Horizontal.TProgressbar")
        self.progress_bar.pack(fill="x", pady=4)

        # Live output log
        tk.Label(page, text="Live Output", bg=BG, fg=ACCENT, font=FONT_BOLD,
                 padx=32, anchor="w").pack(fill="x", pady=(8, 4))
        log_frame = tk.Frame(page, bg=CARD)
        log_frame.pack(fill="both", expand=True, padx=32, pady=(0, 16))
        self.log_text = scrolledtext.ScrolledText(
            log_frame, bg="#0d1117", fg="#4ecca3", font=FONT_MONO,
            relief="flat", state="disabled", wrap="word",
            insertbackground=ACCENT2, padx=12, pady=10,
        )
        self.log_text.pack(fill="both", expand=True)
        self.log_text.tag_configure("stage",  foreground=ACCENT2, font=(*FONT_MONO[:1], 10, "bold"))
        self.log_text.tag_configure("info",   foreground=ACCENT)
        self.log_text.tag_configure("err",    foreground=RED)
        self.log_text.tag_configure("normal", foreground="#c0caf5")

        # Bottom bar
        bot = tk.Frame(page, bg=PANEL)
        bot.pack(fill="x")
        clr_btn = tk.Button(bot, text="🗑  Clear Log", command=self._clear_log)
        _style_button(clr_btn); clr_btn.pack(side="left", padx=12, pady=8)
        rep_btn = tk.Button(bot, text="📊  Open Report →",
                            command=lambda: self._show_page("report"))
        _style_button(rep_btn, primary=True); rep_btn.pack(side="right", padx=12, pady=8)
        return page

    def _log(self, msg: str, tag="normal"):
        self.log_queue.put((msg, tag))

    def _poll_log_queue(self):
        try:
            while True:
                msg, tag = self.log_queue.get_nowait()
                self.log_text.configure(state="normal")
                self.log_text.insert("end", msg, tag)
                self.log_text.see("end")
                self.log_text.configure(state="disabled")
        except queue.Empty:
            pass
        self.after(50, self._poll_log_queue)

    def _clear_log(self):
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")

    def _start_analysis(self):
        if not self.scan_result:
            messagebox.showwarning("No Project", "Please scan a project first (📁 Project Setup).")
            return
        if not self.ai_client:
            client = AIClient(self.var_provider.get(), self.var_url.get(), self.var_apikey.get())
            ok, msg = client.test_connection()
            if not ok:
                messagebox.showerror("Connection Failed", f"Cannot reach AI provider:\n{msg}")
                return
            self.ai_client = client

        # collect models - fall back to first discovered or placeholder
        fallback = self.available_models[0] if self.available_models else "default"
        models = {
            "architect":     self.var_model_arch.get() or fallback,
            "ba":            self.var_model_ba.get()   or fallback,
            "qa":            self.var_model_qa.get()   or fallback,
            "consolidation": self.var_model_cons.get() or fallback,
        }
        enabled = {
            "architect":     self.var_en_arch.get(),
            "ba":            self.var_en_ba.get(),
            "qa":            self.var_en_qa.get(),
            "consolidation": self.var_en_cons.get(),
        }

        self.stop_flag = [False]
        self.start_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        self.var_progress.set(0)
        self._clear_log()
        self._reset_steps()

        scanner = MendixScanner()
        context = scanner.to_context_string(self.scan_result)

        n_enabled = sum(enabled.values())
        self._progress_step = 0
        self._progress_total = n_enabled

        def on_token(tok: str):
            self.log_queue.put((tok, "normal"))

        def on_stage(label: str):
            self._progress_step += 1
            pct = (self._progress_step - 1) / max(self._progress_total, 1) * 100
            self.after(0, lambda l=label, p=pct: self._update_stage(l, p))

        def on_done(results: dict):
            self.after(0, lambda: self._on_analysis_done(results))

        pipeline = AnalysisPipeline(
            client=self.ai_client, models=models, context=context,
            on_token=on_token, on_stage=on_stage, on_done=on_done,
            stop_flag=self.stop_flag,
        )
        threading.Thread(target=pipeline.run, args=(enabled,), daemon=True).start()
        self.status_bar.set("Analysis running...", YELLOW)

    def _stop_analysis(self):
        self.stop_flag[0] = True
        self._log("\n⏹  Stopped by user.\n", "err")
        self.start_btn.configure(state="normal")
        self.stop_btn.configure(state="disabled")
        self.status_bar.set("Stopped", MUTED)

    def _update_stage(self, label: str, pct: float):
        self.var_progress.set(pct)
        self.progress_lbl.configure(text=f"Running: {label}")
        self._log(f"\n\n{'='*60}\n  {label}\n{'='*60}\n\n", "stage")
        # Update step indicator
        for key, lbl in self.step_labels.items():
            if key in label.lower():
                lbl.configure(fg=ACCENT2, text=f"{lbl.cget('text').split()[0]}\n⟳")

    def _reset_steps(self):
        icons = {"architect":"🏗️","ba":"💼","qa":"🧪","consolidation":"📄"}
        for k, lbl in self.step_labels.items():
            lbl.configure(text=f"{icons.get(k,'')}\n—", fg=MUTED)

    def _on_analysis_done(self, results: dict):
        self.last_results = results
        self.var_progress.set(100)
        self.progress_lbl.configure(text="✅ Analysis complete")
        self.start_btn.configure(state="normal")
        self.stop_btn.configure(state="disabled")
        self._log("\n\n✅  All agents complete. Generating report...\n", "stage")
        # Auto-generate report
        self._generate_report(results)
        self.status_bar.set("✅ Analysis complete — Report ready", GREEN)
        for lbl in self.step_labels.values():
            txt = lbl.cget("text").split("\n")[0]
            lbl.configure(text=f"{txt}\n✅", fg=GREEN)

    # ── Page 4: Report ───────────────────────────────────────────────── #

    def _build_report_page(self) -> tk.Frame:
        page = tk.Frame(self.content, bg=BG)

        hero = tk.Frame(page, bg=PANEL)
        hero.pack(fill="x")
        tk.Label(hero, text="📊  Analysis Report", bg=PANEL, fg=TEXT,
                 font=FONT_H1, pady=18, padx=32, anchor="w").pack(fill="x")
        tk.Label(hero, text="View and export the consolidated multi-agent report.",
                 bg=PANEL, fg=MUTED, font=FONT, padx=32, anchor="w").pack(fill="x")
        tk.Frame(hero, bg=BORDER, height=1).pack(fill="x", pady=(12, 0))

        # Action buttons
        btn_row = tk.Frame(page, bg=BG)
        btn_row.pack(fill="x", padx=32, pady=16)

        open_btn = tk.Button(btn_row, text="🌐  Open in Browser",
                             command=self._open_report_browser)
        _style_button(open_btn, primary=True); open_btn.pack(side="left", padx=(0, 10))

        save_btn = tk.Button(btn_row, text="💾  Save Report As...",
                             command=self._save_report_as)
        _style_button(save_btn); save_btn.pack(side="left", padx=(0, 10))

        regen_btn = tk.Button(btn_row, text="🔄  Regenerate Report",
                              command=lambda: self._generate_report(self.last_results))
        _style_button(regen_btn); regen_btn.pack(side="left")

        # Report summary cards
        self.report_summary = tk.Frame(page, bg=BG)
        self.report_summary.pack(fill="x", padx=32, pady=(0, 8))
        tk.Label(self.report_summary,
                 text="Run an analysis first (▶ Run Analysis) to generate a report.",
                 bg=BG, fg=MUTED, font=FONT, pady=12).pack(anchor="w")

        # Report path display
        path_card = tk.Frame(page, bg=CARD)
        path_card.pack(fill="x", padx=32, pady=6)
        tk.Label(path_card, text="Report saved to:", bg=CARD, fg=MUTED,
                 font=FONT_SMALL, padx=16, pady=8).pack(side="left")
        self.report_path_lbl = tk.Label(path_card, text="—", bg=CARD,
                                        fg=ACCENT2, font=FONT_MONO, padx=4)
        self.report_path_lbl.pack(side="left")

        # Section preview
        tk.Label(page, text="Report Sections", bg=BG, fg=ACCENT,
                 font=FONT_BOLD, padx=32, anchor="w").pack(fill="x", pady=(16, 4))

        sections_frame = tk.Frame(page, bg=BG)
        sections_frame.pack(fill="x", padx=32)
        section_defs = [
            ("🏗️", "Architecture",    "System structure, modules, domain model, integrations, risks"),
            ("💼", "Business Analysis","Actors, processes, epics, user stories, acceptance criteria"),
            ("🧪", "QA Report",       "Requirement gaps, test scenarios, risk analysis, NFRs"),
            ("📄", "Consolidation",   "Executive summary, key risks, top recommendations"),
        ]
        for i, (icon, title, desc) in enumerate(section_defs):
            c = tk.Frame(sections_frame, bg=CARD, padx=16, pady=14)
            c.grid(row=i//2, column=i%2, padx=6, pady=6, sticky="nsew")
            sections_frame.columnconfigure(i%2, weight=1)
            tk.Label(c, text=f"{icon}  {title}", bg=CARD, fg=ACCENT2, font=FONT_BOLD).pack(anchor="w")
            tk.Label(c, text=desc, bg=CARD, fg=MUTED, font=FONT_SMALL,
                     wraplength=340, justify="left").pack(anchor="w", pady=(4, 0))

        return page

    def _generate_report(self, results: dict):
        if not self.scan_result:
            return
        gen  = ReportGenerator()
        path = str(Path.home() / "Desktop" / f"MendixReport_{datetime.datetime.now():%Y%m%d_%H%M%S}.html")
        gen.save(self.scan_result, results, path)
        self.report_path = path
        self.report_path_lbl.configure(text=path)
        self._update_report_summary(results)
        self._log(f"\n📊  Report saved → {path}\n", "stage")

    def _update_report_summary(self, results: dict):
        for w in self.report_summary.winfo_children():
            w.destroy()
        cards = [
            ("🏗️", "Architect",    "architect"    in results and bool(results["architect"])),
            ("💼", "BA",           "ba"            in results and bool(results["ba"])),
            ("🧪", "QA",           "qa"            in results and bool(results["qa"])),
            ("📄", "Consolidated", "consolidation" in results and bool(results["consolidation"])),
        ]
        for icon, label, done in cards:
            c = tk.Frame(self.report_summary, bg=CARD if done else PANEL, padx=16, pady=12)
            c.pack(side="left", padx=(0, 8))
            status = "✅  Complete" if done else "⏳  Pending"
            color  = GREEN if done else MUTED
            tk.Label(c, text=f"{icon} {label}", bg=c.cget("bg"), fg=TEXT, font=FONT_BOLD).pack()
            tk.Label(c, text=status, bg=c.cget("bg"), fg=color, font=FONT_SMALL).pack()

    def _open_report_browser(self):
        path = getattr(self, "report_path", None)
        if path and Path(path).exists():
            webbrowser.open(f"file:///{path}")
        else:
            messagebox.showinfo("No Report", "No report generated yet. Run an analysis first.")

    def _save_report_as(self):
        if not self.last_results or not self.scan_result:
            messagebox.showinfo("No Data", "Run an analysis first.")
            return
        dest = filedialog.asksaveasfilename(
            defaultextension=".html",
            filetypes=[("HTML Report", "*.html"), ("All files", "*.*")],
            initialfile=f"MendixReport_{self.scan_result.project_name}.html",
        )
        if dest:
            gen = ReportGenerator()
            gen.save(self.scan_result, self.last_results, dest)
            self.report_path_lbl.configure(text=dest)
            messagebox.showinfo("Saved", f"Report saved to:\n{dest}")
