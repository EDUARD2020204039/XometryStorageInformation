path = '/opt/XometryAnalysis/xometry-app/app.py'
lines = open(path).readlines()
with open(path, 'w') as f:
    for line in lines:
        if 'allow_origins=' in line:
            f.write('    allow_origins=[" *\],\n')
 else:
 f.write(line)
print('Fixed allow_origins line cleanly.')
