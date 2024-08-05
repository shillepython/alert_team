import aiogram
import aiosqlite
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from aiogram import Bot, Dispatcher, types
from aiogram.contrib.middlewares.logging import LoggingMiddleware
from aiogram.utils import executor
from aiogram.dispatcher import FSMContext
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery
from datetime import datetime

API_TOKEN = '7037813515:AAGOQxlALQBuNmOn3KxvM3r1q78Nd6D9Ews'
CHAT_ID = '-1001996234864'

# API_TOKEN = '6994376547:AAESH4_TogYWVB5dldZCbZ6ThMefkXJVfKk'
# CHAT_ID = '-4273210541'

# Initialize bot and dispatcher
bot = Bot(token=API_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(bot, storage=storage)
dp.middleware.setup(LoggingMiddleware())

# Allowed user IDs for admin commands
ALLOWED_USER_IDS = [6385046213, 7259097535]

ITEMS_PER_PAGE = 12

# Google Sheets setup
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds = ServiceAccountCredentials.from_json_keyfile_name("credentials.json", scope)
client = gspread.authorize(creds)
sheet = client.open("AlertTeam").worksheet("доход")

# Database initialization
async def init_db():
    async with aiosqlite.connect('database.db') as db:
        await db.execute('''
            CREATE TABLE IF NOT EXISTS cards (
                id INTEGER PRIMARY KEY,
                card TEXT NOT NULL,
                card_name TEXT NOT NULL,
                bank_name TEXT NOT NULL
            )
        ''')
        await db.execute('''
            CREATE TABLE IF NOT EXISTS earnings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL,
                total_amount REAL NOT NULL,
                user_amount REAL NOT NULL,
                date TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'не выплачено'
            )
        ''')
        await db.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER NOT NULL,
                username TEXT NOT NULL,
                usdt_wallet TEXT NOT NULL,
                experience TEXT,
                max_amount REAL,
                proof_image TEXT,
                is_approve BOOLEAN NOT NULL DEFAULT FALSE
            )
        ''')
        await db.commit()

# States for registration
class Register(StatesGroup):
    username = State()
    usdt_wallet = State()
    experience = State()
    max_amount = State()
    proof_image = State()

class AddEarning(StatesGroup):
    search = State()
    amount = State()

@dp.message_handler(content_types=types.ContentType.NEW_CHAT_MEMBERS)
async def welcome_new_member(message: types.Message):
    for new_member in message.new_chat_members:
        if new_member.username:
            link = f"[{new_member.first_name}](https://t.me/{new_member.username})"
        else:
            link = new_member.first_name

        keyboard = InlineKeyboardMarkup()
        button1 = InlineKeyboardButton(text="ТС (Напиши для начала работы)", url='https://t.me/moneyimperiaa')
        keyboard.add(button1)
        await message.answer(f"Добро пожаловать, {link}!\nТы можешь ознакомиться с информацией в первом закреплённом сообщение, там есть всё для начала твоей работы.", parse_mode=types.ParseMode.MARKDOWN, reply_markup=keyboard)

@dp.message_handler(commands=['get_chat_id'])
async def get_chat_id(message: types.Message):
    chat_id = message.chat.id
    await message.reply(f"Chat ID: {chat_id}")

@dp.message_handler(state=AddEarning.search)
async def process_search(message: types.Message, state: FSMContext):
    query = message.text
    data = await state.get_data()
    original_message_id = data.get("original_message_id")

    await state.update_data(query=query)
    await state.finish()
    await bot.delete_message(message.chat.id, message.message_id)

    if original_message_id:
        await send_user_selection_keyboard(message, query=query, edit_message=True, message_id=original_message_id)

@dp.message_handler(state=AddEarning.amount)
async def process_amount(message: types.Message, state: FSMContext):
    amount = message.text
    if not amount.replace('.', '', 1).isdigit():
        await message.reply("Пожалуйста, введите корректную сумму.")
        return

    total_amount = float(amount)
    user_amount = total_amount * 0.5
    data = await state.get_data()
    username = data['username']
    date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    status = "не выплачено"

    async with aiosqlite.connect('database.db') as db:
        cursor = await db.execute('INSERT INTO earnings (username, total_amount, user_amount, date, status) VALUES (?, ?, ?, ?, ?)', (username, total_amount, user_amount, date, status))
        transaction_id = cursor.lastrowid
        await db.commit()

    sheet.append_row([transaction_id, username, total_amount, user_amount, date, status])
    await message.reply(f"Сумма {total_amount} добавлена для пользователя {username} за {date}. Статус: {status}.")

    await bot.send_message(
        CHAT_ID,
        f"🎉Успешный перевод!\n💪Воркер: #{username}\n💰Сумма перевода: {total_amount}\n🤑Доля спортсмена: {user_amount}"
    )

    await state.finish()


async def is_registered(user_id):
    async with aiosqlite.connect('database.db') as db:
        async with db.execute('SELECT * FROM users WHERE telegram_id = ?', (user_id,)) as cursor:
            user = await cursor.fetchone()
            return user is not None

async def is_approved_user(user_id):
    async with aiosqlite.connect('database.db') as db:
        async with db.execute('SELECT is_approve FROM users WHERE telegram_id = ?', (user_id,)) as cursor:
            user = await cursor.fetchone()
            return user is not None and user[0]

async def send_stats_keyboard(message: types.Message, is_admin: bool):
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True)
    keyboard.add(types.KeyboardButton("ℹ️ Статистика"), types.KeyboardButton("💸 Доход за сегодня"))
    keyboard.add(types.KeyboardButton("💳 Карта"))
    if is_admin:
        keyboard.add(types.KeyboardButton("/setcard"), types.KeyboardButton("/addearn"))
        keyboard.add(types.KeyboardButton("/unpaid"), types.KeyboardButton("/approve"))
    await message.reply("Выберите команду:", reply_markup=keyboard)

# Start command with keyboard
@dp.message_handler(commands=['start'])
async def start(message: types.Message):
    user_id = message.from_user.id
    if not await is_registered(user_id):
        await message.reply(
            "Добро пожаловать в AlertTeam!\n\n"
            "Этот бот создан для выплат, статистики и удобной работы в нашей команде.\n\n"
            "Для начала регистрации укажите какой у вас опыт работы:"
        )
        await Register.experience.set()
    elif not await is_approved_user(user_id):
        await message.reply(
            "Добро пожаловать в AlertTeam!\n\n"
            "Ваш аккаунт находится на стадии проверки, пожалуйста ожидайте решения админа\n"
        )
    else:
        await message.reply(
            "Рады видеть вас снова!\n\n"
            "Этот бот создан для выплат, статистики и удобной работы в нашей команде.\n"
            "Пожалуйста, выберите команду на клавиатуре ниже."
        )
        await send_stats_keyboard(message, user_id in ALLOWED_USER_IDS)

@dp.message_handler(state=Register.experience)
async def process_experience(message: types.Message, state: FSMContext):
    experience = message.text
    await state.update_data(experience=experience)
    await message.reply("Какие суммы вы заводили максимально?")
    await Register.max_amount.set()

@dp.message_handler(state=Register.max_amount)
async def process_max_amount(message: types.Message, state: FSMContext):
    max_amount = message.text
    if not max_amount.replace('.', '', 1).isdigit():
        await message.reply("Пожалуйста, введите корректную сумму.")
        return

    await state.update_data(max_amount=float(max_amount))
    await message.reply("Введите ваш ник:")
    await Register.username.set()

@dp.message_handler(state=Register.username)
async def process_username(message: types.Message, state: FSMContext):
    username = message.text
    async with aiosqlite.connect('database.db') as db:
        async with db.execute('SELECT * FROM users WHERE username = ?', (username,)) as cursor:
            user = await cursor.fetchone()
            if user:
                await message.reply("Этот ник уже занят, пожалуйста, выберите другой ник:")
                return

    await state.update_data(username=username)
    await message.reply("Введите ваш USDT кошелек (TRC20) для выплат:")
    await Register.usdt_wallet.set()

@dp.message_handler(state=Register.usdt_wallet)
async def process_usdt_wallet(message: types.Message, state: FSMContext):
    usdt_wallet = message.text
    await state.update_data(usdt_wallet=usdt_wallet)
    await message.reply("Загрузите картинку доказательств работы (в сжатом формате):")
    await Register.proof_image.set()

@dp.message_handler(content_types=['photo'], state=Register.proof_image)
async def process_proof_image(message: types.Message, state: FSMContext):
    photo = message.photo[-1]
    photo_path = f'photos/{photo.file_id}.jpg'
    await photo.download(photo_path)

    user_data = await state.get_data()
    async with aiosqlite.connect('database.db') as db:
        await db.execute('''
            INSERT INTO users (telegram_id, username, usdt_wallet, experience, max_amount, proof_image, is_approve)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (message.from_user.id, user_data['username'], user_data['usdt_wallet'], user_data['experience'], user_data['max_amount'], photo_path, False))
        await db.commit()

    await state.finish()
    await message.reply("Вы успешно зарегистрированы! Ожидайте подтверждения от администратора.")
    await send_stats_keyboard(message, message.from_user.id in ALLOWED_USER_IDS)

