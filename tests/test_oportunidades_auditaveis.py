from services.oportunidades_auditaveis import motivos_acao

def test_motivos_expoem_valor_e_limites():
    _, motivos=motivos_acao(8,1.2,.08,.15,6_000_000,{"liquidez_min":5_000_000})
    assert all("criterio" in x and "resultado" in x for x in motivos)
    assert next(x for x in motivos if x["criterio"]=="liquidez")["resultado"]=="APROVADO"
