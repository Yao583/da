from otree.api import *
import json
import random
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
    
# --- Load lab session data ---
# ── Load pre-recorded lab session data ─────────────────────────────────────
def _load_lab_data():
    # 1. Dynamically pick the filename based on the treatment toggle
    # if C.ALIGNED:
    #     filename = 'rsd_a_data.csv'
    # else:
    #     filename = 'rsd_na_data.csv'
    filename = 'boston_seed.csv'   
    csv_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', filename)
    csv_path = os.path.abspath(csv_path)
    if not os.path.exists(csv_path):
        raise FileNotFoundError(f"Missing required lab data file: {csv_path}")

    value_col = 'subsession.round_valuations' if C.ALIGNED else 'player.player_valuations'
    required_columns = {
        'subsession.round_number',
        'group.id_in_subsession',
        'subsession.priorities_by_prize',
        'player.id_in_group',
        'player.pref_ranking',
        value_col,
    }
    
    rounds = {}
    with open(csv_path, newline='') as f:
        reader = csv.DictReader(f)
        fieldnames = set(reader.fieldnames or [])
        missing = sorted(required_columns - fieldnames)
        if missing:
            raise ValueError(f"{filename} is missing required columns: {missing}")

        for row in reader:
            try:
                rnd = int(row['subsession.round_number'])
                grp = int(row['group.id_in_subsession'])
                pid = int(row['player.id_in_group'])
            except (TypeError, ValueError, KeyError) as exc:
                raise ValueError(f"Malformed row {reader.line_num} in {filename}: {row}") from exc
            
            if rnd not in rounds:
                rounds[rnd] = {}
            if grp not in rounds[rnd]:
                rounds[rnd][grp] = dict(
                    priorities=row['subsession.priorities_by_prize'].strip(),
                    rankings={},
                    valuations={}  # <--- Now a dictionary mapping Player ID -> Valuations
                )
            
            ranking = (row.get('player.pref_ranking') or '').strip()
            rounds[rnd][grp]['rankings'][pid] = ranking
            
            # 2. Dynamically pick the correct column based on the treatment
            val_str = (row.get(value_col) or '').strip()
                
            rounds[rnd][grp]['valuations'][pid] = val_str

    if not rounds:
        raise ValueError(f"{filename} contains no usable lab rows")

    return rounds


LAB_DATA = _load_lab_data()
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
            ['No', 'No, once you are unpaired from a prize such prize becomes unavailable to you. But no other prize is out of reach. You may be paired to another prize that was previously paired to somebody else. This will create a conflict. If your priority is higher, you will be the new participant matched to that prize.'],
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
    # 1. Gather all available combinations of (lab_round, lab_group)
    all_lab_groups = [(r, g) for r in sorted(LAB_DATA) for g in sorted(LAB_DATA[r])]
    if not all_lab_groups:
        raise RuntimeError(f"No lab groups found for {C.NAME_IN_URL}")

    # 2. In Round 1, shuffle the deck and save it to the participant's persistent memory
    if subsession.round_number == 1:
        for p in subsession.get_players():
            shuffled_groups = all_lab_groups.copy()
            random.shuffle(shuffled_groups)
            p.participant.vars['assigned_lab_groups'] = shuffled_groups
            p.participant.vars['e1_schedule'] = []
            p.participant.vars['e1_successful'] = [False] * C.NR_PRIZES
            p.participant.vars['e1_player_prefs'] = []

    # 3. In EVERY round (1 through 10), deal one card from the deck to the current player
    for p in subsession.get_players():
        assigned_lab_groups = p.participant.vars.get('assigned_lab_groups')
        if not assigned_lab_groups:
            assigned_lab_groups = all_lab_groups.copy()
            random.shuffle(assigned_lab_groups)
            p.participant.vars['assigned_lab_groups'] = assigned_lab_groups

        deck_index = (subsession.round_number - 1) % len(assigned_lab_groups)
        lab_r, lab_g = assigned_lab_groups[deck_index]
        
        # Save it to the current round's player object (oTree will properly save this to the DB)
        p.lab_round_num = lab_r
        p.lab_group_num = lab_g
        p.replaced_id = random.randint(1, C.NUM_LAB_PLAYERS)
        _store_export_snapshot(p)


