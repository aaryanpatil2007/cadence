# GAIT — 3-minute stage script

Screen layout: dashboard (left half), bank (right half), terminal hidden behind.
Second laptop ready with `demo/hijack.sh`, the Mac's Wi-Fi IP, and a copied
`gait_session` cookie + one previously-allowed JWS (grab both from the bank's
"raw JWS" disclosure + browser dev tools during rehearsal).

**0:00 — Baseline.**
Presenter is typing a sentence into the bank memo field. Dashboard shows ~0.9,
status word **You**, both modality bars alive.
> "This daemon has been watching how I type and move for the last minute.
> That number is its confidence that I'm still me. Raw keystrokes never leave
> RAM — everything downstream only ever sees this signed score."

**0:25 — Legit transfer.**
Send $500. Attestation trace lights up: nonce → score 0.9x → signature ✓ →
policy → **allow**. Ledger updates.
> "Fresh nonce from the verifier, the daemon signs the score with a key that
> lives in the Secure Enclave, ten-second expiry. WebAuthn, except the
> authenticator keeps checking it's still you."

**0:45 — T1: Human takeover.**
Teammate slides in mid-sentence and keeps typing the next memo.
Audience watches the number fall — under 0.4 in ~8 seconds, **Someone else**.
They hit Send → **deny**. Step-up challenge appears; teammate types it → deny
again.
> "Same unlocked Mac, same session cookie, same browser. The bank doesn't
> care — the behavior doesn't match."

**1:30 — T2: Automation.**
Presenter returns, score recovers above threshold (show it). Then in terminal:
`python demo/bot.py`, click into the memo field. The bot types with machine
timing. Dashboard flips to **Automation**, score ~0.05. Send → deny.
> "Synthetic input has no micro-variance. Coefficient of variation under 5%
> → hard floor. pyautogui never stood a chance."

**2:10 — T3 + T4: Hijack + replay (second laptop).**
`./hijack.sh <mac-ip> <cookie> <captured-jws>`
- stolen cookie, no attestation → **HTTP 401**
- replay of the earlier allowed JWS → **deny: nonce used**
- (if re-run >10s later) → **deny: attestation expired**
> "Steal the cookie, steal a whole signed attestation — still nothing. One
> nonce, one use, ten seconds."

**2:40 — Close.**
> "A ~55k-parameter model trained on this laptop in under 90 seconds. Raw
> behavior never left RAM. The server only ever saw a signed number. Any API
> can demand one of these before anything irreversible happens."

Slide numbers (fill from `data/models/eval.md` after real enrollment):
takeover latency __s · false-reject __% · bot score __ · params __ · train __s
