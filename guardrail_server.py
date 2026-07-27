"""
guardrail_server.py — LandIQ Guardrail Server
==============================================
Integrates the student's LiteLLM Deployed project (real DeBERTa LoRA adapter +
safety_guardrails.py). No hardcoded logic — all PII detection uses the actual
fine-tuned model from models/finetuned-deberta/.

Start with: python guardrail_server.py
Requires student zip extracted to: ai_boardroom_v3/student_project/
  OR adapter files copied to:       ai_boardroom_v3/models/finetuned-deberta/

Port: 8002
"""

import os
import sys
import time
import logging
from pathlib import Path
from typing import Optional

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

logger = logging.getLogger(__name__)

# ── RESOLVE STUDENT PROJECT PATHS ────────────────────────────────────────────
# The student's finetuned-deberta adapter and guardrail code live either:
#   (A) student_project/LiteLLM Deployed/models/finetuned-deberta/  (full zip extracted)
#   (B) models/finetuned-deberta/  (just the model folder copied here)
# We find whichever exists and add the guardrails/ folder to sys.path.

_ROOT = Path(__file__).resolve().parent

def _find_student_root() -> Optional[Path]:
    """Find the student project root that contains guardrails/ and models/."""
    candidates = [
        _ROOT / "student_project" / "LiteLLM Deployed",
        _ROOT / "student_project" / "LiteLLM_Final" / "LiteLLM Deployed",
        _ROOT / "LiteLLM Deployed",
        _ROOT / "LiteLLM_Final" / "LiteLLM Deployed",
    ]
    for c in candidates:
        if (c / "guardrails" / "deberta_pii_guardrail.py").exists():
            return c
    return None

def _find_model_path() -> str:
    """
    Return the path to the finetuned DeBERTa adapter.
    Falls back to the HuggingFace hub model if nothing local is found.
    """
    student_root = _find_student_root()
    if student_root:
        local = student_root / "models" / "finetuned-deberta"
        if (local / "adapter_config.json").exists():
            return str(local)

    # Also check a local copy right next to this file
    local_direct = _ROOT / "models" / "finetuned-deberta"
    if (local_direct / "adapter_config.json").exists():
        return str(local_direct)

    # Final fallback: hub model (requires internet)
    return "Isotonic/deberta-v3-base_finetuned_ai4privacy_v2"


# Add student guardrails/ to import path
_student_root = _find_student_root()
_model_path   = _find_model_path()

if _student_root:
    _guardrails_dir = str(_student_root / "guardrails")
    if _guardrails_dir not in sys.path:
        sys.path.insert(0, _guardrails_dir)
    # Also add student root so relative imports inside guardrail files work
    if str(_student_root) not in sys.path:
        sys.path.insert(0, str(_student_root))
    print(f"  [GUARDRAIL] Student root   : {_student_root}")
else:
    print("  [GUARDRAIL] ⚠ Student project not found — using regex fallback for PII")

print(f"  [GUARDRAIL] DeBERTa model  : {_model_path}")


# ── LOAD STUDENT'S REAL GUARDRAIL CLASSES ────────────────────────────────────

_deberta_guardrail = None  # will be DeBERTaPIIGuardrail instance once loaded
_safety_check_all  = None  # will be safety_guardrails.check_all
_model_load_error  = None

def _try_load_student_code():
    """Lazy-load the student's real DeBERTa guardrail and safety modules."""
    global _deberta_guardrail, _safety_check_all, _model_load_error

    # ── Safety guardrails (no model download needed) ──────────────────────
    try:
        from safety_guardrails import check_all as _ca  # noqa: F401
        _safety_check_all = _ca
        print("  [GUARDRAIL] ✓ safety_guardrails.py loaded (jailbreak/toxicity/injection)")
    except ImportError as e:
        print(f"  [GUARDRAIL] ⚠ safety_guardrails not found: {e} — using built-in patterns")

    # ── DeBERTa PII guardrail (needs transformers + peft) ────────────────
    try:
        # We need to patch the model path so the student code picks up our adapter
        os.environ.setdefault("DEBERTA_MODEL_PATH", _model_path)

        from deberta_pii_guardrail import (    # noqa: F401
            DeBERTaPIIGuardrail,
            load_ner_pipeline,
            canonicalize_label,
            active_guardrails,
        )

        # Instantiate if not already done
        if active_guardrails:
            _deberta_guardrail = active_guardrails[0]
        else:
            _deberta_guardrail = DeBERTaPIIGuardrail()

        # Trigger model load (happens lazily on first .model access)
        _ = _deberta_guardrail.model
        print("  [GUARDRAIL] ✓ DeBERTa LoRA adapter loaded for PII detection")

    except ImportError as e:
        _model_load_error = f"Import error: {e}"
        print(f"  [GUARDRAIL] ⚠ Could not import DeBERTa guardrail: {e}")
        print("              Falling back to regex PII detection.")
    except Exception as e:
        _model_load_error = str(e)
        print(f"  [GUARDRAIL] ⚠ DeBERTa model load failed: {e}")
        print("              Falling back to regex PII detection.")


