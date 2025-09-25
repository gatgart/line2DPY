# main.py
# FastAPI webhook for LINE -> Google Drive (Render-ready)
# - Verifies X-Line-Signature using raw body + CHANNEL_SECRET
# - Replies fast to webhook; uploads to Google Drive in background
# - Pushes Drive link back to the chat (user/group/room)

import os
import io
import hmac
import base64
import hashlib
import logging
import mimetypes
from typing import Optional

from fastapi import FastAPI, Request, Header, HTTPException, Response, BackgroundTasks

# LINE SDK
from linebot import LineBotApi, WebhookParser
from linebot.models import (
    MessageEvent, TextMessage, FileMessage, ImageMessage, VideoMessage, AudioMessage,
    TextSendMessage,
)
from linebot.exceptions import LineBotApiError, InvalidSignatureError

# Google Drive helper (you provide this file as shown earlier)
from drive_client import get_drive, upload_stream

# ------------------------------------------------------------------------------
# App & Logging
# ------------------------------------------------------------------------------
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger("line2drive")

app = FastAPI(title="LINE2Drive Webhook", version="1.0")

# ------------------------------------------------------------------------------
# Environment
# ------------------------------------------------------------------------------
CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET", "").strip()
CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "").strip()
GOOGLE_DRIVE_FOLDER_ID = os.getenv("GOOGLE_DRIVE_FOLDER_ID", "").strip()

if not CHANNEL_SECRET:
    logger.warning("ENV LINE_CHANNEL_SECRET is empty!")
if not CHANNEL_ACCESS_TOKEN:
    logger.warning("ENV LINE_CHANNEL_ACCESS_TOKEN is empty!")
if not GOOGLE_DRIVE_FOLDER_ID:
    logger.warning("ENV GOOGLE_DRIVE_FOLDER_ID is empty!")

line_bot_api: Optional[LineBotApi] = None
parser: Optional[WebhookParser] = None
drive = None  # lazy-init

# ------------------------------------------------------------------------------
# Utilities
# ------------------------------------------------------------------------------
def _ensure_clients():
    """Lazy-initialize external clients."""
    global line_bot_api, parser, drive
    if line_bot_api is None and CHANNEL_ACCESS_TOKEN:
        line_bot_api = LineBotApi(CHANNEL_ACCESS_TOKEN)
        logger.info("Initialized LineBotApi")
    if parser is None and CHANNEL_SECRET:
        parser = WebhookParser(CHANNEL_SECRET)
        logger.info("Initialized WebhookParser")
    if drive is None:
        try:
            drive = get_drive()
            logger.info("Initialized Google Drive client")
        except Exception as e:
            logger.exception("Failed to initialize Google Drive client: %s", e)
            # Don't raise here—allow webhook to respond 200 and handle later

def _push_target(src) -> Optional[str]:
    """Return target id for push_message (user/group/room)."""
    for attr in ("user_id", "group_id", "room_id"):
        val = getattr(src, attr, None)
        if val:
            return val
    return None

def _safe_ext(content_type: Optional[str]) -> str:
    ext = mimetypes.guess_extension(content_type or "") or ""
    return ".jpg" if ext == ".jpe" else ext

def _compute_signature(secret: str, body: bytes) -> str:
    mac = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).digest()
    return base64.b64encode(mac).decode("utf-8")

