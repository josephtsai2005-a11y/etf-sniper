with open('main.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# 找階段七的 try 開始
try_start = None
try_end = None
for i, line in enumerate(lines):
    if 'if SERPAPI_KEY:' in line and try_start is None and i > 570:
        try_start = i - 1  # try: 那行
        print(f'try 開始: {try_start+1}')
    if try_start and 'Google Trends 失敗' in line:
        try_end = i + 1
        print(f'try 結束: {try_end+1}')
        break

# 在 try_start 前插入 if RUN_MODE != "inst":
# 縮排整個 try 區塊
new_lines = lines[:try_start]
new_lines.append('    if RUN_MODE != "inst":\n')

for line in lines[try_start:try_end]:
    if line.strip():
        new_lines.append('    ' + line)
    else:
        new_lines.append(line)

new_lines.extend(lines[try_end:])

with open('main.py', 'w', encoding='utf-8') as f:
    f.writelines(new_lines)

print('完成')
