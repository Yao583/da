"""
finalize_bonuses.py -- settle everyone pay_bonuses.py could not, once the study is over.

    # 1. Export the participants, and Download demographic data per study
    export DATABASE_URL="$(heroku config:get DATABASE_URL -a <your-app>)"
    python3 export_participants.py -o all_apps_final.csv
    # 2. See who is owed what (report only, writes nothing):
    python3 finalize_bonuses.py all_apps_final.csv \\
        --submissions 6xxx=study_a.csv 6yyy=study_b.csv
    # 3. Write the sheet(s) Prolific's paste box wants -- one per study:
    python3 finalize_bonuses.py all_apps_final.csv --submissions 6xxx=a.csv 6yyy=b.csv \\
        --emit leftovers.csv
    # 4. In Prolific: Bulk actions -> Bulk bonus payment -> paste that study's sheet
    # 5. python3 finalize_bonuses.py --confirm-paid sheet-20260804T153000Z-6xxx

Read-only with respect to the oTree database. It shares ``bonuses_paid.csv`` with
pay_bonuses.py -- same ledger, same batch ids, same --confirm-paid / --discard flow -- so
the two can never pay the same person twice. Dedup is on by default; keep the ledger.

Why it pays by Submission ID: Prolific only attributes a bonus to the study, and hence to the
study's reward-per-hour, when the bonus is keyed by submission id, and it rejects PID-keyed
bulk bonuses outright. Pass one ``--submissions`` export per study (tagged ``STUDY_ID=path``)
and each emitted sheet is pasted into its own study.

Three disjoint groups appear in the export, and only the first two are ever paid a bonus:

    market member   assembled into a group of exactly 8; bonus = participant.bonus_payout,
                    computed post-hoc by allocation.compute_market_bonuses
    leftover        usable finisher with no market to compute a bonus from. Either their
                    market never closed -- a bucket overfills whenever a slow reader's slot
                    times out in the router and gets refilled, so a treatment can end at
                    (say) 4 A_normal against a target of 3 -- or they were the extra member
                    of a market that assembled larger than 8 (see below). They were promised
                    a bonus on ThankYou, so the leftovers are shuffled into fresh markets of
                    3 A_normal + 1 A_lowest + 3 B_normal + 1 B_lowest (reassemble.py) and paid
                    the bonus that market computes. Whoever the composition rule cannot place
                    is paid --flat-fee instead.
    screened out    two kinds, neither paid anything and neither ever in the bonus sheet:
                    (a) study full on arrival -- stopped before Consent; (b) failed the
                    comprehension quiz -- ejected mid-study to the survey app's QuizFailed page.
                    Both are shown no Prolific code of any kind and are asked to return the
                    submission instead.
                    DO NOT REJECT either kind. A rejection penalises the participant's Prolific
                    account; a submission they did not return is left to time out instead.

Oversized markets: a market is assembled as exactly 8, so a larger one means an assembly ran
that should not have (a stale session.vars snapshot re-picking placed codes). The members the
ledger already paid are the market of record -- that is the allocation which actually executed
-- and the rest are demoted to leftovers and re-assembled with everyone else. Without ledger
coverage there is nothing to decide with, so such a market is reported and left out of the
sheet rather than guessed at.

Why re-assembly and not an average: a market is only 3/1/3/1 because each treatment app tells
the designated member "You have the lowest prize priority among the four participants in Group
X" and tells the other three they do not. Relaxing the composition to soak up more of the
residue would make one of those statements false for someone who is about to be paid on it, so
reassemble.py either builds that exact shape or builds nothing. A market consumes three normals
per lowest, so the residue skews lowest and most treatments will form nothing -- those
participants get the flat fee, which is the honest end of it.

The bonus column is in the study's real-world currency (participation fee aside); the
paying round is the same for everyone in the session and is drawn once by the router.
"""

import argparse
import collections
import csv
import datetime
import os
import sys

import allocation
import payments_common as pc
import reassemble
# Shared with pay_bonuses.py so the two scripts cannot disagree about who is owed what, pay
# the same person twice, or resolve a Prolific submission differently.
from payments_common import cell, fail, flag, money, rule