def _store_export_snapshot(player: Player):
    player.app_name = C.NAME_IN_URL
    player.selected_bonus_round = int(player.session.vars.get('paying_round', 0) or 0)

    lab_round = LAB_DATA.get(player.lab_round_num, {}).get(player.lab_group_num)
    if not lab_round:
        return

    player.selected_group_valuations = json.dumps(lab_round.get('valuations', {}), sort_keys=True)
    player.selected_group_pref_ranking = json.dumps(lab_round.get('rankings', {}), sort_keys=True)

    replaced_id = player.replaced_id or 0
    valuations_map = lab_round.get('valuations', {})
    player.valuations = valuations_map.get(replaced_id, '[]')

    priorities_raw = lab_round.get('priorities', '[]')
    try:
        priorities = json.loads(priorities_raw)
        priority_map = {pid: rank for rank, pid in enumerate(priorities, start=1)}
        player.replaced_priority = priority_map.get(replaced_id, 0)
    except (TypeError, ValueError, json.JSONDecodeError):
        player.replaced_priority = 0



def map_ranking_string_to_prefs(ranking: str):
    """Map ranking string like 'BCA' to per-prize ranks like [3, 1, 2]."""
    prefs = [None] * C.NR_PRIZES
    ranking = (ranking or '').strip().upper()
    for rank, prize_letter in enumerate(ranking, start=1):
        prize_num = ord(prize_letter) - ord('A') + 1
        if 1 <= prize_num <= C.NR_PRIZES:
            prefs[prize_num - 1] = rank
    return prefs


def _group_of(valuations):
    """Group A values prize A above prize B; Group B is the reverse."""
    return 'A' if valuations[0] >= valuations[1] else 'B'


def _group_context(lab_round, replaced_id, priority_map):
    """This participant's group, and whether they hold the lowest priority inside it.

    Participants only learn their prize priority when it is the lowest one in their own
    group, so the Decision page needs both facts -- and both are redrawn every period
    along with replaced_id.
    """
    my_group = _group_of(json.loads(lab_round['valuations'][replaced_id]))
    members = [
        pid for pid, raw in lab_round['valuations'].items()
        if _group_of(json.loads(raw)) == my_group
    ]
    lowest_priority_member = max(members, key=lambda pid: priority_map[pid])
    return my_group, lowest_priority_member == replaced_id


def _build_capacity_map():
    """Map each prize id (1..NR_PRIZES) to its number of identical copies/seats."""
    if len(C.CAPACITIES) > C.NR_PRIZES:
        raise RuntimeError(
            f"CAPACITIES length {len(C.CAPACITIES)} exceeds NR_PRIZES {C.NR_PRIZES}"
        )

    capacities = {}
    for prize_id in range(1, C.NR_PRIZES + 1):
        if prize_id <= len(C.CAPACITIES):
            raw_capacity = C.CAPACITIES[prize_id - 1]
        else:
            # If fewer capacities are provided than prizes, remaining prizes have zero seats.
            raw_capacity = 0

        capacity = int(raw_capacity)
        if capacity < 0:
            raise RuntimeError(f"Capacity for prize {prize_id} cannot be negative")

        capacities[prize_id] = capacity

    return capacities


def _ranking_to_prize_ids(ranking: str):
    """Parse a ranking string ('BCA') into ordered prize ids, stopping at an explicit No Prize."""
    choices = []
    for ch in (ranking or '').strip().upper():
        if ch == NO_PRIZE_TOKEN:
            break
        prize_id = ord(ch) - ord('A') + 1
        if 1 <= prize_id <= C.NR_PRIZES:
            choices.append(prize_id)
    return choices


