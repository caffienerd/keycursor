import time
import glob
import threading
from evdev import InputDevice, UInput, ecodes, list_devices


# Names of virtual devices we create — never grab these
VIRTUAL_DEVICE_NAMES = ['ydotool', 'kb-mouse', 'capslock-fix', 'capslock-fix-virtual']


def is_virtual(name: str) -> bool:
    n = name.lower()
    return any(x in n for x in VIRTUAL_DEVICE_NAMES)


def is_keyboard(device: InputDevice) -> bool:
    """True if the device has a full alpha key set."""
    try:
        caps = device.capabilities()
        if ecodes.EV_KEY in caps:
            keys = caps[ecodes.EV_KEY]
            return ecodes.KEY_A in keys and ecodes.KEY_Z in keys
    except Exception:
        pass
    return False


class KeyboardManager:
    def __init__(self):
        self.keyboards: dict[str, InputDevice] = {}  # path -> device
        self.keyboards_lock = threading.Lock()
        self.ui: UInput | None = None
        self.running = True

        self._initial_capslock_check()

        self.monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self.monitor_thread.start()

    # ------------------------------------------------------------------ #
    #  CapsLock helpers                                                    #
    # ------------------------------------------------------------------ #

    def is_capslock_on(self) -> bool:
        """Read real CapsLock state from sysfs — works on Wayland + X11."""
        for path in glob.glob('/sys/class/leds/*capslock*/brightness'):
            try:
                with open(path) as f:
                    if f.read().strip() == '1':
                        return True
            except Exception:
                pass
        return False

    def _initial_capslock_check(self):
        """At startup keyboards aren't grabbed yet — use minimal UInput."""
        print("🔍 Checking CapsLock state...")
        if not self.is_capslock_on():
            print("✅ CapsLock is already OFF")
            return

        print("🔴 CapsLock is ON — turning it off...")
        try:
            ui = UInput(
                events={ecodes.EV_KEY: [ecodes.KEY_CAPSLOCK]},
                name='capslock-fix-virtual'
            )
            time.sleep(0.1)
            ui.write(ecodes.EV_KEY, ecodes.KEY_CAPSLOCK, 1)
            ui.syn()
            time.sleep(0.05)
            ui.write(ecodes.EV_KEY, ecodes.KEY_CAPSLOCK, 0)
            ui.syn()
            time.sleep(0.1)
            ui.close()
            print("✅ CapsLock OFF" if not self.is_capslock_on() else "⚠️  Could not turn off CapsLock")
        except Exception as e:
            print(f"⚠️  Could not turn off CapsLock: {e}")

    def ensure_capslock_off(self):
        """During session — inject via self.ui virtual device."""
        if not self.is_capslock_on() or not self.ui:
            return
        try:
            self.ui.write(ecodes.EV_KEY, ecodes.KEY_CAPSLOCK, 1)
            self.ui.syn()
            time.sleep(0.05)
            self.ui.write(ecodes.EV_KEY, ecodes.KEY_CAPSLOCK, 0)
            self.ui.syn()
        except Exception as e:
            print(f"⚠️  ensure_capslock_off failed: {e}")

    def _fix_led_on_exit(self):
        """Ungrab causes LED to turn on — fix via sysfs."""
        time.sleep(0.15)
        for path in glob.glob('/sys/class/leds/*capslock*/brightness'):
            try:
                with open(path, 'w') as f:
                    f.write('0')
            except Exception:
                pass

    # ------------------------------------------------------------------ #
    #  Device management                                                   #
    # ------------------------------------------------------------------ #

    def _try_grab(self, path: str) -> bool:
        """
        Try to open and grab a device at path.
        Returns True if successfully added.
        Handles devices that exist in list_devices() but aren't ready yet
        (e.g. just woke from sleep).
        """
        try:
            device = InputDevice(path)

            if is_virtual(device.name):
                return False

            if not is_keyboard(device):
                return False

            # Already tracked — check if the fd is still alive
            with self.keyboards_lock:
                if path in self.keyboards:
                    return True  # Already grabbed, nothing to do

            device.grab()

            with self.keyboards_lock:
                self.keyboards[path] = device

            print(f"+ Grabbed: {device.name} ({path})")
            return True

        except Exception:
            return False

    def _release(self, path: str, reason: str = 'removed'):
        """Ungrab and remove a device."""
        with self.keyboards_lock:
            device = self.keyboards.pop(path, None)

        if device:
            try:
                device.ungrab()
            except Exception:
                pass
            try:
                device.close()
            except Exception:
                pass
            print(f"- Released ({reason}): {device.name} ({path})")

    def _monitor_loop(self):
        """
        Main device monitor. Handles:
        - New devices (plugged in, woke from sleep, reconnected)
        - Removed devices (unplugged, went to sleep)
        - Stale fds (device path reused after sleep/wake)
        Polls every 0.5s for fast response to sleep/wake events.
        """
        known_paths: set[str] = set()

        while self.running:
            try:
                current_paths = set(list_devices())

                # --- New or returned devices ---
                for path in current_paths - known_paths:
                    if self._try_grab(path):
                        known_paths.add(path)
                    else:
                        # Not a keyboard or virtual — still track path so we
                        # don't retry it every loop
                        known_paths.add(path)

                # --- Removed devices ---
                for path in known_paths - current_paths:
                    self._release(path, reason='disconnected')
                    known_paths.discard(path)

                # --- Health check existing grabbed devices ---
                # A device that woke from sleep may reuse the same path but
                # have a dead fd — detect this and re-grab.
                with self.keyboards_lock:
                    grabbed_paths = list(self.keyboards.keys())

                for path in grabbed_paths:
                    with self.keyboards_lock:
                        device = self.keyboards.get(path)
                    if device is None:
                        continue
                    try:
                        # Try reading fd state — raises OSError if dead
                        device.fd
                        _ = device.name
                    except Exception:
                        print(f"↻ Dead fd detected: {path} — re-grabbing...")
                        self._release(path, reason='dead fd')
                        known_paths.discard(path)  # Force rediscovery next loop

            except Exception as e:
                print(f"[monitor] error: {e}")

            time.sleep(0.5)

    def find_all_keyboards(self):
        """Return list of InputDevice for all current keyboards (for UInput init)."""
        result = []
        for path in list_devices():
            try:
                device = InputDevice(path)
                if not is_virtual(device.name) and is_keyboard(device):
                    result.append(device)
            except Exception:
                pass
        return result

    def get_devices(self) -> list[InputDevice]:
        with self.keyboards_lock:
            return list(self.keyboards.values())

    def cleanup(self):
        self.running = False

        with self.keyboards_lock:
            paths = list(self.keyboards.keys())

        for path in paths:
            self._release(path, reason='exit')

        self._fix_led_on_exit()

        if self.ui:
            try:
                self.ui.close()
            except Exception:
                pass