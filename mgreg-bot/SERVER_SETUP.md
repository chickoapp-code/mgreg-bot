# Пошаговая инструкция по запуску сервиса на сервере

## Обзор

Эта инструкция поможет вам развернуть сервис автоматизации приглашений тайных гостей на вашем сервере `http://crmbot.restme.pro`.

## Предварительные требования

- Сервер с доступом по SSH
- Python 3.11 или выше
- Права на установку пакетов (sudo)
- Домен/поддомен, указывающий на ваш сервер (crmbot.restme.pro)
- Telegram бот токен
- Доступ к Planfix API

---

## Шаг 1: Подготовка сервера

### 1.1. Подключение к серверу

```bash
ssh user@crmbot.restme.pro
# или
ssh user@your-server-ip
```

### 1.2. Обновление системы (Ubuntu/Debian)

```bash
sudo apt update
sudo apt upgrade -y
```

### 1.3. Установка Python и необходимых инструментов

```bash
# Установка Python 3.11+ и pip
sudo apt install -y python3 python3-pip python3-venv

# Установка дополнительных инструментов
sudo apt install -y git build-essential
```

### 1.4. Создание пользователя для приложения (опционально, но рекомендуется)

```bash
# Создание пользователя
sudo adduser --disabled-password --gecos "" botuser

# Переключение на пользователя
sudo su - botuser
```

---

## Шаг 2: Развертывание кода

### 2.1. Клонирование репозитория

```bash
# Переход в домашнюю директорию
cd ~

# Клонирование репозитория (замените URL на ваш)
git clone https://github.com/your-username/mgreg-bot.git

# Или загрузите код через scp/rsync
cd mgreg-bot
```

### 2.2. Создание виртуального окружения

```bash
# Создание виртуального окружения
python3 -m venv .venv

# Активация виртуального окружения
source .venv/bin/activate
```

### 2.3. Установка зависимостей

```bash
# Обновление pip
pip install --upgrade pip

# Установка зависимостей из requirements.txt
pip install -r requirements.txt
```

---

## Шаг 3: Настройка переменных окружения

### 3.1. Создание файла .env

```bash
# Копирование примера
cp env.example .env

# Открытие файла для редактирования
nano .env
# или
vim .env
```

### 3.2. Заполнение переменных окружения

Отредактируйте `.env` файл и заполните все необходимые значения:

```bash
# Telegram Bot Configuration
BOT_TOKEN=ваш_токен_telegram_бота

# Planfix API Configuration
PLANFIX_BASE_URL=https://conquest.planfix.ru/rest/
PLANFIX_TOKEN=ваш_токен_planfix
PLANFIX_TEMPLATE_ID=413

# Planfix Webhook Configuration (Basic Auth)
PLANFIX_WEBHOOK_LOGIN=ваш_логин_для_вебхука
PLANFIX_WEBHOOK_PASSWORD=ваш_пароль_для_вебхука
PLANFIX_TASK_TEMPLATE_IDS=123,456  # ID шаблонов задач через запятую

# Статусы Planfix
STATUS_DONE_ID=10          # ID статуса "Завершена/к компенсации"
STATUS_CANCELLED_ID=11     # ID статуса "Отменена"

# Кастомные поля Planfix
RESULT_FIELD_ID=100        # ID поля для результатов (текст)
RESULT_FILES_FIELD_ID=101  # ID поля для файлов (файлы)

# Admin Configuration
ADMIN_NAME=@ваш_telegram_username
ADMIN_CHAT_ID=123456789    # Ваш Telegram Chat ID

# Webhook Server Configuration
WEBHOOK_HOST=0.0.0.0       # Слушать на всех интерфейсах
WEBHOOK_PORT=8000          # Порт для вебхук-сервера
WEBHOOK_BASE_URL=http://crmbot.restme.pro  # Публичный URL сервера

# WebApp and Forms Configuration
WEBAPP_HMAC_SECRET=сгенерируйте_случайную_строку_для_подписи_webapp
YFORMS_WEBHOOK_SECRET=сгенерируйте_случайную_строку_для_вебхуков_форм

# Form URLs (6 форм через запятую)
# Формат: resto_a,resto_b,resto_c,delivery_a,delivery_b,delivery_c
FORM_URLS=https://forms.yandex.ru/u/resto_a,https://forms.yandex.ru/u/resto_b,https://forms.yandex.ru/u/resto_c,https://forms.yandex.ru/u/delivery_a,https://forms.yandex.ru/u/delivery_b,https://forms.yandex.ru/u/delivery_c

# Database Configuration
DATABASE_PATH=bot.db       # Путь к базе данных SQLite
```

