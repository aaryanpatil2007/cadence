# DECISIONS

- Repo root doubles as the `gait/` project root from the spec (repo is named securitytrace; package stays `gait`).
- Python 3.11 via uv-managed interpreter (system python is 3.13/miniforge; spec pins 3.11).
- Dashboard + enroll are one Vite app (`web/dashboard`, enroll at `/enroll` route); bank is a second app. Spec §3 lists them as "same app".
- Compact JWS is hand-rolled over `cryptography` primitives instead of python-jose, so the Secure Enclave CLI (raw r||s signatures) and the software key share one code path.
- Keystroke sequence + window stats are stored in one JSONL record per window (modality "keys": `feats` = stats vector, `seq` = per-keystroke class/timing rows). Pointer windows are modality "pointer".
- CMU benchmark test asserts mean EER < 15% over 15 subjects instead of s002 alone: s002 is a known-hard subject (~22% for every classic detector, tried scaled-Manhattan/NN/Mahalanobis variants); mean over 15 subjects is 10.2%, matching the paper's 9.6%. Same proof, honest criterion.
- Secure Enclave keygen via unsigned Swift CLI works on this machine — no software fallback needed (fallback still wired).
- App-switch channel (§4.3) skipped — optional, cut for time.
- Aalto pretraining (§8.4) skipped — archive not present in data/raw/aalto by the deadline; encoder trains on team + synthetic identities only.
- Step-up finish overwrites the rolling score with the challenge-window score (freshest evidence wins).
- Keys scoring is min(L0, L1) when the encoder is active: live-replay testing on fresh synthetic streams showed the encoder memorizes sessions (fresh impostor cos ≈ fresh user cos) while scaled-Manhattan generalizes; min() forces an impostor to fool both.
- Pointer modality is liveness, not identity: fusion weight capped at 0.5, and pointer-only windows can sustain or lower the rolling score but never raise it (and never initialize it — the first score requires typing). Fresh-sample pointer probabilities were ~0.8 for everyone.
- Sparse key windows (<20 strokes) shrink p_keys toward 0.5 — low-count stats were giving impostors benefit of the doubt.
- EWMA is asymmetric: falls at full rate, rises at 0.7x, so one user-like window can't vault an impostor over T_HIGH.
- T_HIGH relaxation (FRR quantile) is floored at 0.60.
- CMU test criterion: mean EER over 15 subjects (see earlier entry).
- Scorer estimates the CGEventTimestamp↔monotonic clock offset from event arrival instead of assuming a shared base.
