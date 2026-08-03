---
title: "AI-Usage Detection: Codebook and Interpretation Guide"
subtitle: "DA matching experiment (oTree) — IRB-44866"
date: "August 3, 2026"
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
toast tells the participant why. Printing is **not** blocked, and no other page
is affected — `Consent`, `ThankYou` and the router behave exactly as before.
Paste was originally left open here too; it is now cancelled separately and on a
wider set of pages, by the paste guard — see §1.2.

This is friction, not prevention. A screenshot, a phone camera, reader mode or
retyping all defeat it (see *What it cannot see*). Its value is as much
measurement as deterrence: a copy is no longer a silent act but a recorded,
deliberate, failed attempt.

**Consequences for the data, in one line each:**

- On guarded pages `ai_copy`, `ai_cut` and `ai_copy_ch` count **attempts**, not
  successes. No copy ever completes there.
- `ai_env['guard']` is set per page, but **the exported value is not usable as a
  wave marker** — `ai_env` is overwritten by each page and the last one is always
  Demographics, where the copy guard does not arm, so it reads `0` for everyone.
  See the warning in §3.5. Separate the waves on the *presence* of
  `ai_env['pguard']` instead, and infer per-page copy-guard state from the page
  name. The columns are not comparable across that boundary.
- `ai_copy_ch` inflates under the guard: a participant re-trying `Ctrl+C` on the
  same 800-character selection adds 800 each time. Prefer the `ai_copy` count and
  treat `ai_copy_ch` as an upper bound.
- `ai_copy_sample` is unaffected and still shows *what* they tried to take —
  `getSelection()` does not care that the copy was cancelled.
- Selection is deliberately left working. Suppressing it with `user-select: none`
  would stop the copy event from firing at all and take `ai_copy`, `ai_copy_ch`,
  `ai_sel_max` and `ai_copy_sample` down with it.

## 1.2 The paste guard (added 3 August 2026)

`_static/global/paste_guard.js` is the return leg of the copy guard. Where the
copy guard makes it expensive to take the instructions **out** to a chatbot, this
makes it expensive to bring an answer back **in**.

It cancels `paste`, `drop`, and the `insertFromPaste` / `insertFromDrop` input
types, which between them cover `Ctrl`/`Cmd`+`V`, right-click → Paste, the
browser menu bar, the mobile long-press Paste bubble, middle-click paste on
Linux, and dragging selected text into a field. The same toast tells the
participant why.

Two differences from the copy guard, both deliberate:

- **It has no page allowlist.** The copy guard names its pages because the
  Prolific completion code and the consent text must stay copyable; nothing
  analogous applies to paste. The pages that load the script *are* the scope:
  `survey/Demographics` plus `Decision` and `InstructionsQuiz` in all four
  treatment apps.
- **It targets form fields rather than exempting them.** The copy guard leaves
  fields alone because copying your own typed text is legitimate. A field is the
  only place a paste does anything, so there is nothing here to exempt.

Participants are **told**, in the text directly above the free-text answer on
`survey/Demographics`: *"Pasting is disabled on this page — please type your
answer directly into the box below."* This matters for interpretation. A paste
attempt into the advice box is not a participant discovering a broken browser; it
is a deliberate act against a stated rule.

**Consequences for the data, in one line each:**

- `ai_paste` and `ai_paste_ch` now count **attempts**, not successes. No paste
  ever completes on an instrumented page.
- `ai_env['pguard']` is `1` under the guard. Pilot rows have no `pguard` key at
  all, so `'pguard' in ai_env` is the wave discriminator — and unlike `guard` it
  actually survives to the export, because the paste guard arms on Demographics.
  Pilot and post-guard rows are **not poolable** on any paste column.
- `ai_paste_ch` inflates on retries exactly as `ai_copy_ch` does. Prefer the
  `ai_paste` count.
