"""Static site pages served by the API (same-origin, no build step).

Brand: Petabyte — deep-navy background with teal/cyan bioluminescent
accents and an amber energy accent, Space Grotesk (display) + Inter (body) +
JetBrains Mono (data). The hexagon node mark (/static/petabyte-logo.png) is the
signature. Token persists in localStorage as 'pb_token' across pages.
"""

_HEAD = """<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>%%TITLE%%</title>
<meta name="description" content="%%DESC%%"/>
<link rel="canonical" href="https://petabyte.market%%PATH%%"/>
<meta property="og:type" content="website"/>
<meta property="og:site_name" content="Petabyte"/>
<meta property="og:title" content="%%TITLE%%"/>
<meta property="og:description" content="%%DESC%%"/>
<meta property="og:url" content="https://petabyte.market%%PATH%%"/>
<meta property="og:image" content="https://petabyte.market/static/og-card.png"/>
<meta name="twitter:card" content="summary_large_image"/>
<meta name="twitter:site" content="@engcool"/>
<meta name="twitter:title" content="%%TITLE%%"/>
<meta name="twitter:description" content="%%DESC%%"/>
<meta name="twitter:image" content="https://petabyte.market/static/og-card.png"/>
<meta name="theme-color" content="#050B16"/>
<script type="application/ld+json">
{"@context":"https://schema.org","@type":"Organization","name":"Petabyte",
 "url":"https://petabyte.market","logo":"https://petabyte.market/static/petabyte-logo.png",
 "description":"A marketplace for renting and monetizing GPU compute.",
 "sameAs":["https://github.com/BDR-Pro","https://x.com/engcool"]}
</script>
<script>(function(){try{var l=localStorage.getItem('pb_lang')||'en';document.documentElement.setAttribute('lang',l);document.documentElement.setAttribute('dir',l==='ar'?'rtl':'ltr');}catch(e){}})();</script>
<script>(function(){try{document.documentElement.setAttribute('data-auth',localStorage.getItem('pb_token')?'in':'out');}catch(e){}})();</script>
<script>(function(){try{var t=localStorage.getItem('pb_theme');if(t!=='light'&&t!=='dark')t=(window.matchMedia&&matchMedia('(prefers-color-scheme: light)').matches)?'light':'dark';document.documentElement.setAttribute('data-theme',t);document.documentElement.setAttribute('data-bs-theme',t);}catch(e){document.documentElement.setAttribute('data-theme','dark');document.documentElement.setAttribute('data-bs-theme','dark');}})();</script>
<link rel="icon" type="image/png" href="/favicon.ico">
<link rel="apple-touch-icon" href="/static/petabyte-mark-180.png">
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Sora:wght@500;600;700;800&family=Figtree:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600&family=IBM+Plex+Sans+Arabic:wght@400;500;600;700&display=swap" rel="stylesheet">
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet" integrity="sha384-QWTKZyjpPEjISv5WaRU9OFeRpok6YctnYmDr5pNlyT2bRjXh0JMhjY6hW+ALEwIH" crossorigin="anonymous">
<script defer src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js" integrity="sha384-YvpcrYf0tY3lHB60NNkmXc5s9fDVZLESaAA55NDzOxhy9GkcIdslK1eN7N6jIeHz" crossorigin="anonymous"></script>
<style>
/* ---- Bootstrap 5.3 themed to match (our layer loads after and wins) ---- */
[data-bs-theme]{--bs-body-bg:transparent;--bs-body-color:var(--ink);--bs-border-color:var(--line);
 --bs-primary:#35E0D0;--bs-primary-rgb:53,224,208;--bs-warning:#FFB224;--bs-warning-rgb:255,178,36;
 --bs-link-color:var(--teal);--bs-link-hover-color:var(--teal-br);
 --bs-font-sans-serif:'Figtree',system-ui,sans-serif;--bs-body-font-size:14.5px;--bs-body-line-height:1.65;
 --bs-border-radius:14px;--bs-border-radius-lg:18px;--bs-secondary-color:var(--mut)}
.navbar{--bs-navbar-padding-y:0;--bs-navbar-padding-x:0}
/* the nav is dense (6 links + AR + theme + sign-in + 2 buttons); give it room and
   collapse to the hamburger earlier so nothing wraps mid-label */
@media(min-width:992px) and (max-width:1180px){.navlinks a{padding:7px 8px;font-size:12.5px}.navcta{gap:6px}}
.navbar-toggler{border:1px solid var(--line2);border-radius:999px;padding:7px 11px;color:var(--mut)}
.navbar-toggler:focus{box-shadow:0 0 0 4px rgba(53,224,208,.15)}
.navbar-toggler svg{width:18px;height:18px;display:block}
@media(max-width:991.98px){
 /* Hide the collapsed menu by default WITHOUT relying on the Bootstrap CDN stylesheet:
    if that asset is slow or blocked, the off-canvas menu must not create horizontal
    overflow. Mirrors Bootstrap's own .collapse:not(.show){display:none}. */
 .navbar-collapse:not(.show){display:none}
 .navbar-collapse{flex-basis:100%;padding:10px 4px 12px}
 .navlinks{flex-direction:column;gap:2px;margin-inline-start:0}
 .navlinks a{padding:9px 13px}
 .navcta{margin-inline-start:0;margin-top:8px;flex-wrap:wrap}}
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
 overflow-x:clip;
 transition:background-color .3s,color .3s}
a{color:inherit;text-decoration:none}
.mono{font-family:var(--mono);font-variant-numeric:tabular-nums}
.wrap{max-width:1120px;margin:0 auto;padding:0 24px}
.teal{color:var(--teal)}.amber{color:var(--amber)}.mut{color:var(--mut)}
/* ---------- value-proposition banners (reusable) ----------
   buyer surfaces lead with savings vs the hyperscalers (green);
   seller surfaces lead with earnings potential (amber). */
.savings-banner,.earn-banner{display:flex;align-items:center;gap:10px 14px;margin-top:14px;
 padding:13px 18px;border-radius:14px;font-family:var(--disp);font-weight:600;font-size:14.5px;flex-wrap:wrap}
.savings-banner{background:linear-gradient(90deg,rgba(74,222,156,.14),rgba(53,224,208,.05));border:1px solid rgba(74,222,156,.35)}
.savings-banner b{color:var(--pos);font-size:19px}
.earn-banner{background:linear-gradient(90deg,rgba(255,178,36,.14),rgba(255,178,36,.04));border:1px solid rgba(255,178,36,.35)}
.earn-banner b{color:var(--amber);font-size:19px}
.savings-banner .sub,.earn-banner .sub{font-family:var(--body);font-weight:400;font-size:12.5px;color:var(--mut)}
/* ---------- earnings calculator (NiceHash-style: pick a GPU, drag utilization,
   watch the numbers move) ---------- */
.calc-controls{display:flex;gap:14px;flex-wrap:wrap;align-items:flex-end;margin:14px 0 6px}
.calc-controls .field label,.calc-util label{display:block;font-size:12px;color:var(--mut);margin-bottom:5px}
.calc-controls input{width:150px;max-width:100%}
.calc-util{margin:12px 0 16px;max-width:460px}
.calc-util input[type=range]{width:100%;accent-color:var(--amber);height:22px;cursor:pointer}
.calc-out{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;max-width:520px}
.calc-tile{background:var(--panel2);border:1px solid var(--line);border-radius:14px;padding:15px 10px;text-align:center}
.calc-n{font-family:var(--disp);font-weight:800;font-size:clamp(19px,4.4vw,27px);letter-spacing:-.02em;color:var(--amber)}
.calc-l{font-size:11px;color:var(--mut);margin-top:3px;text-transform:uppercase;letter-spacing:.05em}
@media(max-width:520px){.calc-out{grid-template-columns:1fr}.calc-controls input{width:100%}}
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
.navlinks{display:flex;gap:2px;margin-inline-start:6px;flex-wrap:nowrap}
.navlinks a{font-size:13px;font-weight:500;color:var(--mut);padding:7px 11px;border-radius:999px;transition:color .15s,background-color .15s;white-space:nowrap}
.navlinks a:hover{color:var(--ink);background:rgba(255,255,255,.05)}
.navlinks a.active{color:var(--teal);background:rgba(53,224,208,.10)}
.navcta{margin-inline-start:auto;display:flex;align-items:center;gap:8px;flex-wrap:nowrap}
.signin{font-size:13px;font-weight:500;color:var(--mut);padding:7px 10px;border-radius:999px;transition:color .15s;white-space:nowrap}
/* auth-state visibility, decided before first paint (no flash of the wrong button) */
html[data-auth=in] #signinlink{display:none!important}
html[data-auth=out] #signoutlink,html[data-auth=out] #mename,html[data-auth=out] #adminlink{display:none!important}
.signin:hover{color:var(--teal)}
/* ---------- buttons ---------- */
button,.btn{font-family:var(--disp);font-weight:600;border:0;border-radius:999px;padding:10px 20px;font-size:13.5px;cursor:pointer;
 transition:transform .12s,filter .15s,border-color .15s,color .15s,box-shadow .15s;display:inline-flex;align-items:center;gap:8px;white-space:nowrap}
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
.tbl th{font-family:var(--mono);font-size:10px;letter-spacing:.14em;text-transform:uppercase;color:var(--dim);text-align:start;padding:13px 16px;border-bottom:1px solid var(--line)}
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
select{appearance:none;-webkit-appearance:none;background-image:linear-gradient(45deg,transparent 50%,var(--mut) 50%),linear-gradient(135deg,var(--mut) 50%,transparent 50%);background-position:calc(100% - 17px) 55%,calc(100% - 12px) 55%;background-size:5px 5px;background-repeat:no-repeat;padding-inline-end:32px}
.field{display:flex;flex-direction:column;gap:5px}
.field>span{font-family:var(--mono);font-size:9.5px;letter-spacing:.15em;text-transform:uppercase;color:var(--dim)}
.filterbar{display:flex;gap:14px;flex-wrap:wrap;align-items:flex-end}
/* ---------- empty state ---------- */
.empty{padding:42px 20px;text-align:center;color:var(--mut)}
.empty svg{width:36px;height:36px;color:var(--dim);margin-bottom:12px}
.empty .et{font-family:var(--disp);font-weight:600;font-size:15px;color:var(--ink);margin-bottom:4px}
.empty .es{font-size:12.5px;margin-bottom:16px}
.stepchip{display:inline-flex;align-items:center;justify-content:center;width:22px;height:22px;border-radius:7px;background:rgba(53,224,208,.12);border:1px solid rgba(53,224,208,.35);color:var(--teal);font-family:var(--mono);font-size:11px;font-weight:600;margin-inline-end:8px;flex:none}
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
/* ---------- Arabic / RTL ----------
   RTL is not "flip everything". Numbers, money, code, curl commands and monospace
   identifiers must stay LTR even inside an Arabic sentence, or a price reads backwards. */
html[dir="rtl"] body{font-family:'IBM Plex Sans Arabic','Figtree',system-ui,sans-serif}
html[dir="rtl"] h1,html[dir="rtl"] h2,html[dir="rtl"] h3{font-family:'IBM Plex Sans Arabic','Sora',sans-serif;letter-spacing:0}
html[dir="rtl"] .eyebrow,html[dir="rtl"] .lbl,html[dir="rtl"] .mini{letter-spacing:0}
/* these carry meaning in one direction only */
html[dir="rtl"] .mono,html[dir="rtl"] code,html[dir="rtl"] .codeline,
html[dir="rtl"] .tbl td.mono,html[dir="rtl"] input[type="number"]{direction:ltr;text-align:start;unicode-bidi:isolate}
html[dir="rtl"] .hexbg{transform:scaleX(-1)}
html[dir="rtl"] .grad{background-position:right}
[dir] .arrow-fwd::after{content:"\2192"}
html[dir="rtl"] .arrow-fwd::after{content:"\2190"}

/* ---------- mobile ----------
   A host checks "is my node earning?" from their phone, in bed. A 7-column table
   scrolled sideways is useless there. Below 720px every .tbl collapses into stacked
   cards, each row labelled by its header via data-l. */
@media(max-width:720px){
  .wrap{padding:0 16px}
  h1{font-size:clamp(28px,8vw,40px)!important}
  .stat{flex:1 1 100%}
  .filterbar{gap:10px}
  .filterbar .field{flex:1 1 calc(50% - 5px)}
  .lfoot{flex-wrap:wrap}
  .lfoot .codeline{order:2;flex:1 1 100%}
  .lbtn{order:1;width:100%;justify-content:center}
  .panel{overflow:visible}
  .tbl thead{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0)}
  .tbl,.tbl tbody,.tbl tr,.tbl td{display:block;width:100%}
  .tbl tr{border:1px solid var(--line);border-radius:var(--r-sm);margin-bottom:10px;
    background:linear-gradient(180deg,var(--depth2),var(--panel2));padding:4px 0}
  .tbl td{display:flex;justify-content:space-between;align-items:center;gap:14px;
    border-bottom:1px solid var(--hair);padding:10px 14px;text-align:end}
  .tbl td:last-child{border-bottom:0}
  .tbl td::before{content:attr(data-l);font-family:var(--mono);font-size:9.5px;
    letter-spacing:.14em;text-transform:uppercase;color:var(--dim);text-align:start;flex:none}
  .tbl td:empty{display:none}
  .tbl td .btn{min-height:44px}
  footer .fcols{gap:24px}
  footer .fcol{min-width:44%}
  /* Phone touch ergonomics: 16px form text stops iOS from zooming on focus; every
     button/control clears the ~44px minimum tap target so it's thumb-friendly. */
  input,select,textarea{font-size:16px;padding:12px 14px}
  input:not([type=checkbox]):not([type=radio]),select,textarea,button,.btn,.signin{min-height:46px}
  .navbar-toggler{min-height:46px;min-width:46px;display:inline-flex;align-items:center;justify-content:center}
  .brand{min-height:44px}
  #forgotlink,#togglelink{display:inline-flex;align-items:center;min-height:44px;padding:0 2px}
  /* Long install/command lines wrap instead of forcing a sideways swipe of a tiny block. */
  pre{white-space:pre-wrap;word-break:break-word;overflow-x:hidden}
}
@media(prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}}
</style></head><body>"""

_NAV = """<nav class="navbar navbar-expand-lg sticky-top"><div class="wrap">
<a class="brand" href="/"><img src="/static/petabyte-logo.png" alt="Petabyte"/><span><b>Petabyte</b><span class="p">.</span></span></a>
<button class="navbar-toggler d-lg-none ms-auto" type="button" data-bs-toggle="collapse" data-bs-target="#pbnav" aria-controls="pbnav" aria-expanded="false" aria-label="Toggle navigation">
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M4 7h16M4 12h16M4 17h16"/></svg>
</button>
<div class="collapse navbar-collapse" id="pbnav">
<div class="navlinks">
  <a href="/marketplace" data-ar="السوق">Marketplace</a><a href="/catalog" data-ar="القوالب">Templates</a><a href="/pricing" data-ar="الأسعار">Pricing</a>
  <a href="/metrics" data-ar="المقاييس">Metrics</a><a href="/install" data-ar="لمالكي كروت الرسومات">For GPU owners</a><a href="/security" data-ar="الأمان">Security</a><a href="/developers" data-ar="المطورون">Developers</a>
</div>
<div class="navcta">
  <a class="signin" id="adminlink" href="/admin" style="display:none">Admin</a>
  <a class="signin" id="mename" href="/account" style="display:none;color:var(--teal)"></a>
  <button class="themetoggle" onclick="toggleLang()" aria-label="Switch language" title="English / العربية" style="font-family:var(--mono);font-size:11px;font-weight:600" id="langbtn">AR</button>
  <button class="themetoggle" onclick="toggleTheme()" aria-label="Toggle light or dark theme" title="Toggle light / dark">
    <svg class="sun" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M2 12h2M20 12h2M5 5l1.4 1.4M17.6 17.6 19 19M19 5l-1.4 1.4M6.4 17.6 5 19"/></svg>
    <svg class="moon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8Z"/></svg>
  </button>
  <a class="signin" id="signinlink" href="/login">Sign in</a>
  <a class="signin" id="signoutlink" href="#" onclick="signout();return false" style="display:none">Sign out</a>
  <a class="btn btn-ghost" href="/demo" data-ar="احجز عرضاً">Book a demo</a>
  <a class="btn btn-amber" href="/app">Open app</a>
</div>
</div>
</div></nav>"""

_FOOT = """<footer>
<div class="fcols">
  <div class="fcol" style="flex:1.4;min-width:200px">
    <span class="fb"><img src="/static/petabyte-logo.png" alt=""/> <b style="font-family:var(--disp);color:var(--ink)">Petabyte</b></span>
    <p class="mut" style="font-size:12px;margin-top:10px;max-width:30ch">A verified marketplace for community GPU power. Operated from Riyadh by Petabyte, Inc.</p>
  </div>
  <div class="fcol"><div class="fh">Product</div>
    <a href="/marketplace" data-ar="السوق">Marketplace</a><a href="/pricing" data-ar="الأسعار">Pricing</a><a href="/app">Console</a>
  </div>
  <div class="fcol"><div class="fh">Use cases</div>
    <a href="/artists">Rendering &amp; art</a><a href="/gamers">Game servers</a><a href="/developers">AI &amp; inference</a>
  </div>
  <div class="fcol"><div class="fh">Sell compute</div>
    <a href="/install">List your PC</a><a href="/account">Earnings</a><a href="/keys">API keys</a>
  </div>
  <div class="fcol"><div class="fh">Developers</div>
    <a href="/docs">API reference</a><a href="/catalog" data-ar="القوالب">Templates</a><a href="/developers">Quickstart</a><a href="/keys">API keys</a>
  </div>
  <div class="fcol"><div class="fh">Company</div>
    <a href="/security">Security &amp; trust</a><a href="/investors">About</a><a href="/status">Status</a>
  </div>
  <div class="fcol"><div class="fh">Legal</div>
    <a href="/privacy">Privacy</a><a href="/terms">Terms</a><a href="/acceptable-use">Acceptable use</a>
  </div>
</div>
<div class="wrap">
<span class="fb">© Petabyte, Inc.</span>
<span class="mut" style="font-size:11.5px" data-ar="شركة بيتابايت — مؤسسة كشركة أمريكية في ولاية ديلاوير، وتُدار من الرياض.">Petabyte, Inc. — a Delaware C-corporation · operated from Riyadh, Saudi Arabia</span>
<span>verified compute · escrowed settlement</span>
</div></footer>"""

