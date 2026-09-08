import click
from click.testing import CliRunner


def test_help_uses_default_map():
    @click.command()
    @click.option("--long/--short", show_default=True)
    def command(long):
        click.echo(long)

    result = CliRunner().invoke(command, ["--help"], default_map={"long": True})
    assert result.exit_code == 0
    assert "[default: long]" in result.output
