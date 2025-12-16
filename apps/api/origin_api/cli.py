"""CLI commands for ORIGIN API."""

import click
from sqlalchemy.orm import Session

from origin_api.db.seed import seed_all
from origin_api.db.session import SessionLocal
from origin_api.settings import get_settings


@click.group()
def cli():
    """ORIGIN API CLI."""
    pass


@cli.command()
def seed():
    """Seed initial data."""
    click.echo("Seeding initial data...")
    db = SessionLocal()
    try:
        seed_all(db)
        click.echo("✓ Seed data created.")
    except Exception as e:
        click.echo(f"✗ Error seeding data: {e}", err=True)
        db.rollback()
    finally:
        db.close()


if __name__ == "__main__":
    cli()

