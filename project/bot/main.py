import sqlite3
import asyncio
import logging
import re
import json
import random
from aiogram import Bot, Dispatcher, Router
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from datetime import datetime
from dotenv import load_dotenv
import os

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('bot.log', encoding='utf-8')
    ]
)

# Загрузка токена из .env
load_dotenv()
TOKEN = os.getenv("TOKEN")
if TOKEN is None:
    raise ValueError("Переменная окружения TOKEN не найдена! Проверьте файл .env.")

# Инициализация бота и диспетчера
bot = Bot(token=TOKEN)
dp = Dispatcher(storage=MemoryStorage())
router = Router()

# Путь к базе данных
DB_PATH = os.path.join(os.path.dirname(__file__), 'pets.db')

# Глобальный планировщик
scheduler = AsyncIOScheduler()


# Подключение к базе данных
def get_db_connection():
    return sqlite3.connect(DB_PATH)


# Инициализация базы данных
def init_db():
    try:
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='channels'")
        if not c.fetchone():
            c.execute("""
                CREATE TABLE channels (
                    chat_id INTEGER PRIMARY KEY,
                    filters TEXT,
                    schedule TEXT,
                    is_active INTEGER DEFAULT 1
                )
            """)
            logging.info("Таблица channels создана")
        conn.commit()
        conn.close()
    except sqlite3.Error as e:
        logging.error(f"Ошибка при инициализации базы данных: {e}")


# Классы для FSM
class FilterStates(StatesGroup):
    waiting_min_age = State()
    waiting_max_age = State()
    waiting_sex = State()
    waiting_name = State()
    waiting_channel_id = State()
    waiting_schedule = State()
    waiting_channel_filters = State()


# Нормализация возраста
def normalize_age(age_str):
    """Извлечь числовое значение возраста из строки"""
    if not age_str or age_str.lower() in ["не указан", "", "unknown"]:
        logging.debug(f"Возраст не указан: {age_str}")
        return None
    match = re.search(r'\d+', age_str)
    if match:
        age = int(match.group())
        logging.debug(f"Нормализованный возраст: {age_str} → {age}")
        return age
    logging.debug(f"Не удалось нормализовать возраст: {age_str}")
    return None


# Нормализация пола
def normalize_sex(sex_str):
    """Привести значение пола к 'Мужской' или 'Женский'"""
    if not sex_str or sex_str.lower() in ["не указан", "", "unknown"]:
        logging.debug(f"Пол не указан: {sex_str}")
        return None
    sex_str = sex_str.lower()
    male_keywords = ["мужской", "самец", "male", "boy", "м", "♂"]
    female_keywords = ["женский", "самка", "female", "girl", "ж", "♀"]
    if any(keyword in sex_str for keyword in male_keywords):
        logging.debug(f"Нормализованный пол: {sex_str} → Мужской")
        return "Мужской"
    if any(keyword in sex_str for keyword in female_keywords):
        logging.debug(f"Нормализованный пол: {sex_str} → Женский")
        return "Женский"
    logging.debug(f"Не удалось нормализовать пол: {sex_str}")
    return None


# Парсинг человеко-читаемого времени в cron
def parse_schedule(schedule_str: str) -> str:
    """Конвертировать строку вроде 'ежедневно в 10:00' в cron"""
    schedule_str = schedule_str.lower().strip()
    try:
        if "ежедневно в" in schedule_str:
            time_str = schedule_str.replace("ежедневно в", "").strip()
            dt = datetime.strptime(time_str, "%H:%M")
            return f"{dt.minute} {dt.hour} * * *"
        elif "каждый" in schedule_str and "в" in schedule_str:
            day_str = schedule_str.split("каждый")[1].split("в")[0].strip()
            time_str = schedule_str.split("в")[1].strip()
            dt = datetime.strptime(time_str, "%H:%M")
            days = {
                "понедельник": "mon",
                "вторник": "tue",
                "среда": "wed",
                "четверг": "thu",
                "пятница": "fri",
                "суббота": "sat",
                "воскресенье": "sun"
            }
            day = next((v for k, v in days.items() if k in day_str), None)
            if not day:
                raise ValueError("Неверный день недели")
            return f"{dt.minute} {dt.hour} * * {day}"
        else:
            raise ValueError("Неверный формат")
    except ValueError as e:
        logging.error(f"Ошибка парсинга расписания: {schedule_str}, {e}")
        raise ValueError("Формат должен быть: 'ежедневно в HH:MM' или 'каждый <день> в HH:MM'")


