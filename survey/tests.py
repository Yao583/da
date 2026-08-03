from otree.api import Bot, Submission, SubmissionMustFail
from . import Demographics, StudyFull, ThankYou

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
    matching_experience='Yes', matching_influence=6,
    intergenerational_advice=ADVICE, comments='',
    website='',  # honeypot left empty -> not flagged as bot
)

# Locks in the 50-word floor enforced by Demographics.error_message.
SHORT = dict(DEMO, intergenerational_advice='rank truthfully')

# 'Yes' with no slider value is rejected; 'No' with no slider value is N/A and fine.
NO_SLIDER = dict(DEMO, matching_influence=None)
NO_EXPERIENCE = dict(DEMO, matching_experience='No', matching_influence=None)


class PlayerBot(Bot):
    def play_round(self):
        # Arrivals the router turned away because every bucket was full stop on StudyFull:
        # Demographics and ThankYou both skip them, so they are never shown a completion
        # code. A human has no next button here; the bot submits it only to reach the end
        # of the session, and asserts they were routed nowhere and paid nothing.
        if self.participant.vars.get('screened_out'):
            assert self.participant.vars.get('treatment') is None
            yield Submission(StudyFull, check_html=False)
            assert self.participant.vars.get('total_payment') == 0
            assert self.participant.payoff == 0
            return

        # Ejected from their treatment by the 4-strikes quiz rule: Demographics skips them
        # too, so they go straight to ThankYou for the base payment. They still reach the
        # end, but the router must not count them towards a bucket's quota.
        if self.participant.vars.get('failed_quiz'):
            yield Submission(ThankYou, check_html=False)
            assert self.participant.vars.get('study_completed') is True
            return

        yield SubmissionMustFail(Demographics, SHORT, check_html=False)
        yield SubmissionMustFail(Demographics, NO_SLIDER, check_html=False)
        # Alternate the branches so both the 'Yes' + rating and the 'No' == N/A
        # paths are exercised within one session.
        answers = DEMO if self.player.id_in_group % 2 else NO_EXPERIENCE
        yield Submission(Demographics, answers, check_html=False)
        yield Submission(ThankYou, check_html=False)
