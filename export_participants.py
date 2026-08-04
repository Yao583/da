#!/usr/bin/env python3
"""export_participants.py -- dump the live oTree participants as a wide CSV.

    export DATABASE_URL="$(heroku config:get DATABASE_URL -a da-prolific)"
    python3 export_participants.py -o all_apps_final.csv

Produces the ``participant.*`` columns finalize_bonuses.py reads, straight from Postgres, so
the end-of-study settlement does not depend on driving the oTree admin's export page. The
shape matches a real oTree "all apps" wide export closely enough for
``payments_common.record_from_csv_row``: dict-valued participant vars are written as Python
reprs, exactly as oTree writes them.

Two columns exist only here and are what a re-assembly needs beyond the payment decision:
``participant.role`` / ``participant.is_lowest`` (the market slot the router assigned) and
``participant.market_vals`` / ``participant.market_ranking`` (what the participant saw and
submitted). ``session.paying_round`` is lifted out of ``otree_session._vars`` and repeated on
every row, because the paying round is a session-level draw that the per-participant export
would otherwise lose.

Read-only: the only statements issued are SELECTs, and the only thing written is the CSV.

Rows with no ``treatment`` are skipped. They are unused participant slots -- a session sized
for 11,000 arrivals holds thousands of them -- and nothing downstream can owe them anything.
"""

import argparse
import csv
import os
import sys

# decode_vars/_VarsUnpickler already solve "read participant.vars without oTree installed",
# including the Currency-inside-a-pickle case. Importing them keeps one decoder in the tree.
from pay_bonuses import decode_vars
from payments_common import fail

# The participant vars worth exporting, in the order they appear in an oTree wide export.
# 'label' and 'code' are columns on otree_participant itself, not vars, so they are not here.
VAR_COLUMNS = [
    'treatment', 'role', 'is_lowest', 'bucket', 'screened_out', 'market_id', 'market_pid',
    'market_vals', 'market_ranking', 'market_detail', 'bonus_payout', 'failed_quiz',
    'suspected_bot', 'study_completed', 'total_payment',
]

FIELDNAMES = (['participant.code', 'participant.label']
              + [f'participant.{name}' for name in VAR_COLUMNS]
              + ['session.code', 'session.paying_round'])


def format_value(value):
    """Render one participant var the way oTree's exporter does.

    Booleans become '1'/'0' (``payments_common.flag`` accepts either that or 'True'), dicts and
    lists become Python reprs (``record_from_csv_row`` parses them back with literal_eval), and
    a missing var becomes '' rather than 'None' -- ``money('')`` reads that as "nothing
    recorded", while 'None' would just be junk.
    """
    if value is None:
        return ''
    if isinstance(value, bool):
        return '1' if value else '0'
    if isinstance(value, (dict, list)):
        return repr(value)
    return str(value)


def fetch(database_url, session_code=None):
    """(participant rows, {session code: paying round}) from Postgres."""
    try:
        import psycopg2
    except ImportError:
        fail('psycopg2 is not installed; pip install psycopg2-binary')

    query = ('SELECT code, label, _session_code, _vars FROM otree_participant '
             'WHERE _vars IS NOT NULL')
    params = []
    if session_code:
        query += ' AND _session_code = %s'
        params.append(session_code)

    conn = psycopg2.connect(database_url, sslmode='require')
    try:
        with conn.cursor() as cur:
            cur.execute(query, params)
            participants = cur.fetchall()
            # The paying round is drawn once per session by the router and is what
            # compute_market_bonuses reads a payoff out of, so a re-assembly cannot be done
            # without it.
            cur.execute('SELECT code, _vars FROM otree_session')
            sessions = cur.fetchall()
    finally:
        conn.close()

    paying_rounds = {}
    for code, blob in sessions:
        svars = decode_vars(blob) or {}
        if svars.get('paying_round') is not None:
            paying_rounds[code] = svars['paying_round']
    return participants, paying_rounds


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('-o', '--out', default='all_apps_final.csv',
                        help='where to write the wide CSV')
    parser.add_argument('--database-url', default=os.environ.get('DATABASE_URL'),
                        help='Postgres URL; defaults to $DATABASE_URL')
    parser.add_argument('--session-code', help='restrict to one oTree session')
    parser.add_argument('--all-rows', action='store_true',
                        help='keep participants with no treatment (unused session slots), '
                             'which are skipped by default')
    args = parser.parse_args()

    if not args.database_url:
        fail('no --database-url and no $DATABASE_URL; '
             'export DATABASE_URL="$(heroku config:get DATABASE_URL -a <app>)"')

    participants, paying_rounds = fetch(args.database_url, args.session_code)
    print(f'otree_participant: {len(participants)} row(s) with vars')
    for code, rnd in sorted(paying_rounds.items()):
        print(f'  session {code}: paying_round = {rnd}')
    if not paying_rounds:
        # Not fatal here -- the export is still a valid record of who did what -- but nothing
        # downstream can compute a market bonus from it without being told the round.
        print('  WARNING: no session records a paying_round; finalize_bonuses.py will need '
              '--paying-round')

    written = skipped = undecodable = 0
    with open(args.out, 'w', newline='', encoding='utf-8') as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDNAMES)
        writer.writeheader()
        for code, label, session_code, blob in participants:
            pvars = decode_vars(blob)
            if pvars is None:
                # Surfaced rather than swallowed: an unreadable row would otherwise look like
                # a participant who was never routed and quietly go unpaid.
                undecodable += 1
                pvars = {}
            if not pvars.get('treatment') and not args.all_rows:
                skipped += 1
                continue
            row = {'participant.code': code or '',
                   'participant.label': (label or '').strip(),
                   'session.code': session_code or '',
                   'session.paying_round': format_value(paying_rounds.get(session_code))}
            for name in VAR_COLUMNS:
                row[f'participant.{name}'] = format_value(pvars.get(name))
            writer.writerow(row)
            written += 1
        fh.flush()
        os.fsync(fh.fileno())

    if undecodable:
        print(f'WARNING: could not decode participant.vars for {undecodable} row(s); they are '
              f'exported with empty vars and cannot be assessed for payment')
    print(f'{args.out}: {written} row(s) written, {skipped} unrouted slot(s) skipped')


if __name__ == '__main__':
    sys.exit(main())