# ======================== Клавиатуры ========================

def main_keyboard():
    """Главное меню"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 Все животные", callback_data="view_all")],
        [InlineKeyboardButton(text="🔍 Фильтры", callback_data="view_filtered")],
        [InlineKeyboardButton(text="📬 Управление рассылкой", callback_data="manage_broadcast")]
    ])


def filters_keyboard(selected_filters: dict) -> InlineKeyboardMarkup:
    """Клавиатура выбора фильтров для интерактивного режима"""

    def mark_selected(text, key):
        if key == "age":
            age_selected = "age_min" in selected_filters and "age_max" in selected_filters
            return f"✔ {text}" if age_selected else text
        return f"✔ {text}" if key in selected_filters else text

    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=mark_selected("📅 Возраст", "age"), callback_data="filter_age")],
        [InlineKeyboardButton(text=mark_selected("⚤ Пол", "sex"), callback_data="filter_sex")],
        [InlineKeyboardButton(text=mark_selected("🔎 Имя", "name"), callback_data="filter_name")],
        [InlineKeyboardButton(text="✅ Показать", callback_data="show_filtered")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_main")]
    ])


def broadcast_filters_keyboard(selected_filters: dict) -> InlineKeyboardMarkup:
    """Клавиатура выбора фильтров для рассылки"""

    def mark_selected(text, key):
        if key == "age":
            age_selected = "age_min" in selected_filters and "age_max" in selected_filters
            return f"✔ {text}" if age_selected else text
        return f"✔ {text}" if key in selected_filters else text

    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=mark_selected("📅 Возраст", "age"), callback_data="broadcast_filter_age")],
        [InlineKeyboardButton(text=mark_selected("⚤ Пол", "sex"), callback_data="broadcast_filter_sex")],
        [InlineKeyboardButton(text=mark_selected("🔎 Имя", "name"), callback_data="broadcast_filter_name")],
        [InlineKeyboardButton(text="✅ Сохранить", callback_data="save_broadcast_filters")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_broadcast_filters")]
    ])


def sex_keyboard(prefix: str = "") -> InlineKeyboardMarkup:
    """Клавиатура выбора пола с поддержкой префикса"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Мужской", callback_data=f"{prefix}sex_Мужской")],
        [InlineKeyboardButton(text="Женский", callback_data=f"{prefix}sex_Женский")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data=f"back_to_{prefix}filters")]
    ])


def age_keyboard(start_age: int, end_age: int, mode: str, prefix: str = "") -> InlineKeyboardMarkup:
    """Клавиатура для выбора возраста с поддержкой префикса"""
    buttons = [[]]
    if end_age < start_age:
        logging.warning(f"Некорректный диапазон возраста: start={start_age}, end={end_age}")
        end_age = start_age
    for age in range(start_age, end_age + 1):
        if len(buttons[-1]) >= 3:
            buttons.append([])
        callback_data = f"{prefix}age_{mode}_{age}"
        buttons[-1].append(InlineKeyboardButton(text=str(age), callback_data=callback_data))
    buttons.append([InlineKeyboardButton(text="🔙 Назад", callback_data=f"back_to_{prefix}filters")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def broadcast_management_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура управления рассылкой"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить канал", callback_data="add_channel")],
        [InlineKeyboardButton(text="📋 Список каналов", callback_data="list_channels")],
        [InlineKeyboardButton(text="🗑 Удалить канал", callback_data="remove_channel")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_main")]
    ])


# ======================== Функции работы с базой данных ========================

def get_all_animals():
    """Получить всех животных из базы"""
    try:
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("SELECT id, name, age, sex, photo_url, description FROM animals")
        animals = [{"id": row[0], "name": row[1], "age": row[2], "sex": row[3],
                    "photo_url": row[4], "description": row[5]} for row in c.fetchall()]
        conn.close()
        logging.info(f"Получено {len(animals)} животных из базы")
        return animals
    except sqlite3.Error as e:
        logging.error(f"Ошибка при получении всех животных: {e}")
        return []


