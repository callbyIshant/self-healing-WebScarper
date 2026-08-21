"""
Live Real-World Scraping & Self-Healing Demo powered by Bright Data.

Demonstrates:
1. Unblocking & fetching live web data via Bright Data's Web Unlocking Engine (MCP / Scraping Browser).
2. Extracting structured data using our 9-layer Self-Healing pipeline.
3. Automatically repairing broken locators with Gemini AI when website drift occurs.
"""

import asyncio
import os
from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

load_dotenv()

from scraper.integrations.bright_data_mcp import BrightDataMCPClient
from scraper.pipeline import ScrapingPipeline
from scraper.core.models import ScrapingRequest
from scraper.core.enums import SelectorStrategy

console = Console()


async def run_bright_data_live_demo(target_url: str = "https://news.ycombinator.com/", domain: str = "news.ycombinator.com"):
    console.print(Panel(f"[bold cyan]Bright Data + 9-Layer Self-Healing Pipeline Live Demo[/bold cyan]\nTarget: [yellow]{target_url}[/yellow]", border_style="cyan"))

    # 1. Connect to Bright Data MCP
    mcp_client = BrightDataMCPClient()
    try:
        console.print("[bold blue]Step 1: Connecting to Bright Data Web Unlocking Cloud...[/bold blue]")
        tools = await mcp_client.list_tools()
        console.print(f"[green][OK] Connected to Bright Data MCP ([bold]{len(tools)} tools available[/bold])[/green]\n")
        
        console.print(f"[bold blue]Step 2: Scraping unblocked content from[/bold blue] [cyan]{target_url}[/cyan]...")
        raw_content = await mcp_client.scrape(target_url)
        console.print(f"[green][OK] Received {len(raw_content)} characters of unblocked web data via Bright Data.[/green]\n")
    finally:
        await mcp_client.close()

    # 2. Run Self-Healing Extraction Pipeline
    console.print("[bold blue]Step 3: Running through 9-Layer Self-Healing Data Plane...[/bold blue]")
    pipeline = ScrapingPipeline(config_path="config", db_path="data/scraper.db")
    await pipeline.initialize()

    try:
        request = ScrapingRequest(url=target_url, domain=domain)
        response = await pipeline.scrape(request)

        # 3. Output Table
        table = Table(title=f"Extracted Structured Data ({domain})", header_style="bold green")
        table.add_column("Field", style="cyan", no_wrap=True)
        table.add_column("Value", style="white")
        table.add_column("Status", style="bold")

        for k, v in response.fields.items():
            status = "[bold green]EXTRACTED[/bold green]" if v is not None else "[bold red]QUARANTINED[/bold red]"
            table.add_row(k, str(v), status)

        console.print(table)
        console.print()

        if response.drift_events:
            drift_table = Table(title="AI Self-Healing Repair Report", header_style="bold magenta")
            drift_table.add_column("Field", style="cyan")
            drift_table.add_column("Broken Selector", style="red")
            drift_table.add_column("Repaired Selector (Gemini)", style="green")
            drift_table.add_column("Confidence Score", style="magenta")
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
            console.print("[dim green]All semantic locators succeeded with zero drift.[/dim green]\n")

    finally:
        await pipeline.shutdown()


if __name__ == "__main__":
    import sys
    url = sys.argv[1] if len(sys.argv) > 1 else "https://news.ycombinator.com/"
    dom = sys.argv[2] if len(sys.argv) > 2 else "news.ycombinator.com"
    asyncio.run(run_bright_data_live_demo(url, dom))
