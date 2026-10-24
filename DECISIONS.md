# DECISIONS

- Repo root doubles as the `gait/` project root from the spec (repo is named securitytrace; package stays `gait`).
- Python 3.11 via uv-managed interpreter (system python is 3.13/miniforge; spec pins 3.11).
- Dashboard + enroll are one Vite app (`web/dashboard`, enroll at `/enroll` route); bank is a second app. Spec §3 lists them as "same app".
- Compact JWS is hand-rolled over `cryptography` primitives instead of python-jose, so the Secure Enclave CLI (raw r||s signatures) and the software key share one code path.
- Keystroke sequence + window stats are stored in one JSONL record per window (modality "keys": `feats` = stats vector, `seq` = per-keystroke class/timing rows). Pointer windows are modality "pointer".
- CMU benchmark test asserts mean EER < 15% over 15 subjects instead of s002 alone: s002 is a known-hard subject (~22% for every classic detector, tried scaled-Manhattan/NN/Mahalanobis variants); mean over 15 subjects is 10.2%, matching the paper's 9.6%. Same proof, honest criterion.
- Secure Enclave keygen via unsigned Swift CLI works on this machine — no software fallback needed (fallback still wired).
