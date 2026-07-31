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
import math

# 2 adds revision counters (bksp/del/mid) and inter-keystroke interval
# distributions. Blobs carry their own 'v'; v1 rows simply lack the new keys and
# read as 0, so ALWAYS filter on the schema before pooling v1 and v2 data.
SCHEMA_VERSION = 2

# Minimum words for survey.Player.intergenerational_advice.
MIN_ADVICE_WORDS = 50
ADVICE_FIELD = 'intergenerational_advice'

# The browser is untrusted input. Raised for schema 2, which carries the raw
# inter-keystroke sequence for the textareas; the JS caps itself at 24000.
MAX_BLOB_CHARS = 32000

# ---------------------------------------------------------------------------
# Flag thresholds. All tunable; record whatever you use in the codebook, and
# prefer re-scoring from the raw columns in your analysis script over trusting
# ai_score, which is only a triage aid.
# ---------------------------------------------------------------------------
T_HIDDEN_MS = 30_000      # >=30s of tab-hidden time summed over the study
T_HIDDEN_ONE_MS = 60_000  # a single absence of >=60s
T_BLUR = 3                # >=3 window blurs
# NOTE on the copy_* thresholds. _static/global/copy_guard.js cancels the
# clipboard on Decision and InstructionsQuiz, so on those pages copy / cut /
# copy_ch count ATTEMPTED copies, not successful ones. Two consequences:
#   - copy_ch inflates. Re-trying Ctrl+C on the same 800-char selection adds 800
#     every time, so treat copy_ch as an upper bound and prefer the copy count.
#   - copy_sample still shows WHAT they tried to take: getSelection() is
#     unaffected by preventDefault. It is the most diagnostic field here.
# Rows are distinguishable via ai_env['guard'] (1 = guard was armed).
T_COPY_CHARS = 200        # >=200 chars copied, or attempted, out of the page
T_SELECT_CHARS = 1500     # a selection this large ~= "select all the instructions"
T_PASTE_CHARS = 100       # >=100 chars pasted in
T_JUMP_CHARS = 40         # one input event inserted >=40 chars
T_KEY_RATIO = 0.5         # keydowns per final character on the free-text answer
T_ADVICE_LEN = 100        # only apply the ratio test to answers at least this long

# --- schema 2: revision and rhythm ---
T_BKSP_RATE = 0.02        # backspaces per final character; below this = no revision
T_IKI_CV = 0.35           # coefficient of variation of the inter-keystroke interval
T_IKI_MIN_N = 50          # never judge rhythm on a handful of keystrokes
# Mobile swipe typing and autocorrect both suppress backspaces AND regularise
# cadence, so the two schema-2 flags below are gated on this where the older
# flags leave the IME confound to the codebook. The asymmetry is deliberate:
# without the gate, no_revision and metronomic_typing would in large part be
# Android detectors. See the codebook, "Confounds".
T_IME_MAX = 5

# Upper edges of the IKI histogram, in ms. MUST match IKI_EDGES in ai_detect.js.
IKI_EDGES = (50, 100, 200, 400, 800, 1600, 3200)
IKI_BUCKETS = len(IKI_EDGES) + 1

_SUM_KEYS = ('blur', 'hid', 'hid_ms', 'copy', 'cut', 'copy_ch', 'paste',
             'paste_ch', 'ctx', 'keys', 'ime', 'jumps',
             'mouse', 'scroll', 'touch', 'click',
             'bksp', 'del', 'mid', 'mid_ep', 'pause',
             # summing sum and sum-of-squares across pages is what makes the
             # pooled mean and SD exact rather than an average of averages
             'iki_n', 'iki_sum', 'iki_sq')
_MAX_KEYS = ('hid_max', 'jump_max', 'sel_max', 'loads', 'iki_max')
_MIN_KEYS = ('iki_min',)   # 0 means "no data", so the min is over non-zero values


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


