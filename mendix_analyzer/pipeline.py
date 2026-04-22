"""
Multi-Agent Analysis Pipeline
Orchestrates Architect → BA → QA → Consolidation agents.
"""
from typing import Callable, Dict, Optional
from .ai_client import AIClient

# ── System prompts ────────────────────────────────────────────────────────── #

ARCHITECT_PROMPT = """You are a Senior Software Architect with 15+ years of Mendix experience.
Analyze the Mendix project metadata provided and produce a structured technical architecture document.

Output the following sections using Markdown headers (##):

## 1. System Overview
Brief description of what the system does and its business domain.

## 2. Architecture Style
Describe the overall architectural pattern (modular monolith, microservices, etc.).

## 3. Module Breakdown
Create a markdown table: | Module | Type | Responsibility | Key Entities |

## 4. Data Model Summary
Describe key entities and their relationships.

## 5. Integration Points
List all external systems, protocols, and purposes.

## 6. Security Design
Describe authentication, authorization, and security mechanisms.

## 7. Risks & Technical Debt
List the top risks with severity (🔴 Critical / 🟠 High / 🟡 Medium / 🟢 Low).

Be precise, technical, and base everything on the provided metadata.
State assumptions clearly if inferred."""

BA_PROMPT = """You are a Senior Business Analyst with expertise in enterprise systems and government platforms.
Using the Mendix project metadata and the Architect's analysis provided, extract business requirements.

Output the following sections using Markdown headers (##):

## 1. Business Overview
What problem does this system solve? Who are the users?

## 2. Actors Table
Markdown table: | Actor | Type | Description | Permissions |

## 3. Business Processes
List 4-6 core business processes as numbered step-by-step flows.

## 4. Epics
List 8-12 epics: | Epic ID | Epic Name | Description |

## 5. User Stories
Write 12+ user stories in format:
**US-XXX**: As a [user], I want [goal], so that [value].

## 6. Acceptance Criteria
Provide Given/When/Then criteria for 3 key user stories.

## 7. Business Rules
Table: | Rule ID | Business Rule | Source |

## 8. Assumptions & Gaps
List what is unclear or missing from requirements.

Focus on business value. Do not repeat technical architecture details."""

QA_PROMPT = """You are a Senior QA Engineer and Software Quality Analyst.
Critically evaluate the Mendix project metadata, Architect analysis, and BA requirements provided.

Output the following sections using Markdown headers (##):

## 1. Requirement Gaps
Table: | Gap ID | Area | Issue | Risk if Unresolved |

## 2. Test Scenarios
Table with 12+ test cases: | TC-ID | Scenario | Steps | Expected Result |

## 3. Edge Cases
List 8+ edge cases that could break the system.

## 4. Risk Analysis
Table: | Risk | Probability | Impact | Mitigation |

## 5. Consistency Check
Compare Architect and BA outputs. Flag contradictions or misalignments.

## 6. Non-Functional Requirements
Cover: Performance, Security, Scalability, Usability, Availability.
Use table: | NFR | Requirement | Status (✅/⚠️/❌) |

## 7. QA Recommendations
Prioritized list with 🔴/🟠/🟡/🟢 priority labels.

Be critical. Challenge every assumption. Think like a production system QA."""

CONSOLIDATION_PROMPT = """You are a Technical Documentation Lead.
Consolidate the outputs from the Architect, Business Analyst, and QA agents into ONE professional document.

Output the following sections using Markdown headers (##):

## Executive Summary
2-3 paragraphs: what the system is, key strengths, critical issues.

## System Overview
Key stats table: | Attribute | Value |

## Architecture Highlights
Top 5 architectural decisions and their rationale.

## Critical Risks (Action Required)
Only 🔴 Critical and 🟠 High risks. Table format with owner column.

## Key User Stories
The 5 most important user stories with acceptance criteria.

## Top 10 Recommendations
Numbered, prioritized, with expected impact.

## Conclusion
One paragraph summarizing the system's maturity and readiness.

Write in professional stakeholder-ready language. Be concise but complete."""


# ── Pipeline ──────────────────────────────────────────────────────────────── #

class AnalysisPipeline:
    """Runs the 4-agent analysis pipeline sequentially."""

    AGENTS = [
        ("architect",     "🏗️  Architect",    ARCHITECT_PROMPT),
        ("ba",            "💼  BA",           BA_PROMPT),
        ("qa",            "🧪  QA",           QA_PROMPT),
        ("consolidation", "📄  Consolidation", CONSOLIDATION_PROMPT),
    ]

    def __init__(
        self,
        client: AIClient,
        models: Dict[str, str],          # {"architect": "llama3", ...}
        context: str,                    # scanner output
        on_token: Callable[[str], None],
        on_stage: Callable[[str], None],
        on_done:  Callable[[Dict], None],
        stop_flag: Optional[list] = None, # [False] — set [True] to abort
    ):
        self.client     = client
        self.models     = models
        self.context    = context
        self.on_token   = on_token
        self.on_stage   = on_stage
        self.on_done    = on_done
        self.stop_flag  = stop_flag or [False]

    def run(self, enabled_agents: Dict[str, bool]) -> Dict[str, str]:
        results: Dict[str, str] = {}
        prior_outputs = ""

        for key, label, system_prompt in self.AGENTS:
            if not enabled_agents.get(key, True):
                continue
            if self.stop_flag[0]:
                break

            self.on_stage(label)
            model = self.models.get(key, list(self.models.values())[0])

            prior_section = ("## PRIOR AGENT OUTPUTS\n" + prior_outputs) if prior_outputs else ""
            user_content = "## PROJECT METADATA\n" + self.context + "\n\n" + prior_section
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": user_content},
            ]

            try:
                output = self.client.chat(
                    model=model,
                    messages=messages,
                    on_token=self.on_token,
                    temperature=0.4,
                )
                results[key] = output
                prior_outputs += f"\n\n### {label} Output\n{output}"
            except Exception as e:
                results[key] = f"**Error running {label} agent:** {e}"
                self.on_token(f"\n\n[ERROR] {label}: {e}\n")

        self.on_done(results)
        return results
