import os

# --- INFRAESTRUTURA DE BANCO DE DADOS ---
SPREADSHEET_URL = 'https://docs.google.com/spreadsheets/d/1U8h3Hw2yBOmCbvBskP9zHyVVJf_3OkXtAopcFSebLvs/edit?usp=drivesdk' 
JSON_KEY = 'credenciais.json' 

# --- CONFIGURAÇÕES ---
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN") 
TELEGRAM_CHAT_ID = "8867098987"

# --- CONTROLE DE USUÁRIOS E PERMISSÕES (FASE 2) ---
# Papéis disponíveis no sistema.
PAPEL_ADMIN = "admin"
PAPEL_USUARIO = "user"

# Identificadores numéricos do Telegram. Podem ser sobrescritos por variáveis
# de ambiente, preservando o padrão de configuração já existente no projeto.
TELEGRAM_ADMIN_ID = (os.environ.get("TELEGRAM_ADMIN_ID") or "8867098987").strip()
TELEGRAM_USUARIOS_LIMITADOS = [
    c.strip()
    for c in os.environ.get("TELEGRAM_USUARIOS_LIMITADOS", "5336458734").split(",")
    if c.strip()
]

# Fonte única de verdade: Telegram ID -> papel.
USUARIOS_AUTORIZADOS = {}
if TELEGRAM_ADMIN_ID:
    USUARIOS_AUTORIZADOS[TELEGRAM_ADMIN_ID] = PAPEL_ADMIN
for _usuario_limitado in TELEGRAM_USUARIOS_LIMITADOS:
    USUARIOS_AUTORIZADOS.setdefault(_usuario_limitado, PAPEL_USUARIO)

# Allowlist de chats processados pelo bot. Os usuários definidos acima são
# sempre autorizados; TELEGRAM_CHATS_AUTORIZADOS permite adicionar outros chats.
_chats_autorizados_extra = [
    c.strip()
    for c in os.environ.get("TELEGRAM_CHATS_AUTORIZADOS", "").split(",")
    if c.strip()
]
CHATS_AUTORIZADOS = list(
    dict.fromkeys(
        [TELEGRAM_CHAT_ID, *USUARIOS_AUTORIZADOS.keys(), *_chats_autorizados_extra]
    )
)

GROQ_API_KEY = os.environ.get("GROQ_API_KEY") # CONFIG IA(GROQ)
DATABASE_URL = os.environ.get("DATABASE_URL") # CONFIG BASE DE DADOS

# Pasta do catálogo de logos ("Ícones B3"), distinta de DRIVE_ROOT_FOLDER_ID
# (Dados Financeiros). O ID informado pelo usuário é o padrão; pode ser
# sobrescrito por DRIVE_LOGOS_FOLDER_ID sem alterar a raiz documental.
DRIVE_LOGOS_FOLDER_ID = (
    os.environ.get("DRIVE_LOGOS_FOLDER_ID") or "1CwnYl7lq5U49vVr-BZBNC737tfvyyhuW"
).strip()

# ==========================================
# PREFERÊNCIAS DO MENU: ⭐ MEUS FAVORITOS
# ==========================================

# A carteira destacada nas varreduras vem do ranking real de favoritos
# (``ativos_acompanhados``). Nao ha mais lista hardcoded de FIIs/acoes.
CARTEIRA_POPULAR_LIMITE = 5
OPORTUNIDADES_LIMITE = 8
THROTTLE_ATUALIZACAO_SEGUNDOS = 3600
LIQUIDEZ_MINIMA_FII = 5_000_000
LIQUIDEZ_MINIMA_ACAO = 5_000_000
COLUNA_NOME_EMPRESA_ACAO = 33
COLUNA_SUBSETOR_ACAO = 34


