"""
finalize_bonuses.py -- turn an exported oTree "all apps" wide CSV into a Prolific
bonus sheet, and pay the finishers whose market never closed.

    python3 finalize_bonuses.py [path/to/all_apps.csv] [-o bonuses.csv]

Read-only: it never touches the oTree database. Every payment decision is printed
so it can be checked before anything is uploaded.

Four disjoint groups appear in the export, and only the first two are ever paid a bonus:

    market member   assembled into a group of 8; bonus = participant.bonus_payout,
                    computed post-hoc by allocation.compute_market_bonuses
    leftover        usable finisher, queued, but their market never closed. A bucket
                    overfills whenever a slow reader's slot times out in the router and
                    gets refilled, so a treatment can end at (say) 4 A_normal against a
                    target of 3. That extra finisher was promised a bonus on ThankYou and
                    there is no market to compute one from, so they are paid the MEAN
                    realised bonus of their own treatment (all treatments pooled if their
                    arm assembled no market at all).
    no bonus        quiz-fails and suspected bots: they reach ThankYou and are paid the
                    base payment via Prolific, but their data is unusable
    screened out    the study was full when they arrived. They were stopped before Consent,
                    shown no completion code, and asked to return the submission -- so they
                    are not paid and never appear in the bonus sheet.

The bonus column is in the study's real-world currency (participation fee aside); the
paying round is the same for everyone in the session and is drawn once by the router.
"""

import argparse
import ast
import collections
import csv
import json
import os
import sys


# --- helpers ---------------------------------------------------------------
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


def cell(row, key):
    return (row.get('participant.' + key, '') or '').strip()


def flag(row, key):
    """oTree exports booleans as '1'/'0'/'True'/'False'/''."""
    return cell(row, key).lower() in ('1', 'true')


def money(value):
    """Parse a currency-ish cell; '' and junk both mean 'no bonus recorded'."""
    text = (value or '').strip().replace('$', '').replace(',', '')
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def rule(title):
    print('\n' + '=' * 78)
    print(title)
    print('=' * 78)


# --- classification --------------------------------------------------------
def classify(rows):
    """Split the export into the four groups. Returns (members, leftovers, no_bonus,
    screened, ignored) lists of rows."""
    members, leftovers, no_bonus, screened, ignored = [], [], [], [], []
    for row in rows:
        if flag(row, 'screened_out'):
            screened.append(row)
            continue
        if not cell(row, 'treatment'):
            # Never routed: an unused participant slot, or someone who closed the tab on
            # the router page before it auto-submitted. Nothing owed either way.
            ignored.append(row)
            continue
        if flag(row, 'failed_quiz') or flag(row, 'suspected_bot'):
            no_bonus.append(row)
            continue
        if cell(row, 'market_id'):
            members.append(row)
        elif flag(row, 'study_completed'):
            # Finished and usable, but no market closed around them.
            leftovers.append(row)
        else:
            # Silent dropout: never reached ThankYou, so no completion code and no
            # Prolific submission to bonus.
            ignored.append(row)
    return members, leftovers, no_bonus, screened, ignored


def treatment_means(members):
    """Mean realised bonus per treatment, plus the pooled mean over all treatments."""
    per = collections.defaultdict(list)
    for row in members:
        amount = money(cell(row, 'bonus_payout'))
        if amount is not None:
            per[cell(row, 'treatment')].append(amount)
    means = {t: sum(v) / len(v) for t, v in per.items() if v}
    pooled_values = [x for v in per.values() for x in v]
    pooled = sum(pooled_values) / len(pooled_values) if pooled_values else 0.0
    return means, pooled


def payee(row):
    """Prolific identifies participants by the label passed in the start URL. Fall back
    to the oTree code so a session run without labels still produces a usable sheet."""
    label = cell(row, 'label')
    return label or cell(row, 'code')


# --- report ----------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('csv_path', nargs='?', default='all_apps.csv',
                        help='exported oTree "all apps" wide CSV')
    parser.add_argument('-o', '--out', default='bonuses.csv',
                        help='where to write the Prolific bonus sheet')
    args = parser.parse_args()

    if not os.path.exists(args.csv_path):
        sys.exit(f"no such file: {args.csv_path}")

    with open(args.csv_path, newline='', encoding='utf-8-sig') as fh:
        rows = list(csv.DictReader(fh))
    if not rows or 'participant.code' not in rows[0]:
        sys.exit(f"{args.csv_path} does not look like an oTree 'all apps' wide export")

    members, leftovers, no_bonus, screened, ignored = classify(rows)
    means, pooled = treatment_means(members)

    rule(f"{args.csv_path}: {len(rows)} participant rows")

    # --- markets ---
    markets = collections.defaultdict(list)
    for row in members:
        markets[cell(row, 'market_id')].append(row)

    print("\nMarkets assembled")
    by_treatment = collections.Counter(mid.rsplit('-', 1)[0] for mid in markets)
    for treatment in sorted(by_treatment):
        mean = means.get(treatment)
        mean_text = f", mean bonus {mean:.2f}" if mean is not None else ""
        print(f"  {treatment:<14} {by_treatment[treatment]} market(s){mean_text}")
    short = [mid for mid, m in markets.items() if len(m) != 8]
    if short:
        print(f"  WARNING: markets not of size 8: "
              f"{', '.join(f'{mid} ({len(markets[mid])})' for mid in sorted(short))}")

    # --- payments ---
    payments = []
    for row in members:
        amount = money(cell(row, 'bonus_payout'))
        if amount is None:
            # A market member with no stored bonus should be impossible; surface it
            # rather than silently paying 0.
            print(f"  WARNING: {cell(row, 'code')} is in market {cell(row, 'market_id')} "
                  f"but has no bonus_payout; treating as leftover")
            leftovers.append(row)
            continue
        payments.append((payee(row), amount, f"market {cell(row, 'market_id')}"))

    if leftovers:
        print(f"\nLeftovers: {len(leftovers)} usable finisher(s) with no market")
    for row in leftovers:
        treatment = cell(row, 'treatment')
        amount = means.get(treatment)
        basis = f"mean {treatment} bonus"
        if amount is None:
            amount, basis = pooled, "mean bonus across all treatments"
        amount = round(amount, 2)
        print(f"  {payee(row):<26} {cell(row, 'bucket'):<10} paid {amount:>6.2f}  ({basis})")
        payments.append((payee(row), amount, f"leftover, {basis}"))

    # --- everyone else ---
    print(f"\nNo bonus (base payment only): {len(no_bonus)} "
          f"(quiz-fail {sum(1 for r in no_bonus if flag(r, 'failed_quiz'))}, "
          f"suspected bot {sum(1 for r in no_bonus if flag(r, 'suspected_bot'))})")

    print(f"\nScreened out (study full): {len(screened)} -- pay nothing, do NOT reject. "
          f"They were shown no completion code and asked to return the submission.")
    for row in screened:
        recorded = money(cell(row, 'total_payment'))
        if recorded:
            print(f"  NOTE: {payee(row)} exports total_payment={recorded} but is owed 0")

    print(f"\nNot routed / silent dropout, nothing owed: {len(ignored)}")

    # --- sheet ---
    with open(args.out, 'w', newline='', encoding='utf-8') as fh:
        writer = csv.writer(fh)
        writer.writerow(['participant_label', 'bonus', 'reason'])
        for label, amount, reason in payments:
            writer.writerow([label, f"{amount:.2f}", reason])

    total = sum(amount for _, amount, _ in payments)
    rule(f"wrote {args.out}: {len(payments)} bonus payments, {total:.2f} total")


if __name__ == '__main__':
    main()
