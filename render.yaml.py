services:
  - type: web
    name: telegram-analytics-bot
    env: python
    region: frankfurt  # или oregon, singapore, ohio
    plan: free
    buildCommand: pip install -r requirements.txt
    startCommand: python app.py
    healthCheckPath: /health
    autoDeploy: true
    envVars:
      - key: BOT_TOKEN
        sync: false
      - key: ADMIN_IDS
        value: "123456789"  # замените на ваш Telegram ID
      - key: PORT
        value: "10000"