# token bootstrap: capture #t=JWT from the OAuth redirect, persist across pages
_AUTHJS = """<script>
(function(){var h=location.hash.match(/t=([^&]+)/);if(h){localStorage.setItem('pb_token',decodeURIComponent(h[1]));document.documentElement.setAttribute('data-auth','in');history.replaceState(null,'',location.pathname);}})();
(function(){try{var m=location.search.match(/[?&]ref=([A-Za-z0-9]{4,16})/);if(m){localStorage.setItem('pb_ref',m[1].toUpperCase());}}catch(e){}})();
function tok(){return localStorage.getItem('pb_token');}
// HTML-escape any user-controlled value before it goes into innerHTML. Server-side
// validation (main.py _clean_label) already rejects HTML metachars at write time; this is
// defence-in-depth at the DOM sink and also neutralises any legacy row stored before that.
function esc(s){return String(s==null?'':s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');}
(function(){try{var p=location.pathname.replace(new RegExp('[/]$'),'')||'/';document.querySelectorAll('.navlinks a').forEach(function(a){if(a.getAttribute('href')===p)a.classList.add('active');});}catch(e){}})();
function authed(){return !!tok();}
async function api(p,o){o=o||{};o.headers=Object.assign({'Content-Type':'application/json'},o.headers||{});
 if(tok())o.headers['Authorization']='Bearer '+tok();var r=await fetch(p,o);var b={};try{b=await r.json()}catch(e){}return {ok:r.ok,status:r.status,body:b};}
function toggleLang(){
  var h=document.documentElement, next=(h.getAttribute('dir')==='rtl')?'en':'ar';
  try{localStorage.setItem('pb_lang',next);}catch(e){}
  location.reload();
}
// Translate in place. Every translatable node carries data-ar; we swap textContent
// and flip direction. No separate Arabic build to drift out of sync.
function applyLang(){
  var ar = document.documentElement.getAttribute('dir')==='rtl';
  var b=document.getElementById('langbtn'); if(b) b.textContent = ar ? 'EN' : 'AR';
  document.querySelectorAll('[data-ar]').forEach(function(el){
    if(!el.hasAttribute('data-en')) el.setAttribute('data-en', el.textContent);
    el.textContent = ar ? el.getAttribute('data-ar') : el.getAttribute('data-en');
  });
  document.querySelectorAll('[data-ar-ph]').forEach(function(el){
    if(!el.hasAttribute('data-en-ph')) el.setAttribute('data-en-ph', el.placeholder||'');
    el.placeholder = ar ? el.getAttribute('data-ar-ph') : el.getAttribute('data-en-ph');
  });
}
document.addEventListener('DOMContentLoaded', applyLang);

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
PBICONS["jupyter"]='<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><circle cx="12" cy="4" r="1.4"/><path d="M4 9c2.6 3 13.4 3 16 0M4 15c2.6 3 13.4 3 16 0"/></svg>';
PBICONS["pytorch"]='<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><path d="M12 3 6 9a8.5 8.5 0 1 0 12 0z"/><circle cx="15" cy="7.5" r="1.1" fill="currentColor"/></svg>';
function pbIcon(n){return PBICONS[n]||PBICONS._default;}
function pbEmpty(cols,title,sub,ctaHref,ctaText){
 return '<tr><td colspan='+cols+'><div class="empty">'+
  '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><rect x="3" y="5" width="18" height="14" rx="2"/><path d="M3 10h18M8 15h4"/></svg>'+
  '<div class="et">'+title+'</div><div class="es">'+sub+'</div>'+
  (ctaHref?('<a class="btn btn-teal" href="'+ctaHref+'">'+ctaText+'</a>'):'')+'</div></td></tr>';}
// ---- Command palette (Cmd/Ctrl+K). Power users never touch a nav bar. ----
var PB_CMDS=[
 {t:"Browse GPUs",           h:"/marketplace", k:"gpu hardware rent inventory"},
 {t:"Templates",             h:"/catalog",     k:"launch jupyter pytorch ollama blender run"},
 {t:"Your account",          h:"/account",     k:"dashboard wallet vms nodes"},
 {t:"Pricing",               h:"/pricing",     k:"cost price hourly"},
 {t:"API docs",              h:"/docs",        k:"api reference developers curl"},
 {t:"API keys",              h:"/keys",        k:"key token auth"},
 {t:"List your GPU",         h:"/install",     k:"sell host earn agent seller"},
 {t:"Security & trust",      h:"/security",    k:"verified attestation isolation escrow"},
 {t:"Status",                h:"/status",      k:"uptime health incident"},
];
function pbPalette(){
  if(document.getElementById('pbpal'))return;
  var d=document.createElement('div');d.id='pbpal';
  d.style.cssText='position:fixed;inset:0;z-index:200;background:rgba(3,7,17,.72);backdrop-filter:blur(6px);display:flex;align-items:flex-start;justify-content:center;padding-top:14vh';
  d.innerHTML='<div style="width:min(560px,92vw);background:var(--panel);border:1px solid var(--line2);border-radius:16px;overflow:hidden;box-shadow:0 30px 80px -30px rgba(0,0,0,.8)">'+
    '<input id="pbpalq" placeholder="Search or jump to…" autocomplete="off" style="width:100%;border:0;border-bottom:1px solid var(--line);border-radius:0;padding:15px 18px;font-size:15px;background:transparent"/>'+
    '<div id="pbpalr" style="max-height:52vh;overflow:auto;padding:6px"></div></div>';
  document.body.appendChild(d);
  var q=document.getElementById('pbpalq'),res=document.getElementById('pbpalr'),sel=0,list=PB_CMDS;
  function paint(){
    res.innerHTML=list.map(function(c,i){
      return '<a href="'+c.h+'" style="display:flex;align-items:center;gap:11px;padding:11px 13px;border-radius:10px;'+(i===sel?'background:rgba(53,224,208,.10)':'')+'">'+
        '<span class="mono mini" style="color:var(--teal)">↵</span>'+
        '<span style="flex:1;font-size:14px">'+c.t+'</span>'+
        '<span class="mini">'+c.h+'</span></a>';}).join('')
      || '<div class="mut" style="padding:18px;text-align:center;font-size:13px">Nothing matches.</div>';
  }
  function filter(){
    var v=q.value.toLowerCase().trim();sel=0;
    list=!v?PB_CMDS:PB_CMDS.filter(function(c){return (c.t+' '+c.k).toLowerCase().indexOf(v)>=0;});
    paint();
  }
  q.addEventListener('input',filter);
  d.addEventListener('click',function(e){if(e.target===d)close();});
  function close(){d.remove();document.removeEventListener('keydown',keys);}
  function keys(e){
    if(e.key==='Escape'){close();}
    else if(e.key==='ArrowDown'){e.preventDefault();sel=Math.min(sel+1,list.length-1);paint();}
    else if(e.key==='ArrowUp'){e.preventDefault();sel=Math.max(sel-1,0);paint();}
    else if(e.key==='Enter'&&list[sel]){location.href=list[sel].h;}
  }
  document.addEventListener('keydown',keys);
  paint();q.focus();
}
document.addEventListener('keydown',function(e){
  if((e.metaKey||e.ctrlKey)&&e.key.toLowerCase()==='k'){e.preventDefault();pbPalette();}
});
window._PBCMDS={};
function pbGoGpu(id){ location.href='/gpu/'+id; }
function pbBuy(id){ location.href='/buy/'+id; }
function pbCloseModal(a1, el){ var m = el && el.closest ? el.closest('div') : null; while(m && m.parentNode !== document.body) m = m.parentNode; if(m) m.remove(); }

// One delegated click handler for everything. No nested quotes in generated HTML,
// so there is no escaping to get wrong. (A lost backslash here used to kill the
// whole script block.)
document.addEventListener('click', function(e){
  var el = e.target.closest && e.target.closest('[data-act]');
  if(!el) return;
  var fn = window[el.getAttribute('data-act')];
  if(typeof fn !== 'function') return;
  e.preventDefault();
  fn(el.getAttribute('data-a1'), el.getAttribute('data-a2') || el);
});

// Show the price BEFORE the buyer commits. Never let someone click Launch and only
// then find out what it cost.
async function pbConfirm(name,hours){
  var est=null;
  try{
    var r=await fetch('/estimate',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({template:name,hours:hours})});
    if(r.ok) est=await r.json();
  }catch(e){}
  if(!est){ if(confirm('Launch '+name+' for '+hours+'h?')) pbLaunch(name,hours); return; }
  var L=[];
  L.push('Launch '+name+' on a '+(est.gpu_model||'CPU')+'?');
  L.push('');
  L.push('$'+Number(est.price_per_hour).toFixed(2)+'/hour x '+est.hours+'h = $'+Number(est.total).toFixed(2));
  L.push('You prepay this into escrow.');
  L.push('');
  L.push('Stop after 1 hour: charged $'+Number(est.if_you_stop_after_1h.charged).toFixed(2)+', refunded $'+Number(est.if_you_stop_after_1h.refunded).toFixed(2)+'.');
  if(est.cloud_comparison){
    L.push('');
    L.push('A comparable public cloud would cost about $'+Number(est.cloud_comparison.reference_total).toFixed(2)+'.');
  }
  if(confirm(L.join(String.fromCharCode(10)))) pbLaunch(name,hours);
}
function pbCmd(name,hours){var Q=String.fromCharCode(39);return 'curl -sX POST https://petabyte.market/launch -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d '+Q+'{"template":"'+name+'","hours":'+(hours||2)+'}'+Q;}
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
    '<button class="copybtn" data-act="pbCopy" data-a1="'+t.name+'">copy</button></div>'+
    '<button class="btn btn-amber lbtn" data-act="pbConfirm" data-a1="'+t.name+'" data-a2="'+(hours||2)+'">Launch</button>'+
   '</div></div>';}).join('');}
function _lres(){var e=document.getElementById('launchresult');if(e){e.style.display='';}return e;}
async function pbLaunch(name,hours){var out=_lres();if(!out)return;
 if(typeof authed==='function'&&!authed()){out.innerHTML='<div class="lres">Please <a class="teal" href="/login">sign in</a> to launch.</div>';return;}
 out.innerHTML='<div class="lres">Reserving a GPU for <b style="text-transform:capitalize">'+name+'</b>…</div>';
 var r=await api('/launch',{method:'POST',body:JSON.stringify({template:name,hours:hours||2})});
 if(r.status===401){out.innerHTML='<div class="lres">Please <a class="teal" href="/login">sign in</a> first.</div>';return;}
 if(r.status===402){out.innerHTML='<div class="lres">Add funds first — <a class="teal" href="/account">open your wallet</a>.</div>';return;}
 if(r.status===409){out.innerHTML='<div class="lres">No matching GPU is online right now. Try again shortly.</div>';return;}
 if(!r.ok){
   // Never show a bare status code. Say what happened, whether money moved,
   // and where to go next.
   var e=(r.body&&r.body.error)||{};
   var msg=e.message||'Something went wrong on our side. Nothing was charged.';
   var lbl=e.next==='/marketplace'?'Find another GPU':(e.next==='/account'?'Add funds':'Continue');
   var act=e.next?('<a class="btn btn-teal" style="margin-top:12px" href="'+e.next+'">'+lbl+'</a>'):'';
   var rid=e.request_id?('<div class="mini" style="margin-top:10px">Reference '+e.request_id+'</div>'):'';
   out.innerHTML='<div class="lres"><div style="font-family:var(--disp);font-weight:600;color:var(--warn);margin-bottom:4px">Could not launch '+name+'</div>'+
     '<div class="mut" style="font-size:13px">'+msg+'</div>'+act+rid+'</div>';
   return;}
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


_DEFAULT_DESC = ("Rent GPUs by the hour from verified hosts, or earn from hardware you "
                 "already own. Escrowed payments, refunded to the cent for hours you do "
                 "not use.")


def _page(title, body, desc=None, path="/"):
    """Every page carries its own description, canonical URL and share card.

    Without these, a link to petabyte.market shared in a DM or on X renders as a bare
    URL with no title, no summary and no image."""
    head = (_HEAD.replace("%%TITLE%%", title)
                 .replace("%%DESC%%", (desc or _DEFAULT_DESC).replace('"', "&quot;"))
                 .replace("%%PATH%%", path))
    return head + _NAV + _AUTHJS + body + _FOOT + "</body></html>"


LANDING_HTML = _page("Petabyte — the compute exchange",
    desc="Rent verified GPUs by the hour, or earn from hardware you already own. One click to launch. Escrow refunds every hour you do not use.", path="/", body="""
<div class="hero"><div class="wrap" style="padding:74px 24px 30px">
  <img class="hexbg" src="/static/petabyte-logo.png" alt=""/>
  <div class="cols" style="align-items:center;gap:34px">
    <div style="flex:1.35 1 420px;min-width:300px">
      <div class="eyebrow"><span class="dot"></span> verified gpu marketplace</div>
      <h1 style="font-size:clamp(40px,6.8vw,76px);margin:20px 0 16px;max-width:15ch"><span data-ar="قدرة حوسبة بدون أسعار السحابة.">GPU compute <span class="grad">without cloud prices.</span></span></h1>
      <p class="mut" style="font-size:17px;max-width:52ch" data-ar="استأجر كروت رسومات بالساعة من مضيفين موثّقين، أو اربح من عتاد تملكه بالفعل. تُحفظ أموالك في ضمان حتى ينتهي العمل — وإذا تعطّل الجهاز، تُعاد إليك.">Rent GPUs by the hour from verified hosts, or earn from hardware you already own. Your money sits in escrow until the work is done — if a node drops, you are refunded.</p>
      <div class="mini" style="margin-top:28px;margin-bottom:10px" data-ar="ما الذي تبحث عنه؟">What are you here for?</div>
      <div style="display:flex;gap:12px;flex-wrap:wrap">
        <a class="btn btn-amber arrow-fwd" href="/marketplace" data-ar="أحتاج كروت رسومات">I need GPUs </a>
        <a class="btn btn-teal" href="/install" data-ar="لديّ كرت رسومات لتأجيره">I have a GPU to rent out</a>
      <div class="mini" style="margin-top:14px" data-ar="تفضّل جولة معنا؟ ">Prefer a walkthrough? <a class="teal" href="/demo" data-ar="احجز عرضاً مدته ٢٠ دقيقة">Book a 20-minute demo</a></div>
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

<!-- CREDIBILITY: every claim here is enforced by a test in the repo. No vanity metrics,
     no fabricated logos. What we can prove, and nothing we cannot. -->
<div class="wrap" style="padding:6px 24px 4px">
  <div class="mini" style="text-align:center;margin-bottom:14px" data-ar="ما الذي نضمنه فعلاً — كل بند منها مغطّى باختبار.">What we actually guarantee — every line below is enforced by a test</div>
  <div class="cols" style="gap:14px;flex-wrap:wrap">
    <div class="card" style="flex:1 1 210px">
      <div class="lbl">Escrow-protected</div>
      <p class="mut" style="font-size:13px;margin-top:6px" data-ar="تُحفظ أموالك في ضمان وتُعاد الساعات غير المستخدمة بالسنت.">Your money is held in escrow and released only for work done. Stop early and the unused hours are refunded to the cent.</p>
    </div>
    <div class="card" style="flex:1 1 210px">
      <div class="lbl">Survives a host failure</div>
      <p class="mut" style="font-size:13px;margin-top:6px" data-ar="إذا تعطّل الجهاز أثناء العمل، ننقلك تلقائياً إلى مضيف آخر.">If a host drops mid-job, we move your instance to another node and you keep going. There is a timeline for every rental that proves it.</p>
    </div>
    <div class="card" style="flex:1 1 210px">
      <div class="lbl">Verified hardware</div>
      <p class="mut" style="font-size:13px;margin-top:6px" data-ar="لا يقبل أي جهاز عملاً مدفوعاً قبل إثبات عتاده تشفيرياً.">No machine can take paid work until it has cryptographically proven what GPU it actually has. Unverified nodes are marked as such.</p>
    </div>
    <div class="card" style="flex:1 1 210px">
      <div class="lbl">Isolated workloads</div>
      <p class="mut" style="font-size:13px;margin-top:6px" data-ar="يعمل كل عبء داخل جهاز افتراضي دقيق، ومنافذه مغلقة افتراضياً لحماية شبكة المضيف.">Each workload runs in its own micro-VM with a default-closed network, so one tenant cannot reach another and a host's home network stays protected.</p>
    </div>
  </div>
  <div style="text-align:center;margin-top:16px">
    <a class="btn btn-ghost" href="/security" data-ar="كيف يعمل هذا">How this works</a>
    <a class="btn btn-ghost" href="/demo" data-ar="شاهده مباشرةً">See it live</a>
  </div>
</div>

<!-- LANDING VIDEO (admin-editable id via /landing/video) -->
<div class="wrap" style="padding:22px 24px 6px">
  <div id="landingvideo" style="max-width:400px;margin:0 auto;display:none">
    <div id="landingvideoratio" style="position:relative;padding-bottom:177.78%;height:0;border-radius:16px;overflow:hidden;border:1px solid var(--line2);background:#000">
      <iframe id="landingvideoframe" style="position:absolute;top:0;left:0;width:100%;height:100%;border:0"
        loading="lazy"
        allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share"
        referrerpolicy="strict-origin-when-cross-origin"
        allowfullscreen title="Petabyte"></iframe>
    </div>
    <!-- fallback: if a video ever cannot embed, this is a live link, not a dead box -->
    <div class="mini" style="text-align:center;margin-top:8px"><a id="landingvideolink" class="teal" href="#" target="_blank" rel="noopener" data-ar="شاهد على يوتيوب">Watch on YouTube ↗</a></div>
  </div>
</div>
<script>
(async function(){
  try{
    var r=await fetch('/landing/video'); if(!r.ok)return;
    var d=await r.json(); var id=d.video_id; if(!id)return;
    var portrait=(d.orientation!=='landscape');   // default portrait for back-compat
    var f=document.getElementById('landingvideoframe');
    f.src='https://www.youtube.com/embed/'+id+'?rel=0&modestbranding=1&playsinline=1';
    // portrait = 9:16 tall; landscape = 16:9 wide (a normal video embeds reliably)
    var box=document.getElementById('landingvideo'), ratio=document.getElementById('landingvideoratio');
    if(portrait){ box.style.maxWidth='400px'; ratio.style.paddingBottom='177.78%'; }
    else { box.style.maxWidth='720px'; ratio.style.paddingBottom='56.25%'; }
    var link=document.getElementById('landingvideolink');
    if(link) link.href=(portrait?'https://youtube.com/shorts/':'https://youtu.be/')+id;
    box.style.display='';
  }catch(e){}
})();
</script>


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

<!-- NEWSLETTER (Mailgun mailing list via /newsletter/subscribe) -->
<div class="wrap" style="padding:10px 24px 40px">
  <div class="card" style="max-width:560px;margin:0 auto;text-align:center">
    <div class="lbl" data-ar="النشرة البريدية">Newsletter</div>
    <h2 style="font-size:19px;margin:6px 0 6px" data-ar="تابع تطوّر Petabyte">Follow how Petabyte is built</h2>
    <p class="mut" style="font-size:13.5px;margin-bottom:14px" data-ar="بريد إلكتروني بين الحين والآخر عن الميزات والتقدّم. لا رسائل مزعجة، وإلغاء الاشتراك بأي وقت.">An occasional email on features and progress. No spam, unsubscribe anytime.</p>
    <div class="filterbar" style="justify-content:center;gap:8px">
      <input id="nl_email" type="email" aria-label="Email address" data-ar-ph="بريدك الإلكتروني" placeholder="you@example.com" style="flex:1;min-width:200px;max-width:320px"/>
      <button class="btn btn-teal" data-act="subscribeNewsletter" data-ar="اشترك">Subscribe</button>
    </div>
    <div id="nl_msg" class="mini" style="min-height:18px;margin-top:10px"></div>
  </div>
</div>
<script>
async function subscribeNewsletter(){
  var m=document.getElementById('nl_msg');
  var input=document.getElementById('nl_email');
  var btn=document.querySelector('[data-act="subscribeNewsletter"]');
  var e=(input.value||'').trim();
  if(!e){m.style.color='var(--warn)';m.textContent='Enter your email.';return;}
  if(btn&&btn.disabled)return;                       // guard against duplicate submits
  if(btn)btn.disabled=true;                          // disable while the request is in flight
  m.style.color='';m.textContent='Subscribing…';
  try{
    var r=await fetch('/newsletter/subscribe',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({email:e})});
    var b={};try{b=await r.json();}catch(_){}
    if(r.ok){m.style.color='var(--pos)';m.textContent=b.message||"Thanks — you're subscribed.";input.value='';}
    else if(r.status===429){m.style.color='var(--warn)';m.textContent='Too many attempts. Please try again shortly.';}
    else{m.style.color='var(--warn)';m.textContent=(b.detail&&b.detail.message)||(b.error&&b.error.message)||"We couldn't subscribe you right now. Please try again shortly.";}
  }catch(err){m.style.color='var(--warn)';m.textContent="We couldn't subscribe you right now. Please try again shortly.";}
  finally{if(btn)btn.disabled=false;}                 // always re-enable
}
</script>

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
      return '<a href="/gpu/'+s.id+'" style="display:flex;align-items:center;gap:12px;padding:11px 0;border-bottom:1px solid var(--hair)">'+
       '<div style="flex:1;min-width:0">'+
        '<div style="font-family:var(--disp);font-weight:600;font-size:14px">'+esc(s.gpu_model||'CPU')+(s.vram_gb?' <span class="mut" style="font-weight:400">· '+s.vram_gb+'GB</span>':'')+'</div>'+
        '<div class="mini" style="margin-top:2px">'+esc(s.region||'unknown region')+' · '+(s.available_units>0?'<span class="teal">available now</span>':'busy')+'</div>'+
       '</div>'+
       '<div style="text-align:end;flex:none">'+
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


MARKETPLACE_HTML = _page("Petabyte — marketplace",
    desc="Browse verified GPUs by model, VRAM, region and price. Compare each one against public cloud rates before you commit.", path="/marketplace", body="""
<div class="wrap" style="padding:48px 22px 10px">
  <div class="eyebrow"><span class="dot"></span> <span data-ar="المعروض المباشر">live inventory</span></div>
  <h1 style="font-size:clamp(30px,5vw,40px);margin:16px 0 8px" data-ar="كروت الرسومات المتاحة">Available <span class="grad-teal">GPUs</span></h1>
  <p class="mut" id="mnote">Loading verified nodes…</p>
  <div id="savingsbanner" class="savings-banner" role="status" style="display:none"></div>
  <div id="demobadge" style="display:none;margin-top:8px"><span class="badge cc" title="This marketplace contains seeded demonstration nodes, clearly labelled and never counted as real traction.">Demo data — includes simulated nodes</span></div>
</div>
<script>
(async function(){try{var st=await (await fetch('/marketplace/stats')).json();
  if(st.contains_demo_data)document.getElementById('demobadge').style.display='';}catch(e){}})();
</script>
<div class="wrap" style="padding:12px 22px 30px">
  <div class="panel filterbar" style="padding:16px 18px;margin-bottom:14px">
    <div class="field"><span data-ar="طراز الكرت">GPU model</span><input id="fgpu" aria-label="Filter by GPU model" placeholder="H100, 4090…" size="10" onkeydown="if(event.key==='Enter')load()"/></div>
    <div class="field"><span data-ar="أقصى $/ساعة">Max $/hr</span><input id="fprice" aria-label="Maximum price per hour" type="number" placeholder="any" size="7" step="0.1" onkeydown="if(event.key==='Enter')load()"/></div>
    <div class="field"><span data-ar="أدنى ذاكرة">Min VRAM</span><input id="fvram" aria-label="Minimum VRAM in GB" type="number" placeholder="GB" size="7" onkeydown="if(event.key==='Enter')load()"/></div>
    <div class="field"><span data-ar="المنطقة">Region</span><input id="fregion" aria-label="Filter by region" placeholder="any" size="8" onkeydown="if(event.key==='Enter')load()"/></div>
    <div class="field"><span data-ar="ترتيب حسب">Sort by</span><select id="fsort" aria-label="Sort results" onchange="load()"><option value="price" data-ar="الأرخص">Cheapest</option><option value="rep" data-ar="الأكثر ثقة">Most trusted</option><option value="vram" data-ar="أكبر ذاكرة">Most VRAM</option></select></div>
    <label class="mini" style="display:flex;align-items:center;gap:6px;padding-bottom:9px"><input id="fconf" type="checkbox" style="width:15px;height:15px;padding:0"/> <span data-ar="سرّية">confidential</span></label>
    <div style="display:flex;gap:8px;padding-bottom:1px">
      <button class="btn btn-teal" onclick="load()" data-ar="تطبيق">Apply</button>
      <button class="btn-ghost btn" onclick="clearf()" data-ar="إعادة تعيين">Reset</button>
    </div>
  </div>
  <div class="panel" style="overflow:auto">
    <table class="tbl"><thead><tr><th data-ar="الكرت">GPU</th><th data-ar="الذاكرة">VRAM</th><th>$/hr</th><th data-ar="مقابل السحابة">vs cloud</th><th data-ar="الثقة">trust</th><th data-ar="المنطقة">region</th><th data-ar="السمعة">rep</th><th data-ar="متاح">free</th></tr></thead>
    <tbody id="mrows"><tr><td colspan="8" style="padding:24px;text-align:center" class="mut mono">loading…</td></tr></tbody></table>
  </div>
  <div style="margin-top:18px;display:flex;gap:14px;align-items:center;flex-wrap:wrap">
    <a class="btn btn-amber" href="/app" data-ar="سجّل الدخول للحجز ←">Sign in to book →</a>
    <span class="mut" data-ar="التصفّح متاح للجميع. الحجز يتطلّب حساباً. يتحدّث التوفّر مباشرةً.">Browsing is open. Booking needs an account. Availability updates live.</span>
  </div>
</div>
<script>
function qs(){var p=new URLSearchParams();var g=v('fgpu');if(g)p.set('gpu',g);var pr=v('fprice');if(pr)p.set('max_price',pr);
 var vr=v('fvram');if(vr)p.set('min_vram',vr);var rg=v('fregion');if(rg)p.set('region',rg);
 if(document.getElementById('fconf').checked)p.set('confidential','true');p.set('sort',document.getElementById('fsort').value);return p.toString();}
function v(id){return (document.getElementById(id).value||'').trim();}
function clearf(){['fgpu','fprice','fvram','fregion'].forEach(function(i){document.getElementById(i).value='';});document.getElementById('fconf').checked=false;load();}
async function load(){var r=await fetch('/marketplace/specs?'+qs());var b=await r.json();
 document.getElementById('mnote').textContent=b.count?b.count+' GPUs match · "vs cloud" compares each GPU to the on-demand cloud rate for the SAME class':'No GPUs match these filters.';
 var tb=document.getElementById('mrows');if(!b.count){tb.innerHTML=pbEmpty(8,'No GPUs match','Widen your filters, or be the first to list one.','/install','List your GPU');return;}
 tb.innerHTML=b.specs.map(function(s){var save=(s.cloud_reference&&s.price_per_hour<s.cloud_reference)?Math.round((1-s.price_per_hour/s.cloud_reference)*100):0;
  var t=[];if(s.trust)t.push('<span class="badge '+(s.trust.rank>=2?'ok':'')+'" title="'+s.trust.evidence+'">'+s.trust.label+'</span>');
  if(s.confidential)t.push('<span class="badge cc" title="Confidential-computing pilot — vendor TEE verification not yet connected">CC pilot</span>');
  if(s.region_verified)t.push('<span class="badge ok">region ✓</span>');
  var rc=s.reputation_score>=80?'var(--pos)':s.reputation_score>=60?'var(--warn)':'var(--bad)';
  var rep=(s.reputation_score!=null?s.reputation_score:'—')+(s.success_rate!=null?' <span class="mut" style="font-size:10px">('+s.success_rate+'%)</span>':'');
  var vram=s.vram_gb?((s.gpu_count>1?s.gpu_count+'× ':'')+s.vram_gb+'GB'):'—';
  return '<tr><td data-l="GPU" style="font-family:var(--disp);font-weight:600">'+esc(s.gpu_model||'CPU')+'</td>'+
   '<td data-l="VRAM" class="mono mut" style="font-size:12px">'+vram+'</td>'+
   '<td data-l="$/hr" class="mono amber">$'+s.price_per_hour.toFixed(2)+(s.auto_price?' <span class="badge cc" title="demand-priced within seller bounds">auto</span>':'')+'</td>'+
   '<td data-l="vs cloud" class="mono" style="color:var(--pos)">'+(save>0?'−'+save+'%':'—')+'</td>'+
   '<td data-l="trust">'+(t.join(' ')||'<span class="mut mono" style="font-size:11px">standard</span>')+'</td>'+
   '<td data-l="Region" class="mut mono" style="font-size:12px">'+esc(s.region||'—')+'</td>'+
   '<td data-l="rep" class="mono" style="color:'+rc+'">'+rep+'</td>'+
   '<td data-l="free" class="mono" style="color:var(--teal)">'+s.available_units+'</td></tr>';}).join('');
 updateSavingsBanner(b.specs);}
// Lead with the headline the buyer cares about: how much cheaper than the hyperscalers.
function updateSavingsBanner(specs){
 var banner=document.getElementById('savingsbanner');
 if(!banner){return;}
 var maxSave=0,cheaper=0;
 (specs||[]).forEach(function(s){
  if(s.cloud_reference && s.price_per_hour < s.cloud_reference){
   cheaper++;
   var pc=Math.round((1-s.price_per_hour/s.cloud_reference)*100);
   if(pc>maxSave){maxSave=pc;}
  }
 });
 if(maxSave>0){
  banner.innerHTML='<span>Up to <b>'+maxSave+'% cheaper</b> than AWS, GCP &amp; Azure on-demand</span>'+
   '<span class="sub">'+cheaper+' GPU'+(cheaper===1?'':'s')+' below the on-demand cloud reference for the same class — a benchmark, not a quote.</span>';
  banner.style.display='';
 }else{
  banner.style.display='none';
 }
}
load();setInterval(load,8000);
</script>""")


