with open('app.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 在 sidebar 最上面加入 CSS 隱藏分隔線的 radio button
old = 'with st.sidebar:'
new = '''# 隱藏分隔線的 radio button
st.markdown("""
<style>
div[data-testid="stRadio"] label:has(p:contains("──")) {
    pointer-events: none;
    opacity: 0.6;
    font-weight: bold;
    font-size: 0.85em;
    color: gray;
}
div[data-testid="stRadio"] label:has(p:contains("──")) div[data-testid="stMarkdownContainer"] {
    display: none;
}
div[data-testid="stRadio"] div:has(label p:contains("──")) input {
    display: none !important;
}
</style>
""", unsafe_allow_html=True)

with st.sidebar:'''

if old in content:
    content = content.replace(old, new, 1)
    print('✅ CSS 加入成功')
else:
    print('❌ 找不到')

with open('app.py', 'w', encoding='utf-8') as f:
    f.write(content)
