#!/bin/bash
# Скрипт для обновления конфигурации Nginx
# Добавляет новые location для нового бота в существующий конфиг

CONFIG_FILE="/etc/nginx/sites-available/planfix-webhook"
BACKUP_FILE="${CONFIG_FILE}.backup.$(date +%Y%m%d_%H%M%S)"

echo "=== Обновление конфигурации Nginx ==="
echo ""

# Создание резервной копии
echo "1. Создание резервной копии..."
sudo cp "$CONFIG_FILE" "$BACKUP_FILE"
echo "   Резервная копия: $BACKUP_FILE"
echo ""

# Проверка, есть ли уже новые location
if sudo grep -q "location /webhooks" "$CONFIG_FILE"; then
    echo "⚠️  В конфиге уже есть location /webhooks"
    echo "   Пропускаем обновление"
    exit 0
fi

echo "2. Добавление новых location для нового бота..."
echo ""

# Создание временного файла с обновленной конфигурацией
TEMP_FILE=$(mktemp)

# Используем sed для добавления новых location после location /health
sudo sed -e '/location \/health {/,/^    }$/ {
    /^    }$/a\
\
    # Новый бот - вебхуки\
    location /webhooks/ {\
        proxy_pass http://127.0.0.1:8001;\
        proxy_set_header Host $host;\
        proxy_set_header X-Real-IP $remote_addr;\
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;\
        proxy_set_header X-Forwarded-Proto $scheme;\
        proxy_http_version 1.1;\
        proxy_set_header Upgrade $http_upgrade;\
        proxy_set_header Connection "upgrade";\
        proxy_connect_timeout 60s;\
        proxy_send_timeout 60s;\
        proxy_read_timeout 60s;\
    }\
\
    # Новый бот - webapp\
    location /webapp/ {\
        proxy_pass http://127.0.0.1:8001;\
        proxy_set_header Host $host;\
        proxy_set_header X-Real-IP $remote_addr;\
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;\
        proxy_set_header X-Forwarded-Proto $scheme;\
        proxy_connect_timeout 60s;\
        proxy_send_timeout 60s;\
        proxy_read_timeout 60s;\
    }\
\
    # Новый бот - корневой путь (health check)\
    location = / {\
        proxy_pass http://127.0.0.1:8001;\
        proxy_set_header Host $host;\
        proxy_set_header X-Real-IP $remote_addr;\
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;\
        proxy_set_header X-Forwarded-Proto $scheme;\
    }
}' "$CONFIG_FILE" > "$TEMP_FILE"

if [ $? -ne 0 ]; then
    echo "   ✗ Ошибка при обновлении конфигурации"
    rm -f "$TEMP_FILE"
    exit 1
fi

echo "3. Применение новой конфигурации..."
# Показываем diff для проверки
echo "   Изменения (первые 30 строк):"
sudo diff -u "$CONFIG_FILE" "$TEMP_FILE" | head -n 30 || true
echo ""

# Применяем изменения
sudo mv "$TEMP_FILE" "$CONFIG_FILE"
echo "   ✓ Конфигурация обновлена"
echo ""

echo "4. Проверка синтаксиса..."
sudo nginx -t
if [ $? -eq 0 ]; then
    echo "   ✓ Синтаксис корректен"
    echo ""
    echo "5. Перезагрузка Nginx..."
    sudo systemctl reload nginx
    echo "   ✓ Nginx перезагружен"
    echo ""
    echo "=== Готово! ==="
    echo ""
    echo "Новые пути для нового бота:"
    echo "  - https://crmbot.restme.pro/webhooks/planfix-guest"
    echo "  - https://crmbot.restme.pro/webhooks/yforms"
    echo "  - https://crmbot.restme.pro/webapp/start"
    echo ""
    echo "Старые пути сохранены:"
    echo "  - https://crmbot.restme.pro/planfix/webhook"
    echo "  - https://crmbot.restme.pro/health"
else
    echo "   ✗ Ошибка в синтаксисе!"
    echo "   Восстановление резервной копии..."
    sudo mv "$BACKUP_FILE" "$CONFIG_FILE"
    echo "   Резервная копия восстановлена"
    exit 1
fi
