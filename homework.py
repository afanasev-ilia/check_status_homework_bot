import logging
import os
import sys
import time
from http import HTTPStatus
from logging import StreamHandler
from typing import Dict

import requests
import telegram
from dotenv import load_dotenv
from telegram import Bot

from exceptions import ApiNot200StatusResponse

load_dotenv()

PRACTICUM_TOKEN = os.getenv('PRACTICUM_TOKEN')
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

RETRY_PERIOD = 600
ENDPOINT = 'https://practicum.yandex.ru/api/user_api/homework_statuses/'
HEADERS = {'Authorization': f'OAuth {PRACTICUM_TOKEN}'}

HOMEWORK_VERDICTS = {
    'approved': 'Работа проверена: ревьюеру всё понравилось. Ура!',
    'reviewing': 'Работа взята на проверку ревьюером.',
    'rejected': 'Работа проверена: у ревьюера есть замечания.',
}

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
handler = StreamHandler(stream=sys.stdout)
formatter = logging.Formatter(
    '%(asctime)s - %(levelname)s - %(message)s - %(funcName)s - %(lineno)d',
)
handler.setFormatter(formatter)
logger.addHandler(handler)


def check_tokens() -> None:
    """Проверяет доступность переменных окружения.
    Raises:
    SystemExit: Если переменные отсутвуют. # noqa: DAR401
    """
    errors = [
        token
        for token in ('PRACTICUM_TOKEN', 'TELEGRAM_TOKEN', 'TELEGRAM_CHAT_ID')
        if globals()[token] is None
    ]
    if errors != []:
        logger.critical('Переменные окружения %s недоступны', errors)
        raise SystemExit(f'Переменные окружения {errors} недоступны')


def send_message(bot: Bot, message: str) -> None:
    """Отправляет сообщение в Telegram чат.
    Args:
    bot: TelegramBot. # noqa: DAR101 bot
    message: Сообщение для отправки. # noqa: DAR101 message
    """
    try:
        bot.send_message(TELEGRAM_CHAT_ID, message)
    except telegram.error.TelegramError:
        logger.error('Ошибка в работе TelegramBot, cообщениe не отправлено')
    logger.debug('Cообщениe в Telegram успешно отправлено')


def get_api_answer(timestamp: int) -> requests.Response:
    """Делает запрос к эндпоинту API-сервиса.
    Args:
    timestamp: Время отправки запроса. # noqa: DAR101 timestamp
    Raises:
    ApiNot200StatusResponse: API возвращает код, не 200. # noqa: DAR401
    Returns:
    homework_statuses.json(): Ответ API. # noqa: DAR201

    """
    try:
        homework_statuses = requests.get(
            ENDPOINT,
            headers=HEADERS,
            params={'from_date': timestamp},
        )
    except requests.RequestException:
        logger.error('Ошибка обработки запроса к API сервису')
    if homework_statuses.status_code != HTTPStatus.OK:
        logger.error(
            'API Практикум.Домашка возвращает код, отличный от 200',
        )
        raise ApiNot200StatusResponse()
    logger.debug(homework_statuses.json())
    logger.debug(homework_statuses.status_code)
    return homework_statuses.json()


def check_response(response: requests.Response) -> requests.Response:
    """Проверяет ответ API на соответствие документации.
    Args:
    response: Ответ API. # noqa: DAR101 timestamp
    Raises:
    TypeError: Если ответ API не словарь'. # noqa: DAR401
    Returns:
    homework_statuses.json(): Ответ API. # noqa: DAR201
    """
    if not isinstance(response, dict) or response.get('homeworks') is None:
        logger.error('Значение по ключу homeworks не доступно')
        raise TypeError('Ответ API не словарь')
    if (
        not isinstance(response.get('homeworks'), list)
        or response.get('current_date') is None
    ):
        logger.error('Значение по ключу current_datee не доступно')
        raise TypeError('Ответ API под ключом "homeworks" не список')
    return response


def parse_status(homework: Dict) -> str:
    """Извлекает из информации о домашней работе статус этой работы.
    Args:
    homework: Общая информация о домашней работе # noqa: DAR101 timestamp
    Raises:
    KeyError: Если статус домашней работы недокументирован. # noqa: DAR401
    Returns:
    str: Cтатус этой работы. # noqa: DAR201
    """
    homework_name = homework.get('homework_name')
    if homework_name is None:
        raise logger.error('В ответе API домашки нет ключа `homework_name`')
    status = homework.get('status')
    if status not in HOMEWORK_VERDICTS:
        raise KeyError('Недокументированный статус домашней работы')
    verdict = HOMEWORK_VERDICTS.get(status)
    return f'Изменился статус проверки работы "{homework_name}". {verdict}'


def main() -> None:
    """Основная логика работы бота."""
    check_tokens()
    bot = telegram.Bot(token=TELEGRAM_TOKEN)
    timestamp = int(time.time())
    # переменная не одноразовая, перед новой итерацией меняем время запроса
    # если импортировать time из time, то перестанет работать time.sleep()
    last_message = ''
    logger.info('Запуск Бота')
    while True:
        try:
            response = get_api_answer(timestamp)
            check_response(response)
            homeworks = response.get('homeworks')
            if len(homeworks) > 0:
                send_message(bot, parse_status(homeworks[0]))
                timestamp = response.get('current_date')
            else:
                logger.debug('Изменений в статусе проверки ДЗ нет')
        except Exception as error:
            message = f'Сбой в работе программы: {error}'
            logger.error(message)
            if message != last_message:
                bot.send_message(TELEGRAM_CHAT_ID, message)
                last_message = message
        time.sleep(RETRY_PERIOD)


if __name__ == '__main__':
    main()
