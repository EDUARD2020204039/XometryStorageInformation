path = '/opt/XometryAnalysis/xometry-app/app.py'

print(f"Reading {path}...")
lines = open(path).readlines()

main_lines = []
other_lines = []
in_main = False

for line in lines:
    if 'if __name__ == "__main__":' in line or "if __name__ == '__main__':" in line:
        in_main = True
        main_lines.append(line)
        continue
    
    if in_main:
        # Simple heuristic: if line starts with space/tab or is empty, it belongs to main block
        # Or if it starts with 'u' (uvicorn) or 'i' (import) inside block (if not indented?)
        # Usually it's indented.
        if line.strip() == '':
            main_lines.append(line)
        elif line.startswith(' ') or line.startswith('\t'):
            main_lines.append(line)
        else:
            in_main = False
            other_lines.append(line)
    else:
        other_lines.append(line)

print(f"Found {len(main_lines)} lines in main block.")
if len(main_lines) == 0:
    print("Main block not found or empty.")
else:   
    new_content = ''.join(other_lines).rstrip() + '\n\n' + ''.join(main_lines)
    with open(path, 'w') as f:
        f.write(new_content)
    print("Moved main block to end.")