def _hist(d, key):
    """Read an IKI histogram out of a blob. Never trusts length or contents."""
    v = d.get(key)
    if not isinstance(v, list):
        return [0] * IKI_BUCKETS
    out = [0] * IKI_BUCKETS
    for i in range(min(len(v), IKI_BUCKETS)):
        n = v[i]
        out[i] = int(n) if isinstance(n, (int, float)) and not isinstance(n, bool) else 0
    return out


def _add_hist(pv, key, add):
    """Element-wise accumulate one page's histogram into participant.vars."""
    cur = pv.get(key)
    if not isinstance(cur, list) or len(cur) != IKI_BUCKETS:
        cur = [0] * IKI_BUCKETS
    pv[key] = [cur[i] + add[i] for i in range(IKI_BUCKETS)]


def decode_raw(s):
    """'3f,2s,45' -> [123, 100, 149]. Base36 ms gaps written by ai_detect.js.

    Bad tokens are skipped rather than raising: this is browser input.
    """
    if not isinstance(s, str) or not s:
        return []
    out = []
    for tok in s.split(','):
        try:
            out.append(int(tok, 36))
        except (ValueError, TypeError):
            continue
    return out


def _pcts(xs, ps=(10, 50, 90)):
    """Exact percentiles by nearest-rank. Returns a dict, empty input -> zeros."""
    if not xs:
        return {p: 0 for p in ps}
    ordered = sorted(xs)
    n = len(ordered)
    out = {}
    for p in ps:
        idx = int(math.ceil(p / 100.0 * n)) - 1
        out[p] = ordered[max(0, min(idx, n - 1))]
    return out


def _hist_median(hist):
    """Bucket-interpolated median, for when the raw sequence is unavailable.

    Coarse by construction -- the buckets span an octave -- so it is only used as
    a fallback and the codebook says so.
    """
    total = sum(hist)
    if not total:
        return 0
    target = total / 2.0
    seen = 0
    for i, n in enumerate(hist):
        if seen + n >= target:
            lo = 0 if i == 0 else IKI_EDGES[i - 1]
            hi = IKI_EDGES[i] if i < len(IKI_EDGES) else lo * 2
            frac = (target - seen) / n if n else 0
            return int(lo + (hi - lo) * frac)
        seen += n
    return int(IKI_EDGES[-1])


