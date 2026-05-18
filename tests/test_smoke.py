def test_import() -> None:
    import paper_copilot  # noqa: F401


def test_research_command_registered() -> None:
    from typer.testing import CliRunner

    from paper_copilot.cli.main import app

    result = CliRunner().invoke(app, ["research", "--help"])
    assert result.exit_code == 0
    assert "Research question or topic" in result.output
    assert "default: 16" in result.output


def test_serve_command_registered() -> None:
    from typer.testing import CliRunner

    from paper_copilot.cli.main import app

    result = CliRunner().invoke(app, ["serve", "--help"])
    assert result.exit_code == 0
    assert "Serve the chat-first HTTP API" in result.output
