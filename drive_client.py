import os, io, json
from googleapiclient.discovery import build
from google.oauth2 import service_account
from googleapiclient.http import MediaIoBaseUpload

SCOPES = ["https://www.googleapis.com/auth/drive.file"]

def _load_credentials():
    # โหมด Secret File (Render): ตั้ง GOOGLE_APPLICATION_CREDENTIALS ให้ชี้ไฟล์ JSON
    key_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if key_path and os.path.exists(key_path):
        return service_account.Credentials.from_service_account_file(key_path, scopes=SCOPES)
    # โหมด ENV JSON
    raw = os.environ.get("GOOGLE_CREDENTIALS_JSON")
    if raw:
        data = json.loads(raw)
        return service_account.Credentials.from_service_account_info(data, scopes=SCOPES)
    raise RuntimeError("No Google credentials provided. Use GOOGLE_APPLICATION_CREDENTIALS or GOOGLE_CREDENTIALS_JSON.")

def get_drive():
    creds = _load_credentials()
    return build("drive", "v3", credentials=creds, cache_discovery=False)

def upload_stream(drive, folder_id: str, filename: str, content_type: str, stream: io.BytesIO):
    media = MediaIoBaseUpload(stream, mimetype=content_type, resumable=True)
    body = {"name": filename}
    if folder_id:
        body["parents"] = [folder_id]
    return drive.files().create(body=body, media_body=media, fields="id,webViewLink,webContentLink").execute()