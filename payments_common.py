"""Shared payment vocabulary for finalize_bonuses.py and pay_bonuses.py.

Both scripts have to answer the same question -- "is this participant a market member who is
owed a bonus?" -- from two different sources: an exported oTree wide CSV and the live
Postgres ``otree_participant`` table. Everything they agree on lives here so the two cannot
drift apart and pay different people.

A *record* is the normalised participant, produced by ``record_from_csv_row`` or
``record_from_vars``, with the fields the payment decision depends on:

    code, label, session_code, treatment, bucket, market_id, bonus,
    screened_out, failed_quiz, study_completed

plus the four a *post-hoc* market needs, which the payment decision itself never reads:

    role, is_lowest, vals_by_round, ranking_by_round

They ride along on the record so reassemble.py can build a market out of finishers no live
market claimed without a second, differently-shaped view of the same participant.

``bonus`` is in US dollars: survey/__init__.py converts the market payoff from Crowns
(allocation.crowns_to_usd) before writing ``bonus_payout``.

Both scripts also have to turn a Prolific PID into a *Submission ID* and record what they
paid, so submission resolution and the payment ledger live here too. They share one ledger
file: pay_bonuses.py settles closed markets while the study runs, finalize_bonuses.py settles
the leftovers at the end, and neither can pay someone the other already has.
"""
import ast
import csv
import json
import os
import sys

# A submission has to be one of these for a bonus to attach to it.
PAYABLE_STATUSES = ('APPROVED', 'AWAITING REVIEW')
# Preference when a PID somehow has more than one submission on the study.
STATUS_PREFERENCE = ('APPROVED', 'AWAITING REVIEW')

LEDGER_FIELDS = [
    'submission_id', 'prolific_pid', 'participant_code', 'market_id',
    'amount', 'bulk_payment_id', 'state', 'timestamp', 'study_id',
]


# --- console ---------------------------------------------------------------
def rule(title):
    print('\n' + '=' * 78)
    print(title)
    print('=' * 78)


def fail(message):
    sys.exit(f"{os.path.basename(sys.argv[0]) or 'payments'}: {message}")


