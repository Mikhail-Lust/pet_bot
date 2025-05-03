import sqlite3
import asyncio
import logging
import re
from aiogram import Bot, Dispatcher, Router
from aiogram.filters import CommandStart
from aiogram.types import Message, InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from dotenv import load_dotenv
import os

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('bot.log', encoding='utf-8')  # ← явно задаем кодировку
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

# Подключение к базе данных
def get_db_connection():
    return sqlite3.connect(DB_PATH)

# Классы для FSM
class FilterStates(StatesGroup):
    waiting_min_age = State()
    waiting_max_age = State()
    waiting_sex = State()
    waiting_name = State()

# Нормализация возраста
def normalize_age(age_str):
    """Извлечь числовое значение возраста из строки"""
    if not age_str or age_str.lower() in ["не указан", "", "unknown"]:
        logging.debug(f"Возраст не указан: {age_str}")
        return None
    # Извлекаем первое целое число (например, "около 1" → 1, "2 года" → 2)
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

# ======================== Клавиатуры ========================

def main_keyboard():
    """Главное меню"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 Все животные", callback_data="view_all")],
        [InlineKeyboardButton(text="🔍 Фильтры", callback_data="view_filtered")]
    ])

def filters_keyboard(selected_filters: dict) -> InlineKeyboardMarkup:
    """Клавиатура выбора фильтров с отметками"""
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

def sex_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура выбора пола"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Мужской", callback_data="sex_Мужской")],
        [InlineKeyboardButton(text="Женский", callback_data="sex_Женский")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_filters")]
    ])

def age_keyboard(start_age: int, end_age: int, mode: str) -> InlineKeyboardMarkup:
    """Клавиатура для выбора возраста"""
    buttons = [[]]  # Инициализируем с пустым списком
    if end_age < start_age:
        logging.warning(f"Некорректный диапазон возраста: start={start_age}, end={end_age}")
        end_age = start_age
    for age in range(start_age, end_age + 1):
        if len(buttons[-1]) >= 3:  # Новая строка после 3 кнопок
            buttons.append([])
        callback_data = f"age_{mode}_{age}"
        buttons[-1].append(InlineKeyboardButton(text=str(age), callback_data=callback_data))
    buttons.append([InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_filters")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

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

        # Фильтр по имени
        if "name" in filters:
            query += " AND name LIKE ?"
            params.append(f"%{filters['name']}%")
            logging.info(f"Применён фильтр по имени: {filters['name']}")

        # Фильтр по полу
        if "sex" in filters:
            query += " AND sex = ?"
            params.append(filters["sex"])
            logging.info(f"Применён фильтр по полу: {filters['sex']}")

        c.execute(query, params)
        animals = [{"id": row[0], "name": row[1], "age": row[2], "sex": row[3],
                    "photo_url": row[4], "description": row[5]} for row in c.fetchall()]
        logging.info(f"Найдено {len(animals)} животных после SQL-фильтров")

        # Фильтр по возрасту (в памяти)
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

        # Нормализация пола для отображения
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

# ======================== Обработчики ========================

@router.message(CommandStart())
async def start(message: Message):
    """Стартовое сообщение"""
    await message.answer("Добро пожаловать! Этот бот помогает найти питомцев из приюта.",
                        reply_markup=main_keyboard())

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
    # Сохраняем состояние списка
    await state.update_data(list_type="view_all")
    logging.info("Показан полный список животных")
    # Отправляем новое сообщение
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
    """Начать выбор пола"""
    await callback.message.edit_text("Выберите пол:", reply_markup=sex_keyboard())
    await state.set_state(FilterStates.waiting_sex)

@router.callback_query(lambda c: c.data.startswith("sex_"))
async def set_sex(callback: CallbackQuery, state: FSMContext):
    """Установить пол в фильтрах"""
    sex = callback.data.split("_")[1]
    data = await state.get_data()
    filters = data.get("filters", {})
    filters["sex"] = sex
    await state.update_data(filters=filters)
    logging.info(f"Установлен фильтр пола: {sex}")
    await callback.message.edit_text("Выберите фильтр:", reply_markup=filters_keyboard(filters))
    await state.set_state(None)

@router.callback_query(lambda c: c.data == "filter_age")
async def start_age_filter(callback: CallbackQuery, state: FSMContext):
    """Начать выбор возраста"""
    max_age = get_max_age()
    if max_age <= 0:
        await callback.answer("Нет доступных возрастов для фильтрации.", show_alert=True)
        return
    await state.update_data(age_min=None, age_max=None)
    await callback.message.edit_text("Выберите минимальный возраст:",
                                    reply_markup=age_keyboard(0, max_age, "min"))
    await state.set_state(FilterStates.waiting_min_age)

@router.callback_query(lambda c: c.data.startswith("age_min_"))
async def set_min_age(callback: CallbackQuery, state: FSMContext):
    """Установить минимальный возраст"""
    min_age = int(callback.data.split("_")[2])
    await state.update_data(age_min=min_age)
    max_age = get_max_age()
    if max_age <= min_age:
        await callback.answer("Максимальный возраст должен быть больше минимального.", show_alert=True)
        return
    logging.info(f"Установлен минимальный возраст: {min_age}")
    await callback.message.edit_text("Выберите максимальный возраст:",
                                    reply_markup=age_keyboard(min_age, max_age, "max"))
    await state.set_state(FilterStates.waiting_max_age)

@router.callback_query(lambda c: c.data.startswith("age_max_"))
async def set_max_age(callback: CallbackQuery, state: FSMContext):
    """Установить максимальный возраст"""
    data = await state.get_data()
    min_age = data.get("age_min", 0)
    max_age = int(callback.data.split("_")[2])

    if max_age < min_age:
        await callback.answer("Максимальный возраст должен быть больше минимального!", show_alert=True)
        return

    filters = data.get("filters", {})
    filters["age_min"] = min_age
    filters["age_max"] = max_age
    await state.update_data(filters=filters)
    logging.info(f"Установлен диапазон возраста: {min_age}-{max_age}")
    await callback.message.edit_text("Выберите фильтр:", reply_markup=filters_keyboard(filters))
    await state.set_state(None)

@router.callback_query(lambda c: c.data == "filter_name")
async def start_name_filter(callback: CallbackQuery, state: FSMContext):
    """Начать поиск по имени"""
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
    await message.answer("Фильтр по имени установлен. Выберите следующий фильтр:",
                        reply_markup=filters_keyboard(filters))
    await state.set_state(None)

@router.callback_query(lambda c: c.data == "back_to_filters")
async def back_to_filters(callback: CallbackQuery, state: FSMContext):
    """Вернуться к выбору фильтров"""
    data = await state.get_data()
    filters = data.get("filters", {})
    await callback.message.edit_text("Выберите фильтр:", reply_markup=filters_keyboard(filters))
    await state.set_state(None)

@router.callback_query(lambda c: c.data == "show_filtered")
async def show_filtered(callback: CallbackQuery, state: FSMContext):
    """Показать животных по фильтрам"""
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
    # Сохраняем состояние списка
    await state.update_data(list_type="show_filtered", filters=filters)
    logging.info("Показан отфильтрованный список животных")
    await callback.message.edit_text("Результаты по фильтрам:", reply_markup=keyboard)

@router.callback_query(lambda c: c.data.startswith("animal_"))
async def show_animal_details(callback: CallbackQuery, state: FSMContext):
    """Показать детали животного с красивой разметкой"""
    animal_id = int(callback.data.split("_")[1])
    animals = get_all_animals()
    animal = next((a for a in animals if a["id"] == animal_id), None)

    if animal:
        # Формируем красивое сообщение с HTML-разметкой (без description)
        text = (
            f"🐾 <b>{animal['name']}</b>\n\n"
            f"📅 <b>Возраст:</b> {animal['age']}\n"
            f"⚤ <b>Пол:</b> {animal['sex']}"
        )

        # Создаём клавиатуру с кнопками
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🌐 Перейти на сайт", url=animal['description'] if animal['description'].startswith('http') else 'https://less-homeless.com')],
            [InlineKeyboardButton(text="🔙 Назад к списку", callback_data="back_to_list")]
        ])

        try:
            # Отправляем фото с подписью и сохраняем ID сообщения
            sent_message = await callback.message.answer_photo(
                photo=animal['photo_url'],
                caption=text,
                parse_mode="HTML",
                reply_markup=keyboard
            )
            # Сохраняем ID сообщения с карточкой
            await state.update_data(card_message_id=sent_message.message_id)
            # Удаляем сообщение со списком
            await callback.message.delete()
        except Exception as e:
            logging.error(f"Ошибка при отправке фото: {e}")
            # Если фото не удалось отправить, отправляем текст
            sent_message = await callback.message.answer(
                text=text,
                parse_mode="HTML",
                reply_markup=keyboard
            )
            # Сохраняем ID сообщения с карточкой
            await state.update_data(card_message_id=sent_message.message_id)
            # Удаляем сообщение со списком
            await callback.message.delete()
    else:
        await callback.answer("Информация о животном не найдена.", show_alert=True)

@router.callback_query(lambda c: c.data == "back_to_list")
async def back_to_list(callback: CallbackQuery, state: FSMContext):
    """Вернуться к предыдущему списку (полному или отфильтрованному)"""
    data = await state.get_data()
    list_type = data.get("list_type", "view_all")
    card_message_id = data.get("card_message_id")

    # Удаляем сообщение с карточкой питомца
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

# ======================== Запуск бота ========================

async def main():
    dp.include_router(router)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())