import time
import select
from evdev import UInput

from keyboard_manager import KeyboardManager
from mouse_ops import MouseOperations
from event_handler import EventHandler
from indicator import TopBarIndicator


class MouseController:
    def __init__(self):
        self.keyboard_manager = KeyboardManager()
        self.mouse_ops = MouseOperations()
        self.indicator = TopBarIndicator()
        self.event_handler = EventHandler(self.mouse_ops, self.indicator, self.keyboard_manager)

        # Wait briefly for monitor to grab initial keyboards
        time.sleep(0.3)

        # Build UInput from first available keyboard
        keyboards = self.keyboard_manager.find_all_keyboards()
        if keyboards:
            self.keyboard_manager.ui = UInput.from_device(keyboards[0], name='kb-mouse-virtual')
            self.event_handler.ui = self.keyboard_manager.ui
        else:
            print("⚠️  No keyboards found for UInput — re-injection disabled")

    def run(self):
        print("=" * 60)
        print("KEYBOARD MOUSE CONTROL - CLEAN EDITION")
        print("=" * 60)
        print("\n🖱️  MOUSE BUTTONS:")
        print("   Enter = Left button (hold to drag)")
        print("   Backspace = Right button")
        print("   \\ = Middle click")
        print("")
        print("🎮 CONTROLS:")
        print("   CapsLock = Toggle mouse mode")
        print("   Q = Precision mode (speed 2, green bar)")
        print("   TAB = Toggle acceleration")
        print("   WASD = Move cursor")
        print("   PageUp/Down = Scroll (HOLD for continuous)")
        print("   1-9,0 = Speed (2-50)")
        print("")
        print("✨ SMART AUTO-EXIT:")
        print("   Any non-mouse key exits mode")
        print("   ALL combos exit (Ctrl+C, Alt+Tab, etc.)")
        print("   EXCEPT: Ctrl/Shift/Alt + Click/RightClick")
        print(f"\n✅ Monitoring keyboards...")
        print("Press Ctrl+C to exit\n")

        try:
            while self.keyboard_manager.running:
                devices = self.keyboard_manager.get_devices()

                if not devices:
                    time.sleep(0.1)
                    continue

                try:
                    r, _, _ = select.select(devices, [], [], 0.5)
                except (ValueError, OSError):
                    # A device fd became invalid — monitor will handle it
                    time.sleep(0.1)
                    continue

                for device in r:
                    try:
                        for event in device.read():
                            pass_through = self.event_handler.handle_event(event)
                            if pass_through and self.keyboard_manager.ui:
                                try:
                                    self.keyboard_manager.ui.write_event(event)
                                    self.keyboard_manager.ui.syn()
                                except Exception:
                                    pass
                    except OSError:
                        # Device disconnected mid-read — monitor will clean up
                        self.keyboard_manager._release(device.path, reason='read error')

        except KeyboardInterrupt:
            print("\n\nExiting...")
        finally:
            self.indicator.cleanup()
            self.mouse_ops.cleanup()
            self.keyboard_manager.cleanup()