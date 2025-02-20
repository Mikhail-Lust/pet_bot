from aiogram import F
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery, Message
from aiogram.filters import CommandStart, StateFilter
from aiogram import Bot, Dispatcher
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.exceptions import TelegramBadRequest
import asyncio
import logging
from aiogram import types
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram import Router
from db import add_channel_to_db, get_user_channels, remove_channel_from_db  # Импортируем функции работы с БД
import os
from dotenv import load_dotenv
from db import (
    update_subscription_status,  # Функция: update_subscription_status(user_id, toggle=False/True)
    get_user_channels,  # Возвращает список каналов для данного user_id
    add_channel,  # Привязывает канал к пользователю
    remove_channel_from_db,  # Удаляет канал из базы для пользователя
    get_user_filters,  # Получает фильтры для рассылки
    save_send_time_to_db,  # Сохраняет время рассылки
    get_send_time_from_db,  # Получает время рассылки
    get_all_users_for_subscription,  # Возвращает всех пользователей для рассылки
    get_animal_by_id,  # Возвращает информацию о животном по ID
    update_user_filter,  init_db,  get_all_animals,
    get_animals_by_filter, get_subscription_status, get_animals_by_color, get_animals_by_filters,get_max_age
)

# Загружаем переменные из .env
load_dotenv()

# Получаем токен
TOKEN = os.getenv("TOKEN")

# Проверяем, загружен ли токен
if TOKEN is None:
    raise ValueError("Переменная окружения TOKEN не найдена! Проверьте файл .env.")

# Инициализация
bot = Bot(token=TOKEN, parse_mode="HTML")
dp = Dispatcher()
logging.basicConfig(level=logging.INFO)
router = Router()

# ======================== КЛАВИАТУРЫ ========================

def main_keyboard():
    """ Главное меню """
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Посмотреть", callback_data="view_animals")],
        [InlineKeyboardButton(text="Рассылка", callback_data="manage_subscription")]
    ])
    return keyboard

def filters_keyboard(selected_filters: dict) -> InlineKeyboardMarkup:
    """Клавиатура выбора фильтров с отметками выбранных опций"""
    def mark_selected(text, key):
        # Для возраста проверяем оба параметра
        if key == "age":
            age_selected = "age_min" in selected_filters and "age_max" in selected_filters
            return f"✔ {text}" if age_selected else text
        return f"✔ {text}" if key in selected_filters else text

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=mark_selected("🐶 Только собачки", "dogs"), callback_data="filter_dogs")],
        [InlineKeyboardButton(text=mark_selected("🐱 Только кошечки", "cats"), callback_data="filter_cats")],
        [InlineKeyboardButton(text=mark_selected("🎨 По окраске", "color"), callback_data="filter_color")],
        [InlineKeyboardButton(text=mark_selected("📅 По возрасту", "age"), callback_data="filter_age")],
        [InlineKeyboardButton(text="✅ Показать", callback_data="show_filtered")],
        [InlineKeyboardButton(text="🔙 Выйти", callback_data="exit_filters")]
    ])
    return keyboard



def subscription_keyboard(user_id):
    """ Клавиатура управления рассылкой """
    channels = get_user_channels(user_id)
    buttons = [[InlineKeyboardButton(text=f"➕ Добавить канал", callback_data="add_channel")]] if not channels else []

    for channel in channels:
        buttons.append([InlineKeyboardButton(text=f"❌ {channel}", callback_data=f"remove_channel:{channel}")])

    buttons.append([InlineKeyboardButton(text="🔙 Назад", callback_data="back")])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


def color_keyboard(selected_colors: list) -> InlineKeyboardMarkup:
    """ Клавиатура выбора окраса с отметками выбранных цветов """
    colors = ["Рыжий", "Черный", "Коричневый", "Белый"]

    def mark_selected(color):
        return f"✔ {color}" if color in selected_colors else color

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=mark_selected(color), callback_data=f"color_{color}")] for color in colors
    ])

    # Добавляем кнопку "🔙 Вернуться к фильтрам"
    keyboard.inline_keyboard.append(
        [InlineKeyboardButton(text="🔙 Вернуться к фильтрам", callback_data="back_to_filters")])
    return keyboard



