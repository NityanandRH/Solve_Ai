"""
app.py — FastAPI application: all endpoints for InnovateTool.
Run with: uvicorn app:app --reload
"""

import os
import json
import time
from typing import Optional, Dict, Any
from fastapi import FastAPI, HTTPException, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel
from dotenv import load_dotenv
from openai import AsyncOpenAI

import utils
import agents
import prompts
from User import (
    UserLogin, UserOut, Token, TokenData,
    verify_password, create_access_token, decode_token
)

load_dotenv()

app = FastAPI(title="InnovateTool API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- PATH SETUP ---
# Get the absolute path of the backend folder
BACKEND_DIR = os.path.dirname(__file__)

# Go up one level, then into frontend
FRONTEND_DIR = os.path.join(BACKEND_DIR, "..", "frontend")

# Point directly to the static folder inside frontend
STATIC_DIR = os.path.join(FRONTEND_DIR, "static")

# Point directly to the index.html file
HTML_PATH = os.path.join(FRONTEND_DIR, "index.html")


# --- ROUTING ---
# 1. Mount the static folder. This maps the URL "/static" to your actual static folder on your hard drive.
if os.path.exists(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# 2. Serve the HTML file when someone visits the root URL ("/")
@app.get("/")
async def serve_home():
    return FileResponse(HTML_PATH)

client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))

SIMPLE_MODEL = os.getenv("SIMPLE_MODEL", "gpt-4o-mini")
ADVANCED_MODEL = os.getenv("ADVANCED_MODEL", "gpt-4o")


# ── Startup ───────────────────────────────────────────────────────────────────

@app.on_event("startup")
async def startup():
    utils.init_db()


# ── Frontend ──────────────────────────────────────────────────────────────────

