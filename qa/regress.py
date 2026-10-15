#!/usr/bin/env python3
"""Regression suite for Bari practice.

Drives the app in headless Chromium, records what every feature produces, and
compares one build against another so a release can be checked for parity
with the one before it.

    python3 qa/regress.py --base-ref v1.1 index.html     # compare against a git tag
    python3 qa/regress.py old.html new.html              # compare two files (or URLs)
    python3 qa/regress.py index.html                     # one build: functional checks only

Each check returns a value. Between two builds a check is:
    same  - identical output
    new   - the base build doesn't have the feature (the check returned "n/a")
    DIFF  - output changed; a regression unless named with --allow
    FAIL  - the check threw, or the page raised an error while it ran
Exit status is 1 if anything is DIFF (and not allowed) or FAIL.

Needs: pip install playwright (Chromium). Sign-in and sync run against the
fake Firebase modules in qa/fake-firebase, so no network is needed.
"""
import argparse, difflib, hashlib, json, pathlib, re, subprocess, sys, tempfile, time, traceback
from playwright.sync_api import sync_playwright

HERE = pathlib.Path(__file__).resolve().parent
FAKE = {k: (HERE / "fake-firebase" / f"{k}.js").read_text() for k in ("app", "auth", "firestore")}

INIT = r"""(()=>{
  let s = %d;
  window.__seed = v => { s = v >>> 0; };
  Math.random = () => { s |= 0; s = s + 0x6D2B79F5 | 0; let t = Math.imul(s ^ s >>> 15, 1 | s);
    t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t; return ((t ^ t >>> 14) >>> 0) / 4294967296; };
  window.__h = str => { let h = 5381; for (let i = 0; i < str.length; i++) h = ((h << 5) + h + str.charCodeAt(i)) | 0; return (h >>> 0).toString(36); };
})();"""

IGNORED_CONSOLE = re.compile(r"Failed to load resource|ERR_TUNNEL|ERR_FAILED|fonts\.g")


class Server:
    """In-memory Firestore for the fake modules."""
    def __init__(self): self.docs = {}
    def __call__(self, op, path, data, merge):
        if op == "get": return json.dumps(self.docs.get(path))
        if op == "list":
            pre = path + "/"
            return json.dumps([[k[len(pre):], v] for k, v in self.docs.items() if k.startswith(pre) and "/" not in k[len(pre):]])
        d = json.loads(data)
        if merge and isinstance(self.docs.get(path), dict): _deep(self.docs[path], d)
        else: self.docs[path] = d
        return "null"

def _deep(a, b):
    for k, v in b.items():
        if isinstance(v, dict) and isinstance(a.get(k), dict): _deep(a[k], v)
        else: a[k] = v


class Env:
    def __init__(self, browser, url, outdir):
        self.browser, self.url, self.outdir = browser, url, outdir
        self.errors, self.dialogs, self.ctxs = [], [], []

    def page(self, viewport=(1300, 900), seed=12345, firebase="block", server=None, url=None, downloads=False):
        ctx = self.browser.new_context(viewport={"width": viewport[0], "height": viewport[1]}, accept_downloads=downloads)
        self.ctxs.append(ctx)
        ctx.add_init_script(INIT % seed)
        pg = ctx.new_page()
        pg.on("pageerror", lambda e: self.errors.append(f"pageerror: {e}"))
        pg.on("console", lambda m: self.errors.append(f"console: {m.text}") if m.type == "error" and not IGNORED_CONSOLE.search(m.text) else None)
        pg.on("dialog", lambda d: (self.dialogs.append(d.message[:80]), d.accept() if self.policy == "accept" else d.dismiss()))
        self.policy = "accept"
        if firebase == "block":
            pg.route("**/www.gstatic.com/firebasejs/**", lambda r: r.abort())
        else:
            pg.expose_function("__srv", server or Server())
            def route(r):
                m = re.search(r"firebase-(\w+)\.js", r.request.url)
                r.fulfill(status=200, content_type="application/javascript", body=FAKE[m.group(1)])
            pg.route("**/www.gstatic.com/firebasejs/**", route)
        pg.goto(url or self.url); pg.wait_for_timeout(350)
        return pg

    def shot(self, pg, name, **kw):
        if self.outdir: pg.screenshot(path=str(self.outdir / f"{name}.png"), **kw)

    def close(self):
        for c in self.ctxs:
            try: c.close()
            except Exception: pass
        self.ctxs = []


CHECKS = []
def check(name):
    def wrap(f): CHECKS.append((name, f)); return f
    return wrap

E = lambda pg, js: pg.evaluate(js)

def tick(pg, sel, on=True):
    """Set a checkbox styled as a chip (the input itself is invisible) and fire its change handler."""
    pg.evaluate("([s,v])=>{ const i=document.querySelector(s); i.checked=v; i.dispatchEvent(new Event('change',{bubbles:true})); }", [sel, on])


# ---------------------------------------------------------------- load / layout
@check("load.shell")
def _(env):
    pg = env.page(); env.shot(pg, "scales_desktop")
    return E(pg, '()=>({title:document.title, h1:document.querySelector("h1").textContent.trim(), tabs:TABS.map(t=>$("tab-"+t).textContent.trim()), start:store.get("tab","scales")})')

@check("layout.tabs_phone_and_desktop")
def _(env):
    out = {}
    for w in (390, 1300):
        pg = env.page(viewport=(w, 860))
        for t in ("scales", "cards", "songs", "prog"):
            pg.click(f"#tab-{t}"); pg.wait_for_timeout(150)
            out[f"{w}:{t}"] = E(pg, f'()=>[document.documentElement.scrollWidth<={w}, !$("view-{t}").hidden]')
            env.shot(pg, f"{t}_{w}", full_page=(w == 390))
    return out


# ---------------------------------------------------------------- scales
SET_SCALE = '''(a)=>{ $("sType").value=a[0]; fillKeys(); $("sKey").value=a[1]; $("sOct").value=a[2]; fillStarts();
  if(a[3]!=null) $("sStart").value=a[3]; $("sDir").value=a[4]; $("sGroup").value=a[5]; buildSeq(); }'''

