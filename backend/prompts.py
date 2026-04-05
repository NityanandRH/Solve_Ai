"""
prompts.py — All LLM prompt templates for InnovateTool.
Each function returns a fully-formed system or user prompt string.
"""


# ── Context / General ────────────────────────────────────────────────────────

def system_base() -> str:
    return (
        "You are InnovateTool AI, an expert innovation and problem-solving assistant. "
        "You help engineers, designers, and entrepreneurs turn raw ideas into structured, "
        "patentable innovations using proven frameworks. Be precise, insightful, and "
        "context-aware. Never hallucinate technical facts."
    )


# ── Ideate Tab ───────────────────────────────────────────────────────────────

def ideate_suggestion(initial_context: str, method: str, question: str,
                       previous_qa: list) -> str:
    qa_str = "\n".join(
        [f"Q{i+1}: {qa['question']}\nA{i+1}: {qa['answer']}" for i, qa in enumerate(previous_qa)]
    ) if previous_qa else "None yet."
    return (
        f"You are assisting with a structured innovation interview using the {method} framework.\n\n"
        f"INITIAL CONTEXT (user's idea/problem):\n{initial_context}\n\n"
        f"PREVIOUS Q&A:\n{qa_str}\n\n"
        f"CURRENT QUESTION BEING ASKED:\n{question}\n\n"
        f"Generate a brief, context-specific hint for this question. "
        f"Include 2-3 concrete examples relevant to the user's context, "
        f"separated by ' | '. Keep the entire hint under 60 words. "
        f"Format: one sentence of guidance, then 'e.g.: example1 | example2 | example3'"
    )


def ideate_summary(method: str, initial_context: str, qa_pairs: list) -> str:
    qa_str = "\n".join(
        [f"Q{i+1} ({qa['field']}): {qa['question']}\nAnswer: {qa['answer']}"
         for i, qa in enumerate(qa_pairs)]
    )
    return (
        f"Based on the following {method} framework interview, produce a structured summary.\n\n"
        f"INITIAL CONTEXT: {initial_context}\n\n"
        f"INTERVIEW Q&A:\n{qa_str}\n\n"
        f"Create a clear, professional summary with these sections:\n"
        f"1. **Problem Statement** (1-2 sentences)\n"
        f"2. **Target User** (who, when, where)\n"
        f"3. **Root Cause** (core issue)\n"
        f"4. **Impact** (consequence of the problem)\n"
        f"5. **Existing Solutions & Gaps** (what's tried and why it fails)\n"
        f"6. **Constraints** (limitations the solution must respect)\n"
        f"7. **Success Criteria** (measurable definition of done)\n\n"
        f"Be concise and precise. Use bullet points within sections."
    )


# ── Analyze Tab ──────────────────────────────────────────────────────────────

def analyze_five_why_suggestion(ideate_summary: str, why_chain: list,
                                  question_num: int) -> str:
    chain_str = "\n".join(
        [f"Why #{i+1}: {w['question']}\nBecause: {w['answer']}"
         for i, w in enumerate(why_chain)]
    ) if why_chain else "Starting the analysis."
    return (
        f"You are facilitating a 5-Why root cause analysis.\n\n"
        f"PROBLEM CONTEXT (from Ideate stage):\n{ideate_summary}\n\n"
        f"WHY CHAIN SO FAR:\n{chain_str}\n\n"
        f"Generate a hint for Why #{question_num} that:\n"
        f"- Builds logically on the previous answer\n"
        f"- Drills deeper toward the true root cause\n"
        f"- Provides 2-3 examples of what the answer might look like\n"
        f"Keep under 60 words. Format: guidance sentence + 'e.g.: ex1 | ex2 | ex3'"
    )


def analyze_swot_suggestion(ideate_summary: str, category: str,
                              previous_swot: dict) -> str:
    prev_str = "\n".join([f"{k}: {v}" for k, v in previous_swot.items()]) if previous_swot else "None yet."
    return (
        f"You are facilitating a SWOT analysis.\n\n"
        f"PROBLEM CONTEXT:\n{ideate_summary}\n\n"
        f"SWOT COMPLETED SO FAR:\n{prev_str}\n\n"
        f"Generate a hint for the '{category}' quadrant that:\n"
        f"- Is specific to the user's problem domain\n"
        f"- Helps them think about factors they might miss\n"
        f"- Provides 2-3 domain-relevant examples\n"
        f"Keep under 60 words. Format: guidance + 'e.g.: ex1 | ex2 | ex3'"
    )


