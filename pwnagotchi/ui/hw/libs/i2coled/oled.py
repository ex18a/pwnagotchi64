from . import SSD1306

EPD_WIDTH = 128
EPD_HEIGHT = 64


class OLED(object):

    def __init__(self, address=0x3C, width=EPD_WIDTH, height=EPD_HEIGHT):
        self.width = width
        self.height = height

        if height == 32:
            self.disp = SSD1306.SSD1306_128_32(width, height, address)
        elif height == 16:
            self.disp = SSD1306.SSD1306_96_16(width, height, address)
        else:
            self.disp = SSD1306.SSD1306_128_64(width, height, address)

    def Init(self):
        self.disp.begin()

    def Clear(self):
        self.disp.clear()

    def display(self, image):
        self.disp.getbuffer(image)
        self.disp.ShowImage()
