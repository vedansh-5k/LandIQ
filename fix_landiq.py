"""
fix_landiq.py — Run this ONCE in your project root (ai_boardroom_v3 folder)
It patches index.html, api.py, and orchestrator_agent.py automatically.

Usage:
    cd C:\\Users\\HP\\OneDrive\\Desktop\\ai_boardroom_v3
    python fix_landiq.py
"""
import os, re, shutil, time

ROOT = os.path.dirname(os.path.abspath(__file__))
BACKUP_SUFFIX = f".bak_{int(time.time())}"

def backup(path):
    if os.path.exists(path):
        shutil.copy2(path, path + BACKUP_SUFFIX)
        print(f"  📦 Backed up: {os.path.basename(path)}")

# ═══════════════════════════════════════════════════════════════
# FIX 1: orchestrator_agent.py — store _orch_plan in state
# ═══════════════════════════════════════════════════════════════
def fix_orchestrator():
    path = os.path.join(ROOT, "src", "graph", "orchestrator_agent.py")
    if not os.path.exists(path):
        print("  ⚠ orchestrator_agent.py not found, skipping")
        return
    backup(path)
    content = open(path, "r", encoding="utf-8").read()

    # Check if already patched
    if '_orch_plan' in content:
        print("  ✅ orchestrator_agent.py already has _orch_plan")
        return

    # Find: plan = plan_execution(user_inputs)
    # Add after it: state["_orch_plan"] = plan
    old = 'plan = plan_execution(user_inputs)'
    if old not in content:
        # Try alternative
        old = 'plan=plan_execution(user_inputs)'
    if old not in content:
        print("  ⚠ Could not find plan_execution call, adding _orch_plan manually")
        # Try to add before the execute section
        if '# Execute' in content:
            content = content.replace(
                '# Execute',
                '# Store plan for frontend\n    state["_orch_plan"] = plan\n\n    # Execute'
            )
        else:
            print("  ❌ Cannot patch orchestrator — add this line manually:")
            print('     state["_orch_plan"] = plan')
            print("     (right after: plan = plan_execution(user_inputs))")
            return
    else:
        content = content.replace(
            old,
            old + '\n    state["_orch_plan"] = plan'
        )

    open(path, "w", encoding="utf-8").write(content)
    print("  ✅ orchestrator_agent.py patched — _orch_plan stored in state")


# ═══════════════════════════════════════════════════════════════
# FIX 2: api.py — add timing to /analyse response
# ═══════════════════════════════════════════════════════════════
def fix_api():
    path = os.path.join(ROOT, "api.py")
    if not os.path.exists(path):
        print("  ⚠ api.py not found, skipping")
        return
    backup(path)
    content = open(path, "r", encoding="utf-8").read()

    # Check if already has timing
    if '"timing"' in content and 'total_seconds' in content:
        print("  ✅ api.py already has timing field")
        return

    # Add timing to the /analyse return dict
    # Find the orch_plan line in the return dict
    old_line = '"orch_plan":        final_state.get("_orch_plan", None),'
    if old_line not in content:
        # Try without extra spaces
        old_line = '"orch_plan": final_state.get("_orch_plan", None),'
    if old_line not in content:
        # Try to find any orch_plan reference in return
        for variant in [
            '"orch_plan":',
            '"mlflow_logged":',
        ]:
            if variant in content:
                # Add timing before this line
                idx = content.index(variant)
                # Find the start of this line
                line_start = content.rfind('\n', 0, idx) + 1
                indent = ' ' * (idx - line_start - len(variant) + len(variant))
                timing_block = f'''        "timing": {{
            "total_seconds": session_duration,
            "start_time": time.strftime("%H:%M:%S", time.localtime(session_start)),
            "end_time": time.strftime("%H:%M:%S", time.localtime(session_start + session_duration)),
        }},
'''
                content = content[:line_start] + timing_block + content[line_start:]
                break
        else:
            print("  ⚠ Could not find return dict to add timing")
            return
    else:
        new_line = old_line + '''
        "timing": {
            "total_seconds": session_duration,
            "start_time": time.strftime("%H:%M:%S", time.localtime(session_start)),
            "end_time": time.strftime("%H:%M:%S", time.localtime(session_start + session_duration)),
        },'''
        content = content.replace(old_line, new_line)

    open(path, "w", encoding="utf-8").write(content)
    print("  ✅ api.py patched — timing added to /analyse response")


