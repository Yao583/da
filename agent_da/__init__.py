from otree.api import *
import json
import random

import allocation
import csv
import os

doc = """
Deferred Acceptance played through a robot agent: instead of applying one prize at a time and
seeing the outcome, the participant states a complete contingent plan up front -- what the robot
applies to when all prizes are available, and what it applies to after being unpaired from each
successive prize. One Prolific participant replaces a lab participant per round; other
choices/rankings are loaded from lab session data.
"""



class C(BaseConstants):
    NAME_IN_URL = 'agent_da'
    PLAYERS_PER_GROUP = None
    NUM_ROUNDS = 5
    NR_TYPES = 6
    NR_PRIZES = 6
    NUM_LAB_PLAYERS = 8
    CAPACITIES = [2, 2, 1, 1, 1, 1] 
    CONFIRM_BUTTON = True
    SHOW_VALUATIONS = False
    SHOW_PRIORITIES = False
    SHOW_CAPACITIES = False
    APP_ROUND_OFFSET = 0  
    ALIGNED = False
    ENVELOPE = False
    # Availability is deliberately hidden in this treatment: the participant states a
    # contingent plan for their robot agent and never learns what actually happened.
    LIVE = False
    

class Subsession(BaseSubsession):
    pass

class Group(BaseGroup):
    pass

# region Player
class Player(BasePlayer):
    assigned_prize = models.IntegerField(initial=0)
    pref_ranking = models.CharField(label="", max_length=C.NR_PRIZES, blank=True)
    replaced_id = models.IntegerField(initial=0)
    # Track the exact lab context for this round
    lab_round_num = models.IntegerField(initial=0)
    lab_group_num = models.IntegerField(initial=0)

    # Export snapshot fields for downstream analysis
    app_name = models.StringField(initial='')
    selected_bonus_round = models.IntegerField(initial=0)
    valuations = models.LongStringField(initial='[]')
    selected_group_valuations = models.LongStringField(initial='{}')
    selected_group_pref_ranking = models.LongStringField(initial='{}')
    replaced_priority = models.IntegerField(initial=0)
    available_prizes_at_turn = models.LongStringField(initial='[]')

    failed_quiz = models.BooleanField(initial=False, blank=True)

# --- Quiz 1: prizes, groups and values ---
    quiz1 = models.StringField(
        label="How many prizes B are initially available?",
        choices=['one', 'two'],
        widget=widgets.RadioSelect,
    )
    quiz2 = models.StringField(
        label="How many prizes C are initially available?",
        choices=['one', 'two'],
        widget=widgets.RadioSelect,
    )

    quiz3 = models.StringField(
        label="How many prizes A are initially available?",
        choices=['one', 'two'],
        widget=widgets.RadioSelect,
    )
    quiz4 = models.StringField(
        label="How many prizes F are initially available?",
        choices=['one', 'two'],
        widget=widgets.RadioSelect,
    )
    quiz5 = models.IntegerField(
        label=f"How many of the {C.NUM_LAB_PLAYERS} participants will be in Group A?",
        blank=True,
    )
    # Select-all answers arrive as sorted, comma-joined option numbers from a hidden input.
    quiz6 = models.StringField(
        label="Select all statements that are true (how the two groups value prizes A and B)",
        blank=True,
    )
    quiz7 = models.StringField(
        label="For the four participants in Group B their second most valuable prize is:",
        choices=['Prize A', 'Prize B', 'Prize C', 'Prize D', 'Prize E', 'Prize F'],
        widget=widgets.RadioSelect,
    )
    quiz8 = models.StringField(
        label="For the four participants in Group A their second most valuable prize is:",
        choices=['Prize A', 'Prize B', 'Prize C', 'Prize D', 'Prize E', 'Prize F'],
        widget=widgets.RadioSelect,
    )
    quiz9 = models.BooleanField(
        label="Every participant values prizes C, D, E and F the same way.",
        choices=[[True, 'True'], [False, 'False']],
        widget=widgets.RadioSelect,
    )
    quiz10 = models.BooleanField(
        label="You cannot tell how much another participant values prizes C, D, E and F just from knowing how much you value these prizes.",
        choices=[[True, 'True'], [False, 'False']],
        widget=widgets.RadioSelect,
    )
    quiz11 = models.IntegerField(
        label="For the example in the table, how much would the participant make if they end up receiving a prize B?",
        blank=True,
    )

