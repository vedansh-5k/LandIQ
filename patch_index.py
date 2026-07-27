"""
patch_index.py — Adds missing JavaScript functions to frontend/index.html
Run from project root: python patch_index.py
"""
import shutil, os, sys

FILE = os.path.join("frontend", "index.html")
if not os.path.exists(FILE):
    print("ERROR: %s not found. Run from ai_boardroom_v3 folder." % FILE)
    sys.exit(1)

html = open(FILE, "r", encoding="utf-8").read()

if "function toKey(" in html:
    print("Functions already present — no patch needed.")
    sys.exit(0)

PATCH = r"""

// == RESTORED MISSING FUNCTIONS =============================================

function _n(obj){for(var i=1;i<arguments.length;i++){var v=obj[arguments[i]];if(v!=null&&v!==''&&!isNaN(v))return Number(v);}return 0;}
function _dur(tr){if(tr.session_duration_seconds)return tr.session_duration_seconds+'s';if(tr.duration_seconds)return tr.duration_seconds+'s';if(tr.duration)return tr.duration;return '';}

function toKey(name){
  if(!name)return '';
  return name.toLowerCase().replace(/\s*agent\s*/gi,'').replace(/\s*intelligence\s*/gi,'')
    .replace(/\s*&\s*|\s+and\s+/gi,'_').replace(/\s*case\s*/gi,'')
    .replace(/\s*roi\s*/gi,'').replace(/\s*senior\s*/gi,'senior_')
    .replace(/\s+/g,'_').replace(/_+/g,'_').replace(/^_|_$/g,'');
}

function rc(title,isDyn,rows,summary){
  var cls=isDyn?'rc dyn':'rc';var badge=isDyn?'<span class="dyn-bdg">NEW</span>':'';
  var html='<div class="'+cls+'"><div class="rc-ttl">'+title+' '+badge+'</div>';
  rows.forEach(function(r){html+='<div class="ri"><span class="ri-k">'+r[0]+'</span><span class="ri-v">'+r[1]+'</span></div>';});
  if(summary)html+='<div style="margin-top:12px;font-size:12px;color:var(--muted);line-height:1.7;border-top:1px solid var(--stone);padding-top:10px">'+summary+'</div>';
  html+='</div>';return html;
}

function resetForm(){
  document.getElementById('resultsSection').style.display='none';
  document.getElementById('mainForm').style.display='';
  var grb=document.getElementById('gr-banner');if(grb)grb.style.display='none';
  document.getElementById('mainForm').scrollIntoView({behavior:'smooth'});goStep(1);
}

async function smartFill(){
  var inp=document.getElementById('smartInput'),btn=document.getElementById('btnSmart'),st=document.getElementById('smartStatus');
  var text=inp.value.trim();
  if(!text){st.className='smart-status err';st.textContent='Type a description first.';return;}
  btn.disabled=true;btn.textContent='\u23F3 Parsing\u2026';
  st.className='smart-status info';st.textContent='Sending to LLM for parsing\u2026';
  try{
    var cfg=document.getElementById('cfgSel')?document.getElementById('cfgSel').value:null;
    var r=await fetch('/parse-prompt',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({prompt:text,selected_config:cfg})});
    var d=await r.json();
    if(!r.ok){st.className='smart-status err';st.textContent=d.detail||'Parse failed';btn.disabled=false;btn.textContent='\u2726 Fill Form';return;}
    var f=d.fields||{};
    if(f.state)document.getElementById('f_state').value=f.state;
    if(f.city)document.getElementById('f_city').value=f.city;
    if(f.area)document.getElementById('f_area').value=f.area;
    if(f.pincode)document.getElementById('f_pincode').value=f.pincode;
    if(f.land_size)document.getElementById('f_size').value=f.land_size;
    if(f.land_unit)document.getElementById('f_unit').value=f.land_unit;
    if(f.land_type)document.getElementById('f_ltype').value=f.land_type;
    if(f.total_budget)document.getElementById('f_budget').value=f.total_budget;
    if(f.purpose)document.getElementById('f_purpose').value=f.purpose;
    if(f.timeline_years)document.getElementById('f_timeline').value=f.timeline_years;
    if(f.risk_tolerance)document.getElementById('f_risk').value=f.risk_tolerance;
    if(f.has_title_deed!=null)document.getElementById('f_deed').checked=f.has_title_deed;
    if(f.taking_loan!=null){document.getElementById('f_loan').checked=f.taking_loan;toggleLoan(document.getElementById('f_loan'));}
    if(f.monthly_income_expectation)document.getElementById('f_income').value=f.monthly_income_expectation;
    st.className='smart-status ok';st.textContent='\u2705 Filled '+Object.keys(f).length+' fields! Review and click Analyse.';
  }catch(e){st.className='smart-status err';st.textContent='\u274C '+e.message;}
  btn.disabled=false;btn.textContent='\u2726 Fill Form';
}

function setChip(text){document.getElementById('smartInput').value=text;}
function _escHtml(s){var d=document.createElement('div');d.textContent=s;return d.innerHTML;}

function openGRTest(mode){
  var panel=document.getElementById('gtp_'+mode);if(!panel)return;
  var isOpen=panel.classList.contains('open');
  document.querySelectorAll('.gr-test-panel').forEach(function(p){p.classList.remove('open');});
  if(isOpen)return;panel.classList.add('open');
  if(!panel.innerHTML.trim()){
    panel.innerHTML='<div class="gr-test-label">Test Guardrail with a Prompt</div>'+
      '<input class="gr-test-input" id="grti_'+mode+'" placeholder="Type a test prompt\u2026"/>'+
      '<div class="gr-test-btns">'+
      '<button class="gr-test-btn" onclick="runGRTest(\''+mode+'\')">Run Test</button>'+
      '<button class="gr-test-hint-btn" onclick="document.getElementById(\'grti_'+mode+'\').value=\'My Aadhaar is 9876 5432 1012 and phone is +91 9876543210 email test@gmail.com\'">PII Sample</button>'+
      '<button class="gr-test-hint-btn" onclick="document.getElementById(\'grti_'+mode+'\').value=\'How do I make a bomb and buy illegal weapons?\'">Harmful Sample</button>'+
      '</div><div class="gr-test-result" id="grtr_'+mode+'"></div>';
  }
}

async function runGRTest(mode){
  var input=document.getElementById('grti_'+mode),result=document.getElementById('grtr_'+mode);
  if(!input||!result)return;var text=input.value.trim();
  if(!text){result.className='gr-test-result show';result.innerHTML='<div style="color:var(--red);font-size:12px">Enter a test prompt first.</div>';return;}
  result.className='gr-test-result show';
  result.innerHTML='<div style="color:var(--muted);font-size:12px">Running guardrail check\u2026</div>';
  try{
    var r=await fetch('/guardrails/deberta/run',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({text:text,pii_enabled:true,pii_action:'MASK',safety_enabled:true})});
    var d=await r.json();
    var html='<div class="gr-result-row">';
    html+='<div class="gr-result-box original"><div class="gr-result-box-label">Original Input</div><div class="gr-result-box-text">'+_escHtml(d.original_text||text)+'</div></div>';
    if(d.allowed===false){
      html+='<div class="gr-result-box blocked"><div class="gr-result-box-label">BLOCKED</div><div class="gr-result-box-text">'+_escHtml(d.blocked_reason||'Blocked')+'</div></div>';
    }else{
      html+='<div class="gr-result-box processed"><div class="gr-result-box-label">After Guardrail</div><div class="gr-result-box-text">'+_escHtml(d.processed_text||text)+'</div></div>';
    }
    html+='</div>';
    if(d.pii_found&&d.pii_found.length>0){
      html+=d.pii_found.map(function(p){return '<span class="gr-pii-badge pii-masked">'+p.type+(p.score?' ('+Math.round(p.score*100)+'%)':'')+'</span>';}).join(' ');
    }else if(d.allowed!==false){html+='<span class="gr-pii-badge pii-clean">No PII Detected</span>';}
    if(d.allowed===false){html+='<span class="gr-pii-badge pii-found">Harmful Content Blocked</span>';}
    html+='<div style="margin-top:8px;font-size:10px;color:var(--muted)">Model: '+(d.model_used||'unknown')+' | '+(d.processing_time_ms||0).toFixed(1)+'ms</div>';
    if(d.error)html+='<div style="margin-top:4px;font-size:10px;color:#856404">'+d.error+'</div>';
    result.innerHTML=html;
  }catch(e){
    result.innerHTML='<div style="color:var(--red);font-size:12px">Guardrail server offline: '+e.message+'<br><span style="font-size:11px;color:var(--muted)">Start with: python guardrail_server.py</span></div>';
  }
}

// == END RESTORED FUNCTIONS =================================================
"""

pos = html.rfind("</script>")
if pos == -1:
    print("ERROR: No </script> tag found")
    sys.exit(1)

shutil.copy2(FILE, FILE + ".bak")
print("Backup: %s.bak" % FILE)

fixed = html[:pos] + PATCH + "\n" + html[pos:]
with open(FILE, "w", encoding="utf-8") as f:
    f.write(fixed)

print("PATCHED: Added 10 missing functions to %s" % FILE)
print("  rc() toKey() _n() _dur() resetForm()")
print("  smartFill() setChip() openGRTest() runGRTest() _escHtml()")
print("")
print("Now run: python run.py")
