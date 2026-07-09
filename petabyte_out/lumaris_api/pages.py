"""Static site pages served by the API (same-origin, no build step).

Brand: "Deep Ocean Compute" — deep-navy background with teal/cyan bioluminescent
accents and an amber energy accent, Space Grotesk (display) + Inter (body) +
JetBrains Mono (data). The hexagon node mark (/static/petabyte-logo.png) is the
signature. Token persists in localStorage as 'pb_token' across pages.
"""

_HEAD = """<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>%%TITLE%%</title>
<script>(function(){try{var t=localStorage.getItem('pb_theme');if(t!=='light'&&t!=='dark')t=(window.matchMedia&&matchMedia('(prefers-color-scheme: light)').matches)?'light':'dark';document.documentElement.setAttribute('data-theme',t);}catch(e){document.documentElement.setAttribute('data-theme','dark');}})();</script>
<link rel="icon" type="image/png" href="/favicon.ico">
<link rel="apple-touch-icon" href="/static/petabyte-mark-180.png">
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;600;700&family=Inter:wght@400;450;500;600&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">
<style>
:root{--bg:#080D1C;--panel:#0F1730;--panel2:#0B1122;--line:#1C2742;--line2:#2A3A5E;
--ink:#EAF0FB;--mut:#93A0BE;--dim:#5D6B8A;
--teal:#4FD6C9;--teal-br:#74ECDD;--deep:#2C9E9B;--amber:#F5B23D;--amber-br:#FFC768;
--pos:#57D9A3;--warn:#F0A44B;--bad:#E5788B;
--gA:rgba(245,178,61,.055);--gB:rgba(79,214,201,.12);--gC:rgba(44,158,155,.12);
--navbg:rgba(8,13,28,.74);--hair:#141C33;
--disp:'Space Grotesk',sans-serif;--body:'Inter',sans-serif;--mono:'JetBrains Mono',monospace;}
html[data-theme=light]{
 --bg:#EDF3F8;--panel:#FFFFFF;--panel2:#F5F9FC;--line:#DBE5EE;--line2:#C2D2DF;
 --ink:#0F1B2D;--mut:#4B5C72;--dim:#7F90A5;
 --teal:#0E9C93;--teal-br:#12B3A8;--deep:#0B7E77;--amber:#B87814;--amber-br:#D69A2E;
 --gA:rgba(245,178,61,.10);--gB:rgba(20,179,168,.13);--gC:rgba(44,158,155,.10);
 --navbg:rgba(237,243,248,.82);--hair:#E6EDF3;}
*{box-sizing:border-box;margin:0;padding:0}
body{background:
 radial-gradient(1100px 620px at 80% -10%,var(--gA),transparent 60%),
 radial-gradient(1000px 720px at -5% -8%,var(--gB),transparent 55%),
 radial-gradient(1300px 900px at 50% 118%,var(--gC),transparent 60%),
 var(--bg);
 color:var(--ink);font-family:var(--body);font-size:14px;line-height:1.6;-webkit-font-smoothing:antialiased;
 transition:background-color .3s,color .3s}
a{color:inherit;text-decoration:none}
.mono{font-family:var(--mono);font-variant-numeric:tabular-nums}
.wrap{max-width:1060px;margin:0 auto;padding:0 22px}
.teal{color:var(--teal)}.amber{color:var(--amber)}.mut{color:var(--mut)}
nav{position:sticky;top:0;z-index:20;backdrop-filter:blur(12px);background:var(--navbg);border-bottom:1px solid var(--line)}
nav .wrap{display:flex;align-items:center;gap:22px;height:62px}
.brand{display:flex;align-items:center;gap:10px;font-family:var(--disp);font-weight:700;font-size:19px;letter-spacing:-.02em}
.brand img{width:26px;height:26px;display:block}
.brand b{font-weight:700}.brand .p{color:var(--teal)}
.navlinks{display:flex;gap:20px;margin-left:10px}
.navlinks a{font-size:13px;color:var(--mut);transition:color .15s}
.navlinks a:hover{color:var(--ink)}
.navcta{margin-left:auto;display:flex;align-items:center;gap:14px}
.signin{font-size:13px;color:var(--mut);transition:color .15s}.signin:hover{color:var(--teal)}
button,.btn{font-family:var(--disp);font-weight:600;border:0;border-radius:10px;padding:9px 16px;font-size:13px;cursor:pointer;transition:transform .12s,filter .15s,border-color .15s,color .15s;display:inline-flex;align-items:center;gap:8px}
button:active,.btn:active{transform:translateY(1px)}
.btn-amber{background:linear-gradient(180deg,var(--amber-br),var(--amber));color:#241802;box-shadow:0 4px 18px -6px rgba(245,178,61,.5)}
.btn-amber:hover{filter:brightness(1.05)}
.btn-teal{background:transparent;color:var(--teal);border:1px solid rgba(79,214,201,.45)}
.btn-teal:hover{border-color:var(--teal);box-shadow:0 0 0 3px rgba(79,214,201,.12)}
.btn-ghost{background:transparent;color:var(--ink);border:1px solid var(--line2)}
.btn-ghost:hover{border-color:var(--teal);color:var(--teal)}
h1{font-family:var(--disp);font-weight:700;letter-spacing:-.028em;line-height:1.02}
h2{font-family:var(--disp);font-weight:600;letter-spacing:-.01em}
.grad{background:linear-gradient(96deg,var(--teal-br),var(--amber));-webkit-background-clip:text;background-clip:text;color:transparent}
.grad-teal{background:linear-gradient(96deg,var(--teal-br),var(--deep));-webkit-background-clip:text;background-clip:text;color:transparent}
.eyebrow{font-family:var(--mono);font-size:11px;letter-spacing:.24em;text-transform:uppercase;color:var(--teal);display:flex;align-items:center;gap:10px}
.dot{width:7px;height:7px;border-radius:50%;background:var(--teal);animation:pulse 2.4s infinite}
@keyframes pulse{0%{box-shadow:0 0 0 0 rgba(79,214,201,.5)}70%{box-shadow:0 0 0 9px rgba(79,214,201,0)}100%{box-shadow:0 0 0 0 rgba(79,214,201,0)}}
.hero{position:relative;overflow:hidden}
.hexbg{position:absolute;right:-60px;top:-30px;width:360px;opacity:.06;pointer-events:none;filter:saturate(1.2)}
.lbl{font-family:var(--mono);font-size:10.5px;letter-spacing:.16em;text-transform:uppercase;color:var(--teal);display:inline-flex;align-items:center;gap:8px;margin-bottom:10px}
.lbl::before{content:"";width:7px;height:7px;border-radius:50%;background:currentColor;box-shadow:0 0 10px currentColor}
.lbl.am{color:var(--amber)}
.panel{background:var(--panel2);border:1px solid var(--line);border-radius:16px}
.card{background:linear-gradient(180deg,var(--panel),var(--panel2));border:1px solid var(--line);border-radius:14px;padding:20px;transition:transform .16s,border-color .16s,box-shadow .16s}
.card:hover{transform:translateY(-2px);border-color:var(--line2);box-shadow:0 14px 40px -22px rgba(79,214,201,.4)}
.cols{display:flex;flex-wrap:wrap;gap:16px}
.c2>*{flex:1 1 calc(50% - 8px);min-width:240px}
.c4>*{flex:1 1 calc(25% - 12px);min-width:180px}
.c3>*{flex:1 1 calc(33.333% - 11px);min-width:220px}
code,pre{font-family:var(--mono)}
pre{background:#060A16;border:1px solid var(--line);border-radius:12px;padding:15px 16px;overflow:auto;font-size:12.5px;line-height:1.75;color:#BFE9E2}
pre .c{color:var(--dim)}
.pill{font-family:var(--mono);font-size:10px;border:1px solid rgba(79,214,201,.35);color:var(--teal);padding:3px 10px;border-radius:999px;background:rgba(79,214,201,.06)}
.tbl{width:100%;border-collapse:collapse;font-size:13px}
.tbl th{font-family:var(--mono);font-size:10px;letter-spacing:.12em;text-transform:uppercase;color:var(--mut);text-align:left;padding:13px 15px;border-bottom:1px solid var(--line)}
.tbl td{padding:13px 15px;border-bottom:1px solid var(--hair)}
.tbl tr:last-child td{border-bottom:0}
.badge{font-family:var(--mono);font-size:10px;padding:3px 8px;border-radius:6px;border:1px solid var(--line2);color:var(--mut)}
.badge.ok{color:var(--teal);border-color:rgba(79,214,201,.4);background:rgba(79,214,201,.09)}
.badge.cc{color:var(--amber);border-color:rgba(245,178,61,.4);background:rgba(245,178,61,.09)}
.stats{display:flex;flex-wrap:wrap;gap:1px;background:var(--line);border:1px solid var(--line);border-radius:16px;overflow:hidden}
.stat{flex:1 1 22%;min-width:150px;background:linear-gradient(180deg,var(--panel),var(--panel2));padding:20px}
.stat .n{font-family:var(--disp);font-weight:700;font-size:28px;margin-top:7px;letter-spacing:-.02em}
.stat .l{font-family:var(--mono);font-size:10px;letter-spacing:.14em;text-transform:uppercase;color:var(--dim)}
.mini{font-family:var(--mono);font-size:10px;letter-spacing:.14em;text-transform:uppercase;color:var(--dim)}
.divider{height:1px;background:linear-gradient(90deg,transparent,var(--line2),transparent);margin:2px 0}
footer{border-top:1px solid var(--line);margin-top:52px}
footer .wrap{display:flex;flex-wrap:wrap;gap:14px;justify-content:space-between;align-items:center;padding:26px 22px 44px;font-family:var(--mono);font-size:11px;color:var(--dim)}
footer .fb{display:flex;align-items:center;gap:9px;color:var(--mut)}
footer .fb img{width:18px;height:18px;opacity:.85}
input,select{font-family:var(--body);background:var(--panel2);border:1px solid var(--line2);color:var(--ink);border-radius:10px;padding:9px 12px;font-size:13px;outline:none}
input:focus{border-color:var(--teal);box-shadow:0 0 0 3px rgba(79,214,201,.14)}
.themetoggle{display:inline-flex;align-items:center;justify-content:center;width:34px;height:34px;border-radius:9px;border:1px solid var(--line2);background:transparent;color:var(--mut);cursor:pointer;padding:0;transition:color .15s,border-color .15s}
.themetoggle:hover{color:var(--teal);border-color:var(--teal)}
.themetoggle svg{width:16px;height:16px}
.themetoggle .sun{display:inline-flex}.themetoggle .moon{display:none}
html[data-theme=light] .themetoggle .sun{display:none}html[data-theme=light] .themetoggle .moon{display:inline-flex}
html[data-theme=light] .hexbg{opacity:.11}
html[data-theme=light] .btn-amber{color:#2a1c02}
.card,.panel,.stat,nav{transition:background-color .3s,border-color .3s}
@media(max-width:760px){.navlinks{display:none}}
@media(prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}}
</style></head><body>"""