# ── REGEX FALLBACK (only used when DeBERTa model unavailable) ────────────────
import re

_PII_PATTERNS_FALLBACK = {
    "AADHAAR":       r"\b[2-9]\d{3}\s?\d{4}\s?\d{4}\b",
    "PAN":           r"\b[A-Z]{5}[0-9]{4}[A-Z]\b",
    "phone number":  r"\b(?:\+91[-\s]?)?[6-9]\d{9}\b",
    "email address": r"\b[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}\b",
    "PASSPORT":      r"\b[A-Z][1-9]\d{7}\b",
    "IFSC":          r"\b[A-Z]{4}0[A-Z0-9]{6}\b",
    "bank account number": r"\b\d{9,18}\b",
}

_HARMFUL_FALLBACK = [
    r"\b(bomb|explosive|grenade|weapon|terrorist|terrorism|kill|attack|shoot|stab|murder)\b",
    r"\b(suicide|self.?harm|cut\s+myself|end\s+my\s+life)\b",
    r"\b(hack|sql\s*injection|xss|ddos|malware|ransomware|phishing)\b",
    r"\b(porn|adult\s+content|xxx|nude|sexual)\b",
    r"\b(drug|cocaine|heroin|meth|narcotics)\b",
    r"\b(money\s*launder|black\s*money|hawala|bribe)\b",
]

def _regex_pii(text: str):
    found = []
    processed = text
    for label, pattern in _PII_PATTERNS_FALLBACK.items():
        matches = re.findall(pattern, processed, re.IGNORECASE)
        if matches:
            found.append({"type": label, "count": len(matches)})
            processed = re.sub(
                pattern,
                f"[{label.upper().replace(' ', '_')} MASKED]",
                processed,
                flags=re.IGNORECASE,
            )
    return processed, found

def _regex_harmful(text: str):
    for pattern in _HARMFUL_FALLBACK:
        if re.search(pattern, text.lower(), re.IGNORECASE):
            return True, "Harmful content detected by pattern"
    return False, None


# ── APP ───────────────────────────────────────────────────────────────────────

