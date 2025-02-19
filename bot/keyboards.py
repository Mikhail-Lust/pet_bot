def time_settings_keyboard():
    """Клавиатура для настроек времени рассылки"""
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton("Частота", callback_data="set_frequency")],  # Выбор частоты сообщений
        [InlineKeyboardButton("Время рассылки", callback_data="set_time")],  # Выбор времени рассылки
        [InlineKeyboardButton("Сбросить настройки", callback_data="reset_settings")]  # Сброс настроек на дефолт
    ])
    return keyboard

def frequency_keyboard():
    """Клавиатура для выбора частоты сообщений в день"""
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton("1 сообщение в день", callback_data="message_count_1")],
        [InlineKeyboardButton("2 сообщения в день", callback_data="message_count_2")],
        [InlineKeyboardButton("3 сообщения в день", callback_data="message_count_3")],
        [InlineKeyboardButton("🔙 Назад", callback_data="back_to_time_settings")]
    ])
    return keyboard

def time_keyboard():
    """Клавиатура для выбора времени рассылки"""
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton("07:00", callback_data="time_07:00")],
        [InlineKeyboardButton("12:00", callback_data="time_12:00")],
        [InlineKeyboardButton("18:00", callback_data="time_18:00")],
        [InlineKeyboardButton("21:00", callback_data="time_21:00")],
        [InlineKeyboardButton("Рандомное время", callback_data="time_random")]
    ])
    return keyboard

def reset_settings_keyboard():
    """Клавиатура для сброса настроек на дефолт"""
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton("Сбросить на дефолт (1 сообщение в день, рандомное время)", callback_data="reset_default")]
    ])
    return keyboard
