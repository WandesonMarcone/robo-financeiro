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
        "Energy",
        "Oil & Gas",
    ],
    "Financeiro": [
        "Bancos",
        "Seguros",
        "Seguros e Resseguros",
        "Serviços Financeiros",
        "Intermediação Financeira",
        "Financial Services",
        "Financial",
        "Finance",
    ],
    "Utilidade Pública": [
        "Utilidades Públicas",
        "Energia Elétrica",
        "Água e Saneamento",
        "Saneamento",
        "Gás e Energia",
        "Utilities",
        "Utility",
    ],
    "Materiais Básicos": [
        "Mineração",
        "Siderurgia e Metalurgia",
        "Papel e Celulose",
        "Química",
        "Petroquímica",
        "Basic Materials",
        "Materials",
    ],
    "Consumo Cíclico": [
        "Comércio",
        "Varejo",
        "Construção Civil",
        "Construção",
        "Materiais de Construção",
        "Eletrônicos",
        "Educação",
        "Viagens e Lazer",
        "Automóveis e Motocicletas",
        "Consumer Cyclical",
        "Consumer Discretionary",
        "Real Estate",
    ],
    "Consumo Não-Cíclico": [
        "Alimentos",
        "Bebidas",
        "Alimentos e Bebidas",
        "Produtos de Uso Pessoal e Limpeza",
        "Consumer Defensive",
        "Consumer Staples",
    ],
    "Saúde": [
        "Serviços Médicos",
        "Medicamentos e Produtos",
        "Hospitais e Análises",
        "Healthcare",
        "Health Care",
    ],
    "Bens Industriais": [
        "Máquinas e Equipamentos",
        "Transporte",
        "Logística",
        "Construção e Engenharia",
        "Material de Transporte",
        "Industrials",
        "Industrial",
    ],
    "Tecnologia e Telecom": [
        "Tecnologia",
        "Tecnologia & Telecom",
        "Telecomunicações",
        "Software e Serviços de Informática",
        "Computadores e Equipamentos",
        "Technology",
        "Communication Services",
        "Communications",
    ],
    "Agronegócio": [
        "Agronegócios",
        "Agropecuária",
        "Açúcar e Álcool",
        "Farm Products",
    ],
}

