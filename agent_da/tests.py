from otree.api import Bot, Submission
from . import Consent, InstructionsQuiz, Decision

QUIZ = dict(
    quiz1='two', quiz2='one', quiz3='two', quiz4='one', quiz5=4, quiz6='1,2',
    quiz7='Prize A', quiz8='Prize B', quiz9=False, quiz10=True, quiz11=13,
    quiz12=True, quiz13=True, quiz14=True, quiz15=True, quiz16='2',
    quiz17=True, quiz18=True, quiz19=True, quiz20=True, quiz21=True,
    quiz22='1,2', quiz23='1,2', quiz24='1,2', quiz25='1,2',
    quiz26='May be unmatched', quiz27='No',
    quiz28='Only unmatched participants', quiz29='Only available prizes', quiz30=True,
    quiz31=True, quiz32='Full contingent plan',
    quiz1_attempts=0, quiz2_attempts=0, quiz3_attempts=0, quiz4_attempts=0, quiz5_attempts=0,
    quiz6_attempts=0, failed_quiz=False,
)


class PlayerBot(Bot):
    def play_round(self):
        if self.round_number == 1:
            yield Submission(Consent, check_html=False)
            yield Submission(InstructionsQuiz, QUIZ, check_html=False)
        yield Submission(Decision, dict(pref_ranking='ABCDEF'), check_html=False)
