from os import environ
# settings.py
SESSION_CONFIGS = [
    dict(
        name='prolific_experiment',
        # --- TWO-ARM STUDY: da and agent_da ----------------------------------
        # The treatment list lives in two places and they must be changed together:
        # app_sequence below and allocation.TREATMENTS. The router raises if it draws
        # a treatment that is not in app_sequence, so a mismatch is a 500 mid-session
        # rather than a startup error. boston / agent_boston are not run here: leaving
        # them in app_sequence would also cost 5 unused Player rows each per slot.
        display_name="Prolific study: da / agent_da",
        # Participant SLOTS, not the recruitment target. Every arrival burns one --
        # finishers, quiz-fails, silent dropouts, and everyone turned away after the
        # study fills. Once they run out oTree answers a bare "Session is full." 404
        # instead of the survey app's StudyFull page, so keep generous headroom: the
        # da-only pilot burned 104 slots for 48 usable finishers (2.17x). The 1,504
        # usable finishers targeted below therefore need ~3,300; 8,000 is the headroom
        # chosen for this run. Note the router rescans every slot in the session on each
        # arrival, so oversizing costs speed, not just database rows.
        # NOTE: for a room session this only prefills the create-session form; the
        # number you type there is what counts.
        num_demo_participants=5000,
        # Groups of 8 formed per treatment. Bucket targets are 3M/M/3M/M (A_normal/A_lowest/
        # B_normal/B_lowest), so each treatment needs 8*M usable finishers. Watch the router's
        # admin report and keep Prolific places open until every bucket's "remaining" hits 0.
        # Here: 8 * 94 markets = 752 usable per treatment, i.e. per-treatment targets of
        # 282/94/282/94, and 1,504 usable finishers across the two arms.
        markets_per_treatment=94,
        app_sequence=[
            'treatment_router',
            'da',
            'agent_da',
            'survey',
        ],
    ),

]

ROOMS = [
    dict(
        name='prolific_study',
        display_name='Prolific Study'
    ),
]
# if you set a property in SESSION_CONFIG_DEFAULTS, it will be inherited by all configs
# in SESSION_CONFIGS, except those that explicitly override it.
# the session config can be accessed from methods in your apps as self.session.config,
# e.g. self.session.config['participation_fee']

SESSION_CONFIG_DEFAULTS = dict(
    real_world_currency_per_point=1.00, participation_fee=6.50, doc=""
)

PARTICIPANT_FIELDS = [
    # Which treatment app the router sent this participant to. oTree runs
    # creating_session for every app, so the export contains da/boston/agent_da/
    # agent_boston rows for participants who never played them -- filter on this column.
    'treatment',
    # Group-of-8 assignment (set by the router; used for post-hoc allocation in survey).
    'role',            # 'A' (values A>B) or 'B' (values B>A); fixed for the whole study
    'is_lowest',       # designated lowest-priority member of their group (A or B)
    'bucket',          # 'A_normal' | 'A_lowest' | 'B_normal' | 'B_lowest'
    'screened_out',    # arrived after all buckets were full (study full); unpaid, asked to
                       # return their Prolific submission (no completion code)
    'market_id',       # id of the assembled group of 8, e.g. 'da-3' (also the RNG seed)
    'market_pid',      # this member's 1..8 slot in the market (with market_id -> reconstructable)
    'market_vals',     # {round: [6 valuations]} the participant actually saw
    'market_ranking',  # {round: ranking string} the participant submitted
    'market_detail',   # {round: {prize, payoff}} from the post-hoc allocation
    'market_queued',   # internal: queued for grouping (assembled at most once)
    'bonus_payout',
    'failed_quiz',
    'study_completed',
    'e1_schedule',
    'e1_successful',
    'e1_valuations',
    'e1_player_prefs',
    'e2_schedule',
    'e2_successful',
    'e2_valuations',
    'e2_player_prefs',
    'total_payment',
    # --- AI-usage instrumentation (soft research flags, see ai_detect.py).
    # Written by ai_detect.record(); for post-hoc exclusion only, nothing routes on it.
    'ai_score', 'ai_flags',
    'ai_blur', 'ai_hid', 'ai_hid_ms', 'ai_hid_max',
    'ai_copy', 'ai_cut', 'ai_copy_ch', 'ai_copy_sample',
    # ai_paste/_ch count paste ATTEMPTS (paste_guard.js cancels them) and include
    # text dragged in; ai_drop says how many of those arrivals were drags.
    'ai_paste', 'ai_paste_ch', 'ai_drop', 'ai_jump_max', 'ai_jumps', 'ai_sel_max',
    'ai_keys', 'ai_ime', 'ai_mouse', 'ai_scroll', 'ai_touch', 'ai_click',
    'ai_loads', 'ai_ctx',
    'ai_advice_len', 'ai_advice_keys', 'ai_advice_ratio', 'ai_advice_pastes',
    'ai_advice_ttfk', 'ai_advice_ms', 'ai_advice_jump_max', 'ai_advice_ime',
    # --- schema 2: revisions, study-wide across every text field ---
    'ai_bksp', 'ai_del', 'ai_mid', 'ai_mid_ep',
    # --- schema 2: typing rhythm, study-wide ---
    'ai_pause', 'ai_iki_n', 'ai_iki_sum', 'ai_iki_sq', 'ai_iki_min', 'ai_iki_max',
    'ai_iki_hist',
    # --- schema 2: revisions and rhythm on the free-text answer ---
    'ai_advice_bksp', 'ai_advice_del', 'ai_advice_bksp_rate', 'ai_advice_prod_ratio',
    'ai_advice_mid', 'ai_advice_mid_ep',
    'ai_advice_iki_n', 'ai_advice_iki_mean', 'ai_advice_iki_sd', 'ai_advice_iki_cv',
    'ai_advice_iki_min', 'ai_advice_iki_max', 'ai_advice_pauses',
    'ai_advice_iki_p10', 'ai_advice_iki_p50', 'ai_advice_iki_p90',
    'ai_advice_iki_exact', 'ai_advice_iki_hist',
    # The raw base36 gap sequence. Also present inside ai_tel_demographics; kept
    # here too so the wide CSV is self-contained for the timing analysis.
    'ai_advice_iki_raw', 'ai_advice_iki_trunc',
    'ai_webdriver', 'ai_env',
    'ai_no_pointer_pages', 'ai_bad_blobs', 'ai_pages_instrumented', 'ai_pages',
    'ai_schema',
]
SESSION_FIELDS = []

# ISO-639 code
# for example: de, fr, ja, ko, zh-hans
LANGUAGE_CODE = 'en'

# e.g. EUR, GBP, CNY, JPY
REAL_WORLD_CURRENCY_CODE = 'USD'
USE_POINTS = False

ADMIN_USERNAME = 'admin'
# for security, best to set admin password in an environment variable
ADMIN_PASSWORD = environ.get('OTREE_ADMIN_PASSWORD')

DEMO_PAGE_INTRO_HTML = """ """

SECRET_KEY = '9969439832928'
