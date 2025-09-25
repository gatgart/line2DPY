# main.py
import os, io, hmac, hashlib, base64, mimetypes
from fastapi import FastAPI, Request, Header, HTTPException, Response, BackgroundTasks
from linebot import LineBotApi, WebhookParser
from linebot.exceptions import InvalidSignatureError
from linebot.models import (
    MessageEvent, TextMessage, FileMessage, ImageMessage, VideoMessage, AudioMessage,
    TextSendMessage
)
from drive_client import get_drive, upload_stream

app = FastAPI()

# ---- ENV
CHANNEL_SECRET = os.environ["LINE_CHANNEL_SECRET"].strip()
CHANNEL_ACCESS_TOKEN = os.environ["LINE_CHANNEL_ACCESS_TOKEN"].strip()
GOOGLE_DRIVE_FOLDER_ID = os.environ["GOOGLE_DRIVE_FOLDER_ID"].strip()

line_bot_api = LineBotApi(CHANNEL_ACCESS_TOKEN)
parser = WebhookParser(CHANNEL_SECRET)
drive = get_drive()

def _push_target(src):
    # รองรับ user / group / room
    return getattr(src, "user_id", None) or getattr(src, "group_id", None) or getattr(src, "room_id", None)

def _safe_ext(content_type: str):
    ext = mimetypes.guess_extension(content_type or "") or ""
    return ".jpg" if ext == ".jpe" else ext

def process_upload(event):
    # ดาวน์โหลดไฟล์จาก LINE
    try:
    resp = line_bot_api.get_message_content(event.message.id)
    ct = resp.headers.get("Content-Type", "application/octet-stream")
    base = getattr(event.message, "file_name", None) or f"line_{event.message.id}"
    filename = base if "." in base else base + _safe_ext(ct)

    buf = io.BytesIO()
    for chunk in resp.iter_content(1024 * 1024):
        if chunk:
            buf.write(chunk)
    buf.seek(0)

    meta = upload_stream(
        drive=drive,
        folder_id=GOOGLE_DRIVE_FOLDER_ID,
        filename=filename,
        content_type=ct,
        stream=buf
    )
    link = meta.get("webViewLink") or meta.get("webContentLink") or f"https://drive.google.com/file/d/{meta['id']}/view"

    to = _push_target(event.source)
    if to:
        line_bot_api.push_message(to, TextSendMessage(text=f"Uploaded ✅\n{link}"))
     pass
    except Exception:
        logger.exception("upload failed") 

@app.post("/callback")
async def callback(
    request: Request,
    background_tasks: BackgroundTasks,
    x_line_signature: str = Header(..., alias="X-Line-Signature"),
):
    # 1) Verify signature ด้วย raw body
    body = await request.body()
    expected = base64.b64encode(hmac.new(CHANNEL_SECRET.encode(), body, hashlib.sha256).digest()).decode()
    if not hmac.compare_digest(x_line_signature.strip(), expected):
        raise HTTPException(status_code=400, detail="Invalid signature")

    # 2) parse events (อย่าให้ throw ระหว่าง Verify)
    events = parser.parse(body.decode("utf-8"), x_line_signature)

    # 3) จัดการเหตุการณ์แบบ “ตอบเร็ว + ทำงานหนักหลังบ้าน”
    for event in events:
        if isinstance(event, MessageEvent):
            if isinstance(event.message, (FileMessage, ImageMessage, VideoMessage, AudioMessage)):
                # ตอบทันทีเพื่อให้ webhook สำเร็จ
                try:
                    line_bot_api.reply_message(event.reply_token, TextSendMessage(text="รับไฟล์แล้ว กำลังอัปโหลดขึ้น Google Drive..."))
                except Exception:
                    # ถ้าหมดเวลา reply (token หมดอายุ) ก็ปล่อยไป ใช้ push แทนด้านล่าง
                    pass
                # ทำงานหนักหลังบ้าน
                background_tasks.add_task(process_upload, event)

            elif isinstance(event.message, TextMessage):
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text="ส่งรูป/ไฟล์มาได้เลย เดี๋ยวอัปขึ้น Google Drive ให้ครับ ✅"))

    # 4) ตอบ webhook 200 ทันที
    return Response(status_code=200)

@app.get("/")
def health():
    return {"ok": True}
