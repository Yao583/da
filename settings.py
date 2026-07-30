from os import environ
# settings.py
SESSION_CONFIGS = [
    dict(
        name='prolific_experiment',
        display_name="Prolific: Router to 4 Treatments",
        num_demo_participants=32,
        # Groups of 8 formed per treatment. Bucket targets are 3M/M/3M/M (A_normal/A_lowest/
        # B_normal/B_lowest), so each treatment needs 8*M usable finishers. Watch the router's
        # admin report and keep Prolific places open until every bucket's "remaining" hits 0.
        markets_per_treatment=1,
        prolific_bot_redirect_url='https://app.prolific.com/submissions/complete?cc=C1HW4JRM',
        app_sequence=[
            'treatment_router',
            'da',
            'boston',
            'agent_da',
            'agent_boston',
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
    real_world_currency_per_point=1.00, participation_fee=2.00, doc=""
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
    'screened_out',    # arrived after all buckets were full (study full); show-up fee only
    'market_id',       # id of the assembled group of 8, e.g. 'da-3' (also the RNG seed)
    'market_pid',      # this member's 1..8 slot in the market (with market_id -> reconstructable)
    'market_vals',     # {round: [6 valuations]} the participant actually saw
    'market_ranking',  # {round: ranking string} the participant submitted
    'market_detail',   # {round: {prize, payoff}} from the post-hoc allocation
    'market_queued',   # internal: queued for grouping (assembled at most once)
    'bonus_payout',
    'failed_quiz',
    'suspected_bot',
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
    # Written by ai_detect.record(); never feeds the suspected_bot hard block.
    'ai_score', 'ai_flags',
    'ai_blur', 'ai_hid', 'ai_hid_ms', 'ai_hid_max',
    'ai_copy', 'ai_cut', 'ai_copy_ch', 'ai_copy_sample',
    'ai_paste', 'ai_paste_ch', 'ai_jump_max', 'ai_jumps', 'ai_sel_max',
    'ai_keys', 'ai_ime', 'ai_mouse', 'ai_scroll', 'ai_touch', 'ai_click',
    'ai_loads', 'ai_ctx',
    'ai_advice_len', 'ai_advice_keys', 'ai_advice_ratio', 'ai_advice_pastes',
    'ai_advice_ttfk', 'ai_advice_ms', 'ai_advice_jump_max', 'ai_advice_ime',
    'ai_webdriver', 'ai_env',
    'ai_no_pointer_pages', 'ai_bad_blobs', 'ai_pages_instrumented', 'ai_pages',
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
