"""
CLI entry point using click and rich.
"""
import asyncio
import glob
import os
import click
import yaml
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

# Ensure .env is loaded before pipeline starts
load_dotenv()

from scraper.pipeline import ScrapingPipeline
from scraper.core.models import ScrapingRequest
from scraper.circuit_breaker.temporal import TemporalBreaker
from scraper.confidence.quarantine import QuarantineStore
from scraper.telemetry.metrics import MetricsCollector

console = Console()


@click.group()
def main():
    """Self-Healing Web Scraper CLI — 9-layer resilient extraction engine."""
    pass


@main.command()
@click.argument('url')
@click.argument('prompt', required=False, default=None)
@click.option('--config', default='config', help='Path to config directory')
@click.option('--db', default='data/scraper.db', help='Path to SQLite database')
def auto(url: str, prompt: str | None, config: str, db: str):
    """Universal Scraper: Give ANY URL, it auto-generates schemas, runs the 9-layer pipeline, and auto-heals when layout changes."""
    from urllib.parse import urlparse
    from playwright.async_api import async_playwright
    from scraper.healing.schema_generator import AutoSchemaGenerator

    async def _run():
        domain = urlparse(url).netloc.replace("www.", "")
        safe_name = domain.replace(".", "_") + ".yaml"
        config_file = os.path.join(config, "domains", safe_name)

        if not os.path.exists(config_file):
            console.print(Panel(f"[bold cyan]First time scraping {domain}[/bold cyan]\nAuto-analyzing accessibility tree to synthesize resilient schema...", border_style="cyan"))
            
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                page = await browser.new_page()
                await page.goto(url, wait_until="domcontentloaded", timeout=20000)
                ax_tree = await page.aria_snapshot()
                await browser.close()

            generator = AutoSchemaGenerator()
            domain_config = await generator.generate_schema(url, ax_tree, user_prompt=prompt)
            saved_path = generator.save_config(domain_config, config_dir=config)
            console.print(f"[bold green][OK] Synthesized schema with {len(domain_config.fields)} fields saved to [yellow]{saved_path}[/yellow][/bold green]\n")

        # Run the full 9-layer self-healing pipeline
        pipeline = ScrapingPipeline(config_path=config, db_path=db)
        await pipeline.initialize()

        try:
            request = ScrapingRequest(url=url, domain=domain)
            console.print(f"[bold blue]Executing 9-Layer Extraction on[/bold blue] [cyan]{url}[/cyan]...")
            response = await pipeline.scrape(request)

            if response.success:
                table = Table(title=f"Extracted Structured Data: {domain}", header_style="bold green")
                table.add_column("Field", style="cyan", no_wrap=True)
                table.add_column("Value", style="white")
                table.add_column("Status", style="bold")

                for k, v in response.fields.items():
                    if k in response.quarantined_fields or v is None:
                        status = "[red]QUARANTINED[/red]"
                        val_str = "[dim italic]Nulled (Awaiting Review)[/dim italic]"
                    else:
                        status = "[green]SUCCESS[/green]"
                        val_str = str(v)
                    table.add_row(k, val_str, status)

                console.print(table)
                console.print()

                if response.drift_events:
                    drift_table = Table(title="AI Self-Healing Repair Report", header_style="bold magenta")
                    drift_table.add_column("Field", style="cyan")
                    drift_table.add_column("Old Selector", style="red")
                    drift_table.add_column("Repaired Selector (Gemini)", style="green")
                    drift_table.add_column("Confidence", style="magenta")
                    drift_table.add_column("Outcome", style="bold")

                    for event in response.drift_events:
                        conf = f"{event.confidence_score:.1%}" if event.confidence_score is not None else "N/A"
                        drift_table.add_row(
                            event.field_name,
                            event.old_selector,
                            event.new_selector or "None",
                            conf,
                            f"[bold green]{event.outcome.value}[/bold green]" if event.auto_healed else f"[yellow]{event.outcome.value}[/yellow]"
                        )
                    console.print(drift_table)
                    console.print()
                else:
                    console.print("[dim green]All locators matched cleanly. LKG baseline updated.[/dim green]\n")
            else:
                console.print(Panel(f"[bold red]Scrape failed:[/bold red] {response.error}", title="Pipeline Error", border_style="red"))
        finally:
            await pipeline.shutdown()

    asyncio.run(_run())