def subscription_keyboard() -> InlineKeyboardMarkup:
    """ Клавиатура для управления рассылкой """
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Переключить статус рассылки", callback_data="toggle_subscription")],
        [InlineKeyboardButton(text="➕ Добавить канал/группу", callback_data="add_channel")],
        [InlineKeyboardButton(text="❌ Удалить канал/группу", callback_data="remove_channel")],
        [InlineKeyboardButton(text="🕒 Установить время рассылки", callback_data="set_send_time")],
        [InlineKeyboardButton(text="🔧 Настроить фильтры рассылки", callback_data="configure_filters")],
        [InlineKeyboardButton(text="⚙️ Включить/выключить рассылку новых животных", callback_data="toggle_new_animal_updates")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_main")]
    ])
    return keyboard

def time_settings_keyboard():
    """Клавиатура для настроек времени рассылки"""
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Частота", callback_data="set_frequency")],
        [InlineKeyboardButton(text="Время рассылки", callback_data="set_time")],
        [InlineKeyboardButton(text="Сбросить настройки", callback_data="reset_settings")]
    ])
    return keyboard


def frequency_keyboard():
    """Клавиатура для выбора частоты сообщений в день"""
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="1 сообщение в день", callback_data="message_count_1")],
        [InlineKeyboardButton(text="2 сообщения в день", callback_data="message_count_2")],
        [InlineKeyboardButton(text="3 сообщения в день", callback_data="message_count_3")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_time_settings")]
    ])
    return keyboard

def time_keyboard():
    """Клавиатура для выбора времени рассылки"""
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="07:00", callback_data="time_07:00")],
        [InlineKeyboardButton(text="12:00", callback_data="time_12:00")],
        [InlineKeyboardButton(text="18:00", callback_data="time_18:00")],
        [InlineKeyboardButton(text="21:00", callback_data="time_21:00")],
        [InlineKeyboardButton(text="Рандомное время", callback_data="time_random")]
    ])
    return keyboard

def reset_settings_keyboard():
    """Клавиатура для сброса настроек на дефолт"""
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Сбросить на дефолт (1 сообщение в день, рандомное время)", callback_data="reset_default")]
    ])
    return keyboard

# ======================== ХЭНДЛЕРЫ ========================


@dp.message(CommandStart())
async def start(message: Message):
    """ Стартовое сообщение """
    await message.answer(
        "Добро пожаловать! Этот бот помогает находить питомцев из приюта.",
        reply_markup=main_keyboard()
    )


@dp.callback_query(F.data == "view_animals")
async def view_animals(callback: CallbackQuery):
    """ Выбор способа просмотра животных """
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 Все", callback_data="view_all")],
        [InlineKeyboardButton(text="🔍 По фильтрам", callback_data="view_filtered")]
    ])
    await callback.message.edit_text("Выберите способ просмотра:", reply_markup=keyboard)


@dp.callback_query(F.data == "view_all")
async def show_all_animals(callback: CallbackQuery):
    """ Отобразить всех животных """
    animals = get_all_animals()
    if not animals:
        await callback.answer("Животных пока нет в базе.", show_alert=True)
        return

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"🐾 {animal['name']}", callback_data=f"animal_{animal['id']}")]
        for animal in animals
    ])
    await callback.message.edit_text("Все доступные животные:", reply_markup=keyboard)



@dp.callback_query(F.data == "view_filtered")
async def choose_filters(callback: CallbackQuery, state: FSMContext):
    """ Открывает меню выбора фильтров """
    data = await state.get_data()
    selected_filters = data.get("filters", {})

    current_text = callback.message.text
    new_text = "Выберите фильтр:"

    # Проверяем, изменился ли текст или клавиатура
    current_keyboard = callback.message.reply_markup
    new_keyboard = filters_keyboard(selected_filters)

    if current_text != new_text or current_keyboard != new_keyboard:
        await callback.message.edit_text(new_text, reply_markup=new_keyboard)


