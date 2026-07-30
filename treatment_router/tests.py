from otree.api import Bot, Submission
from . import RouteToTreatment


class PlayerBot(Bot):
    def play_round(self):
        yield Submission(RouteToTreatment, check_html=False)
