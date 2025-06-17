import asyncio
import nest_asyncio
nest_asyncio.apply()
from datetime import datetime
import time
import logging
from telegram.ext import Application, CommandHandler, ContextTypes
from telegram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import json
import os
import re
import sys
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from telegram import Update
from selenium.webdriver.common.keys import Keys
import unicodedata

# Настройки
TELEGRAM_TOKEN = '7910393346:AAGtPOQasri0UUx06l6myfT-Fa-JVOGbx8Q'
MAIN_CHAT_ID = '5608366073'
SHAI_AGENT_URL = 'https://shai.pro/chat/oleIPg93IvfDaLfc' 
USERS_FILE = 'users.json'

# Исправление кодировки Windows
if sys.platform.startswith('win'):
    os.environ['PYTHONIOENCODING'] = 'utf-8'
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')

# Логирование
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
)
logger = logging.getLogger(__name__)

# Глобальные переменные
last_digest = None
last_digest_date = None

def load_users():
    """Загружает список пользователей из файла"""
    if os.path.exists(USERS_FILE):
        try:
            with open(USERS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Ошибка загрузки пользователей: {e}")
            return {}
    return {}

def save_users(users):
    """Сохраняет список пользователей в файл"""
    try:
        with open(USERS_FILE, 'w', encoding='utf-8') as f:
            json.dump(users, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Ошибка сохранения пользователей: {e}")

def clean_digest_from_analytics(content):
    """Удаляет аналитические секции из дайджеста"""
    
    # Паттерны для удаления аналитических блоков
    analytical_patterns = [
        r'Рыночные тренды.*?(?=\n\n|\n[А-Я]|\n\d+\.|\Z)',
        r'Возможности и риски.*?(?=\n\n|\n[А-Я]|\n\d+\.|\Z)',
        r'Популяризация.*?(?=\n\n|\n[А-Я]|\n\d+\.|\Z)',
        r'Растущая роль.*?(?=\n\n|\n[А-Я]|\n\d+\.|\Z)',
        r'Фокус на клиентский.*?(?=\n\n|\n[А-Я]|\n\d+\.|\Z)',
        r'Потребность в гибкости.*?(?=\n\n|\n[А-Я]|\n\d+\.|\Z)',
        r'Возможности:.*?(?=\n\n|\n[А-Я]|\n\d+\.|\Z)',
        r'Риски:.*?(?=\n\n|\n[А-Я]|\n\d+\.|\Z)',
        r'Влияние на рынок.*?(?=\n\n|\n[А-Я]|\n\d+\.|\Z)',
        r'Аналитический обзор.*?(?=\n\n|\n[А-Я]|\n\d+\.|\Z)',
        r'Выводы:.*?(?=\n\n|\n[А-Я]|\n\d+\.|\Z)',
        r'Тенденции:.*?(?=\n\n|\n[А-Я]|\n\d+\.|\Z)'
    ]
    
    cleaned_content = content
    
    for pattern in analytical_patterns:
        cleaned_content = re.sub(pattern, '', cleaned_content, flags=re.DOTALL | re.IGNORECASE)
    
    # Убираем множественные переносы строк
    cleaned_content = re.sub(r'\n{3,}', '\n\n', cleaned_content)
    
    # Убираем пустые строки в начале и конце
    cleaned_content = cleaned_content.strip()
    
    return cleaned_content

def clean_text_for_selenium(text):
    """Очищает текст от символов, которые не поддерживает ChromeDriver"""
    # Убираем эмоджи и символы за пределами BMP
    cleaned = ''.join(char for char in text if ord(char) < 65536)
    
    # Нормализуем Unicode
    cleaned = unicodedata.normalize('NFKC', cleaned)
    
    # Убираем управляющие символы кроме переносов строк и табуляции
    cleaned = ''.join(char for char in cleaned if unicodedata.category(char)[0] != 'C' or char in '\n\t\r')
    
    return cleaned

def get_ai_digest_from_shai():
    """Получает AI дайджест от SHAI с улучшенной обработкой ошибок"""
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-logging")
    options.add_argument("--log-level=3")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option('useAutomationExtension', False)
    options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    # Добавляем поддержку UTF-8
    options.add_argument("--lang=en-US")
    options.add_argument("--disable-features=VizDisplayCompositor")

    driver = webdriver.Chrome(options=options)
    driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

    try:
        logger.info("Подключение к SHAI...")
        driver.get(SHAI_AGENT_URL)
        
        # Ждем загрузки страницы
        WebDriverWait(driver, 30).until(
            lambda d: d.execute_script("return document.readyState") == "complete"
        )
        
        # Пробуем найти текстовое поле различными способами
        input_selectors = [
            "div.absolute.bottom-0 textarea",
            "textarea",
            "input[type='text']",
            "div[contenteditable='true']",
            "[placeholder*='message']",
            "[placeholder*='Type']",
            ".chat-input textarea",
            ".input-box textarea"
        ]
        
        input_box = None
        for selector in input_selectors:
            try:
                input_box = WebDriverWait(driver, 5).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, selector))
                )
                logger.info(f"Найдено поле ввода с селектором: {selector}")
                break
            except:
                continue
        
        if not input_box:
            logger.error("Не удалось найти поле ввода")
            return None

        # Получаем текущую дату для промпта
        current_date = datetime.now().strftime("%d %B %Y")
        
        # Создаем промпт БЕЗ эмоджи и специальных символов
        prompt = (
            f"Найди конкретные новости и обновления в сфере ИИ за {current_date} года. "
            f"ВАЖНО: Нужны только ФАКТИЧЕСКИЕ новости без аналитики и прогнозов!\n\n"
            f"Темы для поиска:\n"
            f"- Релизы и обновления AI фреймворков (CrewAI, AutoGen, LangGraph, LangChain)\n"
            f"- Анонсы и релизы от OpenAI, Anthropic, Google AI, Microsoft\n"
            f"- Новые GitHub репозитории и релизы (звезды 100+)\n"
            f"- Конкретные AI продукты и стартапы\n"
            f"- Технические обновления и багфиксы\n\n"
            f"Формат ответа:\n"
            f"Для каждой новости:\n"
            f"Название: [название новости]\n"
            f"Дата: [дата]\n"
            f"Компания: [название]\n"
            f"Описание: [краткое описание ТОЛЬКО фактов]\n"
            f"Ссылка: [если есть]\n"
            f"---\n\n"
            f"НЕ ДОБАВЛЯЙ:\n"
            f"- Анализ рыночных трендов\n"
            f"- Прогнозы и предположения\n"
            f"- Выводы о влиянии на рынок\n"
            f"- Аналитические заключения\n"
            f"- Только конкретные факты и новости!"
        )
        
        # Очищаем промпт от проблемных символов
        clean_prompt = clean_text_for_selenium(prompt)
        
        logger.info("Отправка запроса в SHAI...")
        
        # Очищаем поле и вводим текст по частям
        input_box.clear()
        input_box.click()
        
        # Разбиваем текст на части для более надежной отправки
        chunk_size = 500
        for i in range(0, len(clean_prompt), chunk_size):
            chunk = clean_prompt[i:i+chunk_size]
            try:
                input_box.send_keys(chunk)
                time.sleep(0.1)  # Небольшая задержка между частями
            except Exception as e:
                logger.error(f"Ошибка отправки части текста: {e}")
                # Пробуем отправить через JavaScript
                driver.execute_script("arguments[0].value = arguments[1];", input_box, clean_prompt)
                break
        
        # Отправляем сообщение
        try:
            input_box.send_keys(Keys.ENTER)
        except Exception as e:
            logger.warning(f"Ошибка с Enter: {e}, пробуем кнопку отправки")
            # Если Enter не работает, ищем кнопку отправки
            send_buttons = [
                "button[type='submit']",
                "button:contains('Send')",
                "button:contains('Отправить')",
                ".send-button",
                "[aria-label*='send']"
            ]
            
            sent = False
            for btn_selector in send_buttons:
                try:
                    send_btn = driver.find_element(By.CSS_SELECTOR, btn_selector)
                    send_btn.click()
                    sent = True
                    break
                except:
                    continue
            
            if not sent:
                # Последняя попытка через JavaScript
                try:
                    driver.execute_script("arguments[0].form.submit();", input_box)
                except:
                    logger.error("Не удалось отправить сообщение")
                    return None

        logger.info("Ожидание ответа (45 секунд)...")
        time.sleep(45)

        # Пробуем различные селекторы для получения ответа
        answer_selectors = [
            "div.chat-answer-container div.group.relative.pr-10 div > div:nth-child(3) > div:nth-child(2) > div",
            ".chat-message:last-child",
            ".message:last-child",
            ".response:last-child",
            "[class*='message']:last-child",
            "[class*='response']:last-child",
            "[class*='chat']:last-child",
            "div:contains('AI')",
            "div[class*='answer']",
            "div[class*='response']"
        ]
        
        response_text = None
        for selector in answer_selectors:
            try:
                elements = driver.find_elements(By.CSS_SELECTOR, selector)
                if elements:
                    # Берем последний элемент
                    latest_element = elements[-1]
                    text = latest_element.text.strip()
                    if text and len(text) > 50:  # Минимальная длина ответа
                        response_text = text
                        logger.info(f"Найден ответ с селектором: {selector}")
                        break
            except Exception as e:
                logger.debug(f"Ошибка с селектором {selector}: {e}")
                continue
        
        if not response_text:
            # Последняя попытка - получить весь текст страницы и найти ответ
            try:
                page_text = driver.find_element(By.TAG_NAME, "body").text
                # Ищем текст после нашего промпта
                if "Найди конкретные новости" in page_text:
                    parts = page_text.split("Найди конкретные новости")
                    if len(parts) > 1:
                        potential_response = parts[-1].strip()
                        if len(potential_response) > 100:
                            response_text = potential_response[:3000]  # Ограничиваем длину
                            logger.info("Ответ найден в тексте страницы")
            except Exception as e:
                logger.error(f"Ошибка поиска в тексте страницы: {e}")
        
        if response_text:
            # Очищаем ответ от аналитики
            response_text = clean_digest_from_analytics(response_text)
            
            logger.info(f"Получен и очищен ответ ({len(response_text)} символов)")
            return response_text
        else:
            logger.warning("Ответ не найден ни одним способом")
            
            # Сохраняем скриншот для отладки
            try:
                driver.save_screenshot("debug_screenshot.png")
                logger.info("Сохранен скриншот для отладки: debug_screenshot.png")
            except:
                pass
            
            return None

    except Exception as e:
        logger.error(f"Ошибка при работе с SHAI: {e}")
        
        # Сохраняем скриншот при ошибке
        try:
            driver.save_screenshot("error_screenshot.png")
            logger.info("Сохранен скриншот ошибки: error_screenshot.png")
        except:
            pass
        
        return None
    finally:
        driver.quit()

