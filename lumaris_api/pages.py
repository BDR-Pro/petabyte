"""Static site pages served by the API (same-origin, no build step).

Brand: "Deep Ocean Compute" — deep-navy background with teal/cyan bioluminescent
accents and an amber energy accent, Space Grotesk (display) + Inter (body) +
JetBrains Mono (data). The hexagon node mark (/static/petabyte-logo.png) is the
signature. Token persists in localStorage as 'pb_token' across pages.
"""

_HEAD = """<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>%%TITLE%%</title>
<script>(function(){try{var t=localStorage.getItem('pb_theme');if(t!=='light'&&t!=='dark')t=(window.matchMedia&&matchMedia('(prefers-color-scheme: light)').matches)?'light':'dark';document.documentElement.setAttribute('data-theme',t);document.documentElement.setAttribute('data-bs-theme',t);}catch(e){document.documentElement.setAttribute('data-theme','dark');document.documentElement.setAttribute('data-bs-theme','dark');}})();</script>
<link rel="icon" type="image/png" href="/favicon.ico">
<link rel="apple-touch-icon" href="/static/petabyte-mark-180.png">
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Sora:wght@500;600;700;800&family=Figtree:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet" integrity="sha384-QWTKZyjpPEjISv5WaRU9OFeRpok6YctnYmDr5pNlyT2bRjXh0JMhjY6hW+ALEwIH" crossorigin="anonymous">
<script defer src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js" integrity="sha384-YvpcrYf0tY3lHB60NNkmXc5s9fDVZLESaAA55NDzOxhy9GkcIdslK1eN7N6jIeHz" crossorigin="anonymous"></script>
<style>
/* ---- Bootstrap 5.3 themed to Deep Ocean (our layer loads after and wins) ---- */
[data-bs-theme]{--bs-body-bg:transparent;--bs-body-color:var(--ink);--bs-border-color:var(--line);
 --bs-primary:#35E0D0;--bs-primary-rgb:53,224,208;--bs-warning:#FFB224;--bs-warning-rgb:255,178,36;
 --bs-link-color:var(--teal);--bs-link-hover-color:var(--teal-br);
 --bs-font-sans-serif:'Figtree',system-ui,sans-serif;--bs-body-font-size:14.5px;--bs-body-line-height:1.65;
 --bs-border-radius:14px;--bs-border-radius-lg:18px;--bs-secondary-color:var(--mut)}
.navbar{--bs-navbar-padding-y:0;--bs-navbar-padding-x:0}
.navbar-toggler{border:1px solid var(--line2);border-radius:999px;padding:7px 11px;color:var(--mut)}
.navbar-toggler:focus{box-shadow:0 0 0 4px rgba(53,224,208,.15)}
.navbar-toggler svg{width:18px;height:18px;display:block}
@media(max-width:991.98px){
 .navbar-collapse{flex-basis:100%;padding:10px 4px 12px}
 .navlinks{flex-direction:column;gap:2px;margin-left:0}
 .navlinks a{padding:9px 13px}
 .navcta{margin-left:0;margin-top:8px;flex-wrap:wrap}}
:root{--abyss:#030711;--depth:#0A1226;--depth2:#0D1832;--line:#16223F;--line2:#243456;
--ink:#F2F6FF;--mut:#9BA9C9;--dim:#5C6C8F;
--teal:#35E0D0;--teal-br:#8FF5E8;--deep:#149A90;--amber:#FFB224;--amber-br:#FFD076;
--pos:#4ADE9C;--warn:#F0A44B;--bad:#F0718A;
--gA:rgba(255,178,36,.05);--gB:rgba(53,224,208,.10);--gV:rgba(124,58,237,.09);
--navbg:rgba(10,18,38,.66);--hair:#101A32;
--panel:var(--depth);--panel2:#081020;
--disp:'Sora',sans-serif;--body:'Figtree',sans-serif;--mono:'JetBrains Mono',monospace;
--r:18px;--r-sm:12px}
html[data-theme=light]{
 --abyss:#EEF3F9;--depth:#FFFFFF;--depth2:#F6FAFD;--line:#DCE6F0;--line2:#C0D1E1;
 --ink:#0E1A2E;--mut:#4B5D75;--dim:#7E90A7;
 --teal:#0B9D92;--teal-br:#0FBCAE;--deep:#0A7E76;--amber:#B37410;--amber-br:#D6952A;
 --gA:rgba(255,178,36,.10);--gB:rgba(15,188,174,.12);--gV:rgba(124,58,237,.06);
 --navbg:rgba(255,255,255,.72);--hair:#E7EEF5;--panel:#FFFFFF;--panel2:#F4F8FC}
*{box-sizing:border-box;margin:0;padding:0}
::selection{background:rgba(53,224,208,.28)}
body{background:
 radial-gradient(1200px 700px at 85% -12%,var(--gA),transparent 58%),
 radial-gradient(1100px 780px at -8% -6%,var(--gB),transparent 52%),
 radial-gradient(900px 700px at 70% 40%,var(--gV),transparent 60%),
 radial-gradient(1400px 900px at 50% 120%,rgba(20,154,144,.10),transparent 60%),
 var(--abyss);
 color:var(--ink);font-family:var(--body);font-size:14.5px;line-height:1.65;-webkit-font-smoothing:antialiased;
 transition:background-color .3s,color .3s}
a{color:inherit;text-decoration:none}
.mono{font-family:var(--mono);font-variant-numeric:tabular-nums}
.wrap{max-width:1120px;margin:0 auto;padding:0 24px}
.teal{color:var(--teal)}.amber{color:var(--amber)}.mut{color:var(--mut)}
h1{font-family:var(--disp);font-weight:800;letter-spacing:-.035em;line-height:1.0}
h2{font-family:var(--disp);font-weight:700;letter-spacing:-.02em}
.grad{background:linear-gradient(95deg,var(--teal-br) 10%,var(--amber) 90%);-webkit-background-clip:text;background-clip:text;color:transparent}
.grad-teal{background:linear-gradient(95deg,var(--teal-br),var(--deep));-webkit-background-clip:text;background-clip:text;color:transparent}
/* ---------- nav: floating glass pill ---------- */
nav{z-index:40;padding:14px 0 6px;background:linear-gradient(180deg,var(--abyss) 30%,transparent)}
nav .wrap{display:flex;align-items:center;gap:22px;height:58px;background:var(--navbg);
 border:1px solid var(--line);border-radius:999px;padding:0 12px 0 20px;
 backdrop-filter:blur(16px);-webkit-backdrop-filter:blur(16px);
 box-shadow:0 12px 40px -18px rgba(0,0,0,.6),inset 0 1px 0 rgba(255,255,255,.04)}
.brand{display:flex;align-items:center;gap:10px;font-family:var(--disp);font-weight:700;font-size:18px;letter-spacing:-.02em}
.brand img{width:26px;height:26px;display:block;filter:drop-shadow(0 0 8px rgba(53,224,208,.5))}
.brand .p{color:var(--teal)}
.navlinks{display:flex;gap:4px;margin-left:6px}
.navlinks a{font-size:13px;font-weight:500;color:var(--mut);padding:7px 13px;border-radius:999px;transition:color .15s,background-color .15s}
.navlinks a:hover{color:var(--ink);background:rgba(255,255,255,.05)}
.navlinks a.active{color:var(--teal);background:rgba(53,224,208,.10)}
.navcta{margin-left:auto;display:flex;align-items:center;gap:10px}
.signin{font-size:13px;font-weight:500;color:var(--mut);padding:7px 12px;border-radius:999px;transition:color .15s}
.signin:hover{color:var(--teal)}
/* ---------- buttons ---------- */
button,.btn{font-family:var(--disp);font-weight:600;border:0;border-radius:999px;padding:10px 20px;font-size:13.5px;cursor:pointer;
 transition:transform .12s,filter .15s,border-color .15s,color .15s,box-shadow .15s;display:inline-flex;align-items:center;gap:8px}
button:active,.btn:active{transform:translateY(1px)}
.btn-amber{background:linear-gradient(180deg,var(--amber-br),var(--amber));color:#241802;
 box-shadow:0 6px 24px -8px rgba(255,178,36,.55),inset 0 1px 0 rgba(255,255,255,.35)}
.btn-amber:hover{filter:brightness(1.06)}
.btn-teal{background:rgba(53,224,208,.08);color:var(--teal);border:1px solid rgba(53,224,208,.4)}
.btn-teal:hover{border-color:var(--teal);box-shadow:0 0 0 4px rgba(53,224,208,.12),0 0 24px -6px rgba(53,224,208,.5)}
.btn-ghost{background:transparent;color:var(--ink);border:1px solid var(--line2)}
.btn-ghost:hover{border-color:var(--teal);color:var(--teal)}
/* ---------- labels / structure ---------- */
.eyebrow{font-family:var(--mono);font-size:11px;letter-spacing:.26em;text-transform:uppercase;color:var(--teal);display:flex;align-items:center;gap:10px}
.dot{width:7px;height:7px;border-radius:50%;background:var(--teal);box-shadow:0 0 12px var(--teal);animation:pulse 2.4s infinite}
@keyframes pulse{0%{box-shadow:0 0 0 0 rgba(53,224,208,.5)}70%{box-shadow:0 0 0 10px rgba(53,224,208,0)}100%{box-shadow:0 0 0 0 rgba(53,224,208,0)}}
.hero{position:relative;overflow:hidden}
.hexbg{position:absolute;right:-70px;top:-40px;width:420px;opacity:.05;pointer-events:none}
.lbl{font-family:var(--mono);font-size:10.5px;letter-spacing:.18em;text-transform:uppercase;color:var(--teal);display:inline-flex;align-items:center;gap:8px;margin-bottom:10px}
.lbl::before{content:"";width:6px;height:6px;border-radius:50%;background:currentColor;box-shadow:0 0 10px currentColor}
.lbl.am{color:var(--amber)}
.mini{font-family:var(--mono);font-size:10px;letter-spacing:.14em;text-transform:uppercase;color:var(--dim)}
.divider{height:1px;background:linear-gradient(90deg,transparent,var(--line2),transparent);margin:2px 0}
.pill{font-family:var(--mono);font-size:10px;border:1px solid rgba(53,224,208,.35);color:var(--teal);padding:3px 11px;border-radius:999px;background:rgba(53,224,208,.06)}
/* ---------- surfaces ---------- */
.panel{background:var(--panel2);border:1px solid var(--line);border-radius:var(--r)}
.card{position:relative;background:linear-gradient(180deg,var(--depth2),var(--panel2));border:1px solid var(--line);border-radius:var(--r);padding:22px;
 transition:transform .18s,border-color .18s,box-shadow .18s}
.card::before{content:"";position:absolute;inset:0;border-radius:var(--r);padding:1px;
 background:linear-gradient(140deg,rgba(53,224,208,.25),transparent 34%,transparent 70%,rgba(255,178,36,.14));
 -webkit-mask:linear-gradient(#000 0 0) content-box,linear-gradient(#000 0 0);-webkit-mask-composite:xor;mask-composite:exclude;
 opacity:0;transition:opacity .2s;pointer-events:none}
.card:hover{transform:translateY(-3px);box-shadow:0 20px 50px -26px rgba(53,224,208,.45)}
.card:hover::before{opacity:1}
.cols{display:flex;flex-wrap:wrap;gap:16px}
.c2>*{flex:1 1 calc(50% - 8px);min-width:250px}
.c3>*{flex:1 1 calc(33.333% - 11px);min-width:220px}
.c4>*{flex:1 1 calc(25% - 12px);min-width:185px}
/* ---------- code ---------- */
code,pre{font-family:var(--mono)}
pre{position:relative;background:#04070F;border:1px solid var(--line);border-radius:var(--r-sm);padding:15px 17px;overflow:auto;font-size:12.5px;line-height:1.8;color:#A9F0E6}
html[data-theme=light] pre{background:#0E1A2E;color:#9FEDE2}
pre .c{color:var(--dim)}
.codeline{display:flex;align-items:center;gap:10px;background:#04070F;border:1px solid var(--line);border-radius:10px;padding:8px 8px 8px 13px;margin-top:11px}
html[data-theme=light] .codeline{background:#0E1A2E}
.codeline code{flex:1;font-size:11px;color:#9FEDE2;white-space:nowrap;overflow:auto;scrollbar-width:none}
.codeline code::-webkit-scrollbar{display:none}
.copybtn{flex:none;font-family:var(--mono);font-size:10px;letter-spacing:.08em;color:var(--mut);background:rgba(255,255,255,.05);border:1px solid var(--line2);border-radius:7px;padding:5px 10px;cursor:pointer;transition:color .15s,border-color .15s}
.copybtn:hover{color:var(--teal);border-color:var(--teal)}
/* ---------- tables ---------- */
.tbl{width:100%;border-collapse:collapse;font-size:13px}
.tbl th{font-family:var(--mono);font-size:10px;letter-spacing:.14em;text-transform:uppercase;color:var(--dim);text-align:left;padding:13px 16px;border-bottom:1px solid var(--line)}
.tbl td{padding:13px 16px;border-bottom:1px solid var(--hair)}
.tbl tr:last-child td{border-bottom:0}
.tbl tbody tr{transition:background-color .12s}
.tbl tbody tr:hover{background:rgba(53,224,208,.045)}
.badge{font-family:var(--mono);font-size:10px;padding:3px 9px;border-radius:999px;border:1px solid var(--line2);color:var(--mut)}
.badge.ok{color:var(--teal);border-color:rgba(53,224,208,.4);background:rgba(53,224,208,.09)}
.badge.cc{color:var(--amber);border-color:rgba(255,178,36,.4);background:rgba(255,178,36,.09)}
/* ---------- stats ---------- */
.stats{display:flex;flex-wrap:wrap;gap:1px;background:var(--line);border:1px solid var(--line);border-radius:var(--r);overflow:hidden}
.stat{flex:1 1 22%;min-width:150px;background:linear-gradient(180deg,var(--depth2),var(--panel2));padding:20px 22px}
.stat .n{font-family:var(--disp);font-weight:700;font-size:30px;margin-top:6px;letter-spacing:-.03em}
.stat .l{font-family:var(--mono);font-size:9.5px;letter-spacing:.16em;text-transform:uppercase;color:var(--dim)}
/* ---------- forms ---------- */
input,select,textarea{font-family:var(--body);background:var(--panel2);border:1px solid var(--line2);color:var(--ink);border-radius:11px;padding:10px 13px;font-size:13.5px;outline:none;transition:border-color .15s,box-shadow .15s}
input:focus,select:focus,textarea:focus{border-color:var(--teal);box-shadow:0 0 0 4px rgba(53,224,208,.13)}
select{appearance:none;-webkit-appearance:none;background-image:linear-gradient(45deg,transparent 50%,var(--mut) 50%),linear-gradient(135deg,var(--mut) 50%,transparent 50%);background-position:calc(100% - 17px) 55%,calc(100% - 12px) 55%;background-size:5px 5px;background-repeat:no-repeat;padding-right:32px}
.field{display:flex;flex-direction:column;gap:5px}
.field>span{font-family:var(--mono);font-size:9.5px;letter-spacing:.15em;text-transform:uppercase;color:var(--dim)}
.filterbar{display:flex;gap:14px;flex-wrap:wrap;align-items:flex-end}
/* ---------- empty state ---------- */
.empty{padding:42px 20px;text-align:center;color:var(--mut)}
.empty svg{width:36px;height:36px;color:var(--dim);margin-bottom:12px}
.empty .et{font-family:var(--disp);font-weight:600;font-size:15px;color:var(--ink);margin-bottom:4px}
.empty .es{font-size:12.5px;margin-bottom:16px}
.stepchip{display:inline-flex;align-items:center;justify-content:center;width:22px;height:22px;border-radius:7px;background:rgba(53,224,208,.12);border:1px solid rgba(53,224,208,.35);color:var(--teal);font-family:var(--mono);font-size:11px;font-weight:600;margin-right:8px;flex:none}
/* ---------- sonar launch cards (signature) ---------- */
.lgrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:14px}
.lcard{position:relative;display:flex;flex-direction:column;padding:17px 17px 15px;border:1px solid var(--line);border-radius:var(--r);
 background:linear-gradient(180deg,var(--depth2),var(--panel2));transition:border-color .18s,transform .15s,box-shadow .18s;overflow:hidden}
.lcard:hover{border-color:rgba(53,224,208,.5);transform:translateY(-2px);box-shadow:0 18px 44px -24px rgba(53,224,208,.5)}
.lhead{display:flex;align-items:center;gap:13px}
.licon{position:relative;width:46px;height:46px;flex:none;display:flex;align-items:center;justify-content:center;color:var(--teal);
 background:radial-gradient(circle at 30% 25%,rgba(53,224,208,.18),rgba(53,224,208,.04));border:1px solid rgba(53,224,208,.3);border-radius:13px}
.licon svg{width:25px;height:25px}
.lcard:hover .licon::after{content:"";position:absolute;inset:-1px;border-radius:13px;border:1px solid rgba(53,224,208,.6);animation:ping 1s ease-out}
@keyframes ping{0%{transform:scale(1);opacity:.8}100%{transform:scale(1.7);opacity:0}}
.lmeta{flex:1;min-width:0}
.lname{font-family:var(--disp);font-weight:600;text-transform:capitalize;font-size:15px}
.ldesc{font-size:12px;color:var(--mut);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.lport{font-family:var(--mono);font-size:9.5px;color:var(--dim);border:1px solid var(--line2);border-radius:999px;padding:2px 9px;flex:none}
.lbtn{flex:none;padding:8px 16px;font-size:12.5px}
.lfoot{display:flex;align-items:center;gap:10px;margin-top:11px}
.lfoot .codeline{margin-top:0;flex:1;min-width:0}
.lres{margin-top:16px;padding:17px 19px;border:1px solid var(--line2);border-radius:var(--r-sm);background:linear-gradient(180deg,var(--depth2),var(--panel2))}
.lresok{color:var(--pos);font-family:var(--disp);font-weight:600;margin-bottom:6px}
.lres pre{margin-top:10px;font-size:12px;white-space:pre-wrap}
/* ---------- footer ---------- */
footer{border-top:1px solid var(--line);margin-top:64px;background:linear-gradient(180deg,transparent,rgba(53,224,208,.03))}
footer .fcols{display:flex;flex-wrap:wrap;gap:38px;padding:40px 24px 10px;max-width:1120px;margin:0 auto}
footer .fcol{min-width:150px}
footer .fcol .fh{font-family:var(--mono);font-size:10px;letter-spacing:.18em;text-transform:uppercase;color:var(--dim);margin-bottom:12px}
footer .fcol a{display:block;font-size:13px;color:var(--mut);padding:4px 0;transition:color .15s}
footer .fcol a:hover{color:var(--teal)}
footer .wrap{display:flex;flex-wrap:wrap;gap:14px;justify-content:space-between;align-items:center;padding:22px 24px 44px;font-family:var(--mono);font-size:11px;color:var(--dim)}
footer .fb{display:flex;align-items:center;gap:9px;color:var(--mut)}
footer .fb img{width:18px;height:18px;opacity:.85}
/* ---------- theme toggle ---------- */
.themetoggle{display:inline-flex;align-items:center;justify-content:center;width:36px;height:36px;border-radius:999px;border:1px solid var(--line2);background:transparent;color:var(--mut);cursor:pointer;padding:0;transition:color .15s,border-color .15s}
.themetoggle:hover{color:var(--teal);border-color:var(--teal)}
.themetoggle svg{width:16px;height:16px}
.themetoggle .sun{display:inline-flex}.themetoggle .moon{display:none}
html[data-theme=light] .themetoggle .sun{display:none}html[data-theme=light] .themetoggle .moon{display:inline-flex}
html[data-theme=light] .hexbg{opacity:.10}
.card,.panel,.stat,nav .wrap{transition:background-color .3s,border-color .3s}
@media(max-width:780px){.navlinks{display:none}nav .wrap{height:54px}}
@media(prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}}
</style></head><body>"""

