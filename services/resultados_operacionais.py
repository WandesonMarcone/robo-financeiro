"""Classificação única do término das rotinas do robô.

O estado operacional é deliberadamente mais preciso que o resultado técnico do
processo no GitHub Actions: uma rotina pode terminar normalmente, mas ainda
deixar itens pendentes por falha de fonte ou de espelho.
"""

SUCESSO_TOTAL = "SUCESSO_TOTAL"
PARCIAL = "PARCIAL"
FALHOU = "FALHOU"


def classificar_resultado(*, processados=0, falhas=0, pendentes=0) -> str:
    """Retorna sucesso total, parcial ou falha sem inferir dados ausentes.

    ``pendentes`` abrange itens conhecidos que não puderam ser concluídos na
    rodada (por exemplo, documento sem fonte ou espelho do Sheets pendente).
    """
    processados = max(0, int(processados or 0))
    falhas = max(0, int(falhas or 0))
    pendentes = max(0, int(pendentes or 0))
    if not falhas and not pendentes:
        return SUCESSO_TOTAL
    if processados:
        return PARCIAL
    return FALHOU if falhas else PARCIAL
