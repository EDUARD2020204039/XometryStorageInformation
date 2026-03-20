path = '/opt/XometryAnalysis/xometry-app/app.py'

lines = open(path).readlines()
new_lines = []
in_cors_block = False

for line in lines:
    stripped = line.strip()
    if 'app.add_middleware(' in line and 'CORSMiddleware' in lines[lines.index(line)+1]: # Heuristic
        # Verify next line has CORSMiddleware?
        # Actually, let's just find the start.
        pass
    
    # Better logic:
    if 'app.add_middleware' in line:
        in_cors_block = True
        new_lines.append('# ' + line)
        continue
        
    if in_cors_block:
        new_lines.append('# ' + line)
        if stripped.endswith(')'):
            in_cors_block = False
    else:
        new_lines.append(line)

with open(path, 'w') as f:
    f.writelines(new_lines)
    
print("Commented out app.add_middleware block (heuristic).")
