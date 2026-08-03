/*
 * _static/global/paste_guard.js
 *
 * Cancels paste into the study's form fields. Loaded by every page that extends
 * _templates/global/Page.html, and unlike copy_guard.js it arms on all of them.
 *
 * WHAT THIS IS
 *   The return leg of the copy guard. copy_guard.js makes it expensive to take
 *   the instructions OUT to a chatbot; this makes it expensive to bring an
 *   answer back IN. Friction, not prevention: retyping the chatbot's output by
 *   hand defeats it completely, and that is fine. The point is that the cheap
 *   path -- Ctrl+V into the free-text answer -- stops working and becomes a
 *   recorded, deliberate, failed attempt instead of a silent success.
 *
 * NOTE THE INVERSION vs copy_guard.js
 *   copy_guard.js EXEMPTS form fields: copying your own typed text is
 *   legitimate. This file TARGETS them. A field is the only place a paste does
 *   anything, so there is nothing here to exempt.
 *
 * NO GUARDED_PAGES LIST
 *   copy_guard.js has to name its pages because the Prolific completion code on
 *   ThankYou and the consent text must stay copyable. Nothing analogous applies
 *   to paste, so the set of pages that load this file IS the scope: Demographics
 *   plus Decision and InstructionsQuiz in the four treatment apps.
 *
 * CONTRACT WITH ai_detect.js  (loaded immediately after this file)
 *   - We set window.__aiPasteGuard = 1 so the telemetry can stamp env.pguard and
 *     the analysis can tell pre-guard rows (paste = succeeded) from post-guard
 *     rows (paste = attempted, blocked). This must happen BEFORE ai_detect.js
 *     runs: it builds S.env once, at load time.
 *   - We call preventDefault() and NOTHING else. Never stopPropagation() or
 *     stopImmediatePropagation(): ai_detect.js listens for 'paste' and 'drop' in
 *     the same capture phase, and stopping propagation would blind it.
 *     preventDefault suppresses the insertion while every listener still fires,
 *     and clipboardData stays readable, so paste / paste_ch keep measuring the
 *     size of the attempt.
 */
(function () {
    'use strict';

    var NOTICE = 'Pasting is disabled in this study. Please type your answer.';
    var TOAST_MS = 2500;

    window.__aiPasteGuard = 1;   // read by ai_detect.js when it builds S.env

    // ---- helpers ------------------------------------------------------------
    // Same field set as ai_detect.js's isTextField(), kept duplicated so the two
    // files stay independent of each other's load order beyond the flag above.
    // Used only to decide whether to TOAST: a bare Ctrl+V with nothing focused
    // is already a no-op, and announcing it would be noise.
    function isTextField(el) {
        if (!el || !el.tagName) { return false; }
        var tag = el.tagName.toUpperCase();
        if (tag === 'TEXTAREA') { return true; }
        if (tag !== 'INPUT') { return false; }
        var ty = (el.type || 'text').toLowerCase();
        return ty === 'text' || ty === 'number' || ty === 'search' ||
               ty === 'email' || ty === 'tel' || ty === 'url';
    }

    // ---- toast --------------------------------------------------------------
    // Shares #guard-toast with copy_guard.js. Both pages that arm both guards
    // would otherwise stack two fixed, bottom-centred toasts on top of each
    // other when a participant tries Ctrl+C then Ctrl+V. Whichever file fires
    // first creates the element; the other reuses it. Both inject the same CSS,
    // so neither depends on the other having loaded.
    var toastTimer = 0;

    function toast() {
        try {
            var el = document.getElementById('guard-toast');
            if (!el) {
                el = document.createElement('div');
                el.id = 'guard-toast';
                el.setAttribute('role', 'status');
                el.setAttribute('aria-live', 'polite');
                document.body.appendChild(el);
            }
            el.textContent = NOTICE;
            el.className = 'cg-show';
            if (toastTimer) { clearTimeout(toastTimer); }
            toastTimer = setTimeout(function () { el.className = ''; }, TOAST_MS);
        } catch (e) { /* the block itself still worked */ }
    }

    // ---- styles -------------------------------------------------------------
    // Toast only. Deliberately no -webkit-touch-callout rule: that is
    // copy_guard.js's business, and suppressing the iOS callout on Demographics
    // would take away the participant's own select/copy/paste bubble on text
    // they typed themselves.
    try {
        var css = document.createElement('style');
        css.textContent =
            '#guard-toast {' +
                'position: fixed; left: 50%; bottom: 24px; transform: translateX(-50%);' +
                'z-index: 2147483647; max-width: 90vw; padding: 10px 16px;' +
                'background: rgba(33,37,41,.94); color: #fff; border-radius: 6px;' +
                'font-size: 14px; line-height: 1.4; text-align: center;' +
                'box-shadow: 0 2px 10px rgba(0,0,0,.3);' +
                'opacity: 0; visibility: hidden; transition: opacity .15s ease;' +
                'pointer-events: none;' +
            '}' +
            '#guard-toast.cg-show { opacity: 1; visibility: visible; }';
        document.head.appendChild(css);
    } catch (e) { /* cosmetic only */ }

    // ---- the block ----------------------------------------------------------
    // Covers Ctrl/Cmd+V, right-click -> Paste, the browser menu bar, the mobile
    // long-press Paste bubble, and middle-click paste on Linux, all of which
    // dispatch a 'paste' event.
    document.addEventListener('paste', function (e) {
        e.preventDefault();
        if (isTextField(e.target)) { toast(); }
    }, true);

    // Dragging selected text into a textarea inserts it without ever firing
    // 'paste'. Same act, different event: ai_detect.js counts it as a drop.
    document.addEventListener('drop', function (e) {
        e.preventDefault();
        if (isTextField(e.target)) { toast(); }
    }, true);

    // Backstop for anything that reaches the field without dispatching either of
    // the above. Not counted anywhere -- the two listeners already recorded the
    // attempt, and counting here as well would double it. The inputType filter
    // is exact on purpose: insertCompositionText (IME) and every ordinary typing
    // inputType must pass through untouched.
    document.addEventListener('beforeinput', function (e) {
        var t = e.inputType;
        if (t === 'insertFromPaste' || t === 'insertFromPasteAsQuotation' ||
                t === 'insertFromDrop') {
            e.preventDefault();
        }
    }, true);
})();