# /card command
@dp.message_handler(lambda message: message.text.startswith('💳 Карта') or message.text.startswith('/card'))
async def get_card(message: types.Message):
    if not await is_registered(message.from_user.id):
        await message.reply("Вы не зарегистрированы. Пожалуйста, используйте команду /start для регистрации.")
        return
    if not await is_approved_user(message.from_user.id):
        await message.reply("Ваш запрос на вступление в команду находится на рассмотрении, пожалуйста ожидайте.")
        return

    async with aiosqlite.connect('database.db') as db:
        async with db.execute('SELECT card_name, card, bank_name FROM cards ORDER BY id DESC LIMIT 1') as cursor:
            row = await cursor.fetchone()
            if row:
                card_name, card, bank_name = row
                await message.reply(f'''💳 Карты для переводов

🇷🇺{card}
├ От 100
├ {card_name}
└ {bank_name}

⚠️ Осторожно, вам может написать фейк, актуальные реквизиты указаны исключительно в этом сообщении. Будьте внимательны и отправляйте чеки в лс @papa_payments''',
                                    parse_mode=types.ParseMode.HTML)
            else:
                await message.reply("Карта не установлена")

# /setcard command
@dp.message_handler(commands=['setcard'])
async def set_card(message: types.Message):
    if not await is_registered(message.from_user.id):
        await message.reply("Вы не зарегистрированы. Пожалуйста, используйте команду /start для регистрации.")
        return
    if not await is_approved_user(message.from_user.id):
        await message.reply("Ваш запрос на вступление в команду находится на рассмотрении, пожалуйста ожидайте.")
        return

    user_id = message.from_user.id
    if user_id in ALLOWED_USER_IDS:
        args = message.get_args().split(maxsplit=2)
        if len(args) == 3:
            card_name, card, bank_name = args
            async with aiosqlite.connect('database.db') as db:
                await db.execute('INSERT INTO cards (card_name, card, bank_name) VALUES (?, ?, ?)', (card_name, card, bank_name))
                await db.commit()
            await message.reply(f"Карта обновлена на: {card_name} - {card} - {bank_name}")

            async with db.execute('SELECT card_name, card, bank_name FROM cards ORDER BY id DESC LIMIT 1') as cursor:
                row = await cursor.fetchone()
                card_name, card, bank_name = row
            await bot.send_message(CHAT_ID, f'''⚠️Карта обновлена⚠️
💳 Карты для переводов

🇷🇺{card}
├ От 100
├ {card_name}
└ {bank_name}

    ⚠️ Осторожно, вам может написать фейк, актуальные реквизиты указаны исключительно в этом сообщении. Будьте внимательны и отправляйте чеки в лс @papa_payments''')
        else:
            await message.reply("Пожалуйста введите карту в таком формате. Используйте: /setcard <card_name> <card> <bank_name>")
    else:
        await message.reply("У тебя нет прав чтобы это делать.")