@check("scales.every_sequence")
def _(env):
    pg = env.page()
    seqs = E(pg, '''()=>{ const out=[]; const opts=id=>[...$(id).options].map(o=>o.value);
      for(const t of opts("sType")){ $("sType").value=t; fillKeys();
        for(const k of opts("sKey")){ $("sKey").value=k;
          for(const oc of opts("sOct")){ $("sOct").value=oc; fillStarts();
            for(const st of opts("sStart")){ $("sStart").value=st;
              for(const d of opts("sDir")){ $("sDir").value=d; $("sGroup").value="0"; buildSeq();
                out.push(`${t}|${$("sKey").selectedOptions[0].text}|${oc}|${st}|${d}|${$("notice").textContent}| `+S.seq.map(n=>nm(n)+n.o).join(" ")); }}}}}
      return out; }''')
    return {"count": len(seqs), "sha": hashlib.sha1("\n".join(seqs).encode()).hexdigest()[:16], "_lines": seqs}

@check("scales.note_groups")
def _(env):
    pg = env.page(); out = {}
    for t, k in (("major", "0"), ("harmin", "9"), ("blues", "7"), ("chrom", "3")):
        for g in E(pg, '()=>[...$("sGroup").options].map(o=>o.value)'):
            E(pg, f'()=>({SET_SCALE})(["{t}","{k}","1",null,"updown","{g}"])')
            out[f"{t}:{k}:g{g}"] = E(pg, '()=>[$("preview").textContent, S.seq.map(n=>nm(n)+n.o+(n.gs?"|":"")).join(" ")]')
    return out

@check("scales.fingerings")
def _(env):
    pg = env.page()
    return E(pg, '''()=>{ const o={}; for(let m=LO;m<=HI;m++){ const k=fingering(m);
      o[m]=[noteName(m,"sharp"), k.join(" "), pressRows(k).map(r=>r.join(": ")).join(" / "), TIPS[m]||"", __h(fingSVG(k,460))]; } return o; }''')

@check("scales.display")
def _(env):
    pg = env.page(); out = {}
    for t, k, i in (("major", "0", 0), ("major", "0", 7), ("natmin", "4", 3), ("dom7", "10", 2)):
        E(pg, f'()=>({SET_SCALE})(["{t}","{k}","1",null,"updown","0"])'); E(pg, f"()=>go({i})")
        out[f"{t}:{k}:{i}"] = E(pg, '''()=>({notes:$("staff").querySelectorAll(".nt").length, staff:__h($("staff").innerHTML),
          big:$("bigLetter").textContent, cap:$("bigCap").textContent, press:$("press").textContent, tip:$("tip").textContent,
          count:$("count").textContent, fing:__h($("fingWrap").innerHTML)})''')
    env.shot(pg, "scales_display")
    return out

@check("scales.keyboard_and_buttons")
def _(env):
    pg = env.page()
    E(pg, f'()=>({SET_SCALE})(["major","0","1",null,"updown","0"])')
    pg.evaluate("()=>document.activeElement.blur()")
    pg.keyboard.press("ArrowRight"); pg.keyboard.press("ArrowRight"); a = E(pg, "S.i")
    pg.keyboard.press("ArrowLeft"); b = E(pg, "S.i")
    pg.click("#next"); c = E(pg, "S.i"); pg.click("#prev"); d = E(pg, "S.i")
    return [a, b, c, d, E(pg, '$("count").textContent')]

@check("scales.playback")
def _(env):
    pg = env.page()
    E(pg, f'()=>({SET_SCALE})(["major","0","1",null,"updown","0"])')
    E(pg, '()=>{ $("bpm").value=$("bpm").max; $("bpm").dispatchEvent(new Event("input")); $("optCount").checked=false; $("optCount").dispatchEvent(new Event("change")); }')
    pg.click("#play"); pg.wait_for_timeout(1500)
    mid = E(pg, '()=>[S.playing, S.i>0, $("playLabel").textContent]')
    pg.click("#play")
    end = E(pg, '()=>[S.playing, $("playLabel").textContent]')
    pg.evaluate("()=>document.activeElement.blur()"); pg.keyboard.press(" "); pg.wait_for_timeout(100)
    sp = E(pg, "S.playing"); pg.keyboard.press(" ")
    return {"mid": mid, "end": end, "space": [sp, E(pg, "S.playing")]}

FOLLOW = '''()=>{ const feed=(m,n)=>{ for(let k=0;k<n;k++){ SM.heard.add(m);
      if(SM.cand!==m){SM.cand=m;SM.since=performance.now()-1000;SM.n=1;} else SM.n++;
      const w=S.seq[S.i].m, nx=S.seq[S.i+1];
      if(m===w&&SM.n>=3){ sclStep('ok',m); return; }
      if(nx&&m===nx.m&&SM.n>=3){ sclStep(SM.heard.has(w)?'ok':'miss', w, true); if(!SM.done) sclStep('ok',m); return; } } };
    let guard=0;
    while(!SM.done && guard++<200){
      const target=S.seq[S.i].m;
      if(S.i===2){ feed(S.seq[3].m,4); continue; }
      if(S.i===5){ SM.heard.add(target); feed(S.seq[6].m,4); continue; }
      feed(target,4);
    }
    return S.res.join(","); }'''

def mic_on(pg, loop):
    E(pg, f'()=>({SET_SCALE})(["major","0","1",null,"updown","0"])')
    E(pg, f'()=>{{ $("optLoop").checked={str(loop).lower()}; $("optLoop").dispatchEvent(new Event("change")); $("optMic").checked=true; $("optMic").onchange(); }}')
    pg.wait_for_timeout(700)

@check("scales.mic_follow")
def _(env):
    pg = env.page(); mic_on(pg, False)
    res = E(pg, FOLLOW); pg.wait_for_timeout(2200)
    out = {"marks": res, "msg": E(pg, '$("sclMsg").textContent'), "stays_done": E(pg, "SM.done"),
           "red": E(pg, '()=>$("staff").querySelectorAll(".miss,.wrong,.bad").length>0'),
           "prof": E(pg, '()=>{const d=PROF["scale:major:0"]; return d&&[d.label,d.cat,Math.round(d.score),d.reps,d.tries,d.hits]}')}
    E(pg, '()=>{ $("optMic").checked=false; $("optMic").onchange(); }')
    out["mic_released"] = E(pg, "AUD.refs")
    return out

@check("scales.mic_loop_continuous")
def _(env):
    pg = env.page()
    if not E(pg, 'typeof sclNextRun==="function"'): return "n/a"
    mic_on(pg, True)
    r1 = E(pg, FOLLOW); m1 = E(pg, '$("sclMsg").textContent'); pg.wait_for_timeout(2200)
    a = E(pg, '()=>[SM.on, SM.done, SM.run, S.i, S.res.length, $("sclMsg").textContent]')
    r2 = E(pg, FOLLOW); pg.wait_for_timeout(2200)
    b = E(pg, '()=>[SM.run, SM.done, PROF["scale:major:0"].reps]')
    E(pg, '()=>{ $("optLoop").checked=false; $("optLoop").dispatchEvent(new Event("change")); }')
    E(pg, FOLLOW); pg.wait_for_timeout(2200)
    c = E(pg, '()=>[SM.done, SM.run, $("sclMsg").textContent]')
    E(pg, '()=>{ $("optMic").checked=false; $("optMic").onchange(); }')
    return {"run1": [r1, m1], "restarted": a, "run2": [r2, b], "loop_off": c, "mic_released": E(pg, "AUD.refs")}

