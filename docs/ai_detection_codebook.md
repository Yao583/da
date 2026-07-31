---
title: "AI-Usage Detection: Codebook and Interpretation Guide"
subtitle: "DA matching experiment (oTree) — IRB-44866"
date: "July 31, 2026"
---

# 1. What this measures

Participants recruited online may use ChatGPT or a similar assistant to play the
experiment. Because the study is about how *people* reason about matching
mechanisms, an AI-generated ranking is noise presented as data.

The instrumentation records passive browser behaviour on the instructions,
decision, and survey pages, and converts it into a set of **soft research flags**
for post-hoc exclusion.

Nothing in this system blocks a participant, alters their page flow, or changes
their payment. It is deliberately kept separate from the pre-existing honeypot
path (`suspected_bot` --> `BotBlocked` --> Prolific redirect), which remains the only
hard block in the study.

**These signals are not grounds for rejecting a Prolific submission.** They are
analysis-time exclusion flags only.

## 1.1 The copy guard (added 31 July 2026)

`_static/global/copy_guard.js` cancels the clipboard on the two task pages,
`Decision` and `InstructionsQuiz`, in all four treatment apps. Copy, cut,
drag-out and the right-click menu are cancelled outside form fields; a brief
toast tells the participant why. Paste is **not** blocked, printing is **not**
blocked, and no other page is affected — `Consent`, `Demographics`, `ThankYou`
and the router behave exactly as before.

This is friction, not prevention. A screenshot, a phone camera, reader mode or
retyping all defeat it (see *What it cannot see*). Its value is as much
measurement as deterrence: a copy is no longer a silent act but a recorded,
deliberate, failed attempt.

**Consequences for the data, in one line each:**

- On guarded pages `ai_copy`, `ai_cut` and `ai_copy_ch` count **attempts**, not
  successes. No copy ever completes there.
- `ai_env['guard']` is `1` on guarded pages, `0` elsewhere. Use it to separate
  pre-guard pilot rows from post-guard rows — the columns are not comparable
  across that boundary.
- `ai_copy_ch` inflates under the guard: a participant re-trying `Ctrl+C` on the
  same 800-character selection adds 800 each time. Prefer the `ai_copy` count and
  treat `ai_copy_ch` as an upper bound.
- `ai_copy_sample` is unaffected and still shows *what* they tried to take —
  `getSelection()` does not care that the copy was cancelled.
- Selection is deliberately left working. Suppressing it with `user-select: none`
  would stop the copy event from firing at all and take `ai_copy`, `ai_copy_ch`,
  `ai_sel_max` and `ai_copy_sample` down with it.

## What it cannot see

No browser instrumentation can detect any of the following. Treat every number in
this codebook as a **lower bound** on AI use.

- A phone beside the laptop. A participant reading the instructions off the screen
  and typing into a chatbot on their phone shows a perfectly normal keystroke
  ratio and no clipboard activity. This is the residual threat.
- Native OS screenshots (`Cmd+Shift+4`, `Win+Shift+S`) — the keystrokes never
  reach the page.
- A second monitor, or the contents of any other tab or window.
- Clipboard contents absent a paste into our page.

# 2. Where the data lives

| Location | Contents |
|:--|:--|
| Admin --> Data --> **"All apps" wide CSV** | `participant.ai_*` — accumulated totals plus `ai_pages`, the per-page ledger |
| **survey** app CSV, admin Data tab | `survey.1.player.ai_*` — the same summary, mirrored for convenience |
| Each treatment app's CSV | `ai_tel_*` — the raw JSON blob per page, for re-deriving anything |
| Admin --> Data --> **Page times** | oTree's built-in per-page dwell time (not duplicated here) |

**Schema versions.** Every blob carries `v`, and the highest seen per
participant is exported as `ai_schema` (mirrored as `ai_schema`). Schema 1 has no
revision or interval fields; schema 2 (from 31 July 2026) adds them.

