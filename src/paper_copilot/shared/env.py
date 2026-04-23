from dotenv import find_dotenv, load_dotenv

_loaded = False


def load_env() -> None:
    """Load .env from the nearest CWD ancestor directory. Idempotent.

    Real environment variables take precedence over .env values
    (``override=False``), so CI and production deployments that inject
    secrets directly are not clobbered by a stray developer .env.

    ``usecwd=True`` ensures the search starts from the user's current
    working directory, not from the installed package location — so the
    tool-installed CLI (``uv tool install``) resolves the project's .env
    when invoked from the project tree, not from site-packages.
    """
    global _loaded
    if _loaded:
        return
    load_dotenv(find_dotenv(usecwd=True), override=False)
    _loaded = True
