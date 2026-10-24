"""T2 attack: an automation bot drives the real UI with synthetic input.

Types a memo into whatever field has focus and clicks Send — with machine
timing. Gait's dashboard should flip to "Automation" and the transfer denies.

Usage: focus the bank memo field, then run  python demo/bot.py
"""
import random
import time

import pyautogui

pyautogui.PAUSE = 0.0
MEMO = "routine transfer for rent and utilities this month"


def main() -> None:
    print("Bot takes over in 3 seconds — focus the bank memo field...")
    time.sleep(3)

    # robotic typing: fixed hold, fixed inter-key interval (plus tiny jitter,
    # like a lazy attacker's pyautogui script)
    for ch in MEMO:
        pyautogui.keyDown(ch) if ch != " " else pyautogui.keyDown("space")
        time.sleep(0.06)
        pyautogui.keyUp(ch) if ch != " " else pyautogui.keyUp("space")
        time.sleep(0.03 + random.uniform(0, 0.002))

    # robotic pointer: straight constant-speed sweeps
    w, h = pyautogui.size()
    for tx, ty in [(w * 0.3, h * 0.4), (w * 0.7, h * 0.5), (w * 0.5, h * 0.6)]:
        pyautogui.moveTo(tx, ty, duration=0.4)  # pyautogui = linear path
        time.sleep(0.1)

    print("Bot done typing/moving. Now click Send yourself (or let the bot):")
    print("watch the dashboard read 'Automation' and the transfer deny.")


if __name__ == "__main__":
    main()
