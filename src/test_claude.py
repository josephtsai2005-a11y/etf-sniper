import os, sys
sys.path.insert(0, '.')
os.environ['ANTHROPIC_API_KEY'] = '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'

import requests
headers = {
    "x-api-key": os.environ['ANTHROPIC_API_KEY'],
    "anthropic-version": "2023-06-01",
    "content-type": "application/json",
}
body = {
    "model": "claude-sonnet-4-6",
    "max_tokens": 100,
    "messages": [{"role": "user", "content": "test"}],
}
resp = requests.post("https://api.anthropic.com/v1/messages", headers=headers, json=body, timeout=30)
data = resp.json()
print(f'status: {resp.status_code}')
print(f'keys: {data.keys()}')
print(data)
