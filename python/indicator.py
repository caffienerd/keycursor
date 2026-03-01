import threading
import time
import gi

gi.require_version('Gtk', '3.0')
gi.require_version('GtkLayerShell', '0.1')

from gi.repository import Gtk, GLib, GtkLayerShell


class TopBarIndicator:
    """Wayland-native top bar indicator using gtk-layer-shell."""

    def __init__(self):
        self.window = None
        self.visible = False
        self.gtk_ready = False
        self.acceleration_enabled = True
        self.precision_mode = False

        self.gtk_thread = threading.Thread(target=self._run_gtk, daemon=True)
        self.gtk_thread.start()

        timeout = 0
        while not self.gtk_ready and timeout < 50:
            time.sleep(0.05)
            timeout += 1

        if not self.gtk_ready:
            print("[INDICATOR] WARNING: GTK thread timed out")

    def show(self):
        if not self.window or self.visible:
            return
        self.visible = True
        GLib.idle_add(self._do_show)

    def hide(self):
        if not self.window or not self.visible:
            return
        self.visible = False
        GLib.idle_add(self._do_hide)

    def set_acceleration(self, enabled):
        self.acceleration_enabled = enabled
        if self.window and self.visible:
            GLib.idle_add(self.window.queue_draw)

    def set_precision_mode(self, enabled):
        self.precision_mode = enabled
        if self.window and self.visible:
            GLib.idle_add(self.window.queue_draw)

    def _do_show(self):
        if self.window:
            self.window.show_all()
        return False

    def _do_hide(self):
        if self.window:
            self.window.hide()
        return False

    def cleanup(self):
        if self.window:
            GLib.idle_add(Gtk.main_quit)

    def _run_gtk(self):
        indicator = self

        class IndicatorWindow(Gtk.Window):
            def __init__(self):
                super().__init__()

                GtkLayerShell.init_for_window(self)
                GtkLayerShell.set_layer(self, GtkLayerShell.Layer.OVERLAY)
                GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.TOP, True)
                GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.LEFT, True)
                GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.RIGHT, True)
                GtkLayerShell.set_exclusive_zone(self, -1)

                self.set_default_size(-1, 8)
                self.set_decorated(False)
                self.set_accept_focus(False)
                self.set_app_paintable(True)

                screen = self.get_screen()
                visual = screen.get_rgba_visual()
                if visual:
                    self.set_visual(visual)

                drawing_area = Gtk.DrawingArea()
                drawing_area.set_size_request(-1, 8)
                drawing_area.connect('draw', self.on_draw)
                self.add(drawing_area)

                self.show_all()
                self.hide()

            def on_draw(self, widget, cr):
                allocation = widget.get_allocation()

                if indicator.precision_mode:
                    # Green = precision mode
                    cr.set_source_rgba(0.2, 0.85, 0.3, 1.0)
                elif indicator.acceleration_enabled:
                    # White = normal mode with accel ON
                    cr.set_source_rgba(1.0, 1.0, 1.0, 1.0)
                else:
                    # Blue = accel OFF
                    cr.set_source_rgba(0.2, 0.5, 1.0, 1.0)

                cr.rectangle(0, 0, allocation.width, allocation.height)
                cr.fill()
                return False

        try:
            self.window = IndicatorWindow()
            self.gtk_ready = True
            Gtk.main()
        except Exception as e:
            import traceback
            print(f"[INDICATOR] EXCEPTION: {e}")
            print(traceback.format_exc())
            self.gtk_ready = True