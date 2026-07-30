from otree.api import Bot, Submission, SubmissionMustFail
from . import Demographics, ThankYou

# Must clear ai_detect.MIN_ADVICE_WORDS (50). This one is 77 words.
ADVICE = (
    "I would tell a future participant to slow down and read the instructions "
    "carefully before ranking anything, because the payment depends on the prize "
    "you actually receive. Rank the prizes in the order you truly value them, from "
    "highest to lowest, and do not try to guess what other participants will do. "
    "Overall I found the study clear, a little long, and reasonably interesting, "
    "and I did not run into any technical problems while completing it today."
)

DEMO = dict(
    age=30, lgbtq='No', education='High school', state='CA', community='Urban',
    employment='Student', income='Prefer not to say',
    politics='Moderate, middle of the road', party='A Democrat',
    intergenerational_advice=ADVICE, comments='',
    website='',  # honeypot left empty -> not flagged as bot
)

# Locks in the 50-word floor enforced by Demographics.error_message.
SHORT = dict(DEMO, intergenerational_advice='rank truthfully')


class PlayerBot(Bot):
    def play_round(self):
        yield SubmissionMustFail(Demographics, SHORT, check_html=False)
        yield Submission(Demographics, DEMO, check_html=False)
        yield Submission(ThankYou, check_html=False)
