#!/usr/bin/env python3
"""pay_bonuses.py -- pay DA bonuses as each market of 8 closes.

Normal workflow (no Prolific API token needed):

    export DATABASE_URL="$(heroku config:get DATABASE_URL -a <your-app>)"

    # 1. On each Prolific study page: Download demographic data -> <study>.csv
    # 2. See who is owed what (report only, writes nothing):
    python3 pay_bonuses.py --submissions 6xxx=study_a.csv 6yyy=study_b.csv
    # 3. Write the sheet(s) Prolific's paste box wants -- one per study:
    python3 pay_bonuses.py --submissions 6xxx=study_a.csv 6yyy=study_b.csv --emit sheet.csv
    # 4. In Prolific: Bulk actions -> Bulk bonus payment -> paste that study's sheet
    # 5. Record that it went through (the run above prints the exact batch id):
    python3 pay_bonuses.py --confirm-paid sheet-20260803T153000Z-6xxx

If a sheet was generated but never pasted, release those people again with
``--discard <batch-id>``. Until you do one or the other they are held back, so a sheet can
never be pasted twice by accident.

There is also an API path -- ``--token`` plus ``--study-id ... --pay`` -- which does steps 3-5
in one go. It shares the same ledger, so the two cannot double-pay the same person.

Several studies, one session: duplicating a study on Prolific gives the copy its own study id
and its own submission ids, but both copies recruit into the same oTree session. A bonus only
attaches to a submission through the study that owns it, so pass one ``--submissions`` file
per study (tagged ``STUDY_ID=path``) and paste each emitted sheet into its own study. Anyone
whose PID is missing from the exports you passed is reported as unmatched and left unpaid,
never guessed at.

Every run starts with an audit: market sizes (always 8 -- anything else means a market
assembled that should not have), participants whose stored market or bonus no longer matches
what the ledger already paid them, who is newly owed, and any Prolific PID holding more than
one oTree participant record.

Read-only with respect to the oTree database. The only thing it writes is the ledger
(bonuses_paid.csv), which is what stops anyone being paid twice. Keep it.

Why this exists: survey/__init__.py fills in ``bonus_payout`` the moment a group of 8
assembles, but nobody was paid until the whole study closed and finalize_bonuses.py was run
by hand. This settles closed markets continuously instead.

Why it pays by Submission ID: Prolific only attributes a bonus to the *study* -- and hence to
the study's reward-per-hour -- when the bonus is keyed by submission id. Paying by Prolific
PID (what finalize_bonuses.py's sheet does) delivers the money but leaves the study looking
like it pays only the participation fee. Prolific rejects PID-keyed bulk bonuses outright.

Funding note: bonuses come out of the workspace's *available* balance, which excludes money
reserved for the live study. Paying mid-study rather than after it stops may need a top-up.

Scope: members of markets that assembled at exactly 8. Quiz-fails, suspected bots, usable
finishers whose market never closed, and the members of any market that did not assemble at
exactly 8 are all left for finalize_bonuses.py at the end of the study. Both scripts share
bonuses_paid.csv, so neither can pay someone the other already has.
"""

import argparse
import binascii
import csv
import datetime
import io
import os
import pickle

import allocation
import payments_common as pc
# Submission resolution, the ledger and the console helpers are shared with
# finalize_bonuses.py so the two cannot pay the same person twice or disagree about who is
# owed what. Only the Prolific *API* client below is specific to this script.
from payments_common import (
    append_ledger, best_submission_per_pid, discard_batch, fail, mark_paid, migrate_ledger,
    read_ledger, rule,
)

API_BASE = 'https://api.prolific.com'
BATCH_LIMIT = 200          # Prolific's cap on ids per bulk bonus request
PAGE_LIMIT = 200


# --- sources ---------------------------------------------------------------
class _VarsUnpickler(pickle.Unpickler):
    """oTree pickles participant.vars, and a Currency can end up inside it. Currency is a
    Decimal subclass that pickles as (Currency, ('9.00',)), so decoding it as a plain float
    keeps this script runnable without oTree installed."""

    def find_class(self, module, name):
        if module == 'otree.currency' and name in ('Currency', 'BaseCurrency'):
            return float
        return super().find_class(module, name)


