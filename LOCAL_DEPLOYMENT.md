# Local Office Deployment

This project can be run for your organization on one Windows PC inside the same Wi-Fi or LAN.

## What you need

- One Windows PC that stays ON
- Python 3.11+ installed
- MySQL Server installed
- All users connected to the same office Wi-Fi or LAN

## 1. Create the database

Open MySQL and create the database:

```sql
CREATE DATABASE crm_db;
```

## 2. Create your environment file

Copy `.env.example` to `.env` and update the values:

```env
SECRET_KEY=put-a-long-random-secret-here
DB_HOST=localhost
DB_PORT=3306
DB_USER=root
DB_PASSWORD=your-mysql-password
DB_NAME=crm_db
APP_HOST=0.0.0.0
APP_PORT=5000
FLASK_DEBUG=false
```

## 3. Install Python packages

Open PowerShell in the project folder:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## 4. Run the app

For normal local office use:

```powershell
.\.venv\Scripts\Activate.ps1
python app.py
```

## 5. Find the office PC IP

Run:

```powershell
ipconfig
```

Look for the IPv4 address, for example:

```text
192.168.1.20
```

Other users on the same Wi-Fi can open:

```text
http://192.168.1.20:5000
```

## 6. Allow Windows Firewall

Allow inbound TCP port `5000` in Windows Defender Firewall so other office devices can connect.

## 7. Make it more stable

- Give the server PC a static local IP in your router
- Keep MySQL set to start automatically
- Keep the CRM PC plugged in and sleep disabled
- Use a strong MySQL password
- Keep `FLASK_DEBUG=false`

## Recommended next step

For better reliability on Windows, run the app with Waitress instead of the Flask development server:

```powershell
.\.venv\Scripts\Activate.ps1
python -m waitress --host=0.0.0.0 --port=5000 app:app
```

That is better for daily office use than `python app.py`.