def analyze_fishbone_suggestion(ideate_summary: str, category: str,
                                  category_answers: dict) -> str:
    prev_str = "\n".join([f"{k}: {v}" for k, v in category_answers.items()]) if category_answers else "None yet."
    return (
        f"You are facilitating a Fishbone (Ishikawa) Diagram analysis.\n\n"
        f"PROBLEM CONTEXT:\n{ideate_summary}\n\n"
        f"CATEGORIES ANALYSED SO FAR:\n{prev_str}\n\n"
        f"Generate a hint for the '{category}' cause category that:\n"
        f"- Identifies potential causes in this specific category\n"
        f"- Is relevant to the user's problem domain\n"
        f"- Provides 2-3 specific examples\n"
        f"Keep under 60 words. Format: guidance + 'e.g.: ex1 | ex2 | ex3'"
    )


def analyze_summary(method: str, ideate_summary: str, analyze_data: dict) -> str:
    data_str = str(analyze_data)
    return (
        f"Produce a structured summary of the {method} analysis.\n\n"
        f"PROBLEM CONTEXT (from Ideate):\n{ideate_summary}\n\n"
        f"ANALYSIS DATA:\n{data_str}\n\n"
        f"Create a professional summary that:\n"
        f"1. States the analysis method used\n"
        f"2. Presents key findings per category/step\n"
        f"3. Highlights the most critical insight or root cause discovered\n"
        f"4. Suggests 2-3 directions for the Solve phase\n"
        f"Use headers and bullet points. Be concise and actionable."
    )


# ── Solve Tab ────────────────────────────────────────────────────────────────

def solve_system(full_context: str) -> str:
    return (
        f"You are an expert innovation consultant with deep cross-domain knowledge.\n\n"
        f"FULL PROBLEM CONTEXT:\n{full_context}\n\n"
        f"INSTRUCTIONS:\n"
        f"- Answer the user's question with comprehensive, domain-expert insight\n"
        f"- For any solution request: list ALL viable solutions with their advantages AND disadvantages\n"
        f"- Cite analogous solutions from other industries where relevant\n"
        f"- Always end your response with ONE focused follow-up question to refine the solution\n"
        f"- Format clearly with headers, bullets, and bold text for key points\n"
        f"- Be direct, technical, and specific — avoid vague generalities"
    )


def solve_initial_prompt(full_context: str) -> str:
    return (
        f"The user has completed problem definition and analysis. Here is their full context:\n\n"
        f"{full_context}\n\n"
        f"Begin by: (1) acknowledging the problem clearly in 2 sentences, "
        f"(2) presenting the 3-5 most promising solution directions with pros/cons, "
        f"(3) asking which direction they want to explore deeper."
    )


# ── TRIZ Tab ─────────────────────────────────────────────────────────────────

def triz_function_analysis(full_context: str, principles: str) -> str:
    return (
        f"Apply Function Analysis (TRIZ Level 1) to the following problem.\n\n"
        f"CONTEXT:\n{full_context}\n\n"
        f"INSTRUCTIONS:\n"
        f"1. **Component Identification**: List all key system components\n"
        f"2. **Function Mapping**: For each component, identify its useful and harmful functions\n"
        f"3. **Interaction Matrix**: Map how components interact (useful/harmful/missing)\n"
        f"4. **Trimming Candidates**: Identify components that could be trimmed (removed/merged)\n"
        f"5. **Priority Improvements**: Rank top 3 function improvements with justification\n\n"
        f"Use structured tables or lists. Be specific and technical."
    )


def triz_ceca(full_context: str) -> str:
    return (
        f"Apply Cause-Effect Chain Analysis (CECA) to the following problem.\n\n"
        f"CONTEXT:\n{full_context}\n\n"
        f"INSTRUCTIONS:\n"
        f"1. **Undesired Effect (UE)**: State the primary undesired effect clearly\n"
        f"2. **Immediate Causes**: What directly causes the UE?\n"
        f"3. **Causal Chain**: Trace 3-4 levels deep for each immediate cause\n"
        f"4. **Key Contradictions**: Identify any engineering or physical contradictions in the chain\n"
        f"5. **Actionable Causes**: Highlight which causes are most feasible to address\n"
        f"6. **Recommended Direction**: Which node in the chain should be the innovation target?\n\n"
        f"Use a tree-like structure with arrows or indentation to show the chain."
    )