# Aliases de subsetor dentro de um setor canonico.
_ALIASES_SUBSETOR = {
    "Petróleo, Gás & Biocombustíveis": {
        "Exploração e Refino": [
            "Exploração, Refino e Distribuição",
            "Exploração e Produção",
            "Oil & Gas E&P",
            "Oil & Gas Integrated",
            "Oil & Gas Refining",
        ],
        "Distribuição de Combustíveis": [
            "Distribuição",
            "Oil & Gas Refining & Marketing",
            "Oil & Gas Midstream",
        ],
        "Equipamentos e Serviços": [
            "Serviços e Equipamentos",
            "Oil & Gas Equipment & Services",
        ],
    },
    "Financeiro": {
        "Bancos": [
            "Banco",
            "Bancos Comerciais",
            "Banks",
            "Banks - Regional",
            "Banks - Diversified",
        ],
        "Seguros e Resseguros": [
            "Seguros",
            "Resseguros",
            "Insurance",
            "Insurance - Diversified",
            "Insurance - Life",
        ],
        "Serviços Financeiros e Holdings": [
            "Serviços Financeiros",
            "Holdings",
            "Credit Services",
            "Capital Markets",
            "Financial Conglomerates",
        ],
    },
    "Utilidade Pública": {
        "Energia - Geração": [
            "Geração de Energia",
            "Energia Elétrica",
            "Utilities - Independent Power Producers",
            "Utilities - Renewable",
        ],
        "Energia - Transmissão": ["Transmissão de Energia"],
        "Energia - Distribuição e Integrada": [
            "Distribuição de Energia",
            "Energia Integrada",
            "Utilities - Regulated Electric",
            "Utilities - Diversified",
        ],
        "Saneamento e Gestão Ambiental": [
            "Saneamento",
            "Gestão Ambiental",
            "Waste Management",
            "Utilities - Regulated Water",
        ],
    },
    "Materiais Básicos": {
        "Mineração": [
            "Mineração e Metais",
            "Other Industrial Metals & Mining",
            "Gold",
            "Copper",
        ],
        "Siderurgia e Metalurgia": ["Siderurgia", "Metalurgia", "Steel"],
        "Papel, Celulose e Madeira": [
            "Papel e Celulose",
            "Madeira",
            "Paper & Paper Products",
            "Lumber & Wood Production",
        ],
        "Química e Petroquímica": [
            "Química",
            "Petroquímica",
            "Chemicals",
            "Specialty Chemicals",
        ],
    },
    "Consumo Cíclico": {
        "Varejo e E-commerce": [
            "Varejo",
            "Comércio",
            "Department Stores",
            "Internet Retail",
            "Specialty Retail",
        ],
        "Calçados, Vestuário e Moda": [
            "Calçados",
            "Vestuário",
            "Moda",
            "Footwear & Accessories",
            "Apparel Retail",
            "Apparel Manufacturing",
        ],
        "Construção Civil": ["Construção", "Residential Construction"],
        "Materiais de Construção": [
            "Materiais de Construcao",
            "Cerâmica",
            "Building Materials",
            "Building Products & Equipment",
        ],
        "Eletrônicos": [
            "Eletronicos",
            "Eletroeletrônicos",
            "Consumer Electronics",
            "Electronics & Computer Distribution",
        ],
        "Aluguel de Carros e Frotas": [
            "Aluguel de Carros",
            "Locação de Veículos",
            "Rental & Leasing Services",
        ],
        "Shopping Centers e Imóveis": [
            "Shoppings",
            "Exploração de Imóveis",
            "Real Estate Services",
            "REIT - Retail",
            "REIT - Diversified",
            "Real Estate - Development",
        ],
        "Educação": ["Educacional", "Education & Training Services"],
        "Viagens, Lazer e Esportes": [
            "Viagens e Lazer",
            "Travel Services",
            "Leisure",
            "Resorts & Casinos",
        ],
    },
    "Consumo Não-Cíclico": {
        "Alimentos e Carnes": [
            "Alimentos",
            "Packaged Foods",
            "Food Distribution",
        ],
        "Bebidas": ["Bebidas e Refrigerantes", "Beverages - Brewers"],
        "Supermercados": [
            "Comércio e Distribuição",
            "Grocery Stores",
            "Discount Stores",
        ],
        "Produtos de Uso Pessoal": [
            "Produtos de Uso Pessoal e Limpeza",
            "Household & Personal Products",
        ],
    },
    "Saúde": {
        "Hospitais, Análises e Planos": [
            "Hospitais e Análises",
            "Serviços Médicos",
            "Medical Care Facilities",
            "Diagnostics & Research",
            "Healthcare Plans",
        ],
        "Medicamentos e Produtos": [
            "Medicamentos",
            "Produtos para Saúde",
            "Drug Manufacturers - Specialty & Generic",
            "Drug Manufacturers - General",
            "Pharmaceutical Retailers",
        ],
    },
    "Bens Industriais": {
        "Máquinas e Equipamentos": [
            "Máquinas",
            "Equipamentos",
            "Specialty Industrial Machinery",
            "Farm & Heavy Construction Machinery",
            "Auto Parts",
        ],
        "Transporte e Logística": [
            "Transporte",
            "Logística",
            "Railroads",
            "Airlines",
            "Integrated Freight & Logistics",
            "Marine Shipping",
            "Infrastructure Operations",
        ],
    },
    "Tecnologia e Telecom": {
        "Telecomunicações": [
            "Telecom",
            "Telecomunicacoes",
            "Telecom Services",
            "Communication Equipment",
        ],
        "Programas, Computadores e Equipamentos": [
            "Software e Serviços de Informática",
            "Computadores e Equipamentos",
            "Software - Application",
            "Software - Infrastructure",
            "Information Technology Services",
            "Computer Hardware",
        ],
    },
    "Agronegócio": {
        "Açúcar, Álcool e Grãos": [
            "Açúcar e Álcool",
            "Grãos",
            "Farm Products",
            "Agricultural Inputs",
        ],
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


def _subsetor_em_qualquer_setor(nome):
    if not str(nome or "").strip():
        return None, None
    chave = chave_semantica(nome)
    for setor, por_chave in _ALIASES_SUBSETOR_CHAVE.items():
        canonical = por_chave.get(chave)
        if canonical:
            return setor, canonical
    return None, None


def classificar_textos_b3(*textos):
    """Casa textos livres (Yahoo/CVM/planilha) na taxonomia canonica B3.

    Devolve ``(setor, subsetor)`` ou ``(None, None)`` se nenhum texto casar.
    Nao inventa setor fora de ``MAPA_SETORES_B3``.
    """
    candidatos = [str(t).strip() for t in textos if str(t or "").strip()]
    if not candidatos:
        return None, None

    setor_achado = None
    for texto in candidatos:
        setor = resolver_setor(texto)
        if setor:
            setor_achado = setor
            break

    if setor_achado:
        for texto in candidatos:
            sub = resolver_subsetor(setor_achado, texto)
            if sub:
                return setor_achado, sub
        setor_livre, sub_livre = None, None
        for texto in candidatos:
            setor_livre, sub_livre = _subsetor_em_qualquer_setor(texto)
            if sub_livre and setor_livre == setor_achado:
                return setor_achado, sub_livre
        subsetores = SETORES.get(setor_achado) or []
        if subsetores:
            return setor_achado, subsetores[0]
        return setor_achado, None

    for texto in candidatos:
        setor, sub = _subsetor_em_qualquer_setor(texto)
        if setor and sub:
            return setor, sub
    return None, None


__all__ = [
    "SETORES",
    "chave_semantica",
    "classificar_textos_b3",
    "resolver_setor",
    "resolver_subsetor",
    "setor_valido",
    "slugificar",
    "subconjunto_do_setor",
    "subsetor_valido",
    "taxonomia",
]