# Limites máximos de favoritos por usuário, SEPARADOS por tipo. São apenas tetos
# de quantidade: não restringem quais ativos podem ser acompanhados (isso
# continua dependendo do catálogo da tabela ``ativos``). Cadastros já existentes
# acima do teto não são removidos; novas adições e a seleção no cadastro não
# ultrapassam 5 por tipo.
FAVORITOS_LIMITES = {
    "fii": 5,
    "acao": 5,
    "etf": 5,
    "bdr": 5,
}


def _horas_prazo(nome_env, padrao):
    """Lê o prazo de decisão em horas (0/None desativa a expiração)."""
    valor = os.environ.get(nome_env)
    if valor is None or not str(valor).strip():
        return padrao
    try:
        numero = int(str(valor).strip())
    except (TypeError, ValueError):
        return padrao
    return numero if numero > 0 else None


# Prazo (em horas) para o administrador decidir uma solicitação de troca de
# ativo favorito. Padrão confirmado: 48 horas. Quando ``None``/0, a solicitação
# NÃO expira (permanece pendente até decisão). A expiração NUNCA aprova sozinha e
# preserva o histórico (o registro muda de estado, não é apagado).
TROCAS_PRAZO_HORAS = _horas_prazo("TROCAS_PRAZO_HORAS", 48)

# --- 🚨 REGRAS FIXAS DEFINIDAS AQUI 🚨 ---

FILTROS_FIXOS = {
    "fii": {
        "pvp_min": 0.85,
        "pvp_max": 1.05,
        "dy_min": 0.09,
        "liquidez_min": LIQUIDEZ_MINIMA_FII,
        "vacancia_max": 0.10,
    },
    "acao": {
        "pl_min": 3.0,
        "pl_max": 12.0,
        "pvp_min": 0.50,
        "pvp_max": 1.80,
        "dy_min": 0.06,
        "roe_min": 0.10,
        "liquidez_min": LIQUIDEZ_MINIMA_ACAO,
    },
}