def _mean_sd(n, total, sq):
    """Mean and population SD from count / sum / sum-of-squares."""
    if not n:
        return 0.0, 0.0
    mean = total / float(n)
    var = sq / float(n) - mean * mean
    if var < 0:          # floating-point noise on a near-constant series
        var = 0.0
    return mean, math.sqrt(var)


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
            'mouse', 'scroll', 'touch', 'click',
            'bksp', 'del', 'mid', 'mid_ep', 'pause',
            'iki_n', 'iki_sum', 'iki_sq', 'iki_min', 'iki_max')
    out = {k: _num(d, k) for k in keep if k in d}
    # The histogram rides along; the RAW sequence deliberately does not. ai_pages
    # becomes one cell per page in the wide CSV, and the raw series would make it
    # unreadable. It stays in the per-app ai_tel_* column, which holds the full blob.
    if isinstance(d.get('iki_h'), list):
        out['iki_h'] = _hist(d, 'iki_h')
    if _num(d, 'rdrop'):
        out['rdrop'] = 1        # raw was dropped for size; see flush() in the JS
    return out


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

    # Highest schema seen for this participant. The v2 flags are gated on it: a
    # v1 blob simply has no 'bksp' key, which reads as zero backspaces and is
    # indistinguishable from a participant who genuinely never corrected
    # anything. Without this gate, re-scoring pilot data would flag every v1 row
    # as no_revision.
    pv['ai_schema'] = max(_num(pv, 'ai_schema'), _num(d, 'v'))

    for k in _SUM_KEYS:
        pv['ai_' + k] = _num(pv, 'ai_' + k) + _num(d, k)
    for k in _MAX_KEYS:
        pv['ai_' + k] = max(_num(pv, 'ai_' + k), _num(d, k))
    for k in _MIN_KEYS:
        cur, new = _num(pv, 'ai_' + k), _num(d, k)
        pv['ai_' + k] = new if not cur else (min(cur, new) if new else cur)

    _add_hist(pv, 'ai_iki_hist', _hist(d, 'iki_h'))

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

        # --- revisions ---
        bksp = _num(f, 'bksp')
        dele = _num(f, 'del')
        pv['ai_advice_bksp'] = bksp
        pv['ai_advice_del'] = dele
        pv['ai_advice_mid'] = _num(f, 'mid')
        pv['ai_advice_mid_ep'] = _num(f, 'mid_ep')
        pv['ai_advice_bksp_rate'] = round(bksp / length, 4) if length else None
        # The deconfounded ratio: revision keys removed, so a heavy reviser is no
        # longer pushed away from the low-ratio test by the very act of revising.
        pv['ai_advice_prod_ratio'] = (
            round(max(keys - bksp - dele, 0) / length, 3) if length else None
        )

        # --- rhythm ---
        raw = decode_raw(f.get('raw'))
        n_moment = _num(f, 'in_')
        mean, sd = _mean_sd(n_moment, _num(f, 'isum'), _num(f, 'isq'))
        pv['ai_advice_iki_n'] = n_moment
        pv['ai_advice_iki_mean'] = round(mean, 1)
        pv['ai_advice_iki_sd'] = round(sd, 1)
        pv['ai_advice_iki_cv'] = round(sd / mean, 3) if mean else None
        pv['ai_advice_iki_min'] = _num(f, 'imin')
        pv['ai_advice_iki_max'] = _num(f, 'imax')
        pv['ai_advice_pauses'] = _num(f, 'pause')
        hist = _hist(f, 'ih')
        pv['ai_advice_iki_hist'] = hist
        pv['ai_advice_iki_raw'] = f.get('raw') if isinstance(f.get('raw'), str) else ''
        pv['ai_advice_iki_trunc'] = 1 if _num(f, 'rtr') else 0
        if raw:
            # Exact, from the retained sequence.
            p = _pcts(raw)
            pv['ai_advice_iki_p10'] = p[10]
            pv['ai_advice_iki_p50'] = p[50]
            pv['ai_advice_iki_p90'] = p[90]
            pv['ai_advice_iki_exact'] = 1
        else:
            # Fallback: interpolate the median from the buckets. Coarse; p10/p90
            # are not attempted at all rather than reported misleadingly.
            pv['ai_advice_iki_p10'] = 0
            pv['ai_advice_iki_p50'] = _hist_median(hist)
            pv['ai_advice_iki_p90'] = 0
            pv['ai_advice_iki_exact'] = 0

    _rescore(pv)