### 3.3. Генерация секретов

Для генерации безопасных секретов используйте:

```bash
# Генерация WEBAPP_HMAC_SECRET
python3 -c "import secrets; print(secrets.token_urlsafe(32))"

# Генерация YFORMS_WEBHOOK_SECRET
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

### 3.4. Установка прав доступа на .env

```bash
# Защита файла .env от чтения другими пользователями
chmod 600 .env
```

---

## Шаг 4: Настройка Nginx (для проксирования)

### 4.1. Установка Nginx

```bash
sudo apt install -y nginx
```

### 4.2. Создание конфигурации Nginx

```bash
sudo nano /etc/nginx/sites-available/crmbot
```

Добавьте следующую конфигурацию:

```nginx
server {
    listen 80;
    server_name crmbot.restme.pro;

    # Редирект на HTTPS (опционально, но рекомендуется)
    # return 301 https://$server_name$request_uri;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        
        # Для WebSocket (если потребуется в будущем)
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        
        # Таймауты
        proxy_connect_timeout 60s;
        proxy_send_timeout 60s;
        proxy_read_timeout 60s;
    }
}
```

### 4.3. Активация конфигурации

```bash
# Создание символической ссылки
sudo ln -s /etc/nginx/sites-available/crmbot /etc/nginx/sites-enabled/

# Проверка конфигурации
sudo nginx -t

# Перезагрузка Nginx
sudo systemctl reload nginx
```

### 4.4. Настройка HTTPS с Let's Encrypt (рекомендуется)

```bash
# Установка Certbot
sudo apt install -y certbot python3-certbot-nginx

# Получение сертификата
sudo certbot --nginx -d crmbot.restme.pro

# Certbot автоматически обновит конфигурацию Nginx
```

После этого обновите `WEBHOOK_BASE_URL` в `.env`:

```bash
WEBHOOK_BASE_URL=https://crmbot.restme.pro
```

---

## Шаг 5: Настройка systemd службы

### 5.1. Создание файла службы

```bash
sudo nano /etc/systemd/system/crmbot.service
```

Добавьте следующее содержимое (замените пути на ваши):

```ini
[Unit]
Description=CRM Bot Service
After=network.target

[Service]
Type=simple
User=botuser
Group=botuser
WorkingDirectory=/home/botuser/mgreg-bot
Environment="PATH=/home/botuser/mgreg-bot/.venv/bin"
ExecStart=/home/botuser/mgreg-bot/.venv/bin/python -m bot.main
Restart=always
RestartSec=10

# Логирование
StandardOutput=journal
StandardError=journal
SyslogIdentifier=crmbot

# Ограничения безопасности
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
```

**Важно:** Замените в файле:
- `User=botuser` на вашего пользователя (или `root`, если запускаете от root)
- `Group=botuser` на вашу группу (или `root`)
- `/home/botuser/mgreg-bot` на реальный путь к проекту

**Пример для пользователя `root` и пути `/opt/mgreg-bot`:**
```ini
User=root
Group=root
WorkingDirectory=/opt/mgreg-bot
Environment="PATH=/opt/mgreg-bot/.venv/bin"
ExecStart=/opt/mgreg-bot/.venv/bin/python -m bot.main
```

### 5.2. Активация и запуск службы

```bash
# Перезагрузка systemd
sudo systemctl daemon-reload

# Включение автозапуска
sudo systemctl enable crmbot

# Запуск службы
sudo systemctl start crmbot

# Проверка статуса
sudo systemctl status crmbot
```

### 5.3. Просмотр логов

```bash
# Просмотр последних логов
sudo journalctl -u crmbot -f

# Просмотр последних 100 строк
sudo journalctl -u crmbot -n 100

