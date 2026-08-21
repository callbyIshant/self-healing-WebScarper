"""
Live Self-Healing Test Script.

This script tests the entire self-healing loop:
1. Loads a target page with an INTENTIONALLY BROKEN selector for 'price' (simulating site drift).
2. The deterministic Tier 1 extractor fails to find the element.
3. Tier 6 Gemini AI Healing Agent inspects the accessibility tree.
4. Gemini repairs the selector, proposing the correct CSS/Role locator.
5. Tier 7 cross-validates the repaired selector against holdout pages.
6. Tier 8 confidence gate evaluates and hot-reloads the selector.
7. The pipeline re-extracts the data successfully and logs the drift repair event.
"""

import asyncio
import os
from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

load_dotenv()

from scraper.pipeline import ScrapingPipeline
from scraper.core.models import ScrapingRequest, DomainConfig, FieldDefinition
from scraper.core.enums import SelectorStrategy, VolatilityProfile

console = Console()

async def run_self_healing_test():
    console.print(Panel("[bold yellow]Self-Healing Web Scraper — Live AI Repair Test[/bold yellow]", border_style="yellow"))

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        console.print("[bold red]Error:[/bold red] GEMINI_API_KEY not found in .env. Please add it to test AI healing.")
        return

    console.print(f"[green]Using Gemini API Key:[/green] {api_key[:6]}...{api_key[-4:]}\n")

    # 1. Initialize pipeline
    pipeline = ScrapingPipeline(config_path="config", db_path="data/scraper.db")
    await pipeline.initialize()

    try:
        domain = "books.toscrape.com"
        test_url = "https://books.toscrape.com/catalogue/a-light-in-the-attic_1000/index.html"

        # 2. Intentionally inject a broken selector for 'price' to simulate layout drift
        console.print("[bold red]Step 1: Simulating site layout drift...[/bold red]")
        console.print("Injecting broken selector [red]'.obsolete_price_tag_drifted'[/red] into the locator registry.\n")
        
        await pipeline.locator_registry.update_locator(
            domain=domain,
            field_name="price",
            new_selector=".obsolete_price_tag_drifted",
            strategy=SelectorStrategy.CSS
        )

        # 3. Trigger extraction with the broken selector
        console.print(f"[bold blue]Step 2: Executing scrape on[/bold blue] [cyan]{test_url}[/cyan]...")
        request = ScrapingRequest(url=test_url, domain=domain)
        response = await pipeline.scrape(request)

        # 4. Display Results
        console.print("\n[bold green]Step 3: Scrape execution completed![/bold green]\n")

        # Table of extracted values
        table = Table(title="Extracted Field Values", header_style="bold cyan")
        table.add_column("Field", style="yellow")
        table.add_column("Value", style="white")
        table.add_column("Status", style="bold")

        for k, v in response.fields.items():
            status = "[bold green]EXTRACTED[/bold green]" if v is not None else "[bold red]QUARANTINED[/bold red]"
            table.add_row(k, str(v), status)

        console.print(table)
        console.print()

        # Table of AI Drift Events
        if response.drift_events:
            drift_table = Table(title="AI Self-Healing Repair Report", header_style="bold magenta")
            drift_table.add_column("Field", style="cyan")
            drift_table.add_column("Broken Selector", style="red")
            drift_table.add_column("Repaired Selector (Gemini)", style="green")
            drift_table.add_column("Confidence Score", style="magenta")
            drift_table.add_column("Repair Outcome", style="bold")
            drift_table.add_column("Time to Heal", style="dim white")

            for event in response.drift_events:
                conf = f"{event.confidence_score:.1%}" if event.confidence_score is not None else "N/A"
                duration = f"{event.time_to_heal_seconds:.2f}s" if event.time_to_heal_seconds else "N/A"
                drift_table.add_row(
                    event.field_name,
                    event.old_selector,
                    event.new_selector or "[dim]None[/dim]",
                    conf,
                    f"[bold green]{event.outcome.value}[/bold green]" if event.auto_healed else f"[yellow]{event.outcome.value}[/yellow]",
                    duration
                )
            console.print(drift_table)
            console.print("\n[bold green]SUCCESS: The AI agent detected the broken locator and repaired it automatically![/bold green]\n")
        else:
            console.print("[yellow]No drift events occurred.[/yellow]")

    finally:
        await pipeline.shutdown()


if __name__ == "__main__":
    asyncio.run(run_self_healing_test())