@main.command()
@click.argument('url')
@click.option('--domain', required=True, help='Target domain identifier (e.g. books.toscrape.com)')
@click.option('--config', default='config', help='Path to config directory')
@click.option('--db', default='data/scraper.db', help='Path to SQLite database')
def scrape(url: str, domain: str, config: str, db: str):
    """Run a single scrape, auto-heal if needed, and print structured results."""
    async def _run():
        pipeline = ScrapingPipeline(config_path=config, db_path=db)
        await pipeline.initialize()
        
        try:
            request = ScrapingRequest(url=url, domain=domain)
            console.print(f"[bold blue]Scraping[/bold blue] [cyan]{url}[/cyan] ([yellow]{domain}[/yellow])...\n")
            
            response = await pipeline.scrape(request)
            
            if response.success:
                # 1. Extracted Fields Table
                table = Table(title=f"Extracted Data: {domain}", header_style="bold green")
                table.add_column("Field Name", style="cyan", no_wrap=True)
                table.add_column("Extracted Value", style="white")
                table.add_column("Status", style="bold")
                
                for k, v in response.fields.items():
                    if k in response.quarantined_fields or v is None:
                        status = "[red]QUARANTINED[/red]"
                        val_str = "[dim italic]Nulled (Awaiting Review)[/dim italic]"
                    else:
                        status = "[green]SUCCESS[/green]"
                        val_str = str(v)
                    table.add_row(k, val_str, status)
                    
                console.print(table)
                console.print()

                # 2. Drift & Healing Events Panel
                if response.drift_events:
                    drift_table = Table(title="Drift & Healing Events", header_style="bold yellow")
                    drift_table.add_column("Field", style="cyan")
                    drift_table.add_column("Old Selector", style="red")
                    drift_table.add_column("New Selector", style="green")
                    drift_table.add_column("Confidence", style="magenta")
                    drift_table.add_column("Outcome", style="bold")

                    for event in response.drift_events:
                        conf_str = f"{event.confidence_score:.2%}" if event.confidence_score is not None else "N/A"
                        drift_table.add_row(
                            event.field_name,
                            event.old_selector,
                            event.new_selector or "None",
                            conf_str,
                            f"[bold green]{event.outcome.value}[/bold green]" if event.auto_healed else f"[yellow]{event.outcome.value}[/yellow]"
                        )
                    console.print(drift_table)
                    console.print()
                else:
                    console.print("[dim green]No drift detected. All cached deterministic locators succeeded.[/dim green]\n")

            else:
                console.print(Panel(f"[bold red]Scrape failed:[/bold red] {response.error}", title="Pipeline Failure", border_style="red"))
        finally:
            await pipeline.shutdown()
            
    asyncio.run(_run())


@main.command()
@click.option('--config', default='config', help='Path to config directory')
def list_domains(config: str):
    """List all configured domain schemas and their field extractors."""
    pattern = os.path.join(config, "domains", "*.yaml")
    files = glob.glob(pattern)
    
    if not files:
        console.print(f"[yellow]No domain configurations found in {pattern}[/yellow]")
        return

    table = Table(title="Configured Scraping Domains", header_style="bold blue")
    table.add_column("Domain", style="cyan", no_wrap=True)
    table.add_column("Rate Limit (RPM)", style="magenta")
    table.add_column("Fields", style="green")
    table.add_column("Holdout URLs", style="yellow")

    for file_path in files:
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
                domain = data.get("domain", "unknown")
                rpm = data.get("rate_limit", {}).get("requests_per_minute", 30) if isinstance(data.get("rate_limit"), dict) else data.get("rate_limit_rpm", 30)
                fields = ", ".join(f["name"] for f in data.get("fields", []))
                holdouts = len(data.get("holdout_urls", []))
                table.add_row(domain, str(rpm), fields, f"{holdouts} URLs")
        except Exception as e:
            table.add_row(os.path.basename(file_path), "ERROR", str(e), "0")

    console.print(table)


@main.command()
@click.argument('domain')
@click.argument('field_name')
@click.option('--reset-by', required=True, help='Name/ID of the human operator resetting the breaker')
@click.option('--db', default='data/scraper.db', help='Path to SQLite database')
def reset_breaker(domain: str, field_name: str, reset_by: str, db: str):
    """Reset a tripped temporal circuit breaker (thrash lock) for a field."""
    async def _run():
        breaker = TemporalBreaker()
        await breaker.initialize(db)
        await breaker.reset(domain, field_name, reset_by)
        console.print(f"[bold green]Reset temporal breaker[/bold green] for [cyan]{domain}.{field_name}[/cyan] by operator [yellow]{reset_by}[/yellow]")

    asyncio.run(_run())