def triz_trimming(full_context: str) -> str:
    return (
        f"Apply Trimming Analysis (TRIZ Level 1) to the following problem.\n\n"
        f"CONTEXT:\n{full_context}\n\n"
        f"INSTRUCTIONS:\n"
        f"1. **System Model**: List all components and their primary functions\n"
        f"2. **Trimming Candidates**: Identify 3+ components that could potentially be removed\n"
        f"3. **Trimming Rules**: For each candidate, apply trimming rules:\n"
        f"   - Rule A: Component and its function can be eliminated\n"
        f"   - Rule B: Function transferred to another existing component\n"
        f"   - Rule C: Component eliminated if the object no longer needs the function\n"
        f"4. **Resulting Concept**: Describe the trimmed system\n"
        f"5. **Innovation Potential**: Rate the trimmed concept's feasibility and novelty\n\n"
        f"Be specific and propose concrete design changes."
    )


def triz_resources(full_context: str) -> str:
    return (
        f"Apply Resource Identification (TRIZ Level 1) to the following problem.\n\n"
        f"CONTEXT:\n{full_context}\n\n"
        f"INSTRUCTIONS:\n"
        f"1. **Substance Resources**: Identify available materials/substances not being used\n"
        f"2. **Energy Resources**: Identify available energy forms (mechanical, thermal, chemical, etc.)\n"
        f"3. **Space Resources**: Unused spaces, surfaces, or geometries in the system\n"
        f"4. **Time Resources**: Unutilized time periods (before/during/after main function)\n"
        f"5. **Information Resources**: Available signals or data not being exploited\n"
        f"6. **Function Resources**: Functions of existing components that could serve dual purposes\n"
        f"7. **Derived Resources**: What can be derived from combining the above?\n\n"
        f"For each resource found, suggest a specific way to exploit it for the solution."
    )


def triz_nine_windows(full_context: str) -> str:
    return (
        f"Apply the 9 Windows (System Operator) analysis to the following problem.\n\n"
        f"CONTEXT:\n{full_context}\n\n"
        f"Analyse the system across a 3x3 grid:\n"
        f"Columns: PAST | PRESENT | FUTURE\n"
        f"Rows: SUPERSYSTEM (environment) | SYSTEM (the product/solution) | SUBSYSTEM (components)\n\n"
        f"For each cell, describe the state, changes, or opportunities. Then:\n"
        f"1. **Key Trends**: What trends are shaping the system over time?\n"
        f"2. **Super-system Opportunities**: How can the environment be leveraged?\n"
        f"3. **Sub-system Innovations**: What component-level changes create system-level improvement?\n"
        f"4. **Ideal Final Result**: What does the future ideal system look like?\n\n"
        f"Format as a 3x3 table followed by insights."
    )


def triz_contradiction_matrix(full_context: str, improving_param: str,
                               worsening_param: str, principles_data: dict) -> str:
    return (
        f"Apply the TRIZ Contradiction Matrix (Level 2) to the following problem.\n\n"
        f"CONTEXT:\n{full_context}\n\n"
        f"IDENTIFIED CONTRADICTION:\n"
        f"- Improving Parameter: {improving_param}\n"
        f"- Worsening Parameter: {worsening_param}\n\n"
        f"RECOMMENDED INVENTIVE PRINCIPLES (from matrix):\n{str(principles_data)}\n\n"
        f"INSTRUCTIONS:\n"
        f"1. **Contradiction Statement**: Clearly state the engineering contradiction\n"
        f"2. **Principle Application**: For each recommended principle, show how it applies to THIS specific problem\n"
        f"3. **Concept Generation**: Propose 2-3 concrete solution concepts using the principles\n"
        f"4. **Feasibility Assessment**: Rate each concept (High/Medium/Low) with justification\n"
        f"5. **Recommended Direction**: Which concept is most promising and why?"
    )


