"""CGEventTap capture (listen-only). Pushes raw events into a RingBuffer.

Requires Input Monitoring + Accessibility permission for the running binary.
On tap-creation failure, prints the exact binary to grant and exits 2.
"""
from __future__ import annotations

import sys
import threading

from .buffer import RingBuffer

# Mach-time based monotonic seconds
_NS = 1e-9


def _flags_to_sides(flags: int, keycode: int, state: dict) -> tuple[str | None, str | None]:
    """Track left/right modifier identity from flagsChanged keycodes (state dict)."""
    return state.get("shift_side"), state.get("cmd_side")


def run_tap(buffer: RingBuffer, stop_event: threading.Event | None = None) -> None:
    import Quartz

    mask = (
        Quartz.CGEventMaskBit(Quartz.kCGEventKeyDown)
        | Quartz.CGEventMaskBit(Quartz.kCGEventKeyUp)
        | Quartz.CGEventMaskBit(Quartz.kCGEventFlagsChanged)
        | Quartz.CGEventMaskBit(Quartz.kCGEventMouseMoved)
        | Quartz.CGEventMaskBit(Quartz.kCGEventLeftMouseDown)
        | Quartz.CGEventMaskBit(Quartz.kCGEventLeftMouseUp)
        | Quartz.CGEventMaskBit(Quartz.kCGEventRightMouseDown)
        | Quartz.CGEventMaskBit(Quartz.kCGEventRightMouseUp)
        | Quartz.CGEventMaskBit(Quartz.kCGEventLeftMouseDragged)
        | Quartz.CGEventMaskBit(Quartz.kCGEventScrollWheel)
        | Quartz.CGEventMaskBit(Quartz.kCGEventOtherMouseDown)
        | Quartz.CGEventMaskBit(Quartz.kCGEventOtherMouseUp)
    )

    # live modifier side state, updated from flagsChanged
    mod_state: dict = {"shift_side": None, "cmd_side": None}
    _SHIFT = {56: "L", 60: "R"}
    _CMD = {55: "L", 54: "R"}

    def callback(proxy, etype, event, refcon):
        t = Quartz.CGEventGetTimestamp(event) * _NS  # mach ns -> monotonic s
        if etype in (Quartz.kCGEventKeyDown, Quartz.kCGEventKeyUp):
            code = Quartz.CGEventGetIntegerValueField(
                event, Quartz.kCGKeyboardEventKeycode)
            autorep = Quartz.CGEventGetIntegerValueField(
                event, Quartz.kCGKeyboardEventAutorepeat)
            buffer.push_key({
                "t": t,
                "type": "down" if etype == Quartz.kCGEventKeyDown else "up",
                "keycode": int(code),
                "autorepeat": int(autorep),
                "shift_side": mod_state["shift_side"],
                "cmd_side": mod_state["cmd_side"],
            })
        elif etype == Quartz.kCGEventFlagsChanged:
            code = int(Quartz.CGEventGetIntegerValueField(
                event, Quartz.kCGKeyboardEventKeycode))
            flags = Quartz.CGEventGetFlags(event)
            if code in _SHIFT:
                mod_state["shift_side"] = _SHIFT[code] if (
                    flags & Quartz.kCGEventFlagMaskShift) else None
            elif code in _CMD:
                mod_state["cmd_side"] = _CMD[code] if (
                    flags & Quartz.kCGEventFlagMaskCommand) else None
            # modifiers also count as keystroke-ish input for idle tracking
            buffer.push_key({
                "t": t, "type": "down", "keycode": code, "autorepeat": 0,
                "shift_side": mod_state["shift_side"],
                "cmd_side": mod_state["cmd_side"],
            })
        elif etype in (Quartz.kCGEventMouseMoved, Quartz.kCGEventLeftMouseDragged):
            loc = Quartz.CGEventGetLocation(event)
            buffer.push_pointer({
                "t": t, "type": "move" if etype == Quartz.kCGEventMouseMoved else "drag",
                "x": float(loc.x), "y": float(loc.y),
            })
        elif etype in (Quartz.kCGEventLeftMouseDown, Quartz.kCGEventRightMouseDown,
                       Quartz.kCGEventOtherMouseDown):
            loc = Quartz.CGEventGetLocation(event)
            buffer.push_pointer({
                "t": t, "type": "down", "x": float(loc.x), "y": float(loc.y),
                "click_state": int(Quartz.CGEventGetIntegerValueField(
                    event, Quartz.kCGMouseEventClickState)),
                "pressure": float(Quartz.CGEventGetDoubleValueField(
                    event, Quartz.kCGMouseEventPressure)),
            })
        elif etype in (Quartz.kCGEventLeftMouseUp, Quartz.kCGEventRightMouseUp,
                       Quartz.kCGEventOtherMouseUp):
            loc = Quartz.CGEventGetLocation(event)
            buffer.push_pointer({
                "t": t, "type": "up", "x": float(loc.x), "y": float(loc.y),
            })
        elif etype == Quartz.kCGEventScrollWheel:
            buffer.push_pointer({
                "t": t, "type": "scroll",
                "delta_y": int(Quartz.CGEventGetIntegerValueField(
                    event, Quartz.kCGScrollWheelEventPointDeltaAxis1)),
                "delta_x": int(Quartz.CGEventGetIntegerValueField(
                    event, Quartz.kCGScrollWheelEventPointDeltaAxis2)),
                "momentum": int(Quartz.CGEventGetIntegerValueField(
                    event, Quartz.kCGScrollWheelEventMomentumPhase)) != 0,
                "continuous": int(Quartz.CGEventGetIntegerValueField(
                    event, Quartz.kCGScrollWheelEventIsContinuous)) == 1,
            })
        return event

    tap = Quartz.CGEventTapCreate(
        Quartz.kCGSessionEventTap,
        Quartz.kCGHeadInsertEventTap,
        Quartz.kCGEventTapOptionListenOnly,
        mask,
        callback,
        None,
    )
    if tap is None:
        print(
            "\n*** GAIT needs Input Monitoring + Accessibility permission. ***\n"
            f"Grant it to this binary in System Settings > Privacy & Security:\n"
            f"    {sys.executable}\n"
            "(Input Monitoring AND Accessibility, then restart the daemon.)\n",
            file=sys.stderr,
        )
        sys.exit(2)

    source = Quartz.CFMachPortCreateRunLoopSource(None, tap, 0)
    loop = Quartz.CFRunLoopGetCurrent()
    Quartz.CFRunLoopAddSource(loop, source, Quartz.kCFRunLoopCommonModes)
    Quartz.CGEventTapEnable(tap, True)
    print("[capture] event tap running (listen-only)")
    while stop_event is None or not stop_event.is_set():
        Quartz.CFRunLoopRunInMode(Quartz.kCFRunLoopDefaultMode, 0.25, False)


def start_capture_thread(buffer: RingBuffer) -> threading.Thread:
    th = threading.Thread(target=run_tap, args=(buffer,), daemon=True, name="gait-capture")
    th.start()
    return th
