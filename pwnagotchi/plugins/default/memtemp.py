from pwnagotchi.ui.components import LabeledValue
import pwnagotchi.ui.view as view
import pwnagotchi.ui.fonts as fonts
import pwnagotchi.plugins as plugins
import pwnagotchi
import logging
import time


class MemTemp(plugins.Plugin):
    __author__ = 'https://github.com/xenDE'
    __version__ = '1.0.5'
    __license__ = 'GPL3'
    __description__ = 'A plugin that will display memory/cpu usage and temperature'

    ALLOWED_FIELDS = {
        'mem': 'mem_usage',
        'cpu': 'cpu_load',
        'temp': 'cpu_temp',
        'freq': 'cpu_freq'
    }
    DEFAULT_FIELDS = ['mem', 'cpu', 'temp']
    LINE_SPACING = 11
    LABEL_SPACING = 5
    FIELD_WIDTH = 4
    REFRESH_INTERVAL = 15

    def on_loaded(self):
        self._last_refresh = 0.0
        logging.info("memtemp plugin loaded.")

    def mem_usage(self):
        return f"{int(pwnagotchi.mem_usage() * 100)}%"

    def cpu_load(self):
        return f"{int(pwnagotchi.cpu_load() * 100)}%"

    def cpu_temp(self):
        if self.options['scale'] == "fahrenheit":
            temp = (pwnagotchi.temperature() * 9 / 5) + 32
            symbol = "f"
        elif self.options['scale'] == "kelvin":
            temp = pwnagotchi.temperature() + 273.15
            symbol = "k"
        else:
            temp = pwnagotchi.temperature()
            symbol = "c"
        return f"{temp}{symbol}"

    def cpu_freq(self):
        with open('/sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq', 'rt') as fp:
            return f"{round(float(fp.readline())/1000000, 1)}G"

    def pad_text(self, data):
        return " " * (self.FIELD_WIDTH - len(data)) + data

    def field_positions(self, ui):
        positions = {}
        for field in self.ALLOWED_FIELDS:
            layout_pos = ui._layout.get(f"memtemp_{field}")
            if isinstance(layout_pos, (tuple, list)) and len(layout_pos) >= 2:
                positions[field] = (layout_pos[0], layout_pos[1])

        try:
            configured = self.options['positions']
        except Exception:
            return positions

        if not isinstance(configured, dict):
            logging.warning("memtemp: 'positions' must be a table of field = \"x,y\" entries, ignoring it.")
            return positions

        for key, value in configured.items():
            field = str(key).strip().lower()
            if field not in self.ALLOWED_FIELDS:
                logging.warning(f"memtemp: ignoring unknown field '{key}' in 'positions'.")
                continue
            try:
                parts = [int(x.strip()) for x in str(value).split(',')]
                positions[field] = (parts[0], parts[1])
            except Exception:
                logging.warning(f"memtemp: ignoring malformed position '{value}' for '{key}'.")
        return positions

    def on_ui_setup(self, ui):
        try:
            self.fields = self.options['fields'].split(',')
            self.fields = [x.strip() for x in self.fields if x.strip() in self.ALLOWED_FIELDS.keys()]
            self.fields = self.fields[:3]
        except Exception:
            self.fields = self.DEFAULT_FIELDS

        try:
            line_spacing = int(self.options['linespacing'])
        except Exception:
            line_spacing = self.LINE_SPACING

        try:
            pos = self.options['position'].split(',')
            pos = [int(x.strip()) for x in pos]
            v_pos = (pos[0], pos[1])
        except Exception:
            layout_header = ui._layout.get('memtemp_header')
            if layout_header:
                v_pos = layout_header
            elif ui.is_waveshare_v2():
                v_pos = (197, 74)
            elif ui.is_waveshare_v1():
                v_pos = (165, 61)
            elif ui.is_waveshare144lcd():
                v_pos = (73, 67)
            elif ui.is_inky():
                v_pos = (160, 54)
            elif ui.is_waveshare27inch():
                v_pos = (211, 122)
            else:
                v_pos = (175, 61)

        self._positions = self.field_positions(ui)

        for idx, field in enumerate(self.fields):
            v_pos_x = v_pos[0]
            v_pos_y = v_pos[1] + ((len(self.fields) - 3) * -1 * line_spacing)
            position = self._positions.get(field, (v_pos_x, v_pos_y + (idx * line_spacing)))
            label = field.upper() if field in self._positions else self.pad_text(field.upper())
            ui.add_element(
                f"memtemp_{field}",
                LabeledValue(
                    color=view.BLACK,
                    label=label,
                    value="-",
                    position=position,
                    label_font=fonts.Bold,
                    text_font=fonts.Medium,
                    label_spacing=self.LABEL_SPACING,
                )
            )

    def on_unload(self, ui):
        with ui._lock:
            for idx, field in enumerate(self.fields):
                ui.remove_element(f"memtemp_{field}")

    def on_ui_update(self, ui):
        now = time.time()
        if now - self._last_refresh < self.REFRESH_INTERVAL:
            return
        self._last_refresh = now

        for idx, field in enumerate(self.fields):
            reading = getattr(self, self.ALLOWED_FIELDS[field])()
            ui.set(f"memtemp_{field}", reading)
