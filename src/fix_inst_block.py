with open('main.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# 找階段五的 try 開始和 news 模式結束
try_start = None
news_end = None
for i, line in enumerate(lines):
    if '# 抓取最新新聞' in line and try_start is None:
        try_start = i
    if 'RUN_MODE=news，新聞階段完成' in line:
        news_end = i + 3  # 包含 return
        break

print(f'try 開始: {try_start+1}, news 結束: {news_end+1}')

# 在 try_start 前插入 if RUN_MODE != "inst":
# 並縮排整個區塊
new_lines = lines[:try_start-1]  # 保留到 try: 之前
new_lines.append('    if RUN_MODE != "inst":\n')
new_lines.append('      try:\n')

# 把 try 到 news_end 的內容縮排
for line in lines[try_start:news_end]:
    if line.strip():
        new_lines.append('  ' + line)
    else:
        new_lines.append(line)

new_lines.append('    else:\n')
new_lines.append('        log.info("RUN_MODE=inst，跳過新聞/Trends，直接執行法人")\n')
new_lines.extend(lines[news_end:])

with open('main.py', 'w', encoding='utf-8') as f:
    f.writelines(new_lines)
print('完成')
