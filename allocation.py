"""Shared market logic for the four treatment apps and the survey app.

The online study is played *asynchronously*: each participant plays alone against
computer-generated valuations, submitting a ranking each round -- no live wait rooms and
no live allocation. After a full group of 8 usable finishers has been assembled for a
treatment (4 Group-A + 4 Group-B, with one designated lowest-priority member in each
group), the treatment's mechanism is run post-hoc to compute every member's bonus.

Nothing in here reads the retired lab seed CSVs (``boston_seed*.csv``): a market is fully
generatable. A player is Group A (values ``[15, 13, ...]``) or Group B (``[13, 15, ...]``),
and prizes C-F get a random permutation of ``{1, 3, 5, 7}``. Priorities are a random common
order over the 8 players, which makes DA equivalent to serial dictatorship.
"""
import random

# --- Market structure -------------------------------------------------------
NR_PRIZES = 6
NUM_PLAYERS = 8
NUM_ROUNDS = 5
CAPACITIES = [2, 2, 1, 1, 1, 1]          # sums to 8 -> exactly one seat per player
CF_VALUES = [1, 3, 5, 7]                 # idiosyncratic values for prizes C, D, E, F
AB_HIGH, AB_LOW = 15, 13                 # own-group prize / other-group prize
NO_PRIZE_TOKEN = '0'

# Must stay in sync with settings.py's app_sequence: the treatment_router draws from this
# list and raises if the drawn app is not in the session's app_sequence. MECHANISMS below
# always keeps all four entries; dropping a treatment is a routing change only.
TREATMENTS = ['da', 'boston', 'agent_da', 'agent_boston']

# --- Completion buckets -----------------------------------------------------
# Each usable finisher lands in one bucket. A market is assembled from
# 3 A_normal + 1 A_lowest + 3 B_normal + 1 B_lowest, which guarantees 4 Group-A /
# 4 Group-B with exactly one designated-lowest member per group. With a per-treatment
# target of ``M`` markets the bucket targets are a multiple that sums to 8*M.
BUCKETS = ['A_normal', 'A_lowest', 'B_normal', 'B_lowest']
PER_MARKET = {'A_normal': 3, 'A_lowest': 1, 'B_normal': 3, 'B_lowest': 1}


def bucket_of(role, is_lowest):
    return f"{role}_{'lowest' if is_lowest else 'normal'}"


def parse_bucket(bucket):
    """'A_lowest' -> ('A', True); 'B_normal' -> ('B', False)."""
    role, kind = bucket.split('_')
    return role, kind == 'lowest'


def bucket_targets(markets_per_treatment):
    m = max(int(markets_per_treatment), 0)
    return {b: PER_MARKET[b] * m for b in BUCKETS}


# --- Valuations -------------------------------------------------------------
def generate_valuations(role, rng):
    """Group A -> [15, 13, <perm of 1,3,5,7>]; Group B -> [13, 15, <perm>]."""
    cf = CF_VALUES[:]
    rng.shuffle(cf)
    if role == 'A':
        return [AB_HIGH, AB_LOW] + cf
    return [AB_LOW, AB_HIGH] + cf


def group_of(valuations):
    return 'A' if valuations[0] >= valuations[1] else 'B'


# --- Ranking / capacity helpers --------------------------------------------
def build_capacity_map():
    return {i + 1: CAPACITIES[i] for i in range(NR_PRIZES)}


def ranking_to_prize_ids(ranking):
    """Parse a ranking string ('BCA') into ordered prize ids, stopping at No Prize."""
    choices = []
    for ch in (ranking or '').strip().upper():
        if ch == NO_PRIZE_TOKEN:
            break
        prize_id = ord(ch) - ord('A') + 1
        if 1 <= prize_id <= NR_PRIZES:
            choices.append(prize_id)
    return choices


# --- Mechanisms (pure; identical maths to the retired live versions) --------
def run_deferred_acceptance(priority_rank, rankings_by_pid):
    """Applicant-proposing Deferred Acceptance (Gale-Shapley) with per-prize capacities."""
    capacities = build_capacity_map()
    held = {prize_id: [] for prize_id in capacities}
    next_idx = {pid: 0 for pid in rankings_by_pid}
    free = [pid for pid in rankings_by_pid if rankings_by_pid[pid]]

    while free:
        pid = free.pop()
        if next_idx[pid] >= len(rankings_by_pid[pid]):
            continue
        prize = rankings_by_pid[pid][next_idx[pid]]
        next_idx[pid] += 1
        held[prize].append(pid)
        held[prize].sort(key=lambda x: priority_rank[x])  # best priority first
        if len(held[prize]) > capacities[prize]:
            rejected = held[prize].pop()
            if next_idx[rejected] < len(rankings_by_pid[rejected]):
                free.append(rejected)

    assigned = {pid: None for pid in rankings_by_pid}
    for prize, pids in held.items():
        for pid in pids:
            assigned[pid] = prize
    remaining = {p: capacities[p] - len(held[p]) for p in capacities}
    return assigned, remaining


