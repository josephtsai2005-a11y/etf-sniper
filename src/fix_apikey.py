with open('ai_analyzer.py', 'r', encoding='utf-8') as f:
    content = f.read()

old = '''def call_claude(prompt, system="", max_tokens=2000):
    if not ANTHROPIC_API_KEY:
        log.warning("缺少 ANTHROPIC_API_KEY")
        return ""
    headers = {
        "x-api-key": ANTHROPIC_API_KEY,'''

new = '''def call_claude(prompt, system="", max_tokens=2000):
    api_key = os.environ.get("ANTHROPIC_API_KEY", ANTHROPIC_API_KEY)
    if not api_key:
        log.warning("缺少 ANTHROPIC_API_KEY")
        return ""
    headers = {
        "x-api-key": api_key,'''

if old in content:
    content = content.replace(old, new)
    print('✅ 修復成功')
else:
    print('❌ 找不到')

with open('ai_analyzer.py', 'w', encoding='utf-8') as f:
    f.write(content)
