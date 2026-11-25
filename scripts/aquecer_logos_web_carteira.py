"""Importação explícita e limitada de logos, com aprovação de direito de uso."""
import argparse
import re
from sqlalchemy import text
from pipeline_dados.conexao import obter_session_factory
from services.portfolio_logos_web import cadastrar_logo

def executar(classe,tickers):
    from services.logo_service import (_resolver_drive_manager,_consultar_drive,
        obter_bytes_logo_drive,_obter_bytes_logo_dev,_salvar_no_drive)
    factory=obter_session_factory()
    gerente=_resolver_drive_manager(None)
    if gerente is None:
        raise RuntimeError("Drive indisponível")
    for ticker in tickers:
        try:
            with factory() as s:
                if classe=="stock":
                    if not s.execute(text("SELECT to_regclass('public.cadastro_cnpj_acoes')")).scalar():
                        raise ValueError("cadastro_oficial_ausente")
                    cnpj=s.execute(text("SELECT cnpj FROM cadastro_cnpj_acoes WHERE ticker=:ticker"),{"ticker":ticker}).scalar()
                    if not cnpj:
                        raise ValueError("identidade_oficial_ausente")
                    grupo=list(s.execute(text("SELECT ticker FROM cadastro_cnpj_acoes WHERE cnpj=:cnpj ORDER BY ticker"),{"cnpj":cnpj}).scalars())
                    chave=cnpj
                    tipo="ACAO"
                else:
                    existe=s.execute(text("SELECT 1 FROM ativos WHERE ticker=:ticker AND tipo::text='FII' UNION SELECT 1 FROM ativos_catalogo WHERE ticker=:ticker AND tipo='FII' LIMIT 1"),{"ticker":ticker}).scalar()
                    if not existe:
                        raise ValueError("fii_nao_cadastrado")
                    grupo=[ticker]; chave=ticker; tipo="FII"
            dados=None
            for candidato in dict.fromkeys([ticker,*grupo]):
                midia=_consultar_drive(candidato,tipo,gerente)
                if midia:
                    dados=obter_bytes_logo_drive(midia,gerente)
                    if dados:
                        break
            if not dados and classe=="stock":
                dados,mime=_obter_bytes_logo_dev(ticker)
                if dados:
                    _salvar_no_drive(ticker,tipo,dados,mime,gerente)
            if not dados:
                print(ticker,"sem_logo");continue
            with factory() as s:
                cadastrar_logo(s,classe,chave,grupo,dados)
                s.commit()
            print(ticker,"logo_aprovada_cacheada")
        except Exception as exc:
            print(ticker,type(exc).__name__)
if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--classe",choices=("stock","fii"),required=True)
    p.add_argument("--tickers",nargs="+",required=True)
    p.add_argument("--confirmo-direito-publicacao",action="store_true",required=True)
    a=p.parse_args()
    tickers=sorted({t.upper() for t in a.tickers})
    if len(tickers)>10 or any(not re.fullmatch(r"[A-Z0-9]{4,16}",t) for t in tickers):
        p.error("máximo de 10 tickers válidos")
    executar(a.classe,tickers)
