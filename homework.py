import logging
import os
import sys
import time
import typing
from http import HTTPStatus
from logging import StreamHandler

import requests
import telegram
from dotenv import load_dotenv
from pathlib import Path

from exceptions import NotSendMessageTelegram

load_dotenv()

PRACTICUM_TOKEN = os.getenv('PRACTICUM_TOKEN')
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

RETRY_PERIOD = 600  # 10 мин * 60 сек
ENDPOINT = 'https://practicum.yandex.ru/api/user_api/homework_statuses/'
HEADERS = {'Authorization': f'OAuth {PRACTICUM_TOKEN}'}

HOMEWORK_VERDICTS = {
    'approved': 'Работа проверена: ревьюеру всё понравилось. Ура!',
    'reviewing': 'Работа взята на проверку ревьюером.',
    'rejected': 'Работа проверена: у ревьюера есть замечания.',
}

logging.basicConfig(
    level=logging.INFO,
    filename=Path('program.log'),
    filemode='w',
    format=(
        '%(asctime)s - %(levelname)s - %(lineno)d - %(message)s - %(funcName)s'
    ),
)
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
handler = StreamHandler(stream=sys.stdout)
formatter = logging.Formatter(
    '%(asctime)s - %(levelname)s - %(lineno)d - %(message)s - %(funcName)s',
)
handler.setFormatter(formatter)
logger.addHandler(handler)


def func_logger(func: typing.Any) -> typing.Any:
    """Декоратор логирования функций.

    Args:
        func: Функция для логирования.

    Returns:
        func: Функция после логирования.

    """

    def inner(*args: typing.Any, **kwargs: typing.Any) -> typing.Any:
        ret = func(*args, **kwargs)
        logger.debug(
            'Вызов функции "%s" с "%s" вернул "%s"',
            func.__name__,
            (args, kwargs),
            ret,
        )
        return ret

    return inner


def check_tokens() -> None:
    """Проверяет доступность переменных окружения.

    Raises:
        SystemExit: Если переменные отсутвуют.

    """
    empty_tokens = [
        token
        for token in ('PRACTICUM_TOKEN', 'TELEGRAM_TOKEN', 'TELEGRAM_CHAT_ID')
        if globals().get(token) is None
    ]
    if empty_tokens:
        logging.critical('Переменные окружения "%s" недоступны', empty_tokens)
        raise SystemExit(f'Переменные окружения "{empty_tokens}" недоступны')


# @func_logger при добавление декоратора не проходит Pytest
# (AssertionError: Убедитесь, что в функции `send_message` есть docstring.)
def send_message(bot: telegram.Bot, message: str) -> None:
    """Отправляет сообщение в Telegram чат.

    Args:
        bot: TelegramBot.
        message: Сообщение для отправки.

    Raises:
        NotSendMessageTelegram: если cообщениe не отправлено.

    """
    try:
        bot.send_message(TELEGRAM_CHAT_ID, message)
    except telegram.error.TelegramError:
        logging.error('Ошибка в работе TelegramBot, cообщениe не отправлено')
        raise NotSendMessageTelegram(
            'Ошибка в работе TelegramBot, cообщениe не отправлено',
        )
    logger.debug('Cообщениe в Telegram успешно отправлено')


def get_api_answer(timestamp: int) -> requests.Response:
    """Делает запрос к эндпоинту API-сервиса.

    Args:
        timestamp: Время отправки запроса.

    Raises:
        HTTPError: API возвращает код, не 200.

    Returns:
        homework_statuses.json(): Ответ API.

    """
    try:
        response = requests.get(
            url=ENDPOINT,
            headers=HEADERS,
            params={'from_date': timestamp},
        )
    except requests.RequestException:
        logging.error('Ошибка обработки запроса к API сервису')
    if response.status_code != HTTPStatus.OK:
        logging.error(
            'API Практикум.Домашка возвращает код, отличный от 200',
        )
        raise requests.HTTPError()
    logger.debug(
        'Статус ответа %s , ответ = %s ',
        response.status_code,
        response.json(),
    )
    return response.json()


def check_response(
    response: requests.Response,
) -> typing.Dict[str, typing.Any]:
    """Проверяет ответ API на соответствие документации.

    Args:
        response: Ответ API.

    Raises:
        TypeError: Если ответ API не словарь'.

    Returns:
        homework_statuses.json(): Ответ API.

    """
    if (
        isinstance(response, dict)
        and all(key in response for key in ('homeworks', 'current_date'))
        and isinstance(response.get('homeworks'), list)
    ):
        return response.get('homeworks')
    raise TypeError('Тип ответа API не соответвует ожидаемому')


def parse_status(homework: typing.Dict[str, typing.Any]) -> str:
    """Извлекает из информации о домашней работе статус этой работы.

    Args:
        homework: Общая информация о домашней работе.

    Raises:
        KeyError: Значение по ключу не доступно.
        KeyError: Если статус домашней работы недокументирован.

    Returns:
        str: Cтатус этой работы.

    """
    try:
        name, status = homework['homework_name'], homework['status']
    except KeyError:
        logging.error('Значение по ключу не доступно')
    try:
        verdict = HOMEWORK_VERDICTS[status]
    except KeyError:
        raise KeyError('Недокументированный статус домашней работы')
    return f'Изменился статус проверки работы "{name}". {verdict}'


def main() -> None:
    """Основная логика работы бота."""
    check_tokens()
    bot = telegram.Bot(token=TELEGRAM_TOKEN)
    logging.info('Запуск Бота')
    timestamp = int(time.time())
    last_message = None
    while True:
        try:
            response = get_api_answer(timestamp)
            homeworks = check_response(response)
            timestamp = response['current_date']
            if homeworks:
                send_message(bot, parse_status(homeworks[0]))
            else:
                logger.debug('Изменений в статусе проверки ДЗ нет')
        except Exception as error:  # noqa: PIE786
            message = f'Сбой в работе программы: {error}'
            logging.error(message)
            if message != last_message:
                bot.send_message(TELEGRAM_CHAT_ID, message)
                last_message = message
        finally:
            time.sleep(RETRY_PERIOD)
            logger.debug('Погружение программы в сон на %s мин', RETRY_PERIOD)


if __name__ == '__main__':
    main()
