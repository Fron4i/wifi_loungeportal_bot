import time
import datetime
import requests
import logging
from librouteros import connect
from librouteros.login import plain as login_plain

ROUTER_HOST = '91.221.246.23'
ROUTER_PORT = 44444
ROUTER_USER = 'iliya'
ROUTER_PASS = '4`P<OjT1'
BYPASS_LIFETIME = 24 * 3600  # 24 часа


bypass_logger = logging.getLogger("bypass_cleanup")

def print_all_bypass(api):
    bypass_path = api.path('ip', 'hotspot', 'ip-binding')
    bypass_list = list(bypass_path(cmd='print'))
    bypass_logger.info("\n📋 Текущие bypass-записи:")
    for bypass in bypass_list:
        comment = bypass.get('comment')
        bypass_logger.info(f" - mac-address: {bypass.get('mac-address')}, type: {bypass.get('type')}, comment: {comment}")

def add_bypass_by_telegram_id(telegram_id: int):
    url = "https://nas.lounge-place.ru/wifi/submit.php"
    payload = {
        "telegram_id": telegram_id
    }

    try:
        response = requests.post(url, data=payload)
        bypass_logger.info(f"Ответ от бэкенда (status: {response.status_code}): {response.text}")

        if response.status_code != 200:
            bypass_logger.info(f"❌ Ошибка запроса к API: {response.status_code}")
            return

        data = response.json()
        mac_address = data.get("mac_address")

        if not mac_address:
            bypass_logger.info("❌ MAC-адрес не найден в ответе от сервера.")
            return

        add_bypass(mac_address)

    except Exception as e:
        bypass_logger.info(f"❌ Исключение при обращении к API: {e}")


def add_bypass(mac_address: str):
    api = connect(
        host=ROUTER_HOST,
        username=ROUTER_USER,
        password=ROUTER_PASS,
        port=ROUTER_PORT,
        login_method=login_plain,
    )
    print_all_bypass(api)

    bypass_path = api.path('ip', 'hotspot', 'ip-binding')

    # Получаем все bypass и фильтруем в коде
    bypass_list = list(bypass_path(cmd='print'))
    existing = [b for b in bypass_list if b.get('mac-address') == mac_address]
    if existing:
        bypass_logger.info(f"⚠️ Bypass для MAC {mac_address} уже существует, добавлять не будем.")
        print_all_bypass(api)
        api.close()
        return

    now = datetime.datetime.now()
    comment = now.strftime("%d.%m.%Y:%H-%M-%S")

    bypass_path.add(
    **{
        'mac-address': mac_address,
        'type': 'bypassed',
        'comment': comment,
    	}
		)

    bypass_logger.info(f"\n✅ Добавлен bypass для {mac_address} с комментарием (время) {comment}")

    print_all_bypass(api)
    api.close()


def clean_old_bypass():
    api = connect(
        host=ROUTER_HOST,
        username=ROUTER_USER,
        password=ROUTER_PASS,
        port=ROUTER_PORT,
        login_method=login_plain,
    )
    print_all_bypass(api)
    
    bypass_path = api.path('ip', 'hotspot', 'ip-binding')
    now = time.time()
    deleted_count = 0

    bypasses = list(bypass_path(cmd='print'))
    for b in bypasses:
        if b.get('type') == 'bypassed':
            comment = b.get('comment')
            if comment:
                if not isinstance(comment, str):
                    comment = str(comment)
                try:
                    dt = datetime.datetime.strptime(comment, "%d.%m.%Y:%H-%M-%S")
                    created_time = dt.timestamp()
                    if now - created_time > BYPASS_LIFETIME:
                        bypass_logger.info(f"🗑 Удаляем bypass с MAC {b.get('mac-address')}, созданный {dt.strftime('%Y-%m-%d %H:%M:%S')}")
                        bypass_path.remove(b.get('.id'))  # <== Исправлено здесь
                        deleted_count += 1
                except ValueError:
                    pass

    bypass_logger.info(f"\n✅ Удалено bypass записей: {deleted_count}")
    print_all_bypass(api)
    api.close()


if __name__ == "__main__":
    # MAC_TEST = '26:C7:BB:3D:11:76'

    # bypass_logger.info("=== Добавление bypass ===")
    # add_bypass(MAC_TEST)

    # bypass_logger.info("\n=== Очистка старых bypass ===")
    # clean_old_bypass()

    bypass_logger.info("\n=== ЭТО ФАЙЛ mikrotik_api_2.py ===")