@check("scales.settings_persist")
def _(env):
    pg = env.page()
    pg.select_option("#sType", "blues"); pg.select_option("#sKey", "7"); pg.select_option("#sDir", pg.evaluate('[...$("sDir").options].pop().value'))
    pg.select_option("#sGroup", "3"); tick(pg, "#optClick", False)
    before = E(pg, '()=>[$("sType").value,$("sKey").value,$("sDir").value,$("sGroup").value,$("optClick").checked,$("bpm").value]')
    pg.reload(); pg.wait_for_timeout(350)
    after = E(pg, '()=>[$("sType").value,$("sKey").value,$("sDir").value,$("sGroup").value,$("optClick").checked,$("bpm").value]')
    return [before, after]


# ---------------------------------------------------------------- flashcards
def cards(env, **kw):
    pg = env.page(**kw); pg.click("#tab-cards"); pg.wait_for_timeout(100); return pg

@check("cards.options")
def _(env):
    pg = cards(env)
    return E(pg, '()=>({keys:[...$("cKey").options].map(o=>o.textContent), groups:[...$("cGroup").options].map(o=>o.value+":"+o.textContent), faces:[...document.querySelectorAll(".face-opt")].map(i=>i.value+":"+i.checked), ranges:[...document.querySelectorAll(".rng")].map(i=>i.value+":"+i.checked)})')

@check("cards.note_pools")
def _(env):
    pg = cards(env); out = {}
    for rs in (["low"], ["mid"], ["palm"], ["low", "mid", "palm"]):
        for acc in (True, False):
            for key in ("all", "0", "7", "5", "6"):
                out[f"{'+'.join(rs)}|acc={acc}|key={key}"] = E(pg, f'''()=>{{ document.querySelectorAll(".rng").forEach(i=>i.checked={json.dumps(rs)}.includes(i.value));
                  $("cAcc").checked={str(acc).lower()}; $("cKey").value="{key}"; return pool().map(n=>nm(n)+n.o).join(" "); }}''')
    return out

@check("cards.deal")
def _(env):
    pg = cards(env); out = {}
    for g in ("1", "2", "3"):
        out[g] = E(pg, f'''()=>{{ __seed(7); $("cGroup").value="{g}"; const r=[]; let far=0;
          for(let i=0;i<30;i++){{ pickNext(); r.push(C.g.map(n=>nm(n)+n.o).join("-"));
            for(let j=1;j<C.g.length;j++) far=Math.max(far, Math.abs(C.g[j].m-C.g[j-1].m)); }}
          return {{cards:r, widest:far}}; }}''')
    return out

@check("cards.faces")
def _(env):
    pg = cards(env); out = {}
    for faces in (["staff"], ["name"], ["fing"], ["staff", "name"], ["staff", "name", "fing"]):
        out["+".join(faces)] = E(pg, f'''()=>{{ document.querySelectorAll(".face-opt").forEach(i=>i.checked={json.dumps(faces)}.includes(i.value));
          $("cMix").checked=false; setFaces(); __seed(3); $("cGroup").value="2"; pickNext();
          return {{front:["Staff","Name","Fing"].filter(F=>$("face"+F).classList.contains("front")),
            staff:!!$("faceStaff").querySelector("svg"), name:$("faceName").textContent.replace(/\\s+/g," ").trim(),
            fing:$("faceFing").querySelectorAll(".fing").length, hint:$("cardHint").textContent,
            btns:["reveal","got","miss"].map(id=>$(id).disabled)}}; }}''')
    env.shot(pg, "cards")
    return out

@check("cards.grading")
def _(env):
    pg = cards(env)
    E(pg, '()=>{ __seed(11); $("cGroup").value="1"; pickNext(); }')
    first = E(pg, "()=>C.g.map(n=>n.m)")
    pg.click("#reveal"); rev = E(pg, '()=>[C.revealed, $("got").disabled, $("faceName").textContent.replace(/\\s+/g," ").trim()]')
    pg.click("#got"); pg.wait_for_timeout(50)
    pg.click("#reveal"); pg.click("#miss"); pg.click("#reveal"); pg.click("#miss")
    pg.evaluate("()=>document.activeElement.blur()"); pg.keyboard.press(" "); pg.keyboard.press("ArrowRight")
    return {"first": first, "reveal": rev,
            "stats": E(pg, '()=>[stats.right, stats.missed, stats.streak, Object.keys(stats.miss).length]'),
            "score": E(pg, '()=>[$("sRight").textContent,$("sMiss").textContent,$("sStreak").textContent,$("trouble").textContent]'),
            "prof": E(pg, '()=>Object.entries(PROF).map(([k,d])=>[k,d.label,d.cat,Math.round(d.score),d.reps]).sort()'),
            "saved": E(pg, '()=>store.get("stats")')}

@check("cards.mic_mode")
def _(env):
    pg = cards(env)
    E(pg, '()=>{ __seed(5); $("cGroup").value="1"; $("cMic").checked=true; $("cMic").onchange(); }'); pg.wait_for_timeout(700)
    E(pg, "()=>pickNext()")
    t = E(pg, "C.g[0].m")
    E(pg, f"()=>micWrong({t}+2)")
    wrong = E(pg, '()=>[C.revealed, stats.missed, $("listenMsg").textContent, $("card").classList.contains("wrong")]')
    E(pg, f"()=>micRight({t})")
    right = E(pg, '()=>[$("listenMsg").textContent, $("card").classList.contains("ok"), stats.right]')
    pg.wait_for_timeout(1500)
    nxt = E(pg, "()=>[C.revealed, C.gi]")
    E(pg, '()=>{ $("cGroup").value="2"; pickNext(); micRight(C.g[0].m); }')
    two = E(pg, '()=>[C.gi, $("listenMsg").textContent, C.gres]')
    E(pg, '()=>{ $("cMic").checked=false; $("cMic").onchange(); }')
    return {"wrong": wrong, "right": right, "advanced": nxt, "group": two, "mic_released": E(pg, "AUD.refs")}