# Логи с определенного времени
sudo journalctl -u crmbot --since "1 hour ago"
```

---

## Шаг 6: Настройка Planfix

### 6.1. Создание вебхука в Planfix

1. Войдите в Planfix
2. Перейдите в настройки автоматизации
3. Создайте новый вебхук со следующими параметрами:
   - **URL**: `http://crmbot.restme.pro/webhooks/planfix-guest` (или `https://` если настроен SSL)
   - **Метод**: POST
   - **Аутентификация**: Basic Auth
     - Логин: значение из `PLANFIX_WEBHOOK_LOGIN`
     - Пароль: значение из `PLANFIX_WEBHOOK_PASSWORD`
   - **События**: 
     - `task.created`
     - `task.assignee.manual`
     - `task.wait_form`
     - `task.deadline_failed`
     - `task.cancelled_manual`
     - `task.completed_compensation`
     - `task.deadline_updated`

### 6.2. Настройка шаблона задачи

1. Убедитесь, что шаблон задачи "Проверка ресторана" существует
2. Запишите ID шаблона и укажите в `PLANFIX_TASK_TEMPLATE_IDS`

### 6.3. Настройка статусов

1. Найдите ID статуса "Завершена/к компенсации" → `STATUS_DONE_ID`
2. Найдите ID статуса "Отменена" → `STATUS_CANCELLED_ID`

### 6.4. Создание кастомных полей

1. Создайте текстовое поле для результатов → `RESULT_FIELD_ID`
2. Создайте поле типа "Файлы" для вложений → `RESULT_FILES_FIELD_ID`

### 6.5. Обновление .env с ID из Planfix

После настройки Planfix обновите соответствующие переменные в `.env` и перезапустите службу:

```bash
sudo systemctl restart crmbot
```

---

## Шаг 7: Настройка Яндекс Форм

### 7.1. Настройка вебхука в каждой форме

Для каждой из 6 форм:

1. Откройте форму в Яндекс Формах
2. Перейдите в настройки интеграций
3. Настройте вебхук:
   - **URL**: `http://crmbot.restme.pro/webhooks/yforms` (или `https://`)
   - **Метод**: POST
   - **Подпись**: используйте значение из `YFORMS_WEBHOOK_SECRET`
   - **Заголовок подписи**: `X-Forms-Signature`

### 7.2. Добавление скрытых полей

В каждой форме добавьте скрытые поля:
- `sessionId` - ID сессии
- `taskId` - ID задачи
- `guestId` - ID гостя
- `formCode` - код формы (например, `delivery_adjika`)

### 7.3. Обновление FORM_URLS в .env

Убедитесь, что в `.env` указаны правильные URL всех 6 форм:

```bash
FORM_URLS=https://forms.yandex.ru/u/форма1,https://forms.yandex.ru/u/форма2,...
```

---

## Шаг 8: Проверка работы

### 8.1. Проверка доступности сервиса

```bash
# Проверка статуса службы
sudo systemctl status crmbot

# Проверка доступности вебхука-сервера
curl http://localhost:8000/webhooks/planfix-guest

# Проверка через публичный URL
curl http://crmbot.restme.pro/webhooks/planfix-guest
```

### 8.2. Проверка логов

```bash
# Просмотр логов в реальном времени
sudo journalctl -u crmbot -f

# Поиск ошибок
sudo journalctl -u crmbot | grep -i error
```

### 8.3. Тестирование функционала

1. **Регистрация гостя:**
   - Откройте Telegram бота
   - Отправьте `/start`
   - Пройдите регистрацию

2. **Создание задачи в Planfix:**
   - Создайте задачу по шаблону "Проверка ресторана"
   - Проверьте логи: должно появиться сообщение о получении вебхука

3. **Проверка приглашений:**
   - Гости должны получить приглашения в Telegram
   - Проверьте логи на наличие записей об отправке

4. **Тестирование WebApp:**
   - Примите приглашение
   - Нажмите "Начать прохождение"
   - Проверьте, что WebApp открывается

---

## Шаг 9: Настройка мониторинга (опционально)

### 9.1. Настройка автоперезапуска

Служба уже настроена на автоматический перезапуск через systemd (`Restart=always`).

### 9.2. Мониторинг дискового пространства

