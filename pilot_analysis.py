"""
pilot_analysis.py -- pilot diagnostics for the DA-only Prolific batch.

    python3 pilot_analysis.py [path/to/all_apps_48.csv]

Reads an oTree "all apps" wide CSV and prints three sections:

    1. Quiz failure and attentiveness
    2. Suspected AI usage, tiered per docs/ai_detection_codebook.md
    3. Truth-telling rate

Nothing here mutates the data. Rerun it on the next batch: the only assumption
about sample size is that `participant.treatment` marks router-assigned arrivals.

A note on denominators, which matter more than any single number below. Three
disjoint groups appear in the file and only the third ever saw a decision screen:

    screened_out   the study was full when they arrived; no quiz, no decisions,
                   and no payment (they are asked to return their Prolific submission)
    abandoned      opened InstructionsQuiz and never submitted it (silent drop)
    submitters     submitted the quiz page, either passing or failing out

`failed_quiz` can only be observed for submitters, so quoting it over the whole
assigned sample understates it and quoting it over submitters ignores the fact
that abandoning IS a failure mode. Both are printed.
"""

import ast
import json
import os
import sys
from collections import Counter

import pandas as pd

# Thresholds, mirrored from ai_detect.py so this script can re-derive the flags
# independently and check them against the stored ai_flags column. If you retune
# them there, retune them here -- the reconciliation check will tell you.
T_HIDDEN_MS = 30_000
T_HIDDEN_ONE_MS = 60_000
T_BLUR = 3
T_COPY_CHARS = 200
T_SELECT_CHARS = 1500
T_PASTE_CHARS = 100
T_JUMP_CHARS = 40
T_KEY_RATIO = 0.5
T_ADVICE_LEN = 100
T_BKSP_RATE = 0.02
T_IKI_CV = 0.35
T_IKI_MIN_N = 50
T_IME_MAX = 5

# docs/ai_detection_codebook.md section 5.2.
TIER1 = ['copied_out', 'large_selection', 'no_pointer_activity', 'automation_fingerprint']
TIER2 = ['pasted_in', 'paste_like_insert', 'low_keystroke_ratio',
         'no_revision', 'metronomic_typing', 'long_absence']
TIER3 = ['tab_switch']

PRIZES = 'ABCDEF'
NR_ROUNDS = 5
QUIZ_SECTIONS = {1: 'Prizes, groups and values (q1-11)',
                 2: 'Prize priorities (q12-16)',
                 3: 'Submitting your ranking (q17-21)',
                 4: 'Allocation process, part 1 (q22-27)',
                 5: 'Allocation process, part 2 (q28-30)'}
MAX_ATTEMPTS = 4          # the 4th wrong attempt terminates; see InstructionsQuiz.html


# --- helpers ---------------------------------------------------------------
def rule(title):
    print('\n' + '=' * 78)
    print(title)
    print('=' * 78)


def sub(title):
    print('\n--- ' + title + ' ' + '-' * max(0, 72 - len(title)))


def pct(n, d):
    return f"{n:>3}/{d:<3} ({100.0 * n / d:5.1f}%)" if d else f"{n:>3}/0   (  n/a)"


def num(series):
    return pd.to_numeric(series, errors='coerce').fillna(0)


def literal(cell):
    """participant.vars dicts export as Python reprs; be forgiving about it."""
    cell = (cell or '').strip()
    if not cell:
        return {}
    try:
        return ast.literal_eval(cell)
    except (ValueError, SyntaxError):
        try:
            return json.loads(cell)
        except ValueError:
            return {}


def flagset(cell):
    return {f for f in (cell or '').split(',') if f}


def quartiles(values):
    s = pd.Series(list(values), dtype='float')
    if s.empty:
        return 'no data'
    return (f"median {s.median():8.1f}   IQR [{s.quantile(.25):.1f}, {s.quantile(.75):.1f}]"
            f"   n={len(s)}")


