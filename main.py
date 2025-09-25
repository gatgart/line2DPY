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

# main.py
import base64, hmac, hashlib

@app.post("/callback")
async def callback(request: Request, x_line_signature: str = Header(..., alias="X-Line-Signature")):
    body_bytes = await request.body()
    body_text = body_bytes.decode("utf-8")

    # --- DEBUG: compute expected signature from our CHANNEL_SECRET
    expected_sig = base64.b64encode(
        hmac.new(CHANNEL_SECRET.encode("utf-8"), body_bytes, hashlib.sha256).digest()
    ).decode("utf-8")

    # พิมพ์เท่าที่จำเป็น (อย่าพิมพ์ secret)
    print("[LINE DEBUG]",
          "len(body)=", len(body_bytes),
          "header_sig=", repr(x_line_signature.strip()),
          "expected_sig=", repr(expected_sig))

    # ใช้ SDK ตรวจตามปกติ
    try:
        events = parser.parse(body_text, x_line_signature)
    except InvalidSignatureError:
        # แถม detail ให้อ่าน log คู่กัน
        raise HTTPException(status_code=400, detail="Invalid signature")

    # ... ทำงานต่อถ้ามีอีเวนต์ ...
    return "OK"