_NAV = """<nav class="navbar navbar-expand-lg sticky-top"><div class="wrap">
<a class="brand" href="/"><img src="/static/petabyte-logo.png" alt="Petabyte"/><span><b>Petabyte</b><span class="p">.</span></span></a>
<button class="navbar-toggler d-lg-none ms-auto" type="button" data-bs-toggle="collapse" data-bs-target="#pbnav" aria-controls="pbnav" aria-expanded="false" aria-label="Toggle navigation">
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M4 7h16M4 12h16M4 17h16"/></svg>
</button>
<div class="collapse navbar-collapse" id="pbnav">
<div class="navlinks">
  <a href="/marketplace">Marketplace</a><a href="/pricing">Pricing</a>
  <a href="/install">For GPU owners</a><a href="/security">Security</a><a href="/developers">Developers</a>
</div>
<div class="navcta">
  <a class="signin" id="adminlink" href="/admin" style="display:none">Admin</a>
  <a class="signin" id="mename" href="/account" style="display:none;color:var(--teal)"></a>
  <button class="themetoggle" onclick="toggleTheme()" aria-label="Toggle light or dark theme" title="Toggle light / dark">
    <svg class="sun" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M2 12h2M20 12h2M5 5l1.4 1.4M17.6 17.6 19 19M19 5l-1.4 1.4M6.4 17.6 5 19"/></svg>
    <svg class="moon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8Z"/></svg>
  </button>
  <a class="signin" id="signinlink" href="/login">Sign in</a>
  <a class="signin" id="signoutlink" href="#" onclick="signout();return false" style="display:none">Sign out</a>
  <a class="btn btn-amber" href="/app">Open app</a>
</div>
</div>
</div></nav>"""

_FOOT = """<footer>
<div class="fcols">
  <div class="fcol" style="flex:1.4;min-width:200px">
    <span class="fb"><img src="/static/petabyte-logo.png" alt=""/> <b style="font-family:var(--disp);color:var(--ink)">Petabyte</b></span>
    <p class="mut" style="font-size:12px;margin-top:10px;max-width:30ch">Deep Ocean Compute — a verified marketplace for community GPU power. Riyadh.</p>
  </div>
  <div class="fcol"><div class="fh">Product</div>
    <a href="/marketplace">Marketplace</a><a href="/pricing">Pricing</a><a href="/app">Console</a>
  </div>
  <div class="fcol"><div class="fh">Use cases</div>
    <a href="/artists">Rendering &amp; art</a><a href="/gamers">Game servers</a><a href="/developers">AI &amp; inference</a>
  </div>
  <div class="fcol"><div class="fh">Sell compute</div>
    <a href="/install">List your PC</a><a href="/account">Earnings</a><a href="/keys">API keys</a>
  </div>
  <div class="fcol"><div class="fh">Developers</div>
    <a href="/docs">API reference</a><a href="/developers">Quickstart</a><a href="/keys">API keys</a>
  </div>
  <div class="fcol"><div class="fh">Company</div>
    <a href="/security">Security &amp; trust</a><a href="/investors">About</a><a href="/status">Status</a>
  </div>
  <div class="fcol"><div class="fh">Legal</div>
    <a href="/privacy">Privacy</a><a href="/terms">Terms</a><a href="/acceptable-use">Acceptable use</a>
  </div>
</div>
<div class="wrap">
<span class="fb">© Petabyte · Deep Ocean Compute</span>
<span>verified compute · escrowed settlement</span>
</div></footer>"""