@check("cards.settings_persist")
def _(env):
    pg = cards(env)
    tick(pg, '.face-opt[value="name"]'); pg.select_option("#cKey", "7"); pg.select_option("#cGroup", "3"); tick(pg, '.rng[value="palm"]')
    before = E(pg, '()=>store.get("cards")'); pg.reload(); pg.wait_for_timeout(300)
    return [before, E(pg, '()=>[chosenFaces(), $("cKey").value, $("cGroup").value, [...document.querySelectorAll(".rng:checked")].map(i=>i.value)]')]


# ---------------------------------------------------------------- songs
def songs(env, **kw):
    pg = env.page(**kw); pg.click("#tab-songs"); pg.wait_for_timeout(150); return pg

FPRINT = '''()=>{ const w=$("scoreWrap"), c=s=>w.querySelectorAll(s).length;
  const heads=[...w.querySelectorAll(".nh")].map(e=>e.getAttribute("cx")+","+e.getAttribute("cy")).join(";");
  return {vb:w.querySelector("svg").getAttribute("viewBox"), nh:c(".nh"), stem:c(".stem"), beam:c(".beam"), ledger:c(".ledger"),
    flag:c(".flagp"), dot:c(".dot-n"), bar:c(".barline"), glyph:c(".glyph"), sn:c(".sn"), heads:__h(heads),
    // every drawn shape with its attributes and on-screen transform; wrapper groups and invisible click targets don't count
    ink:__h([...w.querySelectorAll("svg *")].filter(e=>!e.children.length && !e.classList.contains("hit")).map(e=>{
      const m=e.getCTM(); return e.tagName+"|"+[...e.attributes].map(a=>a.name+"="+a.value).join(",")+"|"+(m?[m.a,m.b,m.c,m.d,m.e,m.f].map(v=>v.toFixed(2)).join(","):"");
    }).join("~"))}; }'''

@check("songs.library")
def _(env):
    pg = songs(env)
    return E(pg, '()=>songs.map(g=>[g.id,g.title,g.sub,g.level,g.key,g.ckey,g.bpm,g.slow,g.feel,g.bars,g.measures.join(" | "),g.sections.map(s=>s.name+" "+s.a+"-"+s.b).join(", ")])')

@check("songs.render_each")
def _(env):
    pg = songs(env); out = {}
    for i in range(E(pg, "songs.length")):
        E(pg, f'()=>{{ $("songSel").value={i}; $("songSel").onchange(); }}'); pg.wait_for_timeout(60)
        info = E(pg, '''()=>({title:$("songTitle").textContent, sub:$("songSub").textContent, facts:$("songFacts").textContent.replace(/\\s+/g," ").trim(),
          about:$("songAbout").textContent, bad:$("badBars").textContent, secs:$("secTabs").textContent.replace(/\\s+/g," ").trim(), tip:$("secTip").textContent,
          tempo:$("tempoNote").textContent, parsed:(()=>{const r=parseSong(sg().measures); return [r.bad.length, r.ms.length, r.ms.reduce((a,m)=>a+m.ev.filter(e=>!e.rest).length,0)]})()})''')
        info["score"] = E(pg, FPRINT)
        secs = E(pg, "sg().sections.length")
        info["sections"] = []
        for s in range(secs + 1):
            E(pg, f"()=>{{ Q.sec={s}; renderSong(); }}")
            info["sections"].append(E(pg, '()=>[$("scoreWrap").querySelectorAll(".sn.inSec").length, $("secTip").textContent.slice(0,60)]'))
        out[E(pg, "sg().id")] = info
    env.shot(pg, "songs", full_page=True)
    return out

@check("songs.playback_and_swing")
def _(env):
    pg = songs(env)
    E(pg, '()=>{ $("songSel").value=1; $("songSel").onchange(); Q.sec=0; renderSong(); $("sBpm").value=$("sBpm").max; $("sBpm").oninput(); $("sCount").checked=false; }')
    pg.click("#sPlay"); pg.wait_for_timeout(1200)
    mid = E(pg, '()=>[Q.playing, Q.cur>=0, $("scoreWrap").querySelectorAll(".sn.cur").length]')
    pg.click("#sPlay"); end = E(pg, "Q.playing")
    pg.evaluate("()=>document.activeElement.blur()"); pg.keyboard.press(" "); pg.wait_for_timeout(80)
    sp = E(pg, "Q.playing"); pg.keyboard.press(" ")
    swing = E(pg, '()=>[[0.5,0],[0.5,0.5],[1,0],[1.5,1]].map(([d,at])=>[evMs({dur:d,at},600,true).toFixed(1), evMs({dur:d,at},600,false).toFixed(1)])')
    return {"mid": mid, "end": end, "space": [sp, E(pg, "Q.playing")], "swing": swing}

SCORE = '''(miss)=>{ const ex=secNotes(), beat=60/(+$("sBpm").value), fr=[]; let t=0;
  const evs=secEvents();
  evs.forEach(e=>{ const d=evMs(e,beat*1000,$("sSwing").checked)/1000;
    if(!e.rest){ const k=ex.indexOf(e), m = miss.includes(k) ? e.m+2 : e.m;
      for(let x=0; x<d-0.05; x+=0.012) fr.push({t:t+x, m, cents:4, rms:0.1});
      fr.push({t:t+d-0.04, m:null, cents:0, rms:0}); }
    t+=d; });
  Q.frames=fr; recFinish(); const r=Q.report;
  return [r.score, r.hit, r.total, r.feel, Math.round(r.tuneScore), Math.round(r.timeScore), prog()[pkey()], $("report").textContent.replace(/\\s+/g," ").trim().slice(0,160)]; }'''

@check("songs.listen_and_score")
def _(env):
    pg = songs(env)
    E(pg, '()=>{ $("songSel").value=0; $("songSel").onchange(); Q.sec=0; renderSong(); }')
    clean = E(pg, f"()=>({SCORE})([])")
    rough = E(pg, f"()=>({SCORE})([1,3])")
    return {"clean": clean, "rough": rough, "prof": E(pg, '()=>Object.entries(PROF).map(([k,d])=>[k,d.label,d.cat,Math.round(d.score),d.reps])'),
            "tip": E(pg, '$("tempoNote").textContent'), "bpm": E(pg, '$("sBpm").value')}

NEW_SONG = "G4:1 Bb4:0.5 B4:0.5 D5:2\nC#5:1.5 r:0.5 E5:2\nF4:0.5 G4:0.5 A4:0.5 Bb4:0.5 C5:2\nG4:4"