def truthful_ranking(vals):
    """The unique full ranking implied by a valuation vector (values are distinct)."""
    return ''.join(sorted(PRIZES, key=lambda letter: -vals[PRIZES.index(letter)]))


def kendall_tau(order, reference):
    """Tau-a between two orderings of the same items. +1 identical, -1 reversed."""
    pos = {item: i for i, item in enumerate(reference)}
    seq = [pos[item] for item in order]
    n = len(seq)
    concordant = discordant = 0
    for i in range(n):
        for j in range(i + 1, n):
            if seq[i] < seq[j]:
                concordant += 1
            else:
                discordant += 1
    total = n * (n - 1) / 2
    return (concordant - discordant) / total if total else 0.0


# --- sample ----------------------------------------------------------------
def build_sample(df):
    """Split the export into the disjoint groups described in the module docstring."""
    df = df.copy()
    df['_visited'] = num(df['participant.visited']) == 1
    df['_screened'] = num(df['participant.screened_out']) == 1
    df['_assigned'] = df['participant.treatment'].str.strip() != ''
    df['_failed_quiz'] = num(df['participant.failed_quiz']) == 1
    df['_completed'] = num(df['participant.study_completed']) == 1
    # A finisher submitted a ranking in every round; that is the decision sample.
    df['_finisher'] = True
    for r in range(1, NR_ROUNDS + 1):
        df['_finisher'] &= df[f'da.{r}.player.pref_ranking'].str.strip() != ''
    # Submitted the quiz page at all: instrumentation only lands on submit.
    df['_submitted_quiz'] = num(df['participant.ai_pages_instrumented']) >= 1

    assigned = df[df['_assigned'] & ~df['_screened']].copy()
    assigned['_abandoned'] = ~assigned['_submitted_quiz']

    n_rows, n_novisit = len(df), int((~df['_visited']).sum())
    n_screened, n_assigned = int(df['_screened'].sum()), len(assigned)
    assert n_novisit + n_screened + n_assigned == n_rows, (
        f"disposition does not partition the file: {n_novisit}+{n_screened}"
        f"+{n_assigned} != {n_rows}")

    n_ab = int(assigned['_abandoned'].sum())
    n_fail = int(assigned['_failed_quiz'].sum())
    n_fin = int(assigned['_finisher'].sum())
    assert n_ab + n_fail + n_fin == n_assigned, (
        f"quiz outcomes do not partition the assigned sample: {n_ab}+{n_fail}"
        f"+{n_fin} != {n_assigned}")
    assert not (assigned['_failed_quiz'] & assigned['_finisher']).any(), \
        "a participant is both a quiz-failure and a finisher"
    return df, assigned


def check_round_consistency(finishers):
    """participant.vars stores and the per-round player fields must agree."""
    problems = []
    for _, row in finishers.iterrows():
        vals = literal(row['participant.market_vals'])
        ranks = literal(row['participant.market_ranking'])
        code = row['participant.code']
        if len(vals) != NR_ROUNDS or len(ranks) != NR_ROUNDS:
            problems.append(f"{code}: {len(vals)} valuation rounds, {len(ranks)} ranking rounds")
            continue
        for r in range(1, NR_ROUNDS + 1):
            mirror_v = literal(row[f'da.{r}.player.valuations'])
            mirror_r = row[f'da.{r}.player.pref_ranking'].strip().upper()
            if list(vals[str(r)]) != list(mirror_v):
                problems.append(f"{code} r{r}: valuations {vals[str(r)]} != mirror {mirror_v}")
            if ranks[str(r)].strip().upper() != mirror_r:
                problems.append(f"{code} r{r}: ranking {ranks[str(r)]!r} != mirror {mirror_r!r}")
    return problems


