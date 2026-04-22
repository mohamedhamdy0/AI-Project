"""
Mendix Multi-Agent Analyzer - Launcher
Run this file: python run.py
"""
import sys
import os

# Ensure we can import from the package
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from mendix_analyzer.app import MendixAnalyzerApp
except ImportError as e:
    print(f"[ERROR] Missing dependency: {e}")
    print("Run: pip install requests")
    sys.exit(1)

if __name__ == "__main__":
    app = MendixAnalyzerApp()
    app.mainloop()