def get_animals_by_filters(filters: dict):
    """Получить животных по фильтрам"""
    try:
        conn = get_db_connection()
        c = conn.cursor()
        query = "SELECT id, name, age, sex, photo_url, description FROM animals WHERE 1=1"
        params = []

        if "name" in filters:
            query += " AND name LIKE ?"
            params.append(f"%{filters['name']}%")
            logging.info(f"Применён фильтр по имени: {filters['name']}")

        if "sex" in filters:
            query += " AND sex = ?"
            params.append(filters["sex"])
            logging.info(f"Применён фильтр по полу: {filters['sex']}")

        c.execute(query, params)
        animals = [{"id": row[0], "name": row[1], "age": row[2], "sex": row[3],
                    "photo_url": row[4], "description": row[5]} for row in c.fetchall()]
        logging.info(f"Найдено {len(animals)} животных после SQL-фильтров")

        if "age_min" in filters and "age_max" in filters:
            age_min = filters["age_min"]
            age_max = filters["age_max"]
            filtered_animals = []
            for animal in animals:
                age = normalize_age(animal["age"])
                if age is not None and age_min <= age <= age_max:
                    filtered_animals.append(animal)
            animals = filtered_animals
            logging.info(f"После фильтра по возрасту ({age_min}-{age_max}): {len(animals)} животных")

        for animal in animals:
            animal["sex"] = normalize_sex(animal["sex"]) or "Не указан"

        conn.close()
        return animals
    except sqlite3.Error as e:
        logging.error(f"Ошибка при фильтрации животных: {e}")
        return []


def get_max_age():
    """Получить максимальный возраст из базы"""
    try:
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("SELECT age FROM animals")
        ages = [normalize_age(row[0]) for row in c.fetchall() if normalize_age(row[0]) is not None]
        conn.close()
        max_age = max(ages) if ages else 10
        logging.info(f"Максимальный возраст: {max_age}")
        return max_age
    except sqlite3.Error as e:
        logging.error(f"Ошибка при получении максимального возраста: {e}")
        return 10


def add_channel(chat_id: int, filters: dict = None, schedule: str = "0 10 * * *"):
    """Добавить канал в базу для рассылки"""
    try:
        conn = get_db_connection()
        c = conn.cursor()
        filters_json = json.dumps(filters) if filters else "{}"
        logging.info(f"Сохранение канала {chat_id} с фильтрами {filters_json} и расписанием {schedule}")
        c.execute("INSERT OR REPLACE INTO channels (chat_id, filters, schedule, is_active) VALUES (?, ?, ?, 1)",
                  (chat_id, filters_json, schedule))
        conn.commit()
        conn.close()
        logging.info(f"Канал {chat_id} успешно добавлен в базу")

        # Динамически добавляем задачу в планировщик
        schedule_broadcast(chat_id, schedule)
    except sqlite3.Error as e:
        logging.error(f"Ошибка при добавлении канала: {e}")


def get_channels():
    """Получить все каналы из базы"""
    try:
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("SELECT chat_id, filters, schedule, is_active FROM channels")
        channels = [{"chat_id": row[0], "filters": json.loads(row[1]) if row[1] else {},
                     "schedule": row[2], "is_active": row[3]} for row in c.fetchall()]
        conn.close()
        logging.info(f"Получено {len(channels)} каналов: {channels}")
        return channels
    except sqlite3.Error as e:
        logging.error(f"Ошибка при получении каналов: {e}")
        return []


def remove_channel(chat_id: int):
    """Удалить канал из базы и задачу из планировщика"""
    try:
        # Удаление канала из базы данных
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("DELETE FROM channels WHERE chat_id = ?", (chat_id,))
        affected_rows = c.rowcount
        conn.commit()
        conn.close()
        logging.info(f"Канал {chat_id} удалён из базы, затронуто строк: {affected_rows}")

        # Удаление задачи из планировщика
        job_id = str(chat_id)  # Приводим chat_id к строке, так как apscheduler использует строковые идентификаторы
        if scheduler.get_job(job_id):
            scheduler.remove_job(job_id)
            logging.info(f"Задача рассылки для канала {chat_id} удалена из планировщика")
        else:
            logging.info(f"Задача для канала {chat_id} не найдена в планировщике")

        return affected_rows > 0  # Возвращаем True, если канал был удалён

    except sqlite3.Error as e:
        logging.error(f"Ошибка при удалении канала из базы: {e}")
        return False
    except Exception as e:
        logging.error(f"Ошибка при удалении задачи из планировщика: {e}")
        return False