def decode_vars(blob):
    """otree_participant._vars is base64(pickle(dict)) -- see otree/database.py.

    Returns None if a non-empty blob could not be decoded. That is reported rather than
    swallowed: a participant whose vars are unreadable would otherwise look like a
    non-member and quietly go unpaid.
    """
    if not blob:
        return {}
    try:
        return _VarsUnpickler(io.BytesIO(binascii.a2b_base64(blob.encode('utf-8')))).load()
    except Exception:
        return None


def load_from_db(database_url, session_code=None):
    try:
        import psycopg2
    except ImportError:
        fail("psycopg2 is not installed; pip install psycopg2-binary, or use --from-csv")

    query = "SELECT code, label, _session_code, _vars FROM otree_participant WHERE _vars IS NOT NULL"
    params = []
    if session_code:
        query += " AND _session_code = %s"
        params.append(session_code)

    conn = psycopg2.connect(database_url, sslmode='require')
    try:
        with conn.cursor() as cur:
            cur.execute(query, params)
            rows = cur.fetchall()
    finally:
        conn.close()

    records, undecodable = [], []
    for code, label, sess, blob in rows:
        pvars = decode_vars(blob)
        if pvars is None:
            undecodable.append(code)
            pvars = {}
        records.append(pc.record_from_vars(code, label, sess, pvars))
    if undecodable:
        print(f"WARNING: could not decode participant.vars for {len(undecodable)} "
              f"participant(s); they cannot be assessed for payment: "
              f"{', '.join(undecodable[:10])}"
              f"{' ...' if len(undecodable) > 10 else ''}")
    return records


def load_from_csv(path, session_code=None):
    with open(path, newline='', encoding='utf-8-sig') as fh:
        rows = list(csv.DictReader(fh))
    if not rows or 'participant.code' not in rows[0]:
        fail(f"{path} does not look like an oTree 'all apps' wide export")
    records = [pc.record_from_csv_row(row) for row in rows]
    if session_code:
        records = [r for r in records if r['session_code'] == session_code]
    return records


# --- Prolific API ----------------------------------------------------------
class Prolific:
    def __init__(self, token):
        import requests
        self.session = requests.Session()
        self.session.headers.update({
            'Authorization': f'Token {token}',
            'Content-Type': 'application/json',
        })

    def _check(self, response, what):
        if not response.ok:
            fail(f"{what} failed: HTTP {response.status_code}\n{response.text}")
        return response

    def submissions(self, study_id):
        """Every submission on the study, following pagination."""
        base = f"{API_BASE}/api/v1/studies/{study_id}/submissions/"
        url, offset, out = f"{base}?limit={PAGE_LIMIT}&offset=0", 0, []
        while url:
            data = self._check(self.session.get(url, timeout=60),
                               'listing submissions').json()
            page = data.get('results') or []
            out.extend(page)
            nxt = (data.get('_links') or {}).get('next') or {}
            href = nxt.get('href') if isinstance(nxt, dict) else nxt
            if href:
                url = href
            elif len(page) == PAGE_LIMIT:
                offset += PAGE_LIMIT
                url = f"{base}?limit={PAGE_LIMIT}&offset={offset}"
            else:
                url = None
        # Tag with the study we asked for: several studies get merged downstream and the
        # response's own study_id is not guaranteed to be present on every page shape.
        for sub in out:
            sub['study'] = study_id
        return out

    def setup_bonus(self, study_id, pairs):
        """pairs: [(submission_id, amount_float)]. Returns the API's response dict."""
        csv_bonuses = '\n'.join(f"{sid},{amount:.2f}" for sid, amount in pairs)
        response = self.session.post(
            f"{API_BASE}/api/v1/submissions/bonus-payments/",
            json={'study_id': study_id, 'csv_bonuses': csv_bonuses},
            timeout=60,
        )
        return self._check(response, 'setting up the bonus batch').json()

    def pay_bonus(self, bulk_payment_id):
        """NOT idempotent -- calling this twice for one id pays everyone twice."""
        response = self.session.post(
            f"{API_BASE}/api/v1/bulk-bonus-payments/{bulk_payment_id}/pay/",
            json={}, timeout=60,
        )
        return self._check(response, 'paying the bonus batch')


