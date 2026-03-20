path = '/opt/XometryAnalysis/xometry-app/app.py'
with open(path, 'r') as f: content = f.read()
# Replace allow_origins=[\*] with allow_origins=[" *\]
content = content.replace('allow_origins=[\\*]', 'allow_origins=[\*\]')
with open(path, 'w') as f: f.write(content)
print('Fixed allow_origins syntax.')
