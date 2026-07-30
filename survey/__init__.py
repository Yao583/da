from otree.api import *

import allocation

doc = """
Final survey + study completion. Reaching ThankYou marks a participant as a completer. A
usable completer (finished, not a quiz-fail, not a suspected bot) is queued into their
treatment's (role, lowest) bucket; once a full group of 8 is available the treatment's
mechanism is run post-hoc to fill every member's bonus. Screened-out arrivals (study full)
land here too and receive the show-up fee only.
"""


def _queue_and_group(player):
    """Queue a usable completer and assemble any groups of 8 that are now complete.

    Concurrency note (mirrors the router): two completions landing in the same instant on a
    multi-worker deployment could both try to assemble; the window is one request and each
    participant is queued at most once, so at worst a group is assembled one completion late.
    """
    participant = player.participant
    if participant.vars.get('market_queued'):
        return
    treatment = participant.vars.get('treatment')
    bucket = participant.vars.get('bucket')
    if treatment not in allocation.TREATMENTS or bucket not in allocation.BUCKETS:
        return
    if participant.vars.get('failed_quiz') or participant.vars.get('suspected_bot'):
        return

    participant.vars['market_queued'] = True

    session = player.session
    queues = session.vars.get('queues') or {}
    tq = queues.get(treatment) or {b: [] for b in allocation.BUCKETS}
    tq[bucket].append(participant.code)
    queues[treatment] = tq
    session.vars['queues'] = queues

    _assemble_markets(session, treatment)


def _assemble_markets(session, treatment):
    queues = session.vars.get('queues') or {}
    tq = queues.get(treatment)
    if not tq:
        return

    need = allocation.PER_MARKET
    seq = session.vars.get('market_seq') or {}
    paying_round = int(session.vars.get('paying_round', 1) or 1)
    code_to_pp = {pp.code: pp for pp in session.get_participants()}

    while all(len(tq[b]) >= need[b] for b in allocation.BUCKETS):
        picked = []
        for b in allocation.BUCKETS:
            for _ in range(need[b]):
                picked.append(tq[b].pop(0))

        idx = seq.get(treatment, 0) + 1
        seq[treatment] = idx
        market_id = f"{treatment}-{idx}"

        members = []
        for code in picked:
            pp = code_to_pp[code]
            members.append(dict(
                code=code,
                role=pp.vars.get('role', 'A'),
                is_lowest=bool(pp.vars.get('is_lowest', False)),
                vals_by_round=pp.vars.get('market_vals') or {},
                ranking_by_round=pp.vars.get('market_ranking') or {},
            ))

        bonus, detail = allocation.compute_market_bonuses(
            treatment, members, paying_round, seed=market_id
        )
        showup_fee = session.config['participation_fee']
        # market_pid is the member's 1..8 slot in this market; storing it (with market_id as
        # the RNG seed) makes the whole allocation reconstructable from the exported data.
        for pid, code in enumerate(picked, start=1):
            pp = code_to_pp[code]
            pp.vars['market_id'] = market_id
            pp.vars['market_pid'] = pid
            pp.vars['bonus_payout'] = bonus[code]
            pp.vars['market_detail'] = detail[code]
            pp.vars['total_payment'] = showup_fee + bonus[code]
            pp.payoff = bonus[code]

    queues[treatment] = tq
    session.vars['queues'] = queues
    session.vars['market_seq'] = seq


class C(BaseConstants):
    NAME_IN_URL = 'survey'
    PLAYERS_PER_GROUP = None
    NUM_ROUNDS = 1
    PROLIFIC_COMPLETION_URL = 'https://app.prolific.com/submissions/complete?cc=C3DGP1B9'
    # Optional redirect for flagged bots (e.g., Prolific screened-out URL/code).
    PROLIFIC_BOT_REDIRECT_URL = ''

class Subsession(BaseSubsession):
    pass


class Group(BaseGroup):
    pass


