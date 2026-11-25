"""Armazena fatos e indicadores por período, preservando metadados por métrica."""
from __future__ import annotations

import json
from datetime import date, datetime, timezone
from collections import defaultdict
from sqlalchemy import text

DDL = """
CREATE TABLE IF NOT EXISTS fundamentos_periodos (
    camada VARCHAR(20) NOT NULL,
    ticker VARCHAR(20) NOT NULL,
    classe VARCHAR(20) NOT NULL,
    periodo_fim DATE NOT NULL,
    exercicio INTEGER NOT NULL,
    periodicidade VARCHAR(20) NOT NULL,
    documento VARCHAR(20) NOT NULL DEFAULT '',
    itens JSONB NOT NULL,
    atualizado_em TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (camada,ticker,classe,periodo_fim,exercicio,periodicidade,documento),
    CHECK (camada IN ('fundamentos','indicadores')),
    CHECK (jsonb_typeof(itens) = 'object')
)
"""
CHAVES = ("ticker","classe","periodo_fim","exercicio","periodicidade","documento")
MINIMO_ANUAL = {"lucro_liquido","patrimonio_liquido","receita_liquida"}

def agrupar(registros, camada):
    grupos = {}
    agora = datetime.now(timezone.utc).isoformat()
    for item in registros:
        chave = tuple(str(item[k]) if k == "periodo_fim" else (item.get(k) or "") for k in CHAVES)
        grupo = grupos.setdefault(chave, dict(zip(CHAVES,chave), camada=camada,itens={}))
        dados = {k:v for k,v in item.items() if k not in CHAVES and k != "identificador"}
        dados.setdefault("atualizado_em",agora)
        if camada == "fundamentos":
            dados.setdefault("coletado_em",agora)
        grupo["itens"][item["identificador"]] = dados
    return list(grupos.values())

def json_itens(itens):
    return json.dumps(itens, default=str, ensure_ascii=False, allow_nan=False, separators=(",",":"))

def chave_planilha(grupo):
    return "|".join(str(grupo[k]) for k in CHAVES)

def anuais_validos(fundamentos, ano_corrente):
    campos = defaultdict(set)
    for item in fundamentos:
        if item["classe"] == "ACAO" and item["periodicidade"] == "ANUAL" and int(item["exercicio"]) < ano_corrente:
            campos[(item["ticker"],int(item["exercicio"]))].add(item["metrica"])
    return {chave for chave, metricas in campos.items() if MINIMO_ANUAL <= metricas}

def filtrar_historico(fundamentos, indicadores, ano_corrente):
    """Somente trimestres do exercício corrente na base ativa de ações."""
    def manter(item):
        return not (item["classe"] == "ACAO" and item["periodicidade"] == "TRIMESTRAL"
                    and int(item["exercicio"]) < ano_corrente)
    return [x for x in fundamentos if manter(x)], [x for x in indicadores if manter(x)]


def persistir_grupos(sessao, fundamentos, indicadores):
    grupos = agrupar(fundamentos,"fundamentos") + agrupar(indicadores,"indicadores")
    if grupos:
        sessao.execute(text("""
            INSERT INTO fundamentos_periodos(camada,ticker,classe,periodo_fim,exercicio,periodicidade,documento,itens)
            VALUES (:camada,:ticker,:classe,:periodo_fim,:exercicio,:periodicidade,:documento,CAST(:itens_json AS JSONB))
            ON CONFLICT(camada,ticker,classe,periodo_fim,exercicio,periodicidade,documento)
            DO UPDATE SET itens=fundamentos_periodos.itens || EXCLUDED.itens,atualizado_em=NOW()
        """), [dict(g,itens_json=json_itens(g["itens"])) for g in grupos])
    return len(grupos)

