Scripts for preprocessing [Minors on the Move](https://prinminorsonthemove.wordpress.com) project data.

To get this running you need to install [uv](https://docs.astral.sh/uv/getting-started/installation/).

Then simply run

    uv run jupyter lab

If making changes, before committing, run:

    uv run ruff format
    uv run ruff check --fix
    uv run pytest --doctest-modules
