"""Train + calibrate + register device with the verifier (post-enrollment hook)."""
import os

from . import train, calibrate


def main() -> None:
    train.main()
    calibrate.main()
    from gait.daemon.enroll import register_device
    url = os.environ.get("GAIT_VERIFIER_URL", "http://127.0.0.1:7800")
    ok = register_device(url)
    print(f"[train_and_register] device registration: {'ok' if ok else 'FAILED (register later)'}")


if __name__ == "__main__":
    main()
