@echo off
cd /d "C:\Users\DELL\Desktop\Ashwani study\EWOUR_CRM\crm-flask-htmx"
call crmenv\Scripts\activate
python -m waitress --host=0.0.0.0 --port=5000 app:app