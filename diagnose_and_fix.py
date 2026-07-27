"""
diagnose_and_fix.py
-------------------
Run from project root: python diagnose_and_fix.py
Tells you exactly what's broken and fixes what it can automatically.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

print("\n" + "="*60)
print("  LANDIQ DIAGNOSTIC & AUTO-FIX")
print("="*60)

issues = []
fixes = []

# CHECK 1: agents_registry structure
print("\n[CHECK 1] agents_registry/ structure...")
reg = "agents_registry"
if not os.path.isdir(reg):
    issues.append("agents_registry/ folder missing at project root")
else:
    subdirs = [d for d in os.listdir(reg) if os.path.isdir(os.path.join(reg, d))]
    # Check for double-nested folder
    if "agents_registry" in subdirs:
        print("  FIXING: double-nested agents_registry/agents_registry/ found")
        import shutil
        inner = os.path.join(reg, "agents_registry")
        for item in os.listdir(inner):
            src = os.path.join(inner, item)
            dst = os.path.join(reg, item)
            if not os.path.exists(dst):
                shutil.move(src, dst)
        shutil.rmtree(inner)
        subdirs = [d for d in os.listdir(reg) if os.path.isdir(os.path.join(reg, d))]
        fixes.append("Fixed double-nested agents_registry")

    expected = ["location","legal","financial","market","bull","bear","due_diligence","senior_consultant"]
    missing = [e for e in expected if e not in subdirs]
    if missing:
        issues.append(f"Missing agent folders: {missing}")
    else:
        print(f"  ✓ Found {len(subdirs)} agent folders: {sorted(subdirs)}")

    # Check AGENT.md + SKILL.md exist
    for e in expected:
        folder = os.path.join(reg, e)
        if os.path.isdir(folder):
            files = os.listdir(folder)
            if "AGENT.md" not in files:
                issues.append(f"Missing {e}/AGENT.md")
            if "SKILL.md" not in files:
                issues.append(f"Missing {e}/SKILL.md")
    if not issues:
        print(f"  ✓ All AGENT.md + SKILL.md files present")

# CHECK 2: dynamic_agent.py location
print("\n[CHECK 2] src/agents/dynamic_agent.py...")
dyn = "src/agents/dynamic_agent.py"
if not os.path.isfile(dyn):
    issues.append(f"Missing: {dyn}")
    print(f"  ✗ NOT FOUND at {dyn}")
else:
    print(f"  ✓ Found at {dyn}")

# CHECK 3: agent_loader.py location
print("\n[CHECK 3] src/utils/agent_loader.py...")
loader = "src/utils/agent_loader.py"
if not os.path.isfile(loader):
    issues.append(f"Missing: {loader}")
    print(f"  ✗ NOT FOUND at {loader}")
else:
    print(f"  ✓ Found at {loader}")

# CHECK 4: orchestrator_agent.py location
print("\n[CHECK 4] src/graph/orchestrator_agent.py...")
orch = "src/graph/orchestrator_agent.py"
if not os.path.isfile(orch):
    issues.append(f"Missing: {orch}")
    print(f"  ✗ NOT FOUND at {orch}")
else:
    print(f"  ✓ Found at {orch}")

# CHECK 5: api.py has the dynamic orchestrator import
print("\n[CHECK 5] api.py uses dynamic orchestrator...")
with open("api.py", "r") as f:
    api_content = f.read()
if "run_dynamic_advisor" in api_content:
    print("  ✓ api.py imports run_dynamic_advisor")
else:
    issues.append("api.py still uses old orchestrator (run_land_advisor from orchestrator.py)")
    print("  ✗ api.py does NOT use dynamic orchestrator")

# CHECK 6: api.py has /agents endpoint
print("\n[CHECK 6] api.py has /agents endpoint...")
if "def list_agents" in api_content or "def get_agent_catalogue" in api_content:
    print("  ✓ /agents endpoint present")
else:
    issues.append("api.py missing /agents endpoint")
    print("  ✗ /agents endpoint missing")

# CHECK 7: can we import the modules
print("\n[CHECK 7] Testing imports...")
try:
    from src.utils.agent_loader import get_agent_catalogue, load_agent
    cat = get_agent_catalogue()
    print(f"  ✓ agent_loader works — {len(cat)} agents in catalogue")
except Exception as e:
    issues.append(f"agent_loader import failed: {e}")
    print(f"  ✗ agent_loader failed: {e}")

try:
    from src.agents.dynamic_agent import run_dynamic_agent, build_output_model
    print(f"  ✓ dynamic_agent imports OK")
except Exception as e:
    issues.append(f"dynamic_agent import failed: {e}")
    print(f"  ✗ dynamic_agent failed: {e}")

try:
    from src.graph.orchestrator_agent import run_dynamic_advisor, DEFAULT_PLAN
    print(f"  ✓ orchestrator_agent imports OK")
    print(f"  ✓ Default plan layers: {[l for l in DEFAULT_PLAN['layers']]}")
except Exception as e:
    issues.append(f"orchestrator_agent import failed: {e}")
    print(f"  ✗ orchestrator_agent failed: {e}")

# CHECK 8: LLM factory can produce a model
print("\n[CHECK 8] LLM factory test...")
try:
    from src.utils.llm_factory import get_llm_for_agent
    llm = get_llm_for_agent("location", temperature=0.1)
    model = getattr(llm, 'model_name', getattr(llm, 'model', str(type(llm).__name__)))
    print(f"  ✓ LLM factory works: {type(llm).__name__} ({model})")
except Exception as e:
    issues.append(f"LLM factory failed: {e}")
    print(f"  ✗ LLM factory failed: {e}")

# CHECK 9: test runtime agent creation
print("\n[CHECK 9] Runtime agent creation test...")
try:
    from src.utils.agent_loader import create_agent_at_runtime, delete_agent
    TEST = "test_runtime_check"
    if os.path.exists(f"agents_registry/{TEST}"):
        delete_agent(TEST)
    result = create_agent_at_runtime(
        name=TEST, display_name="Test Agent",
        description="test only",
        temperature=0.3, layer=1,
        output_fields=[{"name":"summary","type":"str","description":"test"}],
        role_text="You are a test agent.",
        skill_text="1. Return a test summary."
    )
    after_cat = get_agent_catalogue()
    names = [a["name"] for a in after_cat]
    if TEST in names:
        print(f"  ✓ Runtime creation works — agent appeared immediately ({len(after_cat)} total)")
    else:
        print(f"  ✗ Agent created but not in catalogue")
    delete_agent(TEST)
    print(f"  ✓ Cleanup done")
except Exception as e:
    issues.append(f"Runtime creation failed: {e}")
    print(f"  ✗ Runtime creation failed: {e}")

# SUMMARY
print("\n" + "="*60)
if issues:
    print(f"  ISSUES FOUND ({len(issues)}):")
    for i, issue in enumerate(issues, 1):
        print(f"    {i}. {issue}")
else:
    print("  ✓ ALL CHECKS PASSED — system is fully working")
if fixes:
    print(f"\n  AUTO-FIXED ({len(fixes)}):")
    for f in fixes:
        print(f"    - {f}")
print("="*60)
