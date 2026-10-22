import asyncio

from upstox_service.adapters.repositories.timescale.catalog import DataRepository
from upstox_service.config.settings import Settings


async def run():
    repository = DataRepository(Settings().timescale_dsn)
    try:
        await repository.init_schema()
        count = await repository.bootstrap()
        print(f"Bootstrap registered {count} entities; projection events committed to outbox.")
    finally:
        await repository.close()


def main():
    asyncio.run(run())


if __name__ == "__main__":
    main()