_NAV = """<nav><div class="wrap">
<a class="brand" href="/"><img src="/static/petabyte-logo.png" alt="Petabyte"/><span><b>Petabyte</b><span class="p">.</span></span></a>
<div class="navlinks">
  <a href="/marketplace">Marketplace</a><a href="/install">Become a seller</a>
  <a href="/developers">Developers</a><a href="/investors">Investors</a>
</div>
<div class="navcta">
  <a class="signin" id="adminlink" href="/admin" style="display:none">Admin</a>
  <button class="themetoggle" onclick="toggleTheme()" aria-label="Toggle light or dark theme" title="Toggle light / dark">
    <svg class="sun" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M2 12h2M20 12h2M5 5l1.4 1.4M17.6 17.6 19 19M19 5l-1.4 1.4M6.4 17.6 5 19"/></svg>
    <svg class="moon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8Z"/></svg>
  </button>
  <a class="signin" href="/auth/google/login">Sign in</a>
  <a class="btn btn-amber" href="/app">Open app</a>
</div></div></nav>"""

_FOOT = """<footer><div class="wrap">
<span class="fb"><img src="/static/petabyte-logo.png" alt=""/> Petabyte · Deep Ocean Compute · Riyadh</span>
<span>verified compute · escrowed settlement</span>
</div></footer>"""

