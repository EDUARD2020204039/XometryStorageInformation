import re

APP_PATH = '/opt/XometryAnalysis/xometry-app/app.py'

def fix_cors():
    with open(APP_PATH, 'r', encoding='utf-8') as f:
        content = f.read()

    # Find CORSMiddleware configuration and replace allow_origins
    # Pattern: allow_origins=[...]
    
    # We want to replace whatever list is there with [ *]
    # This might be multi-line, so we need dotall or careful regex
    
    # Simple search for the specific line we likely added or is default
    # allow_origins=[chrome-extension://*, http://localhost:*, ...],
    
    # Regex approach: match allow_origins=\[.*?\]
    content = re.sub(r'allow_origins=\[.*?\]', 'allow_origins=[\*\]', content, flags=re.DOTALL)
    
    # Also verify if verify_connection is not rejecting things elsewhere
    # But usually it is CORS on FastAPI level.
    
    with open(APP_PATH, 'w', encoding='utf-8') as f:
        f.write(content)
        
    print('Updated allow_origins to [\*\]')

if __name__ == '__main__':
    fix_cors()