A v1 row reads as zero on every schema-2 column, which is indistinguishable from
a genuine zero — a v1 participant has "no backspaces" in exactly the way a
perfect transcriber does. The two schema-2 flags are therefore gated on
`ai_schema >= 2` in code, so re-scoring old data cannot manufacture flags. The
raw columns carry no such protection: **filter on `ai_schema` before pooling
pilot and main-wave data.**

Instrumented pages: `InstructionsQuiz` and all five `Decision` rounds in each of
the four treatment apps, plus `survey/Demographics` — seven pages per participant.
Consent, the router, and the terminal pages are deliberately not instrumented.

# 3. Field reference

## 3.1 Summary fields

| Field | Meaning |
|:--|:--|
| `ai_score` | Count of flags fired (0–11). A triage aid, **not** a severity measure |
| `ai_flags` | Comma-separated flag names |
| `ai_schema` | Highest telemetry schema seen. **Filter on this before pooling waves** |
| `ai_pages_instrumented` | Pages that reported telemetry; normally 7 |
| `ai_bad_blobs` | Pages whose payload was missing or unparseable |
| `ai_pages` | Per-page ledger (JSON). Where the sequencing evidence lives |

## 3.2 Attention and presence

| Field | Mirror name | Meaning |
|:--|:--|:--|
| `ai_blur` | `ai_blur_count` | Window blur events (focus left the browser window) |
| `ai_hid` | — | Times the tab became hidden |
| `ai_hid_ms` | `ai_hidden_seconds` | Total time the tab was hidden |
| `ai_hid_max` | `ai_hidden_max_seconds` | Longest single absence |
| `ai_mouse`, `ai_scroll`, `ai_touch`, `ai_click` | `ai_pointer_events` | Throttled activity counts |
| `ai_loads` | — | Page loads, including reloads and validation re-renders |

## 3.3 Clipboard

| Field | Mirror name | Meaning |
|:--|:--|:--|
| `ai_copy`, `ai_cut` | `ai_copy_count` | Copy / cut events. On `Decision` and `InstructionsQuiz` these are **blocked attempts** — see §1.1 |
| `ai_copy_ch` | `ai_copy_chars` | Characters copied out, or attempted. Inflated by repeat attempts under the guard |
| `ai_copy_sample` | — | First 160 characters copied *or attempted*. **Inspect this directly** |
| `ai_paste` | `ai_paste_count` | Paste events |
| `ai_paste_ch` | `ai_paste_chars` | Characters pasted in |
| `ai_sel_max` | `ai_max_selection_chars` | Largest text selection observed |
| `ai_jump_max` | `ai_max_jump_chars` | Largest single-event insertion with no preceding paste event |

## 3.4 Typing dynamics on the free-text answer

| Field | Mirror name | Meaning |
|:--|:--|:--|
| `ai_advice_len` | `ai_advice_chars` | Final character count |
| `ai_advice_keys` | `ai_advice_keys` | Keydowns in that field, **including** revision keys |
| `ai_advice_ratio` | `ai_advice_key_ratio` | Keydowns / characters. Confounded by revision — prefer the productive ratio below |
| `ai_advice_prod_ratio` | `ai_advice_prod_ratio` | `(keys - backspace - delete) / characters`. **The deconfounded ratio; use this one** |
| `ai_advice_ttfk` | `ai_advice_ttfk_ms` | Time to first keystroke |
| `ai_advice_ms` | `ai_advice_compose_ms` | Span from first to last keystroke |
| `ai_advice_ime` | `ai_advice_ime_keys` | IME / mobile swipe-typing keys. **Confound control — see §6** |
| — | `ai_advice_words` | Word count of the submitted answer |

## 3.4a Revisions (schema 2)

Backspaces used to be invisible: they were counted inside `ai_advice_keys` and
nowhere else. They are now separate, which matters because revision *raises* the
old key ratio and therefore pushed genuine typists away from the very flag meant
to catch pasting.