def triz_physical_contradiction(full_context: str) -> str:
    return (
        f"Identify and resolve Physical Contradictions (TRIZ Level 2) in the following problem.\n\n"
        f"CONTEXT:\n{full_context}\n\n"
        f"INSTRUCTIONS:\n"
        f"1. **Physical Contradiction**: State it as '[Parameter] must be X AND [Parameter] must be NOT-X'\n"
        f"2. **Separation in Time**: Can the parameter be X at one time and NOT-X at another?\n"
        f"3. **Separation in Space**: Can different parts be X while the system is NOT-X?\n"
        f"4. **Separation by Condition**: Can it be X under condition A and NOT-X under condition B?\n"
        f"5. **Separation between Parts and Whole**: Can parts be X while the whole is NOT-X?\n"
        f"6. **Best Separation Strategy**: Which approach yields the best solution concept?\n"
        f"7. **Concrete Concept**: Describe the resulting innovative design in detail."
    )


def triz_su_field(full_context: str) -> str:
    return (
        f"Apply Substance-Field (Su-Field) Analysis (TRIZ Level 3) to the following problem.\n\n"
        f"CONTEXT:\n{full_context}\n\n"
        f"INSTRUCTIONS:\n"
        f"1. **System Model**: Identify S1 (object), S2 (tool), and F (field/interaction)\n"
        f"2. **Problem Classification**: Is the model Incomplete, Harmful, or Ineffective?\n"
        f"3. **Standard Solution Class**: Map to one of the 5 classes:\n"
        f"   - Class 1: Improving an insufficient or harmful system\n"
        f"   - Class 2: Improving measurement/detection\n"
        f"   - Class 3: Transition to supersystem\n"
        f"   - Class 4: Detection and measurement standards\n"
        f"   - Class 5: Introduction of substances and fields\n"
        f"4. **Specific Standard Solution**: Identify the applicable standard solution (1-76)\n"
        f"5. **Modified Model**: Draw the improved Su-Field model (text representation)\n"
        f"6. **Physical Concept**: What physical principle enables this solution?\n"
        f"7. **Implementation Path**: How would this be built in practice?"
    )


def triz_scientific_effects(full_context: str) -> str:
    return (
        f"Apply the Scientific Effects approach (TRIZ Level 3) to the following problem.\n\n"
        f"CONTEXT:\n{full_context}\n\n"
        f"INSTRUCTIONS:\n"
        f"1. **Function Required**: State the technical function needed in precise scientific terms\n"
        f"2. **Physics Effects**: List physical effects/phenomena that could perform this function\n"
        f"3. **Chemistry Effects**: List chemical effects or reactions applicable\n"
        f"4. **Geometry Effects**: List geometric or structural configurations that help\n"
        f"5. **Cross-domain Analogies**: How do other fields (biology, aerospace, etc.) solve this?\n"
        f"6. **Effect Combination**: Propose a solution combining 2+ scientific effects\n"
        f"7. **Patentability Check**: Is this combination novel? What makes it inventive?"
    )


def triz_inventive_principles(full_context: str, selected_principles: list) -> str:
    principles_str = ", ".join([f"Principle {p}" for p in selected_principles])
    return (
        f"Apply the following TRIZ Inventive Principles to solve the problem.\n\n"
        f"CONTEXT:\n{full_context}\n\n"
        f"PRINCIPLES TO APPLY: {principles_str}\n\n"
        f"For each principle:\n"
        f"1. State the principle name and core idea\n"
        f"2. Show exactly how it applies to THIS problem\n"
        f"3. Propose a concrete solution concept\n"
        f"4. Rate feasibility (1-5) and novelty (1-5)\n\n"
        f"Then recommend the top 2 solution concepts for further development."
    )


def triz_standard_solutions(full_context: str) -> str:
    return (
        f"Apply the 76 Standard Solutions framework (TRIZ Level 3) to the following problem.\n\n"
        f"CONTEXT:\n{full_context}\n\n"
        f"INSTRUCTIONS:\n"
        f"1. **Diagnose**: Classify the problem type using Su-Field language\n"
        f"2. **Class 1 Solutions**: Apply any relevant 'Build or improve Su-Field' standards\n"
        f"3. **Class 2 Solutions**: Apply 'Eliminate or neutralize harm' standards if relevant\n"
        f"4. **Class 3 Solutions**: Apply 'System transitions' standards\n"
        f"5. **Top 3 Standards**: Identify the 3 most applicable standard solutions with numbers\n"
        f"6. **Concept Synthesis**: Combine the best standards into one solution concept\n"
        f"7. **Next Steps**: What experiments or prototypes would validate this concept?"
    )