# --- classification --------------------------------------------------------
def classify(rows):
    """Split the export into the groups. Returns (members, leftovers, screened, ignored)
    lists of rows."""
    members, leftovers, screened, ignored = [], [], [], []
    for row in rows:
        rec = pc.record_from_csv_row(row)
        if rec['screened_out']:
            screened.append(row)
            continue
        if not rec['treatment']:
            # Never routed: an unused participant slot, or someone who closed the tab on
            # the router page before it auto-submitted. Nothing owed either way.
            ignored.append(row)
            continue
        if rec['failed_quiz']:
            # Ejected by the 4-strikes quiz rule. They were shown no code at all and asked to
            # return the submission, so they are owed nothing -- not even the base payment.
            screened.append(row)
            continue
        if pc.is_market_member(rec):
            members.append(row)
        elif rec['study_completed']:
            # Finished and usable, but no market closed around them.
            leftovers.append(row)
        else:
            # Silent dropout: never reached ThankYou, so no completion code and no
            # Prolific submission to bonus.
            ignored.append(row)
    return members, leftovers, screened, ignored


def paid_as_market(ledger_rows):
    """{market_id: {participant_code, ...}} -- who the ledger paid *as a member of* a market.

    Keyed on the ledger's own market_id column rather than mere presence in the file, because
    a demoted member settled as a leftover is also in the ledger. Only rows recorded against
    the market count as that market's allocation.
    """
    by_market = collections.defaultdict(set)
    for row in ledger_rows:
        market_id = (row.get('market_id') or '').strip()
        code = (row.get('participant_code') or '').strip()
        if market_id and code:
            by_market[market_id].add(code)
    return by_market


def split_oversized_markets(members, paid_by_market):
    """Demote the extra members of any market larger than 8 to leftovers.

    A market is assembled as exactly 8, so a bigger one means an assembly ran twice under the
    same id and its stored allocation covers more people than it computed for. The members the
    ledger paid *as that market* are the market of record: that allocation actually executed
    and the money is gone. The rest have a bonus_payout that was never paid against an
    allocation that was never final, so they are settled as leftovers at the treatment mean.

    Returns (members, demoted, undecidable) -- ``undecidable`` being oversized markets with no
    usable ledger coverage to choose with, which are left out of the sheet entirely.
    """
    by_market = collections.defaultdict(list)
    for row in members:
        by_market[cell(row, 'market_id')].append(row)

    keep, demoted, undecidable = [], [], {}
    for market_id, rows in by_market.items():
        if len(rows) <= allocation.NUM_PLAYERS:
            keep.extend(rows)
            continue
        of_record = paid_by_market.get(market_id, set())
        paid = [r for r in rows if cell(r, 'code') in of_record]
        if len(paid) != allocation.NUM_PLAYERS:
            # No defensible way to pick 8 of them; report rather than guess.
            undecidable[market_id] = rows
            continue
        paid_set = {cell(r, 'code') for r in paid}
        keep.extend(paid)
        demoted.extend(r for r in rows if cell(r, 'code') not in paid_set)
    return keep, demoted, undecidable


def crown_value_of(members, paying_round, override):
    """Dollars per Crown, measured from the markets that already closed.

    Not read from ``allocation.CROWN_VALUE_USD``: what a re-assembled member must be paid is
    whatever rate the *deployed* app paid everyone else at, and the two have differed. Every
    live member stores both the Crowns they won (``market_detail[paying_round]['payoff']``) and
    the dollars they were credited (``bonus_payout``), so the realised rate is simply the ratio
    -- and if the study paid at one consistent rate, every member agrees on it.

    Returns (rate, {rate: count}). A split vote is left for the caller to refuse.
    """
    seen = collections.Counter()
    for row in members:
        detail = pc.mapping(cell(row, 'market_detail'))
        crowns = (detail.get(str(paying_round)) or {}).get('payoff')
        paid = money(cell(row, 'bonus_payout'))
        if crowns and paid is not None:
            seen[round(paid / crowns, 4)] += 1
    if override is not None:
        return override, seen
    if len(seen) == 1:
        return next(iter(seen)), seen
    return None, seen


