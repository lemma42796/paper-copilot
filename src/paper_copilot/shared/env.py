from dotenv import find_dotenv, load_dotenv

_loaded = False


def load_env() -> None:
    """Load .env from the nearest CWD ancestor directory. Idempotent.

    Real environment variables take precedence over .env values
    (``override=False``), so CI and production deployments that inject
    secrets directly are not clobbered by a stray developer .env.

    ``usecwd=True`` ensures the search starts from the current working
    directory rather than the installed package location.
    """
    global _loaded
    if _loaded:
        return
    load_dotenv(find_dotenv(usecwd=True), override=False)
    _loaded = True