@dp.callback_query(F.data == "exit_filters")
async def exit_filters(callback: CallbackQuery, state: FSMContext):
    """ Возвращает в главное меню и сбрасывает фильтры """
    await state.clear()
    await callback.message.edit_text("Вы вернулись в главное меню.", reply_markup=main_keyboard())

@dp.callback_query(F.data == "back_to_filters")
async def back_to_filters(callback: CallbackQuery, state: FSMContext):
    """ Возвращает к выбору фильтров, сохраняя данные """
    # Получаем текущие фильтры из состояния
    data = await state.get_data()
    filters = data.get("filters", {})

    # Показываем клавиатуру с фильтрами
    await callback.message.edit_text("Выберите фильтр:", reply_markup=filters_keyboard(filters))

@dp.callback_query(F.data.startswith("filter_"))
async def set_filter(callback: CallbackQuery, state: FSMContext):
    """ Устанавливает или убирает фильтр """
    filter_param = callback.data.split("_")[1]

    data = await state.get_data()
    filters = data.get("filters", {})

    # Обрабатываем фильтр по окраске отдельно
    if filter_param == "color":
        selected_colors = filters.get("color", [])
        await callback.message.edit_text("Выберите окрас:", reply_markup=color_keyboard(selected_colors))
        return

    # Переключаем состояние фильтра
    if filter_param in filters:
        del filters[filter_param]
    else:
        filters[filter_param] = True

    # Обновляем состояние
    await state.update_data(filters=filters)

    await callback.message.edit_text("Выберите фильтр:", reply_markup=filters_keyboard(filters))


@dp.callback_query(F.data.startswith("color_"))
async def filter_by_color(callback: CallbackQuery, state: FSMContext):
    """ Добавляет/удаляет выбранный окрас в фильтрах """
    color = callback.data.split("_", 1)[1]

    data = await state.get_data()
    filters = data.get("filters", {})
    selected_colors = filters.get("color", [])

    if color in selected_colors:
        selected_colors.remove(color)
    else:
        selected_colors.append(color)

    filters["color"] = selected_colors
    # Обновляем состояние
    await state.update_data(filters=filters)

    await callback.message.edit_text("Выберите окрас:", reply_markup=color_keyboard(selected_colors))

@dp.callback_query(F.data == "show_filtered")
async def show_filtered(callback: CallbackQuery, state: FSMContext):
    """ Отображает животных по выбранным фильтрам """
    data = await state.get_data()
    filters = data.get("filters", {})

    if not filters:
        await callback.answer("Выберите хотя бы один фильтр!", show_alert=True)
        return

    # Получаем животных по всем фильтрам (AND)
    animals = get_animals_by_filters(filters)

    if not animals:
        await callback.answer("Животные по этим фильтрам не найдены. Попробуйте изменить параметры!", show_alert=True)
        return

    # Формируем клавиатуру с найденными животными
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"🐾 {animal[1]}", callback_data=f"animal_{animal[0]}")]
        for animal in animals  # Предположим, что animal[0] - это id, animal[1] - это name
    ])
    await callback.message.edit_text("Результаты по фильтрам:", reply_markup=keyboard)


# Обработчик начала выбора возраста
@dp.callback_query(F.data == "filter_age")
async def start_age_filter(callback: CallbackQuery, state: FSMContext):
    """Начинает процесс выбора возраста"""
    # Сбрасываем предыдущие значения возраста
    await state.update_data(age_min=None, age_max=None)

    max_age_db = get_max_age()
    await callback.message.edit_text(
        "Выберите минимальный возраст:",
        reply_markup=age_keyboard(0, max_age_db, "min")
    )
    await state.set_state("waiting_min_age")


