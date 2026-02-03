services:
  - type: web
    name: telegram-bot-simple
    env: python
    region: frankfurt
    plan: free
    buildCommand: pip install -r requirements.txt
    startCommand: python app.py
    healthCheckPath: /health
    healthCheckTimeout: 180
    autoDeploy: true
    envVars:
      - key: BOT_TOKEN
        sync: false
      - key: PORT
        value: "10000"