# --- Quiz 2: prize priorities ---
    quiz12 = models.BooleanField(
        label="Prize priorities are randomly determined.",
        choices=[[True, 'True'], [False, 'False']],
        widget=widgets.RadioSelect,
    )
    quiz13 = models.BooleanField(
        label=f"Prize priorities are used to order the {C.NUM_LAB_PLAYERS} participants in your group from 1st to {C.NUM_LAB_PLAYERS}th.",
        choices=[[True, 'True'], [False, 'False']],
        widget=widgets.RadioSelect,
    )
    quiz14 = models.BooleanField(
        label="Prize priorities: Anyone has an equal chance of being in any position.",
        choices=[[True, 'True'], [False, 'False']],
        widget=widgets.RadioSelect,
    )
    quiz15 = models.BooleanField(
        label="Nobody can affect their prize priority.",
        choices=[[True, 'True'], [False, 'False']],
        widget=widgets.RadioSelect,
    )
    quiz16 = models.StringField(
        label="Select all the statements that are true (whether you learn your prize priority)",
        blank=True,
    )

# --- Quiz 3: submit your ranking ---
    quiz17 = models.BooleanField(
        label="Your task is to rank prizes.",
        choices=[[True, 'True'], [False, 'False']],
        widget=widgets.RadioSelect,
    )
    quiz18 = models.BooleanField(
        label="You can choose not to rank all prizes.",
        choices=[[True, 'True'], [False, 'False']],
        widget=widgets.RadioSelect,
    )
    quiz19 = models.BooleanField(
        label="You can only rank a prize once, meaning, for example, that you cannot rank prize A first and third even if there are two prize As.",
        choices=[[True, 'True'], [False, 'False']],
        widget=widgets.RadioSelect,
    )
    quiz20 = models.BooleanField(
        label="You will not know other participants' rankings and other participants will not know your ranking.",
        choices=[[True, 'True'], [False, 'False']],
        widget=widgets.RadioSelect,
    )
    quiz21 = models.BooleanField(
        label="Your own ranking cannot affect other participants' ranking.",
        choices=[[True, 'True'], [False, 'False']],
        widget=widgets.RadioSelect,
    )

# --- Quiz 4: allocation process ---
    quiz22 = models.StringField(
        label="Select all statements that are true (the first step of the allocation process)",
        blank=True,
    )
    quiz23 = models.StringField(
        label="If more than two participants are paired with prize A, this creates a conflict. Then: (select all that apply)",
        blank=True,
    )
    quiz24 = models.StringField(
        label="If more than two participants are paired with prize B, this creates a conflict. Then: (select all that apply)",
        blank=True,
    )
    quiz25 = models.StringField(
        label="If more than one participant is paired with prize E, this creates a conflict. Then: (select all that apply)",
        blank=True,
    )
    quiz26 = models.StringField(
        label="At the end of the first part of the allocation process:",
        choices=[
            ['May be unmatched', 'A participant may be unmatched because they did not rank all prizes.'],
            ['Cannot be unmatched', 'Participants cannot end up unmatched.'],
        ],
        widget=widgets.RadioSelect,
    )
    quiz27 = models.StringField(
        label="If at some point in the process you are unpaired from a prize, can you be paired to that prize later on in the process?",
        choices=[
            ['No', "No, once you are unpaired from a prize, that prize becomes unavailable to you. This means that if you were unpaired from a Prize A, you cannot be re-paired to any of the two Prize As. But no other prize that you haven't been unpaired from yet is out of reach. You may be paired to another prize that was previously paired to somebody else."],
            ['Yes', 'Yes'],
        ],
        widget=widgets.RadioSelect,
    )

# --- Quiz 5: second allocation process ---
    quiz28 = models.StringField(
        label="The second part of the allocation process",
        choices=[
            ['Only unmatched participants', 'Involves only participants who are unmatched after the first part'],
            ['All participants', 'Involves all participants'],
        ],
        widget=widgets.RadioSelect,
    )
    quiz29 = models.StringField(
        label="The second part of the allocation process",
        choices=[
            ['Only available prizes', 'Involves only prizes that have not been assigned in part one and remain available.'],
            ['All prizes', 'Involves all prizes.'],
        ],
        widget=widgets.RadioSelect,
    )
    quiz30 = models.BooleanField(
        label="Every unmatched participant randomly receives one of the prizes that are still available, whether they ranked it or not.",
        choices=[[True, 'True'], [False, 'False']],
        widget=widgets.RadioSelect,
    )