def add_song(pg, bars, title="QA tune", swing=True, bpm="96"):
    pg.click("#songAdd"); pg.wait_for_timeout(60)
    if E(pg, '!!$("edSvg")'):                       # v1.2+: staff editor, notation goes in through "Paste notation"
        pg.click('#addBox summary'); pg.fill("#aBars", bars); pg.click("#aLoad")
    else:
        pg.fill("#aBars", bars)
    pg.fill("#aTitle", title); pg.fill("#aSub", "QA"); pg.fill("#aBpm", bpm)
    if swing: tick(pg, "#aSwing")
    pg.click("#aSave"); pg.wait_for_timeout(80)

@check("songs.add_your_own")
def _(env):
    pg = songs(env)
    add_song(pg, NEW_SONG)
    saved = E(pg, '()=>{ const g=songs[songs.length-1]; return {title:g.title, sub:g.sub, level:g.level, bpm:g.bpm, slow:g.slow, feel:g.feel, bars:g.bars, measures:g.measures, sections:g.sections, sel:$("songSel").value==String(songs.length-1), closed:$("addBox").hidden, stored:store.get("songs2").length}; }')
    saved["score"] = E(pg, FPRINT)
    env.shot(pg, "songs_custom")
    pg.reload(); pg.wait_for_timeout(300); pg.click("#tab-songs")
    saved["after_reload"] = E(pg, '()=>[songs.length, sg().title]')
    # a bar that doesn't add up is refused with the parser's message
    pg.click("#songAdd")
    if E(pg, '!!$("edSvg")'): pg.click('#addBox summary'); pg.fill("#aBars", "G4:3"); pg.click("#aLoad")
    else: pg.fill("#aBars", "G4:3"); pg.click("#aSave")
    saved["bad_bar"] = E(pg, '$("aErr").textContent')
    return saved

@check("songs.reset_and_delete")
def _(env):
    pg = songs(env)
    add_song(pg, "G4:4")
    n = E(pg, "songs.length")
    pg.click("#songDel"); pg.wait_for_timeout(60)
    after_del = E(pg, '()=>[songs.length, Q.si, sg().title, store.get("songs2").length]')
    E(pg, '()=>{ songs[0].measures[0]="r:4"; saveSongs(); setProg(p=>p["slowlane:0"]={best:90}); $("songSel").value=0; $("songSel").onchange(); }')
    pg.click("#songDel"); pg.wait_for_timeout(60)
    after_reset = E(pg, '()=>[songs[0].measures[0], prog()["slowlane:0"]||null]')
    return {"before": n, "deleted": after_del, "reset": after_reset, "dialogs": env.dialogs[-2:]}

@check("songs.staff_editor")
def _(env):
    pg = songs(env)
    pg.click("#songAdd")
    if not E(pg, '!!$("edSvg")'): return "n/a"
    E(pg, "()=>{ window.__t=[]; tone=(m)=>__t.push(m); }")
    E(pg, '''()=>{ window.__pt=(li,pos,x)=>{ const svg=$("edSvg").querySelector("svg"), P=svg.createSVGPoint();
        P.x=x; P.y=li*SG.H+SG.TOP-pos*SG.SP/2; const r=P.matrixTransform(svg.getScreenCTM()); return [r.x,r.y]; }; }''')
    def click(pos, x=700):
        X, Y = E(pg, f"()=>__pt(0,{pos},{x})"); pg.mouse.click(X, Y); pg.wait_for_timeout(30)
    for pos in (2, 4, 6, 15, -4): click(pos)
    placed = E(pg, '()=>[ED.ev.map(e=>nm(e)+e.o+":"+e.dur).join(" "), __t.join(","), $("edStatus").textContent]')
    pg.select_option("#edDur", "0.5")
    for pos in (0, 1, 2): click(pos)
    pg.select_option("#edDur", "4"); click(3)
    bars = E(pg, "edMeasures()")
    free = E(pg, '()=>$("edSvg").querySelector(".freelab")?.textContent')
    bb = pg.locator('#edSvg .sn[data-ed="0"] .nh').first.bounding_box(); pg.mouse.click(bb["x"] + bb["width"] / 2, bb["y"] + bb["height"] / 2)
    pg.select_option("#epLen", "2"); pg.click('#edPop label:has-text("♯")')
    edited = E(pg, '()=>[nm(ED.ev[0])+ED.ev[0].o+":"+ED.ev[0].dur, ED.dur]')
    pg.click('#edPop label:has-text("Rest")'); rest = E(pg, "ED.ev[0].rest"); pg.click('#edPop label:has-text("Note")')
    nh = pg.locator('#edSvg .sn[data-ed="1"] .nh').first.bounding_box(); x0, y0 = nh["x"] + nh["width"] / 2, nh["y"] + nh["height"] / 2
    _, yD = E(pg, "()=>__pt(0,6,0)"); _, yB = E(pg, "()=>__pt(0,4,0)")
    pg.mouse.move(x0, y0); pg.mouse.down()
    for k in range(1, 9): pg.mouse.move(x0, y0 + (yD - yB) * k / 8); pg.wait_for_timeout(10)
    pg.mouse.up(); dragged = E(pg, "()=>nm(ED.ev[1])+ED.ev[1].o")
    pg.keyboard.press("Escape"); pg.keyboard.press("ArrowLeft"); pg.keyboard.press("Backspace")
    n1 = E(pg, "ED.ev.length"); pg.keyboard.press("Control+z"); n2 = E(pg, "ED.ev.length")
    pg.fill("#aBpm", "300"); E(pg, "()=>{ED.sel=-1; __t.length=0}"); pg.click("#edPlay"); pg.wait_for_timeout(4500)
    played = E(pg, '()=>[ED.playing, __t.length, ED.ev.filter(e=>!e.rest).length]')
    pg.fill("#aTitle", "Built on the staff"); pg.click("#aSave"); pg.wait_for_timeout(60)
    return {"placed": placed, "bars": bars, "free": free, "edited": edited, "rest": rest, "dragged": dragged,
            "delete_undo": [n1, n2], "played": played, "saved": E(pg, '()=>[sg().title, sg().measures]')}


# ---------------------------------------------------------------- progress
SEED_DAYS = '''()=>{ const t=day0(new Date()), put=(o,min)=>{ ACT.days[dkey(addD(t,o))]={min,runs:2,h:{12:min}}; };
  Object.keys(ACT.days).forEach(k=>delete ACT.days[k]); ACT.goal={days:4,min:10}; daysDirty();
  [0,-1,-2,-3,-4,-5].forEach(o=>put(o,25)); for(let o=-20;o<=-12;o++) put(o,15); put(-30,4); put(-200,70);
  store.set("days",ACT.days); store.set("goal",ACT.goal); }'''

