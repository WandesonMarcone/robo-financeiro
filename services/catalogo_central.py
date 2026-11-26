"""Espelho do universo oficial no catálogo central do Neon.

O ticker continua sendo a chave de negociação e o CNPJ identifica o emissor.
Classes diferentes da mesma companhia (por exemplo, PETR3 e PETR4) portanto
podem coexistir sem que uma substitua a outra. Esta rotina é aditiva: nunca
remove ativos, snapshots, documentos ou vínculos históricos.
"""
from __future__ import annotations

from sqlalchemy import text


def espelhar_acoes_oficiais(sessao):
    """Atualiza o catálogo a partir da lista autorizada e da FCA/CVM.

    A planilha determina quais tickers podem entrar no universo. A FCA somente
    preenche identidade, nome e setor quando houver evidência oficial. Assim,
    uma indisponibilidade temporária da FCA não apaga um ticker já autorizado.
    """
    resultado = sessao.execute(text("""
        INSERT INTO ativos_catalogo
          (ticker,tipo,cnpj,nome_emissor,setor,fonte,data_atualizacao)
        SELECT u.ticker,
               'ACAO',
               co.cnpj,
               co.nome_emissor,
               co.setor,
               CASE WHEN co.ticker IS NULL THEN 'GOOGLE_SHEETS_LISTA_OFICIAL'
                    ELSE 'CVM_FCA' END,
               NOW()
          FROM universo_acoes_autorizadas u
          LEFT JOIN cadastro_cnpj_acoes co ON co.ticker=u.ticker
        ON CONFLICT (ticker) DO UPDATE SET
          tipo=EXCLUDED.tipo,
          cnpj=COALESCE(EXCLUDED.cnpj,ativos_catalogo.cnpj),
          nome_emissor=COALESCE(EXCLUDED.nome_emissor,ativos_catalogo.nome_emissor),
          setor=COALESCE(EXCLUDED.setor,ativos_catalogo.setor),
          fonte=EXCLUDED.fonte,
          data_atualizacao=EXCLUDED.data_atualizacao
    """))
    # Mantém uma identidade por CNPJ e um vínculo por ticker, sem tocar no
    # cadastro legado de ``ativos`` (onde CNPJ ainda é único por compatibilidade).
    sessao.execute(text("""
        INSERT INTO empresas (cnpj,nome,razao_social,fonte,criado_em,atualizado_em)
        SELECT DISTINCT co.cnpj,co.nome_emissor,co.nome_emissor,'CVM_FCA',NOW(),NOW()
          FROM universo_acoes_autorizadas u
          JOIN cadastro_cnpj_acoes co ON co.ticker=u.ticker
         WHERE co.cnpj IS NOT NULL AND co.nome_emissor IS NOT NULL
        ON CONFLICT (cnpj) DO UPDATE SET
          nome=EXCLUDED.nome,razao_social=EXCLUDED.razao_social,
          fonte=EXCLUDED.fonte,atualizado_em=NOW()
    """))
    sessao.execute(text("""
        INSERT INTO empresa_ativos (empresa_id,ativo_id,fonte,evidencia,criado_em)
        SELECT e.id,a.id,'CVM_FCA','vínculo por ticker e CNPJ oficial',NOW()
          FROM universo_acoes_autorizadas u
          JOIN cadastro_cnpj_acoes co ON co.ticker=u.ticker
          JOIN empresas e ON e.cnpj=co.cnpj
          JOIN ativos a ON a.ticker=u.ticker
        ON CONFLICT (ativo_id) DO UPDATE SET
          empresa_id=EXCLUDED.empresa_id,fonte=EXCLUDED.fonte,
          evidencia=EXCLUDED.evidencia
    """))
    return {"catalogo_afetado": int(resultado.rowcount or 0)}
