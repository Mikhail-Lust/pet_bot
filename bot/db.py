import sqlite3
from datetime import datetime
import logging

# ── Функция для подключения к базе данных ──
def get_db_connection():
    conn = sqlite3.connect('animals.db')
    conn.row_factory = sqlite3.Row
    return conn

# ── Инициализация базы данных ──
def init_db():
    with get_db_connection() as conn:
        conn.executescript('''
            CREATE TABLE IF NOT EXISTS animals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT,
                type TEXT,
                age TEXT,
                color TEXT,
                photo_url TEXT,
                contact TEXT,
                source TEXT
            );
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                filters TEXT,
                message_count INTEGER,
                send_time TEXT,
                subscription_status INTEGER DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS user_channels (
                user_id INTEGER,
                channel_id TEXT,
                PRIMARY KEY (user_id, channel_id)
            );
            CREATE TABLE IF NOT EXISTS send_times (
                user_id INTEGER PRIMARY KEY,
                send_time TEXT
            );
        ''')

# ── Функции работы с животными ──
def add_animal(name, type, age, color, photo_url, contact, source="test_data"):
    with get_db_connection() as conn:
        conn.execute('''INSERT INTO animals (name, type, age, color, photo_url, contact, source)
                        VALUES (?, ?, ?, ?, ?, ?, ?)''',
                     (name, type, age, color, photo_url, contact, source))

def get_all_animals():
    with get_db_connection() as conn:
        return conn.execute('SELECT * FROM animals').fetchall()

def get_animals_by_filter(filter_type):
    with get_db_connection() as conn:
        return conn.execute('SELECT * FROM animals WHERE type LIKE ?', (f'%{filter_type}%',)).fetchall()

def get_animals_by_color(color):
    with get_db_connection() as conn:
        return conn.execute('SELECT * FROM animals WHERE lower(trim(color)) LIKE ?', (f"%{color.lower().strip()}%",)).fetchall()

def get_animal_by_id(animal_id: int):
    with get_db_connection() as conn:
        return conn.execute("SELECT * FROM animals WHERE id = ?", (animal_id,)).fetchone()

# ── Функции работы с пользователями ──
def get_user(user_id):
    with get_db_connection() as conn:
        return conn.execute('SELECT * FROM users WHERE user_id = ?', (user_id,)).fetchone()

def add_or_update_user(user_id, filters, message_count, send_time):
    with get_db_connection() as conn:
        conn.execute('''INSERT INTO users (user_id, filters, message_count, send_time)
                        VALUES (?, ?, ?, ?) ON CONFLICT(user_id)
                        DO UPDATE SET filters = excluded.filters, message_count = excluded.message_count, send_time = excluded.send_time''',
                     (user_id, filters, message_count, send_time))

def update_subscription_status(user_id, toggle=False):
    with get_db_connection() as conn:
        user = get_user(user_id)
        new_status = 1 if not user else (1 - user["subscription_status"] if toggle else user["subscription_status"])
        conn.execute('INSERT INTO users (user_id, subscription_status) VALUES (?, ?) ON CONFLICT(user_id) DO UPDATE SET subscription_status = excluded.subscription_status',
                     (user_id, new_status))
        return new_status

def get_user_filters(user_id):
    with get_db_connection() as conn:
        result = conn.execute("SELECT filters FROM users WHERE user_id = ?", (user_id,)).fetchone()
        return result["filters"] if result else None

def update_user_filter(user_id, filters):
    with get_db_connection() as conn:
        conn.execute("UPDATE users SET filters = ? WHERE user_id = ?", (filters, user_id))

# ── Функции работы с каналами ──
def add_channel(user_id, channel_id):
    with get_db_connection() as conn:
        conn.execute('INSERT OR REPLACE INTO user_channels (user_id, channel_id) VALUES (?, ?)', (user_id, channel_id))

def get_user_channels(user_id):
    with get_db_connection() as conn:
        return [row['channel_id'] for row in conn.execute('SELECT channel_id FROM user_channels WHERE user_id = ?', (user_id,)).fetchall()]