# ==========================================
# 🗺️ MAPA DE ISCAS MASTER (CATÁLOGO B3)
# ==========================================
MAPA_ISCAS_MASTER = {
    'XPML11': 'XP MALLS',
    'MXRF11': 'MAXI RENDA',
    'HGLG11': 'CGHG LOG', # Mantido histórico, B3 as vezes usa CSHG
    'VISC11': 'VINCI SHOPPING CENTERS',
    'KNCR11': 'KINEA RENDIMENTOS',
    'GARE11': 'GUARDIAN REAL ESTATE', # Ajustado pelo txt da B3
    'BTLG11': 'BTG PACTUAL LOGÍSTICA',
    'VILG11': 'VINCI LOGÍSTICA',
    'CPSH11': 'CAPITÂNIA SHOPPINGS', 
    'HGCR11': 'CSHG RECEBIVEIS',
    'VGIR11': 'VALORA RENDA IMOBILIÁRIA',
    'RBRY11': 'RBR PRIVATE',
    'CLIN11': 'CLAVE ÍNDICES',
    'KNHF11': 'KINEA HEDGE',
    'KNUQ11': 'KINEA UNIQUE',
    'BTCI11': 'BTG PACTUAL CRÉDITO',
    'RZTR11': 'RIZA TERRAX',
    'GGRC11': 'GGR COVEPI',
    'TRXF11': 'TRX REAL ESTATE',
    'CVBI11': 'VBI CRÉDITO MULTIESTRATÉGIA',

    # --- FAMÍLIA XP ---
    'XPLG11': 'XP LOG FDO',
    'XPLY11': 'XP LOG PRI',
    'XPPR11': 'XP CORPORATE',
    'XPIN11': 'XP INDUSTRIAL',
    'XPCI11': 'XP CRÉDITO IMOBILIÁRIO',
    'XPSF11': 'XP SELECTION',

    # --- FAMÍLIA KINEA ---
    'KNRI11': 'KINEA RENDA IMOBILIÁRIA',
    'KNIP11': 'KINEA ÍNDICES',
    'KNSC11': 'KINEA SECURITIES',
    'KFOF11': 'KINEA FUNDO DE FUNDOS',

    # --- FAMÍLIA BTG PACTUAL ---
    'BRCR11': 'BTG PACTUAL CORPORATE',
    'BCIA11': 'BRADESCO CARTEIRA',
    'BTAL11': 'BTG PACTUAL AGRO',
    'BTLG11': 'BTG PACTUAL LOGÍSTICA',

    # --- FAMÍLIA VINCI & VBI ---
    'VINO11': 'VINCI OFFICES',
    'VIUR11': 'VINCI IMÓVEIS URBANOS',
    'PVBI11': 'VBI PRIME PROPERTIES',
    'LVBI11': 'VBI LOGÍSTICO',
    'RVBI11': 'VBI RENDIMENTOS',

    # --- FAMÍLIA HEDGE & CSHG ---
    'HGBS11': 'HEDGE BRASIL SHOPPING',
    'HGRU11': 'HEDGE RENDA URBANA',
    'HGRE11': 'HEDGE REALTY',
    'HFOF11': 'HEDGE TOP FOFII',

    # --- FAMÍLIA SUNO ---
    'SNCI11': 'SUNO RECEBÍVEIS',
    'SNFF11': 'SUNO FUNDO DE FUNDOS',
    'SNLG11': 'SUNO LOG',
    'SNAG11': 'SUNO AGRO',

    # --- OUTROS GIGANTES DO MERCADO ---
    'IRDM11': 'IRIDIUM RECEBÍVEIS',
    'HCTR11': 'HECTARE CE',
    'DEVA11': 'DEVANT RECEBÍVEIS',
    'RECR11': 'REC RECEBÍVEIS',
    'RECT11': 'REC RENDA',
    'ALZR11': 'ALIANZA TRUST',
    'BRCO11': 'BRESCO LOGÍSTICA',
    'TGAR11': 'TG ATIVO REAL',
    'URPR11': 'URCA PRIME RENDA',
    'MALL11': 'MALLS BRASIL PLURAL',
    'HSML11': 'HSI MALLS',
    'HSLG11': 'HSI LOGÍSTICA',
    'TORD11': 'TORDESILHAS',
    'MCCI11': 'MAUÁ CAPITAL RECEBÍVEIS',
    'SARE11': 'SANTANDER RENDA',
    'RBRL11': 'RB CAPITAL LOGÍSTICO',
    'RBRR11': 'RBR HIGH GRADE',
    'CACR11': 'CARTESIA RECEBÍVEIS'
}

TIPOS_DOC_FII = {
    "0": "Relatorio Gerencial",
    "1": "Fato Relevante",
    "2": "Informe Mensal",
    "3": "Aviso aos Cotistas",
    "4": "Demonstracoes Financeiras",
    "5": "Nova Emissao de Cotas",
    "6": "Assembleia Geral",
    "7": "Rendimentos",
    "8": "Apresentação Trimestral De Resultados",
    "9": "Proposta Emissão de Cotas",
    "10": "Comunicado ao Mercado",
    "11": "Outros",
    "12": "Informe Trimestral",
    "13": "Informe Anual",
    "14": "Regulamento",
    "15": "Prospecto",
    "16": "Lamina",
    "17": "Formulario de Referencia",
    "18": "Edital de Convocacao",
    "19": "Ata de Assembleia",
    "20": "Nova Emissao de Cotas",
    "21": "Nova Emissao de Cotas",
    "22": "Suplemento",
    "23": "Politica de Voto",
    "24": "Relatorio Anual",
    "25": "Relatorio do Administrador",
    "26": "Relatorio do Gestor",
    "27": "Perfil do Fundo",
    "28": "Estudo de Viabilidade",
    "29": "Laudo de Avaliacao",
    "30": "Alteracao de Regulamento",
    "31": "Substituicao de Prestador",
    "32": "Oferta Publica",
    "33": "Direito de Preferencia",
    "34": "Amortizacao",
    "35": "Material Publicitario",
    "36": "Boletim de Voto a Distancia",
    "37": "Esclarecimento",
    "38": "Justificacao",
}