# token bootstrap: capture #t=JWT from the OAuth redirect, persist across pages
_AUTHJS = """<script>
(function(){var h=location.hash.match(/t=([^&]+)/);if(h){localStorage.setItem('pb_token',decodeURIComponent(h[1]));history.replaceState(null,'',location.pathname);}})();
function tok(){return localStorage.getItem('pb_token');}
(function(){try{var p=location.pathname.replace(new RegExp('[/]$'),'')||'/';document.querySelectorAll('.navlinks a').forEach(function(a){if(a.getAttribute('href')===p)a.classList.add('active');});}catch(e){}})();
function authed(){return !!tok();}
async function api(p,o){o=o||{};o.headers=Object.assign({'Content-Type':'application/json'},o.headers||{});
 if(tok())o.headers['Authorization']='Bearer '+tok();var r=await fetch(p,o);var b={};try{b=await r.json()}catch(e){}return {ok:r.ok,status:r.status,body:b};}
function toggleTheme(){var h=document.documentElement,t=h.getAttribute('data-theme')==='light'?'dark':'light';h.setAttribute('data-theme',t);h.setAttribute('data-bs-theme',t);try{localStorage.setItem('pb_theme',t);}catch(e){}}
function signout(){try{localStorage.removeItem('pb_token');}catch(e){}location.href='/';}
(function(){var si=document.getElementById('signinlink'),so=document.getElementById('signoutlink');
 if(authed()){if(si)si.style.display='none';if(so)so.style.display='';}else{if(si)si.style.display='';if(so)so.style.display='none';}})();
(async function(){try{if(authed()){var r=await api('/me');if(r.ok){var m=document.getElementById('mename');if(m){m.textContent='● '+r.body.username;m.style.display='';}
 if(r.body.is_admin){var a=document.getElementById('adminlink');if(a)a.style.display='';}}}}catch(e){}})();
window.PBICONS={
 blender:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><path d="M12 2 3 7v10l9 5 9-5V7z"/><path d="M3 7l9 5 9-5M12 12v10"/></svg>',
 comfyui:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><circle cx="5" cy="6" r="2.2"/><circle cx="19" cy="6" r="2.2"/><circle cx="12" cy="18" r="2.2"/><path d="M7 7l3.5 9M17 7l-3.5 9"/></svg>',
 "sd-webui":'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><rect x="3" y="4" width="18" height="16" rx="2"/><circle cx="8.5" cy="9" r="1.6"/><path d="m3 17 5-4 4 3 3-3 6 5"/></svg>',
 "tensorrt-llm":'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><rect x="6" y="6" width="12" height="12" rx="2"/><path d="M9 2v3M15 2v3M9 19v3M15 19v3M2 9h3M2 15h3M19 9h3M19 15h3"/></svg>',
 ollama:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><path d="M4 5h16v10H8l-4 4z"/></svg>',
 vllm:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><path d="M13 2 4 14h7l-1 8 9-12h-7z"/></svg>',
 ffmpeg:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><rect x="3" y="4" width="18" height="16" rx="2"/><path d="M7 4v16M17 4v16M3 9h4M3 15h4M17 9h4M17 15h4"/></svg>',
 minecraft:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><path d="M4 20 13 11M3 8c3-3 7-4 10-3M22 11c1-4-1-8-4-9"/><path d="m11 9 4 4"/></svg>',
 valheim:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><path d="M5 21 13 13M13 3c5 0 8 3 8 8-4 0-6-1-8-4-2 3-4 4-8 4 0-5 3-8 8-8z"/></svg>',
 factorio:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><circle cx="12" cy="12" r="3.2"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3M5 5l2.1 2.1M16.9 16.9 19 19M19 5l-2.1 2.1M7.1 16.9 5 19"/></svg>',
 _default:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><rect x="4" y="4" width="16" height="16" rx="3"/><path d="M9 9h6v6H9z"/></svg>'};
function pbIcon(n){return PBICONS[n]||PBICONS._default;}
function pbEmpty(cols,title,sub,ctaHref,ctaText){
 return '<tr><td colspan='+cols+'><div class="empty">'+
  '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><rect x="3" y="5" width="18" height="14" rx="2"/><path d="M3 10h18M8 15h4"/></svg>'+
  '<div class="et">'+title+'</div><div class="es">'+sub+'</div>'+
  (ctaHref?('<a class="btn btn-teal" href="'+ctaHref+'">'+ctaText+'</a>'):'')+'</div></td></tr>';}
window._PBCMDS={};
function pbCmd(name,hours){return 'curl -sX POST https://petabyte.market/launch -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d \'{"template":"'+name+'","hours":'+(hours||2)+'}\'';}
async function pbCopy(name,btn){var c=window._PBCMDS[name]||'';try{await navigator.clipboard.writeText(c);}catch(e){
 var ta=document.createElement('textarea');ta.value=c;document.body.appendChild(ta);ta.select();try{document.execCommand('copy');}catch(_){ }document.body.removeChild(ta);}
 if(btn){var o=btn.textContent;btn.textContent='copied';setTimeout(function(){btn.textContent=o;},1200);}}
async function renderLaunch(elId,kinds,hours){var el=document.getElementById(elId);if(!el)return;
 var r=await fetch('/templates');var b=await r.json();var ts=(b.templates||[]).filter(function(t){return kinds.indexOf(t.kind)>=0;});
 if(!ts.length){el.innerHTML='<span class="mut">Nothing available right now.</span>';return;}
 el.className='lgrid';
 el.innerHTML=ts.map(function(t){var cmd=pbCmd(t.name,hours);window._PBCMDS[t.name]=cmd;
  return '<div class="lcard">'+
   '<div class="lhead"><div class="licon">'+pbIcon(t.name)+'</div>'+
   '<div class="lmeta"><div class="lname">'+t.name+'</div><div class="ldesc">'+(t.desc||'')+'</div></div>'+
   (t.port?('<span class="lport">:'+t.port+'</span>'):'<span class="lport">batch</span>')+'</div>'+
   '<div class="lfoot">'+
    '<div class="codeline"><code>'+cmd.replace(/&/g,'&amp;').replace(/</g,'&lt;')+'</code>'+
    '<button class="copybtn" onclick="pbCopy(\''+t.name+'\',this)">copy</button></div>'+
    '<button class="btn btn-amber lbtn" onclick="pbLaunch(\''+t.name+'\','+(hours||2)+')">Launch</button>'+
   '</div></div>';}).join('');}
function _lres(){var e=document.getElementById('launchresult');if(e){e.style.display='';}return e;}
async function pbLaunch(name,hours){var out=_lres();if(!out)return;
 if(typeof authed==='function'&&!authed()){out.innerHTML='<div class="lres">Please <a class="teal" href="/login">sign in</a> to launch.</div>';return;}
 out.innerHTML='<div class="lres">Reserving a GPU for <b style="text-transform:capitalize">'+name+'</b>…</div>';
 var r=await api('/launch',{method:'POST',body:JSON.stringify({template:name,hours:hours||2})});
 if(r.status===401){out.innerHTML='<div class="lres">Please <a class="teal" href="/login">sign in</a> first.</div>';return;}
 if(r.status===402){out.innerHTML='<div class="lres">Add funds first — <a class="teal" href="/account">open your wallet</a>.</div>';return;}
 if(r.status===409){out.innerHTML='<div class="lres">No matching GPU is online right now. Try again shortly.</div>';return;}
 if(!r.ok){out.innerHTML='<div class="lres">Could not launch (error '+r.status+').</div>';return;}
 var b=r.body;
 out.innerHTML='<div class="lres"><div class="lresok">✓ Reserved '+name+' on '+(b.gpu_model||'a node')+' · booking #'+b.booking_id+' · $'+(b.gross_amount!=null?b.gross_amount:'?')+' / '+b.hours+'h</div>'+
  '<div class="mut" style="margin-bottom:4px">Your stable address — it stays the same even if the node changes:</div>'+
  '<pre>'+((b.url&&b.url.ssh)?b.url.ssh:'')+((b.url&&b.url.http)?'\\n'+b.url.http:'')+'</pre>'+
  '<div class="mut" id="lprep" style="margin-top:8px">Preparing your VM…</div></div>';
 pbPollVM(b.vm_id,b.port);}
function pbPollVM(vmid,port){var prep=document.getElementById('lprep'),t0=Date.now();
 var iv=setInterval(async function(){var r=await api('/vm/'+vmid);if(!r.ok)return;var st=r.body.status;
  if(st==='running'){clearInterval(iv);prep.innerHTML='<b class="teal">Ready</b> — connect with the address above'+(port?(' (port '+port+')'):'')+'.';}
  else if(st==='failed'){clearInterval(iv);prep.textContent='No node could host it — you were refunded.';}
  else if(st==='migrating'){prep.textContent='Node changed — reconnecting to a new host (same address)…';}
  else if(st==='stopped'){clearInterval(iv);prep.textContent='Stopped.';}
  else if(Date.now()-t0>90000){clearInterval(iv);prep.innerHTML='Still starting — track it under <a class="teal" href="/account">your VMs</a>.';}
  else{prep.textContent='Preparing your VM… ('+st+')';}},2500);}
</script>"""


def _page(title, body):
    return _HEAD.replace("%%TITLE%%", title) + _NAV + _AUTHJS + body + _FOOT + "</body></html>"


LANDING_HTML = _page("Petabyte — the compute exchange", """
<div class="hero"><div class="wrap" style="padding:74px 24px 30px">
  <img class="hexbg" src="/static/petabyte-logo.png" alt=""/>
  <div class="cols" style="align-items:center;gap:34px">
    <div style="flex:1.35 1 420px;min-width:300px">
      <div class="eyebrow"><span class="dot"></span> verified gpu marketplace</div>
      <h1 style="font-size:clamp(40px,6.8vw,76px);margin:20px 0 16px;max-width:15ch">GPU compute <span class="grad">without cloud prices.</span></h1>
      <p class="mut" style="font-size:17px;max-width:52ch">Rent GPUs by the hour from verified hosts, or earn from hardware you already own. Your money sits in escrow until the work is done — if a node drops, you're refunded.</p>
      <div style="display:flex;gap:12px;margin-top:28px;flex-wrap:wrap">
        <a class="btn btn-amber" href="/marketplace">Browse live GPUs →</a>
        <a class="btn btn-teal" href="/install">List your GPU</a>
      </div>
    </div>
    <div class="panel" style="flex:1 1 320px;min-width:290px;padding:18px 20px">
      <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:12px">
        <span class="mini">Available now</span>
        <a class="mini teal" href="/marketplace">See all →</a>
      </div>
      <div id="heropreview"><div class="mut mono" style="font-size:12px;padding:22px 0;text-align:center">Loading inventory…</div></div>
      <div id="herostats" style="display:none;border-top:1px solid var(--hair);margin-top:12px;padding-top:12px">
        <span class="mini"><span id="s_nodes" class="teal mono">0</span> hosts online · <span id="s_specs" class="mono">0</span> GPUs listed</span>
      </div>
    </div></div>
  </div>
</div></div>

<!-- launch anything: the signature cards, on the front door -->
<div class="wrap" style="padding:40px 24px 8px">
  <div class="lbl" style="margin-bottom:4px">Launch anything</div>
  <h2 style="font-size:clamp(22px,3vw,30px);margin-bottom:6px">Games, art tools, AI stacks — <span class="grad-teal">one click or one line.</span></h2>
  <p class="mut" style="max-width:62ch;margin-bottom:18px">Every card is a real workload. Press Launch, or copy the command — either way we book the cheapest verified GPU and hand you the address.</p>
  <div id="launchgrid"></div>
  <div id="launchresult" style="display:none"></div>
</div>

<!-- audiences -->
<div class="wrap" style="padding:44px 24px 8px"><div class="cols c4">
  <a class="card" href="/gamers" style="display:block">
    <div class="lbl">Gamers</div>
    <h2 style="font-size:17px;margin-bottom:6px">Spin up a game server</h2>
    <p class="mut" style="font-size:13px">Minecraft, Valheim, Factorio — dedicated, hourly, refunded if the node drops.</p></a>
  <a class="card" href="/artists" style="display:block">
    <div class="lbl">Artists</div>
    <h2 style="font-size:17px;margin-bottom:6px">Render 3D &amp; video</h2>
    <p class="mut" style="font-size:13px">Blender, ComfyUI, SD — farm-grade GPUs below the big render farms.</p></a>
  <a class="card" href="/developers" style="display:block">
    <div class="lbl">Builders</div>
    <h2 style="font-size:17px;margin-bottom:6px">Cheaper AI compute</h2>
    <p class="mut" style="font-size:13px">H100-class below cloud on-demand. State intent — the router places the job.</p></a>
  <a class="card" href="/install" style="display:block">
    <div class="lbl am">GPU owners</div>
    <h2 style="font-size:17px;margin-bottom:6px">Turn idle silicon into income</h2>
    <p class="mut" style="font-size:13px">One command to list. Weekly payouts — bank, USDC, or gift card.</p></a>
</div></div>
<script>
async function heroPreview(){
 try{
  var r=await fetch('/marketplace/specs?sort=price');var b=await r.json();
  var el=document.getElementById('heropreview');
  var rows=(b.specs||[]).slice(0,3);
  if(!rows.length){
    el.innerHTML='<div class="empty" style="padding:18px 6px"><div class="et" style="font-size:13px">No GPUs online yet</div>'+
      '<div class="es" style="font-size:12px">Be the first host — one command, and you are listed.</div>'+
      '<a class="btn btn-teal" href="/install">List your GPU</a></div>';
  }else{
    el.innerHTML=rows.map(function(s){
      var save=(s.cloud_reference&&s.price_per_hour<s.cloud_reference)?Math.round((1-s.price_per_hour/s.cloud_reference)*100):0;
      return '<a href="/gpu/'+s.spec_id+'" style="display:flex;align-items:center;gap:12px;padding:11px 0;border-bottom:1px solid var(--hair)">'+
       '<div style="flex:1;min-width:0">'+
        '<div style="font-family:var(--disp);font-weight:600;font-size:14px">'+(s.gpu_model||'CPU')+(s.vram_gb?' <span class="mut" style="font-weight:400">· '+s.vram_gb+'GB</span>':'')+'</div>'+
        '<div class="mini" style="margin-top:2px">'+(s.region||'unknown region')+' · '+(s.available_units>0?'<span class="teal">available now</span>':'busy')+'</div>'+
       '</div>'+
       '<div style="text-align:right;flex:none">'+
        '<div class="mono amber" style="font-size:15px;font-weight:600">$'+Number(s.price_per_hour).toFixed(2)+'</div>'+
        '<div class="mini">/hour'+(save>0?' · <span style="color:var(--pos)">'+save+'% off</span>':'')+'</div>'+
       '</div></a>';}).join('');
  }
  // only show counters when they are real — an empty metric reads as "this does not work"
  var st=await (await fetch('/marketplace/stats')).json();
  if(st.nodes_online>0||st.specs_listed>0){
    document.getElementById('s_nodes').textContent=st.nodes_online;
    document.getElementById('s_specs').textContent=st.specs_listed;
    document.getElementById('herostats').style.display='';
  }
 }catch(e){}
}
heroPreview();setInterval(heroPreview,10000);
renderLaunch('launchgrid',['game','art','render','ai'],2);
</script>""")