INSTALL_HTML = _page("Petabyte — become a seller",
    desc="List a GPU you already own and earn when it is idle. One command to install the agent. Your machine stays yours.", path="/install", body="""
<div class="wrap" style="padding:48px 22px 10px">
  <div class="eyebrow"><span class="dot"></span> <span data-ar="تسجيل جهاز">node onboarding</span></div>
  <h1 style="font-size:clamp(30px,5vw,40px);margin:16px 0 8px" data-ar="أدرِج كرت رسوماتك بأمرٍ واحد">List your GPU in <span class="grad-teal">one command</span></h1>
  <p class="mut" style="max-width:56ch" data-ar="أي جهاز NVIDIA يمكن أن يصبح عقدة. يتحقق المُثبِّت من عتادك، ويعزل المهام داخل Docker، ويجعلك متصلاً خلال ٣٠ ثانية تقريباً. دون حصرية.">Any NVIDIA machine can become a node. The installer verifies your hardware, sandboxes jobs in Docker, and brings you online in ~30 seconds. No exclusivity.</p>
  <div class="earn-banner" role="status" style="max-width:640px">
    <span>You keep <b>90%</b> of every rental</span>
    <span class="sub">Set your own price · withdraw anytime · online in one command, ~30 seconds.</span>
  </div>
</div>
<div class="wrap" style="padding:6px 22px 0">
  <div class="card" style="border-color:rgba(79,214,201,.3);background:linear-gradient(180deg,rgba(79,214,201,.05),transparent)">
    <div class="lbl" data-ar="الخطوة ١ · مفتاح جهازك">Step 1 · your node key</div>
    <p class="mut" id="ikhint" data-ar="تتصل الأجهزة عبر مفتاح API — لا تُخزَّن أي كلمة مرور على الجهاز إطلاقاً. سجّل الدخول لإنشاء مفتاح.">Nodes connect with an API key — no password ever lives on the machine. <a class="teal" href="/login">Sign in</a> to generate one.</p>
    <div id="ikauthed" style="display:none">
      <p class="mut" style="margin-bottom:12px" data-ar="أنشئ مفتاح جهاز، ثم ألصقه في الأمر أدناه كـ PETABYTE_API_KEY. يسجّل الجهاز نفسه ويثبت عتاده بهذا المفتاح.">Generate a node key, then paste it into the command below as <code class="teal">PETABYTE_API_KEY</code>. The node registers &amp; attests itself with this key.</p>
      <button class="btn-amber" onclick="mkkey()" data-ar="أنشئ مفتاح جهاز">Create node key</button>
      <pre id="ikkey" style="display:none;margin-top:14px"></pre>
    </div>
  </div>
</div>
<div class="wrap" style="padding:12px 22px 30px">
  <div class="mini" style="margin:6px 0 12px" data-ar="الخطوة ٢ · شغّل المُثبِّت">Step 2 · run the installer</div>
  <div class="cols c3">
    <div class="card"><div class="lbl" data-ar="لينكس · أوبونتو/دبيان">Linux · Ubuntu/Debian</div>
      <pre>PETABYTE_API_URL=https://petabyte.market \\
PETABYTE_API_KEY=pk_your_node_key \\
PRICE_PER_HOUR=1.5 \\
bash &lt;(curl -fsSL https://petabyte.market/install.sh)</pre></div>
    <div class="card"><div class="lbl" data-ar="ويندوز · WSL2">Windows · WSL2</div>
      <pre>$env:PETABYTE_API_URL="https://petabyte.market"
$env:PETABYTE_API_KEY="pk_your_node_key"
$env:PRICE_PER_HOUR="1.5"
irm https://petabyte.market/install.ps1 | iex</pre>
      <p class="mut" style="font-size:12px;margin-top:9px" data-ar="PowerShell بصلاحيات المدير. يثبّت WSL2 والوكيل.">Elevated PowerShell. Installs WSL2 + the agent.</p></div>
    <div class="card"><div class="lbl" data-ar="تحقّق">Verify</div>
      <pre>systemctl status petabyte-agent
journalctl -u petabyte-agent -f</pre>
      <p class="mut" style="font-size:12px;margin-top:9px" data-ar="يظهر كرت رسوماتك في السوق خلال دقيقة.">Your GPU appears in the <a class="teal" href="/marketplace">marketplace</a> within a minute.</p></div>
  </div>
  <div class="card" style="margin-top:16px">
    <div class="lbl" data-ar="كم يمكن أن أربح؟">Earnings calculator</div>
    <p class="mut" style="margin-bottom:6px" data-ar="اكتب اسم كرت رسوماتك لاقتراح سعر، ثم اسحب مؤشّر الاستخدام لترى دخلك المتوقّع. أنت تحدّد السعر النهائي وتحتفظ بـ٩٠٪.">Type your GPU for a suggested rate, then drag utilization to see what it could earn. You set the final price and keep 90%.</p>
    <div class="calc-controls">
      <div class="field">
        <label for="pgpu">GPU model</label>
        <input id="pgpu" placeholder="e.g. RTX 4090" onkeydown="if(event.key==='Enter')suggest()"/>
      </div>
      <div class="field">
        <label for="calc_price">Your price ($/hr)</label>
        <input id="calc_price" type="number" step="0.05" min="0" value="1.50" oninput="recalc()"/>
      </div>
      <button class="btn btn-teal" onclick="suggest()" data-ar="اقترح سعراً">Suggest a price</button>
    </div>
    <div class="calc-util">
      <label for="calc_util">Utilization &mdash; <b id="calc_util_val" class="amber">50%</b> <span class="mut" style="font-weight:400">of the time rented</span></label>
      <input id="calc_util" type="range" min="0" max="100" value="50" step="5" oninput="recalc()" aria-label="Expected utilization percent"/>
    </div>
    <div class="calc-out">
      <div class="calc-tile"><div class="calc-n" id="calc_day">$0</div><div class="calc-l">per day</div></div>
      <div class="calc-tile"><div class="calc-n" id="calc_month">$0</div><div class="calc-l">per month</div></div>
      <div class="calc-tile"><div class="calc-n" id="calc_year">$0</div><div class="calc-l">per year</div></div>
    </div>
    <p id="psug" class="mini mut" style="margin-top:12px"></p>
    <p class="mini mut" style="margin-top:4px" data-ar="تقديرات بعد رسوم المنصة ١٠٪ (تحتفظ بـ٩٠٪). الأرباح الفعلية تعتمد على الطلب الحقيقي.">Estimates after the 10% platform fee — you keep 90%. Actual earnings depend on real demand.</p>
  </div>
  <div class="card" style="margin-top:16px"><div class="lbl" data-ar="جرّبه دون مخاطرة">Try it risk-free</div>
    <p class="mut" data-ar="يعمل الوكيل داخل بيئة لينكس معزولة — لا يمسّ ألعابك أو ملفاتك، ويعمل فقط حين يكون جهازك خاملاً. أوقفه مؤقتاً متى شئت، أو أزِله تماماً بأمرٍ واحد. وإذا فعّلت Petabyte خاصية WSL لك، فإن إلغاء التثبيت يعيدها كما كانت.">The agent runs in an isolated Linux sandbox — it never touches your games or files, and only works when your PC is idle. <b class="teal">Pause</b> anytime, or <b class="teal">remove it completely</b> in one command. If Petabyte turned on WSL for you, uninstalling turns it back off.</p>
    <pre style="margin-top:10px">$env:PETABYTE_ACTION="pause";     irm https://petabyte.market/manage.ps1 | iex
$env:PETABYTE_ACTION="uninstall"; irm https://petabyte.market/manage.ps1 | iex</pre>
  </div>
  <div class="card" style="margin-top:16px"><div class="lbl am" data-ar="استلم أرباحك">Get paid</div>
    <p class="mut" data-ar="رصيد واحد. اسحب في أي وقت أو وفق جدول أسبوعي — تحويل بنكي أو USDC أو بطاقة هدية. فعّل خيار التعدين عند الخمول لتكسب دخلاً في الخلفية كلما لم يكن جهازك مؤجراً.">One balance. Withdraw anytime or on a weekly schedule — bank, USDC, or gift card. Opt in to idle-fallback and earn a background trickle whenever the node isn't rented. <a class="teal" href="/app">Open the app →</a></p>
  </div>
</div>
<script>
// Earnings calculator: hourly price x hours x utilization, minus the 10% fee. Recompute
// on every keystroke/drag so the numbers move like NiceHash's profitability calculator.
var CALC_KEEP=0.9;   // seller keeps 90% (10% platform fee)
function setMoney(id,v){
  var el=document.getElementById(id);
  if(el){el.textContent='$'+Math.round(v).toLocaleString();}
}
function recalc(){
  var price=parseFloat(document.getElementById('calc_price').value||'0')||0;
  var util=parseInt(document.getElementById('calc_util').value||'0',10)/100;
  var uv=document.getElementById('calc_util_val');
  if(uv){uv.textContent=Math.round(util*100)+'%';}
  var perDay=price*24*util*CALC_KEEP;
  setMoney('calc_day',perDay);
  setMoney('calc_month',perDay*30);
  setMoney('calc_year',perDay*365);
}
async function suggest(){
  var g=(document.getElementById('pgpu').value||'').trim();
  var r=await fetch('/pricing/suggest?gpu_model='+encodeURIComponent(g));
  var b=await r.json();
  var pr=document.getElementById('calc_price');
  if(pr && b.suggested_price){pr.value=b.suggested_price;}
  var psug=document.getElementById('psug');
  if(psug){
    psug.innerHTML='Suggested rate for '+(g?esc(g):'this GPU')+': <b class="amber">$'+esc(b.suggested_price)+
      '/hr</b> · '+esc(b.basis||'')+' · cloud on-demand &asymp; $'+esc(b.cloud_reference)+'/hr';
  }
  recalc();
}
recalc();   // alive from first paint
(function(){ if(authed()){var a=document.getElementById('ikauthed'),h=document.getElementById('ikhint');if(a)a.style.display='';if(h)h.style.display='none';} })();
async function mkkey(){
  await api('/change_role',{method:'POST',body:JSON.stringify({role:'seller'})});   // idempotent
  var r=await api('/create_api_key?days=90&label=node&scopes=node,jobs',{method:'POST'});
  var el=document.getElementById('ikkey'); el.style.display='';
  el.textContent = r.ok ? ('Copy now — shown once:\\n\\nPETABYTE_API_KEY='+r.body.api_key)
                        : 'Could not create a key — make sure you are signed in.';
}
</script>""")


DEVELOPERS_HTML = _page("Petabyte — developers",
    desc="Launch GPU workloads from the API in one call. Keys, scopes, templates and a full reference.", path="/developers", body="""
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
 tb.innerHTML=r.body.keys.map(function(k){return '<tr><td>'+esc(k.label||'—')+'</td><td class="mono mut">'+esc(k.scopes||'—')+'</td>'+
  '<td class="mono mut" style="font-size:11px">'+k.created_at.slice(0,10)+'</td><td class="mono mut" style="font-size:11px">'+k.expires_at.slice(0,10)+'</td>'+
  '<td>'+(k.revoked?'<span class="badge">revoked</span>':'<span class="badge ok">active</span>')+'</td>'+
  '<td>'+(k.revoked?'':'<button class="btn-ghost" data-act="rv" data-a1="'+k.jti+'">revoke</button>')+'</td></tr>';}).join('');}
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
    <div class="mini" style="text-align:end;line-height:1.9">petabyte.market<br><span style="color:var(--teal)">raising · pre-revenue</span></div>
  </div>
  <h1 style="font-size:clamp(30px,5.2vw,50px);margin:20px 0 12px;max-width:20ch">The routing layer for <span class="grad-teal">GPU compute</span>, priced like an energy market.</h1>
  <p class="mut" style="font-size:16px;max-width:70ch">Petabyte aggregates underutilized GPU capacity from distributed providers and routes it to buyers below hyperscaler prices — with cryptographically verified hardware, container isolation, escrow-protected settlement, and a double-entry ledger. Real payment rails and vendor TEE attestation are on the roadmap, not yet live; we say exactly what is built and what is not.</p>
</div></div>
<div class="wrap" style="padding:26px 22px 8px"><div class="cols c2">
  <div class="card"><div class="lbl am">The problem</div>
    <p class="mut">GPU compute is expensive and scarce. Hyperscalers charge premium rates with limited high-end availability — while enormous capacity sits idle across smaller providers, with no efficient way to monetize it.</p></div>
  <div class="card"><div class="lbl">The solution</div>
    <p class="mut">A marketplace that unlocks that hidden supply. Buyers get cheaper on-demand GPUs without lock-in, secured today by hardened container isolation and escrow. Providers turn idle hardware into revenue with escrowed, ledger-tracked settlement. Stronger micro-VM/TEE isolation and idle-fallback are on the roadmap.</p></div>
</div></div>
<div class="wrap" style="padding:16px 22px 8px">
  <div class="panel" style="padding:22px 24px;border-inline-start:3px solid var(--teal);background:linear-gradient(100deg,rgba(79,214,201,.07),rgba(44,158,155,.03))">
    <div class="lbl">Vision — beyond a marketplace</div>
    <p class="mut" style="max-width:92ch">Petabyte starts as a GPU marketplace but builds toward the <span class="teal">routing layer for compute-as-a-commodity</span> — real-time pricing and cross-provider arbitrage that treat GPU power like electricity. The deeper lever: pairing this with <span class="teal">structurally cheap electrons</span> to power AI where the electron is cheapest — the path to a sovereign, trust-minimized compute network.</p>
  </div>
</div>
<div class="wrap" style="padding:26px 22px 8px">
  <div class="mini" style="margin-bottom:14px">Infrastructure — built &amp; tested today</div>
  <div class="cols c4">
    <div class="card" style="padding:16px"><b class="teal" style="font-family:var(--disp);font-size:14px">Lumaris API</b><p class="mut" style="font-size:12.5px;margin-top:5px">Control plane &amp; job orchestration</p></div>
    <div class="card" style="padding:16px"><b class="teal" style="font-family:var(--disp);font-size:14px">Escrow &amp; Ledger</b><p class="mut" style="font-size:12.5px;margin-top:5px">Double-entry, exact-decimal, refund-on-reaper</p></div>
    <div class="card" style="padding:16px"><b class="teal" style="font-family:var(--disp);font-size:14px">Explainable Routing</b><p class="mut" style="font-size:12.5px;margin-top:5px">Deterministic scoring + audit record</p></div>
    <div class="card" style="padding:16px"><b class="teal" style="font-family:var(--disp);font-size:14px">Container Isolation</b><p class="mut" style="font-size:12.5px;margin-top:5px">cap-drop, no-net, read-only, no host fallback</p></div>
    <div class="card" style="padding:16px"><b class="teal" style="font-family:var(--disp);font-size:14px">Agent Attestation</b><p class="mut" style="font-size:12.5px;margin-top:5px">Ed25519-signed hardware reports</p></div>
    <div class="card" style="padding:16px"><b class="teal" style="font-family:var(--disp);font-size:14px">Render &amp; Transcode</b><p class="mut" style="font-size:12.5px;margin-top:5px">Fan-out / stitch pipelines</p></div>
    <div class="card" style="padding:16px"><b class="teal" style="font-family:var(--disp);font-size:14px">AI Templates</b><p class="mut" style="font-size:12.5px;margin-top:5px">One-click vLLM, Ollama, ComfyUI</p></div>
    <div class="card" style="padding:16px"><b class="teal" style="font-family:var(--disp);font-size:14px">Sandbox Ledger</b><p class="mut" style="font-size:12.5px;margin-top:5px">Payout state machine (sandbox by default)</p></div>
  </div>
  <div class="mini" style="margin:20px 0 14px">On the roadmap — <span class="mut">not yet live, and we don't claim otherwise</span></div>
  <div class="cols c4">
    <div class="card" style="padding:16px"><b class="amber" style="font-family:var(--disp);font-size:14px">Vendor TEE Attestation</b><p class="mut" style="font-size:12.5px;margin-top:5px">NVIDIA NRAS / AMD SEV-SNP (stub verifier today)</p></div>
    <div class="card" style="padding:16px"><b class="amber" style="font-family:var(--disp);font-size:14px">Micro-VM Isolation</b><p class="mut" style="font-size:12.5px;margin-top:5px">Firecracker / QEMU + GPU passthrough</p></div>
    <div class="card" style="padding:16px"><b class="amber" style="font-family:var(--disp);font-size:14px">Live Payment Rails</b><p class="mut" style="font-size:12.5px;margin-top:5px">Stripe in / provider payouts out (adapters written)</p></div>
    <div class="card" style="padding:16px"><b class="amber" style="font-family:var(--disp);font-size:14px">Idle Fallback</b><p class="mut" style="font-size:12.5px;margin-top:5px">Hard-preempt utilization capture</p></div>
  </div>
</div>
<div class="wrap" style="padding:22px 22px 8px">
  <div class="stats">
    <div class="stat"><div class="n grad-teal">Live</div><div class="l">Core marketplace infra</div></div>
    <div class="stat"><div class="n teal">500+</div><div class="l">CI assertions, both DB engines</div></div>
    <div class="stat"><div class="n teal">&lt;HS</div><div class="l">vs hyperscaler on-demand</div></div>
    <div class="stat"><div class="n teal">Pre</div><div class="l">Revenue stage</div></div>
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

  <!-- INCIDENTS: failed or stalled transactions and why -->
  <div class="wrap" style="padding:22px 22px 30px">
    <div class="lbl" style="margin-bottom:12px">Incidents <span class="mut" id="inc_sub"></span></div>
    <div class="panel" style="overflow:auto">
      <table class="tbl"><thead><tr><th>Type</th><th>Ref</th><th>Amount</th><th>Age</th><th>Reason</th></tr></thead>
      <tbody id="incrows"><tr><td colspan=5 class="mut mono" style="padding:20px;text-align:center">loading…</td></tr></tbody></table>
    </div>
    <p class="mini" style="margin-top:8px">Stalled = money escrowed/active with no terminal state. Failed jobs are retryable; the reaper fails over or refunds dead nodes.</p>
  </div>

  <!-- STRIPE payments: compute transactions + money flow -->
  <div class="wrap" style="padding:22px 22px 30px">
    <div class="lbl" style="margin-bottom:12px">Compute transactions (Stripe) <span class="mut" id="pay_sub"></span></div>
    <div class="panel" style="overflow:auto">
      <table class="tbl"><thead><tr><th>Tx</th><th>Status</th><th>Recon</th><th>Auth</th><th>Captured</th><th>Fee</th><th>Seller net</th><th>Transferred</th><th>Refunded</th></tr></thead>
      <tbody id="payrows"><tr><td colspan=9 class="mut mono" style="padding:18px;text-align:center">loading…</td></tr></tbody></table>
    </div>
    <p class="mini" style="margin-top:8px">Every amount is integer minor units. Buyer charge = platform fee + seller net; the Stripe processing fee is tracked separately.</p>
  </div>

  <!-- LANDING PAGE settings: the admin-editable video -->
  <div class="wrap" style="padding:22px 22px 30px">
    <div class="lbl" style="margin-bottom:12px">Landing page</div>
    <div class="card">
      <h2 style="font-size:16px;margin-bottom:4px">Homepage video</h2>
      <p class="mut" style="font-size:13px;margin-bottom:12px">Paste a YouTube link (a normal video or a Short) or just its id. It replaces the video on the landing page immediately. <b class="teal">Shorts sometimes refuse to embed (Error 153)</b> — if yours does, upload it as a normal video and pick Landscape.</p>
      <div class="filterbar" style="gap:8px">
        <input id="vid_in" placeholder="https://youtube.com/watch?v=… or a video id" style="flex:1;min-width:240px"/>
        <select id="vid_orient" style="min-width:150px">
          <option value="auto">Shape: auto-detect</option>
          <option value="landscape">Landscape (16:9)</option>
          <option value="portrait">Portrait (Short)</option>
        </select>
        <button class="btn btn-teal" onclick="saveVideo()">Save video</button>
      </div>
      <div id="vid_msg" class="mini" style="margin-top:10px"></div>
      <div id="vid_preview" style="max-width:220px;margin-top:14px;display:none">
        <div style="position:relative;padding-bottom:177.78%;height:0;border-radius:12px;overflow:hidden;border:1px solid var(--line2)">
          <iframe id="vid_frame" style="position:absolute;inset:0;width:100%;height:100%;border:0" allowfullscreen title="preview"></iframe>
        </div>
      </div>
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
  loadUsers();loadSpecs();loadPayouts();loadIncidents();loadPayments();loadVideo();
}
async function loadPayments(){
  var r=await api('/admin/payments');var tb=document.getElementById('payrows');
  if(!r.ok){tb.innerHTML='<tr><td colspan=9 class="mut mono" style="padding:18px;text-align:center">could not load</td></tr>';return;}
  var m2=function(x){return '$'+(Number(x||0)/100).toFixed(2);};
  var txs=r.body.transactions||[];
  document.getElementById('pay_sub').textContent='· '+txs.length+' shown';
  if(!txs.length){tb.innerHTML='<tr><td colspan=9 class="mut mono" style="padding:18px;text-align:center">No Stripe transactions yet.</td></tr>';return;}
  tb.innerHTML=txs.map(function(t){return '<tr><td class="mono" style="font-size:11px">'+t.transaction_id+'</td>'+
    '<td><span class="badge">'+t.status+'</span></td>'+
    '<td class="mini">'+(t.reconciliation_status||'')+'</td>'+
    '<td class="mono">'+m2(t.authorization_amount)+'</td>'+
    '<td class="mono">'+m2(t.captured_amount)+'</td>'+
    '<td class="mono">'+m2(t.platform_fee_amount)+'</td>'+
    '<td class="mono teal">'+m2(t.seller_net_amount)+'</td>'+
    '<td class="mono">'+m2(t.transferred_amount)+'</td>'+
    '<td class="mono '+(t.refunded_amount?'amber':'')+'">'+m2(t.refunded_amount)+'</td></tr>';}).join('');
}
async function loadIncidents(){
  var r=await api('/admin/incidents');var tb=document.getElementById('incrows');
  if(!r.ok){tb.innerHTML='<tr><td colspan=5 class="mut mono" style="padding:20px;text-align:center">could not load</td></tr>';return;}
  var b=r.body,rows=[];
  (b.stalled_bookings||[]).forEach(function(x){rows.push(['stalled booking','#'+x.booking_id+(x.node_online?'':' · node offline'),money(x.amount),(x.age_minutes||0)+'m',x.reason]);});
  (b.failed_jobs||[]).forEach(function(x){rows.push(['failed job','task #'+x.task_id,'—',(x.age_minutes||0)+'m',(x.reason||'').slice(0,80)]);});
  (b.failed_payouts||[]).forEach(function(x){rows.push(['failed payout','#'+x.payout_id,money(x.amount_usd),(x.age_minutes||0)+'m',x.reason]);});
  document.getElementById('inc_sub').textContent=b.counts?('· '+b.counts.stalled_bookings+' stalled · '+b.counts.failed_jobs+' failed jobs · '+b.counts.failed_payouts+' failed payouts'):'';
  if(!rows.length){tb.innerHTML='<tr><td colspan=5 class="mut mono" style="padding:20px;text-align:center">No incidents. Everything is settling normally.</td></tr>';return;}
  tb.innerHTML=rows.map(function(r){return '<tr><td><span class="badge">'+r[0]+'</span></td><td class="mono">'+r[1]+'</td><td class="mono amber">'+r[2]+'</td><td class="mono mut">'+r[3]+'</td><td class="mut" style="font-size:12.5px">'+r[4]+'</td></tr>';}).join('');
}
async function loadVideo(){
  try{var r=await fetch('/landing/video');if(!r.ok)return;var d=await r.json();
    if(d.video_id){document.getElementById('vid_in').value=d.video_id;
      if(d.orientation)document.getElementById('vid_orient').value=d.orientation;
      showVideoPreview(d.video_id, d.orientation);}}catch(e){}
}
function showVideoPreview(id, orient){
  var p=document.getElementById('vid_preview'),f=document.getElementById('vid_frame');
  var box=p.firstElementChild;
  box.style.paddingBottom=(orient==='landscape')?'56.25%':'177.78%';
  p.style.maxWidth=(orient==='landscape')?'320px':'220px';
  f.src='https://www.youtube.com/embed/'+id+'?rel=0&playsinline=1';p.style.display='';
}
async function saveVideo(){
  var m=document.getElementById('vid_msg');var v=(document.getElementById('vid_in').value||'').trim();
  if(!v){m.style.color='var(--warn)';m.textContent='Paste a YouTube link or id.';return;}
  m.style.color='';m.textContent='Saving…';
  var orient=document.getElementById('vid_orient').value;
  var payload={video:v}; if(orient!=='auto')payload.orientation=orient;
  var r=await api('/admin/landing/video',{method:'POST',body:JSON.stringify(payload)});
  if(r.ok){m.style.color='var(--pos)';m.textContent='Saved — '+r.body.orientation+' · id '+r.body.video_id;
    document.getElementById('vid_orient').value=r.body.orientation;showVideoPreview(r.body.video_id,r.body.orientation);}
  else{m.style.color='var(--warn)';m.textContent=(r.body&&r.body.error&&r.body.error.message)||'Could not save.';}
}
async function loadUsers(){var q=document.getElementById('uq').value;
  var r=await api('/admin/users'+(q?('?q='+encodeURIComponent(q)):''));var tb=document.getElementById('urows');
  if(!r.ok||!r.body.users.length){tb.innerHTML='<tr><td colspan=7 class="mut mono" style="padding:20px;text-align:center">No users.</td></tr>';return;}
  tb.innerHTML=r.body.users.map(function(u){var other=u.role==='seller'?'buyer':'seller';
    return '<tr><td style="font-family:var(--disp);font-weight:600">'+esc(u.username)+(u.is_admin?' <span class="badge cc">admin</span>':'')+'</td>'+
     '<td class="mut mono" style="font-size:12px">'+esc(u.email||'—')+'</td>'+
     '<td>'+(u.role==='seller'?'<span class="badge ok">seller</span>':'<span class="badge">buyer</span>')+'</td>'+
     '<td class="mono">'+u.reputation+'</td><td class="mono">'+money(u.balance)+'</td><td class="mono amber">'+money(u.earnings)+'</td>'+
     '<td><button class="btn-ghost" data-act="setRole" data-a1="'+esc(u.username)+'" data-a2="'+other+'">make '+other+'</button></td></tr>';}).join('');}
async function setRole(u,role){await api('/admin/users/'+encodeURIComponent(u)+'/role',{method:'POST',body:JSON.stringify({role:role})});loadUsers();}
async function loadSpecs(){var r=await api('/admin/specs');var tb=document.getElementById('srows');
  if(!r.ok||!r.body.specs.length){tb.innerHTML='<tr><td colspan=8 class="mut mono" style="padding:20px;text-align:center">No nodes.</td></tr>';return;}
  tb.innerHTML=r.body.specs.map(function(s){var t=[];if(s.confidential)t.push('<span class="badge cc">conf</span>');if(s.region_verified)t.push('<span class="badge ok">region ✓</span>');
    var st=s.status==='online'?'<span class="badge ok">online</span>':'<span class="badge">'+s.status+'</span>';
    return '<tr><td class="mono mut">'+s.id+'</td><td>'+esc(s.owner)+'</td>'+
     '<td data-l="GPU" style="font-family:var(--disp);font-weight:600">'+esc(s.gpu_model||'CPU')+'</td>'+
     '<td class="mono amber">$'+s.price_per_hour.toFixed(2)+'</td><td>'+st+'</td>'+
     '<td>'+(t.join(' ')||'<span class="mut mono" style="font-size:11px">standard</span>')+'</td>'+
     '<td class="mono">'+s.jobs_completed+'/'+s.jobs_failed+'</td>'+
     '<td>'+(s.status==='online'?'<button class="btn-ghost" onclick="delist('+s.id+')">delist</button>':'')+'</td></tr>';}).join('');}
async function delist(id){await api('/admin/specs/'+id+'/delist',{method:'POST'});loadSpecs();}
async function loadPayouts(){var r=await api('/admin/payouts');var tb=document.getElementById('prows');
  if(!r.ok||!r.body.payouts.length){tb.innerHTML='<tr><td colspan=5 class="mut mono" style="padding:20px;text-align:center">No pending payouts.</td></tr>';return;}
  tb.innerHTML=r.body.payouts.map(function(p){return '<tr><td class="mono mut">'+p.id+'</td><td>'+esc(p.user)+'</td>'+
    '<td class="mono amber">'+money(p.amount_usd)+'</td><td class="mono mut">'+p.kind+'</td>'+
    '<td class="mono mut" style="font-size:12px">'+(p.created_at?p.created_at.slice(0,10):'—')+'</td></tr>';}).join('');}
boot();
</script>""")


