"""
CLI entry point using click and rich.
"""
import asyncio
import click
from rich.console import Console
from rich.table import Table

from scraper.pipeline import ScrapingPipeline
from scraper.core.models import ScrapingRequest

console = Console()

@click.group()
def main():
    """Self-Healing Web Scraper CLI"""
    pass

@main.command()
@click.argument('url')
@click.option('--domain', required=True, help='Target domain identifier')
@click.option('--config', default='config', help='Path to config directory')
@click.option('--db', default='data/scraper.db', help='Path to SQLite database')
def scrape(url: str, domain: str, config: str, db: str):
    """Run a single scrape and print results as a rich table."""
    async def _run():
        pipeline = ScrapingPipeline(config_path=config, db_path=db)
        await pipeline.initialize()
        
        try:
            request = ScrapingRequest(url=url, domain=domain)
            console.print(f"[bold blue]Scraping {url}...[/bold blue]")
            
            response = await pipeline.scrape(request)
            
            if response.success:
                table = Table(title=f"Results for {domain}")
                table.add_column("Field", style="cyan")
                table.add_column("Value", style="magenta")
                
                for k, v in response.results.items():
                    table.add_row(k, str(v))
                    
                console.print(table)
            else:
                console.print(f"[bold red]Scrape failed:[/bold red] {response.error}")
        finally:
            await pipeline.shutdown()
            
    asyncio.run(_run())

@main.command()
@click.option('--config', default='config', help='Path to config directory')
def list_domains(config: str):
    """Lists configured domains."""
    console.print(f"Listing domains from {config} (Not implemented)")

@main.command()
@click.argument('domain')
@click.argument('field_name')
@click.option('--reset-by', required=True, help='User resetting the breaker')
@click.option('--db', default='data/scraper.db', help='Path to SQLite database')
def reset_breaker(domain: str, field_name: str, reset_by: str, db: str):
    """Resets temporal breaker for a field."""
    console.print(f"Resetting breaker for {domain}.{field_name} by {reset_by} (Not implemented)")

@main.command()
@click.option('--domain', default=None, help='Filter by domain')
@click.option('--db', default='data/scraper.db', help='Path to SQLite database')
def quarantine_list(domain: str, db: str):
    """Lists quarantined records."""
    console.print(f"Listing quarantine records for {domain or 'all domains'} (Not implemented)")

@main.command()
@click.option('--port', default=9090, help='Port for Prometheus metrics server')
def metrics(port: int):
    """Starts Prometheus metrics server."""
    console.print(f"Starting metrics server on port {port} (Not implemented)")

if __name__ == '__main__':
    main()
