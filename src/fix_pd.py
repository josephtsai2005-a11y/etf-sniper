f = open('main.py', encoding='utf-8')
c = f.read()
f.close()
# 移除重複的 import pandas
import re
c = re.sub(r'(import pandas as pd\s*\n){2,}', 'import pandas as pd\n', c)
open('main.py', 'w', encoding='utf-8').write(c)
print('fixed, pd count:', c.count('import pandas as pd'))