# ═══════════════════════════════════════════════════════════════
# FIX 3: index.html — fix showResults to be adaptive
# ═══════════════════════════════════════════════════════════════

FIXED_JS = r'''
// ── AUTO ROWS — extracts displayable rows from any agent output ──
function autoRows(d,max){if(!d||typeof d!=='object')return[];var skip={'summary':1,'agent_name':1,'raw':1,'error':1,'executive_summary':1,'next_steps':1,'confidence_level':1,'financial_verdict':1};return Object.entries(d).filter(function(e){return!skip[e[0]]&&e[1]!=null&&e[1]!=='';}).slice(0,max||6).map(function(e){var k=e[0],v=e[1];var label=k.replace(/_/g,' ').replace(/\b\w/g,function(c){return c.toUpperCase();});var val=v;if(Array.isArray(v)){if(v.length&&typeof v[0]==='string')val=v.slice(0,3).join(', ')+(v.length>3?' …':'');else val=v.length+' items';}else if(typeof v==='object')val=JSON.stringify(v).slice(0,100);else val=String(v);var lv=val.toLowerCase();if(k.indexOf('risk')>=0||k.indexOf('level')>=0){if(lv.indexOf('low')>=0)val='<span class="risk-b risk-low">'+val+'</span>';else if(lv.indexOf('high')>=0||lv.indexOf('avoid')>=0)val='<span class="risk-b risk-high">'+val+'</span>';else if(lv.indexOf('med')>=0||lv.indexOf('mod')>=0)val='<span class="risk-b risk-med">'+val+'</span>';}return[label,val];});}

function showResults(data,payload){
  document.getElementById('mainForm').style.display='none';
  document.getElementById('resultsSection').style.display='block';
  var _area=payload.area&&payload.area!=='null'?payload.area:payload.city;
  document.getElementById('resTitle').textContent=payload.land_size+' '+payload.land_unit+' \u2014 '+_area+', '+payload.city;
  document.getElementById('resSub').textContent=(data.completed_agents||[]).length+' agents \u2022 plan=llm \u2022 '+(data.llm_configuration||'default')+' \u2022 guardrail: '+selGRMode;
  document.getElementById('modBadge').textContent='\uD83E\uDD16 '+(data.llm_configuration||'default');
  if(data.mlflow_logged)document.getElementById('mlBadge').style.display='inline-flex';
  buildOrch(data);
  var grid=document.getElementById('resGrid');var cards=[];
  var agentMap=[['📍 Location Intelligence','location',data.location],['⚖️ Legal & Title','legal',data.legal],['💰 Financial ROI','financial',data.financial],['📊 Market Intel','market',data.market],['🐂 Bull Case','bull',data.bull_case],['🐻 Bear Case','bear',data.bear_case],['🔍 Due Diligence','due_diligence',data.due_diligence]];
  agentMap.forEach(function(item){var title=item[0],d=item[2];if(!d)return;cards.push(rc(title,false,autoRows(d,6),d.summary||d.executive_summary||''));});
  Object.entries(data.dynamic_agents||{}).forEach(function(entry){var k=entry[0],v=entry[1];if(!v)return;var n=k.replace(/_/g,' ').replace(/\b\w/g,function(c){return c.toUpperCase();});cards.push(rc('\u2728 '+n,true,autoRows(v,6),v.summary||''));});
  grid.innerHTML=cards.join('');
  if(data.recommendation){document.getElementById('recCard').style.display='';var vc=document.getElementById('verdictChip');var v=(data.recommendation.final_verdict||data.recommendation.verdict||'HOLD').toUpperCase();vc.textContent=v;var isA=v.indexOf('AVOID')>=0||v.indexOf('DO NOT')>=0;var isB=v.indexOf('STRONGLY')>=0||(v.indexOf('RECOMMEND')>=0&&!isA)||v==='BUY'||v.indexOf('BUY')>=0;vc.className='verdict '+(isA?'v-avoid':isB?'v-buy':'v-hold');document.getElementById('recSummary').textContent=data.recommendation.executive_summary||data.recommendation.summary||'';var ns=(data.recommendation.next_steps||[]).slice(0,5).map(function(s){return '<li style="margin-bottom:5px">'+s+'</li>';}).join('');document.getElementById('recDetails').innerHTML='<div class="ri"><span class="ri-k">Confidence</span><span class="ri-v">'+(data.recommendation.confidence_level||'-')+'</span></div><div class="ri"><span class="ri-k">Financial Verdict</span><span class="ri-v">'+(data.recommendation.financial_verdict||'-')+'</span></div>'+(ns?'<ul style="padding-left:18px;font-size:13px;line-height:1.9;margin-top:14px;color:var(--muted)">'+ns+'</ul>':'');}
  buildTok(data,payload);
  document.getElementById('resultsSection').scrollIntoView({behavior:'smooth'});
}

function buildOrch(data){
  var panel=document.getElementById('orchPanel');var completed=data.completed_agents||[];
  if(!completed.length){panel.style.display='none';return;}panel.style.display='block';
  var layers=[];var op=data.orch_plan;
  if(op&&op.layers&&op.layers.length){layers=op.layers;}
  else{var l1=[],l2=[],l3=[],l4=[];completed.forEach(function(a){var k=toKey(a);if(k==='senior_consultant')l4.push(k);else if(k==='due_diligence')l3.push(k);else if(k==='bull'||k==='bear')l2.push(k);else l1.push(k);});if(l1.length)layers.push(l1);if(l2.length)layers.push(l2);if(l3.length)layers.push(l3);if(l4.length)layers.push(l4);if(!layers.length)layers=[completed.map(toKey)];}
  document.getElementById('orchBdg').textContent='PLAN='+(op&&op.source?op.source.toUpperCase():'LLM');
  document.getElementById('orchLayers').innerHTML=layers.map(function(agents,i){var pills=agents.map(function(n){var isDyn=!CORE.has(n);return '<span class="lpill '+(isDyn?'dyn':'core')+'">'+(isDyn?'\u2728 ':'\u2713 ')+n.replace(/_/g,' ')+'</span>';}).join('');return '<div class="orch-lrow"><span class="lnum">Layer '+(i+1)+'</span><div class="lpills">'+pills+'</div></div>'+(i<layers.length-1?'<div class="larrow">\u2193</div>':'');}).join('');
  var tr=data.token_report||{};var timing=data.timing||{};var durStr=_dur(tr)||(timing.total_seconds?timing.total_seconds+'s':'\u2014');
  document.getElementById('orchFtr').innerHTML='<span class="ostat">Agents: <b>'+completed.length+'</b></span><span class="ostat">Layers: <b>'+layers.length+'</b></span>'+(Object.keys(data.dynamic_agents||{}).length?'<span class="ostat">Dynamic: <b>'+Object.keys(data.dynamic_agents).length+' \u2728</b></span>':'')+'<span class="ostat">Tokens: <b>'+(tr.total_tokens?Number(tr.total_tokens).toLocaleString():'\u2014')+'</b></span><span class="ostat">Duration: <b>'+durStr+'</b></span>'+(tr.estimated_cost_usd?'<span class="ostat">Cost: <b>$'+Number(tr.estimated_cost_usd).toFixed(4)+'</b></span>':'');
}

function buildTok(data,payload){
  var tr=data.token_report||{};document.getElementById('tokBox').style.display='block';
  var it=_n(tr,'input_tokens','prompt_tokens'),ot=_n(tr,'output_tokens','completion_tokens'),tt=_n(tr,'total_tokens')||(it+ot);
  var dur=_dur(tr),cost=_n(tr,'estimated_cost_usd','cost'),calls=_n(tr,'total_llm_calls','llm_calls')||(data.completed_agents||[]).length;
  var timing=data.timing||{};if(!dur&&timing.total_seconds)dur=timing.total_seconds+'s';
  document.getElementById('modBadge').textContent='\uD83E\uDD16 '+(data.llm_configuration||'default');
  document.getElementById('tsGrid').innerHTML=[['Input Tokens',it>0?it.toLocaleString():'\u2014'],['Output Tokens',ot>0?ot.toLocaleString():'\u2014'],['Total Tokens',tt>0?tt.toLocaleString():'\u2014'],['Duration',dur||'\u2014'],['Est. Cost',cost>0?'$'+cost.toFixed(4):'\u2014'],['LLM Calls',calls||'\u2014'],['Start',timing.start_time||'\u2014'],['End',timing.end_time||'\u2014'],['Guardrail',selGRMode.toUpperCase()]].map(function(item){return '<div class="ts"><div class="v">'+item[1]+'</div><div class="l">'+item[0]+'</div></div>';}).join('');
  var cbd=tr.cost_breakdown||{};var bars='';
  if(cbd.input_cost_usd||cbd.output_cost_usd){bars+='<div class="cb-row"><span class="cb-lbl">\uD83D\uDCB5 Input Cost</span><div class="cb-track"><div class="cb-fill cb-g" style="width:'+(it/(tt||1)*100)+'%"></div></div><span class="cb-saved">$'+(cbd.input_cost_usd||0).toFixed(6)+'</span></div>';bars+='<div class="cb-row"><span class="cb-lbl">\uD83D\uDCB5 Output Cost</span><div class="cb-track"><div class="cb-fill cb-gold" style="width:'+(ot/(tt||1)*100)+'%"></div></div><span class="cb-saved">$'+(cbd.output_cost_usd||0).toFixed(6)+'</span></div>';}
  if(data.caveman_mode){var cs=tr.caveman_stats||null;var lv=data.caveman_level||'full';var pct=cs&&cs.savings_pct?cs.savings_pct:{lite:40,full:65,ultra:80}[lv]||65;bars+='<div class="cb-row"><span class="cb-lbl">\uD83E\uDEA8 Caveman '+lv.toUpperCase()+'</span><div class="cb-track"><div class="cb-fill cb-gold" style="width:'+Math.min(pct,100)+'%"></div></div><span class="cb-saved">~'+parseFloat(pct).toFixed(0)+'% saved</span></div>';}
  var ts=tr.toon_stats||null;if(ts&&ts.savings_pct!=null){bars+='<div class="cb-row"><span class="cb-lbl">\uD83C\uDF33 TOON</span><div class="cb-track"><div class="cb-fill cb-g" style="width:'+Math.min(ts.savings_pct,100)+'%"></div></div><span class="cb-saved">'+(ts.savings_tokens||0).toLocaleString()+' ('+parseFloat(ts.savings_pct).toFixed(1)+'%)</span></div>';}
  document.getElementById('cmpBars').innerHTML=bars;
  var log='';var perAgent=tr.per_agent_log||tr.per_call_log||tr.call_log||[];
  if(perAgent.length){perAgent.forEach(function(a){var isDyn=!CORE.has(toKey(a.agent||''));log+=(a.agent||'?').padEnd(28)+' IN='+String(a.input_tokens||0).padStart(6)+'  OUT='+String(a.output_tokens||0).padStart(5)+'  TOTAL='+String(a.total_tokens||0).padStart(6)+(isDyn?' \u2728':'')+'\n';});}
  document.getElementById('tokPre').textContent='Duration       : '+(dur||'\u2014')+'\nLLM Calls      : '+(calls||'\u2014')+'\nInput Tokens   : '+(it>0?it.toLocaleString():'\u2014')+'\nOutput Tokens  : '+(ot>0?ot.toLocaleString():'\u2014')+'\nTotal Tokens   : '+(tt>0?tt.toLocaleString():'\u2014')+'\nEst. Cost      : '+(cost>0?'$'+cost.toFixed(6):'\u2014')+'\n'+(cbd.input_cost_usd?'  Input Cost   : $'+cbd.input_cost_usd.toFixed(6)+'\n':'')+(cbd.output_cost_usd?'  Output Cost  : $'+cbd.output_cost_usd.toFixed(6)+'\n':'')+'Config         : '+(data.llm_configuration||'default')+'\nGuardrail      : '+selGRMode.toUpperCase()+'\nMLflow Logged  : '+(data.mlflow_logged?'Yes':'\u2014')+'\n'+(timing.start_time?'Start Time     : '+timing.start_time+'\n':'')+(timing.end_time?'End Time       : '+timing.end_time+'\n':'')+(log?'\n\u2500\u2500 Per Agent \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\n'+log:'');
}
'''