@main.command()
@click.option('--domain', default=None, help='Filter by domain')
@click.option('--db', default='data/scraper.db', help='Path to SQLite database')
@click.option('--cold-storage', default='data/cold_storage', help='Path to cold storage')
def quarantine_list(domain: str | None, db: str, cold_storage: str):
    """List all quarantined extractions pending review."""
    async def _run():
        store = QuarantineStore()
        await store.initialize(db, cold_storage)
        records = await store.get_pending(domain)
        
        if not records:
            console.print(f"[green]Quarantine queue is empty for {domain or 'all domains'}.[/green]")
            return

        table = Table(title=f"Quarantined Records ({len(records)})", header_style="bold red")
        table.add_column("Snapshot ID", style="dim cyan")
        table.add_column("Domain", style="cyan")
        table.add_column("Field", style="yellow")
        table.add_column("Broken Selector", style="red")
        table.add_column("Confidence", style="magenta")
        table.add_column("Quarantined At", style="white")

        for r in records:
            conf = f"{r.confidence_score:.1%}" if r.confidence_score is not None else "N/A"
            table.add_row(
                r.snapshot_id[:8] + "...",
                r.domain,
                r.field_name,
                r.broken_selector or "N/A",
                conf,
                r.quarantined_at.strftime("%Y-%m-%d %H:%M:%S") if r.quarantined_at else "N/A"
            )

        console.print(table)

    asyncio.run(_run())


@main.command()
@click.option('--port', default=9090, help='Port for Prometheus metrics server')
def metrics(port: int):
    """Start Prometheus metrics server."""
    collector = MetricsCollector()
    collector.start_metrics_server(port)
    console.print(f"[bold green]Prometheus metrics exporter running on http://localhost:{port}/metrics[/bold green]")
    console.print("[dim]Press Ctrl+C to stop...[/dim]")
    try:
        while True:
            import time
            time.sleep(1)
    except KeyboardInterrupt:
        console.print("\n[yellow]Metrics server stopped.[/yellow]")


# ──────────────────────────────────────────────
# Bright Data Scraper Studio CLI Commands
# ──────────────────────────────────────────────

@main.command()
@click.argument('url')
@click.argument('prompt')
def bdata_create(url: str, prompt: str):
    """Create a custom scraper in Bright Data Scraper Studio via bdata CLI."""
    from scraper.integrations.bright_data import BrightDataScraperStudioClient
    async def _run():
        client = BrightDataScraperStudioClient()
        console.print(f"[bold blue]Creating Scraper Studio collector for[/bold blue] [cyan]{url}[/cyan]...")
        collector_id = await client.bdata_create_scraper(url, prompt)
        console.print(f"[bold green]Collector Created:[/bold green] [yellow]{collector_id}[/yellow]")
    asyncio.run(_run())


@main.command()
@click.argument('collector_id')
@click.argument('url')
def bdata_run(collector_id: str, url: str):
    """Run a Scraper Studio custom scraper via bdata CLI."""
    from scraper.integrations.bright_data import BrightDataScraperStudioClient
    async def _run():
        client = BrightDataScraperStudioClient()
        console.print(f"[bold blue]Running Scraper Studio collector[/bold blue] [yellow]{collector_id}[/yellow] on [cyan]{url}[/cyan]...")
        output = await client.bdata_run_scraper(collector_id, url)
        console.print(output)
    asyncio.run(_run())


@main.command()
@click.argument('collector_id')
@click.argument('what_broke')
def bdata_heal(collector_id: str, what_broke: str):
    """Propose an AI self-healing fix in Scraper Studio via bdata CLI."""
    from scraper.integrations.bright_data import BrightDataScraperStudioClient
    async def _run():
        client = BrightDataScraperStudioClient()
        console.print(f"[bold yellow]Triggering Scraper Studio heal for[/bold yellow] [yellow]{collector_id}[/yellow]...")
        output = await client.bdata_heal_scraper(collector_id, what_broke)
        console.print(output)
    asyncio.run(_run())


@main.command()
@click.argument('collector_id')
@click.option('--reject', is_flag=True, default=False, help='Reject the proposed fix')
def bdata_approve(collector_id: str, reject: bool):
    """Approve or reject a Scraper Studio self-healing fix via bdata CLI."""
    from scraper.integrations.bright_data import BrightDataScraperStudioClient
    async def _run():
        client = BrightDataScraperStudioClient()
        action = "Rejecting" if reject else "Approving"
        console.print(f"[bold green]{action} fix for Scraper Studio collector[/bold green] [yellow]{collector_id}[/yellow]...")
        output = await client.bdata_approve_heal(collector_id, reject=reject)
        console.print(output)
    asyncio.run(_run())


if __name__ == '__main__':
    main()

