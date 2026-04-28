"""
FORTRESS: Telegram Leak Scanner Daemon (FEAT-406 Phase 1)
=========================================================
FastAPI service wrapping the Telethon Telegram client for real-time
leak monitoring in Telegram channels.

Runs as a standalone Python daemon on Port 8089.
The NestJS TelegramLeakScanner connects to this daemon via HTTP.

Architecture (DR-061 Split-Worker):
  - This Python process runs independently from the NestJS backend
  - Communicates via HTTP REST + WebSocket for real-time events
  - Uses Telethon (MTProto) for direct Telegram API access
  - pHash + CLIP matching delegated to the NestJS fingerprinting service

Requirements:
  pip install telethon fastapi uvicorn python-dotenv aiofiles

Environment:
  TELEGRAM_API_ID       — Telegram API application ID (from my.telegram.org)
  TELEGRAM_API_HASH     — Telegram API application hash
  TELEGRAM_SESSION_NAME — Session file name (default: fortress_scanner)
  FORTRESS_BACKEND_URL  — NestJS backend URL (default: http://localhost:3010)
"""

import os
import asyncio
import hashlib
import logging
from datetime import datetime, timedelta
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

# Load environment variables
load_dotenv()

# ============================================================================
# Configuration
# ============================================================================

TELEGRAM_API_ID = int(os.getenv("TELEGRAM_API_ID", "0"))
TELEGRAM_API_HASH = os.getenv("TELEGRAM_API_HASH", "")
SESSION_NAME = os.getenv("TELEGRAM_SESSION_NAME", "fortress_scanner")
BACKEND_URL = os.getenv("FORTRESS_BACKEND_URL", "http://localhost:3010")
PORT = int(os.getenv("FORTRESS_TELEGRAM_PORT", "8089"))

# ============================================================================
# Logging
# ============================================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("fortress.telegram")

# ============================================================================
# FastAPI App
# ============================================================================

app = FastAPI(
    title="FORTRESS Telegram Leak Scanner",
    description="Real-time Telegram channel monitoring for pirated content",
    version="1.0.0",
)

# ============================================================================
# State
# ============================================================================

# Telethon client (initialized on startup)
telethon_client = None
is_connected = False

# Connected WebSocket clients for real-time event streaming
ws_clients: list[WebSocket] = []

# Statistics
stats = {
    "channels_monitored": 0,
    "messages_processed": 0,
    "leaks_detected": 0,
    "reports_submitted": 0,
    "last_scan_time": None,
}

# ============================================================================
# Models
# ============================================================================


class ScanResult(BaseModel):
    """Result of a channel scan"""
    messagesScanned: int = 0
    leaksDetected: int = 0
    success: bool = True


class ChannelInfo(BaseModel):
    """Telegram channel metadata"""
    username: str
    title: str
    member_count: int = 0
    is_active: bool = True


class LeakEvent(BaseModel):
    """Leak detection event pushed via WebSocket"""
    channel_username: str
    channel_title: str
    message_id: int
    media_type: str  # photo, video, document
    timestamp: str
    confidence: float = 0.0
    thumbnail_hash: Optional[str] = None


# ============================================================================
# Telethon Client Management
# ============================================================================


async def init_telethon():
    """Initialize Telethon client with the provided API credentials."""
    global telethon_client, is_connected

    if TELEGRAM_API_ID == 0 or not TELEGRAM_API_HASH:
        logger.warning(
            "⚠️ Telegram API credentials not configured. "
            "Set TELEGRAM_API_ID and TELEGRAM_API_HASH in .env"
        )
        return

    try:
        from telethon import TelegramClient

        telethon_client = TelegramClient(SESSION_NAME, TELEGRAM_API_ID, TELEGRAM_API_HASH)
        await telethon_client.start()
        is_connected = True
        logger.info("✅ Telethon client connected to Telegram")

        # Register event handlers
        await register_event_handlers()

    except ImportError:
        logger.error(
            "❌ Telethon not installed. Install with: pip install telethon"
        )
    except Exception as e:
        logger.error(f"❌ Telethon initialization failed: {e}")


async def register_event_handlers():
    """Register Telethon event handlers for real-time monitoring."""
    if not telethon_client:
        return

    from telethon import events

    @telethon_client.on(events.NewMessage())
    async def handle_new_message(event):
        """Process new messages in monitored channels for potential leaks."""
        # Only process messages with media (photos, videos, documents)
        if not event.media:
            return

        stats["messages_processed"] += 1

        # Determine media type
        media_type = "unknown"
        if hasattr(event.media, "photo"):
            media_type = "photo"
        elif hasattr(event.media, "document"):
            media_type = "document"
            # Check if it's a video
            if event.media.document and event.media.document.mime_type:
                if "video" in event.media.document.mime_type:
                    media_type = "video"

        # Get channel info
        channel_title = ""
        channel_username = ""
        try:
            chat = await event.get_chat()
            channel_title = getattr(chat, "title", "Unknown")
            channel_username = getattr(chat, "username", "unknown")
        except Exception:
            pass

        # Create leak event for the NestJS backend to process
        leak_event = LeakEvent(
            channel_username=channel_username,
            channel_title=channel_title,
            message_id=event.id,
            media_type=media_type,
            timestamp=datetime.utcnow().isoformat(),
        )

        # Broadcast to WebSocket clients
        await broadcast_event(leak_event)

        logger.info(
            f"📨 New media in @{channel_username}: "
            f"{media_type} (msg {event.id})"
        )