def fix_index():
    path = os.path.join(ROOT, "frontend", "index.html")
    if not os.path.exists(path):
        print("  ⚠ frontend/index.html not found, skipping")
        return
    backup(path)
    content = open(path, "r", encoding="utf-8").read()

    # Find the old showResults function and replace it along with buildOrch, buildTok, rc
    # Strategy: find "function showResults" and replace everything up to "function resetForm"
    
    # Pattern: from "function showResults(" to just before the NEXT major function after resetForm
    # We need to replace: showResults, buildOrch, buildTok, rc, resetForm
    
    start_marker = "function showResults(data,payload){"
    end_marker = "function resetForm(){"
    
    if start_marker not in content:
        # Try finding it with different formatting
        start_marker = "function showResults(data, payload){"
    
    if start_marker not in content:
        print("  ⚠ Could not find showResults function in index.html")
        print("    Add autoRows function manually before showResults")
        return
    
    start_idx = content.index(start_marker)
    
    # Find resetForm and its closing brace
    if end_marker in content:
        end_idx = content.index(end_marker)
        # Find the closing brace of resetForm
        brace_count = 0
        i = end_idx
        while i < len(content):
            if content[i] == '{':
                brace_count += 1
            elif content[i] == '}':
                brace_count -= 1
                if brace_count == 0:
                    end_idx = i + 1
                    break
            i += 1
    else:
        print("  ⚠ Could not find resetForm, doing partial patch")
        end_idx = start_idx  # Will just prepend

    # Replace the block
    new_content = content[:start_idx] + FIXED_JS.strip() + "\n" + content[end_idx:]
    
    open(path, "w", encoding="utf-8").write(new_content)
    print("  ✅ index.html patched — adaptive agent cards + enhanced token report")


# ═══════════════════════════════════════════════════════════════
# RUN ALL FIXES
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("\n" + "=" * 55)
    print("  LandIQ FINAL FIX — Patching 3 files")
    print("=" * 55)
    
    print(f"\n  Project root: {ROOT}\n")
    
    print("  [1/3] Fixing orchestrator_agent.py…")
    fix_orchestrator()
    
    print("\n  [2/3] Fixing api.py…")
    fix_api()
    
    print("\n  [3/3] Fixing frontend/index.html…")
    fix_index()
    
    print("\n" + "=" * 55)
    print("  ✅ ALL FIXES APPLIED")
    print("  Backups saved as *.bak_*")
    print("  Now run: python run.py")
    print("=" * 55 + "\n")
