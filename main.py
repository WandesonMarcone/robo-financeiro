import pandas as pd
import requests
import io

url = "https://www.fundamentus.com.br/resultado.php"
df = pd.read_html(io.StringIO(requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}).text), decimal=',', thousands='.')[0]
print("Nomes das colunas encontradas no Fundamentus:")
print(df.columns.tolist())