def clean_digest_from_analytics(content):
    """Удаляет аналитические секции из дайджеста"""
    
    # Паттерны для удаления аналитических блоков
    analytical_patterns = [
        r'Рыночные тренды.*?(?=\n\n|\n[А-Я]|\n\d+\.|\Z)',
        r'Возможности и риски.*?(?=\n\n|\n[А-Я]|\n\d+\.|\Z)',
        r'Популяризация.*?(?=\n\n|\n[А-Я]|\n\d+\.|\Z)',
        r'Растущая роль.*?(?=\n\n|\n[А-Я]|\n\d+\.|\Z)',
        r'Фокус на клиентский.*?(?=\n\n|\n[А-Я]|\n\d+\.|\Z)',
        r'Потребность в гибкости.*?(?=\n\n|\n[А-Я]|\n\d+\.|\Z)',
        r'Возможности:.*?(?=\n\n|\n[А-Я]|\n\d+\.|\Z)',
        r'Риски:.*?(?=\n\n|\n[А-Я]|\n\d+\.|\Z)',
        r'Влияние на рынок.*?(?=\n\n|\n[А-Я]|\n\d+\.|\Z)',
        r'Аналитический обзор.*?(?=\n\n|\n[А-Я]|\n\d+\.|\Z)',
        r'Выводы:.*?(?=\n\n|\n[А-Я]|\n\d+\.|\Z)',
        r'Тенденции:.*?(?=\n\n|\n[А-Я]|\n\d+\.|\Z)'
    ]
    
    cleaned_content = content
    
    for pattern in analytical_patterns:
        cleaned_content = re.sub(pattern, '', cleaned_content, flags=re.DOTALL | re.IGNORECASE)
    
    # Убираем множественные переносы строк
    cleaned_content = re.sub(r'\n{3,}', '\n\n', cleaned_content)
    
    # Убираем пустые строки в начале и конце
    cleaned_content = cleaned_content.strip()
    
    return cleaned_content