- A drag-and-drop feeds `ai_paste` and `ai_paste_ch` too — it is a paste that
  arrived by another route. `ai_drop` records how many of the arrivals were
  drags. This keeps `pasted_in` and its 100-character threshold covering both
  routes with no change to the flag logic, and leaves pilot scores untouched
  (`ai_drop` reads as 0 there).
- No clipboard *content* is captured on the paste side. There is no paste-side
  counterpart to `ai_copy_sample`; the decision was counts only.
- `ai_drop` reaches the All-apps wide CSV only. It has no `survey.Player` mirror
  column, so that adding it required **no DB migration** — the guard ships onto a
  running study without an `otree resetdb`.

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

Instrumented pages: within whichever **one** treatment app the router assigned,
`InstructionsQuiz` plus all five `Decision` rounds; then `survey/Demographics`.
Seven pages per participant, which is what `ai_pages_instrumented` should read
for anyone who finished. Consent, the router, and the terminal pages are
deliberately not instrumented. The export contains `da`/`boston`/`agent_da`/
`agent_boston` rows for participants who never played them — filter on
`participant.treatment`.

Page labels in `ai_pages` are `<app>/InstructionsQuiz` and
`<app>/Decision/<round>`, plus the literal `survey/Demographics`.

**What each ledger entry contains.** `_compact()` keeps a fixed subset of the
blob: `ms`, `loads`, `blur`, `hid`, `hid_ms`, `hid_max`, `hid_t1`, `copy`, `cut`,
`paste`, `drop`, `copy_ch`, `paste_ch`, `sel_max`, `ctx`, `keys`, `ime`, `jumps`,
`jump_max`, `ttfk`, `comp_ms`, `mouse`, `scroll`, `touch`, `click`, `bksp`,
`del`, `mid`, `mid_ep`, `pause`, the IKI moments, and `iki_h`. Deliberately
**not** kept: the raw interval sequences (they would make the wide-CSV cell
unreadable) and `env` (see the §3.5 warning). A page whose blob was missing or
unparseable appears as `{"err": ...}` and increments `ai_bad_blobs`. `hid_t1` —
milliseconds from page load to the first time the tab was hidden — is the field
that makes the §5.3 sequencing argument checkable, and it exists **only** here.
The complete, uncompacted blob is always available in the app's own
`ai_tel_*` column.

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
| `ai_mouse`, `ai_scroll` | part of `ai_pointer_events` | Throttled at 200 ms, so these are "periods with movement", not raw event counts |
| `ai_touch` | part of `ai_pointer_events` | `touchstart`, not throttled |
| `ai_click` | — | Clicks. **Not** included in `ai_pointer_events` — see the warning below |
| `ai_loads` | — | Page loads, including reloads and validation re-renders |

> **Three different definitions of "pointer activity" exist in the code.** They
> are easy to confuse and they disagree:
>
> - `ai_pointer_events` (the mirror column) = `ai_mouse + ai_scroll + ai_touch`. **No clicks.**
> - the `no_pointer_activity` **flag** = the same three, also **no clicks**.
> - `ai_no_pointer_pages` (a per-page tally) = mouse + scroll + touch **+ click**.
>
> So a participant who only ever clicked — plausible for a keyboard-driven or
> assistive-technology user — can score `no_pointer_activity` while
> `ai_no_pointer_pages` is 0. If the two disagree, check `ai_click` directly
> before treating the flag as evidence of automation.

## 3.3 Clipboard

