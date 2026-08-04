from otree.api import *
import random
import time

import allocation


class C(BaseConstants):
    NAME_IN_URL = 'router'
    PLAYERS_PER_GROUP = None
    NUM_ROUNDS = 1
    # Must stay a subset of the session config's app_sequence: app_after_this_page raises
    # if a participant is drawn into an app they will never reach. The 'live' treatment is
    # excluded from the study, so it is listed in neither place.
    TREATMENT_APPS = allocation.TREATMENTS
    BUCKETS = allocation.BUCKETS
    # A participant who hasn't made a request in this long is treated as a dropout and stops
    # holding a slot in their bucket, so the next arrival can refill it. This measures time
    # since the last HTTP *request*, not elapsed study time, and the treatment apps make no
    # AJAX/live-method calls -- so the whole 690-line InstructionsQuiz (full instructions plus
    # a 30-field quiz with retries) is a single silent gap. Set this below a careful reader's
    # time on that page and their slot gets double-booked: they still finish and count, so the
    # bucket lands one over target and the extra finisher is stranded with no market and no
    # bonus. Lowering it trades recruitment wait for over-recruitment, and the extras cluster
    # on slow readers -- the da-only pilot ran 10 minutes and finished A_normal 19/18.
    ACTIVE_TIMEOUT_SECONDS = 20 * 60  # 20 mins


class Subsession(BaseSubsession):
    pass


class Group(BaseGroup):
    pass


class Player(BasePlayer):
    pass


def _markets_per_treatment(session):
    return max(int(session.config.get('markets_per_treatment', 1) or 1), 0)


def _bucket_counts(session):
    """Per (treatment, bucket): usable completions and in-flight actives.

    Balance is computed within this session only; if the study is run as several
    sessions, each one rebalances independently.
    """
    completed = {t: {b: 0 for b in C.BUCKETS} for t in C.TREATMENT_APPS}
    active = {t: {b: 0 for b in C.BUCKETS} for t in C.TREATMENT_APPS}
    now = int(time.time())

    for pp in session.get_participants():
        treatment = pp.vars.get('treatment')
        bucket = pp.vars.get('bucket')
        if treatment not in completed or bucket not in C.BUCKETS:
            continue

        if pp.vars.get('study_completed'):
            # Belt and braces: quiz failures are ejected before ThankYou, so they never
            # get study_completed in the first place and cannot fill up a bucket's quota.
            if not pp.vars.get('failed_quiz'):
                completed[treatment][bucket] += 1
        else:
            last_seen = getattr(pp, '_last_request_timestamp', None) or 0
            if now - last_seen <= C.ACTIVE_TIMEOUT_SECONDS:
                active[treatment][bucket] += 1

    return completed, active


def _draw_bucket(session):
    """Pick the (treatment, bucket) that still needs finishers and is least loaded.

    Returns None when every bucket's pipeline (completions + in-flight actives) is already
    at target -- the caller then turns the arrival away unpaid. Buckets that are pipeline-full
    but not completion-full recover as their actives time out and later arrivals refill.
    """
    completed, active = _bucket_counts(session)
    targets = allocation.bucket_targets(_markets_per_treatment(session))

    candidates = []
    for t in C.TREATMENT_APPS:
        for b in C.BUCKETS:
            target = targets[b]
            if completed[t][b] < target and completed[t][b] + active[t][b] < target:
                # Primary key: current pipeline load; ties go to fewest finishers.
                load = (completed[t][b] + active[t][b], completed[t][b])
                candidates.append((load, t, b))

    if not candidates:
        return None

    lowest = min(load for load, _, _ in candidates)
    _, t, b = random.choice([c for c in candidates if c[0] == lowest])
    return t, b


def creating_session(subsession):
    # Draw the globally shared paying round (1 through 5) exactly once.
    if 'paying_round' not in subsession.session.vars:
        subsession.session.vars['paying_round'] = random.randint(1, allocation.NUM_ROUNDS)


def vars_for_admin_report(subsession):
    """Live per-(treatment, bucket) counter so recruitment can be topped up to fill every
    bucket. Shows completed / active / queued / remaining against target, plus how many
    markets each treatment has actually assembled.

    ``queued`` and ``markets`` come from the two session vars the survey app writes in
    ``_assemble_markets``: ``queues`` ({treatment: {bucket: [codes]}}) holds usable finishers
    still waiting for a market, and ``market_seq`` ({treatment: n}) counts assembled markets.
    A finisher only leaves the queue when a whole group of 8 closes around them, so a queue
    that stops draining is the early warning that someone will be stranded without a bonus.
    """
    session = subsession.session
    completed, active = _bucket_counts(session)
    markets = _markets_per_treatment(session)
    targets = allocation.bucket_targets(markets)
    queues = session.vars.get('queues') or {}
    seq = session.vars.get('market_seq') or {}

    rows = []
    for t in C.TREATMENT_APPS:
        tq = queues.get(t) or {}
        for b in C.BUCKETS:
            done = completed[t][b]
            act = active[t][b]
            rows.append(dict(
                treatment=t,
                bucket=b,
                target=targets[b],
                completed=done,
                active=act,
                queued=len(tq.get(b) or []),
                remaining=max(targets[b] - done, 0),
            ))

    # Per-treatment market progress. ``stranded`` is what is left queued once every whole
    # market that CAN be assembled already has been -- those finishers were promised a bonus
    # on ThankYou and cannot be paid one, so this must read 0 before recruitment closes.
    treatments = []
    stranded_total = 0
    for t in C.TREATMENT_APPS:
        tq = queues.get(t) or {}
        waiting = sum(len(tq.get(b) or []) for b in C.BUCKETS)
        treatments.append(dict(
            treatment=t,
            assembled=seq.get(t, 0),
            target=markets,
            queued=waiting,
        ))
        stranded_total += waiting

    usable_total = sum(r['completed'] for r in rows)
    return dict(
        rows=rows,
        treatments=treatments,
        markets_per_treatment=markets,
        usable_total=usable_total,
        markets_assembled=sum(t['assembled'] for t in treatments),
        markets_target=markets * len(C.TREATMENT_APPS),
        stranded=stranded_total,
        full_groups=usable_total // allocation.NUM_PLAYERS,
    )


# The invisible page instantly teleports the participant to their assigned app.
class RouteToTreatment(Page):
    @staticmethod
    def app_after_this_page(player, upcoming_apps):
        participant = player.participant

        # Already routed on a previous request: honor the prior decision.
        if participant.vars.get('screened_out'):
            return 'survey'

        treatment = participant.vars.get('treatment')
        if treatment not in C.TREATMENT_APPS:
            drawn = _draw_bucket(player.session)
            if drawn is None:
                # Study is full: send them to the survey app's StudyFull dead end, which
                # asks them to return their Prolific submission. No completion code, no
                # payment, excluded from data. They are stopped before Consent, so they
                # are turned away without having done any work.
                participant.vars['screened_out'] = True
                return 'survey'

            treatment, bucket = drawn
            role, is_lowest = allocation.parse_bucket(bucket)
            # Record immediately so the next arrival counts this participant as in flight.
            # Two participants arriving in the same instant on a multi-worker deployment can
            # read the same counts, but the window is one request and the rule self-corrects
            # on the next arrival.
            participant.vars['treatment'] = treatment
            participant.vars['bucket'] = bucket
            participant.vars['role'] = role
            participant.vars['is_lowest'] = is_lowest

        if treatment not in upcoming_apps:
            raise RuntimeError(
                f"Assigned treatment '{treatment}' is not in upcoming apps: {upcoming_apps}"
            )

        return treatment


page_sequence = [RouteToTreatment]