| Field | Mirror name | Meaning |
|:--|:--|:--|
| `ai_advice_bksp` | `ai_advice_backspaces` | Backspace keydowns in the advice field |
| `ai_advice_del` | `ai_advice_deletes` | Delete keydowns |
| `ai_advice_bksp_rate` | `ai_advice_bksp_rate` | Backspaces per final character. **Feeds `no_revision`** |
| `ai_advice_mid` | `ai_advice_midtext_keys` | Keydowns with the caret *not* at the end of the text |
| `ai_advice_mid_ep` | `ai_advice_midtext_episodes` | Separate occasions of going back to edit. More interpretable than `mid` |
| `ai_bksp`, `ai_del`, `ai_mid_ep` | `ai_typing_*` | The same three, totalled across every text field in the study |

Mid-text editing is detected from the caret position at keydown. A selection
being replaced counts as mid-text. `input type="number"` throws on
`selectionStart` in Chrome, so number fields (`age`, the numeric quiz answers)
always read as "at the end" — treat their `mid` as unmeasured, not as zero.

## 3.4b Inter-keystroke intervals (schema 2)

The gap in milliseconds between consecutive keydowns in the same field. Recorded
three ways, cheapest first.

| Field | Mirror name | Meaning |
|:--|:--|:--|
| `ai_advice_iki_hist` | — | 8-bucket histogram of **every** gap |
| `ai_advice_iki_n` | `ai_advice_iki_n` | Gaps used for the mean and SD |
| `ai_advice_iki_mean` | `ai_advice_iki_mean_ms` | Mean gap |
| `ai_advice_iki_sd` | `ai_advice_iki_sd_ms` | SD of the gap |
| `ai_advice_iki_cv` | `ai_advice_iki_cv` | SD / mean. **Feeds `metronomic_typing`** |
| `ai_advice_iki_p10/50/90` | `ai_advice_iki_p*_ms` | Percentiles |
| `ai_advice_iki_exact` | `ai_advice_iki_exact` | 1 = percentiles computed from the raw sequence; 0 = median interpolated from buckets, p10/p90 unavailable and reported as 0 |
| `ai_advice_pauses` | `ai_advice_pauses` | Gaps of 2 s or more — deliberation pauses |
| `ai_advice_iki_min/max` | — | Extremes |
| `ai_advice_iki_raw` | — | The raw sequence. See below |
| `ai_advice_iki_trunc` | — | 1 = the raw sequence hit the 1200-sample cap |

**Histogram buckets**, upper edges in ms — identical constants in
`ai_detect.js` and `ai_detect.py`:

```
[0,50) [50,100) [100,200) [200,400) [400,800) [800,1600) [1600,3200) [3200,inf)
```

**Mean and SD are computed only over gaps below 5000 ms.** A single bathroom
break would otherwise swamp 1500 genuine intervals. Every gap still appears in
the histogram, in `pauses`, and in `iki_max`. The SD is exact, not
bucket-approximated: the browser ships count, sum and sum-of-squares.

**Decoding `ai_advice_iki_raw`:** comma-separated base36 integers,
milliseconds, clamped at 9999, capped at 1200 samples, textareas only.

```python
gaps = [int(t, 36) for t in raw.split(',') if t]     # or ai_detect.decode_raw(raw)
```

If a page's blob would exceed the 24000-character cap, the raw sequences are
dropped first and `rdrop: 1` is set on that page in `ai_pages`; all counters,
histograms and moments survive. A dropped page shows `ai_advice_iki_exact = 0`.

## 3.5 Environment

| Field | Meaning |
|:--|:--|
| `ai_webdriver` | `navigator.webdriver` set, or a headless user-agent |
| `ai_env` | Raw fingerprint: languages, plugins, cores, screen, viewport, timezone |
| `ai_env['guard']` | `1` if the copy guard was armed on that page, `0` if not. **Required to interpret the clipboard columns — see §1.1** |
| `ai_no_pointer_pages` | Pages with zero pointer activity of any kind |

# 4. Flag definitions

Thresholds are the `T_*` constants in `ai_detect.py`. They are **first guesses,
not empirical** — see §7.

