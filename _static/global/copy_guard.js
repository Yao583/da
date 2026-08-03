/*
 * _static/global/copy_guard.js
 *
 * Clipboard friction for the task pages. Loaded once by every page that extends
 * _templates/global/Page.html, but only ARMS itself on the pages named in
 * GUARDED_PAGES below.
 *
 * WHAT THIS IS
 *   Friction, not prevention. A screenshot, a phone camera, reader mode, "view
 *   source", or simply retyping all defeat it and none of those are blockable
 *   from a web page. The point is to raise the cost above "select all, Ctrl+C,
 *   paste into a chatbot", and to turn a copy from an invisible act into a
 *   recorded, deliberate attempt. ai_detect.js remains the primary instrument.
 *
 * CONTRACT WITH ai_detect.js  (loaded immediately after this file)
 *   - We set window.__aiCopyGuard = 1 so the telemetry can stamp env.guard and
 *     the analysis can tell pre-guard rows (copy = succeeded) from post-guard
 *     rows (copy = attempted, blocked).
 *   - We call preventDefault() and NOTHING else. Never stopPropagation() or
 *     stopImmediatePropagation(): ai_detect.js listens for 'copy'/'cut'/
 *     'contextmenu' in the same capture phase, and stopping propagation would
 *     blind it. preventDefault suppresses the clipboard write while every
 *     listener still fires.
 *   - Selection is deliberately left working. user-select:none would stop the
 *     copy event from firing at all, and copy / copy_ch / sel_max / copy_s
 *     would all go dark.
 */
(function () {
    'use strict';

    // Which oTree page classes are guarded, lowercased. Edit this to change
    // coverage. Consent, Demographics, ThankYou, BotBlocked and the router are
    // left alone on purpose: consent text should stay savable, and the Prolific
    // return page must stay copyable.
    var GUARDED_PAGES = ['decision', 'instructionsquiz'];

    var NOTICE = 'Copying is disabled in this study.';
    var TOAST_MS = 2500;
    var FIELD_SEL = 'input, textarea, select, [contenteditable=""], [contenteditable="true"]';

    // ---- identity: /p/<code>/<app>/<PageName>/<page_index> -------------------
    // Same idiom as ai_detect.js, kept duplicated so the two files stay
    // independent of each other's load order beyond the flag above.
    var seg = window.location.pathname.split('/');
    var clean = [];
    for (var i = 0; i < seg.length; i++) { if (seg[i]) { clean.push(seg[i]); } }
    var pageName = clean.length >= 4 ? clean[3] : 'page';

    if (GUARDED_PAGES.indexOf(pageName.toLowerCase()) < 0) { return; }

    window.__aiCopyGuard = 1;   // read by ai_detect.js when it builds S.env

    // ---- helpers ------------------------------------------------------------
    // True when the event came from somewhere the participant is entering their
    // own answer. Those stay fully functional: copying your own typed text, the
    // right-click menu, and spellcheck are all legitimate.
    function inField(el) {
        try {
            if (!el || typeof el.closest !== 'function') { return false; }
            return !!el.closest(FIELD_SEL);
        } catch (e) {
            return false;
        }
    }

    // ---- toast --------------------------------------------------------------
    // Without visible feedback a participant concludes their browser is broken
    // and emails the researcher. Fixed position so nothing on the page reflows.
    //
    // #guard-toast is SHARED with paste_guard.js. On Decision and
    // InstructionsQuiz both guards are armed, and two separately-id'd toasts
    // would stack on top of each other when a participant tries Ctrl+C then
    // Ctrl+V. Whichever file fires first creates the element; the other reuses
    // it. Both inject the same CSS, so neither depends on the other's load
    // order. Look the element up each time rather than caching it.
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
            el.textContent = NOTICE + ' Please answer using your own judgment.';
            el.className = 'cg-show';
            if (toastTimer) { clearTimeout(toastTimer); }
            toastTimer = setTimeout(function () { el.className = ''; }, TOAST_MS);
        } catch (e) { /* the block itself still worked */ }
    }

    // ---- styles -------------------------------------------------------------
    // Injected from JS so they only ever apply on a guarded page.
    //   -webkit-touch-callout: suppresses the iOS long-press "Copy" bubble.
    //   NOT user-select: see the header note.
    try {
        var css = document.createElement('style');
        css.textContent =
            'body { -webkit-touch-callout: none; }' +
            FIELD_SEL + ' { -webkit-touch-callout: default; }' +
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
    // Overwriting the payload beats a bare preventDefault: a paste into a chatbot
    // then yields the notice rather than whatever was on the clipboard before.
    function blockClipboard(e) {
        if (inField(e.target)) { return; }
        try {
            var cd = e.clipboardData || window.clipboardData;
            if (cd) { cd.setData('text/plain', NOTICE); }
        } catch (err) { /* preventDefault below is the real guarantee */ }
        e.preventDefault();
        toast();
    }

    document.addEventListener('copy', blockClipboard, true);
    document.addEventListener('cut', blockClipboard, true);

    // Drag-selected text straight into another window is the same leak.
    document.addEventListener('dragstart', function (e) {
        if (inField(e.target)) { return; }
        e.preventDefault();
        toast();
    }, true);

    // Removes the right-click "Copy" / "Search with..." path. ai_detect still
    // counts the attempt in ctx.
    document.addEventListener('contextmenu', function (e) {
        if (inField(e.target)) { return; }
        e.preventDefault();
        toast();
    }, true);

    // No keydown interception: cancelling the copy event already covers Ctrl+C,
    // Cmd+C, right-click -> Copy, and the browser's own menu bar.
})();