# token bootstrap: capture #t=JWT from the OAuth redirect, persist across pages
_AUTHJS = """<script>
(function(){var h=location.hash.match(/t=([^&]+)/);if(h){localStorage.setItem('pb_token',decodeURIComponent(h[1]));history.replaceState(null,'',location.pathname);}})();
function tok(){return localStorage.getItem('pb_token');}
function authed(){return !!tok();}
async function api(p,o){o=o||{};o.headers=Object.assign({'Content-Type':'application/json'},o.headers||{});
 if(tok())o.headers['Authorization']='Bearer '+tok();var r=await fetch(p,o);var b={};try{b=await r.json()}catch(e){}return {ok:r.ok,status:r.status,body:b};}
function toggleTheme(){var h=document.documentElement,t=h.getAttribute('data-theme')==='light'?'dark':'light';h.setAttribute('data-theme',t);try{localStorage.setItem('pb_theme',t);}catch(e){}}
(async function(){try{if(authed()){var r=await api('/admin/whoami');if(r.ok){var a=document.getElementById('adminlink');if(a)a.style.display='';}}}catch(e){}})();
</script>"""


def _page(title, body):
    return _HEAD.replace("%%TITLE%%", title) + _NAV + body + _FOOT + _AUTHJS + "</body></html>"


LANDING_HTML = _page("Petabyte — the compute exchange", """
<div class="hero"><div class="wrap" style="padding:64px 22px 22px">
  <img class="hexbg" src="/static/petabyte-logo.png" alt=""/>
  <div class="eyebrow"><span class="dot"></span> live GPU marketplace</div>
  <h1 style="font-size:clamp(36px,6.4vw,64px);margin:18px 0 12px;max-width:16ch">Rent verified GPUs.<br><span class="grad">Settle in seconds.</span></h1>
  <p class="mut" style="font-size:17px;max-width:56ch">A decentralized exchange for GPU compute — verified nodes, escrowed payments, prices below the hyperscalers.</p>
  <div style="display:flex;gap:12px;margin-top:26px;flex-wrap:wrap">
    <a class="btn btn-amber" href="/install">List your GPU →</a>
    <a class="btn btn-teal" href="/marketplace">Browse live GPUs</a>
  </div>
</div></div>
<div class="wrap" style="padding:14px 22px 6px">
  <div class="stats">
    <div class="stat"><div class="l">Nodes online</div><div class="n teal" id="s_nodes">—</div></div>
    <div class="stat"><div class="l">GPUs listed</div><div class="n" id="s_specs">—</div></div>
    <div class="stat"><div class="l">Jobs settled</div><div class="n" id="s_jobs">—</div></div>
    <div class="stat"><div class="l">GMV to date</div><div class="n amber" id="s_gmv">—</div></div>
  </div>
</div>
<div class="wrap" style="padding:38px 22px 8px"><div class="cols c2">
  <div class="card"><div class="lbl">For GPU owners</div>
    <h2 style="font-size:20px;margin-bottom:8px">Turn idle silicon into income</h2>
    <p class="mut">One command to list — Linux, Windows, or a mining rig. Weekly payouts in bank, USDC, or gift card. Idle nodes earn a background trickle.</p>
    <div style="margin-top:16px"><a class="btn btn-ghost" href="/install">Install a node</a></div></div>
  <div class="card"><div class="lbl am">For builders</div>
    <h2 style="font-size:20px;margin-bottom:8px">Cheaper AI compute, verified</h2>
    <p class="mut">H100-class GPUs below cloud on-demand. Cryptographic integrity, confidential computing, data-residency guarantees. State your intent — the router places the job.</p>
    <div style="margin-top:16px"><a class="btn btn-ghost" href="/developers">Read the API</a></div></div>
</div></div>
<script>
function anim(el,to,fmt){var f=parseFloat(el.dataset.v||'0');el.dataset.v=to;var t0=performance.now();
 function s(t){var k=Math.min(1,(t-t0)/650),e=1-Math.pow(1-k,3),v=f+(to-f)*e;el.textContent=fmt?fmt(v):Math.round(v).toLocaleString();if(k<1)requestAnimationFrame(s)}requestAnimationFrame(s)}
var money=n=>'$'+Number(n||0).toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2});
async function stats(){try{var r=await fetch('/marketplace/stats');if(!r.ok)return;var s=await r.json();
 anim(document.getElementById('s_nodes'),s.nodes_online);anim(document.getElementById('s_specs'),s.specs_listed);
 anim(document.getElementById('s_jobs'),s.jobs_completed);anim(document.getElementById('s_gmv'),s.gmv,money);}catch(e){}}
stats();setInterval(stats,5000);
</script>""")


