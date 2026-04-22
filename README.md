# ⚡ Mendix Multi-Agent Analyzer

A professional desktop application that analyzes any **Mendix 10** project using local AI agents (no cloud, fully on-premises) and generates a comprehensive technical + business documentation report.

---

## 🚀 Features

- 📁 **Project Scanner** — reads any Mendix project directory (no `.mpr` binary parsing required)
- 🤖 **4-Agent AI Pipeline** — Architect → Business Analyst → QA Engineer → Consolidation
- 🌐 **Local AI Support** — works with Ollama, LM Studio, Jan, AnythingLLM, Llamafile, or built-in GGUF
- 📊 **HTML Report** — self-contained dark-theme report with module tables, risk register, user stories
- 🔒 **100% On-Premises** — no data leaves your machine

---

## 📋 Requirements

- Python 3.9+ (or use the Python bundled with LM Studio)
- `pip install requests`
- A local AI provider running (see below)

---

## ▶️ Quick Start

```bash
# 1. Clone the repo
git clone <your-repo-url>
cd mendix-analyzer

# 2. Install dependency
pip install requests

# 3. Launch
python run.py
```

Or double-click **`launch.bat`** on Windows — it auto-detects Python.

---

## 🤖 Supported Local AI Providers

| Provider | Default Port | Notes |
|---|---|---|
| **LM Studio** | 1234 | Install from lmstudio.ai — already has CLI (`lms server start`) |
| **Ollama** | 11434 | `winget install Ollama.Ollama` then `ollama pull qwen2.5:3b` |
| **Jan** | 1337 | jan.ai |
| **AnythingLLM** | 3001 | anythingllm.com |
| **Llamafile** | 8080 | Single executable, no install |
| **Built-in GGUF** | N/A | Place `.gguf` file in `/models/` folder |

---

## 🏗️ Project Structure

```
mendix-analyzer/
├── launch.bat                  # Windows launcher (auto-finds Python)
├── run.py                      # Entry point
├── requirements.txt            # pip dependencies
├── models/                     # Place .gguf model files here (gitignored)
└── mendix_analyzer/
    ├── app.py                  # Desktop UI (tkinter, dark theme)
    ├── scanner.py              # Mendix project metadata extractor
    ├── ai_client.py            # Multi-provider AI client with streaming
    ├── pipeline.py             # 4-agent orchestration + prompts
    └── report_gen.py           # HTML report generator
```

---

## 📊 Report Output

The generated HTML report includes:
- **Architecture** — modules, entities, integrations, security, risks
- **Business Analysis** — actors, processes, epics, user stories, acceptance criteria
- **QA Report** — gaps, test scenarios, risk analysis, NFRs
- **Executive Summary** — consolidated findings and top recommendations

---

## 🔧 Starting LM Studio Server via CLI

```powershell
# List models
lms ls

# Start server (port 1234)
lms server start
```

---

## 📝 License

MIT License — free to use, modify, and distribute.
