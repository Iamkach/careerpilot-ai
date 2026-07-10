#!/usr/bin/env python3
"""Build a self-contained, print-to-PDF HTML report from architecture-analysis.md.

The Markdown is base64-embedded (bulletproof for emoji/unicode) and rendered in the
browser with marked.js + mermaid.js (CDN). Re-run after editing the .md:

    python docs/architecture/build_report.py
"""
import base64
import pathlib

HERE = pathlib.Path(__file__).parent
MD = (HERE / "architecture-analysis.md").read_text(encoding="utf-8")
B64 = base64.b64encode(MD.encode("utf-8")).decode("ascii")

HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AI Job Search Pipeline — Architecture Analysis</title>
<script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.min.js"></script>
<style>
  :root{
    --bg:#ffffff; --fg:#1f2733; --muted:#5b6675; --line:#e3e8ef;
    --brand:#2f6fed; --chip:#eef3fb; --code:#0f172a; --codebg:#f5f7fb;
    --topbar:#141b2b; --sidebar:270px; --maxw:900px;
  }
  *{box-sizing:border-box}
  html{scroll-behavior:smooth}
  body{margin:0;background:#eef1f6;color:var(--fg);
    font:16px/1.62 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;}
  /* top bar */
  .topbar{position:sticky;top:0;z-index:50;background:var(--topbar);color:#eaf0fb;
    display:flex;align-items:center;justify-content:space-between;padding:10px 20px;
    box-shadow:0 1px 0 rgba(0,0,0,.2)}
  .topbar b{font-weight:700}
  .topbar .hint{font-size:.8rem;color:#a9b6cf}
  .layout{display:flex;max-width:calc(var(--sidebar) + var(--maxw) + 80px);margin:0 auto;gap:28px;padding:0 20px}
  /* toc */
  nav.toc{width:var(--sidebar);flex:0 0 var(--sidebar);position:sticky;top:56px;align-self:flex-start;
    max-height:calc(100vh - 72px);overflow:auto;padding:18px 6px 40px;font-size:.85rem}
  nav.toc h4{margin:.2em 0 .5em;text-transform:uppercase;letter-spacing:.08em;font-size:.7rem;color:var(--muted)}
  nav.toc a{display:block;color:#41506a;text-decoration:none;padding:3px 8px;border-radius:6px;line-height:1.35}
  nav.toc a:hover{background:var(--chip);color:var(--brand)}
  nav.toc a.l1{font-weight:700;margin-top:10px;color:#1b2740}
  nav.toc a.l2{padding-left:18px}
  nav.toc a.l3{padding-left:30px;color:#68738a;font-size:.8rem}
  /* article */
  main{flex:1 1 auto;min-width:0;background:var(--bg);margin:24px 0 60px;padding:14px 46px 60px;
    border-radius:14px;box-shadow:0 2px 24px rgba(20,30,50,.08)}
  h1,h2,h3,h4{line-height:1.25;font-weight:700;letter-spacing:-.01em}
  main>h1:first-child{font-size:2.1rem;margin:.6em 0 .1em;background:linear-gradient(90deg,#2f6fed,#7b3fe4);
    -webkit-background-clip:text;background-clip:text;-webkit-text-fill-color:transparent}
  h1{font-size:1.75rem;margin:1.4em 0 .3em;padding-top:.5em;border-top:4px solid var(--line)}
  h2{font-size:1.4rem;margin:1.6em 0 .2em}
  h3{font-size:1.14rem;margin:1.3em 0 .2em;color:#2b3648}
  h4{font-size:1rem;margin:1.1em 0 .2em;color:var(--muted)}
  p{margin:.6em 0}
  a{color:var(--brand);text-decoration:none}
  a:hover{text-decoration:underline}
  hr{border:none;border-top:1px solid var(--line);margin:2em 0}
  code{font-family:"SF Mono",ui-monospace,"Cascadia Code",Consolas,monospace;font-size:.84em;
    background:var(--codebg);padding:.1em .38em;border-radius:5px;color:var(--code)}
  blockquote{margin:1em 0;padding:10px 16px;border-left:4px solid var(--brand);background:var(--chip);
    border-radius:0 10px 10px 0;color:#2b3648}
  blockquote p{margin:.3em 0}
  table{border-collapse:collapse;width:100%;margin:1em 0;font-size:.86rem;display:block;overflow-x:auto}
  th,td{border:1px solid var(--line);padding:7px 10px;text-align:left;vertical-align:top}
  th{background:var(--chip);font-weight:600;white-space:nowrap}
  tr:nth-child(even) td{background:#fafbfd}
  .mermaid{display:flex;justify-content:center;margin:1.1em 0;padding:16px;background:#fcfdff;
    border:1px solid var(--line);border-radius:12px;overflow-x:auto}
  .mermaid svg{max-width:100%;height:auto}
  .mermaid *{animation:none !important} /* kill edge-dash animation: static + print-friendly */
  ul,ol{padding-left:1.3em}
  li{margin:.2em 0}
  /* print */
  @media print{
    body{background:#fff}
    .topbar,nav.toc{display:none !important}
    .layout{display:block;max-width:none;padding:0}
    main{box-shadow:none;margin:0;padding:0;border-radius:0}
    main>h1{-webkit-text-fill-color:#2f6fed}
    h1{page-break-before:always;border-top:none}
    main>h1:first-child{page-break-before:avoid}
    .mermaid,table,blockquote{page-break-inside:avoid}
    a{color:#1b2740}
  }
  @media (max-width:820px){ nav.toc{display:none} main{padding:14px 18px 40px} }
</style>
</head>
<body>
  <div class="topbar">
    <b>Architecture Analysis &middot; AI Job Search Pipeline</b>
    <span class="hint">Print to PDF: Ctrl/Cmd + P &rarr; Save as PDF</span>
  </div>
  <div class="layout">
    <nav class="toc" id="toc"><h4>Contents</h4></nav>
    <main id="content">Rendering&hellip;</main>
  </div>
  <script id="md" type="text/plain">%%B64%%</script>
  <script>
    (async function(){
      const b64 = document.getElementById('md').textContent.trim();
      const bytes = Uint8Array.from(atob(b64), c=>c.charCodeAt(0));
      const md = new TextDecoder('utf-8').decode(bytes);
      marked.setOptions({gfm:true, breaks:false});
      const content = document.getElementById('content');
      content.innerHTML = marked.parse(md);
      // convert ```mermaid fences into <pre class="mermaid"> for mermaid.run()
      content.querySelectorAll('pre > code.language-mermaid').forEach(code=>{
        const pre = document.createElement('pre');
        pre.className = 'mermaid';
        pre.textContent = code.textContent;
        code.parentElement.replaceWith(pre);
      });
      // slugged ids + TOC from h1/h2/h3
      const toc = document.getElementById('toc');
      let n=0;
      content.querySelectorAll('h1,h2,h3').forEach(h=>{
        if(!h.id){ h.id = 'h'+(n++); }
        const a = document.createElement('a');
        a.href = '#'+h.id;
        a.textContent = h.textContent.replace(/\\s*<a.*/,'');
        a.className = 'l'+h.tagName[1];
        toc.appendChild(a);
      });
      mermaid.initialize({startOnLoad:false, theme:'default', securityLevel:'loose',
        flowchart:{htmlLabels:true, useMaxWidth:true, curve:'basis'},
        er:{useMaxWidth:true}, sequence:{useMaxWidth:true}, gantt:{useMaxWidth:true}});
      try { await mermaid.run({querySelector:'.mermaid'}); }
      catch(e){ console.error('mermaid', e); }
    })();
  </script>
</body>
</html>
"""

out = HTML.replace("%%B64%%", B64)
(HERE / "architecture-analysis.html").write_text(out, encoding="utf-8")
print("wrote architecture-analysis.html ({} KB from {} KB markdown)".format(
    len(out)//1024, len(MD)//1024))