def remove_channel_from_db(user_id, channel_id):
    with get_db_connection() as conn:
        conn.execute('DELETE FROM user_channels WHERE user_id = ? AND channel_id = ?', (user_id, channel_id))

# ── Функции работы с подписками ──
def get_all_users_for_subscription():
    with get_db_connection() as conn:
        return [row['user_id'] for row in conn.execute("SELECT user_id FROM users WHERE subscription_status = 1").fetchall()]

def save_send_time_to_db(user_id: int, send_time: datetime):
    with get_db_connection() as conn:
        conn.execute('INSERT OR REPLACE INTO send_times (user_id, send_time) VALUES (?, ?)', (user_id, send_time))

def get_send_time_from_db(user_id: int):
    with get_db_connection() as conn:
        result = conn.execute("SELECT send_time FROM send_times WHERE user_id = ?", (user_id,)).fetchone()
        return datetime.strptime(result['send_time'], "%Y-%m-%d %H:%M:%S") if result else None

def update_subscription_status(user_id, status):
    """Обновить статус рассылки для пользователя в базе данных."""
    with get_db_connection() as conn:
        conn.execute('''
            INSERT INTO users (user_id, subscription_status)
            VALUES (?, ?)
            ON CONFLICT(user_id) DO UPDATE
            SET subscription_status = excluded.subscription_status
        ''', (user_id, status))

def get_subscription_status(user_id):
    """Получить текущий статус рассылки для пользователя."""
    with get_db_connection() as conn:
        result = conn.execute('SELECT subscription_status FROM users WHERE user_id = ?', (user_id,)).fetchone()
        return result['subscription_status'] if result else None

def get_all_users_for_subscription():
    """Получить всех пользователей с активной подпиской."""
    with get_db_connection() as conn:
        return [row['user_id'] for row in conn.execute("SELECT user_id FROM users WHERE subscription_status = 1").fetchall()]

# ── Функции работы с каналами ──
def add_channel_to_db(user_id, channel_link):
    """ Добавляем канал в базу данных """
    with get_db_connection() as conn:
        conn.execute("INSERT INTO user_channels (user_id, channel_id) VALUES (?, ?)", (user_id, channel_link))

def get_user_channels(user_id):
    """ Получаем каналы пользователя из базы данных """
    with get_db_connection() as conn:
        return [row['channel_id'] for row in conn.execute('SELECT channel_id FROM user_channels WHERE user_id = ?', (user_id,)).fetchall()]

def remove_channel_from_db(user_id, channel_id):
    """ Удаляем канал из базы данных """
    with get_db_connection() as conn:
        conn.execute("DELETE FROM user_channels WHERE user_id = ? AND channel_id = ?", (user_id, channel_id))

def get_db_connection():
    """ Функция для подключения к базе данных """
    conn = sqlite3.connect('animals.db')
    conn.row_factory = sqlite3.Row
    return conn


# ── Логирование ──
logging.basicConfig(level=logging.INFO)

def log_error(message):
    logging.error(message)

def log_info(message):
    logging.info(message)

# ── Функция для установки времени рассылки ──
def set_send_time(user_id: int, time: str) -> None:
    """
    Сохраняет время рассылки для пользователя в базе данных.
    Время в формате "HH:MM".
    """
    send_time = datetime.strptime(time, "%H:%M")  # Преобразуем строку в объект datetime
    save_send_time_to_db(user_id, send_time)  # Функция для сохранения времени в базе данных

import sqlite3
from datetime import datetime

# Функция для подключения к базе данных
def get_db_connection():
    conn = sqlite3.connect('animals.db')
    conn.row_factory = sqlite3.Row
    return conn

# ── Функция для сохранения времени рассылки в базе данных ──
def save_send_time_to_db(user_id: int, send_time: datetime):
    with get_db_connection() as conn:
        conn.execute('INSERT OR REPLACE INTO send_times (user_id, send_time) VALUES (?, ?)', (user_id, send_time))

# ── Функция для получения времени рассылки из базы данных ──
def get_send_time_from_db(user_id: int):
    with get_db_connection() as conn:
        result = conn.execute("SELECT send_time FROM send_times WHERE user_id = ?", (user_id,)).fetchone()
        return datetime.strptime(result['send_time'], "%Y-%m-%d %H:%M:%S") if result else None

