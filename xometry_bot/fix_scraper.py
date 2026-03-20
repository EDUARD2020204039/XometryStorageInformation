
path = '/home/saladin/xometry_bot/scraper.py'
try:
    with open(path, 'r') as f:
        s = f.read()
    
    # Fix the corruption and apply the desired change
    s = s.replace('credentials: .omit.', 'credentials: "omit"')
    s = s.replace('credentials: "include"', 'credentials: "omit"')
    
    with open(path, 'w') as f:
        f.write(s)
    print("Successfully patched scraper.py")
except Exception as e:
    print(f"Error: {e}")