# --- cell parsing ----------------------------------------------------------
def money(value):
    """Parse a currency-ish value; '' and junk both mean 'no bonus recorded'.

    Accepts the strings a CSV export produces and the numbers the database stores.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = (value or '').strip().replace('$', '').replace(',', '')
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def cell(row, key):
    return (row.get('participant.' + key, '') or '').strip()


def flag(row, key):
    """oTree exports booleans as '1'/'0'/'True'/'False'/''."""
    return cell(row, key).lower() in ('1', 'true')


def mapping(value):
    """Parse a dict-valued participant var; anything unreadable means 'no rounds recorded'.

    oTree exports these as Python reprs ("{'1': [15, 13, ...]}"), but be forgiving about JSON
    too -- a dict that arrives already decoded (the database path) is passed straight through.
    """
    if isinstance(value, dict):
        return value
    text = (value or '').strip()
    if not text:
        return {}
    for parse in (ast.literal_eval, json.loads):
        try:
            parsed = parse(text)
        except (ValueError, SyntaxError, TypeError):
            continue
        if isinstance(parsed, dict):
            return parsed
    return {}


# --- record normalisation --------------------------------------------------
def record_from_csv_row(row):
    """Normalise one row of an oTree 'all apps' wide export."""
    return dict(
        code=cell(row, 'code'),
        label=cell(row, 'label'),
        session_code=(row.get('session.code', '') or '').strip(),
        treatment=cell(row, 'treatment'),
        bucket=cell(row, 'bucket'),
        market_id=cell(row, 'market_id'),
        bonus=money(cell(row, 'bonus_payout')),
        screened_out=flag(row, 'screened_out'),
        failed_quiz=flag(row, 'failed_quiz'),
        study_completed=flag(row, 'study_completed'),
        role=cell(row, 'role'),
        is_lowest=flag(row, 'is_lowest'),
        vals_by_round=mapping(cell(row, 'market_vals')),
        ranking_by_round=mapping(cell(row, 'market_ranking')),
    )


def record_from_vars(code, label, session_code, pvars):
    """Normalise one decoded ``otree_participant._vars`` dict."""
    pvars = pvars or {}
    return dict(
        code=(code or '').strip(),
        label=(label or '').strip(),
        session_code=(session_code or '').strip(),
        treatment=str(pvars.get('treatment') or '').strip(),
        bucket=str(pvars.get('bucket') or '').strip(),
        market_id=str(pvars.get('market_id') or '').strip(),
        bonus=money(pvars.get('bonus_payout')),
        screened_out=bool(pvars.get('screened_out')),
        failed_quiz=bool(pvars.get('failed_quiz')),
        study_completed=bool(pvars.get('study_completed')),
        role=str(pvars.get('role') or '').strip(),
        is_lowest=bool(pvars.get('is_lowest')),
        vals_by_round=mapping(pvars.get('market_vals')),
        ranking_by_round=mapping(pvars.get('market_ranking')),
    )


# --- the payment decision --------------------------------------------------
def is_market_member(rec):
    """A usable finisher whose group of 8 assembled.

    ``market_id`` is written in the same block as ``bonus_payout`` when a market closes
    (survey/__init__.py), so a set market_id already implies the market completed.
    """
    return bool(
        rec['treatment']
        and not rec['screened_out']
        and not rec['failed_quiz']
        and rec['market_id']
    )


def owed_bonus(rec):
    """A market member with a real, positive bonus recorded against them."""
    return is_market_member(rec) and rec['bonus'] is not None and rec['bonus'] > 0


def payee(rec):
    """Prolific identifies participants by the label passed in the start URL. Fall back to
    the oTree code so a session run without labels still produces a usable sheet."""
    return rec['label'] or rec['code']


def markets_by_id(records):
    """{market_id: [record, ...]} over every market member, sized or not.

    A market is assembled as exactly 8 (survey/__init__.py), so any other size means an
    assembly ran that should not have. Both scripts group this way -- one to hold those
    members back from payment, the other to work out which of them to settle -- so the
    grouping lives here.
    """
    markets = {}
    for rec in records:
        if is_market_member(rec):
            markets.setdefault(rec['market_id'], []).append(rec)
    return markets


# --- ledger ----------------------------------------------------------------
def read_ledger(path):
    if not os.path.exists(path):
        return []
    with open(path, newline='', encoding='utf-8') as fh:
        return list(csv.DictReader(fh))


def migrate_ledger(path):
    """Bring an older ledger up to LEDGER_FIELDS before anything is appended to it.

    append_ledger only writes a header when the file is new, so a ledger written before a
    column was added would take the new, wider rows under its old, narrower header and every
    value after the missing column would land in the wrong place. Rewriting once (atomically,
    and only when the header actually differs) keeps the historical rows readable and leaves
    the new column empty for them.
    """
    if not os.path.exists(path):
        return
    with open(path, newline='', encoding='utf-8') as fh:
        header = next(csv.reader(fh), None)
    if header is None or header == LEDGER_FIELDS:
        return
    missing = [name for name in LEDGER_FIELDS if name not in header]
    unknown = [name for name in header if name not in LEDGER_FIELDS]
    if unknown:
        fail(f"{path} has unexpected column(s) {', '.join(unknown)}; refusing to rewrite a "
             f"ledger this script did not write")
    rewrite_ledger(path, read_ledger(path))
    print(f"{path}: added column(s) {', '.join(missing)} to the existing ledger")


def append_ledger(path, rows):
    """Append and fsync. Called *before* the money moves, never after."""
    is_new = not os.path.exists(path)
    with open(path, 'a', newline='', encoding='utf-8') as fh:
        writer = csv.DictWriter(fh, fieldnames=LEDGER_FIELDS)
        if is_new:
            writer.writeheader()
        writer.writerows(rows)
        fh.flush()
        os.fsync(fh.fileno())


def rewrite_ledger(path, rows):
    tmp = path + '.tmp'
    with open(tmp, 'w', newline='', encoding='utf-8') as fh:
        writer = csv.DictWriter(fh, fieldnames=LEDGER_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


def mark_paid(path, bulk_payment_id, from_states=('setup',)):
    rows = read_ledger(path)
    changed = 0
    for row in rows:
        if row.get('bulk_payment_id') == bulk_payment_id and row.get('state') in from_states:
            row['state'] = 'paid'
            changed += 1
    rewrite_ledger(path, rows)
    return changed


def discard_batch(path, bulk_payment_id):
    """Drop an emitted batch that was never pasted, releasing those people to be paid later."""
    rows = read_ledger(path)
    keep, dropped = [], 0
    for row in rows:
        if row.get('bulk_payment_id') == bulk_payment_id and row.get('state') == 'emitted':
            dropped += 1
        else:
            keep.append(row)
    rewrite_ledger(path, keep)
    return dropped


def ledger_covers(ledger):
    """(codes, pids) already settled, in whatever state.

    A row stuck at 'setup' may or may not have gone through, so it counts as covered here too
    and is reconciled by hand rather than risking a second payment.
    """
    codes = {(r.get('participant_code') or '').strip() for r in ledger}
    pids = {(r.get('prolific_pid') or '').strip() for r in ledger}
    return codes - {''}, pids - {''}


def already_settled(rec, codes, pids):
    return rec['code'] in codes or bool(rec['label'] and rec['label'] in pids)


# --- Prolific submissions --------------------------------------------------
def _find_column(fieldnames, *words):
    """Locate a header cell containing all of ``words``. Prolific's export has varied over
    time between 'Submission id', 'Submission ID' and 'submission_id'."""
    for name in fieldnames or []:
        flat = ''.join(ch for ch in (name or '').lower() if ch.isalnum())
        if all(word in flat for word in words):
            return name
    return None


def parse_submissions_arg(spec):
    """'<study id>=<path>' or a bare '<path>'. Returns (study, path).

    The demographic export has no study column, so which study a file describes is only
    knowable from the command line. A bare path still identifies the study well enough to keep
    its sheet separate -- it just cannot be handed to the API, which wants the real id.
    """
    study, sep, path = spec.partition('=')
    if not sep:
        path = spec
        study = os.path.splitext(os.path.basename(spec))[0]
    if not path:
        fail(f"--submissions {spec!r}: no file path")
    return study.strip(), path


def submissions_from_csv(path, study):
    """Read Prolific's 'Download demographic data' export for one study.

    Returns a list of raw submission dicts tagged with ``study``; merging several studies is
    best_submission_per_pid's job, so the CSV and API paths stay interchangeable downstream.
    """
    with open(path, newline='', encoding='utf-8-sig') as fh:
        rows = list(csv.DictReader(fh))
    if not rows:
        fail(f"{path} is empty")

    fields = list(rows[0].keys())
    sub_col = _find_column(fields, 'submission', 'id')
    pid_col = _find_column(fields, 'participant', 'id')
    status_col = _find_column(fields, 'status')
    if not sub_col or not pid_col:
        fail(f"{path} has no Submission id / Participant id columns (found: "
             f"{', '.join(fields[:8])}...). Use the study's 'Download demographic data' "
             f"export, not the oTree export.")

    if not status_col:
        print(f"WARNING: {path} has no status column; submission statuses cannot be "
              f"checked, so returned/rejected submissions will not be filtered out.")

    raw = [{'id': (r.get(sub_col) or '').strip(),
            'participant_id': (r.get(pid_col) or '').strip(),
            'status': (r.get(status_col) or '').strip() if status_col else 'APPROVED',
            'study': study}
           for r in rows]
    return [s for s in raw if s['id'] and s['participant_id']]


def load_submissions(specs):
    """Resolve every --submissions entry into one {pid: (submission_id, status, study)} map."""
    raw = []
    for spec in specs:
        study, path = parse_submissions_arg(spec)
        rows = submissions_from_csv(path, study)
        print(f"{path}: {len(rows)} submission(s) for study {study}")
        raw.extend(rows)
    return best_submission_per_pid(raw)


def normalise_status(status):
    return ' '.join(str(status or '').replace('_', ' ').replace('-', ' ').upper().split())


def best_submission_per_pid(submissions):
    """One submission per participant, preferring the one a bonus can attach to.

    Returns {pid: (submission_id, status, study)}. ``submissions`` may span several studies
    (a duplicated study recruits into the same oTree session), so a PID can legitimately
    appear more than once; that is reported rather than silently collapsed, because paying
    the wrong study's submission is not an error Prolific will catch for you.
    """
    best, studies_per_pid = {}, {}
    for sub in submissions:
        pid = sub.get('participant_id') or sub.get('participant')
        if not pid:
            continue
        study = sub.get('study') or sub.get('study_id') or ''
        status = normalise_status(sub.get('status'))
        rank = (STATUS_PREFERENCE.index(status)
                if status in STATUS_PREFERENCE else len(STATUS_PREFERENCE))
        studies_per_pid.setdefault(pid, set()).add(study)
        current = best.get(pid)
        if current is None or rank < current[0]:
            best[pid] = (rank, sub.get('id'), status, study)

    crossed = sorted(pid for pid, seen in studies_per_pid.items() if len(seen) > 1)
    if crossed:
        print(f"\nWARNING: {len(crossed)} Prolific PID(s) have a submission on more than one "
              f"study. Only the best-status one is used, so a bonus earned on the other\n"
              f"study will not be paid by this run. Check these by hand:")
        for pid in crossed[:20]:
            print(f"  {pid}  studies: {', '.join(sorted(studies_per_pid[pid]))}  "
                  f"using {best[pid][1]} [{best[pid][2]}] from {best[pid][3]}")
        if len(crossed) > 20:
            print(f"  ... and {len(crossed) - 20} more")

    return {pid: (sid, status, study) for pid, (_, sid, status, study) in best.items()}


def resolve_payable(recs, submissions, bonus_of):
    """Split ``recs`` into (payable, unmatched, unpayable) against a submissions map.

    ``bonus_of(rec)`` supplies the amount, because pay_bonuses.py pays the stored bonus while
    finalize_bonuses.py may pay a treatment mean. Returns payable entries of
    ``(rec, amount, submission_id, status, study)``.
    """
    payable, unmatched, unpayable = [], [], []
    for rec in sorted(recs, key=lambda r: (r['market_id'], r['label'])):
        pid = rec['label']
        found = submissions.get(pid)
        if not pid or not found:
            unmatched.append(rec)
            continue
        submission_id, status, study = found
        if status in PAYABLE_STATUSES:
            payable.append((rec, bonus_of(rec), submission_id, status, study))
        else:
            unpayable.append((rec, status))
    return payable, unmatched, unpayable


def report_unresolved(unmatched, unpayable, amount_of):
    """Print the two 'NOT paid' groups both scripts produce, identically."""
    if unmatched:
        print(f"\nNo Prolific submission found ({len(unmatched)}) -- NOT paid:")
        for rec in unmatched:
            print(f"  {payee(rec):<26} {rec['market_id']:<16} {amount_of(rec):>7.2f}")
        print("  If a second study is recruiting into this session, pass its "
              "'Download demographic data'\n  export too: --submissions "
              "STUDY_A=a.csv STUDY_B=b.csv")
    if unpayable:
        print(f"\nSubmission not in a payable state ({len(unpayable)}) -- NOT paid:")
        for rec, status in unpayable:
            print(f"  {payee(rec):<26} {rec['market_id']:<16} "
                  f"{amount_of(rec):>7.2f}  [{status}]")


def emit_sheets(payable, out_path, ledger_path, stamp, market_of=None):
    """Write one paste-ready sheet per study and record the rows as 'emitted'.

    ``payable`` is resolve_payable's output. A bonus only attaches to a submission through the
    study that owns it, so a run spanning two studies produces two sheets and two batch ids --
    Prolific's paste box belongs to a single study and rejects ids that are not its own. With
    one study the caller's exact path and an unsuffixed batch id are kept, so single-study
    workflows are unchanged.

    Rows go in as 'emitted', never 'paid': the money has not moved until the sheet is pasted
    and --confirm-paid is run.

    ``market_of(rec)`` supplies the ledger's market_id column, which records *what the payment
    was for*, not merely where the participant is stored. A leftover paid a treatment mean must
    not be recorded against a market -- otherwise it looks like a member of it, and the next run
    can no longer tell which participants were paid as that market.
    """
    market_of = market_of or (lambda rec: rec['market_id'])
    by_study = {}
    for entry in payable:
        by_study.setdefault(entry[4], []).append(entry)

    migrate_ledger(ledger_path)
    stem, ext = os.path.splitext(out_path)
    single = len(by_study) == 1

    rule(f"{len(by_study)} sheet(s) written")
    for study in sorted(by_study):
        batch = by_study[study]
        path = out_path if single else f"{stem}-{study}{ext}"
        batch_id = f"sheet-{stamp}" if single else f"sheet-{stamp}-{study}"
        with open(path, 'w', newline='', encoding='utf-8') as fh:
            # Prolific's paste box wants bare "<submission id>,<amount>" lines, no header.
            for _, amount, submission_id, _, _ in batch:
                fh.write(f"{submission_id},{amount:.2f}\n")
            fh.flush()
            os.fsync(fh.fileno())
        append_ledger(ledger_path, [
            dict(submission_id=submission_id, prolific_pid=rec['label'],
                 participant_code=rec['code'], market_id=market_of(rec),
                 amount=f"{amount:.2f}", bulk_payment_id=batch_id, state='emitted',
                 timestamp=stamp, study_id=study)
            for rec, amount, submission_id, _, _ in batch])

        subtotal = sum(amount for _, amount, _, _, _ in batch)
        print(f"\n{path}: {len(batch)} payment(s), {subtotal:.2f} total, batch {batch_id}\n"
              f"  1. Prolific -> study {study} -> Bulk actions -> Bulk bonus payment\n"
              f"  2. Paste the contents of {path}, then click Pay Bonuses\n"
              f"  3. python3 {os.path.basename(sys.argv[0])} --confirm-paid {batch_id}")
    print(f"\nUntil confirmed, these {len(payable)} participant(s) are held back from\n"
          f"further runs. If a sheet is never pasted: "
          f"python3 {os.path.basename(sys.argv[0])} --discard <batch id>")
    return by_study
