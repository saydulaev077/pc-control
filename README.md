# PC Control v5 Ultimate — Railway + Raspberry Pi

Этот комплект разделяет управление на 3 части:

**Telegram / сайт → Railway → Raspberry Pi → Windows ПК**

Это позволяет нажать **«🟢 Включить ПК»**, даже когда Windows-компьютер выключен. Raspberry Pi при этом должен оставаться включённым.

## 1. Railway

Загрузи этот проект в GitHub и создай проект в Railway из репозитория.

Railway использует `railway.toml` и запускает:

```text
python railway_app.py
```

Добавь Variables:

```text
BOT_TOKEN=токен_Telegram_бота
ALLOWED_USER_ID=твой_telegram_id
WEB_PASSWORD=сильный_пароль_для_сайта
AGENT_SECRET=случайная_длинная_секретная_строка
```

После деплоя Railway даст домен вида `https://....up.railway.app`.
Он нужен для Raspberry Pi как `RAILWAY_URL`.

## 2. Windows ПК

Для старого полного Windows-сервера установи зависимости из `windows-requirements.txt`:

```powershell
python -m pip install -r windows-requirements.txt
```\n\n## 3. Raspberry Pi

Скопируй на Raspberry Pi файл `pi_agent.py` и `pi_requirements.txt`.

Установи:

```bash
python3 -m pip install -r pi_requirements.txt
```

Задай переменные:

```bash
export RAILWAY_URL="https://ТВОЙ-ДОМЕН.up.railway.app"
export AGENT_SECRET="та же строка, что в Railway"
export PC_CONTROL_URL="http://IP_КОМПЬЮТЕРА:5000"
export PC_AGENT_SECRET="отдельная длинная строка"
export PC_MAC="AA:BB:CC:DD:EE:FF"
```

В переменных Windows добавь:

```powershell
$env:PC_AGENT_SECRET="та же строка, что указана на Raspberry Pi"
$env:PC_CONTROL_HOST="0.0.0.0"
$env:PC_CONTROL_PORT="5000"
```

Запусти обычный сервер PC Control:

```powershell
python server.py
```

Важно: Windows Firewall должен разрешать вход на TCP-порт 5000 из локальной сети.

## 4. Wake-on-LAN

На Windows/материнской плате включи Wake-on-LAN:

- включи Wake on LAN в BIOS/UEFI;
- в свойствах Ethernet-адаптера разреши пробуждение компьютера;
- запиши MAC-адрес сетевой карты;
- впиши его в `PC_MAC` на Raspberry Pi.

Для надёжного Wake-on-LAN компьютер лучше подключить к роутеру **по Ethernet**, а не по Wi-Fi.

## 5. Запуск агента Raspberry Pi

```bash
python3 pi_agent.py
```

Теперь:

- сайт Railway → «🟢 Включить ПК» → Raspberry Pi отправляет Wake-on-LAN;
- Telegram → «🟢 Включить ПК» → то же самое;
- выключение/перезагрузка/сон передаются на Windows после того, как ПК включён.

## Безопасность

Не публикуй порт 5000 Windows ПК напрямую в интернет. Railway общается только с Raspberry Pi через исходящие HTTPS-запросы. Raspberry Pi общается с ПК внутри домашней сети.

`AGENT_SECRET`, `PC_AGENT_SECRET`, `BOT_TOKEN` и пароль сайта никому не отправляй.
