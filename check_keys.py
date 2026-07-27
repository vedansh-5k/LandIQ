import os
from pathlib import Path

p = Path(".env")
if p.exists():
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
else:
    print("!! No .env file found in this folder.")

print("=" * 60)
print("  KEY PRESENCE")
print("=" * 60)
for name in ("GROQ_API_KEY", "GOOGLE_API_KEY"):
    v = os.environ.get(name, "")
    print("  %-16s %s" % (name, ("SET (%d chars, ...%s)" % (len(v), v[-4:])) if v else "MISSING"))

print("\n" + "=" * 60)
print("  LIVE CALL TEST")
print("=" * 60)

if os.environ.get("GROQ_API_KEY"):
    try:
        from langchain_groq import ChatGroq
        g = ChatGroq(api_key=os.environ["GROQ_API_KEY"],
                     model=os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile"),
                     temperature=0.1, max_tokens=30)
        r = g.invoke([("human", "Reply with the single word: ok")])
        print("  GROQ    -> WORKS. reply=%r" % (r.content or "")[:40])
        print("           usage=%s" % (getattr(r, "usage_metadata", None),))
    except Exception as e:
        print("  GROQ    -> FAILED: %s" % str(e)[:200])
else:
    print("  GROQ    -> skipped (no key)")

if os.environ.get("GOOGLE_API_KEY"):
    for m in ("gemini-2.0-flash", "gemini-2.0-flash-001", "gemini-1.5-flash", "gemini-flash-latest"):
        try:
            from langchain_google_genai import ChatGoogleGenerativeAI
            g = ChatGoogleGenerativeAI(google_api_key=os.environ["GOOGLE_API_KEY"],
                                       model=m, temperature=0.1, max_output_tokens=30)
            r = g.invoke([("human", "Reply with the single word: ok")])
            print("  GEMINI  -> WORKS with model id '%s'. reply=%r" % (m, (r.content or "")[:40]))
            break
        except Exception as e:
            print("  GEMINI  -> '%s' rejected: %s" % (m, str(e)[:150]))
else:
    print("  GEMINI  -> skipped (no key)")

print("=" * 60)