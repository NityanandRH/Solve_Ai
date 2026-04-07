"""
agents.py — LangGraph state graphs for each InnovateTool tab.
Each graph manages the structured conversation flow for its stage.
"""

import os
import json
from typing import TypedDict, List, Optional, Dict, Any
from openai import AsyncAzureOpenAI
from dotenv import load_dotenv
import prompts

load_dotenv()

SIMPLE_MODEL = os.getenv("SIMPLE_MODEL", "gpt-4o-mini")
ADVANCED_MODEL = os.getenv("ADVANCED_MODEL", "gpt-4o")

# Azure OpenAI client — deployment names must match SIMPLE_MODEL / ADVANCED_MODEL env vars
client = AsyncAzureOpenAI(
    api_key=os.getenv("AZURE_OPENAI_API_KEY"),
    api_version="2024-02-01",
    azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT", ""),
)


# ── State Types ───────────────────────────────────────────────────────────────

class IdeateState(TypedDict):
    session_id: str
    user_id: str
    method: str                      # 'psc' | 'design_thinking' | 'jtbd'
    initial_context: str
    questions: List[Dict]            # [{id, question, field, hint, answer, suggestion}]
    current_index: int
    summary: Optional[str]
    completed: bool


class AnalyzeState(TypedDict):
    session_id: str
    user_id: str
    method: str                      # '5why' | 'swot' | 'fishbone'
    ideate_summary: str
    questions: List[Dict]            # method-specific Q&A list
    chat_history: List[Dict]         # [{role, content}]
    current_index: int
    analysis_data: Dict              # structured data per method
    summary: Optional[str]
    completed: bool


class SolveState(TypedDict):
    session_id: str
    user_id: str
    full_context: str
    chat_history: List[Dict]
    initialized: bool
    completed: bool


class TRIZState(TypedDict):
    session_id: str
    user_id: str
    full_context: str
    level: int
    tool: str
    chat_history: List[Dict]
    analysis_result: Optional[str]
    completed: bool


class PatentState(TypedDict):
    session_id: str
    user_id: str
    full_context: str
    claims: Optional[str]
    prior_art_analysis: Optional[str]
    circumvention_analysis: Optional[str]
    draft_document: Optional[str]
    chat_history: List[Dict]
    completed: bool


# ── Ideate Agent ──────────────────────────────────────────────────────────────

async def ideate_get_suggestion(state: IdeateState) -> str:
    """Generate LLM hint/suggestion for the current question."""
    idx = state["current_index"]
    if idx >= len(state["questions"]):
        return ""

    current_q = state["questions"][idx]
    previous_qa = [
        {"question": q["question"], "answer": q.get("answer", "")}
        for q in state["questions"][:idx]
        if q.get("answer")
    ]

    prompt = prompts.ideate_suggestion(
        initial_context=state["initial_context"],
        method=state["method"],
        question=current_q["question"],
        previous_qa=previous_qa
    )

    response = await client.chat.completions.create(
        model=SIMPLE_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.6,
        max_tokens=150
    )
    return response.choices[0].message.content


async def ideate_submit_answer(state: IdeateState, answer: str) -> IdeateState:
    """Record an answer and advance the question index."""
    idx = state["current_index"]
    if idx < len(state["questions"]):
        state["questions"][idx]["answer"] = answer

    next_idx = idx + 1
    state["current_index"] = next_idx
    state["completed"] = next_idx >= len(state["questions"])
    return state


async def ideate_generate_summary(state: IdeateState) -> str:
    """Generate a structured summary of the ideate stage."""
    qa_pairs = [q for q in state["questions"] if q.get("answer")]
    prompt = prompts.ideate_summary(
        method=state["method"],
        initial_context=state["initial_context"],
        qa_pairs=qa_pairs
    )
    response = await client.chat.completions.create(
        model=SIMPLE_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.5,
        max_tokens=800
    )
    return response.choices[0].message.content


async def ideate_modify_answer(state: IdeateState, question_index: int,
                                new_answer: str) -> IdeateState:
    """Modify a specific question answer without restarting."""
    if 0 <= question_index < len(state["questions"]):
        state["questions"][question_index]["answer"] = new_answer
        # Regenerate suggestion for next unanswered question
        state["summary"] = None  # Invalidate summary
    return state


# ── Analyze Agent ─────────────────────────────────────────────────────────────