@check("prog.proficiency_math")
def _(env):
    pg = env.page()
    E(pg, '''()=>{ Object.keys(PROF).forEach(k=>delete PROF[k]);
      logPractice("scale:major:0","C major scale","scales",14,15); logPractice("scale:major:0","C major scale","scales",15,15);
      [1,1,0,1].forEach(c=>logPractice("note:62","D4","notes",c,1));
      logPractice("song:slowlane:0","Slow Lane Blues — The call","pieces",8,10);
      PROF["scale:blues:7"]={label:"G blues",cat:"scales",score:90,best:91,reps:5,tries:60,hits:55,last:Date.now()-40*DAY}; }''')
    return E(pg, '()=>Object.entries(PROF).map(([k,d])=>{ const p=profNow(d); return [k,d.label,d.cat,+d.score.toFixed(3),+(d.best||0).toFixed(3),d.reps,d.tries,d.hits,p.now,p.best,band(p.now)[1],ago(p.days)]; }).sort()')

@check("prog.proficiency_view")
def _(env):
    pg = env.page()
    E(pg, '''()=>{ Object.keys(PROF).forEach(k=>delete PROF[k]);
      [["scale:major:0","C major scale","scales",15,15],["scale:natmin:9","A minor scale","scales",9,15],["note:62","D4","notes",1,1],
       ["note:64","E4","notes",0,1],["song:slowlane:3","Slow Lane Blues — Whole tune","pieces",30,40]].forEach(a=>logPractice(...a));
      Object.values(PROF).forEach((d,i)=>d.last=Date.now()-(i+1)*3600e3); }''')
    pg.click("#tab-prog"); pg.wait_for_timeout(150); out = {}
    for s in E(pg, '()=>[...$("profSort").options].map(o=>o.value)'):
        pg.select_option("#profSort", s)
        out[s] = E(pg, '()=>[$("profTiles").textContent.replace(/\\s+/g," ").trim(), [...document.querySelectorAll("#profBody .prow .pname, #profBody .ntile b")].map(e=>e.textContent).join(","), $("profBody").querySelectorAll("h3").length]')
    env.shot(pg, "progress", full_page=True)
    return out

@check("prog.practice_log_views")
def _(env):
    pg = env.page(); E(pg, SEED_DAYS); pg.click("#tab-prog"); pg.wait_for_timeout(150); out = {}
    for v in ("1d", "1w", "4w", "1y"):
        pg.check(f'input[name=actv][value="{v}"]'); pg.wait_for_timeout(60)
        row = [E(pg, '$("actLab").textContent'), E(pg, '$("actSum").textContent'), E(pg, '()=>__h($("actChart").innerHTML)')]
        pg.click("#actPrev"); row.append(E(pg, '$("actLab").textContent')); row.append(E(pg, '$("actNext").disabled'))
        pg.click("#actNext"); pg.click("#actPrev"); pg.click("#actPrev"); pg.click("#actToday"); row.append(E(pg, '$("actLab").textContent'))
        out[v] = row
    return out

@check("prog.streaks_and_goal")
def _(env):
    pg = env.page(); E(pg, SEED_DAYS)
    st = E(pg, '()=>{ const s=actStats(); return {cur:s.cur,best:s.best,practiced:s.practiced,thisWeek:s.thisWeek,weeksMet:s.weeksMet,wBest:s.wBest,wCur:s.wCur,mins:Math.round(s.totalMin),weekMin:Math.round(s.thisWeekMin)}; }')
    pg.click("#tab-prog"); pg.wait_for_timeout(100)
    pg.click("#gUp"); pg.click("#gUp"); pg.click("#gDn"); pg.select_option("#gMin", "20")
    return {"stats": st, "goal": E(pg, '()=>[ACT.goal, store.get("goal"), $("goalCard").textContent.replace(/\\s+/g," ").trim()]'),
            "stats_at_20": E(pg, '()=>{const s=actStats(); return [s.cur,s.best,s.practiced]}')}

@check("prog.achievements")
def _(env):
    pg = env.page()
    E(pg, '''()=>{ const t=day0(new Date()); Object.keys(ACT.days).forEach(k=>delete ACT.days[k]); daysDirty();
      for(let o=-9;o<=0;o++) ACT.days[dkey(addD(t,o))]={min:70,runs:1,h:{9:70}};
      Object.keys(PROF).forEach(k=>delete PROF[k]);
      for(let k=0;k<12;k++) PROF["scale:major:"+k]={label:"k"+k,cat:"scales",score:95,best:95,reps:6,tries:90,hits:88,last:Date.now()};
      ACT.ach={}; actCheck(true); }''')
    pg.click("#tab-prog"); pg.wait_for_timeout(100)
    return {"ids": E(pg, "()=>ACHS.map(a=>a[0]+':'+a[2])"), "earned": E(pg, "()=>Object.keys(ACT.ach).filter(k=>!k.startsWith('wk:')).sort()"),
            "sub": E(pg, '$("achSub").textContent'), "tiles": E(pg, '()=>[...document.querySelectorAll("#achList .ach")].map(e=>e.classList.contains("got")?"got":e.querySelector("small").textContent)')}

@check("prog.manual_entry_and_timer")
def _(env):
    pg = env.page(); pg.click("#tab-prog"); pg.wait_for_timeout(100)
    y = E(pg, "()=>dkey(addD(day0(new Date()),-1))")
    pg.click(".logman summary"); pg.fill("#manDate", y); pg.fill("#manMin", "25"); pg.click("#manAdd")
    manual = [E(pg, '$("manMsg").textContent'), round(E(pg, f'()=>dget("{y}").min'))]
    pg.click("#sessBtn"); on = E(pg, '()=>[!!ACT.sess, $("sessBtn").textContent.includes("End")]')
    E(pg, "()=>{ ACT.sess.start=Date.now()-12*60000; store.set('sess',ACT.sess); }")
    before = E(pg, "()=>(dget(dkey(new Date()))||{min:0}).min")
    pg.click("#sessBtn"); pg.wait_for_timeout(100)
    return {"manual": manual, "timer_on": on, "toast": E(pg, '$("toast").textContent'),
            "added": round(E(pg, "()=>(dget(dkey(new Date()))||{min:0}).min") - before), "timer_off": E(pg, '()=>[ACT.sess, $("sessBtn").textContent.trim()]')}

