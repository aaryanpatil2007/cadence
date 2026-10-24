# Cadence — pitch content (Best Security Hack)

## One-liner
WebAuthn proves it was you at login. **Cadence proves it's still you — every
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

## Numbers for the slide (real team data, data/models/eval.md)
- Pretraining: 3,000 typists / 79k sequences from the Aalto 136M corpus,
  **5.6% EER on 60 typists the model never saw**, trained on a MacBook GPU
- On-device personalization: 55,360 params, fine-tuned in ~3 s
- Keys AUC on held-out windows: **1.00** (user vs both teammates)
- User false-reject while typing at T_HIGH=0.70: **0%**; mean score 0.96
- Takeover detection: **2.5 s** (dissimilar typist), **5 s** (similar typist)
- Automation: score floors to **0.02 within 5 s**
- Attestation: ES256, 10 s TTL, single-use nonce, **Secure Enclave key**