class Player(BasePlayer):
    
    # --- SINGLE CHOICE QUESTIONS ---
    age = models.IntegerField(label="What is your age?", min=18, max=100)
    
    lgbtq = models.StringField(
        label="Do you identify as LGBTQ+?",
        choices=["Yes", "No", "Prefer not to say"],
        widget=widgets.RadioSelectHorizontal
    )
    
    education = models.StringField(
        label="What is the highest level of education you have achieved?",
        choices=[
            "Less than high school", "High school", 
            "2 year college degree (e.g., AA, AS)", "4 year college degree (e.g., BS, BA)", 
            "Master's degree (e.g., MA, MS, MEng, MEd, MSW, MBA)", 
            "Professional (MD, DDS, DVM, LLB, JD) or doctoral degree (PhD, EdD)", "I’m not sure"
        ]
    )
    
    state = models.StringField(label="Currently, in which US state or territory are you located?")
    
    community = models.StringField(
        label="How would you describe the community where you currently live?",
        choices=["Urban", "Suburban", "Rural"],
        widget=widgets.RadioSelectHorizontal
    )
    
    employment = models.StringField(
        label="Which of the following best describes your current employment situation?",
        choices=[
            "Employed full-time", "Employed part-time", "Self-employed", "Not employed", 
            "Retired", "Student", "Stay-at-home parent or partner", "Prefer not to say"
        ]
    )
    
    income = models.StringField(
        label="In 2024, what was your total income from all sources, before taxes?",
        choices=[
            "Less than $30,000", "$30,000 to less than $40,000", "$40,000 to less than $50,000",
            "$50,000 to less than $60,000", "$60,000 to less than $70,000", "$70,000 to less than $80,000",
            "$80,000 to less than $90,000", "$90,000 to less than $100,000", "$100,000 or more", "Prefer not to say"
        ]
    )
    
    politics = models.StringField(
        label="When it comes to politics in the United States, where would you place yourself on this scale?",
        choices=[
            "Very conservative", "Conservative", "Slightly conservative", "Moderate, middle of the road", 
            "Slightly liberal", "Liberal", "Very liberal", "I’m not sure", "I do not identify on this scale"
        ]
    )
    
    party = models.StringField(
        label="As of today, do you identify more as a Republican or a Democrat?",
        choices=["A Republican", "A Democrat"],
        widget=widgets.RadioSelectHorizontal
    )
    
    # Honeypot: hidden from normal users, but naive bots often fill it.
    website = models.StringField(blank=True, initial='')
    suspected_bot = models.BooleanField(initial=False)

    # --- MARK ALL THAT APPLY: RACE (QID15) ---
    race_native = models.BooleanField(label="American Indian or Alaska Native", widget=widgets.CheckboxInput, blank=True)
    race_asian = models.BooleanField(label="Asian or Asian American", widget=widgets.CheckboxInput, blank=True)
    race_black = models.BooleanField(label="Black or African American", widget=widgets.CheckboxInput, blank=True)
    race_hispanic = models.BooleanField(label="Hispanic or Latino/a", widget=widgets.CheckboxInput, blank=True)
    race_mena = models.BooleanField(label="Middle Eastern or North African", widget=widgets.CheckboxInput, blank=True)
    race_hawaiian = models.BooleanField(label="Native Hawaiian or Pacific Islander", widget=widgets.CheckboxInput, blank=True)
    race_white = models.BooleanField(label="White or European", widget=widgets.CheckboxInput, blank=True)
    race_other = models.BooleanField(label="Other / Best described as something else", widget=widgets.CheckboxInput, blank=True)
    race_prefer_not = models.BooleanField(label="Prefer not to say", widget=widgets.CheckboxInput, blank=True)

    # --- MARK ALL THAT APPLY: GENDER (QID16) ---
    gender_man = models.BooleanField(label="Man", widget=widgets.CheckboxInput, blank=True)
    gender_woman = models.BooleanField(label="Woman", widget=widgets.CheckboxInput, blank=True)
    gender_trans_nonbinary = models.BooleanField(label="Transgender, Non-binary, or another gender", widget=widgets.CheckboxInput, blank=True)
    gender_prefer_not = models.BooleanField(label="Prefer not to answer", widget=widgets.CheckboxInput, blank=True)

    # --- MARK ALL THAT APPLY: SEXUALITY (QID17) ---
    sex_gay_lesbian = models.BooleanField(label="Gay or lesbian", widget=widgets.CheckboxInput, blank=True)
    sex_straight = models.BooleanField(label="Straight, that is not gay or lesbian etc.", widget=widgets.CheckboxInput, blank=True)
    sex_bisexual = models.BooleanField(label="Bisexual", widget=widgets.CheckboxInput, blank=True)
    sex_different = models.BooleanField(label="I use a different term", widget=widgets.CheckboxInput, blank=True)
    sex_dont_know = models.BooleanField(label="I don’t know", widget=widgets.CheckboxInput, blank=True)
    sex_prefer_not = models.BooleanField(label="Prefer not to answer", widget=widgets.CheckboxInput, blank=True)

    intergenerational_advice = models.LongStringField(
        label="Intergenerational advice: If someone plays this game in the future, what would you recommend them to do in order to maximize their earnings.",
        blank=False,
    )
    comments = models.LongStringField(
        label="If you have any comments or feedback about this study, please leave them below.",
        blank=True
    )