def triz_advanced_trimming(full_context: str) -> str:
    return (
        f"Apply Advanced Trimming and Functional Modeling (TRIZ Level 3) to the following problem.\n\n"
        f"CONTEXT:\n{full_context}\n\n"
        f"INSTRUCTIONS:\n"
        f"1. **Complete Functional Model**: Map ALL components, functions (useful/harmful/neutral)\n"
        f"2. **Trimming Target Selection**: Apply all trimming rules to identify candidates\n"
        f"3. **Function Redistribution**: For each trimmed component, show where its function moves\n"
        f"4. **Contradictions Surfaced**: What new contradictions arise from trimming?\n"
        f"5. **Resolve Contradictions**: Apply appropriate Level 2/3 tools to resolve them\n"
        f"6. **Ideal Final Result**: State the IFR — the system that performs all functions itself\n"
        f"7. **Architectural Redesign**: Describe the fundamentally redesigned system concept"
    )


# ── Patent Tab ───────────────────────────────────────────────────────────────

def patent_generate_claims(full_context: str) -> str:
    return (
        f"You are a patent attorney and innovation expert. Generate a structured patent claim set.\n\n"
        f"INNOVATION CONTEXT:\n{full_context}\n\n"
        f"Generate:\n"
        f"1. **Independent Claim 1** (broadest claim — method or apparatus)\n"
        f"2. **Independent Claim 2** (alternative form — system or composition if applicable)\n"
        f"3. **Dependent Claims 3-8** (narrowing specific embodiments)\n"
        f"4. **Abstract** (150-250 words, neutral technical summary)\n\n"
        f"Format each claim as:\n"
        f"'Claim N: [claim text in proper patent language, one per line for steps]'\n\n"
        f"Use proper patent language: 'comprising', 'wherein', 'configured to', 'the method of claim 1, further comprising'.\n"
        f"Make claims as broad as defensible based on the described innovation."
    )


def patent_analyze_prior_art(full_context: str, claims: str) -> str:
    return (
        f"Perform a prior art landscape analysis for the following invention.\n\n"
        f"INVENTION CONTEXT:\n{full_context}\n\n"
        f"DRAFT CLAIMS:\n{claims}\n\n"
        f"Provide:\n"
        f"1. **Technology Domain**: What field does this invention belong to?\n"
        f"2. **Key Technical Features**: What are the novel technical elements?\n"
        f"3. **Likely Prior Art**: Describe categories of existing patents/publications that may overlap\n"
        f"4. **Distinguishing Features**: What makes this invention different from the prior art?\n"
        f"5. **Patentability Assessment**: Novelty (Y/N), Non-obviousness (Y/N/Questionable), Utility (Y/N)\n"
        f"6. **Strengthening Recommendations**: How to make claims stronger and less vulnerable?\n"
        f"7. **Risk Areas**: Which claims are most vulnerable to prior art challenges?"
    )


def patent_circumvent(full_context: str, claims: str) -> str:
    return (
        f"As a patent strategy expert, identify ways to design around the following patent claims.\n\n"
        f"INVENTION CONTEXT:\n{full_context}\n\n"
        f"CLAIMS TO CIRCUMVENT:\n{claims}\n\n"
        f"Provide:\n"
        f"1. **Claim Weakness Analysis**: Identify specific limitations in each claim\n"
        f"2. **Design-Around Strategies** (for each main claim):\n"
        f"   - Alternative A: [description of circumventing approach]\n"
        f"   - Alternative B: [description of circumventing approach]\n"
        f"3. **Freedom to Operate**: What implementations are clearly outside the claim scope?\n"
        f"4. **Dependency Map**: Which dependent claims can be bypassed independently?\n"
        f"5. **Strengthening Advice**: How should claims be rewritten to close these gaps?\n"
        f"6. **Competitive Landscape**: What patent filing strategy would protect the most ground?"
    )