FUNDING_VIEW_HTML = _page("Petabyte — funding metrics", """
<div class="wrap" style="padding:48px 22px 8px">
  <div class="eyebrow"><span class="dot"></span> investor / founder</div>
  <h1 style="font-size:clamp(30px,5vw,40px);margin:16px 0 6px">Funding <span class="grad-teal">metrics</span></h1>
  <p class="mut">Computed live from authoritative database rows — never fabricated. Read-only, operators only.</p>
</div>
<div class="wrap" style="padding:8px 22px 8px">
  <div id="fsignin" class="card" style="display:none"><div class="lbl">Restricted</div>
    <p class="mut">Sign in with an operator account.</p>
    <div style="margin-top:14px"><a class="btn btn-amber" href="/auth/google/login">Sign in</a></div></div>
  <div id="fdenied" class="card" style="display:none;border-color:rgba(229,120,139,.4)">
    <div class="lbl" style="color:var(--bad)">Not authorized</div>
    <p class="mut">This account isn't a platform admin.</p></div>
</div>
<div id="fconsole" style="display:none">
  <div class="wrap" style="padding:4px 22px 4px">
    <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center">
      <button class="btn-ghost" id="sc_real" onclick="fload('real')">Real (LIVE money)</button>
      <button class="btn-ghost" id="sc_test" onclick="fload('test')">Test mode</button>
      <button class="btn-ghost" id="sc_demo" onclick="fload('demo')">Demo</button>
      <span class="mini mono" id="f_asof" style="margin-inline-start:auto"></span>
    </div>
    <div id="f_banner" class="card" style="display:none;margin-top:12px"></div>
    <div class="stats" style="margin-top:12px">
      <div class="stat"><div class="l">GMV (captured)</div><div class="n amber" id="f_gmv">—</div><div class="mini" id="f_netgmv"></div></div>
      <div class="stat"><div class="l">Net platform revenue</div><div class="n teal" id="f_net">—</div><div class="mini" id="f_take"></div></div>
      <div class="stat"><div class="l">Active buyers</div><div class="n" id="f_buyers">—</div><div class="mini" id="f_arpu"></div></div>
      <div class="stat"><div class="l">Active sellers / GPUs</div><div class="n" id="f_sellers">—</div><div class="mini" id="f_gpus"></div></div>
    </div>
    <div class="panel" style="margin-top:12px;padding:16px 18px;display:flex;flex-wrap:wrap;gap:26px">
      <div><span class="mini">Gross take rate</span><div class="mono teal" id="f_takeg" style="font-size:18px">—</div></div>
      <div><span class="mini">Job success</span><div class="mono" id="f_success" style="font-size:18px">—</div></div>
      <div><span class="mini">Refund rate</span><div class="mono" id="f_refund" style="font-size:18px">—</div></div>
      <div><span class="mini">Utilization</span><div class="mono" id="f_util" style="font-size:18px">—</div></div>
      <div><span class="mini">Fill rate</span><div class="mono" id="f_fill" style="font-size:18px">—</div></div>
      <div><span class="mini">Unfulfilled demand</span><div class="mono amber" id="f_unmet" style="font-size:18px">—</div></div>
    </div>
    <div class="panel" style="margin-top:12px;padding:16px 18px;display:flex;flex-wrap:wrap;gap:26px">
      <div><span class="mini">Seller liability (owed)</span><div class="mono amber" id="f_liab" style="font-size:18px">—</div></div>
      <div><span class="mini">Payouts paid</span><div class="mono" id="f_paid" style="font-size:18px">—</div></div>
      <div><span class="mini">Repeat-buyer rate</span><div class="mono teal" id="f_repeat" style="font-size:18px">—</div></div>
      <div><span class="mini">Retention 30d</span><div class="mono" id="f_ret30" style="font-size:18px">—</div></div>
      <div><span class="mini">Retention 90d</span><div class="mono" id="f_ret90" style="font-size:18px">—</div></div>
    </div>
    <p class="mini mut" id="f_note" style="margin:12px 2px 30px"></p>
  </div>
</div>
<script>
function fd(minor){if(minor===null||minor===undefined)return '—';return '$'+(minor/100).toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2});}
function fp(rate){if(rate===null||rate===undefined)return '—';return (rate*100).toFixed(1)+'%';}
function fnum(n){return (n===null||n===undefined)?'—':String(n);}
async function fboot(){
  if(!tok()){document.getElementById('fsignin').style.display='block';return;}
  var w=await api('/admin/whoami');
  if(!w.ok){document.getElementById(w.status===403?'fdenied':'fsignin').style.display='block';return;}
  document.getElementById('fconsole').style.display='block';fload('real');
}
async function fload(scope){
  ['real','test','demo'].forEach(function(s){var b=document.getElementById('sc_'+s);if(b)b.style.opacity=(s===scope?'1':'.55');});
  var r=await api('/admin/funding?scope='+scope);
  if(!r.ok)return;var b=r.body,m=b.money_minor,mk=b.marketplace,rt=b.rates,lq=b.liquidity,re=b.retention;
  document.getElementById('f_asof').textContent='scope: '+b.scope+'  ·  '+(b.as_of||'').slice(0,19).replace('T',' ')+'Z';
  var ban=document.getElementById('f_banner');
  if(scope==='real'&&!m.gmv_captured){ban.style.display='block';ban.style.borderColor='rgba(240,180,80,.5)';
    ban.innerHTML='<div class="lbl" style="color:var(--warn)">No real (LIVE) traction yet</div><p class="mut">The platform is in Stripe TEST mode, so REAL GMV is $0 by design — this is honest, not a bug. Use <b>Test mode</b> to see test-mode activity. TEST/demo figures are never shown as real traction.</p>';}
  else if(scope!=='real'){ban.style.display='block';ban.style.borderColor='rgba(240,180,80,.5)';
    ban.innerHTML='<div class="lbl" style="color:var(--warn)">'+(scope==='demo'?'DEMO data':'TEST-mode data')+' — not real traction</div><p class="mut">These figures are '+(scope==='demo'?'seeded demo':'Stripe TEST-mode')+' activity, shown for verification only.</p>';}
  else{ban.style.display='none';}
  document.getElementById('f_gmv').textContent=fd(m.gmv_captured);
  document.getElementById('f_netgmv').textContent='net of refunds '+fd(m.net_gmv);
  document.getElementById('f_net').textContent=fd(m.net_platform_revenue);
  document.getElementById('f_take').textContent='net take '+fp(rt.take_rate_net);
  document.getElementById('f_buyers').textContent=fnum(mk.active_buyers);
  document.getElementById('f_arpu').textContent='ARPU '+fd(mk.arpu_minor);
  document.getElementById('f_sellers').textContent=fnum(mk.active_sellers);
  document.getElementById('f_gpus').textContent=fnum(mk.active_gpus_online)+' GPUs online';
  document.getElementById('f_takeg').textContent=fp(rt.take_rate_gross);
  document.getElementById('f_success').textContent=fp(rt.job_success_rate);
  document.getElementById('f_refund').textContent=fp(rt.refund_rate);
  document.getElementById('f_util').textContent=fp(lq.utilization);
  document.getElementById('f_fill').textContent=fp(lq.fill_rate);
  document.getElementById('f_unmet').textContent=fnum(lq.unfulfilled_demand);
  document.getElementById('f_liab').textContent=fd(m.seller_liability_outstanding);
  document.getElementById('f_paid').textContent=fd(m.payouts_paid);
  document.getElementById('f_repeat').textContent=fp(re.repeat_buyer_rate);
  document.getElementById('f_ret30').textContent=fp(re.buyer_retention_30d);
  document.getElementById('f_ret90').textContent=fp(re.buyer_retention_90d);
  document.getElementById('f_note').textContent=b.note;
}
fboot();
</script>""")


LOGIN_HTML = _page("Petabyte — sign in", """
<div class="wrap" style="max-width:440px;padding:60px 22px 40px">
  <div class="eyebrow"><span class="dot"></span> <span id="eyebrow">account</span></div>
  <h1 style="font-size:clamp(28px,5vw,36px);margin:16px 0 6px"><span id="title">Sign in</span></h1>
  <p class="mut" id="subtitle">Welcome back. Sign in to book compute or manage your nodes.</p>

  <div class="card" style="margin-top:20px">
    <label class="mini" for="u" style="display:block;margin-bottom:6px">Username</label>
    <input id="u" placeholder="username" style="width:100%" autocomplete="username"/>
    <label class="mini" for="p" style="display:block;margin:14px 0 6px">Password</label>
    <input id="p" type="password" placeholder="password (8+ characters)" style="width:100%" autocomplete="current-password"
           onkeydown="if(event.key==='Enter')go()"/>
    <button class="btn-amber" style="width:100%;justify-content:center;margin-top:18px" onclick="go()">
      <span id="btn">Sign in</span>
    </button>
    <p id="err" class="mut" style="display:none;color:var(--bad);margin-top:12px;font-size:13px"></p>

    <p id="forgotrow" style="text-align:right;margin-top:10px;font-size:12px">
      <a class="teal" href="#" onclick="forgot();return false" id="forgotlink">Forgot password?</a>
    </p>

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
function fail(m){var e=document.getElementById('err');e.textContent=m;e.style.color='var(--bad)';e.style.display='';}
function info(m){var e=document.getElementById('err');e.textContent=m;e.style.color='var(--mut)';e.style.display='';}
async function forgot(){
  var id=document.getElementById('u').value.trim();
  if(!id){ id=(prompt("Enter your account email or username to reset your password:")||"").trim(); }
  if(!id){ return; }
  try{
    await fetch('/password/forgot',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({identifier:id})});
  }catch(e){}
  info("If an account matches, we've emailed a password reset link. Check your inbox.");
}
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
      var _ref=null;try{_ref=localStorage.getItem('pb_ref')}catch(e){}
      var rr=await fetch('/register_user',{method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify(_ref?{username:u,password:p,ref:_ref}:{username:u,password:p})});
      if(rr.ok){try{localStorage.removeItem('pb_ref')}catch(e){}}
      if(!rr.ok){var b={};try{b=await rr.json()}catch(e){}
        if(rr.status===422){fail("Username must be 3–64 characters and password at least 8.");}
        else if(rr.status===429||rr.status===503){fail("Too many attempts — wait a moment and try again.");}
        else{fail((typeof b.detail==='string'?b.detail:null)||"That username is taken — try another."); }
        return;}
    }
    var t=await login(u,p);
    if(!t){fail(mode==="register"?"Account created — but sign-in failed. Try signing in.":"Wrong username or password."); return;}
    localStorage.setItem('pb_token', t);document.documentElement.setAttribute('data-auth','in');
    location.href='/app';
  }catch(e){fail("Network error — check your connection and try again.");}
}
</script>""")


RESET_HTML = _page("Petabyte — reset password", """
<div class="wrap" style="max-width:440px;padding:60px 22px 40px">
  <div class="eyebrow"><span class="dot"></span> <span>account</span></div>
  <h1 style="font-size:clamp(28px,5vw,36px);margin:16px 0 6px">Choose a new password</h1>
  <p class="mut">Enter a new password for your Petabyte account.</p>

  <div class="card" style="margin-top:20px" id="form">
    <label class="mini" style="display:block;margin-bottom:6px">New password</label>
    <input id="p1" type="password" placeholder="new password (8+ characters)" style="width:100%" autocomplete="new-password"/>
    <label class="mini" style="display:block;margin:14px 0 6px">Confirm password</label>
    <input id="p2" type="password" placeholder="re-enter new password" style="width:100%" autocomplete="new-password"
           onkeydown="if(event.key==='Enter')reset()"/>
    <button class="btn-amber" style="width:100%;justify-content:center;margin-top:18px" onclick="reset()">
      <span>Update password</span>
    </button>
    <p id="err" class="mut" style="display:none;color:var(--bad);margin-top:12px;font-size:13px"></p>
  </div>

  <div class="card" style="margin-top:20px;display:none" id="done">
    <p style="margin:0">Your password has been updated.</p>
    <a class="btn btn-amber" style="width:100%;justify-content:center;margin-top:16px" href="/login">Sign in</a>
  </div>
</div>
<script>
function tok(){ return new URLSearchParams(location.search).get('token')||''; }
function fail(m){var e=document.getElementById('err');e.textContent=m;e.style.display='';}
async function reset(){
  var p1=document.getElementById('p1').value, p2=document.getElementById('p2').value;
  if(p1.length<8){fail("Password must be at least 8 characters."); return;}
  if(p1!==p2){fail("Passwords do not match."); return;}
  var t=tok();
  if(!t){fail("This reset link is missing its token. Request a new link from the sign-in page."); return;}
  document.getElementById('err').style.display='none';
  try{
    var r=await fetch('/password/reset',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({token:t,new_password:p1})});
    if(r.ok){
      document.getElementById('form').style.display='none';
      document.getElementById('done').style.display='';
      return;
    }
    var b={};try{b=await r.json()}catch(e){}
    fail((typeof b.detail==='string'?b.detail:null)||"This reset link is invalid or has expired.");
  }catch(e){fail("Network error — check your connection and try again.");}
}
</script>""")