# --- Quiz 6: how you submit your ranking ---
    quiz31 = models.BooleanField(
        label="You submit your ranking through your own robot agent, which applies to prizes on your behalf.",
        choices=[[True, 'True'], [False, 'False']],
        widget=widgets.RadioSelect,
    )
    quiz32 = models.StringField(
        label="What information do you give your robot?",
        choices=[
            ['Full contingent plan', 'What prize to apply for if all prizes are available, and what prize to apply for next in each case where a prize you applied for becomes unavailable.'],
            ['First choice only', 'Only what prize to apply for if all prizes are available.'],
            ['Nothing', 'Nothing; the robot decides on its own what to apply for.'],
        ],
        widget=widgets.RadioSelect,
    )

    # --- Quiz Attempt Counters ---
    quiz1_attempts = models.IntegerField(initial=0, blank=True)
    quiz2_attempts = models.IntegerField(initial=0, blank=True)
    quiz3_attempts = models.IntegerField(initial=0, blank=True)
    quiz4_attempts = models.IntegerField(initial=0, blank=True)
    quiz5_attempts = models.IntegerField(initial=0, blank=True)
    quiz6_attempts = models.IntegerField(initial=0, blank=True)
# endregion

# region functions
EXPECTED_PRIZE_SET = frozenset(chr(ord('A') + i) for i in range(C.NR_PRIZES))
NO_PRIZE_TOKEN = '0'


def creating_session(subsession: Subsession):
    # Async design: no seed data. Group (A/B) and lowest-priority status are assigned by the
    # treatment_router (participant.vars) when the participant first arrives; valuations are
    # generated lazily per round. Here we only initialise the per-participant export stores.
    if subsession.round_number == 1:
        for p in subsession.get_players():
            p.participant.vars.setdefault('market_vals', {})
            p.participant.vars.setdefault('market_ranking', {})


def _ordinal(n):
    s = {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10 * (n % 100 not in (11, 12, 13)), 'th')
    return f"{n}{s}"


def ensure_round_valuations(player: Player):
    """Draw once (and persist) this participant's valuations for the current round.

    The router fixes the participant's Group (A/B) for the whole study; A/B values follow the
    role while C-F are a fresh random permutation of {1, 3, 5, 7} each round -- matching the
    original per-round value variation. The realised vector is stored in participant.vars so
    the post-hoc allocation (survey app) reproduces exactly what the participant saw.
    """
    key = str(player.subsession.round_number)
    store = player.participant.vars.get('market_vals') or {}
    if key not in store:
        role = player.participant.vars.get('role', 'A')
        rng = random.Random(f"{player.participant.code}|vals|{key}")
        store[key] = allocation.generate_valuations(role, rng)
        player.participant.vars['market_vals'] = store
    return store[key]


def _prize_rows(valuations):
    rows = [
        dict(letter=chr(ord('A') + i), capacity=C.CAPACITIES[i], value=value, status='Available')
        for i, value in enumerate(valuations)
    ]
    rows.sort(key=lambda row: row['value'], reverse=True)
    return rows
# endregion
# region Pages
class Consent(Page):
    @staticmethod
    def is_displayed(player: Player):
        return player.subsession.round_number == 1


class InstructionsQuiz(Page):
    form_model = 'player'
    form_fields = ['quiz1', 'quiz2', 'quiz3', 'quiz4', 'quiz5', 'quiz6', 'quiz7', 'quiz8', 'quiz9',
        'quiz10', 'quiz11', 'quiz12', 'quiz13', 'quiz14', 'quiz15', 'quiz16', 'quiz17',
        'quiz18', 'quiz19', 'quiz20', 'quiz21', 'quiz22', 'quiz23', 'quiz24', 'quiz25',
        'quiz26', 'quiz27', 'quiz28', 'quiz29', 'quiz30', 'quiz31', 'quiz32', 'quiz1_attempts',
        'quiz2_attempts', 'quiz3_attempts', 'quiz4_attempts', 'quiz5_attempts',
        'quiz6_attempts', 'failed_quiz']

    @staticmethod
    def is_displayed(player):
        return player.subsession.round_number == 1

    @staticmethod
    def vars_for_template(player: Player):
        return dict(
            nr_prizes=C.NR_PRIZES,
            nr_prizes_ordinal=_ordinal(C.NR_PRIZES),
            nr_players_ordinal=_ordinal(C.NUM_LAB_PLAYERS),
            nr_rounds=C.NUM_ROUNDS,
            nr_others=C.NUM_LAB_PLAYERS - 1,
            players_per_group=C.NUM_LAB_PLAYERS,
            indices=[j for j in range(1, C.NR_PRIZES + 1)],
            letters=[chr(ord('A') + j) for j in range(C.NR_PRIZES)],
            letters_str=','.join(chr(ord('A') + j) for j in range(C.NR_PRIZES)),
            capacities=C.CAPACITIES,
            round_number=player.subsession.round_number,
            total_rounds=C.NUM_ROUNDS,
        )

    @staticmethod
    def js_vars(player: Player):
        return dict(nr_prizes=C.NR_PRIZES, ALIGNED=C.ALIGNED, LIVE=C.LIVE)

    @staticmethod
    def before_next_page(player: Player, timeout_happened):
        # If the JavaScript flagged them as failed, strip their bonus and remember it.
        if player.failed_quiz:
            player.participant.vars['failed_quiz'] = True
            player.participant.vars['bonus_payout'] = 0

    @staticmethod
    def app_after_this_page(player: Player, upcoming_apps):
        # Eject them immediately to the final survey app if they failed.
        if player.failed_quiz:
            return 'survey'


