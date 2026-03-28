"""Diagnostic: check raw Copilot API response for reasoning tokens."""
import asyncio
import httpx
from dotenv import load_dotenv
load_dotenv()

from pana.ai.providers.copilot.auth import COPILOT_HEADERS, get_copilot_base_url
from pana.state import state


async def main():
    access_token = state.get("copilot.access_token")
    if not access_token:
        print("ERROR: Not authenticated.")
        return

    base_url = get_copilot_base_url(access_token)
    headers = {**COPILOT_HEADERS, "Authorization": f"Bearer {access_token}"}

    # --- Raw non-streaming request ---
    print("=== RAW NON-STREAMING RESPONSE ===")
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{base_url}/chat/completions",
            headers=headers,
            json={
                "model": "gpt-5-mini",
                "messages": [{"role": "user", "content": "What is 2+2?"}],
                "reasoning_effort": "high",
            },
            timeout=30,
        )
        data = resp.json()
        # Print full response to see ALL fields
        import json
        print(json.dumps(data, indent=2, default=str)[:3000])

    # --- Raw streaming request ---
    print("\n=== RAW STREAMING CHUNKS (first 10) ===")
    async with httpx.AsyncClient() as client:
        async with client.stream(
            "POST",
            f"{base_url}/chat/completions",
            headers=headers,
            json={
                "model": "gpt-5-mini",
                "messages": [{"role": "user", "content": "What is 2+2?"}],
                "reasoning_effort": "high",
                "stream": True,
            },
            timeout=30,
        ) as resp:
            count = 0
            async for line in resp.aiter_lines():
                if not line.startswith("data: "):
                    continue
                payload = line[6:]
                if payload == "[DONE]":
                    print(f"  [DONE] (after {count} chunks)")
                    break
                count += 1
                if count <= 10:
                    import json
                    chunk = json.loads(payload)
                    # Print full chunk to see all fields
                    print(f"  Chunk {count}: {json.dumps(chunk, default=str)[:500]}")
            print(f"  Total chunks: {count}")

    # --- Also try with reasoning object format (GPT-5 style) ---
    print("\n=== WITH reasoning OBJECT PARAM ===")
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{base_url}/chat/completions",
            headers=headers,
            json={
                "model": "gpt-5-mini",
                "messages": [{"role": "user", "content": "What is 2+2?"}],
                "reasoning": {"effort": "high"},
            },
            timeout=30,
        )
        data = resp.json()
        import json
        print(json.dumps(data, indent=2, default=str)[:3000])


asyncio.run(main())
