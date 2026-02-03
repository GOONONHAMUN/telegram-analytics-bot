services:
  - type: web
    name: telegram-analytics-bot
    env: python
    region: frankfurt
    plan: free
    buildCommand: pip install -r requirements.txt
    startCommand: python app.py
    healthCheckPath: /health
    autoDeploy: true
    envVars:
      - key: BOT_TOKEN
        sync: false
      - key: API_ID
        sync: false
      - key: API_HASH
        sync: false
      - key: ADMIN_IDS
        value: "123456789"  # Замените на ваш ID
      - key: PORT
        value: "10000"
