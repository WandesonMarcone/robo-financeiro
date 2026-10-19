"""Taxonomia setorial validada do catalogo.

A taxonomia base e o mapa oficial usado pelo projeto (``config.MAPA_SETORES_B3``).
Sobre ele aplicamos dois conjuntos de regras:

* **aliases** semanticos, para que nomes equivalentes da CVM/B3 (por exemplo
  ``Petroleo e Gas`` e ``Petroleo, Gas & Biocombustiveis``) não criem setores
  duplicados;
* **validacao**, usada pela IA. A IA so pode classificar em um setor/subsetor
  desta taxonomia; nomes desconhecidos viram sugestao para revisao humana em vez
  de registros novos.

Importadores de fonte oficial (CVM) podem continuar cadastrando um nome oficial
que ainda nao exista na taxonomia; nesse caso o repositorio o cria como
``fonte`` oficial. A restricao de "nao criar livremente" vale para a IA.
"""

from __future__ import annotations

import re
import unicodedata

import config

_ARTIGOS = {
    "a",
    "as",
    "o",
    "os",
    "de",
    "da",
    "das",
    "do",
    "dos",
    "e",
    "em",
    "com",
    "para",
    "por",
}


def _sem_acento(valor):
    texto = unicodedata.normalize("NFKD", str(valor or ""))
    return "".join(c for c in texto if not unicodedata.combining(c))


def chave_semantica(valor):
    """Chave tolerante a acentos, caixa, pontuacao e artigos."""
    texto = _sem_acento(valor).casefold()
    texto = texto.replace("&", " e ")
    tokens = re.findall(r"[a-z0-9]+", texto)
    tokens = [token for token in tokens if token not in _ARTIGOS]
    return "-".join(tokens)


def slugificar(valor):
    texto = _sem_acento(valor).casefold()
    texto = re.sub(r"[^a-z0-9]+", "-", texto).strip("-")
    return texto or "sem-nome"


def _mapa_b3():
    mapa = getattr(config, "MAPA_SETORES_B3", None) or {}
    return mapa


# Aliases de setor. As chaves sao comparadas pela chave semantica.
_ALIASES_SETOR = {
    "Petróleo, Gás & Biocombustíveis": [
        "Petróleo e Gás",
        "Petroleo e Gas",
        "Petróleo, Gás e Biocombustíveis",
        "Petroleo, Gas e Biocombustiveis",
        "Exploração e Produção de Petróleo e Gás",
    ],
    "Financeiro": [
        "Bancos",
        "Seguros",
        "Seguros e Resseguros",
        "Serviços Financeiros",
        "Intermediação Financeira",
    ],
    "Utilidade Pública": [
        "Utilidades Públicas",
        "Energia Elétrica",
        "Água e Saneamento",
        "Saneamento",
        "Gás e Energia",
    ],
    "Materiais Básicos": [
        "Mineração",
        "Siderurgia e Metalurgia",
        "Papel e Celulose",
        "Química",
        "Petroquímica",
    ],
    "Consumo Cíclico": [
        "Comércio",
        "Varejo",
        "Construção Civil",
        "Construção",
        "Educação",
        "Viagens e Lazer",
        "Automóveis e Motocicletas",
    ],
    "Consumo Não-Cíclico": [
        "Alimentos",
        "Bebidas",
        "Alimentos e Bebidas",
        "Produtos de Uso Pessoal e Limpeza",
    ],
    "Saúde": [
        "Serviços Médicos",
        "Medicamentos e Produtos",
        "Hospitais e Análises",
    ],
    "Bens Industriais": [
        "Máquinas e Equipamentos",
        "Transporte",
        "Logística",
        "Construção e Engenharia",
        "Material de Transporte",
    ],
    "Tecnologia e Telecom": [
        "Tecnologia",
        "Telecomunicações",
        "Software e Serviços de Informática",
        "Computadores e Equipamentos",
    ],
    "Agronegócio": [
        "Agronegócios",
        "Agropecuária",
        "Açúcar e Álcool",
    ],
}

