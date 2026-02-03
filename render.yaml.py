services:
  - type: web
    name: telegram-analytics-bot
    env: python
    region: frankfurt
    plan: free
    buildCommand: pip install -r requirements.txt
    startCommand: python app.py  # ВАЖНО: python app.py, не gunicorn!
    healthCheckPath: /health
    autoDeploy: true

