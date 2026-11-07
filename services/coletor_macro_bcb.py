"""Coleta oficial e idempotente de séries BCB/SGS para a Central."""
from datetime import datetime, timedelta
import requests
from sqlalchemy import text

SERIES_SGS = {
    "SELIC_EFETIVA": (11, "Selic efetiva", "TAXA", "BCB/SGS 11", "DIARIA", "OFICIAL", "após divulgação BCB"),
    "SELIC_META": (432, "Meta Selic", "TAXA", "BCB/SGS 432", "DIARIA", "OFICIAL", "decisão Copom"),
    "CDI": (12, "CDI", "TAXA", "BCB/SGS 12 (CETIP)", "DIARIA", "OFICIAL", "fechamento"),
    # Série mensal de variação do IPCA. A data de referência é preservada tal
    # como divulgada pelo BCB; nunca é transformada em cotação intradiária.
    "IPCA": (433, "IPCA - variação mensal", "INFLACAO", "BCB/SGS 433", "MENSAL", "OFICIAL", "divulgação mensal"),
    "USD_BRL_PTAX": (1, "Dólar PTAX (venda)", "MOEDA", "BCB/SGS 1", "DIARIA", "OFICIAL", "fechamento PTAX"),
}

def coletar_bcb(dias=10, session_factory=None):
    """Busca janela curta e faz upsert; não inventa valor quando BCB não responde."""
    from atualizador_documentos import SessionDB
    session = session_factory() if session_factory else SessionDB()
    resultado = {"fonte": "BCB/SGS", "series": {}, "falhas": []}
    inicio = (datetime.now() - timedelta(days=max(1, min(int(dias), 365)))).strftime("%d/%m/%Y")
    fim = datetime.now().strftime("%d/%m/%Y")
    try:
        for codigo, (sgs, nome, classe, fonte, periodicidade, tipo, horario) in SERIES_SGS.items():
            try:
                # Um savepoint por série evita que a falha de uma fonte mensal
                # desfaça Selic/CDI/PTAX já recebidos no mesmo ciclo.
                with session.begin_nested():
                    serie_id = session.execute(text("""
                    INSERT INTO series_mercado (codigo,nome,classe,fonte,periodicidade,tipo_valor,horario_referencia)
                    VALUES (:codigo,:nome,:classe,:fonte,:periodicidade,:tipo,:horario)
                    ON CONFLICT (codigo) DO UPDATE SET nome=EXCLUDED.nome, fonte=EXCLUDED.fonte, atualizado_em=NOW()
                    RETURNING id
                    """), {"codigo":codigo,"nome":nome,"classe":classe,"fonte":fonte,"periodicidade":periodicidade,"tipo":tipo,"horario":horario}).scalar_one()
                    # IPCA é mensal: uma janela maior impede que o painel pareça
                    # vazio nos dias posteriores à divulgação do mês.
                    inicio_serie = (
                        (datetime.now() - timedelta(days=65)).strftime("%d/%m/%Y")
                        if codigo == "IPCA" else inicio
                    )
                    url=f"https://api.bcb.gov.br/dados/serie/bcdata.sgs.{sgs}/dados?formato=json&dataInicial={inicio_serie}&dataFinal={fim}"
                    response=requests.get(url,timeout=20); response.raise_for_status(); linhas=response.json()
                    gravadas=0
                    for item in linhas:
                        data=datetime.strptime(item["data"], "%d/%m/%Y")
                        valor=float(str(item["valor"]).replace(",", "."))
                        session.execute(text("""
                        INSERT INTO observacoes_mercado (serie_id,referencia_em,valor,origem)
                        VALUES (:serie,:referencia,:valor,'BCB/SGS')
                        ON CONFLICT (serie_id,referencia_em) DO UPDATE SET valor=EXCLUDED.valor, origem=EXCLUDED.origem, coletado_em=NOW()
                        """), {"serie":serie_id,"referencia":data,"valor":valor}); gravadas+=1
                resultado["series"][codigo]={"gravadas":gravadas,"ultima_referencia":linhas[-1]["data"] if linhas else None}
            except Exception as exc:
                resultado["falhas"].append({"serie":codigo,"erro":type(exc).__name__})
        session.commit()
        return resultado
    finally:
        session.close()
