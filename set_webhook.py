import requests

TOKEN = "7777811765:AAEk3XQibBBYSFKRfQLzOWs_KpGOcPFR274"
URL_RENDER = "https://robo-financeiro-7wkd.onrender.com" # <--- COLOQUE AQUI A URL DO SEU RENDER

webhook_url = f"https://api.telegram.org/bot{TOKEN}/setWebhook?url={URL_RENDER}/{TOKEN}"

response = requests.get(webhook_url)
print(response.json())
