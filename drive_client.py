import os, io, json
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
from google.oauth2 import service_account
from google.oauth2.credentials import Credentials

# ใช้สิทธิแบบเต็มเพื่อหลบประเด็นสิทธิ + รองรับ Shared Drive
SCOPES = ["https://www.googleapis.com/auth/drive"]

def _load_credentials():
    # โหมด OAuth (สำหรับทางเลือก B) — เปิดด้วย GOOGLE_OAUTH_MODE=1
    if os.getenv("GOOGLE_OAUTH_MODE", "0") in ("1", "true", "True"):
        refresh_token = os.environ["GOOGLE_REFRESH_TOKEN"]
        client_id = os.environ["GOOGLE_CLIENT_ID"]
        client_secret = os.environ["GOOGLE_CLIENT_SECRET"]
        return Credentials(
            token=None,
            refresh_token=refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=client_id,
            client_secret=client_secret,
            scopes=SCOPES,
        )

    # โหมด Service Account (ดีสำหรับ Shared Drive)
    key_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if key_path and os.path.exists(key_path):
        return service_account.Credentials.from_service_account_file(key_path, scopes=SCOPES)
    raw = os.environ.get("GOOGLE_CREDENTIALS_JSON")
    if raw:
        return service_account.Credentials.from_service_account_info(json.loads(raw), scopes=SCOPES)
    raise RuntimeError("No Google credentials provided.")

def get_drive():
    creds = _load_credentials()
    return build("drive", "v3", credentials=creds, cache_discovery=False)

def upload_stream(drive, folder_id: str, filename: str, content_type: str, stream: io.BytesIO):
    media = MediaIoBaseUpload(stream, mimetype=content_type, resumable=True)
    body = {"name": filename}
    if folder_id:
        body["parents"] = [folder_id]  # parent ใน Shared Drive
    return drive.files().create(
        body=body,
        media_body=media,
        fields="id,webViewLink,webContentLink,driveId,parents,owners",
        supportsAllDrives=True,    # ✅ สำคัญสำหรับ Shared Drive
    ).execute()
