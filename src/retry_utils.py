"""
retry_utils.py
共用重試工具，用於外部API/Sheets寫入等可能因暫時性網路問題失敗的操作。

背景：2026-08-26事故——Claude API呼叫全數成功、報告內容都生成好了，
但寫入Google Sheets這一步遇到網路瞬斷（RemoteDisconnected），整份報告因此遺失，
且沒有備份機制可以救回。教訓是：任何「前面步驟都成功、只差最後寫入」的環節，
只要沒有重試保護，一次偶發網路問題就會讓所有心血白費。

這裡把「哪些錯誤值得重試、哪些重試也沒用」的判斷邏輯收斂成共用函式，
避免每個檔案各寫一份、標準不一致，也避免對「重試也沒用」的錯誤（例如認證失敗、
資料格式錯誤）做無意義的重試，浪費時間。
"""
import logging
import time

log = logging.getLogger(__name__)


def is_retryable_error(e: Exception) -> bool:
    """
    判斷這個例外值不值得重試。

    值得重試（暫時性問題，換個時間點大機率會成功）：
    - 連線中斷/逾時（requests.exceptions.ConnectionError / Timeout、RemoteDisconnected等）
    - Google Sheets API 限流（429）或伺服器暫時性錯誤（5xx）

    不值得重試（重試也沒用，直接放棄比較快，也不浪費重試次數）：
    - 認證/權限錯誤（401/403）
    - 請求本身有問題（400）或找不到資源（404）
    - 其他無法辨識的例外（保守起見不重試，避免對資料格式錯誤這類邏輯錯誤做無意義重試）
    """
    import requests as _requests

    if isinstance(e, (_requests.exceptions.ConnectionError, _requests.exceptions.Timeout,
                       ConnectionError, TimeoutError)):
        return True

    msg = str(e)
    if any(kw in msg for kw in (
        "RemoteDisconnected", "Connection aborted", "Connection reset",
        "Broken pipe", "Read timed out", "Max retries exceeded",
    )):
        return True

    try:
        import gspread
        if isinstance(e, gspread.exceptions.APIError):
            status = None
            try:
                status = e.response.status_code
            except Exception:
                pass
            if status in (429, 500, 502, 503, 504):
                return True
            if status in (400, 401, 403, 404):
                return False
    except ImportError:
        pass

    return False


def retry_sheets_write(fn, retries: int = 2, base_wait: float = 5, label: str = "Sheets寫入"):
    """
    執行 fn()（不帶參數的 callable，用 lambda 或 closure 包裝實際的 Sheets 操作），
    遇到可重試的暫時性錯誤時等待後重試；遇到重試也沒用的錯誤直接放棄，不浪費時間。

    回傳 fn() 的結果。重試耗盡、或遇到不可重試錯誤時，往外拋出原始例外，
    由呼叫端決定如何處理（通常是 log.warning 後放棄本次寫入，不影響主流程，
    但至少log會明確記錄是「重試過仍失敗」還是「判斷不值得重試」，方便之後排查）。
    """
    last_error = None
    for attempt in range(retries + 1):
        try:
            return fn()
        except Exception as e:
            last_error = e
            retryable = is_retryable_error(e)
            if attempt < retries and retryable:
                wait = base_wait * (attempt + 1)
                log.warning(f"{label}失敗，判斷為暫時性錯誤，{wait}秒後重試（第{attempt+1}次）: {e}")
                time.sleep(wait)
                continue
            if not retryable:
                log.warning(f"{label}失敗，判斷為非暫時性錯誤（重試也沒用），直接放棄: {e}")
            else:
                log.warning(f"{label}失敗（已重試{retries}次仍失敗，放棄）: {e}")
            raise last_error
