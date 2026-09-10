"""Fase 8.6: cobertura por campo de FII; placeholder nao e dado."""
from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from modules.scraper_fiis import interpretar_vacancia_html, montar_linha_fii
from pipeline_dados.banco_dados import (
    Ativo,
    AtivoPerfil,
    Base,
    DadosFinanceirosFiis,
    SnapshotFii,
    TipoAtivo,
)
from pipeline_dados.cobertura_fiis import (
    AUSENTE,
    DERIVADO,
    FONTE_INEXISTENTE,
    NAO_MAPEADO,
    PREENCHIDO,
    avaliar_campos_fii,
    campos_pendentes,
    cobertura_campos_fii,
    eh_placeholder_fii,
)
from pipeline_dados.espelhamento_mercado_5c import gravar_snapshot_fii
from pipeline_dados.freshness import FRESH, MISSING
from services.mercado import obter_cobertura_fii, obter_snapshots, obter_universo


def _sessao():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def test_placeholder_nao_e_dado_utilizavel():
    assert eh_placeholder_fii("Pendente de IA") is True
    assert eh_placeholder_fii("pendente") is True
    assert eh_placeholder_fii("12 meses") is False
    assert eh_placeholder_fii(None) is False


def test_5c_nao_persiste_placeholder_walt_alavancagem():
    session = _sessao()
    ativo = Ativo(ticker="MXRF11", cnpj=None, tipo=TipoAtivo.FII)
    session.add(ativo)
    session.flush()
    snap, _, status = gravar_snapshot_fii(
        session,
        ativo,
        {
            "ticker": "MXRF11",
            "preco": 9.87,
            "pvp": 0.95,
            "dy": 0.12,
            "qtd_imoveis": 0,
            "liquidez": 1500000.0,
            "vpa": 10.39,
            "lucro_12m": 1.0,
            "dividendo_mensal": 0.09,
            "walt": "Pendente de IA",
            "alavancagem": "Pendente de IA",
        },
        date(2026, 9, 3),
    )
    session.commit()
    assert status in ("CRIADO", "ATUALIZADO")
    assert snap.walt is None
    assert snap.alavancagem is None
    session.close()


def test_walt_real_persiste_quando_vier_da_fonte():
    session = _sessao()
    ativo = Ativo(ticker="HGLG11", cnpj=None, tipo=TipoAtivo.FII)
    session.add(ativo)
    session.flush()
    snap, _, _ = gravar_snapshot_fii(
        session,
        ativo,
        {
            "ticker": "HGLG11",
            "preco": 160.0,
            "walt": "4.5 anos",
            "alavancagem": "12%",
        },
        date(2026, 9, 3),
    )
    session.commit()
    assert snap.walt == "4.5 anos"
    assert snap.alavancagem == "12%"
    session.close()


def test_vacancia_html_nao_inventa_escala_sem_percentual():
    assert interpretar_vacancia_html("12,5%") == 0.125
    assert interpretar_vacancia_html("0%") == 0.0
    assert interpretar_vacancia_html("12,5") == 12.5
    assert interpretar_vacancia_html("-") is None
    assert interpretar_vacancia_html("") is None


def test_montar_linha_ainda_grava_placeholder_no_sheets():
    linha = montar_linha_fii(
        "MXRF11", "Papel", "CRI", 9.87, None, 0.95, 0.0, None,
        0, "Não informado / Não aplicável", None, None,
        None, None, 0.0, "02/09 10:00",
    )
    assert linha[10] == "Pendente de IA"
    assert linha[11] == "Pendente de IA"