MARKETPLACE_HTML = _page("Petabyte — marketplace", """
<div class="wrap" style="padding:48px 22px 10px">
  <div class="eyebrow"><span class="dot"></span> live inventory</div>
  <h1 style="font-size:clamp(30px,5vw,40px);margin:16px 0 8px">Available <span class="grad-teal">GPUs</span></h1>
  <p class="mut" id="mnote">Loading verified nodes…</p>
</div>
<div class="wrap" style="padding:12px 22px 30px">
  <div class="panel filterbar" style="padding:16px 18px;margin-bottom:14px">
    <div class="field"><span>GPU model</span><input id="fgpu" placeholder="H100, 4090…" size="10" onkeydown="if(event.key==='Enter')load()"/></div>
    <div class="field"><span>Max $/hr</span><input id="fprice" type="number" placeholder="any" size="7" step="0.1" onkeydown="if(event.key==='Enter')load()"/></div>
    <div class="field"><span>Min VRAM</span><input id="fvram" type="number" placeholder="GB" size="7" onkeydown="if(event.key==='Enter')load()"/></div>
    <div class="field"><span>Region</span><input id="fregion" placeholder="any" size="8" onkeydown="if(event.key==='Enter')load()"/></div>
    <div class="field"><span>Sort by</span><select id="fsort" onchange="load()"><option value="price">Cheapest</option><option value="rep">Most trusted</option><option value="vram">Most VRAM</option></select></div>
    <label class="mini" style="display:flex;align-items:center;gap:6px;padding-bottom:9px"><input id="fconf" type="checkbox" style="width:15px;height:15px;padding:0"/> confidential</label>
    <div style="display:flex;gap:8px;padding-bottom:1px">
      <button class="btn btn-teal" onclick="load()">Apply</button>
      <button class="btn-ghost btn" onclick="clearf()">Reset</button>
    </div>
  </div>
  <div class="panel" style="overflow:auto">
    <table class="tbl"><thead><tr><th>GPU</th><th>VRAM</th><th>$/hr</th><th>vs cloud</th><th>trust</th><th>region</th><th>rep</th><th>free</th></tr></thead>
    <tbody id="mrows"><tr><td colspan="8" style="padding:24px;text-align:center" class="mut mono">loading…</td></tr></tbody></table>
  </div>
  <div style="margin-top:18px;display:flex;gap:14px;align-items:center;flex-wrap:wrap">
    <a class="btn btn-amber" href="/app">Sign in to book →</a>
    <span class="mut">Browsing is open. Booking needs an account. Availability updates live.</span>
  </div>
</div>
<script>
function qs(){var p=new URLSearchParams();var g=v('fgpu');if(g)p.set('gpu',g);var pr=v('fprice');if(pr)p.set('max_price',pr);
 var vr=v('fvram');if(vr)p.set('min_vram',vr);var rg=v('fregion');if(rg)p.set('region',rg);
 if(document.getElementById('fconf').checked)p.set('confidential','true');p.set('sort',document.getElementById('fsort').value);return p.toString();}
function v(id){return (document.getElementById(id).value||'').trim();}
function clearf(){['fgpu','fprice','fvram','fregion'].forEach(function(i){document.getElementById(i).value='';});document.getElementById('fconf').checked=false;load();}
async function load(){var r=await fetch('/marketplace/specs?'+qs());var b=await r.json();var aws=b.aws_reference||12.29;
 document.getElementById('mnote').textContent=b.count?b.count+' GPUs match · reference cloud $'+aws+'/hr':'No GPUs match these filters.';
 var tb=document.getElementById('mrows');if(!b.count){tb.innerHTML=pbEmpty(8,'No GPUs match','Widen your filters, or be the first to list one.','/install','List your GPU');return;}
 tb.innerHTML=b.specs.map(function(s){var save=Math.round((1-s.price_per_hour/aws)*100);
  var t=[];if(s.confidential)t.push('<span class="badge cc">conf</span>');if(s.region_verified)t.push('<span class="badge ok">region ✓</span>');
  var rc=s.reputation_score>=80?'var(--pos)':s.reputation_score>=60?'var(--warn)':'var(--bad)';
  var rep=(s.reputation_score!=null?s.reputation_score:'—')+(s.success_rate!=null?' <span class="mut" style="font-size:10px">('+s.success_rate+'%)</span>':'');
  var vram=s.vram_gb?((s.gpu_count>1?s.gpu_count+'× ':'')+s.vram_gb+'GB'):'—';
  return '<tr><td style="font-family:var(--disp);font-weight:600">'+(s.gpu_model||'CPU')+'</td>'+
   '<td class="mono mut" style="font-size:12px">'+vram+'</td>'+
   '<td class="mono amber">$'+s.price_per_hour.toFixed(2)+(s.auto_price?' <span class="badge cc" title="demand-priced within seller bounds">auto</span>':'')+'</td>'+
   '<td class="mono" style="color:var(--pos)">'+(save>0?'−'+save+'%':'—')+'</td>'+
   '<td>'+(t.join(' ')||'<span class="mut mono" style="font-size:11px">standard</span>')+'</td>'+
   '<td class="mut mono" style="font-size:12px">'+(s.region||'—')+'</td>'+
   '<td class="mono" style="color:'+rc+'">'+rep+'</td>'+
   '<td class="mono" style="color:var(--teal)">'+s.available_units+'</td></tr>';}).join('');}
load();setInterval(load,8000);
</script>""")


INSTALL_HTML = _page("Petabyte — become a seller", """
<div class="wrap" style="padding:48px 22px 10px">
  <div class="eyebrow"><span class="dot"></span> node onboarding</div>
  <h1 style="font-size:clamp(30px,5vw,40px);margin:16px 0 8px">List your GPU in <span class="grad-teal">one command</span></h1>
  <p class="mut" style="max-width:56ch">Any NVIDIA machine can become a node. The installer verifies your hardware, sandboxes jobs in Docker, and brings you online in ~30 seconds. No exclusivity.</p>
</div>
<div class="wrap" style="padding:6px 22px 0">
  <div class="card" style="border-color:rgba(79,214,201,.3);background:linear-gradient(180deg,rgba(79,214,201,.05),transparent)">
    <div class="lbl">Step 1 · your node key</div>
    <p class="mut" id="ikhint">Nodes connect with an API key — no password ever lives on the machine. <a class="teal" href="/login">Sign in</a> to generate one.</p>
    <div id="ikauthed" style="display:none">
      <p class="mut" style="margin-bottom:12px">Generate a node key, then paste it into the command below as <code class="teal">PETABYTE_API_KEY</code>. The node registers &amp; attests itself with this key.</p>
      <button class="btn-amber" onclick="mkkey()">Create node key</button>
      <pre id="ikkey" style="display:none;margin-top:14px"></pre>
    </div>
  </div>
</div>
<div class="wrap" style="padding:12px 22px 30px">
  <div class="mini" style="margin:6px 0 12px">Step 2 · run the installer</div>
  <div class="cols c3">
    <div class="card"><div class="lbl">Linux · Ubuntu/Debian</div>
      <pre>PETABYTE_API_URL=https://petabyte.market \\
PETABYTE_API_KEY=pk_your_node_key \\
PRICE_PER_HOUR=1.5 \\
bash &lt;(curl -fsSL https://petabyte.market/install.sh)</pre></div>
    <div class="card"><div class="lbl">Windows · WSL2</div>
      <pre>$env:PETABYTE_API_URL="https://petabyte.market"
$env:PETABYTE_API_KEY="pk_your_node_key"
$env:PRICE_PER_HOUR="1.5"
irm https://petabyte.market/install.ps1 | iex</pre>
      <p class="mut" style="font-size:12px;margin-top:9px">Elevated PowerShell. Installs WSL2 + the agent.</p></div>
    <div class="card"><div class="lbl">Verify</div>
      <pre>systemctl status petabyte-agent
journalctl -u petabyte-agent -f</pre>
      <p class="mut" style="font-size:12px;margin-top:9px">Your GPU appears in the <a class="teal" href="/marketplace">marketplace</a> within a minute.</p></div>
  </div>
  <div class="card" style="margin-top:16px">
    <div class="lbl">What should I charge?</div>
    <p class="mut" style="margin-bottom:10px">Type your GPU — we suggest a price from what similar live nodes charge and the cloud reference. You always set the final number.</p>
    <div style="display:flex;gap:10px;flex-wrap:wrap;align-items:center">
      <input id="pgpu" placeholder="e.g. RTX 4090" size="14" onkeydown="if(event.key==='Enter')suggest()"/>
      <button class="btn btn-teal" onclick="suggest()">Suggest a price</button>
      <span id="psug" class="mono" style="font-size:13px"></span>
    </div>
  </div>
  <div class="card" style="margin-top:16px"><div class="lbl">Try it risk-free</div>
    <p class="mut">The agent runs in an isolated Linux sandbox — it never touches your games or files, and only works when your PC is idle. <b class="teal">Pause</b> anytime, or <b class="teal">remove it completely</b> in one command. If Petabyte turned on WSL for you, uninstalling turns it back off.</p>
    <pre style="margin-top:10px">$env:PETABYTE_ACTION="pause";     irm https://petabyte.market/manage.ps1 | iex
$env:PETABYTE_ACTION="uninstall"; irm https://petabyte.market/manage.ps1 | iex</pre>
  </div>
  <div class="card" style="margin-top:16px"><div class="lbl am">Get paid</div>
    <p class="mut">One balance. Withdraw anytime or on a weekly schedule — bank, USDC, or gift card. Opt in to idle-fallback and earn a background trickle whenever the node isn't rented. <a class="teal" href="/app">Open the app →</a></p>
  </div>
</div>
<script>
async function suggest(){var g=(document.getElementById('pgpu').value||'').trim();
  var r=await fetch('/pricing/suggest?gpu_model='+encodeURIComponent(g));var b=await r.json();
  document.getElementById('psug').innerHTML='Suggested <b class="amber">$'+b.suggested_price+'/hr</b> <span class="mut">· '+b.basis+' · cloud ≈ $'+b.cloud_reference+'</span>';}
(function(){ if(authed()){var a=document.getElementById('ikauthed'),h=document.getElementById('ikhint');if(a)a.style.display='';if(h)h.style.display='none';} })();
async function mkkey(){
  await api('/change_role',{method:'POST',body:JSON.stringify({role:'seller'})});   // idempotent
  var r=await api('/create_api_key?days=90&label=node&scopes=node,jobs',{method:'POST'});
  var el=document.getElementById('ikkey'); el.style.display='';
  el.textContent = r.ok ? ('Copy now — shown once:\\n\\nPETABYTE_API_KEY='+r.body.api_key)
                        : 'Could not create a key — make sure you are signed in.';
}
</script>""")


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


LOGIN_HTML = _page("Petabyte — sign in", """
<div class="wrap" style="max-width:440px;padding:60px 22px 40px">
  <div class="eyebrow"><span class="dot"></span> <span id="eyebrow">account</span></div>
  <h1 style="font-size:clamp(28px,5vw,36px);margin:16px 0 6px"><span id="title">Sign in</span></h1>
  <p class="mut" id="subtitle">Welcome back. Sign in to book compute or manage your nodes.</p>

  <div class="card" style="margin-top:20px">
    <label class="mini" style="display:block;margin-bottom:6px">Username</label>
    <input id="u" placeholder="username" style="width:100%" autocomplete="username"/>
    <label class="mini" style="display:block;margin:14px 0 6px">Password</label>
    <input id="p" type="password" placeholder="password (8+ characters)" style="width:100%" autocomplete="current-password"
           onkeydown="if(event.key==='Enter')go()"/>
    <button class="btn-amber" style="width:100%;justify-content:center;margin-top:18px" onclick="go()">
      <span id="btn">Sign in</span>
    </button>
    <p id="err" class="mut" style="display:none;color:var(--bad);margin-top:12px;font-size:13px"></p>

    <div style="display:flex;align-items:center;gap:10px;margin:18px 0">
      <div style="flex:1;height:1px;background:var(--line)"></div>
      <span class="mini">or</span>
      <div style="flex:1;height:1px;background:var(--line)"></div>
    </div>
    <a class="btn btn-ghost" style="width:100%;justify-content:center" href="/auth/google/login">Continue with Google</a>
  </div>

  <p class="mut" style="text-align:center;margin-top:18px;font-size:13px">
    <span id="toggletext">New here?</span>
    <a class="teal" href="#" onclick="toggleMode();return false" id="togglelink">Create an account</a>
  </p>
</div>
<script>
var mode="signin";
function toggleMode(){
  mode = mode==="signin" ? "register" : "signin";
  var reg = mode==="register";
  document.getElementById('title').textContent = reg ? "Create account" : "Sign in";
  document.getElementById('btn').textContent   = reg ? "Create account" : "Sign in";
  document.getElementById('eyebrow').textContent = reg ? "new account" : "account";
  document.getElementById('subtitle').textContent = reg
    ? "Create an account to buy compute or list your GPUs." : "Welcome back. Sign in to book compute or manage your nodes.";
  document.getElementById('toggletext').textContent = reg ? "Already have an account?" : "New here?";
  document.getElementById('togglelink').textContent = reg ? "Sign in" : "Create an account";
  document.getElementById('p').setAttribute('autocomplete', reg ? 'new-password' : 'current-password');
  document.getElementById('err').style.display='none';
}
function fail(m){var e=document.getElementById('err');e.textContent=m;e.style.display='';}
async function login(u,p){
  var r = await fetch('/login', {method:'POST',
    headers:{'Content-Type':'application/x-www-form-urlencoded'},
    body:'username='+encodeURIComponent(u)+'&password='+encodeURIComponent(p)});
  return r.ok ? (await r.json()).access_token : null;
}
async function go(){
  var u=document.getElementById('u').value.trim(), p=document.getElementById('p').value;
  if(!u||!p){fail("Enter a username and password."); return;}
  if(mode==="register"){
    if(u.length<3||u.length>64){fail("Username must be 3–64 characters."); return;}
    if(p.length<8){fail("Password must be at least 8 characters."); return;}
  }
  document.getElementById('err').style.display='none';
  try{
    if(mode==="register"){
      var rr=await fetch('/register_user',{method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({username:u,password:p})});
      if(!rr.ok){var b={};try{b=await rr.json()}catch(e){}
        if(rr.status===422){fail("Username must be 3–64 characters and password at least 8.");}
        else if(rr.status===429||rr.status===503){fail("Too many attempts — wait a moment and try again.");}
        else{fail((typeof b.detail==='string'?b.detail:null)||"That username is taken — try another."); }
        return;}
    }
    var t=await login(u,p);
    if(!t){fail(mode==="register"?"Account created — but sign-in failed. Try signing in.":"Wrong username or password."); return;}
    localStorage.setItem('pb_token', t);
    location.href='/app';
  }catch(e){fail("Network error — check your connection and try again.");}
}
</script>""")


