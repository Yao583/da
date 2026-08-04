"""reassemble.py -- form markets, post hoc, out of the finishers no live market claimed.

The live app assembles a market the moment a treatment has 3 A_normal + 1 A_lowest +
3 B_normal + 1 B_lowest waiting (survey/__init__.py). When the study stops, whatever is left in
those queues is stranded: they finished, they are owed a bonus, and there is no market to
compute one from. This module builds markets out of that residue so they can be paid a real
bonus rather than an average, and reports who still cannot be placed.

The composition is deliberately *not* relaxed. Each treatment app tells the designated member
"You have the lowest prize priority among the four participants in Group X" and tells everyone
else they do not (da/Decision.html and its seven siblings). Only 3/1/3/1 keeps both statements
true of the market that actually gets paid, so a market is either exactly that shape or it is
not formed at all. Because a market consumes three normals per lowest, the residue skews
heavily lowest and most treatments will form nothing -- that is the honest answer, and the
caller pays those participants a flat fee instead.

Everything here is pure: no database, no files, no clock. ``assemble`` is deterministic given
its ``seed``, and the market ids it mints continue the session's existing sequence, so a rerun
after an interruption recomputes the identical allocation and the identical amounts rather than
quietly paying different numbers.
"""
import collections
import random

import allocation


def next_market_indices(records):
    """{treatment: next free index} from the market ids already in the export.

    The same rule as survey/__init__.py's ``_next_market_index``: ids already written on
    participants are the authority on what has been used, so a new market can never collide
    with one that was assembled live (``da-1..da-3`` -> ``da-4``).
    """
    highest = collections.defaultdict(int)
    for rec in records:
        market_id = (rec.get('market_id') or '').strip()
        treatment, sep, suffix = market_id.rpartition('-')
        if sep and suffix.isdigit():
            highest[treatment] = max(highest[treatment], int(suffix))
    return {t: highest[t] + 1 for t in allocation.TREATMENTS}


def member_of(rec):
    """One record as compute_market_bonuses wants it.

    ``role``/``is_lowest`` come from the router, ``market_vals``/``market_ranking`` from play.
    A missing round leaves a gap that scores 0 for that round only, which is why the caller
    checks the paying round is present before trusting the result.
    """
    return dict(
        code=rec['code'],
        role=rec['role'] or 'A',
        is_lowest=bool(rec['is_lowest']),
        vals_by_round=rec['vals_by_round'] or {},
        ranking_by_round=rec['ranking_by_round'] or {},
    )


def assemble(pool, paying_round, seed, crown_value_usd, start_indices=None):
    """Form every 3/1/3/1 market the pool supports. Returns (markets, leftovers).

    ``pool`` is normalised records (payments_common.record_from_csv_row). Each market is
    ``{'market_id', 'treatment', 'members'}`` where ``members`` is a list of
    ``(record, market_pid, bonus_usd)`` in slot order 1..8. ``leftovers`` is everyone the
    composition rule could not place, in input order.

    ``crown_value_usd`` is passed in rather than read from ``allocation``: the rate that
    matters is the one the *deployed* app paid the rest of the study at, which is not
    necessarily the one in the working copy, and paying half of what everyone else got is not
    an error a sheet of bare numbers would ever show you. The caller establishes it from the
    export and states it out loud.

    Slots are filled in ``allocation.BUCKETS`` order, matching a live assembly, so a market's
    ``market_pid`` means the same thing here as it does on a participant assembled during the
    study -- and with ``market_id`` as the RNG seed that makes the whole allocation
    reconstructable from the exported data.
    """
    indices = dict(start_indices or {})
    by_treatment = collections.defaultdict(lambda: collections.defaultdict(list))
    order = {rec['code']: i for i, rec in enumerate(pool)}
    for rec in pool:
        if rec['treatment'] in allocation.TREATMENTS and rec['bucket'] in allocation.BUCKETS:
            by_treatment[rec['treatment']][rec['bucket']].append(rec)

    placed, markets = set(), []
    for treatment in allocation.TREATMENTS:
        buckets = by_treatment.get(treatment)
        if not buckets:
            continue
        # Per-treatment RNG so adding or removing a treatment's participants cannot reshuffle
        # another treatment's markets, and the whole run stays reproducible from one --seed.
        rng = random.Random(f'{seed}-{treatment}')
        queues = {}
        for bucket in allocation.BUCKETS:
            queue = sorted(buckets.get(bucket, []), key=lambda r: r['code'])
            rng.shuffle(queue)
            queues[bucket] = queue

        need = allocation.PER_MARKET
        while all(len(queues[b]) >= need[b] for b in allocation.BUCKETS):
            picked = []
            for bucket in allocation.BUCKETS:
                for _ in range(need[bucket]):
                    picked.append(queues[bucket].pop(0))

            index = indices.get(treatment, 1)
            indices[treatment] = index + 1
            market_id = f'{treatment}-{index}'

            bonus, _detail = allocation.compute_market_bonuses(
                treatment, [member_of(rec) for rec in picked], paying_round, seed=market_id)
            markets.append(dict(
                market_id=market_id,
                treatment=treatment,
                # allocation works in Crowns; this is the one place they become dollars, the
                # same boundary survey/__init__.py crosses when a live market closes.
                members=[(rec, pid, round(bonus[rec['code']] * crown_value_usd, 2))
                         for pid, rec in enumerate(picked, start=1)],
            ))
            placed.update(rec['code'] for rec in picked)

    leftovers = sorted((rec for rec in pool if rec['code'] not in placed),
                       key=lambda r: order[r['code']])
    return markets, leftovers


def feasibility(pool):
    """{treatment: {bucket: count, 'markets': n, 'leftover': n}} -- why a treatment formed what
    it formed. Reported before anything is paid, because "0 markets" is a claim worth showing
    the arithmetic for."""
    counts = collections.defaultdict(collections.Counter)
    for rec in pool:
        if rec['treatment'] in allocation.TREATMENTS and rec['bucket'] in allocation.BUCKETS:
            counts[rec['treatment']][rec['bucket']] += 1

    report = {}
    for treatment in allocation.TREATMENTS:
        bucket_counts = counts.get(treatment, collections.Counter())
        total = sum(bucket_counts.values())
        if not total:
            continue
        n = min(bucket_counts[b] // allocation.PER_MARKET[b] for b in allocation.BUCKETS)
        row = {b: bucket_counts[b] for b in allocation.BUCKETS}
        row['markets'] = n
        row['leftover'] = total - n * allocation.NUM_PLAYERS
        report[treatment] = row
    return report