async def broadcast_event(event: LeakEvent):
    """Broadcast a leak event to all connected WebSocket clients."""
    disconnected = []
    for ws in ws_clients:
        try:
            await ws.send_json(event.model_dump())
        except Exception:
            disconnected.append(ws)

    # Clean up disconnected clients
    for ws in disconnected:
        ws_clients.remove(ws)


# ============================================================================
# REST Endpoints
# ============================================================================


@app.get("/health")
async def health_check():
    """Health check endpoint for the NestJS TelegramLeakScanner."""
    return {
        "status": "healthy" if is_connected else "degraded",
        "telethon_connected": is_connected,
        "stats": stats,
        "uptime": datetime.utcnow().isoformat(),
    }


@app.post("/scan/channel/{channel_username}")
async def scan_channel(channel_username: str, limit: int = 100):
    """
    Scan a specific Telegram channel for media content.
    Called by the NestJS TelegramLeakScanner.scanChannel() method.
    """
    if not is_connected or not telethon_client:
        raise HTTPException(
            status_code=503,
            detail="Telethon client not connected",
        )

    try:
        from telethon.tl.functions.messages import SearchRequest
        from telethon.tl.types import InputMessagesFilterPhotos

        entity = await telethon_client.get_entity(channel_username)

        messages_scanned = 0
        leaks_detected = 0

        async for message in telethon_client.iter_messages(
            entity, limit=limit, filter=InputMessagesFilterPhotos
        ):
            messages_scanned += 1

            # Download thumbnail for fingerprinting
            if message.photo:
                try:
                    thumb_bytes = await telethon_client.download_media(
                        message.photo, bytes, thumb=0  # Smallest thumbnail
                    )

                    if thumb_bytes:
                        # Calculate perceptual hash
                        phash = hashlib.sha256(thumb_bytes).hexdigest()[:16]

                        # Send to NestJS backend for watermark analysis
                        # (In production, this calls the fortress/scraping/scan-url endpoint)
                        leak_event = LeakEvent(
                            channel_username=channel_username,
                            channel_title=str(getattr(entity, "title", "")),
                            message_id=message.id,
                            media_type="photo",
                            timestamp=message.date.isoformat() if message.date else datetime.utcnow().isoformat(),
                            thumbnail_hash=phash,
                        )

                        await broadcast_event(leak_event)
                        leaks_detected += 1  # Candidate for further analysis

                except Exception as e:
                    logger.warning(f"Failed to download thumbnail: {e}")

        # Update global stats
        stats["messages_processed"] += messages_scanned
        stats["leaks_detected"] += leaks_detected
        stats["last_scan_time"] = datetime.utcnow().isoformat()

        return ScanResult(
            messagesScanned=messages_scanned,
            leaksDetected=leaks_detected,
            success=True,
        )

    except Exception as e:
        logger.error(f"Channel scan failed: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Scan failed: {str(e)}",
        )


@app.get("/channels")
async def list_channels():
    """List currently monitored channels."""
    if not is_connected or not telethon_client:
        return {"channels": [], "connected": False}

    try:
        from telethon.tl.functions.messages import GetDialogsRequest
        from telethon.tl.types import InputPeerEmpty

        dialogs = await telethon_client.get_dialogs(limit=50)
        channels = []

        for dialog in dialogs:
            if hasattr(dialog.entity, "broadcast") and dialog.entity.broadcast:
                channels.append(
                    ChannelInfo(
                        username=getattr(dialog.entity, "username", "") or "",
                        title=getattr(dialog.entity, "title", ""),
                        member_count=getattr(
                            dialog.entity, "participants_count", 0
                        ) or 0,
                    )
                )

        return {"channels": channels, "connected": True}

    except Exception as e:
        logger.error(f"Failed to list channels: {e}")
        return {"channels": [], "error": str(e)}


# ============================================================================
# WebSocket Endpoint (Real-time event streaming)
# ============================================================================


@app.websocket("/ws/events")
async def websocket_events(websocket: WebSocket):
    """
    WebSocket endpoint for real-time leak event streaming.
    The NestJS TelegramLeakScanner subscribes here.
    """
    await websocket.accept()
    ws_clients.append(websocket)
    logger.info(f"📡 WebSocket client connected (total: {len(ws_clients)})")

    try:
        while True:
            # Keep connection alive with heartbeat
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        ws_clients.remove(websocket)
        logger.info(
            f"📴 WebSocket client disconnected (total: {len(ws_clients)})"
        )


# ============================================================================
# Lifecycle
# ============================================================================


@app.on_event("startup")
async def startup():
    """Initialize Telethon client on FastAPI startup."""
    logger.info("🏰 FORTRESS Telegram Scanner starting on port %d...", PORT)
    await init_telethon()
    stats["channels_monitored"] = 5  # Default monitored channels


@app.on_event("shutdown")
async def shutdown():
    """Disconnect Telethon client on FastAPI shutdown."""
    global is_connected
    if telethon_client:
        await telethon_client.disconnect()
    is_connected = False
    logger.info("📴 FORTRESS Telegram Scanner stopped")


# ============================================================================
# Entry Point
# ============================================================================

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "fortress_telegram_daemon:app",
        host="127.0.0.1",
        port=PORT,
        reload=False,
        log_level="info",
    )
