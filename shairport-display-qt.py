#!/usr/bin/env /usr/bin/python3

from PyQt5.QtWidgets import (
    QApplication,
    QSlider,
    QPushButton,
    QLabel,
    QWidget,
    QProgressBar,
    QDesktopWidget,
    QGraphicsDropShadowEffect,
)
from PyQt5 import uic

from PyQt5.QtCore import QTimer, Qt, QSize
from PyQt5.QtGui import (
    QPixmap,
    QFont,
    QBrush,
    QColor,
    QIcon,
    QPainter,
)

from PIL import Image

import dbus
import dbus.mainloop.glib
import datetime
import signal
import sys
import os
import logging
import colorsys
import argparse

# Art dominant color gradient -- 90% brightness to 20% brightnessd
GRADIENT_TOP = 0.9
GRADIENT_BOTTOM = 0.2


class ShairportSyncClient(QApplication):
    def __init__(self, argv):

        super().__init__(argv)

        self.log = logging.getLogger("shairport-display")
        self.ArtPath = None
        self.Title = None
        self.Artist = None
        self.Album = None
        self.playing = False

        self.format = logging.Formatter(
            "%(asctime)s - [%(levelname)s] - %(message)s", "%Y-%m-%d %H:%M:%S"
        )

        self.handler = logging.StreamHandler(stream=sys.stdout)
        self.handler.setFormatter(self.format)

        # logging.DEBUG or logging.INFO
        self.handler.setLevel(logging.DEBUG)

        self.log.addHandler(self.handler)
        self.log.setLevel(logging.DEBUG)

        self.log.info("Starting application")

        self.backlight = ""
        self.DisplayCleared = True

        self.properties_changed = None

        self._setup_loop()
        self._setup_bus()
        self._setup_signals()

        self.length = 0
        self.progress = 0
        self.duration = 500  # milliseconds
        self.timer = None
        self.incr = 0
        self.clientname = ""
        self.servicename = ""
        self.volwanted = -10.0
        self.volsent = -10.0

        self.keys = [
            "art mpris:artUrl",
            "title xesam:title",
            "artist xesam:artist",
            "album xesam:album",
            "length mpris:length",
        ]

        try:
            self.window = uic.loadUi(os.path.dirname(argv[0]) + "/shairport-display.ui")
        except self.window.DoesNotExist:
            print("Cannot find shairport-display.ui or syntax error in ui file")
            exit(1)

        # get command line args
        parser = argparse.ArgumentParser(description="Shairport Sync Display")
        parser.add_argument(
            "--config",
            choices=["desktop", "raspberrypiofficial7inchscreen"],
            default="raspberrypiofficial7inchscreen",
        )
        args = parser.parse_args()

        self.desktopmode = False
        if args.config.lower() == "desktop":
            self.desktopmode = True

        if self.desktopmode is False:
            self.window.resize(QDesktopWidget().availableGeometry().size())
            self.window.setWindowFlag(Qt.FramelessWindowHint)
            self.window.setCursor(Qt.BlankCursor)
            for (topdir, backlights, _) in os.walk("/sys/class/backlight/"):
                for backlight in backlights:
                    with open(topdir + backlight + "/max_brightness", "r") as f:
                        self.backlight = topdir + backlight
                        self.max_brightness = f.read()
            if self.backlight:
                self.log.debug("using backlight: '" + self.backlight + "'")
            else:
                self.log.debug("no backlight found, backlight control disabled")

        # self.window.setStyleSheet("background-color : black; color : black;")

        self.window.setAutoFillBackground(True)
        self.window.resizeEvent = self.onResize
        self.window.keyPressEvent = self.keyPressEvent
        self.window.show()

        self.metadata = {}

        self.CW = self.window.findChild(QWidget, "centralwidget")
        self.CW.setStyleSheet("#centralwidget {background: black}")

        self.B1 = self.window.findChild(QPushButton, "b1")
        self.B2 = self.window.findChild(QPushButton, "b2")
        self.B3 = self.window.findChild(QPushButton, "b3")

        self.window.findChild(QPushButton, "v1").setIcon(QIcon("mute.png"))
        self.window.findChild(QPushButton, "v2").setIcon(QIcon("vol.png"))
        self.window.findChild(QPushButton, "v1").setIconSize(QSize(20, 20))
        self.window.findChild(QPushButton, "v2").setIconSize(QSize(20, 20))

        self.B1.setText("")
        self.B1.setIcon(QIcon("fff.png"))
        self.B1.setIconSize(QSize(40, 40))

        self.B3.setText("")
        self.B3.setIcon(QIcon("ff.png"))
        self.B3.setIconSize(QSize(40, 40))

        self.B2.setText("")
        if self.playing:
            self.B2.setIcon(QIcon("pause.png"))
        else:
            self.B2.setIcon(QIcon("play.png"))

        self.B2.setIconSize(QSize(40, 40))

        # self.B4 = self.window.findChild(QPushButton, 'b4')
        self.B1.clicked.connect(self.b1)
        self.B2.clicked.connect(self.b2)
        self.B3.clicked.connect(self.b3)
        # self.B4.clicked.connect(self.b4)

        self.Vol = self.window.findChild(QSlider, "Vol")
        self.Vol.valueChanged.connect(self.vol)

        self.Art = self.window.findChild(QLabel, "CoverArt")

        self.Title = self.window.findChild(QLabel, "Title")
        self.Title.setFont(QFont("Helvetica Neue", 16, QFont.Bold))

        self.Artist = self.window.findChild(QLabel, "Artist")
        self.Artist.setFont(QFont("Helvetica Neue", 14, QFont.Normal))

        self.Album = self.window.findChild(QLabel, "Album")
        self.Album.setFont(QFont("Helvetica Neue", 14, QFont.Normal))

        self.Client = self.window.findChild(QLabel, "Client")
        self.Service = self.window.findChild(QLabel, "Service")

        self.ProgressBar = self.window.findChild(QProgressBar, "ProgressBar")
        self.ProgressBar.setMaximumHeight(7)

        # self.ProgressBar.setStyleSheet(
        #    "QProgressBar {
        #    border: 0px solid gray; height: 2px; max-height:2px;}")
        # self.ProgressBar.setStyleSheet(
        #    "QProgressBar::chunk {background: light blue;}")
        # self.animation = QPropertyAnimation(self.ProgressBar, b"value")
        self.ProgressBar.setRange(0, 100)

        self.Remaining = self.window.findChild(QLabel, "Remaining")
        self.Remaining.setFont(QFont("Montserrat", 10, QFont.Normal))
        self.Elapsed = self.window.findChild(QLabel, "Elapsed")
        self.Elapsed.setFont(QFont("Montserrat", 10, QFont.Normal))

        self._clear_display()
        self._initialize_display()
        self._start_timer()

        self.window.destroyed.connect(self.quit)

    def rotate(self, input, d):
        Lfirst = " .. " + input[0:d]
        Lsecond = input[d:]
        return Lsecond + Lfirst

    def onResize(self, event):

        size = self.window.size()
        self.log.info("resize width: %d", size.width())
        self.log.info("resize height: %d", size.height())

        if self.Title is not None:
            self.Title.setMaximumWidth(int(size.width() / 2))

        if self.Artist is not None:
            self.Artist.setMaximumWidth(int(size.width() / 2))

        if self.Album is not None:
            self.Album.setMaximumWidth(int(size.width() / 2))

        if self.ArtPath is not None:
            pixmap = QPixmap(self.ArtPath)
            if pixmap.width() >= pixmap.height():
                self.Art.setPixmap(
                    pixmap.scaledToWidth(
                        int((size.width() / 2) - 100), Qt.SmoothTransformation
                    )
                )
            else:
                self.Art.setPixmap(
                    pixmap.scaledToHeight(
                        int((size.width() / 2) - 100), Qt.SmoothTransformation
                    )
                )

    def Remote(self):
        the_object = self._bus.get_object(
            "org.gnome.ShairportSync", "/org/gnome/ShairportSync"
        )
        return dbus.Interface(the_object, "org.gnome.ShairportSync.RemoteControl")

    def vol(self):
        self._bus.call_blocking(
            "org.gnome.ShairportSync",
            "/org/gnome/ShairportSync",
            "org.freedesktop.DBus.Properties",
            "Set",
            "ssv",
            ["org.gnome.ShairportSync", "Volume", self.Vol.value() / 10.0],
        )

    def b1(self):
        self.log.debug("previous")
        self.Remote().Previous()

    def b2(self):
        self.log.debug("playpause")
        self.Remote().PlayPause()

    def b3(self):
        self.log.debug("next")
        self.Remote().Next()

    def event(self, e):
        return QApplication.event(self, e)

    def _get_sps_info(self, path, item):
        try:
            result = self._bus.call_blocking(
                "org.gnome.ShairportSync",
                "/org/gnome/ShairportSync",
                "org.freedesktop.DBus.Properties",
                "Get",
                "ss",
                ["org.gnome.ShairportSync" + path, item],
            )
        except dbus.exceptions.DBusException:
            self.log.warning("_get_sps_info failed %s %s", path, item)
            return None
        return result

    def _tickEvent(self):

        if (self.incr % 10) == 0:

            if self._get_sps_info(".RemoteControl", "Available") != 0:
                self.clientname = self._get_sps_info(".RemoteControl", "ClientName")
                self.servicename = self._get_sps_info("", "ServiceName")

                if self.clientname is not None:
                    self.Client.setText(self.clientname)
                else:
                    self.Client.setText("?")

                if self.servicename is not None:
                    self.Service.setText(self.servicename)
                else:
                    self.Service.setText("?")

                s = self._get_sps_info(".RemoteControl", "PlayerState")
                self._fixplaypause(s)
            else:
                self.log.debug("Remote control is not available")
                # self._clear_display()

        if "title" in self.metadata and len(self.metadata["title"]) > 22:
            newtitle = self.rotate(
                self.metadata["title"], self.incr % len(self.metadata["title"])
            )
            self.Title.setText(newtitle)

        if "album" in self.metadata and len(self.metadata["album"]) > 30:
            newtitle = self.rotate(
                self.metadata["album"], self.incr % len(self.metadata["album"])
            )
            self.Album.setText(newtitle)

        if "artist" in self.metadata and len(self.metadata["artist"]) > 30:
            newtitle = self.rotate(
                self.metadata["artist"], self.incr % len(self.metadata["artist"])
            )
            self.Artist.setText(newtitle)

        self.incr = self.incr + 1

        if self.length != 0:
            # self.animation.setStartValue(self.progress / self.length * 100.0)
            self.progress += self.duration / 1000.0
            # self.animation.setEndValue(self.progress / self.length * 100.0)
            # self.log.debug("progress: %f",
            #    self.progress / self.length * 100.0)
            # self.log.debug("elapsed: %s",
            #    str(datetime.timedelta(seconds=self.progress)))
            self.ProgressBar.setValue(int(self.progress / self.length * 100))
            # self.animation.setDuration(self.duration)
            # self.animation.start()
            elapsed = round(self.progress)

            elapsed_time = datetime.timedelta(seconds=elapsed)
            remaining_time = datetime.timedelta(seconds=self.length - elapsed)

            elapsed_formated = ":".join(str(elapsed_time).split(":")[1:])
            remaining_formated = ":".join(str(remaining_time).split(":")[1:])

            self.Elapsed.setText(elapsed_formated)
            self.Remaining.setText("-" + remaining_formated)

        return True

    def quit(self, *args):
        self.log.info("Stopping application")
        self.properties_changed.remove()
        self._set_backlight(False)
        QApplication.quit()

    def _setup_loop(self):
        self._loop = dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)

    def _setup_bus(self):

        dbus.set_default_main_loop(self._loop)

        if dbus.SystemBus().name_has_owner("org.gnome.ShairportSync"):
            self.log.debug("shairport-sync dbus service is running on the system bus")
            self._bus = dbus.SystemBus()
            return

        if dbus.SessionBus().name_has_owner("org.gnome.ShairportSync"):
            self.log.debug("shairport-sync dbus service is running on the session bus")
            self._bus = dbus.SessionBus()
            return

        self.log.error("shairport-sync dbus service is not running")
        exit(1)

    def _fullscreen_mode(self):

        if self.window.windowState() & Qt.WindowState.WindowFullScreen:
            self.log.debug("normal")
            self.window.showNormal()
        else:
            self.log.debug("fullscreen")
            self.window.showFullScreen()

    def keyPressEvent(self, event):

        if event.key() == Qt.Key_Q:
            self.quit()
        if event.key() == Qt.Key_F:
            self._fullscreen_mode()

    def _set_backlight(self, power):

        if self.backlight:
            try:
                with open(self.backlight + "/brightness", "w") as f:
                    if power:
                        f.write(self.max_brightness)
                    else:
                        f.write("0")

            except FileNotFoundError:
                self.log.warning("path: '" + self.backlight + "' does not exist")
            except PermissionError:
                self.log.warning("incorrect permissions for '" + self.backlight + "'")

    def _initialize_display(self):

        self._set_backlight(True)

        self.DisplayCleared = False

        for tl in QApplication.topLevelWidgets():
            tl.setVisible(True)

        self.log.info("Get initial volume from player.")
        initialVolume = self._get_sps_info(".RemoteControl", "AirplayVolume")
        if initialVolume is None:
            self.log.warning("shairport-sync is not running on the bus")
            exit(1)
        else:
            self.handleAirplayVolume(initialVolume)

        self.log.info("Get initial metadata from player.")
        initialMetadata = self._get_sps_info(".RemoteControl", "Metadata")
        if initialMetadata is None:
            self.log.warning("shairport-sync is not running on the bus")
            exit(1)
        else:
            self.handleMetadata(initialMetadata)

    def _setup_signals(self):
        self.properties_changed = self._bus.add_signal_receiver(
            handler_function=self.handlePropertyChanges,
            signal_name="PropertiesChanged",
            dbus_interface="org.freedesktop.DBus.Properties",
            bus_name="org.gnome.ShairportSync",
            member_keyword="signal",
        )

    def average_image_color(self, filename):
        i = Image.open(filename)
        h = i.histogram()

        # split into red, green, blue
        r = h[0:256]
        g = h[256 : 256 * 2]
        b = h[256 * 2 : 256 * 3]

        # perform the weighted average of each channel:
        # the *index* is the channel value, and the *value* is its weight
        return (
            sum(i * w for i, w in enumerate(r)) / sum(r),
            sum(i * w for i, w in enumerate(g)) / sum(g),
            sum(i * w for i, w in enumerate(b)) / sum(b),
        )

    def rgb_to_hex(self, r, g, b):
        return "#%02x%02x%02x" % (r, g, b)

    def color_variant(self, hex_color, brightness_offset=1):
        """takes a color like #87c95f and produces a \
        lighter or darker variant"""
        if len(hex_color) != 7:
            raise Exception(
                "Passed %s into color_variant(), \
                needs to be in #87c95f format."
                % hex_color
            )
        rgb_hex = [hex_color[x : x + 2] for x in [1, 3, 5]]
        new_rgb_int = [int(hex_value, 16) + brightness_offset for hex_value in rgb_hex]
        new_rgb_int = [
            min([255, max([0, i])]) for i in new_rgb_int
        ]  # make sure new values are between 0 and 255
        return self.rgb_to_hex(
            int(new_rgb_int[0]), int(new_rgb_int[1]), int(new_rgb_int[2])
        )

    def _meta_changed(self, metadata):

        for k in self.keys:
            key = k.split(" ")[0]
            if key in metadata:
                if isinstance(metadata[key], str) and len(metadata[key]) == 0:
                    self.log.debug("length is %s %d", metadata[key], len(metadata[key]))
                    pass
                if (key not in self.metadata) or (self.metadata[key] != metadata[key]):
                    if key not in self.metadata:
                        self.log.debug("%s not in self.metadata", key)
                    else:
                        self.log.debug(
                            "%s IS in self.metadata self.metadata[art]=%s",
                            key,
                            self.metadata["art"],
                        )
                    self.log.debug("metadata changed 1 %s", key)
                    return True
            if key not in metadata:
                if key in self.metadata or self.metadata[key] != metadata[key]:
                    self.log.debug("metadata changed 2 %s", key)
                    return True
        self.log.debug("metadata not changed")
        return False

    def _set_metadata(self, metadata):

        if not self._meta_changed(metadata):
            return

        for key in metadata:
            self.log.info("metadata %s: %s", key, metadata[key])

        self.metadata = metadata

        self.Title.setText(metadata["title"])
        self.Artist.setText(metadata["artist"])
        self.Album.setText(metadata["album"])

        self.log.debug(" reset art stuff ")

        size = self.window.size()

        self.Title.setMaximumWidth(int(size.width() / 2))
        self.Artist.setMaximumWidth(int(size.width() / 2))
        self.Album.setMaximumWidth(int(size.width() / 2))

        self.log.info(
            "track length us: %s %d",
            str(datetime.timedelta(microseconds=metadata["length"])),
            metadata["length"],
        )

        if metadata["art"] is None or len(metadata["art"]) == 0:
            self.log.debug(" art path none ")
            return

        self.ArtPath = metadata["art"]

        if len(self.ArtPath):
            dominantcolor = self.average_image_color(self.ArtPath)
            (h, l, s) = colorsys.rgb_to_hls(
                dominantcolor[0], dominantcolor[1], dominantcolor[2]
            )
            l1 = l * GRADIENT_TOP
            l2 = l1 * GRADIENT_BOTTOM
            (r, g, b) = colorsys.hls_to_rgb(h, l, s)
            (r2, g2, b2) = colorsys.hls_to_rgb(h, l2, s)
            col1 = self.rgb_to_hex(int(r), int(g), int(b))
            col2 = self.rgb_to_hex(int(r2), int(g2), int(b2))
            self.CW.setStyleSheet(
                "#centralwidget \
                {background: qlineargradient(x1:0 y1:0, x2:0 y2:1, stop:0 "
                + col1
                + ", stop:1 "
                + col2
                + ");}"
            )

            pixmap = QPixmap(self.ArtPath)
            if pixmap.width() >= pixmap.height():
                pixmap = pixmap.scaledToWidth(
                    int((size.width() / 2) - 100), Qt.SmoothTransformation
                )
            else:
                pixmap = pixmap.scaledToHeight(
                    int((size.width() / 2) - 100), Qt.SmoothTransformation
                )
            radius = 15

            # create empty pixmap of same size as original
            rounded = QPixmap(pixmap.size())
            rounded.fill(QColor("transparent"))

            # draw rounded rect on new pixmap using original pixmap as brush
            painter = QPainter(rounded)
            painter.setRenderHint(QPainter.Antialiasing)
            painter.setBrush(QBrush(pixmap))
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(pixmap.rect(), radius, radius)

            # set pixmap of label
            self.Art.setPixmap(rounded)

            # free stuff up
            del painter
            del rounded

            shadow = QGraphicsDropShadowEffect()
            shadow.setBlurRadius(40)
            shadow.setColor(QColor(0, 0, 0, 180))
            self.Art.setGraphicsEffect(shadow)

    def _stop_timer(self):
        if self.timer is not None:
            self.log.debug("stopping timer")
            self.timer.stop()
            self.timer = None

    def _start_timer(self):
        if self.timer is None:
            self.log.debug("starting new timer")
            self.timer = QTimer()
            self.timer.setTimerType(Qt.PreciseTimer)
            self.timer.timeout.connect(self._tickEvent)
            self.timer.start(self.duration)

    def _clear_display(self):

        # self._set_backlight(False)

        self.ArtPath = None
        for tl in QApplication.topLevelWidgets():
            tl.setVisible(False)
        self.DisplayCleared = True

    def _fixplaypause(self, state):
        if state == "Playing":
            if self.DisplayCleared:
                self.log.debug("wake up display")
                self._initialize_display()
                self._start_timer()
            if self.playing is False:
                self._start_timer()
                self.log.debug("SET PAUSE")
                self.B2.setIcon(QIcon("pause.png"))
                self.playing = True
        elif state == "Paused":
            if self.playing:
                # self._stop_timer()
                self.log.debug("SET PLAY")
                self.B2.setIcon(QIcon("play.png"))
                self.playing = False
        elif state == "Stopped":
            self._clear_display()
            self._stop_timer()
            self.playing = False

    def handleAirplayVolume(self, nv):
        bb = self.Vol.blockSignals(True)
        self.Vol.setValue(int(nv * 10)) # airplay volume is 0 to -30, slider is 0 to -300
        self.Vol.blockSignals(bb)

    def handleProgressString(self, data):
        self.log.debug("progresstring signal")
        start, current, end = [int(x) for x in data.split("/")]
        self.log.debug("start: %d", start)
        self.log.debug("current: %d", current)
        self.log.debug("end: %d", end)

        self.length = round((end - start) / 44100)
        elapsed = round((current - start) / 44100)
        self.log.debug(
            "track length seconds: %s", str(datetime.timedelta(seconds=self.length))
        )
        self.log.debug("elapsed: %s", str(datetime.timedelta(seconds=elapsed)))
        self.progress = elapsed

    def handleMetadata(self, metadata_from_dbus):
        metadata = {}
        # if the metadata contains the songdatakind stuff, use it.
        # It's not always there though.
        try:
            st = metadata_from_dbus["sps:songdatakind"]
            if st == 1:
                self.log.info("stream is untimed")
                self.streamIsTimed = False
                self.ProgressBar.setVisible(False)
                self.Elapsed.setVisible(False)
                self.Remaining.setVisible(False)
                self.B1.setVisible(False)
                self.B2.setVisible(True)
                self.B3.setVisible(False)
            else:
                self.log.info("stream is timed")
                self.streamIsTimed = True
                self.ProgressBar.setVisible(True)
                self.Elapsed.setVisible(True)
                self.Remaining.setVisible(True)
                self.B1.setVisible(True)
                self.B2.setVisible(True)
                self.B3.setVisible(True)
        except KeyError:
            pass
        for k in self.keys:
            f = k.split(" ")[0]
            t = k.split(" ")[1]
            if t in metadata_from_dbus:
                if f == "artist":
                    metadata[f] = ", ".join(metadata_from_dbus[t])
                else:
                    metadata[f] = metadata_from_dbus[t]
                self.log.debug("set %s to %s", f, metadata[f])
            else:
                if f == "length":
                    metadata[f] = 0
                else:
                    metadata[f] = ""
        metadata["art"] = metadata["art"].split("://")[-1]
        self._set_metadata(metadata)

    def handlePropertyChanges(self, *args, **kwargs):
        interface = args[0]
        data = args[1]
        # self.log.debug("Received signal for %s", interface)
        if "AirplayVolume" in data:
            self.log.debug("airplay volume property change")
            self.handleAirplayVolume(data["AirplayVolume"])
        if "ProgressString" in data:
            self.log.debug("progress property change")
            self.handleProgressString(data["ProgressString"])
        if "Metadata" in data:
            self.log.debug("metadata property change")
            self.handleMetadata(data["Metadata"])
        if "PlayerState" in data:
            self.log.debug("playerstate signal")
            state = data["PlayerState"]
            self._fixplaypause(state)

        if "Active" in data:
            if data["Active"]:
                self.log.info("device connected")
                self._initialize_display()
            else:
                self.log.info("device disconnected")
                self._clear_display()


if __name__ == "__main__":

    client = ShairportSyncClient(sys.argv)
    signal.signal(signal.SIGINT, lambda *args: client.quit())

    client.startTimer(500)

    client.exec_()