def get_source_link(source):
    """Получает ссылку на источник"""
    source_links = {
        'GitHub': 'https://github.com',
        'LinkedIn': 'https://linkedin.com',
        'Reddit': 'https://reddit.com',
        'OpenAI': 'https://openai.com',
        'Anthropic': 'https://anthropic.com',
        'Google AI': 'https://ai.google',
        'Microsoft': 'https://microsoft.com'
    }
    return source_links.get(source, None)

def format_digest_for_telegram(content):
    """Форматирует сырой контент от SHAI для красивого отображения в Telegram"""
    if not content:
        return "Дайджест пуст"
    
    lines = content.split('\n')
    formatted_lines = []
    
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        
        if not line:
            i += 1
            continue
            
        # Обрабатываем заголовки новостей
        if line.startswith('Название:'):
            if formatted_lines and formatted_lines[-1] != '':
                formatted_lines.append('')
                formatted_lines.append('━━━━━━━━━━━━━━━━━━━━')
                formatted_lines.append('')
            
            title = line.replace('Название:', '').strip()
            formatted_lines.append(f'📰 <b>{title}</b>')
            
        elif line.startswith('Дата:'):
            date = line.replace('Дата:', '').strip()
            formatted_lines.append(f'📅 <b>Дата:</b> {date}')
            
        elif line.startswith('Компания:'):
            company = line.replace('Компания:', '').strip()
            formatted_lines.append(f'🏢 <b>Компания:</b> {company}')
            
        elif line.startswith('Источник:'):
            source = line.replace('Источник:', '').strip()
            source_link = get_source_link(source)
            if source_link:
                formatted_lines.append(f'🔗 <b>Источник:</b> <a href="{source_link}">{source}</a>')
            else:
                formatted_lines.append(f'🔗 <b>Источник:</b> {source}')
            
        elif line.startswith('Ссылка:'):
            link = line.replace('Ссылка:', '').strip()
            if link and link != 'Подробнее' and link.startswith('http'):
                formatted_lines.append(f'🌐 <b>Ссылка:</b> <a href="{link}">Читать полностью</a>')
            elif link and link != 'Подробнее':
                formatted_lines.append(f'🌐 <b>Ссылка:</b> {link}')
                
        elif line.startswith('Описание:'):
            description = line.replace('Описание:', '').strip()
            formatted_lines.append('')
            formatted_lines.append(f'📝 <b>Описание:</b>')
            formatted_lines.append(f'<i>{description}</i>')
            
        elif line == '---':
            # Пропускаем разделители из промпта
            continue
                
        elif re.match(r'^\d+\.\s+', line):
            if formatted_lines:
                formatted_lines.append('')
                formatted_lines.append('━━━━━━━━━━━━━━━━━━━━')
                formatted_lines.append('')
            
            title = re.sub(r'^\d+\.\s+', '', line)
            formatted_lines.append(f'📰 <b>{title}</b>')
            
        elif line and not line.startswith('НЕ ДОБАВЛЯЙ'):
            # Добавляем только содержательные строки
            if len(line) > 10:  # Игнорируем очень короткие строки
                formatted_lines.append(line)
        
        i += 1
    
    # Убираем лишние пустые строки в конце
    while formatted_lines and formatted_lines[-1] in ['', '━━━━━━━━━━━━━━━━━━━━']:
        formatted_lines.pop()
    
    result = '\n'.join(formatted_lines)
    
    # Если результат пустой или слишком короткий
    if not result or len(result) < 50:
        return "❌ Не удалось получить новости за сегодня или данные требуют дополнительной обработки."
    
    return result

