import logging
import os
import random

# Store all the original defaults in a dictionary
_DEFAULTS = {
    'LOOK_R': '( ⚆_⚆)',
    'LOOK_L': '(☉_☉ )',
    'LOOK_R_HAPPY': '( ◕‿◕)',
    'LOOK_L_HAPPY': '(◕‿◕ )',
    'SLEEP': '(⇀‿‿↼)',
    'SLEEP2': '(≖‿‿≖)',
    'AWAKE': '(◕‿‿◕)',
    'BORED': '(-__-)',
    'INTENSE': '(°▃▃°)',
    'COOL': '(⌐■_■)',
    'HAPPY': '(•‿‿•)',
    'GRATEFUL': '(^‿‿^)',
    'EXCITED': '(ᵔ◡◡ᵔ)',
    'MOTIVATED': '(☼‿‿☼)',
    'DEMOTIVATED': '(≖__≖)',
    'SMART': '(✜‿‿✜)',
    'LONELY': '(ب__ب)',
    'SAD': '(╥☁╥ )',
    'ANGRY': "(-_-')",
    'FRIEND': '(♥‿‿♥)',
    'BROKEN': '(☓‿‿☓)',
    'BLIND': '(☓‿‿☓)',
    'DEBUG': '(#__#)',
    'UPLOAD': '(1__0)',
    'UPLOAD1': '(1__1)',
    'UPLOAD2': '(0__1)'
}

# Create a blank dictionary for your custom config overrides
_CONFIG_FACES = {}

IMAGE_EXTENSIONS = ('.png', '.bmp', '.jpg', '.jpeg', '.gif')

PNG = False
IMAGE_DIR = '/root/faces'

_IMAGES = {}
_IMAGE_NAMES = {}


def _is_image_path(value):
    return isinstance(value, str) and value.lower().endswith(IMAGE_EXTENSIONS) and os.path.isfile(value)


def _discover_images():
    _IMAGES.clear()
    _IMAGE_NAMES.clear()

    if not os.path.isdir(IMAGE_DIR):
        logging.warning(f"faces: png mode is on but '{IMAGE_DIR}' is not a directory -- falling back to text faces")
        return

    for face_name in _DEFAULTS:
        for extension in IMAGE_EXTENSIONS:
            path = os.path.join(IMAGE_DIR, f"{face_name.lower()}{extension}")
            if os.path.isfile(path):
                _IMAGES[face_name] = path
                _IMAGE_NAMES[path] = face_name
                break

    for face_name, face_value in _CONFIG_FACES.items():
        if _is_image_path(face_value):
            _IMAGES[face_name] = face_value
            _IMAGE_NAMES[face_value] = face_name

    missing = [n for n in _DEFAULTS if n not in _IMAGES]
    logging.info(f"faces: loaded {len(_IMAGES)} face images from {IMAGE_DIR}")
    if missing:
        logging.info(f"faces: still using text for {', '.join(sorted(missing))}")


def load_from_config(config):
    """Loads your config.toml face settings into the override dictionary"""
    global PNG, IMAGE_DIR

    for face_name, face_value in config.items():
        key = face_name.upper()
        if key == 'PNG':
            PNG = bool(face_value)
        elif key == 'IMAGE_DIR':
            IMAGE_DIR = str(face_value)
        else:
            _CONFIG_FACES[key] = face_value

    if PNG:
        _discover_images()


def as_text(value):
    """Maps a face image path back to a printable face, for logs and the status file"""
    face_name = _IMAGE_NAMES.get(value)
    if face_name is None:
        return value
    fallback = _CONFIG_FACES.get(face_name, _DEFAULTS.get(face_name))
    if isinstance(fallback, list):
        fallback = fallback[0]
    if _is_image_path(fallback):
        fallback = _DEFAULTS.get(face_name)
    return fallback or face_name

# The Interceptor: This runs every time the system asks for a face variable
def __getattr__(name):
    # Check if the face is in your config, otherwise use the default
    val = _CONFIG_FACES.get(name, _DEFAULTS.get(name))

    if val is not None:
        # If the value is a list (from your config), pick a random one!
        if isinstance(val, list):
            val = random.choice(val)
        if PNG:
            return _IMAGES.get(name, val)
        return val

    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")