def _run_deferred_acceptance(priority_rank, rankings_by_pid):
    """Applicant-proposing Deferred Acceptance (Gale-Shapley) with per-prize capacities.

    priority_rank: pid -> rank (1 = highest priority), common to all prizes.
    rankings_by_pid: pid -> ordered list of prize ids (No Prize already truncated).

    Returns (assigned, remaining) where assigned maps pid -> prize id (or None if the
    applicant exhausted their list without securing a seat) and remaining maps
    prize id -> seats still open after part one.
    """
    capacities = _build_capacity_map()
    held = {prize_id: [] for prize_id in capacities}
    next_idx = {pid: 0 for pid in rankings_by_pid}
    # Only applicants who ranked at least one prize ever propose.
    free = [pid for pid in rankings_by_pid if rankings_by_pid[pid]]

    while free:
        pid = free.pop()
        if next_idx[pid] >= len(rankings_by_pid[pid]):
            continue  # list exhausted -> stays unmatched in part one

        prize = rankings_by_pid[pid][next_idx[pid]]
        next_idx[pid] += 1

        held[prize].append(pid)
        held[prize].sort(key=lambda x: priority_rank[x])  # best priority first
        if len(held[prize]) > capacities[prize]:
            rejected = held[prize].pop()  # lowest-priority applicant loses the seat
            if next_idx[rejected] < len(rankings_by_pid[rejected]):
                free.append(rejected)

    assigned = {pid: None for pid in rankings_by_pid}
    for prize, pids in held.items():
        for pid in pids:
            assigned[pid] = prize

    remaining = {prize_id: capacities[prize_id] - len(held[prize_id]) for prize_id in capacities}
    return assigned, remaining


def _random_fill_unmatched(assigned, remaining, priority_order):
    """Part two: applicants unmatched after DA randomly receive one of the remaining seats."""
    unmatched = [pid for pid in priority_order if assigned[pid] is None]
    seats = [prize_id for prize_id, n in remaining.items() for _ in range(n)]
    random.shuffle(seats)
    for pid, prize_id in zip(unmatched, seats):
        assigned[pid] = prize_id
        remaining[prize_id] -= 1


def get_available_prize_ids_before_turn(player: Player):
    """Prizes that still have an open seat once all strictly-higher-priority applicants are placed.

    Because the seed priorities are a single common order over players, the top-priority
    applicants' Deferred Acceptance seats coincide with a serial dictatorship among them, and
    the online participant can secure a seat at exactly the prizes that still have capacity here.
    """
    lab_round = LAB_DATA[player.lab_round_num][player.lab_group_num]
    priorities = json.loads(lab_round['priorities'])
    priority_map = {player_id: rank for rank, player_id in enumerate(priorities, start=1)}
    my_priority = priority_map[player.replaced_id]

    lab_rankings = lab_round['rankings']
    remaining_seats = _build_capacity_map()
    priority_order = sorted(range(1, C.NUM_LAB_PLAYERS + 1), key=lambda pid: priority_map[pid])

    for pid in priority_order:
        if priority_map[pid] >= my_priority:
            break  # reached the online participant's slot

        for prize_id in _ranking_to_prize_ids(lab_rankings.get(pid, '')):
            if remaining_seats.get(prize_id, 0) > 0:
                remaining_seats[prize_id] -= 1
                break

    return sorted(prize_id for prize_id, seats_left in remaining_seats.items() if seats_left > 0)


