#!/bin/bash
# Скрипт для проверки работы Nginx и проксирования на вебхук-сервер

echo "=== Проверка Nginx ==="
echo ""

# 1. Проверка синтаксиса конфигурации
echo "1. Проверка синтаксиса конфигурации Nginx:"
sudo nginx -t
if [ $? -eq 0 ]; then
    echo "✅ Конфигурация Nginx корректна"
else
    echo "❌ Ошибка в конфигурации Nginx"
    exit 1
fi
echo ""

# 2. Проверка статуса службы Nginx
echo "2. Статус службы Nginx:"
sudo systemctl status nginx --no-pager | head -n 10
echo ""

# 3. Проверка, что Nginx слушает на порту 80
echo "3. Проверка, что Nginx слушает на порту 80:"
sudo ss -tulpn | grep :80
if [ $? -eq 0 ]; then
    echo "✅ Nginx слушает на порту 80"
else
    echo "❌ Nginx не слушает на порту 80"
fi
echo ""

# 4. Проверка, что вебхук-сервер слушает на порту 8001
echo "4. Проверка, что вебхук-сервер слушает на порту 8001:"
sudo ss -tulpn | grep :8001
if [ $? -eq 0 ]; then
    echo "✅ Вебхук-сервер слушает на порту 8001"
else
    echo "❌ Вебхук-сервер НЕ слушает на порту 8001"
    echo "   Запустите сервис: python -m bot.main"
fi
echo ""

# 5. Проверка прямого доступа к вебхук-серверу
echo "5. Проверка прямого доступа к вебхук-серверу (localhost:8001):"
curl -s http://localhost:8001/ | head -n 5
if [ $? -eq 0 ]; then
    echo "✅ Вебхук-сервер отвечает напрямую"
else
    echo "❌ Вебхук-сервер не отвечает"
fi
echo ""

# 6. Проверка доступа через Nginx (локально)
echo "6. Проверка доступа через Nginx (localhost:80):"
curl -s http://localhost/ | head -n 5
if [ $? -eq 0 ]; then
    echo "✅ Nginx проксирует запросы на вебхук-сервер"
else
    echo "❌ Nginx не проксирует запросы"
fi
echo ""

# 7. Проверка доступа через публичный домен (если доступен)
echo "7. Проверка доступа через публичный домен:"
DOMAIN="crmbot.restme.pro"
curl -s -o /dev/null -w "HTTP Status: %{http_code}\n" http://${DOMAIN}/
echo ""

# 8. Проверка конкретного эндпоинта вебхука
echo "8. Проверка эндпоинта /webhooks/planfix-guest (GET):"
curl -s http://localhost/webhooks/planfix-guest | python3 -m json.tool 2>/dev/null || curl -s http://localhost/webhooks/planfix-guest
echo ""

# 9. Проверка логов Nginx на ошибки
echo "9. Последние ошибки в логах Nginx (если есть):"
sudo tail -n 5 /var/log/nginx/error.log 2>/dev/null || echo "Логи ошибок не найдены или пусты"
echo ""

echo "=== Проверка завершена ==="

