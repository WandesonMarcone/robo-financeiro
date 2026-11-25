"""Cadastro por ticker da CVM: um emissor pode ter várias classes de ação."""
from __future__ import annotations

import re
from datetime import date

from sqlalchemy import text, inspect

DDL = """
CREATE TABLE IF NOT EXISTS cadastro_cnpj_acoes (
    ticker VARCHAR(20) PRIMARY KEY,
    cnpj VARCHAR(14) NOT NULL,
    nome_emissor TEXT,
    setor TEXT,
    codigo_cvm TEXT,
    fonte TEXT NOT NULL,
    referencia_fonte TEXT,
    validado_em TIMESTAMPTZ NOT NULL DEFAULT NOW()
)
"""

def cnpj_valido(valor):
    digitos = re.sub(r"[^0-9]", "", str(valor or ""))
    if len(digitos) != 14 or len(set(digitos)) == 1:
        return None
    for tamanho, pesos in ((12, (5,4,3,2,9,8,7,6,5,4,3,2)),
                           (13, (6,5,4,3,2,9,8,7,6,5,4,3,2))):
        resto = sum(int(d)*p for d,p in zip(digitos[:tamanho], pesos)) % 11
        if int(digitos[tamanho]) != (0 if resto < 2 else 11-resto):
            return None
    return digitos

def extrair_cadastro(geral, valores):
    from pipeline_dados.coletor_catalogo_cvm import (
        _selecionar_mais_recente, _texto, _sem_acento, _mercado_valido,
    )
    coluna_tipo = "Valor_Mobiliario" if "Valor_Mobiliario" in valores.columns else "Tipo"
    obrigatorias = {"CNPJ_Companhia", "Codigo_Negociacao", coluna_tipo, "Data_Fim_Negociacao"}
    if not obrigatorias.issubset(valores.columns) or not {"CNPJ_Companhia","Nome_Empresarial"}.issubset(geral.columns):
        raise ValueError("layout_FCA_nao_reconhecido")
    geral = geral.copy()
    valores = valores.copy()
    geral["CNPJ_Companhia"] = geral["CNPJ_Companhia"].map(cnpj_valido)
    valores["CNPJ_Companhia"] = valores["CNPJ_Companhia"].map(cnpj_valido)
    valores["Codigo_Negociacao"] = valores["Codigo_Negociacao"].map(lambda x: _texto(x).upper())
    empresas = {}
    for _, linha in _selecionar_mais_recente(geral, ["CNPJ_Companhia"]).iterrows():
        cnpj = linha["CNPJ_Companhia"]
        if not cnpj or not _texto(linha.get("Nome_Empresarial")):
            continue
        empresas[cnpj] = {
            "cnpj": cnpj, "nome_emissor": _texto(linha.get("Nome_Empresarial")),
            "setor": _texto(linha.get("Setor_Atividade")) or None,
            "codigo_cvm": _texto(linha.get("Codigo_CVM")) or _texto(linha.get("CD_CVM")) or None,
        }
    candidatos = {}
    for _, linha in _selecionar_mais_recente(valores, ["CNPJ_Companhia","Codigo_Negociacao"]).iterrows():
        cnpj, ticker = linha["CNPJ_Companhia"], linha["Codigo_Negociacao"]
        if cnpj not in empresas or not re.fullmatch(r"[A-Z]{4}[0-9]{1,2}", ticker):
            continue
        tipo = _sem_acento(linha.get(coluna_tipo))
        if not tipo or not any(t in tipo for t in ("acao","acoes","unit")) or any(t in tipo for t in ("bdr","debenture","recibo","direito")):
            continue
        if not _mercado_valido(linha.get("Mercado")) or _texto(linha.get("Data_Fim_Negociacao")):
            continue
        candidatos.setdefault(ticker, {})[cnpj] = dict(empresas[cnpj], ticker=ticker, referencia_fonte=_texto(linha.get("Data_Referencia")) or None)
    ambiguos = sorted(t for t,v in candidatos.items() if len(v)!=1)
    return {t:next(iter(v.values())) for t,v in candidatos.items() if len(v)==1}, ambiguos

def ler_cadastro(sessao):
    # Compatibilidade durante a implantação e com os testes legados.
    bind = sessao.get_bind()
    if bind.dialect.name != "postgresql":
        return {}
    if not inspect(bind).has_table("cadastro_cnpj_acoes"):
        return {}
    return {r["ticker"]: dict(r) for r in sessao.execute(text(
        "SELECT ticker,cnpj,nome_emissor,setor,codigo_cvm,fonte,referencia_fonte,validado_em FROM cadastro_cnpj_acoes"
    )).mappings()}

def consultar_ticker(sessao, ticker):
    bind = sessao.get_bind()
    if bind.dialect.name != "postgresql" or not inspect(bind).has_table("cadastro_cnpj_acoes"):
        return None
    r = sessao.execute(text("SELECT ticker,cnpj,nome_emissor,setor,codigo_cvm,fonte FROM cadastro_cnpj_acoes WHERE ticker=:ticker"), {"ticker": ticker}).mappings().first()
    return dict(r) if r else None


def combinar_mapas_oficiais(mapas_por_ano):
    """Une FCA(s) com precedência do ano atual, sem escolher ambiguidade."""
    mapa, referencias, ambiguos = {}, {}, set()
    for ano, mapa_ano, ambiguos_ano, fonte in mapas_por_ano:
        for ticker, cadastro in mapa_ano.items():
            if ticker not in mapa:
                mapa[ticker] = cadastro
                referencias[ticker] = {"ano": ano, "fonte": fonte}
        ambiguos.update(ambiguos_ano)
    for ticker in ambiguos:
        mapa.pop(ticker, None)
        referencias.pop(ticker, None)
    return mapa, referencias, ambiguos