def run_boston_allocation(priority_rank, rankings_by_pid):
    """Boston (immediate acceptance) with per-prize capacities."""
    remaining = build_capacity_map()
    assigned = {pid: None for pid in rankings_by_pid}
    choice_round = 0

    while True:
        applicants_by_prize = {}
        for pid, choices in rankings_by_pid.items():
            if assigned[pid] is not None or choice_round >= len(choices):
                continue
            applicants_by_prize.setdefault(choices[choice_round], []).append(pid)

        if not applicants_by_prize:
            break

        for prize_id, applicants in applicants_by_prize.items():
            applicants.sort(key=lambda pid: priority_rank[pid])  # best priority first
            winners = applicants[:remaining[prize_id]]
            for pid in winners:
                assigned[pid] = prize_id
            remaining[prize_id] -= len(winners)  # permanent
        choice_round += 1

    return assigned, remaining


MECHANISMS = {
    'da': run_deferred_acceptance,
    'agent_da': run_deferred_acceptance,
    'boston': run_boston_allocation,
    'agent_boston': run_boston_allocation,
}


def random_fill_unmatched(assigned, remaining, priority_order, rng):
    """Part two: applicants unmatched after part one randomly take a remaining seat."""
    unmatched = [pid for pid in priority_order if assigned[pid] is None]
    seats = [prize_id for prize_id, n in remaining.items() for _ in range(n)]
    rng.shuffle(seats)
    for pid, prize_id in zip(unmatched, seats):
        assigned[pid] = prize_id
        remaining[prize_id] -= 1


# --- Priority order (common order over the 8, honoring the reveal) ----------
def build_priority_order(pids, roles, lowest_a, lowest_b, rng):
    """A random common priority order (best first) constrained so the designated
    lowest-A member is worst-ranked among the four A-members and the designated lowest-B
    member is worst-ranked among the four B-members -- exactly what those two participants
    were told during play.
    """
    order = list(pids)
    rng.shuffle(order)

    def _demote(group_pids, lowest_pid):
        positions = [i for i, pid in enumerate(order) if pid in group_pids]
        worst_pos = max(positions)
        cur = order.index(lowest_pid)
        if cur != worst_pos:
            order[cur], order[worst_pos] = order[worst_pos], order[cur]

    a_pids = {pid for pid in pids if roles[pid] == 'A'}
    b_pids = {pid for pid in pids if roles[pid] == 'B'}
    _demote(a_pids, lowest_a)
    _demote(b_pids, lowest_b)
    return order


# --- Post-hoc bonus computation for one assembled market --------------------
def compute_market_bonuses(treatment, members, paying_round, seed):
    """Compute every member's bonus for one assembled group of 8.

    ``members``: list of 8 dicts, each with keys ``code``, ``role`` ('A'/'B'),
    ``is_lowest`` (bool), ``vals_by_round`` ({round_str: [6 ints]}) and
    ``ranking_by_round`` ({round_str: str}). Exactly four are role 'A' (one lowest) and
    four are role 'B' (one lowest).

    Returns ``(bonus_by_code, detail_by_code)`` where ``bonus`` is the payoff in
    ``paying_round`` and ``detail`` is ``{code: {round_str: {'prize': int, 'payoff': int}}}``.
    Deterministic given ``seed`` (priority orders and random fills are drawn from it).
    """
    rng = random.Random(seed)
    mechanism = MECHANISMS[treatment]
    pids = list(range(1, len(members) + 1))          # 1..8 market-local ids
    member_by_pid = {i + 1: m for i, m in enumerate(members)}
    roles = {pid: member_by_pid[pid]['role'] for pid in pids}
    lowest_a = next(pid for pid in pids
                    if roles[pid] == 'A' and member_by_pid[pid]['is_lowest'])
    lowest_b = next(pid for pid in pids
                    if roles[pid] == 'B' and member_by_pid[pid]['is_lowest'])

    detail = {m['code']: {} for m in members}
    for rnd in range(1, NUM_ROUNDS + 1):
        key = str(rnd)
        priority_order = build_priority_order(pids, roles, lowest_a, lowest_b, rng)
        priority_rank = {pid: rank for rank, pid in enumerate(priority_order, start=1)}
        rankings_by_pid = {
            pid: ranking_to_prize_ids(member_by_pid[pid]['ranking_by_round'].get(key, ''))
            for pid in pids
        }
        assigned, remaining = mechanism(priority_rank, rankings_by_pid)
        random_fill_unmatched(assigned, remaining, priority_order, rng)
        for pid in pids:
            m = member_by_pid[pid]
            vals = m['vals_by_round'].get(key, [0] * NR_PRIZES)
            prize = assigned[pid]
            payoff = vals[prize - 1] if prize and 1 <= prize <= len(vals) else 0
            detail[m['code']][key] = {'prize': prize, 'payoff': payoff}

    paying_key = str(paying_round)
    bonus = {m['code']: detail[m['code']].get(paying_key, {}).get('payoff', 0)
             for m in members}
    return bonus, detail
