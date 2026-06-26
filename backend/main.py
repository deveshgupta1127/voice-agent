import json
import logging
import re
import uuid
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from config import get_settings
from database.connection import init_db, get_db, close_db
from pipeline.orchestrator import PipelineOrchestrator
from agents.router_agent import RouterAgent
from agents.card_agent import CardAgent
from agents.account_agent import AccountAgent
from agents.transaction_agent import TransactionAgent
from agents.payment_agent import PaymentAgent
from llm.provider_factory import get_provider
from tools.tool_registry import build_registry
from rag.pipeline import RAGPipeline
from utils.logger import setup_logging

setup_logging()
logger = logging.getLogger("voice_agent")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    await init_db(settings.DATABASE_PATH)
    logger.info("Database initialized")
    yield
    await close_db()
    logger.info("Database closed")


app = FastAPI(title="Banking Voice Agent", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    orchestrator: PipelineOrchestrator | None = None

    try:
        while True:
            raw = await websocket.receive_text()
            msg = json.loads(raw)
            msg_type = msg.get("type", "")

            if msg_type == "start_session":
                config = msg.get("config", {})
                provider = config.get("llm_provider", "anthropic")
                settings = get_settings()
                db = await get_db()

                async def send_event(event: dict):
                    await websocket.send_json(event)

                orchestrator = PipelineOrchestrator(
                    llm_provider_name=provider,
                    event_callback=send_event,
                    settings=settings,
                    db=db,
                )
                await orchestrator.start()

            elif msg_type == "audio_chunk" and orchestrator:
                audio_data = msg.get("data", "")
                if audio_data:
                    await orchestrator.handle_audio_chunk(audio_data)

            elif msg_type == "stop_recording" and orchestrator:
                await orchestrator.handle_stop_recording()

            elif msg_type == "barge_in" and orchestrator:
                await orchestrator.handle_barge_in()

            elif msg_type == "end_session":
                if orchestrator:
                    await orchestrator.shutdown()
                break

    except WebSocketDisconnect:
        logger.info("Client disconnected")
    except Exception as e:
        logger.error("WebSocket error: %s", e)
        try:
            await websocket.send_json({"type": "error", "stage": "websocket", "message": str(e)})
        except Exception:
            pass
    finally:
        if orchestrator:
            await orchestrator.shutdown()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Text chat endpoints — test agents without STT / TTS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

_chat_sessions: dict[str, dict] = {}


class ChatStartRequest(BaseModel):
    llm_provider: str = "anthropic"
    language: str = "en-IN"
    pre_verified: bool = False
    customer_id: str | None = None
    customer_name: str | None = None


class ChatMessageRequest(BaseModel):
    session_id: str
    message: str


@app.post("/api/chat/start")
async def chat_start(req: ChatStartRequest):
    settings = get_settings()
    db = await get_db()
    llm = get_provider(req.llm_provider, settings)
    try:
        rag = RAGPipeline()
    except Exception:
        rag = None
    registry = build_registry(db, rag=rag)

    agents = {
        "router": RouterAgent(llm, registry),
        "card_agent": CardAgent(llm, registry),
        "account_agent": AccountAgent(llm, registry),
        "transaction_agent": TransactionAgent(llm, registry),
        "payment_agent": PaymentAgent(llm, registry),
    }

    session_state = {
        "customer_id": req.customer_id if req.pre_verified else None,
        "customer_name": req.customer_name if req.pre_verified else None,
        "verified": req.pre_verified,
        "language": req.language,
    }

    session_id = str(uuid.uuid4())[:8]
    _chat_sessions[session_id] = {
        "_id": session_id,
        "agents": agents,
        "active_agent": "router",
        "conversation_history": [],
        "session_state": session_state,
        "turn_number": 0,
        "llm": llm,
        "registry": registry,
    }

    return {"session_id": session_id, "session_state": session_state}


@app.post("/api/chat/message")
async def chat_message(req: ChatMessageRequest):
    session = _chat_sessions.get(req.session_id)
    if not session:
        return {"error": "Session not found. Call /api/chat/start first."}

    session["turn_number"] += 1
    session["conversation_history"].append({"role": "user", "content": req.message})

    result = await _run_chat_turn(session)
    return result


async def _run_chat_turn(session: dict) -> dict:
    agents = session["agents"]
    active_name = session["active_agent"]
    agent = agents[active_name]
    history = session["conversation_history"]
    state = session["session_state"]

    all_tool_calls: list[dict] = []
    text_chunks: list[str] = []

    async def on_text(delta: str) -> None:
        text_chunks.append(delta)

    async def on_tool_start(name: str, args: dict) -> None:
        pass

    async def on_tool_end(name: str, args: dict, result: Any, duration_ms: float) -> None:
        pass

    response = await agent.run(history, state, on_text, on_tool_start, on_tool_end)

    for tc in response.tool_calls_made:
        all_tool_calls.append({
            "tool": tc["name"],
            "args": tc["args"],
            "result": tc["result"],
            "duration_ms": round(tc.get("duration_ms", 0), 1),
        })

    _update_chat_session_state(session, response)

    clean_text = re.sub(r"\[HANDOVER:\s*\w+\]", "", response.text)
    end_session = "[END_SESSION]" in clean_text
    clean_text = clean_text.replace("[END_SESSION]", "").strip()
    history.append({"role": "assistant", "content": clean_text})

    handover_chain: list[str] = []

    if response.handover:
        target = response.handover["target_agent"]
        if target in agents:
            handover_chain.append(f"{active_name} → {target}")
            session["active_agent"] = target

            if target != "router":
                history.append({
                    "role": "user",
                    "content": "[Customer transferred — proceed based on conversation history]",
                })
                sub_result = await _run_chat_turn(session)
                all_tool_calls.extend(sub_result.get("tool_calls", []))
                clean_text += "\n\n" + sub_result.get("agent_response", "")
                handover_chain.extend(sub_result.get("handover_chain", []))
                end_session = end_session or sub_result.get("end_session", False)

    result = {
        "agent": session["active_agent"],
        "agent_response": clean_text,
        "tool_calls": all_tool_calls,
        "handover_chain": handover_chain,
        "session_state": session["session_state"],
        "turn": session["turn_number"],
        "end_session": end_session,
    }

    if end_session:
        _chat_sessions.pop(session.get("_id", ""), None)

    return result


def _update_chat_session_state(session: dict, response) -> None:
    state = session["session_state"]
    for tc in response.tool_calls_made:
        if tc["name"] == "verify_identity" and isinstance(tc["result"], dict):
            if tc["result"].get("verified"):
                state["verified"] = True
                state["customer_id"] = tc["result"].get("customer_id")
                state["customer_name"] = tc["result"].get("customer_name")


@app.get("/api/chat/sessions")
async def chat_list_sessions():
    return {
        sid: {
            "active_agent": s["active_agent"],
            "turn_number": s["turn_number"],
            "session_state": s["session_state"],
        }
        for sid, s in _chat_sessions.items()
    }


@app.delete("/api/chat/{session_id}")
async def chat_end_session(session_id: str):
    if session_id in _chat_sessions:
        del _chat_sessions[session_id]
        return {"status": "ended", "session_id": session_id}
    return {"error": "Session not found"}


@app.get("/health")
async def health_check():
    try:
        db = await get_db()
        cursor = await db.execute("SELECT 1")
        await cursor.fetchone()
        return {"status": "ok", "db": True}
    except Exception:
        return {"status": "ok", "db": False}


if __name__ == "__main__":
    import uvicorn
    settings = get_settings()
    uvicorn.run("main:app", host=settings.HOST, port=settings.PORT, reload=True)