def test_cobertura_por_campo_marca_preenchido_ausente_derivado():
    agora = datetime(2026, 9, 3, 12, 0, 0)
    session = _sessao()
    ativo = Ativo(ticker="MXRF11", cnpj=None, tipo=TipoAtivo.FII)
    session.add(ativo)
    session.flush()
    session.add(
        SnapshotFii(
            ativo_id=ativo.id,
            data_referencia=date(2026, 9, 3),
            data_coleta=agora - timedelta(minutes=10),
            preco=Decimal("9.87"),
            pvp=Decimal("0.95"),
            dy=Decimal("0.12"),
            vpa=Decimal("10.39"),
            lucro_12m=Decimal("1.0"),
            dividendo_mensal=Decimal("0.09"),
            qtd_imoveis=0,
            liquidez=Decimal("1500000"),
            walt=None,
            alavancagem=None,
        )
    )
    session.add(AtivoPerfil(ativo_id=ativo.id, setor="CRI", tipo_fii="Papel"))
    session.commit()
    rel = avaliar_campos_fii(session, ativo, agora=agora)
    assert rel["campos"]["preco"]["status"] == PREENCHIDO
    assert rel["campos"]["preco"]["freshness"] == FRESH
    assert rel["campos"]["qtd_imoveis"]["status"] == PREENCHIDO
    assert rel["campos"]["qtd_imoveis"]["valor"] == 0
    assert rel["campos"]["vpa"]["status"] == DERIVADO
    assert rel["campos"]["lucro_12m"]["status"] == DERIVADO
    assert rel["campos"]["dividendo_mensal"]["status"] == DERIVADO
    assert rel["campos"]["walt"]["status"] == FONTE_INEXISTENTE
    assert rel["campos"]["alavancagem"]["status"] == FONTE_INEXISTENTE
    assert rel["campos"]["vacancia"]["status"] == NAO_MAPEADO
    assert rel["campos"]["numero_cotas"]["status"] == NAO_MAPEADO
    assert rel["campos"]["valor_mercado"]["status"] == NAO_MAPEADO
    assert rel["campos"]["patrimonio_liquido"]["status"] == AUSENTE
    assert rel["campos"]["vacancia_fisica"]["status"] == FONTE_INEXISTENTE
    assert rel["campos"]["rendimento_por_cota"]["status"] == FONTE_INEXISTENTE
    assert rel["resumo"]["percentual_preenchido"] is not None
    assert 0 <= rel["resumo"]["percentual_preenchido"] <= 1
    session.close()


def test_contabil_cvm_preenchido_nao_mascara_campo_sem_fonte():
    agora = datetime(2026, 9, 3, 12, 0, 0)
    session = _sessao()
    ativo = Ativo(ticker="GARE11", cnpj=None, tipo=TipoAtivo.FII)
    session.add(ativo)
    session.flush()
    session.add(
        DadosFinanceirosFiis(
            ativo_id=ativo.id,
            data_referencia=date(2026, 1, 1),
            data_coleta=agora - timedelta(days=10),
            patrimonio_liquido=1000.0,
            cotas_emitidas=500.0,
            cotistas=10,
        )
    )
    session.commit()
    rel = avaliar_campos_fii(session, ativo, agora=agora)
    assert rel["campos"]["patrimonio_liquido"]["status"] == PREENCHIDO
    assert rel["campos"]["cotas_emitidas"]["status"] == PREENCHIDO
    assert rel["campos"]["preco"]["status"] == AUSENTE
    assert rel["campos"]["preco"]["freshness"] == MISSING
    assert rel["campos"]["vacancia_financeira"]["status"] == FONTE_INEXISTENTE
    assert rel["campos"]["valor_patrimonial_cotas"]["status"] == AUSENTE
    assert rel["campos"]["percentual_dividend_yield_mes"]["status"] == AUSENTE
    assert rel["campos"]["receita_imoveis"]["status"] == AUSENTE
    assert rel["campos"]["despesas_taxas"]["status"] == AUSENTE
    assert rel["campos"]["resultado_ligado_venda"]["status"] == FONTE_INEXISTENTE
    session.close()


def test_cobertura_nao_expande_universo():
    session = _sessao()
    rel = cobertura_campos_fii(session)
    assert rel["tipo"] == "FII"
    assert "walt" in rel["pendentes"]
    assert "alavancagem" in rel["pendentes"]
    assert "vacancia_fisica" in campos_pendentes()
    assert "resultado_ligado_venda" in campos_pendentes()
    assert "receita_imoveis" not in campos_pendentes()
    assert "despesas_taxas" not in campos_pendentes()
    session.close()


def test_servico_mercado_expoe_cobertura_fii_sem_alterar_contrato():
    session = _sessao()
    ativo = Ativo(ticker="MXRF11", cnpj=None, tipo=TipoAtivo.FII)
    session.add(ativo)
    session.flush()
    session.add(
        SnapshotFii(
            ativo_id=ativo.id,
            data_referencia=date(2026, 9, 3),
            data_coleta=datetime(2026, 9, 3, 10, 0, 0),
            preco=Decimal("9.87"),
        )
    )
    session.commit()
    rel = obter_cobertura_fii(ticker="MXRF11", session=session)
    assert rel["avaliados"] == ["MXRF11"]
    assert rel["por_ticker"]["MXRF11"]["campos"]["preco"]["status"] == PREENCHIDO
    assert callable(obter_snapshots)
    assert callable(obter_universo)
    session.close()
