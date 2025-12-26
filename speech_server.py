#!/usr/bin/env python3
"""
Lightweight transcript relay server.

- POST /transcript {"text": "..."} to broadcast a transcript string to all connected websocket clients.
- WebSocket /ws streams each transcript to connected clients.
- GET /health returns {"status": "ok"}.

Run locally:
  uvicorn speech_server:app --host 0.0.0.0 --port 8000

Docker (from repo root):
  docker build -f Dockerfile.speech-server -t voice-transcript-server .
  docker run --rm -p 8000:8000 voice-transcript-server
"""

from __future__ import annotations

import asyncio
from collections import deque
from typing import Set

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel


class TranscriptIn(BaseModel):
    text: str


app = FastAPI(title="Voice Transcript Relay")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

clients: Set[WebSocket] = set()
backlog_limit = 50
backlog: deque[str] = deque(maxlen=backlog_limit)
clients_lock = asyncio.Lock()


async def broadcast(text: str) -> None:
    stale: list[WebSocket] = []
    async with clients_lock:
        for ws in clients:
            try:
                await ws.send_text(text)
            except Exception:
                stale.append(ws)
        for ws in stale:
            try:
                clients.remove(ws)
            except KeyError:
                pass


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.post("/transcript")
async def post_transcript(payload: TranscriptIn) -> dict:
    text = payload.text.strip()
    if not text:
        return {"status": "ignored", "reason": "empty"}
    backlog.append(text)
    await broadcast(text)
    return {"status": "ok", "length": len(text)}


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    await websocket.accept()
    async with clients_lock:
        clients.add(websocket)
    try:
        # Send recent backlog on connect so clients can display context.
        for item in backlog:
            await websocket.send_text(item)
        while True:
            # Keep the socket alive; clients are read-only so we just wait for disconnects.
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        async with clients_lock:
            try:
                clients.remove(websocket)
            except KeyError:
                pass
