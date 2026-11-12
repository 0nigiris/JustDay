from justday.hearing import HearingMixin


class Fake(HearingMixin):
    def __init__(self, barge):
        self.cfg = {"audio": {"barge_in": barge}}
        self.state, self.stopped, self.heard = "speaking", False, False
        self._holding, self._activation = False, ""
        self.brain = type("B", (), {"busy": False})()

    def stop_speaking(self):
        self.stopped = True

    def listen(self, followup=False, prefill=None):
        self.heard = True
        return True


def test_name_interrupts_answer_only_when_allowed():
    """«Джарвис, стоп» посреди ответа: с настройкой он замолкает и слушает, без неё — как раньше, не слышит."""
    on = Fake(True)
    on._wake_by_name(None, lambda: None)
    assert on.stopped and on.heard
    off = Fake(False)
    off._wake_by_name(None, lambda: None)
    assert not off.stopped and not off.heard