# ── Функция для обновления настроек пользователя (время рассылки и количество сообщений) ──
def update_user_send_settings(user_id: int, send_time: str, message_count: int):
    """Обновляет настройки рассылки для пользователя (время и количество сообщений)."""
    with get_db_connection() as conn:
        send_time_obj = datetime.strptime(send_time, "%H:%M")  # Преобразуем строку в объект datetime
        conn.execute('''INSERT OR REPLACE INTO users (user_id, send_time, message_count)
                        VALUES (?, ?, ?)''',
                     (user_id, send_time_obj, message_count))

# ── Функция для получения настроек пользователя (время рассылки и количество сообщений) ──
def get_user_send_settings(user_id: int):
    """Получает настройки рассылки для пользователя: время и количество сообщений в день."""
    with get_db_connection() as conn:
        result = conn.execute('SELECT send_time, message_count FROM users WHERE user_id = ?', (user_id,)).fetchone()
        if result:
            send_time = datetime.strptime(result['send_time'], "%Y-%m-%d %H:%M:%S").strftime("%H:%M")
            return send_time, result['message_count']
        return None, None


def update_user_send_settings(user_id: int, send_time: str, message_count: int):
    """Обновляет настройки рассылки для пользователя (время и количество сообщений)."""
    with get_db_connection() as conn:
        if send_time:
            send_time_obj = datetime.strptime(send_time, "%H:%M")  # Преобразуем строку в объект datetime
        else:
            send_time_obj = None
        conn.execute('''INSERT OR REPLACE INTO users (user_id, send_time, message_count)
                        VALUES (?, ?, ?)''',
                     (user_id, send_time_obj, message_count))


def get_user_send_settings(user_id: int):
    """Получает настройки рассылки для пользователя: время и количество сообщений в день."""
    with get_db_connection() as conn:
        result = conn.execute('SELECT send_time, message_count FROM users WHERE user_id = ?', (user_id,)).fetchone()
        if result:
            send_time = datetime.strptime(result['send_time'], "%Y-%m-%d %H:%M:%S").strftime("%H:%M") if result['send_time'] else None
            return send_time, result['message_count']
        return None, None


def get_send_time_from_db(user_id: int):
    with get_db_connection() as conn:
        result = conn.execute("SELECT send_time FROM send_times WHERE user_id = ?", (user_id,)).fetchone()
        if result:
            return datetime.strptime(result['send_time'], "%Y-%m-%d %H:%M:%S").strftime("%H:%M")
        return None

def reset_send_settings(user_id: int):
    """Сбрасывает настройки рассылки пользователя на дефолтные значения."""
    default_time = "00:00"  # По умолчанию время рассылки 00:00
    default_frequency = 1  # По умолчанию частота 1 сообщение в день

    # Обновляем настройки в базе данных
    with get_db_connection() as conn:
        conn.execute('''
            INSERT OR REPLACE INTO users (user_id, send_time, message_count)
            VALUES (?, ?, ?)
        ''', (user_id, default_time, default_frequency))


# Инициализация базы данных (для примера, можно использовать SQLAlchemy или другой ORM)
def get_db():
    conn = sqlite3.connect('animals.db')
    return conn

# Получение текущих настроек пользователя (время рассылки, частота)
def get_user_send_settings(user_id: int):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT send_time, message_count FROM users WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    conn.close()
    if result:
        return result
    else:
        # Вернем значения по умолчанию, если пользователь не найден
        return ("00:00", 1)

# Обновление настроек пользователя (время рассылки, частота)
async def update_user_send_settings(user_id: int, send_time: str, message_count: int):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT OR REPLACE INTO users (user_id, send_time, message_count) VALUES (?, ?, ?)",
        (user_id, send_time, message_count)
    )
    conn.commit()
    conn.close()

def delete_duplicates():
    with get_db_connection() as conn:
        conn.execute('''
            DELETE FROM animals
            WHERE id NOT IN (
                SELECT id FROM (
                    SELECT MIN(id) AS id
                    FROM animals
                    GROUP BY name, type, age, color, photo_url, contact, source
                )
            );
        ''')
