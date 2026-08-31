import logging
from flask import redirect

from pwnagotchi import plugins
from pwnagotchi.utils import StatusFile


class ChannelControl(plugins.Plugin):
    __author__ = 'ex18a'
    __version__ = '1.0.0'
    __license__ = 'GPL3'
    __description__ = ('Live on/off switch (Web UI -> Plugins) for whether the AI may pick 5GHz '
                        'channels in addition to 2.4GHz, which always stays available. Works by '
                        'filtering the already-uncapped channel list ai/train.py hands to plugins '
                        'via the ai_policy hook -- never touches the trained model\'s action space '
                        '(that\'s sized from real hardware capability at startup, in ai/gym.py), so '
                        'toggling this at any point never invalidates brain.nn.')

    def __init__(self):
        self.enable_5ghz = True
        self._status = None

    def on_loaded(self):
        default = bool(self.options.get('enable_5ghz', True))
        try:
            self._status = StatusFile('/root/.channel_control', data_format='json')
            self.enable_5ghz = bool(self._status.data_field_or('enable_5ghz', default=default))
        except Exception as e:
            logging.error("channel_control: failed to load saved state (%s)" % e)
            self.enable_5ghz = default
        logging.info("channel_control loaded, 5ghz %s" % ("enabled" if self.enable_5ghz else "disabled"))

    def _save(self):
        if self._status is None:
            return
        try:
            self._status.update(data={'enable_5ghz': self.enable_5ghz})
        except Exception as e:
            logging.error("channel_control: failed to save state (%s)" % e)

    def on_ai_policy(self, agent, policy):
        if self.enable_5ghz:
            return
        if not policy.get('channels'):
            return
        policy['channels'] = [ch for ch in policy['channels'] if ch <= 14]

    def on_webhook(self, path, request):
        if path == "toggle":
            self.enable_5ghz = not self.enable_5ghz
            self._save()
            logging.info("channel_control: 5ghz now %s" % ("enabled" if self.enable_5ghz else "disabled"))
            return redirect(".")

        status = "enabled" if self.enable_5ghz else "disabled"
        action = "Disable" if self.enable_5ghz else "Enable"
        return """
        <html><head><meta name="viewport" content="width=device-width, initial-scale=1">
        <title>Channel Control</title></head>
        <body style="font-family:sans-serif;background:#111;color:#eee;padding:24px">
        <h2>Channel Control</h2>
        <p>2.4GHz channels are always available to the AI.</p>
        <p>5GHz channels are currently <b>%s</b>.</p>
        <a href="./toggle" style="display:inline-block;padding:12px 24px;background:#333;
           color:#fff;text-decoration:none;border-radius:8px;font-size:16px">%s 5GHz</a>
        </body></html>
        """ % (status, action)