def schedule_broadcast(chat_id: int, schedule: str):
    """Добавить или обновить задачу рассылки для конкретного канала"""
    try:
        if not schedule.strip():
            logging.error(f"Пустое расписание для канала {chat_id}")
            return
        # Удаляем старую задачу, если она существует
        if scheduler.get_job(str(chat_id)):
            scheduler.remove_job(str(chat_id))
            logging.info(f"Старая задача для канала {chat_id} удалена")

        # Добавляем новую задачу, передавая chat_id
        scheduler.add_job(
            broadcast_animal_for_channel,
            trigger=CronTrigger.from_crontab(schedule),
            args=[chat_id],
            id=str(chat_id)
        )
        logging.info(f"Задача рассылки добавлена для канала {chat_id} с расписанием {schedule}")
    except ValueError as e:
        logging.error(f"Ошибка при добавлении задачи для канала {chat_id}: {e}")


async def broadcast_animal_for_channel(chat_id: int):
    """Отправить случайного питомца в указанный канал"""
    channels = get_channels()
    channel = next((c for c in channels if c["chat_id"] == chat_id), None)

    if not channel:
        logging.error(f"Канал {chat_id} не найден в базе")
        return

    if not channel["is_active"]:
        logging.info(f"Канал {chat_id} неактивен, пропуск")
        return

    filters = channel["filters"]
    logging.info(f"Применение фильтров для канала {chat_id}: {filters}")
    animals = get_animals_by_filters(filters)

    if not animals:
        logging.info(f"Для канала {chat_id} не найдено животных по фильтрам {filters}")
        return

    animal = random.choice(animals)
    text = (
        f"🐾 <b>{animal['name']}</b>\n\n"
        f"📅 <b>Возраст:</b> {animal['age']}\n"
        f"⚤ <b>Пол:</b> {animal['sex']}"
    )
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🌐 Перейти на сайт", url=animal['description'] if animal['description'].startswith(
            'http') else 'https://less-homeless.com')]
    ])

    try:
        await bot.send_photo(
            chat_id=chat_id,
            photo=animal['photo_url'],
            caption=text,
            parse_mode="HTML",
            reply_markup=keyboard
        )
        logging.info(f"Отправлен питомец {animal['name']} в канал {chat_id}")
    except Exception as e:
        logging.error(f"Ошибка при отправке фото в канал {chat_id}: {e}")
        try:
            await bot.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode="HTML",
                reply_markup=keyboard
            )
            logging.info(f"Отправлен текстовый питомец {animal['name']} в канал {chat_id}")
        except Exception as e:
            logging.error(f"Ошибка при отправке текста в канал {chat_id}: {e}")


async def broadcast_animal():
    """Ручной запуск рассылки во все активные каналы (для отладки)"""
    channels = get_channels()
    logging.info(f"Ручной запуск рассылки для {len(channels)} каналов")

    for channel in channels:
        if not channel["is_active"]:
            logging.info(f"Канал {channel['chat_id']} неактивен, пропуск")
            continue
        await broadcast_animal_for_channel(channel["chat_id"])


# ======================== Обработчики ========================

@router.message(CommandStart())
async def start(message: Message):
    """Стартовое сообщение"""
    await message.answer("Добро пожаловать! Этот бот помогает найти питомцев из приюта.",
                         reply_markup=main_keyboard())


@router.message(FilterStates.waiting_channel_id)
async def process_channel_id(message: Message, state: FSMContext):
    """Обработать ID канала"""
    try:
        chat_id = int(message.text.strip())
        await state.update_data(channel_id=chat_id, state="channel_filters")
        await message.answer(
            "Введите расписание (например, 'ежедневно в 10:00' или 'каждый понедельник в 15:00'):"
        )
        await state.set_state(FilterStates.waiting_schedule)
    except ValueError:
        await message.answer("Некорректный ID канала. Введите число, например, -100123456789.")
        return


