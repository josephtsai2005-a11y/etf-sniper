with open('main.py', 'r', encoding='utf-8') as f:
    content = f.read()

old = '''# 強制使用台灣今日日期（不受執行時間影響）
import pytz as _pytz
_tw_now = __import__("datetime").datetime.now(_pytz.timezone("Asia/Taipei"))
_today_str = _tw_now.strftime("%Y%m%d")
TRADE_DATE = os.environ.get("TRADE_DATE", _today_str)'''

new = '''# 交易日判斷：15:30 前用前一個交易日，15:30 後用今日
import pytz as _pytz
from datetime import timedelta
_tw_now = __import__("datetime").datetime.now(_pytz.timezone("Asia/Taipei"))
if _tw_now.hour < 15 or (_tw_now.hour == 15 and _tw_now.minute < 30):
    _trade_day = _tw_now - timedelta(days=1)
    # 若前一天是週日(6)或週一(0)要再往前
    while _trade_day.weekday() >= 5:
        _trade_day -= timedelta(days=1)
else:
    _trade_day = _tw_now
_today_str = _trade_day.strftime("%Y%m%d")
TRADE_DATE = os.environ.get("TRADE_DATE", _today_str)'''

if old in content:
    content = content.replace(old, new)
    print('✅ TRADE_DATE 修復成功')
else:
    print('❌ 找不到目標')

with open('main.py', 'w', encoding='utf-8') as f:
    f.write(content)
