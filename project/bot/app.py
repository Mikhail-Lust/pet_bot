import asyncio
from parser import run_scheduler  # функция, запускающая планировщик парсера
from main import start_bot        # оборачиваем бота в отдельную функцию

async def main():
    # Запуск задач параллельно
    await asyncio.gather(
        run_scheduler(),
        start_bot()
    )

if __name__ == "__main__":
    asyncio.run(main())