| Field | Mirror name | Meaning |
|:--|:--|:--|
| `ai_copy`, `ai_cut` | `ai_copy_count` | Copy / cut events. On `Decision` and `InstructionsQuiz` these are **blocked attempts** — see §1.1 |
| `ai_copy_ch` | `ai_copy_chars` | Characters copied out, or attempted. Inflated by repeat attempts under the guard |
| `ai_copy_sample` | — | First 160 characters copied *or attempted*. **Inspect this directly.** First-write-wins: the first non-empty copy of the whole study, not the largest or the most recent |
| `ai_ctx` | — | Right-click menu openings. Cancelled outside form fields on the copy-guarded pages, still counted |
| `ai_paste` | `ai_paste_count` | Paste events. On every instrumented page these are **blocked attempts**, and they include drag-and-drop arrivals — see §1.2 |
| `ai_paste_ch` | `ai_paste_chars` | Characters pasted in, or attempted. Inflated by repeat attempts under the guard |
| `ai_drop` | — | How many of the above arrived by drag-and-drop rather than the clipboard. Blocked, counted as an attempt |
| `ai_sel_max` | `ai_max_selection_chars` | Largest text selection observed. Sampled from `selectionchange`, throttled at 250 ms |
| `ai_jumps` | — | Count of large insertions **not** attributable to a paste event — see below |
| `ai_jump_max` | `ai_max_jump_chars` | Largest single insertion in one `input` event, in characters |

**How jumps are counted, precisely** — the two fields differ and the difference
matters, because `paste_like_insert` keys off `ai_jump_max`:

- An `input` event that grows the field by **20 or more characters** is a jump.
  Smaller insertions are never recorded at all, so `ai_jump_max` is either 0 or
  at least 20.
- `ai_jump_max` records the size of **every** such insertion, including one that
  a `paste` event just caused.
- `ai_jumps` (the count) additionally requires that **no paste event fired in the
  previous 200 ms**. That is the "arrived by some other route" counter:
  middle-click paste, drag-and-drop, autofill, or a script setting `.value`.

Pre-guard, a successful 500-character paste therefore set `ai_jump_max` to 500
and left `ai_jumps` at 0, which made `paste_like_insert` partly redundant with
`pasted_in`. **Post-guard the two separate cleanly**: a cancelled paste inserts
nothing, fires no `input` event, and so cannot move `ai_jump_max` at all. Any
non-zero `ai_jump_max` on a post-guard row means text reached the field by a
route the guard did not close — which makes it one of the sharper columns you
have. Check `ai_env['pguard']` before comparing the two waves on it.

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
| `ai_advice_pastes` | — | Paste attempts **into the advice box specifically**, drags included. The most targeted paste column there is: study-wide `ai_paste` also counts attempts on the quiz and age fields |
| `ai_advice_jump_max` | — | Largest single insertion into the advice box. The per-field counterpart to `ai_jump_max` |
| — | `ai_advice_words` | Word count of the submitted answer |

Every column in this section and in §3.4a/§3.4b is **assigned, not accumulated** —
they are read off the one `survey/Demographics` blob rather than summed across
pages, unlike the study-wide totals in §3.2/§3.3. A participant who never reached
Demographics (screened out, quiz-fail, honeypot) has none of them, and they read
as 0 rather than as missing.

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
| `ai_bksp`, `ai_del`, `ai_mid_ep` | `ai_typing_backspaces`, `ai_typing_deletes`, `ai_typing_midtext_episodes` | The same three, totalled across every text field in the study |
| `ai_mid` | — | Study-wide mid-text keydowns. No mirror column; wide CSV only |

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

## 3.4c Study-wide typing totals

Everything above is the advice box alone. The same measures are also summed
across **every** text field on **every** instrumented page — the quiz number
inputs and `age` as well as the two textareas. These have no mirror columns and
appear only in the All-apps wide CSV.

| Field | Meaning |
|:--|:--|
| `ai_keys` | Keydowns in text fields, study-wide. Includes revision keys |
| `ai_ime` | IME / swipe keydowns, study-wide. The study-wide swipe indicator |
| `ai_pause` | Gaps of 2 s or more, study-wide |
| `ai_iki_hist` | 8-bucket interval histogram, study-wide, same edges as above |
| `ai_iki_n`, `ai_iki_sum`, `ai_iki_sq` | Count, sum, and sum-of-squares of the gaps below 5000 ms |
| `ai_iki_min`, `ai_iki_max` | Extremes. `ai_iki_min` is the minimum over **non-zero** values, since 0 encodes "no data" |

`ai_iki_sum` and `ai_iki_sq` are raw moments, not summary statistics — they are
stored that way so that pooling across pages gives an **exact** SD rather than an
average of per-page averages. Recover the statistics yourself:

```python
mean = ai_iki_sum / ai_iki_n
sd   = math.sqrt(max(ai_iki_sq / ai_iki_n - mean**2, 0))   # or ai_detect._mean_sd()
```

These totals are dominated by the advice box in practice — it is the only field
where anyone types more than a few characters — so treat them as a robustness
check on the `ai_advice_*` versions rather than as independent evidence.

## 3.5 Environment

| Field | Meaning |
|:--|:--|
| `ai_webdriver` | `navigator.webdriver` set, or a headless user-agent |
| `ai_env` | Raw fingerprint: languages, plugins, cores, screen, viewport, timezone. **Last-write-wins — see below** |
| `ai_env['guard']` | Whether the copy guard was armed. **Not usable as written — see below** |
| `ai_env['pguard']` | Whether the paste guard was armed. Use its **presence**, not its value, as the wave marker — see below |
| `ai_no_pointer_pages` | Pages with zero mouse, scroll, touch **and** click |

> **`ai_env` is overwritten by every page, so it holds only the last one.**
> `record()` assigns `pv['ai_env'] = env` rather than merging, and
> `survey/Demographics` is the last instrumented page every participant sees.
> The exported `ai_env` is therefore always Demographics' fingerprint.
>
> The practical consequences:
>
> - **`ai_env['guard']` reads `0` for every completed participant**, because the
>   copy guard does not arm on Demographics. It cannot tell you what regime the
>   *task* pages were under, and it is not the pre/post-guard wave marker that
>   §1.1 originally claimed. To recover per-page guard state, use the page name:
>   `Decision` and `InstructionsQuiz` are copy-guarded, nothing else is.
> - **`ai_env['pguard']` works, but only by presence.** It reads `1` for every
>   post-guard participant (the paste guard *does* arm on Demographics) and the
>   key is absent entirely on pilot rows, so `'pguard' in ai_env` is a reliable
>   wave discriminator. Its *value* is likewise uninformative about other pages.
> - The browser fingerprint fields (`scr`, `tz`, `hc`, …) are stable within a
>   session, so losing the earlier pages costs nothing there. Only the two guard
>   flags are page-dependent, and only they are affected.
>
> Per-page guard state is not preserved anywhere else either: `_compact()` keeps
> the counters for `ai_pages` but not `env`. If you want it in the data rather
> than inferred from page names, add `'env'` to that keep list — an additive
> change that costs one key per page in the ledger.

# 4. Flag definitions

Thresholds are the `T_*` constants in `ai_detect.py`. They are **first guesses,
not empirical** — see §7.

| Flag | Condition |
|:--|:--|
| `tab_switch` | `ai_hid_ms >= 30000` or `ai_blur >= 3` |
| `long_absence` | `ai_hid_max >= 60000` |
| `copied_out` | `ai_copy_ch >= 200` or `ai_cut > 0`. Name kept for continuity; post-guard it reads "attempted to copy out" |
| `large_selection` | `ai_sel_max >= 1500` |
| `pasted_in` | `ai_paste_ch >= 100`. Name kept for continuity; post-guard it reads "attempted to paste in", and covers drag-and-drop |
| `paste_like_insert` | `ai_jump_max >= 40` |
| `low_keystroke_ratio` | `ai_advice_len >= 100` and `ai_advice_ratio < 0.5`. Note it uses the **raw** ratio, not `ai_advice_prod_ratio` — see §5.4 |
| `no_revision` | `ai_advice_len >= 100` and `ai_advice_keys > 0` and `ai_advice_bksp_rate < 0.02`, **and** `ai_schema >= 2`, **and** `ai_advice_ime <= 5` |
| `metronomic_typing` | `ai_advice_iki_n >= 50` and `0 < ai_advice_iki_cv < 0.35`, **and** `ai_schema >= 2`, **and** `ai_advice_ime <= 5` |
| `no_pointer_activity` | 3+ pages instrumented and zero mouse/scroll/touch. **Clicks are not counted** — see §3.2 |
| `automation_fingerprint` | `ai_webdriver` true |