TIPOS_DOC_ACAO = {
    "0": "Fato Relevante",
    "1": "Aviso aos Acionistas",
    "2": "Comunicado ao Mercado",
    "3": "Demonstracoes Financeiras",
    "4": "Apresentação de Resultados",
    "5": "Relatório de Sustentabilidade",
    "6": "Outros"
}

# ==========================================
# CONFIGURAÇÕES DO COLETOR CVM (AÇÕES)
# ==========================================

# Mapa de padronização de contas contábeis da CVM
MAPA_CONTAS_CVM = {
    # --- BALANÇO PATRIMONIAL (ATIVO) ---
    '1': 'ativo_total',
    '1.01.01': 'caixa',                  # Conta analítica exata de Caixa e Equivalentes

    # --- BALANÇO PATRIMONIAL (PASSIVO E PL) ---
    '2': 'passivo_total',
    '2.01.04': 'divida_curto_prazo',     # Empréstimos a Curto Prazo
    '2.02.01': 'divida_longo_prazo',     # Empréstimos a Longo Prazo
    '2.03': 'patrimonio_liquido',

    # --- D.R.E. (RESULTADOS) ---
    '3.01': 'receita',
    '3.03': 'lucro_bruto',
    '3.05': 'ebit',                      # Alterado de 'ebitda' para 'ebit'
    '3.06': 'resultado_financeiro',
    '3.11': 'lucro_liquido',

    # --- D.F.C. (FLUXO DE CAIXA) ---
    '6.01': 'fco',
    '6.01.01.04': 'depreciacao'          # Adicionado para permitir o cálculo do EBITDA
}

# Identidade de emissores: cadastro_cnpj_acoes (CVM/B3/RI), sem mapa manual.

