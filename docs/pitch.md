# GAIT — pitch content (Best Security Hack)

## One-liner
WebAuthn proves it was you at login. **Gait proves it's still you — every
second after.**

## The gap
Everything downstream of login trusts a bearer token. Cookies get stolen,
sessions get hijacked, unlocked laptops get borrowed, bots drive real UIs.
MFA happens once; attacks happen later.

## The technical core

The keystroke encoder is **pretrained on the Aalto 136M-keystroke dataset**
(TypeNet-style supervised contrastive learning over thousands of real typists,
on this laptop's GPU) so it learns what distinguishes typists *in general*;
your 5-minute enrollment then just locates you in that space via top-k
similarity to your enrollment embeddings. Validation EER on typists the model
never saw: see `data/models/encoder_pretrained_meta.json`. The pointer model
draws population negatives from the Balabit mouse-dynamics corpus. On-device
training picks the best of {scratch, pretrained-frozen, fine-tuned} by
held-out AUC — honest model selection, no cherry-picking.

## What we built (24 h)
- A macOS daemon that learns one person's typing + pointer dynamics from a
  5-minute enrollment and keeps a rolling confidence score, updated every
  2.5 s, decaying on idle.
- A ~55,000-parameter contrastive keystroke encoder, **trained on the laptop
  in under 90 seconds**, fused with a pointer GMM and a scaled-Manhattan
  baseline; calibrated thresholds from held-out + impostor sessions.
- Short-lived attestations: compact JWS (ES256) over {score, nonce, exp=10 s},
  signed by a **Secure Enclave-resident P-256 key**, verified server-side with
  single-use nonces and a full audit trail.
- A demo bank where a session cookie alone moves exactly $0.

## Live kills (3 minutes)
1. Teammate takes over mid-sentence → score collapses in <10 s → deny, failed step-up
2. pyautogui bot types + clicks → robotic-timing floor → "Automation", deny
3. Stolen cookie from a second laptop → 401
4. Replayed signed attestation → "nonce used"; 10 s later → "expired"

## Privacy by construction
- Raw events: RAM ring buffer, max 12 s, zero file handles in the capture layer
- On disk: timing features + 11 coarse key classes. No keycodes, no text, ever
  (CI test greps for leaks)
- Server sees: one signed float

## Honest limits
Root malware on the host can lie to the verifier — identical trust boundary to
Touch ID on a compromised machine. Trained human mimicry is out of scope.

## Numbers for the slide (from data/models/eval.md after enrollment)
- Takeover detection latency: __ s (target <10)
- User false-reject at T_HIGH: __ % (target ≤5)
- Bot score: 0.02 (hard floor)
- Model: ~55k params · trained in __ s on-device
- Attestation: ES256, 10 s TTL, single-use nonce, Secure Enclave key