MARKETPLACE_HTML = _page("Petabyte — marketplace", """
<div class="wrap" style="padding:48px 22px 10px">
  <div class="eyebrow"><span class="dot"></span> live inventory</div>
  <h1 style="font-size:clamp(30px,5vw,40px);margin:16px 0 8px">Available <span class="grad-teal">GPUs</span></h1>
  <p class="mut" id="mnote">Loading verified nodes…</p>
</div>
<div class="wrap" style="padding:12px 22px 30px">
  <div class="panel" style="overflow:hidden">
    <table class="tbl"><thead><tr><th>GPU</th><th>$/hr</th><th>vs cloud</th><th>trust</th><th>region</th><th>rep</th></tr></thead>
    <tbody id="mrows"><tr><td colspan="6" style="padding:24px;text-align:center" class="mut mono">loading…</td></tr></tbody></table>
  </div>
  <div style="margin-top:18px;display:flex;gap:14px;align-items:center;flex-wrap:wrap">
    <a class="btn btn-amber" href="/app">Sign in to book →</a>
    <span class="mut">Browsing is open. Booking needs an account.</span>
  </div>
</div>
<script>
async function load(){var r=await fetch('/marketplace/specs');var b=await r.json();var aws=b.aws_reference||12.29;
 document.getElementById('mnote').textContent=b.count?b.count+' GPUs bookable now · reference cloud $'+aws+'/hr':'No GPUs online right now — check back soon.';
 var tb=document.getElementById('mrows');if(!b.count){tb.innerHTML='<tr><td colspan=6 style="padding:24px;text-align:center" class="mut mono">No bookable GPUs online.</td></tr>';return;}
 tb.innerHTML=b.specs.map(function(s){var save=Math.round((1-s.price_per_hour/aws)*100);
  var t=[];if(s.confidential)t.push('<span class="badge cc">confidential</span>');if(s.region_verified)t.push('<span class="badge ok">region ✓</span>');
  var rc=s.reputation_score>=80?'var(--pos)':s.reputation_score>=60?'var(--warn)':'var(--bad)';
  return '<tr><td style="font-family:var(--disp);font-weight:600">'+(s.gpu_model||'CPU')+'</td>'+
   '<td class="mono amber">$'+s.price_per_hour.toFixed(2)+'</td>'+
   '<td class="mono" style="color:var(--pos)">'+(save>0?'−'+save+'%':'—')+'</td>'+
   '<td>'+(t.join(' ')||'<span class="mut mono" style="font-size:11px">standard</span>')+'</td>'+
   '<td class="mut mono" style="font-size:12px">'+(s.region||'—')+'</td>'+
   '<td class="mono" style="color:'+rc+'">'+(s.reputation_score!=null?s.reputation_score:'—')+'</td></tr>';}).join('');}
load();setInterval(load,8000);
</script>""")


INSTALL_HTML = _page("Petabyte — become a seller", """
<div class="wrap" style="padding:48px 22px 10px">
  <div class="eyebrow"><span class="dot"></span> node onboarding</div>
  <h1 style="font-size:clamp(30px,5vw,40px);margin:16px 0 8px">List your GPU in <span class="grad-teal">one command</span></h1>
  <p class="mut" style="max-width:56ch">Any NVIDIA machine can become a node. The installer verifies your hardware, sandboxes jobs in Docker, and brings you online in ~30 seconds. No exclusivity.</p>
</div>
<div class="wrap" style="padding:12px 22px 30px">
  <div class="cols c3">
    <div class="card"><div class="lbl">Linux · Ubuntu/Debian</div>
      <pre>PETABYTE_API_URL=https://petabyte.market \\
PETABYTE_USER=you PETABYTE_PASS=secret \\
PRICE_PER_HOUR=1.5 \\
bash &lt;(curl -fsSL https://petabyte.market/install.sh)</pre></div>
    <div class="card"><div class="lbl">Windows · WSL2</div>
      <pre>$env:PETABYTE_API_URL="https://petabyte.market"
$env:PETABYTE_USER="you"; $env:PETABYTE_PASS="secret"
$env:PRICE_PER_HOUR="1.5"
irm https://petabyte.market/install.ps1 | iex</pre>
      <p class="mut" style="font-size:12px;margin-top:9px">Elevated PowerShell. Installs WSL2 + the agent.</p></div>
    <div class="card"><div class="lbl">Verify</div>
      <pre>systemctl status petabyte-agent
journalctl -u petabyte-agent -f</pre>
      <p class="mut" style="font-size:12px;margin-top:9px">Your GPU appears in the <a class="teal" href="/marketplace">marketplace</a> within a minute.</p></div>
  </div>
  <div class="card" style="margin-top:16px"><div class="lbl am">Get paid</div>
    <p class="mut">One balance. Withdraw anytime or on a weekly schedule — bank, USDC, or gift card. Opt in to idle-fallback and earn a background trickle whenever the node isn't rented. <a class="teal" href="/app">Open the app →</a></p>
  </div>
</div>""")