# Aliases de subsetor dentro de um setor canonico.
_ALIASES_SUBSETOR = {
    "Petróleo, Gás & Biocombustíveis": {
        "Exploração e Refino": [
            "Exploração, Refino e Distribuição",
            "Exploração e Produção",
        ],
        "Distribuição de Combustíveis": ["Distribuição"],
        "Equipamentos e Serviços": ["Serviços e Equipamentos"],
    },
    "Financeiro": {
        "Bancos": ["Banco", "Bancos Comerciais"],
        "Seguros e Resseguros": ["Seguros", "Resseguros"],
        "Serviços Financeiros e Holdings": ["Serviços Financeiros", "Holdings"],
    },
    "Utilidade Pública": {
        "Energia - Geração": ["Geração de Energia", "Energia Elétrica"],
        "Energia - Transmissão": ["Transmissão de Energia"],
        "Energia - Distribuição e Integrada": [
            "Distribuição de Energia",
            "Energia Integrada",
        ],
        "Saneamento e Gestão Ambiental": ["Saneamento", "Gestão Ambiental"],
    },
    "Materiais Básicos": {
        "Mineração": ["Mineração e Metais"],
        "Siderurgia e Metalurgia": ["Siderurgia", "Metalurgia"],
        "Papel, Celulose e Madeira": ["Papel e Celulose", "Madeira"],
        "Química e Petroquímica": ["Química", "Petroquímica"],
    },
    "Consumo Cíclico": {
        "Varejo e E-commerce": ["Varejo", "Comércio"],
        "Construção Civil": ["Construção"],
        "Educação": ["Educacional"],
        "Viagens, Lazer e Esportes": ["Viagens e Lazer"],
    },
    "Consumo Não-Cíclico": {
        "Alimentos e Carnes": ["Alimentos"],
        "Bebidas": ["Bebidas e Refrigerantes"],
        "Supermercados": ["Comércio e Distribuição"],
        "Produtos de Uso Pessoal": ["Produtos de Uso Pessoal e Limpeza"],
    },
    "Saúde": {
        "Hospitais, Análises e Planos": ["Hospitais e Análises", "Serviços Médicos"],
        "Medicamentos e Produtos": ["Medicamentos", "Produtos para Saúde"],
    },
    "Bens Industriais": {
        "Máquinas e Equipamentos": ["Máquinas", "Equipamentos"],
        "Transporte e Logística": ["Transporte", "Logística"],
    },
    "Tecnologia e Telecom": {
        "Telecomunicações": ["Telecom"],
        "Programas, Computadores e Equipamentos": [
            "Software e Serviços de Informática",
            "Computadores e Equipamentos",
        ],
    },
    "Agronegócio": {
        "Açúcar, Álcool e Grãos": ["Açúcar e Álcool", "Grãos"],
    },
}


def _construir_taxonomia():
    setores = {}
    aliases_setor = {}
    aliases_subsetor = {}

    for nome_setor, subsetores in _mapa_b3().items():
        canonical = str(nome_setor).strip()
        setores[canonical] = [str(s).strip() for s in (subsetores or {}).keys()]
        aliases_setor[chave_semantica(canonical)] = canonical

    for canonical, aliases in _ALIASES_SETOR.items():
        if canonical not in setores:
            continue
        for alias in aliases:
            chave = chave_semantica(alias)
            existente = aliases_setor.get(chave)
            if existente is not None and existente != canonical:
                # Nunca deixa um alias ambiguo sobrescrever um setor real.
                continue
            aliases_setor[chave] = canonical

    for setor, mapa in _ALIASES_SUBSETOR.items():
        if setor not in setores:
            continue
        por_chave = {
            chave_semantica(subsetor): subsetor for subsetor in setores[setor]
        }
        for canonical, aliases in mapa.items():
            if canonical not in setores[setor]:
                continue
            por_chave[chave_semantica(canonical)] = canonical
            for alias in aliases:
                por_chave.setdefault(chave_semantica(alias), canonical)
        aliases_subsetor[setor] = por_chave

    return setores, aliases_setor, aliases_subsetor


SETORES, _ALIASES_SETOR_CHAVE, _ALIASES_SUBSETOR_CHAVE = _construir_taxonomia()


def resolver_setor(nome):
    """Retorna o nome canonico do setor ou ``None`` se não for validado."""
    if not str(nome or "").strip():
        return None
    return _ALIASES_SETOR_CHAVE.get(chave_semantica(nome))


def resolver_subsetor(setor_nome, subsetor_nome):
    """Retorna o subsetor canonico dentro do setor ou ``None``."""
    if not str(subsetor_nome or "").strip():
        return None
    setor = resolver_setor(setor_nome)
    if setor is None:
        return None
    return _ALIASES_SUBSETOR_CHAVE.get(setor, {}).get(
        chave_semantica(subsetor_nome)
    )


def setor_valido(nome):
    return resolver_setor(nome) is not None


def subsetor_valido(setor_nome, subsetor_nome):
    return resolver_subsetor(setor_nome, subsetor_nome) is not None


def subconjunto_do_setor(setor_nome):
    setor = resolver_setor(setor_nome)
    if setor is None:
        return []
    return list(SETORES.get(setor, []))


def taxonomia():
    """Copia da taxonomia validada (setor -> subsetores canonicos)."""
    return {setor: list(subsetores) for setor, subsetores in SETORES.items()}


__all__ = [
    "SETORES",
    "chave_semantica",
    "resolver_setor",
    "resolver_subsetor",
    "setor_valido",
    "slugificar",
    "subconjunto_do_setor",
    "subsetor_valido",
    "taxonomia",
]
