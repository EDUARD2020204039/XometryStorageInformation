import re

path = '/opt/XometryAnalysis/xometry-app/app.py'

print(f"Reading {path}...")
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

# Construct the safe string: allow_origins=["*"],
# We match ANY allow_origins=... line
# Indentation seems to be 4 spaces based on previous greps
safe_line = '    allow_origins=[' + chr(34) + chr(42) + chr(34) + '],'

print(f"Replacing with: {safe_line.strip()}")

# Regex to find the line. allow_origins=\[.*?\] might span lines, but let's assume one line or use dotall
# Check what we have currently: allow_origins=[" *], (invalid)
# Regex: allow_origins=\[.*?\] should match it.
content_new = re.sub(r'allow_origins=\[.*?\]', safe_line.strip(), content, flags=re.DOTALL)

# But wait, my manual indented string vs regex replacement.
# If I replace just the list part:
content_new = re.sub(r'allow_origins=\[.*?\],', safe_line + ',', content)
# Wait, the comma might be matched or not.
# Let's replace the Whole line.
content_new = re.sub(r'.*allow_origins=.*', safe_line, content)

with open(path, 'w', encoding='utf-8') as f:
    f.write(content_new)

print("Write complete.")
