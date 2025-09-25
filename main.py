# main.py
import os, hmac, hashlib, base64
from fastapi import FastAPI, Request, Header, HTTPException
from fastapi import Response

app = FastAPI()
CHANNEL_SECRET = os.environ["LINE_CHANNEL_SECRET"].strip()

@app.post("/callback")
async def callback(
    request: Request,
    x_line_signature: str = Header(..., alias="X-Line-Signature"),
):
    body = await request.body()
    sig = x_line_signature.strip()
    expected = base64.b64encode(
        hmac.new(CHANNEL_SECRET.encode(), body, hashlib.sha256).digest()
    ).decode()

    # ใช้ compare_digest ปลอดภัยกว่าการเทียบสตริงตรง ๆ
    if not hmac.compare_digest(sig, expected):
        raise HTTPException(status_code=400, detail="Invalid signature")

    # สำหรับปุ่ม "Verify" ใน LINE Console: ไม่ต้อง parse อะไร ตอบ 200 ได้เลย
    return Response(status_code=200)