DEVELOPERS_HTML = _page("Petabyte — developers", """
<div class="wrap" style="padding:48px 22px 10px">
  <div class="eyebrow"><span class="dot"></span> API reference</div>
  <h1 style="font-size:clamp(30px,5vw,40px);margin:16px 0 8px">Build on the <span class="grad-teal">exchange</span></h1>
  <p class="mut">REST + JSON. Full interactive schema at <a class="teal" href="/docs">/docs</a> · keys on the <a class="teal" href="/keys">keys page</a>.</p>
</div>
<div class="wrap" style="padding:12px 22px 30px">
  <div class="cols c2">
    <div class="card"><div class="lbl">Accounts</div>
      <p class="mono" style="font-size:12.5px;line-height:2.05">
      POST /register_user <span class="mut">create account</span><br>
      GET /auth/google/login <span class="mut">Google sign-in</span><br>
      POST /create_api_key <span class="mut">scoped key</span></p></div>
    <div class="card"><div class="lbl">Marketplace</div>
      <p class="mono" style="font-size:12.5px;line-height:2.05">
      GET /marketplace/specs <span class="mut">public inventory</span><br>
      GET /marketplace/stats <span class="mut">live totals</span><br>
      POST /solve <span class="mut">intent → placement</span></p></div>
    <div class="card"><div class="lbl">Run compute</div>
      <p class="mono" style="font-size:12.5px;line-height:2.05">
      POST /request_vm <span class="mut">book + escrow</span><br>
      POST /create_task <span class="mut">notebook · template · vm</span><br>
      POST /transcode <span class="mut">video fan-out</span><br>
      POST /render <span class="mut">Blender fan-out</span></p></div>
    <div class="card"><div class="lbl am">Wallet &amp; payouts</div>
      <p class="mono" style="font-size:12.5px;line-height:2.05">
      GET /wallet <span class="mut">balance + earnings</span><br>
      POST /wallet/methods <span class="mut">gift · USDC · bank</span><br>
      POST /wallet/withdraw <span class="mut">cash out</span></p></div>
  </div>
  <div style="margin-top:18px"><a class="btn btn-amber" href="/docs">Open interactive docs →</a></div>
</div>""")


KEYS_HTML = _page("Petabyte — API keys", """
<div class="wrap" style="padding:48px 22px 10px">
  <div class="eyebrow"><span class="dot"></span> credentials</div>
  <h1 style="font-size:clamp(30px,5vw,40px);margin:16px 0 8px">API <span class="grad-teal">keys</span></h1>
  <p class="mut">Scoped keys for nodes and integrations. The secret is shown once — copy it right away.</p>
</div>
<div class="wrap" style="padding:12px 22px 34px">
  <div id="hint" class="card" style="display:none;border-color:rgba(79,214,201,.3);background:linear-gradient(180deg,rgba(79,214,201,.05),transparent);margin-bottom:16px">
    <span class="mut">Keys sync to your account once you <a class="teal" href="/auth/google/login">sign in</a>. You can still generate one below.</span>
  </div>
  <div class="card"><div class="lbl">New key</div>
    <div style="display:flex;gap:10px;flex-wrap:wrap;align-items:center;margin-top:4px">
      <input id="label" placeholder="label · my-node" size="16"/>
      <input id="scopes" placeholder="scopes · node,jobs" size="15"/>
      <input id="days" type="number" value="90" min="1" max="90" size="4" title="days valid"/>
      <button class="btn-amber" onclick="mk()">Generate key</button>
    </div>
    <pre id="newkey" style="display:none;margin-top:14px"></pre>
    <p id="needauth" class="mut" style="display:none;margin-top:12px">Sign in to generate a key — <a class="teal" href="/auth/google/login">continue with Google</a>.</p>
  </div>
  <div class="panel" style="margin-top:16px;overflow:hidden">
    <table class="tbl"><thead><tr><th>Label</th><th>Scopes</th><th>Created</th><th>Expires</th><th>Status</th><th></th></tr></thead>
    <tbody id="krows"><tr><td colspan=6 class="mut mono" style="padding:22px;text-align:center">No keys yet.</td></tr></tbody></table>
  </div>
</div>
<script>
if(authed())list();else document.getElementById('hint').style.display='';
async function list(){var r=await api('/account/keys');var tb=document.getElementById('krows');
 if(!r.ok||!r.body.keys||!r.body.keys.length){tb.innerHTML='<tr><td colspan=6 class="mut mono" style="padding:22px;text-align:center">No keys yet.</td></tr>';return;}
 tb.innerHTML=r.body.keys.map(function(k){return '<tr><td>'+(k.label||'—')+'</td><td class="mono mut">'+(k.scopes||'—')+'</td>'+
  '<td class="mono mut" style="font-size:11px">'+k.created_at.slice(0,10)+'</td><td class="mono mut" style="font-size:11px">'+k.expires_at.slice(0,10)+'</td>'+
  '<td>'+(k.revoked?'<span class="badge">revoked</span>':'<span class="badge ok">active</span>')+'</td>'+
  '<td>'+(k.revoked?'':'<button class="btn-ghost" onclick="rv(\\''+k.jti+'\\')">revoke</button>')+'</td></tr>';}).join('');}
async function mk(){if(!authed()){document.getElementById('needauth').style.display='';return;}
 var q=new URLSearchParams({days:document.getElementById('days').value||'90'});
 var lb=document.getElementById('label').value,sc=document.getElementById('scopes').value;
 if(lb)q.set('label',lb);if(sc)q.set('scopes',sc);
 var r=await api('/create_api_key?'+q.toString(),{method:'POST'});
 if(r.ok){var el=document.getElementById('newkey');el.style.display='';el.textContent='Copy now — shown once:\\n\\n'+r.body.api_key;list();}}
async function rv(jti){await api('/keys/'+jti+'/revoke',{method:'POST'});list();}
</script>""")


