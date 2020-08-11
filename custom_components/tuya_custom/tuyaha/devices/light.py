from .base import TuyaDevice

"""The minimum brightness value set in the API that does not turn off the light."""
MIN_BRIGHTNESS = 10.3


class TuyaLight(TuyaDevice):

    def __init__(self, data, api):
        super().__init__(data, api)
        self._support_color = False

    def set_support_color(self, supported):
        self._support_color = supported

    def _color_mode(self):
        work_mode = self.data.get("color_mode", "white")
        return True if work_mode == "colour" else False

    @staticmethod
    def _convert_scale(value, old_min, old_max, new_min, new_max):
        if value == 0:
            return 0
        new_val = max(min(value, old_max), old_min)
        return max(round((new_val / old_max) * new_max), new_min)

    def _standard_brightness(self, value):
        return TuyaLight._convert_scale(
            value,
            self.min_brightness(),
            self.max_brightness(),
            1,
            255,
        )

    def _tuya_brightness(self, value):
        return TuyaLight._convert_scale(
            value,
            1,
            255,
            self.min_brightness(),
            self.max_brightness(),
        )

    def brightness(self):
        brightness = -1
        if self._color_mode():
            if "color" in self.data:
                brightness = int(self.data.get("color").get("brightness", "-1"))
        else:
            brightness = int(self.data.get("brightness", "-1"))
        return self._standard_brightness(brightness)

    def _set_brightness(self, brightness):
        if self._color_mode():
            data = self.data.get("color", {})
            data["brightness"] = brightness
            self._update_data("color", data, force_val=True)
        else:
            self._update_data("brightness", brightness)

    def min_brightness(self, mode_color: bool = None):
        if mode_color is True or (mode_color is None and self._color_mode()):
            return 1
        else:
            return 10

    def max_brightness(self, mode_color: bool = None):
        if mode_color is True or (mode_color is None and self._color_mode()):
            return 255
        else:
            return 1000

    def support_color(self):
        if not self._support_color:
            if self.data.get("color") or self.data.get("color_mode") == "colour":
                self._support_color = True
        return self._support_color

    def support_color_temp(self):
        return self.data.get("color_temp") is not None

    def hs_color(self):
        if self.support_color():
            color = self.data.get("color")
            if self._color_mode() and color:
                return color.get("hue", 0.0), float(color.get("saturation", 0.0)) * 100
            else:
                return 0.0, 0.0
        else:
            return None

    def color_temp(self):
        return self.data.get("color_temp")

    def min_color_temp(self):
        return 10000

    def max_color_temp(self):
        return 1000

    def turn_on(self):
        if self._control_device("turnOnOff", {"value": "1"}):
            self._update_data("state", "true")

    def turn_off(self):
        if self._control_device("turnOnOff", {"value": "0"}):
            self._update_data("state", "false")

    def set_brightness(self, brightness):
        """Set the brightness(0-255) of light."""
        if int(brightness) > 0:
            """convert to scale 0-100 with MIN_BRIGHTNESS."""
            set_value = round(min(max(brightness * 100 / 255.0, MIN_BRIGHTNESS), 100), 1)
            value = self._tuya_brightness(brightness)
            if self._control_device("brightnessSet", {"value": set_value}):
                self._update_data("state", "true")
                self._set_brightness(value)
        else:
            self.turn_off()

    def set_color(self, color):
        """Set the color of light."""
        cur_brightness = self.data.get("color", {}).get(
            "brightness", self.min_brightness(mode_color=True)
        )
        hsv_color = {
            "hue": color[0] if color[1] != 0 else 0,  # color white
            "saturation": color[1] / 100,
        }
        if len(color) < 3:
            hsv_color["brightness"] = cur_brightness
        else:
            hsv_color["brightness"] = color[2]
        # color white
        white_mode = hsv_color["saturation"] == 0
        is_color = self._color_mode()
        if self._control_device("colorSet", {"color": hsv_color}):
            self._update_data("state", "true")
            self._update_data("color", hsv_color, force_val=True)
            if not is_color and not white_mode:
                self._update_data("color_mode", "colour")
            elif is_color and white_mode:
                self._update_data("color_mode", "white")

    def set_color_temp(self, color_temp):
        if self._control_device("colorTemperatureSet", {"value": color_temp}):
            self._update_data("state", "true")
            self._update_data("color_mode", "white")
            self._update_data("color_temp", color_temp)

    def update(self):
        return self._update(use_discovery=True)
