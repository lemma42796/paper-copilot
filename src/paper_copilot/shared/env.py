from dotenv import load_dotenv

_loaded = False


def load_env() -> None:
    """Load .env from the nearest ancestor directory. Idempotent.

    Real environment variables take precedence over .env values
    (``override=False``), so CI and production deployments that inject
    secrets directly are not clobbered by a stray developer .env.
    """
    global _loaded
    if _loaded:
        return
    load_dotenv(override=False)
    _loaded = True