# --- Deferred Acceptance allocation logic ---
def run_deferred_acceptance(player: Player):
    # Retrieve and validate the unique lab data assigned to this round.
    lab_round_data = LAB_DATA.get(player.lab_round_num)
    if not lab_round_data or player.lab_group_num not in lab_round_data:
        raise RuntimeError(
            f"Missing lab context for round/group {(player.lab_round_num, player.lab_group_num)}"
        )

    lab_round = lab_round_data[player.lab_group_num]
    replaced_id = player.replaced_id or 1
    if replaced_id not in lab_round['valuations']:
        raise RuntimeError(
            f"No valuation row for replaced_id={replaced_id} in "
            f"{(player.lab_round_num, player.lab_group_num)}"
        )

    priorities = json.loads(lab_round['priorities'])
    valuations = json.loads(lab_round['valuations'][replaced_id])
    lab_rankings = lab_round['rankings']

    priority_rank = {pid: rank for rank, pid in enumerate(priorities, start=1)}
    if replaced_id not in priority_rank:
        raise RuntimeError(f"replaced_id={replaced_id} is missing from priorities {priorities}")

    # Players ordered by the common priority (highest priority first).
    priority_order = sorted(range(1, C.NUM_LAB_PLAYERS + 1), key=lambda pid: priority_rank[pid])

    # The online participant occupies the replaced lab player's priority slot; everyone else
    # is seeded from the lab data. Build each applicant's ordered prize-id list.
    rankings_by_pid = {}
    for pid in range(1, C.NUM_LAB_PLAYERS + 1):
        if pid == replaced_id:
            rankings_by_pid[pid] = _ranking_to_prize_ids(player.pref_ranking)
        else:
            rankings_by_pid[pid] = _ranking_to_prize_ids(lab_rankings.get(pid, ''))

    # ==========================================================
    # SCENARIO 1: Online participant replaces lab participant
    # ==========================================================
    # Part one: applicant-proposing Deferred Acceptance with per-prize capacities.
    assigned, remaining = _run_deferred_acceptance(priority_rank, rankings_by_pid)

    if assigned[replaced_id] is not None:
        # Part two: applicants still unmatched randomly receive a remaining seat.
        _random_fill_unmatched(assigned, remaining, priority_order)
        my_prize = assigned[replaced_id]

    else:
        # ==========================================================
        # SCENARIO 2: Online unmatched -> Insert and shift priorities
        # ==========================================================
        k = priority_rank[replaced_id]
        insert_index = k - 1  # Convert 1-based priority to 0-based index

        # Create new queue: Insert online, shift everyone back, drop the last person
        new_priority_pids = priority_order.copy()
        new_priority_pids.insert(insert_index, 'online')
        new_priority_pids = new_priority_pids[:C.NUM_LAB_PLAYERS]

        # Ranks are re-derived from the new queue order so DA sees 1..NUM_LAB_PLAYERS.
        new_priority_rank = {pid: i + 1 for i, pid in enumerate(new_priority_pids)}

        new_rankings_by_pid = {}
        for pid in new_priority_pids:
            if pid == 'online':
                new_rankings_by_pid['online'] = _ranking_to_prize_ids(player.pref_ranking)
            else:
                new_rankings_by_pid[pid] = _ranking_to_prize_ids(lab_rankings.get(pid, ''))

        # Part one + part two for the new shifted group
        assigned2, remaining2 = _run_deferred_acceptance(new_priority_rank, new_rankings_by_pid)
        _random_fill_unmatched(assigned2, remaining2, new_priority_pids)
        my_prize = assigned2['online']

    # ==========================================================
    # RECORD RESULTS
    # ==========================================================
    player.assigned_prize = my_prize
    if my_prize and not 1 <= my_prize <= len(valuations):
        raise RuntimeError(
            f"Prize {my_prize} is out of bounds for valuations length {len(valuations)}"
        )
    player.payoff = valuations[my_prize - 1] if my_prize else 0
    my_priority = priority_rank[replaced_id]

    schedule = player.participant.vars.get('e1_schedule', [])
    schedule.append([player.round_number, my_priority, player.assigned_prize])
    player.participant.vars['e1_schedule'] = schedule
    
    player.participant.vars['e1_successful'] = [
        i + 1 == player.assigned_prize for i in range(C.NR_PRIZES)
    ]
