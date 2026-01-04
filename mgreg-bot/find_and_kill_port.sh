#!/bin/bash
# Скрипт для поиска и остановки процесса на порту 8001

PORT=8001

echo "=== Поиск процесса на порту $PORT ==="
echo ""

# Поиск процесса через lsof
echo "1. Поиск через lsof:"
sudo lsof -i :$PORT

# Поиск процесса через fuser
echo ""
echo "2. Поиск через fuser:"
sudo fuser $PORT/tcp

# Поиск через ss
echo ""
echo "3. Поиск через ss:"
sudo ss -tulpn | grep :$PORT

echo ""
echo "=== Варианты остановки процесса ==="
echo ""
echo "Если это ваш старый процесс бота, остановите его:"
echo "  sudo kill -9 <PID>"
echo ""
echo "Или найдите все процессы Python и остановите нужный:"
echo "  ps aux | grep python"
echo "  sudo kill -9 <PID>"
echo ""
echo "Или если вы используете screen/tmux:"
echo "  screen -ls    # список сессий"
echo "  screen -r <session>  # подключиться и остановить (Ctrl+C)"
echo ""
echo "  tmux ls       # список сессий"
echo "  tmux attach -t <session>  # подключиться и остановить (Ctrl+C)"