@check("prog.export_import")
def _(env):
    pg = env.page(downloads=True)
    E(pg, SEED_DAYS); E(pg, '()=>{ logPractice("note:62","D4","notes",1,1); stats.right=3; store.set("stats",stats); actSave(true); }')
    pg.click("#tab-prog")
    with pg.expect_download() as dl: pg.click("#dataExport")
    path = dl.value.path(); data = json.loads(pathlib.Path(path).read_text())
    keys = sorted(data["data"].keys())
    src = {k: data["data"][k] for k in ("bari:days", "bari:goal", "bari:stats")}
    pg2 = env.page(seed=999)
    imp = pathlib.Path(tempfile.mkdtemp()) / "export.json"; imp.write_text(json.dumps(data))
    pg2.click("#tab-prog"); pg2.set_input_files("#dataImport", str(imp)); pg2.wait_for_timeout(1500)
    got = {k: pg2.evaluate(f'()=>localStorage.getItem("{k}")') for k in src}
    return {"app": data["app"], "v": data["v"], "keys": keys, "roundtrip": got == src,
            "prof_after": pg2.evaluate('()=>Object.keys(PROF)'), "file": dl.value.suggested_filename.split("-")[0]}


# ---------------------------------------------------------------- sign-in and sync
TOT = "()=>Math.round(Object.values(mergedDays()).reduce((a,r)=>a+r.min,0))"
DAYS3 = "()=>{const t=day0(new Date()); return [-2,-1,0].map(o=>{const r=dget(dkey(addD(t,o))); return r?Math.round(r.min):0;})}"

def device(env, server, seed, seed_js):
    pg = env.page(firebase="fake", server=server, seed=seed)
    pg.evaluate(seed_js); pg.reload(); pg.wait_for_timeout(1500)
    return pg

@check("sync.two_devices")
def _(env):
    srv = Server()
    A = device(env, srv, 101, """()=>{ const t=day0(new Date()), k=o=>dkey(addD(t,o));
      localStorage.setItem("bari:days",JSON.stringify({[k(-2)]:{min:30,runs:2,h:{9:30}},[k(-1)]:{min:15,runs:1,h:{9:15}}}));
      localStorage.setItem("bari:daysBackfilled","true"); ACT.noSave=true;
      localStorage.setItem("bari:prof",JSON.stringify({"scale:major:0":{label:"C major scale",cat:"scales",score:80,best:82,reps:4,last:1000}}));
      localStorage.setItem("bari:goal",JSON.stringify({days:5,min:10}));
      localStorage.setItem("bari:_ts",JSON.stringify({prof:1000,goal:5000})); }""")
    out = {"chip_out": A.text_content("#acctBtn").strip()}
    A.click("#acctBtn"); A.wait_for_timeout(900)
    out["chip_in"] = A.text_content("#acctBtn").strip(); out["docs"] = sorted(re.sub(r"devices/\w+", "devices/*", k) for k in srv.docs)
    B = device(env, srv, 202, """()=>{ const t=day0(new Date()), k=o=>dkey(addD(t,o));
      localStorage.setItem("bari:days",JSON.stringify({[k(-1)]:{min:20,runs:1,h:{18:20}},[k(0)]:{min:25,runs:3,h:{8:25}}}));
      localStorage.setItem("bari:daysBackfilled","true"); ACT.noSave=true;
      localStorage.setItem("bari:prof",JSON.stringify({"scale:major:0":{label:"C major scale",cat:"scales",score:90,best:90,reps:6,last:2000},
                                                      "note:62":{label:"D4",cat:"notes",score:70,best:70,reps:3,last:1500}}));
      localStorage.setItem("bari:goal",JSON.stringify({days:3,min:10}));
      localStorage.setItem("bari:_ts",JSON.stringify({prof:2000,goal:1000})); }""")
    B.click("#acctBtn"); B.wait_for_timeout(900)
    out["B_first"] = [B.evaluate(DAYS3), B.evaluate(TOT), B.evaluate("ACT.goal.days"), B.evaluate('PROF["scale:major:0"].score'), B.evaluate('"note:62" in PROF')]
    A.evaluate("()=>syncNow()"); A.wait_for_timeout(700)
    out["A_resync"] = [A.evaluate(DAYS3), A.evaluate(TOT), A.evaluate("ACT.goal.days"), A.evaluate('"note:62" in PROF')]
    for _ in range(2):
        A.evaluate("()=>syncNow()"); A.wait_for_timeout(400); B.evaluate("()=>syncNow()"); B.wait_for_timeout(400)
    out["no_double_count"] = [A.evaluate(TOT), B.evaluate(TOT)]
    B.evaluate("()=>{ const e=Date.now(); addMinutes(e-600000,e); actSave(true); return pushNow(); }"); B.wait_for_timeout(400)
    A.evaluate("()=>syncNow()"); A.wait_for_timeout(600)
    out["live_minutes"] = [A.evaluate(DAYS3)[2], A.evaluate("()=>Math.round(Object.values(ACT.days).reduce((a,r)=>a+r.min,0))")]
    A.click("#acctBtn"); A.wait_for_timeout(200)
    out["panel"] = re.sub(r"\d+\s*(s|sec|min|seconds?|minutes?) ago|just now", "<t>", A.text_content("#acctPanel").strip().replace("\n", " "))[:140]
    A.evaluate("()=>CLOUD.signOut()"); A.wait_for_timeout(300)
    A.evaluate('()=>{ window.__nextUser={uid:"u2",email:"other@example.com"}; }')
    A.click("#acctBtn"); A.wait_for_timeout(1600)
    out["switch_account"] = [A.evaluate(TOT), A.evaluate('()=>store.get("owner")'), len(env.dialogs) > 0]
    return out

@check("sync.failure_paths")
def _(env):
    out = {}
    pg = env.page()                                   # Firebase can't load
    out["cdn_blocked"] = pg.text_content("#acctBtn").strip()
    pg.click("#acctBtn"); pg.wait_for_timeout(700)
    out["cdn_blocked_click"] = [pg.text_content("#acctBtn").strip(), pg.is_hidden("#acctPanel")]
    srv = Server(); pg = env.page(firebase="fake", server=srv); pg.wait_for_timeout(1200)
    pg.evaluate("()=>window.__closePopup=true"); pg.click("#acctBtn"); pg.wait_for_timeout(500)
    out["popup_closed"] = [pg.text_content("#acctBtn").strip(), pg.is_hidden("#acctPanel")]
    pg.evaluate("()=>window.__closePopup=false"); pg.click("#acctBtn"); pg.wait_for_timeout(700)
    pg.evaluate("()=>CLOUD.signOut()"); pg.wait_for_timeout(200)
    out["signed_out"] = pg.text_content("#acctBtn").strip()
    n = len(env.dialogs); pg.click("#acctBtn"); pg.wait_for_timeout(700)
    out["same_account_back"] = [pg.text_content("#acctBtn").strip(), len(env.dialogs) == n]
    return out

