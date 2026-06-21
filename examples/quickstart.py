"""Minimal end-to-end example.

Run:  python examples/quickstart.py
"""
import asyncio

from veil import Engine, FetchRequest, Politeness


async def main() -> None:
    engine = Engine(
        # Be a good citizen: respect robots.txt, 1s between hits to a host.
        politeness=Politeness(respect_robots=True, delay=1.0),
    )
    try:
        resp = await engine.fetch(
            FetchRequest(
                url="https://example.com",
                # Only accept the response if this text is present; otherwise
                # the engine escalates to a heavier strategy.
                success_marker="Example Domain",
            )
        )
        print(f"Fetched via '{resp.strategy}' in {resp.attempts} attempt(s)")
        print(f"Status: {resp.status}, {len(resp.text)} bytes")
    finally:
        await engine.aclose()


if __name__ == "__main__":
    asyncio.run(main())