INVESTORS_HTML = _page("Petabyte — investors", """
<div class="hero"><div class="wrap" style="padding:52px 22px 8px">
  <img class="hexbg" src="/static/petabyte-logo.png" alt=""/>
  <div style="display:flex;justify-content:space-between;align-items:flex-start;flex-wrap:wrap;gap:12px">
    <div class="eyebrow"><span class="dot"></span> compute-as-a-commodity</div>
    <div class="mini" style="text-align:right;line-height:1.9">petabyte.market<br><span style="color:var(--teal)">raising · pre-revenue</span></div>
  </div>
  <h1 style="font-size:clamp(30px,5.2vw,50px);margin:20px 0 12px;max-width:20ch">The routing layer for <span class="grad-teal">GPU compute</span>, priced like an energy market.</h1>
  <p class="mut" style="font-size:16px;max-width:70ch">Petabyte aggregates underutilized GPU capacity from distributed providers and routes it to buyers at prices far below the hyperscalers — with confidential computing, escrow-protected settlement, and automated payout rails built in from day one.</p>
</div></div>
<div class="wrap" style="padding:26px 22px 8px"><div class="cols c2">
  <div class="card"><div class="lbl am">The problem</div>
    <p class="mut">GPU compute is expensive and scarce. Hyperscalers charge premium rates with limited high-end availability — while enormous capacity sits idle across smaller providers, with no efficient way to monetize it.</p></div>
  <div class="card"><div class="lbl">The solution</div>
    <p class="mut">A decentralized marketplace that unlocks that hidden supply. Buyers get cheaper on-demand GPUs without lock-in, secured by micro-VM isolation and escrow. Providers turn idle hardware into revenue — automated payouts, idle-fallback so nothing sits unused.</p></div>
</div></div>
<div class="wrap" style="padding:16px 22px 8px">
  <div class="panel" style="padding:22px 24px;border-left:3px solid var(--teal);background:linear-gradient(100deg,rgba(79,214,201,.07),rgba(44,158,155,.03))">
    <div class="lbl">Vision — beyond a marketplace</div>
    <p class="mut" style="max-width:92ch">Petabyte starts as a GPU marketplace but builds toward the <span class="teal">routing layer for compute-as-a-commodity</span> — real-time pricing and cross-provider arbitrage that treat GPU power like electricity. The deeper lever: pairing this with <span class="teal">structurally cheap electrons</span> to power AI where the electron is cheapest — the path to a sovereign, trust-minimized compute network.</p>
  </div>
</div>
<div class="wrap" style="padding:26px 22px 8px">
  <div class="mini" style="margin-bottom:14px">Infrastructure — fully built</div>
  <div class="cols c4">
    <div class="card" style="padding:16px"><b class="teal" style="font-family:var(--disp);font-size:14px">Lumaris API</b><p class="mut" style="font-size:12.5px;margin-top:5px">Control plane &amp; job orchestration</p></div>
    <div class="card" style="padding:16px"><b class="teal" style="font-family:var(--disp);font-size:14px">Confidential Compute</b><p class="mut" style="font-size:12.5px;margin-top:5px">Firecracker / QEMU micro-VM isolation</p></div>
    <div class="card" style="padding:16px"><b class="teal" style="font-family:var(--disp);font-size:14px">Escrow &amp; Settlement</b><p class="mut" style="font-size:12.5px;margin-top:5px">Atomic, refund-on-reaper protection</p></div>
    <div class="card" style="padding:16px"><b class="teal" style="font-family:var(--disp);font-size:14px">Payout Rails</b><p class="mut" style="font-size:12.5px;margin-top:5px">Automated provider settlement</p></div>
    <div class="card" style="padding:16px"><b class="amber" style="font-family:var(--disp);font-size:14px">Render &amp; Transcode</b><p class="mut" style="font-size:12.5px;margin-top:5px">Fan-out / stitch pipelines</p></div>
    <div class="card" style="padding:16px"><b class="amber" style="font-family:var(--disp);font-size:14px">AI Templates</b><p class="mut" style="font-size:12.5px;margin-top:5px">One-click vLLM, Ollama, ComfyUI</p></div>
    <div class="card" style="padding:16px"><b class="amber" style="font-family:var(--disp);font-size:14px">Idle Fallback</b><p class="mut" style="font-size:12.5px;margin-top:5px">Hard-preempt utilization capture</p></div>
    <div class="card" style="padding:16px"><b class="amber" style="font-family:var(--disp);font-size:14px">Security Suite</b><p class="mut" style="font-size:12.5px;margin-top:5px">169-assertion test coverage</p></div>
  </div>
</div>
<div class="wrap" style="padding:22px 22px 8px">
  <div class="stats">
    <div class="stat"><div class="n grad-teal">Live</div><div class="l">Core infra</div></div>
    <div class="stat"><div class="n teal">169</div><div class="l">Security assertions</div></div>
    <div class="stat"><div class="n teal">&lt;HS</div><div class="l">vs hyperscaler cost</div></div>
    <div class="stat"><div class="n teal">2026</div><div class="l">First revenue</div></div>
  </div>
</div>
<div class="wrap" style="padding:22px 22px 8px">
  <div class="card" style="text-align:center;background:linear-gradient(100deg,rgba(245,178,61,.08),rgba(79,214,201,.05));border-color:rgba(79,214,201,.3)">
    <p style="font-family:var(--disp);font-weight:600;font-size:18px">Building the Gulf's compute exchange.</p>
    <p class="mut" style="margin-top:7px">For the deck, model, and a live demo — <a class="teal" href="mailto:info@petabyte.market">info@petabyte.market</a></p>
  </div>
</div>""")


