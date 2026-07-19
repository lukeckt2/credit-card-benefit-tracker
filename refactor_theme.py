import re
import os

os.system('git checkout app/static/styles.css')

with open('app/static/styles.css', 'r') as f:
    css = f.read()

# We will define a bunch of CSS variables in :root
# First, let's extract :root block and add the new variables.

root_vars_light = """
  color-scheme: light;
  --bg: #f8fafc;
  --panel-bg: rgba(255, 255, 255, 0.65);
  --panel-border: rgba(255, 255, 255, 0.8);
  --panel-border-hover: rgba(59, 130, 246, 0.4);
  --glass-blur: blur(24px);
  --line: rgba(0, 0, 0, 0.06);
  --line-strong: rgba(0, 0, 0, 0.12);
  --text: #0f172a;
  --muted: #64748b;
  --accent: #3b82f6;
  --accent-gradient: linear-gradient(135deg, #3b82f6, #8b5cf6);
  --accent-glow: rgba(59, 130, 246, 0.25);
  --green: #10b981;
  --orange: #f59e0b;
  --red: #ef4444;
  --danger-bg: rgba(254, 226, 226, 0.7);
  --notice-bg: rgba(209, 250, 229, 0.7);

  /* New theme variables */
  --hero-grad-1: rgba(219, 234, 254, 0.6);
  --hero-grad-2: rgba(237, 233, 254, 0.6);
  --card-bg-40: rgba(255, 255, 255, 0.4);
  --card-bg-50: rgba(255, 255, 255, 0.5);
  --card-bg-70: rgba(255, 255, 255, 0.7);
  --card-bg-80: rgba(255, 255, 255, 0.8);
  --hover-dim: rgba(0, 0, 0, 0.02);
  --dim-bg-03: rgba(0, 0, 0, 0.03);
  --dim-bg-05: rgba(0, 0, 0, 0.05);
  --text-notice: #065f46;
  --text-error: #991b1b;
  --text-th: #334155;
  --inactive-bg: rgba(15, 23, 42, 0.04);
  --inactive-row-bg: rgba(15, 23, 42, 0.02);
"""

root_vars_dark = """
[data-theme="dark"] {
  color-scheme: dark;
  --bg: #0f172a;
  --panel-bg: rgba(30, 41, 59, 0.65);
  --panel-border: rgba(255, 255, 255, 0.1);
  --panel-border-hover: rgba(59, 130, 246, 0.4);
  --glass-blur: blur(24px);
  --line: rgba(255, 255, 255, 0.1);
  --line-strong: rgba(255, 255, 255, 0.2);
  --text: #f8fafc;
  --muted: #94a3b8;
  --accent: #3b82f6;
  --accent-gradient: linear-gradient(135deg, #3b82f6, #8b5cf6);
  --accent-glow: rgba(59, 130, 246, 0.25);
  --green: #10b981;
  --orange: #f59e0b;
  --red: #ef4444;
  --danger-bg: rgba(127, 29, 29, 0.5);
  --notice-bg: rgba(6, 78, 59, 0.5);

  --hero-grad-1: rgba(30, 58, 138, 0.4);
  --hero-grad-2: rgba(76, 29, 149, 0.4);
  --card-bg-40: rgba(30, 41, 59, 0.4);
  --card-bg-50: rgba(30, 41, 59, 0.5);
  --card-bg-70: rgba(30, 41, 59, 0.7);
  --card-bg-80: rgba(30, 41, 59, 0.8);
  --hover-dim: rgba(255, 255, 255, 0.02);
  --dim-bg-03: rgba(255, 255, 255, 0.03);
  --dim-bg-05: rgba(255, 255, 255, 0.05);
  --text-notice: #34d399;
  --text-error: #f87171;
  --text-th: #cbd5e1;
  --inactive-bg: rgba(30, 41, 59, 0.2);
  --inactive-row-bg: rgba(30, 41, 59, 0.15);
}
"""

css = re.sub(r':root\s*\{[^}]+\}', f":root {{{root_vars_light}}}\n\n{root_vars_dark}", css)

# Replace all hardcoded values with the variables
css = css.replace('rgba(219, 234, 254, 0.6)', 'var(--hero-grad-1)')
css = css.replace('rgba(237, 233, 254, 0.6)', 'var(--hero-grad-2)')

css = css.replace('rgba(255, 255, 255, 0.8)', 'var(--card-bg-80)')
css = css.replace('rgba(255, 255, 255, 0.7)', 'var(--card-bg-70)')
css = css.replace('rgba(255, 255, 255, 0.5)', 'var(--card-bg-50)')
css = css.replace('rgba(255, 255, 255, 0.4)', 'var(--card-bg-40)')

css = css.replace('rgba(0, 0, 0, 0.02)', 'var(--hover-dim)')
css = css.replace('rgba(0, 0, 0, 0.03)', 'var(--dim-bg-03)')
css = css.replace('rgba(0, 0, 0, 0.05)', 'var(--dim-bg-05)')

css = css.replace('color: #065f46;', 'color: var(--text-notice);')
css = css.replace('color: #991b1b;', 'color: var(--text-error);')
css = css.replace('color: #334155;', 'color: var(--text-th);')

# Inactive overrides manually:
css = re.sub(r'&\.is-inactive\s*\{\s*opacity:\s*0\.75;\s*filter:\s*grayscale\(0\.4\);\s*\}',
             '&.is-inactive {\n    background: var(--inactive-bg);\n    opacity: 0.8;\n    filter: grayscale(0.4);\n  }', css)

css = re.sub(r'& tbody:has\(tr:hover\) tr:not\(:hover\)\s*\{\s*opacity:\s*0\.65;\s*filter:\s*grayscale\(0\.3\);\s*\}',
             '& tbody:has(tr:hover) tr:not(:hover) {\n    background-color: var(--inactive-row-bg);\n    opacity: 0.7;\n    filter: grayscale(0.5);\n  }', css)


with open('app/static/styles.css', 'w') as f:
    f.write(css)

print("CSS refactored for theme toggle!")
