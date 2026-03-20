import re

APP_PATH = '/opt/XometryAnalysis/xometry-app/app.py'

def repair():
    with open(APP_PATH, 'r', encoding='utf-8') as f:
        content = f.read()

    # Log what we see
    if 'allow_origins=[\*]' in content:
        print('Found broken syntax: allow_origins=[\*]')
        content = content.replace('allow_origins=[\*]', 'allow_origins=[" *\]')
 else:
 print('Did not find exact string allow_origins=[\*]. Checking regex.')
 # Fallback regex
 content = re.sub(r'allow_origins=\[\\\*\]', 'allow_origins=[\*\]', content)
 
 with open(APP_PATH, 'w', encoding='utf-8') as f:
 f.write(content)
 
 print('Repaired app.py')

if __name__ == '__main__':
 repair()
