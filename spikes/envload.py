from pathlib import Path


def load_env():
    env = {}
    for line in (Path(__file__).parent.parent / "backend" / ".env").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env