# endregion
# region Pages
# --- Pages ---
class Consent(Page):
    @staticmethod
    def is_displayed(player: Player):
        return player.subsession.round_number == 1 
    
class InstructionsQuiz(Page):
    form_model = 'player'
    form_fields = ['quiz1', 'quiz2', 'quiz3', 'quiz4', 'quiz5', 'quiz6', 'quiz7', 'quiz8', 'quiz9',
        'quiz10', 'quiz11', 'quiz12', 'quiz13', 'quiz14', 'quiz15', 'quiz16', 'quiz17', 'quiz18',
        'quiz19', 'quiz20', 'quiz21', 'quiz22', 'quiz23', 'quiz24', 'quiz25', 'quiz26', 'quiz27',
        'quiz28', 'quiz29', 'quiz30', 'quiz31', 'quiz32', 'quiz1_attempts', 'quiz2_attempts',
        'quiz3_attempts', 'quiz4_attempts', 'quiz5_attempts', 'quiz6_attempts',
        'failed_quiz']
    
    @staticmethod
    def vars_for_template(player: Player):
        lab_round = LAB_DATA[player.lab_round_num][player.lab_group_num]
        priorities = json.loads(lab_round['priorities'])
        valuations = json.loads(lab_round['valuations'][player.replaced_id])
        priority_map = {player_id: rank for rank, player_id in enumerate(priorities, start=1)}
        my_priority = priority_map[player.replaced_id]
        letters = [chr(ord('A') + j) for j in range(C.NR_PRIZES)]
        def ordinal(n):
            s = {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10 * (n % 100 not in (11, 12, 13)), 'th')
            return f"{n}{s}"
        return dict(
            nr_prizes = C.NR_PRIZES,
            nr_prizes_ordinal = ordinal(C.NR_PRIZES),
            nr_players_ordinal = ordinal(C.NUM_LAB_PLAYERS),
            nr_rounds = C.NUM_ROUNDS,
            nr_others=C.NUM_LAB_PLAYERS - 1,
            players_per_group = C.NUM_LAB_PLAYERS,
            indices = [j for j in range(1, C.NR_PRIZES + 1)],
            letters = letters,
            letters_str = ','.join(letters),
            valuations = valuations,
            priorities = [my_priority] * C.NR_PRIZES,
            capacities = C.CAPACITIES,
            round_number = player.subsession.round_number,
            total_rounds = C.NUM_ROUNDS,
        )

    @staticmethod
    def is_displayed(player):
        return player.subsession.round_number == 1
    @staticmethod
    def js_vars(player: Player):
        return dict(
            nr_prizes=C.NR_PRIZES, # (You already had this one here!)
            ALIGNED=C.ALIGNED,      # <-- Add this new line!
            LIVE = C.LIVE,
        )
    @staticmethod
    def before_next_page(player: Player, timeout_happened):
        # If the JavaScript flagged them as failed, strip their bonus and save it to memory
        if player.failed_quiz:
            player.participant.vars['failed_quiz'] = True
            player.participant.vars['bonus_payout'] = 0
            
    @staticmethod
    def app_after_this_page(player: Player, upcoming_apps):
        # Eject them immediately to the final survey app if they failed
        if player.failed_quiz:
            return 'survey'