ACCOUNT_HTML = _page("Petabyte — your account", """
<div id="guest" class="wrap" style="max-width:460px;padding:70px 22px;text-align:center">
  <img src="/static/petabyte-logo.png" style="width:56px;opacity:.8"/>
  <h1 style="font-size:28px;margin:18px 0 8px">Your account</h1>
  <p class="mut">Sign in to see your nodes, jobs, keys, and wallet in one place.</p>
  <div style="margin-top:18px"><a class="btn btn-amber" href="/login">Sign in</a></div>
</div>

<div id="hub" style="display:none">
  <!-- profile header -->
  <div class="hero"><div class="wrap" style="padding:44px 22px 10px">
    <div style="display:flex;gap:20px;align-items:center;flex-wrap:wrap">
      <div id="avatar" style="width:74px;height:74px;border-radius:18px;background:linear-gradient(135deg,var(--teal),var(--deep));display:flex;align-items:center;justify-content:center;font-family:var(--disp);font-weight:700;font-size:30px;color:#04201e"></div>
      <div style="flex:1;min-width:200px">
        <h1 id="uname" style="font-size:clamp(26px,4vw,34px);margin:0"></h1>
        <div style="display:flex;gap:8px;margin-top:8px;flex-wrap:wrap;align-items:center">
          <span id="role" class="badge"></span>
          <span id="adminbadge" class="badge cc" style="display:none">admin</span>
          <span class="mini">reputation <b id="rep" class="teal"></b></span>
        </div>
      </div>
      <div style="display:flex;gap:10px;flex-wrap:wrap">
        <a class="btn btn-teal" href="/app">Open dashboard</a>
        <button class="btn-ghost" onclick="signout()">Sign out</button>
      </div>
    </div>
    <div class="stats" style="margin-top:22px">
      <div class="stat"><div class="l">Balance</div><div class="n teal" id="bal">—</div></div>
      <div class="stat"><div class="l">Earnings</div><div class="n amber" id="earn">—</div></div>
      <div class="stat"><div class="l">My nodes</div><div class="n" id="nnodes">—</div></div>
      <div class="stat"><div class="l">My jobs</div><div class="n" id="njobs">—</div></div>
    </div>
  </div></div>

  <!-- quick access: every endpoint that matters to you -->
  <div class="wrap" style="padding:26px 22px 6px">
    <div class="mini" style="margin-bottom:12px">Quick access</div>
    <div class="cols c4">
      <a class="card" href="/marketplace" style="text-decoration:none"><b class="teal" style="font-family:var(--disp)">Rent a GPU</b><p class="mut" style="font-size:12.5px;margin-top:5px">Browse live inventory &amp; book</p></a>
      <a class="card" href="/app" style="text-decoration:none"><b class="teal" style="font-family:var(--disp)">Run a job</b><p class="mut" style="font-size:12.5px;margin-top:5px">Notebook, model, render, transcode</p></a>
      <a class="card" href="/install" style="text-decoration:none"><b class="amber" style="font-family:var(--disp)">List your GPU</b><p class="mut" style="font-size:12.5px;margin-top:5px">Become a seller · node key</p></a>
      <a class="card" href="/developers" style="text-decoration:none"><b class="amber" style="font-family:var(--disp)">API &amp; docs</b><p class="mut" style="font-size:12.5px;margin-top:5px">Build on the exchange</p></a>
    </div>
  </div>

  <!-- my nodes -->
  <div class="wrap" style="padding:26px 22px 4px">
    <div style="display:flex;justify-content:space-between;align-items:baseline;flex-wrap:wrap;gap:10px;margin-bottom:12px">
      <div class="lbl" style="margin:0">My nodes</div><a class="mini teal" href="/install">+ list a node</a>
    </div>
    <div class="panel" style="overflow:auto"><table class="tbl">
      <thead><tr><th>#</th><th>GPU</th><th>$/hr</th><th>Status</th><th>Trust</th><th>Region</th><th>Jobs</th></tr></thead>
      <tbody id="noderows"><tr><td colspan=7 class="mut mono" style="padding:20px;text-align:center">loading…</td></tr></tbody>
    </table></div>
  </div>

  <!-- my jobs -->
  <div class="wrap" style="padding:26px 22px 4px">
    <div class="lbl" style="margin-bottom:12px">My jobs</div>
    <div class="panel" style="overflow:auto"><table class="tbl">
      <thead><tr><th>#</th><th>As</th><th>GPU</th><th>Hours</th><th>Amount</th><th>Status</th><th>When</th></tr></thead>
      <tbody id="jobrows"><tr><td colspan=7 class="mut mono" style="padding:20px;text-align:center">loading…</td></tr></tbody>
    </table></div>
  </div>

  <!-- wallet -->
  <div class="wrap" style="padding:26px 22px 4px">
    <div class="lbl" style="margin-bottom:12px">Wallet</div>
    <div class="card">
      <div style="display:flex;gap:22px;flex-wrap:wrap;align-items:center">
        <div><span class="mini">Balance</span><div class="mono teal" style="font-size:20px;font-weight:600" id="wbal">—</div></div>
        <div><span class="mini">Earnings</span><div class="mono amber" style="font-size:20px;font-weight:600" id="wearn">—</div></div>
        <div style="flex:1"></div>
        <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center">
          <input id="amt" type="number" value="50" min="1" size="5" style="width:90px"/>
          <button class="btn-amber" onclick="deposit()">Add funds</button>
          <button class="btn-ghost" onclick="withdraw()">Withdraw</button>
        </div>
      </div>
      <p id="wmsg" class="mut" style="font-size:12.5px;margin-top:12px;display:none"></p>
      <div id="methods" class="mini" style="margin-top:12px"></div>
    </div>
  </div>

  <!-- api keys -->
  <div class="wrap" style="padding:26px 22px 4px">
    <div class="lbl" style="margin-bottom:12px">API keys</div>
    <div class="card">
      <div style="display:flex;gap:10px;flex-wrap:wrap;align-items:center">
        <input id="klabel" placeholder="label · my-node" size="16"/>
        <button class="btn-amber" onclick="mkkey()">Create key</button>
        <span class="mut" style="font-size:12px">Shown once — copy immediately.</span>
      </div>
      <pre id="knew" style="display:none;margin-top:12px"></pre>
    </div>
    <div class="panel" style="margin-top:12px;overflow:auto"><table class="tbl">
      <thead><tr><th>Label</th><th>Scopes</th><th>Expires</th><th>Status</th><th></th></tr></thead>
      <tbody id="keyrows"><tr><td colspan=5 class="mut mono" style="padding:18px;text-align:center">loading…</td></tr></tbody>
    </table></div>
  </div>

  <!-- my VMs -->
  <div class="wrap" id="vmsection" style="padding:8px 22px 0;display:none">
    <div class="lbl" style="margin-bottom:12px">My VMs</div>
    <div class="panel" style="overflow:auto"><table class="tbl">
      <thead><tr><th>VM</th><th>Template</th><th>Status</th><th>$/hr</th><th>Hrs left</th><th></th></tr></thead>
      <tbody id="vmrows"><tr><td colspan=6 class="mut mono" style="padding:16px;text-align:center">loading…</td></tr></tbody>
    </table></div>
  </div>

  <!-- seller earnings -->
  <div class="wrap" id="earnsection" style="padding:20px 22px 0;display:none">
    <div class="lbl" style="margin-bottom:12px">Node earnings</div>
    <div class="card">
      <div class="cols c4" style="margin-bottom:14px">
        <div><div class="mini">Earnings</div><div id="se_earn" style="font-family:var(--disp);font-size:20px" class="teal">—</div></div>
        <div><div class="mini">Utilization</div><div id="se_util" style="font-family:var(--disp);font-size:20px">—</div></div>
        <div><div class="mini">Nodes online</div><div id="se_online" style="font-family:var(--disp);font-size:20px">—</div></div>
        <div><div class="mini">Active rentals</div><div id="se_active" style="font-family:var(--disp);font-size:20px">—</div></div>
      </div>
      <div class="panel" style="overflow:auto"><table class="tbl">
        <thead><tr><th>GPU</th><th>Busy/Units</th><th>$/hr</th><th>Pricing</th><th>Rep</th><th>Jobs</th></tr></thead>
        <tbody id="se_rows"></tbody>
      </table></div>
    </div>
  </div>

  <!-- launch templates -->
  <div class="wrap" style="padding:26px 22px 34px">
    <div class="lbl" style="margin-bottom:12px">Launch on a GPU</div>
    <div class="card">
      <p class="mut" style="margin-bottom:14px">Pick a stack — one click reserves the cheapest matching GPU and starts it, then hands you a connection to run your work on.</p>
      <div id="launchgrid"></div>
      <div id="launchresult" style="display:none"></div>
    </div>
  </div>
</div>

<script>
function money(n){return '$'+Number(n||0).toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2});}
function wmsg(m){var e=document.getElementById('wmsg');e.textContent=m;e.style.display='';}
function showGuest(msg){var g=document.getElementById('guest');g.style.display='';var p=g.querySelector('p');if(p&&msg)p.textContent=msg;}
async function boot(){
  if(!authed()){showGuest('Sign in to see your nodes, jobs, keys, and wallet in one place.');return;}
  var me=await api('/me');
  if(me.status===401||me.status===403){showGuest('Your session expired — please sign in again.');return;}
  if(!me.ok){showGuest('You\\'re signed in, but your profile couldn\\'t load (error '+me.status+'). Refresh, or the server may need a redeploy.');return;}
  document.getElementById('guest').style.display='none';
  document.getElementById('hub').style.display='';
  var u=me.body;
  document.getElementById('uname').textContent=u.username;
  document.getElementById('avatar').textContent=(u.username||'?').slice(0,1).toUpperCase();
  document.getElementById('role').textContent=u.role;
  document.getElementById('role').className='badge '+(u.role==='seller'?'ok':'');
  if(u.is_admin)document.getElementById('adminbadge').style.display='';
  document.getElementById('rep').textContent=u.reputation;
  document.getElementById('bal').textContent=money(u.balance);
  document.getElementById('earn').textContent=money(u.earnings);
  document.getElementById('nnodes').textContent=u.nodes;
  document.getElementById('njobs').textContent=u.bookings;
  document.getElementById('wbal').textContent=money(u.balance);
  document.getElementById('wearn').textContent=money(u.earnings);
  loadNodes();loadJobs();loadKeys();loadMethods();loadTemplates();loadVMs();loadEarnings();
}
async function loadVMs(){var r=await api('/vm');if(!r.ok)return;var vms=r.body.vms||[];
  if(!vms.length)return; document.getElementById('vmsection').style.display='';
  document.getElementById('vmrows').innerHTML=vms.map(function(v){
    var live=(v.status==='running'||v.status==='starting'||v.status==='migrating');
    var act=live?('<button class="btn-ghost" style="padding:4px 10px;font-size:11px" onclick="vmExtend(\\''+v.vm_id+'\\')">+1h</button> <button class="btn-ghost" style="padding:4px 10px;font-size:11px" onclick="vmStop(\\''+v.vm_id+'\\')">Stop</button>'):'';
    return '<tr><td class="mono" style="font-size:11px">vm-'+v.vm_id+'</td><td style="text-transform:capitalize">'+(v.template||'')+'</td>'+
      '<td><span class="badge '+(v.status==='running'?'ok':'')+'">'+v.status+'</span></td>'+
      '<td class="mono amber">$'+Number(v.hourly_rate||0).toFixed(2)+'</td>'+
      '<td class="mono">'+(v.hours_left||0)+'h</td><td>'+act+'</td></tr>';}).join('');}
async function vmStop(id){await api('/vm/'+id+'/stop',{method:'POST'});loadVMs();}
async function vmExtend(id){var r=await api('/vm/'+id+'/extend',{method:'POST',body:JSON.stringify({hours:1})});if(r.status===402)wmsg('Add funds to extend.');loadVMs();}
async function loadEarnings(){var r=await api('/seller/earnings');if(!r.ok)return;var e=r.body;
  if(!e.nodes)return; document.getElementById('earnsection').style.display='';
  document.getElementById('se_earn').textContent=money(e.earnings_total);
  document.getElementById('se_util').textContent=e.utilization+'%';
  document.getElementById('se_online').textContent=e.nodes_online+'/'+e.nodes;
  document.getElementById('se_active').textContent=e.active_rentals;
  document.getElementById('se_rows').innerHTML=(e.specs||[]).map(function(s){
    var pr=s.auto_price?('<span class="badge cc">auto $'+Number(s.min_price||0).toFixed(2)+'–'+Number(s.max_price||0).toFixed(2)+'</span>'):'fixed';
    return '<tr><td style="font-family:var(--disp);font-weight:600">'+s.gpu_model+'</td>'+
      '<td class="mono">'+s.busy+'/'+s.units+'</td><td class="mono amber">$'+Number(s.price_per_hour||0).toFixed(2)+'</td>'+
      '<td>'+pr+'</td><td class="mono">'+s.reputation+'</td><td class="mono mut">'+s.jobs_completed+'✓ '+s.jobs_failed+'✗</td></tr>';}).join('');}
async function loadNodes(){var r=await api('/account/specs');var tb=document.getElementById('noderows');
  if(!r.ok||!r.body.specs.length){tb.innerHTML='<tr><td colspan=7 class="mut mono" style="padding:20px;text-align:center">No nodes yet — <a class="teal" href="/install">list one</a>.</td></tr>';return;}
  tb.innerHTML=r.body.specs.map(function(s){var t=[];if(s.attested)t.push('<span class="badge ok">attested</span>');if(s.confidential)t.push('<span class="badge cc">conf</span>');
   return '<tr><td class="mono mut">'+s.id+'</td><td style="font-family:var(--disp);font-weight:600">'+(s.gpu_model||'CPU')+'</td>'+
   '<td class="mono amber">$'+s.price_per_hour.toFixed(2)+'</td><td>'+(s.status==='online'?'<span class="badge ok">online</span>':'<span class="badge">'+s.status+'</span>')+'</td>'+
   '<td>'+(t.join(' ')||'—')+'</td><td class="mut mono" style="font-size:12px">'+(s.region||'—')+'</td><td class="mono">'+s.jobs_completed+'/'+s.jobs_failed+'</td></tr>';}).join('');}
async function loadJobs(){var r=await api('/account/bookings');var tb=document.getElementById('jobrows');
  if(!r.ok||!r.body.bookings.length){tb.innerHTML='<tr><td colspan=7 class="mut mono" style="padding:20px;text-align:center">No jobs yet — <a class="teal" href="/marketplace">rent a GPU</a>.</td></tr>';return;}
  tb.innerHTML=r.body.bookings.map(function(b){return '<tr><td class="mono mut">'+b.id+'</td><td>'+(b.role==='buyer'?'<span class="badge">bought</span>':'<span class="badge ok">sold</span>')+'</td>'+
   '<td style="font-family:var(--disp);font-weight:600">'+b.gpu_model+'</td><td class="mono">'+b.hours+'h</td><td class="mono amber">'+money(b.gross_amount)+'</td>'+
   '<td><span class="badge">'+b.status+'</span></td><td class="mut mono" style="font-size:12px">'+(b.created_at?b.created_at.slice(0,10):'—')+'</td></tr>';}).join('');}
async function loadKeys(){var r=await api('/account/keys');var tb=document.getElementById('keyrows');
  if(!r.ok||!r.body.keys||!r.body.keys.length){tb.innerHTML='<tr><td colspan=5 class="mut mono" style="padding:18px;text-align:center">No keys yet.</td></tr>';return;}
  tb.innerHTML=r.body.keys.map(function(k){return '<tr><td>'+(k.label||'—')+'</td><td class="mono mut">'+(k.scopes||'—')+'</td>'+
   '<td class="mono mut" style="font-size:11px">'+k.expires_at.slice(0,10)+'</td>'+
   '<td>'+(k.revoked?'<span class="badge">revoked</span>':'<span class="badge ok">active</span>')+'</td>'+
   '<td>'+(k.revoked?'':'<button class="btn-ghost" onclick="rvkey(\\''+k.jti+'\\')">revoke</button>')+'</td></tr>';}).join('');}
async function mkkey(){var lb=document.getElementById('klabel').value;var q=new URLSearchParams({days:'90'});if(lb)q.set('label',lb);
  var r=await api('/create_api_key?'+q.toString(),{method:'POST'});var el=document.getElementById('knew');el.style.display='';
  el.textContent=r.ok?('Copy now — shown once:\\n\\n'+r.body.api_key):'Could not create key.';loadKeys();}
async function rvkey(j){await api('/keys/'+j+'/revoke',{method:'POST'});loadKeys();}
async function deposit(){var a=parseFloat(document.getElementById('amt').value||'0');
  var r=await api('/deposit',{method:'POST',body:JSON.stringify({amount:a})});
  if(r.ok){document.getElementById('bal').textContent=money(r.body.balance);document.getElementById('wbal').textContent=money(r.body.balance);wmsg('Added '+money(a)+' (sandbox credit).');}
  else if(r.status===403){wmsg('Live mode: deposits go through checkout, not here.');}else{wmsg('Could not add funds.');}}
async function withdraw(){var a=parseFloat(document.getElementById('amt').value||'0');
  var r=await api('/wallet/withdraw',{method:'POST',body:JSON.stringify({amount:a})});
  wmsg(r.ok?('Withdrawal of '+money(a)+' requested.'):(r.body&&r.body.detail?r.body.detail:'Add a payout method first.'));loadMethods();}
async function loadMethods(){var r=await api('/wallet/methods');var el=document.getElementById('methods');
  if(r.ok&&r.body.methods&&r.body.methods.length){el.innerHTML='Payout methods: '+r.body.methods.map(function(m){return '<span class="badge ok">'+(m.kind||m.type||'method')+'</span>';}).join(' ');}
  else{el.innerHTML='No payout method yet — add bank / USDC / gift card in the <a class="teal" href="/app">dashboard</a> to withdraw.';}}
async function loadTemplates(){renderLaunch('launchgrid',['ai','render','art','game'],2);}
boot();
</script>""")