# Os nomes antigos continuam atendendo SELECTs da API e consultas administrativas.
# Não são usados para INSERT após a migração.
VIEW_FATOS = """
CREATE VIEW fundamentos_ativos AS
SELECT r.id, j.key::varchar(96) AS identificador, p.ticker, r.cnpj, p.classe,
       r.periodo_inicio, p.periodo_fim, p.exercicio, p.periodicidade, p.documento,
       r.escopo,r.demonstracao,r.conta_codigo,r.metrica,r.valor,r.unidade,r.moeda,
       r.fonte,r.qualidade_fonte,r.url_origem,r.coletado_em,r.atualizado_em
FROM fundamentos_periodos p CROSS JOIN LATERAL jsonb_each(p.itens) j
CROSS JOIN LATERAL jsonb_to_record(j.value) AS r(
    id bigint,cnpj varchar(14),periodo_inicio date,escopo varchar(20),
    demonstracao varchar(30),conta_codigo varchar(40),metrica varchar(80),
    valor numeric(30,8),unidade varchar(20),moeda varchar(8),fonte varchar(80),
    qualidade_fonte varchar(20),url_origem text,coletado_em timestamptz,atualizado_em timestamptz)
WHERE p.camada='fundamentos'
"""
VIEW_INDICADORES = """
CREATE VIEW indicadores_valuation_ativos AS
SELECT r.id,j.key::varchar(96) AS identificador,p.ticker,p.classe,p.periodo_fim,
       p.exercicio,p.periodicidade,r.indicador,r.valor,r.unidade,r.formula_versao,
       COALESCE(r.entradas,'{}'::jsonb) AS entradas,r.qualidade,r.atualizado_em
FROM fundamentos_periodos p CROSS JOIN LATERAL jsonb_each(p.itens) j
CROSS JOIN LATERAL jsonb_to_record(j.value) AS r(
    id bigint,indicador varchar(80),valor numeric(30,8),unidade varchar(20),
    formula_versao varchar(40),entradas jsonb,qualidade varchar(20),atualizado_em timestamptz)
WHERE p.camada='indicadores'
"""

def podar_trimestres(sessao, fundamentos, ano_corrente):
    # Aplica a política de retenção mesmo quando o DFP ainda não chegou.
    # Dados antigos da migração inicial permanecem no backup.
    sessao.execute(text("""
        DELETE FROM fundamentos_periodos
        WHERE classe='ACAO' AND periodicidade='TRIMESTRAL' AND exercicio<:ano
    """), {"ano":ano_corrente})


def migrar(session_factory=None, planilha=None, ano_corrente=None):
    """Migração transacional e idempotente; preserva originais para auditoria."""
    if session_factory is None:
        from pipeline_dados.conexao import obter_session_factory
        session_factory = obter_session_factory()
    ano_corrente = ano_corrente or date.today().year
    with session_factory() as s:
        s.execute(text("SELECT pg_advisory_xact_lock(260025)"))
        tipo = s.execute(text("SELECT relkind FROM pg_class WHERE oid=to_regclass('public.fundamentos_ativos')")).scalar()
        if tipo == "v":
            podar_trimestres(s,[],ano_corrente)
            s.commit()
            return {"status":"ja_migrado"}
        if tipo != "r":
            raise RuntimeError("base_original_ausente")
        s.execute(text("LOCK TABLE fundamentos_ativos, indicadores_valuation_ativos IN SHARE ROW EXCLUSIVE MODE"))
        f = [dict(r) for r in s.execute(text("SELECT * FROM fundamentos_ativos")).mappings()]
        i = [dict(r) for r in s.execute(text("SELECT * FROM indicadores_valuation_ativos")).mappings()]
        retidos_f,retidos_i = filtrar_historico(f,i,ano_corrente)
        from services.planilha_fundamentos_valuation import gravar_fundamentos_planilha
        gravar_fundamentos_planilha(retidos_f,retidos_i,[],planilha=planilha)
        s.execute(text(DDL))
        s.execute(text("CREATE INDEX IF NOT EXISTS idx_fundamentos_periodos_ticker ON fundamentos_periodos(ticker,periodo_fim DESC)"))
        persistir_grupos(s,retidos_f,retidos_i)
        s.execute(text("ALTER TABLE fundamentos_ativos RENAME TO fundamentos_ativos_backup_v1"))
        s.execute(text("ALTER TABLE indicadores_valuation_ativos RENAME TO indicadores_valuation_ativos_backup_v1"))
        s.execute(text(VIEW_FATOS))
        s.execute(text(VIEW_INDICADORES))
        for nome,original,camada in (("fundamentos_ativos",retidos_f,"fundamentos"),("indicadores_valuation_ativos",retidos_i,"indicadores")):
            lidos = {r[0]:str(r[1]) for r in s.execute(text(f"SELECT identificador,valor FROM {nome}"))}
            # O tipo numeric da view preserva a escala do original.
            esperados = {r["identificador"]:str(r["valor"]) for r in original}
            if lidos != esperados:
                raise RuntimeError(f"migracao_divergente:{camada}")
        grupos = s.execute(text("SELECT count(*) FROM fundamentos_periodos")).scalar()
        s.commit()
    return {"status":"migrado","fatos_anteriores":len(f),"fatos_retidos":len(retidos_f),
            "indicadores_anteriores":len(i),"indicadores_retidos":len(retidos_i),"linhas_consolidadas":grupos,
            "backups_preservados":True}