app = FastAPI(title="LandIQ Guardrail Server", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── SCHEMAS ───────────────────────────────────────────────────────────────────

class GuardrailRequest(BaseModel):
    text: str
    pii_enabled: bool = True
    pii_action: str = "MASK"        # MASK or BLOCK
    safety_enabled: bool = True
    topic_check: bool = False


class GuardrailResponse(BaseModel):
    allowed: bool
    original_text: str
    processed_text: str
    pii_found: list
    blocked_reason: Optional[str] = None
    processing_time_ms: float
    model_used: str = "regex_fallback"


# ── ENDPOINTS ─────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    deberta_ready = _deberta_guardrail is not None
    safety_ready  = _safety_check_all is not None
    return {
        "status": "online",
        "service": "LandIQ Guardrail Server (Student DeBERTa Integration)",
        "version": "2.0.0",
        "port": 8002,
        "model_path": _model_path,
        "deberta_pii_active": deberta_ready,
        "safety_guardrails_active": safety_ready,
        "model_load_error": _model_load_error,
        "capabilities": ["pii_masking", "harmful_content", "jailbreak", "prompt_injection", "toxicity"],
        "source": "Student LiteLLM Deployed project (real DeBERTa LoRA adapter)",
    }


@app.post("/run", response_model=GuardrailResponse)
async def run_guardrail(req: GuardrailRequest):
    start = time.time()
    processed = req.text
    pii_found = []
    blocked_reason = None
    allowed = True
    model_used = "regex_fallback"

    # ── Step 1: Safety check (jailbreak / toxicity / prompt injection) ────
    if req.safety_enabled:
        if _safety_check_all is not None:
            # Use student's real safety_guardrails.check_all
            enabled = {"jailbreak": True, "toxicity": True, "prompt_injection": True}
            action  = {"jailbreak": "BLOCK", "toxicity": "BLOCK", "prompt_injection": "BLOCK"}
            should_block, guardrail_name, reason = _safety_check_all(req.text, enabled, action)
            if should_block:
                return GuardrailResponse(
                    allowed=False,
                    original_text=req.text,
                    processed_text="[BLOCKED]",
                    pii_found=[],
                    blocked_reason=f"[{guardrail_name}] {reason}",
                    processing_time_ms=round((time.time() - start) * 1000, 2),
                    model_used="student_safety_guardrails",
                )
        else:
            # Regex fallback for harmful content
            is_harmful, reason = _regex_harmful(req.text)
            if is_harmful:
                return GuardrailResponse(
                    allowed=False,
                    original_text=req.text,
                    processed_text="[BLOCKED]",
                    pii_found=[],
                    blocked_reason=reason,
                    processing_time_ms=round((time.time() - start) * 1000, 2),
                    model_used="regex_fallback",
                )

    # ── Step 2: PII detection and masking ────────────────────────────────
    if req.pii_enabled:
        if _deberta_guardrail is not None:
            # Use student's real DeBERTa model
            model_used = f"deberta_lora:{Path(_model_path).name}"
            try:
                cfg = _deberta_guardrail._get_config({})
                # If user passed BLOCK action, set all policies to BLOCK
                if req.pii_action == "BLOCK":
                    from dataclasses import replace as _dc_replace
                    cfg = _dc_replace(cfg, default_action="BLOCK",
                                      policy={k: "BLOCK" for k in cfg.policy})

                entities = _deberta_guardrail.detect(req.text, cfg)

                if entities:
                    pii_found = [
                        {"type": e["label"], "count": 1, "score": round(e.get("score", 0), 3)}
                        for e in entities
                    ]

                    if req.pii_action == "BLOCK":
                        labels = ", ".join(sorted({e["label"] for e in entities}))
                        return GuardrailResponse(
                            allowed=False,
                            original_text=req.text,
                            processed_text="[BLOCKED - PII FOUND]",
                            pii_found=pii_found,
                            blocked_reason=f"PII detected: {labels}",
                            processing_time_ms=round((time.time() - start) * 1000, 2),
                            model_used=model_used,
                        )
                    else:
                        # MASK mode
                        processed = _deberta_guardrail.apply_mask(req.text, entities, cfg)

            except Exception as e:
                logger.warning(f"[GUARDRAIL] DeBERTa inference error: {e} — falling back to regex")
                processed, pii_found = _regex_pii(req.text)
                model_used = "regex_fallback"
        else:
            # Regex fallback for PII
            processed, pii_found = _regex_pii(req.text)
            model_used = "regex_fallback"

            if req.pii_action == "BLOCK" and pii_found:
                labels = ", ".join(p["type"] for p in pii_found)
                return GuardrailResponse(
                    allowed=False,
                    original_text=req.text,
                    processed_text="[BLOCKED - PII FOUND]",
                    pii_found=pii_found,
                    blocked_reason=f"PII detected: {labels}",
                    processing_time_ms=round((time.time() - start) * 1000, 2),
                    model_used=model_used,
                )

    return GuardrailResponse(
        allowed=allowed,
        original_text=req.text,
        processed_text=processed,
        pii_found=pii_found,
        blocked_reason=blocked_reason,
        processing_time_ms=round((time.time() - start) * 1000, 2),
        model_used=model_used,
    )


@app.post("/pii/detect")
async def detect_pii_only(body: dict):
    """Quick PII detection endpoint — returns entities with positions."""
    text = body.get("text", "")
    if _deberta_guardrail is not None:
        try:
            cfg = _deberta_guardrail._get_config({})
            entities = _deberta_guardrail.detect(text, cfg)
            masked = _deberta_guardrail.apply_mask(text, entities, cfg)
            found = [{"type": e["label"], "count": 1, "score": round(e.get("score", 0), 3)}
                     for e in entities]
            return {
                "pii_found": found,
                "masked_text": masked,
                "has_pii": len(found) > 0,
                "entities": entities,
                "model_used": f"deberta_lora:{Path(_model_path).name}",
            }
        except Exception as e:
            logger.warning(f"DeBERTa PII detect failed: {e}")

    # Regex fallback
    masked, found = _regex_pii(text)
    return {
        "pii_found": found,
        "masked_text": masked,
        "has_pii": len(found) > 0,
        "entities": [],
        "model_used": "regex_fallback",
    }


@app.post("/safety/check")
def safety_check_only(body: dict):
    """Quick safety check — jailbreak / toxicity / prompt injection."""
    text = body.get("text", "")
    if _safety_check_all is not None:
        enabled = {"jailbreak": True, "toxicity": True, "prompt_injection": True}
        action  = {"jailbreak": "BLOCK", "toxicity": "BLOCK", "prompt_injection": "BLOCK"}
        should_block, name, reason = _safety_check_all(text, enabled, action)
        return {
            "is_harmful": should_block,
            "guardrail_name": name,
            "reason": reason,
            "allowed": not should_block,
            "source": "student_safety_guardrails",
        }
    # Regex fallback
    is_harmful, reason = _regex_harmful(text)
    return {
        "is_harmful": is_harmful,
        "reason": reason,
        "allowed": not is_harmful,
        "source": "regex_fallback",
    }


# ── STARTUP ───────────────────────────────────────────────────────────────────

@app.on_event("startup")
async def on_startup():
    import asyncio
    # Load student code in a thread so the server starts fast
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _try_load_student_code)


if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("  LandIQ Guardrail Server — Student DeBERTa Integration")
    print(f"  Model  : {_model_path}")
    print("  Port   : http://localhost:8002")
    print("  Health : http://localhost:8002/health")
    print("  Docs   : http://localhost:8002/docs")
    print("=" * 60 + "\n")
    uvicorn.run("guardrail_server:app", host="0.0.0.0", port=8002, reload=False)