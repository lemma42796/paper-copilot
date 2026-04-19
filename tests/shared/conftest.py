from collections.abc import Iterator

import pytest

from paper_copilot.shared import logging as pc_logging


@pytest.fixture(autouse=True)
def _reset_logging_config() -> Iterator[None]:
    yield
    pc_logging._reset_for_tests()
