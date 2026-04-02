@echo off
cd /d "C:\Users\DELL\Desktop\Ashwani study\EWOUR_CRM\crm-flask-htmx"
call crmenv\Scripts\activate
python -c "from app import app; app.run(debug=True, host='0.0.0.0', port=5000)"