def sincronizar(session_factory=None, planilha=None, coletor=None, hoje=None,
                anos_retroativos=3):
    if session_factory is None:
        from pipeline_dados.conexao import obter_session_factory
        session_factory = obter_session_factory()
    if planilha is None:
        from services.planilha_fundamentos_valuation import _planilha_padrao
        planilha = _planilha_padrao()
    if coletor is None:
        from pipeline_dados.coletor_catalogo_cvm import ColetorCatalogoCVM
        coletor = ColetorCatalogoCVM()
    universo = {str(x).strip().upper() for x in planilha.worksheet("BD_Acoes").col_values(1)[1:]
                if re.fullmatch(r"[A-Z]{4}[0-9]{1,2}", str(x).strip().upper())}
    with session_factory() as s:
        universo.update(r[0].upper() for r in s.execute(text("""
            SELECT ticker FROM ativos WHERE tipo::text='ACAO'
            UNION SELECT ticker FROM ativos_catalogo WHERE tipo::text='ACAO'
        """)) if r[0])
    hoje = hoje or date.today()
    # A FCA do ano corrente pode ainda não trazer uma companhia recém-listada,
    # em reorganização societária ou com a publicação pendente. Nunca usamos o
    # mapa manual: procuramos somente arquivos FCA oficiais anteriores e
    # mantemos a referência de qual arquivo confirmou cada vínculo.
    mapas_por_ano = []
    erros_fontes = []
    for ano in range(hoje.year, max(hoje.year - int(anos_retroativos), 2000) - 1, -1):
        try:
            geral, valores, fonte = coletor.baixar_dataframes(ano)
            mapa_ano, ambiguos_ano = extrair_cadastro(geral, valores)
            print(f"FCA {ano}: {len(geral)} emissores/linhas, {len(valores)} valores, {len(mapa_ano)} vínculos, {len(ambiguos_ano)} ambiguidades; colunas={list(valores.columns)}")
            if mapa_ano:
                mapas_por_ano.append((ano, mapa_ano, set(ambiguos_ano), fonte))
            else:
                erros_fontes.append({"ano": ano, "erro": "SEM_VINCULOS"})
        except Exception as exc:
            erros_fontes.append({"ano": ano, "erro": type(exc).__name__})
            print(f"FCA {ano}: {type(exc).__name__}: {str(exc)[:200]}")
    if not mapas_por_ano:
        raise ValueError(f"FCA_sem_vinculos_validos: {erros_fontes}")
    # O ano mais recente tem precedência; o histórico apenas preenche o que
    # não foi localizado nele. Ambiguidade nunca é resolvida por chute.
    mapa, referencias, ambiguos = combinar_mapas_oficiais(mapas_por_ano)
    selecionados = sorted(universo & set(mapa))
    if not selecionados:
        raise ValueError("FCA_sem_correspondencias_no_universo")
    with session_factory() as s:
        s.execute(text(DDL))
        anteriores = {r["ticker"]: r["cnpj"] for r in s.execute(text("SELECT ticker,cnpj FROM cadastro_cnpj_acoes")).mappings()}
        # Uma transação, sem modificar tabelas com unicidade legada do CNPJ.
        s.execute(text("""
            INSERT INTO cadastro_cnpj_acoes(ticker,cnpj,nome_emissor,setor,codigo_cvm,fonte,referencia_fonte)
            VALUES (:ticker,:cnpj,:nome_emissor,:setor,:codigo_cvm,:fonte,:referencia_fonte)
            ON CONFLICT(ticker) DO UPDATE SET cnpj=EXCLUDED.cnpj,
              nome_emissor=EXCLUDED.nome_emissor,setor=EXCLUDED.setor,
              codigo_cvm=EXCLUDED.codigo_cvm,fonte=EXCLUDED.fonte,
              referencia_fonte=EXCLUDED.referencia_fonte,validado_em=NOW()
        """), [dict(mapa[t], fonte=referencias[t]["fonte"],
                     referencia_fonte=f'{referencias[t]["fonte"]}#ano={referencias[t]["ano"]}')
               for t in selecionados])
        # Reprioriza apenas ativos cuja identidade mudou ou passou a existir.
        # A fila pode ainda não existir na primeira instalação.
        fila_existe = s.execute(text("SELECT to_regclass('public.fila_fundamentos_acoes')")).scalar()
        mudaram = [t for t in selecionados if anteriores.get(t)!=mapa[t]["cnpj"]]
        if fila_existe and mudaram:
            s.execute(text("""
                UPDATE fila_fundamentos_acoes SET proxima_tentativa=NOW()
                WHERE ticker=:ticker AND estado<>'EM_COLETA'
            """), [{"ticker":t} for t in mudaram])
        s.commit()
    return {"universo":len(universo), "confirmados":len(selecionados),
            "novos":sum(t not in anteriores for t in selecionados),
            "alterados":[t for t in mudaram if t in anteriores],
            "nao_localizados":sorted(universo-set(selecionados)),
            "ambiguos":sorted(universo & set(ambiguos)),
            "fontes_consultadas": [item[3] for item in mapas_por_ano],
            "falhas_fontes": erros_fontes}