class Decision(Page):
    form_model = 'player'
    form_fields = ['pref_ranking']
    @staticmethod
    def vars_for_template(player: Player):
        lab_round = LAB_DATA[player.lab_round_num][player.lab_group_num]
        priorities = json.loads(lab_round['priorities'])
        valuations = json.loads(lab_round['valuations'][player.replaced_id])
        priority_map = {player_id: rank for rank, player_id in enumerate(priorities, start=1)}
        my_priority = priority_map[player.replaced_id]
        my_group, is_lowest_in_group = _group_context(
            lab_round, player.replaced_id, priority_map
        )
        available_prize_ids = get_available_prize_ids_before_turn(player)

        _store_export_snapshot(player)
        player.available_prizes_at_turn = json.dumps(available_prize_ids)

        def ordinal(n):
            s = {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10 * (n % 100 not in (11, 12, 13)), 'th')
            return f"{n}{s}"

        letters_alpha = [chr(ord('A') + j) for j in range(C.NR_PRIZES)]

        # Keep display rows aligned by sorting letter/value/status together.
        prize_rows = []
        for prize_idx, value in enumerate(valuations, start=1):
            prize_rows.append(dict(
                letter=chr(ord('A') + prize_idx - 1),
                capacity=C.CAPACITIES[prize_idx - 1],
                value=value,
                status='Available' if prize_idx in available_prize_ids else 'Taken',
            ))

        prize_rows.sort(key=lambda row: row['value'], reverse=True)
        sorted_letters = [row['letter'] for row in prize_rows]
        sorted_valuations = [row['value'] for row in prize_rows]
        sorted_prize_statuses = [row['status'] for row in prize_rows]
            
        return dict(
            nr_prizes=C.NR_PRIZES,
            nr_prizes_ordinal=ordinal(C.NR_PRIZES),
            nr_players_ordinal=ordinal(C.NUM_LAB_PLAYERS),
            nr_rounds=C.NUM_ROUNDS,
            nr_others=C.NUM_LAB_PLAYERS - 1,
            players_per_group=C.NUM_LAB_PLAYERS,
            indices=list(range(1, C.NR_PRIZES + 1)),
            letters=sorted_letters,
            letters_alpha=letters_alpha,
            letters_str=','.join([chr(ord('A') + j) for j in range(C.NR_PRIZES)]),
            valuations=sorted_valuations,
            my_priority=my_priority,
            priorities=[my_priority] * C.NR_PRIZES,
            capacities=C.CAPACITIES,
            prize_rows=prize_rows,
            my_group=my_group,
            is_lowest_in_group=is_lowest_in_group,
            round_number=player.subsession.round_number, 
            total_rounds=C.NUM_ROUNDS,
            prize_statuses=sorted_prize_statuses,
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

        # Safety Check: Ensure they are valid letters
        if not set(selected_prizes).issubset(EXPECTED_PRIZE_SET | {NO_PRIZE_TOKEN}):
            return "Please select valid prizes from the dropdown menus."
    @staticmethod
    def before_next_page(player: Player, timeout_happened):
        clean_ranking = player.pref_ranking.replace('-', '').strip().upper()
        player.pref_ranking = clean_ranking      
        player.participant.vars['e1_player_prefs'] = [[rank] for rank in map_ranking_string_to_prefs(player.pref_ranking)]
        
        # Run the algorithm instantly!
        run_deferred_acceptance(player)
        current_global_period = player.subsession.round_number + C.APP_ROUND_OFFSET

        
        # Catch the payout if the current period matches the randomly drawn one
        if current_global_period == player.session.vars['paying_round']:
            player.participant.vars['bonus_payout'] = player.payoff

    @staticmethod
    def is_displayed(player: Player):
        return True
    @staticmethod
    def js_vars(player: Player):
        # Never ship availability to the browser here: the robot-agent plan is entirely
        # hypothetical, so the page must not know which prizes still have an open seat.
        # (vars_for_template still records available_prizes_at_turn for the export.)
        return dict(
            nr_prizes=C.NR_PRIZES,
            ALIGNED=C.ALIGNED,
            LIVE=C.LIVE,
        )
    @staticmethod
    def app_after_this_page(player: Player, upcoming_apps):
        # Once they submit their final decision, teleport them to survey
        if player.round_number == C.NUM_ROUNDS:
            return 'survey'
        
      
# endregion
page_sequence = [Consent, InstructionsQuiz, Decision] 
