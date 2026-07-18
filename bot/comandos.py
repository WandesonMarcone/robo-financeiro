from sqlalchemy import func
from bot.loader import bot
from atualizador_documentos import SessionDB 
from pipeline_dados.banco_dados import Ativo, DocumentosQualitativos

# ==========================================
# 📊 COMANDOS DE PLANILHA DO GOOGLE
# ==========================================

# Permite adicionar um novo ativo direto na sua planilha do Drive via Telegram
@bot.message_handler(commands=['adicionar'])
def comando_adicionar(message):
    try:
        # Separa o comando da palavra. Ex: ["/adicionar", "BBAS3"]
        partes = message.text.split()
        if len(partes) < 2:
            bot.reply_to(message, "⚠️ Uso correto: `/adicionar TICKER` (ex: /adicionar BBAS3)", parse_mode="Markdown")
            return

        ticker = partes[1].strip().upper()
        bot.reply_to(message, f"A procurar {ticker} e a injetar na Planilha do Google...")

        # Conecta no Google Sheets
        planilha = conectar_gspread().open_by_url(config.SPREADSHEET_URL)

        # Inteligência simples: Se terminar em 11 é FII, se não é Ação.
        is_fii = True if ticker.endswith('11') else False
        nome_aba = "BD_FIIs" if is_fii else "BD_Acoes"
        aba = planilha.worksheet(nome_aba)

        # Encontra a última linha vazia da aba escolhida
        dados = aba.get_all_values()
        proxima_linha = len(dados) + 1

        # Insere o dado na planilha oficial
        aba.update(f'A{proxima_linha}', [[ticker]])

        bot.send_message(message.chat.id, f"✅ *{ticker}* adicionado com sucesso na aba `{nome_aba}`!", parse_mode="Markdown")
    except Exception as e:
        bot.reply_to(message, f"❌ Erro ao adicionar ativo: {e}")

# ==========================================
# ⚙️ COMANDOS DE MONITORAMENTO E STATUS
# ==========================================

# Comando /reciclar: Reativa documentos que foram descartados incorretamente no passado
@bot.message_handler(commands=['reciclar_rejeitados'])
def comando_reciclar_rejeitados(message):
    bot.send_message(message.chat.id, "♻️ Buscando documentos rejeitados no banco...")
    session = SessionDB()
    try:
        # Muda o status de rejeitado para pendente para uma nova tentativa de IA
        rejeitados = session.query(DocumentosQualitativos).filter(
            DocumentosQualitativos.status_processamento == 'REJEITADO_DUPLO_FATOR'
        ).all()

        contador = 0
        for doc in rejeitados:
            doc.status_processamento = 'PENDENTE' 
            contador += 1

        session.commit()
        bot.send_message(message.chat.id, f"✅ {contador} documentos foram devolvidos para a fila!")
    finally:
        session.close()

# ==========================================
# COMANDO SECRETO PARA TESTAR A VARREDURA
# ==========================================
@bot.message_handler(commands=['forcar_varredura'])
def acionar_varredura_manual(message):
    # 1. Responde instantaneamente para o Telegram e pro Render não darem Timeout
    bot.reply_to(message, "⚙️ *Iniciando varredura na B3 em segundo plano...*\nIsso pode levar alguns minutos. Pode continuar usando o bot normalmente, eu te aviso quando terminar!", parse_mode="Markdown")

    # 2. Cria a função pesada isolada
    def tarefa_pesada_background():
        try:
            from atualizador_documentos import rotina_de_atualizacao_em_massa
            relatorios_baixados = rotina_de_atualizacao_em_massa()

            # Quando terminar, envia uma nova mensagem avisando
            bot.send_message(message.chat.id, f"✅ *Varredura Concluída!*\n\n📥 Documentos inéditos salvos no Drive: **{relatorios_baixados}**", parse_mode="Markdown")
        except Exception as e:
            bot.send_message(message.chat.id, f"❌ *Erro na varredura:* {e}", parse_mode="Markdown")

    # 3. Dá a ordem para o Python rodar isso em uma trilha separada (Thread)
    thread = threading.Thread(target=tarefa_pesada_background)
    thread.start()