async def send_message_to_chat(chat_id, content, bot=None):
    """Отправляет сообщение в конкретный чат"""
    if bot is None:
        bot = Bot(token=TELEGRAM_TOKEN)
    
    formatted_content = format_digest_for_telegram(content)
    max_length = 4000
    
    if len(formatted_content) <= max_length:
        try:
            await bot.send_message(
                chat_id=chat_id, 
                text=formatted_content, 
                parse_mode='HTML',
                disable_web_page_preview=True
            )
            logger.info(f"Сообщение отправлено в чат {chat_id}")
        except Exception as e:
            logger.error(f"Ошибка с HTML форматированием для чата {chat_id}: {e}")
            clean_content = re.sub(r'<[^>]+>', '', formatted_content)
            try:
                await bot.send_message(chat_id=chat_id, text=clean_content)
                logger.info(f"Сообщение отправлено в чат {chat_id} (без форматирования)")
            except Exception as e2:
                logger.error(f"Критическая ошибка отправки в чат {chat_id}: {e2}")
    else:
        # Разбиваем на части
        parts = []
        current_part = ""
        
        for line in formatted_content.split('\n'):
            if line.startswith('📰') and len(current_part) > 2000:
                if current_part:
                    parts.append(current_part.strip())
                current_part = line + '\n'
            else:
                current_part += line + '\n'
                
            if len(current_part) > max_length:
                parts.append(current_part.strip())
                current_part = ""
        
        if current_part:
            parts.append(current_part.strip())
        
        for i, part in enumerate(parts, 1):
            header = f"📰 <b>AI Дайджест - Часть {i}/{len(parts)}</b>\n\n" if len(parts) > 1 else ""
            message = header + part
            
            try:
                await bot.send_message(
                    chat_id=chat_id, 
                    text=message, 
                    parse_mode='HTML',
                    disable_web_page_preview=True
                )
                logger.info(f"Часть {i}/{len(parts)} отправлена в чат {chat_id}")
                if i < len(parts):
                    await asyncio.sleep(2)
            except Exception as e:
                logger.error(f"Ошибка отправки части {i} в чат {chat_id}: {e}")
                clean_message = re.sub(r'<[^>]+>', '', message)
                try:
                    await bot.send_message(chat_id=chat_id, text=clean_message)
                    logger.info(f"Часть {i}/{len(parts)} отправлена в чат {chat_id} (без форматирования)")
                except:
                    logger.error(f"Критическая ошибка с частью {i} для чата {chat_id}")

