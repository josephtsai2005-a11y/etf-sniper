f = open('main.py', encoding='utf-8')
c = f.read()
f.close()

old = '        log.info(f"{sheet_name} 寫入完成")\n        time.sleep(5)\n\n\ndef _write_institutional_to_sheets'
new = '        log.info(f"{sheet_name} 寫入完成")\n        time.sleep(15)\n\n\ndef _write_institutional_to_sheets'

if old in c:
    c = c.replace(old, new, 1)
    open('main.py', 'w', encoding='utf-8').write(c)
    print('SUCCESS')
else:
    print('ERROR')