GAMERS_HTML = _page("Petabyte — game servers", """
<div class="wrap" style="padding:48px 22px 8px">
  <div class="eyebrow"><span class="dot"></span> game servers</div>
  <h1 style="font-size:clamp(30px,5vw,42px);margin:16px 0 8px">Spin up a <span class="grad-teal">game server</span>.<br/>Or rent out your <span class="grad">rig</span>.</h1>
  <p class="mut" style="max-width:60ch">Low-latency, dedicated game servers on community hardware — priced below the big hosts. Launch a server in a container, or turn your idle gaming PC into income when you're not playing.</p>
</div>

<!-- rent a game by command -->
<div class="wrap" style="padding:22px 22px 6px">
  <div class="lbl" style="margin-bottom:10px">Rent a game server</div>
  <div class="card">
    <p class="mut" style="margin-bottom:14px">One click reserves the cheapest suitable node and launches the server — you never pick a host. You'll get the address to connect on.</p>
    <div id="launchgrid"></div>
    <div id="launchresult" style="display:none"></div>
    <p class="mini" style="margin-top:12px">Other titles (CS2, Rust, ARK, Palworld…) run via a custom Docker image — <a class="teal" href="/developers">see the API</a>.</p>
  </div>
</div>

<!-- two paths -->
<div class="wrap" style="padding:26px 22px 4px">
  <div class="cols c2">
    <div class="card">
      <div class="lbl">Rent a server</div>
      <p class="mut">Pick a game and a nearby node, and we launch a dedicated container with the ports you need. Escrowed by the hour — stop anytime.</p>
      <ul class="mut" style="margin:12px 0 0 18px;font-size:13px;line-height:1.9">
        <li>Dedicated CPU/RAM, low-latency regions</li>
        <li>One-click popular games, or bring your own image</li>
        <li>Pay by the hour, refunded if the node drops</li>
      </ul>
      <div style="margin-top:16px"><a class="btn btn-amber" href="/marketplace">Browse nodes →</a></div>
    </div>
    <div class="card">
      <div class="lbl am">Host on your PC</div>
      <p class="mut">Turn your gaming PC into a paid game-server host when you're not using it. Same one-command install as a compute node — jobs run sandboxed in Docker.</p>
      <ul class="mut" style="margin:12px 0 0 18px;font-size:13px;line-height:1.9">
        <li>Runs in Docker — your machine stays yours</li>
        <li>Set your price, pause anytime</li>
        <li>Weekly payouts · bank, USDC, or gift card</li>
      </ul>
      <div style="margin-top:16px"><a class="btn btn-teal" href="/install">List your PC →</a></div>
    </div>
  </div>
</div>

<!-- live hosts -->
<div class="wrap" style="padding:26px 22px 4px">
  <div class="lbl" style="margin-bottom:12px">Nodes that can host</div>
  <div class="panel" style="overflow:auto"><table class="tbl">
    <thead><tr><th>Host</th><th>vCPU / RAM proxy</th><th>$/hr</th><th>Region</th><th>Rep</th><th>Free</th></tr></thead>
    <tbody id="hostrows"><tr><td colspan=6 class="mut mono" style="padding:22px;text-align:center">loading…</td></tr></tbody>
  </table></div>
</div>

<div class="wrap" style="padding:22px 22px 34px">
  <p class="mini">Popular game images powered by open-source stacks (LinuxGSM · CM2Network · Pterodactyl-compatible). Anti-cheat and licensed titles remain the operator's responsibility.</p>
</div>

<script>
renderLaunch('launchgrid',['game'],2);
async function hosts(){var r=await fetch('/marketplace/specs?sort=price');var b=await r.json();var tb=document.getElementById('hostrows');
  if(!b.count){tb.innerHTML=pbEmpty(6,'No hosts online yet','Turn your gaming PC into a paid host in one command.','/install','List your PC');return;}
  tb.innerHTML=b.specs.map(function(s){
   var rc=s.reputation_score>=80?'var(--pos)':s.reputation_score>=60?'var(--warn)':'var(--bad)';
   var save=(s.cloud_reference&&s.price_per_hour<s.cloud_reference)?Math.round((1-s.price_per_hour/s.cloud_reference)*100):0;
   return '<tr style="cursor:pointer" onclick="location.href=\'/gpu/'+s.id+'\'">'+
    '<td><div style="font-family:var(--disp);font-weight:600">'+(s.gpu_count>1?s.gpu_count+'× ':'')+(s.gpu_model||'CPU')+'</div>'+
      '<div class="mini" style="margin-top:2px">'+(s.cpu?s.cpu+' vCPU':'')+(s.ram_gb?' · '+s.ram_gb+'GB RAM':'')+'</div></td>'+
    '<td class="mono mut">'+(s.vram_gb?s.vram_gb+' GB':'—')+'</td>'+
    '<td><div class="mono amber" style="font-weight:600">$'+s.price_per_hour.toFixed(2)+'</div>'+
      (s.auto_price?'<span class="badge cc" style="font-size:9px">auto</span>':'')+'</td>'+
    '<td class="mono" style="color:var(--pos)">'+(save>0?'−'+save+'%':'—')+'</td>'+
    '<td>'+(s.attested?'<span class="badge ok">verified</span>':'<span class="badge">unverified</span>')+
      (s.confidential?' <span class="badge cc">CC</span>':'')+'</td>'+
    '<td class="mut mono" style="font-size:12px">'+(s.region||'—')+(s.region_verified?' <span class="teal">✓</span>':'')+'</td>'+
    '<td class="mono" style="color:'+rc+'">'+(s.reputation_score!=null?s.reputation_score:'—')+
      '<div class="mini">'+(s.success_rate!=null?s.success_rate+'% ok':'no history')+'</div></td>'+
    '<td><span class="badge '+(s.available_units>0?'ok':'')+'">'+(s.available_units>0?s.available_units+' free':'busy')+'</span></td>'+
    '</tr>';}).join('');}
hosts();setInterval(hosts,8000);
</script>""")


