from .base import TuyaDevice


class TuyaScene(TuyaDevice):
    def available(self):
        return True

    def activate(self):
        self.api.device_control(self.obj_id, "turnOnOff", {"value": "1"})

    def update(self, use_discovery=True):
        return True
