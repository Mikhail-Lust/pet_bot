import sqlite3
import aiohttp
import asyncio
from bs4 import BeautifulSoup
from fake_headers import Headers
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from datetime import datetime
import logging
import os

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),  # Вывод в консоль
        logging.FileHandler('parser.log')  # Сохранение в файл
    ]
)

# Путь к базе данных
DB_PATH = os.path.join(os.path.dirname(__file__), 'pets.db')  # pets.db в директории скрипта




# Инициализация базы данных
def init_db():
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS animals
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                      name TEXT UNIQUE,
                      age TEXT,
                      sex TEXT,
                      description TEXT,
                      photo_url TEXT)''')
        conn.commit()
        c.execute("SELECT COUNT(*) FROM animals")
        count = c.fetchone()[0]
        logging.info(f"База данных инициализирована по пути: {DB_PATH}")
        logging.info(f"Текущее количество записей в таблице animals: {count}")
        return conn
    except sqlite3.Error as e:
        logging.error(f"Ошибка при инициализации базы данных: {e}")
        raise


# Асинхронный запрос страницы
async def fetch_page(session, url):
    headers = Headers(browser='chrome', os='win').generate()
    logging.info(f"Отправка запроса на страницу: {url}")
    try:
        async with session.get(url, headers=headers) as response:
            if response.status == 200:
                logging.info(f"Страница успешно получена: {url}")
                return await response.text()
            else:
                logging.error(f"Ошибка HTTP {response.status} при запросе {url}")
                return None
    except Exception as e:
        logging.error(f"Ошибка при запросе {url}: {e}")
        return None


# Парсинг страницы
async def parse_page(html, page_num):
    if not html:
        logging.warning(f"Нет данных для парсинга на странице {page_num}")
        return []

    logging.info(f"Начало парсинга страницы {page_num}")
    soup = BeautifulSoup(html, 'html.parser')
    cards = soup.find_all('div', class_='card zs_card')
    animals = []

    logging.info(f"Найдено {len(cards)} карточек на странице {page_num}")
    for idx, card in enumerate(cards, 1):
        try:
            # Извлечение данных
            pet_link = card.find('a', class_='card__title w-inline-block')
            pet_link = pet_link.get('href') if pet_link else ''
            logging.debug(f"Карточка {idx}: Ссылка = {pet_link}")

            pet_img = card.find('div', class_='lazyload card__image')
            pet_img = pet_img.get('data-bg') if pet_img else ''
            logging.debug(f"Карточка {idx}: Фото = {pet_img}")

            pet_name = card.find('h2')
            pet_name = pet_name.text.strip() if pet_name else 'Без имени'
            logging.debug(f"Карточка {idx}: Имя = {pet_name}")

            # Извлечение возраста с проверкой
            pet_age = card.find('div', class_='card__value')
            pet_age = pet_age.text.strip() if pet_age and pet_age.text.strip() else 'Не указан'
            if pet_age == 'Не указан':
                logging.info(f"Карточка {idx}: Возраст не указан для {pet_name}")
            else:
                logging.debug(f"Карточка {idx}: Возраст = {pet_age}")

            # Попытка извлечь пол
            sex_elements = card.find_all('div', class_='card__value')
            pet_sex = sex_elements[1].text.strip() if len(sex_elements) > 1 else 'Не указан'
            logging.debug(f"Карточка {idx}: Пол = {pet_sex}")

            animals.append({
                'name': pet_name,
                'age': pet_age,
                'sex': pet_sex,
                'photo_url': pet_img,
                'description': pet_link
            })
            logging.info(f"Карточка {idx} успешно спарсена: {pet_name}")
        except (AttributeError, IndexError) as e:
            logging.warning(f"Ошибка при парсинге карточки {idx} на странице {page_num}: {e}")
            continue

    logging.info(f"Парсинг страницы {page_num} завершён, найдено {len(animals)} животных")
    return animals


# Сохранение в базу данных
async def save_to_db(animals, conn):
    try:
        c = conn.cursor()
        added = 0
        updated = 0
        skipped = 0
        logging.info(f"Сохранение {len(animals)} животных в базу данных")

        for animal in animals:
            try:
                c.execute('''INSERT OR REPLACE INTO animals 
                            (name, age, sex, description, photo_url)
                            VALUES (?, ?, ?, ?, ?)''',
                          (animal['name'], animal['age'], animal['sex'],
                           animal['description'], animal['photo_url']))
                c.execute('SELECT COUNT(*) FROM animals WHERE name = ?', (animal['name'],))
                exists = c.fetchone()[0]
                if exists > 1:
                    updated += 1
                else:
                    added += 1
                logging.debug(f"Обработано животное: {animal['name']}")
            except sqlite3.IntegrityError as e:
                logging.warning(f"Пропущено животное {animal['name']} из-за ошибки: {e}")
                skipped += 1
                continue

        conn.commit()
        logging.info(f"Результат сохранения: {added} добавлено, {updated} обновлено, {skipped} пропущено")
        c.execute("SELECT COUNT(*) FROM animals")
        total = c.fetchone()[0]
        logging.info(f"Общее количество записей в таблице animals: {total}")
    except sqlite3.Error as e:
        logging.error(f"Ошибка при сохранении в базу данных: {e}")


# Основная функция парсинга
async def main():
    logging.info("Запуск парсинга")
    conn = init_db()
    all_animals = []
    base_url = 'https://less-homeless.com/find-your-best-friend-today/page/{}/'
    max_pages = 15

    logging.info(f"Парсинг начат, максимум страниц: {max_pages}")
    async with aiohttp.ClientSession() as session:
        for page in range(1, max_pages + 1):
            url = base_url.format(page)
            html = await fetch_page(session, url)
            animals = await parse_page(html, page)
            if not animals:
                logging.info(f"Нет данных на странице {page}, завершаем парсинг")
                break
            all_animals.extend(animals)
            logging.info(f"Страница {page} обработана, найдено {len(animals)} животных, всего: {len(all_animals)}")
            await asyncio.sleep(1)  # Задержка для избежания блокировки

    await save_to_db(all_animals, conn)
    conn.close()
    logging.info(f"Парсинг завершён: {datetime.now()}, всего обработано {len(all_animals)} животных")


# Настройка планировщика
async def run_scheduler():
    logging.info("Настройка планировщика")
    scheduler = AsyncIOScheduler()
    scheduler.add_job(main, 'cron', hour=13, minute=00)  # Запуск каждый день в 13:16
    scheduler.start()
    logging.info("Планировщик запущен, следующее обновление в 13:00")

    # Немедленный запуск парсинга для теста
    logging.info("Выполняем немедленный запуск парсинга")
    await main()

    try:
        while True:
            await asyncio.sleep(3600)  # Проверяем каждые 60 минут
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()
        logging.info("Планировщик остановлен")

#
# if __name__ == "__main__":
#     asyncio.run(run_scheduler())