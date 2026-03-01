import time
import glob
import threading
import subprocess
from evdev import InputDevice, UInput, ecodes, list_devices


class KeyboardManager:
    def __init__(self):
        self.keyboards = {}
        self.keyboards_lock = threading.Lock()
        self.ui = None
        self.running = True

        self.monitor_thread = threading.Thread(target=self.monitor_new_devices, daemon=True)
        self.monitor_thread.start()

        self._initial_capslock_check()

    # ------------------------------------------------------------------ #
    #  CapsLock helpers                                                    #
    # ------------------------------------------------------------------ #

    def is_capslock_on(self):
        """Read real CapsLock state. Uses sysfs (works on Wayland + X11)."""
        for path in glob.glob('/sys/class/leds/*capslock*/brightness'):
            try:
                with open(path) as f:
                    if f.read().strip() == '1':
                        return True
            except Exception:
                pass
        return False

    def _initial_capslock_check(self):
        """On startup, keyboards aren't grabbed yet — use a minimal UInput to fix."""
        print("🔍 Checking CapsLock state...")
        if not self.is_capslock_on():
            print("✅ CapsLock is already OFF")
            return

        print("🔴 CapsLock is ON — turning it off...")
        try:
            # Create minimal UInput with just KEY_CAPSLOCK — no need to
            # clone a real keyboard, avoids any filtering/loop issues
            ui = UInput(
                events={ecodes.EV_KEY: [ecodes.KEY_CAPSLOCK]},
                name='capslock-fix-virtual'
            )
            time.sleep(0.1)  # Let udev register the device
            ui.write(ecodes.EV_KEY, ecodes.KEY_CAPSLOCK, 1)
            ui.syn()
            time.sleep(0.05)
            ui.write(ecodes.EV_KEY, ecodes.KEY_CAPSLOCK, 0)
            ui.syn()
            time.sleep(0.1)
            ui.close()
            if not self.is_capslock_on():
                print("✅ CapsLock OFF")
            else:
                print("⚠️  Could not turn off CapsLock")
        except Exception as e:
            print(f"⚠️  Could not turn off CapsLock: {e}")

    def ensure_capslock_off(self):
        """
        Called during session (keyboards already grabbed).
        Uses self.ui virtual device to inject the keypress.
        Only acts if CapsLock is actually on.
        """
        if not self.is_capslock_on():
            return
        if not self.ui:
            return
        try:
            self.ui.write(ecodes.EV_KEY, ecodes.KEY_CAPSLOCK, 1)
            self.ui.syn()
            time.sleep(0.05)
            self.ui.write(ecodes.EV_KEY, ecodes.KEY_CAPSLOCK, 0)
            self.ui.syn()
            time.sleep(0.05)
        except Exception as e:
            print(f"⚠️  ensure_capslock_off failed: {e}")

    def fix_led_on_exit(self):
        """Fix LED turning on after ungrab via sysfs."""
        time.sleep(0.15)
        for path in glob.glob('/sys/class/leds/*capslock*/brightness'):
            try:
                with open(path, 'w') as f:
                    f.write('0')
            except Exception:
                pass

    # ------------------------------------------------------------------ #
    #  Keyboard management                                                 #
    # ------------------------------------------------------------------ #

    def find_all_keyboards(self):
        keyboards = []
        devices = [InputDevice(path) for path in list_devices()]

        for device in devices:
            if 'ydotool' in device.name.lower() or 'kb-mouse' in device.name.lower():
                continue

            caps = device.capabilities()
            if ecodes.EV_KEY in caps:
                keys = caps[ecodes.EV_KEY]
                if ecodes.KEY_A in keys and ecodes.KEY_Z in keys:
                    keyboards.append(device)
                    print(f"Found keyboard: {device.name} ({device.path})")

        return keyboards

    def add_keyboard(self, device):
        with self.keyboards_lock:
            if device.path not in self.keyboards:
                try:
                    device.grab()
                    self.keyboards[device.path] = device
                    print(f"+ Added: {device.name}")
                except Exception as e:
                    print(f"Failed to add {device.name}: {e}")

    def remove_keyboard(self, path):
        with self.keyboards_lock:
            if path in self.keyboards:
                device = self.keyboards[path]
                try:
                    device.ungrab()
                except:
                    pass
                print(f"- Removed: {device.name}")
                del self.keyboards[path]

    def monitor_new_devices(self):
        known_paths = set()

        while self.running:
            try:
                current_devices = list_devices()
                current_paths = set(current_devices)

                new_paths = current_paths - known_paths
                for path in new_paths:
                    try:
                        device = InputDevice(path)
                        if 'ydotool' in device.name.lower() or 'kb-mouse' in device.name.lower():
                            known_paths.add(path)
                            continue
                        caps = device.capabilities()
                        if ecodes.EV_KEY in caps:
                            keys = caps[ecodes.EV_KEY]
                            if ecodes.KEY_A in keys and ecodes.KEY_Z in keys:
                                self.add_keyboard(device)
                                known_paths.add(path)
                    except:
                        pass

                removed_paths = known_paths - current_paths
                for path in removed_paths:
                    self.remove_keyboard(path)
                    known_paths.discard(path)

                time.sleep(2)
            except:
                time.sleep(2)

    def get_devices(self):
        with self.keyboards_lock:
            return list(self.keyboards.values())

    def cleanup(self):
        self.running = False
        with self.keyboards_lock:
            for device in self.keyboards.values():
                try:
                    device.ungrab()
                except:
                    pass

        self.fix_led_on_exit()

        if self.ui:
            self.ui.close()