# БЕТОН: Docker Compose и VM

## Автоматическая установка и обновление (Ubuntu)

Скачайте и распакуйте репозиторий в постоянную папку, например `/opt/beton`, или клонируйте его. В корне папки запустите:

```bash
sudo bash istall.sh
```

Имя `istall.sh` сохранено согласно запросу. Скрипт устанавливает Git, rsync, Docker Engine и Compose, включает Docker при загрузке сервера, создаёт `.env`, собирает приложение и ждёт готовности контейнера. При первом запуске запрашивает адрес GitHub-репозитория (если папка скачана ZIP-архивом) и публичный URL сайта. Существующий `.env` сохраняется. Нужны Ubuntu 22.04/24.04, sudo и доступ в интернет.

Для схемы с отдельной reverse-proxy VM укажите приватный IP **сервера приложения** при первом запуске:

```bash
sudo env APP_BIND_IP=10.100.0.215 BETON_PUBLIC_ORIGIN=https://ludka.naebalovo.space bash istall.sh
```

По умолчанию приложение слушает `127.0.0.1:8000`. Nginx, DNS и HTTPS на отдельной proxy VM настраиваются по инструкции ниже; установщик разворачивает сервер приложения.

Затем для каждого обновления достаточно:

```bash
cd /opt/beton
sudo bash update.sh
```

Скрипт получает последний коммит выбранной ветки, сохраняет резервную копию работающей SQLite в `.deploy/backups/`, синхронизирует исходники и выполняет сборку и запуск Compose с ожиданием готовности. `.env`, `.git`, `.deploy`, `.venv`, `data`, `instance` и SQLite-файлы сохраняются, volume `beton-data` не удаляется. Остальные локальные изменения исходников заменяются версией из GitHub, удалённые из репозитория файлы удаляются и на сервере. Используйте отдельную папку только для этого проекта.

Адрес репозитория и ветка сохраняются в `.deploy/`; по умолчанию выбирается основная ветка GitHub. Их можно изменить явно:

```bash
sudo env REPO_URL=https://github.com/OWNER/REPO.git BRANCH=main bash update.sh
```

Для приватного репозитория заранее настройте Git-доступ для пользователя, запускающего скрипты (при `sudo` это root); не записывайте токен в URL. Запуски защищены от одновременного выполнения. Коммит успешного обновления записывается в `.deploy/version`. При ошибке скрипт завершится с ненулевым кодом; автоматического отката нет. Для диагностики: `sudo docker compose logs --tail=100 web`. Резервные копии хранятся без автоматического удаления.


Сайт и Flask API собраны в один Docker Compose сервис на app-VM. Аккаунты, рейтинг и прогресс хранятся в SQLite на именованном volume `beton-data`; пересборка контейнера данные не удаляет. Публичный домен обслуживает отдельная Nginx reverse-proxy VM, которая соединяется с app-VM по приватному адресу.

## Локально

Требуется Python 3.10+.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m backend.app
```

Откройте `http://127.0.0.1:8000`. API-тесты: `.\.venv\Scripts\python.exe -m unittest discover -s tests -v`.

## Установка Docker на Ubuntu

