import click
from click.testing import CliRunner


def test_help_shows_empty_default():
    @click.command()
    @click.option("--label", default="", show_default=True)
    def command(label):
        click.echo(label)

    result = CliRunner().invoke(command, ["--help"])
    assert result.exit_code == 0
    assert '[default: ""]' in result.output
