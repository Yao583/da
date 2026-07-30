"""
ai_detect.py -- passive AI-usage instrumentation, server side.

Top-level module (same pattern as allocation.py): the oTree project root is on
sys.path, so every app does a bare `import ai_detect`.

SCOPE
-----
Everything here is a SOFT RESEARCH FLAG for post-hoc exclusion. Nothing here
blocks a participant, changes their page flow, or changes their payment. The
existing hard-block path (survey honeypot -> participant.vars['suspected_bot']
-> BotBlocked -> Prolific bot-redirect) is deliberately separate and is NOT
wired to any signal in this module. Do not connect them: a participant who
alt-tabs to check their email, or who drafts their answer in Notes and pastes
it, would otherwise be ejected for nothing.

DATA FLOW
---------
    _static/global/ai_detect.js
      -> hidden input  ai_tel_<pagename>
      -> Player.ai_tel_<pagename>  (per app, per round)
      -> record()             -> participant.vars['ai_*']  (All-apps wide CSV)
      -> mirror_to_player()   -> survey.Player.ai_*        (survey app CSV)
"""

import json

SCHEMA_VERSION = 1

# Minimum words for survey.Player.intergenerational_advice.
MIN_ADVICE_WORDS = 50
ADVICE_FIELD = 'intergenerational_advice'

# The browser is untrusted input.
MAX_BLOB_CHARS = 8000

# ---------------------------------------------------------------------------
# Flag thresholds. All tunable; record whatever you use in the codebook, and
# prefer re-scoring from the raw columns in your analysis script over trusting
# ai_score, which is only a triage aid.
# ---------------------------------------------------------------------------
T_HIDDEN_MS = 30_000      # >=30s of tab-hidden time summed over the study
T_HIDDEN_ONE_MS = 60_000  # a single absence of >=60s
T_BLUR = 3                # >=3 window blurs
T_COPY_CHARS = 200        # >=200 chars copied out of the page
T_SELECT_CHARS = 1500     # a selection this large ~= "select all the instructions"
T_PASTE_CHARS = 100       # >=100 chars pasted in
T_JUMP_CHARS = 40         # one input event inserted >=40 chars
T_KEY_RATIO = 0.5         # keydowns per final character on the free-text answer
T_ADVICE_LEN = 100        # only apply the ratio test to answers at least this long

_SUM_KEYS = ('blur', 'hid', 'hid_ms', 'copy', 'cut', 'copy_ch', 'paste',
             'paste_ch', 'ctx', 'keys', 'ime', 'jumps',
             'mouse', 'scroll', 'touch', 'click')
_MAX_KEYS = ('hid_max', 'jump_max', 'sel_max', 'loads')


# ---------------------------------------------------------------------------
# word counting -- ONE rule, used by the server check and mirrored by the live
# counter in ai_detect.js, so the number the participant sees and the server's
# verdict always agree.
#   Python: len(text.split())               splits on runs of Unicode whitespace
#   JS:     (v.match(/\S+/g) || []).length   same
# ---------------------------------------------------------------------------
def word_count(text):
    return len((text or '').split())


def advice_error(text):
    """Return an error string for Demographics.error_message, or None."""
    text = (text or '').strip()
    if not text:
        return None          # blank=False already produces a field-level error
    n = word_count(text)
    if n < MIN_ADVICE_WORDS:
        return (
            f"Please write at least {MIN_ADVICE_WORDS} words. "
            f"Your answer currently has {n} word{'' if n == 1 else 's'}. "
            "Tell us what you would recommend to a future participant, and how "
            "you felt about the experiment."
        )
    return None


# ---------------------------------------------------------------------------
# parsing
# ---------------------------------------------------------------------------
def _num(d, key, default=0):
    v = d.get(key, default)
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, (int, float)):
        return v
    return default


def parse(blob):
    """Browser blob -> dict. Never raises, never trusts."""
    if not blob:
        return {}
    if len(blob) > MAX_BLOB_CHARS:
        return {'err': 'oversize', 'raw_len': len(blob)}
    try:
        d = json.loads(blob)
    except Exception:
        return {'err': 'unparseable', 'raw_len': len(blob)}
    if not isinstance(d, dict):
        return {'err': 'not_a_dict'}
    return d


def _compact(d):
    """Trim one page's blob down to what belongs in the exported ledger."""
    if not d:
        return {'err': 'empty'}
    if d.get('err'):
        return {'err': d['err']}
    keep = ('ms', 'loads', 'blur', 'hid', 'hid_ms', 'hid_max', 'hid_t1',
            'copy', 'cut', 'paste', 'copy_ch', 'paste_ch', 'sel_max', 'ctx',
            'keys', 'ime', 'jumps', 'jump_max', 'ttfk', 'comp_ms',
            'mouse', 'scroll', 'touch', 'click')
    return {k: _num(d, k) for k in keep if k in d}


