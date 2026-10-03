import os
import re
import urllib.request

headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
}

os.makedirs('app/static/fonts', exist_ok=True)

queries = [
    ('Instrument Serif', 'https://fonts.googleapis.com/css2?family=Instrument+Serif:ital@0;1&display=swap'),
    ('Inter', 'https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&display=swap'),
    ('JetBrains Mono', 'https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500&display=swap'),
]

downloaded_faces = []

for family, url in queries:
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req) as resp:
        css = resp.read().decode('utf-8')
    
    # Split into blocks
    raw_blocks = css.split('@font-face')
    for raw in raw_blocks[1:]:
        # Filter for latin subset
        if '/* latin */' in raw or 'U+0000-00FF' in raw:
            fam_match = re.search(r'font-family:\s*[\'"]?([^\'";]+)[\'"]?', raw)
            style_match = re.search(r'font-style:\s*([^;]+);', raw)
            weight_match = re.search(r'font-weight:\s*([^;]+);', raw)
            src_match = re.search(r'src:\s*url\((https://[^)]+\.woff2)\)', raw)
            display_match = re.search(r'font-display:\s*([^;]+);', raw)
            range_match = re.search(r'unicode-range:\s*([^;]+);', raw)

            if fam_match and src_match:
                fam = fam_match.group(1).strip()
                style = style_match.group(1).strip() if style_match else 'normal'
                weight = weight_match.group(1).strip() if weight_match else '400'
                src_url = src_match.group(1).strip()
                disp = display_match.group(1).strip() if display_match else 'swap'
                urange = range_match.group(1).strip() if range_match else ''

                # Generate clean filename
                clean_fam = fam.lower().replace(' ', '-')
                filename = f"{clean_fam}-{weight}{'-italic' if style == 'italic' else ''}.woff2"
                filepath = os.path.join('app/static/fonts', filename)

                print(f"Downloading {fam} ({weight}, {style}) -> {filename} ...")
                urllib.request.urlretrieve(src_url, filepath)

                downloaded_faces.append({
                    'family': fam,
                    'style': style,
                    'weight': weight,
                    'filename': filename,
                    'display': disp,
                    'range': urange
                })

# Generate fonts.css
css_lines = []
for face in downloaded_faces:
    css_lines.append(f"""@font-face {{
  font-family: '{face['family']}';
  font-style: {face['style']};
  font-weight: {face['weight']};
  font-display: {face['display']};
  src: url('/static/fonts/{face['filename']}') format('woff2');
  unicode-range: {face['range']};
}}""")

fonts_css_content = '\n\n'.join(css_lines) + '\n'
with open('app/static/fonts/fonts.css', 'w', encoding='utf-8') as f:
    f.write(fonts_css_content)

print(f"Successfully downloaded {len(downloaded_faces)} font files and generated app/static/fonts/fonts.css")