# ------------------------------------------------------------------------------
# Background job: download from LINE -> upload to Drive -> push link
# ------------------------------------------------------------------------------
def process_upload(event: MessageEvent):
    """Runs outside request/response to keep webhook snappy."""
    try:
        _ensure_clients()
        if line_bot_api is None or drive is None:
            logger.error("Clients not ready (LINE or Drive); cannot process upload.")
            return

        # 1) Download content stream from LINE
        resp = line_bot_api.get_message_content(event.message.id)
        content_type = getattr(resp, "content_type", None) or "application/octet-stream"


        # 2) Determine filename
        base = getattr(event.message, "file_name", None) or f"line_{event.message.id}"
        filename = base if "." in base else base + _safe_ext(content_type)

        # 3) Buffer -> BytesIO (you can switch to temp file if very large)
        buf = io.BytesIO()
        for chunk in resp.iter_content(1024 * 1024):
            if chunk:
                buf.write(chunk)
        buf.seek(0)

        # 4) Upload to Google Drive
        meta = upload_stream(
            drive=drive,
            folder_id=GOOGLE_DRIVE_FOLDER_ID,
            filename=filename,
            content_type=content_type,
            stream=buf,
        )
        file_id = meta.get("id")
        link = meta.get("webViewLink") or meta.get("webContentLink") or (
            f"https://drive.google.com/file/d/{file_id}/view" if file_id else None
        )

        # 5) Push link back to the chat
        to = _push_target(event.source)
        if to and link:
            try:
                line_bot_api.push_message(to, TextSendMessage(text=f"Uploaded ✅\n{link}"))
            except LineBotApiError as e:
                logger.exception("Failed to push link: %s", e)
        else:
            logger.warning("Missing push target or link (to=%s, link=%s)", to, link)

    except Exception:
        logger.exception("process_upload failed")

# ------------------------------------------------------------------------------
# Routes
# ------------------------------------------------------------------------------
@app.get("/")
def health():
    """Basic health with readiness hints (do not expose secrets)."""
    return {
        "ok": True,
        "env": {
            "has_channel_secret": bool(CHANNEL_SECRET),
            "has_access_token": bool(CHANNEL_ACCESS_TOKEN),
            "has_folder_id": bool(GOOGLE_DRIVE_FOLDER_ID),
        },
        "clients": {
            "line_bot_api": line_bot_api is not None,
            "parser": parser is not None,
            "drive": drive is not None,
        },
    }

@app.get("/callback")
def callback_get():
    """Helpful when you open the URL in a browser."""
    return {"ok": True, "note": "LINE calls POST here"}

@app.post("/callback")
async def callback(
    request: Request,
    background_tasks: BackgroundTasks,
    x_line_signature: str = Header(..., alias="X-Line-Signature"),
):
    # Ensure required envs/clients
    if not (CHANNEL_SECRET and CHANNEL_ACCESS_TOKEN and GOOGLE_DRIVE_FOLDER_ID):
        raise HTTPException(status_code=500, detail="Server misconfigured: missing env")

    _ensure_clients()
    if parser is None or line_bot_api is None:
        raise HTTPException(status_code=500, detail="Server misconfigured: clients not ready")

    # 1) Verify signature using RAW body
    body_bytes = await request.body()
    expected_sig = _compute_signature(CHANNEL_SECRET, body_bytes)
    if not hmac.compare_digest(x_line_signature.strip(), expected_sig):
        # Optional: log a short debug line (do NOT log secrets)
        logger.debug("Signature mismatch")
        raise HTTPException(status_code=400, detail="Invalid signature")

    # 2) Parse events (LINE's verify sends {"destination":"...","events":[]})
    try:
        events = parser.parse(body_bytes.decode("utf-8"), x_line_signature)
    except InvalidSignatureError:
        raise HTTPException(status_code=400, detail="Invalid signature")
    except Exception:
        logger.exception("parser.parse failed")
        # Do not break LINE verify; but better to surface as 400/200 based on your policy
        return Response(status_code=200)

    # 3) Handle events: reply fast, heavy work in background
    for event in events:
        if isinstance(event, MessageEvent):
            if isinstance(event.message, (FileMessage, ImageMessage, VideoMessage, AudioMessage)):
                # Reply immediately to keep webhook fast
                try:
                    line_bot_api.reply_message(
                        event.reply_token,
                        TextSendMessage(text="รับไฟล์แล้ว กำลังอัปโหลดขึ้น Google Drive..."),
                    )
                except LineBotApiError as e:
                    logger.warning("reply_message failed (will still push later): %s", e)
                # Upload in background
                background_tasks.add_task(process_upload, event)

            elif isinstance(event.message, TextMessage):
                try:
                    line_bot_api.reply_message(
                        event.reply_token,
                        TextSendMessage(text="ส่งรูป/ไฟล์มาได้เลย เดี๋ยวอัปขึ้น Google Drive ให้ครับ ✅"),
                    )
                except LineBotApiError as e:
                    logger.warning("reply_message failed: %s", e)

    # 4) Always return 200 for a successfully handled webhook
    return Response(status_code=200)
