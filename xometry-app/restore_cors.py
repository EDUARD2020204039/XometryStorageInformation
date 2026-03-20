path = '/opt/XometryAnalysis/xometry-app/app.py'
lines = open(path).readlines()
with open(path, 'w') as f:
    for line in lines:
        if line.strip().startswith('# app.add_middleware'):
            f.write(line.replace('# ', ''))
        elif line.strip().startswith('#     CORSMiddleware'):
            f.write(line.replace('# ', ''))
        elif line.strip().startswith('#     allow_'):
             f.write(line.replace('# ', ''))
        elif line.strip().startswith('# )'):
             f.write(line.replace('# ', ''))
        else:
             f.write(line)
print('Restored (attempted).')
