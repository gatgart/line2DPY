import os, io, json, time, mimetypes
from typing import List
from fastapi import FastAPI, Request, Header, HTTPException
from linebot import LineBotApi, WebhookParser
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, FileMessage, ImageMessage, VideoMessage, AudioMessage, TextSendMessage
from drive_client import get_drive, upload_stream

app = FastAPI()

# --- ENV ---
CHANNEL_SECRET = os.environ["LINE_CHANNEL_SECRET"]
CHANNEL_ACCESS_TOKEN = os.environ["LINE_CHANNEL_ACCESS_TOKEN"]
GOOGLE_DRIVE_FOLDER_ID = os.environ["GOOGLE_DRIVE_FOLDER_ID"]  # โฟลเดอร์ปลายทางในไดรฟ์
# สำหรับ credentials: ใช้ได้สองแบบ
# 1) GOOGLE_APPLICATION_CREDENTIALS -> path ไปยัง secret file (Render Secret File)
# 2) GOOGLE_CREDENTIALS_JSON -> ใส่ JSON ทั้งก้อนเป็น env var
drive = get_drive()

line_bot_api = LineBotApi(CHANNEL_ACCESS_TOKEN)
parser = WebhookParser(CHANNEL_SECRET)

@app.get("/")
def health():
    return {"ok": True, "ts": int(time.time())}

@app.post("/callback")
async def callback(request: Request, x_line_signature: str = Header(None, convert_underscores=False)):
    body = await request.body()
    try:
        events: List = parser.parse(body.decode("utf-8"), x_line_signature or "")
    except InvalidSignatureError:
        raise HTTPException(status_code=400, detail="Invalid signature")

    for event in events:
        if isinstance(event, MessageEvent):
            # 1) ไฟล์/มีเดีย -> ดาวน์โหลดจาก LINE แล้วอัปโหลดขึ้น Drive
            if isinstance(event.message, (FileMessage, ImageMessage, VideoMessage, AudioMessage)):
                try:
                    resp = line_bot_api.get_message_content(event.message.id)  # stream response
                    # สร้างชื่อไฟล์
                    ct = resp.headers.get("Content-Type", "application/octet-stream")
                    # ชื่อไฟล์จาก FileMessage ถ้ามี; ถ้าไม่มีก็เดาจาก mimetype
                    base = getattr(event.message, "file_name", None) or f"line_{event.message.id}"
                    ext = mimetypes.guess_extension(ct) or ""
                    if ext == ".jpe":  # บางที guess จะคืน .jpe
                        ext = ".jpg"
                    filename = base if base.lower().endswith(ext) or "." in base else base + ext

                    buf = io.BytesIO()
                    for chunk in resp.iter_content(chunk_size=1024 * 1024):
                        if chunk:
                            buf.write(chunk)
                    buf.seek(0)

                    file_meta = upload_stream(
                        drive=drive,
                        folder_id=GOOGLE_DRIVE_FOLDER_ID,
                        filename=filename,
                        content_type=ct,
                        stream=buf
                    )

                    # ตอบกลับลิงก์ดูไฟล์
                    link = file_meta.get("webViewLink") or file_meta.get("webContentLink") or f"https://drive.google.com/file/d/{file_meta['id']}/view"
                    line_bot_api.reply_message(
                        event.reply_token,
                        TextSendMessage(text=f"Uploaded ✅\n{link}")
                    )
                except Exception as e:
                    line_bot_api.reply_message(
                        event.reply_token,
                        TextSendMessage(text=f"อัปโหลดไม่สำเร็จ: {e}")
                    )

            # 2) ข้อความธรรมดา -> ตอบรับ
            elif isinstance(event.message, TextMessage):
                line_bot_api.reply_message(
                    event.reply_token,
                    TextSendMessage(text="ส่งรูป/ไฟล์มาได้เลย เดี๋ยวอัปขึ้น Google Drive ให้นะครับ ✅")
                )

    return "OK"
