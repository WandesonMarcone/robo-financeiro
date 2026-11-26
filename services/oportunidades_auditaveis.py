"""Persistência explicável da triagem de oportunidades no Neon."""
from __future__ import annotations

import json
from datetime import date
from sqlalchemy import text


def registrar(sessao, ticker, classe, referencia, elegivel, criterios, motivos,
              score=None, fonte="TRIAGEM_MERCADO"):
    """Registra aprovação ou reprovação; nunca transforma sinal em recomendação."""
    sessao.execute(text("""
        INSERT INTO oportunidades_triagem
          (ticker,classe,referencia_em,score,elegivel,motivos,criterios,fonte)
        VALUES (:ticker,:classe,:referencia,:score,:elegivel,
                CAST(:motivos AS jsonb),CAST(:criterios AS jsonb),:fonte)
        ON CONFLICT(ticker,classe,referencia_em,fonte) DO UPDATE SET
          score=EXCLUDED.score,elegivel=EXCLUDED.elegivel,motivos=EXCLUDED.motivos,
          criterios=EXCLUDED.criterios,criado_em=NOW()
    """), {"ticker": str(ticker).upper(), "classe": str(classe).upper(),
           "referencia": referencia or date.today(), "score": score,
           "elegivel": bool(elegivel), "motivos": json.dumps(motivos or [], ensure_ascii=False),
           "criterios": json.dumps(criterios or {}, ensure_ascii=False), "fonte": fonte})


def _limite_percentual(valor, limite):
    """Converte limites configurados como fração para a escala observada."""
    if limite is None:
        return None
    try:
        if float(limite) < 1 and valor is not None and float(valor) >= 1:
            return float(limite) * 100
    except (TypeError, ValueError):
        pass
    return limite


def motivos_acao(pl, pvp, dy, roe, liquidez, filtros):
    valores={"pl":pl,"pvp":pvp,"dy":dy,"roe":roe,"liquidez":liquidez}
    regras={"pl":[filtros.get("pl_min",3),filtros.get("pl_max",12)],
            "pvp":[filtros.get("pvp_min",.5),filtros.get("pvp_max",1.8)],
            "dy":[filtros.get("dy_min",.06),None],"roe":[filtros.get("roe_min",.1),None],
            "liquidez":[filtros.get("liquidez_min"),None]}
    motivos=[]
    for chave,valor in valores.items():
        minimo,maximo=regras[chave]
        try: numero=float(valor)
        except (TypeError,ValueError):
            motivos.append({"criterio":chave,"resultado":"SEM_DADO"}); continue
        if chave in {"dy", "roe"}:
            minimo = _limite_percentual(numero, minimo)
            maximo = _limite_percentual(numero, maximo)
        ok=(minimo is None or numero>=minimo) and (maximo is None or numero<=maximo)
        motivo={"criterio":chave,"resultado":"APROVADO" if ok else "REPROVADO","valor":numero,"minimo":minimo,"maximo":maximo}
        if chave in {"dy", "roe"}:
            motivo["unidade"]="percentual"
        motivos.append(motivo)
    return valores,motivos


def registrar_acoes_dataframe(df, filtros, referencia=None):
    """Espelha a triagem de ações no Neon sem bloquear o garimpo."""
    if df is None or getattr(df, "empty", True):
        return 0
    from atualizador_documentos import SessionDB
    from modules.relatorio_mercado import eh_oportunidade_acao
    sessao=SessionDB()
    try:
        if not sessao.execute(text("SELECT to_regclass('public.oportunidades_triagem')")).scalar():
            return 0
        total=0
        for ticker, linha in df.iterrows():
            criterios,motivos=motivos_acao(linha.get("P/L"),linha.get("P/VP"),linha.get("Div.Yield"),linha.get("ROE"),linha.get("Liq.2meses"),filtros)
            elegivel=eh_oportunidade_acao(criterios["pl"],criterios["pvp"],criterios["dy"],criterios["roe"],criterios["liquidez"],ticker,filtros)
            score=sum(1 for m in motivos if m["resultado"]=="APROVADO")
            registrar(sessao,ticker,"ACAO",referencia,elegivel,criterios,motivos,score)
            total+=1
        sessao.commit()
        return total
    except Exception:
        sessao.rollback()
        return 0
    finally:
        sessao.close()