Инструкция рассчитана на Ubuntu 22.04/24.04, домен с A-записью на VM и пользователя с `sudo`.

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl nginx certbot python3-certbot-nginx ufw rsync
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
ARCH=$(dpkg --print-architecture)
CODENAME=$(. /etc/os-release && echo "${UBUNTU_CODENAME:-$VERSION_CODENAME}")
echo "deb [arch=$ARCH signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $CODENAME stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo systemctl enable --now docker
sudo docker compose version
```

## Передача проекта

Из PowerShell на компьютере, в корне репозитория. Замените пользователя и IP VM:

```powershell
ssh user@SERVER_IP "mkdir -p /tmp/beton"
scp -r Dockerfile docker-compose.yml .dockerignore .env.example backend deploy games_5_7.html requirements.txt user@SERVER_IP:/tmp/beton/
```

На VM:

```bash
sudo install -d /opt/beton
sudo rsync -a /tmp/beton/ /opt/beton/
sudo chown -R root:root /opt/beton
cd /opt/beton
```

## Запуск приложения

Создайте конфигурацию и замените домен:

```bash
sudo cp .env.example .env
sudo sed -i 's|https://example.com|https://ludka.naebalovo.space|' .env
sudo sed -i 's|APP_BIND_IP=127.0.0.1|APP_BIND_IP=10.100.0.215|' .env
sudo chmod 600 .env
sudo cat .env
```

В `.env` должны быть значения:

```ini
BETON_PUBLIC_ORIGIN=https://ludka.naebalovo.space
BETON_COOKIE_SECURE=true
APP_PORT=8000
APP_BIND_IP=10.100.0.215
```

`APP_BIND_IP` должен быть приватным IP-адресом самой app-VM. Docker опубликует порт 8000 на этом интерфейсе, а не на всех адресах.

Соберите и запустите:

```bash
sudo docker compose up -d --build
sudo docker compose ps
sudo docker compose logs --tail=100 web
curl -i http://10.100.0.215:8000/api/auth/me
```

Дождитесь статуса `healthy`. Проверочный API должен вернуть HTTP 200 и `{"user":null}`. На сетевом firewall/security group разрешите TCP/8000 на app-VM только с приватного IP reverse-proxy VM. Не публикуйте этот порт на публичном интерфейсе и не полагайтесь только на UFW: Docker может обходить его правила для опубликованных портов. Пересобрать и обновить сайт можно командой `sudo docker compose up -d --build`; SQLite volume при этом сохраняется.

## Отдельная reverse-proxy VM

В примерах публичный IP домена указывает на reverse-proxy VM; обе машины соединены приватной сетью, а адрес app-VM — `10.100.0.215`. На reverse-proxy VM установите Nginx и Certbot:

```bash
sudo apt-get update
sudo apt-get install -y nginx certbot python3-certbot-nginx ufw
sudo systemctl enable --now nginx
```

Ограничьте входящий порт 8000 на app-VM адресом reverse-proxy VM. Замените `10.100.0.10` на приватный IP reverse proxy; правило задаётся на app-VM и, если у провайдера есть security groups, продублируйте его там:

```bash
sudo ufw allow OpenSSH
sudo ufw allow from 10.100.0.10 to 10.100.0.215 port 8000 proto tcp
sudo ufw enable
```

На reverse-proxy VM проверьте DNS A-запись домена. Из PowerShell в корне проекта передайте три Nginx-файла на proxy VM, заменив пользователя и адрес:

```powershell
scp deploy/mail-beton-bootstrap.conf deploy/mail-beton.conf user@PROXY_IP:/tmp/
```

На reverse-proxy VM конфиг сайта должен жить отдельно от почтового `/etc/nginx/sites-available/mail.conf`. Убедитесь, что для `ludka.naebalovo.space` включён только `mail-beton.conf`:

```bash
sudo grep -RIn 'server_name ludka.naebalovo.space' /etc/nginx/sites-enabled /etc/nginx/conf.d
```

Если Certbot ранее добавил блоки `ludka.naebalovo.space` в `mail.conf`, сделайте резервную копию и удалите из `mail.conf` только эти Certbot-блоки сайта; server-блоки `mail.naebalovo.space` не трогайте.

Если сертификат уже выпущен и файлы `/etc/letsencrypt/live/ludka.naebalovo.space/fullchain.pem` и `privkey.pem` существуют, bootstrap и повторный запуск Certbot не нужны. Сразу установите итоговый конфиг:

```bash
sudo install -m 0644 /tmp/mail-beton.conf /etc/nginx/sites-available/mail-beton.conf
sudo nginx -t && sudo systemctl reload nginx
```

HTTP bootstrap нужен только для первой выдачи сертификата, когда TLS-файлов ещё нет. В этом случае установите его отдельно:

```bash
sudo cp /etc/nginx/sites-available/mail.conf /etc/nginx/sites-available/mail.conf.bak
sudo install -m 0644 /tmp/mail-beton-bootstrap.conf /etc/nginx/sites-available/mail-beton.conf
sudo ln -sfn /etc/nginx/sites-available/mail-beton.conf /etc/nginx/sites-enabled/mail-beton.conf
sudo nginx -t
sudo systemctl reload nginx
curl -I -H 'Host: ludka.naebalovo.space' http://127.0.0.1
```

Bootstrap-конфиг временно проксирует HTTP на app-VM и нужен только для первичного выпуска сертификата. Если сертификат уже есть, этот шаг пропустите. Для первого выпуска разрешите публично только SSH, HTTP и HTTPS на reverse-proxy VM:

```bash
sudo ufw allow OpenSSH
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable
sudo certbot --nginx -d ludka.naebalovo.space --redirect --agree-tos -m admin@naebalovo.space
sudo certbot renew --dry-run
```

Certbot должен изменить отдельный `mail-beton.conf`, а не почтовый `mail.conf`. После успешного выпуска сертификата поставьте итоговый HTTPS virtual host, который отправляет запросы на `10.100.0.215:8000`:

```bash
sudo install -m 0644 /tmp/mail-beton.conf /etc/nginx/sites-available/mail-beton.conf
sudo nginx -t
sudo systemctl reload nginx
curl -I https://ludka.naebalovo.space
```

Проверьте, что в `nginx -T` блок `server_name ludka.naebalovo.space` проксирует на `10.100.0.215:8000`, и он ровно один для HTTPS. Серверы `mail.naebalovo.space` остаются в `mail.conf` без изменений. Сертификаты ожидаются по путям `/etc/letsencrypt/live/ludka.naebalovo.space/`. Порт 8000 никогда не открывайте всему интернету.

## Обслуживание и резервные копии

```bash
cd /opt/beton
sudo docker compose ps
sudo docker compose logs -f web
sudo docker compose restart web
sudo docker compose up -d --build
```

Создать SQLite backup через online backup API и скопировать его из контейнера на VM:

```bash
sudo docker compose exec -T web python -c 'import sqlite3; source=sqlite3.connect("/data/beton.sqlite3"); target=sqlite3.connect("/tmp/beton-backup.sqlite3"); source.backup(target); target.close(); source.close()'
umask 077
sudo docker compose exec -T web python -c 'import shutil, sys; source=open("/tmp/beton-backup.sqlite3", "rb"); shutil.copyfileobj(source, sys.stdout.buffer); source.close()' > "$HOME/beton-backup-$(date +%F-%H%M%S).sqlite3"
```

Volume можно проверить командой `sudo docker volume inspect beton-data`. Не выполняйте `sudo docker compose down -v`, если хотите сохранить аккаунты и игровой прогресс: флаг `-v` удалит базу.

## Тесты и безопасность

Запуск тестов на Linux: `.venv/bin/python -m unittest discover -s tests -v`. На Windows: `.\.venv\Scripts\python.exe -m unittest discover -s tests -v`.

`backend/` — Flask API и SQLite, `games_5_7.html` — сайт, `tests/` — API-тесты, `Dockerfile` и `docker-compose.yml` — контейнерный запуск, `deploy/` — Nginx-конфиги. Пароли хранятся как scrypt-хэши, сессии защищены HttpOnly cookie. Раунды аккаунтов и выплаты рассчитывает сервер. Гостевая игра остаётся локальной и не переносит деньги в аккаунт.

## Исправления денежного учёта

Исправлена оценка покера: 10, J, Q и K имеют разные достоинства. Раньше четыре разные карты этой группы ошибочно считались каре с выплатой ×25. Это подтверждённая ошибка начисления; установить причину конкретной накрутки без журналов сервера нельзя.

Баланс и денежная статистика хранятся в десятичных TEXT-колонках `*_exact`, считаются целыми числами произвольной длины в Python и BigInt в браузере. Старые числовые колонки сохраняются для совместимости схемы и больше не служат источником денежных данных. Миграция при старте копирует существующие суммы один раз, без сброса аккаунтов. Перед обновлением сделайте SQLite backup по инструкции выше.

API возвращает денежные суммы больше `Number.MAX_SAFE_INTEGER` десятичными строками. Ставки принимаются целыми числами или десятичными строками, кратными 50. Фиксированного числового потолка баланса нет; остаются ограничения памяти, диска и размера HTTP-запроса (128 КиБ).

SQL-запросы с пользовательскими значениями параметризованы. Изменение денег и завершение раунда проходят в `BEGIN IMMEDIATE`; повторное или параллельное завершение не выдаёт вторую выплату. Чужие Origin и `Sec-Fetch-Site: cross-site` отклоняются для изменяющих запросов.

Проверки: `python -m unittest discover -s tests -v`, JavaScript: `node tests/check_frontend.cjs`. Покрыты SQL-инъекции, подмена суммы, повторная и параллельная выплата, сохранение огромного баланса и ошибки покерных комбинаций. Анимацию напёрстков нужно дополнительно проверить визуально в браузере: повторные раунды и изменение ширины окна.

### Напёрстки

Гостевая игра и аккаунт используют одну анимацию: шарик показывается 1,2 секунды, затем идут 28 перестановок: попарные обмены чередуются с одновременным движением трёх стаканов. Первые движения сохраняют прежнюю скорость, затем длительность сокращается с 220 до 45 мс, а финальная серия идёт без пауз. Сервер сохраняет начальное положение и последовательность перестановок; выплата соответствует фактическому финальному положению. При возвращении в незавершённый раунд показ повторяется без новой ставки. Шарик нарисован CSS и не зависит от шрифта эмодзи.

Это настоящее отслеживаемое перемешивание: последовательность доступна браузеру, поэтому скрипт может вычислить правильный ответ. Этот режим выбран явно; сервер продолжает проверять ставки, суммы выплат и однократность завершения раунда.

Браузерная проверка: задайте `BETON_CHROME` (путь к Chrome) и `BETON_NODE` (путь к Node.js), затем запустите `python -m unittest discover -s tests -p test_cups_browser.py -v`. Проверяются показ и скрытие шарика, повторные раунды гостя и аккаунта, правильная выплата при отслеживании стакана, изменение ширины окна и восстановление активного раунда. Скриншот сохраняется в `instance/cups-browser.png`.

### Сохранение больших балансов

Баланс и денежная статистика браузера сохраняются десятичными строками. При чтении старых сохранений также поддерживаются значения вида `1e+100`: они преобразуются в целое число без промежуточного JavaScript Number и без замены прогресса стартовым состоянием. Перед записью локального сохранения сохраняется его предыдущая корректная версия; при повреждении основной записи используется резервная.

Для аккаунтов источником баланса остаётся сервер: локальная резервная копия не используется для начисления денег. При запуске старые денежные значения SQLite в экспоненциальном формате приводятся к обычной десятичной записи без изменения суммы. Страница игры отдаётся с `Cache-Control: no-store`, чтобы браузер не сохранял устаревшую обработку больших чисел.

Проверен переход через триллион, выигрыш, повторный вход в аккаунт и перезагрузка страницы, включая суммы из 5001 цифры. Удалён прежний верхний CHECK у устаревшего числового поля в схеме новых баз; рабочие денежные значения хранятся в TEXT-полях `*_exact`. Фиксированного потолка баланса нет, остаются ограничения памяти и размера хранилища.

### Награды за задания и аварийный резерв

В аккаунте награды выдаёт сервер: `/api/quests/claim` проверяет игровую статистику и сохраняет отметку получения вместе с начислением денег в одной транзакции. Клиент не задаёт размер награды. Учитываются серверные бонусы заданий; повторные и параллельные запросы не дают дополнительной выплаты.

Для резерва `/api/refill/challenge` выдаёт уравнение с двухминутным сроком ответа, а `/api/refill/claim` проверяет одноразовый ответ. Резерв 5000 ₽ доступен при балансе не выше 500 ₽, без незавершённого раунда, с перерывом 10 минут (9 минут при серверном флаге `careful`). Отмена вопроса не начисляет деньги и не запускает перерыв. Неверный ответ погашает уравнение; можно запросить новое. Баланс и перерыв проверяются повторно при начислении, поэтому изменение данных в браузере не позволяет обойти условия.

Гостевая игра продолжает начислять эти награды локально. Проверки API находятся в `tests/test_rewards.py`, браузерная проверка кнопок, уравнения и сохранения начислений — в `tests/rewards_browser.html`.

Покупки аккаунта проходят через `/api/shop/buy`: сервер берёт цену из каталога, проверяет доступные средства и сохраняет предмет, списание и счётчик покупок одной транзакцией. Поэтому задание «Коллекционер» учитывает реальные покупки; подмена цены или повторная покупка того же предмета отклоняется.

В «Выше/ниже» одинаковый ранг считается верным ответом для обоих направлений, увеличивает счётчик успешных ходов и позволяет забрать выплату. Коэффициенты учитывают равенство в вероятности успеха; это также работает для двойки и туза. Неверное направление при отличающемся ранге по-прежнему завершает раунд проигрышем.