# ----------FORÇAR CVM------------
@bot.message_handler(commands=['forcar_cvm'])
def rodar_cvm(message):
    bot.send_message(message.chat.id, "⏳ Iniciando download de balanços da CVM. Isso pode demorar alguns minutos...")
    try:
        from coletor_cvm import AcoesCVMReader
        session = SessionDB()
        coletor = AcoesCVMReader(session)

        # Você pode mudar o ano aqui futuramente ou deixar dinâmico
        coletor.atualizar_acoes(2026) 

        session.close()
        bot.send_message(message.chat.id, "✅ Coleta CVM concluída! Balanços salvos no banco de dados.")
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Erro na CVM: {str(e)}")

# Varre todo o site da B3 para encontrar o "Nome Oficial" de todos os FIIs e salva em um arquivo de texto
@bot.message_handler(commands=['mapear_nomes'])
def comando_mapear_nomes_b3(message):
    import time
    import requests
    import threading # ⬅️ A CHAVE DA SOLUÇÃO (Permite rodar em segundo plano)

    # 1. O bot responde na mesma hora, acalmando o servidor do Telegram
    bot.send_message(message.chat.id, "🕵️‍♂️ Comando recebido! Como a B3 é lenta, enviei essa tarefa para o segundo plano. Pode continuar usando o Telegram normalmente, te enviarei o arquivo TXT assim que estiver pronto.")

    # 2. Definimos a tarefa pesada (A auditoria real que demora minutos)
    def tarefa_pesada():
        url = "https://fnet.bmfbovespa.com.br/fnet/publico/pesquisarGerenciadorDocumentosDados"
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36'}
        nomes_unicos = set()

        try:
            # Paginação de 50 em 50 documentos na API da B3
            for start in range(0, 5000, 50):
                params = {'d': '1', 's': str(start), 'l': '50', 'tipoFundo': '1'}

                sucesso = False
                for tentativa in range(3): # Tenta 3 vezes caso a B3 bloqueie a conexão
                    try:
                        res = requests.get(url, params=params, headers=headers, timeout=45)
                        res.raise_for_status() 
                        data = res.json().get('data', [])
                        sucesso = True
                        break 
                    except Exception as e:
                        time.sleep(2) 

                if not sucesso:
                    bot.send_message(message.chat.id, f"⚠️ Aviso: A B3 travou na página {start}. O arquivo será gerado com o que consegui até agora.")
                    break

                if not data:
                    break # Fim dos dados

                # Extrai o nome de cada fundo e adiciona no cofre sem repetições (Set)
                for item in data:
                    descricao = item.get('descricaoFundo', '').upper().strip()
                    if descricao:
                        nomes_unicos.add(descricao)

                time.sleep(1.5) # Pausa para não ser banido pela B3

            lista_ordenada = sorted(list(nomes_unicos))
            texto_final = "\n".join(lista_ordenada)

            caminho_arquivo = "/tmp/nomes_b3_auditoria.txt"

            # Gera o arquivo TXT físico com os resultados
            with open(caminho_arquivo, "w", encoding="utf-8") as f:
                f.write(f"--- CATÁLOGO DE NOMES DA B3 ({len(lista_ordenada)} fundos encontrados) ---\n\n")
                f.write(texto_final)

            # Envia o arquivo finalizado para o usuário no Telegram
            with open(caminho_arquivo, "rb") as f:
                bot.send_document(message.chat.id, f, caption="🎯 Auditoria concluída em segundo plano! Aqui está a lista exata da B3.")

        except Exception as e:
            bot.send_message(message.chat.id, f"❌ Erro crítico na thread de mapeamento: {str(e)}")

    # 3. Dispara a tarefa pesada em uma Thread separada (Background)
    thread = threading.Thread(target=tarefa_pesada)
    thread.start()