@check("sync.embedded_preview")
def _(env):
    if not env.url.startswith("file://"): return "skipped (needs a local file)"
    frame = pathlib.Path(tempfile.mkdtemp()) / "frame.html"
    frame.write_text(f'<iframe src="{env.url}" width="1200" height="800"></iframe>')
    pg = env.page(url=frame.as_uri()); pg.wait_for_timeout(800)
    f = pg.frames[1]
    return {"account_chip": f.query_selector("#acctBtn") is not None, "export_button": f.query_selector("#dataExport") is not None,
            "tabs": f.evaluate("()=>TABS.length")}


# ---------------------------------------------------------------- runner
def collect(browser, url, outdir, only=None):
    res = {}
    for name, fn in CHECKS:
        if only and not any(name.startswith(o) for o in only): continue
        env = Env(browser, url, outdir); t = time.time()
        try:
            v = fn(env); err = env.errors[:]
            res[name] = {"value": v, "errors": err, "secs": round(time.time() - t, 1)}
        except Exception as e:
            res[name] = {"value": None, "errors": env.errors + [f"exception: {e.__class__.__name__}: {str(e).splitlines()[0][:300]}"],
                         "trace": traceback.format_exc()[-1500:], "secs": round(time.time() - t, 1)}
        finally:
            env.close()
        mark = "FAIL" if res[name]["errors"] else "ok"
        print(f"  {mark:4} {name} ({res[name]['secs']}s)", file=sys.stderr)
    return res

def to_url(p):
    if re.match(r"https?://|file://", p): return p
    return pathlib.Path(p).resolve().as_uri()

def git_file(ref):
    root = HERE.parent
    txt = subprocess.run(["git", "-C", str(root), "show", f"{ref}:index.html"], capture_output=True, text=True, check=True).stdout
    f = pathlib.Path(tempfile.mkdtemp()) / f"index-{ref.replace('/', '_')}.html"; f.write_text(txt); return str(f)

def short(v, n=220):
    s = json.dumps(v, ensure_ascii=False); return s if len(s) <= n else s[:n] + "…"

def diff_lines(a, b, limit=12):
    """Readable diff of two check values: paths whose values differ."""
    out = []
    def walk(x, y, path):
        if len(out) >= limit: return
        if isinstance(x, dict) and isinstance(y, dict):
            for k in sorted(set(x) | set(y), key=str):
                if x.get(k) != y.get(k): walk(x.get(k), y.get(k), f"{path}.{k}")
        elif isinstance(x, list) and isinstance(y, list) and len(x) == len(y) and len(x) > 3:
            for i, (p, q) in enumerate(zip(x, y)):
                if p != q: walk(p, q, f"{path}[{i}]")
        elif isinstance(x, list) and isinstance(y, list) and all(isinstance(z, str) for z in x + y) and len(x) + len(y) > 6:
            for l in difflib.unified_diff(x, y, lineterm="", n=0):
                if not l.startswith(("---", "+++", "@@")): out.append(f"    {path}: {l[:200]}")
        else:
            out.append(f"    {path or '(value)'}:\n      base   {short(x)}\n      target {short(y)}")
    walk(a, b, "")
    return out[:limit]

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("builds", nargs="+", help="[BASE] TARGET: html files or URLs")
    ap.add_argument("--base-ref", help="git ref whose index.html is the base (e.g. v1.1)")
    ap.add_argument("--allow", action="append", default=[], help="check name allowed to differ (repeatable)")
    ap.add_argument("--only", action="append", help="run only checks starting with this prefix")
    ap.add_argument("--out", default=str(HERE / "out"), help="where results.json and screenshots go")
    a = ap.parse_args()
    builds = a.builds[:]
    if a.base_ref: builds = [git_file(a.base_ref)] + builds
    if len(builds) > 2: ap.error("give at most a base and a target")
    out = pathlib.Path(a.out); out.mkdir(parents=True, exist_ok=True)
    labels = ["base", "target"] if len(builds) == 2 else ["target"]
    results = {}
    with sync_playwright() as p:
        br = p.chromium.launch(args=["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream", "--autoplay-policy=no-user-gesture-required"])
        for lab, b in zip(labels, builds):
            print(f"\n{lab}: {b}", file=sys.stderr)
            shots = out / lab; shots.mkdir(exist_ok=True)
            results[lab] = collect(br, to_url(b), shots, a.only)
        br.close()
    (out / "results.json").write_text(json.dumps({"builds": dict(zip(labels, builds)), "results": results}, indent=1, ensure_ascii=False))

    bad = 0; rows = []
    T = results["target"]; B = results.get("base")
    for name, _ in CHECKS:
        if name not in T: continue
        t = T[name]
        if t["errors"]:
            bad += 1; rows.append(("FAIL", name, ["    " + e[:300] for e in t["errors"][:6]])); continue
        if B is None: rows.append(("ok", name, [])); continue
        b = B.get(name, {"value": "n/a", "errors": []})
        bv, tv = b["value"], t["value"]
        if isinstance(bv, dict) and "_lines" in bv:
            same = bv["sha"] == tv["sha"]; detail = [] if same else diff_lines(bv["_lines"], tv["_lines"])
        else:
            same = bv == tv; detail = [] if same else diff_lines(bv, tv)
        if b["errors"]: rows.append(("fixed", name, ["    base: " + e[:200] for e in b["errors"][:3]] + detail))
        elif same: rows.append(("same", name, []))
        elif bv == "n/a" or b["errors"] and bv is None: rows.append(("new", name, []))
        elif name in a.allow: rows.append(("allowed", name, detail))
        else: bad += 1; rows.append(("DIFF", name, detail))
    print()
    for st, name, detail in rows:
        print(f"{st:8} {name}")
        for d in detail: print(d)
    counts = {}
    for st, *_ in rows: counts[st] = counts.get(st, 0) + 1
    print("\n" + ", ".join(f"{v} {k}" for k, v in counts.items()) + f"  ->  {'PASS' if not bad else 'NEEDS A LOOK'}")
    print(f"details: {out / 'results.json'}  screenshots: {out}/<base|target>/")
    sys.exit(1 if bad else 0)

if __name__ == "__main__":
    main()
