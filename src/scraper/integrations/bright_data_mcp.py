"""
Bright Data Model Context Protocol (MCP) Client.

Enables calling Bright Data's MCP server over SSE to scrape, search, unblock,
and extract web data from any live target site.
"""

from __future__ import annotations

import os
import json
import asyncio
from typing import Any, Optional, Dict, List
from dotenv import load_dotenv

load_dotenv()

import httpx
import structlog

logger = structlog.get_logger(__name__)


class BrightDataMCPClient:
    """
    Client for Bright Data MCP Server (SSE + JSON-RPC).
    """

    def __init__(self, token: Optional[str] = None) -> None:
        self.token = token or os.environ.get("BRIGHT_DATA_API_KEY")
        if not self.token:
            raise ValueError("BRIGHT_DATA_API_KEY is required for Bright Data MCP.")
            
        self.base_url = "https://mcp.brightdata.com"
        self.sse_url = f"{self.base_url}/sse?token={self.token}"
        self._session_endpoint: Optional[str] = None
        self._responses: Dict[int, asyncio.Future] = {}
        self._request_id = 0
        self._connected = asyncio.Event()
        self._listen_task: Optional[asyncio.Task] = None
        self._client: Optional[httpx.AsyncClient] = None

    async def connect(self, timeout: float = 15.0) -> None:
        """
        Connect to Bright Data MCP SSE stream and initialize protocol.
        """
        if self._connected.is_set() and self._session_endpoint:
            return

        self._client = httpx.AsyncClient(timeout=60.0)
        self._listen_task = asyncio.create_task(self._sse_listener())

        try:
            await asyncio.wait_for(self._connected.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            raise TimeoutError("Timed out waiting for Bright Data MCP SSE handshake.")

        # Send initialize handshake
        await self.send_rpc(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "SelfHealingScraper", "version": "1.0.0"}
            }
        )
        logger.info("bright_data_mcp_initialized", endpoint=self._session_endpoint)

    async def _sse_listener(self) -> None:
        async with httpx.AsyncClient(timeout=None) as sse_client:
            async with sse_client.stream("GET", self.sse_url) as response:
                current_event = "message"
                async for line in response.aiter_lines():
                    if not line:
                        continue
                    if line.startswith("event:"):
                        current_event = line.replace("event:", "").strip()
                    elif line.startswith("data:"):
                        data_str = line.replace("data:", "").strip()
                        if current_event == "endpoint":
                            self._session_endpoint = data_str
                            self._connected.set()
                        elif current_event == "message":
                            try:
                                msg = json.loads(data_str)
                                req_id = msg.get("id")
                                if req_id is not None and req_id in self._responses:
                                    fut = self._responses.pop(req_id)
                                    if not fut.done():
                                        fut.set_result(msg)
                            except Exception:
                                pass

    async def send_rpc(self, method: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Send a JSON-RPC 2.0 call to the active session endpoint and await result.
        """
        if not self._session_endpoint:
            raise RuntimeError("Bright Data MCP is not connected.")

        self._request_id += 1
        req_id = self._request_id
        
        loop = asyncio.get_event_loop()
        fut = loop.create_future()
        self._responses[req_id] = fut

        post_url = f"{self.base_url}{self._session_endpoint}&token={self.token}"
        payload = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": method,
            "params": params or {}
        }

        if not self._client:
            self._client = httpx.AsyncClient(timeout=60.0)

        response = await self._client.post(post_url, json=payload)
        response.raise_for_status()

        try:
            result_msg = await asyncio.wait_for(fut, timeout=60.0)
            if "error" in result_msg:
                raise RuntimeError(f"MCP RPC Error: {result_msg['error']}")
            return result_msg.get("result", {})
        except asyncio.TimeoutError:
            self._responses.pop(req_id, None)
            raise TimeoutError(f"RPC call '{method}' timed out after 60s.")

    async def list_tools(self) -> List[Dict[str, Any]]:
        """
        List all available tools provided by Bright Data MCP.
        """
        await self.connect()
        result = await self.send_rpc("tools/list")
        return result.get("tools", [])

    async def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Any:
        """
        Execute a tool on Bright Data MCP server (e.g. web_unlocker, scrape, search).
        """
        await self.connect()
        result = await self.send_rpc("tools/call", {"name": tool_name, "arguments": arguments})
        return result

    async def scrape(self, url: str) -> str:
        """
        Scrape any live target URL using Bright Data's unblocking engine.
        """
        tools = await self.list_tools()
        tool_names = [t.get("name") for t in tools]
        
        # Pick the most appropriate scraping tool available
        chosen_tool = "scrape_as_html" if "scrape_as_html" in tool_names else ("scrape_as_markdown" if "scrape_as_markdown" in tool_names else (tool_names[0] if tool_names else "scrape"))
        
        logger.info("bright_data_mcp_scraping", url=url, tool=chosen_tool)
        result = await self.call_tool(chosen_tool, {"url": url})
        content_items = result.get("content", [])
        if content_items and isinstance(content_items, list):
            return content_items[0].get("text", "")
        return str(result)

    async def close(self) -> None:
        if self._listen_task:
            self._listen_task.cancel()
        if self._client:
            await self._client.aclose()
