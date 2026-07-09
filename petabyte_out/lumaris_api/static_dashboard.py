DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Petabyte — the compute exchange</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;600;700&family=Inter:wght@400;450;500;600&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">
<style>
:root{
  --bg:#0B1020; --panel:#141A2E; --panel2:#101627; --line:#232C45; --line2:#2E3958;
  --ink:#EAEEF7; --mut:#8A93AD; --amber:#F5B23D; --cyan:#4FD6C9; --grid:#151C33;
  --pos:#57D9A3; --warn:#F0A44B; --bad:#E5788B;
  --disp:'Space Grotesk',system-ui,sans-serif; --body:'Inter',system-ui,sans-serif; --mono:'JetBrains Mono',ui-monospace,monospace;
}
*{box-sizing:border-box}
html{scroll-behavior:smooth}
body{margin:0;background:
  radial-gradient(1200px 500px at 80% -10%, rgba(245,178,61,.06), transparent 60%),
  radial-gradient(900px 500px at 0% 0%, rgba(79,214,201,.05), transparent 55%),
  var(--bg);
  color:var(--ink);font-family:var(--body);font-size:14px;line-height:1.55;-webkit-font-smoothing:antialiased}
a{color:inherit}
.mono{font-family:var(--mono);font-variant-numeric:tabular-nums}
.wrap{max-width:1080px;margin:0 auto;padding:0 22px}

/* top bar */
.bar{position:sticky;top:0;z-index:20;backdrop-filter:blur(10px);
  background:rgba(11,16,32,.72);border-bottom:1px solid var(--line)}
.bar .wrap{display:flex;align-items:center;gap:14px;height:62px}
.logo{display:flex;align-items:center;gap:10px;font-family:var(--disp);font-weight:700;font-size:18px;letter-spacing:-.01em}
.spark{width:22px;height:22px;display:block}
.tagline{color:var(--mut);font-size:12px;letter-spacing:.02em}
.auth{margin-left:auto;display:flex;align-items:center;gap:8px}
input{font-family:var(--body);background:#0B1122;border:1px solid var(--line2);color:var(--ink);
  border-radius:10px;padding:9px 11px;font-size:13px;outline:none;transition:border-color .15s,box-shadow .15s}
