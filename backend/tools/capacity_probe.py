"""Small authenticated HTTP load probe for establishing deployment baselines."""

import argparse
import asyncio
import statistics
import time
import httpx


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("url")
    parser.add_argument("--token", required=True)
    parser.add_argument("--requests", type=int, default=200)
    parser.add_argument("--concurrency", type=int, default=20)
    args = parser.parse_args()
    semaphore = asyncio.Semaphore(args.concurrency)
    latencies = []
    failures = 0
    async with httpx.AsyncClient(headers={"Authorization": f"Bearer {args.token}"}, timeout=15) as client:
        async def request_once():
            nonlocal failures
            async with semaphore:
                started = time.perf_counter()
                response = await client.get(f"{args.url.rstrip('/')}/panels")
                latencies.append((time.perf_counter() - started) * 1000)
                failures += int(response.status_code >= 400)
        await asyncio.gather(*(request_once() for _ in range(args.requests)))
    ordered = sorted(latencies)
    p95 = ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))]
    print(f"requests={len(latencies)} failures={failures} median_ms={statistics.median(latencies):.1f} p95_ms={p95:.1f}")


if __name__ == "__main__":
    asyncio.run(main())