@router.message(FilterStates.waiting_schedule)
async def process_schedule(message: Message, state: FSMContext):
    """Обработать расписание"""
    schedule_str = message.text.strip()
    try:
        cron_schedule = parse_schedule(schedule_str)
        await state.update_data(schedule=cron_schedule)
        await message.answer(
            "Расписание установлено. Теперь выберите фильтры для рассылки:",
            reply_markup=broadcast_filters_keyboard({})
        )
        await state.set_state(FilterStates.waiting_channel_filters)
    except ValueError as e:
        await message.answer(
            f"Ошибка: {e}. Примеры: 'ежедневно в 10:00', 'каждый понедельник в 15:00'."
        )
        return


@router.message(Command("list_channels"))
async def cmd_list_channels(message: Message):
    """Показать список каналов"""
    channels = get_channels()
    logging.info(f"Запрос списка каналов, получено: {channels}")
    if not channels:
        await message.answer("Нет привязанных каналов.")
        return
    text = "Привязанные каналы:\n"
    for channel in channels:
        status = "активен" if channel["is_active"] else "отключён"
        filters = channel["filters"] or "без фильтров"
        text += f"ID: {channel['chat_id']}, Фильтры: {filters}, Расписание: {channel['schedule']}, Статус: {status}\n"
    await message.answer(text)


@router.callback_query(lambda c: c.data == "manage_broadcast")
async def manage_broadcast(callback: CallbackQuery):
    """Открыть меню управления рассылкой"""
    await callback.message.edit_text("Управление рассылкой:", reply_markup=broadcast_management_keyboard())


@router.callback_query(lambda c: c.data == "add_channel")
async def start_add_channel(callback: CallbackQuery, state: FSMContext):
    """Начать добавление канала через callback"""
    await callback.message.edit_text(
        "Введите ID канала или группы (например, -100123456789). Убедитесь, что бот добавлен как администратор."
    )
    await state.set_state(FilterStates.waiting_channel_id)


@router.callback_query(lambda c: c.data.startswith("remove_channel"))
async def process_remove_channel(callback: CallbackQuery):
    """Удалить выбранный канал"""
    try:
        chat_id = int(callback.data.split("_")[2])
        logging.info(f"Попытка удаления канала {chat_id}")

        if remove_channel(chat_id):
            await callback.message.answer(f"Канал {chat_id} успешно удалён.")
        else:
            await callback.message.answer(f"Канал {chat_id} не найден или не удалён.")

    except Exception as e:
        logging.error(f"Ошибка при обработке удаления канала: {e}")
        await callback.message.answer("Ошибка при удалении канала.")


@router.callback_query(lambda c: c.data == "list_channels")
async def callback_list_channels(callback: CallbackQuery):
    """Показать список каналов через callback"""
    channels = get_channels()
    logging.info(f"Callback запрос списка каналов, получено: {channels}")
    if not channels:
        await callback.message.edit_text(
            "Нет привязанных каналов.", reply_markup=broadcast_management_keyboard()
        )
        return
    text = "Привязанные каналы:\n"
    for channel in channels:
        status = "активен" if channel["is_active"] else "отключён"
        filters = channel["filters"] or "без фильтров"
        text += f"ID: {channel['chat_id']}, Фильтры: {filters}, Расписание: {channel['schedule']}, Статус: {status}\n"
    await callback.message.edit_text(text, reply_markup=broadcast_management_keyboard())


@router.callback_query(lambda c: c.data == "view_all")
async def show_all_animals(callback: CallbackQuery, state: FSMContext):
    """Показать всех животных"""
    animals = get_all_animals()
    if not animals:
        await callback.answer("Животных пока нет в базе.", show_alert=True)
        return

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"🐾 {animal['name']}", callback_data=f"animal_{animal['id']}")]
        for animal in animals
    ])
    await state.update_data(list_type="view_all")
    logging.info("Показан полный список животных")
    await callback.message.answer("Все доступные животные:", reply_markup=keyboard)


@router.callback_query(lambda c: c.data == "view_filtered")
async def choose_filters(callback: CallbackQuery, state: FSMContext):
    """Открыть меню выбора фильтров"""
    data = await state.get_data()
    selected_filters = data.get("filters", {})
    logging.info(f"Текущие фильтры: {selected_filters}")
    await callback.message.edit_text("Выберите фильтр:", reply_markup=filters_keyboard(selected_filters))


@router.callback_query(lambda c: c.data == "back_to_main")
async def back_to_main(callback: CallbackQuery, state: FSMContext):
    """Вернуться в главное меню"""
    await state.clear()
    await callback.message.edit_text("Главное меню:", reply_markup=main_keyboard())


