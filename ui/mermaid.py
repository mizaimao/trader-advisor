"""Render Mermaid diagrams.

Mermaid needs an iframe to execute its module script (CSP/script-type
restrictions). st.html doesn't execute scripts; components.html does.

Implementation notes:
- `startOnLoad: false` + explicit `mermaid.run()` is the modern pattern
  recommended over `startOnLoad: true`, which had reliability issues in
  iframe contexts where the script may run before the DOM is fully parsed.
- Pinning mermaid 11 (current as of 2026); 10 had occasional rendering
  hangs in some browsers/Streamlit combos that left empty placeholders.
- `htmlLabels: true` enables `<br/>` line breaks inside node labels.
- The post-render SVG is constrained to container width so it doesn't
  overflow the iframe.
"""
import streamlit.components.v1 as components


def render(code: str, height: int = 600):
    html = f"""<!DOCTYPE html>
<html>
<head>
<style>
  body {{ margin: 0; padding: 0; background: #0e0e1a; font-family: sans-serif; }}
  .container {{ background:#0e0e1a; padding:16px; }}
  .mermaid {{ background:transparent; margin:0; text-align: center; }}
  .mermaid svg {{ max-width: 100%; height: auto; }}
  .mermaid-error {{ color: #ff6b6b; font-family: monospace; padding: 12px;
                   background: rgba(255,107,107,0.08); border-radius: 6px;
                   white-space: pre-wrap; }}
</style>
</head>
<body>
<div class="container">
<pre class="mermaid">
{code}
</pre>
</div>
<script type="module">
    import mermaid from 'https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.esm.min.mjs';
    mermaid.initialize({{
        startOnLoad: false,
        theme: 'dark',
        securityLevel: 'loose',
        themeVariables: {{
            primaryColor: '#1a1a2e',
            primaryTextColor: '#e8e8e8',
            primaryBorderColor: '#4a90d9',
            lineColor: '#7ab8f5',
            secondaryColor: '#232342',
            tertiaryColor: '#1a1a2e',
            background: '#0e0e1a',
            mainBkg: '#1a1a2e',
            secondBkg: '#232342',
        }},
        flowchart: {{ curve: 'basis', padding: 16, htmlLabels: true }},
    }});
    try {{
        await mermaid.run({{ querySelector: '.mermaid' }});
    }} catch (err) {{
        const el = document.querySelector('.mermaid');
        if (el) {{
            el.outerHTML = '<div class="mermaid-error">Mermaid render failed: '
                + (err && err.message ? err.message : String(err)) + '</div>';
        }}
    }}
</script>
</body>
</html>"""
    components.html(html, height=height, scrolling=True)