# --- section 1 -------------------------------------------------------------
def section_quiz(assigned):
    rule('1. QUIZ FAILURE AND ATTENTIVENESS')

    n = len(assigned)
    n_ab = int(assigned['_abandoned'].sum())
    n_fail = int(assigned['_failed_quiz'].sum())
    n_fin = int(assigned['_finisher'].sum())
    submitters = assigned[~assigned['_abandoned']]

    sub('Disposition of everyone who reached the quiz page')
    print(f"  assigned to da, not screened out    {n}")
    print(f"  passed the quiz, played 5 rounds    {pct(n_fin, n)}")
    print(f"  FAILED OUT (4 wrong on a section)   {pct(n_fail, n)}")
    print(f"  abandoned mid-quiz, never submitted {pct(n_ab, n)}")
    print(f"\n  headline failure rate, all arrivals            {pct(n_fail, n)}")
    print(f"  headline failure rate, submitters only        {pct(n_fail, len(submitters))}")
    print(f"  did not get past the quiz (failed + abandoned) {pct(n_fail + n_ab, n)}")

    completed = int((assigned['_failed_quiz'] & assigned['_completed']).sum())
    print(f"\n  quiz-failures who still reached ThankYou (payable) {pct(completed, n_fail)}")

    sub('Attempts per section, passers only (n=%d)' % n_fin)
    print("  A section unlocks the next only when every question in it is correct,")
    print("  so attempts>1 means the participant got something wrong and retried.")
    fin = assigned[assigned['_finisher']]
    att = pd.DataFrame({s: num(fin[f'da.1.player.quiz{s}_attempts']) for s in QUIZ_SECTIONS})
    print(f"\n  {'section':<38} {'mean':>6} {'max':>4}  {'first-try correct':>18}")
    for s, label in QUIZ_SECTIONS.items():
        first = int((att[s] == 1).sum())
        print(f"  {label:<38} {att[s].mean():6.2f} {int(att[s].max()):4d}  {pct(first, n_fin)}")
    total_excess = att.sum(axis=1) - len(QUIZ_SECTIONS)
    any_retry = int((total_excess > 0).sum())
    print(f"\n  needed a retry on at least one section  {pct(any_retry, n_fin)}")
    print(f"  perfect run, all 5 sections first try   {pct(n_fin - any_retry, n_fin)}")
    print(f"  excess attempts per passer: mean {total_excess.mean():.2f}, "
          f"median {total_excess.median():.0f}, max {int(total_excess.max())}")
    print(f"  distribution of excess attempts: "
          f"{dict(sorted(Counter(total_excess.astype(int)).items()))}")

    sub('Where the failures happened')
    print("  The terminating section is the last one reached with 4 attempts.")
    failed = assigned[assigned['_failed_quiz']]
    where = Counter()
    for _, row in failed.iterrows():
        last = None
        for s in QUIZ_SECTIONS:
            a = int(num(pd.Series([row[f'da.1.player.quiz{s}_attempts']])).iloc[0])
            if a >= MAX_ATTEMPTS:
                last = s
        where[last] += 1
    for s, label in QUIZ_SECTIONS.items():
        print(f"  {label:<38} {pct(where.get(s, 0), n_fail)}")
    if where.get(None):
        print(f"  {'(no section reached 4 attempts)':<38} {where[None]}")

    sub('Time spent on the instructions/quiz page')
    print("  Wall-clock ms on da/InstructionsQuiz, from the ai_pages ledger.")
    for label, group in (('passers ', fin), ('failures', failed)):
        secs = []
        for cell in group['participant.ai_pages']:
            page = literal(cell).get('da/InstructionsQuiz') or {}
            if page.get('ms'):
                secs.append(page['ms'] / 1000.0)
        print(f"  {label} seconds: {quartiles(secs)}")