| Flag | Condition |
|:--|:--|
| `tab_switch` | `ai_hid_ms >= 30000` or `ai_blur >= 3` |
| `long_absence` | `ai_hid_max >= 60000` |
| `copied_out` | `ai_copy_ch >= 200` or `ai_cut > 0`. Name kept for continuity; post-guard it reads "attempted to copy out" |
| `large_selection` | `ai_sel_max >= 1500` |
| `pasted_in` | `ai_paste_ch >= 100` |
| `paste_like_insert` | `ai_jump_max >= 40` |
| `low_keystroke_ratio` | `ai_advice_len >= 100` and ratio `< 0.5` |
| `no_revision` | `ai_advice_len >= 100` and `ai_advice_bksp_rate < 0.02`, **and** `ai_schema >= 2`, **and** `ai_advice_ime <= 5` |
| `metronomic_typing` | `ai_advice_iki_n >= 50` and `0 < ai_advice_iki_cv < 0.35`, **and** `ai_schema >= 2`, **and** `ai_advice_ime <= 5` |
| `no_pointer_activity` | 3+ pages instrumented and zero mouse/touch/scroll |
| `automation_fingerprint` | `ai_webdriver` true |

`ai_score` is the count of flags above and now ranges **0-11**, not 0-9. Any
pilot analysis that hard-coded the old maximum needs updating — which is another
reason §5.1 says not to threshold on it.

The two schema-2 flags carry an IME gate **in code**, where the older flags
leave the same confound to prose in §6. This is deliberate, not an
inconsistency: swipe typing and autocorrect suppress backspaces and regularise
cadence simultaneously, so without the gate these two would substantially be
Android detectors rather than AI detectors.

# 5. Interpretation

## 5.1 The first rule: do not threshold on `ai_score`

`ai_score` is an unweighted count of flags that differ enormously in
diagnosticity. A participant who alt-tabbed three times scores 1; so does one
running a scripted browser. **Always work from the underlying columns.**

## 5.2 Flags tiered by precision

**Tier 1 — high precision. These justify action.**

- `copied_out` — text was copied, or on the guarded task pages *attempted to be
  copied*, out of the page. On an instructions page there is almost no legitimate
  reason to do this. Check `ai_copy_sample`: if it contains your instruction text,
  that is about as direct as browser evidence gets. Post-guard this flag gets
  *stronger*, not weaker: an accidental Ctrl+C no longer counts for much, but a
  participant who keeps retrying after being told copying is disabled has
  demonstrated intent.
- `large_selection` — a select-all of the instructions. Usually co-occurs with
  `copied_out`. A large `ai_sel_max` with `ai_copy` of 0 suggests copying through
  an extension or share sheet that does not fire the event.
- `automation_fingerprint` — a scripted browser, not a human. Rare but decisive.
- `no_pointer_activity` — zero mouse, scroll, and touch across the entire study.
  A human cannot produce this.

**Tier 2 — moderate. Requires corroboration.**

- `pasted_in`, `paste_like_insert`, `low_keystroke_ratio` — these three almost
  always fire together on a pasted free-text answer. They fire *identically* for a
  conscientious participant who drafted in Notes and pasted. The discriminator is
  whether the same participant also copied text **out** earlier (see §5.3).
- `no_revision`, `metronomic_typing` — the transcription signature: text typed by
  hand, but not composed by hand. These are the counterpart to the paste flags now
  that the copy guard pushes participants toward retyping, and they fire on cases
  the paste flags cannot see. **Treat as Tier 2 until you have calibrated them on
  your own pilot distributions** — the thresholds (0.02 and 0.35) are first
  guesses, and a fast, accurate touch-typist writing a short answer in one go can
  trip `no_revision` innocently. They earn Tier 1 only when they co-occur.
- `long_absence` — a single absence of a minute or more.

**Tier 3 — covariate only. Never an exclusion criterion on its own.**

- `tab_switch` — by far the noisiest signal. Excluding on this alone would drop
  30–50% of a normal online sample. Everyone checks email, the recruitment tab, or
  a message mid-study.

## 5.3 Look for the sequence, not the flag

Individual flags are weak. The AI workflow leaves a distinctive signature, visible
in the `ai_pages` ledger:

> **copy on `*/InstructionsQuiz` --> long hidden interval on that same page -->
> paste on `survey/Demographics`**

Text leaves the page, time passes off-page, text arrives back. This closed loop is
worth considerably more than any single flag. A participant who merely pasted
their own draft will not show the copy-out leg.

