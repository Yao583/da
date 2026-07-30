from otree.api import Bot, Submission
from . import Demographics, ThankYou

DEMO = dict(
    age=30, lgbtq='No', education='High school', state='CA', community='Urban',
    employment='Student', income='Prefer not to say',
    politics='Moderate, middle of the road', party='A Democrat',
    intergenerational_advice='rank truthfully', comments='',
    website='',  # honeypot left empty -> not flagged as bot
)


class PlayerBot(Bot):
    def play_round(self):
        yield Submission(Demographics, DEMO, check_html=False)
        yield Submission(ThankYou, check_html=False)
