with open('diff_analyzer.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

for i, line in enumerate(lines):
    if 'dates = sorted(df[date_col].unique())[-days:]' in line:
        print(f'找到第 {i+1} 行')
        lines.insert(i, '        df[date_col] = df[date_col].astype(str).str.replace("-","")\n')
        print('✅ 插入成功')
        break

with open('diff_analyzer.py', 'w', encoding='utf-8') as f:
    f.writelines(lines)
