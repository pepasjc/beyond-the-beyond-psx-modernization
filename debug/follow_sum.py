import sys, ast
rows = []
for line in sys.stdin:
    p = line.split(' ', 1)
    if p[0].isdigit() and p[1].startswith('['):
        rows.append(ast.literal_eval(p[1]))
ly = [r[0][1] for r in rows]; dy = [r[1][1] for r in rows]
print('leader steps', [b - a for a, b in zip(ly, ly[1:]) if b != a][:40])
print('dragon steps', [b - a for a, b in zip(dy, dy[1:])][:90])
print('gap', [l - d for l, d in zip(ly, dy)][1::4][:24])
