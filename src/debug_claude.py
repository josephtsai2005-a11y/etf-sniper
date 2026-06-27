import os, requests
os.environ['ANTHROPIC_API_KEY'] = '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'

from ai_analyzer import call_claude
result = call_claude("hello, reply in one word")
print(f'result: {repr(result)}')
