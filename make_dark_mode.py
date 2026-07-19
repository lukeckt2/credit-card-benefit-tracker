import re

with open('app/static/styles.css', 'r') as f:
    css = f.read()

# Replace root variables
css = re.sub(r'color-scheme: light;', 'color-scheme: dark;', css)
css = re.sub(r'--bg: #f8fafc;', '--bg: #0f172a;', css)
css = re.sub(r'--panel-bg: rgba\(255, 255, 255, 0.65\);', '--panel-bg: rgba(30, 41, 59, 0.65);', css)
css = re.sub(r'--panel-border: rgba\(255, 255, 255, 0.8\);', '--panel-border: rgba(255, 255, 255, 0.1);', css)
css = re.sub(r'--line: rgba\(0, 0, 0, 0.06\);', '--line: rgba(255, 255, 255, 0.1);', css)
css = re.sub(r'--line-strong: rgba\(0, 0, 0, 0.12\);', '--line-strong: rgba(255, 255, 255, 0.2);', css)
css = re.sub(r'--text: #0f172a;', '--text: #f8fafc;', css)
css = re.sub(r'--muted: #64748b;', '--muted: #94a3b8;', css)
css = re.sub(r'--danger-bg: rgba\(254, 226, 226, 0.7\);', '--danger-bg: rgba(127, 29, 29, 0.5);', css)
css = re.sub(r'--notice-bg: rgba\(209, 250, 229, 0.7\);', '--notice-bg: rgba(6, 78, 59, 0.5);', css)

# Gradients
css = re.sub(r'rgba\(219, 234, 254, 0.6\)', 'rgba(30, 58, 138, 0.4)', css) # hero gradient start
css = re.sub(r'rgba\(237, 233, 254, 0.6\)', 'rgba(76, 29, 149, 0.4)', css) # hero gradient end

# Replace hardcoded backgrounds
# rgba(255, 255, 255, X) -> rgba(30, 41, 59, X) or similar
css = re.sub(r'rgba\(255, 255, 255, ([0-9.]+)\)', r'rgba(30, 41, 59, \1)', css)

# rgba(0, 0, 0, X) -> rgba(255, 255, 255, X)
css = re.sub(r'rgba\(0, 0, 0, ([0-9.]+)\)', r'rgba(255, 255, 255, \1)', css)

# specific text colors
css = re.sub(r'color: #065f46;', 'color: #34d399;', css) # notice text
css = re.sub(r'color: #991b1b;', 'color: #f87171;', css) # error text
css = re.sub(r'color: #334155;', 'color: #cbd5e1;', css) # th text

# specific backgrounds
css = re.sub(r'background: #fff;', 'background: var(--bg);', css)

with open('app/static/styles.css', 'w') as f:
    f.write(css)

print("Dark mode applied!")