```bash
# Добавление в cron для мониторинга
crontab -e

# Добавьте строку (проверка каждый час)
0 * * * * df -h | mail -s "Disk usage" your-email@example.com
```

### 9.3. Ротация логов

Логи systemd автоматически ротируются. Для проверки:

```bash
# Проверка конфигурации ротации
sudo journalctl --disk-usage

# Очистка старых логов (оставить последние 7 дней)
sudo journalctl --vacuum-time=7d
```

---

## Управление службой

### Основные команды

```bash
# Запуск
sudo systemctl start crmbot

# Остановка
sudo systemctl stop crmbot

# Перезапуск
sudo systemctl restart crmbot

# Статус
sudo systemctl status crmbot

# Включение автозапуска
sudo systemctl enable crmbot

# Отключение автозапуска
sudo systemctl disable crmbot

# Просмотр логов
sudo journalctl -u crmbot -f
```

### Обновление кода

```bash
# Переход в директорию проекта
cd ~/mgreg-bot

# Остановка службы
sudo systemctl stop crmbot

# Обновление кода (если используете git)
git pull

# Активация виртуального окружения
source .venv/bin/activate

# Установка новых зависимостей (если изменился requirements.txt)
pip install -r requirements.txt

# Запуск службы
sudo systemctl start crmbot

# Проверка статуса
sudo systemctl status crmbot
```

---

## Решение проблем

### Проблема: Служба не запускается

```bash
# Проверка статуса
sudo systemctl status crmbot

# Просмотр подробных логов
sudo journalctl -u crmbot -n 50

# Проверка прав доступа к файлам
ls -la ~/mgreg-bot/.env
ls -la ~/mgreg-bot/bot.db
```

### Проблема: Вебхук не доступен извне

```bash
# Проверка, что служба слушает на правильном порту
sudo netstat -tulpn | grep 8000

# Проверка правил firewall
sudo ufw status

# Открытие порта (если нужно)
sudo ufw allow 8000/tcp
```

### Проблема: Ошибки подключения к Planfix

1. Проверьте токен в `.env`
2. Проверьте доступность Planfix API:
   ```bash
   curl -H "Authorization: Bearer YOUR_TOKEN" https://conquest.planfix.ru/rest/contact/templates
   ```

### Проблема: База данных не создается

```bash
# Проверка прав на запись
ls -la ~/mgreg-bot/

# Создание директории для БД (если нужно)
mkdir -p ~/mgreg-bot
chmod 755 ~/mgreg-bot
```

---

## Бэкапы

### Резервное копирование базы данных

```bash
# Создание скрипта бэкапа
nano ~/backup.sh
```

Содержимое скрипта:

```bash
#!/bin/bash
BACKUP_DIR="/home/botuser/backups"
DATE=$(date +%Y%m%d_%H%M%S)
mkdir -p $BACKUP_DIR
cp ~/mgreg-bot/bot.db $BACKUP_DIR/bot_$DATE.db
# Удаление старых бэкапов (старше 7 дней)
find $BACKUP_DIR -name "bot_*.db" -mtime +7 -delete
```

```bash
# Делаем скрипт исполняемым
chmod +x ~/backup.sh

# Добавляем в cron (каждый день в 3:00)
crontab -e
# Добавить: 0 3 * * * /home/botuser/backup.sh
```

---

## Контакты и поддержка

При возникновении проблем проверьте:
1. Логи службы: `sudo journalctl -u crmbot -f`
2. Логи Nginx: `sudo tail -f /var/log/nginx/error.log`
3. Конфигурацию в `.env`
4. Настройки в Planfix и Яндекс Формах

---

## Дополнительные рекомендации

1. **Использование Docker (опционально):**
   Если предпочитаете Docker, используйте `docker-compose.yml`:
   ```bash
   docker-compose up -d
   ```

2. **Настройка резервного копирования:**
   Регулярно делайте бэкапы `.env` и `bot.db`

3. **Мониторинг ресурсов:**
   Используйте `htop` или `top` для мониторинга использования ресурсов

4. **Обновления безопасности:**
   Регулярно обновляйте систему:
   ```bash
   sudo apt update && sudo apt upgrade -y
   ```