# --- audit -----------------------------------------------------------------
def audit(records, owed, ledger):
    """Report what the payment selection looks like, before any money is involved.

    Markets are written in blocks of exactly 8 (survey/__init__.py) and every payoff is a
    positive prize value, so the number of people owed a bonus should always be 8 * markets.
    When it is not, something assembled a market it should not have, and the cheapest place to
    notice is here -- before a sheet is emitted.
    """
    rule("audit")

    # --- market roster ---
    # Sized over every market member, not just those owed, so a market is never called
    # undersized merely because one of its members has no bonus recorded.
    markets = pc.markets_by_id(records)
    print(f"{len(markets)} market(s), {len(owed)} member(s) owed a bonus")
    bad = sorted(mid for mid, members in markets.items()
                 if len(members) != allocation.NUM_PLAYERS)
    if bad:
        print(f"  WARNING: markets not of size {allocation.NUM_PLAYERS}: "
              f"{', '.join(f'{mid} ({len(markets[mid])})' for mid in bad)}")
        print(f"  Their members are held back from payment and left for "
              f"finalize_bonuses.py.")
    if len(owed) % allocation.NUM_PLAYERS:
        print(f"  WARNING: {len(owed)} is not a multiple of {allocation.NUM_PLAYERS}, so these "
              f"are not whole markets. See the drift check below.")

    # --- ledger drift ---
    # A participant whose market_id or bonus has changed since they were paid was re-placed
    # into a later market, which means the amount already sent no longer matches their data.
    by_code = {r['code']: r for r in records}
    drift = []
    for row in ledger:
        rec = by_code.get(row.get('participant_code'))
        if rec is None:
            continue
        was_amount, was_market = pc.money(row.get('amount')), (row.get('market_id') or '')
        now_amount, now_market = rec['bonus'], rec['market_id']
        if was_market != now_market or (was_amount is not None and now_amount is not None
                                        and abs(was_amount - now_amount) > 0.005):
            drift.append((rec, was_amount, was_market, now_amount, now_market))
    if drift:
        print(f"\n  STOP: {len(drift)} already-paid participant(s) no longer match the ledger.")
        print("  They were re-placed into a different market after being paid, so the amount\n"
              "  sent is not the amount their data now shows. Decide what the study should do\n"
              "  about them before paying anyone else; market_detail and market_pid still\n"
              "  record what each market actually computed.")
        for rec, was_amount, was_market, now_amount, now_market in drift:
            was = 'n/a' if was_amount is None else f"{was_amount:.2f}"
            now = 'n/a' if now_amount is None else f"{now_amount:.2f}"
            print(f"    {rec['code']:<10} {pc.payee(rec):<26} paid {was:>6} as "
                  f"{was_market:<16} -> now {now:>6} in {now_market}")

    # --- repeat PIDs ---
    # A duplicated Prolific study does not exclude the original's participants unless the
    # original is added to its exclusion list, so the same person can hold two oTree records.
    per_pid = {}
    for rec in records:
        if rec['label']:
            per_pid.setdefault(rec['label'], []).append(rec)
    repeats = sorted(pid for pid, recs in per_pid.items() if len(recs) > 1)
    if repeats:
        print(f"\n  {len(repeats)} Prolific PID(s) with more than one oTree participant "
              f"record:")
        for pid in repeats[:20]:
            detail = ', '.join(f"{r['code']}({r['market_id'] or 'no market'})"
                               for r in per_pid[pid])
            print(f"    {pid}  {detail}")
        if len(repeats) > 20:
            print(f"    ... and {len(repeats) - 20} more")