def get_analyze_questions(method: str) -> List[Dict]:
    """Return the structured question list for the chosen analysis method."""
    if method == "5why":
        return [
            {"id": i+1, "question": f"Why did this happen? (Why #{i+1})",
             "field": f"why_{i+1}", "answer": None, "suggestion": None}
            for i in range(5)
        ]
    elif method == "swot":
        return [
            {"id": 1, "question": "What are the key Strengths of your current approach or position?",
             "field": "strengths", "answer": None, "suggestion": None},
            {"id": 2, "question": "What are the main Weaknesses or internal limitations?",
             "field": "weaknesses", "answer": None, "suggestion": None},
            {"id": 3, "question": "What external Opportunities could be leveraged?",
             "field": "opportunities", "answer": None, "suggestion": None},
            {"id": 4, "question": "What external Threats or risks must be considered?",
             "field": "threats", "answer": None, "suggestion": None},
        ]
    elif method == "fishbone":
        return [
            {"id": 1, "question": "People: What human factors (skills, behaviour, training) contribute to this problem?",
             "field": "people", "answer": None, "suggestion": None},
            {"id": 2, "question": "Process: What process or procedure gaps cause or worsen this problem?",
             "field": "process", "answer": None, "suggestion": None},
            {"id": 3, "question": "Materials: What material or component issues contribute?",
             "field": "materials", "answer": None, "suggestion": None},
            {"id": 4, "question": "Machines/Equipment: What equipment or technology failures contribute?",
             "field": "machines", "answer": None, "suggestion": None},
            {"id": 5, "question": "Environment: What environmental factors (physical, economic, regulatory) play a role?",
             "field": "environment", "answer": None, "suggestion": None},
            {"id": 6, "question": "Methods/Management: What management decisions or methods are contributing causes?",
             "field": "methods", "answer": None, "suggestion": None},
        ]
    return []


async def analyze_get_suggestion(state: AnalyzeState) -> str:
    """Generate context-aware hint for current analysis question."""
    idx = state["current_index"]
    if idx >= len(state["questions"]):
        return ""

    method = state["method"]
    current_q = state["questions"][idx]
    previous = {
        q["field"]: q.get("answer", "")
        for q in state["questions"][:idx]
        if q.get("answer")
    }

    if method == "5why":
        why_chain = [
            {"question": q["question"], "answer": q.get("answer", "")}
            for q in state["questions"][:idx] if q.get("answer")
        ]
        prompt = prompts.analyze_five_why_suggestion(
            state["ideate_summary"], why_chain, idx + 1
        )
    elif method == "swot":
        prompt = prompts.analyze_swot_suggestion(
            state["ideate_summary"], current_q["field"].upper(), previous
        )
    elif method == "fishbone":
        prompt = prompts.analyze_fishbone_suggestion(
            state["ideate_summary"], current_q["field"].title(), previous
        )
    else:
        return ""

    response = await client.chat.completions.create(
        model=SIMPLE_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.6,
        max_tokens=150
    )
    return response.choices[0].message.content


async def analyze_submit_answer(state: AnalyzeState, answer: str) -> AnalyzeState:
    idx = state["current_index"]
    if idx < len(state["questions"]):
        state["questions"][idx]["answer"] = answer
        field = state["questions"][idx]["field"]
        state["analysis_data"][field] = answer

    next_idx = idx + 1
    state["current_index"] = next_idx
    state["completed"] = next_idx >= len(state["questions"])
    return state


async def analyze_generate_summary(state: AnalyzeState) -> str:
    prompt = prompts.analyze_summary(
        method=state["method"],
        ideate_summary=state["ideate_summary"],
        analyze_data=state["analysis_data"]
    )
    response = await client.chat.completions.create(
        model=SIMPLE_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.5,
        max_tokens=800
    )
    return response.choices[0].message.content


# ── Solve Agent ───────────────────────────────────────────────────────────────

async def solve_initialize(state: SolveState) -> str:
    """Generate the initial solve response based on full context."""
    system = prompts.solve_system(state["full_context"])
    initial_prompt = prompts.solve_initial_prompt(state["full_context"])

    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": initial_prompt}
    ]

    response = await client.chat.completions.create(
        model=ADVANCED_MODEL,
        messages=messages,
        temperature=0.7,
        stream=True
    )
    return response  # Return stream for streaming response


async def solve_chat(state: SolveState, user_message: str):
    """Continue the solve conversation."""
    system = prompts.solve_system(state["full_context"])
    messages = [{"role": "system", "content": system}]

    # Add history
    for msg in state["chat_history"]:
        messages.append({"role": msg["role"], "content": msg["content"]})

    messages.append({"role": "user", "content": user_message})

    response = await client.chat.completions.create(
        model=ADVANCED_MODEL,
        messages=messages,
        temperature=0.7,
        stream=True
    )
    return response


# ── TRIZ Agent ────────────────────────────────────────────────────────────────