def paying_round_of(rows, override):
    """The round the bonus is drawn from -- a session-level draw, identical for everyone.

    export_participants.py carries it out of session.vars into a ``session.paying_round``
    column. Guessing it wrong would pay every re-assembled member the wrong round's payoff and
    look entirely plausible in the sheet, so an absent column is fatal rather than defaulted.
    """
    if override is not None:
        return override
    seen = {(row.get('session.paying_round', '') or '').strip() for row in rows}
    seen.discard('')
    if not seen:
        fail("no session.paying_round column in the export and no --paying-round; re-run "
             "export_participants.py, or pass the round the study actually paid")
    if len(seen) > 1:
        fail(f"the export mixes sessions with different paying rounds ({', '.join(sorted(seen))}); "
             f"re-run with --session-code, or pass --paying-round")
    value = seen.pop()
    if not value.isdigit() or not 1 <= int(value) <= allocation.NUM_ROUNDS:
        fail(f"session.paying_round is {value!r}, which is not a round in 1..{allocation.NUM_ROUNDS}")
    return int(value)


def payee(row):
    """Prolific identifies participants by the label passed in the start URL. Fall back
    to the oTree code so a session run without labels still produces a usable sheet."""
    label = cell(row, 'label')
    return label or cell(row, 'code')


def read_paid_ledger(path):
    """Load the shared ledger. Returns (rows, codes, PIDs) already settled, in whatever state
    -- a row stuck at 'setup' may or may not have gone through, so it counts as settled here
    too and is reconciled by hand."""
    rows = pc.read_ledger(path)
    if rows and 'participant_code' not in rows[0]:
        sys.exit(f"{path} does not look like a pay_bonuses.py ledger")
    codes, pids = pc.ledger_covers(rows)
    return rows, codes, pids


