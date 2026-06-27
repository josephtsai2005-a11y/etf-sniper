import os, requests
key = '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'
headers = {
    'x-api-key': key,
    'anthropic-version': '2023-06-01',
    'content-type': 'application/json',
}
body = {
    'model': 'claude-sonnet-4-6',
    'max_tokens': 100,
    'messages': [{'role': 'user', 'content': 'test'}],
}
resp = requests.post('https://api.anthropic.com/v1/messages', headers=headers, json=body, timeout=30)
data = resp.json()
print(f'status: {resp.status_code}')
print(data)