ACCOUNT_HTML = _page("Petabyte — your account", """
<div id="guest" class="wrap" style="max-width:460px;padding:70px 22px;text-align:center">
  <img src="/static/petabyte-logo.png" alt="Petabyte" style="width:56px;opacity:.8"/>
  <h1 style="font-size:28px;margin:18px 0 8px">Your account</h1>
  <p class="mut">Sign in to see your nodes, jobs, keys, and wallet in one place.</p>
  <div style="margin-top:18px"><a class="btn btn-amber" href="/login">Sign in</a></div>
</div>

<div id="hub" style="display:none">
  <!-- onboarding: what do I do next? -->
  <div class="wrap" id="onbsection" style="padding:22px 22px 0;display:none">
    <div class="card">
      <div style="display:flex;align-items:center;justify-content:space-between;gap:14px;flex-wrap:wrap">
        <div>
          <div class="lbl" id="onblbl">Getting started</div>
          <h2 style="font-size:18px" id="onbnext">—</h2>
          <p class="mut" style="font-size:13px;margin-top:2px" id="onbdetail"></p>
        </div>
        <div style="text-align:end;flex:none">
          <div class="mono teal" style="font-size:24px;font-weight:700" id="onbpct">0%</div>
          <div class="mini" id="onbcount"></div>
        </div>
      </div>
      <div style="height:6px;background:var(--hair);border-radius:999px;margin:14px 0 12px;overflow:hidden">
        <div id="onbbar" style="height:100%;width:0%;background:linear-gradient(90deg,var(--teal),var(--amber));transition:width .5s"></div>
      </div>
      <div id="onbsteps" style="display:flex;flex-direction:column;gap:2px"></div>
    </div>
  </div>

  <!-- EMAIL VERIFICATION — required before payouts, and how we reach you at 2am -->
  <div class="wrap" id="emailsection" style="padding:20px 22px 0;display:none">
    <div class="card" style="border-color:rgba(255,178,36,.4)">
      <div class="lbl am">Action needed</div>
      <h2 style="font-size:17px;margin-bottom:5px">Verify your email</h2>
      <p class="mut" style="font-size:13px;margin-bottom:12px">Required before you can be paid out — and it's how we reach you if your node has a problem.</p>
      <div class="filterbar">
        <label class="field" style="flex:1;min-width:220px"><span>Email</span>
          <input id="emailin" type="email" placeholder="you@example.com"/></label>
        <button class="btn btn-amber" onclick="sendVerify()">Send link</button>
      </div>
      <div id="emailtok" style="display:none;margin-top:12px">
        <div class="filterbar">
          <label class="field" style="flex:1;min-width:220px"><span>Paste the code from your email</span>
            <input id="emailcode" placeholder="verification code"/></label>
          <button class="btn btn-teal" onclick="confirmVerify()">Verify</button>
        </div>
      </div>
      <div id="emailmsg" class="mini" style="margin-top:10px"></div>
    </div>
  </div>

  <!-- NOTIFICATIONS — you have a whole notification system; show it -->
  <div class="wrap" id="notifsection" style="padding:20px 22px 0;display:none">
    <div style="display:flex;align-items:center;gap:10px;margin-bottom:10px">
      <div class="lbl" style="margin:0">Activity</div>
      <span class="badge ok" id="notifcount"></span>
    </div>
    <div class="panel" id="notiflist" style="padding:4px 16px"></div>
  </div>

  <!-- what is burning money RIGHT NOW -->
  <div class="wrap" id="burnsection" style="padding:20px 22px 0;display:none">
    <div class="stats">
      <div class="stat"><div class="l">Balance</div><div class="n mono" id="b_bal">—</div></div>
      <div class="stat"><div class="l">Burning now</div><div class="n mono amber" id="b_burn">—</div></div>
      <div class="stat"><div class="l">Next 24h</div><div class="n mono" id="b_24">—</div></div>
      <div class="stat"><div class="l">Runway</div><div class="n mono teal" id="b_run">—</div></div>
    </div>
    <p class="mut" style="font-size:12.5px;margin-top:8px" id="b_note"></p>
  </div>

  <!-- seller diagnostics: WHY am I not earning? -->
  <div class="wrap" id="diagsection" style="padding:20px 22px 0;display:none">
    <div class="lbl am">Your nodes</div>
    <div id="diagblockers" style="display:flex;flex-direction:column;gap:10px;margin-bottom:14px"></div>
    <div class="panel" style="overflow:auto">
      <table class="tbl"><thead><tr><th>GPU</th><th>Status</th><th>$/hr</th><th>Utilization</th><th>Jobs</th><th>Rep</th><th>Earned</th></tr></thead>
      <tbody id="diagrows"></tbody></table>
    </div>
  </div>

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
          <button id="roleswitch" class="btn btn-teal" onclick="switchRole()" aria-label="Switch your role" style="display:none;padding:6px 14px;font-size:12.5px"></button>
          <span id="rolemsg" class="mini" style="color:var(--bad)"></span>
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
          <input id="amt" type="number" aria-label="Amount to add (USD)" value="50" min="1" size="5" style="width:90px"/>
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
        <input id="klabel" aria-label="API key label" placeholder="label · my-node" size="16"/>
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
  // Self-service role switch: sellers lead with earnings, buyers with cheap compute.
  var rs=document.getElementById('roleswitch');
  if(rs){
    var target=(u.role==='seller')?'buyer':'seller';
    rs.textContent=(u.role==='seller')?'Switch to buying':'Become a seller — earn from your GPU';
    rs.setAttribute('aria-label',(u.role==='seller')?'Switch your role to buyer':'Switch your role to seller');
    rs.dataset.target=target;
    rs.style.display='';
  }
  if(u.is_admin)document.getElementById('adminbadge').style.display='';
  document.getElementById('rep').textContent=u.reputation;
  document.getElementById('bal').textContent=money(u.balance);
  document.getElementById('earn').textContent=money(u.earnings);
  document.getElementById('nnodes').textContent=u.nodes;
  document.getElementById('njobs').textContent=u.bookings;
  document.getElementById('wbal').textContent=money(u.balance);
  document.getElementById('wearn').textContent=money(u.earnings);
  if(new URLSearchParams(location.search).get('funded')==='1'){
    wmsg('Payment received — your balance updates as soon as Stripe confirms.');}
  loadNodes();loadJobs();loadKeys();loadMethods();loadTemplates();loadVMs();loadEarnings();loadOnboarding();loadDiagnostics();loadBurn();loadEmail();loadNotifs();setInterval(loadBurn,20000);
}
async function loadVMs(){var r=await api('/vm');if(!r.ok)return;var vms=r.body.vms||[];
  if(!vms.length)return; document.getElementById('vmsection').style.display='';
  document.getElementById('vmrows').innerHTML=vms.map(function(v){
    var live=(v.status==='running'||v.status==='starting'||v.status==='migrating');
    var act='<button class="btn-ghost" style="padding:4px 10px;font-size:11px" data-act="vmEvents" data-a1="'+v.vm_id+'">Timeline</button>'+(live?(' '+'<button class="btn-ghost" style="padding:4px 10px;font-size:11px" data-act="vmExtend" data-a1="'+v.vm_id+'">+1h</button> <button class="btn-ghost" style="padding:4px 10px;font-size:11px" data-act="vmStop" data-a1="'+v.vm_id+'">Stop</button>'):'');
    return '<tr><td class="mono" style="font-size:11px">vm-'+v.vm_id+'</td><td style="text-transform:capitalize">'+(v.template||'')+'</td>'+
      '<td><span class="badge '+(v.status==='running'?'ok':'')+'">'+v.status+'</span></td>'+
      '<td class="mono amber">$'+Number(v.hourly_rate||0).toFixed(2)+'</td>'+
      '<td class="mono">'+(v.hours_left||0)+'h</td><td>'+act+'</td></tr>';}).join('');}
// --- VM EVENT TIMELINE. The backend records created -> tunnel_registered ->
// migrated -> tunnel_registered. That timeline IS the failover proof — the single
// most convincing thing we can show a buyer — and it was never displayed.
async function vmEvents(id){
  var r=await api('/vm/'+id+'/events'); if(!r.ok)return;
  var evs=r.body.events||[];
  var d=document.createElement('div');
  d.style.cssText='position:fixed;inset:0;z-index:200;background:rgba(3,7,17,.72);backdrop-filter:blur(6px);display:flex;align-items:center;justify-content:center;padding:20px';
  var label={'created':'Instance created','tunnel_registered':'Reachable through the tunnel',
             'migrated':'Host failed — moved to another node','stopped':'Stopped',
             'expired':'Prepaid window ended','extended':'Extended'};
  d.innerHTML='<div style="width:min(520px,94vw);background:var(--panel);border:1px solid var(--line2);border-radius:16px;padding:22px">'+
    '<div class="lbl">Timeline</div><h2 style="font-size:17px;margin-bottom:14px">'+id+'</h2>'+
    (evs.length?evs.map(function(e,i){
      var mig=e.event==='migrated';
      return '<div style="display:flex;gap:12px;align-items:flex-start;padding:9px 0">'+
        '<div style="display:flex;flex-direction:column;align-items:center;flex:none">'+
          '<span style="width:9px;height:9px;border-radius:50%;background:'+(mig?'var(--warn)':'var(--teal)')+'"></span>'+
          (i<evs.length-1?'<span style="width:1px;flex:1;min-height:20px;background:var(--line2)"></span>':'')+
        '</div><div style="flex:1"><div style="font-size:13.5px;font-family:var(--disp);font-weight:600;'+(mig?'color:var(--warn)':'')+'">'+
        (label[e.event]||e.event)+'</div>'+
        (e.detail?'<div class="mut" style="font-size:12px">'+e.detail+'</div>':'')+
        '<div class="mini">'+(e.at||'').replace('T',' ').slice(0,19)+'</div></div></div>';}).join('')
      :'<div class="mut" style="font-size:13px">No events yet.</div>')+
    '<div style="margin-top:14px;text-align:end"><button class="btn btn-ghost" data-act="pbCloseModal">Close</button></div></div>';
  d.addEventListener('click',function(e){if(e.target===d)d.remove();});
  document.body.appendChild(d);
}
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
    return '<tr><td style="font-family:var(--disp);font-weight:600">'+esc(s.gpu_model)+'</td>'+
      '<td class="mono">'+s.busy+'/'+s.units+'</td><td class="mono amber">$'+Number(s.price_per_hour||0).toFixed(2)+'</td>'+
      '<td>'+pr+'</td><td class="mono">'+s.reputation+'</td><td class="mono mut">'+s.jobs_completed+'✓ '+s.jobs_failed+'✗</td></tr>';}).join('');}
async function loadNodes(){var r=await api('/account/specs');var tb=document.getElementById('noderows');
  if(!r.ok||!r.body.specs.length){tb.innerHTML='<tr><td colspan=7 class="mut mono" style="padding:20px;text-align:center">No nodes yet — <a class="teal" href="/install">list one</a>.</td></tr>';return;}
  tb.innerHTML=r.body.specs.map(function(s){var t=[];if(s.attested)t.push('<span class="badge ok">attested</span>');if(s.confidential)t.push('<span class="badge cc">conf</span>');
   return '<tr><td class="mono mut">'+s.id+'</td><td style="font-family:var(--disp);font-weight:600">'+esc(s.gpu_model||'CPU')+'</td>'+
   '<td class="mono amber">$'+s.price_per_hour.toFixed(2)+'</td><td>'+(s.status==='online'?'<span class="badge ok">online</span>':'<span class="badge">'+esc(s.status)+'</span>')+'</td>'+
   '<td>'+(t.join(' ')||'—')+'</td><td class="mut mono" style="font-size:12px">'+esc(s.region||'—')+'</td><td class="mono">'+s.jobs_completed+'/'+s.jobs_failed+'</td></tr>';}).join('');}
async function loadJobs(){var r=await api('/account/bookings');var tb=document.getElementById('jobrows');
  if(!r.ok||!r.body.bookings.length){tb.innerHTML='<tr><td colspan=7 class="mut mono" style="padding:20px;text-align:center">No jobs yet — <a class="teal" href="/marketplace">rent a GPU</a>.</td></tr>';return;}
  tb.innerHTML=r.body.bookings.map(function(b){return '<tr><td class="mono mut">'+b.id+'</td><td>'+(b.role==='buyer'?'<span class="badge">bought</span>':'<span class="badge ok">sold</span>')+'</td>'+
   '<td style="font-family:var(--disp);font-weight:600">'+esc(b.gpu_model)+'</td><td class="mono">'+b.hours+'h</td><td class="mono amber">'+money(b.gross_amount)+'</td>'+
   '<td><span class="badge">'+esc(b.status)+'</span></td><td class="mut mono" style="font-size:12px">'+(b.created_at?b.created_at.slice(0,10):'—')+'</td></tr>';}).join('');}
async function loadKeys(){var r=await api('/account/keys');var tb=document.getElementById('keyrows');
  if(!r.ok||!r.body.keys||!r.body.keys.length){tb.innerHTML='<tr><td colspan=5 class="mut mono" style="padding:18px;text-align:center">No keys yet.</td></tr>';return;}
  tb.innerHTML=r.body.keys.map(function(k){return '<tr><td>'+esc(k.label||'—')+'</td><td class="mono mut">'+esc(k.scopes||'—')+'</td>'+
   '<td class="mono mut" style="font-size:11px">'+k.expires_at.slice(0,10)+'</td>'+
   '<td>'+(k.revoked?'<span class="badge">revoked</span>':'<span class="badge ok">active</span>')+'</td>'+
   '<td>'+(k.revoked?'':'<button class="btn-ghost" data-act="rvkey" data-a1="'+k.jti+'">revoke</button>')+'</td></tr>';}).join('');}
async function mkkey(){var lb=document.getElementById('klabel').value;var q=new URLSearchParams({days:'90'});if(lb)q.set('label',lb);
  var r=await api('/create_api_key?'+q.toString(),{method:'POST'});var el=document.getElementById('knew');el.style.display='';
  el.textContent=r.ok?('Copy now — shown once:\\n\\n'+r.body.api_key):'Could not create key.';loadKeys();}
async function rvkey(j){await api('/keys/'+j+'/revoke',{method:'POST'});loadKeys();}
async function deposit(){var a=parseFloat(document.getElementById('amt').value||'0');
  if(!(a>0)){wmsg('Enter an amount.');return;}
  // Open Stripe's hosted card page for a wallet top-up (test or live per config).
  var r=await api('/wallet/topup',{method:'POST',body:JSON.stringify({amount_minor:Math.round(a*100)})});
  if(r.ok && r.body.checkout_url){
    wmsg((r.body.test_mode?'Test mode — ':'')+'Redirecting to secure Stripe checkout…');
    location.href=r.body.checkout_url;
  } else if(r.status===400){ wmsg((r.body&&r.body.detail)?r.body.detail:'Enter a valid amount.'); }
  else { wmsg('Could not start checkout — please try again.'); }}
async function withdraw(){var a=parseFloat(document.getElementById('amt').value||'0');
  var r=await api('/wallet/withdraw',{method:'POST',body:JSON.stringify({amount:a})});
  wmsg(r.ok?('Withdrawal of '+money(a)+' requested.'):(r.body&&r.body.detail?r.body.detail:'Add a payout method first.'));loadMethods();}
async function loadMethods(){var r=await api('/wallet/methods');var el=document.getElementById('methods');
  if(r.ok&&r.body.methods&&r.body.methods.length){el.innerHTML='Payout methods: '+r.body.methods.map(function(m){return '<span class="badge ok">'+(m.kind||m.type||'method')+'</span>';}).join(' ');}
  else{el.innerHTML='No payout method yet — add bank / USDC / gift card in the <a class="teal" href="/app">dashboard</a> to withdraw.';}}
async function loadTemplates(){renderLaunch('launchgrid',['ai','render','art','game'],2);}

// --- ROLE SWITCH: a signed-in user can move between buying and selling. ---
async function switchRole(){
  var btn=document.getElementById('roleswitch');
  if(!btn){return;}
  var target=btn.dataset.target;
  var msg=document.getElementById('rolemsg');
  if(msg){msg.textContent='';}
  btn.disabled=true;
  var r=await api('/change_role',{method:'POST',body:JSON.stringify({role:target})});
  if(r.ok){
    location.href=(target==='seller')?'/install':'/marketplace';   // land where the new role is useful
  }else{
    btn.disabled=false;
    if(msg){msg.textContent=(r.body&&r.body.detail)?r.body.detail:'Could not switch role — please try again.';}
  }
}

// --- ONBOARDING: what do I do next? Buyers and hosts get different funnels. ---
async function loadOnboarding(){
  var r=await api('/onboarding'); if(!r.ok)return; var o=r.body;
  if(o.percent>=100){document.getElementById('onbsection').style.display='none';return;}
  document.getElementById('onbsection').style.display='';
  document.getElementById('onblbl').textContent = o.role==='host'?'Getting paid':'Getting started';
  document.getElementById('onbpct').textContent = o.percent+'%';
  document.getElementById('onbcount').textContent = o.completed+' of '+o.total+' done';
  document.getElementById('onbbar').style.width = o.percent+'%';
  if(o.next_step){
    document.getElementById('onbnext').textContent = o.next_step.title;
    document.getElementById('onbdetail').textContent = o.next_step.detail;
  }
  document.getElementById('onbsteps').innerHTML = o.steps.map(function(s,i){
    var isNext = o.next_step && s.key===o.next_step.key;
    return '<div style="display:flex;align-items:center;gap:11px;padding:8px 0;border-bottom:1px solid var(--hair);'+(isNext?'':'opacity:.62')+'">'+
      (s.done
        ? '<span style="width:20px;height:20px;border-radius:50%;background:rgba(74,222,156,.15);border:1px solid var(--pos);color:var(--pos);display:inline-flex;align-items:center;justify-content:center;font-size:11px;flex:none">✓</span>'
        : '<span style="width:20px;height:20px;border-radius:50%;border:1px solid '+(isNext?'var(--teal)':'var(--line2)')+';flex:none"></span>')+
      '<span style="flex:1;font-size:13.5px;'+(s.done?'text-decoration:line-through;color:var(--dim)':'')+'">'+s.title+'</span>'+
      (!s.done&&isNext?'<a class="btn btn-teal" style="padding:5px 13px;font-size:12px" href="'+s.action+'">Do it</a>':'')+
      '</div>';}).join('');
}

// --- EMAIL VERIFICATION. Without this the onboarding checklist is a dead end:
// it says "verify your email" and there is nowhere to do it — while verification
// gates every payout.
async function loadEmail(){
  var r=await api('/me'); if(!r.ok)return;
  if(r.body.email_verified){document.getElementById('emailsection').style.display='none';return;}
  document.getElementById('emailsection').style.display='';
  if(r.body.email) document.getElementById('emailin').value=r.body.email;
}
async function sendVerify(){
  var e=document.getElementById('emailin').value.trim();
  var m=document.getElementById('emailmsg');
  if(!e){m.textContent='Enter an email address.';return;}
  m.textContent='Sending…';
  var r=await api('/email/verify/request',{method:'POST',body:JSON.stringify({email:e})});
  if(!r.ok){m.textContent=(r.body&&r.body.error&&r.body.error.message)||'Could not send the link.';return;}
  document.getElementById('emailtok').style.display='';
  m.textContent='Check your inbox. The link expires in '+(r.body.expires_in_minutes||15)+' minutes.';
  if(r.body.debug_token){document.getElementById('emailcode').value=r.body.debug_token;m.textContent+=' (sandbox: code filled in for you)';}
}
async function confirmVerify(){
  var t=document.getElementById('emailcode').value.trim();
  var m=document.getElementById('emailmsg');
  var r=await api('/email/verify/confirm',{method:'POST',body:JSON.stringify({token:t})});
  if(!r.ok){m.textContent=(r.body&&r.body.error&&r.body.error.message)||'That code is invalid or expired.';return;}
  m.textContent='Verified.';
  document.getElementById('emailsection').style.display='none';
  loadOnboarding();
}

// --- NOTIFICATIONS. The backend has emitted these all along (payout requested/
// confirmed/failed, node offline, refunds) and the app never showed a single one.
async function loadNotifs(){
  var r=await api('/notifications'); if(!r.ok)return;
  var ns=(r.body.notifications||[]).slice(0,12);
  if(!ns.length)return;
  document.getElementById('notifsection').style.display='';
  document.getElementById('notifcount').textContent=ns.length+' recent';
  var icon={'payout.requested':'↑','payout.confirmed':'✓','payout.failed':'!',
            'booking.refunded':'↩','job.completed':'✓','node.offline':'!',
            'payout_method.added':'⚠','email.verify':'✉'};
  document.getElementById('notiflist').innerHTML=ns.map(function(n){
    var bad=(n.event_type||'').indexOf('failed')>=0||(n.event_type||'').indexOf('offline')>=0||(n.event_type||'')==='payout_method.added';
    return '<div style="display:flex;gap:12px;align-items:flex-start;padding:11px 0;border-bottom:1px solid var(--hair)">'+
      '<span class="mono" style="width:20px;flex:none;color:'+(bad?'var(--warn)':'var(--teal)')+'">'+(icon[n.event_type]||'•')+'</span>'+
      '<div style="flex:1;min-width:0">'+
        '<div style="font-size:13.5px;font-family:var(--disp);font-weight:600">'+(n.subject||n.event_type)+'</div>'+
        '<div class="mut" style="font-size:12.5px">'+(n.body||'')+'</div></div>'+
      '<span class="mini" style="flex:none">'+(n.status||'')+'</span></div>';}).join('');
}

// --- BURN RATE: the number a buyer actually wants is not "balance", it's
// "what is costing me money right now, even while I'm not looking".
async function loadBurn(){
  var r=await api('/buyer/spend'); if(!r.ok)return; var b=r.body;
  if(!b.active_instances && !(Number(b.spent_lifetime)>0)) return;
  document.getElementById('burnsection').style.display='';
  var money=function(x){return '$'+Number(x||0).toFixed(2);};
  document.getElementById('b_bal').textContent=money(b.balance);
  document.getElementById('b_burn').textContent=money(b.burn_rate_per_hour)+'/hr';
  document.getElementById('b_24').textContent=money(b.projected_24h);
  document.getElementById('b_run').textContent=(b.hours_of_runway!=null?b.hours_of_runway+'h':'—');
  document.getElementById('b_note').textContent=
    b.active_instances
      ? b.active_instances+' instance'+(b.active_instances===1?'':'s')+' running. '+
        money(b.in_escrow)+' is held in escrow and refunded for hours you do not use.'
      : 'Nothing running. '+money(b.spent_lifetime)+' spent to date.';
}

// --- SELLER DIAGNOSTICS: "my GPU is on, why am I earning nothing?" ---
async function loadDiagnostics(){
  var r=await api('/seller/dashboard'); if(!r.ok)return; var d=r.body;
  if(!d.nodes||!d.nodes.length)return;
  document.getElementById('diagsection').style.display='';
  document.getElementById('diagblockers').innerHTML=(d.blockers||[]).map(function(b){
    return '<div class="card" style="padding:14px 16px;border-color:rgba(255,178,36,.35)">'+
      '<div style="font-family:var(--disp);font-weight:600;font-size:13.5px;color:var(--amber)">'+b.issue+'</div>'+
      '<div class="mut" style="font-size:12.5px;margin-top:3px">'+b.fix+'</div></div>';}).join('')
    || '<div class="mut mono" style="font-size:12px">No blockers — your nodes are visible and priced competitively. If you are still not earning, it is demand, not you.</div>';
  document.getElementById('diagrows').innerHTML=d.nodes.map(function(n){
    return '<tr>'+
      '<td data-l="GPU" style="font-family:var(--disp);font-weight:600">'+(n.gpu_model||'CPU')+'</td>'+
      '<td data-l="Status">'+(n.online?'<span class="badge ok">online</span>':'<span class="badge">offline</span>')+
        (n.attested?'':' <span class="badge cc">unverified</span>')+'</td>'+
      '<td data-l="$/hr" class="mono amber">$'+Number(n.price_per_hour).toFixed(2)+'</td>'+
      '<td data-l="Utilization"><div style="display:flex;align-items:center;gap:7px">'+
        '<div style="flex:1;height:5px;background:var(--hair);border-radius:999px;overflow:hidden;min-width:44px">'+
        '<div style="height:100%;width:'+n.utilization_pct+'%;background:var(--teal)"></div></div>'+
        '<span class="mono mini">'+n.utilization_pct+'%</span></div></td>'+
      '<td data-l="Jobs" class="mono">'+n.jobs_completed+(n.jobs_failed?' <span style="color:var(--bad)">/'+n.jobs_failed+'</span>':'')+'</td>'+
      '<td data-l="Rep" class="mono">'+(n.reputation!=null?n.reputation:'—')+'</td>'+
      '<td data-l="Earned" class="mono teal">$'+Number(n.earned_total).toFixed(2)+'</td></tr>';}).join('');
}
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
   return '<tr style="cursor:pointer" data-act="pbGoGpu" data-a1="'+s.id+'">'+
    '<td data-l="GPU"><div style="font-family:var(--disp);font-weight:600">'+(s.gpu_count>1?s.gpu_count+'× ':'')+esc(s.gpu_model||'CPU')+'</div>'+
      '<div class="mini" style="margin-top:2px">'+(s.cpu?s.cpu+' vCPU':'')+(s.ram_gb?' · '+s.ram_gb+'GB RAM':'')+'</div></td>'+
    '<td data-l="VRAM" class="mono mut">'+(s.vram_gb?s.vram_gb+' GB':'—')+'</td>'+
    '<td data-l="$/hr"><div class="mono amber" style="font-weight:600">$'+s.price_per_hour.toFixed(2)+'</div>'+
      (s.auto_price?'<span class="badge cc" style="font-size:9px">auto</span>':'')+'</td>'+
    '<td class="mono" style="color:var(--pos)">'+(save>0?'−'+save+'%':'—')+'</td>'+
    '<td data-l="Trust">'+(s.trust?'<span class="badge '+(s.trust.rank>=2?'ok':'')+'" title="'+s.trust.evidence+'">'+s.trust.label+'</span>':(s.attested?'<span class="badge ok">verified</span>':'<span class="badge">unverified</span>'))+
      (s.confidential?' <span class="badge cc" title="Confidential-computing pilot — vendor TEE verification not yet connected">CC pilot</span>':'')+'</td>'+
    '<td data-l="Region" class="mut mono" style="font-size:12px">'+esc(s.region||'—')+(s.region_verified?' <span class="teal">✓</span>':'')+'</td>'+
    '<td data-l="Reputation" class="mono" style="color:'+rc+'">'+(s.reputation_score!=null?s.reputation_score:'—')+
      '<div class="mini">'+(s.success_rate!=null?s.success_rate+'% ok':'no history')+'</div></td>'+
    '<td data-l="Available"><span class="badge '+(s.available_units>0?'ok':'')+'">'+(s.available_units>0?s.available_units+' free':'busy')+'</span></td>'+
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
   return '<tr><td style="font-family:var(--disp);font-weight:600">'+esc(s.gpu_model||'CPU')+'</td>'+
    '<td class="mono mut" style="font-size:12px">'+(s.vram_gb?s.vram_gb+'GB':'—')+'</td>'+
    '<td class="mono amber">$'+s.price_per_hour.toFixed(2)+'</td><td class="mut mono" style="font-size:12px">'+esc(s.region||'—')+'</td>'+
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
function row(k,v){return '<div style="display:flex;justify-content:space-between;gap:16px;padding:9px 0;border-bottom:1px solid var(--hair)"><span class="mut" style="font-size:13px">'+k+'</span><span class="mono" style="font-size:13px;text-align:end">'+v+'</span></div>';}
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
    '<h1 style="font-size:clamp(28px,4vw,40px);margin-bottom:8px">'+(s.gpu_count>1?s.gpu_count+'× ':'')+esc(s.gpu_model)+'</h1>'+
    '<div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:20px">'+status+
      (s.trust?'<span class="badge '+(s.trust.rank>=2?'ok':'')+'" title="'+s.trust.evidence+'">'+s.trust.label+'</span>':'')+
      (s.confidential?'<span class="badge cc" title="Confidential-computing pilot — vendor TEE verification not yet connected">CC pilot</span>':'')+
      (s.region_verified?'<span class="badge ok">Region verified</span>':'')+'</div>'+
    '<div class="card" style="margin-bottom:16px">'+
     '<div class="lbl">Specifications</div>'+
     row('GPU',(s.gpu_count>1?s.gpu_count+'× ':'')+esc(s.gpu_model))+
     row('VRAM',s.vram_gb?s.vram_gb+' GB':'—')+
     row('vCPU',s.cpu||'—')+
     row('System RAM',s.ram_gb?s.ram_gb+' GB':'—')+
     row('Region',esc(s.region||'unknown')+(s.region_verified?' (verified)':' (host-reported)'))+
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
     '<p class="mut" style="font-size:13px;margin-bottom:8px"><b>'+(s.trust?s.trust.label:'Self-reported')+':</b> '+(s.trust?s.trust.evidence:'')+' '+s.verification.method+'. The agent reports CPU, RAM, and GPU model, and signs the report with a key held on the machine — so the listing cannot be silently altered in transit.</p>'+
     '<p class="mut" style="font-size:13px;margin-bottom:8px">'+(s.verification.limits||'')+'</p>'+
     '<p class="mut" style="font-size:13px">'+(s.confidential?'This host reports support for confidential computing (pilot verifier — not vendor-attested).':'This host does not advertise confidential computing.')+' Region is '+(s.region_verified?'checked against the host network address.':'self-reported by the host and not independently checked.')+'</p>'+
    '</div>'+
   '</div>'+
   '<div style="flex:1 1 280px;min-width:260px;position:sticky;top:88px">'+
    '<div class="card">'+
     '<div style="display:flex;align-items:baseline;gap:8px">'+
      '<span class="mono amber" style="font-size:34px;font-weight:700">$'+Number(s.price_per_hour).toFixed(2)+'</span><span class="mut">/hour</span></div>'+
     (s.savings_pct?'<div class="mini" style="color:var(--pos);margin-top:4px">'+s.savings_pct+'% below the on-demand cloud rate for this GPU class ($'+Number(s.cloud_reference).toFixed(2)+'/hr)</div>':'<div class="mini" style="margin-top:4px">No comparable public cloud rate for this GPU — we don\'t quote a saving we can\'t back up.</div>')+
     (s.auto_price?'<div class="mini" style="margin-top:6px"><span class="badge cc">auto-priced</span> moves with demand, within the host\\'s limits</div>':'')+
     '<div style="margin-top:16px">'+
      (bookable?'<button class="btn btn-amber" style="width:100%;justify-content:center" data-act="pbBuy" data-a1="'+SPEC_ID+'">Rent &amp; run on this GPU →</button>':'<button class="btn btn-ghost" style="width:100%;justify-content:center" disabled>Not bookable right now</button>')+
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


PRICING_HTML = _page("Petabyte — pricing",
    desc="Live GPU prices per hour, compared against comparable public cloud rates. You prepay into escrow and are refunded for unused hours.", path="/pricing", body="""
<div class="hero"><div class="wrap" style="padding:60px 24px 18px">
  <div class="eyebrow"><span class="dot"></span> <span data-ar="الأسعار">pricing</span></div>
  <h1 style="font-size:clamp(34px,5vw,54px);margin:16px 0 12px" data-ar="ادفع مقابل الساعات التي تستخدمها فعلاً.">Pay for the hours <span class="grad">you actually use.</span></h1>
  <p class="mut" style="font-size:16px;max-width:58ch" data-ar="يحدّد المضيفون أسعارهم بأنفسهم، لذا تختلف الأسعار حسب الكرت والتوفّر. تُحاسَب على المدة التي تحتجز فيها الجهاز — أوقف مبكراً ويُعاد إليك المبلغ غير المستخدم.">Hosts set their own prices, so rates vary by GPU and availability. You are billed for the time you hold the machine — stop early and the unused prepay is refunded.</p>
</div></div>

<div class="wrap" style="padding:26px 24px 8px">
  <div class="lbl" data-ar="أسعار مباشرة">Live prices</div>
  <div class="panel" style="overflow:auto">
    <table class="tbl">
      <thead><tr><th data-ar="الكرت">GPU</th><th data-ar="الذاكرة">VRAM</th><th>Petabyte</th><th data-ar="مرجع السحابة">Cloud reference</th><th data-ar="توفيرك">You save</th><th data-ar="المنطقة">Region</th><th></th></tr></thead>
      <tbody id="prows"><tr><td colspan=7 class="mut mono" style="padding:22px;text-align:center">Loading live prices…</td></tr></tbody>
    </table>
  </div>
  <p class="mut" style="font-size:12.5px;margin-top:10px" data-ar="يحدّد كل مضيف أسعاره، وتتغيّر مع الطلب والتوفّر. «مرجع السحابة» هو سعر عند الطلب من مزوّد سحابي كبير لفئة كرت مماثلة، يُستخدم كمعيار للمقارنة — وليس عرض سعر من أي مزوّد بعينه.">Prices are set by individual hosts and change with demand and availability. "Cloud reference" is an on-demand hyperscaler rate for a comparable GPU class, used as a benchmark — not a quote from any specific provider.</p>
</div>

<div class="wrap" style="padding:34px 24px 8px"><div class="cols c3">
  <div class="card"><div class="lbl" data-ar="كيف تعمل الفوترة">How billing works</div>
    <h2 style="font-size:17px;margin-bottom:8px" data-ar="بالساعة، مع استرداد">Hourly, with refunds</h2>
    <p class="mut" style="font-size:13px" data-ar="تدفع مقدّماً لمدة معيّنة. عند الإيقاف نحاسبك على الساعات التي احتجزتها (ساعة واحدة كحد أدنى) ونعيد الباقي إلى محفظتك. يمكنك التمديد في أي وقت.">You prepay for a window. When you stop, we bill the hours you held (minimum one) and refund the rest to your wallet. Extend at any time.</p></div>
  <div class="card"><div class="lbl" data-ar="رسوم المنصة">Platform fee</div>
    <h2 style="font-size:17px;margin-bottom:8px" data-ar="١٠٪ على الإيجارات المكتملة">10% on completed rentals</h2>
    <p class="mut" style="font-size:13px" data-ar="تُقتطع من الإيجار، لا تُضاف فوقه. يرى المضيفون صافي أرباحهم بدقّة قبل الإدراج.">Taken from the rental, not added on top. Hosts see their exact payout before they list.</p></div>
  <div class="card"><div class="lbl am" data-ar="مدفوعات المضيفين">Host payouts</div>
    <h2 style="font-size:17px;margin-bottom:8px" data-ar="اسحب متى شئت">Withdraw when you want</h2>
    <p class="mut" style="font-size:13px" data-ar="تتراكم الأرباح مع كل إيجار مكتمل، ويمكن سحبها عند الطلب أو وفق جدول أسبوعي.">Earnings accrue per completed rental and can be withdrawn on demand or on a weekly schedule.</p></div>
</div></div>
<script>
async function prices(){
 var r=await fetch('/marketplace/specs?sort=price');var b=await r.json();var tb=document.getElementById('prows');
 if(!b.count){tb.innerHTML=pbEmpty(7,'No GPUs listed yet','Prices appear here as hosts come online.','/install','List your GPU');return;}
 tb.innerHTML=b.specs.map(function(s){
  var save=(s.cloud_reference&&s.price_per_hour<s.cloud_reference)?Math.round((1-s.price_per_hour/s.cloud_reference)*100):0;
  return '<tr>'+
   '<td data-l="GPU" style="font-family:var(--disp);font-weight:600">'+esc(s.gpu_model||'CPU')+'</td>'+
   '<td data-l="VRAM" class="mono mut">'+(s.vram_gb?s.vram_gb+' GB':'—')+'</td>'+
   '<td data-l="Petabyte" class="mono amber" style="font-weight:600">$'+Number(s.price_per_hour).toFixed(2)+'/hr</td>'+
   '<td data-l="Cloud" class="mono mut">'+(s.cloud_reference?'$'+Number(s.cloud_reference).toFixed(2)+'/hr':'<span class="mini">no comparable rate</span>')+'</td>'+
   '<td data-l="You save" class="mono" style="color:var(--pos)">'+(save>0?save+'%':'—')+'</td>'+
   '<td data-l="Region" class="mut mono" style="font-size:12px">'+esc(s.region||'—')+'</td>'+
   '<td data-l="" class="tbl-action"><a class="btn btn-teal" style="padding:6px 14px;font-size:12px" href="/gpu/'+s.id+'">View</a></td></tr>';}).join('');
}
prices();setInterval(prices,10000);
</script>""")


SECURITY_HTML = _page("Petabyte — security &amp; trust",
    desc="How Petabyte isolates workloads, verifies hardware, protects host networks, and holds buyer funds in escrow.", path="/security", body="""
<div class="hero"><div class="wrap" style="padding:60px 24px 18px">
  <div class="eyebrow"><span class="dot"></span> <span data-ar="الأمان والثقة">security &amp; trust</span></div>
  <h1 style="font-size:clamp(34px,5vw,54px);margin:16px 0 12px" data-ar="ما نتحقّق منه، وما لا نتحقّق منه.">What we verify, <span class="grad">and what we don't.</span></h1>
  <p class="mut" style="font-size:16px;max-width:62ch" data-ar="استئجار القدرة الحوسبية من غرباء لا ينجح إلا إذا عرف الطرفان بالضبط ما هو مضمون. هذه هي النسخة الصادقة — بما في ذلك الأجزاء التي ما زلنا نبنيها.">Renting compute from strangers only works if both sides know exactly what is guaranteed. Here is the honest version — including the parts we are still building.</p>
</div></div>

<div class="wrap" style="padding:26px 24px 8px"><div class="cols c2">
  <div class="card"><div class="lbl" data-ar="التحقّق من العتاد">Hardware verification</div>
    <h2 style="font-size:18px;margin-bottom:8px" data-ar="تقارير عتاد موقّعة">Signed hardware reports</h2>
    <p class="mut" style="font-size:13.5px" data-ar="عند تثبيت المضيف للوكيل، يُنشئ زوج مفاتيح على الجهاز ويوقّع تقريراً بمعالجه وذاكرته وطراز كرت رسوماته. نتحقّق من هذا التوقيع قبل السماح بإدراج الكرت، بحيث لا يمكن تزوير الإدراج أو تعديله أثناء النقل.">When a host installs the agent, it generates a keypair on the machine and signs a report of its CPU, RAM, and GPU model. We verify that signature before the GPU can be listed, so a listing cannot be forged or altered in transit.</p>
    <p class="mut" style="font-size:13.5px;margin-top:10px" data-ar="ما هذا ليس: إنه ليس جذر ثقة عتادياً. يستطيع مضيف مصرّ أن يبلّغ عن عتاد لا يملكه. السمعة المبنية على المهام المكتملة هي الإشارة الأقوى، وتظهر على كل إدراج."><b class="teal">What this is not:</b> it is not a hardware root of trust. A determined host could still report hardware it does not have. Reputation from completed jobs is the stronger signal, and it is shown on every listing.</p>
  </div>
  <div class="card"><div class="lbl" data-ar="عزل الأعباء">Workload isolation</div>
    <h2 style="font-size:18px;margin-bottom:8px" data-ar="تعمل المهام داخل حاويات">Jobs run in containers</h2>
    <p class="mut" style="font-size:13.5px" data-ar="يعمل عبء عملك داخل حاوية Docker على جهاز المضيف، مع إسقاط الصلاحيات، وحدٍّ للعمليات، وسقفٍ للذاكرة. وحيث يكون gVisor مثبّتاً لدى المضيف، نشغّل الحاوية تحت نواة في فضاء المستخدم لحدٍّ أقوى بين مهمتك وجهازه.">Your workload runs in a Docker container on the host, with privileges dropped, a process limit, and a memory cap. Where the host has gVisor installed, we run the container under a user-space kernel for a stronger boundary between your job and their machine.</p>
    <p class="mut" style="font-size:13.5px;margin-top:10px" data-ar="ما هذا ليس: الحاويات ليست حدّاً عتادياً. لا تضع على أي جهاز بياناتٍ لا تحتمل أن يراها المضيف. للأعمال الحسّاسة، استخدم مضيفاً يعلن عن الحوسبة السرّية، أو لا تستخدم بنية تحتية مشتركة."><b class="teal">What this is not:</b> containers are not a hardware boundary. Do not put data on a node that you could not tolerate the host seeing. For sensitive work, use a host that advertises confidential computing, or don't use shared infrastructure.</p>
  </div>
  <div class="card"><div class="lbl" data-ar="حماية المدفوعات">Payment protection</div>
    <h2 style="font-size:18px;margin-bottom:8px" data-ar="ضمان تحتفظ به Petabyte">Escrow, held by Petabyte</h2>
    <p class="mut" style="font-size:13.5px" data-ar="عند الحجز، يخرج المبلغ من محفظتك وتحتفظ به Petabyte طوال مدة الإيجار. يُدفع للمضيف عند الإكمال؛ وتأخذ المنصة ١٠٪ من الإيجار. هذا سجلّ داخلي، وليس ضماناً على البلوكتشين — Petabyte هي الحافظة.">When you book, the money leaves your wallet and is held by Petabyte for the rental. The host is paid on completion; the platform takes 10% of the rental. This is an internal ledger, not an on-chain escrow — Petabyte is the custodian.</p>
    <p class="mut" style="font-size:13.5px;margin-top:10px" data-ar="أوقف مبكراً فتُحاسَب فقط على الساعات التي احتجزت فيها الجهاز (ساعة واحدة كحد أدنى). ويعود المبلغ غير المستخدم إلى محفظتك.">Stop early and you are billed only for the hours you held the machine (minimum one). The unused prepay returns to your wallet.</p>
  </div>
  <div class="card"><div class="lbl" data-ar="عند اختفاء جهاز">When a node disappears</div>
    <h2 style="font-size:18px;margin-bottom:8px" data-ar="نقل تلقائي، أو استرداد">Failover, or refund</h2>
    <p class="mut" style="font-size:13.5px" data-ar="يرسل المضيفون نبضة حياة. فإن صمت أحدهم، ننقل جهازك إلى جهاز مؤهّل آخر — دون تغيّر العنوان الذي تتصل به — ونستعيد من أحدث لقطة. وإن لم يستطع أي جهاز استلامه، يُسترَد الإيجار.">Hosts send a heartbeat. If one goes quiet, we move your machine to another eligible node — the address you connect to does not change — and restore from the most recent snapshot. If no node can take it, the rental is refunded.</p>
    <p class="mut" style="font-size:13.5px;margin-top:10px" data-ar="انتبه: الاستعادة تكون من آخر نقطة حفظ، لا من نسخة حيّة متزامنة. النقل التلقائي يعني إعادة التشغيل من لقطة، وليس انعدام فقدان البيانات."><b class="teal">Be aware:</b> recovery is from the last checkpoint, not a live mirror. A failover means restarting from a snapshot, not zero data loss.</p>
  </div>
</div></div>

<div class="wrap" style="padding:22px 24px 8px">
  <div class="card">
    <div class="lbl am" data-ar="قيد البناء">Still building</div>
    <h2 style="font-size:18px;margin-bottom:10px" data-ar="ادّعاءات لا نطلقها بعد">Claims we are not making yet</h2>
    <p class="mut" style="font-size:13.5px" data-ar="نفضّل أن نكون موثوقين لا مبهرين. هذه في خارطة الطريق وهي ليست فعّالة اليوم:">We would rather be trusted than impressive. These are on the roadmap and are <b>not</b> live today:</p>
    <ul class="mut" style="font-size:13.5px;margin:10px 0 0 20px">
      <li style="padding:3px 0" data-ar="إثبات مدعوم عتادياً (SEV-SNP / TDX). الإثبات اليوم موقّع برمجياً من الوكيل.">Hardware-backed attestation (SEV-SNP / TDX). Today's attestation is software-signed by the agent.</li>
      <li style="padding:3px 0" data-ar="تحقّق مستقل من الأداء المُعلَن عبر قياسات معيارية.">Independent benchmark verification of advertised performance.</li>
      <li style="padding:3px 0" data-ar="تدقيق أمني خارجي منشور أو تقرير SOC 2.">A published external security audit or SOC 2 report.</li>
      <li style="padding:3px 0" data-ar="ضمانات رسمية لموقع تخزين البيانات. المنطقة مُبلّغ عنها من المضيف ما لم تُوسم بأنها موثّقة.">Formal data-residency guarantees. Region is host-reported unless marked verified.</li>
    </ul>
    <p class="mut" style="font-size:13px;margin-top:12px" data-ar="إن كان أي ادّعاء مهمّاً لعبء عملك، اسألنا قبل الحجز —">If a claim matters for your workload, ask us before you book — <a class="teal" href="mailto:info@petabyte.market">info@petabyte.market</a>.</p>
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
    Questions: <a class="teal" href="mailto:info@petabyte.market">info@petabyte.market</a>.
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
<p class="mut">Financial records are kept as required for accounting. Other data is kept while your account is open. You can request a copy of your data or ask us to delete your account by emailing <a class="teal" href="mailto:info@petabyte.market">info@petabyte.market</a>.</p>
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
<h2 """ + _LEGAL_H + """>Company</h2>
<p class="mut">Petabyte is operated by <b>Petabyte, Inc.</b>, a C-corporation incorporated in the State of Delaware, United States, with operations in Riyadh, Saudi Arabia. For legal notices, contracts, or verification of the entity during due diligence, write to <a class="teal" href="mailto:info@petabyte.market">info@petabyte.market</a>.</p>
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
<p class="mut">We may suspend a rental or an account, withhold settlement, and where required report to authorities. Report abuse to <a class="teal" href="mailto:info@petabyte.market">info@petabyte.market</a> — include the VM address or node id if you have it.</p>
""")


STATUS_HTML = _page("Petabyte — status",
    desc="Live platform status and component health.", path="/status", body="""
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


SELLER_EARNINGS_HTML = _page("Petabyte — seller earnings",
    desc="Connect your Stripe account to receive payouts, and track compute earnings, commission, transfers and bank payouts.",
    path="/seller/payouts", body="""
<div class="wrap" style="padding:52px 24px 8px;max-width:900px">
  <div class="eyebrow"><span class="dot"></span> seller earnings</div>
  <h1 style="font-size:clamp(28px,4.4vw,42px);margin:14px 0 8px">Get paid for your compute</h1>
  <div class="earn-banner" role="status" style="max-width:660px">
    <span>You keep <b>90%</b> of every job</span>
    <span class="sub">Withdraw anytime — bank, USDC, or gift card. A GPU starts earning the moment it is online and verified.</span>
  </div>
  <p class="mut" id="signedout" style="display:none">Please <a class="teal" href="/login">sign in</a> to set up payouts.</p>

  <div id="setup" style="display:none">
    <div class="card" style="margin-top:16px">
      <div class="lbl">Your GPUs</div>
      <p class="mini" style="margin:6px 0 12px">A GPU earns once it is <b>online</b> and <b>verified</b> — then it is visible to buyers and can take paid jobs.</p>
      <div id="nodes_box"><div class="mut mono" style="padding:8px 0">loading…</div></div>
      <div id="nodes_blockers"></div>
    </div>

    <div class="card" style="margin-top:16px">
      <div class="lbl">Stripe payout account</div>
      <div id="stripe_state" class="mut mono" style="padding:10px 0">Checking…</div>
      <div id="stripe_why" class="mini" style="color:var(--warn);margin-bottom:10px"></div>
      <div style="display:flex;gap:10px;flex-wrap:wrap">
        <button class="btn btn-teal" id="btn_connect" data-act="scConnect" style="display:none">Connect Stripe account</button>
        <button class="btn btn-amber" id="btn_onboard" data-act="scOnboard" style="display:none">Continue Stripe onboarding →</button>
        <button class="btn btn-ghost" id="btn_refresh" data-act="scRefresh" style="display:none">Refresh status</button>
      </div>
      <div id="stripe_detail" class="mini" style="margin-top:12px"></div>
    </div>

    <div class="card" style="margin-top:16px">
      <div class="lbl">Earnings (Stripe compute jobs)</div>
      <div class="stats" id="earn_stats" style="margin-top:10px"></div>
      <p class="mini" style="margin-top:8px">A <b>transfer</b> moves funds to your Stripe balance; a <b>bank payout</b> is Stripe paying your bank on its own schedule — these are different events.</p>
      <div class="panel" style="overflow:auto;margin-top:12px">
        <table class="tbl"><thead><tr><th>Transaction</th><th>Status</th><th>Captured</th><th>Your net</th><th>Transferred</th></tr></thead>
        <tbody id="earn_rows"><tr><td colspan=5 class="mut mono" style="padding:18px;text-align:center">loading…</td></tr></tbody></table>
      </div>
    </div>
  </div>
</div>
<script>
function m2(x){return '$'+(Number(x||0)/100).toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2});}
async function scLoad(){
  if(!authed()){document.getElementById('signedout').style.display='';return;}
  document.getElementById('setup').style.display='';
  var r=await api('/payments/connect/status');var st=r.body;
  var el=document.getElementById('stripe_state'),why=document.getElementById('stripe_why');
  var bC=document.getElementById('btn_connect'),bO=document.getElementById('btn_onboard'),bR=document.getElementById('btn_refresh');
  bC.style.display=bO.style.display=bR.style.display='none';
  if(!st.connected){el.textContent='Not connected.';why.textContent=st.why_blocked||'';bC.style.display='';}
  else{
    el.innerHTML='State: <b class="'+(st.payout_ready?'teal':'amber')+'">'+st.onboarding_state+'</b>'+(st.payout_ready?' — payouts enabled ✓':'');
    why.textContent=st.payout_ready?'':(st.why_blocked||'');
    bR.style.display='';
    if(!st.payout_ready)bO.style.display='';
    document.getElementById('stripe_detail').innerHTML=
      'account '+(st.connected_account_id||'')+' · country '+(st.country||'?')+' · '+
      'charges '+(st.charges_enabled?'✓':'✗')+' · payouts '+(st.payouts_enabled?'✓':'✗')+
      ' · transfers '+(st.transfers_capability||'?')+
      (st.requirements_due&&st.requirements_due.length?(' · needs: '+st.requirements_due.join(', ')):'');
  }
  var e=await api('/seller/earnings/stripe');var b=e.body;
  document.getElementById('earn_stats').innerHTML=
    '<div class="stat"><div class="n teal">'+m2(b.gross_compute_minor)+'</div><div class="l">Gross compute</div></div>'+
    '<div class="stat"><div class="n">'+m2(b.platform_commission_minor)+'</div><div class="l">Petabyte commission</div></div>'+
    '<div class="stat"><div class="n teal">'+m2(b.net_earnings_minor)+'</div><div class="l">Net earnings</div></div>'+
    '<div class="stat"><div class="n">'+m2(b.transferred_minor)+'</div><div class="l">Transferred</div></div>'+
    '<div class="stat"><div class="n amber">'+m2(b.transfers_pending_minor)+'</div><div class="l">Transfers pending</div></div>';
  var tb=document.getElementById('earn_rows');var js=b.jobs||[];
  tb.innerHTML=js.length?js.map(function(j){return '<tr><td class="mono">'+j.transaction_id+'</td><td><span class="badge">'+j.status+'</span></td><td class="mono">'+m2(j.captured)+'</td><td class="mono teal">'+m2(j.net)+'</td><td class="mono">'+m2(j.transferred)+(j.stripe_transfer_id?'':'')+'</td></tr>';}).join(''):'<tr><td colspan=5 class="mut mono" style="padding:18px;text-align:center">No paid jobs yet.</td></tr>';
}
async function scConnect(){var r=await api('/payments/connect/account',{method:'POST',body:'{}'});if(r.ok)scOnboard();else alert('Could not create account');}
async function scOnboard(){var r=await api('/payments/connect/onboarding-link',{method:'POST',body:'{}'});if(r.ok&&r.body.url)location.href=r.body.url;else alert('Could not start onboarding');}
async function scRefresh(){await api('/payments/connect/refresh',{method:'POST',body:'{}'});scLoad();}
// Your GPUs: online/verified -> visible to buyers -> earning. Answers "my GPU is on,
// why is nothing running?" with the actual blocker, not a zero.
async function scNodes(){
  var r=await api('/seller/dashboard');if(!r.ok)return;var b=r.body;var box=document.getElementById('nodes_box');
  var ns=b.nodes||[];
  if(!ns.length){box.innerHTML='<p class="mut" style="font-size:13px">No GPUs listed yet. <a class="teal" href="/install">List your hardware →</a></p>';}
  else{
    box.innerHTML=ns.map(function(n){
      var visible=n.online&&n.attested;
      function chip(ok,on,off){return '<span class="badge '+(ok?'ok':'')+'">'+(ok?on:off)+'</span>';}
      return '<div class="panel" style="padding:12px;margin-bottom:10px">'+
        '<div style="display:flex;justify-content:space-between;gap:10px;flex-wrap:wrap;align-items:center">'+
          '<b class="mono">'+(n.gpu_model||'GPU')+'</b>'+
          '<div style="display:flex;gap:6px;flex-wrap:wrap">'+
            chip(n.online,'online','offline')+
            chip(n.attested,'verified','unverified')+
            chip(visible,'visible to buyers','hidden')+
          '</div>'+
        '</div>'+
        '<div class="mini" style="margin-top:8px">$'+Number(n.price_per_hour).toFixed(2)+'/hr · '+
          (n.utilization_pct||0)+'% utilized · '+n.jobs_completed+' jobs done'+
          (n.success_rate!=null?(' · '+n.success_rate+'% success'):'')+' · earned $'+Number(n.earned_total||0).toFixed(2)+'</div>'+
      '</div>';}).join('');
  }
  var bl=b.blockers||[];var wb=document.getElementById('nodes_blockers');
  wb.innerHTML=bl.length?('<div class="lbl" style="margin-top:6px">To start earning</div>'+bl.map(function(x){
    return '<p class="mini" style="color:var(--warn);margin-top:6px">• '+(x.issue||'')+' <span class="mut">'+(x.fix||'')+'</span></p>';}).join('')):'';
}
scLoad();scNodes();
</script>""")


DEFAULT_WORKLOAD = ("import torch\\n"
 "print('cuda available:', torch.cuda.is_available())\\n"
 "if torch.cuda.is_available():\\n"
 "    print('gpu:', torch.cuda.get_device_name(0))\\n"
 "    x = torch.randn(4096, 4096, device='cuda')\\n"
 "    y = (x @ x).mean()\\n"
 "    torch.cuda.synchronize()\\n"
 "    print('matmul mean:', float(y))\\n"
 "else:\\n"
 "    print('no CUDA device visible')\\n")


BUY_HTML = _page("Petabyte — rent & run on a GPU",
    desc="Rent a verified GPU by the hour and run your workload from the browser. Pay by card; charged only for the GPU time you actually use.",
    path="/buy", body="""
<div class="wrap" style="padding:34px 24px 44px;max-width:960px">
  <a class="mini" href="/marketplace" style="color:var(--mut)">← Back to marketplace</a>
  <p class="mut" id="buy_signedout" style="display:none;margin-top:18px">Please <a class="teal" href="/login">sign in</a> to rent a GPU.</p>
  <div id="buywrap" style="margin-top:14px"><div class="mut mono" style="padding:40px 0">Loading GPU…</div></div>
</div>
<script>
var SPEC_ID=location.pathname.split('/').pop();
var CFG={gateway:'fake',test_mode:true,publishable_key:''};
var GPU=null,TX=null,SECRET=null,TASKID=null,QUOTE=null,POLL=null,STRIPE=null,CARDEL=null,PHASE='idle';
var DEFAULT_CODE=\"""" + DEFAULT_WORKLOAD + """\";

function el(id){return document.getElementById(id);}
function m2(x){return '$'+(Number(x||0)/100).toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2});}
function esc(s){return String(s==null?'':s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}
function row2(k,v){return '<div style="display:flex;justify-content:space-between;gap:16px;padding:8px 0;border-bottom:1px solid var(--hair)"><span class="mut" style="font-size:13px">'+k+'</span><span class="mono" style="font-size:13px;text-align:end">'+v+'</span></div>';}

// Buyer-facing labels — the primary message NEVER exposes a raw state-machine name.
var FRIENDLY={
 'DRAFT':'Starting…','PAYMENT_REQUIRES_ACTION':'Waiting for card confirmation…',
 'PAYMENT_AUTHORIZED':'Card authorized — reserving your GPU…',
 'GPU_RESERVED':'GPU reserved — sending your workload…',
 'DISPATCHING':'Sending your workload to the GPU…',
 'RUNNING':'Running on the GPU…',
 'METERING_FINALIZED':'Measuring exactly what you used…',
 'PAYMENT_CAPTURE_PENDING':'Finalizing your charge…',
 'PAYMENT_CAPTURED':'Done — charged for actual usage.',
 'SELLER_TRANSFER_PENDING':'Done — charged for actual usage.',
 'SELLER_TRANSFERRED':'Done — charged for actual usage.','COMPLETED':'Done — charged for actual usage.'};
var SETTLED={'PAYMENT_CAPTURED':1,'SELLER_TRANSFER_PENDING':1,'SELLER_TRANSFERRED':1,'COMPLETED':1};
var FAILED={'PAYMENT_FAILED':1,'AUTHORIZATION_EXPIRED':1,'RESERVATION_FAILED':1,'DISPATCH_FAILED':1,
 'JOB_FAILED':1,'CAPTURE_FAILED':1,'TRANSFER_FAILED':1,'CANCELLED':1,'REFUNDED':1,
 'REFUND_PENDING':1,'DISPUTED':1};
var STEPS=[['pay','Card authorized'],['reserve','GPU reserved'],['run','Workload ran on the GPU'],['charge','Charged for actual usage']];

function setMsg(t){var m=el('buy_msg');if(m)m.textContent=t;}
function renderSteps(done){done=done||{};var s=el('buy_steps');if(!s)return;
 s.innerHTML=STEPS.map(function(p){var ok=done[p[0]];
  return '<div style="display:flex;gap:8px;align-items:center;padding:3px 0">'+
   '<span style="color:'+(ok?'var(--teal)':'var(--mut)')+'">'+(ok?'✓':'○')+'</span>'+
   '<span class="'+(ok?'':'mut')+'" style="font-size:13px">'+p[1]+'</span></div>';}).join('');}

async function loadBuy(){
 if(typeof authed==='function'&&!authed()){el('buy_signedout').style.display='';el('buywrap').style.display='none';return;}
 var c=await api('/payments/config');if(c.ok)CFG=c.body;
 var r=await fetch('/marketplace/specs/'+SPEC_ID);var w=el('buywrap');
 if(!r.ok){w.innerHTML='<div class="empty"><div class="et">GPU not found</div><div class="es">It may have gone offline or been delisted.</div><a class="btn btn-teal" href="/marketplace">Browse available GPUs</a></div>';return;}
 GPU=await r.json();renderShell(GPU);
}

function renderShell(s){
 var bookable=s.online&&s.available_units>0&&s.can_accept_paid_jobs;
 var mode=CFG.gateway==='fake'?'Sandbox mode — no card needed for this test run.':(CFG.test_mode?'Stripe TEST mode — use card 4242 4242 4242 4242, any future date, any CVC. No real money moves.':'Live payment.');
 el('buywrap').innerHTML=
  '<h1 style="font-size:clamp(24px,3.4vw,34px);margin:6px 0 4px">Rent '+(s.gpu_count>1?s.gpu_count+'× ':'')+esc(s.gpu_model)+'</h1>'+
  '<p class="mut" style="margin-bottom:18px;max-width:60ch">Pay by card. You are authorized up to a maximum and charged only for the GPU time you actually use — the rest of the hold is released automatically.</p>'+
  '<div class="cols" style="gap:18px;align-items:flex-start">'+
   '<div style="flex:1.25 1 360px;min-width:300px">'+
    '<div class="card">'+
     '<div class="lbl">This GPU</div>'+
     row2('Model',(s.gpu_count>1?s.gpu_count+'× ':'')+esc(s.gpu_model))+
     row2('VRAM',s.vram_gb?s.vram_gb+' GB':'—')+
     row2('Price','$'+Number(s.price_per_hour).toFixed(2)+' /hour')+
     row2('Capacity',s.available_units+' of '+s.total_units+' free')+
     (bookable?'':'<p class="mini" style="color:var(--warn);margin-top:8px">This GPU is not bookable right now (offline, full, or the host is not payout-ready).</p>')+
    '</div>'+
    '<div class="card" style="margin-top:16px">'+
     '<div class="lbl">Your workload</div>'+
     '<label class="mini" style="display:block;margin-top:10px">Max runtime (hours)</label>'+
     '<input id="buy_hours" type="number" min="1" max="24" value="1" style="width:120px;padding:9px;margin-top:4px"/>'+
     '<label class="mini" style="display:block;margin-top:12px">Code to run on the GPU</label>'+
     '<textarea id="buy_code" rows="9" class="mono" style="width:100%;margin-top:4px;padding:10px;font-size:12.5px">'+esc(DEFAULT_CODE)+'</textarea>'+
     '<div id="card-row" style="display:none;margin-top:14px">'+
       '<label class="mini" style="display:block">Card details</label>'+
       '<div id="card-element" style="padding:12px;border:1px solid var(--line);border-radius:8px;margin-top:4px"></div>'+
       '<div id="card-errors" class="mini" style="color:var(--warn);margin-top:6px"></div>'+
     '</div>'+
     '<button class="btn btn-amber" id="buy_pay" data-act="buyRun" style="width:100%;margin-top:16px"'+(bookable?'':' disabled')+'>Rent &amp; run →</button>'+
     '<button class="btn btn-ghost" id="buy_cancel" data-act="buyCancel" style="width:100%;margin-top:8px;display:none">Cancel &amp; release</button>'+
     '<p class="mini" id="buy_note" style="margin-top:10px">'+mode+'</p>'+
    '</div>'+
   '</div>'+
   '<div style="flex:1 1 320px;min-width:280px">'+
    '<div class="card" id="buy_progress" style="display:none">'+
     '<div class="lbl">Progress</div>'+
     '<div id="buy_msg" style="font-family:var(--disp);font-size:16px;margin:10px 0">Starting…</div>'+
     '<div id="buy_steps" class="mini"></div>'+
    '</div>'+
    '<div class="card" id="buy_result" style="display:none;margin-top:16px">'+
     '<div class="lbl">Result &amp; receipt</div>'+
     '<div id="buy_result_body" style="margin-top:8px"></div>'+
    '</div>'+
    '<div class="card" id="buy_error" style="display:none;margin-top:16px">'+
     '<div class="lbl" style="color:var(--warn)">Heads up</div>'+
     '<div id="buy_error_body" class="mut" style="font-size:13px;margin-top:6px"></div>'+
    '</div>'+
   '</div>'+
  '</div>';
}

function showError(msg){el('buy_error').style.display='';el('buy_error_body').textContent=msg;}
function fail(msg){var b=el('buy_pay');if(b){b.disabled=false;b.style.display='';}showError(msg);setMsg('Stopped.');PHASE='idle';return null;}

async function buyRun(){
 if(PHASE==='awaiting_card')return realConfirm();
 if(PHASE!=='idle')return;
 PHASE='pricing';
 el('buy_error').style.display='none';el('buy_pay').disabled=true;
 el('buy_progress').style.display='';setMsg('Getting a price…');renderSteps({});
 var hours=Math.max(1,Math.min(24,parseInt((el('buy_hours').value||'1'),10)||1));
 var secs=hours*3600;
 var q=await api('/payments/quote',{method:'POST',body:JSON.stringify({spec_id:SPEC_ID,estimated_seconds:secs})});
 if(!q.ok)return fail(q.status===409?'This GPU can’t take paid jobs right now.':'Could not price this job.');
 QUOTE=q.body;
 if(!QUOTE.seller_payout_ready)return fail('This host isn’t set up to receive payouts yet, so it can’t take paid jobs.');
 setMsg('Authorizing your card for up to '+m2(QUOTE.authorization_amount)+'…');
 var a=await api('/payments/authorize',{method:'POST',body:JSON.stringify({spec_id:SPEC_ID,estimated_seconds:secs})});
 if(!a.ok||!a.body.transaction_id)return fail(a.status===409?'This GPU can’t take paid jobs right now.':'Could not start the payment.');
 TX=a.body.transaction_id;SECRET=a.body.client_secret;
 el('buy_cancel').style.display='';
 if(CFG.gateway==='real'){
   PHASE='awaiting_card';
   var okc=await mountCard();
   if(!okc)return;
   setMsg('Enter your test card above, then press Pay.');
   var b=el('buy_pay');b.disabled=false;b.textContent='Pay '+m2(QUOTE.authorization_amount)+' & run';
   return;
 }
 PHASE='running';
 var sc=await api('/payments/'+TX+'/simulate-card',{method:'POST'});
 if(!sc.ok)return fail('Card confirmation failed.');
 await afterCard();
}

async function mountCard(){
 el('card-row').style.display='';
 await new Promise(function(res){if(window.Stripe)return res();var sc=document.createElement('script');sc.src='https://js.stripe.com/v3/';sc.onload=res;sc.onerror=res;document.head.appendChild(sc);});
 if(!window.Stripe||!CFG.publishable_key){fail('Card entry is unavailable (Stripe.js did not load).');return false;}
 STRIPE=Stripe(CFG.publishable_key);var elements=STRIPE.elements();
 CARDEL=elements.create('card');CARDEL.mount('#card-element');
 CARDEL.on('change',function(ev){el('card-errors').textContent=(ev.error&&ev.error.message)||'';});
 return true;
}

async function realConfirm(){
 var b=el('buy_pay');b.disabled=true;setMsg('Confirming your card with Stripe…');
 var res=await STRIPE.confirmCardPayment(SECRET,{payment_method:{card:CARDEL}});
 if(res.error){el('card-errors').textContent=res.error.message||'Card was declined.';b.disabled=false;PHASE='awaiting_card';setMsg('Card was not accepted — try again.');return;}
 PHASE='running';b.style.display='none';
 await afterCard();
}

async function afterCard(){
 renderSteps({pay:1});setMsg('Card authorized — reserving your GPU…');
 var cf=await api('/payments/'+TX+'/confirm',{method:'POST'});
 if(!cf.ok)return fail('We could not confirm the authorization.');
 var rv=await api('/payments/'+TX+'/reserve',{method:'POST'});
 if(!rv.ok)return fail(rv.status===409?'No capacity is free on this GPU right now.':'Could not reserve the GPU.');
 renderSteps({pay:1,reserve:1});setMsg('Sending your workload to the GPU…');
 var code=(el('buy_code').value)||\"print('hello gpu')\";
 var dp=await api('/payments/'+TX+'/dispatch',{method:'POST',body:JSON.stringify({task_type:'notebook',code:code})});
 if(!dp.ok)return fail('Could not start the job on the GPU.');
 TASKID=dp.body.task_id||null;
 el('buy_pay').style.display='none';
 startPoll();
}

function startPoll(){
 if(POLL)clearInterval(POLL);var t0=Date.now();
 POLL=setInterval(async function(){
  var pr=await api('/payments/'+TX);if(!pr.ok)return;var st=pr.body.status;
  setMsg(FRIENDLY[st]||'Working…');
  if(st==='GPU_RESERVED'||st==='DISPATCHING')renderSteps({pay:1,reserve:1});
  if(st==='RUNNING'||st==='METERING_FINALIZED'||st==='PAYMENT_CAPTURE_PENDING')renderSteps({pay:1,reserve:1,run:1});
  if(SETTLED[st]){clearInterval(POLL);renderSteps({pay:1,reserve:1,run:1,charge:1});return complete(pr.body);}
  if(FAILED[st]){clearInterval(POLL);return failTerminal(st);}
  if(Date.now()-t0>240000){clearInterval(POLL);setMsg('Still working — this is taking longer than usual. You can leave this page; the job keeps running.');}
 },2000);
}

async function complete(tx){
 el('buy_cancel').style.display='none';
 setMsg('Done — you were charged '+m2(tx.captured_amount)+' for actual usage.');
 var out='';
 if(TASKID){var tk=await api('/tasks/'+TASKID);if(tk.ok&&tk.body.result)out=tk.body.result;}
 var rc=await api('/payments/'+TX+'/receipt');var r=rc.ok?rc.body:{};
 el('buy_result').style.display='';
 el('buy_result_body').innerHTML=
  '<div class="stat"><div class="n teal">'+m2(tx.captured_amount)+'</div><div class="l">Charged for actual usage</div></div>'+
  '<p class="mini" style="margin-top:8px">Authorized up to '+m2(tx.authorization_amount)+' — the unused hold was released. You only pay for GPU time used.</p>'+
  (out?('<div class="lbl" style="margin-top:14px">Workload output</div><pre style="white-space:pre-wrap;font-size:12px;max-height:280px;overflow:auto;background:var(--panel);padding:10px;border-radius:8px">'+esc(out)+'</pre>'):'<p class="mut" style="font-size:13px;margin-top:12px">The job finished. No text output was returned.</p>')+
  '<div class="mini" style="margin-top:12px">Receipt '+esc(r.transaction_id||TX)+' · '+(r.is_completed_payment?'payment complete':'processing')+'</div>';
}

function failTerminal(st){
 var b=el('buy_pay');if(b)b.style.display='none';
 var MSG={
  'JOB_FAILED':'The workload failed on the GPU. Release the reservation below — you’re only charged for actual usage.',
  'CAPTURE_FAILED':'The job ran but finalizing the charge failed. Release the reservation below and contact support if your card was not charged correctly.',
  'DISPATCH_FAILED':'We couldn’t start the job on the GPU. Release the reservation below; nothing was captured.',
  'RESERVATION_FAILED':'The GPU’s capacity was taken before we could reserve it. Nothing was charged.',
  'AUTHORIZATION_EXPIRED':'The card authorization expired before the job ran. Nothing was charged.',
  'PAYMENT_FAILED':'The card was not authorized. Nothing was charged.',
  'CANCELLED':'This rental was cancelled. Nothing was charged.',
  'REFUNDED':'This rental was refunded.',
  'REFUND_PENDING':'This rental is being refunded — the charge will be returned to your card.',
  'DISPUTED':'This charge is under dispute. Our team will follow up; nothing more is needed here.'};
 el('buy_cancel').style.display=(st==='JOB_FAILED'||st==='CAPTURE_FAILED'||st==='DISPATCH_FAILED')?'':'none';
 showError(MSG[st]||'The rental ended early.');setMsg('Ended.');
}

async function buyCancel(){
 if(!TX)return;var b=el('buy_cancel');b.disabled=true;setMsg('Releasing…');
 var r=await api('/payments/'+TX+'/cancel',{method:'POST'});
 if(r.ok){setMsg('Released. Nothing further will be charged.');b.style.display='none';}
 else if(r.status===409){setMsg('The job is still running and can’t be cancelled right now.');b.disabled=false;}
 else{setMsg('Couldn’t release it here — it will be reclaimed automatically shortly.');b.disabled=false;}
}

loadBuy();
</script>""")


METRICS_HTML = _page("Petabyte — marketplace metrics",
    desc="Operations and investor metrics computed from real database queries: supply, utilization, GMV, take rate, buyer savings and job reliability. Demo data is clearly labelled.",
    path="/metrics", body="""
<div class="wrap" style="padding:52px 24px 6px">
  <div class="eyebrow"><span class="dot"></span> <span data-ar="مقاييس السوق">marketplace metrics</span></div>
  <h1 style="font-size:clamp(28px,4.4vw,42px);margin:14px 0 8px">Marketplace &amp; unit economics</h1>
  <p class="mut" style="max-width:70ch">Every number is computed live from the database — the ledger, bookings, specs and jobs. No hardcoded figures. Hover a metric for its definition.</p>
  <div id="demobanner" style="display:none;margin-top:16px" class="card">
    <b class="amber">Demo data</b> <span class="mut">— these figures include seeded, clearly-labelled demonstration entities, not real traction. Switch the scope to “Real only” to see production numbers.</span>
  </div>
  <div class="filterbar" style="margin-top:16px;gap:10px;align-items:flex-end">
    <div class="field"><span>Scope</span>
      <select id="mscope" onchange="loadMetrics()">
        <option value="all">All (demo + real)</option>
        <option value="demo">Demo only</option>
        <option value="real">Real only</option>
      </select></div>
    <div class="field"><span>Since</span><input id="msince" type="date" onchange="loadMetrics()"/></div>
    <div class="field"><span>Until</span><input id="muntil" type="date" onchange="loadMetrics()"/></div>
    <button class="btn btn-ghost" onclick="document.getElementById('msince').value='';document.getElementById('muntil').value='';loadMetrics()">Clear dates</button>
  </div>
</div>

<div class="wrap" style="padding:6px 24px 8px">
  <div class="lbl" style="margin:14px 0 8px">Supply</div>
  <div class="stats" id="grp_supply"></div>
  <div class="lbl" style="margin:22px 0 8px">Demand &amp; reliability</div>
  <div class="stats" id="grp_demand"></div>
  <div class="lbl" style="margin:22px 0 8px">Unit economics</div>
  <div class="stats" id="grp_econ"></div>
</div>

<div class="wrap" style="padding:8px 24px 10px"><div class="cols c2">
  <div class="card"><div class="lbl">Supply by region</div><div id="by_region" style="margin-top:10px"></div></div>
  <div class="card"><div class="lbl">Supply by hardware</div><div id="by_hw" style="margin-top:10px"></div></div>
</div></div>

<div class="wrap" style="padding:8px 24px 40px">
  <div class="card" id="integritycard">
    <div class="lbl">Integrity</div>
    <p class="mut" id="integritytext" style="font-size:13px;margin-top:8px">—</p>
  </div>
  <p class="mini" style="margin-top:14px">Metric definitions: <a class="teal" href="/metrics/definitions">/metrics/definitions</a>. Take rate should equal the configured platform fee; the ledger must always balance.</p>
</div>

<script>
var DEFS={};
function tile(label,val,def){return '<div class="stat" title="'+(def||'').replace(/"/g,"&quot;")+'"><div class="n teal">'+val+'</div><div class="l">'+label+'</div></div>';}
function money(n){return '$'+Number(n||0).toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2});}
function bars(obj){var e=Object.entries(obj||{});if(!e.length)return '<span class="mut mono" style="font-size:12px">none</span>';
  var max=Math.max.apply(null,e.map(function(x){return x[1]}));
  return e.sort(function(a,b){return b[1]-a[1]}).map(function(x){
    var pct=max?Math.round(100*x[1]/max):0;
    return '<div style="display:flex;align-items:center;gap:10px;padding:5px 0">'+
      '<span class="mono" style="flex:1;font-size:12.5px">'+x[0]+'</span>'+
      '<span style="flex:2;height:8px;background:var(--hair);border-radius:6px;overflow:hidden"><span style="display:block;height:100%;width:'+pct+'%;background:var(--teal)"></span></span>'+
      '<span class="mono mut" style="width:28px;text-align:end;font-size:12px">'+x[1]+'</span></div>';
  }).join('');}
async function loadDefs(){try{DEFS=(await (await fetch('/metrics/definitions')).json()).definitions||{};}catch(e){}}
async function loadMetrics(){
  var scope=document.getElementById('mscope').value;
  var since=document.getElementById('msince').value,until=document.getElementById('muntil').value;
  var qs='scope='+scope+(since?'&since='+since:'')+(until?'&until='+until:'');
  var m;try{m=await (await fetch('/metrics/overview?'+qs)).json();}catch(e){return;}
  document.getElementById('demobanner').style.display=m.contains_demo_data?'':'none';
  var s=m.supply,d=m.demand,e=m.economics,j=m.jobs;
  document.getElementById('grp_supply').innerHTML=
    tile('Registered nodes',s.registered,DEFS.contains_demo_data)+
    tile('Online',s.online,'Nodes currently heartbeating')+
    tile('Verified',s.verified,'Nodes with a signed hardware attestation')+
    tile('Utilization',s.utilization_pct+'%',DEFS.utilization_pct)+
    tile('Available GPU-hrs',s.available_gpu_hours,DEFS.available_gpu_hours)+
    tile('Booked GPU-hrs',s.booked_gpu_hours,DEFS.booked_gpu_hours);
  document.getElementById('grp_demand').innerHTML=
    tile('Active buyers',d.active_buyers,'Distinct buyers with a booking in range')+
    tile('Repeat buyers',d.repeat_buyers,DEFS.repeat_buyers)+
    tile('Active sellers',d.active_sellers,'Sellers with a settled booking')+
    tile('Jobs completed',j.completed,DEFS.completion_rate_pct)+
    tile('Jobs failed',j.failed,'Buyer jobs that reported failure')+
    tile('Completion rate',(j.completion_rate_pct==null?'—':j.completion_rate_pct+'%'),DEFS.completion_rate_pct);
  document.getElementById('grp_econ').innerHTML=
    tile('GMV',money(e.gmv),DEFS.gmv)+
    tile('Platform revenue',money(e.platform_revenue),DEFS.platform_revenue)+
    tile('Seller payouts',money(e.seller_payouts),DEFS.seller_payouts)+
    tile('Effective take rate',e.effective_take_rate_pct+'%',DEFS.effective_take_rate_pct)+
    tile('Avg $/hr',(e.avg_hourly_price==null?'—':money(e.avg_hourly_price)),'Mean listed hourly price of online nodes')+
    tile('Buyer savings vs cloud',money(e.buyer_savings_vs_cloud),DEFS.buyer_savings_vs_cloud);
  document.getElementById('by_region').innerHTML=bars(s.by_region);
  document.getElementById('by_hw').innerHTML=bars(s.by_hardware);
  var ok=m.integrity.ledger_balanced;
  document.getElementById('integritytext').innerHTML=
    (ok===true?'<b style="color:var(--pos)">Ledger balanced</b> — every transaction\\'s debits equal its credits and the books sum to zero.'
      :ok===false?'<b style="color:var(--bad)">Ledger imbalance detected</b> — broken tx: '+JSON.stringify(m.integrity.broken_transactions)
      :'Ledger check unavailable.');
}
loadDefs().then(loadMetrics);setInterval(loadMetrics,15000);
</script>""")


TEMPLATES_HTML = _page("Petabyte — templates",
    desc="One-click curated templates: Jupyter, PyTorch, Ollama, vLLM, ComfyUI, Blender, game servers — placed on the cheapest verified GPU that fits.", path="/catalog", body="""
<div class="hero"><div class="wrap" style="padding:56px 24px 12px">
  <div class="eyebrow"><span class="dot"></span> one-click templates</div>
  <h1 style="font-size:clamp(32px,5vw,52px);margin:16px 0 12px" data-ar="اختر عبء عمل. اضغط تشغيل.">Pick a workload. <span class="grad">Press launch.</span></h1>
  <p class="mut" style="font-size:16px;max-width:60ch" data-ar="لا معالج إعداد. لا ضبط للتخزين والشبكة ومفاتيح SSH قبل أن تفعل أي شيء. اختر ما تريد تشغيله — نضعه على أرخص كرت رسومات موثّق يناسبه ونعطيك العنوان.">No wizard. No configuring storage, networking, and SSH keys before you can do anything. Choose what you want to run — we place it on the cheapest verified GPU that fits and hand you the address.</p>
</div></div>

<div class="wrap" style="padding:14px 24px 8px">
  <div class="filterbar" style="margin-bottom:18px">
    <div id="tplchips" style="display:flex;gap:8px;flex-wrap:wrap"></div>
    <div style="margin-inline-start:auto;display:flex;align-items:center;gap:9px">
      <span class="mini">Hours</span>
      <input id="tplhours" type="number" min="1" max="720" value="2" style="width:72px" onchange="paintTemplates()"/>
    </div>
  </div>
  <div id="tplgrid"></div>
  <div id="launchresult" style="display:none"></div>

  <div class="card" style="margin-top:22px">
    <div class="lbl">Launch from the API</div>
    <h2 style="font-size:17px;margin-bottom:6px" data-ar="شغّل أي قالب عبر الواجهة البرمجية">Launch any template via the API</h2>
    <p class="mut" style="font-size:13px;margin-bottom:10px" data-ar="نشغّل حالياً قوالب مُدارة ومدقّقة فقط — لا صور عشوائية من المستخدم — لأن العبء يعمل على جهاز شخص آخر. صور المستخدم المخصّصة على خارطة الطريق.">Today we run <b>curated, audited templates only</b> — not arbitrary user images — because every workload runs on someone else's machine, and an unreviewed image is the host's risk. Custom images are on the roadmap behind stronger isolation.</p>
    <div class="codeline"><code>curl -sX POST https://petabyte.market/api/v1/deployments -H "X-API-KEY: $KEY" -H "Content-Type: application/json" -d '{"template":"vllm","hours":4}'</code>
      <button class="copybtn" onclick="navigator.clipboard&amp;&amp;navigator.clipboard.writeText(this.previousElementSibling.textContent);this.textContent='copied'">copy</button></div>
    <p class="mut" style="font-size:12.5px;margin-top:10px">Full reference in the <a class="teal" href="/docs">API docs</a>.</p>
  </div>
</div>
<script>
var TPL_KINDS=[["all","Everything"],["notebook","Notebooks"],["ai","AI &amp; inference"],["art","Art &amp; image"],["render","Render &amp; video"],["game","Game servers"]];
var TPL_ACTIVE="all";
function paintChips(){
  document.getElementById('tplchips').innerHTML=TPL_KINDS.map(function(k){
    var on=k[0]===TPL_ACTIVE;
    return '<button class="btn '+(on?'btn-teal':'btn-ghost')+'" style="padding:7px 15px;font-size:12.5px" onclick="TPL_ACTIVE=\\''+k[0]+'\\';paintChips();paintTemplates()">'+k[1]+'</button>';
  }).join('');
}
function paintTemplates(){
  var h=parseInt(document.getElementById('tplhours').value||'2',10);
  var kinds = TPL_ACTIVE==='all' ? ['notebook','ai','art','render','game'] : [TPL_ACTIVE];
  renderLaunch('tplgrid', kinds, h);
}
paintChips();paintTemplates();
</script>""")


CONTACT_HTML = _page("Petabyte — contact",
    desc="Talk to Petabyte: support, hosting, volume and investor enquiries. "
         "Riyadh, Saudi Arabia.",
    path="/contact", body="""
<div class="hero"><div class="wrap" style="padding:56px 24px 10px">
  <div class="eyebrow"><span class="dot"></span> <span data-ar="تواصل معنا">contact</span></div>
  <h1 style="font-size:clamp(32px,5vw,52px);margin:16px 0 12px" data-ar="تحدّث إلى إنسان.">Talk to a <span class="grad">human.</span></h1>
  <p class="mut" style="font-size:16px;max-width:58ch" data-ar="Petabyte فريق صغير في الرياض. هذا يعني أنك تحصل على إجابة حقيقية ممّن بنى المنتج فعلاً — عادةً خلال يوم.">Petabyte is a small team in Riyadh. That means you get a real answer from someone who actually built the thing — usually within a day.</p>
</div></div>

<div class="wrap" style="padding:14px 24px 8px">
  <div class="cols" style="gap:18px;align-items:stretch">
    <div class="card" style="flex:1 1 320px">
      <div class="lbl" data-ar="أين تكتب">Where to write</div>
      <p style="margin-top:8px"><a class="teal mono" style="font-size:16px" href="mailto:info@petabyte.market">info@petabyte.market</a></p>
      <p class="mut" style="font-size:13px;margin-top:8px" data-ar="بريد واحد لكل شيء — الدعم، وإدراج كرت رسومات، وبلاغات الأمان، وأسئلة المستثمرين. اكتب الموضوع في عنوان الرسالة ليصل إلى الشخص المناسب.">One inbox for everything — support, listing a GPU, security reports, and investor questions. Put the topic in the subject line and it reaches the right person.</p>
      <p class="mut" style="font-size:12.5px;margin-top:12px" data-ar="مقرّنا الرياض، السعودية (UTC+3). نجيب على بلاغات الأمان أولاً، ولن نتّخذ إجراءً قانونياً ضد الأبحاث حسنة النية.">Based in Riyadh, Saudi Arabia (UTC+3). We answer security reports first, and we will not take legal action against good-faith research.</p>
    </div>

    <div class="card" style="flex:1 1 320px">
      <div class="lbl am" data-ar="الفرق والكميات">Teams &amp; volume</div>
      <h2 style="font-size:17px;margin-bottom:6px" data-ar="تحتاج أكثر من الخدمة الذاتية؟">Need more than the self-serve flow?</h2>
      <p class="mut" style="font-size:13.5px;margin-bottom:12px" data-ar="معظم الناس لا يحتاجون للتحدث إلينا — تسجّل، تضيف رصيداً، وتشغّل. تواصل معنا إن كنت تحتاج شيئاً لا يفعله المنتج بعد:">Most people never need to talk to us — you sign up, add funds, and launch. Get in touch if you need something the product does not do yet:</p>
      <ul class="mut" style="font-size:13.5px;padding-inline-start:18px;line-height:1.85">
        <li data-ar="قدرة محجوزة لعملية تدريب">Reserved capacity for a training run</li>
        <li data-ar="فوترة بدلاً من الرصيد المدفوع مسبقاً">Invoicing instead of prepaid balance</li>
        <li data-ar="منطقة محدّدة، أو عتاد لا ندرجه">A specific region, or hardware we do not list</li>
        <li data-ar="فوترة مشتركة للمؤسسة عبر فريق">Shared org billing across a team</li>
      </ul>
      <a class="btn btn-amber" style="margin-top:14px" href="mailto:info@petabyte.market?subject=Capacity%20enquiry" data-ar="راسلنا بشأن القدرة">Email us about capacity</a>
      <p class="mini" style="margin-top:10px" data-ar="سنخبرك بصدق إن كنّا لا نستطيع خدمتك بعد.">We will tell you honestly if we cannot serve you yet.</p>
    </div>
  </div>

  <div class="card" style="margin-top:18px">
    <div class="lbl" data-ar="في أماكن أخرى">Elsewhere</div>
    <div style="display:flex;gap:10px;flex-wrap:wrap;margin-top:8px">
      <a class="btn btn-ghost" href="https://github.com/BDR-Pro" rel="noopener">GitHub</a>
      <a class="btn btn-ghost" href="https://x.com/engcool" rel="noopener">X</a>
      <a class="btn btn-ghost" href="/status" data-ar="حالة المنصة">Platform status</a>
      <a class="btn btn-ghost" href="/security" data-ar="الأمان">Security</a>
    </div>
  </div>
</div>""")


NOTFOUND_HTML = _page("Petabyte — page not found",
    desc="That page does not exist.", path="/", body="""
<div class="wrap" style="padding:90px 24px 60px;text-align:center">
  <div class="mono" style="font-size:56px;color:var(--teal);font-weight:600">404</div>
  <h1 style="font-size:clamp(26px,4vw,38px);margin:12px 0 10px" data-ar="هذه الصفحة غير موجودة.">That page is not here.</h1>
  <p class="mut" style="max-width:46ch;margin:0 auto 22px" data-ar="قد يكون الرابط قديماً، أو ربما نقلناه. لا خطب في حسابك أو أجهزتك.">The link may be old, or we may have moved it. Nothing is wrong with your account or your instances.</p>
  <div style="display:flex;gap:10px;justify-content:center;flex-wrap:wrap">
    <a class="btn btn-teal" href="/marketplace">Browse GPUs</a>
    <a class="btn btn-ghost" href="/catalog">Templates</a>
    <a class="btn btn-ghost" href="/account">Your account</a>
    <a class="btn btn-ghost" href="/contact">Contact us</a>
  </div>
  <p class="mini" style="margin-top:20px">Press <span class="mono">&#8984;K</span> to jump anywhere.</p>
</div>""")


DEMO_HTML = _page("Petabyte — book a demo",
    desc="See Petabyte live. We will walk you through the marketplace, launch a real "
         "GPU, and show your workload running. Book a 20-minute call.",
    path="/demo", body="""
<div class="hero"><div class="wrap" style="padding:56px 24px 10px">
  <div class="eyebrow"><span class="dot"></span> book a demo</div>
  <h1 style="font-size:clamp(32px,5.4vw,54px);margin:16px 0 12px" data-ar="شاهد النظام وهو يعمل.">See it <span class="grad">actually run.</span></h1>
  <p class="mut" style="font-size:16px;max-width:60ch" data-ar="مكالمة مدتها ٢٠ دقيقة. نعرض لك السوق مباشرةً، ونشغّل كرت رسومات حقيقياً، ونمرّ على حالتك أنت — لا شرائح فقط.">A 20-minute call. We show you the live marketplace, launch a real GPU, and walk through your actual workload — not slides. If we are not a fit yet, we will tell you.</p>
</div></div>

<div class="wrap" style="padding:14px 24px 30px">
  <div class="cols" style="gap:18px;align-items:flex-start">
    <div class="card" style="flex:1.2 1 340px">
      <div class="lbl">Tell us what you need</div>
      <div id="demoform" style="margin-top:10px">
        <div class="filterbar" style="flex-direction:column;align-items:stretch;gap:12px">
          <label class="field"><span data-ar="الاسم">Name</span><input id="d_name" data-ar-ph="اسمك" placeholder="Your name"/></label>
          <label class="field"><span data-ar="البريد الإلكتروني">Email</span><input id="d_email" type="email" data-ar-ph="you@company.com" placeholder="you@company.com"/></label>
          <label class="field"><span data-ar="جهة العمل (اختياري)">Organization (optional)</span><input id="d_org" data-ar-ph="الشركة أو الجامعة" placeholder="Company or university"/></label>
          <label class="field"><span data-ar="ما الذي تريد تشغيله؟">What do you want to run?</span><textarea id="d_workload" rows="3" data-ar-ph="مثال: تدريب نموذج، استنتاج، معالجة فيديو…" placeholder="e.g. fine-tuning, batch inference, rendering, ~200 GPU-hours"></textarea></label>
          <div class="cols" style="gap:10px">
            <label class="field" style="flex:1"><span data-ar="أنا…">I am…</span>
              <select id="d_role">
                <option value="buyer" data-ar="أحتاج قدرة حوسبة">I need compute</option>
                <option value="host" data-ar="لديّ عتاد لتأجيره">I have hardware to rent out</option>
                <option value="investor" data-ar="مستثمر">An investor</option>
                <option value="other" data-ar="أخرى">Something else</option>
              </select></label>
            <label class="field" style="flex:1"><span data-ar="اليوم المفضّل (اختياري)">Preferred day (optional)</span><input id="d_date" type="date"/></label>
            <label class="field" style="flex:1"><span data-ar="الوقت المفضّل">Preferred time</span>
              <select id="d_slot">
                <option value="" data-ar="أي وقت يناسبكم">Any time that works</option>
                <option value="morning" data-ar="صباحاً (٩ص–١٢م بتوقيت الرياض)">Morning (9am–12pm Riyadh)</option>
                <option value="afternoon" data-ar="بعد الظهر (١٢م–٤م)">Afternoon (12–4pm Riyadh)</option>
                <option value="evening" data-ar="مساءً (٤م–٧م)">Evening (4–7pm Riyadh)</option>
              </select></label>
          </div>
          <button class="btn btn-amber" style="width:100%;justify-content:center" data-act="submitDemo" data-ar="اطلب موعداً">Request a demo</button>
          <div id="d_msg" class="mini" style="min-height:18px"></div>
        </div>
      </div>
    </div>

    <div style="flex:1 1 300px;display:flex;flex-direction:column;gap:14px">
      <div class="card">
        <div class="lbl am">What you will see</div>
        <ul class="mut" style="font-size:13.5px;padding-inline-start:18px;line-height:1.9;margin-top:6px">
          <li data-ar="السوق الحقيقي — كروت رسومات فعلية بأسعارها الآن.">The real marketplace — actual GPUs at their live prices</li>
          <li data-ar="تشغيل حقيقي بنقرة واحدة، ننتظر حتى يعمل.">A one-click launch, live, until it is running</li>
          <li data-ar="كيف يحمي الضمان أموالك ويعيد الساعات غير المستخدمة.">How escrow holds your money and refunds unused hours</li>
          <li data-ar="ماذا يحدث عند تعطّل مضيف أثناء العمل.">What happens when a host dies mid-job</li>
        </ul>
      </div>
      <div class="card">
        <div class="lbl">Prefer to just try it?</div>
        <p class="mut" style="font-size:13px;margin:6px 0 12px" data-ar="لست مضطراً لحجز موعد. يمكنك التسجيل وإضافة رصيد والتشغيل خلال دقائق.">You do not have to book anything. You can sign up, add funds, and launch in minutes.</p>
        <a class="btn btn-teal" style="width:100%;justify-content:center" href="/marketplace" data-ar="تصفّح كروت الرسومات">Browse GPUs now</a>
      </div>
    </div>
  </div>
</div>
<script>
(function(){var d=document.getElementById('d_date');if(d){var t=new Date();t.setMinutes(t.getMinutes()-t.getTimezoneOffset());d.min=t.toISOString().slice(0,10);}})();
async function submitDemo(){
  var m=document.getElementById('d_msg');
  var name=(document.getElementById('d_name').value||'').trim();
  var email=(document.getElementById('d_email').value||'').trim();
  if(!name||!email){m.style.color='var(--warn)';m.textContent='Please add your name and email.';return;}
  m.style.color='';m.textContent='Sending…';
  var payload={name:name,email:email,
    organization:(document.getElementById('d_org').value||'').trim(),
    workload:(document.getElementById('d_workload').value||'').trim(),
    role:document.getElementById('d_role').value,
    preferred_time:[(document.getElementById('d_date').value||''),(document.getElementById('d_slot').value||'')].filter(Boolean).join(' ').trim(),
    source:'demo-page'};
  try{
    var r=await fetch('/demo/request',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
    var b=await r.json();
    if(!r.ok){m.style.color='var(--warn)';m.textContent=(b.error&&b.error.message)||(b.detail)||'Could not send. Try emailing info@petabyte.market.';return;}
    document.getElementById('demoform').innerHTML='<div style="text-align:center;padding:20px 10px">'+
      '<div class="mono" style="font-size:32px;color:var(--teal)">&#10003;</div>'+
      '<div style="font-family:var(--disp);font-weight:600;margin:8px 0 4px" data-ar="تم استلام الطلب">Request received</div>'+
      '<div class="mut" style="font-size:13.5px">'+b.message+'</div>'+
      (b.booking_url?('<a class="btn btn-amber" style="margin-top:14px" href="'+b.booking_url+'" target="_blank" rel="noopener" data-ar="اختر وقتاً يناسبك ←">Pick your time →</a>'):'')+
      '<div class="mini" style="margin-top:10px" data-ar="المرجع">Reference '+b.reference+'</div></div>';
  }catch(e){m.style.color='var(--warn)';m.textContent='Network error. Try emailing info@petabyte.market.';}
}
</script>""")
