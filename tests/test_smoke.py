def test_import() -> None:
    import paper_copilot  # noqa: F401


def test_research_command_registered() -> None:
    from typer.testing import CliRunner

    from paper_copilot.cli.main import app

    result = CliRunner().invoke(app, ["research", "--help"])
    assert result.exit_code == 0
    assert "Research question or topic" in result.output