@router.callback_query(lambda c: c.data == "filter_sex")
async def start_sex_filter(callback: CallbackQuery, state: FSMContext):
    """Начать выбор пола для интерактивных фильтров"""
    await callback.message.edit_text("Выберите пол:", reply_markup=sex_keyboard())
    await state.set_state(FilterStates.waiting_sex)


@router.callback_query(lambda c: c.data == "broadcast_filter_sex")
async def start_broadcast_sex_filter(callback: CallbackQuery, state: FSMContext):
    """Начать выбор пола для фильтров рассылки"""
    await callback.message.edit_text("Выберите пол:", reply_markup=sex_keyboard("broadcast_"))
    await state.set_state(FilterStates.waiting_sex)


@router.callback_query(lambda c: c.data.startswith("sex_") or c.data.startswith("broadcast_sex_"))
async def set_sex(callback: CallbackQuery, state: FSMContext):
    """Установить пол в фильтрах"""
    prefix = "broadcast_" if callback.data.startswith("broadcast_") else ""
    # Разбиваем callback.data и берём последний элемент как пол
    parts = callback.data.split("_")
    sex = parts[-1]  # Пол всегда последний
    data = await state.get_data()
    filters = data.get("filters", {})
    filters["sex"] = sex
    await state.update_data(filters=filters)
    logging.info(f"Установлен фильтр пола: {sex}")
    if prefix:
        await callback.message.edit_text("Выберите фильтр:", reply_markup=broadcast_filters_keyboard(filters))
    else:
        await callback.message.edit_text("Выберите фильтр:", reply_markup=filters_keyboard(filters))
    await state.set_state(None)


@router.callback_query(lambda c: c.data == "filter_age")
async def start_age_filter(callback: CallbackQuery, state: FSMContext):
    """Начать выбор возраста для интерактивных фильтров"""
    max_age = get_max_age()
    if max_age <= 0:
        await callback.answer("Нет доступных возрастов для фильтрации.", show_alert=True)
        return
    await state.update_data(age_min=None, age_max=None)
    await callback.message.edit_text("Выберите минимальный возраст:",
                                     reply_markup=age_keyboard(0, max_age, "min"))
    await state.set_state(FilterStates.waiting_min_age)


@router.callback_query(lambda c: c.data == "broadcast_filter_age")
async def start_broadcast_age_filter(callback: CallbackQuery, state: FSMContext):
    """Начать выбор возраста для фильтров рассылки"""
    max_age = get_max_age()
    if max_age <= 0:
        await callback.answer("Нет доступных возрастов для фильтрации.", show_alert=True)
        return
    await state.update_data(age_min=None, age_max=None)
    await callback.message.edit_text("Выберите минимальный возраст:",
                                     reply_markup=age_keyboard(0, max_age, "min", "broadcast_"))
    await state.set_state(FilterStates.waiting_min_age)


@router.callback_query(lambda c: c.data.startswith("age_min_") or c.data.startswith("broadcast_age_min_"))
async def set_min_age(callback: CallbackQuery, state: FSMContext):
    """Установить минимальный возраст"""
    prefix = "broadcast_" if callback.data.startswith("broadcast_") else ""
    # Разбиваем callback.data и берём последний элемент как возраст
    parts = callback.data.split("_")
    min_age = int(parts[-1])  # Возраст всегда последний
    await state.update_data(age_min=min_age)
    max_age = get_max_age()
    if max_age <= min_age:
        await callback.answer("Максимальный возраст должен быть больше минимального.", show_alert=True)
        return
    logging.info(f"Установлен минимальный возраст: {min_age}")
    await callback.message.edit_text("Выберите максимальный возраст:",
                                     reply_markup=age_keyboard(min_age, max_age, "max", prefix))
    await state.set_state(FilterStates.waiting_max_age)


