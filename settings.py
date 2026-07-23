from os import environ
# settings.py
SESSION_CONFIGS = [
    dict(
        name='prolific_experiment',
        display_name="Prolific: Router to 4 Treatments",
        num_demo_participants=5,
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