ARTISTS_HTML = _page("Petabyte — for artists", """
<div class="wrap" style="padding:48px 22px 8px">
  <div class="eyebrow"><span class="dot"></span> render on demand</div>
  <h1 style="font-size:clamp(30px,5vw,42px);margin:16px 0 8px">Render <span class="grad-teal">3D &amp; video</span>.<br/>Or rent out your <span class="grad">workstation</span>.</h1>
  <p class="mut" style="max-width:60ch">GPU render farms and video transcode on community hardware — below the big farms' prices. Fire off a Blender frame job, a ComfyUI batch, or an H.264/AV1 transcode, or turn your idle workstation into income between projects.</p>
</div>

<!-- render a project -->
<div class="wrap" style="padding:22px 22px 6px">
  <div class="lbl" style="margin-bottom:10px">Render a project</div>
  <div class="card">
    <p class="mut" style="margin-bottom:14px">Pick a stack — one click reserves the cheapest matching GPU and starts it, then hands you the address to connect and render.</p>
    <div id="launchgrid"></div>
    <div id="launchresult" style="display:none"></div>
    <p class="mini" style="margin-top:12px">For big batch jobs, fan out frames with <span class="mono">/render</span> (Blender) or segments with <span class="mono">/transcode</span> (FFmpeg) instead of a single container — <a class="teal" href="/developers">see the API</a>.</p>
  </div>
</div>

<!-- two paths -->
<div class="wrap" style="padding:26px 22px 4px">
  <div class="cols c2">
    <div class="card">
      <div class="lbl">Rent a render node</div>
      <p class="mut">Pick a GPU and launch Blender, ComfyUI, Stable Diffusion, or an FFmpeg transcode. Escrowed by the hour — stop anytime, refunded if the node drops.</p>
      <ul class="mut" style="margin:12px 0 0 18px;font-size:13px;line-height:1.9">
        <li>3D (Blender/Cycles/OptiX), 2D/AI (ComfyUI, SD)</li>
        <li>NVENC/NVDEC video transcode</li>
        <li>Frame &amp; segment fan-out for big jobs</li>
      </ul>
      <div style="margin-top:16px"><a class="btn btn-amber" href="/marketplace">Browse GPUs →</a></div>
    </div>
    <div class="card">
      <div class="lbl am">Host your workstation</div>
      <p class="mut">Rent out your creative rig when you're not rendering. Same one-command install — jobs run sandboxed in Docker, your files stay yours.</p>
      <ul class="mut" style="margin:12px 0 0 18px;font-size:13px;line-height:1.9">
        <li>Runs in Docker — isolated from your work</li>
        <li>Set your price, pause anytime</li>
        <li>Weekly payouts · bank, USDC, or gift card</li>
      </ul>
      <div style="margin-top:16px"><a class="btn btn-teal" href="/install">List your rig →</a></div>
    </div>
  </div>
</div>

<!-- live hosts -->
<div class="wrap" style="padding:26px 22px 4px">
  <div class="lbl" style="margin-bottom:12px">GPUs available to render</div>
  <div class="panel" style="overflow:auto"><table class="tbl">
    <thead><tr><th>GPU</th><th>VRAM</th><th>$/hr</th><th>Region</th><th>Rep</th><th>Free</th></tr></thead>
    <tbody id="rhostrows"><tr><td colspan=6 class="mut mono" style="padding:22px;text-align:center">loading…</td></tr></tbody>
  </table></div>
</div>

<div class="wrap" style="padding:22px 22px 34px">
  <p class="mini">Stacks powered by open-source images (Blender · ComfyUI · AUTOMATIC1111 · FFmpeg NVENC). You own your outputs; licensing of assets and plugins is the artist's responsibility.</p>
</div>

<script>
renderLaunch('launchgrid',['render','art'],2);
async function rhosts(){var r=await fetch('/marketplace/specs?sort=price');var b=await r.json();var tb=document.getElementById('rhostrows');
  if(!b.count){tb.innerHTML=pbEmpty(6,'No GPUs online yet','Rent out your workstation between projects.','/install','List your rig');return;}
  tb.innerHTML=b.specs.map(function(s){var rc=s.reputation_score>=80?'var(--pos)':s.reputation_score>=60?'var(--warn)':'var(--bad)';
   return '<tr><td style="font-family:var(--disp);font-weight:600">'+(s.gpu_model||'CPU')+'</td>'+
    '<td class="mono mut" style="font-size:12px">'+(s.vram_gb?s.vram_gb+'GB':'—')+'</td>'+
    '<td class="mono amber">$'+s.price_per_hour.toFixed(2)+'</td><td class="mut mono" style="font-size:12px">'+(s.region||'—')+'</td>'+
    '<td class="mono" style="color:'+rc+'">'+(s.reputation_score!=null?s.reputation_score:'—')+'</td>'+
    '<td class="mono" style="color:var(--teal)">'+s.available_units+'</td></tr>';}).join('');}
rhosts();setInterval(rhosts,8000);
</script>""")


GPU_DETAIL_HTML = _page("Petabyte — GPU", """
<div class="wrap" style="padding:34px 24px 10px">
  <a class="mini" href="/marketplace" style="color:var(--mut)">← Back to marketplace</a>
  <div id="gpuwrap" style="margin-top:14px">
    <div class="mut mono" style="padding:40px 0">Loading GPU…</div>
  </div>
</div>
<script>
var SPEC_ID=location.pathname.split('/').pop();
function row(k,v){return '<div style="display:flex;justify-content:space-between;gap:16px;padding:9px 0;border-bottom:1px solid var(--hair)"><span class="mut" style="font-size:13px">'+k+'</span><span class="mono" style="font-size:13px;text-align:right">'+v+'</span></div>';}
async function loadGpu(){
 var r=await fetch('/marketplace/specs/'+SPEC_ID);
 var w=document.getElementById('gpuwrap');
 if(!r.ok){w.innerHTML='<div class="empty"><div class="et">GPU not found</div><div class="es">It may have gone offline or been delisted.</div><a class="btn btn-teal" href="/marketplace">Browse available GPUs</a></div>';return;}
 var s=await r.json();
 var bookable=s.online&&s.available_units>0&&s.can_accept_paid_jobs;
 var status=bookable?'<span class="badge ok">Available now</span>':(s.online?'<span class="badge">Fully booked</span>':'<span class="badge">Offline</span>');
 w.innerHTML=
  '<div class="cols" style="gap:18px;align-items:flex-start">'+
   '<div style="flex:1.6 1 380px;min-width:300px">'+
    '<h1 style="font-size:clamp(28px,4vw,40px);margin-bottom:8px">'+(s.gpu_count>1?s.gpu_count+'× ':'')+s.gpu_model+'</h1>'+
    '<div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:20px">'+status+
      (s.verification.hardware_attested?'<span class="badge ok">Hardware verified</span>':'')+
      (s.confidential?'<span class="badge cc">Confidential computing</span>':'')+
      (s.region_verified?'<span class="badge ok">Region verified</span>':'')+'</div>'+
    '<div class="card" style="margin-bottom:16px">'+
     '<div class="lbl">Specifications</div>'+
     row('GPU',(s.gpu_count>1?s.gpu_count+'× ':'')+s.gpu_model)+
     row('VRAM',s.vram_gb?s.vram_gb+' GB':'—')+
     row('vCPU',s.cpu||'—')+
     row('System RAM',s.ram_gb?s.ram_gb+' GB':'—')+
     row('Region',(s.region||'unknown')+(s.region_verified?' (verified)':' (host-reported)'))+
     row('Capacity',s.available_units+' of '+s.total_units+' free')+
    '</div>'+
    '<div class="card" style="margin-bottom:16px">'+
     '<div class="lbl">Reliability</div>'+
     row('Reputation',(s.reputation_score!=null?s.reputation_score+' / 100':'no history yet'))+
     row('Jobs completed',s.jobs_completed)+
     row('Jobs failed',s.jobs_failed)+
     row('Success rate',s.success_rate!=null?s.success_rate+'%':'no history yet')+
     '<p class="mut" style="font-size:12.5px;margin-top:10px">New hosts start with no history. Reputation is earned from completed rentals on Petabyte.</p>'+
    '</div>'+
    '<div class="card">'+
     '<div class="lbl">What is actually verified</div>'+
     '<p class="mut" style="font-size:13px;margin-bottom:8px">'+s.verification.method+'. The agent reports CPU, RAM, and GPU model, and signs the report with a key held on the machine — so the listing cannot be silently altered in transit.</p>'+
     '<p class="mut" style="font-size:13px">'+(s.confidential?'This host reports support for confidential computing.':'This host does not advertise confidential computing.')+' Region is '+(s.region_verified?'checked against the host network address.':'self-reported by the host and not independently checked.')+'</p>'+
    '</div>'+
   '</div>'+
   '<div style="flex:1 1 280px;min-width:260px;position:sticky;top:88px">'+
    '<div class="card">'+
     '<div style="display:flex;align-items:baseline;gap:8px">'+
      '<span class="mono amber" style="font-size:34px;font-weight:700">$'+Number(s.price_per_hour).toFixed(2)+'</span><span class="mut">/hour</span></div>'+
     (s.savings_pct?'<div class="mini" style="color:var(--pos);margin-top:4px">'+s.savings_pct+'% below the on-demand cloud rate for this GPU class ($'+Number(s.cloud_reference).toFixed(2)+'/hr)</div>':'<div class="mini" style="margin-top:4px">No comparable public cloud rate for this GPU — we don\'t quote a saving we can\'t back up.</div>')+
     (s.auto_price?'<div class="mini" style="margin-top:6px"><span class="badge cc">auto-priced</span> moves with demand, within the host\\'s limits</div>':'')+
     '<div style="margin-top:16px">'+
      (bookable?'<a class="btn btn-amber" style="width:100%;justify-content:center" href="/account">Launch on this GPU →</a>':'<button class="btn btn-ghost" style="width:100%;justify-content:center" disabled>Not bookable right now</button>')+
     '</div>'+
     '<div class="divider" style="margin:16px 0"></div>'+
     '<div class="lbl" style="margin-bottom:8px">If something goes wrong</div>'+
     '<p class="mut" style="font-size:12.5px;margin-bottom:7px">'+s.protection.escrow+'</p>'+
     '<p class="mut" style="font-size:12.5px;margin-bottom:7px">'+s.protection.node_failure+'</p>'+
     '<p class="mut" style="font-size:12.5px">'+s.protection.billing+'</p>'+
    '</div>'+
   '</div>'+
  '</div>';
}
loadGpu();setInterval(loadGpu,15000);
</script>""")


PRICING_HTML = _page("Petabyte — pricing", """
<div class="hero"><div class="wrap" style="padding:60px 24px 18px">
  <div class="eyebrow"><span class="dot"></span> pricing</div>
  <h1 style="font-size:clamp(34px,5vw,54px);margin:16px 0 12px">Pay for the hours <span class="grad">you actually use.</span></h1>
  <p class="mut" style="font-size:16px;max-width:58ch">Hosts set their own prices, so rates vary by GPU and availability. You are billed for the time you hold the machine — stop early and the unused prepay is refunded.</p>
</div></div>

<div class="wrap" style="padding:26px 24px 8px">
  <div class="lbl">Live prices</div>
  <div class="panel" style="overflow:auto">
    <table class="tbl">
      <thead><tr><th>GPU</th><th>VRAM</th><th>Petabyte</th><th>Cloud reference</th><th>You save</th><th>Region</th><th></th></tr></thead>
      <tbody id="prows"><tr><td colspan=7 class="mut mono" style="padding:22px;text-align:center">Loading live prices…</td></tr></tbody>
    </table>
  </div>
  <p class="mut" style="font-size:12.5px;margin-top:10px">Prices are set by individual hosts and change with demand and availability. "Cloud reference" is an on-demand hyperscaler rate for a comparable GPU class, used as a benchmark — not a quote from any specific provider.</p>
</div>

<div class="wrap" style="padding:34px 24px 8px"><div class="cols c3">
  <div class="card"><div class="lbl">How billing works</div>
    <h2 style="font-size:17px;margin-bottom:8px">Hourly, with refunds</h2>
    <p class="mut" style="font-size:13px">You prepay for a window. When you stop, we bill the hours you held (minimum one) and refund the rest to your wallet. Extend at any time.</p></div>
  <div class="card"><div class="lbl">Platform fee</div>
    <h2 style="font-size:17px;margin-bottom:8px">10% on completed rentals</h2>
    <p class="mut" style="font-size:13px">Taken from the rental, not added on top. Hosts see their exact payout before they list.</p></div>
  <div class="card"><div class="lbl am">Host payouts</div>
    <h2 style="font-size:17px;margin-bottom:8px">Withdraw when you want</h2>
    <p class="mut" style="font-size:13px">Earnings accrue per completed rental and can be withdrawn on demand or on a weekly schedule.</p></div>
</div></div>
<script>
async function prices(){
 var r=await fetch('/marketplace/specs?sort=price');var b=await r.json();var tb=document.getElementById('prows');
 if(!b.count){tb.innerHTML=pbEmpty(7,'No GPUs listed yet','Prices appear here as hosts come online.','/install','List your GPU');return;}
 tb.innerHTML=b.specs.map(function(s){
  var save=(s.cloud_reference&&s.price_per_hour<s.cloud_reference)?Math.round((1-s.price_per_hour/s.cloud_reference)*100):0;
  return '<tr>'+
   '<td style="font-family:var(--disp);font-weight:600">'+(s.gpu_model||'CPU')+'</td>'+
   '<td class="mono mut">'+(s.vram_gb?s.vram_gb+' GB':'—')+'</td>'+
   '<td class="mono amber" style="font-weight:600">$'+Number(s.price_per_hour).toFixed(2)+'/hr</td>'+
   '<td class="mono mut">'+(s.cloud_reference?'$'+Number(s.cloud_reference).toFixed(2)+'/hr':'<span class="mini">no comparable rate</span>')+'</td>'+
   '<td class="mono" style="color:var(--pos)">'+(save>0?save+'%':'—')+'</td>'+
   '<td class="mut mono" style="font-size:12px">'+(s.region||'—')+'</td>'+
   '<td><a class="btn btn-teal" style="padding:6px 14px;font-size:12px" href="/gpu/'+s.spec_id+'">View</a></td></tr>';}).join('');
}
prices();setInterval(prices,10000);
</script>""")