# Обработчик выбора минимального возраста
@dp.callback_query(F.data.startswith("age_min_"))
async def set_min_age(callback: CallbackQuery, state: FSMContext):
    """Сохраняет минимальный возраст и запрашивает максимальный"""
    min_age = int(callback.data.split("_")[2])
    await state.update_data(age_min=min_age)

    max_age_db = get_max_age()
    await callback.message.edit_text(
        "Выберите максимальный возраст:",
        reply_markup=age_keyboard(min_age, max_age_db, "max")
    )
    await state.set_state("waiting_max_age")


# Обработчик выбора максимального возраста
@dp.callback_query(F.data.startswith("age_max_"))
async def set_max_age(callback: CallbackQuery, state: FSMContext):
    """Сохраняет максимальный возраст и обновляет фильтры"""
    data = await state.get_data()
    min_age = data.get("age_min", 0)
    max_age = int(callback.data.split("_")[2])

    if max_age < min_age:
        await callback.answer("❗ Максимальный возраст должен быть больше минимального!", show_alert=True)
        return

    # Обновляем фильтры в состоянии
    current_data = await state.get_data()
    filters = current_data.get("filters", {})
    filters["age_min"] = min_age
    filters["age_max"] = max_age
    await state.update_data(filters=filters)

    await back_to_filters(callback, state)


