import time
import logging

_LOGGER = logging.getLogger(__name__)


class TuyaDevice:
    def __init__(self, data, api):
        self.api = api
        self.data = data.get("data")
        self.obj_id = data.get("id")
        self.obj_type = data.get("ha_type")
        self.obj_name = data.get("name")
        self.dev_type = data.get("dev_type")
        self.icon = data.get("icon")

    def _update_data(self, key, value):
        if self.data:
            self.data[key] = value
            self.api.update_device_data(self.obj_id, self.data)

    def _control_device(self, action, param=None):
        success, response = self.api.device_control(self.obj_id, action, param)
        if not success:
            self._update_data("online", False)
        return success

    def _update(self, use_discovery=False):
        """Avoid get cache value after control."""
        time.sleep(0.5)

        if use_discovery:
            # workaround for https://github.com/PaulAnnekov/tuyaha/issues/3
            devices = self.api.discovery()
            if not devices:
                return
            for device in devices:
                if device["id"] == self.obj_id:
                    if not self.data:
                        self.data = {}
                    self.data.update(device["data"])
                    return True
            return

        success, response = self.api.device_control(
            self.obj_id, "QueryDevice", namespace="query"
        )
        if success:
            # _LOGGER.info(response)
            self.data = response["payload"]["data"]
            return True
        return

    def name(self):
        return self.obj_name

    def state(self):
        state = self.data.get("state")
        if state is None:
            return None
        elif isinstance(state, str):
            if state == "true":
                return True
            return False
        else:
            return bool(state)

    def device_type(self):
        return self.dev_type

    def object_id(self):
        return self.obj_id

    def object_type(self):
        return self.obj_type

    def available(self):
        return self.data.get("online")

    def iconurl(self):
        return self.icon

    def update(self):
        return self._update()