`ai_score` is the count of flags above and now ranges **0-11**, not 0-9. Any
pilot analysis that hard-coded the old maximum needs updating — which is another
reason §5.1 says not to threshold on it.

The two schema-2 flags carry an IME gate **in code**, where the older flags
leave the same confound to prose in §6. This is deliberate, not an
inconsistency: swipe typing and autocorrect suppress backspaces and regularise
cadence simultaneously, so without the gate these two would substantially be
Android detectors rather than AI detectors.

`no_revision` additionally requires `ai_advice_keys > 0`, so a participant who
produced the answer with **no keystrokes at all** does not trip it. That is
correct — the flag is about typing without revising, and someone who never typed
has not done that — but it means the two flags are not redundant: the pure-paste
case is caught by `low_keystroke_ratio` and `paste_like_insert` instead. Check
those before concluding that a clean `no_revision` means a clean row.

**Nothing else in the study reads these flags.** `ai_flags` and `ai_score` are
written to `participant.vars`, mirrored onto `survey.Player`, and exported. No
page branches on them, and they are not wired to `suspected_bot`, payment, or
the bot redirect.

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
actually left. Since the paste guard, the third leg is an *attempted* paste — the
text never actually arrived. Both legs are still diagnostic, and arguably more so,
because each is now a deliberate act against a stated rule rather than an
invisible one.

Expect the loop to close less often, though. A participant blocked at the first
step may retype the instructions by hand; one blocked at the third may retype the
answer. Either way the hidden-interval leg survives, and the residual channels for
text that genuinely lands in the box are `paste_like_insert` and
`low_keystroke_ratio` — neither of which the guards touch. Watch for
`copied_out` and `pasted_in` **without** a completed insertion as the
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
- **Drafting elsewhere, then trying to paste.** Still a real confound, but the
  paste guard has changed its shape. That participant can no longer paste at all:
  they trip `pasted_in` on the *attempt*, then either retype the draft — which
  produces ordinary typing dynamics and clears `paste_like_insert` and
  `low_keystroke_ratio` — or abandon it. So the old signature of all three flags
  firing together no longer arises innocently. `pasted_in` alone, with clean
  typing dynamics after it, is the drafted-elsewhere participant; `pasted_in`
  together with `paste_like_insert` and `low_keystroke_ratio` post-guard means
  text reached the box by a route the guard did not close, which is a stronger
  signal than it was pre-guard. Corroborate with copy-out either way, and check
  `ai_env['pguard']` before pooling with pilot rows.
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
- Both guards are likewise overt: a blocked attempt produces a visible toast
  ("Copying is disabled in this study" / "Pasting is disabled in this study"), so
  no one is left thinking their browser is broken. The paste rule is additionally
  stated in the text above the free-text answer, *before* anyone tries it. They
  restrict two interactions; they do not restrict progress, completion, or
  payment, and consent text remains fully copyable.
- Blocking paste has an accessibility cost worth naming: a participant using
  dictation, a translation tool, or an assistive editor to compose their answer
  elsewhere can no longer transfer it, and must retype. The free-text question is
  a 50-word minimum, so this is friction rather than exclusion, but it is a real
  burden on a minority of participants and should be weighed if the minimum ever
  rises.
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
| `_static/global/paste_guard.js` | Cancels paste and drop on every page that loads it. No allowlist — change coverage by changing which templates extend `global/Page.html` |
| `_templates/global/Page.html` | Loads all three scripts, both guards before `ai_detect.js` (which reads their flags once, at load). Bump the `?v=` on any `<script>` after editing it |
| `settings.py` | `PARTICIPANT_FIELDS` entries that make the data exportable |

A related control: the free-text advice question enforces a **50-word minimum**,
validated server-side in `Demographics.error_message`. The live word counter shown
to participants is a hint only and never blocks; the server is authoritative.