@app.get("/")
async def serve_frontend():
    index_path = os.path.join(FRONTEND_DIR, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {"message": "InnovateTool API running. Place frontend files in ../frontend/"}


# ── Auth helpers ──────────────────────────────────────────────────────────────

async def get_current_user(authorization: str = Header(None)) -> TokenData:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Not authenticated")
    token = authorization.split(" ", 1)[1]
    token_data = decode_token(token)
    if not token_data:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return token_data


async def require_admin(current_user: TokenData = Depends(get_current_user)) -> TokenData:
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return current_user


async def get_session_or_404(session_id: str, current_user: TokenData):
    session = await utils.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if session["user_id"] != current_user.user_id and current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Not your session")
    return session


# ── Streaming helper ──────────────────────────────────────────────────────────

async def stream_openai(response_stream, user_id: str, session_id: str,
                         stage: str, model: str):
    """Convert OpenAI streaming response to SSE format and log tokens."""
    full_content = []
    prompt_tokens = 0
    completion_tokens = 0
    start = time.time()

    try:
        async for chunk in response_stream:
            if chunk.choices and chunk.choices[0].delta.content:
                text = chunk.choices[0].delta.content
                full_content.append(text)
                yield f"data: {json.dumps({'text': text})}\n\n"
            if hasattr(chunk, 'usage') and chunk.usage:
                prompt_tokens = chunk.usage.prompt_tokens or 0
                completion_tokens = chunk.usage.completion_tokens or 0
    except Exception as e:
        yield f"data: {json.dumps({'error': str(e)})}\n\n"
    finally:
        duration_ms = int((time.time() - start) * 1000)
        if prompt_tokens == 0:
            # Estimate if usage not in stream
            total_text = "".join(full_content)
            completion_tokens = len(total_text.split()) * 4 // 3
            prompt_tokens = 500
        await utils.log_token_usage(
            user_id, session_id, stage, model,
            prompt_tokens, completion_tokens, duration_ms
        )
        yield f"data: {json.dumps({'done': True, 'full': ''.join(full_content)})}\n\n"


# ── Auth Routes ───────────────────────────────────────────────────────────────

@app.post("/api/auth/login", response_model=Token)
async def login(credentials: UserLogin):
    user = await utils.get_user_by_username(credentials.username)
    if not user or not verify_password(credentials.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid username or password")

    token = create_access_token({
        "sub": user["username"],
        "user_id": user["id"],
        "role": user["role"]
    })
    return Token(
        access_token=token,
        token_type="bearer",
        user=UserOut(id=user["id"], username=user["username"], role=user["role"])
    )


@app.get("/api/auth/me", response_model=UserOut)
async def get_me(current_user: TokenData = Depends(get_current_user)):
    user = await utils.get_user_by_id(current_user.user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return UserOut(id=user["id"], username=user["username"], role=user["role"])


# ── Session Routes ────────────────────────────────────────────────────────────

class SessionCreate(BaseModel):
    name: str


class SessionRename(BaseModel):
    name: str


@app.get("/api/sessions")
async def list_sessions(current_user: TokenData = Depends(get_current_user)):
    sessions = await utils.get_user_sessions(current_user.user_id)
    return {"sessions": sessions}


@app.post("/api/sessions")
async def create_session(body: SessionCreate,
                          current_user: TokenData = Depends(get_current_user)):
    session = await utils.create_session(current_user.user_id, body.name)
    return {"session": session}


@app.get("/api/sessions/{session_id}")
async def get_session(session_id: str,
                       current_user: TokenData = Depends(get_current_user)):
    session = await get_session_or_404(session_id, current_user)
    return {"session": session}


@app.patch("/api/sessions/{session_id}")
async def rename_session(session_id: str, body: SessionRename,
                          current_user: TokenData = Depends(get_current_user)):
    await get_session_or_404(session_id, current_user)
    await utils.rename_session(session_id, body.name)
    return {"message": "Renamed"}


@app.delete("/api/sessions/{session_id}")
async def delete_session(session_id: str,
                          current_user: TokenData = Depends(get_current_user)):
    await get_session_or_404(session_id, current_user)
    await utils.delete_session(session_id)
    return {"message": "Deleted"}


# ── Context Routes ────────────────────────────────────────────────────────────

class ContextBody(BaseModel):
    context: str


@app.post("/api/sessions/{session_id}/context")
async def set_context(session_id: str, body: ContextBody,
                       current_user: TokenData = Depends(get_current_user)):
    await get_session_or_404(session_id, current_user)
    await utils.update_session_context(session_id, body.context)
    await utils.reset_stages_after(session_id, "ideate")
    await utils.update_stage_status(session_id, "context", True)
    await utils.log_checkpoint(
        current_user.user_id, session_id, "context",
        detail=body.context[:200]
    )
    return {"message": "Context saved"}


# ── Ideate Routes ─────────────────────────────────────────────────────────────

class IdeateMethodBody(BaseModel):
    method: str  # 'psc' | 'design_thinking' | 'jtbd'


class IdeateAnswerBody(BaseModel):
    answer: str


class IdeateModifyBody(BaseModel):
    question_index: int
    new_answer: str


@app.post("/api/sessions/{session_id}/ideate/start")
async def ideate_start(session_id: str, body: IdeateMethodBody,
                        current_user: TokenData = Depends(get_current_user)):
    session = await get_session_or_404(session_id, current_user)
    if not session["initial_context"]:
        raise HTTPException(status_code=400, detail="Set initial context first")

    # Load question set from TRIZ data
    with open(os.path.join(os.path.dirname(__file__), "triz_data.json")) as f:
        triz_data = json.load(f)

    method_map = {
        "psc": "psc_questions",
        "design_thinking": "design_thinking_questions",
        "jtbd": "jtbd_questions"
    }
    q_key = method_map.get(body.method, "psc_questions")
    questions = triz_data.get(q_key, [])

    ideate_data = {
        "method": body.method,
        "questions": questions,
        "current_index": 0,
        "summary": None,
        "completed": False
    }
    await utils.update_session_field(session_id, "ideate_data", ideate_data)
    await utils.reset_stages_after(session_id, "analyze")
    await utils.log_checkpoint(
        current_user.user_id, session_id, "ideate",
        tool_used=body.method, detail="Started ideate stage"
    )

    # Generate suggestion for first question
    state = agents.IdeateState(
        session_id=session_id, user_id=current_user.user_id,
        method=body.method, initial_context=session["initial_context"],
        questions=questions, current_index=0, summary=None, completed=False
    )
    suggestion = await agents.ideate_get_suggestion(state)
    ideate_data["questions"][0]["suggestion"] = suggestion
    await utils.update_session_field(session_id, "ideate_data", ideate_data)

    return {"ideate_data": ideate_data}


@app.get("/api/sessions/{session_id}/ideate/current")
async def ideate_current(session_id: str,
                          current_user: TokenData = Depends(get_current_user)):
    session = await get_session_or_404(session_id, current_user)
    ideate_data = session.get("ideate_data", {})
    if not ideate_data:
        raise HTTPException(status_code=400, detail="Ideate not started")
    return {"ideate_data": ideate_data}


@app.post("/api/sessions/{session_id}/ideate/answer")
async def ideate_answer(session_id: str, body: IdeateAnswerBody,
                         current_user: TokenData = Depends(get_current_user)):
    session = await get_session_or_404(session_id, current_user)
    ideate_data = session.get("ideate_data", {})
    if not ideate_data:
        raise HTTPException(status_code=400, detail="Ideate not started")

    idx = ideate_data["current_index"]
    questions = ideate_data["questions"]

    if idx >= len(questions):
        raise HTTPException(status_code=400, detail="All questions answered")

    questions[idx]["answer"] = body.answer
    next_idx = idx + 1
    ideate_data["current_index"] = next_idx
    ideate_data["completed"] = next_idx >= len(questions)
    ideate_data["summary"] = None

    # Pre-generate suggestion for next question
    if next_idx < len(questions):
        state = agents.IdeateState(
            session_id=session_id, user_id=current_user.user_id,
            method=ideate_data["method"],
            initial_context=session["initial_context"],
            questions=questions, current_index=next_idx,
            summary=None, completed=False
        )
        suggestion = await agents.ideate_get_suggestion(state)
        questions[next_idx]["suggestion"] = suggestion

    ideate_data["questions"] = questions
    await utils.update_session_field(session_id, "ideate_data", ideate_data)

    if ideate_data["completed"]:
        await utils.update_stage_status(session_id, "ideate", True)
        await utils.log_checkpoint(
            current_user.user_id, session_id, "ideate",
            tool_used=ideate_data["method"], detail="Completed all questions"
        )

    return {"ideate_data": ideate_data}


@app.post("/api/sessions/{session_id}/ideate/modify")
async def ideate_modify(session_id: str, body: IdeateModifyBody,
                         current_user: TokenData = Depends(get_current_user)):
    session = await get_session_or_404(session_id, current_user)
    ideate_data = session.get("ideate_data", {})
    if not ideate_data:
        raise HTTPException(status_code=400, detail="Ideate not started")

    idx = body.question_index
    questions = ideate_data["questions"]
    if not (0 <= idx < len(questions)):
        raise HTTPException(status_code=400, detail="Invalid question index")

    questions[idx]["answer"] = body.new_answer
    ideate_data["questions"] = questions
    ideate_data["summary"] = None  # Invalidate summary

    await utils.update_session_field(session_id, "ideate_data", ideate_data)
    await utils.reset_stages_after(session_id, "analyze")

    return {"ideate_data": ideate_data}


@app.post("/api/sessions/{session_id}/ideate/summary")
async def ideate_summary(session_id: str,
                          current_user: TokenData = Depends(get_current_user)):
    session = await get_session_or_404(session_id, current_user)
    ideate_data = session.get("ideate_data", {})
    if not ideate_data:
        raise HTTPException(status_code=400, detail="Ideate not started")

    async def generate():
        state = agents.IdeateState(
            session_id=session_id, user_id=current_user.user_id,
            method=ideate_data["method"],
            initial_context=session["initial_context"],
            questions=ideate_data["questions"],
            current_index=ideate_data["current_index"],
            summary=None, completed=ideate_data["completed"]
        )

        qa_pairs = [q for q in state["questions"] if q.get("answer")]
        prompt = prompts.ideate_summary(
            method=state["method"],
            initial_context=state["initial_context"],
            qa_pairs=qa_pairs
        )
        stream = await client.chat.completions.create(
            model=SIMPLE_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.5,
            stream=True
        )
        full = []
        async for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                text = chunk.choices[0].delta.content
                full.append(text)
                yield f"data: {json.dumps({'text': text})}\n\n"

        summary_text = "".join(full)
        ideate_data["summary"] = summary_text
        await utils.update_session_field(session_id, "ideate_data", ideate_data)
        await utils.log_token_usage(
            current_user.user_id, session_id, "ideate", SIMPLE_MODEL,
            500, len(summary_text.split()) * 2, 0
        )
        yield f"data: {json.dumps({'done': True, 'full': summary_text})}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


# ── Analyze Routes ────────────────────────────────────────────────────────────

class AnalyzeStartBody(BaseModel):
    method: str  # '5why' | 'swot' | 'fishbone'


class AnalyzeAnswerBody(BaseModel):
    answer: str


@app.post("/api/sessions/{session_id}/analyze/start")
async def analyze_start(session_id: str, body: AnalyzeStartBody,
                         current_user: TokenData = Depends(get_current_user)):
    session = await get_session_or_404(session_id, current_user)
    ideate_data = session.get("ideate_data", {})
    if not ideate_data.get("summary") and not ideate_data.get("completed"):
        raise HTTPException(status_code=400, detail="Complete Ideate stage first")

    ideate_summary = ideate_data.get("summary", session["initial_context"])
    questions = agents.get_analyze_questions(body.method)

    analyze_data = {
        "method": body.method,
        "ideate_summary": ideate_summary,
        "questions": questions,
        "current_index": 0,
        "analysis_data": {},
        "summary": None,
        "completed": False
    }

    # Generate suggestion for first question
    state = agents.AnalyzeState(
        session_id=session_id, user_id=current_user.user_id,
        method=body.method, ideate_summary=ideate_summary,
        questions=questions, chat_history=[], current_index=0,
        analysis_data={}, summary=None, completed=False
    )
    suggestion = await agents.analyze_get_suggestion(state)
    if questions:
        analyze_data["questions"][0]["suggestion"] = suggestion

    await utils.update_session_field(session_id, "analyze_data", analyze_data)
    await utils.reset_stages_after(session_id, "solve")
    await utils.log_checkpoint(
        current_user.user_id, session_id, "analyze",
        tool_used=body.method, detail="Started analyze stage"
    )

    return {"analyze_data": analyze_data}


@app.get("/api/sessions/{session_id}/analyze/current")
async def analyze_current(session_id: str,
                           current_user: TokenData = Depends(get_current_user)):
    session = await get_session_or_404(session_id, current_user)
    return {"analyze_data": session.get("analyze_data", {})}


@app.post("/api/sessions/{session_id}/analyze/answer")
async def analyze_answer(session_id: str, body: AnalyzeAnswerBody,
                          current_user: TokenData = Depends(get_current_user)):
    session = await get_session_or_404(session_id, current_user)
    analyze_data = session.get("analyze_data", {})
    if not analyze_data:
        raise HTTPException(status_code=400, detail="Analyze not started")

    idx = analyze_data["current_index"]
    questions = analyze_data["questions"]

    if idx >= len(questions):
        raise HTTPException(status_code=400, detail="All questions answered")

    questions[idx]["answer"] = body.answer
    field = questions[idx]["field"]
    analyze_data["analysis_data"][field] = body.answer

    next_idx = idx + 1
    analyze_data["current_index"] = next_idx
    analyze_data["completed"] = next_idx >= len(questions)
    analyze_data["summary"] = None

    if next_idx < len(questions):
        state = agents.AnalyzeState(
            session_id=session_id, user_id=current_user.user_id,
            method=analyze_data["method"],
            ideate_summary=analyze_data["ideate_summary"],
            questions=questions, chat_history=[],
            current_index=next_idx, analysis_data=analyze_data["analysis_data"],
            summary=None, completed=False
        )
        suggestion = await agents.analyze_get_suggestion(state)
        questions[next_idx]["suggestion"] = suggestion

    analyze_data["questions"] = questions
    await utils.update_session_field(session_id, "analyze_data", analyze_data)

    if analyze_data["completed"]:
        await utils.update_stage_status(session_id, "analyze", True)
        await utils.log_checkpoint(
            current_user.user_id, session_id, "analyze",
            tool_used=analyze_data["method"], detail="Completed analysis"
        )

    return {"analyze_data": analyze_data}


@app.post("/api/sessions/{session_id}/analyze/summary")
async def analyze_summary_endpoint(session_id: str,
                                    current_user: TokenData = Depends(get_current_user)):
    session = await get_session_or_404(session_id, current_user)
    analyze_data = session.get("analyze_data", {})

    async def generate():
        prompt = prompts.analyze_summary(
            method=analyze_data.get("method", ""),
            ideate_summary=analyze_data.get("ideate_summary", ""),
            analyze_data=analyze_data.get("analysis_data", {})
        )
        stream = await client.chat.completions.create(
            model=SIMPLE_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.5,
            stream=True
        )
        full = []
        async for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                text = chunk.choices[0].delta.content
                full.append(text)
                yield f"data: {json.dumps({'text': text})}\n\n"

        summary_text = "".join(full)
        analyze_data["summary"] = summary_text
        await utils.update_session_field(session_id, "analyze_data", analyze_data)
        yield f"data: {json.dumps({'done': True, 'full': summary_text})}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


# ── Solve Routes ──────────────────────────────────────────────────────────────

class SolveChatBody(BaseModel):
    message: str


@app.post("/api/sessions/{session_id}/solve/init")
async def solve_init(session_id: str,
                      current_user: TokenData = Depends(get_current_user)):
    session = await get_session_or_404(session_id, current_user)

    # Build full context
    ideate_data = session.get("ideate_data", {})
    analyze_data = session.get("analyze_data", {})
    full_context = prompts.build_full_context(
        initial_context=session["initial_context"],
        ideate_summary=ideate_data.get("summary"),
        analyze_summary=analyze_data.get("summary")
    )

    solve_data = session.get("solve_data", {})
    if not solve_data:
        solve_data = {"full_context": full_context, "chat_history": [], "initialized": False}

    async def generate():
        sys_prompt = prompts.solve_system(full_context)
        init_prompt = prompts.solve_initial_prompt(full_context)
        stream = await client.chat.completions.create(
            model=ADVANCED_MODEL,
            messages=[
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": init_prompt}
            ],
            temperature=0.7,
            stream=True
        )
        full = []
        async for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                text = chunk.choices[0].delta.content
                full.append(text)
                yield f"data: {json.dumps({'text': text})}\n\n"

        ai_response = "".join(full)
        solve_data["chat_history"].append({"role": "assistant", "content": ai_response})
        solve_data["initialized"] = True
        solve_data["full_context"] = full_context
        await utils.update_session_field(session_id, "solve_data", solve_data)
        await utils.log_checkpoint(
            current_user.user_id, session_id, "solve", detail="Initialized solve stage"
        )
        yield f"data: {json.dumps({'done': True, 'full': ai_response})}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


@app.post("/api/sessions/{session_id}/solve/chat")
async def solve_chat(session_id: str, body: SolveChatBody,
                      current_user: TokenData = Depends(get_current_user)):
    session = await get_session_or_404(session_id, current_user)
    solve_data = session.get("solve_data", {})
    if not solve_data:
        raise HTTPException(status_code=400, detail="Initialize solve first")

    solve_data["chat_history"].append({"role": "user", "content": body.message})

    async def generate():
        sys_prompt = prompts.solve_system(solve_data["full_context"])
        messages = [{"role": "system", "content": sys_prompt}]
        for msg in solve_data["chat_history"][-20:]:
            messages.append({"role": msg["role"], "content": msg["content"]})

        stream = await client.chat.completions.create(
            model=ADVANCED_MODEL, messages=messages,
            temperature=0.7, stream=True
        )
        full = []
        async for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                text = chunk.choices[0].delta.content
                full.append(text)
                yield f"data: {json.dumps({'text': text})}\n\n"

        ai_response = "".join(full)
        solve_data["chat_history"].append({"role": "assistant", "content": ai_response})
        await utils.update_session_field(session_id, "solve_data", solve_data)
        await utils.update_stage_status(session_id, "solve", True)
        yield f"data: {json.dumps({'done': True, 'full': ai_response})}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


@app.get("/api/sessions/{session_id}/solve/history")
async def solve_history(session_id: str,
                         current_user: TokenData = Depends(get_current_user)):
    session = await get_session_or_404(session_id, current_user)
    solve_data = session.get("solve_data", {})
    return {"chat_history": solve_data.get("chat_history", [])}


# ── TRIZ Routes ───────────────────────────────────────────────────────────────

class TRIZStartBody(BaseModel):
    level: int
    tool: str
    extra_params: Optional[Dict[str, Any]] = {}


class TRIZChatBody(BaseModel):
    message: str


@app.post("/api/sessions/{session_id}/triz/analyze")
async def triz_analyze(session_id: str, body: TRIZStartBody,
                        current_user: TokenData = Depends(get_current_user)):
    session = await get_session_or_404(session_id, current_user)

    ideate_data = session.get("ideate_data", {})
    analyze_data = session.get("analyze_data", {})
    solve_data = session.get("solve_data", {})

    full_context = prompts.build_full_context(
        initial_context=session["initial_context"],
        ideate_summary=ideate_data.get("summary"),
        analyze_summary=analyze_data.get("summary")
    )

    triz_data = {
        "level": body.level,
        "tool": body.tool,
        "full_context": full_context,
        "chat_history": [],
        "analysis_result": None,
        "completed": False
    }

    async def generate():
        stream = await agents.triz_analyze(
            full_context, body.level, body.tool, body.extra_params
        )
        full = []
        async for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                text = chunk.choices[0].delta.content
                full.append(text)
                yield f"data: {json.dumps({'text': text})}\n\n"

        result = "".join(full)
        triz_data["analysis_result"] = result
        triz_data["chat_history"] = [{"role": "assistant", "content": result}]
        triz_data["completed"] = True
        await utils.update_session_field(session_id, "triz_data", triz_data)
        await utils.update_stage_status(session_id, "triz", True)
        await utils.log_checkpoint(
            current_user.user_id, session_id, "triz",
            tool_used=body.tool, detail=f"Level {body.level} - {body.tool}"
        )
        yield f"data: {json.dumps({'done': True, 'full': result})}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


@app.post("/api/sessions/{session_id}/triz/chat")
async def triz_chat(session_id: str, body: TRIZChatBody,
                     current_user: TokenData = Depends(get_current_user)):
    session = await get_session_or_404(session_id, current_user)
    triz_data = session.get("triz_data", {})
    if not triz_data:
        raise HTTPException(status_code=400, detail="Run TRIZ analysis first")

    triz_data["chat_history"].append({"role": "user", "content": body.message})

    async def generate():
        state = agents.TRIZState(
            session_id=session_id, user_id=current_user.user_id,
            full_context=triz_data["full_context"],
            level=triz_data["level"], tool=triz_data["tool"],
            chat_history=triz_data["chat_history"][:-1],
            analysis_result=triz_data["analysis_result"],
            completed=False
        )
        stream = await agents.triz_chat(state, body.message)
        full = []
        async for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                text = chunk.choices[0].delta.content
                full.append(text)
                yield f"data: {json.dumps({'text': text})}\n\n"

        ai_response = "".join(full)
        triz_data["chat_history"].append({"role": "assistant", "content": ai_response})
        await utils.update_session_field(session_id, "triz_data", triz_data)
        yield f"data: {json.dumps({'done': True, 'full': ai_response})}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


@app.get("/api/sessions/{session_id}/triz/history")
async def triz_history(session_id: str,
                        current_user: TokenData = Depends(get_current_user)):
    session = await get_session_or_404(session_id, current_user)
    triz_data = session.get("triz_data", {})
    return {"triz_data": triz_data}


# ── Patent Routes ─────────────────────────────────────────────────────────────

@app.post("/api/sessions/{session_id}/patent/claims")
async def patent_claims(session_id: str,
                         current_user: TokenData = Depends(get_current_user)):
    session = await get_session_or_404(session_id, current_user)
    ideate_data = session.get("ideate_data", {})
    analyze_data = session.get("analyze_data", {})
    triz_data = session.get("triz_data", {})

    full_context = prompts.build_full_context(
        initial_context=session["initial_context"],
        ideate_summary=ideate_data.get("summary"),
        analyze_summary=analyze_data.get("summary"),
        triz_insights=triz_data.get("analysis_result", "")[:500] if triz_data else None
    )

    patent_data = session.get("patent_data", {})
    if not patent_data:
        patent_data = {"full_context": full_context, "claims": None,
                       "prior_art": None, "circumvention": None,
                       "draft": None, "chat_history": []}

    async def generate():
        stream = await agents.patent_generate_claims(full_context)
        full = []
        async for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                text = chunk.choices[0].delta.content
                full.append(text)
                yield f"data: {json.dumps({'text': text})}\n\n"

        claims_text = "".join(full)
        patent_data["claims"] = claims_text
        patent_data["full_context"] = full_context
        await utils.update_session_field(session_id, "patent_data", patent_data)
        await utils.log_checkpoint(
            current_user.user_id, session_id, "patent",
            tool_used="claims", detail="Generated patent claims"
        )
        yield f"data: {json.dumps({'done': True, 'full': claims_text})}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


@app.post("/api/sessions/{session_id}/patent/prior-art")
async def patent_prior_art(session_id: str,
                            current_user: TokenData = Depends(get_current_user)):
    session = await get_session_or_404(session_id, current_user)
    patent_data = session.get("patent_data", {})
    if not patent_data or not patent_data.get("claims"):
        raise HTTPException(status_code=400, detail="Generate claims first")

    async def generate():
        stream = await agents.patent_analyze_prior_art(
            patent_data["full_context"], patent_data["claims"]
        )
        full = []
        async for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                text = chunk.choices[0].delta.content
                full.append(text)
                yield f"data: {json.dumps({'text': text})}\n\n"

        analysis_text = "".join(full)
        patent_data["prior_art"] = analysis_text
        await utils.update_session_field(session_id, "patent_data", patent_data)
        await utils.log_checkpoint(
            current_user.user_id, session_id, "patent",
            tool_used="prior_art", detail="Analyzed prior art"
        )
        yield f"data: {json.dumps({'done': True, 'full': analysis_text})}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


@app.post("/api/sessions/{session_id}/patent/circumvent")
async def patent_circumvent_endpoint(session_id: str,
                                      current_user: TokenData = Depends(get_current_user)):
    session = await get_session_or_404(session_id, current_user)
    patent_data = session.get("patent_data", {})
    if not patent_data or not patent_data.get("claims"):
        raise HTTPException(status_code=400, detail="Generate claims first")

    async def generate():
        stream = await agents.patent_circumvent(
            patent_data["full_context"], patent_data["claims"]
        )
        full = []
        async for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                text = chunk.choices[0].delta.content
                full.append(text)
                yield f"data: {json.dumps({'text': text})}\n\n"

        circumvention_text = "".join(full)
        patent_data["circumvention"] = circumvention_text
        await utils.update_session_field(session_id, "patent_data", patent_data)
        yield f"data: {json.dumps({'done': True, 'full': circumvention_text})}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


@app.post("/api/sessions/{session_id}/patent/search-strings")
async def patent_search_strings(session_id: str,
                                 current_user: TokenData = Depends(get_current_user)):
    session = await get_session_or_404(session_id, current_user)
    patent_data = session.get("patent_data", {})

    full_context = patent_data.get("full_context", session["initial_context"])
    claims = patent_data.get("claims", "")

    async def generate():
        stream = await agents.patent_search_strings(full_context, claims)
        full = []
        async for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                text = chunk.choices[0].delta.content
                full.append(text)
                yield f"data: {json.dumps({'text': text})}\n\n"

        result_text = "".join(full)
        patent_data["search_strings"] = result_text
        await utils.update_session_field(session_id, "patent_data", patent_data)
        await utils.log_checkpoint(
            current_user.user_id, session_id, "patent",
            tool_used="search_strings", detail="Generated patent search strings"
        )
        yield f"data: {json.dumps({'done': True, 'full': result_text})}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


@app.post("/api/sessions/{session_id}/patent/draft")
async def patent_draft(session_id: str,
                        current_user: TokenData = Depends(get_current_user)):
    session = await get_session_or_404(session_id, current_user)
    patent_data = session.get("patent_data", {})
    if not patent_data or not patent_data.get("claims"):
        raise HTTPException(status_code=400, detail="Generate claims first")

    async def generate():
        stream = await agents.patent_draft_document(
            patent_data["full_context"],
            patent_data["claims"],
            patent_data.get("prior_art", "Not yet analyzed")
        )
        full = []
        async for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                text = chunk.choices[0].delta.content
                full.append(text)
                yield f"data: {json.dumps({'text': text})}\n\n"

        draft_text = "".join(full)
        patent_data["draft"] = draft_text
        await utils.update_session_field(session_id, "patent_data", patent_data)
        await utils.update_stage_status(session_id, "patent", True)
        await utils.log_checkpoint(
            current_user.user_id, session_id, "patent",
            tool_used="draft", detail="Generated full patent draft"
        )
        yield f"data: {json.dumps({'done': True, 'full': draft_text})}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


@app.get("/api/sessions/{session_id}/patent")
async def get_patent_data(session_id: str,
                           current_user: TokenData = Depends(get_current_user)):
    session = await get_session_or_404(session_id, current_user)
    return {"patent_data": session.get("patent_data", {})}


# ── Admin Routes ──────────────────────────────────────────────────────────────

class AdminChatBody(BaseModel):
    message: str
    chat_history: Optional[list] = []


@app.get("/api/admin/telemetry")
async def admin_telemetry(current_user: TokenData = Depends(require_admin)):
    data = await utils.get_admin_telemetry()
    return data


@app.post("/api/admin/chat")
async def admin_chat(body: AdminChatBody,
                      current_user: TokenData = Depends(require_admin)):
    telemetry_summary = await utils.get_telemetry_summary_for_llm()

    async def generate():
        stream = await agents.admin_chat(
            telemetry_summary, body.message, body.chat_history
        )
        async for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                text = chunk.choices[0].delta.content
                yield f"data: {json.dumps({'text': text})}\n\n"
        yield f"data: {json.dumps({'done': True})}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


# ── TRIZ Data Reference ───────────────────────────────────────────────────────

@app.get("/api/triz-data")
async def get_triz_data(current_user: TokenData = Depends(get_current_user)):
    with open(os.path.join(os.path.dirname(__file__), "triz_data.json")) as f:
        return json.load(f)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)