def patent_generate_search_strings(full_context: str, claims: str) -> str:
    return (
        f"You are a patent search expert. Generate optimised search strings for the following invention "
        f"that can be copy-pasted directly into major patent databases.\n\n"
        f"INVENTION CONTEXT:\n{full_context}\n\n"
        f"PATENT CLAIMS (if available):\n{claims or 'Not yet generated'}\n\n"
        f"Generate search strings for each of the following databases. "
        f"Use the correct syntax for each platform:\n\n"
        f"## 1. Google Patents (https://patents.google.com)\n"
        f"- Use natural language + Boolean (AND, OR, NOT)\n"
        f"- Provide 2 search strings: one broad, one narrow\n\n"
        f"## 2. Espacenet (https://worldwide.espacenet.com)\n"
        f"- Use CPC classification codes where applicable\n"
        f"- Use field codes: ti= (title), ab= (abstract), ct= (claims), ta= (title+abstract)\n"
        f"- Provide 2 search strings\n\n"
        f"## 3. USPTO Patent Full-Text (https://ppubs.uspto.gov)\n"
        f"- Use USPTO query syntax with field tags: TTL/ ABST/ ACLM/ SPEC/\n"
        f"- Include CPC/USPC class suggestions\n"
        f"- Provide 2 search strings\n\n"
        f"## 4. Orbit Intelligence / Questel\n"
        f"- Use IPC/CPC codes + keyword Boolean logic\n"
        f"- Include suggested IPC codes relevant to this invention\n"
        f"- Provide 1-2 search strings\n\n"
        f"## 5. Derwent Innovation (Clarivate)\n"
        f"- Use Derwent Manual Codes where applicable\n"
        f"- Use TS= (topic search), TI= (title), AB= (abstract) field tags\n"
        f"- Provide 1-2 search strings\n\n"
        f"## 6. Key IPC / CPC Classification Codes\n"
        f"- List the 3-5 most relevant IPC and CPC classification codes for this invention\n"
        f"- Briefly explain what each code covers\n\n"
        f"## 7. Recommended Search Strategy\n"
        f"- Suggest the order in which to use these databases\n"
        f"- Note which databases are best for this technology domain\n"
        f"- Mention any free vs. paid access considerations\n\n"
        f"Format each search string in a code block for easy copying. "
        f"Make strings specific enough to find relevant prior art but broad enough not to miss key results."
    )


def patent_draft_document(full_context: str, claims: str, analysis: str) -> str:
    return (
        f"Draft a complete patent application document for the following invention.\n\n"
        f"INVENTION CONTEXT:\n{full_context}\n\n"
        f"CLAIMS:\n{claims}\n\n"
        f"PRIOR ART ANALYSIS:\n{analysis}\n\n"
        f"Generate a full patent application with these sections:\n\n"
        f"# TITLE OF INVENTION\n"
        f"# FIELD OF THE INVENTION\n"
        f"# BACKGROUND OF THE INVENTION (problem being solved, prior art limitations)\n"
        f"# SUMMARY OF THE INVENTION\n"
        f"# BRIEF DESCRIPTION OF DRAWINGS (describe 3-5 figures conceptually)\n"
        f"# DETAILED DESCRIPTION OF PREFERRED EMBODIMENTS\n"
        f"  - First Embodiment\n"
        f"  - Alternative Embodiments\n"
        f"  - Working Examples\n"
        f"# CLAIMS (use the provided claims)\n"
        f"# ABSTRACT\n\n"
        f"Write in formal patent language. Be specific, technical, and thorough. "
        f"The detailed description should be at least 800 words."
    )


# ── Admin Tab ────────────────────────────────────────────────────────────────

def admin_telemetry_chat(telemetry_summary: str, question: str) -> str:
    return (
        f"You are an analytics assistant for InnovateTool administrators.\n\n"
        f"CURRENT TELEMETRY DATA:\n{telemetry_summary}\n\n"
        f"USER QUESTION: {question}\n\n"
        f"Answer the question based strictly on the telemetry data provided. "
        f"If the data doesn't support a definitive answer, say so. "
        f"Provide actionable insights for team management. "
        f"Format your response clearly with numbers and percentages where relevant."
    )


# ── Context Transfer ─────────────────────────────────────────────────────────

def build_full_context(initial_context: str, ideate_summary: str = None,
                        analyze_summary: str = None, solve_highlights: str = None,
                        triz_insights: str = None) -> str:
    parts = [f"INITIAL CONTEXT:\n{initial_context}"]
    if ideate_summary:
        parts.append(f"\nIDEATE STAGE SUMMARY:\n{ideate_summary}")
    if analyze_summary:
        parts.append(f"\nANALYSIS STAGE SUMMARY:\n{analyze_summary}")
    if solve_highlights:
        parts.append(f"\nSOLVE STAGE HIGHLIGHTS:\n{solve_highlights}")
    if triz_insights:
        parts.append(f"\nTRIZ ANALYSIS INSIGHTS:\n{triz_insights}")
    return "\n\n".join(parts)