# SETORES DAS AÇÕES
MAPA_SETORES_B3 = {
    "Petróleo, Gás & Biocombustíveis": {
        "Exploração e Refino": ["PETR3", "PETR4", "PRIO3", "ENAT3", "RECV3", "RRRP3"],
        "Distribuição de Combustíveis": ["VBBR3", "CSAN3", "UGPA3", "RAIZ4"],
        "Equipamentos e Serviços": ["OSPA3", "LUPA3"]
    },
    "Financeiro": {
        "Bancos": ["ITUB3", "ITUB4", "BBDC3", "BBDC4", "BBAS3", "SANB4", "SANB11", "BPAC11", "ABCB4", "BRSR6", "BMGB4", "PINE4"],
        "Seguros e Resseguros": ["BBSE3", "CXSE3", "PSSA3", "IRBR3", "WIZC3"],
        "Serviços Financeiros e Holdings": ["B3SA3", "CIEL3", "BPAN4", "ITSA4", "SIMH3"]
    },
    "Utilidade Pública": {
        "Energia - Geração": ["EGIE3", "AURE3", "ENEV3", "AESB3", "MEGA3", "GEPA4"],
        "Energia - Transmissão": ["TAEE3", "TAEE4", "TAEE11", "TRPL4", "ALUP11"],
        "Energia - Distribuição e Integrada": ["ELET3", "ELET6", "CMIG4", "CPLE6", "EQTL3", "ENGI11", "NEOE3", "LIGT3"],
        "Saneamento e Gestão Ambiental": ["SBSP3", "SAPR11", "CSMG3", "AMBP3", "ORVR3"]
    },
    "Materiais Básicos": {
        "Mineração": ["VALE3", "CMIN3", "BRAP4", "CBAV3", "AURA33", "LITH3"],
        "Siderurgia e Metalurgia": ["GGBR4", "GOAU3", "GOAU4", "CSNA3", "USIM3", "USIM5", "FESA4"],
        "Papel, Celulose e Madeira": ["SUZB3", "KLBN11", "RANI3", "DXCO3"],
        "Química e Petroquímica": ["UNIP3", "UNIP6", "BRKM5", "DEXP3"]
    },
    "Consumo Cíclico": {
        "Varejo e E-commerce": ["MGLU3", "BHIA3", "LREN3", "GUAR3", "CEAB3", "PETZ3", "AMER3", "CGRA4"],
        "Calçados, Vestuário e Moda": ["ALPA4", "VULC3", "AZZA3", "SOMA3"],
        "Construção Civil": ["CYRE3", "EZTC3", "MRVE3", "DIRR3", "TEND3", "CURY3", "GFSA3", "HBOR3", "MDNE3", "PLPL3"],
        "Materiais de Construção": ["PTBL3"],
        "Eletrônicos": ["MLAS3"],
        "Aluguel de Carros e Frotas": ["RENT3", "MOVI3", "VAMO3"],
        "Shopping Centers e Imóveis": ["IGTI11", "MULT3", "ALOS3", "JHSF3", "SYNE3", "LPSB3"],
        "Educação": ["YDUQ3", "COGN3", "ANIM3", "SEER3", "CSED3"],
        "Viagens, Lazer e Esportes": ["CVCB3", "SMFT3", "SHOW3"]
    },
    "Consumo Não-Cíclico": {
        "Alimentos e Carnes": ["JBSS3", "BEEF3", "MRFG3", "BRFS3", "MDIA3", "CAML3", "ZAMP3", "MEAL3"],
        "Bebidas": ["ABEV3"],
        "Supermercados": ["ASAI3", "CRFB3", "PCAR3", "GMAT3", "MATE3"],
        "Produtos de Uso Pessoal": ["NTCO3"]
    },
    "Saúde": {
        "Hospitais, Análises e Planos": ["RDOR3", "FLRY3", "DASA3", "MATD3", "QUAL3", "ONCO3", "AALR3", "ODPV3"],
        "Medicamentos e Produtos": ["RADL3", "HYPE3", "PGMN3", "VVEO3", "BLAU3", "PNVL3"]
    },
    "Bens Industriais": {
        "Máquinas e Equipamentos": ["WEGE3", "TUPY3", "POMO4", "ROMI3", "KEPL3", "AERI3", "SHUL4", "FRAS3"],
        "Material de Transporte": ["EMBJ3", "EMBR3"],
        "Transporte e Logística": ["RAIL3", "CCRO3", "AZUL4", "GOLL4", "STBP3", "JSLG3", "HBSA3", "LOGN3", "TGMA3", "PORT3"]
    },
    "Tecnologia e Telecom": {
        "Telecomunicações": ["VIVT3", "TIMS3", "OIBR3", "FIQE3", "DESK3"],
        "Programas, Computadores e Equipamentos": ["TOTS3", "LWSA3", "POSI3", "CASH3", "INTB3", "NGRD3", "BMOB3"]
    },
    "Agronegócio": {
        "Açúcar, Álcool e Grãos": ["SLCE3", "AGRO3", "SMTO3", "TTEN3", "SOJA3", "JALL3", "AGXY3"]
    }
}

# SETORES DOS FIIs (macro Tijolo/Papel/FOF/Hibrido + segmento canonico)
MAPA_SETORES_FII = {
    "Tijolo": [
        "Logística",
        "Shoppings",
        "Lajes Corporativas",
        "Residencial",
        "Renda Urbana",
        "Hotéis",
        "Educacional",
        "Hospitais",
        "Varejo",
        "Desenvolvimento",
        "Agronegócio",
        "Fiagro",
        "Infraestrutura",
        "Outros",
    ],
    "Papel": ["CRI"],
    "FOF": ["Cotas de FIIs"],
    "Híbrido": ["Misto"],
}
