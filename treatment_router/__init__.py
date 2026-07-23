from otree.api import *
import random
import time

class C(BaseConstants):
    NAME_IN_URL = 'router'
    PLAYERS_PER_GROUP = None
    NUM_ROUNDS = 1
    # Must stay a subset of the session config's app_sequence: app_after_this_page raises
    # if a participant is drawn into an app they will never reach. The 'live' treatment is
    # excluded from the study, so it is listed in neither place.
    TREATMENT_APPS = [
        'da',
        'boston',
        'agent_da',
        'agent_boston',
    ]
    # A participant who hasn't made a request in 20 minutes is treated as a dropout and
    # stops holding a slot in their treatment, so the next arrival refills that arm.
    # This measures time since the last HTTP request, not elapsed study time, and the
    # apps define no live_method -- so a slow reader sitting on the one-page
    # InstructionsQuiz can trip it. That is safe: the arm merely looks emptier, so it
    # gains an extra completer rather than losing one, and later arrivals correct it.
    # Don't push this much lower for that reason.
    ACTIVE_TIMEOUT_SECONDS = 20 * 60

class Subsession(BaseSubsession):
    pass

class Group(BaseGroup):
    pass

class Player(BasePlayer):
    pass


def _treatment_counts(session):
    """Per treatment: (usable completions, participants still in flight).

    Balance is computed within this session only; if the study is run as several
    sessions, each one rebalances independently.
    """
    completed = {t: 0 for t in C.TREATMENT_APPS}
    active = {t: 0 for t in C.TREATMENT_APPS}
    now = int(time.time())

    for pp in session.get_participants():
        treatment = pp.vars.get('treatment')
        if treatment not in completed:
            continue

        if pp.vars.get('study_completed'):
            # Quiz failures and flagged bots reach the end but their data is
            # unusable, so they must not fill up a treatment's quota.
            if not pp.vars.get('failed_quiz') and not pp.vars.get('suspected_bot'):
                completed[treatment] += 1
        else:
            last_seen = getattr(pp, '_last_request_timestamp', None) or 0
            if now - last_seen <= C.ACTIVE_TIMEOUT_SECONDS:
                active[treatment] += 1

    return completed, active


def _draw_treatment(session):
    # Send this participant to whichever treatment is currently carrying the fewest
    # people, so completed counts even out as dropouts free their slots.
    completed, active = _treatment_counts(session)

    def load(treatment):
        # Primary key is current load; ties go to the treatment with fewest finishers.
        return (completed[treatment] + active[treatment], completed[treatment])

    lowest = min(load(t) for t in C.TREATMENT_APPS)
    return random.choice([t for t in C.TREATMENT_APPS if load(t) == lowest])


def creating_session(subsession):
    # Draw the globally shared paying round (1 through 5) exactly once.
    if 'paying_round' not in subsession.session.vars:
        subsession.session.vars['paying_round'] = random.randint(1, 5)

# The invisible page instantly teleports them to their assigned app
class RouteToTreatment(Page):
    @staticmethod
    def app_after_this_page(player, upcoming_apps):
        # Assign treatment when participant first lands here.
        treatment = player.participant.vars.get('treatment')

        if treatment not in C.TREATMENT_APPS:
            treatment = _draw_treatment(player.session)
            # Record it immediately so the next arrival counts this participant
            # as in flight. Two participants arriving in the same instant on a
            # multi-worker deployment can read the same counts, but the window is
            # one request and the rule self-corrects on the next arrival.
            player.participant.vars['treatment'] = treatment

        if treatment not in upcoming_apps:
            raise RuntimeError(
                f"Assigned treatment '{treatment}' is not in upcoming apps: {upcoming_apps}"
            )

        return treatment

# Notice the WaitPage has been removed so online participants don't get stuck!
page_sequence = [RouteToTreatment]
