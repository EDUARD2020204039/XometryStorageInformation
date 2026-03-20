path = '/opt/XometryAnalysis/xometry-app/app.py'
lines = open(path).readlines()

# Identify lines belonging to if __name__ == '__main__': block
# Usually it's:
# if __name__ ==  __main__:
#     import uvicorn
#     uvicorn.run(...)

main_block = []
other_lines = []

in_main = False
for line in lines:
    if 'if __name__ == \__main__\:' in line or \if __name__ == __main__ :\ in line:
        in_main = True
        main_block.append(line)
    elif in_main:
        # Assume indentation implies block membership or specific uvicorn calls
        if line.strip().startswith('import uvicorn') or line.strip().startswith('uvicorn.run'):
             main_block.append(line)
        elif line.strip() == '': # Empty lines in block
             main_block.append(line)
        else:
             # End of block?
             if line.startswith(' '): # indented
                 main_block.append(line)
             else:
                 in_main = False
                 other_lines.append(line)
    else:
        other_lines.append(line)

# Reconstruct
new_content = ''.join(other_lines) + '\n' + ''.join(main_block)

with open(path, 'w') as f:
    f.write(new_content)

print(f'Moved {len(main_block)} lines to the end.')