@router.callback_query(lambda c: c.data.startswith("age_max_") or c.data.startswith("broadcast_age_max_"))
async def set_max_age(callback: CallbackQuery, state: FSMContext):
    """Установить максимальный возраст"""
    prefix = "broadcast_" if callback.data.startswith("broadcast_") else ""
    # Разбиваем callback.data и берём последний элемент как возраст
    parts = callback.data.split("_")
    max_age = int(parts[-1])  # Возраст всегда последний
    data = await state.get_data()
    min_age = data.get("age_min", 0)

    if max_age < min_age:
        await callback.answer("Максимальный возраст должен быть больше минимального!", show_alert=True)
        return

    filters = data.get("filters", {})
    filters["age_min"] = min_age
    filters["age_max"] = max_age
    await state.update_data(filters=filters)
    logging.info(f"Установлен диапазон возраста: {min_age}-{max_age}")
    if prefix:
        await callback.message.edit_text("Выберите фильтр:", reply_markup=broadcast_filters_keyboard(filters))
    else:
        await callback.message.edit_text("Выберите фильтр:", reply_markup=filters_keyboard(filters))
    await state.set_state(None)


@router.callback_query(lambda c: c.data == "filter_name")
async def start_name_filter(callback: CallbackQuery, state: FSMContext):
    """Начать поиск по имени для интерактивных фильтров"""
    await callback.message.edit_text("Введите имя животного (или часть имени):")
    await state.set_state(FilterStates.waiting_name)


@router.callback_query(lambda c: c.data == "broadcast_filter_name")
async def start_broadcast_name_filter(callback: CallbackQuery, state: FSMContext):
    """Начать поиск по имени для фильтров рассылки"""
    await callback.message.edit_text("Введите имя животного (или часть имени):")
    await state.set_state(FilterStates.waiting_name)


@router.message(FilterStates.waiting_name)
async def set_name(message: Message, state: FSMContext):
    """Установить имя в фильтрах"""
    name = message.text.strip()
    if not name:
        await message.answer("Имя не может быть пустым. Попробуйте снова.")
        return

    data = await state.get_data()
    filters = data.get("filters", {})
    filters["name"] = name
    await state.update_data(filters=filters)
    logging.info(f"Установлен фильтр имени: {name}")

    if data.get("state") == "channel_filters":
        await message.answer("Фильтр по имени установлен. Выберите следующий фильтр:",
                             reply_markup=broadcast_filters_keyboard(filters))
    else:
        await message.answer("Фильтр по имени установлен. Выберите следующий фильтр:",
                             reply_markup=filters_keyboard(filters))
    await state.set_state(None)


@router.callback_query(lambda c: c.data == "back_to_filters")
async def back_to_filters(callback: CallbackQuery, state: FSMContext):
    """Вернуться к выбору интерактивных фильтров"""
    data = await state.get_data()
    filters = data.get("filters", {})
    await callback.message.edit_text("Выберите фильтр:", reply_markup=filters_keyboard(filters))
    await state.set_state(None)


@router.callback_query(lambda c: c.data == "back_to_broadcast_filters")
async def back_to_broadcast_filters(callback: CallbackQuery, state: FSMContext):
    """Вернуться к выбору фильтров рассылки"""
    data = await state.get_data()
    filters = data.get("filters", {})
    await callback.message.edit_text("Выберите фильтр:", reply_markup=broadcast_filters_keyboard(filters))
    await state.set_state(None)


@router.callback_query(lambda c: c.data == "show_filtered")
async def show_filtered(callback: CallbackQuery, state: FSMContext):
    """Показать животных по интерактивным фильтрам"""
    data = await state.get_data()
    filters = data.get("filters", {})
    logging.info(f"Применение фильтров: {filters}")

    if not filters:
        await callback.answer("Выберите хотя бы один фильтр!", show_alert=True)
        return

    animals = get_animals_by_filters(filters)
    if not animals:
        await callback.answer("Животные по этим фильтрам не найдены.", show_alert=True)
        return

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"🐾 {animal['name']}", callback_data=f"animal_{animal['id']}")]
        for animal in animals
    ])
    await state.update_data(list_type="show_filtered", filters=filters)
    logging.info("Показан отфильтрованный список животных")
    await callback.message.edit_text("Результаты по фильтрам:", reply_markup=keyboard)


@router.callback_query(lambda c: c.data == "save_broadcast_filters")
async def save_broadcast_filters(callback: CallbackQuery, state: FSMContext):
    """Сохранить фильтры для канала"""
    data = await state.get_data()
    filters = data.get("filters", {})
    chat_id = data.get("channel_id")
    schedule = data.get("schedule", "0 10 * * *")
    add_channel(chat_id, filters=filters, schedule=schedule)
    logging.info(f"Фильтры для канала {chat_id} сохранены: {filters}, расписание: {schedule}")
    await callback.message.edit_text("Фильтры и расписание для канала сохранены.",
                                     reply_markup=broadcast_management_keyboard())
    await state.set_state(None)


