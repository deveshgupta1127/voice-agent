import json
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from config import get_settings
from database.connection import init_db, get_db, close_db
from pipeline.orchestrator import PipelineOrchestrator

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
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
