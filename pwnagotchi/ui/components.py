import logging
import os

from PIL import Image, ImageOps
from textwrap import TextWrapper


IMAGE_EXTENSIONS = ('.png', '.bmp', '.jpg', '.jpeg', '.gif')

_IMAGE_CACHE = {}
_IMAGE_FAILURES = set()


def _load_image(path, invert, max_width):
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return None

    key = (path, invert, max_width, mtime)
    if key in _IMAGE_CACHE:
        return _IMAGE_CACHE[key]

    try:
        with Image.open(path) as opened:
            image = opened.convert('RGBA')
    except Exception as e:
        if path not in _IMAGE_FAILURES:
            _IMAGE_FAILURES.add(path)
            logging.warning(f"could not load face image {path}: {e}")
        return None

    flattened = Image.new('RGBA', image.size, (255, 255, 255, 255))
    flattened.alpha_composite(image)
    prepared = flattened.convert('L')

    if max_width and prepared.width > max_width:
        height = max(1, round(prepared.height * max_width / prepared.width))
        prepared = prepared.resize((max_width, height), Image.LANCZOS)

    if invert:
        prepared = ImageOps.invert(prepared)

    prepared = prepared.convert('1')
    _IMAGE_CACHE[key] = prepared
    return prepared


def _fit_to_max_x(value, value_x, max_x, font):
    if max_x is None or font is None:
        return value
    budget = max_x - value_x
    if font.getlength(value) <= budget:
        return value
    ellipsis = '…'
    trimmed = value
    while trimmed and font.getlength(trimmed + ellipsis) > budget:
        trimmed = trimmed[:-1]
    return (trimmed + ellipsis) if trimmed else ellipsis


class Widget(object):
    def __init__(self, xy, color=0):
        self.xy = xy
        self.color = color

    def draw(self, canvas, drawer):
        raise Exception("not implemented")


class Bitmap(Widget):
    def __init__(self, path, xy, color=0):
        super().__init__(xy, color)
        self.image = Image.open(path)

    def draw(self, canvas, drawer):
        canvas.paste(self.image, self.xy)


class Line(Widget):
    def __init__(self, xy, color=0, width=1):
        super().__init__(xy, color)
        self.width = width

    def draw(self, canvas, drawer):
        drawer.line(self.xy, fill=self.color, width=self.width)


class Rect(Widget):
    def draw(self, canvas, drawer):
        drawer.rectangle(self.xy, outline=self.color)


class FilledRect(Widget):
    def draw(self, canvas, drawer):
        drawer.rectangle(self.xy, fill=self.color)


class Text(Widget):
    def __init__(self, value="", position=(0, 0), font=None, color=0, wrap=False, max_length=0, max_lines=0,
                 suffix="", suffix_font=None, center_width=None, right_edge=None, max_x=None, png=False):
        super().__init__(position, color)
        self.png = png
        self.value = value
        self.font = font
        self.wrap = wrap
        self.max_length = max_length
        self.max_lines = max_lines
        self.suffix = suffix
        self.suffix_font = suffix_font
        self.suffix_xy = None
        self.center_width = center_width
        self.right_edge = right_edge
        self.max_x = max_x
        self.wrapper = TextWrapper(width=self.max_length, replace_whitespace=False) if wrap else None

    def _draw_image(self, canvas):
        max_width = self.center_width or canvas.size[0]
        image = _load_image(self.value, self.color == 0xff, max_width)
        if image is None:
            return False
        x, y = self.xy
        if self.center_width:
            x += max(0, (self.center_width - image.width) // 2)
        canvas.paste(image, (int(x), int(y)))
        return True

    def draw(self, canvas, drawer):
        if self.value is not None:
            if self.png and str(self.value).lower().endswith(IMAGE_EXTENSIONS):
                self._draw_image(canvas)
                return
            if self.wrap:
                text = '\n'.join('\n'.join(self.wrapper.wrap(line)) if line else ''
                                  for line in self.value.split('\n'))
            else:
                text = self.value
            if self.max_lines:
                lines = text.split('\n')
                if len(lines) > self.max_lines:
                    text = '\n'.join(lines[:self.max_lines])
            if self.center_width:
                center_x = self.xy[0] + self.center_width / 2
                drawer.text((center_x, self.xy[1]), text, font=self.font, fill=self.color,
                            anchor="ma", align="center")
            elif self.right_edge is not None:
                drawer.text((self.right_edge, self.xy[1]), text, font=self.font, fill=self.color,
                            anchor="ra")
            else:
                text = _fit_to_max_x(text, self.xy[0], self.max_x, self.font)
                drawer.text(self.xy, text, font=self.font, fill=self.color)
            if self.suffix:
                suffix_font = self.suffix_font or self.font
                if self.suffix_xy is not None:
                    suffix_pos = self.suffix_xy
                else:
                    offset_x = self.font.getlength(text)
                    suffix_pos = (self.xy[0] + offset_x, self.xy[1])
                drawer.text(suffix_pos, self.suffix, font=suffix_font, fill=self.color)


class LabeledValue(Widget):
    def __init__(self, label, value="", position=(0, 0), label_font=None, text_font=None, color=0, label_spacing=5):
        super().__init__(position, color)
        self.label = label
        self.value = value
        self.label_font = label_font
        self.text_font = text_font
        self.label_spacing = label_spacing

    def draw(self, canvas, drawer):
        if self.label is None:
            drawer.text(self.xy, self.value, font=self.label_font, fill=self.color)
        else:
            pos = self.xy
            drawer.text(pos, self.label, font=self.label_font, fill=self.color)
            if self.label_font is not None:
                label_width = self.label_font.getlength(self.label)
            else:
                label_width = 5 * len(self.label)
            drawer.text((pos[0] + self.label_spacing + label_width, pos[1]), self.value, font=self.text_font, fill=self.color)
