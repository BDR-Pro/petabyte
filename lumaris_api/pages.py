"""Static site pages served by the API (same-origin, no build step).

Brand: Petabyte — deep-navy background with teal/cyan bioluminescent
accents and an amber energy accent, Sora (display) + Figtree (body) +
JetBrains Mono (data). The hexagon node mark (/static/petabyte-logo.png) is the
signature. The session JWT lives in an HttpOnly `pb_session` cookie (never localStorage, so
XSS can't read it); the readable `pb_csrf` cookie is the double-submit CSRF token and the
"signed in" hint. api() sends the cookie automatically and adds X-CSRF-Token on writes.
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
<script>(function(){try{document.documentElement.setAttribute('data-auth',(document.cookie.indexOf('pb_csrf=')>=0)?'in':'out');}catch(e){}})();</script>
<script>(function(){try{var t=localStorage.getItem('pb_theme');if(t!=='light'&&t!=='dark')t=(window.matchMedia&&matchMedia('(prefers-color-scheme: light)').matches)?'light':'dark';document.documentElement.setAttribute('data-theme',t);document.documentElement.setAttribute('data-bs-theme',t);}catch(e){document.documentElement.setAttribute('data-theme','dark');document.documentElement.setAttribute('data-bs-theme','dark');}})();</script>
<link rel="icon" type="image/png" href="/favicon.ico">
<link rel="apple-touch-icon" href="/static/petabyte-mark-180.png">
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Sora:wght@500;600;700;800&family=Inter:wght@400;450;500;600;700&family=JetBrains+Mono:wght@400;500;600&family=Cairo:wght@400;500;600;700&display=swap" rel="stylesheet">
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
@media(min-width:992px) and (max-width:1260px){.navlinks a{padding:7px 8px;font-size:12.5px}.navcta{gap:6px}.navcta .btn{padding:8px 13px;font-size:12.5px}nav .wrap{gap:10px}}
.navbar-toggler{border:1px solid var(--line2);border-radius:999px;padding:7px 11px;color:var(--mut)}
.navbar-toggler:focus{box-shadow:0 0 0 4px rgba(53,224,208,.15)}
.navbar-toggler svg{width:18px;height:18px;display:block}
/* the hamburger is mobile-only; hide it on desktop even if the Bootstrap CDN is slow/blocked */
@media(min-width:992px){.navbar-toggler{display:none!important}}
@media(max-width:991.98px){
 /* Hide the collapsed menu by default WITHOUT relying on the Bootstrap CDN stylesheet: if
    that asset is slow or blocked, the signed-in nav (mename + theme + sign-out + CTAs) must
    not render open and overflow the viewport. Mirrors Bootstrap's own .collapse:not(.show). */
 .navbar-collapse:not(.show){display:none}
 .navbar-collapse{flex-basis:100%;padding:10px 4px 12px}
 .navlinks{flex-direction:column;gap:2px;margin-inline-start:0}
 .navlinks a{padding:9px 13px}
 .navcta{margin-inline-start:0;margin-top:8px;flex-wrap:wrap}}
:root{--abyss:#070C18;--depth:#0F1828;--depth2:#14223C;--line:#213152;--line2:#2E4066;
--ink:#EDF2FC;--mut:#9EABC7;--dim:#657493;
--teal:#3AE0CF;--teal-br:#93F6EA;--deep:#12A093;--amber:#FFBE45;--amber-br:#FFD684;
--pos:#4FE0A0;--warn:#F2B450;--bad:#F2748C;
--gA:rgba(255,190,66,.06);--gB:rgba(58,224,207,.11);--gV:rgba(129,90,240,.10);
--navbg:rgba(13,21,39,.74);--hair:#152037;
--panel:var(--depth);--panel2:#0B1626;
--disp:'Sora',system-ui,sans-serif;--body:'Inter',system-ui,sans-serif;--mono:'JetBrains Mono',ui-monospace,monospace;
--r:18px;--r-sm:12px}
html[data-theme=light]{
 --abyss:#EEF3FA;--depth:#FFFFFF;--depth2:#F6FAFD;--line:#E1EAF3;--line2:#C8D7E5;
 --ink:#0F1C30;--mut:#4E6079;--dim:#8091A8;
 --teal:#0B9C90;--teal-br:#0FBCAE;--deep:#0A7E76;--amber:#AE720F;--amber-br:#D0902A;
 --gA:rgba(255,178,36,.10);--gB:rgba(15,188,174,.12);--gV:rgba(124,58,237,.06);
 --navbg:rgba(255,255,255,.80);--hair:#EAF0F6;--panel:#FFFFFF;--panel2:#F5F9FC}
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
h1{font-family:var(--disp);font-weight:800;letter-spacing:-.035em;line-height:1.0}
h2{font-family:var(--disp);font-weight:700;letter-spacing:-.02em}
.grad{background:linear-gradient(95deg,var(--teal-br) 10%,var(--amber) 90%);-webkit-background-clip:text;background-clip:text;color:transparent}
.grad-teal{background:linear-gradient(95deg,var(--teal-br),var(--deep));-webkit-background-clip:text;background-clip:text;color:transparent}
/* ---------- nav: floating glass pill ---------- */
nav{z-index:40;padding:14px 0 6px;background:linear-gradient(180deg,var(--abyss) 30%,transparent)}
nav .wrap{display:flex;align-items:center;gap:14px;min-height:58px;background:var(--navbg);
 border:1px solid var(--line);border-radius:26px;padding:6px 12px 6px 20px;flex-wrap:wrap;row-gap:6px;
 backdrop-filter:blur(16px);-webkit-backdrop-filter:blur(16px);
 box-shadow:0 12px 40px -18px rgba(0,0,0,.6),inset 0 1px 0 rgba(255,255,255,.05)}
.brand{display:flex;align-items:center;gap:10px;font-family:var(--disp);font-weight:700;font-size:18px;letter-spacing:-.02em}
.brand img{width:26px;height:26px;display:block;filter:drop-shadow(0 0 8px rgba(53,224,208,.5))}
.brand .p{color:var(--teal)}
.navlinks{display:flex;gap:2px;margin-inline-start:6px;flex-wrap:nowrap}
.navlinks a{font-size:13px;font-weight:500;color:var(--mut);padding:7px 11px;border-radius:999px;transition:color .15s,background-color .15s;white-space:nowrap}
.navlinks a:hover{color:var(--ink);background:rgba(255,255,255,.05)}
.navlinks a.active{color:var(--teal);background:rgba(53,224,208,.10)}
.navcta{margin-inline-start:auto;display:flex;align-items:center;gap:8px;flex-wrap:nowrap}
.navcta .btn{padding:9px 16px;font-size:13px}
/* signed-in account chip: a compact identity pill instead of loose inline text */
#mename{max-width:150px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;
 background:rgba(58,224,207,.09);border:1px solid rgba(58,224,207,.24);padding:6px 12px}
/* the marketing "Book a demo" CTA is redundant once you're signed in — reclaim the room */
html[data-auth=in] #navdemo{display:none!important}
/* signed-in carries more controls (account + admin + sign out); compact them so the bar
   stays a single tidy row instead of wrapping. */
html[data-auth=in] .navlinks a{padding:6px 8px;font-size:12.5px}
html[data-auth=in] .navcta{gap:6px}
html[data-auth=in] .navcta .btn{padding:8px 14px;font-size:12.5px}
html[data-auth=in] nav .wrap{gap:10px}
html[data-auth=in] #mename{max-width:112px}
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
/* small helper / caption text — readable body copy, NOT a label. Uppercase micro-labels
   are .eyebrow / .lbl; .mini is for full sentences of secondary guidance so they read as
   prose, not terminal output. */
.mini{font-size:12px;line-height:1.55;color:var(--mut)}
.mini.cap{font-family:var(--mono);font-size:10px;letter-spacing:.14em;text-transform:uppercase;color:var(--dim);line-height:1.4}
.divider{height:1px;background:linear-gradient(90deg,transparent,var(--line2),transparent);margin:2px 0}
.pill{font-family:var(--mono);font-size:10px;border:1px solid rgba(53,224,208,.35);color:var(--teal);padding:3px 11px;border-radius:999px;background:rgba(53,224,208,.06)}
/* ---------- surfaces ---------- */
.panel{background:var(--panel2);border:1px solid var(--line);border-radius:var(--r)}
.card{position:relative;background:linear-gradient(180deg,var(--depth2),var(--panel2));border:1px solid var(--line);border-radius:var(--r);padding:22px;
 box-shadow:0 1px 2px rgba(0,0,0,.18),0 10px 30px -24px rgba(0,0,0,.5);
 transition:transform .18s,border-color .18s,box-shadow .18s}
html[data-theme=light] .card{box-shadow:0 1px 2px rgba(16,32,60,.05),0 12px 30px -22px rgba(16,32,60,.18)}
.card::before{content:"";position:absolute;inset:0;border-radius:var(--r);padding:1px;
 background:linear-gradient(140deg,rgba(58,224,207,.30),transparent 36%,transparent 68%,rgba(255,190,66,.16));
 -webkit-mask:linear-gradient(#000 0 0) content-box,linear-gradient(#000 0 0);-webkit-mask-composite:xor;mask-composite:exclude;
 opacity:0;transition:opacity .25s;pointer-events:none}
.card:hover{transform:translateY(-3px);border-color:var(--line2);box-shadow:0 24px 56px -28px rgba(58,224,207,.40),0 4px 14px -8px rgba(0,0,0,.4)}
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
.badge.warn{color:var(--warn);border-color:rgba(242,180,80,.42);background:rgba(242,180,80,.10)}
.badge.bad{color:var(--bad);border-color:rgba(242,116,140,.42);background:rgba(242,116,140,.11)}
/* status badge: a leading dot + the text label, so state never rides on colour alone.
   .ok=live/healthy · .warn=in-progress/attention · .bad=stopped/failed · plain=neutral/idle */
.badge.st{display:inline-flex;align-items:center;gap:6px;padding-inline-start:8px}
.badge.st::before{content:"";width:6px;height:6px;border-radius:50%;background:currentColor;flex:none}
/* ---------- test-mode banner (shown on money screens whenever payments are in sandbox/TEST) ---------- */
.pb-testmode{display:flex;gap:8px;align-items:center;justify-content:center;flex-wrap:wrap;
  margin:0 0 18px;padding:10px 14px;border-radius:var(--r);font-size:13px;line-height:1.4;
  color:var(--amber);border:1px solid rgba(255,178,36,.4);background:rgba(255,178,36,.09)}
.pb-testmode b{font-family:var(--mono);font-size:10px;letter-spacing:.06em;padding:3px 8px;border-radius:999px;
  color:#241802;background:linear-gradient(180deg,var(--amber-br),var(--amber))}
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
/* ---------- loading skeletons (reusable; respect reduced-motion) ---------- */
.skel{position:relative;overflow:hidden;background:linear-gradient(180deg,var(--depth2),var(--panel2));border:1px solid var(--line);border-radius:var(--r);padding:22px}
.skel-b{display:block;background:linear-gradient(90deg,var(--line) 25%,var(--line2) 37%,var(--line) 63%);background-size:400% 100%;border-radius:8px;animation:skel 1.4s ease infinite}
@keyframes skel{0%{background-position:100% 50%}100%{background-position:0 50%}}
@media(prefers-reduced-motion:reduce){.skel-b{animation:none}}
/* ---------- key/value summary rows (cost breakdowns, receipts, specs) ---------- */
.sumrow{display:flex;justify-content:space-between;gap:16px;padding:8px 0;border-bottom:1px solid var(--hair);font-size:13px}
.sumrow:last-child{border-bottom:0}
.sumrow .k{color:var(--mut)}
.sumrow .v{font-family:var(--mono);font-variant-numeric:tabular-nums;text-align:end;color:var(--ink)}
.sumrow.total{border-top:1px solid var(--line2);border-bottom:0;margin-top:6px;padding-top:13px}
.sumrow.total .k{color:var(--ink);font-family:var(--disp);font-weight:600;font-size:14.5px}
.sumrow.total .v{color:var(--amber);font-family:var(--disp);font-weight:700;font-size:18px}
/* ---------- launch compute: numbered sections + selectable cards (AWS-style) ---------- */
.lsec{margin-bottom:16px}
.lsec-h{display:flex;align-items:center;gap:12px;margin-bottom:2px}
.lsec-h h2{font-size:18px}
.lsec-sub{color:var(--mut);font-size:13px;margin:2px 0 0 34px}
.lsec.locked{opacity:.5;pointer-events:none;filter:saturate(.5)}
.picks{display:grid;grid-template-columns:repeat(auto-fill,minmax(190px,1fr));gap:11px;margin-top:14px}
.pick{position:relative;text-align:start;display:flex;flex-direction:column;gap:7px;padding:14px;border:1px solid var(--line2);border-radius:14px;
 background:var(--panel2);cursor:pointer;transition:border-color .15s,box-shadow .15s,transform .12s;color:inherit;width:100%;font:inherit;
 min-width:0;overflow:hidden;white-space:normal}
.pick>*{min-width:0;max-width:100%}
.pick:hover{border-color:var(--teal);transform:translateY(-2px)}
.pick:focus-visible{outline:none;border-color:var(--teal);box-shadow:0 0 0 4px rgba(53,224,208,.18)}
.pick[aria-checked="true"]{border-color:var(--teal);background:rgba(53,224,208,.07);box-shadow:0 0 0 1px var(--teal) inset}
.pick .pk-top{display:flex;align-items:center;gap:10px}
.pick .pk-ic{width:34px;height:34px;flex:none;display:flex;align-items:center;justify-content:center;color:var(--teal);
 background:rgba(53,224,208,.08);border:1px solid rgba(53,224,208,.25);border-radius:10px}
.pick .pk-ic svg{width:20px;height:20px}
.pick .pk-top{min-width:0}
.pick .pk-name{font-family:var(--disp);font-weight:600;font-size:14.5px;text-transform:capitalize;line-height:1.2;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.pick .pk-desc{font-size:12px;color:var(--mut);line-height:1.45;white-space:normal;overflow-wrap:anywhere}
.pick .pk-meta{display:flex;gap:6px;flex-wrap:wrap;margin-top:2px}
.pick .pk-check{position:absolute;top:11px;inset-inline-end:12px;color:var(--teal);opacity:0;font-weight:700}
.pick[aria-checked="true"] .pk-check{opacity:1}
/* selectable machine rows */
.mpick{display:flex;align-items:center;gap:14px;flex-wrap:wrap;padding:13px 15px;border:1px solid var(--line);border-radius:13px;
 background:var(--panel2);cursor:pointer;transition:border-color .15s,background-color .15s;width:100%;text-align:start;color:inherit;font:inherit;margin-top:9px}
.mpick:hover{border-color:var(--line2)}
.mpick:focus-visible{outline:none;border-color:var(--teal);box-shadow:0 0 0 4px rgba(53,224,208,.16)}
.mpick[aria-checked="true"]{border-color:var(--teal);background:rgba(53,224,208,.06)}
.mpick .mp-gpu{font-family:var(--disp);font-weight:600;font-size:14.5px;flex:1 1 150px;min-width:130px}
.mpick .mp-col{font-family:var(--mono);font-size:12px;color:var(--mut);flex:0 0 auto}
.mpick .mp-price{font-family:var(--disp);font-weight:700;color:var(--amber);font-size:15px;margin-inline-start:auto}
.seg{display:inline-flex;border:1px solid var(--line2);border-radius:999px;overflow:hidden;background:var(--panel2)}
.seg button{background:transparent;border:0;border-radius:0;color:var(--mut);font-family:var(--mono);font-size:11px;letter-spacing:.04em;padding:7px 13px;text-transform:uppercase}
.seg button[aria-pressed="true"]{background:rgba(53,224,208,.12);color:var(--teal)}
.compat{display:flex;align-items:center;gap:7px;font-size:12.5px;padding:3px 0}
.compat .ic{width:16px;height:16px;flex:none}
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
html[dir="rtl"] body{font-family:'Cairo','Inter',system-ui,sans-serif;font-size:15px}
html[dir="rtl"] h1,html[dir="rtl"] h2,html[dir="rtl"] h3{font-family:'Cairo','Sora',sans-serif;letter-spacing:0;font-weight:700}
html[dir="rtl"] .eyebrow,html[dir="rtl"] .lbl,html[dir="rtl"] .mini{letter-spacing:.05em}
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
  footer .fcols{gap:24px}
  footer .fcol{min-width:44%}
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
  <a href="/marketplace" data-ar="السوق">Marketplace</a><a href="/launch" data-ar="التشغيل">Launch</a><a href="/models" data-ar="النماذج">Models</a><a href="/cluster" data-ar="الحوسبة الموزعة">Distributed</a><a href="/catalog" data-ar="القوالب">Templates</a><a href="/pricing" data-ar="الأسعار">Pricing</a>
  <a href="/metrics" data-ar="المقاييس">Metrics</a><a href="/install" data-ar="لمالكي كروت الرسومات">For GPU owners</a><a href="/security" data-ar="الأمان">Security</a><a href="/wiki" data-ar="الويكي">Wiki</a><a href="/developers" data-ar="المطورون">Developers</a>
</div>
<div class="navcta">
  <a class="signin" id="adminlink" href="/admin" style="display:none">Admin</a>
  <a class="signin" id="consolelink" href="/console" style="display:none">Console</a>
  <a class="signin" id="mename" href="/account" style="display:none;color:var(--teal)"></a>
  <button class="themetoggle" onclick="toggleLang()" aria-label="Switch language" title="English / العربية" style="font-family:var(--mono);font-size:11px;font-weight:600" id="langbtn">AR</button>
  <button class="themetoggle" onclick="toggleTheme()" aria-label="Toggle light or dark theme" title="Toggle light / dark">
    <svg class="sun" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M2 12h2M20 12h2M5 5l1.4 1.4M17.6 17.6 19 19M19 5l-1.4 1.4M6.4 17.6 5 19"/></svg>
    <svg class="moon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8Z"/></svg>
  </button>
  <a class="signin" id="signinlink" href="/login">Sign in</a>
  <a class="signin" id="signoutlink" href="#" onclick="signout();return false" style="display:none">Sign out</a>
  <a class="btn btn-ghost" href="/demo" data-ar="احجز عرضاً">Book a demo</a>
  <a class="btn btn-amber" href="/console">Open console</a>
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
    <a href="/marketplace" data-ar="السوق">Marketplace</a><a href="/cluster" data-ar="الحوسبة الموزعة">Distributed</a><a href="/pricing" data-ar="الأسعار">Pricing</a><a href="/console">Console</a>
  </div>
  <div class="fcol"><div class="fh">Use cases</div>
    <a href="/artists">Rendering &amp; art</a><a href="/gamers">Game servers</a><a href="/developers">AI &amp; inference</a>
  </div>
  <div class="fcol"><div class="fh">Sell compute</div>
    <a href="/install">List your PC</a><a href="/account">Earnings</a><a href="/keys">API keys</a>
  </div>
  <div class="fcol"><div class="fh">Developers</div>
    <a href="/wiki">Wiki</a><a href="/docs">API reference</a><a href="/catalog" data-ar="القوالب">Templates</a><a href="/developers">Quickstart</a><a href="/keys">API keys</a>
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

# Auth is a browser HttpOnly cookie now (the JWT is NOT in localStorage, so an XSS payload
# can't read the session). The readable pb_csrf cookie is the double-submit token AND the
# "signed in" hint. No more #t=JWT fragment capture — the cookie is set server-side on login.
_AUTHJS = """<script>
(function(){try{var m=location.search.match(/[?&]ref=([A-Za-z0-9]{4,16})/);if(m){localStorage.setItem('pb_ref',m[1].toUpperCase());}}catch(e){}})();
function pbCookie(n){var m=document.cookie.match(new RegExp('(?:^|; )'+n.replace(/[.*+?^${}()|[\\]\\\\]/g,'\\\\$&')+'=([^;]*)'));return m?decodeURIComponent(m[1]):'';}
// The JWT lives in an HttpOnly cookie the browser attaches automatically; JS can't read it.
// tok() is kept only so CLI-facing curl snippets keep a slot; in the browser it is empty.
function tok(){return '';}
// HTML-escape any user-controlled value before it goes into innerHTML. Server-side
// validation (main.py _clean_label) already rejects HTML metachars at write time; this is
// defence-in-depth at the DOM sink and also neutralises any legacy row stored before that.
function esc(s){return String(s==null?'':s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');}
(function(){try{var p=location.pathname.replace(new RegExp('[/]$'),'')||'/';document.querySelectorAll('.navlinks a').forEach(function(a){if(a.getAttribute('href')===p)a.classList.add('active');});}catch(e){}})();
// signed-in hint = the readable CSRF cookie the server sets beside the HttpOnly session.
function authed(){return !!pbCookie('pb_csrf');}
async function api(p,o){o=o||{};o.headers=Object.assign({'Content-Type':'application/json'},o.headers||{});
 o.credentials='same-origin';                       // send the session cookie on same-origin calls
 var m=(o.method||'GET').toUpperCase();
 if(m!=='GET'&&m!=='HEAD'&&m!=='OPTIONS'){var ct=pbCookie('pb_csrf');if(ct)o.headers['X-CSRF-Token']=ct;}  // CSRF double-submit
 var r=await fetch(p,o);var b={};try{b=await r.json()}catch(e){}return {ok:r.ok,status:r.status,body:b};}
// Money-screen honesty: any page with a #pbtestmode slot shows a clear TEST-MODE banner while the
// platform is in sandbox / Stripe test mode — so no one ever mistakes a demo for a real charge.
async function pbTestBanner(){var el=document.getElementById('pbtestmode');if(!el)return;
 try{var r=await fetch('/payments/config');var c=await r.json();
  if(c&&c.test_mode){el.innerHTML='<div class="pb-testmode" role="status" data-ar="وضع تجريبي — لا تُخصم أي بطاقة حقيقية ولا تتحرك أي أموال حقيقية. للعروض فقط."><b>TEST MODE</b><span>No real card is charged and no real money moves — this is a sandbox for demos.</span></div>';}
  else{el.textContent='';}
 }catch(e){}}
document.addEventListener('DOMContentLoaded',pbTestBanner);
function toggleLang(){
  var h=document.documentElement, next=(h.getAttribute('dir')==='rtl')?'en':'ar';
  try{localStorage.setItem('pb_lang',next);}catch(e){}
  location.reload();
}
// Translate in place. Every translatable node carries data-ar; we swap innerHTML (NOT
// textContent — that would flatten child markup like gradient spans, links, <code> and <b>
// even for English readers) and flip direction. No separate Arabic build to drift out of sync.
function applyLang(){
  var ar = document.documentElement.getAttribute('dir')==='rtl';
  var b=document.getElementById('langbtn'); if(b) b.textContent = ar ? 'EN' : 'AR';
  document.querySelectorAll('[data-ar]').forEach(function(el){
    // Snapshot the ORIGINAL English markup once; data-ar is authored as plain text, so setting
    // innerHTML from it is safe (only ever our own server-rendered markup, never user input).
    if(!el.hasAttribute('data-en-html')) el.setAttribute('data-en-html', el.innerHTML);
    el.innerHTML = ar ? el.getAttribute('data-ar') : el.getAttribute('data-en-html');
  });
  document.querySelectorAll('[data-ar-ph]').forEach(function(el){
    if(!el.hasAttribute('data-en-ph')) el.setAttribute('data-en-ph', el.placeholder||'');
    el.placeholder = ar ? el.getAttribute('data-ar-ph') : el.getAttribute('data-en-ph');
  });
}
document.addEventListener('DOMContentLoaded', applyLang);

function toggleTheme(){var h=document.documentElement,t=h.getAttribute('data-theme')==='light'?'dark':'light';h.setAttribute('data-theme',t);h.setAttribute('data-bs-theme',t);try{localStorage.setItem('pb_theme',t);}catch(e){}}
// The session cookie is HttpOnly, so JS can't delete it — sign-out must hit the server, which
// clears it (POST /logout is CSRF-exempt). Redirect home regardless of the network outcome.
function signout(){try{fetch('/logout',{method:'POST',credentials:'same-origin'}).finally(function(){location.href='/';});}catch(e){location.href='/';}}
(function(){var si=document.getElementById('signinlink'),so=document.getElementById('signoutlink');
 if(authed()){if(si)si.style.display='none';if(so)so.style.display='';}else{if(si)si.style.display='';if(so)so.style.display='none';}})();
(async function(){try{if(authed()){var cl=document.getElementById('consolelink');if(cl)cl.style.display='';var r=await api('/me');if(r.ok){var m=document.getElementById('mename');if(m){m.textContent='● '+r.body.username;m.style.display='';}
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
 {t:"Launch compute",        h:"/launch",      k:"launch run workload template gpu ec2 configure new instance"},
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
      <input id="nl_email" type="email" data-ar-ph="بريدك الإلكتروني" placeholder="you@example.com" style="flex:1;min-width:200px;max-width:320px"/>
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
  <div id="demobadge" style="display:none;margin-top:8px"><span class="badge cc" title="This marketplace contains seeded demonstration nodes, clearly labelled and never counted as real traction.">Demo data — includes simulated nodes</span></div>
</div>
<script>
(async function(){try{var st=await (await fetch('/marketplace/stats')).json();
  if(st.contains_demo_data)document.getElementById('demobadge').style.display='';}catch(e){}})();
</script>
<div class="wrap" style="padding:12px 22px 30px">
  <div class="panel filterbar" style="padding:16px 18px;margin-bottom:14px">
    <div class="field"><span data-ar="طراز الكرت">GPU model</span><input id="fgpu" placeholder="H100, 4090…" size="10" onkeydown="if(event.key==='Enter')load()"/></div>
    <div class="field"><span data-ar="أقصى $/ساعة">Max $/hr</span><input id="fprice" type="number" placeholder="any" size="7" step="0.1" onkeydown="if(event.key==='Enter')load()"/></div>
    <div class="field"><span data-ar="أدنى ذاكرة">Min VRAM</span><input id="fvram" type="number" placeholder="GB" size="7" onkeydown="if(event.key==='Enter')load()"/></div>
    <div class="field"><span data-ar="المنطقة">Region</span><input id="fregion" placeholder="any" size="8" onkeydown="if(event.key==='Enter')load()"/></div>
    <div class="field"><span data-ar="ترتيب حسب">Sort by</span><select id="fsort" onchange="load()"><option value="price" data-ar="الأرخص">Cheapest</option><option value="rep" data-ar="الأكثر ثقة">Most trusted</option><option value="vram" data-ar="أكبر ذاكرة">Most VRAM</option></select></div>
    <label class="mini" style="display:flex;align-items:center;gap:6px;padding-bottom:9px"><input id="fconf" type="checkbox" style="width:15px;height:15px;padding:0"/> <span data-ar="سرّية">confidential</span></label>
    <div style="display:flex;gap:8px;padding-bottom:1px">
      <button class="btn btn-teal" onclick="load()" data-ar="تطبيق">Apply</button>
      <button class="btn-ghost btn" onclick="clearf()" data-ar="إعادة تعيين">Reset</button>
    </div>
  </div>
  <div class="panel" style="overflow:auto">
    <table class="tbl"><thead><tr><th data-ar="الكرت">GPU</th><th data-ar="الذاكرة">VRAM</th><th>$/hr</th><th data-ar="مقابل السحابة">vs cloud</th><th data-ar="الثقة">trust</th><th data-ar="المنطقة">region</th><th data-ar="السمعة">rep</th><th data-ar="متاح">free</th><th></th></tr></thead>
    <tbody id="mrows"><tr><td colspan="9" style="padding:24px;text-align:center" class="mut mono">loading…</td></tr></tbody></table>
  </div>
  <div style="margin-top:18px;display:flex;gap:14px;align-items:center;flex-wrap:wrap">
    <a class="btn btn-amber" href="/console" data-ar="سجّل الدخول للحجز ←">Sign in to book →</a>
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
 var tb=document.getElementById('mrows');if(!b.count){tb.innerHTML=pbEmpty(9,'No GPUs match','Widen your filters, or be the first to list one.','/install','List your GPU');return;}
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
   '<td data-l="Trust">'+(t.join(' ')||'<span class="mut mono" style="font-size:11px">standard</span>')+'</td>'+
   '<td data-l="Region" class="mut mono" style="font-size:12px">'+esc(s.region||'—')+'</td>'+
   '<td data-l="rep" class="mono" style="color:'+rc+'">'+rep+'</td>'+
   '<td data-l="free" class="mono" style="color:var(--teal)">'+s.available_units+'</td>'+
   '<td data-l="" class="tbl-action"><a class="btn btn-teal" style="padding:6px 13px;font-size:12px" href="/launch?spec='+s.id+'">Launch →</a></td></tr>';}).join('');}
load();setInterval(load,8000);
</script>""")


INSTALL_HTML = _page("Petabyte — become a seller",
    desc="List a GPU you already own and earn when it is idle. One command to install the agent. Your machine stays yours.", path="/install", body="""
<div class="wrap" style="padding:48px 22px 10px">
  <div class="eyebrow"><span class="dot"></span> <span data-ar="تسجيل جهاز">node onboarding</span></div>
  <h1 style="font-size:clamp(30px,5vw,40px);margin:16px 0 8px" data-ar="أدرِج كرت رسوماتك بأمرٍ واحد">List your GPU in <span class="grad-teal">one command</span></h1>
  <p class="mut" style="max-width:56ch" data-ar="أي جهاز NVIDIA يمكن أن يصبح عقدة. يتحقق المُثبِّت من عتادك، ويعزل المهام داخل Docker، ويجعلك متصلاً خلال ٣٠ ثانية تقريباً. دون حصرية.">Any NVIDIA machine can become a node. The installer verifies your hardware, sandboxes jobs in Docker, and brings you online in ~30 seconds. No exclusivity.</p>
</div>
<!-- PRIMARY path: as easy as starting a miner — paste a wallet, no account needed -->
<div class="wrap" style="padding:6px 22px 0">
  <div class="card" style="border-color:rgba(240,180,41,.35);background:linear-gradient(180deg,rgba(240,180,41,.06),transparent)">
    <div class="lbl am" data-ar="ابدأ مثل المُعدِّن · بلا حساب">Start like a miner · no account</div>
    <p class="mut" style="margin-bottom:6px" data-ar="الصق محفظة USDC التي تريد أن تُدفع إليها. هذه هويتك وعنوان استلامك — بلا بريد، بلا كلمة مرور. شغّل الأمر الوحيد الذي نعطيك إياه، ويتصل كرت رسوماتك. (السحب لاحقاً يتطلب تحقق هوية سريع كما يفرض النظام.)">Paste the USDC wallet you want to be paid to. That's your identity <i>and</i> your payout address — no email, no password. Run the one command we hand back and your GPU is online. <b class="teal">Withdrawing later needs a quick identity check</b>, as regulation requires.</p>
    <div style="display:flex;gap:10px;flex-wrap:wrap;align-items:center;margin-top:10px">
      <input id="qwallet" placeholder="0x… your USDC wallet" size="30" spellcheck="false" style="font-family:ui-monospace,monospace;min-width:min(340px,90vw)" onkeydown="if(event.key==='Enter')walletStart(null,this)"/>
      <button class="btn-amber" id="qbtn" data-act="walletStart" data-ar="أنشئ أمر التثبيت">Create my installer</button>
      <span id="qmsg" class="mono" style="font-size:12.5px"></span>
    </div>
    <p class="mut" style="font-size:11.5px;margin-top:9px" data-ar="USDC على إيثريوم أو بوليجون أو Base أو Arbitrum أو Optimism. نفحص العناوين مقابل قائمة OFAC.">USDC on Ethereum, Polygon, Base, Arbitrum or Optimism. Addresses are screened against the OFAC sanctions list.</p>
  </div>
</div>
<div class="wrap" style="padding:14px 22px 0"><div class="mut" style="font-size:12px;text-align:center;letter-spacing:.04em" data-ar="أو استخدم حساباً كاملاً لتحديد سعر مخصص">— or use a full account to set a custom price —</div></div>
<!-- signed OUT: one prompt to sign in, nothing else to read yet -->
<div class="wrap" id="iksignin" style="padding:6px 22px 0;display:none">
  <div class="card" style="border-color:rgba(79,214,201,.3);background:linear-gradient(180deg,rgba(79,214,201,.05),transparent)">
    <div class="lbl" data-ar="الخطوة ١ · سجّل الدخول">Step 1 · sign in</div>
    <p class="mut" data-ar="تتصل الأجهزة عبر مفتاح API — لا تُخزَّن أي كلمة مرور على الجهاز إطلاقاً. سجّل الدخول أو أنشئ حساباً مجانياً لتوليد أمر التثبيت الجاهز.">Nodes connect with an API key — no password ever lives on the machine. <a class="teal" href="/login">Sign in or create a free account</a> and your ready-to-paste installer appears right here.</p>
  </div>
</div>
<!-- signed IN: pick a price (optional) and generate the exact command in one click -->
<div class="wrap" id="ikgen" style="padding:6px 22px 0;display:none">
  <div class="card" style="border-color:rgba(79,214,201,.3);background:linear-gradient(180deg,rgba(79,214,201,.05),transparent)">
    <div class="lbl" data-ar="الخطوة ١ · حدّد سعرك (اختياري)">Step 1 · set your price <span class="mut">(optional)</span></div>
    <p class="mut" style="margin-bottom:12px" data-ar="اكتب اسم كرت رسوماتك لرؤية سعر عادل بالساعة، مبني على مرجع الأداء والأجهزة الحيّة. أو اترك الخانة فارغة وسيسعّر كل جهاز نفسه تلقائياً من مقياس أداء كرت رسوماته حين يتصل — لا حاجة لتخمين رقم.">Type your GPU to see a fair hourly price — built from the performance benchmark and live nodes. Or leave it blank: each node auto-prices from its own GPU's benchmark when it comes online, so you never have to guess a number.</p>
    <div style="display:flex;gap:10px;flex-wrap:wrap;align-items:center">
      <input id="pgpu" placeholder="e.g. RTX 4090" size="14" onkeydown="if(event.key==='Enter')sugPrice()"/>
      <button class="btn btn-teal" data-act="sugPrice" data-ar="اقترح">Suggest</button>
      <span class="mut">$</span>
      <input id="pprice" placeholder="auto" size="4" inputmode="decimal" style="text-align:right"/>
      <span class="mut">/hr</span>
      <span id="psug" class="mono mut" style="font-size:12.5px"></span>
    </div>
    <div style="margin-top:18px">
      <button class="btn-amber" id="genbtn" data-act="genInstaller" data-ar="أنشئ مفتاحي وأمر التثبيت">Create my node key &amp; installer command</button>
    </div>
  </div>
</div>
<!-- generated result: real key + this server's address + your price, already filled in -->
<div class="wrap" id="ikout" style="padding:12px 22px 6px;display:none">
  <div class="mini" style="margin:6px 0 10px" data-ar="الخطوة ٢ · شغّل هذا على جهازك">Step 2 · run this on your GPU machine</div>
  <p class="mut" style="max-width:64ch;margin-bottom:12px" data-ar="أمر واحد يثبّت الوكيل، يقيس أداء كرت رسوماتك، ويتصل — لا مفتاح تلصقه، ولا خطوات تفاعلية. إن لم تحدد سعراً، يسعّر الجهاز نفسه من مقياس الأداء. عامل هذا الرابط كأنه كلمة مرور: كل تشغيل يُسجّل جهازاً باسم حسابك، وينتهي خلال ٣٠ يوماً.">One command installs the agent, benchmarks your GPU, and brings the node online — <b class="teal">no key to paste, nothing interactive</b>. If you didn't set a price, the node auto-prices from its benchmark. Treat this link like a password: each run enrols a worker under your account, and it expires in 30 days.</p>
  <div class="cols c2">
    <div class="card"><div class="lbl" data-ar="لينكس · ماك">Linux · macOS <span class="mut">— paste in a terminal</span></div>
      <pre id="cmdlinux" style="white-space:pre-wrap;word-break:break-all"></pre>
      <button class="btn btn-teal" style="margin-top:10px" data-act="pbCopy" data-a1="seller_linux" data-ar="نسخ">Copy command</button></div>
    <div class="card"><div class="lbl" data-ar="ويندوز · PowerShell (يثبّت WSL2)">Windows · PowerShell <span class="mut">(installs WSL2)</span></div>
      <pre id="cmdwin" style="white-space:pre-wrap;word-break:break-all"></pre>
      <button class="btn btn-teal" style="margin-top:10px" data-act="pbCopy" data-a1="seller_win" data-ar="نسخ">Copy command</button>
      <p class="mut" style="font-size:12px;margin-top:9px" data-ar="شغّله في PowerShell بصلاحيات المدير.">Run in an elevated PowerShell window.</p></div>
  </div>
  <div class="card" style="margin-top:14px"><div class="lbl" data-ar="ثم راقبه وهو يتصل">Then watch it come online</div>
    <pre>systemctl status petabyte-agent
journalctl -u petabyte-agent -f</pre>
    <p class="mut" style="font-size:13px;margin-top:9px" data-ar="يظهر كرت رسوماتك في السوق ولوحة التحكم خلال دقيقة.">Your GPU appears in the <a class="teal" href="/marketplace">marketplace</a> and your <a class="teal" href="/console">dashboard</a> within a minute.</p>
  </div>
</div>
<div class="wrap" style="padding:12px 22px 30px">
  <div class="card"><div class="lbl" data-ar="جرّبه دون مخاطرة">Try it risk-free</div>
    <p class="mut" data-ar="يعمل الوكيل داخل بيئة لينكس معزولة — لا يمسّ ألعابك أو ملفاتك، ويعمل فقط حين يكون جهازك خاملاً. أوقفه مؤقتاً متى شئت، أو أزِله تماماً بأمرٍ واحد. وإذا فعّلت Petabyte خاصية WSL لك، فإن إلغاء التثبيت يعيدها كما كانت.">The agent runs in an isolated Linux sandbox — it never touches your games or files, and only works when your PC is idle. <b class="teal">Pause</b> anytime, or <b class="teal">remove it completely</b> in one command. If Petabyte turned on WSL for you, uninstalling turns it back off.</p>
    <pre style="margin-top:10px">$env:PETABYTE_ACTION="pause";     irm https://petabyte.market/manage.ps1 | iex
$env:PETABYTE_ACTION="uninstall"; irm https://petabyte.market/manage.ps1 | iex</pre>
  </div>
  <div class="card" style="margin-top:16px"><div class="lbl am" data-ar="استلم أرباحك">Get paid</div>
    <p class="mut" data-ar="رصيد واحد. اسحب في أي وقت أو وفق جدول أسبوعي — تحويل بنكي أو USDC أو بطاقة هدية. فعّل خيار التعدين عند الخمول لتكسب دخلاً في الخلفية كلما لم يكن جهازك مؤجراً.">One balance. Withdraw anytime or on a weekly schedule — bank, USDC, or gift card. Opt in to idle-fallback and earn a background trickle whenever the node isn't rented. <a class="teal" href="/console">Open the console →</a></p>
  </div>
  <div class="card" style="margin-top:16px"><div class="lbl" data-ar="تفكّر في شراء كرت رسومات؟">Thinking of buying a GPU to rent?</div>
    <p class="mut" data-ar="احسب الأرباح الصافية، ومتى يسترد الكرت ثمنه، والعائد السنوي لكل كرت — بأرقام شفافة يمكنك تعديلها.">See net earnings, payback time and 1-year ROI per card — transparent numbers you can tune to your own electricity and utilization. <a class="teal" href="/roi">Open the ROI calculator →</a></p>
  </div>
</div>
<script>
function _esch(s){return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}
async function sugPrice(){var g=(document.getElementById('pgpu').value||'').trim();
  try{var r=await fetch('/pricing/suggest?gpu_model='+encodeURIComponent(g));var b=await r.json();
    if(b&&b.suggested_price){document.getElementById('pprice').value=Number(b.suggested_price).toFixed(2);}
    document.getElementById('psug').innerHTML=(b&&b.suggested_price)?('· '+b.basis+' · cloud ≈ $'+b.cloud_reference):'';
  }catch(e){document.getElementById('psug').textContent='';}}
async function genInstaller(a1, btn){
  if(!authed()){location.href='/login';return;}
  if(btn&&btn.disabled)return;
  var lbl=btn?btn.textContent:'';
  if(btn){btn.disabled=true;btn.textContent='Creating…';}
  // Explicit price pins the rate; a blank field lets each node auto-price from its GPU benchmark.
  var pt=(document.getElementById('pprice').value||'').trim(), pn=parseFloat(pt);
  var body=(pt!==''&&pn>0)?JSON.stringify({price:pn}):JSON.stringify({});
  var r=await api('/nodes/install_token',{method:'POST',body:body});
  if(btn){btn.disabled=false;btn.textContent=lbl;}
  if(!(r.ok&&r.body&&r.body.install)){alert('Could not create your installer — please make sure you are signed in.');return;}
  _renderCmds(r.body.install.linux, r.body.install.windows);
}
// Fill the two command boxes from the server-built one-liners and reveal them. The whole command
// is a single curl|bash / irm|iex — no key to paste, nothing interactive. Shared by both paths.
function _renderCmds(linux, win){
  window._PBCMDS['seller_linux']=linux; window._PBCMDS['seller_win']=win;
  document.getElementById('cmdlinux').innerHTML=_esch(linux);
  document.getElementById('cmdwin').innerHTML=_esch(win);
  var out=document.getElementById('ikout'); out.style.display='';
  out.scrollIntoView({behavior:'smooth',block:'start'});
}
// Wallet-only path: no login. Paste a USDC wallet -> a token-bound one-liner comes back.
async function walletStart(a1, btn){
  var w=(document.getElementById('qwallet').value||'').trim();
  var msg=document.getElementById('qmsg');
  if(!/^0x[0-9a-fA-F]{40}$/.test(w)){ msg.style.color='var(--amber)';
    msg.textContent='Enter a 0x… wallet address (42 characters).'; return; }
  if(btn&&btn.disabled)return; var lbl=btn?btn.textContent:'';
  if(btn){btn.disabled=true;btn.textContent='Creating…';} msg.textContent='';
  try{
    var r=await fetch('/nodes/quickstart',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({wallet:w})});
    var b=await r.json();
    if(btn){btn.disabled=false;btn.textContent=lbl;}
    if(!r.ok || !b.install){ msg.style.color='var(--amber)';
      msg.textContent=(b&&b.detail)?b.detail:'Could not create your installer — try again.'; return; }
    msg.style.color='var(--teal)'; msg.textContent='✓ ready below';
    _renderCmds(b.install.linux, b.install.windows);
  }catch(e){ if(btn){btn.disabled=false;btn.textContent=lbl;}
    msg.style.color='var(--amber)'; msg.textContent='Network error — try again.'; }
}
(function(){var si=document.getElementById('iksignin'),gn=document.getElementById('ikgen');
  if(authed()){if(gn)gn.style.display='';}else{if(si)si.style.display='';}})();
</script>""")


ROI_HTML = _page("Petabyte — GPU ROI calculator",
    desc="Buy a GPU and rent it: see net earnings, payback time and 1-year ROI per card. Transparent math, editable assumptions, live benchmark-anchored prices.",
    path="/roi", body="""
<div class="wrap" style="padding:48px 22px 10px">
  <div class="eyebrow"><span class="dot"></span> <span data-ar="حاسبة العائد">rig economics</span></div>
  <h1 style="font-size:clamp(30px,5vw,40px);margin:16px 0 8px" data-ar="اشترِ كرت رسومات وأجّره — متى يسترد ثمنه؟">Buy a GPU and rent it — <span class="grad-teal">when does it pay for itself?</span></h1>
  <p class="mut" style="max-width:64ch" data-ar="نعرض لك الحساب كاملاً: الأرباح بالساعة (من سعر السوق المرتكز على الأداء) ناقص عمولة المنصة والكهرباء، مقابل تكلفة العتاد. عدّل الافتراضات وشاهد نقطة التعادل والعائد السنوي.">Here's the full math: earnings per hour (from the benchmark-anchored market price) minus our fee and electricity, against what the card costs. Tune the assumptions and watch the breakeven and 1-year ROI change.</p>
</div>
<div class="wrap" style="padding:6px 22px 0">
  <div class="card" style="border-color:rgba(240,180,41,.30);background:linear-gradient(180deg,rgba(240,180,41,.05),transparent)">
    <b class="amber" data-ar="هذا نموذج، وليس وعداً.">This is a model, not a promise.</b>
    <span class="mut" data-ar="أكبر عامل هو عدد ساعات التأجير يومياً — وهو يعتمد على الطلب، والطلب ما زال مبكّراً. اضبطه على ما تتوقعه. اختر «الكرت فقط» أو «الحاسوب كامل» (يضيف تكلفة بقية القطع واستهلاكها). تكلفة العتاد افتراضها سعر الإطلاق؛ اكتب سعر اليوم. الكهرباء تُحسب أثناء ساعات التشغيل فقط.">The biggest factor is <b>how many hours a day it's actually rented</b> — that's demand-dependent, and demand is still early. Set it to what you realistically expect. Choose <b>GPU-only</b> or <b>whole PC</b> (adds the rest-of-build cost + its power). Hardware cost defaults to launch MSRP — type today's real price. Electricity counts load only while it's running.</span>
  </div>
</div>
<div class="wrap" style="padding:14px 22px 0">
  <div class="cols c3">
    <div class="card"><div class="lbl" data-ar="ساعات التأجير يومياً">Hours rented per day</div>
      <div style="display:flex;align-items:center;gap:12px">
        <input id="hours" type="range" min="0" max="24" value="8" step="1" style="flex:1" oninput="roiRecalc()"/>
        <b class="mono teal" id="hoursv" style="min-width:5ch;text-align:right">8 h</b>
      </div>
      <p class="mut" style="font-size:12px;margin-top:6px" data-ar="غيّرها من ساعة واحدة إلى ٢٤. كن متحفظاً في البداية.">Drag from 1 to 24. Be conservative early on.</p></div>
    <div class="card"><div class="lbl" data-ar="سعر الكهرباء">Electricity — $ per kWh</div>
      <div style="display:flex;align-items:center;gap:10px">
        <span class="mut">$</span>
        <input id="kwh" value="0.12" size="5" inputmode="decimal" style="text-align:right" oninput="roiRecalc()"/>
        <span class="mut">/ kWh</span>
      </div>
      <p class="mut" style="font-size:12px;margin-top:6px" data-ar="متوسط أمريكا ≈ ٠٫١٧. استخدم سعر فاتورتك.">US avg ≈ $0.17. Use your bill's rate.</p></div>
    <div class="card"><div class="lbl" data-ar="ما الذي تحسبه؟">Cost & power of…</div>
      <div style="display:flex;gap:8px;flex-wrap:wrap">
        <button id="scopeGpu" class="btn btn-teal" data-ar="الكرت فقط" onclick="roiScope(false)">Just the GPU</button>
        <button id="scopePc" class="btn" data-ar="الحاسوب كامل" onclick="roiScope(true)">Whole PC</button>
      </div>
      <p class="mut" id="scopeNote" style="font-size:12px;margin-top:8px"></p></div>
  </div>
</div>
<div class="wrap" style="padding:14px 22px 6px">
  <div id="roihead" class="mut mono" style="font-size:13px;margin-bottom:10px"></div>
  <div style="overflow-x:auto">
    <table style="width:100%;border-collapse:collapse;min-width:760px" class="mono">
      <thead><tr style="text-align:left;border-bottom:1px solid var(--line)">
        <th style="padding:8px 10px" data-ar="الكرت">GPU</th>
        <th style="padding:8px 10px" data-ar="تحتفظ/ساعة">You keep /hr</th>
        <th style="padding:8px 10px" data-ar="كهرباء/ساعة">Power /hr</th>
        <th style="padding:8px 10px" id="thcost" data-ar="تكلفة العتاد">Hardware $</th>
        <th style="padding:8px 10px" data-ar="صافي/شهر">Net /mo</th>
        <th style="padding:8px 10px" data-ar="التعادل">Breakeven</th>
        <th style="padding:8px 10px" data-ar="العائد السنوي">1-yr ROI</th>
        <th style="padding:8px 10px" data-ar="اشترِ">Buy</th>
      </tr></thead>
      <tbody id="roirows"><tr><td colspan="8" class="mut" style="padding:14px 10px">Loading…</td></tr></tbody>
    </table>
  </div>
  <p id="roidisc" class="mut" style="font-size:11.5px;margin-top:12px"></p>
  <p class="mut" style="font-size:11.5px;margin-top:4px" data-ar="الأرباح مبنية على السعر المرجعي المرتكز على أداء الكرت (ما يدفعه المشتري) ناقص عمولتنا؛ السعر الفعلي يحدده البائع والطلب. لا شيء هنا مضمون.">Earnings use the benchmark-anchored reference price (what a buyer pays) minus our fee; the real price is set by the seller and demand. Nothing here is guaranteed.</p>
  <div style="margin-top:18px"><a class="btn btn-amber" href="/install" data-ar="ابدأ مثل المُعدِّن ←">Start earning — paste your wallet →</a></div>
</div>
<div class="wrap" style="padding:22px 22px 40px">
  <div class="lbl" style="margin-bottom:12px" data-ar="عتاد وأدوات مفيدة">Gear &amp; tools for your rig</div>
  <div id="gearlist" class="cols c3"></div>
  <p id="geardisc" class="mut" style="font-size:11.5px;margin-top:12px"></p>
</div>
<script>
var _ROI=null, _FULL=false;
function _e2(s){return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}
function _money(n){return (n>=0?'':'-')+'$'+Math.abs(n).toFixed(2);}
function roiScope(full){ _FULL=full;
  var a=document.getElementById('scopePc'), b=document.getElementById('scopeGpu');
  a.className=full?'btn btn-teal':'btn'; b.className=full?'btn':'btn btn-teal';
  for(var i=0;_ROI&&i<_ROI.gpus.length;i++){ _ROI.gpus[i]._cost=null; }  // reset overrides on scope change
  roiRecalc(); }
function roiCost(el){ if(!_ROI)return; var g=el.getAttribute('data-g'); var v=parseFloat(el.value);
  for(var i=0;i<_ROI.gpus.length;i++){ if(_ROI.gpus[i].gpu_model===g){ _ROI.gpus[i]._cost=(v>0?v:null); } }
  roiRecalc(); }
function _defCost(g){ return g.gpu_cost_usd + (_FULL?g.system_cost_ref:0); }
function roiRecalc(){
  if(!_ROI)return;
  var hours=parseFloat(document.getElementById('hours').value); if(!(hours>=0))hours=0;
  var kwh=parseFloat((document.getElementById('kwh').value||'').trim()); if(!(kwh>=0))kwh=0;
  document.getElementById('hoursv').textContent=hours+' h';
  var rows=_ROI.gpus.map(function(g){
    var watts=g.gpu_tdp_w+(_FULL?g.system_watts_ref:0);
    var cost=(g._cost&&g._cost>0)?g._cost:_defCost(g);
    var powerHr=(watts/1000)*kwh;
    var netHr=g.net_price_per_hr-powerHr;              // per rented hour, after power
    var netDay=netHr*hours, netMo=netDay*30;
    var be=(netDay>0)?(cost/netDay):null;             // days
    var roi=(cost>0)?(netDay*365/cost*100):null;
    return {g:g,watts:watts,cost:cost,powerHr:powerHr,netMo:netMo,be:be,roi:roi};
  });
  rows.sort(function(a,b){ var an=(a.be==null),bn=(b.be==null); if(an!==bn)return an?1:-1; return (a.be||0)-(b.be||0); });
  var html=rows.map(function(r){
    var g=r.g;
    var beTxt=(r.be==null)?'<span class="mut">— never</span>':((r.be<60)?(r.be.toFixed(0)+' days'):((r.be/30).toFixed(1)+' mo'));
    var beColor=(r.be==null)?'var(--mut)':((r.be<270)?'var(--teal)':((r.be<540)?'var(--amber)':'var(--mut)'));
    var roiTxt=(r.roi==null)?'—':(r.roi.toFixed(0)+'%/yr');
    var buys=(g.buy_urls||[]).map(function(b){return '<a class="teal" href="'+b.url+'" target="_blank" rel="noopener nofollow sponsored">'+_e2(b.retailer)+'</a>';}).join(' · ');
    return '<tr style="border-bottom:1px solid var(--line)">'+
      '<td style="padding:8px 10px"><b>'+_e2(g.gpu_model)+'</b> <span class="mut" style="font-size:11px">'+(g.benchmark_tflops_fp16||'')+' TF · '+r.watts+'W</span></td>'+
      '<td style="padding:8px 10px">$'+g.net_price_per_hr.toFixed(2)+'</td>'+
      '<td style="padding:8px 10px" class="mut">'+_money(r.powerHr)+'</td>'+
      '<td style="padding:8px 10px"><span class="mut">$</span><input data-g="'+_e2(g.gpu_model)+'" value="'+Math.round(r.cost)+'" size="5" inputmode="decimal" style="width:6ch;text-align:right;background:transparent;border:1px solid var(--line);border-radius:6px;color:inherit;padding:2px 4px" oninput="roiCost(this)"/></td>'+
      '<td style="padding:8px 10px;color:'+(r.netMo>0?'var(--teal)':'var(--mut)')+'">'+_money(r.netMo)+'</td>'+
      '<td style="padding:8px 10px;color:'+beColor+'">'+beTxt+'</td>'+
      '<td style="padding:8px 10px">'+roiTxt+'</td>'+
      '<td style="padding:8px 10px">'+buys+'</td>'+
      '</tr>';
  }).join('');
  document.getElementById('roirows').innerHTML=html||'<tr><td colspan="8" class="mut" style="padding:14px 10px">No data.</td></tr>';
  var a=_ROI.assumptions;
  document.getElementById('thcost').textContent=_FULL?'Whole-PC $':'GPU $';
  document.getElementById('scopeNote').textContent=_FULL
    ?('Adds ~$'+a.system_cost_ref_usd+' and ~'+a.system_watts_ref+'W for the rest of the build (editable per row).')
    :('Just the card. Switch to Whole PC to add ~$'+a.system_cost_ref_usd+' + ~'+a.system_watts_ref+'W for CPU/board/PSU/etc.');
  document.getElementById('roihead').textContent='Rented '+hours+' h/day at $'+kwh.toFixed(2)+'/kWh, after our '+a.platform_fee_pct+'% fee, '+(_FULL?'whole-PC':'GPU-only')+' — soonest payback first:';
}
(function(){
  fetch('/pricing/roi').then(function(r){return r.json();}).then(function(d){
    _ROI=d;
    var disc=(d.affiliate&&d.affiliate.disclosure)?d.affiliate.disclosure:'';
    if(d.affiliate&&!d.affiliate.enabled){ disc+=' (Affiliate programs not enabled yet — links are plain, non-monetised searches.)'; }
    document.getElementById('roidisc').textContent=disc;
    roiScope(false);
  }).catch(function(e){ document.getElementById('roirows').innerHTML='<tr><td colspan="8" class="mut" style="padding:14px 10px">Could not load pricing.</td></tr>'; });
  fetch('/partners').then(function(r){return r.json();}).then(function(d){
    var el=document.getElementById('gearlist'); if(!el)return;
    el.innerHTML=(d.partners||[]).map(function(p){
      return '<div class="card"><div class="lbl" style="font-size:11px;letter-spacing:.04em">'+_e2(p.category)+'</div>'+
        '<a class="teal" href="'+p.url+'" target="_blank" rel="noopener nofollow sponsored" style="font-weight:600">'+_e2(p.name)+' →</a>'+
        '<p class="mut" style="font-size:12.5px;margin-top:6px">'+_e2(p.blurb)+'</p></div>';
    }).join('');
    var gd=document.getElementById('geardisc');
    if(gd){ gd.textContent=(d.affiliate&&d.affiliate.disclosure)?d.affiliate.disclosure:''; }
  }).catch(function(e){});
})();
</script>""")


DEVELOPERS_HTML = _page("Petabyte — developers",
    desc="Two APIs: rent GPUs and run jobs (Developer API), or buy live GPU-market data (Data API). Interactive Scalar references, scoped keys, try-free sandbox.", path="/developers", body="""
<div class="wrap" style="padding:48px 22px 10px">
  <div class="eyebrow"><span class="dot"></span> API reference</div>
  <h1 style="font-size:clamp(30px,5vw,40px);margin:16px 0 8px">Build on the <span class="grad-teal">exchange</span></h1>
  <p class="mut">Two products, two references. REST + JSON · keys on the <a class="teal" href="/keys">keys page</a>.</p>
</div>
<div class="wrap" style="padding:12px 22px 8px">
  <div class="cols c2">
    <div class="card" style="border-color:rgba(255,183,77,.32);background:linear-gradient(180deg,rgba(255,183,77,.06),transparent)">
      <div class="lbl am">Developer API <span class="mut">· build compute</span></div>
      <p class="mut" style="font-size:13.5px;margin:6px 0 12px">Rent verified GPUs by the hour with escrow, deploy workloads and templates, run jobs, manage wallet &amp; payouts. Scoped keys carry <code class="teal">node</code> / <code class="teal">jobs</code>.</p>
      <a class="btn btn-amber arrow-fwd" href="/devs">Open the Developer API reference </a>
    </div>
    <div class="card" style="border-color:rgba(79,214,201,.32);background:linear-gradient(180deg,rgba(79,214,201,.06),transparent)">
      <div class="lbl">Data API <span class="mut">· buy market data</span></div>
      <p class="mut" style="font-size:13.5px;margin:6px 0 12px">Live GPU price index, history, savings, supply, demand, workloads, templates and the authenticity dataset. Metered, pay-as-you-go. Scoped key carries <code class="teal">data</code>.</p>
      <a class="btn btn-teal arrow-fwd" href="/data">Open the Data API reference </a>
    </div>
  </div>
  <div class="card" style="margin-top:14px;border-color:rgba(255,255,255,.10)">
    <p class="mut" style="font-size:12.5px;margin:0"><b>Two products, two references — they share no endpoint.</b> Nothing in the Data API appears in the Developer API, and vice-versa. The Data API is gated to <code class="teal">data</code>-scoped keys — a <code class="teal">node</code>/<code class="teal">jobs</code> key is refused there (403). Full combined schema at <a class="teal" href="/docs">/docs</a>.</p>
  </div>
</div>
<div class="wrap" style="padding:20px 22px 6px">
  <div class="eyebrow"><span class="dot"></span> quick reference</div>
</div>
<div class="wrap" style="padding:8px 22px 30px">
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
    <div class="card"><div class="lbl">Distributed <span class="mut">· 1 job, N GPUs</span></div>
      <p class="mono" style="font-size:12.5px;line-height:2.05">
      POST /distributed <span class="mut">cluster across N machines</span><br>
      POST /jobs/rendezvous <span class="mut">each rank posts VPN addr</span><br>
      GET /jobs/{id}/hostfile <span class="mut">MPI / torchrun hostfile</span><br>
      GET /jobs/{id}/cluster <span class="mut">nodes + launch cmds</span></p>
      <p class="mut" style="font-size:12px;margin-top:8px">Split one job across up to 100 GPUs on <b>different machines</b>, wired into one <b>torchrun/NCCL cluster over the VPN</b>. Gang-scheduled (one rank per PC), escrowed all-or-nothing.</p></div>
    <div class="card"><div class="lbl">Use your own scheduler <span class="mut">· another provider</span></div>
      <p class="mut" style="font-size:13px;margin:4px 0 8px">Already on <b>Slurm, MPI, Ray or Kubernetes</b>? Don't change your stack — burst into Petabyte as an extra node pool. The cluster exports as the artifacts your launcher already reads:</p>
      <p class="mono" style="font-size:12px;line-height:1.9">
      mpirun --hostfile hostfile -np N …<br>
      torchrun --master_addr=&lt;rank0&gt; …<br>
      ray start --address=&lt;rank0&gt;<br>
      slurm: ResumeProgram → POST /distributed</p>
      <p class="mut" style="font-size:12px;margin-top:6px">Petabyte is another provider, not an infra change.</p></div>
    <div class="card"><div class="lbl am">Wallet &amp; payouts</div>
      <p class="mono" style="font-size:12.5px;line-height:2.05">
      GET /wallet <span class="mut">balance + earnings</span><br>
      POST /wallet/methods <span class="mut">gift · USDC · bank</span><br>
      POST /wallet/withdraw <span class="mut">cash out (free / ⚡instant)</span></p></div>
    <div class="card"><div class="lbl">Data API <span class="mut">· metered</span></div>
      <p class="mono" style="font-size:12.5px;line-height:2.05">
      GET /api/v1/data/gpu-prices <span class="mut">price index</span><br>
      GET /api/v1/data/gpu-prices/history <span class="mut">time-series</span><br>
      GET /api/v1/data/savings <span class="mut">vs-cloud index</span><br>
      GET /api/v1/data/availability <span class="mut">live supply</span><br>
      GET /api/v1/data/demand <span class="mut">bookings, GMV, realized $/hr</span><br>
      GET /api/v1/data/workloads <span class="mut">job &amp; template mix</span><br>
      GET /api/v1/data/templates <span class="mut">templates bought: jobs, buyers, GMV, models</span><br>
      GET /api/v1/data/market <span class="mut">inventory summary</span><br>
      GET /api/v1/data/benchmarks <span class="mut">authenticity dataset</span><br>
      GET /api/v1/data/usage <span class="mut">your quota (free)</span></p>
      <p class="mut" style="font-size:12px;margin-top:8px">Needs a <code class="teal">data</code>-scoped key. A free monthly quota, then pay-as-you-go from your wallet balance. Datasets are aggregate/anonymized — no seller identity.</p></div>
    <div class="card" style="border-color:rgba(79,214,201,.3);background:linear-gradient(180deg,rgba(79,214,201,.05),transparent)">
      <div class="lbl">Try it free <span class="mut">· no signup</span></div>
      <p class="mut" style="font-size:12.5px;margin:2px 0 10px">Two ways to explore before you spend a cent:</p>
      <p class="mono" style="font-size:12.5px;line-height:1.9">
      <b class="teal">1 · Dummy data, keyless.</b> Example payloads for every dataset:</p>
      <div class="codeline" style="margin:6px 0 12px"><code>curl -s https://petabyte.market/api/v1/data/sample</code></div>
      <p class="mono" style="font-size:12.5px;line-height:1.9">
      <b class="teal">2 · Real data, sandbox key.</b> Live endpoints, free &amp; unmetered:</p>
      <div class="codeline" style="margin:6px 0 8px"><code>curl -s https://petabyte.market/api/v1/data/gpu-prices -H "X-API-KEY: {{SANDBOX_KEY}}"</code></div>
      <p class="mut" style="font-size:12px;margin-top:8px">The sandbox key <code class="teal">{{SANDBOX_KEY}}</code> is read-only, never billed, and safe to publish. When you're ready for production, mint a <code class="teal">data</code>-scoped key and top up your wallet.</p></div>
  </div>
  <div style="margin-top:18px;display:flex;gap:12px;flex-wrap:wrap">
    <a class="btn btn-amber" href="/devs">Developer API reference →</a>
    <a class="btn btn-teal" href="/data">Data API reference →</a>
    <a class="btn" href="/docs" style="border:1px solid rgba(255,255,255,.18)">Full schema (/docs) →</a>
  </div>
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
<div class="wrap" style="padding:22px 22px 0">
  <div id="inv_live" class="panel" style="display:none;padding:18px 20px;border-inline-start:3px solid var(--teal);background:linear-gradient(100deg,rgba(79,214,201,.07),rgba(44,158,155,.03))">
    <div class="lbl">Live traction <span class="mini mut mono" id="inv_asof"></span></div>
    <div class="stats" style="margin-top:10px">
      <div class="stat"><div class="n grad-teal" id="inv_gmv">—</div><div class="l">GMV (captured, live)</div></div>
      <div class="stat"><div class="n teal" id="inv_jobs">—</div><div class="l">Paid jobs</div></div>
      <div class="stat"><div class="n" id="inv_gpus">—</div><div class="l">GPUs online</div></div>
      <div class="stat"><div class="n" id="inv_take">—</div><div class="l">Gross take rate</div></div>
    </div>
    <p class="mini mut" style="margin-top:8px">Live, LIVE-money-only figures from the ledger. <a class="teal" href="/traction">Full traction →</a></p>
  </div>
</div>
<div class="wrap" style="padding:22px 22px 8px">
  <div class="stats">
    <div class="stat"><div class="n grad-teal">Live</div><div class="l">Core marketplace infra</div></div>
    <div class="stat"><div class="n teal">500+</div><div class="l">CI assertions, both DB engines</div></div>
    <div class="stat"><div class="n teal">&lt;HS</div><div class="l">vs hyperscaler on-demand</div></div>
    <div class="stat"><div class="n teal">Pre</div><div class="l">Revenue stage</div></div>
  </div>
  <p class="mini mut" style="margin-top:12px;text-align:center">Numbers are wired to the ledger, not the deck — see <a class="teal" href="/traction">live traction</a> and <a class="teal" href="/trust">verifiable receipts</a>.</p>
</div>
<div class="wrap" style="padding:22px 22px 8px">
  <div class="card" style="text-align:center;background:linear-gradient(100deg,rgba(245,178,61,.08),rgba(79,214,201,.05));border-color:rgba(79,214,201,.3)">
    <p style="font-family:var(--disp);font-weight:600;font-size:18px">Building the Gulf's compute exchange.</p>
    <p class="mut" style="margin-top:7px">For the deck, model, and a live demo — <a class="teal" href="mailto:info@petabyte.market">info@petabyte.market</a></p>
  </div>
</div>
<script>
(async function(){
  try{
    var r=await api('/metrics/traction');
    if(!r||!r.ok||!r.body||!r.body.has_real_data)return;   // pre-revenue: keep the honest static tiles
    var b=r.body;
    document.getElementById('inv_gmv').textContent='$'+((b.gmv_captured_minor||0)/100).toLocaleString(undefined,{maximumFractionDigits:0});
    document.getElementById('inv_jobs').textContent=String(b.paid_jobs||0);
    document.getElementById('inv_gpus').textContent=String(b.active_gpus_online||0);
    document.getElementById('inv_take').textContent=(b.take_rate_gross==null)?'—':((b.take_rate_gross*100).toFixed(1)+'%');
    document.getElementById('inv_asof').textContent='· live '+(b.as_of||'').slice(0,10);
    document.getElementById('inv_live').style.display='block';
  }catch(e){}
})();
</script>""")


TRACTION_HTML = _page("Petabyte — traction", """
<div class="hero"><div class="wrap" style="padding:52px 22px 8px">
  <img class="hexbg" src="/static/petabyte-logo.png" alt=""/>
  <div class="eyebrow"><span class="dot"></span> live traction · public</div>
  <h1 style="font-size:clamp(28px,5vw,44px);margin:18px 0 10px;max-width:22ch">Traction, <span class="grad-teal">computed live</span> from the ledger.</h1>
  <p class="mut" style="max-width:74ch">Every number on this page is a live query over the same authoritative database rows the money moves through — never a slide, never fabricated. We show <b class="teal">LIVE money only</b>: test-mode and demo activity are excluded and never counted as real traction. Zeros are honest — the platform runs Stripe in TEST mode until launch.</p>
</div></div>
<div class="wrap" style="padding:14px 22px 8px">
  <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center">
    <span class="mini mono" id="t_asof">loading…</span>
    <a class="btn-ghost" href="/trust" style="margin-inline-start:auto">Verify a job receipt →</a>
    <a class="btn-ghost" href="/investors">Investor overview →</a>
  </div>
  <div id="t_banner" class="card" style="display:none;margin-top:12px"></div>
  <div class="stats" style="margin-top:12px">
    <div class="stat"><div class="l">GMV (captured, live)</div><div class="n amber" id="t_gmv">—</div><div class="mini" id="t_netgmv"></div></div>
    <div class="stat"><div class="l">Paid jobs</div><div class="n teal" id="t_jobs">—</div><div class="mini" id="t_settled"></div></div>
    <div class="stat"><div class="l">GPUs online</div><div class="n" id="t_gpus">—</div><div class="mini" id="t_gpuhrs"></div></div>
    <div class="stat"><div class="l">Active buyers / sellers</div><div class="n" id="t_parties">—</div><div class="mini" id="t_sellers"></div></div>
  </div>
  <div class="panel" style="margin-top:12px;padding:16px 18px;display:flex;flex-wrap:wrap;gap:28px">
    <div><span class="mini">Gross take rate</span><div class="mono teal" id="t_take" style="font-size:18px">—</div></div>
    <div><span class="mini">Job success rate</span><div class="mono" id="t_success" style="font-size:18px">—</div></div>
    <div><span class="mini">GPU utilization</span><div class="mono" id="t_util" style="font-size:18px">—</div></div>
  </div>
  <p class="mini mut" id="t_note" style="margin:14px 2px 8px"></p>
  <div class="card" style="margin:10px 0 34px;background:linear-gradient(100deg,rgba(79,214,201,.06),rgba(44,158,155,.02))">
    <div class="lbl">How we count</div>
    <p class="mut" style="max-width:92ch">GMV is captured money on real (LIVE, non-demo) compute transactions — one canonical definition, not a hand-picked figure. Job success, take rate and utilization are ratios over the same rows; a rate with no denominator shows <span class="mono">—</span> (undefined), never a faked 0%. See the <a class="teal" href="/trust">trust page</a> for cryptographic per-job receipts and the double-entry ledger balance.</p>
  </div>
</div>
<script>
function td(minor){if(minor===null||minor===undefined)return '—';return '$'+(minor/100).toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2});}
function tp(rate){if(rate===null||rate===undefined)return '—';return (rate*100).toFixed(1)+'%';}
function tn(n){return (n===null||n===undefined)?'—':String(n);}
async function tload(){
  var r=await api('/metrics/traction');
  if(!r||!r.ok){document.getElementById('t_asof').textContent='metrics unavailable';return;}
  var b=r.body;
  document.getElementById('t_asof').textContent='live · '+(b.as_of||'').slice(0,19).replace('T',' ')+'Z';
  var ban=document.getElementById('t_banner');
  if(!b.has_real_data){ban.style.display='block';ban.style.borderColor='rgba(240,180,80,.5)';
    ban.innerHTML='<div class="lbl" style="color:var(--warn)">Pre-revenue — no live transactions yet</div><p class="mut">Real GMV is $0 by design: the platform runs Stripe in TEST mode until launch, and we never show test or demo activity as real traction. This page will fill in automatically the moment real money moves — the numbers are wired to the ledger, not to a slide.</p>';}
  else{ban.style.display='none';}
  document.getElementById('t_gmv').textContent=td(b.gmv_captured_minor);
  document.getElementById('t_netgmv').textContent='net of refunds '+td(b.net_gmv_minor);
  document.getElementById('t_jobs').textContent=tn(b.paid_jobs);
  document.getElementById('t_settled').textContent=tn(b.settled_jobs)+' settled';
  document.getElementById('t_gpus').textContent=tn(b.active_gpus_online);
  document.getElementById('t_gpuhrs').textContent=tn(b.gpu_hours_available)+' GPU-hours available';
  document.getElementById('t_parties').textContent=tn(b.active_buyers)+' / '+tn(b.active_sellers);
  document.getElementById('t_sellers').textContent='buyers / sellers (real, paid)';
  document.getElementById('t_take').textContent=tp(b.take_rate_gross);
  document.getElementById('t_success').textContent=tp(b.job_success_rate);
  document.getElementById('t_util').textContent=tp(b.utilization);
  document.getElementById('t_note').textContent=b.note;
}
tload();
</script>""")


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
      <div style="margin-inline-start:auto"><span class="mini" id="a_asof"></span></div>
    </div>
  </div>

  <div class="wrap" style="padding:14px 22px 2px">
    <div class="lbl" style="margin-bottom:10px">Live operations</div>
    <div class="stats">
      <div class="stat"><div class="l">GPU utilization</div><div class="n teal" id="a_util">—</div><div class="mini" id="a_util_sub"></div></div>
      <div class="stat"><div class="l">Active VMs</div><div class="n" id="a_vms">—</div><div class="mini" id="a_vms_sub"></div></div>
      <div class="stat"><div class="l">Clusters running</div><div class="n" id="a_clusters">—</div><div class="mini" id="a_clusters_sub"></div></div>
      <div class="stat"><div class="l">In escrow</div><div class="n amber" id="a_escrow">—</div><div class="mini" id="a_escrow_sub"></div></div>
    </div>
    <div class="stats" style="margin-top:10px">
      <div class="stat"><div class="l">Disk rental</div><div class="n" id="a_disk">—</div><div class="mini" id="a_disk_sub"></div></div>
      <div class="stat"><div class="l">Teams</div><div class="n" id="a_teams">—</div><div class="mini" id="a_teams_sub"></div></div>
      <div class="stat"><div class="l">Ledger</div><div class="n" id="a_ledger">—</div><div class="mini" id="a_ledger_sub"></div></div>
      <div class="stat"><div class="l">Payout backlog</div><div class="n" id="a_backlog">—</div><div class="mini" id="a_backlog_sub"></div></div>
    </div>
  </div>

  <div class="wrap" style="padding:12px 22px 2px">
    <div style="display:flex;gap:10px;flex-wrap:wrap">
      <a class="btn btn-ghost" href="/metrics">Marketplace metrics</a>
      <a class="btn btn-ghost" href="/admin/funding-view">Funding metrics</a>
      <a class="btn btn-ghost" href="/status">Public status</a>
    </div>
    <p class="mini" style="margin-top:8px">Full time-series (per-endpoint latency, error rates, background workers) live in Grafana; these tiles are the at-a-glance operational heartbeat, refreshed every 20s.</p>
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
  loadOps();loadUsers();loadSpecs();loadPayouts();loadIncidents();loadPayments();loadVideo();
  if(!window._adminTick){window._adminTick=setInterval(function(){loadOverviewTiles();loadOps();},20000);}
}
async function loadOverviewTiles(){
  var ov=await api('/admin/overview');if(!ov.ok)return;var o=ov.body;
  document.getElementById('a_users').textContent=o.users.total;
  document.getElementById('a_nodes').textContent=o.specs.online;
  document.getElementById('a_jobs').textContent=o.jobs.completed;
  document.getElementById('a_gmv').textContent=money(o.gmv);
  document.getElementById('a_rev').textContent=money(o.platform_revenue);
  document.getElementById('a_pend').textContent=o.payouts_pending.count+' · '+money(o.payouts_pending.amount);
}
async function loadOps(){
  var r=await api('/admin/ops');if(!r.ok)return;var o=r.body;
  var m=o.marketplace||{},h=o.health||{},cl=o.clusters||{},d=o.disk||{},t=o.teams||{},v=o.vms||{};
  document.getElementById('a_util').textContent=(m.utilization_pct||0)+'%';
  document.getElementById('a_util_sub').textContent=(m.booked||0)+' booked · '+(m.available_units||0)+' free · '+(m.online||0)+' online';
  document.getElementById('a_vms').textContent=v.active||0;
  document.getElementById('a_vms_sub').textContent=(v.migrations_total||0)+' failovers total';
  document.getElementById('a_clusters').textContent=cl.running||0;
  document.getElementById('a_clusters_sub').textContent=(cl.complete||0)+' complete · '+(cl.failed||0)+' failed';
  document.getElementById('a_escrow').textContent=money(o.in_escrow);
  document.getElementById('a_escrow_sub').textContent='buyer money held';
  document.getElementById('a_disk').textContent=d.nodes||0;
  document.getElementById('a_disk_sub').textContent=(d.alloc_gb||0)+' GB pledged';
  document.getElementById('a_teams').textContent=t.count||0;
  document.getElementById('a_teams_sub').textContent=money(t.balance)+' pooled';
  var lg=document.getElementById('a_ledger');
  lg.textContent=h.ledger_balanced?'balanced':'IMBALANCE';
  lg.className='n '+(h.ledger_balanced?'teal':'');
  lg.style.color=h.ledger_balanced?'':'var(--bad)';
  document.getElementById('a_ledger_sub').textContent=h.ledger_balanced?'debits = credits':((h.imbalanced_tx||0)+' broken tx');
  document.getElementById('a_backlog').textContent=h.payout_backlog||0;
  document.getElementById('a_backlog_sub').textContent=(h.payout_backlog?('oldest '+h.payout_backlog_age_hours+'h'):'clear');
  var asof=document.getElementById('a_asof');if(asof)asof.textContent='updated '+new Date().toLocaleTimeString();
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
  tb.innerHTML=rows.map(function(r){return '<tr><td><span class="badge">'+esc(r[0])+'</span></td><td class="mono">'+esc(r[1])+'</td><td class="mono amber">'+esc(r[2])+'</td><td class="mono mut">'+esc(r[3])+'</td><td class="mut" style="font-size:12.5px">'+esc(r[4])+'</td></tr>';}).join('');
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
  if(!authed()){document.getElementById('fsignin').style.display='block';return;}
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
    <label class="mini" style="display:block;margin-bottom:6px">Username</label>
    <input id="u" placeholder="username" style="width:100%" autocomplete="username"/>
    <label class="mini" style="display:block;margin:14px 0 6px">Password</label>
    <input id="p" type="password" placeholder="password (8+ characters)" style="width:100%" autocomplete="current-password"
           onkeydown="if(event.key==='Enter')go()"/>
    <div id="otprow" style="display:none">
      <label class="mini" style="display:block;margin:14px 0 6px">Authenticator code</label>
      <input id="otp" inputmode="numeric" autocomplete="one-time-code" placeholder="6-digit code (or a backup code)" style="width:100%"
             onkeydown="if(event.key==='Enter')go()"/>
    </div>
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
async function login(u,p,otp){
  var body='username='+encodeURIComponent(u)+'&password='+encodeURIComponent(p);
  if(otp)body+='&otp='+encodeURIComponent(otp);
  var r = await fetch('/login', {method:'POST', credentials:'same-origin',
    headers:{'Content-Type':'application/x-www-form-urlencoded'}, body:body});
  var b={};try{b=await r.json()}catch(e){}
  return {ok:r.ok, token:b.access_token, code:(b.error&&b.error.code)||null, status:r.status};
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
    var otp=(document.getElementById('otp')||{}).value;
    var res=await login(u,p,otp);
    if(!res.ok){
      if(res.code==='TOTP_REQUIRED'){document.getElementById('otprow').style.display='';
        info("Enter the 6-digit code from your authenticator app.");document.getElementById('otp').focus();return;}
      if(res.code==='TOTP_INVALID'){document.getElementById('otprow').style.display='';
        fail("That code is incorrect or expired — try again.");return;}
      fail(mode==="register"?"Account created — but sign-in failed. Try signing in.":"Wrong username or password.");return;}
    // The server set the HttpOnly session + readable pb_csrf cookies on the /login response;
    // nothing to store in JS (the JWT is deliberately not reachable from JS anymore).
    document.documentElement.setAttribute('data-auth','in');
    location.href='/console';
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
  <img src="/static/petabyte-logo.png" style="width:56px;opacity:.8"/>
  <h1 style="font-size:28px;margin:18px 0 8px">Your account</h1>
  <p class="mut">Sign in to see your nodes, jobs, keys, and wallet in one place.</p>
  <div style="margin-top:18px"><a class="btn btn-amber" href="/login">Sign in</a></div>
</div>

<div id="hub" style="display:none">
  <div class="wrap" style="padding:18px 22px 0"><div id="pbtestmode"></div></div>
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
        </div>
      </div>
      <div style="display:flex;gap:10px;flex-wrap:wrap">
        <a class="btn btn-teal" href="/console">Open dashboard</a>
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
      <a class="card" href="/console" style="text-decoration:none"><b class="teal" style="font-family:var(--disp)">Run a job</b><p class="mut" style="font-size:12.5px;margin-top:5px">Notebook, model, render, transcode</p></a>
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
          <label class="mut" style="font-size:12px;display:flex;align-items:center;gap:4px" data-ar="فوري (رسوم)"><input type="checkbox" id="instant"/> ⚡ instant (fee)</label>
        </div>
      </div>
      <p id="wmsg" class="mut" style="font-size:12.5px;margin-top:12px;display:none"></p>
      <div id="methods" class="mini" style="margin-top:12px"></div>
    </div>
  </div>

  <!-- invite & earn (referrals) -->
  <div class="wrap" style="padding:26px 22px 4px">
    <div class="lbl" style="margin-bottom:12px" data-ar="ادعُ واكسب">Invite &amp; earn</div>
    <div class="card" style="border-color:rgba(79,214,201,.25)">
      <p class="mut" style="margin-bottom:10px" data-ar="شارك رابطك. عندما يبدأ من تدعوه باستئجار أو إدراج كرت رسومات، تحصلان كلاكما على رصيد.">Share your link. When someone you invite starts renting or listing a GPU, <b class="teal">you both get credit</b> (<span id="refreward">—</span> each).</p>
      <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center">
        <input id="reflink" readonly value="" size="34" style="flex:1;min-width:min(320px,80vw);font-family:ui-monospace,monospace"/>
        <button class="btn-amber" onclick="copyRef(this)" data-ar="انسخ الرابط">Copy link</button>
      </div>
      <div class="mini" id="refstat" style="margin-top:12px"></div>
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
  if(new URLSearchParams(location.search).get('funded')==='1'){
    wmsg('Payment received — your balance updates as soon as Stripe confirms.');}
  loadNodes();loadJobs();loadKeys();loadMethods();loadTemplates();loadVMs();loadEarnings();loadOnboarding();loadDiagnostics();loadBurn();loadEmail();loadNotifs();loadReferral();setInterval(loadBurn,20000);
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
  var inst=!!(document.getElementById('instant')&&document.getElementById('instant').checked);
  if(inst){var q=await api('/wallet/payout_quote?amount='+a);
    if(q.ok&&q.body&&q.body.instant){ if(!q.body.instant.available){wmsg('Amount too small for an instant payout — use the free scheduled option.');return;}
      if(!confirm('Instant payout: fee $'+q.body.instant.fee_usd.toFixed(2)+' — you receive $'+q.body.instant.net_usd.toFixed(2)+'.\\n\\nScheduled payouts are free. Continue instant?'))return; } }
  var body={amount:a,instant:inst}; if(window._pmId)body.method_id=window._pmId;
  var r=await api('/wallet/withdraw',{method:'POST',body:JSON.stringify(body)});
  if(r.ok){var f=r.body.fee_usd||0; wmsg('Withdrawal of '+money(r.body.amount_usd)+' requested'+(f>0?(' (instant, fee '+money(f)+')'):' (free, scheduled)')+'.');}
  else{wmsg(r.body&&r.body.detail?(r.body.detail.message||r.body.detail):'Add a payout method first.');}
  loadMethods();}
async function loadMethods(){var r=await api('/wallet/methods');var el=document.getElementById('methods');
  if(r.ok&&r.body.methods&&r.body.methods.length){window._pmId=r.body.methods[0].id;
    el.innerHTML='Payout methods: '+r.body.methods.map(function(m){return '<span class="badge ok">'+(m.kind||m.type||'method')+'</span>';}).join(' ')+' <span class="mut">· ⚡ instant costs a small fee; scheduled is free</span>';}
  else{window._pmId=null;el.innerHTML='No payout method yet — add bank / USDC / gift card in the <a class="teal" href="/console">dashboard</a> to withdraw.';}}
async function loadTemplates(){renderLaunch('launchgrid',['ai','render','art','game'],2);}
async function loadReferral(){var r=await api('/referral');if(!r.ok)return;var b=r.body;
  var el=document.getElementById('reflink');if(el)el.value=b.link;
  var rw=document.getElementById('refreward');if(rw)rw.textContent='$'+Number(b.reward_usd).toFixed(2);
  var st=document.getElementById('refstat');if(st)st.innerHTML='Invited <b class="teal">'+b.invited+'</b> · qualified <b class="teal">'+b.qualified+'</b> · pending '+b.pending+' · credit earned <b class="amber">$'+Number(b.credit_earned_usd).toFixed(2)+'</b>';}
function copyRef(btn){var el=document.getElementById('reflink');if(!el)return;el.select();
  try{navigator.clipboard.writeText(el.value);}catch(e){try{document.execCommand('copy');}catch(_){}}
  if(btn){var o=btn.textContent;btn.textContent='copied';setTimeout(function(){btn.textContent=o;},1200);}}

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
        '<div style="font-size:13.5px;font-family:var(--disp);font-weight:600">'+esc(n.subject||n.event_type)+'</div>'+
        '<div class="mut" style="font-size:12.5px">'+esc(n.body||'')+'</div></div>'+
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
    <div class="skel" aria-busy="true" aria-label="Loading GPU"><span class="skel-b" style="height:38px;width:45%"></span><span class="skel-b" style="height:14px;width:30%;margin-top:14px"></span><div class="cols" style="gap:18px;margin-top:20px"><span class="skel-b" style="height:220px;flex:1.6 1 380px"></span><span class="skel-b" style="height:220px;flex:1 1 280px"></span></div></div>
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
 var status=bookable?'<span class="badge st ok">Available now</span>':(s.online?'<span class="badge st warn">Fully booked</span>':'<span class="badge st bad">Offline</span>');
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
     (s.savings_pct?'<div class="mini" style="color:var(--pos);margin-top:4px">'+s.savings_pct+'% below the on-demand cloud rate for this GPU class ($'+Number(s.cloud_reference).toFixed(2)+'/hr)</div>':'<div class="mini" style="margin-top:4px">No comparable public cloud rate for this GPU — we don\\'t quote a saving we can\\'t back up.</div>')+
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

<div class="wrap" style="padding:26px 24px 8px">
  <div class="lbl" data-ar="السعر المرجعي حسب الأداء">Reference price by GPU (benchmark-ordered)</div>
  <p class="mut" style="font-size:13px;max-width:70ch;margin:6px 0 12px" data-ar="السعر المرجعي مشتقّ من معيار FP16 TFLOPS لكل كرت، لذا لا يكون الكرت الأبطأ أغلى من الأسرع أبداً. «متوسط مباشر» هو متوسط أسعار المضيفين المتصلين الآن لهذا الطراز.">Every GPU's <b>reference $/hr</b> is derived from its FP16 TFLOPS benchmark, so a slower card is <b>never priced above a faster one</b>. "Live avg" is the mean of hosts currently online for that model.</p>
  <div class="panel" style="overflow:auto">
    <table class="tbl">
      <thead><tr><th data-ar="الكرت">GPU</th><th>FP16 TFLOPS</th><th data-ar="السعر المرجعي">Reference $/hr</th><th data-ar="متوسط مباشر">Live avg $/hr</th><th data-ar="مرجع السحابة">Cloud ref</th><th data-ar="توفيرك">Save</th></tr></thead>
      <tbody id="crows"><tr><td colspan=6 class="mut mono" style="padding:22px;text-align:center">Loading catalog…</td></tr></tbody>
    </table>
  </div>
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
   '<td>'+'<a class="btn btn-teal" style="padding:6px 14px;font-size:12px" href="/gpu/'+s.id+'">View</a></td></tr>';}).join('');
}
prices();setInterval(prices,10000);
// Benchmark-ordered reference catalog: reference $/hr is monotonic in the FP16 benchmark, so a
// slower GPU is never priced above a faster one. Enriched with the live marketplace average.
async function catalog(){
 var r=await fetch('/pricing/catalog');if(!r.ok)return;var b=await r.json();var tb=document.getElementById('crows');
 if(!b.count){tb.innerHTML='<tr><td colspan=6 class="mut mono" style="padding:18px;text-align:center">Catalog unavailable.</td></tr>';return;}
 tb.innerHTML=b.catalog.map(function(g){
  return '<tr>'+
   '<td style="font-family:var(--disp);font-weight:600">'+esc(g.gpu_model)+'</td>'+
   '<td data-l="FP16 TFLOPS" class="mono mut">'+Number(g.benchmark_tflops_fp16).toFixed(0)+'</td>'+
   '<td data-l="Reference" class="mono amber" style="font-weight:600">$'+Number(g.reference_price_per_hour).toFixed(2)+'</td>'+
   '<td data-l="Live avg" class="mono">'+(g.avg_price_per_hour!=null?('$'+Number(g.avg_price_per_hour).toFixed(2)+' <span class="mini mut">('+g.live_listings+')</span>'):'<span class="mini mut">none online</span>')+'</td>'+
   '<td data-l="Cloud ref" class="mono mut">'+(g.cloud_reference!=null?'$'+Number(g.cloud_reference).toFixed(2):'—')+'</td>'+
   '<td data-l="Save" class="mono" style="color:var(--pos)">'+(g.savings_vs_cloud_pct!=null?Math.round(g.savings_vs_cloud_pct)+'%':'—')+'</td></tr>';}).join('');
}
catalog();
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
      <li style="padding:3px 0" data-ar="إثبات مدعوم عتادياً عبر مورّد حقيقي (SEV-SNP / TDX / NVIDIA CC). شارة «السرّية» اليوم فاشلة-الإغلاق: لا يمكن للنموذج البرمجي إصدارها في الإنتاج.">Hardware-backed attestation via a real vendor verifier (SEV-SNP / TDX / NVIDIA CC). The <b>confidential</b> badge today is <b>fail-closed</b> — the software stub cannot mint it in production, so it is never faked.</li>
      <li style="padding:3px 0" data-ar="إعادة قياس الأداء بتوقيت الخادم على عيّنة من المهام الحقيقية (اليوم القياس مُبلّغ من العقدة وموقّع، ويُقارَن ببيانات عامة).">Server-timed benchmark <i>re-measurement</i> on a sample of real jobs. Today a signed benchmark is compared to public reference data (see <a class="teal" href="/trust">Trust</a>) — node-reported, not yet platform-timed.</li>
      <li style="padding:3px 0" data-ar="تدقيق أمني خارجي منشور أو تقرير SOC 2.">A published external security audit or SOC 2 report.</li>
      <li style="padding:3px 0" data-ar="ضمانات رسمية لموقع تخزين البيانات. المنطقة مُبلّغ عنها من المضيف ما لم تُوسم بأنها موثّقة.">Formal data-residency guarantees. Region is host-reported unless marked verified.</li>
    </ul>
    <p class="mut" style="font-size:13px;margin-top:12px" data-ar="ما نتحقّق منه فعلاً اليوم، بأرقام حيّة:">What we <b>do</b> verify today, with live numbers and a receipt you can re-check yourself: <a class="teal" href="/trust">petabyte.market/trust</a>. If a claim matters for your workload, ask before you book — <a class="teal" href="mailto:info@petabyte.market">info@petabyte.market</a>.</p>
  </div>
</div>

<div class="wrap" style="padding:22px 24px 8px"><div class="cols c3">
  <a class="card" href="/privacy" style="display:block"><div class="lbl">Legal</div><h2 style="font-size:16px">Privacy policy</h2><p class="mut" style="font-size:13px">What we collect, and your workload's data lifecycle.</p></a>
  <a class="card" href="/terms" style="display:block"><div class="lbl">Legal</div><h2 style="font-size:16px">Terms of service</h2><p class="mut" style="font-size:13px">The agreement for buyers and hosts.</p></a>
  <a class="card" href="/refunds" style="display:block"><div class="lbl">Legal</div><h2 style="font-size:16px">Refunds &amp; disputes</h2><p class="mut" style="font-size:13px">Escrow protection, refunds, and the dispute SLA.</p></a>
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
<h2 """ + _LEGAL_H + """>Data lifecycle — your workload</h2>
<p class="mut">Objects you upload for a job (scenes, inputs, outputs) are <b>client-side encrypted</b> before storage, and streamed to the node over TLS via one-time pre-signed URLs — the node holds no standing credentials to your storage. A job runs in a container on the host; when the rental ends the container and its working data are torn down. Backups a job takes are encrypted with a per-task key. We do <b>not</b> read the contents of your workloads, and we do not retain your input/output objects beyond what the job and your account need. The honest boundary is on the <a class="teal" href="/security">security page</a>: a container is not a hardware boundary, so for data you could not tolerate the host observing, use a <b>confidential</b> node or don't use shared infrastructure.</p>
<h2 """ + _LEGAL_H + """>Retention and your rights</h2>
<p class="mut">Financial records are kept as required for accounting. Other data is kept while your account is open. You can request a copy of your data or ask us to delete your account by emailing <a class="teal" href="mailto:info@petabyte.market">info@petabyte.market</a>.</p>
""")