SECURITY_HTML = _page("Petabyte — security &amp; trust", """
<div class="hero"><div class="wrap" style="padding:60px 24px 18px">
  <div class="eyebrow"><span class="dot"></span> security &amp; trust</div>
  <h1 style="font-size:clamp(34px,5vw,54px);margin:16px 0 12px">What we verify, <span class="grad">and what we don't.</span></h1>
  <p class="mut" style="font-size:16px;max-width:62ch">Renting compute from strangers only works if both sides know exactly what is guaranteed. Here is the honest version — including the parts we are still building.</p>
</div></div>

<div class="wrap" style="padding:26px 24px 8px"><div class="cols c2">
  <div class="card"><div class="lbl">Hardware verification</div>
    <h2 style="font-size:18px;margin-bottom:8px">Signed hardware reports</h2>
    <p class="mut" style="font-size:13.5px">When a host installs the agent, it generates a keypair on the machine and signs a report of its CPU, RAM, and GPU model. We verify that signature before the GPU can be listed, so a listing cannot be forged or altered in transit.</p>
    <p class="mut" style="font-size:13.5px;margin-top:10px"><b class="teal">What this is not:</b> it is not a hardware root of trust. A determined host could still report hardware it does not have. Reputation from completed jobs is the stronger signal, and it is shown on every listing.</p>
  </div>
  <div class="card"><div class="lbl">Workload isolation</div>
    <h2 style="font-size:18px;margin-bottom:8px">Jobs run in containers</h2>
    <p class="mut" style="font-size:13.5px">Your workload runs in a Docker container on the host, with privileges dropped, a process limit, and a memory cap. Where the host has gVisor installed, we run the container under a user-space kernel for a stronger boundary between your job and their machine.</p>
    <p class="mut" style="font-size:13.5px;margin-top:10px"><b class="teal">What this is not:</b> containers are not a hardware boundary. Do not put data on a node that you could not tolerate the host seeing. For sensitive work, use a host that advertises confidential computing, or don't use shared infrastructure.</p>
  </div>
  <div class="card"><div class="lbl">Payment protection</div>
    <h2 style="font-size:18px;margin-bottom:8px">Escrow, held by Petabyte</h2>
    <p class="mut" style="font-size:13.5px">When you book, the money leaves your wallet and is held by Petabyte for the rental. The host is paid on completion; the platform takes 10% of the rental. This is an internal ledger, not an on-chain escrow — Petabyte is the custodian.</p>
    <p class="mut" style="font-size:13.5px;margin-top:10px">Stop early and you are billed only for the hours you held the machine (minimum one). The unused prepay returns to your wallet.</p>
  </div>
  <div class="card"><div class="lbl">When a node disappears</div>
    <h2 style="font-size:18px;margin-bottom:8px">Failover, or refund</h2>
    <p class="mut" style="font-size:13.5px">Hosts send a heartbeat. If one goes quiet, we move your machine to another eligible node — the address you connect to does not change — and restore from the most recent snapshot. If no node can take it, the rental is refunded.</p>
    <p class="mut" style="font-size:13.5px;margin-top:10px"><b class="teal">Be aware:</b> recovery is from the last checkpoint, not a live mirror. A failover means restarting from a snapshot, not zero data loss.</p>
  </div>
</div></div>

<div class="wrap" style="padding:22px 24px 8px">
  <div class="card">
    <div class="lbl am">Still building</div>
    <h2 style="font-size:18px;margin-bottom:10px">Claims we are not making yet</h2>
    <p class="mut" style="font-size:13.5px">We would rather be trusted than impressive. These are on the roadmap and are <b>not</b> live today:</p>
    <ul class="mut" style="font-size:13.5px;margin:10px 0 0 20px">
      <li style="padding:3px 0">Hardware-backed attestation (SEV-SNP / TDX). Today's attestation is software-signed by the agent.</li>
      <li style="padding:3px 0">Independent benchmark verification of advertised performance.</li>
      <li style="padding:3px 0">A published external security audit or SOC 2 report.</li>
      <li style="padding:3px 0">Formal data-residency guarantees. Region is host-reported unless marked verified.</li>
    </ul>
    <p class="mut" style="font-size:13px;margin-top:12px">If a claim matters for your workload, ask us before you book — <a class="teal" href="mailto:security@petabyte.market">security@petabyte.market</a>.</p>
  </div>
</div>

<div class="wrap" style="padding:22px 24px 8px"><div class="cols c3">
  <a class="card" href="/privacy" style="display:block"><div class="lbl">Legal</div><h2 style="font-size:16px">Privacy policy</h2><p class="mut" style="font-size:13px">What we collect and why.</p></a>
  <a class="card" href="/terms" style="display:block"><div class="lbl">Legal</div><h2 style="font-size:16px">Terms of service</h2><p class="mut" style="font-size:13px">The agreement for buyers and hosts.</p></a>
  <a class="card" href="/acceptable-use" style="display:block"><div class="lbl">Legal</div><h2 style="font-size:16px">Acceptable use</h2><p class="mut" style="font-size:13px">What you may not run, and what hosts may not do.</p></a>
</div></div>""")


def _legal(title, body):
    return _page("Petabyte — " + title, """
<div class="wrap" style="padding:56px 24px 8px;max-width:760px">
  <div class="eyebrow"><span class="dot"></span> legal</div>
  <h1 style="font-size:clamp(30px,4.4vw,44px);margin:16px 0 8px">""" + title + """</h1>
  <p class="mini" style="margin-bottom:26px">Last updated 11 July 2026 · Petabyte, Riyadh, Saudi Arabia</p>
  <div class="card" style="line-height:1.75">""" + body + """
  <p class="mut" style="font-size:12.5px;margin-top:20px;padding-top:14px;border-top:1px solid var(--hair)">
    Questions: <a class="teal" href="mailto:legal@petabyte.market">legal@petabyte.market</a>.
    This document is provided in good faith and is not a substitute for legal advice.</p>
  </div>
</div>""")


_LEGAL_H = 'style="font-family:var(--disp);font-weight:600;font-size:16px;margin:20px 0 6px"'

PRIVACY_HTML = _legal("Privacy policy", """
<p class="mut">We collect the minimum needed to run a compute marketplace, and we tell you plainly what that is.</p>
<h2 """ + _LEGAL_H + """>What we collect</h2>
<p class="mut"><b>Account data:</b> your username, a hashed password (we never store the plaintext), and email if you provide one.
<b>Host data:</b> hardware reported by the agent (CPU, RAM, GPU model), heartbeat times, and the network address the agent connects from — used to place jobs and to check region claims.
<b>Usage data:</b> bookings, rentals, job status, and wallet transactions. <b>Payment data:</b> handled by our payment processor; we do not store card numbers.</p>
<h2 """ + _LEGAL_H + """>What we do not collect</h2>
<p class="mut">We do not read the contents of your workloads. We do not sell your data or share it with advertisers. We do not track you across other websites.</p>
<h2 """ + _LEGAL_H + """>What hosts can see</h2>
<p class="mut">A host runs your container on their machine. They can see that a job is running and its resource usage. Containers limit but do not eliminate what a determined host could observe — see our <a class="teal" href="/security">security page</a> for the honest boundary. Do not place data on shared infrastructure that you could not tolerate the host seeing.</p>
<h2 """ + _LEGAL_H + """>Retention and your rights</h2>
<p class="mut">Financial records are kept as required for accounting. Other data is kept while your account is open. You can request a copy of your data or ask us to delete your account by emailing <a class="teal" href="mailto:privacy@petabyte.market">privacy@petabyte.market</a>.</p>
""")

TERMS_HTML = _legal("Terms of service", """
<p class="mut">Petabyte is a marketplace. Buyers rent compute; hosts supply it. We operate the platform, hold funds in escrow during a rental, and settle them on completion.</p>
<h2 """ + _LEGAL_H + """>What we are</h2>
<p class="mut">We are an intermediary, not the owner of the hardware. Hosts are independent parties who set their own prices and availability. We verify what we can (see <a class="teal" href="/security">Security</a>) and show reputation earned from completed jobs, but we do not warrant any host's performance.</p>
<h2 """ + _LEGAL_H + """>Money</h2>
<p class="mut">Funds you deposit are held by Petabyte. When you book, the amount is moved into escrow for that rental. On completion we pay the host their share and take a 10% platform fee from the rental. If you stop early, you are billed for the hours you held the machine (minimum one hour) and the remainder is returned to your wallet. If a rental cannot be delivered, you are refunded.</p>
<h2 """ + _LEGAL_H + """>Availability</h2>
<p class="mut">We do not guarantee uptime. Hosts are consumer and datacenter machines that can go offline. When a host fails mid-rental we attempt to move your machine to another node at the same address, restoring from the most recent snapshot; recovery is from a checkpoint, not a live mirror. If we cannot, you are refunded.</p>
<h2 """ + _LEGAL_H + """>Your responsibilities</h2>
<p class="mut">You are responsible for what you run and for complying with the <a class="teal" href="/acceptable-use">Acceptable use policy</a> and applicable law, including any licences for software or game servers you deploy. Hosts are responsible for the machines they list and must not tamper with buyers' workloads.</p>
<h2 """ + _LEGAL_H + """>Liability</h2>
<p class="mut">To the extent permitted by law, our liability for any rental is limited to the amount you paid for it. We are not liable for lost work, lost profits, or data loss — keep your own backups.</p>
<h2 """ + _LEGAL_H + """>Termination</h2>
<p class="mut">We may suspend accounts that breach these terms or the acceptable use policy. You can close your account at any time; hosts can uninstall the agent in one command.</p>
""")

AUP_HTML = _legal("Acceptable use policy", """
<p class="mut">Someone else's computer is running your code. These rules exist so both sides are safe.</p>
<h2 """ + _LEGAL_H + """>You may not use Petabyte to</h2>
<ul class="mut" style="margin:8px 0 0 20px">
  <li style="padding:3px 0">Attack, scan, or disrupt other systems, or run botnets, DDoS tooling, or credential-stuffing.</li>
  <li style="padding:3px 0">Break into, tamper with, or escape the container onto a host's machine.</li>
  <li style="padding:3px 0">Process or generate child sexual abuse material, or content that incites violence.</li>
  <li style="padding:3px 0">Run workloads that are illegal where you are, where the host is, or where we operate.</li>
  <li style="padding:3px 0">Infringe copyright — including running pirated software or unlicensed game servers.</li>
  <li style="padding:3px 0">Mine cryptocurrency on a rented GPU without the host's consent (hosts may opt in to idle mining on their own hardware).</li>
  <li style="padding:3px 0">Evade sanctions, launder money, or conceal the origin of funds.</li>
</ul>
<h2 """ + _LEGAL_H + """>Hosts may not</h2>
<ul class="mut" style="margin:8px 0 0 20px">
  <li style="padding:3px 0">Interfere with, inspect, copy, or exfiltrate a buyer's workload or data.</li>
  <li style="padding:3px 0">Misrepresent their hardware, region, or capabilities.</li>
  <li style="padding:3px 0">Take payment and deliberately fail to deliver compute.</li>
</ul>
<h2 """ + _LEGAL_H + """>Enforcement</h2>
<p class="mut">We may suspend a rental or an account, withhold settlement, and where required report to authorities. Report abuse to <a class="teal" href="mailto:abuse@petabyte.market">abuse@petabyte.market</a> — include the VM address or node id if you have it.</p>
""")


STATUS_HTML = _page("Petabyte — status", """
<div class="wrap" style="padding:56px 24px 8px;max-width:820px">
  <div class="eyebrow"><span class="dot"></span> service status</div>
  <h1 style="font-size:clamp(30px,4.4vw,44px);margin:16px 0 20px">System status</h1>
  <div class="card">
    <div id="statrows"><div class="mut mono" style="padding:16px 0">Checking…</div></div>
  </div>
  <p class="mut" style="font-size:12.5px;margin-top:12px">Live from our own health checks. Host machines are independent and can go offline individually — that is expected, and rentals fail over or refund.</p>
</div>
<script>
function srow(name,ok,detail){return '<div style="display:flex;align-items:center;gap:12px;padding:12px 0;border-bottom:1px solid var(--hair)">'+
 '<span style="width:9px;height:9px;border-radius:50%;background:'+(ok?'var(--pos)':'var(--bad)')+';box-shadow:0 0 10px '+(ok?'var(--pos)':'var(--bad)')+'"></span>'+
 '<span style="flex:1;font-family:var(--disp);font-weight:600;font-size:14px">'+name+'</span>'+
 '<span class="mono mut" style="font-size:12px">'+detail+'</span></div>';}
async function stat(){
 var api_ok=false,detail='unreachable';
 try{var r=await fetch('/healthz');api_ok=r.ok;detail=r.ok?'operational':'degraded';}catch(e){}
 var nodes='—';
 try{var st=await (await fetch('/marketplace/stats')).json();nodes=st.nodes_online+' hosts online';}catch(e){}
 document.getElementById('statrows').innerHTML=
  srow('API',api_ok,detail)+srow('Marketplace',api_ok,nodes)+srow('Settlement',api_ok,api_ok?'operational':'degraded');
}
stat();setInterval(stat,15000);
</script>""")
