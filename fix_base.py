with open('templates/base.html', 'r', encoding='utf-8') as f:
    lines = f.readlines()

print(f'Total lines: {len(lines)}')

# Find the two extra_scripts lines
indices = [i for i, l in enumerate(lines) if 'extra_scripts' in l]
print(f'extra_scripts at lines: {[i+1 for i in indices]}')

if len(indices) == 2:
    # Keep everything up to and including the first extra_scripts (index indices[0])
    # then just the closing </html>
    kept = lines[:indices[0]+1]
    kept.append('\n</html>\n')
    with open('templates/base.html', 'w', encoding='utf-8') as f:
        f.writelines(kept)
    print(f'Fixed. New total lines: {len(kept)}')
else:
    print('Nothing to fix or unexpected structure.')