Since the copy guard, the first leg is an *attempted* copy — the text never
actually left. The sequence is still diagnostic, and arguably more so, but expect
the loop to close less often: a participant blocked at the first step may retype
the instructions by hand, in which case only the hidden-interval and paste legs
survive. Watch for `copied_out` **without** a later `pasted_in` as the new
guarded-page signature.

## 5.4 Reading the keystroke ratio

`ai_advice_key_ratio` = keydowns / final characters.

| Ratio | Interpretation |
|:--|:--|
| 0.9 – 1.4 | Genuine typing. Above 1.0 is normal: shift, backspace, and arrow keys all register as keydowns |
| 0.3 – 0.7 | Paste followed by substantial editing |
| below 0.1 | Effectively a pure paste |

Reference values from instrumented test runs: a simulated typist produced **1.13**
(340 keydowns, 300 characters); a simulated paste produced **0.014** (6 keydowns,
420 characters).

The flag threshold of 0.5 is deliberately generous. Genuine typists rarely fall
below 0.7.

**Use `ai_advice_prod_ratio` instead where you can.** The raw ratio is
confounded: backspaces and arrow keys are keydowns, so the more someone revises,
the higher their ratio climbs and the further they sit from the flag. Two people
with a ratio of 1.13 can be a careful reviser and a flawless transcriber. The
productive ratio removes backspace and delete and should sit near 1.0 for genuine
typing regardless of revision style; the revision itself is then measured
separately by `ai_advice_bksp_rate` and `ai_advice_midtext_episodes`.

## 5.5 Reading the interval distribution

The single most useful number is the **coefficient of variation**,
`ai_advice_iki_cv` = SD / mean.

| CV | Interpretation |
|:--|:--|
| 0.8 – 2.5 | Normal composition. Fast within words, slow at word and clause boundaries, occasional long thinking pauses |
| 0.4 – 0.8 | Steady, practised typing. Common in fluent touch-typists writing something they have already decided |
| below 0.35 | Implausibly even. Keystrokes not driven by composition — transcription, or a script |

Corroborate with shape, not just CV:

- **Genuine composition** is right-skewed with a long tail: a spike in the
  100-200 ms buckets, a real tail past 1600 ms, and `ai_advice_pauses` greater
  than zero. Thinking leaves gaps.
- **Transcription from another window** concentrates in one or two adjacent
  buckets with almost nothing past 800 ms, and near-zero pauses. The participant
  is reading and copying, not deciding.
- **A script** puts nearly everything in a single bucket and often has
  `iki_min` equal to `iki_max`.

`ai_advice_pauses` is worth checking on its own. A 250-word answer written with
**zero** pauses of two seconds or more is unusual for genuine composition, no
matter what the CV says.

Where `ai_advice_iki_exact = 1`, the percentiles come from the retained raw
sequence and are exact; the p90/p50 ratio is a good burstiness measure. Where it
is 0, only the interpolated median exists and it is coarse — the buckets span an
octave.

# 6. Confounds and false positives

Every item below is real and observed in practice. They are the reason these flags
must remain soft.

- **Legitimate tab switching.** The dominant confound. Treat as a covariate.
- **Drafting elsewhere, then pasting.** Trips `pasted_in`, `paste_like_insert`,
  and `low_keystroke_ratio` simultaneously — an innocent participant can look
  maximally guilty on the free-text measures. Corroborate with copy-out.
- **Mobile swipe typing and autocorrect.** Inserts many characters per input event
  and reports `keyCode 229`. **Always exclude participants with high
  `ai_advice_ime_keys` from the keystroke-ratio test**, or the flag will
  principally identify Android users. The same confound hits the schema-2
  measures even harder — autocorrect fixes errors *without* a Backspace, so a
  mobile typist can show a backspace rate near zero while revising constantly,
  and swipe input produces its own artificial cadence. `no_revision` and
  `metronomic_typing` therefore carry the IME gate in code; the ratio test still
  does not, so apply it yourself.