# --- section 2 -------------------------------------------------------------
def rederive_flags(row):
    """Recompute the flag set from the raw columns, per ai_detect.py._rescore."""
    g = lambda k: float(num(pd.Series([row['participant.' + k]])).iloc[0])

    def opt(k):
        v = str(row['participant.' + k]).strip()
        if v in ('', 'None'):
            return None
        try:
            return float(v)
        except ValueError:
            return None

    flags = []
    if g('ai_hid_ms') >= T_HIDDEN_MS or g('ai_blur') >= T_BLUR:
        flags.append('tab_switch')
    if g('ai_hid_max') >= T_HIDDEN_ONE_MS:
        flags.append('long_absence')
    if g('ai_copy_ch') >= T_COPY_CHARS or g('ai_cut') > 0:
        flags.append('copied_out')
    if g('ai_sel_max') >= T_SELECT_CHARS:
        flags.append('large_selection')
    if g('ai_paste_ch') >= T_PASTE_CHARS:
        flags.append('pasted_in')
    if g('ai_jump_max') >= T_JUMP_CHARS:
        flags.append('paste_like_insert')

    ratio = opt('ai_advice_ratio')
    if g('ai_advice_len') >= T_ADVICE_LEN and ratio is not None and ratio < T_KEY_RATIO:
        flags.append('low_keystroke_ratio')

    v2 = g('ai_schema') >= 2
    swipe = g('ai_advice_ime') > T_IME_MAX
    bksp_rate = opt('ai_advice_bksp_rate')
    if (v2 and not swipe and g('ai_advice_len') >= T_ADVICE_LEN
            and g('ai_advice_keys') > 0
            and bksp_rate is not None and bksp_rate < T_BKSP_RATE):
        flags.append('no_revision')
    cv = opt('ai_advice_iki_cv')
    if (v2 and not swipe and g('ai_advice_iki_n') >= T_IKI_MIN_N
            and cv is not None and 0 < cv < T_IKI_CV):
        flags.append('metronomic_typing')

    pointer = g('ai_mouse') + g('ai_touch') + g('ai_scroll')
    if g('ai_pages_instrumented') >= 3 and pointer == 0:
        flags.append('no_pointer_activity')
    if str(row['participant.ai_webdriver']).strip() not in ('', 'False', '0'):
        flags.append('automation_fingerprint')
    return flags


def ai_loop_legs(row):
    """The section 5.3 sequence: text out of the task pages -> time away -> text in."""
    pages = literal(row['participant.ai_pages'])
    copied_out = away = pasted_in = False
    for label, page in pages.items():
        if not isinstance(page, dict):
            continue
        task_page = 'InstructionsQuiz' in label or 'Decision' in label
        if task_page and (page.get('copy', 0) or page.get('cut', 0)
                          or page.get('sel_max', 0) >= T_SELECT_CHARS):
            copied_out = True
            if page.get('hid_ms', 0) >= T_HIDDEN_MS:
                away = True
        if 'Demographics' in label and (page.get('paste_ch', 0) >= T_PASTE_CHARS
                                        or page.get('jump_max', 0) >= T_JUMP_CHARS):
            pasted_in = True
    return copied_out, away, pasted_in