input:focus{border-color:var(--amber);box-shadow:0 0 0 3px rgba(245,178,61,.15)}
input::placeholder{color:#59627E}
button{font-family:var(--disp);font-weight:600;border:0;border-radius:10px;padding:9px 15px;font-size:13px;cursor:pointer;transition:transform .12s,filter .15s}
button:active{transform:translateY(1px)}
button:focus-visible{outline:2px solid var(--amber);outline-offset:2px}
.btn{background:linear-gradient(180deg,#F7C05A,#F5B23D);color:#241802}
.btn:hover{filter:brightness(1.06)}
.btn-ghost{background:transparent;color:var(--ink);border:1px solid var(--line2)}
.btn-ghost:hover{border-color:var(--amber);color:var(--amber)}
.who{font-family:var(--mono);font-size:12px;color:var(--cyan);padding:5px 10px;border:1px solid var(--line2);border-radius:999px}

/* hero exchange board */
.hero{padding:34px 0 10px}
.eyebrow{font-family:var(--mono);font-size:11px;letter-spacing:.22em;text-transform:uppercase;color:var(--amber);display:flex;align-items:center;gap:9px}
.dot{width:7px;height:7px;border-radius:50%;background:var(--cyan);box-shadow:0 0 0 0 rgba(79,214,201,.6);animation:pulse 2.4s infinite}
@keyframes pulse{0%{box-shadow:0 0 0 0 rgba(79,214,201,.5)}70%{box-shadow:0 0 0 9px rgba(79,214,201,0)}100%{box-shadow:0 0 0 0 rgba(79,214,201,0)}}
h1{font-family:var(--disp);font-weight:700;font-size:clamp(30px,5vw,50px);line-height:1.02;letter-spacing:-.025em;margin:14px 0 6px}
h1 .grad{background:linear-gradient(100deg,var(--amber),var(--cyan));-webkit-background-clip:text;background-clip:text;color:transparent}
.sub{color:var(--mut);max-width:56ch;font-size:15px}

.board{margin:26px 0 6px;display:grid;grid-template-columns:repeat(4,1fr);gap:1px;background:var(--line);border:1px solid var(--line);border-radius:16px;overflow:hidden}
.cell{background:var(--panel);padding:18px 18px 16px;position:relative}
.cell .k{font-family:var(--mono);font-size:10.5px;letter-spacing:.14em;text-transform:uppercase;color:var(--mut)}
.cell .v{font-family:var(--disp);font-weight:700;font-size:30px;letter-spacing:-.02em;margin-top:6px}
.cell .v.amber{color:var(--amber)} .cell .v.cyan{color:var(--cyan)}
.cell::after{content:"";position:absolute;left:18px;right:18px;bottom:0;height:2px;background:linear-gradient(90deg,transparent,var(--line2),transparent)}

/* sections */
section{padding:30px 0}
.h{display:flex;align-items:baseline;justify-content:space-between;margin-bottom:14px;gap:16px}
.h h2{font-family:var(--disp);font-weight:600;font-size:15px;letter-spacing:.02em;margin:0}
.h .note{font-family:var(--mono);font-size:11px;color:var(--mut)}
.panel{background:var(--panel2);border:1px solid var(--line);border-radius:16px}

/* wallet strip */
.wallet{display:flex;align-items:center;gap:10px;flex-wrap:wrap;padding:14px 16px}
.chip{font-family:var(--mono);font-size:12px;color:var(--mut);border:1px solid var(--line);border-radius:999px;padding:6px 12px}
.chip b{color:var(--ink)}
.wallet .grow{flex:1}

/* table */
.tbl{width:100%;border-collapse:collapse;font-size:13px}
.tbl th{font-family:var(--mono);font-size:10.5px;letter-spacing:.1em;text-transform:uppercase;color:var(--mut);text-align:left;padding:12px 14px;border-bottom:1px solid var(--line)}
.tbl td{padding:13px 14px;border-bottom:1px solid var(--grid)}
.tbl tbody tr{transition:background .12s}
.tbl tbody tr:hover{background:#121A30}
.gpu{font-family:var(--disp);font-weight:600}
.price{font-family:var(--mono);color:var(--amber);font-weight:600}
.save{font-family:var(--mono);color:var(--pos);font-weight:600}
.badge{font-family:var(--mono);font-size:10px;letter-spacing:.04em;padding:3px 7px;border-radius:6px;border:1px solid var(--line2);color:var(--mut);white-space:nowrap}
.badge.ok{color:var(--cyan);border-color:rgba(79,214,201,.4);background:rgba(79,214,201,.08)}
.badge.cc{color:var(--amber);border-color:rgba(245,178,61,.4);background:rgba(245,178,61,.08)}
.rep{font-family:var(--mono);font-weight:600}
.mini{font-family:var(--mono);font-size:11px;color:var(--mut)}

/* run panel */
.run{display:grid;grid-template-columns:1.2fr .8fr;gap:16px}
@media(max-width:820px){.run{grid-template-columns:1fr}.board{grid-template-columns:repeat(2,1fr)}.tbl .hide{display:none}}
textarea{width:100%;min-height:120px;background:#0B1122;border:1px solid var(--line2);color:var(--ink);border-radius:12px;
  padding:13px;font-family:var(--mono);font-size:12.5px;line-height:1.6;resize:vertical;outline:none}
textarea:focus{border-color:var(--amber);box-shadow:0 0 0 3px rgba(245,178,61,.12)}
.console{background:#080C18;border:1px solid var(--line);border-radius:12px;padding:14px;min-height:120px;
  font-family:var(--mono);font-size:12.5px;line-height:1.65;white-space:pre-wrap;color:#BFE9E2;overflow:auto}
.console .sys{color:var(--mut)} .console .ok{color:var(--pos)} .console .amber{color:var(--amber)}
.empty{color:var(--mut);font-family:var(--mono);font-size:12px;padding:22px 14px;text-align:center}
.foot{color:var(--mut);font-size:12px;padding:26px 0 40px;text-align:center;border-top:1px solid var(--line);margin-top:10px}
@media(prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important;scroll-behavior:auto}}
</style></head>
<body>
<div class="bar"><div class="wrap">
  <div class="logo">
    <svg class="spark" viewBox="0 0 24 24" fill="none"><path d="M13 2 4 14h6l-1 8 9-12h-6l1-8Z" fill="#F5B23D"/></svg>
    Petabyte
  </div>
  <span class="tagline">the compute exchange</span>
  <div class="auth">
    <input id="u" placeholder="username" size="10" autocomplete="username"/>
    <input id="p" type="password" placeholder="password" size="10" autocomplete="current-password"/>
    <button class="btn-ghost" onclick="reg()">Create account</button>
    <button class="btn" onclick="login()">Sign in</button>
    <span id="who" class="who" style="display:none"></span>
  </div>
</div></div>

<div class="wrap">
  <div class="hero">
    <div class="eyebrow"><span class="dot"></span> live marketplace</div>
    <h1>Rent verified GPUs.<br><span class="grad">Settle in seconds.</span></h1>
    <p class="sub">A decentralized exchange for GPU compute — cryptographically verified nodes,
    escrowed payments, and prices that undercut hyperscalers. Sign in to browse inventory and run a job.</p>
  </div>

  <div class="board" id="board">
    <div class="cell"><div class="k">Nodes online</div><div class="v cyan" id="s_nodes">—</div></div>
    <div class="cell"><div class="k">GPUs listed</div><div class="v" id="s_specs">—</div></div>
    <div class="cell"><div class="k">Jobs settled</div><div class="v" id="s_jobs">—</div></div>
    <div class="cell"><div class="k">GMV to date</div><div class="v amber" id="s_gmv">—</div></div>
  </div>

  <section>
    <div class="h"><h2>Your balance</h2><span class="note" id="paynote"></span></div>
    <div class="panel wallet">
      <span class="chip">balance <b id="bal" class="mono">$0.00</b></span>
      <span class="chip">earnings <b id="earn" class="mono">$0.00</b></span>
      <span class="grow"></span>
      <input id="dep" type="number" value="50" min="1" size="6" aria-label="deposit amount"/>
      <button class="btn-ghost" onclick="deposit()">Add funds</button>
    </div>
  </section>

  <section>
    <div class="h"><h2>Available GPUs</h2><span class="note" id="specnote">sign in to view live inventory</span></div>
    <div class="panel" style="overflow:hidden">
      <table class="tbl"><thead><tr>
        <th>GPU</th><th>$/hr</th><th class="hide">vs cloud</th><th>trust</th>
        <th class="hide">throughput</th><th>region</th><th></th>
      </tr></thead><tbody id="specs"><tr><td colspan="7" class="empty">— locked —</td></tr></tbody></table>
    </div>
  </section>

  <section>
    <div class="h"><h2>Run a job</h2><span class="note">books the cheapest match, escrows, streams the result</span></div>
    <div class="run">
      <div>
        <textarea id="code" spellcheck="false">print("hello from a petabyte gpu")
print(6 * 7)</textarea>
        <div style="margin-top:12px"><button class="btn" onclick="runJob()">Run on cheapest GPU →</button></div>
      </div>
      <div class="console" id="console"><span class="sys">console idle — sign in, add funds, then run.</span></div>
    </div>
  </section>
</div>
<div class="foot mono">Petabyte · integrity-verified compute · escrowed settlement · prices vs cloud on-demand</div>

<script>
const API=location.origin;
let TOKEN=(function(){var h=location.hash.match(/t=([^&]+)/);if(h){localStorage.setItem('pb_token',decodeURIComponent(h[1]));history.replaceState(null,'',location.pathname);}return localStorage.getItem('pb_token');})();
const AWS_H100=parseFloat('__AWS_REF__')||12.29;
const $=id=>document.getElementById(id);
const money=n=>'$'+Number(n||0).toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2});

async function api(path,opt={}){opt.headers=Object.assign({'Content-Type':'application/json'},opt.headers||{});
  if(TOKEN)opt.headers['Authorization']='Bearer '+TOKEN;
  const r=await fetch(API+path,opt);let b={};try{b=await r.json()}catch(e){}
  return {ok:r.ok,status:r.status,body:b};}

/* animated count-up so the board reads like a live exchange */
function animate(el,to,fmt){const from=parseFloat(el.dataset.v||'0');el.dataset.v=to;
  const t0=performance.now(),d=650;
  function step(t){const k=Math.min(1,(t-t0)/d),e=1-Math.pow(1-k,3),val=from+(to-from)*e;
    el.textContent=fmt?fmt(val):Math.round(val).toLocaleString();if(k<1)requestAnimationFrame(step)}
  requestAnimationFrame(step);}
async function stats(){const r=await api('/marketplace/stats');if(!r.ok)return;const s=r.body;
  animate($('s_nodes'),s.nodes_online);animate($('s_specs'),s.specs_listed);
  animate($('s_jobs'),s.jobs_completed);animate($('s_gmv'),s.gmv,money);}

function con(html,cls){const c=$('console');c.innerHTML+=`<span class="${cls||''}">${html}</span>`;c.scrollTop=c.scrollHeight;}
function conReset(html,cls){$('console').innerHTML=`<span class="${cls||''}">${html}</span>`;}

async function reg(){if(!$('u').value||!$('p').value)return toast('enter a username and password');
  const r=await api('/register_user',{method:'POST',body:JSON.stringify({username:$('u').value,password:$('p').value})});
  toast(r.ok?'account created — now sign in':'could not create account ('+r.status+')');}
async function login(){const f=new URLSearchParams({username:$('u').value,password:$('p').value});
  const r=await fetch(API+'/login',{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},body:f});
  const b=await r.json().catch(()=>({}));if(!r.ok){return toast('sign in failed');}
  TOKEN=b.access_token;localStorage.setItem('pb_token',TOKEN);$('who').style.display='';$('who').textContent='● '+$('u').value;
  $('u').style.display='none';$('p').style.display='none';
  wallet();specs();conReset('signed in — ready to run.','sys');}
async function deposit(){const r=await api('/deposit',{method:'POST',body:JSON.stringify({amount:parseFloat($('dep').value)})});
  if(r.ok){animate($('bal'),r.body.balance,money);}else if(r.status===403){toast('deposits are handled at checkout')}else{toast('could not add funds')}}
async function wallet(){const r=await api('/wallet');if(r.ok){animate($('bal'),r.body.balance,money);animate($('earn'),r.body.earnings,money);}}

async function specs(){const r=await api('/specs');const tb=$('specs');if(!r.ok){return;}
  const rows=r.body.specs;$('specnote').textContent=rows.length?`${rows.length} bookable now · reference cloud $${AWS_H100}/hr`:'';
  if(!rows.length){tb.innerHTML='<tr><td colspan=7 class=empty>No bookable GPUs online right now.</td></tr>';return;}
  tb.innerHTML=rows.map(s=>{const save=Math.round((1-s.price_per_hour/AWS_H100)*100);
    const trust=[]; if(s.confidential)trust.push('<span class="badge cc">confidential</span>');
    if(s.region_verified)trust.push('<span class="badge ok">region ✓</span>');
    const rep=s.reputation_score!=null?`<span class="rep" style="color:${s.reputation_score>=80?'var(--pos)':s.reputation_score>=60?'var(--warn)':'var(--bad)'}">${s.reputation_score}</span>`:'—';
    const tok=s.benchmark_tokens_sec?`<span class="mini">${Math.round(s.benchmark_tokens_sec)} tok/s</span>`:'<span class="mini">—</span>';
    return `<tr>
      <td><span class="gpu">${s.gpu_model||'CPU'}</span> <span class="mini">rep ${rep}</span></td>
      <td class="price">$${s.price_per_hour.toFixed(2)}</td>
      <td class="hide">${save>0?`<span class="save">−${save}%</span>`:'<span class="mini">—</span>'}</td>
      <td>${trust.join(' ')||'<span class="mini">standard</span>'}</td>
      <td class="hide">${tok}</td>
      <td><span class="mini">${s.region||'—'}${s.region_verified?'':''}</span></td>
      <td><button class="btn-ghost" onclick="runJob(${s.spec_id})">run</button></td>
    </tr>`}).join('');}

async function runJob(specId){
  if(!TOKEN)return toast('sign in first');
  conReset('booking a node…','sys');
  const code=$('code').value;let spec=specId;
  if(!spec){const s=await api('/specs');if(!s.body.specs||!s.body.specs.length)return conReset('No GPUs available.','amber');spec=s.body.specs[0].spec_id;}
  const bk=await api('/request_vm',{method:'POST',body:JSON.stringify({spec_id:spec,hours:1})});
  if(!bk.ok){return conReset(bk.status===402?'Add funds before booking.':'Booking failed: '+JSON.stringify(bk.body),'amber');}
  con(`\nbooked #${bk.body.booking_id} · escrow ${money(bk.body.gross_amount)} (fee ${money(bk.body.platform_fee)}, seller ${money(bk.body.seller_payout)})`,'sys');
  const tk=await api('/create_task',{method:'POST',body:JSON.stringify({booking_id:bk.body.booking_id,task_type:'notebook',code})});
  if(!tk.ok){return con('\ntask failed: '+JSON.stringify(tk.body),'amber');}
  const tid=tk.body.task_id;con(`\ndispatched task #${tid} → waiting for a node…`,'sys');
  const t0=Date.now();
  const poll=setInterval(async()=>{const t=await api('/tasks/'+tid);
    if(['completed','failed'].includes(t.body.status)){clearInterval(poll);
      con(`\n\n── ${t.body.status.toUpperCase()} ──\n`,t.body.status==='completed'?'ok':'amber');
      con(t.body.result||'(no output)');wallet();specs();stats();}
    else if(Date.now()-t0>60000){clearInterval(poll);con('\ntimed out.','amber');}
  },1200);}

let tT;function toast(m){clearTimeout(tT);let el=$('toast');
  if(!el){el=document.createElement('div');el.id='toast';el.style.cssText=
   'position:fixed;left:50%;bottom:26px;transform:translateX(-50%);background:#141A2E;border:1px solid var(--line2);'+
   'color:var(--ink);font-family:var(--mono);font-size:12.5px;padding:10px 16px;border-radius:10px;z-index:99;box-shadow:0 8px 30px rgba(0,0,0,.4)';document.body.appendChild(el);}
  el.textContent=m;el.style.opacity='1';tT=setTimeout(()=>el.style.opacity='0',2600);}

if(TOKEN){$('who').style.display='';$('who').textContent='● signed in';$('u').style.display='none';$('p').style.display='none';wallet();specs();conReset('signed in — ready to run.','sys');}
stats();setInterval(stats,5000);
</script></body></html>"""
