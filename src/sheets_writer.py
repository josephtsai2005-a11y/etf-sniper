"""
sheets_writer.py
Google Sheets 連線工具
需要: gspread, google-auth
"""
import gspread
import logging
from google.oauth2.service_account import Credentials
from typing import Optional
import os

log = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


def get_client(credentials_path: Optional[str] = None) -> gspread.Client:
    """
    建立 Google Sheets 連線
    credentials_path: service account JSON 路徑
    若未指定，從環境變數 GOOGLE_APPLICATION_CREDENTIALS 讀取
    """
    cred_path = credentials_path or os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if not cred_path:
        raise ValueError("請設定 GOOGLE_APPLICATION_CREDENTIALS 環境變數或傳入 credentials_path")

    creds = Credentials.from_service_account_file(cred_path, scopes=SCOPES)
    return gspread.authorize(creds)


def get_or_create_spreadsheet(client: gspread.Client, spreadsheet_id: str) -> gspread.Spreadsheet:
    """取得試算表"""
    try:
        ss = client.open_by_key(spreadsheet_id)
        log.info(f"已開啟試算表：{ss.title}")
    except gspread.exceptions.SpreadsheetNotFound:
        raise ValueError(f"找不到試算表 ID: {spreadsheet_id}，請確認 ID 正確且已共用給 Service Account")

    return ss