def section_ai(assigned):
    rule('2. SUSPECTED AI USAGE  (docs/ai_detection_codebook.md sections 4-5, 7)')

    fin = assigned[assigned['_finisher']].copy()
    failed = assigned[assigned['_failed_quiz']]
    n_fin = len(fin)

    sub('Reconciliation against the stored flags')
    mismatch = 0
    for _, row in assigned[~assigned['_abandoned']].iterrows():
        if set(rederive_flags(row)) != flagset(row['participant.ai_flags']):
            mismatch += 1
            print(f"  MISMATCH {row['participant.code']}: stored "
                  f"{row['participant.ai_flags']!r} vs re-derived {rederive_flags(row)}")
    print(f"  re-derived flags match stored ai_flags for "
          f"{pct(len(assigned[~assigned['_abandoned']]) - mismatch, len(assigned[~assigned['_abandoned']]))}"
          f" submitters")

    sub('Exposure differs by group -- do not pool these')
    print("  Instrumented pages per participant (the flags can only fire on pages seen):")
    print(f"    finishers      {dict(sorted(Counter(num(fin['participant.ai_pages_instrumented']).astype(int)).items()))}")
    print(f"    quiz-failures  {dict(sorted(Counter(num(failed['participant.ai_pages_instrumented']).astype(int)).items()))}")
    print("  Quiz-failures never reach the free-text survey question, so the five")
    print("  typing-dynamics flags are structurally unavailable to them. Rates below")
    print("  are therefore reported on the 49 finishers.")

    sub('ai_score distribution, finishers (n=%d)' % n_fin)
    print("  Reminder (codebook 5.1): ai_score is an unweighted count of flags of very")
    print("  different diagnosticity. It is a triage aid, never an exclusion rule.")
    dist = Counter(num(fin['participant.ai_score']).astype(int))
    for score in sorted(dist):
        print(f"    ai_score = {score}   {pct(dist[score], n_fin)}   {'#' * dist[score]}")
    clean = dist.get(0, 0)
    print(f"\n  zero flags        {pct(clean, n_fin)}")
    print(f"  at least one flag {pct(n_fin - clean, n_fin)}")

    sub('Per-flag prevalence, finishers')
    counts = Counter()
    for cell in fin['participant.ai_flags']:
        counts.update(flagset(cell))
    for tier_name, tier in (('TIER 1 (high precision -- these justify action)', TIER1),
                            ('TIER 2 (moderate -- needs corroboration)', TIER2),
                            ('TIER 3 (covariate only -- never exclude on this alone)', TIER3)):
        print(f"\n  {tier_name}")
        for f in tier:
            print(f"    {f:<24} {pct(counts.get(f, 0), n_fin)}")
    any_t1 = int(fin['participant.ai_flags'].apply(
        lambda c: bool(flagset(c) & set(TIER1))).sum())
    any_t2 = int(fin['participant.ai_flags'].apply(
        lambda c: bool(flagset(c) & set(TIER2))).sum())
    print(f"\n  any Tier 1 flag   {pct(any_t1, n_fin)}")
    print(f"  any Tier 2 flag   {pct(any_t2, n_fin)}")
    print("\n  Caveat (codebook 1.1): copy_guard.js cancels the clipboard on Decision and")
    print("  InstructionsQuiz, so copied_out there counts ATTEMPTED copies. That makes")
    print("  the flag stronger as evidence of intent, and ai_copy_ch an upper bound.")

    sub('The section 5.3 sequence: copy out -> time off-page -> paste in')
    legs = fin.apply(ai_loop_legs, axis=1, result_type='expand')
    legs.columns = ['copied_out', 'away', 'pasted_in']
    full_loop = int((legs['copied_out'] & legs['away'] & legs['pasted_in']).sum())
    copy_away = int((legs['copied_out'] & legs['away']).sum())
    copy_only = int((legs['copied_out'] & ~legs['pasted_in']).sum())
    print(f"  copy attempt on a task page                     {pct(int(legs['copied_out'].sum()), n_fin)}")
    print(f"  ...and >=30s hidden on that same page           {pct(copy_away, n_fin)}")
    print(f"  ...and a later paste into the survey (FULL LOOP) {pct(full_loop, n_fin)}")
    print(f"  copy attempt with NO later paste                {pct(copy_only, n_fin)}")
    print("  (the post-guard signature: blocked at step 1, so they retyped by hand)")
    print("\n  Where the copies happened. This is why the copied_out count above can")
    print("  exceed the first line here: a copy on survey/Demographics fires the flag")
    print("  but is not part of the instructions->AI->answer loop.")
    where = Counter()
    for cell in fin['participant.ai_pages']:
        for label, page in literal(cell).items():
            if isinstance(page, dict) and (page.get('copy', 0) or page.get('cut', 0)):
                where[label] += 1
    for label, k in sorted(where.items(), key=lambda kv: -kv[1]):
        print(f"    {label:<28} {k} participant(s)")

    sub('What participants tried to copy (ai_copy_sample, verbatim)')
    shown = 0
    for _, row in assigned.iterrows():
        s = str(row['participant.ai_copy_sample']).strip()
        if not s:
            continue
        shown += 1
        role = ('finisher' if row['_finisher'] else
                'quiz-fail' if row['_failed_quiz'] else 'abandoned')
        print(f"\n  [{row['participant.code']} | {role} | flags: "
              f"{row['participant.ai_flags'] or 'none'}]")
        print(f"    {s!r}")
    if not shown:
        print("  (none)")

    sub('High-confidence exclusion set (codebook 7.2)')
    print("  Rule: (copied_out AND pasted_in) OR automation_fingerprint OR no_pointer_activity.")
    print("  This is a ROBUSTNESS set, not a data-cleaning rule: report primary results")
    print("  on the full sample, then show how far they move when these are dropped.")
    excl = fin['participant.ai_flags'].apply(
        lambda c: (('copied_out' in flagset(c) and 'pasted_in' in flagset(c))
                   or 'automation_fingerprint' in flagset(c)
                   or 'no_pointer_activity' in flagset(c)))
    print(f"\n  would be excluded {pct(int(excl.sum()), n_fin)}")
    for _, row in fin[excl].iterrows():
        print(f"    {row['participant.code']}  {row['participant.ai_flags']}")
    return set(fin.loc[excl, 'participant.code'])