class Decision(Page):
    form_model = 'player'
    form_fields = ['pref_ranking']

    @staticmethod
    def vars_for_template(player: Player):
        valuations = ensure_round_valuations(player)
        role = player.participant.vars.get('role', 'A')
        is_lowest = bool(player.participant.vars.get('is_lowest', False))

        # Export snapshot for this round.
        player.app_name = C.NAME_IN_URL
        player.selected_bonus_round = int(player.session.vars.get('paying_round', 0) or 0)
        player.valuations = json.dumps(valuations)

        prize_rows = _prize_rows(valuations)
        return dict(
            nr_prizes=C.NR_PRIZES,
            nr_prizes_ordinal=_ordinal(C.NR_PRIZES),
            nr_players_ordinal=_ordinal(C.NUM_LAB_PLAYERS),
            nr_rounds=C.NUM_ROUNDS,
            nr_others=C.NUM_LAB_PLAYERS - 1,
            players_per_group=C.NUM_LAB_PLAYERS,
            indices=list(range(1, C.NR_PRIZES + 1)),
            letters=[row['letter'] for row in prize_rows],
            letters_alpha=[chr(ord('A') + j) for j in range(C.NR_PRIZES)],
            letters_str=','.join(chr(ord('A') + j) for j in range(C.NR_PRIZES)),
            valuations=[row['value'] for row in prize_rows],
            capacities=C.CAPACITIES,
            prize_rows=prize_rows,
            prize_statuses=[row['status'] for row in prize_rows],
            my_group=role,
            is_lowest_in_group=is_lowest,
            round_number=player.subsession.round_number,
            total_rounds=C.NUM_ROUNDS,
        )

    @staticmethod
    def error_message(player: Player, values):
        raw_ranking = (values.get('pref_ranking', '') or '').upper().strip()

        # Require an explicit first-row selection (blank default is not allowed).
        if not raw_ranking or raw_ranking.startswith('-'):
            return "Please make a choice in the first row before continuing."

        # Extract selected options (prize letters plus optional explicit no-prize token).
        selected_prizes = [char for char in raw_ranking if char != '-']
        trimmed_ranking = raw_ranking.rstrip('-')
        if len(selected_prizes) != len(set(selected_prizes)) or '-' in trimmed_ranking:
            if C.ENVELOPE:
                return "Please revise your decision: You can rank each prize at most once. If you leave an envelope empty, all subsequent envelopes have to be empty as well."
            else:
                return "Please revise your decision: You can rank each prize at most once. If you leave a rank empty, all subsequent ranks have to be empty as well."

        if NO_PRIZE_TOKEN in selected_prizes:
            no_prize_index = raw_ranking.find(NO_PRIZE_TOKEN)
            if raw_ranking[no_prize_index + 1:].replace('-', ''):
                return "If you choose No Prize, all subsequent ranks must be empty."

        # Safety check: ensure they are valid letters.
        if not set(selected_prizes).issubset(EXPECTED_PRIZE_SET | {NO_PRIZE_TOKEN}):
            return "Please select valid prizes from the dropdown menus."

    @staticmethod
    def before_next_page(player: Player, timeout_happened):
        clean_ranking = player.pref_ranking.replace('-', '').strip().upper()
        player.pref_ranking = clean_ranking
        # Persist this round's ranking for the post-hoc allocation (survey app).
        store = player.participant.vars.get('market_ranking') or {}
        store[str(player.subsession.round_number)] = clean_ranking
        player.participant.vars['market_ranking'] = store

    @staticmethod
    def is_displayed(player: Player):
        return True

    @staticmethod
    def js_vars(player: Player):
        # Availability is never shipped to the browser: the participant ranks blind.
        return dict(nr_prizes=C.NR_PRIZES, ALIGNED=C.ALIGNED, LIVE=C.LIVE)

    @staticmethod
    def app_after_this_page(player: Player, upcoming_apps):
        # Once they submit their final decision, teleport them to survey.
        if player.round_number == C.NUM_ROUNDS:
            return 'survey'
# endregion
page_sequence = [Consent, InstructionsQuiz, Decision]