# --- main ------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--study-id', action='append', metavar='STUDY_ID', default=None,
                        help='Prolific study id; repeat once per study when several are '
                             'recruiting into the same session. Needed for --pay and for the '
                             'API submissions lookup')
    parser.add_argument('--submissions', nargs='+', metavar='[STUDY_ID=]PATH',
                        help="Prolific's 'Download demographic data' CSV, used to map "
                             "Prolific PIDs to Submission IDs without an API token. Pass one "
                             "per study -- a duplicated study has its own submission ids and "
                             "its own bonus page, so prefix each file with its study id "
                             "(STUDY_ID=path) to pay through it")
    parser.add_argument('--emit', metavar='PATH',
                        help='write a <submission_id>,<amount> sheet to paste into Prolific '
                             "(Bulk actions -> Bulk bonus payment)")
    parser.add_argument('--confirm-paid', metavar='BATCH_ID',
                        help='mark an emitted sheet as paid, after pasting it into Prolific')
    parser.add_argument('--discard', metavar='BATCH_ID',
                        help='drop an emitted sheet that was never pasted, releasing those '
                             'participants to be paid on a later run')
    parser.add_argument('--pay', action='store_true',
                        help='pay through the Prolific API instead of emitting a sheet; '
                             'requires --token and a study id per study being paid')
    parser.add_argument('--from-csv', metavar='PATH',
                        help="read an exported oTree 'all apps' wide CSV instead of the "
                             "live database (useful for a dry run)")
    parser.add_argument('--database-url', default=os.environ.get('DATABASE_URL'),
                        help='defaults to $DATABASE_URL')
    parser.add_argument('--token', default=os.environ.get('PROLIFIC_TOKEN'),
                        help='defaults to $PROLIFIC_TOKEN')
    parser.add_argument('--session-code', help='restrict to one oTree session')
    parser.add_argument('--ledger', default='bonuses_paid.csv',
                        help='payment ledger; every row in it is skipped on later runs. '
                             'KEEP IT -- losing this file means paying everyone again')
    parser.add_argument('--max-total', type=float, default=500.00,
                        help='abort if this run would pay more than this (default 500.00)')
    parser.add_argument('--limit', type=int,
                        help='pay at most N participants this run (use 1 for a first test)')
    parser.add_argument('--ignore-stranded', action='store_true',
                        help='proceed even though the ledger has unreconciled setup rows')
    args = parser.parse_args()

    # --- ledger bookkeeping; neither needs the database ---
    if args.confirm_paid and args.discard:
        fail("--confirm-paid and --discard are mutually exclusive")
    if args.confirm_paid:
        changed = mark_paid(args.ledger, args.confirm_paid, from_states=('emitted', 'setup'))
        if not changed:
            fail(f"no unconfirmed rows for batch {args.confirm_paid} in {args.ledger}")
        rule(f"batch {args.confirm_paid}: {changed} row(s) marked paid")
        return
    if args.discard:
        dropped = discard_batch(args.ledger, args.discard)
        if not dropped:
            fail(f"no emitted rows for batch {args.discard} in {args.ledger}")
        rule(f"batch {args.discard}: {dropped} row(s) discarded, released for a later run")
        return

    if args.pay and not (args.study_id or args.submissions):
        fail("--pay needs a study id: pass --study-id, or tag each --submissions file "
             "STUDY_ID=path")
    if args.emit and args.pay:
        fail("--emit writes a sheet to paste by hand; --pay goes through the API. Pick one.")

    # --- load participants ---
    if args.from_csv:
        records = load_from_csv(args.from_csv, args.session_code)
        source = args.from_csv
    else:
        if not args.database_url:
            fail("no database URL: set $DATABASE_URL or pass --database-url (or --from-csv)")
        records = load_from_db(args.database_url, args.session_code)
        source = 'live database'

    rule(f"{source}: {len(records)} participant record(s)")

    owed = [r for r in records if pc.owed_bonus(r)]
    members_no_bonus = [r for r in records
                        if pc.is_market_member(r) and not pc.owed_bonus(r)]
    print(f"\nMarket members owed a bonus: {len(owed)}  "
          f"(total {sum(r['bonus'] for r in owed):.2f})")
    for rec in members_no_bonus:
        print(f"  WARNING: {rec['code']} is in market {rec['market_id']} but has no usable "
              f"bonus_payout; left for finalize_bonuses.py")

    # --- drop anyone the ledger already covers ---
    ledger = read_ledger(args.ledger)
    audit(records, owed, ledger)

    # --- hold back markets that are not exactly 8 ---
    # A market is assembled as exactly 8, so any other size means an assembly ran that should
    # not have and its allocation cannot be trusted. Nobody in it is paid from here; the whole
    # market is left for finalize_bonuses.py, which settles the extras as leftovers.
    markets = pc.markets_by_id(records)
    bad_markets = {mid for mid, members in markets.items()
                   if len(members) != allocation.NUM_PLAYERS}
    held = [r for r in owed if r['market_id'] in bad_markets]
    if held:
        owed = [r for r in owed if r['market_id'] not in bad_markets]
        print(f"\nHeld back, market not of size {allocation.NUM_PLAYERS} ({len(held)}) -- left "
              f"for finalize_bonuses.py:")
        for rec in sorted(held, key=lambda r: (r['market_id'], r['label'])):
            print(f"  {pc.payee(rec):<26} {rec['market_id']:<16} {rec['bonus']:>7.2f}")

    stranded = [row for row in ledger if row.get('state') == 'setup']
    unconfirmed = [row for row in ledger if row.get('state') == 'emitted']
    seen_codes = {row.get('participant_code') for row in ledger}
    seen_pids = {row.get('prolific_pid') for row in ledger if row.get('prolific_pid')}
    already = {r['code'] for r in owed
               if r['code'] in seen_codes or (r['label'] and r['label'] in seen_pids)}
    # Matched on PID alone: a different oTree record for someone already paid. With two
    # studies recruiting into one session that can be a second, genuinely earned bonus rather
    # than a repeat of the first, so it is named instead of just counted.
    pid_only = [r for r in owed if r['code'] in already and r['code'] not in seen_codes]
    owed = [r for r in owed if r['code'] not in already]
    print(f"\nAlready in {args.ledger}, skipped: {len(already)}")
    if pid_only:
        print(f"  of which {len(pid_only)} matched on Prolific PID but not participant code "
              f"-- check whether these are second bonuses that are still owed:")
        for rec in pid_only:
            print(f"    {pc.payee(rec):<26} {rec['code']:<10} {rec['market_id']:<16} "
                  f"{rec['bonus']:>7.2f}")

    if owed:
        print(f"\nOwed and not yet in the ledger ({len(owed)}):")
        for rec in sorted(owed, key=lambda r: (r['market_id'], r['label'])):
            print(f"  {pc.payee(rec):<26} {rec['code']:<10} {rec['market_id']:<16} "
                  f"{rec['bonus']:>7.2f}  session {rec['session_code']}")

    if unconfirmed:
        batches = sorted({row.get('bulk_payment_id') for row in unconfirmed})
        rule(f"{len(unconfirmed)} row(s) emitted but not confirmed paid")
        print("A sheet was written but the ledger does not know whether you pasted it into\n"
              "Prolific. Those participants are held back until you say. For each batch:\n")
        for batch in batches:
            n = sum(1 for row in unconfirmed if row.get('bulk_payment_id') == batch)
            amount = sum(float(row.get('amount') or 0) for row in unconfirmed
                         if row.get('bulk_payment_id') == batch)
            print(f"  {batch}  ({n} payment(s), {amount:.2f})")
            print(f"    paid it:     python3 pay_bonuses.py --confirm-paid {batch}")
            print(f"    never sent:  python3 pay_bonuses.py --discard {batch}")

    if stranded:
        rule(f"STOP: {len(stranded)} ledger row(s) stuck at state=setup")
        print("A previous run created a Prolific bonus batch but never confirmed the pay\n"
              "call. Because that endpoint is not idempotent this script will NOT retry\n"
              "them. Check each batch below in the Prolific dashboard, then edit the ledger\n"
              "state to 'paid' (it went through) or delete the rows (it did not).\n")
        for row in stranded:
            print(f"  batch {row.get('bulk_payment_id')}  {row.get('prolific_pid')}  "
                  f"{row.get('amount')}  {row.get('timestamp')}")
        if args.pay and not args.ignore_stranded:
            fail("refusing to pay with unreconciled rows; re-run with --ignore-stranded "
                 "once you have checked them")

    if not owed:
        rule("nothing to pay")
        return

    # --- resolve PID -> submission id ---
    if args.submissions:
        submissions = pc.load_submissions(args.submissions)
    elif args.token:
        if not args.study_id:
            fail("--study-id is needed to look submissions up through the API")
        api = Prolific(args.token)
        raw = []
        for study_id in args.study_id:
            rows = api.submissions(study_id)
            print(f"Prolific study {study_id}: {len(rows)} submission(s)")
            raw.extend(rows)
        submissions = best_submission_per_pid(raw)
    else:
        if args.pay or args.emit:
            fail("no way to resolve Submission IDs: pass --submissions with Prolific's "
                 "'Download demographic data' CSV, or --token to use the API")
        rule("no submission source -- reporting the selection only")
        for rec in sorted(owed, key=lambda r: (r['market_id'], r['label'])):
            print(f"  {pc.payee(rec):<26} {rec['market_id']:<16} {rec['bonus']:>7.2f}")
        print(f"\n{len(owed)} participant(s), {sum(r['bonus'] for r in owed):.2f} total")
        return

    payable, unmatched, unpayable = pc.resolve_payable(
        owed, submissions, bonus_of=lambda r: r['bonus'])
    pc.report_unresolved(unmatched, unpayable, amount_of=lambda r: r['bonus'])

    if args.limit is not None:
        payable = payable[:args.limit]

    if not payable:
        rule("nothing payable this run")
        return

    # A bonus only attaches to a submission through the study that owns it, so everything
    # downstream -- sheets, batches, API calls -- is grouped by study.
    by_study = {}
    for entry in payable:
        by_study.setdefault(entry[4], []).append(entry)

    rule(f"{len(payable)} bonus payment(s) across {len(by_study)} study(ies)")
    for study in sorted(by_study):
        print(f"\nstudy {study}:")
        for rec, amount, submission_id, status, _ in by_study[study]:
            print(f"  {pc.payee(rec):<26} {rec['market_id']:<16} {amount:>7.2f}  "
                  f"sub {submission_id}  [{status}]")
    total = sum(amount for _, amount, _, _, _ in payable)
    print(f"\n  {'TOTAL':<26} {'':<16} {total:>7.2f}")

    if total > args.max_total:
        fail(f"total {total:.2f} exceeds --max-total {args.max_total:.2f}; re-run with a "
             f"higher --max-total if that is genuinely expected")

    stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')

    # --- emit a sheet to paste into Prolific by hand ---
    if args.emit:
        pc.emit_sheets(payable, args.emit, args.ledger, stamp)
        return

    if not args.pay:
        rule("DRY RUN -- nothing was paid.")
        print(f"Write a sheet to paste:  --emit sheet.csv\n"
              f"Or pay through the API:  --token ... --study-id ... --pay")
        return

    # --- pay, one study at a time, one batch at a time ---
    known_studies = set(args.study_id or ())
    unknown = sorted(s for s in by_study if s not in known_studies)
    if unknown:
        fail(f"cannot pay through the API without real study ids for: {', '.join(unknown)}. "
             f"Tag each file --submissions STUDY_ID=path, or pass --study-id per study.")

    migrate_ledger(args.ledger)

    def ledger_rows(batch, bulk_id, state):
        return [dict(submission_id=submission_id, prolific_pid=rec['label'],
                     participant_code=rec['code'], market_id=rec['market_id'],
                     amount=f"{amount:.2f}", bulk_payment_id=bulk_id,
                     state=state, timestamp=stamp, study_id=study)
                for rec, amount, submission_id, _, study in batch]

    api = Prolific(args.token)
    for study in sorted(by_study):
        entries = by_study[study]
        for start in range(0, len(entries), BATCH_LIMIT):
            batch = entries[start:start + BATCH_LIMIT]
            pairs = [(submission_id, amount) for _, amount, submission_id, _, _ in batch]

            setup = api.setup_bonus(study, pairs)
            bulk_id = setup.get('id')
            if not bulk_id:
                fail(f"bonus setup returned no id: {setup}")
            # Prolific quotes these in cents.
            print(f"\nstudy {study} batch {bulk_id}: {len(batch)} payment(s), "
                  f"amount {setup.get('amount', 0) / 100:.2f}, "
                  f"fees {setup.get('fees', 0) / 100:.2f}, "
                  f"total {setup.get('total_amount', 0) / 100:.2f}")

            # Written before the money moves: if the pay call dies mid-flight the ledger still
            # names the batch, and the next run stops rather than paying it again.
            append_ledger(args.ledger, ledger_rows(batch, bulk_id, 'setup'))

            api.pay_bonus(bulk_id)
            mark_paid(args.ledger, bulk_id)
            print(f"batch {bulk_id}: paid")

    rule(f"paid {len(payable)} bonus(es), {total:.2f} total; ledger: {args.ledger}")
    print("Prolific processes bulk bonuses asynchronously -- allow a few minutes, then\n"
          "confirm the amounts against each study's Bonuses page.")


if __name__ == '__main__':
    main()