# --- report ----------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('csv_path', nargs='?', default='all_apps.csv',
                        help='exported oTree "all apps" wide CSV')
    parser.add_argument('-o', '--out', default='bonuses.csv',
                        help='annotated record of every payment decision (who, how much, '
                             'which submission, and why)')
    parser.add_argument('--submissions', nargs='+', metavar='[STUDY_ID=]PATH',
                        help="Prolific's 'Download demographic data' CSV, used to map "
                             "Prolific PIDs to Submission IDs. Pass one per study -- a "
                             "duplicated study has its own submission ids and its own bonus "
                             "page, so prefix each file with its study id (STUDY_ID=path)")
    parser.add_argument('--emit', metavar='PATH',
                        help='write the bare <submission_id>,<amount> sheet Prolific\'s paste '
                             'box wants (one file per study) and record it in the ledger')
    parser.add_argument('--confirm-paid', metavar='BATCH_ID',
                        help='mark an emitted sheet as paid, after pasting it into Prolific')
    parser.add_argument('--discard', metavar='BATCH_ID',
                        help='drop an emitted sheet that was never pasted, releasing those '
                             'participants to be paid on a later run')
    parser.add_argument('--flat-fee', type=float, default=3.00, metavar='USD',
                        help='paid to every leftover the 3/1/3/1 composition could not place '
                             'into a market (default: 3.00)')
    parser.add_argument('--seed', default='final',
                        help='RNG seed for the re-assembly. The same seed over the same pool '
                             'always produces the same markets and the same amounts, so a '
                             'dry run can be trusted and a rerun cannot silently repay '
                             'different numbers')
    parser.add_argument('--paying-round', type=int, metavar='N',
                        help='round the bonus is drawn from; defaults to the export\'s '
                             'session.paying_round column')
    parser.add_argument('--crown-value', type=float, metavar='USD',
                        help='dollars per Crown for re-assembled members; defaults to the rate '
                             'the already-closed markets were actually paid at, which is what '
                             'keeps two identical payoffs worth the same money')
    parser.add_argument('--ledger', default='bonuses_paid.csv',
                        help='payment ledger shared with pay_bonuses.py; everyone in it is '
                             'left out of the sheet. KEEP IT -- losing this file means paying '
                             'everyone again')
    parser.add_argument('--already-paid', metavar='LEDGER', dest='already_paid',
                        help='deprecated alias for --ledger')
    args = parser.parse_args()

    if args.already_paid:
        args.ledger = args.already_paid
        print("NOTE: --already-paid is now --ledger (finalize writes to it as well as "
              "reading it).")

    # --- ledger bookkeeping; neither needs the export ---
    if args.confirm_paid and args.discard:
        fail("--confirm-paid and --discard are mutually exclusive")
    if args.confirm_paid:
        changed = pc.mark_paid(args.ledger, args.confirm_paid, from_states=('emitted', 'setup'))
        if not changed:
            fail(f"no unconfirmed rows for batch {args.confirm_paid} in {args.ledger}")
        rule(f"batch {args.confirm_paid}: {changed} row(s) marked paid")
        return
    if args.discard:
        dropped = pc.discard_batch(args.ledger, args.discard)
        if not dropped:
            fail(f"no emitted rows for batch {args.discard} in {args.ledger}")
        rule(f"batch {args.discard}: {dropped} row(s) discarded, released for a later run")
        return

    if not os.path.exists(args.csv_path):
        sys.exit(f"no such file: {args.csv_path}")

    ledger_rows, paid_codes, paid_pids = read_paid_ledger(args.ledger)

    def already_settled(row):
        return (cell(row, 'code') in paid_codes
                or (cell(row, 'label') and cell(row, 'label') in paid_pids))

    with open(args.csv_path, newline='', encoding='utf-8-sig') as fh:
        rows = list(csv.DictReader(fh))
    if not rows or 'participant.code' not in rows[0]:
        sys.exit(f"{args.csv_path} does not look like an oTree 'all apps' wide export")

    members, leftovers, screened, ignored = classify(rows)

    rule(f"{args.csv_path}: {len(rows)} participant rows")

    paying_round = paying_round_of(rows, args.paying_round)
    print(f"paying round: {paying_round}")

    # --- oversized markets ---
    # Done before the re-assembly, so a demoted member goes into the pool as an ordinary
    # leftover rather than keeping a bonus an allocation that never became final computed.
    paid_by_market = paid_as_market(ledger_rows)
    members, demoted, undecidable = split_oversized_markets(members, paid_by_market)
    if demoted:
        print(f"\nOversized market(s): {len(demoted)} member(s) demoted to leftovers")
        print(f"  A market is assembled as exactly {allocation.NUM_PLAYERS}, so a larger one "
              f"means an assembly ran twice under\n  the same id. The "
              f"{allocation.NUM_PLAYERS} already in {args.ledger} are the market of record; "
              f"these were\n  never paid, and their stored bonus is discarded with the "
              f"allocation that produced it:")
        for row in demoted:
            print(f"    {payee(row):<26} {cell(row, 'market_id'):<16} "
                  f"stored bonus {cell(row, 'bonus_payout')}")
        leftovers.extend(demoted)
    if undecidable:
        print(f"\nWARNING: {len(undecidable)} oversized market(s) with no usable ledger "
              f"coverage -- LEFT OUT of the sheet:")
        for market_id, market_rows in sorted(undecidable.items()):
            paid_here = len(paid_by_market.get(market_id, set()))
            print(f"    {market_id}: {len(market_rows)} members, {paid_here} paid as this "
                  f"market (expected {allocation.NUM_PLAYERS})")
        print("  Settle these by hand: there is no defensible way to pick which "
              f"{allocation.NUM_PLAYERS} were the market.")

    # --- markets ---
    markets = collections.defaultdict(list)
    for row in members:
        markets[cell(row, 'market_id')].append(row)

    print("\nMarkets assembled live")
    by_treatment = collections.Counter(mid.rsplit('-', 1)[0] for mid in markets)
    for treatment in sorted(by_treatment):
        print(f"  {treatment:<14} {by_treatment[treatment]} market(s)")
    short = [mid for mid, m in markets.items() if len(m) != allocation.NUM_PLAYERS]
    if short:
        print(f"  WARNING: markets not of size {allocation.NUM_PLAYERS}: "
              f"{', '.join(f'{mid} ({len(markets[mid])})' for mid in sorted(short))}")

    # --- payments ---
    # Members of a market that closed live keep the bonus that market computed for them; only
    # the ones pay_bonuses.py has already handled are left out of the sheet.
    payments = []
    market_of = {}          # participant code -> market the payment is *for*
    pid_of = {}             # participant code -> 1..8 slot within that market
    settled = 0
    for row in members:
        amount = money(cell(row, 'bonus_payout'))
        if amount is None:
            # A market member with no stored bonus should be impossible; surface it
            # rather than silently paying 0.
            print(f"  WARNING: {cell(row, 'code')} is in market {cell(row, 'market_id')} "
                  f"but has no bonus_payout; treating as leftover")
            leftovers.append(row)
            continue
        if already_settled(row):
            settled += 1
            continue
        code = cell(row, 'code')
        market_of[code] = cell(row, 'market_id')
        pid_of[code] = cell(row, 'market_pid')
        payments.append((row, amount, f"market {cell(row, 'market_id')}"))

    print(f"\nAlready in {args.ledger}, left out of the sheet: {settled}")

    # --- leftovers: re-assemble what the composition rule allows, flat-fee the rest ---
    row_by_code = {cell(row, 'code'): row for row in leftovers}
    pool = []
    unpayable_pool = []
    for row in leftovers:
        if already_settled(row):
            settled += 1
            continue
        if not cell(row, 'label'):
            # No Prolific PID, so no submission and no way to pay them. Keeping them out of the
            # pool matters: one of them holding a scarce _normal slot would strand a whole
            # market of eight people who *can* be paid. Reported below with the unmatched.
            unpayable_pool.append(row)
            continue
        pool.append(pc.record_from_csv_row(row))

    if leftovers:
        print(f"\nLeftovers: {len(leftovers)} usable finisher(s) with no market of their own "
              f"({len(pool)} to place, {settled} already paid, {len(unpayable_pool)} with no "
              f"Prolific PID)")

    print(f"\nRe-assembly (needs {allocation.PER_MARKET['A_normal']} A_normal + "
          f"{allocation.PER_MARKET['A_lowest']} A_lowest + {allocation.PER_MARKET['B_normal']} "
          f"B_normal + {allocation.PER_MARKET['B_lowest']} B_lowest per market)")
    for treatment, row in sorted(reassemble.feasibility(pool).items()):
        print(f"  {treatment:<14} A_n={row['A_normal']:>3} A_l={row['A_lowest']:>3} "
              f"B_n={row['B_normal']:>3} B_l={row['B_lowest']:>3}  -> {row['markets']} market(s), "
              f"{row['leftover']} unplaced")

    crown_value, rates_seen = crown_value_of(members, paying_round, args.crown_value)
    if crown_value is None:
        fail(f"the closed markets were paid at more than one dollars-per-Crown rate "
             f"({', '.join(f'{r} x{n}' for r, n in sorted(rates_seen.items()))}); pass "
             f"--crown-value to say which one the re-assembled members should get")
    print(f"\nCrown value: ${crown_value:.2f} per Crown"
          + (f" (measured from {sum(rates_seen.values())} already-closed market member(s))"
             if args.crown_value is None else " (--crown-value)"))
    if crown_value != allocation.CROWN_VALUE_USD:
        print(f"  NOTE: allocation.CROWN_VALUE_USD is {allocation.CROWN_VALUE_USD}, but the "
              f"study actually paid {crown_value}. Paying the\n  measured rate, so a "
              f"re-assembled member is worth the same as anyone else with that payoff.")

    new_markets, unplaced = reassemble.assemble(
        pool, paying_round, args.seed, crown_value,
        # Continue each treatment's own numbering, so a new market can never reuse an id a
        # live one already wrote (and the ledger stays readable as one sequence).
        start_indices=reassemble.next_market_indices(
            [pc.record_from_csv_row(row) for row in rows]))

    for market in new_markets:
        subtotal = sum(amount for _, _, amount in market['members'])
        print(f"\n  {market['market_id']} ({market['treatment']}), {subtotal:.2f} total")
        for rec, pid, amount in market['members']:
            row = row_by_code[rec['code']]
            print(f"    {pid}  {payee(row):<26} {rec['bucket']:<10} paid {amount:>6.2f}")
            market_of[rec['code']] = market['market_id']
            pid_of[rec['code']] = pid
            payments.append((row, amount, f"market {market['market_id']} (re-assembled)"))

    flat = round(args.flat_fee, 2)
    if unplaced:
        print(f"\n  Unplaced: {len(unplaced)} finisher(s) paid the flat fee of {flat:.2f}")
        for rec in unplaced:
            row = row_by_code[rec['code']]
            market_of[rec['code']] = 'leftover'
            payments.append((row, flat, "leftover, flat fee"))

    # Carried through as owed-but-unresolvable rather than dropped, so resolve_payable reports
    # them by name under "No Prolific submission found" instead of them vanishing from the run.
    for row in unpayable_pool:
        market_of[cell(row, 'code')] = 'leftover'
        payments.append((row, flat, "leftover, flat fee"))

    # --- everyone else ---
    quiz_fails = sum(1 for r in screened if flag(r, 'failed_quiz'))
    print(f"\nScreened out: {len(screened)} -- pay nothing, do NOT reject "
          f"(study full {len(screened) - quiz_fails}, failed quiz {quiz_fails}).")
    print(f"  Both kinds were shown no Prolific code and asked to return the submission. If one "
          f"did not\n  return it, leave it to time out: rejecting penalises the participant's "
          f"account and\n  neither kind was paid anything to begin with.")
    for row in screened:
        recorded = money(cell(row, 'total_payment'))
        if recorded:
            print(f"  NOTE: {payee(row)} exports total_payment={recorded} but is owed 0")

    print(f"\nNot routed / silent dropout, nothing owed: {len(ignored)}")

    if not payments:
        rule("nothing left to pay")
        return

    # --- resolve PID -> submission id ---
    # Prolific rejects PID-keyed bulk bonuses, so nothing can be paid without this. Without
    # --submissions the run still reports the full decision, it just cannot write a sheet.
    reason_of = {cell(row, 'code'): reason for row, _, reason in payments}
    amount_of = {cell(row, 'code'): amount for row, amount, _ in payments}
    recs = [pc.record_from_csv_row(row) for row, _, _ in payments]

    if args.submissions:
        submissions = pc.load_submissions(args.submissions)
        payable, unmatched, unpayable = pc.resolve_payable(
            recs, submissions, bonus_of=lambda r: amount_of[r['code']])
        pc.report_unresolved(unmatched, unpayable, amount_of=lambda r: amount_of[r['code']])
    else:
        if args.emit:
            fail("no way to resolve Submission IDs: pass --submissions with Prolific's "
                 "'Download demographic data' CSV (one per study)")
        payable = [(rec, amount_of[rec['code']], '', '', '') for rec in recs]

    # --- annotated record of every decision ---
    # market_id and market_pid are what make a re-assembled allocation auditable: market_id is
    # the RNG seed compute_market_bonuses was given, and market_pid is the member's slot in it,
    # so the two together reproduce the whole thing from the export.
    with open(args.out, 'w', newline='', encoding='utf-8') as fh:
        writer = csv.writer(fh)
        writer.writerow(['submission_id', 'bonus', 'study_id', 'participant_label',
                         'participant_code', 'market_id', 'market_pid', 'reason'])
        for rec, amount, submission_id, _, study in payable:
            code = rec['code']
            writer.writerow([submission_id, f"{amount:.2f}", study, rec['label'], code,
                             market_of.get(code, ''), pid_of.get(code, ''), reason_of[code]])

    total = sum(amount for _, amount, _, _, _ in payable)
    rule(f"wrote {args.out}: {len(payable)} bonus payments, {total:.2f} total")
    if not args.submissions:
        print("Report only -- no Submission IDs resolved, so no sheet can be pasted.\n"
              "Pass --submissions STUDY_A=a.csv STUDY_B=b.csv --emit leftovers.csv to pay.")
        return

    # --- paste-ready sheet(s), one per study ---
    if args.emit:
        stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        # What the payment was *for*, which is not always where the participant is stored: a
        # re-assembled member records their new market, and a flat-fee leftover records no
        # market at all -- otherwise the next run counts them as a member of one.
        pc.emit_sheets(payable, args.emit, args.ledger, stamp,
                       market_of=lambda rec: market_of.get(rec['code'], 'leftover'))
        return

    rule("DRY RUN -- nothing was written to the ledger.")
    print("Write the sheet(s) to paste:  --emit leftovers.csv")


if __name__ == '__main__':
    main()