async def triz_analyze(full_context: str, level: int, tool: str,
                        extra_params: Dict = None):
    """Run TRIZ analysis for the chosen level and tool. Returns a stream."""
    extra_params = extra_params or {}

    prompt_map = {
        "function_analysis": lambda: prompts.triz_function_analysis(
            full_context, str(extra_params)),
        "ceca": lambda: prompts.triz_ceca(full_context),
        "trimming": lambda: prompts.triz_trimming(full_context),
        "resources": lambda: prompts.triz_resources(full_context),
        "nine_windows": lambda: prompts.triz_nine_windows(full_context),
        "contradiction_matrix": lambda: prompts.triz_contradiction_matrix(
            full_context,
            extra_params.get("improving_param", ""),
            extra_params.get("worsening_param", ""),
            extra_params
        ),
        "inventive_principles": lambda: prompts.triz_inventive_principles(
            full_context, extra_params.get("principles", [])
        ),
        "physical_contradiction": lambda: prompts.triz_physical_contradiction(full_context),
        "su_field": lambda: prompts.triz_su_field(full_context),
        "standard_solutions": lambda: prompts.triz_standard_solutions(full_context),
        "scientific_effects": lambda: prompts.triz_scientific_effects(full_context),
        "advanced_trimming": lambda: prompts.triz_advanced_trimming(full_context),
    }

    prompt_fn = prompt_map.get(tool)
    if not prompt_fn:
        raise ValueError(f"Unknown TRIZ tool: {tool}")

    prompt = prompt_fn()
    response = await client.chat.completions.create(
        model=ADVANCED_MODEL,
        messages=[
            {"role": "system", "content": prompts.system_base()},
            {"role": "user", "content": prompt}
        ],
        temperature=0.6,
        stream=True
    )
    return response


async def triz_chat(state: TRIZState, user_message: str):
    """Follow-up chat after TRIZ analysis."""
    system = (
        f"{prompts.system_base()}\n\n"
        f"CONTEXT: {state['full_context']}\n\n"
        f"TRIZ ANALYSIS (Level {state['level']}, Tool: {state['tool']}):\n"
        f"{state.get('analysis_result', 'See conversation history')}"
    )
    messages = [{"role": "system", "content": system}]
    for msg in state["chat_history"]:
        messages.append({"role": msg["role"], "content": msg["content"]})
    messages.append({"role": "user", "content": user_message})

    response = await client.chat.completions.create(
        model=ADVANCED_MODEL,
        messages=messages,
        temperature=0.7,
        stream=True
    )
    return response


# ── Patent Agent ──────────────────────────────────────────────────────────────

async def patent_generate_claims(full_context: str):
    """Generate patent claims. Returns a stream."""
    prompt = prompts.patent_generate_claims(full_context)
    response = await client.chat.completions.create(
        model=ADVANCED_MODEL,
        messages=[
            {"role": "system", "content": prompts.system_base()},
            {"role": "user", "content": prompt}
        ],
        temperature=0.4,
        stream=True
    )
    return response


async def patent_analyze_prior_art(full_context: str, claims: str):
    prompt = prompts.patent_analyze_prior_art(full_context, claims)
    response = await client.chat.completions.create(
        model=ADVANCED_MODEL,
        messages=[
            {"role": "system", "content": prompts.system_base()},
            {"role": "user", "content": prompt}
        ],
        temperature=0.4,
        stream=True
    )
    return response


async def patent_circumvent(full_context: str, claims: str):
    prompt = prompts.patent_circumvent(full_context, claims)
    response = await client.chat.completions.create(
        model=ADVANCED_MODEL,
        messages=[
            {"role": "system", "content": prompts.system_base()},
            {"role": "user", "content": prompt}
        ],
        temperature=0.5,
        stream=True
    )
    return response


async def patent_search_strings(full_context: str, claims: str):
    prompt = prompts.patent_generate_search_strings(full_context, claims)
    response = await client.chat.completions.create(
        model=ADVANCED_MODEL,
        messages=[
            {"role": "system", "content": prompts.system_base()},
            {"role": "user", "content": prompt}
        ],
        temperature=0.3,
        stream=True
    )
    return response


async def patent_draft_document(full_context: str, claims: str, analysis: str):
    prompt = prompts.patent_draft_document(full_context, claims, analysis)
    response = await client.chat.completions.create(
        model=ADVANCED_MODEL,
        messages=[
            {"role": "system", "content": prompts.system_base()},
            {"role": "user", "content": prompt}
        ],
        temperature=0.3,
        stream=True
    )
    return response


# ── Admin Agent ───────────────────────────────────────────────────────────────

async def admin_chat(telemetry_summary: str, question: str,
                      chat_history: List[Dict]):
    system_content = (
        "You are an analytics assistant for InnovateTool administrators.\n\n"
        "You have access to the following live telemetry data about all users. "
        "Answer questions using ONLY this data. Be specific: use exact usernames, "
        "numbers, and stage names from the data. Never say you lack information if "
        "it is present below.\n\n"
        f"{telemetry_summary}"
    )
    messages = [{"role": "system", "content": system_content}]
    for msg in chat_history[-10:]:
        messages.append({"role": msg["role"], "content": msg["content"]})
    messages.append({"role": "user", "content": question})

    response = await client.chat.completions.create(
        model=SIMPLE_MODEL,
        messages=messages,
        temperature=0.4,
        stream=True
    )
    return response