# PAGES
class Demographics(Page):
    form_model = 'player'
    
    # We pass every single field to the page
    form_fields = [
        'age', 
        'race_native', 'race_asian', 'race_black', 'race_hispanic', 'race_mena', 'race_hawaiian', 'race_white', 'race_other', 'race_prefer_not',
        'gender_man', 'gender_woman', 'gender_trans_nonbinary', 'gender_prefer_not',
        'sex_gay_lesbian', 'sex_straight', 'sex_bisexual', 'sex_different', 'sex_dont_know', 'sex_prefer_not',
        'lgbtq', 'education', 'state', 'community', 'employment', 'income', 'politics', 'party', 'intergenerational_advice', 'comments',
        'website',
    ]

    @staticmethod
    def is_displayed(player: Player):
        # Skip demographics for quiz-fails, suspected bots, and screened-out (study full).
        return (
            not player.participant.vars.get('failed_quiz', False)
            and not player.participant.vars.get('suspected_bot', False)
            and not player.participant.vars.get('screened_out', False)
        )

    @staticmethod
    def before_next_page(player: Player, timeout_happened):
        honeypot_value = (player.website or '').strip()
        is_honeypot_triggered = bool(honeypot_value)

        player.suspected_bot = is_honeypot_triggered
        player.participant.vars['suspected_bot'] = is_honeypot_triggered
        player.participant.vars['blocked_for_bot'] = is_honeypot_triggered

        if is_honeypot_triggered:
            player.participant.vars['suspected_bot_reason'] = 'demographics_honeypot_filled'
            player.participant.vars['suspected_bot_value'] = honeypot_value[:120]


class BotBlocked(Page):
    @staticmethod
    def is_displayed(player: Player):
        return bool(player.participant.vars.get('suspected_bot', False))

    @staticmethod
    def vars_for_template(player: Player):
        redirect_url = player.session.config.get(
            'prolific_bot_redirect_url',
            C.PROLIFIC_BOT_REDIRECT_URL,
        ) or ''
        return dict(redirect_url=redirect_url)

class ThankYou(Page):
    form_model = 'player'

    @staticmethod
    def is_displayed(player: Player):
        return not player.participant.vars.get('suspected_bot', False)

    @staticmethod
    def vars_for_template(player: Player):
        participant = player.participant
        # Reaching this page counts as study completion for router rebalancing.
        participant.vars['study_completed'] = True

        screened_out = bool(participant.vars.get('screened_out', False))
        failed_quiz = bool(participant.vars.get('failed_quiz', False))
        usable = not screened_out and not failed_quiz and not participant.vars.get('suspected_bot')

        # Queue this completer and assemble any group of 8 that is now complete. The bonus is
        # usually still pending here (the participant's groupmates finish later); it is filled
        # in once their group closes and is exported for the manual Prolific bonus payment.
        if usable:
            _queue_and_group(player)

        showup_fee = player.session.config['participation_fee']
        bonus = participant.vars.get('bonus_payout', None)
        bonus_pending = usable and bonus is None
        bonus_amount = bonus or 0

        participant.payoff = bonus_amount
        participant.vars['total_payment'] = showup_fee + bonus_amount

        return {
            'treatment': participant.vars.get('treatment', 'Unknown'),
            'winning_round': player.session.vars.get('paying_round', 1),
            'participation_fee': showup_fee,
            'usable': usable,
            'screened_out': screened_out,
            'failed_quiz': failed_quiz,
            'bonus_pending': bonus_pending,
            'redemption_code': participant.label or participant.code,
        }

# Make sure to add it to the sequence!
page_sequence = [Demographics, BotBlocked, ThankYou]
