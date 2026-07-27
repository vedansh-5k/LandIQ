"""
FIX: Guardrail offline display
Run from project root:  python fix_offline.py

Patches api.py + frontend/index.html so that:
  - Server ON  → real DeBERTa results (no change)
  - Server OFF → yellow "CANNOT ANALYZE" warning (not fake Blocked/pass-through)
"""
import shutil, re
from pathlib import Path

fixed = 0

# ═══════════════════════════════════════════════════════════════════
# FIX 1: api.py — return allowed=None when offline (not True/False)
# ═══════════════════════════════════════════════════════════════════
api = Path("api.py")
if not api.exists():
    print("ERROR: api.py not found — run from project root"); raise SystemExit(1)

src = api.read_text(encoding="utf-8")
shutil.copy2(api, api.with_suffix(".py.bak"))

OLD_API = '''    except httpx.ConnectError:
        return {"allowed": True, "processed_text": req.text, "pii_found": [],
                "blocked_reason": None, "error": "Guardrail server offline"}
    except Exception as e:
        return {"allowed": True, "processed_text": req.text, "pii_found": [],
                "blocked_reason": None, "error": "Guardrail error: %s" % str(e)}'''

NEW_API = '''    except httpx.ConnectError:
        return {"allowed": None, "processed_text": None, "pii_found": [],
                "blocked_reason": None, "error": "Guardrail server offline — start with: python guardrail_server.py",
                "model_used": None, "processing_time_ms": 0}
    except Exception as e:
        return {"allowed": None, "processed_text": None, "pii_found": [],
                "blocked_reason": None, "error": "Guardrail error: %s" % str(e),
                "model_used": None, "processing_time_ms": 0}'''

if OLD_API in src:
    src = src.replace(OLD_API, NEW_API, 1)
    api.write_text(src, encoding="utf-8")
    fixed += 1
    print("OK  api.py patched — offline now returns allowed=None")
else:
    # Try alternate match (allowed: False version)
    alt = src.replace('"allowed": False', '"allowed": True')
    if OLD_API in alt:
        # The file has allowed: False, replace that
        old_false = OLD_API.replace('"allowed": True', '"allowed": False')
        if old_false in src:
            src = src.replace(old_false, NEW_API, 1)
            api.write_text(src, encoding="utf-8")
            fixed += 1
            print("OK  api.py patched (was allowed:False) — now returns allowed=None")
        else:
            print("SKIP  api.py — could not find exact offline block to patch")
    else:
        print("SKIP  api.py — offline block not found (may already be patched)")


# ═══════════════════════════════════════════════════════════════════
# FIX 2: frontend/index.html — show yellow warning when d.error
# ═══════════════════════════════════════════════════════════════════
html_path = Path("frontend/index.html")
if not html_path.exists():
    print("ERROR: frontend/index.html not found"); raise SystemExit(1)

html = html_path.read_text(encoding="utf-8")
shutil.copy2(html_path, html_path.with_suffix(".html.bak"))

# Fix A: The BLOCKED display — check d.error FIRST
OLD_BLOCK = "if(d.allowed===false){\n      html+='<div class=\"gr-result-box blocked\"><div class=\"gr-result-box-label\">BLOCKED</div><div class=\"gr-result-box-text\">'+_escHtml(d.blocked_reason||'Blocked')+'</div></div>';\n    }else{"

NEW_BLOCK = """if(d.error){
      html+='<div class="gr-result-box blocked" style="background:#fff3cd;border-color:#ffc107"><div class="gr-result-box-label" style="color:#856404">\\u26a0 CANNOT ANALYZE</div><div class="gr-result-box-text" style="color:#856404">'+_escHtml(d.error)+'</div></div>';
    }else if(d.allowed===false){
      html+='<div class="gr-result-box blocked"><div class="gr-result-box-label">BLOCKED</div><div class="gr-result-box-text">'+_escHtml(d.blocked_reason||'Blocked')+'</div></div>';
    }else{"""

if OLD_BLOCK in html:
    html = html.replace(OLD_BLOCK, NEW_BLOCK, 1)
    fixed += 1
    print("OK  index.html Fix A — offline shows yellow warning box")
else:
    # Flexible regex match
    pat_a = re.compile(
        r"if\(d\.allowed===false\)\{\s*html\+='<div class=\"gr-result-box blocked\">"
        r"<div class=\"gr-result-box-label\">BLOCKED</div>"
        r"<div class=\"gr-result-box-text\">' *\+ *_escHtml\(d\.blocked_reason\|\|'Blocked'\) *\+ *"
        r"'</div></div>';\s*\}else\{",
        re.DOTALL
    )
    m = pat_a.search(html)
    if m:
        html = html[:m.start()] + NEW_BLOCK + html[m.end():]
        fixed += 1
        print("OK  index.html Fix A (flex) — offline shows yellow warning box")
    else:
        if "d.error" in html and "CANNOT ANALYZE" in html:
            print("SKIP  index.html Fix A — already patched")
        else:
            print("WARN  index.html Fix A — pattern not found, manual edit needed")

# Fix B: The badge — check d.error FIRST
OLD_BADGE = 'if(d.allowed===false){html+=\'<span class="gr-pii-badge pii-found">Harmful Content Blocked</span>\';}'

NEW_BADGE = """if(d.error){html+='<span class="gr-pii-badge" style="background:#fff3cd;color:#856404;border:1px solid #ffc107">\\u26a0 Guardrail Unavailable</span>';}
    else if(d.allowed===false){html+='<span class="gr-pii-badge pii-found">Harmful Content Blocked</span>';}"""

if OLD_BADGE in html:
    html = html.replace(OLD_BADGE, NEW_BADGE, 1)
    fixed += 1
    print("OK  index.html Fix B — offline badge shows yellow warning")
else:
    pat_b = re.compile(
        r"if\(d\.allowed===false\)\{html\+='"
        r'<span class="gr-pii-badge pii-found">Harmful Content Blocked</span>'
        r"';\}"
    )
    m = pat_b.search(html)
    if m:
        html = html[:m.start()] + NEW_BADGE + html[m.end():]
        fixed += 1
        print("OK  index.html Fix B (flex) — offline badge shows yellow warning")
    else:
        if "Guardrail Unavailable" in html:
            print("SKIP  index.html Fix B — already patched")
        else:
            print("WARN  index.html Fix B — pattern not found, manual edit needed")

if fixed > 0:
    html_path.write_text(html, encoding="utf-8")

print(f"\n{'='*50}")
print(f"  {fixed} fix(es) applied")
print(f"  Backups: api.py.bak, frontend/index.html.bak")
print(f"{'='*50}")
if fixed > 0:
    print("\nNow:")
    print("  1. Restart: python api.py  (or python run.py)")
    print("  2. Start guardrail server: python guardrail_server.py")
    print("  3. Ctrl+Shift+R in browser")
    print("  4. Run Test → real DeBERTa results")
    print("  5. Stop guardrail_server.py → Run Test → yellow warning")
    print("  6. That PROVES real integration to sir")