# ---------------------------------------------------------------------------
# accumulation
# ---------------------------------------------------------------------------
def record(player, page_label, blob):
    """Fold one page's telemetry into participant.vars. Call from before_next_page.

    page_label   e.g. 'da/InstructionsQuiz' or 'da/Decision/3'
    """
    pv = player.participant.vars
    d = parse(blob)

    pages = pv.get('ai_pages') or {}
    pages[page_label] = _compact(d)
    pv['ai_pages'] = pages
    pv['ai_pages_instrumented'] = _num(pv, 'ai_pages_instrumented') + 1

    if not d or d.get('err'):
        pv['ai_bad_blobs'] = _num(pv, 'ai_bad_blobs') + 1
        _rescore(pv)
        return

    for k in _SUM_KEYS:
        pv['ai_' + k] = _num(pv, 'ai_' + k) + _num(d, k)
    for k in _MAX_KEYS:
        pv['ai_' + k] = max(_num(pv, 'ai_' + k), _num(d, k))

    if not pv.get('ai_copy_sample') and d.get('copy_s'):
        pv['ai_copy_sample'] = str(d['copy_s'])[:160]

    env = d.get('env')
    if isinstance(env, dict) and env:
        pv['ai_env'] = env
        if _num(env, 'wd') or _num(env, 'hl'):
            pv['ai_webdriver'] = True

    if (_num(d, 'mouse') + _num(d, 'touch') +
            _num(d, 'scroll') + _num(d, 'click')) == 0:
        pv['ai_no_pointer_pages'] = _num(pv, 'ai_no_pointer_pages') + 1

    # --- per-field typing dynamics for the free-text answer ---
    fields = d.get('f') if isinstance(d.get('f'), dict) else {}
    f = fields.get(ADVICE_FIELD)
    if isinstance(f, dict):
        length = _num(f, 'len')
        keys = _num(f, 'k')
        pv['ai_advice_len'] = length
        pv['ai_advice_keys'] = keys
        pv['ai_advice_ratio'] = round(keys / length, 3) if length else None
        pv['ai_advice_ttfk'] = _num(f, 'ttfk')
        pv['ai_advice_ms'] = _num(f, 'ms')
        pv['ai_advice_jump_max'] = _num(f, 'jmax')
        pv['ai_advice_ime'] = _num(f, 'ime')
        pv['ai_advice_pastes'] = _num(f, 'paste')

    _rescore(pv)


def _rescore(pv):
    """Recompute the flag set. Additive, transparent, deliberately not a model."""
    flags = []
    if _num(pv, 'ai_hid_ms') >= T_HIDDEN_MS or _num(pv, 'ai_blur') >= T_BLUR:
        flags.append('tab_switch')
    if _num(pv, 'ai_hid_max') >= T_HIDDEN_ONE_MS:
        flags.append('long_absence')
    if _num(pv, 'ai_copy_ch') >= T_COPY_CHARS or _num(pv, 'ai_cut') > 0:
        flags.append('copied_out')
    if _num(pv, 'ai_sel_max') >= T_SELECT_CHARS:
        flags.append('large_selection')
    if _num(pv, 'ai_paste_ch') >= T_PASTE_CHARS:
        flags.append('pasted_in')
    if _num(pv, 'ai_jump_max') >= T_JUMP_CHARS:
        flags.append('paste_like_insert')

    ratio = pv.get('ai_advice_ratio')
    if (_num(pv, 'ai_advice_len') >= T_ADVICE_LEN
            and isinstance(ratio, (int, float)) and ratio < T_KEY_RATIO):
        flags.append('low_keystroke_ratio')

    pointer = _num(pv, 'ai_mouse') + _num(pv, 'ai_touch') + _num(pv, 'ai_scroll')
    if _num(pv, 'ai_pages_instrumented') >= 3 and pointer == 0:
        flags.append('no_pointer_activity')

    if pv.get('ai_webdriver'):
        flags.append('automation_fingerprint')

    pv['ai_flags'] = ','.join(flags)
    pv['ai_score'] = len(flags)


# ---------------------------------------------------------------------------
# export mirror
# ---------------------------------------------------------------------------
def mirror_to_player(player):
    """Copy the participant-level summary onto survey.Player.

    participant.vars only reaches the "All apps" wide CSV (via PARTICIPANT_FIELDS);
    this mirror also puts the numbers in the survey app's own CSV and in the admin
    Data tab. Safe to call more than once.
    """
    pv = player.participant.vars
    ratio = pv.get('ai_advice_ratio')
    player.ai_score = int(_num(pv, 'ai_score'))
    player.ai_flags = str(pv.get('ai_flags') or '')[:255]
    player.ai_blur_count = int(_num(pv, 'ai_blur'))
    player.ai_hidden_seconds = int(_num(pv, 'ai_hid_ms') // 1000)
    player.ai_hidden_max_seconds = int(_num(pv, 'ai_hid_max') // 1000)
    player.ai_copy_count = int(_num(pv, 'ai_copy') + _num(pv, 'ai_cut'))
    player.ai_copy_chars = int(_num(pv, 'ai_copy_ch'))
    player.ai_paste_count = int(_num(pv, 'ai_paste'))
    player.ai_paste_chars = int(_num(pv, 'ai_paste_ch'))
    player.ai_max_jump_chars = int(_num(pv, 'ai_jump_max'))
    player.ai_max_selection_chars = int(_num(pv, 'ai_sel_max'))
    player.ai_pointer_events = int(
        _num(pv, 'ai_mouse') + _num(pv, 'ai_scroll') + _num(pv, 'ai_touch')
    )
    player.ai_advice_words = word_count(getattr(player, ADVICE_FIELD, '') or '')
    player.ai_advice_chars = int(_num(pv, 'ai_advice_len'))
    player.ai_advice_keys = int(_num(pv, 'ai_advice_keys'))
    player.ai_advice_key_ratio = float(ratio) if isinstance(ratio, (int, float)) else 0.0
    player.ai_advice_ttfk_ms = int(_num(pv, 'ai_advice_ttfk'))
    player.ai_advice_compose_ms = int(_num(pv, 'ai_advice_ms'))
    player.ai_advice_ime_keys = int(_num(pv, 'ai_advice_ime'))
    player.ai_webdriver = bool(pv.get('ai_webdriver'))
    player.ai_pages_instrumented = int(_num(pv, 'ai_pages_instrumented'))