- **Fast, accurate touch-typists.** A practised typist composing a short answer in
  one pass genuinely produces few backspaces and a fairly even rhythm. This is the
  main innocent explanation for `no_revision`, and the reason it is Tier 2.
- **External keyboards and key repeat.** Holding Backspace to delete a word emits
  a burst of repeat keydowns a few tens of milliseconds apart, inflating both the
  backspace count and the lowest histogram bucket. Check `ai_advice_iki_hist[0]`
  before reading a very low CV as suspicious.
- **Browser autofill and password managers.** Produce large insertions on the
  demographic fields, unrelated to AI.
- **iOS Safari.** Fires blur and visibility events for the share sheet, the
  keyboard, and app backgrounding — inflated blur counts on mobile.
- **Privacy browsers** (Brave, Firefox with resistFingerprinting). Report one
  language and no plugins. This is *not* automation; only `navigator.webdriver`
  and a headless user-agent feed `automation_fingerprint`, and even `webdriver` is
  occasionally set by managed corporate browsers.

## 6.1 The base-rate problem

Before excluding anyone, work through the arithmetic. Suppose 5% of the sample
uses AI, and a flag is 90% sensitive and 90% specific:

- True positives: 0.05 x 0.90 = **4.5%** of the sample
- False positives: 0.95 x 0.10 = **9.5%** of the sample

Positive predictive value is 4.5 / (4.5 + 9.5), or about **32%**. **Roughly
two-thirds of flagged participants are innocent.** At realistic prevalence, only
Tier 1 flags survive this calculation.

# 7. Recommended analysis workflow

1. **Report primary results on the full sample.** Do not build exclusions into the
   main specification.
2. **Add a robustness column** excluding only high-confidence cases: `copied_out`
   *and* `pasted_in` together, or `automation_fingerprint`, or
   `no_pointer_activity`.
3. **Report how far the estimates move.** If they barely move, you have shown that
   contamination is not driving the findings — a stronger claim than presenting a
   sample that merely looks clean.
4. Consider `ai_hidden_seconds` as a continuous covariate rather than a cutoff.
5. Never exclude on `tab_switch` alone.

## 7.1 Calibrate before trusting any threshold

The `T_*` constants were set a priori. After the first pilot batch, plot the
distributions of `ai_hid_ms`, `ai_copy_ch`, and `ai_advice_key_ratio`. Genuine AI
users typically appear as a visibly **separate mode** rather than a tail. Place
cutoffs at the gap, then record the values you used in this codebook so the
exclusion rule is reproducible.

# 8. Ethics and policy

- Participants see a visible request not to use AI on the instructions page and
  above the free-text survey question. There is no covert trap, no hidden prompt,
  and no deception in the detection system.
- The copy guard is likewise overt: a blocked attempt produces a visible toast
  ("Copying is disabled in this study"), so no one is left thinking their browser
  is broken. It restricts one interaction on two pages; it does not restrict
  progress, completion, or payment, and consent text remains fully copyable.
- The consent form was not modified for this instrumentation. If interaction
  logging is not covered by the approved protocol, consider an amendment.
- `ai_copy_sample` stores up to 160 characters of copied text. In practice this is
  your own page text, but it should be noted in the data-management plan.
- These signals must not be used to reject Prolific submissions, and must not be
  wired into `suspected_bot`, `blocked_for_bot`, or the bot-redirect path.

# 9. Implementation reference

| File | Role |
|:--|:--|
| `ai_detect.py` | Server side: parsing, accumulation, flag scoring, word-count rule, export mirror |
| `_static/global/ai_detect.js` | Client instrumentation; writes one hidden field per page |
| `_static/global/copy_guard.js` | Cancels the clipboard on the pages in its `GUARDED_PAGES` array. Edit that array to change coverage |
| `_templates/global/Page.html` | Loads both scripts, guard first. Bump the `?v=` on either `<script>` after editing it |
| `settings.py` | `PARTICIPANT_FIELDS` entries that make the data exportable |

A related control: the free-text advice question enforces a **50-word minimum**,
validated server-side in `Demographics.error_message`. The live word counter shown
to participants is a hint only and never blocks; the server is authoritative.
