from drive_client import _load_credentials
from googleapiclient.discovery import build

@app.get("/debug/about")
def debug_about():
    creds = _load_credentials()
    svc = build("drive", "v3", credentials=creds, cache_discovery=False)
    return svc.about().get(fields="user,emailAddress").execute()