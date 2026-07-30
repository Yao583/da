/*
 * _static/global/ai_detect.js
 *
 * Passive instrumentation for AI-assistance detection. Loaded once by every page
 * that extends _templates/global/Page.html.
 *
 * Contract with ai_detect.py:
 *   - one hidden input inside oTree's #form
 *   - name = 'ai_tel_' + <PageClassName>.toLowerCase(), derived from the oTree URL
 *     /p/<code>/<app>/<PageName>/<page_index>
 *   - value = compact JSON; oTree ignores it unless the page lists that exact
 *     name in form_fields
 *
 * These are SOFT research flags. Nothing here blocks, redirects, or repays anyone.
 * The hard-block honeypot path in survey/ is separate and untouched.
 */
(function () {
    'use strict';

    var SCHEMA = 1;
    var FLUSH_MS = 1000;      // periodic serialise interval
    var JUMP_MIN = 20;        // chars added in one input event = "jump"
    var COPY_SAMPLE = 160;    // chars of copied text retained
    var MAX_BLOB = 6000;      // hard cap on the POSTed payload
    var CAP = 100000;         // hard cap on any single counter

    var form = document.getElementById('form');
    if (!form) { return; }

    // ---- identity: /p/<code>/<app>/<PageName>/<page_index> -------------------
    var seg = window.location.pathname.split('/');
    var clean = [];
    for (var i = 0; i < seg.length; i++) { if (seg[i]) { clean.push(seg[i]); } }
    var appName  = clean.length >= 3 ? clean[2] : '';
    var pageName = clean.length >= 4 ? clean[3] : 'page';
    var FIELD = 'ai_tel_' + pageName.toLowerCase();
    var SKEY  = 'aitel:' + window.location.pathname;   // survives reload / re-render

    // Reuse an existing input if one is ever added to a template; else create it.
    var input = form.querySelector('[name="' + FIELD + '"]');
    if (!input) {
        input = document.createElement('input');
        input.type = 'hidden';
        input.name = FIELD;
        input.id = 'id_' + FIELD;
        input.value = '';
        form.appendChild(input);
    }

    // ---- state --------------------------------------------------------------
    function blank() {
        return {
            v: SCHEMA, page: pageName, app: appName,
            t_first: Date.now(), loads: 0, ms: 0,
            blur: 0, hid: 0, hid_ms: 0, hid_max: 0, hid_t1: -1,
            copy: 0, cut: 0, paste: 0, copy_ch: 0, paste_ch: 0, copy_s: '',
            sel_max: 0, ctx: 0,
            keys: 0, ime: 0, jumps: 0, jump_max: 0, ttfk: -1,
            k_t0: 0, k_t1: 0, comp_ms: 0,
            mouse: 0, scroll: 0, touch: 0, click: 0,
            f: {}, env: {}
        };
    }

    var S = null;
    try {
        var saved = window.sessionStorage.getItem(SKEY);
        if (saved) { S = JSON.parse(saved); }
    } catch (e) { S = null; }
    if (!S || S.v !== SCHEMA) { S = blank(); }
    S.loads = (S.loads || 0) + 1;

    var hiddenSince = 0;
    var lastPasteAt = 0;
    var dirtyFlag = false;

    function bump(k, n) { if (S[k] < CAP) { S[k] += n; } }
    function dirty() { dirtyFlag = true; }

    // ---- environment fingerprint (once) -------------------------------------
    try {
        var nav = navigator;
        S.env = {
            wd:   nav.webdriver ? 1 : 0,
            hl:   /headless|phantom|electron|puppeteer|playwright|selenium/i
                      .test(nav.userAgent || '') ? 1 : 0,
            langs: (nav.languages || []).length,
            lang:  nav.language || '',
            plug:  (nav.plugins || []).length,
            hc:    nav.hardwareConcurrency || 0,
            mem:   nav.deviceMemory || 0,
            touchp: nav.maxTouchPoints || 0,
            scr:   (screen.width || 0) + 'x' + (screen.height || 0),
            vp:    (window.innerWidth || 0) + 'x' + (window.innerHeight || 0),
            dpr:   window.devicePixelRatio || 1,
            tzo:   new Date().getTimezoneOffset(),
            tz:    ''
        };
        S.env.tz = Intl.DateTimeFormat().resolvedOptions().timeZone || '';
    } catch (e2) { /* best-effort */ }

    // ---- helpers ------------------------------------------------------------
    function throttle(fn, ms) {
        var last = 0;
        return function () {
            var n = Date.now();
            if (n - last >= ms) { last = n; fn(); }
        };
    }

    function isTextField(el) {
        if (!el || !el.tagName) { return false; }
        var tag = el.tagName.toUpperCase();
        if (tag === 'TEXTAREA') { return true; }
        if (tag !== 'INPUT') { return false; }
        var ty = (el.type || 'text').toLowerCase();
        return ty === 'text' || ty === 'number' || ty === 'search' ||
               ty === 'email' || ty === 'tel' || ty === 'url';
    }

    function rec(el) {
        var name = el.name || el.id || 'anon';
        if (!S.f[name]) {
            S.f[name] = { k: 0, ime: 0, len: 0, ttfk: -1, ms: 0,
                          jmax: 0, jumps: 0, paste: 0, t0: 0, t1: 0 };
        }
        return S.f[name];
    }

    // Seed known lengths so a server re-render (validation error repopulates the
    // textarea) is not mistaken for a giant paste.
    function seedLengths() {
        var els = document.querySelectorAll('input, textarea');
        for (var i = 0; i < els.length; i++) {
            if (isTextField(els[i])) {
                els[i].__aiLen = (els[i].value || '').length;
                rec(els[i]).len = els[i].__aiLen;
            }
        }
    }

    // ---- clipboard and selection --------------------------------------------
    function onCopy(kind) {
        var txt = '';
        try { txt = String(window.getSelection ? window.getSelection() : ''); }
        catch (e) { txt = ''; }
        bump(kind, 1);
        bump('copy_ch', txt.length);
        if (!S.copy_s && txt) { S.copy_s = txt.slice(0, COPY_SAMPLE); }
        dirty();
    }
    document.addEventListener('copy', function () { onCopy('copy'); }, true);
    document.addEventListener('cut',  function () { onCopy('cut');  }, true);

    document.addEventListener('paste', function (e) {
        var txt = '';
        try {
            var cd = e.clipboardData || window.clipboardData;
            txt = (cd && cd.getData('text')) || '';
        } catch (err) { txt = ''; }
        bump('paste', 1);
        bump('paste_ch', txt.length);
        lastPasteAt = Date.now();
        if (isTextField(e.target)) { rec(e.target).paste += 1; }
        dirty();
    }, true);

    document.addEventListener('selectionchange', throttle(function () {
        var n = 0;
        try { n = String(window.getSelection()).length; } catch (e) { n = 0; }
        if (n > S.sel_max) { S.sel_max = n; dirty(); }
    }, 250));

    document.addEventListener('contextmenu', function () { bump('ctx', 1); dirty(); }, true);

    // ---- focus / visibility ledger ------------------------------------------
    function closeHidden() {
        if (hiddenSince) {
            var dt = Date.now() - hiddenSince;
            hiddenSince = 0;
            bump('hid_ms', dt);
            if (dt > S.hid_max) { S.hid_max = dt; }
        }
    }

    window.addEventListener('blur', function () { bump('blur', 1); dirty(); });

    document.addEventListener('visibilitychange', function () {
        if (document.hidden) {
            hiddenSince = Date.now();
            bump('hid', 1);
            if (S.hid_t1 < 0) { S.hid_t1 = Date.now() - S.t_first; }
            flush(true);                 // persist before the tab is frozen
        } else {
            closeHidden();
            dirty();
        }
    });

    window.addEventListener('pagehide',     function () { closeHidden(); flush(true); });
    window.addEventListener('beforeunload', function () { closeHidden(); flush(true); });

    // ---- typing dynamics ----------------------------------------------------
    document.addEventListener('keydown', function (e) {
        if (!isTextField(e.target)) { return; }
        var now = Date.now();
        var r = rec(e.target);
        // isComposing / keyCode 229 = IME or mobile swipe-typing. Counted
        // separately so those participants can be excluded from the ratio test.
        if (e.isComposing || e.keyCode === 229) { bump('ime', 1); r.ime += 1; }
        bump('keys', 1);
        r.k += 1;
        if (!S.k_t0) { S.k_t0 = now; }
        S.k_t1 = now;
        if (S.ttfk < 0) { S.ttfk = now - S.t_first; }
        if (!r.t0) { r.t0 = now; r.ttfk = now - S.t_first; }
        r.t1 = now;
        dirty();
    }, true);

    // ---- paste-like insertions ----------------------------------------------
    document.addEventListener('input', function (e) {
        var el = e.target;
        if (!isTextField(el)) { return; }
        var cur  = (el.value || '').length;
        var prev = (typeof el.__aiLen === 'number') ? el.__aiLen : 0;
        el.__aiLen = cur;
        var delta = cur - prev;
        var r = rec(el);
        r.len = cur;
        if (delta >= JUMP_MIN) {
            // A jump with no paste event just before it = middle-click paste,
            // drag-and-drop, autofill, or a programmatic value assignment.
            if (Date.now() - lastPasteAt >= 200) { bump('jumps', 1); r.jumps += 1; }
            if (delta > S.jump_max) { S.jump_max = delta; }
            if (delta > r.jmax)     { r.jmax = delta; }
        }
        dirty();
    }, true);

    // ---- human presence -----------------------------------------------------
    var passive = { passive: true, capture: true };
    window.addEventListener('mousemove',
        throttle(function () { bump('mouse', 1);  dirty(); }, 200), passive);
    window.addEventListener('scroll',
        throttle(function () { bump('scroll', 1); dirty(); }, 200), passive);
    window.addEventListener('touchstart',
        function () { bump('touch', 1); dirty(); }, passive);
    window.addEventListener('click',
        function () { bump('click', 1); dirty(); }, passive);

    // ---- live word counter (UX only; the server is authoritative) ------------
    (function wordCounter() {
        var minWords = 0;
        try {
            if (typeof js_vars !== 'undefined' && js_vars && js_vars.min_advice_words) {
                minWords = js_vars.min_advice_words;
            }
        } catch (e) { minWords = 0; }
        var ta = document.getElementById('id_intergenerational_advice');
        if (!minWords || !ta) { return; }

        var out = document.createElement('div');
        out.id = 'ai-wordcount';
        out.className = 'form-text';
        out.style.marginTop = '4px';
        ta.parentNode.insertBefore(out, ta.nextSibling);

        // Same rule as ai_detect.word_count(): runs of non-whitespace.
        function count(v) { return ((v || '').match(/\S+/g) || []).length; }
        function paint() {
            var n = count(ta.value);
            out.textContent = n + ' / ' + minWords + ' words';
            out.className = 'form-text ' + (n >= minWords ? 'text-success' : 'text-danger');
        }
        ta.addEventListener('input', paint);
        paint();
    })();

    // ---- flush --------------------------------------------------------------
    function flush(force) {
        if (!force && !dirtyFlag) { return; }
        dirtyFlag = false;
        try {
            S.ms = Date.now() - S.t_first;
            S.comp_ms = (S.k_t0 && S.k_t1) ? (S.k_t1 - S.k_t0) : 0;
            for (var k in S.f) {
                if (Object.prototype.hasOwnProperty.call(S.f, k)) {
                    var r = S.f[k];
                    r.ms = (r.t0 && r.t1) ? (r.t1 - r.t0) : 0;
                }
            }
            var json = JSON.stringify(S);
            if (json.length > MAX_BLOB) {
                json = JSON.stringify({ v: SCHEMA, page: pageName, err: 'oversize',
                                        n: json.length });
            }
            input.value = json;
            try { window.sessionStorage.setItem(SKEY, json); } catch (e) { /* quota */ }
        } catch (e) {
            input.value = '{"v":' + SCHEMA + ',"err":"flush"}';
        }
    }

    seedLengths();
    flush(true);                                   // value exists from t=0
    setInterval(function () { flush(false); }, FLUSH_MS);

    // requestSubmit() and real button clicks fire 'submit' (capture => we run first).
    form.addEventListener('submit', function () { closeHidden(); flush(true); }, true);

    // The quiz-fail path calls form.submit() directly, which fires NO submit event.
    try {
        var nativeSubmit = HTMLFormElement.prototype.submit;
        HTMLFormElement.prototype.submit = function () {
            try { if (this === form) { closeHidden(); flush(true); } } catch (e) { /* noop */ }
            return nativeSubmit.apply(this, arguments);
        };
    } catch (e) { /* the 1s interval is the fallback */ }
})();