@dp.message_handler(commands=['addearn'])
async def add_earn_start(message: types.Message):
    if not await is_registered(message.from_user.id):
        await message.reply("Вы не зарегистрированы. Пожалуйста, используйте команду /start для регистрации.")
        return
    if not await is_approved_user(message.from_user.id):
        await message.reply("Ваш запрос на вступление в команду находится на рассмотрении, пожалуйста ожидайте.")
        return
    await send_user_selection_keyboard(message)


async def send_user_selection_keyboard(message, page=1, query=None, edit_message=False, message_id=None):
    async with aiosqlite.connect('database.db') as db:
        if query:
            cursor = await db.execute("SELECT username FROM users WHERE username LIKE ?", (f"%{query}%",))
        else:
            cursor = await db.execute("SELECT username FROM users LIMIT ? OFFSET ?",
                                      (ITEMS_PER_PAGE, (page - 1) * ITEMS_PER_PAGE))
        users = await cursor.fetchall()
        total_users = await db.execute("SELECT COUNT(*) FROM users")
        total_users = await total_users.fetchone()
        total_pages = (total_users[0] + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE

    keyboard = InlineKeyboardMarkup(row_width=3)
    for user in users:
        keyboard.insert(InlineKeyboardButton(user[0], callback_data=f"select_user_{user[0]}"))

    if page > 1:
        keyboard.row(
            InlineKeyboardButton("⬅️", callback_data=f"prev_page_{page - 1}"),
            InlineKeyboardButton(f"{page}/{total_pages}", callback_data="noop"),
            InlineKeyboardButton("➡️", callback_data=f"next_page_{page + 1 if page < total_pages else 1}")
        )
    else:
        keyboard.row(
            InlineKeyboardButton(" ", callback_data="noop"),  # Пустая кнопка для выравнивания
            InlineKeyboardButton(f"{page}/{total_pages}", callback_data="noop"),
            InlineKeyboardButton("➡️", callback_data=f"next_page_{page + 1 if page < total_pages else 1}")
        )

    keyboard.row(
        InlineKeyboardButton("Поиск по нику", callback_data="search_user"),
        InlineKeyboardButton("Отмена", callback_data="cancel")
    )

    if edit_message and message_id:
        try:
            await bot.edit_message_text("Выберите пользователя:", chat_id=message.chat.id, message_id=message_id,
                                        reply_markup=keyboard)
        except aiogram.utils.exceptions.MessageNotModified:
            pass  # Игнорируем ошибку, если сообщение не изменилось
        state = dp.current_state(user=message.from_user.id)
        await state.update_data(page=page, query=query, original_message_id=message_id)
    else:
        msg = await message.reply("Выберите пользователя:", reply_markup=keyboard)
        state = dp.current_state(user=message.from_user.id)
        await state.update_data(original_message_id=msg.message_id, query=query)


@dp.callback_query_handler(lambda c: c.data.startswith('prev_page_') or c.data.startswith('next_page_'))
async def change_page(callback_query: CallbackQuery):
    await bot.answer_callback_query(callback_query.id)
    page = int(callback_query.data.split('_')[2])
    state = dp.current_state(user=callback_query.from_user.id)
    data = await state.get_data()
    original_message_id = data.get("original_message_id")
    query = data.get("query", None)
    await send_user_selection_keyboard(callback_query.message, page, query=query, edit_message=True, message_id=original_message_id)


@dp.callback_query_handler(lambda c: c.data.startswith('prev_page_') or c.data.startswith('next_page_'))
async def change_page(callback_query: CallbackQuery):
    await bot.answer_callback_query(callback_query.id)
    page = int(callback_query.data.split('_')[2])
    state = dp.current_state(user=callback_query.from_user.id)
    data = await state.get_data()
    original_message_id = data.get("original_message_id")
    query = data.get("query", None)
    await send_user_selection_keyboard(callback_query.message, page, query=query, edit_message=True, message_id=original_message_id)

@dp.callback_query_handler(lambda c: c.data == 'search_user')
async def search_user(callback_query: CallbackQuery):
    await bot.answer_callback_query(callback_query.id)
    state = dp.current_state(user=callback_query.from_user.id)
    await state.update_data(original_message_id=callback_query.message.message_id)
    await bot.send_message(callback_query.from_user.id, "Введите ник для поиска:")
    await AddEarning.search.set()

@dp.callback_query_handler(lambda c: c.data.startswith('select_user_'))
async def process_user_selection(callback_query: CallbackQuery):
    await bot.answer_callback_query(callback_query.id)
    username = callback_query.data.split('_')[2]
    await bot.send_message(callback_query.from_user.id, f"Вы выбрали пользователя {username}. Введите сумму:")
    await AddEarning.amount.set()
    state = dp.current_state(user=callback_query.from_user.id)
    await state.update_data(username=username)


@dp.callback_query_handler(lambda c: c.data == 'cancel')
async def cancel(callback_query: CallbackQuery):
    await bot.answer_callback_query(callback_query.id, "Действие отменено", show_alert=True)
    state = dp.current_state(user=callback_query.from_user.id)
    data = await state.get_data()
    original_message_id = data.get("original_message_id")
    await bot.delete_message(callback_query.message.chat.id, original_message_id)


# /todayearnings command
@dp.message_handler(lambda message: message.text.startswith('💸 Доход за сегодня')  or message.text.startswith('/todayearnings'))
async def today_earnings(message: types.Message):
    if not await is_registered(message.from_user.id):
        await message.reply("Вы не зарегистрированы. Пожалуйста, используйте команду /start для регистрации.")
        return
    if not await is_approved_user(message.from_user.id):
        await message.reply("Ваш запрос на вступление в команду находится на рассмотрении, пожалуйста ожидайте.")
        return

    today = datetime.now().strftime("%Y-%m-%d")
    async with aiosqlite.connect('database.db') as db:
        async with db.execute('SELECT SUM(total_amount) FROM earnings WHERE date LIKE ?', (f'{today}%',)) as cursor:
            row = await cursor.fetchone()
            total = row[0] if row[0] is not None else 0
            await message.reply(f"Общая сумма заработанная за сегодня: {total:.2f}")

# /stats command
@dp.message_handler(lambda message: message.text.startswith('ℹ️ Статистика'))
async def stats(message: types.Message):
    if not await is_registered(message.from_user.id):
        await message.reply("Вы не зарегистрированы. Пожалуйста, используйте команду /start для регистрации.")
        return
    if not await is_approved_user(message.from_user.id):
        await message.reply("Ваш запрос на вступление в команду находится на рассмотрении, пожалуйста ожидайте.")
        return

    async with aiosqlite.connect('database.db') as db:
        async with db.execute('SELECT SUM(total_amount) FROM earnings WHERE username = (SELECT username FROM users WHERE telegram_id = ?)', (message.from_user.id,)) as cursor:
            row = await cursor.fetchone()
            total_earnings = row[0] if row[0] is not None else 0

        today = datetime.now().strftime("%Y-%m-%d")
        async with db.execute('SELECT SUM(user_amount) FROM earnings WHERE date LIKE ? AND username = (SELECT username FROM users WHERE telegram_id = ?)', (f'{today}%', message.from_user.id)) as cursor:
            row = await cursor.fetchone()
            today_earnings = row[0] if row[0] is not None else 0

        async with db.execute('SELECT SUM(total_amount) FROM earnings WHERE date LIKE ? AND username = (SELECT username FROM users WHERE telegram_id = ?)', (f'{today}%', message.from_user.id)) as cursor:
            row = await cursor.fetchone()
            today_total_earnings = row[0] if row[0] is not None else 0

        async with db.execute('SELECT SUM(user_amount) FROM earnings WHERE username = (SELECT username FROM users WHERE telegram_id = ?) AND user_amount > 0 AND status = "не выплачено"', (message.from_user.id,)) as cursor:
            row = await cursor.fetchone()
            total_unpaid = row[0] if row[0] is not None else 0

        await message.reply(f"📊 Ваша статистика:\n"
                            f"🤑 Общая сумма профитов за все время: {total_earnings:.2f}\n"
                            f"💵 Общая сумма профитов за сегодня: {today_total_earnings:.2f}\n\n"
                            f"💰 Твой доход за сегодня: {today_earnings:.2f}\n"
                            f"💸 Сумма, что не выплачена: {total_unpaid:.2f}\n\n"
                            f"ℹ️ Выплаты производят админы в порядке очереди, бот вас оповестит как произойдёт выплата.")

# /unpaid command for admin
@dp.message_handler(commands=['unpaid'])
async def unpaid(message: types.Message):
    user_id = message.from_user.id
    if user_id in ALLOWED_USER_IDS:
        async with aiosqlite.connect('database.db') as db:
            async with db.execute('''
                SELECT e.id, u.username, u.usdt_wallet, SUM(e.total_amount) as total_unpaid, SUM(e.user_amount) as user_unpaid
                FROM earnings e
                JOIN users u ON e.username = u.username
                WHERE e.status = "не выплачено"
                GROUP BY u.username, u.usdt_wallet, e.id
            ''') as cursor:
                rows = await cursor.fetchall()
                for row in rows:
                    transaction_id, username, wallet, total_unpaid, user_unpaid = row
                    keyboard = InlineKeyboardMarkup().add(InlineKeyboardButton('Выплачено', callback_data=f'paid_{transaction_id}'))
                    await message.reply(f"👤 {username}\n💰 Доля воркера: {user_unpaid:.2f}\n💼 Кошелек: `{wallet}`", reply_markup=keyboard, parse_mode=types.ParseMode.MARKDOWN)
    else:
        await message.reply("У тебя нет прав чтобы это делать.")

# Callback query handler for marking as paid
@dp.callback_query_handler(lambda c: c.data.startswith('paid_'))
async def process_callback_paid(callback_query: CallbackQuery):
    transaction_id = int(callback_query.data.split('_')[1])
    new_status = "выплачено"

    async with aiosqlite.connect('database.db') as db:
        await db.execute('UPDATE earnings SET status = ? WHERE id = ?', (new_status, transaction_id))
        await db.commit()

        async with db.execute('''
            SELECT e.username, u.telegram_id, u.usdt_wallet, e.user_amount
            FROM earnings e
            JOIN users u ON e.username = u.username
            WHERE e.id = ?
        ''', (transaction_id,)) as cursor:
            row = await cursor.fetchone()
            if row:
                username, telegram_id, usdt_wallet, user_amount = row

    sheet_data = sheet.get_all_records()
    for i, row in enumerate(sheet_data):
        if row['id'] == transaction_id:
            sheet.update_cell(i + 2, 6, new_status)  # Обновляем статус в 6-й колонке (на основе структуры данных)

    if telegram_id:
        await bot.send_message(telegram_id, f"Произведена оплата суммы {user_amount:.2f} на ваш кошелек:\n`{usdt_wallet}`", parse_mode=types.ParseMode.MARKDOWN)

    await bot.answer_callback_query(callback_query.id, text="Статус обновлен на 'выплачено'")
    await bot.edit_message_reply_markup(callback_query.message.chat.id, callback_query.message.message_id, reply_markup=None)

@dp.message_handler(commands=['approve'])
async def approve(message: types.Message):
    user_id = message.from_user.id
    if user_id in ALLOWED_USER_IDS:
        async with aiosqlite.connect('database.db') as db:
            async with db.execute('SELECT * FROM users WHERE is_approve = FALSE') as cursor:
                rows = await cursor.fetchall()
                if not rows:
                    await message.reply("Нет новых регистраций для одобрения.")
                    return
                for row in rows:
                    (user_id, telegram_id, username, usdt_wallet, experience, max_amount, proof_image, is_approve) = row
                    keyboard = InlineKeyboardMarkup().add(
                        InlineKeyboardButton('Одобрить', callback_data=f'approve_{user_id}'),
                        InlineKeyboardButton('Отклонить', callback_data=f'reject_{user_id}')
                    )
                    await message.reply_photo(
                        photo=open(proof_image, 'rb'),
                        caption=f"👤 Ник: {username}\n💼 Кошелек: {usdt_wallet}\n📈 Опыт: {experience}\n💰 Макс. сумма: {max_amount}",
                        reply_markup=keyboard
                    )
    else:
        await message.reply("У тебя нет прав чтобы это делать.")

@dp.callback_query_handler(lambda c: c.data.startswith('approve_'))
async def process_approve(callback_query: CallbackQuery):
    user_id = int(callback_query.data.split('_')[1])

    async with aiosqlite.connect('database.db') as db:
        await db.execute('UPDATE users SET is_approve = TRUE WHERE id = ?', (user_id,))
        await db.commit()

        async with db.execute('SELECT telegram_id FROM users WHERE id = ?', (user_id,)) as cursor:
            row = await cursor.fetchone()
            if row:
                telegram_id = row[0]
                await bot.send_message(telegram_id, "Ваша регистрация была одобрена. Теперь вы можете использовать все функции бота.")

    await bot.answer_callback_query(callback_query.id, text="Регистрация одобрена")
    await bot.delete_message(callback_query.message.chat.id, callback_query.message.message_id)

@dp.callback_query_handler(lambda c: c.data.startswith('reject_'))
async def process_reject(callback_query: CallbackQuery):
    user_id = int(callback_query.data.split('_')[1])

    async with aiosqlite.connect('database.db') as db:
        async with db.execute('SELECT telegram_id FROM users WHERE id = ?', (user_id,)) as cursor:
            row = await cursor.fetchone()
            if row:
                telegram_id = row[0]
                await bot.send_message(telegram_id, "Ваша регистрация была отклонена. Пожалуйста, свяжитесь с администратором для получения подробностей.")

        await db.execute('DELETE FROM users WHERE id = ?', (user_id,))
        await db.commit()

    await bot.answer_callback_query(callback_query.id, text="Регистрация отклонена")
    await bot.delete_message(callback_query.message.chat.id, callback_query.message.message_id)

if __name__ == '__main__':
    import asyncio
    loop = asyncio.get_event_loop()
    loop.run_until_complete(init_db())
    executor.start_polling(dp, skip_updates=True)
