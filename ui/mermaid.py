"""Render Mermaid diagrams.

Mermaid needs an iframe to execute its module script (CSP/script-type
restrictions). st.html doesn't execute scripts; components.html does.
The deprecation warning on components.html is harmless until Streamlit's
st.iframe API ships.
"""
import streamlit.components.v1 as components


def render(code: str, height: int = 600):
    html = f"""<!DOCTYPE html>
<html>
<head>
<style>
  body {{ margin: 0; padding: 0; background: #0e0e1a; font-family: sans-serif; }}
  .container {{ background:#0e0e1a; padding:16px; }}
  pre.mermaid {{ background:transparent; margin:0; }}
</style>
</head>
<body>
<div class="container">
<pre class="mermaid">
{code}
</pre>
</div>
<script type="module">
    import mermaid from 'https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.esm.min.mjs';
    mermaid.initialize({{
        startOnLoad: true,
        theme: 'dark',
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
        flowchart: {{ curve: 'basis', padding: 16 }},
    }});
</script>
</body>
</html>"""
    components.html(html, height=height, scrolling=True)