def _rescore(pv):
    """Recompute the flag set. Additive, transparent, deliberately not a model."""
    flags = []
    if _num(pv, 'ai_hid_ms') >= T_HIDDEN_MS or _num(pv, 'ai_blur') >= T_BLUR:
        flags.append('tab_switch')
    if _num(pv, 'ai_hid_max') >= T_HIDDEN_ONE_MS:
        flags.append('long_absence')
    # Name kept stable so existing analysis scripts keep working. On guarded
    # pages this now reads "attempted to copy out" -- see the T_COPY_CHARS note.
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

    # --- schema 2. Gated on the schema (v1 blobs cannot support these) and on
    # IME (see the note at T_IME_MAX). ---
    v2 = _num(pv, 'ai_schema') >= 2
    swipe = _num(pv, 'ai_advice_ime') > T_IME_MAX

    # Typed a substantial answer and essentially never corrected it. Transcribing
    # from a chatbot window is linear; composing is not.
    bksp_rate = pv.get('ai_advice_bksp_rate')
    if (v2 and not swipe
            and _num(pv, 'ai_advice_len') >= T_ADVICE_LEN
            and _num(pv, 'ai_advice_keys') > 0
            and isinstance(bksp_rate, (int, float)) and bksp_rate < T_BKSP_RATE):
        flags.append('no_revision')

    # Implausibly even cadence. Human typing is bursty -- fast within a word,
    # slow at word and clause boundaries -- so a low coefficient of variation
    # means the keystrokes were not driven by composition.
    cv = pv.get('ai_advice_iki_cv')
    if (v2 and not swipe
            and _num(pv, 'ai_advice_iki_n') >= T_IKI_MIN_N
            and isinstance(cv, (int, float)) and 0 < cv < T_IKI_CV):
        flags.append('metronomic_typing')

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
def _advice_text(player):
    """The advice answer, or '' when the participant never saw Demographics.

    Screened-out arrivals (study full), quiz-fails and honeypot-flagged bots all
    skip Demographics and go straight to ThankYou, which calls mirror_to_player.
    Their advice field is NULL, and oTree raises TypeError on reading a null
    field -- a plain getattr() default does NOT help, because the attribute
    exists and it is the descriptor that raises. Without this, ThankYou returns
    a 500 and those participants cannot reach the Prolific completion link.
    """
    getter = getattr(player, 'field_maybe_none', None)
    if callable(getter):
        try:
            return getter(ADVICE_FIELD) or ''
        except Exception:
            pass
    try:
        return getattr(player, ADVICE_FIELD, '') or ''
    except Exception:
        return ''



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
    player.ai_advice_words = word_count(_advice_text(player))
    player.ai_advice_chars = int(_num(pv, 'ai_advice_len'))
    player.ai_advice_keys = int(_num(pv, 'ai_advice_keys'))
    player.ai_advice_key_ratio = float(ratio) if isinstance(ratio, (int, float)) else 0.0
    player.ai_advice_ttfk_ms = int(_num(pv, 'ai_advice_ttfk'))
    player.ai_advice_compose_ms = int(_num(pv, 'ai_advice_ms'))
    player.ai_advice_ime_keys = int(_num(pv, 'ai_advice_ime'))
    # --- schema 2: revisions and rhythm on the free-text answer ---
    bksp_rate = pv.get('ai_advice_bksp_rate')
    prod = pv.get('ai_advice_prod_ratio')
    cv = pv.get('ai_advice_iki_cv')
    player.ai_advice_backspaces = int(_num(pv, 'ai_advice_bksp'))
    player.ai_advice_deletes = int(_num(pv, 'ai_advice_del'))
    player.ai_advice_bksp_rate = float(bksp_rate) if isinstance(bksp_rate, (int, float)) else 0.0
    player.ai_advice_prod_ratio = float(prod) if isinstance(prod, (int, float)) else 0.0
    player.ai_advice_midtext_keys = int(_num(pv, 'ai_advice_mid'))
    player.ai_advice_midtext_episodes = int(_num(pv, 'ai_advice_mid_ep'))
    player.ai_advice_iki_n = int(_num(pv, 'ai_advice_iki_n'))
    player.ai_advice_iki_mean_ms = float(_num(pv, 'ai_advice_iki_mean'))
    player.ai_advice_iki_sd_ms = float(_num(pv, 'ai_advice_iki_sd'))
    player.ai_advice_iki_cv = float(cv) if isinstance(cv, (int, float)) else 0.0
    player.ai_advice_iki_p10_ms = int(_num(pv, 'ai_advice_iki_p10'))
    player.ai_advice_iki_p50_ms = int(_num(pv, 'ai_advice_iki_p50'))
    player.ai_advice_iki_p90_ms = int(_num(pv, 'ai_advice_iki_p90'))
    player.ai_advice_iki_exact = bool(_num(pv, 'ai_advice_iki_exact'))
    player.ai_advice_pauses = int(_num(pv, 'ai_advice_pauses'))
    player.ai_typing_backspaces = int(_num(pv, 'ai_bksp'))
    player.ai_typing_deletes = int(_num(pv, 'ai_del'))
    player.ai_typing_midtext_episodes = int(_num(pv, 'ai_mid_ep'))
    player.ai_webdriver = bool(pv.get('ai_webdriver'))
    player.ai_pages_instrumented = int(_num(pv, 'ai_pages_instrumented'))
    player.ai_schema = int(_num(pv, 'ai_schema'))