async def test_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда для тестирования получения дайджеста (только для админа)"""
    if str(update.effective_user.id) != MAIN_CHAT_ID:
        await update.message.reply_text("🚫 У вас нет доступа к этой команде.")
        return
    
    await update.message.reply_text("🔧 Запускаю тест получения дайджеста...")
    
    digest = get_ai_digest_from_shai()
    
    if digest:
        await update.message.reply_text(f"✅ Тест успешен! Получено {len(digest)} символов")
        
        # Отправляем полученный дайджест
        current_time = datetime.now().strftime("%d.%m.%Y %H:%M")
        header = f"🧪 <b>Тестовый AI Дайджест от SHAI</b>\n📅 {current_time}\n\n"
        full_message = header + digest
        
        await send_message_to_chat(update.effective_chat.id, full_message)
    else:
        await update.message.reply_text("❌ Тест не прошел. Не удалось получить дайджест.")

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start"""
    user_id = str(update.effective_user.id)
    username = update.effective_user.username or "Unknown"
    first_name = update.effective_user.first_name or "User"
    
    # Загружаем пользователей
    users = load_users()
    
    # Добавляем нового пользователя
    if user_id not in users:
        users[user_id] = {
            'username': username,
            'first_name': first_name,
            'joined_at': datetime.now().isoformat(),
            'chat_id': update.effective_chat.id
        }
        save_users(users)
        logger.info(f"Новый пользователь добавлен: {first_name} (@{username}, ID: {user_id})")
    
    # Приветственное сообщение
    welcome_message = (
        f"👋 Привет, {first_name}!\n\n"
        f"🤖 Добро пожаловать в AI Дайджест Бот!\n\n"
        f"📅 Каждый день в 12:35 я буду присылать свежий дайджест новостей из мира искусственного интеллекта.\n\n"
        f"🌟 <b>Что включает дайджест:</b>\n"
        f"• AI agents и мультиагентные системы\n"
        f"• Новые релизы AI фреймворков\n"
        f"• Обновления от OpenAI, Anthropic, Google AI\n"
        f"• Интересные GitHub репозитории\n"
        f"• Обсуждения в LinkedIn и Reddit\n"
        f"• Новые AI стартапы и продукты\n\n"
        f"⚡ А сейчас получи актуальный дайджест за сегодня!"
    )
    
    await update.message.reply_text(welcome_message, parse_mode='HTML')
    
    # Отправляем текущий дайджест, если он есть
    global last_digest, last_digest_date
    current_date = datetime.now().date()
    
    if last_digest and last_digest_date == current_date:
        # Если есть дайджест за сегодня, отправляем его
        logger.info(f"Отправляем существующий дайджест новому пользователю {user_id}")
        current_time = datetime.now().strftime("%d.%m.%Y %H:%M")
        header = f"🤖 <b>AI Дайджест от SHAI</b>\n📅 {current_time}\n🌟 <i>Свежие новости искусственного интеллекта</i>\n\n"
        full_message = header + last_digest
        
        await send_message_to_chat(update.effective_chat.id, full_message)
    else:
        # Если нет дайджеста за сегодня, получаем новый
        logger.info(f"Получаем новый дайджест для пользователя {user_id}")
        await update.message.reply_text("⏳ Получаю для вас актуальный дайджест, подождите...")
        
        # Получаем новый дайджест
        digest = get_ai_digest_from_shai()
        
        if digest:
            if len(digest.strip()) < 50:
                message = "⚠️ Получен слишком короткий ответ от SHAI. Возможно, нет новых данных за сегодня."
                await update.message.reply_text(message)
            elif "не найдено" in digest.lower() or "нет информации" in digest.lower():
                message = f"📭 SHAI сообщает об отсутствии новых данных:\n\n{digest}"
                await update.message.reply_text(message)
            else:
                # Сохраняем дайджест для других новых пользователей
                last_digest = digest
                last_digest_date = current_date
                
                current_time = datetime.now().strftime("%d.%m.%Y %H:%M")
                header = f"🤖 <b>AI Дайджест от SHAI</b>\n📅 {current_time}\n🌟 <i>Свежие новости искусственного интеллекта</i>\n\n"
                full_message = header + digest
                
                await send_message_to_chat(update.effective_chat.id, full_message)
        else:
            error_message = "❌ Не удалось получить данные от SHAI. Попробуйте позже или дождитесь ежедневной рассылки в 12:35."
            await update.message.reply_text(error_message)

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает статистику пользователей (только для админа)"""
    if str(update.effective_user.id) != MAIN_CHAT_ID:
        await update.message.reply_text("🚫 У вас нет доступа к этой команде.")
        return
    
    users = load_users()
    total_users = len(users)
    
    if total_users == 0:
        await update.message.reply_text("📊 Пользователей пока нет.")
        return
    
    # Сортируем по дате присоединения
    sorted_users = sorted(users.items(), key=lambda x: x[1].get('joined_at', ''), reverse=True)
    
    stats_message = f"📊 <b>Статистика бота</b>\n\n"
    stats_message += f"👥 Всего пользователей: {total_users}\n\n"
    stats_message += f"<b>Последние пользователи:</b>\n"
    
    for i, (user_id, user_data) in enumerate(sorted_users[:10], 1):
        name = user_data.get('first_name', 'Unknown')
        username = user_data.get('username', '')
        joined = user_data.get('joined_at', '')
        
        if joined:
            try:
                joined_date = datetime.fromisoformat(joined).strftime('%d.%m.%Y %H:%M')
            except:
                joined_date = joined
        else:
            joined_date = 'Unknown'
            
        username_str = f"@{username}" if username else "без username"
        stats_message += f"{i}. {name} ({username_str}) - {joined_date}\n"
    
    if total_users > 10:
        stats_message += f"\n... и еще {total_users - 10} пользователей"
    
    await update.message.reply_text(stats_message, parse_mode='HTML')

async def send_daily_digest(context: ContextTypes.DEFAULT_TYPE):
    """Отправляет ежедневный дайджест всем пользователям"""
    logger.info("Запуск ежедневного AI дайджеста")
    global last_digest, last_digest_date
    
    # Получаем дайджест
    digest = get_ai_digest_from_shai()
    
    if digest:
        # Сохраняем дайджест
        last_digest = digest
        last_digest_date = datetime.now().date()
        
        # Загружаем список пользователей
        users = load_users()
        
        # Формируем заголовок сообщения
        current_time = datetime.now().strftime("%d.%m.%Y %H:%M")
        header = f"🤖 <b>AI Дайджест от SHAI</b>\n📅 {current_time}\n🌟 <i>Свежие новости искусственного интеллекта</i>\n\n"
        full_message = header + digest
        
        # Отправляем дайджест всем пользователям
        sent_count = 0
        error_count = 0
        
        for user_id, user_data in users.items():
            try:
                chat_id = user_data.get('chat_id', user_id)
                await send_message_to_chat(chat_id, full_message)
                sent_count += 1
                # Небольшая задержка между отправками
                await asyncio.sleep(0.5)
            except Exception as e:
                logger.error(f"Ошибка отправки дайджеста пользователю {user_id}: {e}")
                error_count += 1
        
        # Отправляем статистику админу
        stats_message = (
            f"📊 <b>Статистика рассылки дайджеста</b>\n\n"
            f"✅ Успешно отправлено: {sent_count}\n"
            f"❌ Ошибок: {error_count}\n"
            f"👥 Всего пользователей: {len(users)}"
        )
        
        try:
            bot = Bot(token=TELEGRAM_TOKEN)
            await bot.send_message(
                chat_id=MAIN_CHAT_ID,
                text=stats_message,
                parse_mode='HTML'
            )
        except Exception as e:
            logger.error(f"Ошибка отправки статистики админу: {e}")
            
        logger.info(f"Рассылка завершена: {sent_count} успешно, {error_count} ошибок")
    else:
        # Если не удалось получить дайджест, уведомляем админа
        error_message = "❌ Не удалось получить дайджест от SHAI для ежедневной рассылки"
        try:
            bot = Bot(token=TELEGRAM_TOKEN)
            await bot.send_message(
                chat_id=MAIN_CHAT_ID,
                text=error_message
            )
        except Exception as e:
            logger.error(f"Ошибка отправки уведомления об ошибке: {e}")
        
        logger.error("Не удалось получить дайджест для рассылки")

async def main():
    logger.info("Запуск AI Дайджест Бота")
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("stats", stats_command))
    app.add_handler(CommandHandler("test", test_command))

    # Настройка планировщика
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        send_daily_digest,
        CronTrigger(hour=12, minute=35),
        args=[app.context_types.context]
    )
    scheduler.start()

    try:
        bot = Bot(token=TELEGRAM_TOKEN)
        await bot.send_message(
            chat_id=MAIN_CHAT_ID,
            text="🤖 <b>AI Дайджест Бот запущен!</b>\n"
                 "⏰ Ежедневная отправка настроена на 12:35\n"
                 "✅ Бот готов к работе!",
            parse_mode='HTML'
        )
    except Exception as e:
        logger.error(f"Ошибка отправки стартового сообщения: {e}")

    logger.info("Бот запущен и ожидает команды")
    await app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    import nest_asyncio
    nest_asyncio.apply()
    asyncio.run(main())