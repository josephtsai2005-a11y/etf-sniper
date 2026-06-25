import re

with open('main.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# 找階段六和六.五的行號
stage6_start = None
stage65_start = None
stage7_start = None

for i, line in enumerate(lines):
    if '階段六：三大法人' in line:
        stage6_start = i
    if '階段六.五：基本面' in line:
        stage65_start = i
    if '階段七：Google Trends' in line:
        stage7_start = i

print(f'階段六開始: {stage6_start+1}')
print(f'階段六.五開始: {stage65_start+1}')
print(f'階段七開始: {stage7_start+1}')

# 切出各段
block6 = lines[stage6_start:stage65_start]
block65 = lines[stage65_start:stage7_start]

# 重組：六.五 → 六 → 七
new_lines = lines[:stage6_start] + block65 + block6 + lines[stage7_start:]

with open('main.py', 'w', encoding='utf-8') as f:
    f.writelines(new_lines)

print('✅ 順序修復完成')