ADMIN_HTML = _page("Petabyte — admin", """
<div class="wrap" style="padding:48px 22px 8px">
  <div class="eyebrow"><span class="dot"></span> operations</div>
  <h1 style="font-size:clamp(30px,5vw,40px);margin:16px 0 8px">Admin <span class="grad-teal">console</span></h1>
  <p class="mut">Platform overview, users, nodes, and payouts. Operators only.</p>
</div>

<div class="wrap" style="padding:12px 22px 8px">
  <div id="signin" class="card" style="display:none">
    <div class="lbl">Restricted</div>
    <p class="mut">Sign in with an operator account to open the console.</p>
    <div style="margin-top:14px"><a class="btn btn-amber" href="/auth/google/login">Sign in</a></div>
  </div>
  <div id="denied" class="card" style="display:none;border-color:rgba(229,120,139,.4)">
    <div class="lbl" style="color:var(--bad)">Not authorized</div>
    <p class="mut">This account isn't a platform admin. An owner can grant access by adding your username or email to <code class="teal">ADMIN_USERS</code>.</p>
  </div>
</div>

<div id="console" style="display:none">
  <div class="wrap" style="padding:8px 22px 4px">
    <div class="stats">
      <div class="stat"><div class="l">Users</div><div class="n teal" id="a_users">—</div><div class="mini" id="a_users_sub"></div></div>
      <div class="stat"><div class="l">Nodes online</div><div class="n" id="a_nodes">—</div><div class="mini" id="a_nodes_sub"></div></div>
      <div class="stat"><div class="l">Jobs completed</div><div class="n" id="a_jobs">—</div><div class="mini" id="a_jobs_sub"></div></div>
      <div class="stat"><div class="l">GMV</div><div class="n amber" id="a_gmv">—</div><div class="mini" id="a_rev_sub"></div></div>
    </div>
    <div class="panel" style="margin-top:12px;padding:16px 18px;display:flex;flex-wrap:wrap;gap:22px;align-items:center">
      <div><span class="mini">Platform revenue</span><div class="mono teal" style="font-size:18px;font-weight:600" id="a_rev">—</div></div>
      <div><span class="mini">Payouts pending</span><div class="mono amber" style="font-size:18px;font-weight:600" id="a_pend">—</div></div>
    </div>
  </div>

  <div class="wrap" style="padding:22px 22px 4px">
    <div style="display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap;margin-bottom:12px">
      <div class="lbl" style="margin:0">Users</div>
      <input id="uq" placeholder="search username" size="18" onkeyup="if(event.key==='Enter')loadUsers()"/>
    </div>
    <div class="panel" style="overflow:auto">
      <table class="tbl"><thead><tr><th>User</th><th>Email</th><th>Role</th><th>Rep</th><th>Balance</th><th>Earnings</th><th></th></tr></thead>
      <tbody id="urows"><tr><td colspan=7 class="mut mono" style="padding:20px;text-align:center">loading…</td></tr></tbody></table>
    </div>
  </div>

  <div class="wrap" style="padding:22px 22px 4px">
    <div class="lbl" style="margin-bottom:12px">Nodes</div>
    <div class="panel" style="overflow:auto">
      <table class="tbl"><thead><tr><th>#</th><th>Owner</th><th>GPU</th><th>$/hr</th><th>Status</th><th>Trust</th><th>Jobs</th><th></th></tr></thead>
      <tbody id="srows"><tr><td colspan=8 class="mut mono" style="padding:20px;text-align:center">loading…</td></tr></tbody></table>
    </div>
  </div>

  <div class="wrap" style="padding:22px 22px 30px">
    <div class="lbl" style="margin-bottom:12px">Pending payouts</div>
    <div class="panel" style="overflow:auto">
      <table class="tbl"><thead><tr><th>#</th><th>User</th><th>Amount</th><th>Rail</th><th>Requested</th></tr></thead>
      <tbody id="prows"><tr><td colspan=5 class="mut mono" style="padding:20px;text-align:center">loading…</td></tr></tbody></table>
    </div>
  </div>
</div>

<script>
var money=n=>'$'+Number(n||0).toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2});
function show(id){var e=document.getElementById(id);if(e)e.style.display='';}
async function boot(){
  if(!authed()){show('signin');return;}
  var ov=await api('/admin/overview');
  if(ov.status===403){show('denied');return;}
  if(!ov.ok){show('signin');return;}
  var o=ov.body;
  document.getElementById('a_users').textContent=o.users.total;
  document.getElementById('a_users_sub').textContent=o.users.sellers+' sellers · '+o.users.buyers+' buyers';
  document.getElementById('a_nodes').textContent=o.specs.online;
  document.getElementById('a_nodes_sub').textContent=o.specs.attested+' attested · '+o.specs.confidential+' confidential';
  document.getElementById('a_jobs').textContent=o.jobs.completed;
  document.getElementById('a_jobs_sub').textContent=o.jobs.running+' running · '+o.jobs.pending+' pending';
  document.getElementById('a_gmv').textContent=money(o.gmv);
  document.getElementById('a_rev').textContent=money(o.platform_revenue);
  document.getElementById('a_pend').textContent=o.payouts_pending.count+' · '+money(o.payouts_pending.amount);
  document.getElementById('console').style.display='';
  loadUsers();loadSpecs();loadPayouts();
}
async function loadUsers(){var q=document.getElementById('uq').value;
  var r=await api('/admin/users'+(q?('?q='+encodeURIComponent(q)):''));var tb=document.getElementById('urows');
  if(!r.ok||!r.body.users.length){tb.innerHTML='<tr><td colspan=7 class="mut mono" style="padding:20px;text-align:center">No users.</td></tr>';return;}
  tb.innerHTML=r.body.users.map(function(u){var other=u.role==='seller'?'buyer':'seller';
    return '<tr><td style="font-family:var(--disp);font-weight:600">'+u.username+(u.is_admin?' <span class="badge cc">admin</span>':'')+'</td>'+
     '<td class="mut mono" style="font-size:12px">'+(u.email||'—')+'</td>'+
     '<td>'+(u.role==='seller'?'<span class="badge ok">seller</span>':'<span class="badge">buyer</span>')+'</td>'+
     '<td class="mono">'+u.reputation+'</td><td class="mono">'+money(u.balance)+'</td><td class="mono amber">'+money(u.earnings)+'</td>'+
     '<td><button class="btn-ghost" onclick="setRole(\\''+u.username+'\\',\\''+other+'\\')">make '+other+'</button></td></tr>';}).join('');}
async function setRole(u,role){await api('/admin/users/'+encodeURIComponent(u)+'/role',{method:'POST',body:JSON.stringify({role:role})});loadUsers();}
async function loadSpecs(){var r=await api('/admin/specs');var tb=document.getElementById('srows');
  if(!r.ok||!r.body.specs.length){tb.innerHTML='<tr><td colspan=8 class="mut mono" style="padding:20px;text-align:center">No nodes.</td></tr>';return;}
  tb.innerHTML=r.body.specs.map(function(s){var t=[];if(s.confidential)t.push('<span class="badge cc">conf</span>');if(s.region_verified)t.push('<span class="badge ok">region ✓</span>');
    var st=s.status==='online'?'<span class="badge ok">online</span>':'<span class="badge">'+s.status+'</span>';
    return '<tr><td class="mono mut">'+s.id+'</td><td>'+s.owner+'</td>'+
     '<td style="font-family:var(--disp);font-weight:600">'+(s.gpu_model||'CPU')+'</td>'+
     '<td class="mono amber">$'+s.price_per_hour.toFixed(2)+'</td><td>'+st+'</td>'+
     '<td>'+(t.join(' ')||'<span class="mut mono" style="font-size:11px">standard</span>')+'</td>'+
     '<td class="mono">'+s.jobs_completed+'/'+s.jobs_failed+'</td>'+
     '<td>'+(s.status==='online'?'<button class="btn-ghost" onclick="delist('+s.id+')">delist</button>':'')+'</td></tr>';}).join('');}
async function delist(id){await api('/admin/specs/'+id+'/delist',{method:'POST'});loadSpecs();}
async function loadPayouts(){var r=await api('/admin/payouts');var tb=document.getElementById('prows');
  if(!r.ok||!r.body.payouts.length){tb.innerHTML='<tr><td colspan=5 class="mut mono" style="padding:20px;text-align:center">No pending payouts.</td></tr>';return;}
  tb.innerHTML=r.body.payouts.map(function(p){return '<tr><td class="mono mut">'+p.id+'</td><td>'+p.user+'</td>'+
    '<td class="mono amber">'+money(p.amount_usd)+'</td><td class="mono mut">'+p.kind+'</td>'+
    '<td class="mono mut" style="font-size:12px">'+(p.created_at?p.created_at.slice(0,10):'—')+'</td></tr>';}).join('');}
boot();
</script>""")