TERMS_HTML = _legal("Terms of service", """
<p class="mut">Petabyte is a marketplace. Buyers rent compute; hosts supply it. We operate the platform, hold funds in escrow during a rental, and settle them on completion.</p>
<h2 """ + _LEGAL_H + """>What we are</h2>
<p class="mut">We are an intermediary, not the owner of the hardware. Hosts are independent parties who set their own prices and availability. We verify what we can (see <a class="teal" href="/security">Security</a>) and show reputation earned from completed jobs, but we do not warrant any host's performance.</p>
<h2 """ + _LEGAL_H + """>Money</h2>
<p class="mut">Funds you deposit are held by Petabyte. When you book, the amount is moved into escrow for that rental. On completion we pay the host their share and take a 10% platform fee from the rental. If you stop early, you are billed for the hours you held the machine (minimum one hour) and the remainder is returned to your wallet. If a rental cannot be delivered, you are refunded. Full details and the dispute process are in the <a class="teal" href="/refunds">Refunds &amp; disputes policy</a>.</p>
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

REFUNDS_HTML = _legal("Refunds &amp; disputes", """
<p class="mut">You are renting a stranger's machine. Escrow and this policy exist so that if it doesn't deliver, you don't lose your money.</p>
<h2 """ + _LEGAL_H + """>Your money is held in escrow</h2>
<p class="mut">When you book, the amount moves from your wallet into escrow held by Petabyte for that rental — it is <b>not</b> paid to the host until the work is delivered. Every completed job carries a <a class="teal" href="/trust">verifiable receipt</a> (the node's signed result + the sha256 of the output), and payouts to hosts are held for a settlement window so fraud can be caught before money leaves.</p>
<h2 """ + _LEGAL_H + """>When you are refunded automatically</h2>
<ul class="mut" style="margin:8px 0 0 20px">
  <li style="padding:3px 0"><b>The host can't deliver:</b> if a node goes offline mid-rental and we cannot fail your machine over to another eligible node, the rental is refunded.</li>
  <li style="padding:3px 0"><b>The job never ran:</b> if we could not place your workload at all, you are refunded in full.</li>
  <li style="padding:3px 0"><b>You stop early:</b> you are billed only for the hours you actually held the machine (minimum one hour). The unused prepay returns to your wallet.</li>
</ul>
<h2 """ + _LEGAL_H + """>Raising a dispute</h2>
<p class="mut">If you believe you were charged for compute you did not receive — or a result is wrong — email <a class="teal" href="mailto:info@petabyte.market">info@petabyte.market</a> with your <b>booking id</b> or <b>VM id</b> and what went wrong. We investigate using signals we already hold: the signed result receipt, the node's heartbeats, and — where the job is deterministic — cross-node re-verification of the output hash.</p>
<table style="width:100%;border-collapse:collapse;margin:10px 0;font-size:13.5px">
  <tr><td class="mut" style="padding:6px 0;border-bottom:1px solid var(--hair)">We acknowledge your dispute</td><td class="mono" style="text-align:right;border-bottom:1px solid var(--hair)">within 2 business days</td></tr>
  <tr><td class="mut" style="padding:6px 0;border-bottom:1px solid var(--hair)">We resolve it (refund, partial, or explained)</td><td class="mono" style="text-align:right;border-bottom:1px solid var(--hair)">within 10 business days</td></tr>
</table>
<p class="mut">Outcomes are a full refund, a partial refund for the portion not delivered, or — if the evidence shows the compute <i>was</i> delivered — the charge upheld, with the receipt and signals we relied on shared with you so the decision is not a black box.</p>
<h2 """ + _LEGAL_H + """>When a host is at fault</h2>
<p class="mut">A host who takes a booking and fails to deliver, misrepresents hardware, or whose result diverges from independent re-verification has their <b>payouts frozen</b> pending review. Buyers are made whole from escrow <b>before</b> any payout to that host — your refund does not wait on us recovering from the host.</p>
<h2 """ + _LEGAL_H + """>Card chargebacks</h2>
<p class="mut">If you funded your wallet by card, please contact us before filing a card chargeback — we can almost always resolve a delivery dispute faster than your bank can, and a receipt makes it straightforward.</p>
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


TRUST_HTML = _page("Petabyte — trust &amp; transparency",
    desc="Live, honest transparency: GPUs by verification tier, jobs completed, cryptographically signed results, quorum checks, and a ledger that balances. Verify your own job.",
    path="/trust", body="""
<div class="hero"><div class="wrap" style="padding:60px 24px 18px">
  <div class="eyebrow"><span class="dot"></span> trust &amp; transparency</div>
  <h1 style="font-size:clamp(34px,5vw,54px);margin:16px 0 12px">Don't trust us. <span class="grad">Verify.</span></h1>
  <p class="mut" style="font-size:16px;max-width:64ch">Every number below is a live database aggregate — zeros mean zero, nothing is invented. Each completed job carries a cryptographic receipt you can re-check yourself.</p>
  <p class="mini" style="margin-top:12px">The same honesty applies to the money: see <a class="teal" href="/traction">live marketplace traction →</a> (LIVE-money-only, computed from the ledger).</p>
</div></div>

<div class="wrap" style="padding:26px 24px 8px">
  <div class="stats" id="trust_stats"><div class="mut mono" style="padding:12px 0">loading live numbers…</div></div>
</div>

<div class="wrap" style="padding:14px 24px 8px"><div class="cols c2">
  <div class="card"><div class="lbl">the trust ladder</div>
    <h2 style="font-size:18px;margin-bottom:8px">A tier is earned, never assumed</h2>
    <p class="mut" style="font-size:13.5px"><b class="teal">self-reported</b> — registered via the API; nothing proven.</p>
    <p class="mut" style="font-size:13.5px;margin-top:6px"><b class="teal">agent-verified</b> — the node signed a hardware report with its on-device Ed25519 key.</p>
    <p class="mut" style="font-size:13.5px;margin-top:6px"><b class="teal">benchmark-consistent</b> — plus a signed benchmark that MATCHES public reference data for the claimed GPU (FP16 TFLOPS, Blender Open Data, Cinebench, PugetBench). A benchmark that contradicts the listing is flagged, not rewarded.</p>
    <p class="mini" style="margin-top:10px">We do <b>not</b> claim hardware TEE attestation from the software stub — <a class="teal" href="/security">confidential computing</a> is a separate, fail-closed badge.</p>
  </div>
  <div class="card"><div class="lbl">verify your own job</div>
    <h2 style="font-size:18px;margin-bottom:8px">A receipt you can re-check offline</h2>
    <p class="mut" style="font-size:13.5px">Every completed job exposes a receipt at <span class="mono">/jobs/&lt;id&gt;/receipt</span> (signed in as the buyer). It contains the node's Ed25519 <b>signature</b> over the exact signed payload, the <b>sha256</b> of the real output bytes, and the node's attested <b>public key</b>.</p>
    <p class="mut" style="font-size:13.5px;margin-top:8px">Reconstruct the message as canonical JSON of the payload and verify the signature against the public key — no need to take our word for it. Our server also re-verifies it live and shows you the result.</p>
    <p class="mini" style="margin-top:10px">A forged or tampered result is rejected on submission and <b>freezes the seller's payouts</b> pending review.</p>
  </div>
</div></div>

<div class="wrap" style="padding:14px 24px 30px"><div class="cols c3">
  <a class="card" href="/security" style="display:block"><div class="lbl">security</div><h2 style="font-size:16px">What we verify — and don't</h2><p class="mut" style="font-size:13px">Isolation, escrow, attestation, honestly.</p></a>
  <a class="card" href="/status" style="display:block"><div class="lbl">status</div><h2 style="font-size:16px">Live system status</h2><p class="mut" style="font-size:13px">API, marketplace, settlement health.</p></a>
  <a class="card" href="/terms" style="display:block"><div class="lbl">legal</div><h2 style="font-size:16px">Terms &amp; escrow</h2><p class="mut" style="font-size:13px">How funds are held and refunded.</p></a>
</div></div>

<script>
function tstat(label,val,sub){return '<div class="stat"><div class="stat-n mono">'+val+'</div><div class="stat-l">'+label+(sub?' <span class="mut" style="font-size:11px">'+sub+'</span>':'')+'</div></div>';}
async function trustload(){
 try{
  var s=await (await fetch('/trust/summary')).json();
  var t=s.trust_tiers||{};
  var led=s.ledger_balanced===true?'balanced':(s.ledger_balanced===false?'IMBALANCED':'—');
  document.getElementById('trust_stats').innerHTML=
    tstat('attested GPUs',s.attested_gpus)+
    tstat('benchmark-consistent',(t.benchmark_consistent||0))+
    tstat('confidential nodes',(s.confidential_nodes_active||0))+
    tstat('jobs completed',s.jobs_completed)+
    tstat('verifiable receipts',s.verifiable_receipts)+
    tstat('results bound to output bytes',s.results_content_bound)+
    tstat('sellers frozen for fraud',s.sellers_fraud_flagged)+
    tstat('double-entry ledger',led);
 }catch(e){document.getElementById('trust_stats').innerHTML='<div class="mut mono" style="padding:12px 0">status unavailable</div>';}
}
trustload();setInterval(trustload,30000);
</script>""")


SELLER_EARNINGS_HTML = _page("Petabyte — seller earnings",
    desc="Connect your Stripe account to receive payouts, and track compute earnings, commission, transfers and bank payouts.",
    path="/seller/payouts", body="""
<div class="wrap" style="padding:52px 24px 8px;max-width:900px">
  <div id="pbtestmode"></div>
  <div class="eyebrow"><span class="dot"></span> seller earnings</div>
  <h1 style="font-size:clamp(28px,4.4vw,42px);margin:14px 0 8px">Get paid for your compute</h1>
  <p class="mut" id="signedout" style="display:none">Please <a class="teal" href="/login">sign in</a> to set up payouts.</p>

  <div id="setup" style="display:none">
    <div class="card" style="margin-top:16px">
      <div class="lbl">Your GPUs</div>
      <p class="mini" style="margin:6px 0 12px">A GPU earns once it is <b>online</b> and <b>verified</b> — then it is visible to buyers and can take paid jobs.</p>
      <div id="nodes_box"><div class="mut mono" style="padding:8px 0">loading…</div></div>
      <div id="nodes_blockers"></div>
    </div>

    <div class="card" style="margin-top:16px">
      <div class="lbl">Rent your spare disk <span class="badge">extra earnings</span></div>
      <p class="mini" style="margin:6px 0 12px">Rent unused disk to a web3 / BitTorrent storage network (Storj, BTFS, Sia). It's a <b>separate, always-on</b> earner — it runs even while a paid GPU job is on the box, and it's <b>not</b> tied to your GPU being idle. Pick a provider and a GB cap; earnings land in your Petabyte balance (minus a 10% fee). You can change the cap, pause, or delete at any time.</p>
      <div id="disk_box"><div class="mut mono" style="padding:8px 0">loading…</div></div>
    </div>

    <div class="card" style="margin-top:16px">
      <div class="lbl">Estimated earnings</div>
      <p class="mini" style="margin:6px 0 10px">What you take home after Petabyte's 10% fee. The <b>net rate</b> is exact; daily/monthly are an <b>estimate</b> — actual earnings depend on demand.</p>
      <div id="earn_forecast"><div class="mut mono" style="padding:8px 0">loading…</div></div>
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
  // Estimated earnings — net of Petabyte's 10% fee. The net rate is exact; daily/monthly are
  // an estimate at a few utilization levels (same honest math as the agent + /nodes/*/forecast).
  (function(){
    var fc=document.getElementById('earn_forecast');if(!fc)return;
    function money(x){return '$'+Number(x).toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2});}
    if(!ns.length){fc.innerHTML='<p class="mut" style="font-size:13px">List a GPU to see your estimated earnings.</p>';return;}
    var netHr=ns.reduce(function(a,n){return a+Number(n.price_per_hour||0)*0.9;},0);
    var rows=[0.25,0.50,0.75].map(function(u){var d=netHr*24*u;return '<tr><td>'+Math.round(u*100)+'% utilized</td><td class="mono teal">'+money(d)+'/day</td><td class="mono">'+money(d*30)+'/mo</td></tr>';}).join('');
    fc.innerHTML='<div class="mini" style="margin-bottom:8px">Net rate across your '+ns.length+' GPU'+(ns.length>1?'s':'')+': <b class="teal">'+money(netHr)+'/hr</b></div>'+
      '<div class="panel" style="overflow:auto"><table class="tbl"><thead><tr><th>If your GPUs are…</th><th>Estimated</th><th></th></tr></thead><tbody>'+rows+'</tbody></table></div>';
  })();
  if(!ns.length){box.innerHTML='<p class="mut" style="font-size:13px">No GPUs listed yet. <a class="teal" href="/install">List your hardware →</a></p>';}
  else{
    box.innerHTML=ns.map(function(n){
      var visible=n.online&&n.attested;
      function chip(ok,on,off){return '<span class="badge st '+(ok?'ok':'warn')+'">'+(ok?on:off)+'</span>';}
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
          (n.utilization_pct||0)+'% utilized · '+n.jobs_completed+(n.jobs_completed===1?' job done':' jobs done')+
          (n.success_rate!=null?(' · '+n.success_rate+'% success'):'')+' · earned $'+Number(n.earned_total||0).toFixed(2)+'</div>'+
        (n.suggested_price!=null?('<div class="mini" style="margin-top:8px;padding-top:8px;border-top:1px solid var(--line)">'+
          '<b class="teal">Suggested $'+Number(n.suggested_price).toFixed(2)+'/hr</b>'+
          (n.savings_vs_cloud_pct!=null?(' <span class="badge ok">~'+Math.round(n.savings_vs_cloud_pct)+'% below cloud</span>'):'')+
          (n.auto_price?' <span class="badge">auto-price on</span>':'')+
          '<span class="mut" style="display:block;margin-top:4px">'+esc(n.suggested_reason||'')+'</span></div>'):'')+
      '</div>';}).join('');
  }
  var bl=b.blockers||[];var wb=document.getElementById('nodes_blockers');
  wb.innerHTML=bl.length?('<div class="lbl" style="margin-top:6px">To start earning</div>'+bl.map(function(x){
    return '<p class="mini" style="color:var(--warn);margin-top:6px">• '+(x.issue||'')+' <span class="mut">'+(x.fix||'')+'</span></p>';}).join('')):'';
  diskRender(ns);
}

// ---- Spare-disk rental: an explicit, always-on earner per node (provider + GB cap required) ----
var DISK_PROVIDERS=[];
async function diskProviders(){
  if(DISK_PROVIDERS.length) return DISK_PROVIDERS;
  var r=await api('/disk/providers');
  DISK_PROVIDERS=(r.ok&&r.body&&r.body.providers)||[];
  return DISK_PROVIDERS;
}
async function diskRender(ns){
  var box=document.getElementById('disk_box');if(!box)return;
  ns=(ns||[]).filter(function(n){return n.spec_id;});
  if(!ns.length){box.innerHTML='<p class="mut" style="font-size:13px">List a GPU first — its spare disk can then be rented here.</p>';return;}
  var provs=await diskProviders();
  var opts=provs.map(function(p){return '<option value="'+p.id+'">'+esc(p.name)+' (~$'+Number(p.est_usd_per_tb_month||0).toFixed(2)+'/TB/mo)</option>';}).join('');
  box.innerHTML=ns.map(function(n){var i=n.spec_id;return ''+
    '<div class="panel" style="padding:12px;margin-bottom:10px">'+
      '<div style="display:flex;justify-content:space-between;gap:10px;flex-wrap:wrap;align-items:center">'+
        '<b class="mono">'+esc(n.gpu_model||'GPU')+'</b>'+
        '<span class="mono mut" style="font-size:11px" id="disk_stat_'+i+'">…</span>'+
      '</div>'+
      '<div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-top:10px">'+
        '<select id="disk_prov_'+i+'" style="padding:8px">'+opts+'</select>'+
        '<input id="disk_gb_'+i+'" type="number" min="1" placeholder="GB cap" style="width:120px;padding:8px"/>'+
        '<button class="btn btn-teal" data-act="diskSave" data-a1="'+i+'">Enable / update</button>'+
        '<button class="btn btn-ghost" data-act="diskPause" data-a1="'+i+'">Pause</button>'+
        '<button class="btn btn-ghost" data-act="diskDelete" data-a1="'+i+'">Delete</button>'+
      '</div>'+
    '</div>';}).join('');
  ns.forEach(function(n){diskStatus(n.spec_id);});
}
async function diskStatus(i){
  var el=document.getElementById('disk_stat_'+i);if(!el)return;
  var r=await api('/nodes/'+i+'/disk');if(!r.ok){el.textContent='';return;}
  var d=r.body;
  if(d.enabled){
    var pv=document.getElementById('disk_prov_'+i);if(pv&&d.provider)pv.value=d.provider;
    var gb=document.getElementById('disk_gb_'+i);if(gb&&d.alloc_gb)gb.value=d.alloc_gb;
    el.innerHTML='<span class="teal">renting</span> '+esc(d.provider||'')+' · '+(d.alloc_gb||0)+' GB cap · '+
      Number(d.used_gb||0).toFixed(1)+' GB used · ~$'+Number(d.est_daily_usd||0).toFixed(3)+'/day · earned $'+Number(d.credited_total_usd||0).toFixed(2);
  } else {
    el.textContent='off · '+(n_diskNode(d)||'not renting');
  }
}
function n_diskNode(d){return d&&d.node_name?('node '+d.node_name):'';}
async function diskSave(i){
  var prov=(document.getElementById('disk_prov_'+i)||{}).value;
  var gb=Number((document.getElementById('disk_gb_'+i)||{}).value||0);
  if(!prov){alert('Pick a storage provider.');return;}
  if(!(gb>=1)){alert('Enter a GB cap (how much disk to rent).');return;}
  var r=await api('/nodes/disk',{method:'POST',body:JSON.stringify({spec_id:Number(i),enabled:true,provider:prov,alloc_gb:gb})});
  if(!r.ok){var m=(r.body&&r.body.error&&r.body.error.message)||(r.body&&typeof r.body.detail==='string'&&r.body.detail)||'Could not enable disk rental.';alert(m);return;}
  diskStatus(i);
}
async function diskPause(i){
  var r=await api('/nodes/disk',{method:'POST',body:JSON.stringify({spec_id:Number(i),enabled:false})});
  if(r.ok)diskStatus(i);
}
async function diskDelete(i){
  if(!confirm('Delete this disk contribution? The node stops and its data is wiped.'))return;
  var r=await api('/nodes/'+i+'/disk',{method:'DELETE'});
  if(r.ok){var gb=document.getElementById('disk_gb_'+i);if(gb)gb.value='';diskStatus(i);}
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
  <div id="pbtestmode" style="margin-top:14px"></div>
  <p class="mut" id="buy_signedout" style="display:none;margin-top:18px">Please <a class="teal" href="/login">sign in</a> to rent a GPU.</p>
  <div id="buywrap" style="margin-top:14px"><div class="skel" aria-busy="true" aria-label="Loading GPU"><span class="skel-b" style="height:30px;width:40%"></span><span class="skel-b" style="height:14px;width:72%;margin-top:16px"></span><span class="skel-b" style="height:14px;width:55%;margin-top:10px"></span><span class="skel-b" style="height:180px;width:100%;margin-top:18px"></span></div></div>
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
     '<label class="mini" for="buy_hours" style="display:block;margin-top:10px">Max runtime (hours)</label>'+
     '<input id="buy_hours" type="number" min="1" max="24" value="1" oninput="renderCost()" style="width:120px;padding:9px;margin-top:4px"/>'+
     '<label class="mini" for="buy_code" style="display:block;margin-top:12px">Code to run on the GPU</label>'+
     '<textarea id="buy_code" rows="9" class="mono" style="width:100%;margin-top:4px;padding:10px;font-size:12.5px">'+esc(DEFAULT_CODE)+'</textarea>'+
     '<div id="card-row" style="display:none;margin-top:14px">'+
       '<label class="mini" for="card-element" style="display:block">Card details</label>'+
       '<div id="card-element" style="padding:12px;border:1px solid var(--line);border-radius:8px;margin-top:4px"></div>'+
       '<div id="card-errors" class="mini" style="color:var(--warn);margin-top:6px"></div>'+
     '</div>'+
     '<button class="btn btn-amber" id="buy_pay" data-act="buyRun" style="width:100%;margin-top:16px"'+(bookable?'':' disabled')+'>Rent &amp; run →</button>'+
     '<button class="btn btn-ghost" id="buy_cancel" data-act="buyCancel" style="width:100%;margin-top:8px;display:none">Cancel &amp; release</button>'+
     '<p class="mini" id="buy_note" style="margin-top:10px">'+mode+'</p>'+
    '</div>'+
   '</div>'+
   '<div style="flex:1 1 320px;min-width:280px;position:sticky;top:88px">'+
    '<div class="card" id="buy_cost">'+
     '<div class="lbl">Estimated cost</div>'+
     '<div id="buy_cost_body" style="margin-top:6px"></div>'+
    '</div>'+
    '<div class="card" id="buy_progress" style="display:none;margin-top:16px">'+
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
 // Prefill from the /launch guided launcher (custom-code path hands off here). No secrets are
 // carried — only the code text and hours the buyer already typed on /launch.
 try{
   var pc=sessionStorage.getItem('pb_launch_code');
   if(pc!=null){var ce=el('buy_code');if(ce)ce.value=pc;sessionStorage.removeItem('pb_launch_code');
     var ph=sessionStorage.getItem('pb_launch_hours');if(ph){var he=el('buy_hours');if(he)he.value=ph;}sessionStorage.removeItem('pb_launch_hours');
     var note=el('buy_note');if(note)note.textContent='Loaded from the launcher — review and press Rent & run. '+note.textContent;}
 }catch(e){}
 renderCost();
}

// Live cost summary — never let the buyer commit without seeing what it costs. Estimate is
// rate x max-hours; the server re-prices authoritatively at authorize time. The 10% fee is a
// split OF the rental (captured = fee + seller_net), not an add-on, so it is not in the total.
function renderCost(){
 var b=el('buy_cost_body');if(!b||!GPU)return;
 var hi=el('buy_hours');
 var hours=Math.max(1,Math.min(24,parseInt((hi&&hi.value)||'1',10)||1));
 var rate=Number(GPU.price_per_hour)||0;
 var est=rate*hours;
 b.innerHTML=
  '<div class="sumrow"><span class="k">Machine</span><span class="v">'+(GPU.gpu_count>1?GPU.gpu_count+'× ':'')+esc(GPU.gpu_model)+(GPU.vram_gb?' · '+GPU.vram_gb+'GB':'')+'</span></div>'+
  '<div class="sumrow"><span class="k">Price per hour</span><span class="v">$'+rate.toFixed(2)+'</span></div>'+
  '<div class="sumrow"><span class="k">Max runtime</span><span class="v">'+hours+' h</span></div>'+
  '<div class="sumrow"><span class="k">Estimated compute cost</span><span class="v">$'+est.toFixed(2)+'</span></div>'+
  '<div class="sumrow"><span class="k">Platform fee (10%)</span><span class="v" style="color:var(--mut)">taken from host</span></div>'+
  '<div class="sumrow total"><span class="k">Estimated total</span><span class="v">$'+est.toFixed(2)+'</span></div>'+
  '<p class="mini" style="margin-top:10px">The 10% platform fee is taken from the rental — the host keeps 90%, nothing is added on top of your bill. You authorize a small headroom buffer and pay only for the GPU time you actually use; the rest of the hold is released.</p>';
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


LAUNCH_HTML = _page("Petabyte — launch compute",
    desc="Launch a GPU workload the way you would an EC2 instance: choose a curated template or your own code, pick a verified host, see the exact price, and launch.",
    path="/launch", body="""
<div class="wrap" id="lcroot" style="padding:26px 24px 60px;max-width:1180px">
  <div class="eyebrow"><span class="dot"></span> launch compute</div>
  <h1 style="font-size:clamp(28px,4.2vw,40px);margin:12px 0 6px">Launch a workload</h1>
  <p class="mut" style="max-width:66ch">Choose what to run, pick a verified host, see exactly what it costs, and launch. Every price and placement is computed on our servers — the browser only previews them.</p>
  <p class="mut" id="lc_signedout" style="display:none;margin-top:12px">You are browsing as a guest. <a class="teal" href="/login">Sign in</a> to launch — you can still explore templates and hosts below.</p>

  <div id="mytpls" class="lsec" style="display:none;margin-top:20px">
    <div class="lsec-h"><span class="stepchip" style="background:rgba(255,190,66,.12);border-color:rgba(255,190,66,.35);color:var(--amber)">★</span><h2 style="font-size:16px">Your launch templates</h2></div>
    <div class="lsec-sub" style="margin-inline-start:34px">Saved configurations you can relaunch. Stored in this browser only — no secrets.</div>
    <div id="mytplgrid" class="picks" style="margin-top:12px"></div>
  </div>

  <div class="cols" style="gap:20px;align-items:flex-start;margin-top:22px">
    <div style="flex:1.55 1 460px;min-width:320px">

      <div class="lsec" id="sec1">
        <div class="card">
          <div class="lsec-h"><span class="stepchip">1</span><h2>What do you want to run?</h2></div>
          <div class="lsec-sub">Curated, audited app templates — or your own code in a locked-down sandbox. <span class="mut">(Custom container images are on the roadmap; today Petabyte runs curated templates only.)</span></div>
          <input id="tsearch" aria-label="Search templates" placeholder="Search templates…" style="width:100%;margin-top:14px"/>
          <div id="tcats" class="seg" style="margin-top:12px;flex-wrap:wrap"></div>
          <div id="tgrid" class="picks" aria-label="Workload templates" role="radiogroup"></div>
          <div id="tdetail" style="margin-top:14px"></div>
        </div>
      </div>

      <div class="lsec locked" id="sec2" aria-disabled="true">
        <div class="card">
          <div class="lsec-h"><span class="stepchip">2</span><h2>Choose compute</h2></div>
          <div class="lsec-sub">Verified hosts. Hosts are anonymous — you pick by hardware, reputation and price.</div>
          <div id="computebody" style="margin-top:12px"></div>
        </div>
      </div>

      <div class="lsec locked" id="sec3" aria-disabled="true">
        <div class="card">
          <div class="lsec-h"><span class="stepchip">3</span><h2>Configure</h2></div>
          <div id="configbody" style="margin-top:12px"></div>
        </div>
      </div>

      <div class="lsec locked" id="sec4" aria-disabled="true">
        <div class="card">
          <div class="lsec-h"><span class="stepchip">4</span><h2>Review &amp; launch</h2></div>
          <div id="reviewbody" style="margin-top:12px"></div>
        </div>
      </div>
    </div>

    <div style="flex:1 1 300px;min-width:280px;position:sticky;top:88px">
      <div class="card">
        <div class="lbl">Your configuration</div>
        <div id="costbody" style="margin-top:6px"><p class="mut" style="font-size:13px">Pick a workload to see pricing.</p></div>
        <div id="reviewactions" style="margin-top:16px;display:none">
          <button id="reviewbtn" class="btn btn-amber" style="width:100%;justify-content:center">Review &amp; Launch →</button>
          <button id="savetplbtn" class="btn btn-ghost" style="width:100%;justify-content:center;margin-top:8px">Save as template</button>
        </div>
        <p class="mini" style="margin-top:10px">Estimated. The final charge is metered to the second on our servers and can never exceed the authorized maximum — the rest is refunded.</p>
      </div>
      <div id="launchstatus" class="card" style="display:none;margin-top:14px"></div>
    </div>
  </div>
</div>
<script>
(function(){
 function esc(s){return String(s==null?'':s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/\"/g,'&quot;');}
 function mUSD(x){return '$'+Number(x||0).toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2});}
 function el(id){return document.getElementById(id);}
 var CATS=[['all','All'],['notebook','Notebooks'],['ai','AI / LLM'],['art','Image / Art'],['render','Render / Video'],['game','Game servers']];
 // Frontend guidance only — the server (/route, /estimate, /launch) is authoritative on placement.
 var REC_VRAM={vllm:24,'tensorrt-llm':24,ollama:16,comfyui:12,'sd-webui':12,jupyter:16,pytorch:16,blender:8,ffmpeg:8};
 var DEF_MODEL={ollama:'llama3',vllm:'Qwen/Qwen2.5-1.5B-Instruct'};
 var DEFAULT_CODE=\"""" + DEFAULT_WORKLOAD + """\";
 var S={type:null,template:null,model:'',hours:1,spec:null,region:'',maxPrice:'',minVram:0,confidential:false,sort:'price',code:DEFAULT_CODE,place:'auto'};
 var TPL=[],SPECS=[],WALLET=null,EST=null,LAUNCHING=false,EST_SEQ=0;

 function saveDraft(){try{var d={type:S.type,template:S.template,model:S.model,hours:S.hours,region:S.region,maxPrice:S.maxPrice,minVram:S.minVram,confidential:S.confidential,sort:S.sort,place:S.place,spec:S.spec?S.spec.id:null};sessionStorage.setItem('pb_launch_draft',JSON.stringify(d));}catch(e){}}
 // ---------- section locking ----------
 function unlock(n){for(var i=2;i<=4;i++){var s=el('sec'+i);if(!s)continue;var on=i<=n;s.classList.toggle('locked',!on);s.setAttribute('aria-disabled',on?'false':'true');}}

 // ---------- 1. templates ----------
 function catChips(){var c=el('tcats');c.innerHTML=CATS.map(function(k){return '<button type="button" data-lc="cat" data-v="'+k[0]+'" aria-pressed="'+(S._cat===k[0]||(!S._cat&&k[0]==='all'))+'">'+k[1]+'</button>';}).join('');}
 function tCards(){
  var q=(el('tsearch').value||'').toLowerCase().trim(),cat=S._cat||'all';
  var list=TPL.filter(function(t){
    if(cat!=='all'&&t.kind!==cat)return false;
    if(q&&(t.name+' '+(t.desc||'')).toLowerCase().indexOf(q)<0)return false;
    return true;});
  var cards=list.map(function(t){
    var rec=REC_VRAM[t.name];
    return '<button type="button" class="pick" role="radio" aria-checked="'+(S.type==='app'&&S.template===t.name)+'" data-lc="pickTpl" data-type="app" data-v="'+esc(t.name)+'">'+
      '<span class="pk-check">✓</span>'+
      '<span class="pk-top"><span class="pk-ic">'+pbIcon(t.name)+'</span><span class="pk-name">'+esc(t.name)+'</span></span>'+
      '<span class="pk-desc">'+esc(t.desc||'')+'</span>'+
      '<span class="pk-meta">'+(t.gpu?'<span class="badge ok">GPU</span>':'<span class="badge">CPU</span>')+
        (rec?'<span class="badge">'+rec+'GB+ VRAM</span>':'')+
        (t.port?'<span class="badge">:'+t.port+'</span>':'<span class="badge">batch</span>')+'</span>'+
    '</button>';}).join('');
  // the always-available "custom code" workload (notebook pipeline)
  var custom='<button type="button" class="pick" role="radio" aria-checked="'+(S.type==='code')+'" data-lc="pickTpl" data-type="code" data-v="__code__">'+
      '<span class="pk-check">✓</span>'+
      '<span class="pk-top"><span class="pk-ic">'+pbIcon('pytorch')+'</span><span class="pk-name">Custom code</span></span>'+
      '<span class="pk-desc">Run your own Python in a locked, network-isolated sandbox on a host you choose.</span>'+
      '<span class="pk-meta"><span class="badge ok">GPU</span><span class="badge">notebook</span></span>'+
    '</button>';
  var showCustom=(cat==='all'||cat==='notebook')&&(!q||'custom code python notebook'.indexOf(q)>=0);
  el('tgrid').innerHTML=cards+(showCustom?custom:'')||'<p class="mut" style="font-size:13px;grid-column:1/-1">No templates match. <a class="teal" href="#" data-lc="clearsearch">Clear search</a></p>';
 }
 function tDetail(){
  var d=el('tdetail');
  if(S.type==='code'){
    d.innerHTML='<div class="panel" style="padding:14px 16px"><div class="lbl" style="margin-bottom:8px">Custom code · notebook</div>'+
      '<p class="mini">Your Python runs inside a hardened container: no network, read-only filesystem, dropped capabilities, fixed CPU/RAM. Choose the host in the next step, then edit the code in Configure.</p></div>';return;}
  if(S.type!=='app'){d.innerHTML='';return;}
  var t=TPL.filter(function(x){return x.name===S.template;})[0];if(!t){d.innerHTML='';return;}
  var rec=REC_VRAM[t.name];
  var rows=''+
    row('Environment','Curated Docker image, audited by Petabyte')+
    row('Category',({ai:'AI / LLM',art:'Image / Art',render:'Render / Video',game:'Game server',notebook:'Notebook'})[t.kind]||t.kind)+
    (rec?row('Recommended VRAM',rec+' GB or more'):'')+
    row('Access',t.port?('In-container service on port '+t.port+' (reached over your private tunnel)'):'Batch job (no exposed port)')+
    row('Network egress',(t.egress==='none'?'None (fully isolated)':(t.egress==='open'?'Open':'Limited')))+
    row('Publisher','Petabyte')+
    row('Status','<span class="badge st ok">Curated · verified</span>');
  var modelField=DEF_MODEL[t.name]!==undefined?
    '<label class="mini" for="lc_model" style="display:block;margin-top:12px">Model</label>'+
    '<input id="lc_model" value="'+esc(S.model||DEF_MODEL[t.name])+'" placeholder="'+esc(DEF_MODEL[t.name])+'" style="width:100%;max-width:360px;margin-top:4px"/>'+
    '<p class="mini" style="margin-top:5px">The model this server will pull and serve. This is the one runtime parameter this template accepts.</p>':'';
  d.innerHTML='<div class="panel" style="padding:16px"><div class="lbl" style="margin-bottom:8px">'+esc(t.name)+' — details</div>'+rows+modelField+'</div>';
  var mi=el('lc_model');if(mi)mi.addEventListener('input',function(){S.model=mi.value;saveDraft();});
 }
 function row(k,v){return '<div class="sumrow"><span class="k">'+k+'</span><span class="v" style="max-width:60%">'+v+'</span></div>';}

 function pickTpl(type,v){
  if(type==='code'){S.type='code';S.template=null;}
  else{S.type='app';S.template=v;if(DEF_MODEL[v]!==undefined&&!S.model)S.model=DEF_MODEL[v];S.place='auto';}
  // reset a machine choice that no longer applies
  if(type==='app')S.spec=S.spec;  // keep any preview
  tCards();tDetail();renderCompute();renderConfig();unlock(3);saveDraft();refreshCost();
  el('sec2').scrollIntoView({behavior:'smooth',block:'nearest'});
 }

 // ---------- 2. compute ----------
 function renderCompute(){
  var b=el('computebody');
  var appMode=(S.type==='app');
  var head=appMode?
    '<div class="seg" role="radiogroup" aria-label="Placement" style="margin-bottom:6px">'+
      '<button type="button" data-lc="place" data-v="auto" aria-pressed="'+(S.place==='auto')+'">Auto-place (recommended)</button>'+
      '<button type="button" data-lc="place" data-v="pick" aria-pressed="'+(S.place==='pick')+'">Browse hosts</button>'+
    '</div>':'';
  var note=appMode&&S.place==='auto'?
    '<p class="mini" style="margin:6px 0 4px">Petabyte places this on the cheapest verified host that meets the template requirements and your limits below. You are charged that host&#39;s rate.</p>':
    (appMode?'<p class="mini" style="margin:6px 0 4px">Pick the exact host this template runs on — your estimate and launch both use it. If it goes offline first, launch says so before anything is charged.</p>':
             '<p class="mini" style="margin:6px 0 4px">Pick the exact host your code runs on.</p>');
  var filters=
    '<div class="filterbar" style="margin:10px 0 4px">'+
      '<label class="field" style="flex:0 0 auto"><span>Sort</span>'+
        '<span class="seg"><button type="button" data-lc="sort" data-v="price" aria-pressed="'+(S.sort==='price')+'">Cheapest</button>'+
        '<button type="button" data-lc="sort" data-v="rep" aria-pressed="'+(S.sort==='rep')+'">Best rep</button>'+
        '<button type="button" data-lc="sort" data-v="vram" aria-pressed="'+(S.sort==='vram')+'">Most VRAM</button></span></label>'+
      '<label class="field"><span>Min VRAM (GB)</span><input id="f_vram" type="number" min="0" value="'+(S.minVram||'')+'" placeholder="any" style="width:100px"/></label>'+
      '<label class="field"><span>Max $/hr</span><input id="f_price" type="number" min="0" step="0.01" value="'+(S.maxPrice||'')+'" placeholder="any" style="width:100px"/></label>'+
      '<label class="field"><span>Region</span><input id="f_region" value="'+esc(S.region||'')+'" placeholder="any" style="width:120px"/></label>'+
    '</div>';
  var showList=(!appMode)||(S.place==='pick');
  b.innerHTML=head+note+((appMode&&S.place==='auto')?
      '<div id="autopreview" style="margin-top:8px"></div>':
      filters+'<div id="mlist" aria-label="Available hosts"></div>');
  if(appMode&&S.place==='auto'){renderAutoPreview();}
  else{
    var vf=el('f_vram'),pf=el('f_price'),rf=el('f_region');
    if(vf)vf.addEventListener('input',function(){S.minVram=vf.value;saveDraft();renderMachineList();});
    if(pf)pf.addEventListener('input',function(){S.maxPrice=pf.value;saveDraft();renderMachineList();});
    if(rf)rf.addEventListener('input',function(){S.region=rf.value;saveDraft();renderMachineList();});
    renderMachineList();
  }
 }
 function specQuery(){
  var p=[];p.push('sort='+encodeURIComponent(S.sort||'price'));
  if(S.minVram)p.push('min_vram='+encodeURIComponent(S.minVram));
  if(S.maxPrice)p.push('max_price='+encodeURIComponent(S.maxPrice));
  if(S.region)p.push('region='+encodeURIComponent(S.region));
  return '/marketplace/specs?'+p.join('&');
 }
 function compatFor(s){
  var rec=(S.type==='app'&&REC_VRAM[S.template])||0;
  if(!rec)return {ok:true,html:''};
  var ok=(s.vram_gb||0)>=rec;
  return {ok:ok,html:'<span class="compat" style="color:'+(ok?'var(--pos)':'var(--warn)')+'">'+(ok?'✓':'⚠')+' '+(ok?'meets':'below')+' '+rec+'GB rec.</span>'};
 }
 function machineRow(s){
  var trust=s.trust?('<span class="badge '+(s.trust.rank>=2?'ok':'')+'" title="'+esc(s.trust.evidence||'')+'">'+esc(s.trust.label)+'</span>'):'';
  var rep=s.reputation_score!=null?('<span class="mp-col">rep '+s.reputation_score+'</span>'):'';
  var c=compatFor(s);
  return '<button type="button" class="mpick" role="radio" aria-checked="'+(S.spec&&S.spec.id===s.id)+'" data-lc="pickMachine" data-v="'+esc(s.id)+'">'+
    '<span class="mp-gpu">'+(s.gpu_count>1?s.gpu_count+'× ':'')+esc(s.gpu_model||'CPU')+' '+trust+'</span>'+
    '<span class="mp-col">'+(s.vram_gb?s.vram_gb+'GB':'—')+' VRAM</span>'+
    '<span class="mp-col">'+(s.cpu?s.cpu+' vCPU':'')+(s.ram_gb?' · '+s.ram_gb+'GB':'')+'</span>'+
    '<span class="mp-col">'+esc(s.region||'—')+'</span>'+rep+
    (c.html?'<span class="mp-col">'+c.html+'</span>':'')+
    '<span class="mp-price">'+mUSD(s.price_per_hour)+'<span class="mut" style="font-size:11px">/hr</span></span>'+
  '</button>';
 }
 async function renderMachineList(){
  var box=el('mlist');if(!box)return;
  box.innerHTML='<div class="mut mono" style="padding:14px 0;font-size:13px">Finding hosts…</div>';
  try{
   var r=await fetch(specQuery());var b=await r.json();SPECS=b.specs||[];
   if(!SPECS.length){box.innerHTML='<div class="empty" style="padding:26px 12px"><div class="et">No hosts match</div><div class="es">Relax the filters, or check back — availability updates live.</div></div>';return;}
   box.innerHTML=SPECS.map(machineRow).join('');
  }catch(e){box.innerHTML='<p class="mut" style="font-size:13px">Could not load hosts. <a class="teal" href="#" data-lc="reloadmachines">Retry</a></p>';}
 }
 async function renderAutoPreview(){
  var box=el('autopreview');if(!box)return;
  box.innerHTML='<div class="mut mono" style="font-size:13px">Checking matching hosts…</div>';
  try{
   var p=[];p.push('sort=price');if(S.type==='app'&&REC_VRAM[S.template])p.push('min_vram='+REC_VRAM[S.template]);
   var r=await fetch('/marketplace/specs?'+p.join('&'));var b=await r.json();var ss=b.specs||[];
   if(!ss.length){box.innerHTML='<p class="mini" style="color:var(--warn)">⚠ No verified host currently meets this template&#39;s requirements. Try "Browse hosts" or check back shortly.</p>';return;}
   var cheapest=ss[0];
   box.innerHTML='<div class="panel" style="padding:12px 14px"><div class="compat" style="color:var(--pos)">✓ '+ss.length+' verified host'+(ss.length>1?'s':'')+' match — cheapest from '+mUSD(cheapest.price_per_hour)+'/hr ('+esc(cheapest.gpu_model||'CPU')+', '+(cheapest.vram_gb||0)+'GB).</div>'+
     '<p class="mini" style="margin-top:6px">Your final host and price are locked in server-side at launch.</p></div>';
  }catch(e){box.innerHTML='';}
 }
 function pickMachine(id){
  var s=SPECS.filter(function(x){return x.id===id;})[0];if(!s)return;S.spec=s;
  document.querySelectorAll('#mlist .mpick').forEach(function(n){n.setAttribute('aria-checked', n.getAttribute('data-v')===id?'true':'false');});
  renderConfig();unlock(3);saveDraft();refreshCost();
 }

 // ---------- 3. configure ----------
 function renderConfig(){
  var b=el('configbody');
  var hrs='<label class="mini" for="lc_hours" style="display:block">Max runtime (hours)</label>'+
    '<input id="lc_hours" type="number" min="1" max="24" value="'+(S.hours||1)+'" style="width:120px;margin-top:4px"/>'+
    '<p class="mini" style="margin-top:5px">Sizes the pre-authorization hold (a small buffer is added). You pay only for the time actually used; the rest is released.</p>';
  var code=S.type==='code'?
    '<label class="mini" for="lc_code" style="display:block;margin-top:14px">Code to run</label>'+
    '<textarea id="lc_code" rows="9" class="mono" style="width:100%;margin-top:4px;font-size:12.5px">'+esc(S.code||DEFAULT_CODE)+'</textarea>':'';
  var adv=(S.type==='app')?
    '<details style="margin-top:14px"><summary style="cursor:pointer;font-family:var(--disp);font-weight:600;font-size:13.5px">Advanced placement</summary>'+
      '<div style="margin-top:10px">'+
      '<label class="mini" for="lc_maxp" style="display:block">Max price ($/hr)</label><input id="lc_maxp" type="number" min="0" step="0.01" value="'+(S.maxPrice||'')+'" placeholder="no limit" style="width:140px;margin-top:4px"/>'+
      '<label class="mini" for="lc_reg" style="display:block;margin-top:10px">Preferred region</label><input id="lc_reg" value="'+esc(S.region||'')+'" placeholder="any" style="width:180px;margin-top:4px"/>'+
      '<p class="mini" style="margin-top:8px">Environment variables, custom ports and persistent storage are not configurable on curated templates yet — Petabyte sets them per audited template.</p>'+
      '</div></details>':
    '<p class="mini" style="margin-top:12px">This runs your code as-is. Custom container images, environment variables, ports and extra storage are not available on this path yet.</p>';
  b.innerHTML=hrs+code+adv;
  var h=el('lc_hours');if(h)h.addEventListener('input',function(){S.hours=Math.max(1,Math.min(24,parseInt(h.value||'1',10)||1));saveDraft();refreshCost();});
  var cd=el('lc_code');if(cd)cd.addEventListener('input',function(){S.code=cd.value;saveDraft();});
  var mp=el('lc_maxp');if(mp)mp.addEventListener('input',function(){S.maxPrice=mp.value;saveDraft();});
  var rg=el('lc_reg');if(rg)rg.addEventListener('input',function(){S.region=rg.value;saveDraft();});
 }

 // ---------- cost panel (server-authoritative /estimate) ----------
 // In "Browse hosts" mode the buyer is pinning a specific host, so we can't price (or launch)
 // until one is actually selected — otherwise a missing pick would silently auto-place. Auto
 // mode needs no host up front.
 function canEstimate(){if(S.type==='code')return !!S.spec;if(S.type==='app')return S.place!=='pick'||!!S.spec;return false;}
 async function refreshCost(){
  var cb=el('costbody');
  if(!canEstimate()){cb.innerHTML='<p class="mut" style="font-size:13px">'+(S.type?'Choose a host to price this run.':'Pick a workload to see pricing.')+'</p>';el('reviewactions').style.display='none';return;}
  cb.innerHTML='<div class="mut mono" style="font-size:13px;padding:6px 0">Pricing…</div>';
  // Invalidate any in-flight estimate and lock launch until the fresh price lands, so a
  // slower earlier response can never overwrite a newer one or leave a stale total launchable.
  EST=null;renderReview();
  var body={hours:S.hours};
  if(S.type==='code'){body.spec_id=S.spec.id;}
  else{body.template=S.template;if(S.place==='pick'&&S.spec)body.spec_id=S.spec.id;}   // honor the chosen host
  var seq=++EST_SEQ;
  try{
   var r=await fetch('/estimate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
   if(seq!==EST_SEQ)return;                    // a newer estimate started; drop this one
   if(!r.ok){cb.innerHTML='<p class="mut" style="font-size:13px">'+(r.status===404?'No matching host is available right now.':'Could not price this yet.')+'</p>';el('reviewactions').style.display='none';return;}
   var est=await r.json();
   if(seq!==EST_SEQ)return;
   EST=est;
   var mach=(S.spec&&(S.type==='code'||S.place==='pick'))?((S.spec.gpu_count>1?S.spec.gpu_count+'× ':'')+esc(S.spec.gpu_model)):(esc(EST.gpu_model||'CPU')+' (auto)');
   var cloud=EST.cloud_comparison?('<div class="sumrow"><span class="k">A hyperscaler would cost</span><span class="v" style="color:var(--mut)">~'+mUSD(EST.cloud_comparison.reference_total)+'</span></div>'):'';
   cb.innerHTML=
    '<div class="sumrow"><span class="k">Workload</span><span class="v">'+(S.type==='code'?'Custom code':esc(S.template))+'</span></div>'+
    '<div class="sumrow"><span class="k">Machine</span><span class="v">'+mach+'</span></div>'+
    '<div class="sumrow"><span class="k">Rate</span><span class="v">'+mUSD(EST.price_per_hour)+'/hr</span></div>'+
    '<div class="sumrow"><span class="k">Max runtime</span><span class="v">'+EST.hours+' h</span></div>'+
    '<div class="sumrow"><span class="k">Min charge (1h)</span><span class="v">'+mUSD(EST.min_charge)+'</span></div>'+
    '<div class="sumrow"><span class="k">Platform fee</span><span class="v" style="color:var(--mut)">incl. (from host)</span></div>'+
    cloud+
    '<div class="sumrow total"><span class="k">Estimated total</span><span class="v">'+mUSD(EST.total)+'</span></div>';
   if(WALLET){
     var short=Number(EST.total)>Number(WALLET.balance);
     cb.innerHTML+='<div class="sumrow"><span class="k">Wallet balance</span><span class="v" style="color:'+(short?'var(--warn)':'var(--mut)')+'">'+mUSD(WALLET.balance)+'</span></div>'+
       (short?'<p class="mini" style="color:var(--warn);margin-top:8px">⚠ Estimated total is above your balance. <a class="teal" href="/account">Add funds</a> before launching.</p>':'');
   }
   el('reviewactions').style.display=authed()?'':'none';
   renderReview();unlock(4);
  }catch(e){if(seq!==EST_SEQ)return;cb.innerHTML='<p class="mut" style="font-size:13px">Could not reach pricing.</p>';}
 }

 // ---------- 4. review ----------
 function renderReview(){
  var b=el('reviewbody');if(!EST){b.innerHTML='<p class="mut" style="font-size:13px">Complete the steps above.</p>';return;}
  var rows=
    row('Workload',S.type==='code'?'Custom code (notebook)':esc(S.template)+(S.model?(' · model '+esc(S.model)):''))+
    row('Machine',(S.spec&&(S.type==='code'||S.place==='pick'))?((S.spec.gpu_count>1?S.spec.gpu_count+'× ':'')+esc(S.spec.gpu_model)+' · '+(S.spec.vram_gb||0)+'GB · '+esc(S.spec.region||'')):(esc(EST.gpu_model||'CPU')+' · auto-placed · '+esc(EST.region||'')))+
    row('Runtime',EST.hours+' hour(s) max')+
    row('Rate',mUSD(EST.price_per_hour)+'/hr')+
    row('Estimated total',mUSD(EST.total))+
    (WALLET?row('Wallet',mUSD(WALLET.balance)):'');
  b.innerHTML='<div class="panel" style="padding:16px">'+rows+'</div>'+
    '<p class="mini" style="margin-top:10px">Launching authorizes up to a maximum on your card/wallet and starts the workload. You are charged only for what you use.</p>'+
    '<div style="display:flex;gap:10px;flex-wrap:wrap;margin-top:12px">'+
     '<button type="button" class="btn btn-amber" id="launchbtn" data-lc="launch" style="flex:1;min-width:180px;justify-content:center">'+(authed()?'Launch compute →':'Sign in to launch')+'</button>'+
    '</div>';
 }

 // ---------- launch ----------
 async function doLaunch(){
  if(LAUNCHING)return;
  if(!authed()){location.href='/login';return;}
  var btn=el('launchbtn');
  if(S.type==='code'){
    // hand off to the polished, tested notebook checkout with our config carried over
    if(!S.spec){return;}
    try{sessionStorage.setItem('pb_launch_code',S.code||DEFAULT_CODE);sessionStorage.setItem('pb_launch_hours',String(S.hours||1));}catch(e){}
    location.href='/buy/'+S.spec.id;return;
  }
  LAUNCHING=true;if(btn){btn.disabled=true;btn.textContent='Launching…';}
  var st=el('launchstatus');st.style.display='';
  function stage(msg,done){st.innerHTML='<div class="lbl">Launching</div><div id="lc_stage" style="font-family:var(--disp);font-size:15px;margin:8px 0">'+msg+'</div>'+(done||'');}
  stage('Reserving a verified host…');
  var body={template:S.template,hours:S.hours||1};
  if(S.model)body.template_params={model:S.model};
  if(S.maxPrice)body.max_price_per_hour=Number(S.maxPrice);
  if(S.region)body.region=S.region;
  if(S.place==='pick'&&S.spec)body.spec_id=S.spec.id;   // honor the buyer's explicit host choice
  var r=await api('/launch',{method:'POST',body:JSON.stringify(body)});
  if(r.status===401){LAUNCHING=false;location.href='/login';return;}
  if(r.status===402){LAUNCHING=false;if(btn){btn.disabled=false;btn.textContent='Launch compute →';}stage('Not enough balance.','<a class="btn btn-teal" href="/account" style="margin-top:6px">Add funds</a>');return;}
  if(!r.ok){
    LAUNCHING=false;if(btn){btn.disabled=false;btn.textContent='Launch compute →';}
    var e=(r.body&&r.body.error)||{};var msg=e.message||(r.status===409?'No matching host is online right now. Try again shortly.':'Something went wrong. Nothing was charged.');
    stage('Could not launch.','<div class="mut" style="font-size:13px;margin-top:4px">'+esc(msg)+'</div>'+(e.request_id?'<div class="mini" style="margin-top:8px">Reference '+esc(e.request_id)+'</div>':''));
    return;}
  var b=r.body;
  stage('Reserved on '+esc(b.gpu_model||'a host')+' — starting…',
    '<div class="mini" style="margin-top:8px">Booking #'+esc(b.booking_id)+' · '+mUSD(b.gross_amount)+' / '+b.hours+'h</div>'+
    (((b.url&&(b.url.ssh||b.url.http)))?'<pre style="margin-top:10px;white-space:pre-wrap;font-size:12px">'+esc((b.url.ssh||'')+(b.url.http?('\\n'+b.url.http):''))+'</pre>':'')+
    '<div class="mut" id="lc_prep" style="margin-top:8px;font-size:13px">Preparing your workload…</div>');
  try{sessionStorage.removeItem('pb_launch_draft');}catch(e){}
  pollVM(b.vm_id,b.port);
 }
 function pollVM(vmid,port){
  var prep=el('lc_prep'),t0=Date.now();
  var iv=setInterval(async function(){
   var r=await api('/vm/'+vmid);if(!r.ok)return;var s=r.body.status;
   if(s==='running'){clearInterval(iv);if(prep)prep.innerHTML='<b class="teal">Running</b> — connect at the address above'+(port?(' (port '+port+')'):'')+'. Manage it under <a class="teal" href="/account">your account</a>.';}
   else if(s==='failed'){clearInterval(iv);if(prep)prep.textContent='No host could start it — you were refunded.';}
   else if(s==='migrating'){if(prep)prep.textContent='Host changed — reconnecting (same address)…';}
   else if(Date.now()-t0>90000){clearInterval(iv);if(prep)prep.innerHTML='Still starting — track it under <a class="teal" href="/account">your account</a>.';}
   else if(prep){prep.textContent='Preparing your workload… ('+s+')';}
  },2500);
 }

 // ---------- launch templates (localStorage; NO secrets) ----------
 function tplKey(){return 'pb_launch_templates';}
 function loadTpls(){try{return JSON.parse(localStorage.getItem(tplKey())||'[]');}catch(e){return [];}}
 function saveTpls(a){try{localStorage.setItem(tplKey(),JSON.stringify(a));}catch(e){}}
 function renderMyTpls(){
  var a=loadTpls();var wrap=el('mytpls');if(!a.length){wrap.style.display='none';return;}
  wrap.style.display='';
  el('mytplgrid').innerHTML=a.map(function(t,i){
   return '<div class="pick" style="cursor:default">'+
     '<span class="pk-top"><span class="pk-ic">'+pbIcon(t.template||'pytorch')+'</span><span class="pk-name">'+esc(t.name)+'</span></span>'+
     '<span class="pk-desc">'+esc(t.type==='code'?'Custom code':(t.template||''))+' · '+(t.hours||1)+'h'+(t.minVram?(' · '+t.minVram+'GB+'):'')+'</span>'+
     '<span class="pk-meta" style="margin-top:6px">'+
       '<button type="button" class="btn btn-amber" style="padding:6px 12px;font-size:12px" data-lc="tplLaunch" data-v="'+i+'">Launch</button>'+
       '<button type="button" class="btn btn-ghost" style="padding:6px 12px;font-size:12px" data-lc="tplDup" data-v="'+i+'">Duplicate</button>'+
       '<button type="button" class="btn btn-ghost" style="padding:6px 12px;font-size:12px" data-lc="tplDel" data-v="'+i+'">Delete</button>'+
     '</span></div>';
  }).join('');
 }
 function saveAsTemplate(){
  if(!S.type){return;}
  var name=prompt('Name this launch template:',(S.type==='code'?'Custom code':S.template)+' · '+(S.hours||1)+'h');
  if(!name)return;
  var a=loadTpls();
  a.unshift({name:name,type:S.type,template:S.template,model:S.model||'',hours:S.hours||1,minVram:S.minVram||(REC_VRAM[S.template]||0),maxPrice:S.maxPrice||'',region:S.region||'',code:S.type==='code'?(S.code||''):''});
  saveTpls(a);renderMyTpls();
  var sb=el('savetplbtn');if(sb){var o=sb.textContent;sb.textContent='Saved ✓';setTimeout(function(){sb.textContent=o;},1400);}
 }
 function applyTpl(t){
  S.type=t.type;S.template=t.template||null;S.model=t.model||'';S.hours=t.hours||1;S.minVram=t.minVram||0;S.maxPrice=t.maxPrice||'';S.region=t.region||'';
  if(t.type==='code'){S.code=t.code||DEFAULT_CODE;S.place='pick';}else{S.place='auto';}
  S._cat='all';S.spec=null;
  catChips();tCards();tDetail();renderCompute();renderConfig();unlock(t.type==='code'?2:3);saveDraft();refreshCost();
  el('sec1').scrollIntoView({behavior:'smooth',block:'start'});
 }

 // ---------- delegated events ----------
 el('lcroot').addEventListener('click',function(e){
  var t=e.target.closest('[data-lc]');if(!t)return;
  var act=t.getAttribute('data-lc'),v=t.getAttribute('data-v');
  if(act==='pickTpl'){e.preventDefault();pickTpl(t.getAttribute('data-type'),v);}
  else if(act==='cat'){S._cat=v;catChips();tCards();}
  else if(act==='place'){e.preventDefault();S.place=v;renderCompute();refreshCost();saveDraft();}
  else if(act==='sort'){S.sort=v;renderCompute();}
  else if(act==='pickMachine'){e.preventDefault();pickMachine(v);}
  else if(act==='launch'){e.preventDefault();doLaunch();}
  else if(act==='clearsearch'){e.preventDefault();el('tsearch').value='';tCards();}
  else if(act==='reloadmachines'){e.preventDefault();renderMachineList();}
  else if(act==='tplLaunch'){e.preventDefault();applyTpl(loadTpls()[+v]);}
  else if(act==='tplDup'){e.preventDefault();var a=loadTpls();var c=JSON.parse(JSON.stringify(a[+v]));c.name=c.name+' (copy)';a.unshift(c);saveTpls(a);renderMyTpls();}
  else if(act==='tplDel'){e.preventDefault();var a=loadTpls();a.splice(+v,1);saveTpls(a);renderMyTpls();}
 });
 // keyboard: Enter/Space activate a role=radio card
 el('lcroot').addEventListener('keydown',function(e){
  if(e.key!=='Enter'&&e.key!==' ')return;
  var t=e.target.closest('.pick[role="radio"],.mpick[role="radio"]');if(!t)return;
  e.preventDefault();t.click();
 });
 el('tsearch').addEventListener('input',tCards);
 el('reviewbtn').addEventListener('click',function(){el('sec4').scrollIntoView({behavior:'smooth',block:'start'});renderReview();});
 el('savetplbtn').addEventListener('click',saveAsTemplate);

 // ---------- boot ----------
 async function boot(){
  if(!authed())el('lc_signedout').style.display='';
  try{var meR=await api('/me');if(meR.ok)WALLET={balance:meR.body.balance,earnings:meR.body.earnings};}catch(e){}
  try{var r=await fetch('/templates');var b=await r.json();TPL=b.templates||[];
      TPL.forEach(function(t){if(t.min_vram)REC_VRAM[t.name]=t.min_vram;});}catch(e){TPL=[];}   // server is the source of truth
  S._cat='all';catChips();tCards();renderMyTpls();
  // deep links + draft
  var qs=new URLSearchParams(location.search);
  var qt=qs.get('template'),qspec=qs.get('spec');
  var draft=null;try{draft=JSON.parse(sessionStorage.getItem('pb_launch_draft')||'null');}catch(e){}
  if(qt&&TPL.filter(function(x){return x.name===qt;})[0]){pickTpl('app',qt);}
  else if(qspec){S.type='code';S.template=null;
    try{var sr=await fetch('/marketplace/specs/'+encodeURIComponent(qspec));if(sr.ok){var sd=await sr.json();sd.id=qspec;S.spec=sd;}}catch(e){}
    tCards();tDetail();renderCompute();renderConfig();unlock(3);refreshCost();
    el('sec2').scrollIntoView({behavior:'smooth',block:'nearest'});}
  else if(draft&&draft.type){
    S.type=draft.type;S.template=draft.template;S.model=draft.model||'';S.hours=draft.hours||1;S.region=draft.region||'';S.maxPrice=draft.maxPrice||'';S.minVram=draft.minVram||0;S.sort=draft.sort||'price';S.place=draft.place||'auto';
    // Restore the exact host the buyer had chosen (custom code, or an app "Browse hosts" pick)
    if(draft.spec){try{var dsr=await fetch('/marketplace/specs/'+encodeURIComponent(draft.spec));if(dsr.ok){var dsd=await dsr.json();dsd.id=draft.spec;S.spec=dsd;}}catch(e){}}
    tCards();tDetail();renderCompute();renderConfig();
    if(draft.type==='app'){unlock(3);refreshCost();}
    else if(S.spec){unlock(3);refreshCost();}   // code draft with its host back → straight to pricing
    else{unlock(2);}                             // code draft without a host → resume at host choice
  }
 }
 boot();
})();
</script>""")

CLUSTER_HTML = _page("Petabyte — distributed compute",
    desc="Run one job across many GPUs on different machines, wired into a single cluster over the VPN — or bring your own scheduler (Slurm/MPI/Ray) and use Petabyte as another provider.",
    path="/cluster", body="""
<div class="wrap" style="padding:34px 24px 44px;max-width:1000px">
  <div class="eyebrow"><span class="dot"></span> distributed compute</div>
  <h1 style="font-size:clamp(26px,3.6vw,38px);margin:14px 0 6px">Run one job across <span class="grad-teal">many GPUs</span></h1>
  <p class="mut" style="max-width:66ch">Split a single job across GPUs on <b>different machines</b>, wired into one cluster over the VPN (torchrun/NCCL). Gang-scheduled — one rank per machine — and escrowed all-or-nothing: a cluster that can't fully form is refused and refunded.</p>
  <div id="pbtestmode" style="margin-top:12px"></div>
  <p class="mut" id="cl_signedout" style="display:none;margin-top:10px">Please <a class="teal" href="/login">sign in</a> to launch a cluster.</p>
  <div id="cl_avail" class="mono mut" style="margin-top:12px;font-size:13px">Checking available machines…</div>
  <div class="cols" style="gap:18px;align-items:flex-start;margin-top:16px">
    <div style="flex:1.2 1 360px;min-width:300px">
      <div class="card">
        <div class="lbl">Your cluster</div>
        <label class="mini" style="display:block;margin-top:10px">GPUs — one per machine</label>
        <input id="cl_n" type="number" min="2" value="4" oninput="clusterEst()" style="width:130px;padding:9px;margin-top:4px"/>
        <label class="mini" style="display:block;margin-top:12px">Max runtime (hours)</label>
        <input id="cl_hours" type="number" min="1" max="168" value="1" oninput="clusterEst()" style="width:130px;padding:9px;margin-top:4px"/>
        <label class="mini" style="display:block;margin-top:12px">Collective backend</label>
        <select id="cl_backend" style="padding:9px;margin-top:4px;width:160px"><option value="nccl">NCCL (GPU)</option><option value="gloo">Gloo (CPU/fallback)</option></select>
        <label style="display:flex;gap:8px;align-items:center;margin-top:14px;cursor:pointer">
          <input id="cl_vpn" type="checkbox"/>
          <span class="mini">Private network (VPN) — get a WireGuard tunnel into your cluster</span></label>
        <label style="display:flex;gap:8px;align-items:center;margin-top:10px;cursor:pointer">
          <input id="cl_selftest" type="checkbox" onchange="clusterSelftest()"/>
          <span class="mini">Cluster self-test first — every rank runs a real all-reduce to prove the cluster communicates and reduces correctly (no image needed)</span></label>
        <label class="mini" style="display:block;margin-top:12px">Container image</label>
        <input id="cl_image" value="pytorch/pytorch:2.3.0-cuda12.1-cudnn8-runtime" style="width:100%;padding:9px;margin-top:4px" class="mono"/>
        <label class="mini" style="display:block;margin-top:12px">Command (each node runs it under torchrun)</label>
        <input id="cl_cmd" value="torchrun train.py --epochs 3" style="width:100%;padding:9px;margin-top:4px" class="mono"/>
        <details style="margin-top:12px"><summary class="mini" style="cursor:pointer">Advanced — GPU class / region</summary>
          <input id="cl_gpu" placeholder="gpu_class · e.g. RTX 4090" style="width:100%;padding:9px;margin-top:8px" class="mono"/>
          <input id="cl_region" placeholder="region · e.g. us-east" style="width:100%;padding:9px;margin-top:8px" class="mono"/>
        </details>
        <div id="cl_est" class="mut" style="font-size:13px;margin-top:14px">Estimated cost shown once machines are available.</div>
        <button class="btn btn-amber" id="cl_go" data-act="clusterLaunch" style="width:100%;margin-top:12px">Form the cluster →</button>
        <p class="mini" style="margin-top:10px">You prepay all N GPUs into escrow up-front. If the full cluster can't be reserved, you're charged nothing.</p>
      </div>
    </div>
    <div style="flex:1 1 340px;min-width:300px">
      <div class="card" id="cl_result" style="display:none"><div class="lbl">Your cluster</div><div id="cl_result_body" style="margin-top:8px"></div></div>
      <div class="card" id="cl_error" style="display:none;border-color:rgba(255,120,120,.3)"><div class="lbl" style="color:var(--warn)">Heads up</div><div id="cl_error_body" class="mut" style="font-size:13px;margin-top:6px"></div></div>
      <div class="card" style="margin-top:16px">
        <div class="lbl">Already on Slurm / MPI / Ray?</div>
        <p class="mut" style="font-size:13px;margin:6px 0 8px">Don't change your stack — Petabyte is another provider. Every rank registers its VPN address, then the cluster exports as the artifacts your launcher already reads:</p>
        <p class="mono" style="font-size:12px;line-height:1.9">
        GET /jobs/{id}/hostfile <span class="mut">MPI / torchrun</span><br>
        GET /jobs/{id}/cluster <span class="mut">nodes + launch cmds</span></p>
        <p class="mini" style="margin-top:6px">Full recipes on the <a class="teal" href="/devs">Developer API</a>.</p>
      </div>
    </div>
  </div>
</div>
<script>
var AVAIL={available_nodes:0,max_cluster:0,est_price_per_hour:null};
function clEl(id){return document.getElementById(id);}
function clusterSelftest(){
 // The self-test runs the built-in all-reduce, not a container — grey out image/command so it's
 // clear they're ignored for this run (the server needs neither).
 var on=!!(clEl('cl_selftest')&&clEl('cl_selftest').checked);
 ['cl_image','cl_cmd'].forEach(function(id){var el=clEl(id);if(el){el.disabled=on;el.style.opacity=on?'.45':'';}});
}
async function clusterAvail(){
 if(typeof authed==='function'&&!authed()){var so=clEl('cl_signedout');if(so)so.style.display='';}
 try{var r=await fetch('/distributed/availability');if(r.ok)AVAIL=await r.json();}catch(e){}
 var a=clEl('cl_avail');
 if(a){a.textContent=AVAIL.available_nodes+' machines available now — you can form a cluster of up to '+AVAIL.max_cluster+' GPUs (cap '+AVAIL.max_nodes_cap+').';}
 var n=clEl('cl_n');
 if(n){n.max=Math.max(2,AVAIL.max_cluster||2);if(Number(n.value)>Number(n.max))n.value=n.max;}
 clusterEst();
}
function clusterEst(){
 var e=clEl('cl_est');if(!e)return;
 var n=Number((clEl('cl_n')||{}).value||0),h=Number((clEl('cl_hours')||{}).value||0),p=AVAIL.est_price_per_hour;
 if(p&&n>=2&&h>=1){e.innerHTML='&#8776; $'+(n*p*h).toFixed(2)+' &nbsp;<span class="mut">('+n+' GPUs &times; $'+Number(p).toFixed(2)+'/hr &times; '+h+'h, escrowed up-front)</span>';}
 else{e.textContent='Estimated cost shown once machines are available.';}
}
async function clusterLaunch(){
 if(typeof authed==='function'&&!authed()){location.href='/login';return;}
 var go=clEl('cl_go');go.disabled=true;clEl('cl_error').style.display='none';
 var body={image:clEl('cl_image').value.trim(),command:clEl('cl_cmd').value.trim(),
  world_size:Number(clEl('cl_n').value),hours:Number(clEl('cl_hours').value),backend:clEl('cl_backend').value,
  vpn:!!(clEl('cl_vpn')&&clEl('cl_vpn').checked)};
 if(clEl('cl_selftest')&&clEl('cl_selftest').checked)body.selftest=true;  // built-in all-reduce, no container
 var gc=(clEl('cl_gpu')||{}).value;if(gc)body.gpu_class=gc.trim();
 var rg=(clEl('cl_region')||{}).value;if(rg)body.region=rg.trim();
 var r=await api('/distributed',{method:'POST',body:JSON.stringify(body)});
 go.disabled=false;
 if(!r.ok){
  var m=(r.body&&r.body.error&&r.body.error.message)||(r.body&&typeof r.body.detail==='string'&&r.body.detail)||'Could not form the cluster.';
  clEl('cl_error').style.display='';clEl('cl_error_body').textContent=m;return;
 }
 await clusterShow(r.body);
}
async function clusterShow(j){
 var host=location.origin;
 var cl=await api('/jobs/'+j.job_id+'/cluster');var L=(cl.ok&&cl.body&&cl.body.launch)||{};
 window._PBCMDS['cl_hostfile']='curl -H "Authorization: Bearer $PB_TOKEN" '+host+'/jobs/'+j.job_id+'/hostfile > hostfile';
 window._PBCMDS['cl_mpirun']=L.mpirun||'';
 window._PBCMDS['cl_torchrun']=L.torchrun||'';
 window._PBCMDS['cl_ray']=L.ray_worker||'';
 var rows=(j.ranks||[]).map(function(rk){return '<div style="display:flex;justify-content:space-between;padding:3px 0;font-size:12.5px" class="mono"><span>rank '+rk.rank+(rk.is_master?' (master)':'')+'</span><span class="mut">node '+rk.spec_id+'</span></div>';}).join('');
 function line(lbl,name){return '<div style="display:flex;gap:8px;align-items:center;margin-top:8px"><code class="mono" style="flex:1;font-size:11.5px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">'+esc(window._PBCMDS[name]||'—')+'</code><button class="copybtn" data-act="pbCopy" data-a1="'+name+'">copy</button></div>';}
 clEl('cl_result_body').innerHTML=
  '<div style="font-family:var(--disp);font-size:16px;margin-bottom:6px">Cluster forming: '+j.world_size+' GPUs across '+j.world_size+' machines</div>'+
  '<p class="mut" style="font-size:12.5px;margin-bottom:8px">Escrowed &#8776; $'+Number(j.estimated_cost).toFixed(2)+' for '+j.hours+'h &middot; backend '+esc(j.backend)+' &middot; wired over the VPN.</p>'+
  rows+
  '<div class="lbl" style="margin-top:14px">Drive it from your own scheduler</div>'+
  '<div class="mini" style="margin-top:4px">MPI hostfile</div>'+line('hostfile','cl_hostfile')+
  '<div class="mini" style="margin-top:10px">torchrun</div>'+line('torchrun','cl_torchrun')+
  '<div class="mini" style="margin-top:10px">Ray worker</div>'+line('ray','cl_ray')+
  (j.vpn?('<div class="lbl" style="margin-top:14px">Private network (VPN)</div>'+
    '<p class="mini" style="margin-top:4px">A private WireGuard tunnel into your cluster.</p>'+
    '<button class="btn btn-teal" style="margin-top:8px" data-act="clVpnDownload" data-a1="'+j.job_id+'">Download VPN config</button>'):'')+
  '<p class="mini" style="margin-top:12px"><a class="teal" data-act="clOpenManifest" data-a1="'+j.job_id+'" style="cursor:pointer">Live cluster status &rarr;</a> &middot; commands fill in as nodes register their VPN address.</p>';
 clEl('cl_result').style.display='';
}
function clOpenManifest(id){location.href='/jobs/manifest/'+id;}
async function clVpnDownload(id){
 try{var r=await fetch('/jobs/'+id+'/vpn_config',{credentials:'same-origin'});
  if(!r.ok){alert('VPN config not available for this cluster.');return;}
  var text=await r.text();var b=new Blob([text],{type:'text/plain'});
  var a=document.createElement('a');a.href=URL.createObjectURL(b);a.download='petabyte-cluster-'+id+'.conf';
  document.body.appendChild(a);a.click();a.remove();
 }catch(e){alert('Could not download the VPN config.');}
}
document.addEventListener('DOMContentLoaded',clusterAvail);
</script>""")

CONSOLE_HTML = _page("Petabyte — console",
    desc="Your Petabyte control plane: running compute, jobs, wallet and spend, available GPUs, clusters, API keys, teams and hosting — one operational view.",
    path="/console", body="""
<style>
/* ---------- Console control-plane shell (marketing chrome hidden here) ---------- */
body > nav{display:none!important}
footer{display:none!important}
:root{--editor-bg:#0B1122;--editor-ink:#F2F6FF;--console-ink:#BFE9E2}
html[data-theme=light]{--editor-bg:#F5F9FC;--editor-ink:#0E1A2E;--console-ink:#0E5C55}
.cshell{display:grid;grid-template-columns:238px minmax(0,1fr);min-height:100vh}
.csidebar{position:sticky;top:0;align-self:start;height:100vh;overflow-y:auto;border-inline-end:1px solid var(--line);background:var(--depth);display:flex;flex-direction:column;padding:14px 12px}
.cbrand{display:flex;align-items:center;gap:9px;padding:4px 8px 12px;font-family:var(--disp);font-weight:700;font-size:16px;letter-spacing:-.01em;cursor:pointer}
.cbrand img{width:22px;height:22px}
.cnav{display:flex;flex-direction:column;gap:1px;flex:1}
.cnav-grp{font-size:10.5px;letter-spacing:.06em;text-transform:uppercase;color:var(--dim);margin:15px 8px 5px;font-weight:600}
.cnav a{display:flex;align-items:center;gap:10px;padding:8px 10px;border-radius:8px;color:var(--mut);font-size:13.5px;font-weight:500;cursor:pointer;transition:background-color .12s,color .12s}
.cnav a:hover{background:rgba(255,255,255,.045);color:var(--ink)}
.cnav a.on{background:rgba(53,224,208,.10);color:var(--teal)}
.cnav a svg{width:16px;height:16px;flex:none;opacity:.85}
.csidefoot{border-top:1px solid var(--line);padding-top:8px;margin-top:8px;display:flex;flex-direction:column;gap:1px}
.csidefoot a{display:flex;align-items:center;gap:10px;padding:8px 10px;border-radius:8px;color:var(--mut);font-size:13.5px;font-weight:500;cursor:pointer;text-decoration:none}
.csidefoot a:hover{background:rgba(255,255,255,.045);color:var(--ink)}
.csidefoot a svg{width:16px;height:16px;flex:none;opacity:.85}
.cmain{display:flex;flex-direction:column;min-width:0}
.ctopbar{position:sticky;top:0;z-index:30;display:flex;align-items:center;gap:12px;padding:9px 20px;border-bottom:1px solid var(--line);background:rgba(3,7,17,.82);backdrop-filter:blur(10px);-webkit-backdrop-filter:blur(10px)}
html[data-theme=light] .ctopbar{background:rgba(255,255,255,.82)}
.cham{display:none;background:transparent;border:1px solid var(--line2);border-radius:9px;color:var(--mut);padding:7px 10px;cursor:pointer}
.cham svg{width:16px;height:16px;display:block}
.cws{display:flex;align-items:center;gap:9px;min-width:0}
.cws .av{width:26px;height:26px;border-radius:7px;background:linear-gradient(135deg,var(--teal),var(--deep));display:flex;align-items:center;justify-content:center;font-family:var(--disp);font-weight:700;font-size:13px;color:#04201e;flex:none}
.cws b{font-family:var(--disp);font-size:14px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:160px}
.cenv{font-size:10px;font-family:var(--mono);letter-spacing:.06em;padding:3px 7px;border-radius:6px;border:1px solid var(--line2);color:var(--mut);white-space:nowrap}
.cenv.test{color:var(--amber);border-color:rgba(255,178,36,.4);background:rgba(255,178,36,.08)}
.cenv.live{color:var(--pos);border-color:rgba(74,222,156,.4);background:rgba(74,222,156,.08)}
.csearch{margin-inline-start:auto;display:flex;align-items:center;gap:9px;min-width:190px;max-width:300px;background:var(--depth2);border:1px solid var(--line2);border-radius:9px;color:var(--dim);font-size:13px;padding:8px 11px;cursor:text}
.csearch svg{width:15px;height:15px;flex:none}
.csearch span{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.csearch kbd{margin-inline-start:auto;font-family:var(--mono);font-size:10.5px;border:1px solid var(--line2);border-radius:5px;padding:1px 6px;color:var(--mut)}
.citop{display:inline-flex;align-items:center;justify-content:center;width:34px;height:34px;border-radius:9px;border:1px solid var(--line2);background:transparent;color:var(--mut);cursor:pointer;flex:none}
.citop:hover{color:var(--teal);border-color:var(--teal)}
.citop svg{width:16px;height:16px;flex:none}
.cbody{padding:22px 24px 44px;min-width:0;width:100%;max-width:1200px}
.cpagehead{display:flex;align-items:flex-start;justify-content:space-between;gap:16px;flex-wrap:wrap;margin-bottom:20px}
.cpagehead h1{font-family:var(--disp);font-weight:700;font-size:22px;letter-spacing:-.01em;margin:0}
.cpagehead p{color:var(--mut);font-size:13.5px;margin-top:3px;max-width:60ch}
.cpageact{display:flex;gap:8px;flex-wrap:wrap}
.cmetrics{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;margin-bottom:22px}
.cmetric{border:1px solid var(--line);border-radius:12px;padding:14px 15px;background:var(--depth);min-width:0}
.cmetric .k{font-size:12px;color:var(--mut)}
.cmetric .v{font-family:var(--disp);font-weight:700;font-size:23px;letter-spacing:-.02em;margin-top:5px;line-height:1.12}
.cmetric .c{font-size:11.5px;color:var(--dim);margin-top:3px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.cmetric .c.pos{color:var(--pos)}.cmetric .c.warn{color:var(--warn)}
.cgrid{display:grid;grid-template-columns:1.5fr 1fr;gap:16px;align-items:start}
.cgcol{display:flex;flex-direction:column;gap:16px;min-width:0}
.csec{border:1px solid var(--line);border-radius:12px;background:var(--depth);overflow:hidden}
.csec-h{display:flex;align-items:center;justify-content:space-between;gap:10px;padding:12px 15px;border-bottom:1px solid var(--line)}
.csec-h h2{font-family:var(--disp);font-size:14px;font-weight:600;margin:0}
.csec-h a,.csec-h button{font-size:12.5px;color:var(--teal);background:transparent;border:0;cursor:pointer;padding:0}
.csec-b{padding:4px 15px 10px}
.crow{display:flex;align-items:center;gap:12px;padding:10px 0;border-bottom:1px solid var(--line)}
.crow:last-child{border-bottom:0}
.crow .rt{font-family:var(--disp);font-weight:600;font-size:13.5px}
.crow .rs{font-size:12px;color:var(--mut);font-weight:400}
.crow .rr{margin-inline-start:auto;display:flex;gap:6px;align-items:center;flex:none}
.cmoney{display:flex;justify-content:space-between;gap:12px;padding:7px 0;font-size:13px;border-bottom:1px solid var(--line)}
.cmoney:last-child{border-bottom:0}
.cmoney .mk{color:var(--mut)}.cmoney .mv{font-family:var(--mono);font-variant-numeric:tabular-nums}
.cbtn{font-family:var(--disp);font-weight:600;font-size:12.5px;border-radius:8px;padding:7px 13px;border:1px solid var(--line2);background:transparent;color:var(--ink);cursor:pointer;transition:border-color .12s,color .12s,filter .12s;white-space:nowrap;display:inline-flex;align-items:center;gap:6px;text-decoration:none}
.cbtn:hover{border-color:var(--teal);color:var(--teal)}
.cbtn.pri{background:linear-gradient(180deg,var(--amber-br),var(--amber));color:#241802;border:0}
.cbtn.pri:hover{filter:brightness(1.05);color:#241802}
.cbtn.sm{padding:5px 10px;font-size:11.5px;border-radius:7px}
.cempty{text-align:center;padding:18px 8px}
.cempty .et{font-family:var(--disp);font-weight:600;font-size:13.5px}
.cempty .es{color:var(--mut);font-size:12.5px;margin:4px 0 12px}
/* keep the run editor + console output + tables from the original console */
.ctab-btn{display:none}
#c_code{width:100%;min-height:150px;background:var(--editor-bg);color:var(--editor-ink);border:1px solid var(--line2);border-radius:12px;padding:13px;font-family:var(--mono);font-size:12.5px;line-height:1.6;resize:vertical}
.c_console{background:var(--editor-bg);color:var(--console-ink);border:1px solid var(--line);border-radius:12px;padding:14px;min-height:150px;font-family:var(--mono);font-size:12.5px;line-height:1.6;white-space:pre-wrap;overflow:auto}
.c_console .sys{color:var(--mut)}.c_console .ok{color:var(--pos)}.c_console .amber{color:var(--amber)}
html[dir="rtl"] #c_code,html[dir="rtl"] .c_console{direction:ltr;text-align:left}
.crun{display:grid;grid-template-columns:1.1fr .9fr;gap:16px}
.cscrim{display:none;position:fixed;inset:0;background:rgba(3,7,17,.55);z-index:55}
.cscrim.on{display:block}
@media(max-width:900px){
 .cshell{grid-template-columns:minmax(0,1fr)}
 .csidebar{position:fixed;inset:0 auto 0 0;width:250px;z-index:60;transform:translateX(-100%);transition:transform .2s ease}
 .csidebar.open{transform:none;box-shadow:0 0 60px rgba(0,0,0,.6)}
 .cham{display:inline-flex}
 .cmetrics{grid-template-columns:repeat(2,minmax(0,1fr))}
 .cgrid{grid-template-columns:minmax(0,1fr)}
 .crun{grid-template-columns:1fr}
 .csearch{min-width:0}
}
@media(max-width:520px){.cmetrics{grid-template-columns:1fr 1fr}.csearch span,.csearch kbd{display:none}.csearch{min-width:0;max-width:44px;justify-content:center;padding:8px}.cws b{display:none}.cbody{padding:18px 16px 40px}}
@media(prefers-reduced-motion:reduce){.csidebar{transition:none}}
</style>
<div class="cscrim" id="cscrim"></div>
<div class="cshell" id="cshell">
  <aside class="csidebar" id="csidebar">
    <div class="cbrand" data-act="cGo" data-a1="overview"><img src="/static/petabyte-logo.png" alt=""/> Petabyte</div>
    <nav class="cnav" aria-label="Console">
      <div class="cnav-grp">Compute</div>
      <a id="cnav-overview" data-act="cGo" data-a1="overview"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/></svg> Overview</a>
      <a id="cnav-compute" data-act="cGo" data-a1="compute"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><rect x="4" y="4" width="16" height="16" rx="2"/><path d="M9 9h6v6H9z"/></svg> Compute</a>
      <a id="cnav-jobs" data-act="cGo" data-a1="jobs"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M4 6h16M4 12h16M4 18h10"/></svg> Jobs</a>
      <a href="/catalog"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M4 5h16v6H4zM4 15h10v4H4z"/></svg> Templates</a>
      <a id="cnav-clusters" data-act="cGo" data-a1="clusters"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><circle cx="6" cy="6" r="2"/><circle cx="18" cy="6" r="2"/><circle cx="12" cy="18" r="2"/><path d="M7.5 7.5 11 16M16.5 7.5 13 16"/></svg> Clusters</a>
      <a id="cnav-storage" data-act="cGo" data-a1="storage"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><ellipse cx="12" cy="5" rx="8" ry="3"/><path d="M4 5v6c0 1.7 3.6 3 8 3s8-1.3 8-3V5M4 11v6c0 1.7 3.6 3 8 3s8-1.3 8-3v-6"/></svg> Storage</a>
      <div class="cnav-grp">Account</div>
      <a id="cnav-billing" data-act="cGo" data-a1="billing"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><rect x="3" y="6" width="18" height="12" rx="2"/><path d="M3 10h18"/></svg> Wallet &amp; billing</a>
      <a id="cnav-access" data-act="cGo" data-a1="access"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><circle cx="8" cy="12" r="3.5"/><path d="M11 12h9M17 12v4"/></svg> API keys</a>
      <a id="cnav-teams" data-act="cGo" data-a1="teams"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><circle cx="9" cy="9" r="3"/><path d="M3 20a6 6 0 0 1 12 0M16 6.5a3 3 0 0 1 0 5.5M21 20a5 5 0 0 0-4-4.9"/></svg> Teams</a>
      <div class="cnav-grp" id="cnav-hostgrp" style="display:none">Hosting</div>
      <a id="cnav-seller" data-act="cGo" data-a1="seller" style="display:none"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><rect x="3" y="4" width="18" height="12" rx="2"/><path d="M8 20h8M12 16v4"/></svg> Nodes &amp; earnings</a>
    </nav>
    <div class="csidefoot">
      <a href="/account"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3M5 5l2 2M17 17l2 2M19 5l-2 2M7 17l-2 2"/></svg> Settings</a>
      <a href="/developers"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M9 8 5 12l4 4M15 8l4 4-4 4"/></svg> Docs</a>
    </div>
  </aside>
  <div class="cmain">
    <header class="ctopbar">
      <button class="cham" id="cham" aria-label="Menu"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M4 7h16M4 12h16M4 17h16"/></svg></button>
      <div class="cws"><span class="av" id="c_wsav">·</span><b id="c_wsname">Workspace</b><span class="cenv" id="c_env">…</span></div>
      <div class="csearch" data-act="cPalette" role="button" tabindex="0" aria-label="Search and commands"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><circle cx="11" cy="11" r="7"/><path d="m21 21-4-4"/></svg><span>Search or run a command</span><kbd>⌘K</kbd></div>
      <button class="citop" data-act="cGo" data-a1="access" title="Notifications" aria-label="Notifications"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M6 9a6 6 0 0 1 12 0c0 5 2 6 2 6H4s2-1 2-6M10 20a2 2 0 0 0 4 0"/></svg></button>
      <button class="citop" onclick="try{toggleTheme()}catch(e){}" title="Theme" aria-label="Toggle theme"><svg class="sun" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M2 12h2M20 12h2M5 5l1.4 1.4M17.6 17.6 19 19M19 5l-1.4 1.4M6.4 17.6 5 19"/></svg></button>
      <button class="citop" onclick="try{signout()}catch(e){location.href='/login'}" title="Sign out" aria-label="Sign out"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M15 4h3a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2h-3M10 17l-5-5 5-5M5 12h11"/></svg></button>
    </header>
    <div class="cbody">
      <p class="mut" id="c_signedout" style="display:none">Please <a class="teal" href="/login">sign in</a> to open your console.</p>
      <div id="c_main" style="display:none">
        <div class="cpagehead" id="c_pagehead"></div>

        <section id="tab-overview" class="cpanel">
          <div class="cmetrics" id="c_ov_metrics"></div>
          <div class="cgrid">
            <div class="cgcol">
              <section class="csec"><div class="csec-h"><h2>Running compute</h2><button data-act="cGo" data-a1="compute">Manage</button></div><div class="csec-b" id="c_ov_running"><p class="mut" style="font-size:13px;padding:8px 0">Loading…</p></div></section>
              <section class="csec"><div class="csec-h"><h2>Recent jobs</h2><button data-act="cGo" data-a1="jobs">View all</button></div><div class="csec-b" id="c_ov_jobs"><p class="mut" style="font-size:13px;padding:8px 0">Loading…</p></div></section>
              <section class="csec"><div class="csec-h"><h2>Available compute</h2><a href="/marketplace">Marketplace →</a></div><div class="csec-b" id="c_ov_avail"><p class="mut" style="font-size:13px;padding:8px 0">Loading…</p></div></section>
            </div>
            <div class="cgcol">
              <section class="csec"><div class="csec-h"><h2>Wallet &amp; spend</h2><button data-act="cGo" data-a1="billing">Billing</button></div><div class="csec-b" id="c_ov_wallet"><p class="mut" style="font-size:13px;padding:8px 0">Loading…</p></div></section>
              <section class="csec" id="c_ov_seller_sect" style="display:none"><div class="csec-h"><h2>Hosting</h2><a href="/seller/payouts">Earnings →</a></div><div class="csec-b" id="c_ov_seller"></div></section>
              <section class="csec"><div class="csec-h"><h2>Recent activity</h2></div><div class="csec-b" id="c_ov_activity"><p class="mut" style="font-size:13px;padding:8px 0">Loading…</p></div></section>
            </div>
          </div>
        </section>

        <section id="tab-compute" class="cpanel" style="display:none">
          <div class="csec"><div class="csec-h"><h2>Run a job</h2></div><div class="csec-b">
            <div class="crun">
              <div>
                <textarea id="c_code" spellcheck="false">print("hello from a petabyte gpu")
print(6 * 7)</textarea>
                <div style="margin-top:10px"><button class="cbtn pri" data-act="cRun">Run on cheapest GPU →</button></div>
                <p class="mini" style="margin-top:8px">Books the cheapest matching GPU, escrows the hour, streams the result. Add funds in Billing first.</p>
              </div>
              <div class="c_console" id="c_out"><span class="sys">console idle — press Run.</span></div>
            </div>
          </div></div>
          <section class="csec" style="margin-top:16px"><div class="csec-h"><h2>Available GPUs</h2><a href="/marketplace">Marketplace →</a></div>
            <div class="panel" style="overflow:auto"><table class="tbl"><thead><tr><th>GPU</th><th>$/hr</th><th>vs cloud</th><th>Trust</th><th>Region</th><th></th></tr></thead><tbody id="c_specs"><tr><td colspan=6 class="mut mono" style="text-align:center;padding:16px">Loading…</td></tr></tbody></table></div>
          </section>
          <section class="csec" style="margin-top:16px"><div class="csec-h"><h2>Your VMs</h2><span class="mut" style="font-size:12px">stable address survives failover</span></div>
            <div class="panel" style="overflow:auto"><table class="tbl"><thead><tr><th>Template</th><th>Status</th><th>Address</th><th>Failover</th><th>Left</th><th></th></tr></thead><tbody id="c_vms"><tr><td colspan=6 class="mut mono" style="text-align:center;padding:16px">Loading…</td></tr></tbody></table></div>
          </section>
        </section>

        <section id="tab-jobs" class="cpanel" style="display:none">
          <section class="csec"><div class="csec-h"><h2>Reservations</h2><button data-act="cGo" data-a1="compute">Run a job</button></div>
            <div class="panel" style="overflow:auto"><table class="tbl"><thead><tr><th>When</th><th>GPU</th><th>Hours</th><th>Amount</th><th>Status</th></tr></thead><tbody id="c_jobs"><tr><td colspan=5 class="mut mono" style="text-align:center;padding:16px">Loading…</td></tr></tbody></table></div>
          </section>
        </section>

        <section id="tab-clusters" class="cpanel" style="display:none">
          <section class="csec"><div class="csec-h"><h2>Distributed clusters</h2><a href="/cluster">Form a cluster →</a></div>
            <div class="panel" style="overflow:auto"><table class="tbl"><thead><tr><th>Job</th><th>Status</th><th>Size</th><th>Rendezvous</th></tr></thead><tbody id="c_clusters"><tr><td colspan=4 class="mut mono" style="text-align:center;padding:16px">Loading…</td></tr></tbody></table></div>
            <p class="mini" style="margin:10px 15px 14px">torchrun / MPI / Ray across many machines, wired over a private VPN.</p>
          </section>
        </section>

        <section id="tab-storage" class="cpanel" style="display:none">
          <p class="mut" style="font-size:13.5px;max-width:74ch">Persistent volumes outlive any single VM — keep datasets, checkpoints and model weights between runs. Snapshots are <b class="teal">incremental</b>: only the content that actually changed is uploaded, identical files are stored once, and a restore ships just the delta. You pay for unique bytes, not for a full-disk mirror.</p>
          <div class="cmetrics" id="c_stor_metrics" style="margin-top:14px"></div>
          <section class="csec" style="margin-top:14px;max-width:520px"><div class="csec-h"><h2>Create a volume</h2></div><div class="csec-b">
            <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-top:6px"><input id="c_volname" placeholder="volume name (e.g. checkpoints)" style="flex:1;min-width:160px"/><input id="c_volsize" type="number" min="1" placeholder="size cap GB (optional)" style="width:170px" title="optional hard cap on unique bytes held"/><button class="cbtn pri" data-act="cVolCreate">Create</button></div>
            <p class="mini" id="c_volmsg" style="margin-top:8px;text-transform:none;letter-spacing:0"></p>
          </div></section>
          <div class="panel" style="overflow:auto;margin-top:14px"><table class="tbl"><thead><tr><th>Volume</th><th>Stored (deduped)</th><th>Snapshots</th><th>Saved by dedup</th><th>Created</th><th></th></tr></thead><tbody id="c_volumes"><tr><td colspan=6 class="mut mono" style="text-align:center;padding:16px">Loading…</td></tr></tbody></table></div>
          <div id="c_vol_detail" style="display:none;margin-top:16px"></div>
          <p class="mini" style="margin:12px 2px;text-transform:none;letter-spacing:0">Snapshots are taken from a VM with the agent or CLI — <code>petabyte volume snapshot &lt;name&gt;</code> uploads only the delta. See the <a class="teal" href="/developers">developer docs</a>.</p>
        </section>

        <section id="tab-billing" class="cpanel" style="display:none">
          <div class="cmetrics" id="c_bill_wallet" style="margin-bottom:16px"></div>
          <div style="display:flex;gap:16px;flex-wrap:wrap">
            <section class="csec" style="flex:1 1 300px"><div class="csec-h"><h2>Add funds</h2></div><div class="csec-b">
              <div style="display:flex;gap:8px;align-items:center;margin-top:6px"><input id="c_dep" type="number" value="50" min="1" style="width:120px"/><button class="cbtn pri" data-act="cDeposit">Add funds</button></div>
              <p class="mini" style="margin-top:8px">In live mode, funds are added by card at checkout.</p>
            </div></section>
            <section class="csec" style="flex:1 1 300px"><div class="csec-h"><h2>Withdraw earnings</h2></div><div class="csec-b">
              <div style="display:flex;gap:8px;align-items:center;margin-top:6px;flex-wrap:wrap"><select id="c_wmethod" style="flex:1;min-width:150px"></select><input id="c_wamt" type="number" placeholder="amount" min="1" style="width:110px"/><button class="cbtn" data-act="cWithdraw">Withdraw</button></div>
              <p class="mini" id="c_wnomethod" style="margin-top:8px;display:none">No payout method yet — add bank / USDC / gift card on the <a class="teal" href="/seller/payouts">earnings page</a>.</p>
            </div></section>
          </div>
          <section class="csec" style="margin-top:16px"><div class="csec-h"><h2>Payout history</h2></div>
            <div class="panel" style="overflow:auto"><table class="tbl"><thead><tr><th>Amount</th><th>Kind</th><th>Status</th><th>When</th></tr></thead><tbody id="c_payouts"></tbody></table></div>
          </section>
          <section class="csec" style="margin-top:16px"><div class="csec-h"><h2>Receipts</h2></div>
            <div class="panel" style="overflow:auto"><table class="tbl"><thead><tr><th>When</th><th>GPU</th><th>Hours</th><th>Amount</th><th>Status</th></tr></thead><tbody id="c_bookings"></tbody></table></div>
          </section>
          <section class="csec" style="margin-top:16px"><div class="csec-h"><h2>Refer &amp; earn</h2></div><div class="csec-b" id="c_referral" style="padding-top:10px"></div></section>
        </section>

        <section id="tab-teams" class="cpanel" style="display:none">
          <p class="mut" style="font-size:13.5px;max-width:70ch">Share a wallet across a lab or company and set a hard budget cap so a runaway job can never overspend. Add people, give each a role, remove them when they leave.</p>
          <p class="mini" style="margin-top:8px;text-transform:none;letter-spacing:0;font-size:12px">Roles — <b class="teal">admin</b>: manage members, funds &amp; budget, and run compute · <b class="teal">billing</b>: add funds &amp; set the budget, and run compute · <b class="teal">member</b>: run compute against the team wallet.</p>
          <div class="panel" style="overflow:auto;margin-top:12px"><table class="tbl"><thead><tr><th>Team</th><th>Your role</th><th>Balance</th><th>Budget cap</th><th>Spent</th><th>Members</th><th></th></tr></thead><tbody id="c_orgs"><tr><td colspan=7 class="mut mono" style="text-align:center;padding:16px">Loading…</td></tr></tbody></table></div>
          <div id="c_team_detail" style="display:none;margin-top:16px"></div>
          <section class="csec" style="margin-top:16px;max-width:460px"><div class="csec-h"><h2>Create a team</h2></div><div class="csec-b">
            <div style="display:flex;gap:8px;align-items:center;margin-top:6px"><input id="c_orgname" placeholder="team / lab name" style="flex:1"/><button class="cbtn pri" data-act="cOrgCreate">Create</button></div>
            <p class="mini" id="c_orgmsg" style="margin-top:8px"></p>
          </div></section>
        </section>

        <section id="tab-access" class="cpanel" style="display:none">
          <section class="csec" style="margin-top:12px"><div class="csec-h"><h2>Two-factor authentication</h2></div>
            <div class="csec-b" style="padding-top:10px">
              <p class="mut" style="font-size:13.5px;max-width:66ch">Protect sign-in with a one-time code from an authenticator app (Google Authenticator, Authy, 1Password). After a password, a 6-digit code is required to log in.</p>
              <div class="card" id="c_2fa" style="margin-top:12px"><span class="mut">Loading…</span></div>
            </div>
          </section>
          <p class="mut" style="font-size:13.5px;max-width:66ch">Programmatic access for CI, scripts and your own tools. Scope a key, set an expiry, revoke any time. The full key is shown once at creation.</p>
          <section class="csec" style="margin-top:12px"><div class="csec-b" style="padding-top:14px">
            <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap"><input id="c_keylabel" placeholder="label (e.g. ci-runner)" style="flex:1;min-width:150px"/><input id="c_keydays" type="number" value="30" min="1" max="90" style="width:90px" title="days until expiry"/><input id="c_keyscopes" placeholder="scopes (comma-sep, optional)" style="flex:1;min-width:150px"/><button class="cbtn pri" data-act="cKeyCreate">Create key</button></div>
            <div id="c_keyout" style="display:none;margin-top:12px"></div>
          </div></section>
          <div class="panel" style="overflow:auto;margin-top:12px"><table class="tbl"><thead><tr><th>Label</th><th>Scopes</th><th>Expires</th><th>Status</th><th></th></tr></thead><tbody id="c_keys"><tr><td colspan=5 class="mut mono" style="text-align:center;padding:16px">Loading…</td></tr></tbody></table></div>
          <p class="mini" style="margin:8px 2px">Full API reference at <a class="teal" href="/developers">/developers</a> and <a class="teal" href="/docs">/docs</a>.</p>
          <section class="csec" style="margin-top:20px"><div class="csec-h"><h2>Notifications</h2></div>
            <div class="panel" style="overflow:auto"><table class="tbl"><thead><tr><th>When</th><th>Event</th><th>Subject</th><th>Status</th></tr></thead><tbody id="c_notifs"></tbody></table></div>
          </section>
          <section class="csec" style="margin-top:20px"><div class="csec-h"><h2>Audit log <span class="mut" id="c_audit_integrity" style="font-weight:400;text-transform:none;letter-spacing:0"></span></h2></div>
            <div class="csec-b" style="padding-top:10px"><p class="mut" style="font-size:13px;max-width:66ch">Immutable "who did what, when" — logins, key create/revoke, role and team changes, spend. Hash-chained so any edit or deletion is detectable (the security-team / SOC-2 trail).</p></div>
            <div class="panel" style="overflow:auto"><table class="tbl"><thead><tr><th>When</th><th>Action</th><th>Target</th><th>Detail</th><th>IP</th></tr></thead><tbody id="c_audit"><tr><td colspan=5 class="mut mono" style="text-align:center;padding:14px">Loading…</td></tr></tbody></table></div>
          </section>
        </section>

        <section id="tab-seller" class="cpanel" style="display:none">
          <div id="c_seller" style="margin-top:2px"></div>
        </section>
      </div>
    </div>
  </div>
</div>
<script>
var CTABS=['overview','compute','jobs','clusters','storage','billing','teams','access','seller'];
var CLOADED={};
function cD2(x){return '$'+Number(x||0).toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2});}
function cInt(x){return Number(x||0).toLocaleString();}
function cBadge(s){var t=String(s==null?'':s);var ok=(t==='running'||t==='complete'||t==='completed'||t==='online'||t==='paid'||t==='ready'||t==='active'||t==='sent')?' ok':'';return '<span class="badge'+ok+'">'+esc(t)+'</span>';}
function cStat(n,l,cls){return '<div class="stat"><div class="n '+(cls||'')+'">'+n+'</div><div class="l">'+esc(l)+'</div></div>';}
function cTs(s){return esc(String(s==null?'':s).replace('T',' ').slice(0,16));}
function cMetric(k,v,c,cls){return '<div class="cmetric"><div class="k">'+esc(k)+'</div><div class="v">'+v+'</div><div class="c '+(cls||'')+'">'+c+'</div></div>';}
function cEmpty(t,s,arg,cta,href){var btn=href?('<a class="cbtn sm" href="'+href+'">'+cta+'</a>'):('<button class="cbtn sm" data-act="cGo" data-a1="'+arg+'">'+cta+'</button>');
  return '<div class="cempty"><div class="et">'+esc(t)+'</div><div class="es">'+esc(s)+'</div>'+btn+'</div>';}
function cGo(name){cNav(name);}
function cPalette(){try{pbPalette();}catch(e){}}

var PAGEMETA={
 overview:{t:'Overview',s:'Your compute, jobs, spend and infrastructure at a glance.',a:[['Launch compute','pri','compute'],['Add funds','','billing']]},
 compute:{t:'Compute',s:'Run a job on the cheapest matching GPU, or manage running VMs.',a:[['Marketplace','href','/marketplace']]},
 jobs:{t:'Jobs',s:'Your reservations and their status.',a:[['Run a job','pri','compute']]},
 clusters:{t:'Clusters',s:'Multi-GPU distributed jobs across many machines.',a:[['Form a cluster','href','/cluster']]},
 storage:{t:'Storage',s:'Persistent volumes with incremental, deduplicated snapshots.',a:[]},
 billing:{t:'Wallet & billing',s:'Balance, funding, payouts, receipts and referrals.',a:[]},
 access:{t:'API keys',s:'Programmatic access for CI, scripts and tools.',a:[]},
 teams:{t:'Teams',s:'Share a wallet and set budget caps.',a:[]},
 seller:{t:'Hosting',s:'Your nodes, utilization and earnings.',a:[['List your PC','href','/install']]}
};
function cHead(name){
  var m=PAGEMETA[name]||PAGEMETA.overview;
  var acts=(m.a||[]).map(function(x){var label=x[0],kind=x[1],arg=x[2];
    if(kind==='href')return '<a class="cbtn" href="'+arg+'">'+esc(label)+'</a>';
    return '<button class="cbtn'+(kind==='pri'?' pri':'')+'" data-act="cGo" data-a1="'+arg+'">'+esc(label)+'</button>';}).join('');
  var el=document.getElementById('c_pagehead');if(el)el.innerHTML='<div><h1>'+esc(m.t)+'</h1><p>'+esc(m.s)+'</p></div><div class="cpageact">'+acts+'</div>';
}
function cNav(name){
  if(CTABS.indexOf(name)<0)name='overview';
  CTABS.forEach(function(t){
    var el=document.getElementById('tab-'+t);if(el)el.style.display=(t===name)?'':'none';
    var a=document.getElementById('cnav-'+t);if(a)a.classList.toggle('on',t===name);
  });
  cHead(name);
  try{history.replaceState(null,'','#'+name);}catch(e){}
  if(!CLOADED[name]){CLOADED[name]=true;cLoadTab(name);}
  var sb=document.getElementById('csidebar');if(sb)sb.classList.remove('open');
  var sc=document.getElementById('cscrim');if(sc)sc.classList.remove('on');
  try{document.querySelector('.cbody').scrollTop=0;window.scrollTo(0,0);}catch(e){}
}
var cTab=cNav;
function cLoadTab(name){
  if(name==='overview')cOverview();
  else if(name==='compute')cCompute();
  else if(name==='jobs')cJobs();
  else if(name==='clusters')cClusters();
  else if(name==='storage')cStorage();
  else if(name==='billing')cBilling();
  else if(name==='teams')cTeams();
  else if(name==='access')cAccess();
  else if(name==='seller')cSeller();
}

async function consoleLoad(){
  if(typeof authed==='function' && !authed()){var so=document.getElementById('c_signedout');if(so)so.style.display='';return;}
  document.getElementById('c_main').style.display='';
  cEnvBadge();
  await cWorkspace();
  var start=(location.hash||'').replace('#','');
  cNav(CTABS.indexOf(start)>=0?start:'overview');
}
async function cEnvBadge(){
  var el=document.getElementById('c_env');if(!el)return;
  try{var c=await (await fetch('/payments/config')).json();
    if(c&&c.test_mode){el.className='cenv test';el.textContent='TEST';el.title='Sandbox — no real card is charged, no real money moves.';}
    else{el.className='cenv live';el.textContent='LIVE';el.title='Live — real payments.';}
  }catch(e){el.textContent='';}
}
async function cWorkspace(){
  var me=((await api('/me'))||{}).body||{};window._CME=me;
  var nm=document.getElementById('c_wsname');if(nm)nm.textContent=me.username||'Workspace';
  var av=document.getElementById('c_wsav');if(av)av.textContent=((me.username||'?').slice(0,1)).toUpperCase();
  var seller=(me.nodes>0)||me.role==='seller';
  ['cnav-hostgrp','cnav-seller','c_ov_seller_sect'].forEach(function(id){var e=document.getElementById(id);if(e)e.style.display=seller?'':'none';});
}
async function cWalletStrip(){
  var me=((await api('/me'))||{}).body||{};window._CME=me;
  if(CLOADED['overview'])cLoadMetrics();
}

async function cOverview(){
  cLoadMetrics();cRunning();cOvWallet();cOvJobs();cOvAvail();cOvActivity();cOvSeller();
}
async function cLoadMetrics(){
  var me=((await api('/me'))||{}).body||{};window._CME=me;
  var sp=((await api('/buyer/spend'))||{}).body||{};
  var vms=(((await api('/vms'))||{}).body||{}).vms||[];
  var run=vms.filter(function(v){return v.status==='running';}).length;
  var start=vms.filter(function(v){return v.status==='starting'||v.status==='migrating';}).length;
  var el=document.getElementById('c_ov_metrics');if(!el)return;
  el.innerHTML=
    cMetric('Wallet',cD2(me.balance),'earned '+cD2(me.earnings),'pos')+
    cMetric('Running',(run+start)+' compute',run+' running · '+start+' starting')+
    cMetric('Spend',cD2(sp.burn_rate_per_hour)+'/hr','~'+cD2(sp.projected_24h)+' next 24h','warn')+
    cMetric('Jobs',cInt(me.bookings),(sp.active_instances||0)+' active now');
}
async function cRunning(){
  var vms=(((await api('/vms'))||{}).body||{}).vms||[];
  var el=document.getElementById('c_ov_running');if(!el)return;
  var live=vms.filter(function(v){return ['running','starting','migrating'].indexOf(v.status)>=0;});
  if(!live.length){el.innerHTML=cEmpty('Nothing running','Launch a workload and it shows up here.','compute','Launch compute');return;}
  el.innerHTML=live.slice(0,5).map(function(v){var u=v.url||{};var isrun=(v.status==='running');
    return '<div class="crow"><div style="min-width:0"><div class="rt">'+esc(v.template||'vm')+' '+cBadge(v.status)+'</div>'+
      '<div class="rs mono" style="font-size:11.5px">'+esc(u.hostname||u.id||'')+(v.hours_left!=null?(' · '+v.hours_left+'h left'):'')+'</div></div>'+
      '<div class="rr">'+(isrun?('<button class="cbtn sm" data-act="cVmExtend" data-a1="'+esc(v.vm_id)+'">+1h</button><button class="cbtn sm" data-act="cVmStop" data-a1="'+esc(v.vm_id)+'">Stop</button>'):'')+'</div></div>';
  }).join('');
}
async function cOvWallet(){
  var sp=((await api('/buyer/spend'))||{}).body||{};var me=window._CME||{};
  var el=document.getElementById('c_ov_wallet');if(!el)return;
  el.innerHTML=
    '<div class="cmoney"><span class="mk">Available</span><span class="mv teal">'+cD2(me.balance)+'</span></div>'+
    '<div class="cmoney"><span class="mk">Current spend</span><span class="mv amber">'+cD2(sp.burn_rate_per_hour)+'/hr</span></div>'+
    '<div class="cmoney"><span class="mk">Projected 24h</span><span class="mv">'+cD2(sp.projected_24h)+'</span></div>'+
    '<div class="cmoney"><span class="mk">In escrow</span><span class="mv">'+cD2(sp.in_escrow)+'</span></div>'+
    '<div class="cmoney"><span class="mk">Est. runway</span><span class="mv">'+(sp.hours_of_runway!=null?sp.hours_of_runway+'h':'&#8734;')+'</span></div>'+
    '<div style="margin-top:12px;display:flex;gap:8px"><button class="cbtn pri sm" data-act="cGo" data-a1="billing">Add funds</button><button class="cbtn sm" data-act="cGo" data-a1="billing">Billing</button></div>';
}
async function cOvJobs(){
  var bk=(((await api('/account/bookings'))||{}).body||{}).bookings||[];
  var el=document.getElementById('c_ov_jobs');if(!el)return;
  if(!bk.length){el.innerHTML=cEmpty('No jobs yet','Run your first workload.','compute','Run a job');return;}
  el.innerHTML=bk.slice(0,5).map(function(b){
    return '<div class="crow"><div style="min-width:0"><div class="rt">'+esc(b.gpu_model||'GPU')+' '+cBadge(b.status)+'</div>'+
      '<div class="rs">'+cTs(b.created_at)+' · '+esc(String(b.hours))+'h</div></div>'+
      '<div class="rr mono" style="font-size:13px">'+cD2(b.gross_amount)+'</div></div>';
  }).join('');
}
async function cOvAvail(){
  var specs=(((await api('/specs'))||{}).body||{}).specs||[];
  var el=document.getElementById('c_ov_avail');if(!el)return;
  if(!specs.length){el.innerHTML='<p class="mut" style="font-size:13px;padding:8px 0">No GPUs online right now.</p>';return;}
  var top=specs.slice().sort(function(a,b){return a.price_per_hour-b.price_per_hour;}).slice(0,4);
  el.innerHTML=top.map(function(s){var save=(s.cloud_reference&&s.price_per_hour<s.cloud_reference)?Math.round((1-s.price_per_hour/s.cloud_reference)*100):0;
    return '<div class="crow"><div style="min-width:0"><div class="rt">'+esc(s.gpu_model||'CPU')+'</div><div class="rs">'+esc(s.region||'')+(save>0?(' · <span class="teal">-'+save+'% vs cloud</span>'):'')+'</div></div>'+
      '<div class="rr"><span class="mono amber" style="font-size:13px">'+cD2(s.price_per_hour)+'/hr</span><button class="cbtn sm" data-act="cGo" data-a1="compute">Launch</button></div></div>';
  }).join('');
}
async function cOvActivity(){
  var ns=(((await api('/notifications'))||{}).body||{}).notifications||[];
  var el=document.getElementById('c_ov_activity');if(!el)return;
  if(!ns.length){el.innerHTML='<p class="mut" style="font-size:13px;padding:8px 0">No recent activity.</p>';return;}
  el.innerHTML=ns.slice(0,6).map(function(n){
    return '<div class="crow" style="gap:8px"><div style="min-width:0"><div class="rt" style="font-size:13px">'+esc(n.subject||n.event_type||'')+'</div><div class="rs" style="font-size:11.5px">'+cTs(n.created_at)+'</div></div><div class="rr">'+cBadge(n.status)+'</div></div>';
  }).join('');
}
async function cOvSeller(){
  var me=window._CME||{};var sect=document.getElementById('c_ov_seller_sect');
  if(!((me.nodes>0)||me.role==='seller')){if(sect)sect.style.display='none';return;}
  if(sect)sect.style.display='';
  var r=await api('/seller/dashboard');var el=document.getElementById('c_ov_seller');if(!el)return;
  var ns=((r.body||{}).nodes)||[];
  if(!ns.length){el.innerHTML=cEmpty('No nodes yet','Connect a GPU and start earning.','','List your PC','/install');return;}
  var online=ns.filter(function(n){return n.online;}).length;
  var earned=ns.reduce(function(a,n){return a+Number(n.earned_total||0);},0);
  el.innerHTML=
    '<div class="cmoney"><span class="mk">Nodes</span><span class="mv">'+cInt(ns.length)+' ('+online+' online)</span></div>'+
    '<div class="cmoney"><span class="mk">Earned to date</span><span class="mv teal">'+cD2(earned)+'</span></div>'+
    '<div style="margin-top:12px"><a class="cbtn sm" href="/seller/payouts">Earnings &amp; payouts →</a></div>';
}
async function cJobs(){
  var bs=(((await api('/account/bookings'))||{}).body||{}).bookings||[];
  document.getElementById('c_jobs').innerHTML=bs.length?bs.map(function(b){
    return '<tr><td data-l="When" class="mono" style="font-size:11px">'+cTs(b.created_at)+'</td><td data-l="GPU" class="mono">'+esc(b.gpu_model||'')+'</td><td data-l="Hours" class="mono">'+esc(String(b.hours))+'</td><td data-l="Amount" class="mono">'+cD2(b.gross_amount)+'</td><td data-l="Status">'+cBadge(b.status)+'</td></tr>';
  }).join(''):'<tr><td colspan=5 class="mut mono" style="text-align:center;padding:16px">No reservations yet. <a class="teal" href="/marketplace">Rent a GPU →</a></td></tr>';
}

async function cCompute(){
  var specs=(((await api('/specs'))||{}).body||{}).specs||[];
  document.getElementById('c_specs').innerHTML=specs.length?specs.map(function(s){
    var save=(s.cloud_reference&&s.price_per_hour<s.cloud_reference)?Math.round((1-s.price_per_hour/s.cloud_reference)*100):0;
    var trust=s.trust?('<span class="badge'+(s.trust.rank>=2?' ok':'')+'">'+esc(s.trust.label||'')+'</span>'):'<span class="mut mono">standard</span>';
    return '<tr><td data-l="GPU" class="mono">'+esc(s.gpu_model||'CPU')+'</td>'+
     '<td data-l="$/hr" class="mono amber">'+cD2(s.price_per_hour)+'</td>'+
     '<td data-l="vs cloud" class="mono">'+(save>0?('<span class="teal">-'+save+'%</span>'):'—')+'</td>'+
     '<td data-l="Trust">'+trust+'</td>'+
     '<td data-l="Region" class="mono">'+esc(s.region||'—')+'</td>'+
     '<td data-l=""><button class="cbtn sm" data-act="cRun" data-a1="'+s.spec_id+'">Run</button></td></tr>';
    }).join(''):'<tr><td colspan=6 class="mut mono" style="text-align:center;padding:16px">No GPUs online right now.</td></tr>';
  var vms=(((await api('/vms'))||{}).body||{}).vms||[];
  document.getElementById('c_vms').innerHTML=cVmRows(vms);
}
function cVmRows(vms){
  if(!vms.length)return '<tr><td colspan=6 class="mut mono" style="text-align:center;padding:16px">No VMs yet. <a class="teal" href="/marketplace">Rent a GPU →</a></td></tr>';
  return vms.map(function(v){var u=v.url||{};var live=(v.status==='running');
    return '<tr><td data-l="Template" class="mono">'+esc(v.template||'vm')+'</td>'+
     '<td data-l="Status">'+cBadge(v.status)+'</td>'+
     '<td data-l="Address" class="mono" style="font-size:11px">'+esc(u.hostname||u.id||'')+'</td>'+
     '<td data-l="Failover" class="mono">'+(v.migrations?('moved '+v.migrations+'&times;'):'—')+'</td>'+
     '<td data-l="Left" class="mono">'+(v.hours_left!=null?v.hours_left+'h':'—')+'</td>'+
     '<td data-l="">'+(live?('<button class="cbtn sm" data-act="cVmExtend" data-a1="'+esc(v.vm_id)+'">+1h</button> <button class="cbtn sm" data-act="cVmStop" data-a1="'+esc(v.vm_id)+'">Stop</button>'):'—')+'</td></tr>';
  }).join('');
}
async function cVmExtend(id){var r=await api('/vm/'+id+'/extend',{method:'POST',body:JSON.stringify({hours:1})});
  if(!r.ok)alert((r.body&&(r.body.detail||r.body.message))||'Could not extend.');cCompute();cWalletStrip();}
async function cVmStop(id){if(!confirm('Stop VM '+id+'? This releases the node.'))return;
  var r=await api('/vm/'+id+'/stop',{method:'POST'});if(!r.ok)alert('Could not stop.');cCompute();if(CLOADED['overview'])cRunning();}

function cOut(el,text,cls){var s=document.createElement('span');if(cls)s.className=cls;s.textContent=text;
  el.appendChild(document.createElement('br'));el.appendChild(s);el.scrollTop=el.scrollHeight;}
async function cRun(specId){
  if(typeof authed==='function' && !authed()){location.href='/login';return;}
  if(CTABS.indexOf('compute')>=0 && document.getElementById('tab-compute').style.display==='none')cNav('compute');
  var out=document.getElementById('c_out');out.innerHTML='<span class="sys">booking a node…</span>';
  var code=(document.getElementById('c_code')||{}).value||'';
  var spec=specId;
  if(!spec){var s=await api('/specs');var list=(s.body||{}).specs||[];
    if(!list.length){out.innerHTML='<span class="amber">No GPUs available.</span>';return;}spec=list[0].spec_id;}
  var bk=await api('/request_vm',{method:'POST',body:JSON.stringify({spec_id:Number(spec),hours:1})});
  if(!bk.ok){out.innerHTML='<span class="amber">'+(bk.status===402?'Add funds before booking (Billing).':'Booking failed: '+esc(JSON.stringify(bk.body)))+'</span>';return;}
  cOut(out,'booked #'+bk.body.booking_id+' · escrow '+cD2(bk.body.gross_amount)+' (fee '+cD2(bk.body.platform_fee)+', seller '+cD2(bk.body.seller_payout)+')','sys');
  var tk=await api('/create_task',{method:'POST',body:JSON.stringify({booking_id:bk.body.booking_id,task_type:'notebook',code:code})});
  if(!tk.ok){cOut(out,'task failed: '+JSON.stringify(tk.body),'amber');return;}
  var tid=tk.body.task_id;cOut(out,'dispatched task #'+tid+' → waiting for a node…','sys');
  var t0=Date.now();
  var poll=setInterval(async function(){
    var t=await api('/tasks/'+tid);var st=(t.body||{}).status;
    if(st==='completed'||st==='failed'){clearInterval(poll);
      cOut(out,'── '+String(st).toUpperCase()+' ──',st==='completed'?'ok':'amber');
      cOut(out,t.body.result||'(no output)','');cWalletStrip();cCompute();}
    else if(Date.now()-t0>60000){clearInterval(poll);cOut(out,'timed out.','amber');}
  },1400);
}

async function cClusters(){
  var cls=(((await api('/clusters'))||{}).body||{}).clusters||[];
  document.getElementById('c_clusters').innerHTML=cls.length?cls.map(function(j){
    return '<tr><td data-l="Job" class="mono">#'+j.job_id+'</td>'+
     '<td data-l="Status">'+cBadge(j.status)+'</td>'+
     '<td data-l="Size" class="mono">'+j.world_size+'&times; '+esc(j.backend||'')+'</td>'+
     '<td data-l="Rendezvous">'+(j.rendezvous_ready?'<span class="badge ok">ready</span>':'<span class="badge">forming</span>')+'</td></tr>';
    }).join(''):'<tr><td colspan=4 class="mut mono" style="text-align:center;padding:16px">No clusters yet. <a class="teal" href="/cluster">Form one →</a></td></tr>';
}

function cBytes(n){n=Number(n||0);if(n<1024)return n+' B';var u=['KB','MB','GB','TB','PB'],i=-1;do{n/=1024;i++;}while(n>=1024&&i<u.length-1);return n.toFixed(n<10?1:0)+' '+u[i];}
async function cStorage(){
  var vs=(((await api('/volumes'))||{}).body||{}).volumes||[];
  var totStored=vs.reduce(function(a,v){return a+Number(v.bytes_stored||0);},0);
  var totSnaps=vs.reduce(function(a,v){return a+Number(v.snapshots||0);},0);
  var mel=document.getElementById('c_stor_metrics');
  if(mel)mel.innerHTML=cMetric('Volumes',cInt(vs.length),'persistent')+cMetric('Stored',cBytes(totStored),'after dedup','pos')+cMetric('Snapshots',cInt(totSnaps),'point-in-time');
  var el=document.getElementById('c_volumes');if(!el)return;
  el.innerHTML=vs.length?vs.map(function(v){
    return '<tr><td data-l="Volume" class="mono">'+esc(v.name)+(v.size_limit_gb?' <span class="mut" style="font-size:11px">cap '+v.size_limit_gb+' GB</span>':'')+'</td>'+
     '<td data-l="Stored" class="mono">'+cBytes(v.bytes_stored)+'</td>'+
     '<td data-l="Snapshots" class="mono">'+cInt(v.snapshots)+'</td>'+
     '<td data-l="Saved" class="mono teal">'+(v.dedup_saved_bytes?cBytes(v.dedup_saved_bytes):'—')+'</td>'+
     '<td data-l="Created" class="mono" style="font-size:11px">'+esc(String(v.created_at||'').slice(0,10))+'</td>'+
     '<td data-l=""><button class="cbtn sm" data-act="cVolOpen" data-a1="'+v.id+'">Open</button> <button class="cbtn sm" data-act="cVolDelete" data-a1="'+v.id+'" data-a2="'+esc(v.name)+'">Delete</button></td></tr>';
    }).join(''):'<tr><td colspan=6 class="mut mono" style="text-align:center;padding:16px">No volumes yet. Create one to keep datasets and checkpoints between runs.</td></tr>';
}
async function cVolCreate(){
  var name=((document.getElementById('c_volname')||{}).value||'').trim();
  var cap=((document.getElementById('c_volsize')||{}).value||'').trim();
  var msg=document.getElementById('c_volmsg');
  if(!name){if(msg)msg.textContent='Enter a volume name.';return;}
  var body={name:name};if(cap)body.size_limit_gb=Number(cap);
  var r=await api('/volumes',{method:'POST',body:JSON.stringify(body)});
  if(r.ok){document.getElementById('c_volname').value='';document.getElementById('c_volsize').value='';if(msg)msg.textContent='Created "'+name+'".';cStorage();}
  else{if(msg)msg.textContent=(r.body&&r.body.error&&r.body.error.message)||(r.body&&typeof r.body.detail==='string'&&r.body.detail)||'Could not create volume.';}
}
async function cVolOpen(id){
  var box=document.getElementById('c_vol_detail');if(!box)return;
  var r=await api('/volumes/'+id);
  if(!r.ok){box.style.display='';box.innerHTML='<div class="csec"><div class="csec-b"><p class="mut" style="padding:12px 0">Could not load this volume.</p></div></div>';return;}
  var v=r.body||{};var snaps=v.snapshots||[];
  var rows=snaps.length?snaps.map(function(s){
    return '<tr><td data-l="#" class="mono">'+s.seq+'</td>'+
     '<td data-l="Label" class="mono">'+esc(s.label||'—')+'</td>'+
     '<td data-l="Files" class="mono">'+cInt(s.files)+'</td>'+
     '<td data-l="Delta uploaded" class="mono teal">'+cBytes(s.delta_bytes)+'</td>'+
     '<td data-l="Logical size" class="mono">'+cBytes(s.total_bytes)+'</td>'+
     '<td data-l="When" class="mono" style="font-size:11px">'+cTs(s.created_at)+'</td></tr>';
    }).join(''):'<tr><td colspan=6 class="mut mono" style="text-align:center;padding:14px">No snapshots yet — take one from a VM with <span class="mono">petabyte volume snapshot '+esc(v.name)+'</span>.</td></tr>';
  box.style.display='';
  box.innerHTML='<div class="csec"><div class="csec-h"><h2>Snapshots — '+esc(v.name)+'</h2>'+
    '<span class="mini" style="text-transform:none;letter-spacing:0;color:var(--mut)">'+cBytes(v.bytes_stored)+' stored · '+cBytes(v.dedup_saved_bytes)+' saved by dedup</span></div>'+
    '<div class="panel" style="overflow:auto;margin:12px 15px"><table class="tbl"><thead><tr><th>#</th><th>Label</th><th>Files</th><th>Delta uploaded</th><th>Logical size</th><th>When</th></tr></thead><tbody>'+rows+'</tbody></table></div>'+
    '<p class="mini" style="margin:2px 15px 14px;text-transform:none;letter-spacing:0">Each snapshot only uploads content that changed since the last one. Restore ships just the delta.</p></div>';
  try{box.scrollIntoView({behavior:'smooth',block:'nearest'});}catch(e){}
}
async function cVolDelete(id,name){
  if(!confirm('Delete volume "'+name+'"? This removes every snapshot and all stored content. This cannot be undone.'))return;
  var r=await api('/volumes/'+id,{method:'DELETE'});
  if(!r.ok){alert((r.body&&r.body.error&&r.body.error.message)||(r.body&&typeof r.body.detail==='string'&&r.body.detail)||'Could not delete volume.');return;}
  var box=document.getElementById('c_vol_detail');if(box)box.style.display='none';
  cStorage();
}

async function cBilling(){
  var w=((await api('/wallet'))||{}).body||{};
  document.getElementById('c_bill_wallet').innerHTML=
    cMetric('Balance',cD2(w.balance),'available','pos')+cMetric('Withdrawable',cD2(w.withdrawable),'ready to pay out')+
    cMetric('Clearing',cD2(w.clearing),'settling')+cMetric('Earnings',cD2(w.earnings),'to date');
  var ms=(((await api('/wallet/methods'))||{}).body||{}).methods||[];
  var payable=ms.filter(function(m){return m.payable;});
  var sel=document.getElementById('c_wmethod');
  sel.innerHTML=payable.length?payable.map(function(m){return '<option value="'+m.id+'">'+esc((m.label||m.kind)+' — '+m.destination)+'</option>';}).join(''):'<option value="">No payout method</option>';
  var nomsg=document.getElementById('c_wnomethod');if(nomsg)nomsg.style.display=payable.length?'none':'';
  var ps=(((await api('/wallet/payouts'))||{}).body||{}).payouts||[];
  document.getElementById('c_payouts').innerHTML=ps.length?ps.map(function(p){
    return '<tr><td data-l="Amount" class="mono">'+cD2(p.amount_usd)+'</td>'+
     '<td data-l="Kind" class="mono">'+esc(p.kind||'')+'</td>'+
     '<td data-l="Status">'+cBadge(p.status)+'</td>'+
     '<td data-l="When" class="mono" style="font-size:11px">'+cTs(p.created_at)+'</td></tr>';
    }).join(''):'<tr><td colspan=4 class="mut mono" style="text-align:center;padding:14px">No payouts yet.</td></tr>';
  var bs=(((await api('/account/bookings'))||{}).body||{}).bookings||[];
  document.getElementById('c_bookings').innerHTML=bs.length?bs.map(function(b){
    return '<tr><td data-l="When" class="mono" style="font-size:11px">'+cTs(b.created_at)+'</td>'+
     '<td data-l="GPU" class="mono">'+esc(b.gpu_model||'')+'</td>'+
     '<td data-l="Hours" class="mono">'+esc(String(b.hours))+'</td>'+
     '<td data-l="Amount" class="mono">'+cD2(b.gross_amount)+'</td>'+
     '<td data-l="Status">'+cBadge(b.status)+'</td></tr>';
    }).join(''):'<tr><td colspan=5 class="mut mono" style="text-align:center;padding:14px">No bookings yet.</td></tr>';
  cReferral();
}
async function cDeposit(){
  var amt=parseFloat((document.getElementById('c_dep')||{}).value);
  if(!amt||amt<=0){alert('Enter an amount.');return;}
  var r=await api('/deposit',{method:'POST',body:JSON.stringify({amount:amt})});
  if(r.ok){cWalletStrip();cBilling();}
  else if(r.status===403){alert('In live mode, funds are added at checkout — rent a GPU and pay by card.');}
  else{alert('Could not add funds.');}
}
async function cWithdraw(){
  var mid=(document.getElementById('c_wmethod')||{}).value;
  var amt=parseFloat((document.getElementById('c_wamt')||{}).value);
  if(!mid){alert('Add a payout method first (link below the box).');return;}
  if(!amt||amt<=0){alert('Enter an amount.');return;}
  var r=await api('/wallet/withdraw',{method:'POST',body:JSON.stringify({method_id:Number(mid),amount:amt})});
  if(r.ok){alert('Payout requested: '+cD2(r.body.amount_usd));cWalletStrip();cBilling();}
  else{alert((r.body&&(r.body.message||r.body.detail))||'Withdrawal failed.');}
}
async function cReferral(){
  var r=((await api('/referral'))||{}).body||{};
  var el=document.getElementById('c_referral');if(!el)return;
  el.innerHTML='<div class="stats" style="margin-bottom:12px">'+
    cStat(cD2(r.reward_usd),'You earn','amber')+cStat(cInt(r.invited),'Invited','')+
    cStat(cInt(r.qualified),'Qualified','')+cStat(cD2(r.credit_earned_usd),'Credit earned','teal')+'</div>'+
    '<div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center">'+
    '<input id="c_reflink" readonly value="'+esc(r.link||'')+'" style="flex:1;min-width:220px"/>'+
    '<button class="cbtn" data-act="cRefCopy">Copy link</button></div>'+
    '<p class="mini" style="margin-top:8px">Both sides get spendable compute credit when someone you invite completes their first paid rental.</p>';
}
function cRefCopy(){var i=document.getElementById('c_reflink');if(!i||!i.value)return;i.select();
  try{navigator.clipboard.writeText(i.value);}catch(e){try{document.execCommand('copy');}catch(_){}}}

async function cTeams(){
  var orgs=(((await api('/orgs'))||{}).body||{}).orgs||[];
  document.getElementById('c_orgs').innerHTML=orgs.length?orgs.map(function(o){
    return '<tr><td data-l="Team" class="mono">'+esc(o.name)+'</td>'+
     '<td data-l="Your role">'+cBadge(o.your_role)+'</td>'+
     '<td data-l="Balance" class="mono">'+cD2(o.balance)+'</td>'+
     '<td data-l="Budget cap" class="mono">'+(o.budget_cap!=null?cD2(o.budget_cap):'&#8734;')+'</td>'+
     '<td data-l="Spent" class="mono">'+cD2(o.spent)+'</td>'+
     '<td data-l="Members" class="mono">'+cInt(o.members)+'</td>'+
     '<td data-l=""><button class="cbtn sm" data-act="cTeamOpen" data-a1="'+o.org_id+'">Manage</button></td></tr>';
    }).join(''):'<tr><td colspan=7 class="mut mono" style="text-align:center;padding:16px">No teams yet — create one to share a wallet and set a budget cap.</td></tr>';
}
async function cOrgCreate(){
  var name=((document.getElementById('c_orgname')||{}).value||'').trim();
  var msg=document.getElementById('c_orgmsg');
  if(name.length<2){if(msg)msg.textContent='Team name must be at least 2 characters.';return;}
  var r=await api('/orgs',{method:'POST',body:JSON.stringify({name:name})});
  if(r.ok){document.getElementById('c_orgname').value='';if(msg)msg.textContent='Created "'+name+'" — you are the admin.';cTeams();cTeamOpen(r.body.org_id);}
  else{if(msg)msg.textContent=(r.body&&typeof r.body.detail==='string'&&r.body.detail)||'Could not create team.';}
}
async function cTeamOpen(orgId){
  var box=document.getElementById('c_team_detail');if(!box)return;
  var r=await api('/orgs/'+orgId);
  if(!r.ok){box.style.display='';box.innerHTML='<div class="csec"><div class="csec-b"><p class="mut" style="padding:12px 0">Could not load this team.</p></div></div>';return;}
  var o=r.body||{};var isAdmin=(o.your_role==='admin');var mem=o.members||[];
  var rows=mem.map(function(mm){
    var roleCell=isAdmin
      ? '<select data-role-select="1" data-org="'+orgId+'" data-user="'+esc(mm.username)+'">'+
          ['admin','billing','member'].map(function(rn){return '<option value="'+rn+'"'+(mm.role===rn?' selected':'')+'>'+rn+'</option>';}).join('')+'</select>'
      : cBadge(mm.role);
    var rm=isAdmin?'<button class="cbtn sm" data-act="cMemberRemove" data-a1="'+orgId+'" data-a2="'+esc(mm.username)+'">Remove</button>':'';
    return '<tr><td data-l="Member" class="mono">'+esc(mm.username)+'</td><td data-l="Role">'+roleCell+'</td><td data-l="">'+rm+'</td></tr>';
  }).join('');
  var invite=isAdmin
    ? '<div class="csec-h" style="border:0;padding:14px 15px 6px"><h2>Add a member</h2></div>'+
      '<div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;padding:0 15px 14px">'+
      '<input id="c_inv_user" placeholder="username" style="flex:1;min-width:150px"/>'+
      '<select id="c_inv_role"><option value="member">member</option><option value="billing">billing</option><option value="admin">admin</option></select>'+
      '<button class="cbtn pri" data-act="cMemberAdd" data-a1="'+orgId+'">Add</button>'+
      '<p class="mini" id="c_inv_msg" style="width:100%;margin-top:4px;text-transform:none;letter-spacing:0"></p></div>'
    : '<p class="mini" style="margin:12px 15px;text-transform:none;letter-spacing:0">Only a team admin can add or change members.</p>';
  box.style.display='';
  box.innerHTML='<div class="csec"><div class="csec-h"><h2>Members — '+esc(o.name)+'</h2>'+
    '<span class="mini" style="text-transform:none;letter-spacing:0;color:var(--mut)">balance '+cD2(o.balance)+' · spent '+cD2(o.spent)+' · budget '+(o.budget_cap!=null?cD2(o.budget_cap):'&#8734;')+'</span></div>'+
    '<div class="panel" style="overflow:auto;margin:12px 15px"><table class="tbl"><thead><tr><th>Member</th><th>Role</th><th></th></tr></thead><tbody>'+rows+'</tbody></table></div>'+
    invite+(isAdmin?'<div id="c_team_audit" style="margin:6px 15px 14px"></div>':'')+'</div>';
  if(isAdmin)cOrgAudit(orgId);
}
async function cMemberAdd(orgId){
  var u=((document.getElementById('c_inv_user')||{}).value||'').trim();
  var role=(document.getElementById('c_inv_role')||{}).value||'member';
  var msg=document.getElementById('c_inv_msg');
  if(!u){if(msg)msg.textContent='Enter a username.';return;}
  var r=await api('/orgs/'+orgId+'/members',{method:'POST',body:JSON.stringify({username:u,role:role})});
  if(r.ok){cTeamOpen(orgId);cTeams();}
  else{if(msg)msg.textContent=(r.body&&typeof r.body.detail==='string'&&r.body.detail)||(r.status===404?'No user with that username.':'Could not add member.');}
}
async function cMemberRole(orgId,username,role){
  var r=await api('/orgs/'+orgId+'/members/'+encodeURIComponent(username),{method:'PUT',body:JSON.stringify({role:role})});
  if(!r.ok)alert((r.body&&(r.body.detail||r.body.message))||'Could not change role.');
  cTeamOpen(orgId);cTeams();
}
async function cMemberRemove(orgId,username){
  if(!confirm('Remove '+username+' from this team?'))return;
  var r=await api('/orgs/'+orgId+'/members/'+encodeURIComponent(username),{method:'DELETE'});
  if(!r.ok)alert((r.body&&(r.body.detail||r.body.message))||'Could not remove member.');
  cTeamOpen(orgId);cTeams();
}
document.addEventListener('change',function(e){var s=e.target;
  if(s&&s.getAttribute&&s.getAttribute('data-role-select')!=null){
    cMemberRole(s.getAttribute('data-org'),s.getAttribute('data-user'),s.value);}});

async function cAccess(){
  var ks=(((await api('/account/keys'))||{}).body||{}).keys||[];
  document.getElementById('c_keys').innerHTML=ks.length?ks.map(function(k){
    var sc=Array.isArray(k.scopes)?k.scopes.join(' '):String(k.scopes||'');
    return '<tr><td data-l="Label" class="mono">'+esc(k.label||'—')+'</td>'+
     '<td data-l="Scopes" class="mono" style="font-size:11px">'+esc(sc)+'</td>'+
     '<td data-l="Expires" class="mono" style="font-size:11px">'+esc(String(k.expires_at||'').slice(0,10))+'</td>'+
     '<td data-l="Status">'+(k.revoked?'<span class="badge">revoked</span>':'<span class="badge ok">active</span>')+'</td>'+
     '<td data-l="">'+(k.revoked?'':'<button class="cbtn sm" data-act="cKeyRevoke" data-a1="'+esc(k.jti)+'">Revoke</button>')+'</td></tr>';
    }).join(''):'<tr><td colspan=5 class="mut mono" style="text-align:center;padding:14px">No API keys yet. Create one to drive Petabyte from code or CI.</td></tr>';
  c2faLoad();cNotifs();cAudit();
}
async function c2faLoad(){
  var el=document.getElementById('c_2fa');if(!el)return;
  var s=((await api('/account/2fa'))||{}).body||{};
  if(s.enabled){
    el.innerHTML='<div><span class="badge ok">2FA is on</span> <span class="mut" style="font-size:13px">Sign-in requires a code from your authenticator app.</span></div>'+
      '<div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-top:12px">'+
      '<input id="c2fa_dis_pw" type="password" placeholder="password" style="min-width:150px"/>'+
      '<input id="c2fa_dis_code" inputmode="numeric" placeholder="current code" style="width:130px"/>'+
      '<button class="btn btn-ghost" data-act="c2faDisable">Turn off 2FA</button></div>'+
      '<p class="mini" id="c2fa_msg" style="margin-top:8px;text-transform:none;letter-spacing:0"></p>';
  } else {
    el.innerHTML='<div><span class="badge">2FA is off</span></div>'+
      '<button class="btn btn-amber" style="margin-top:12px" data-act="c2faSetup">Set up authenticator app</button>'+
      '<p class="mini" id="c2fa_msg" style="margin-top:8px;text-transform:none;letter-spacing:0"></p>';
  }
}
async function c2faSetup(){
  var r=await api('/account/2fa/setup',{method:'POST'});
  if(!r.ok){alert('Could not start 2FA setup.');return;}
  var d=r.body||{};var el=document.getElementById('c_2fa');
  var grouped=(d.secret||'').replace(/(.{4})/g,'$1 ').trim();
  el.innerHTML='<div class="lbl">Add this account to your authenticator app</div>'+
    '<p class="mut" style="font-size:13px;margin:6px 0">Scan the setup URI as a QR, or type the secret in manually, then enter the 6-digit code to confirm.</p>'+
    '<div class="mini">Secret (manual entry)</div><input readonly value="'+esc(grouped)+'" class="mono" style="width:100%;margin-top:4px"/>'+
    '<div class="mini" style="margin-top:10px">Setup URI (otpauth)</div><input readonly value="'+esc(d.otpauth_uri||'')+'" class="mono" style="width:100%;font-size:11px;margin-top:4px"/>'+
    '<div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-top:12px">'+
    '<input id="c2fa_code" inputmode="numeric" placeholder="6-digit code" style="width:130px"/>'+
    '<input id="c2fa_pw" type="password" placeholder="password" style="min-width:150px"/>'+
    '<button class="btn btn-amber" data-act="c2faEnable">Enable 2FA</button></div>'+
    '<p class="mini" id="c2fa_msg" style="margin-top:8px;text-transform:none;letter-spacing:0"></p>';
}
async function c2faEnable(){
  var code=(document.getElementById('c2fa_code')||{}).value||'';
  var pw=(document.getElementById('c2fa_pw')||{}).value||'';
  var msg=document.getElementById('c2fa_msg');
  var r=await api('/account/2fa/enable',{method:'POST',body:JSON.stringify({code:code,password:pw})});
  if(!r.ok){if(msg)msg.textContent=((r.body&&r.body.error&&r.body.error.message)||(r.body&&r.body.detail)||'Could not enable — check the code and password.');return;}
  var codes=(r.body||{}).backup_codes||[];var el=document.getElementById('c_2fa');
  el.innerHTML='<div><span class="badge ok">2FA is on</span></div>'+
    '<div class="lbl" style="margin-top:12px">Recovery codes — save these now</div>'+
    '<p class="mut" style="font-size:13px;margin:6px 0">Each works once if you lose your device. They are shown only this time.</p>'+
    '<div class="panel" style="padding:12px;columns:2"><div class="mono" style="font-size:13px;line-height:1.9">'+
    codes.map(function(x){return esc(x);}).join('<br>')+'</div></div>'+
    '<button class="btn btn-ghost" style="margin-top:12px" data-act="cAccess">Done</button>';
}
async function c2faDisable(){
  var pw=(document.getElementById('c2fa_dis_pw')||{}).value||'';
  var code=(document.getElementById('c2fa_dis_code')||{}).value||'';
  var msg=document.getElementById('c2fa_msg');
  var r=await api('/account/2fa/disable',{method:'POST',body:JSON.stringify({password:pw,code:code})});
  if(!r.ok){if(msg)msg.textContent=((r.body&&r.body.error&&r.body.error.message)||(r.body&&r.body.detail)||'Could not disable — check the password and code.');return;}
  c2faLoad();
}
function cAuditBadge(el,integ){
  if(!el)return;
  if(integ&&integ.intact){el.innerHTML='<span class="badge ok">chain verified</span> '+integ.checked+' events, tamper-evident';}
  else if(integ){el.innerHTML='<span class="badge" style="color:var(--bad);border-color:var(--bad)">chain broken</span> from #'+integ.first_broken_id;}
  else{el.textContent='';}
}
function cAuditRows(events){
  if(!events.length)return '<tr><td colspan=5 class="mut mono" style="text-align:center;padding:14px">No events yet.</td></tr>';
  return events.map(function(e){
    var d=e.detail; if(d&&typeof d==='object'){try{d=JSON.stringify(d);}catch(x){d='';}}
    return '<tr><td data-l="When" class="mono" style="font-size:11px">'+cTs(e.at)+'</td>'+
     '<td data-l="Action" class="mono">'+esc(e.action||'')+'</td>'+
     '<td data-l="Target" class="mono" style="font-size:11px">'+esc(e.resource||e.target||'—')+'</td>'+
     '<td data-l="Detail" class="mut" style="font-size:12px">'+esc(d||'')+'</td>'+
     '<td data-l="IP" class="mono" style="font-size:11px">'+esc(e.ip||'—')+'</td></tr>';
  }).join('');
}
async function cAudit(){
  var r=((await api('/account/audit'))||{}).body||{};
  document.getElementById('c_audit').innerHTML=cAuditRows(r.events||[]);
  cAuditBadge(document.getElementById('c_audit_integrity'), r.integrity);
}
async function cOrgAudit(orgId){
  var el=document.getElementById('c_team_audit');if(!el)return;
  var r=((await api('/orgs/'+orgId+'/audit'))||{}).body||{};
  el.innerHTML='<div class="lbl" style="margin-top:16px">Team audit log <span class="mut" id="c_team_audit_integ" style="font-weight:400;text-transform:none;letter-spacing:0"></span></div>'+
    '<div class="panel" style="overflow:auto;margin-top:8px"><table class="tbl"><thead><tr><th>When</th><th>Actor</th><th>Action</th><th>Target</th><th>Detail</th></tr></thead><tbody>'+
    ((r.events||[]).length?(r.events||[]).map(function(e){
      var d=e.detail; if(d&&typeof d==='object'){try{d=JSON.stringify(d);}catch(x){d='';}}
      return '<tr><td data-l="When" class="mono" style="font-size:11px">'+cTs(e.at)+'</td>'+
       '<td data-l="Actor" class="mono">'+esc(e.actor||'—')+'</td>'+
       '<td data-l="Action" class="mono">'+esc(e.action||'')+'</td>'+
       '<td data-l="Target" class="mono" style="font-size:11px">'+esc(e.resource||'—')+'</td>'+
       '<td data-l="Detail" class="mut" style="font-size:12px">'+esc(d||'')+'</td></tr>';
    }).join(''):'<tr><td colspan=5 class="mut mono" style="text-align:center;padding:14px">No events yet.</td></tr>')+
    '</tbody></table></div>';
  cAuditBadge(document.getElementById('c_team_audit_integ'), r.integrity);
}
async function cKeyCreate(){
  var label=encodeURIComponent((document.getElementById('c_keylabel')||{}).value||'');
  var days=Number((document.getElementById('c_keydays')||{}).value||7);
  var scopes=encodeURIComponent((document.getElementById('c_keyscopes')||{}).value||'');
  var q='days='+days+(label?'&label='+label:'')+(scopes?'&scopes='+scopes:'');
  var r=await api('/create_api_key?'+q,{method:'POST'});
  var out=document.getElementById('c_keyout');
  if(r.ok){out.style.display='';out.innerHTML='<div class="lbl">New key — copy it now, it is shown once</div>'+
    '<code class="mono" style="word-break:break-all;color:var(--teal)">'+esc(r.body.api_key)+'</code>';cAccess();}
  else{alert('Could not create key.');}
}
async function cKeyRevoke(jti){
  if(!confirm('Revoke this key? Any agent using it stops working.'))return;
  var r=await api('/keys/'+jti+'/revoke',{method:'POST'});
  if(r.ok)cAccess();else alert('Could not revoke.');
}
async function cNotifs(){
  var ns=(((await api('/notifications'))||{}).body||{}).notifications||[];
  document.getElementById('c_notifs').innerHTML=ns.length?ns.map(function(n){
    return '<tr><td data-l="When" class="mono" style="font-size:11px">'+cTs(n.created_at)+'</td>'+
     '<td data-l="Event" class="mono">'+esc(n.event_type||'')+'</td>'+
     '<td data-l="Subject">'+esc(n.subject||'')+'</td>'+
     '<td data-l="Status">'+cBadge(n.status)+'</td></tr>';
    }).join(''):'<tr><td colspan=4 class="mut mono" style="text-align:center;padding:14px">No notifications.</td></tr>';
}

async function cSeller(){
  var r=await api('/seller/dashboard');var el=document.getElementById('c_seller');if(!el)return;
  if(!r.ok){el.innerHTML='<div class="csec"><div class="csec-b"><p class="mut" style="padding:12px 0">Could not load hosting data.</p></div></div>';return;}
  var ns=(r.body||{}).nodes||[];
  if(!ns.length){el.innerHTML='<div class="csec"><div class="csec-b" style="padding:16px"><div style="font-family:var(--disp);font-weight:600;color:var(--amber)">Become a host</div>'+
    '<p class="mut" style="font-size:13.5px;margin:6px 0 12px">Turn an idle GPU into income — Petabyte rents it out, and you can also earn from spare disk. One agent per computer.</p>'+
    '<a class="cbtn pri" href="/install">List your PC →</a></div></div>';return;}
  var online=ns.filter(function(n){return n.online;}).length;
  var earned=ns.reduce(function(a,n){return a+Number(n.earned_total||0);},0);
  el.innerHTML='<div class="cmetrics">'+cMetric('Nodes',cInt(ns.length),online+' online')+cMetric('Online',cInt(online),'accepting jobs','pos')+cMetric('Earned',cD2(earned),'to date')+'</div>'+
    '<section class="csec" style="margin-top:16px"><div class="csec-b" style="padding:14px"><p class="mut" style="font-size:13.5px">Manage nodes, spare-disk rental and payouts on your <a class="teal" href="/seller/payouts">earnings page →</a></p></div></section>';
}

// sidebar drawer (mobile) + command palette entries
(function(){
  var ham=document.getElementById('cham'),sb=document.getElementById('csidebar'),sc=document.getElementById('cscrim');
  if(ham&&sb&&sc){
    ham.addEventListener('click',function(){var open=!sb.classList.contains('open');sb.classList.toggle('open',open);sc.classList.toggle('on',open);});
    sc.addEventListener('click',function(){sb.classList.remove('open');sc.classList.remove('on');});
  }
  var srch=document.querySelector('.csearch');
  if(srch)srch.addEventListener('keydown',function(e){if(e.key==='Enter'||e.key===' '){e.preventDefault();cPalette();}});
  window.addEventListener('hashchange',function(){var h=(location.hash||'').replace('#','');if(CTABS.indexOf(h)>=0)cNav(h);});
  try{if(window.PB_CMDS&&window.PB_CMDS.push){
    PB_CMDS.push(
      {t:'Console: Overview',h:'/console#overview',k:'dashboard home console'},
      {t:'Launch compute',h:'/console#compute',k:'run job gpu launch new'},
      {t:'Console: Jobs',h:'/console#jobs',k:'reservations bookings history'},
      {t:'Console: Clusters',h:'/console#clusters',k:'distributed multi gpu torchrun'},
      {t:'Wallet & billing',h:'/console#billing',k:'add funds deposit withdraw pay money'},
      {t:'API keys',h:'/console#access',k:'token ci key developer'},
      {t:'Teams',h:'/console#teams',k:'iam members org budget'},
      {t:'Browse marketplace',h:'/marketplace',k:'gpu rent available'}
    );
  }}catch(e){}
})();
consoleLoad();
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
  var mvol=function(v){return e.restricted?'🔒 admin':money(v);};   // money volumes redacted for non-admins (L1)
  document.getElementById('grp_econ').innerHTML=
    tile('GMV',mvol(e.gmv),DEFS.gmv)+
    tile('Platform revenue',mvol(e.platform_revenue),DEFS.platform_revenue)+
    tile('Seller payouts',mvol(e.seller_payouts),DEFS.seller_payouts)+
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
  var btn=document.querySelector('[data-act="submitDemo"]');
  if(btn&&btn.disabled) return;                       // guard: no duplicate lead on double-click
  var name=(document.getElementById('d_name').value||'').trim();
  var email=(document.getElementById('d_email').value||'').trim();
  if(!name||!email){m.style.color='var(--warn)';m.textContent='Please add your name and email.';return;}
  if(btn) btn.disabled=true;
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
    if(!r.ok){if(btn) btn.disabled=false;m.style.color='var(--warn)';
      m.textContent=(b.error&&b.error.message)||(typeof b.detail==='string'?b.detail:'Please check your name and email, then try again.');return;}
    document.getElementById('demoform').innerHTML='<div style="text-align:center;padding:20px 10px">'+
      '<div class="mono" style="font-size:32px;color:var(--teal)">&#10003;</div>'+
      '<div style="font-family:var(--disp);font-weight:600;margin:8px 0 4px" data-ar="تم استلام الطلب">Request received</div>'+
      '<div class="mut" style="font-size:13.5px">'+b.message+'</div>'+
      (b.booking_url?('<a class="btn btn-amber" style="margin-top:14px" href="'+b.booking_url+'" target="_blank" rel="noopener" data-ar="اختر وقتاً يناسبك ←">Pick your time →</a>'):'')+
      '<div class="mini" style="margin-top:10px" data-ar="المرجع">Reference '+b.reference+'</div></div>';
  }catch(e){if(btn) btn.disabled=false;m.style.color='var(--warn)';m.textContent='Network error. Try emailing info@petabyte.market.';}
}
</script>""")


# ============================ MODELS — discover / download / manage (Hugging Face-grade UX) ============================
_MODELS_CSS = """<style>
.mgrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:14px;margin-top:18px}
.mcard{border:1px solid var(--hair);border-radius:12px;padding:15px 16px;background:var(--panel,#fff);cursor:pointer;transition:border-color .12s,transform .12s}
.mcard:hover{border-color:var(--teal);transform:translateY(-1px)}
.mcard h3{font-size:15px;margin:0 0 6px;word-break:break-word}
.mrow{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-top:8px}
.mtag{font-size:11px;padding:2px 8px;border-radius:999px;border:1px solid var(--hair);color:var(--mut)}
.mbar{display:flex;gap:10px;flex-wrap:wrap;align-items:center;margin-top:14px}
.mbar input,.mbar select{padding:9px 11px;border:1px solid var(--hair);border-radius:9px;background:transparent;color:inherit;font:inherit}
.mfiles td{font-size:12.5px}
.mprog{height:12px;border-radius:999px;background:var(--hair);overflow:hidden}
.mprog>i{display:block;height:100%;background:linear-gradient(90deg,var(--teal),var(--amber));width:0}
.cbar{display:inline-block;background:var(--code,#0b1020);color:#cfe;border-radius:8px;padding:10px 12px;font-family:var(--mono,monospace);font-size:12.5px}
.gfit{color:var(--teal)}.gtight{color:var(--amber)}.gbad{color:#e5484d}
</style>"""

_MODELS_JS_HELPERS = """
function mBytes(n){n=Number(n||0);if(!n)return '';var u=['B','KB','MB','GB','TB'],i=0;while(n>=1024&&i<u.length-1){n/=1024;i++;}return (n>=100||i===0?n.toFixed(0):n.toFixed(1))+' '+u[i];}
function mParams(n){n=Number(n||0);if(!n)return '';if(n>=1e9)return (n%1e9?(n/1e9).toFixed(1):(n/1e9).toFixed(0))+'B';if(n>=1e6)return (n/1e6).toFixed(0)+'M';return ''+n;}
function mCompat(level){var map={good:['✓ Runs','gfit'],tight:['~ Tight','gtight'],insufficient:['✗ Too big','gbad'],unknown:['? Unknown','gtight']};var x=map[level]||map.unknown;return '<span class="'+x[1]+'">'+x[0]+'</span>';}
function mMachine(hw){if(!hw)return '';var g=hw.gpu_name||((hw.cpu_count||'?')+' CPU');var v=hw.vram_gb?(' · '+hw.vram_gb+' GB VRAM'):'';var r=hw.ram_gb?(' · '+hw.ram_gb+' GB RAM'):'';return 'This machine: '+esc(g)+v+r;}
"""

MODELS_HTML = _page("Petabyte — Models",
    desc="Discover and install open AI models with one command or one click — Hugging Face-grade convenience, provider-independent, hardware-aware.",
    path="/models", body=_MODELS_CSS + """
<div class="wrap" style="padding:40px 24px 60px">
  <div id="pbtestmode"></div>
  <div style="display:flex;justify-content:space-between;align-items:flex-end;flex-wrap:wrap;gap:12px">
    <div>
      <h1 style="margin:0">Models</h1>
      <p class="mut" style="margin:6px 0 0;max-width:60ch">Discover open models and install them in one action. Petabyte figures out the compatible files, verifies checksums, resumes broken downloads, and caches everything locally — you never touch a storage URL.</p>
    </div>
    <a class="btn btn-teal" href="/models/installed">Installed models →</a>
  </div>
  <div id="m_machine" class="mut mini" style="margin-top:12px"></div>
  <div class="mbar">
    <input id="m_q" placeholder="Search models (e.g. llama, qwen, code 7b)" style="flex:1;min-width:220px"/>
    <select id="m_license"><option value="">any license</option><option>apache-2.0</option><option>mit</option><option>llama3.1</option><option>gemma</option></select>
    <input id="m_maxparams" type="number" min="1" placeholder="max params (B)" style="width:150px"/>
    <label class="mini" style="display:flex;align-items:center;gap:6px"><input type="checkbox" id="m_fits"/> fits my machine</label>
    <button class="btn btn-amber" id="m_go">Search</button>
  </div>
  <div id="m_grid" class="mgrid"><p class="mut" style="padding:20px 0">Loading models…</p></div>
</div>
<script>
""" + _MODELS_JS_HELPERS + """
var M_HW=null;
async function mLoad(q){
  var grid=document.getElementById('m_grid');grid.innerHTML='<p class="mut" style="padding:20px 0">Loading…</p>';
  var qs='?q='+encodeURIComponent(q||'');
  var lic=document.getElementById('m_license').value;if(lic)qs+='&license='+encodeURIComponent(lic);
  var mp=document.getElementById('m_maxparams').value;if(mp)qs+='&max_params='+(Number(mp)*1e9);
  var r=await api('/api/models/search'+qs);
  if(!r.ok){grid.innerHTML='<p class="mut">Search is unavailable right now.</p>';return;}
  M_HW=r.body.machine;document.getElementById('m_machine').textContent=mMachine(M_HW);
  var rows=r.body.models||[];
  var fits=document.getElementById('m_fits').checked;
  if(fits)rows=rows.filter(function(x){return x.compatibility==='good'||x.compatibility==='tight';});
  if(!rows.length){grid.innerHTML='<p class="mut" style="padding:20px 0">No models found.</p>';return;}
  grid.innerHTML=rows.map(function(x){
    var badges=(x.installed?'<span class="mtag" style="color:var(--teal);border-color:var(--teal)">Installed</span>':'')+
      '<span class="mtag">'+mCompat(x.compatibility)+'</span>';
    return '<div class="mcard" data-id="'+esc(x.id)+'" onclick="mOpen(this)">'+
      '<h3>'+esc(x.id)+'</h3>'+
      '<div class="mut mini">'+esc(x.architecture||x.pipeline||'model')+'</div>'+
      '<div class="mrow">'+(x.parameters?'<span class="mtag">'+mParams(x.parameters)+' params</span>':'')+
        (x.license?'<span class="mtag">'+esc(x.license)+'</span>':'')+
        (x.downloads?'<span class="mtag">'+Number(x.downloads).toLocaleString()+' pulls</span>':'')+'</div>'+
      '<div class="mrow">'+badges+'</div></div>';
  }).join('');
}
function mOpen(el){location.href='/models/'+el.getAttribute('data-id');}
document.getElementById('m_go').addEventListener('click',function(){mLoad(document.getElementById('m_q').value);});
document.getElementById('m_q').addEventListener('keydown',function(e){if(e.key==='Enter')mLoad(this.value);});
document.getElementById('m_fits').addEventListener('change',function(){mLoad(document.getElementById('m_q').value);});
mLoad('');
</script>""")


MODEL_DETAIL_HTML = _page("Petabyte — Model",
    desc="Model details, hardware compatibility, files and one-click install on Petabyte.",
    path="/models", body=_MODELS_CSS + """
<div class="wrap" style="padding:34px 24px 60px">
  <div id="pbtestmode"></div>
  <a class="mini teal" href="/models">← all models</a>
  <div id="m_head" style="margin-top:10px"><p class="mut">Loading…</p></div>
  <div id="m_prog" style="display:none;margin:18px 0">
    <div class="mini" id="m_prog_label" style="margin-bottom:6px"></div>
    <div class="mprog"><i id="m_prog_bar"></i></div>
    <div class="mini mut" id="m_prog_sub" style="margin-top:6px"></div>
  </div>
  <div id="m_msg" class="mini" style="margin-top:10px"></div>
  <div id="m_body"></div>
</div>
<script>
""" + _MODELS_JS_HELPERS + """
var MID=decodeURIComponent(location.pathname.replace(/^\\/models\\//,'').replace(/\\/$/,''));
var M_JOB=null;
function setMsg(t,cls){var m=document.getElementById('m_msg');m.textContent=t||'';m.className='mini '+(cls||'');}
async function mInfo(){
  var head=document.getElementById('m_head');
  var r=await api('/api/models/'+MID);
  if(!r.ok){head.innerHTML='<h1>'+esc(MID)+'</h1><p class="mut">'+esc((r.body&&r.body.error&&r.body.error.message)||'Could not load this model.')+'</p>';return;}
  var m=r.body.manifest, comp=r.body.compatibility, installed=r.body.installed;
  var hw=comp.machine||{};
  var dl=installed
    ? '<button class="btn btn-teal" id="m_rm" onclick="mRemove()">Remove</button> <span class="teal mini">✓ Installed</span>'
    : '<button class="btn btn-amber" id="m_dl" onclick="mPull()">Download model</button>';
  head.innerHTML='<h1 style="margin:6px 0 4px">'+esc(m.id)+'</h1>'+
    '<div class="mut">'+[m.parameters?mParams(m.parameters)+' params':'',esc(m.architecture||''),esc(m.format||''),esc(m.license||''),m.total_size?mBytes(m.total_size):''].filter(Boolean).join(' · ')+'</div>'+
    '<div style="margin:14px 0">'+dl+'</div>'+
    '<div class="panel" style="padding:12px 14px;max-width:560px"><b>Compatibility</b> '+mCompat(comp.level)+
      '<div class="mini mut" style="margin-top:4px">'+esc(mMachine(hw))+'</div>'+
      (comp.reasons||[]).map(function(x){return '<div class="mini mut">• '+esc(x)+'</div>';}).join('')+
      (comp.alternatives&&comp.alternatives.length?('<div class="mini" style="margin-top:6px">Lighter options: '+comp.alternatives.map(function(a){return esc(a.quantization)+' (~'+a.vram_gb+' GB)';}).join(' · ')+'</div>'):'')+
    '</div>';
  var reqs=m.requirements||{};
  var files=(m.files||[]).map(function(f){return '<tr><td class="mono">'+esc(f.path)+'</td><td class="mono">'+mBytes(f.size)+'</td><td>'+(f.sha256?'<span class="teal">sha256</span>':'<span class="mut">—</span>')+'</td></tr>';}).join('');
  var tr=m.trust||{};
  document.getElementById('m_body').innerHTML=
    '<h2 style="margin-top:22px">Hardware requirements</h2>'+
    '<p class="mut">~'+(reqs.vram_gb||'?')+' GB VRAM · ~'+(reqs.ram_gb||'?')+' GB RAM · '+(reqs.disk_gb||'?')+' GB disk'+(m.context_length?(' · context '+m.context_length):'')+'</p>'+
    '<h2 style="margin-top:22px">Files ('+(m.files||[]).length+')</h2>'+
    '<div class="panel" style="overflow:auto"><table class="tbl mfiles"><thead><tr><th>File</th><th>Size</th><th>Verify</th></tr></thead><tbody>'+files+'</tbody></table></div>'+
    '<h2 style="margin-top:22px">Source &amp; trust</h2>'+
    '<p class="mut">source: '+esc(m.source||'')+' · '+(tr.source_verified?'<span class="teal">verified source</span>':'<span class="amber">unverified source</span>')+' · '+(tr.hashed?'<span class="teal">weights hash-verified</span>':'<span class="amber">weights not hash-verified</span>')+'</p>'+
    '<p class="mini mut">Petabyte never runs downloaded repository code. Remote code (trust_remote_code) is off by default.</p>';
}
async function mPull(){
  var btn=document.getElementById('m_dl');if(btn)btn.disabled=true;setMsg('');
  var r=await api('/api/models/pull',{method:'POST',body:JSON.stringify({id:MID,force:true})});
  if(r.status===401){setMsg('Please sign in to install a model on this node.','amber');if(btn)btn.disabled=false;return;}
  if(r.status===503){showCli();if(btn)btn.disabled=false;return;}
  if(!r.ok){setMsg((r.body&&r.body.error&&r.body.error.message)||'Could not start the download.','amber');if(btn)btn.disabled=false;return;}
  M_JOB=r.body.job_id;document.getElementById('m_prog').style.display='';pollJob(M_JOB);
}
function showCli(){
  setMsg('Server-side install is disabled on this node. Install locally with the CLI:','amber');
  document.getElementById('m_prog').style.display='none';
  document.getElementById('m_body').insertAdjacentHTML('afterbegin','<div class="cbar" style="margin:8px 0 4px">petabyte model pull '+esc(MID)+'</div>');
}
async function pollJob(jid){
  var bar=document.getElementById('m_prog_bar'),lab=document.getElementById('m_prog_label'),sub=document.getElementById('m_prog_sub');
  var t=setInterval(async function(){
    var r=await api('/api/models/downloads/'+jid);
    if(!r.ok){clearInterval(t);return;}
    var j=r.body;
    bar.style.width=(j.percent||0)+'%';
    lab.textContent=(j.status==='done'?'✓ Ready':'Downloading '+(j.file||''))+' — '+(j.percent||0)+'%';
    sub.textContent=mBytes(j.downloaded)+' / '+mBytes(j.total)+' · '+(j.files_done||0)+'/'+(j.files_total||0)+' files'+(j.cache_hits?(' · '+j.cache_hits+' cached'):'');
    if(['done','error','gated','incompatible','busy'].indexOf(j.status)>=0){
      clearInterval(t);
      if(j.status==='done'){setMsg('✓ Installed and verified.','teal');mInfo();}
      else{setMsg(j.error||j.message||'Download failed.','amber');}
    }
  },700);
}
async function mRemove(){
  if(!confirm('Remove '+MID+' from this node?'))return;
  var r=await api('/api/models/'+MID,{method:'DELETE'});
  if(!r.ok){setMsg((r.body&&r.body.error&&r.body.error.message)||'Could not remove.','amber');return;}
  setMsg('Removed.','teal');mInfo();
}
mInfo();
</script>""")


MODELS_INSTALLED_HTML = _page("Petabyte — Installed models",
    desc="Models installed on this Petabyte node, with sizes, cache usage and removal.",
    path="/models/installed", body=_MODELS_CSS + """
<div class="wrap" style="padding:40px 24px 60px">
  <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:12px">
    <h1 style="margin:0">Installed models</h1>
    <a class="btn btn-amber" href="/models">＋ Discover models</a>
  </div>
  <div id="mi_cache" class="mut mini" style="margin-top:10px"></div>
  <div class="panel" style="overflow:auto;margin-top:14px"><table class="tbl"><thead><tr><th>Model</th><th>Size</th><th>Format</th><th>Status</th><th></th></tr></thead><tbody id="mi_rows"><tr><td colspan=5 class="mut mono" style="text-align:center;padding:16px">Loading…</td></tr></tbody></table></div>
</div>
<script>
""" + _MODELS_JS_HELPERS + """
async function miLoad(){
  var r=await api('/api/models/installed');
  var tb=document.getElementById('mi_rows');
  if(!r.ok){tb.innerHTML='<tr><td colspan=5 class="mut">Could not load.</td></tr>';return;}
  var rows=r.body.models||[];
  if(!rows.length){tb.innerHTML='<tr><td colspan=5 class="mut mono" style="text-align:center;padding:16px">No models installed. <a class="teal" href="/models">Discover models →</a></td></tr>';}
  else{tb.innerHTML=rows.map(function(x){
    return '<tr><td class="mono">'+esc(x.id)+'</td><td class="mono">'+mBytes(x.total_size)+'</td><td class="mono">'+esc(x.format||'—')+'</td>'+
      '<td>'+(x.installed?'<span class="teal">Ready</span>':'<span class="amber">incomplete</span>')+'</td>'+
      '<td><button class="btn btn-teal" data-mid="'+esc(x.id)+'" onclick="miRemove(this)">Remove</button></td></tr>';
  }).join('');}
}
async function miRemove(el){
  var id=el.getAttribute('data-mid');
  if(!confirm('Remove '+id+'?'))return;
  var r=await api('/api/models/'+id,{method:'DELETE'});
  miLoad();
}
miLoad();
</script>""")