@router.callback_query(lambda c: c.data.startswith("animal_"))
async def show_animal_details(callback: CallbackQuery, state: FSMContext):
    """Показать детали животного с красивой разметкой"""
    animal_id = int(callback.data.split("_")[1])
    animals = get_all_animals()
    animal = next((a for a in animals if a["id"] == animal_id), None)

    if animal:
        text = (
            f"🐾 <b>{animal['name']}</b>\n\n"
            f"📅 <b>Возраст:</b> {animal['age']}\n"
            f"⚤ <b>Пол:</b> {animal['sex']}"
        )
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🌐 Перейти на сайт",
                                  url=animal['description'] if animal['description'].startswith(
                                      'http') else 'https://less-homeless.com')],
            [InlineKeyboardButton(text="🔙 Назад к списку", callback_data="back_to_list")]
        ])
        try:
            sent_message = await callback.message.answer_photo(
                photo=animal['photo_url'],
                caption=text,
                parse_mode="HTML",
                reply_markup=keyboard
            )
            await state.update_data(card_message_id=sent_message.message_id)
            await callback.message.delete()
        except Exception as e:
            logging.error(f"Ошибка при отправке фото: {e}")
            sent_message = await callback.message.answer(
                text=text,
                parse_mode="HTML",
                reply_markup=keyboard
            )
            await state.update_data(card_message_id=sent_message.message_id)
            await callback.message.delete()
    else:
        await callback.answer("Информация о животном не найдена.", show_alert=True)


@router.callback_query(lambda c: c.data == "back_to_list")
async def back_to_list(callback: CallbackQuery, state: FSMContext):
    """Вернуться к предыдущему списку (полному или отфильтрованному)"""
    data = await state.get_data()
    list_type = data.get("list_type", "view_all")
    card_message_id = data.get("card_message_id")

    if card_message_id:
        try:
            await bot.delete_message(chat_id=callback.message.chat.id, message_id=card_message_id)
        except Exception as e:
            logging.error(f"Ошибка при удалении карточки питомца: {e}")

    if list_type == "show_filtered":
        filters = data.get("filters", {})
        animals = get_animals_by_filters(filters)
        if not animals:
            await callback.message.answer("Животные по этим фильтрам не найдены.")
            return
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f"🐾 {animal['name']}", callback_data=f"animal_{animal['id']}")]
            for animal in animals
        ])
        await callback.message.answer("Результаты по фильтрам:", reply_markup=keyboard)
        logging.info(f"Восстановлен отфильтрованный список с фильтрами: {filters}")
    else:
        animals = get_all_animals()
        if not animals:
            await callback.message.answer("Животных пока нет в базе.")
            return
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f"🐾 {animal['name']}", callback_data=f"animal_{animal['id']}")]
            for animal in animals
        ])
        await callback.message.answer("Все доступные животные:", reply_markup=keyboard)
        logging.info("Восстановлен полный список животных")


# ======================== Запуск бота и планировщика ========================

async def main():
    # Инициализация базы данных
    init_db()

    # Инициализация и запуск планировщика
    global scheduler
    scheduler.remove_all_jobs()  # Очистка старых задач
    logging.info("Все старые задачи удалены")
    channels = get_channels()
    for channel in channels:
        if channel["is_active"]:
            try:
                scheduler.add_job(
                    broadcast_animal_for_channel,
                    trigger=CronTrigger.from_crontab(channel["schedule"]),
                    args=[channel["chat_id"]],
                    id=str(channel["chat_id"])
                )
                logging.info(
                    f"Задача рассылки добавлена для канала {channel['chat_id']} с расписанием {channel['schedule']}")
            except ValueError as e:
                logging.error(f"Некорректное расписание для канала {channel['chat_id']}: {e}")
    logging.info(f"Текущие задачи: {[job.id for job in scheduler.get_jobs()]}")
    scheduler.start()
    logging.info("Планировщик запущен")

    # Запуск бота
    dp.include_router(router)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
# ======================== Запуск бота ========================

async def start_bot():
    dp.include_router(router)
    await dp.start_polling(bot)


# if __name__ == "__main__":
#     asyncio.run(main())