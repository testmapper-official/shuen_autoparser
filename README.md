[Русский](#русский) | [English](#english)

---

## Русский

# Shuen Auto - WC3 Backup Manager

Локальное веб-приложение для управления профилями и бэкапами сервера Warcraft III Shuen (1.27a). Автоматизирует процесс парсинга, сохранения и восстановления данных профиля с сервера `shuen.ddns.net`, а также упрощает запуск игры.

## ✨ Основные возможности

- **Автоматический парсинг:** Фоновый запрос на сервер каждые N минут (настраивается от 1 до 30 минут). При любом изменении JSON-объекта создается локальный бэкап.
- **Управление бэкапами:** Просмотр, удаление, переименование и восстановление бэкапов на сервер напрямую из интерфейса.
- **Лаунчер:** Запуск `KKWE - Launch 1.27.bat` с автоматическим определением рабочей директории.

## 🛠 Установка и запуск

У вас есть два способа запустить приложение: использовать готовый скомпилированный релиз (не требует установки Python) или запустить из исходного кода.

### Вариант 1: Скомпилированный релиз (Рекомендуется)

1. Перейдите во вкладку **Releases** на странице репозитория.
2. Найдите последний релиз и скачайте прикрепленный архив `.zip` (например, `ShuenAuto.zip`).
3. Распакуйте архив в любую удобную для вас папку на вашем компьютере.
4. Запустите файл `Shuen Auto.exe`. 
5. Приложение автоматически запустит локальный сервер и откроет интерфейс в вашем браузере по умолчанию.

*Примечание: Поскольку приложение не имеет цифровой подписи издателя, при первом запуске Windows SmartScreen может показать предупреждение. Нажмите "Подробнее" -> "Выполнить в любом случае". Консольное окно, которое откроется вместе с браузером, не закрывайте — оно работает в фоновом режиме.*

### Вариант 2: Из исходного кода (Для разработчиков)

1. Убедитесь, что у вас установлен **Python 3.8** или выше.
2. Клонируйте или скачайте репозиторий в любую папку.
3. Откройте терминал в папке проекта и установите необходимые зависимости:

pip install flask requests beautifulsoup4 apscheduler waitress

4. Запустите приложение:

python app.py

5. Браузер откроется автоматически. Если этого не произошло, перейдите по адресу: http://localhost:5000

## 📖 Первый запуск

При первом запуске приложение заблокирует интерфейс и предложит пройти 2 обязательных шага:

1. **Шаг 1: Настройка профиля** — Введите имя профиля и пароль от сервера Shuen. Приложение проверит существование профиля и валидность пароля.
2. **Шаг 2: Путь Warcraft III** — Укажите путь к файлу `KKWE - Launch 1.27.bat` через стандартное окно выбора Windows.

После успешного прохождения шагов интерфейс разблокируется.

## 📄 Лицензия

Этот проект распространяется под лицензией Creative Commons Attribution-NonCommercial 4.0 International (CC BY-NC 4.0). Подробности смотрите в файле LICENSE.

---

## English

# Shuen Auto - WC3 Backup Manager

A local web application for managing profiles and backups for the Warcraft III Shuen server (1.27a). It automates the process of parsing, saving, and restoring profile data from the `shuen.ddns.net` server, and also simplifies launching the game.

## ✨ Features

- **Automatic Parsing:** A background request to the server every N minutes (configurable from 1 to 30 minutes). If any change in the JSON object occurs, a local backup is created.
- **Backup Management:** View, delete, rename, and restore backups to the server directly from the interface.
- **Launcher:** Launch `KKWE - Launch 1.27.bat` with automatic working directory detection.

## 🛠 Installation and Launch

You have two ways to run the application: use a pre-compiled release (does not require Python installation) or run from source code.

### Option 1: Pre-compiled Release (Recommended)

1. Go to the **Releases** tab on the repository page.
2. Find the latest release and download the attached `.zip` archive (e.g., `ShuenAuto.zip`).
3. Extract the archive to any convenient folder on your computer.
4. Run the `Shuen Auto.exe` file.
5. The application will automatically start the local server and open the interface in your default browser.

*Note: Since the application does not have a publisher digital signature, Windows SmartScreen may show a warning on the first launch. Click "More info" -> "Run anyway". Do not close the console window that opens alongside the browser — it runs in the background.*

### Option 2: From Source Code (For Developers)

1. Make sure you have **Python 3.8** or higher installed.
2. Clone or download the repository to any folder.
3. Open a terminal in the project folder and install the required dependencies:

pip install flask requests beautifulsoup4 apscheduler waitress

4. Run the application:

python app.py

5. The browser will open automatically. If this does not happen, go to: http://localhost:5000

## 📖 First Launch

On the first launch, the application will lock the interface and prompt you to complete 2 mandatory steps:

1. **Step 1: Profile Setup** — Enter your profile name and password for the Shuen server. The application will check the profile's existence and password validity.
2. **Step 2: Warcraft III Path** — Specify the path to the `KKWE - Launch 1.27.bat` file using the standard Windows file selection dialog.

After successfully completing the steps, the interface will be unlocked.

## 📄 License

This project is licensed under the Creative Commons Attribution-NonCommercial 4.0 International (CC BY-NC 4.0). See the LICENSE file for details.