# --- section 3 -------------------------------------------------------------
def section_truthtelling(assigned, excluded_codes):
    rule('3. TRUTH-TELLING RATE')
    print("Definition: a decision is truthful iff the participant ranked ALL 6 prizes")
    print("AND the ranking order equals their valuations sorted descending. Valuations")
    print("within a round are always distinct, so the truthful ranking is unique.")

    fin = assigned[assigned['_finisher']].copy()
    rows = []
    for _, p in fin.iterrows():
        vals = literal(p['participant.market_vals'])
        ranks = literal(p['participant.market_ranking'])
        for r in range(1, NR_ROUNDS + 1):
            v = list(vals[str(r)])
            submitted = ranks[str(r)].strip().upper()
            truth = truthful_ranking(v)
            body = submitted.split('0')[0]          # No-Prize token terminates
            full = len(body) == len(PRIZES) and set(body) == set(PRIZES)
            rows.append(dict(
                code=p['participant.code'], role=p['participant.role'], rnd=r,
                submitted=submitted, truth=truth, length=len(body),
                has_no_prize='0' in submitted,
                full=full,
                truthful=bool(full and body == truth),
                top1=bool(body and body[0] == truth[0]),
                tau=kendall_tau(body, truth) if full else None,
                excluded=p['participant.code'] in excluded_codes,
            ))
    d = pd.DataFrame(rows)
    n_dec, n_p = len(d), d['code'].nunique()

    sub('Headline')
    print(f"  decisions analysed  {n_dec}  ({n_p} participants x {NR_ROUNDS} rounds)")
    print(f"  TRUTHFUL            {pct(int(d['truthful'].sum()), n_dec)}  of all decisions")

    sub('Decomposition -- the two ways to fail the definition')
    n_full = int(d['full'].sum())
    print(f"  ranked all 6 prizes                      {pct(n_full, n_dec)}")
    print(f"  ...and ordered them truthfully           {pct(int(d['truthful'].sum()), n_full)}")
    print(f"  truncated ranking (fails on completeness) {pct(n_dec - n_full, n_dec)}")
    print(f"  used the No-Prize token                   {pct(int(d['has_no_prize'].sum()), n_dec)}")
    print(f"\n  ranking length distribution: "
          f"{dict(sorted(Counter(d['length']).items()))}")

    sub('By round -- is there learning?')
    print(f"  {'round':>5}  {'truthful':>20}  {'full ranking':>20}  {'truthful | full':>20}")
    for r in range(1, NR_ROUNDS + 1):
        g = d[d['rnd'] == r]
        gf = g[g['full']]
        print(f"  {r:>5}  {pct(int(g['truthful'].sum()), len(g)):>20}  "
              f"{pct(int(g['full'].sum()), len(g)):>20}  "
              f"{pct(int(gf['truthful'].sum()), len(gf)):>20}")

    sub('By participant')
    per = d.groupby('code')['truthful'].sum().astype(int)
    always = int((per == NR_ROUNDS).sum())
    never = int((per == 0).sum())
    print(f"  truthful in ALL {NR_ROUNDS} rounds  {pct(always, n_p)}")
    print(f"  truthful in NO round      {pct(never, n_p)}")
    print(f"  rounds-truthful distribution: {dict(sorted(Counter(per).items()))}")
    print(f"  mean rounds truthful: {per.mean():.2f} / {NR_ROUNDS}")

    sub('Diagnostics reported alongside, NOT folded into the headline')
    print("  A ranking that swaps ranks 5 and 6 is behaviourally unlike a random one.")
    print(f"  first-ranked prize is the highest-valued  {pct(int(d['top1'].sum()), n_dec)}")
    taus = d.loc[d['full'], 'tau'].astype(float)
    print(f"  Kendall tau vs truthful order, full rankings: mean {taus.mean():.3f}, "
          f"median {taus.median():.3f}")
    near = int(((taus >= 0.8) & (taus < 1.0)).sum())
    print(f"  near-truthful (tau in [0.8, 1.0), i.e. one adjacent swap-ish) "
          f"{pct(near, len(taus))}")

    sub('Splits')
    print("  Group A values prize A at 15 and B at 13; group B is the mirror image.")
    for role in sorted(d['role'].unique()):
        g = d[d['role'] == role]
        print(f"  group {role}  {pct(int(g['truthful'].sum()), len(g))}")
    keep = d[~d['excluded']]
    print(f"\n  full sample                        {pct(int(d['truthful'].sum()), n_dec)}")
    print(f"  excluding high-confidence AI cases {pct(int(keep['truthful'].sum()), len(keep))}"
          f"   (drops {n_dec - len(keep)} decisions)")

    sub('Hand-check: first 3 decisions')
    for _, row in d.head(3).iterrows():
        p = fin[fin['participant.code'] == row['code']].iloc[0]
        v = list(literal(p['participant.market_vals'])[str(row['rnd'])])
        print(f"  {row['code']} r{row['rnd']}: values A-F {v}  ->  truthful {row['truth']}"
              f"  |  submitted {row['submitted']:<7} -> {row['truthful']}")
    return d


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        os.path.dirname(os.path.abspath(__file__)), 'all_apps_48.csv')
    df = pd.read_csv(path, dtype=str, keep_default_na=False)

    rule('PILOT ANALYSIS  --  ' + os.path.basename(path))
    print(f"rows {len(df)}   columns {len(df.columns)}   "
          f"sessions {sorted(set(df['session.code']) - {''})}")

    df, assigned = build_sample(df)
    print(f"\nnever arrived (blank oTree rows)  {int((~df['_visited']).sum())}")
    print(f"screened out (study full)         {int(df['_screened'].sum())}")
    print(f"assigned to a treatment           {len(assigned)}   "
          f"treatments: {sorted(set(assigned['participant.treatment']))}")

    problems = check_round_consistency(assigned[assigned['_finisher']])
    print(f"\nround-level consistency (participant.vars vs per-round player fields): "
          f"{'OK' if not problems else str(len(problems)) + ' PROBLEMS'}")
    for p in problems[:10]:
        print('  ' + p)

    section_quiz(assigned)
    excluded = section_ai(assigned)
    section_truthtelling(assigned, excluded)
    print()


if __name__ == '__main__':
    main()