def age_keyboard(start_age: int, end_age: int, mode: str) -> InlineKeyboardMarkup:
    """Генерирует клавиатуру для выбора возраста"""
    buttons = []
    for age in range(start_age, end_age + 1):
        if age % 3 == 0 and age != start_age:
            buttons.append([])
        callback_data = f"age_{mode}_{age}"
        buttons[-1].append(InlineKeyboardButton(text=str(age), callback_data=callback_data))

    # Добавляем кнопку возврата
    buttons.append([InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_filters")])

    return InlineKeyboardMarkup(inline_keyboard=buttons)





@dp.callback_query(F.data.startswith("animal_"))
async def show_animal_details(callback: CallbackQuery):
    """ Показать детали животного """
    animal_id = int(callback.data.split("_")[1])
    animals = get_all_animals()
    animal = next((a for a in animals if a["id"] == animal_id), None)

    if animal:
        text = f"🐾 <b>{animal['name']}</b>\n" \
               f"📅 Возраст: {animal['age']}\n" \
               f"🎨 Окраска: {animal['color']}\n" \
               f"📞 Контакты: {animal['contact']}"

        await callback.message.answer_photo(photo=animal['photo_url'], caption=text, parse_mode="HTML")
    else:
        await callback.answer("Информация о животном не найдена.", show_alert=True)


# РАССЫЛКА

@dp.callback_query(lambda c: c.data == "manage_subscription")
async def manage_subscription(callback: CallbackQuery):
    user_id = callback.from_user.id
    # Выводим сообщение с доступными опциями
    text = "Выберите опцию для управления рассылкой:"
    await callback.message.edit_text(text, reply_markup=subscription_keyboard())


@dp.callback_query(lambda c: c.data == "back_to_main")
async def back_to_main(callback: CallbackQuery):
    await callback.message.edit_text("Главное меню", reply_markup=main_keyboard())


@dp.callback_query(F.data == 'toggle_subscription')
async def toggle_subscription_status(callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    current_status = get_subscription_status(user_id)  # Получаем текущий статус из базы

    # Переключаем статус
    new_status = 1 if current_status == 0 else 0
    update_subscription_status(user_id, new_status)  # Обновляем статус в БД

    status_message = "✅Рассылка включена.✅" if new_status == 1 else "❌Рассылка выключена.❌"

    # Редактируем сообщение, чтобы отобразить новый статус
    await callback_query.message.edit_text(
        text=f"{status_message}\n\nИспользуйте кнопки ниже для управления рассылкой.",
        reply_markup=subscription_keyboard()  # Обновленная клавиатура
    )

    # Подтверждаем нажатие callback
    await callback_query.answer(f"Статус рассылки изменен на: {status_message}")



#ДОБАВИТЬ/УДАЛИТЬ КАНАЛ
# Инициализация роутера
router = Router()


class AddChannel(StatesGroup):
    wait_for_channel = State()  # Состояние ожидания ссылки канала

# Обработчик кнопки для добавления канала
@router.callback_query(lambda c: c.data == 'add_channel')
async def add_channel(callback_query: CallbackQuery, state: FSMContext):
    # Отправляем сообщение с просьбой ввести канал
    await callback_query.message.answer("Пожалуйста, отправьте ссылку на канал или группу (например, @channel_name):")
    # Переходим в режим ожидания канала
    await state.set_state(AddChannel.wait_for_channel)


# Обработчик для обработки канала, который был отправлен пользователем
@router.message(StateFilter(AddChannel.wait_for_channel))  # Новый способ фильтрации с использованием StateFilter
async def process_channel(message: types.Message, state: FSMContext):
    channel_link = message.text.strip()

    # Проверяем, начинается ли ссылка с '@'
    if not channel_link.startswith('@'):
        await message.reply("Ссылка на канал должна начинаться с '@'. Пожалуйста, отправьте правильную ссылку.")
        return

    # Проводим проверку, чтобы убедиться, что пользователь является администратором в этом канале
    try:
        chat = await bot.get_chat(channel_link)  # Пытаемся получить чат
        logging.info(f"Chat data: {chat}")
        member = await bot.get_chat_member(chat.id, message.from_user.id)
        logging.info(f"User data: {member}")

        # Проверяем статус пользователя: если он администратор или владелец, то можно добавлять канал
        if member.status not in ['administrator', 'creator']:  # 'creator' заменили на 'owner'
            await message.reply("У вас нет прав администратора или владельца на этом канале.")
            logging.warning(f"User {message.from_user.id} is not an admin or creator.")
            return

        # Дополнительно проверяем, является ли сам бот администратором канала
        bot_member = await bot.get_chat_member(chat.id, bot.id)
        logging.info(f"Bot status: {bot_member.status}")
        if bot_member.status not in ['administrator', 'creator']:  # 'creator' заменили на 'owner'
            await message.reply("Бот не является администратором этого канала. Пожалуйста, добавьте бота как администратора.")
            logging.warning(f"Bot is not an admin or creator in channel {channel_link}.")
            return

    except Exception as e:
        await message.reply(f"Не удалось найти канал. Ошибка: {str(e)}")
        logging.error(f"Error when checking channel: {str(e)}")
        return

    # Добавляем канал в базу данных
    user_id = message.from_user.id
    add_channel_to_db(user_id, channel_link)

    # Подтверждаем добавление
    await message.reply(f"Канал {channel_link} успешно добавлен.")

    # Завершаем процесс
    await state.clear()  # Используем clear() вместо finish()


# Обработчик кнопки для удаления канала
@router.callback_query(lambda c: c.data == 'remove_channel')
async def remove_channel(callback_query: CallbackQuery):
    user_id = callback_query.from_user.id

    # Получаем список каналов пользователя из базы данных
    channels = get_user_channels(user_id)

    if not channels:
        await callback_query.message.answer("У вас нет добавленных каналов для удаления.")
        return

    # Формируем список для выбора канала
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=channel, callback_data=f"remove_{channel}")]
        for channel in channels
    ])

    await callback_query.message.answer("Выберите канал для удаления:", reply_markup=keyboard)


# Обработчик для удаления выбранного канала
@router.callback_query(lambda c: c.data.startswith('remove_'))
async def process_channel_removal(callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    channel_to_remove = callback_query.data[len("remove_"):]

    # Удаляем канал из базы данных
    remove_channel_from_db(user_id, channel_to_remove)

    # Подтверждаем удаление
    await callback_query.message.answer(f"Канал {channel_to_remove} успешно удален.")


dp.include_router(router)  # Это добавит все обработчики из router в диспетчер






# ======================== ЛОГИРОВАНИЕ  ========================



# ======================== ЗАПУСК БОТА ========================

async def main():
    init_db()
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
